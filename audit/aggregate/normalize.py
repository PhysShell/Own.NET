#!/usr/bin/env python3
"""
Own.NET Audit — normalization: SARIF -> categorized findings (Plan.md §3.4).

Reads every tool's SARIF through the *same* ``parse_sarif`` as ``oracle_compare.py``
(reused, not duplicated — that parser is the one that stopped the silent 38-line
drop on the ScreenToGif oracle run), then maps each ``(tool, ruleId)`` to a
problem category from Plan.md §2 using the knowledge base in
``static/taxonomy/categories.yml``.

Three honesty rules, mirroring the rest of the repo:

  * Unmapped rules are **not dropped** — they land in ``uncategorized`` and are
    surfaced in coverage, so the taxonomy grows deliberately.
  * ``OWN001`` is an umbrella leak code; it is split by its ``[resource: ...]``
    tag so subscription/timer leaks (cat. 2/3) are not collapsed into the
    IDisposable bucket (cat. 1).
  * DevExpress third-party findings are baseline-suppressed — dropped from the
    main report but **counted** in coverage, never hidden silently.

This module's only in-repo seam is ``scripts/oracle_compare.parse_sarif``; own-check
is consumed solely via its CLI. Neither couples ``audit/`` to the ``ownlang`` core.

Usage:
  normalize.py --sarif own-check=own.sarif --sarif codeql=codeql.sarif \\
               --taxonomy static/taxonomy/categories.yml [--strip PREFIX] [--json out.json]
  normalize.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

RESOURCE_RE = re.compile(r"\[resource:\s*([^\]]+)\]", re.IGNORECASE)


def _import_oracle() -> tuple[Any, Any]:
    """Reuse the oracle's SARIF reader (Plan.md §3.4: reuse, don't duplicate).

    Only this one symbol is borrowed from the in-repo scripts/; it is a pure
    SARIF->Finding reader. On lift-out (Plan.md Phase 4) it gets vendored."""
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts"))
    try:
        from oracle_compare import norm_path, parse_sarif
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "normalize: cannot import parse_sarif from scripts/oracle_compare.py "
            f"(expected at {repo / 'scripts'}): {exc}"
        ) from exc
    return parse_sarif, norm_path


parse_sarif, norm_path = _import_oracle()


@dataclass
class AuditFinding:
    """One analyzer result, categorized. ``fkey`` is the basename (lower-cased) for
    cross-tool matching — robust to path-prefix differences between tools, exactly
    like oracle_compare.Finding."""

    tool: str
    path: str
    line: int
    rule: str
    message: str
    category: int = 0
    category_name: str = "uncategorized"
    resource: str | None = None
    suppressed: bool = False
    suppress_reason: str = ""
    note: bool = False           # analysis-skipped coverage note (e.g. OWN050), not a verdict
    fkey: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.fkey = self.path.lower().rsplit("/", 1)[-1]

    @property
    def module(self) -> str:
        """Directory of the finding (the heatmap roll-up unit), or ``(root)``."""
        return self.path.rsplit("/", 1)[0] if "/" in self.path else "(root)"

    @property
    def scored(self) -> bool:
        """A finding counts toward the report only if it is neither third-party
        suppressed nor an analysis-skipped coverage note."""
        return not self.suppressed and not self.note


@dataclass
class Taxonomy:
    rules: dict[str, Any]
    category_severity: dict[int, str]
    suppress_tokens: list[str]
    coverage_note_rules: set[str]

    def severity_for(self, category: int) -> str:
        return self.category_severity.get(category, "P3")


def load_taxonomy(path: str | Path) -> Taxonomy:
    import yaml  # scoped dep — see audit/requirements.txt

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sev = {int(k): str(v) for k, v in (data.get("category_severity") or {}).items()}
    suppress = list((data.get("suppress") or {}).get("path_or_message_contains") or [])
    notes = {str(r) for r in (data.get("coverage_notes") or [])}
    return Taxonomy(rules=dict(data.get("rules") or {}),
                    category_severity=sev, suppress_tokens=suppress,
                    coverage_note_rules=notes)


def _resource_tag(message: str) -> str | None:
    m = RESOURCE_RE.search(message or "")
    return m.group(1).strip().lower() if m else None


def _match_rule(rule: str, rules: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a ruleId to its taxonomy spec. Exact match wins; otherwise the most
    specific glob (longest non-wildcard run) wins."""
    if rule in rules:
        return rules[rule]
    best: tuple[int, dict[str, Any]] | None = None
    for pat, spec in rules.items():
        if any(c in pat for c in "*?[") and fnmatchcase(rule, pat):
            specificity = len(pat.replace("*", "").replace("?", ""))
            if best is None or specificity > best[0]:
                best = (specificity, spec)
    return best[1] if best else None


def categorize(rule: str, resource: str | None,
               rules: dict[str, Any]) -> tuple[int, str]:
    """(category, name) for a ruleId, splitting umbrella codes by resource tag."""
    spec = _match_rule(rule, rules)
    if spec is None:
        return 0, "uncategorized"
    if "by_resource" in spec:
        by = spec["by_resource"]
        chosen = by.get(resource) if resource is not None else None
        if chosen is None:
            chosen = by.get("*", {})
        return int(chosen.get("category", 0)), str(chosen.get("name", "uncategorized"))
    return int(spec.get("category", 0)), str(spec.get("name", "uncategorized"))


def _suppressed(path: str, message: str, tokens: list[str]) -> str:
    """Reason string if this finding is third-party baseline-suppressed, else ''."""
    hay = f"{path}\n{message}".lower()
    for tok in tokens:
        if tok.lower() in hay:
            return f"third-party: {tok}"
    return ""


def normalize_results(raw: list[Any], tax: Taxonomy) -> list[AuditFinding]:
    """Turn oracle_compare Findings (tool/path/line/rule/message) into categorized
    AuditFindings. We ignore the oracle's leak/other ``cls`` and apply our own
    richer taxonomy instead."""
    out: list[AuditFinding] = []
    for f in raw:
        resource = _resource_tag(f.message)
        category, name = categorize(f.rule, resource, tax.rules)
        reason = _suppressed(f.path, f.message, tax.suppress_tokens)
        is_note = f.rule in tax.coverage_note_rules
        out.append(AuditFinding(
            tool=f.tool, path=f.path, line=f.line, rule=f.rule, message=f.message,
            category=category, category_name=name, resource=resource,
            suppressed=bool(reason), suppress_reason=reason, note=is_note))
    return out


def coverage(findings: list[AuditFinding]) -> dict[str, Any]:
    """The honesty ledger: what was categorized, what was suppressed, which rules
    are analysis-skipped coverage notes, and which rules have no taxonomy entry yet
    (so they are visibly pending, not lost)."""
    kept = [f for f in findings if f.scored]
    suppressed = [f for f in findings if f.suppressed]
    notes = [f for f in findings if f.note and not f.suppressed]
    uncategorized = Counter(f.rule for f in kept if f.category == 0)
    return {
        "tools": sorted({f.tool for f in findings}),
        "total": len(findings),
        "kept": len(kept),
        "suppressed": len(suppressed),
        "suppressed_by": dict(Counter(f.suppress_reason for f in suppressed)),
        "analysis_skipped": len(notes),
        "analysis_skipped_by": dict(Counter(f.rule for f in notes)),
        "by_category": dict(Counter(f.category for f in kept)),
        "uncategorized_rules": dict(uncategorized),
    }


def normalize(sarif_inputs: list[tuple[str, str]], tax: Taxonomy,
              strips: list[str]) -> tuple[list[AuditFinding], dict[str, Any]]:
    raw: list[Any] = []
    for tool, path in sarif_inputs:
        raw += parse_sarif(Path(path).read_text(encoding="utf-8"), tool, strips)
    findings = normalize_results(raw, tax)
    return findings, coverage(findings)


def finding_to_dict(f: AuditFinding) -> dict[str, Any]:
    return {
        "tool": f.tool, "path": f.path, "line": f.line, "rule": f.rule,
        "category": f.category, "category_name": f.category_name,
        "resource": f.resource, "suppressed": f.suppressed,
        "suppress_reason": f.suppress_reason, "message": f.message,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Normalize SARIF into categorized findings.")
    ap.add_argument("--sarif", action="append", default=[], metavar="TOOL=PATH",
                    help="a tool's SARIF as tool=path (repeatable)")
    ap.add_argument("--taxonomy", default=str(
        Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"),
        help="categories.yml (default: the shipped taxonomy)")
    ap.add_argument("--strip", action="append", default=[], metavar="PREFIX",
                    help="path prefix to strip from finding paths (repeatable)")
    ap.add_argument("--json", dest="json_out", default="",
                    help="write normalized findings + coverage as JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    inputs: list[tuple[str, str]] = []
    for spec in args.sarif:
        tool, _, path = spec.partition("=")
        if not path:
            ap.error(f"--sarif expects tool=path, got {spec!r}")
        inputs.append((tool, path))

    tax = load_taxonomy(args.taxonomy)
    findings, cov = normalize(inputs, tax, args.strip)
    payload = {"coverage": cov,
               "findings": [finding_to_dict(f) for f in findings if f.scored]}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(cov, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Selftest — embedded fixtures, in the style of oracle_compare._selftest.       #
# --------------------------------------------------------------------------- #

def _own_sarif() -> str:
    """own-check-style SARIF exercising the OWN001 [resource:] split + OWN014."""
    def res(rule: str, msg: str, uri: str, line: int) -> dict[str, Any]:
        return {"ruleId": rule, "level": "warning", "message": {"text": msg},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri}, "region": {"startLine": line}}}]}
    return json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Own.NET"}},
        "results": [
            res("OWN001", "event subscribed but never unsubscribed [resource: subscription token]",
                "src/Vm/CustomerViewModel.cs", 12),
            res("OWN001", "timer never stopped [resource: timer]", "src/Vm/TimerViewModel.cs", 30),
            res("OWN001", "field never disposed [resource: disposable field]",
                "src/Vm/ReportViewModel.cs", 7),
            res("OWN001", "local IDisposable never disposed", "src/Util/Io.cs", 9),
            res("OWN014", "region escape: view-model promoted to App lifetime",
                "src/Vm/StaticEventEscapeViewModel.cs", 50),
            res("OWN050", "cannot verify 'X.Y' — unresolved [resource: unresolved reference]",
                "src/Util/Unknown.cs", 3),
        ]}]})


def _codeql_sarif() -> str:
    def res(rule: str, uri: str, line: int) -> dict[str, Any]:
        return {"ruleId": rule, "message": {"text": "not disposed"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri}, "region": {"startLine": line}}}]}
    return json.dumps({"runs": [{"results": [
        res("cs/local-not-disposed", "src/Util/Io.cs", 9),       # agrees with own local leak
        res("cs/empty-block", "DevExpress.Xpf/Grid/Helper.cs", 4),  # third-party -> suppressed
        res("FOO999", "src/Util/Misc.cs", 3),                    # unmapped -> uncategorized
    ]}]})


def _selftest() -> int:
    tax_path = Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:  # total derives from the call count
        checks.append("" if ok else msg)

    # The shipped taxonomy must parse and carry the split that the OWN001 fix needs.
    tax = load_taxonomy(tax_path)
    check("by_resource" in tax.rules.get("OWN001", {}),
          "shipped categories.yml lost the OWN001 by_resource split")
    check(tax.rules.get("OWN014", {}).get("name") == "region-escape",
          "shipped categories.yml: OWN014 must be region-escape, not subscription-leak")

    own = normalize_results(parse_sarif(_own_sarif(), "own-check", []), tax)
    by_file = {f.fkey: f for f in own}

    # OWN001 umbrella split by [resource: ...] tag.
    cases = {
        "customerviewmodel.cs": (2, "subscription-leak"),
        "timerviewmodel.cs": (3, "timer-leak"),
        "reportviewmodel.cs": (1, "idisposable-leak"),
        "io.cs": (1, "idisposable-leak"),                # no resource tag -> "*" fallback
        "staticeventescapeviewmodel.cs": (2, "region-escape"),
    }
    for fkey, (cat, name) in cases.items():
        got = by_file.get(fkey)
        check(got is not None and (got.category, got.category_name) == (cat, name),
              f"{fkey}: expected ({cat},{name}), got "
              f"{None if got is None else (got.category, got.category_name)}")

    # OWN050 is an analysis-skipped coverage note, not a verdict: routed out of
    # scoring (Codex review on #100), never a phantom uncategorized P3 candidate.
    own050 = by_file.get("unknown.cs")
    check(own050 is not None and own050.note and not own050.scored,
          "OWN050 must be a coverage note (note=True, scored=False)")

    # Glob mapping + uncategorized + DevExpress suppression on the CodeQL run.
    cq = normalize_results(parse_sarif(_codeql_sarif(), "codeql", []), tax)
    cq_by = {f.fkey: f for f in cq}
    check(cq_by["io.cs"].category == 1, "cs/local-not-disposed should map to category 1")
    check(cq_by["helper.cs"].suppressed, "DevExpress finding must be baseline-suppressed")
    check(cq_by["misc.cs"].category == 0, "unmapped FOO999 must be uncategorized (category 0)")

    cov = coverage(own + cq)
    check(cov["suppressed"] == 1, f"coverage suppressed count wrong: {cov['suppressed']}")
    check(cov["analysis_skipped"] == 1 and cov["analysis_skipped_by"].get("OWN050") == 1,
          "OWN050 must be counted as analysis-skipped in coverage")
    check("OWN050" not in cov["uncategorized_rules"],
          "OWN050 (a coverage note) must not pollute uncategorized rules")
    check(cov["uncategorized_rules"].get("FOO999") == 1,
          "uncategorized rule FOO999 must be surfaced in coverage exactly once")
    # a suppressed finding must not leak into the kept category tally
    check(cov["by_category"].get(0, 0) == 1,
          f"suppressed finding leaked into kept categories: {cov['by_category']}")

    # severity baseline comes from the category, not the tool level
    check(tax.severity_for(1) == "P1" and tax.severity_for(0) == "P3",
          "category severity baseline wrong")

    # glob specificity: CA2000 (exact, cat 1) must beat CA2* (glob, cat 14)
    check(categorize("CA2000", None, tax.rules)[0] == 1,
          "exact CA2000 should win over CA2* glob")
    check(categorize("CA1822", None, tax.rules)[0] == 14,
          "CA1* glob should map to general-quality (14)")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"NORMALIZE SELFTEST FAIL: {f}")
    print(f"normalize selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
