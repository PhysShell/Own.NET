#!/usr/bin/env python3
"""
Own.NET Audit — scoring (Plan.md §3.5). Generalizes ``oracle_compare.compare()``
from a 3-way leak diff into a cross-tool confidence + severity + heatmap roll-up.

Three axes, kept independent on purpose:

  1. **Agreement** — findings at the same ``(basename, line ± window)`` across tools
     cluster together (robust to path-prefix differences, exactly as oracle_compare
     matches). A cluster confirmed by >= 2 distinct tools is ``high`` confidence;
     a lone finding is a ``candidate`` (a unique own-check catch, or a possible FP).
  2. **Severity** — each cluster inherits a baseline ``P0..P3`` from its category
     (``category_severity`` in the taxonomy). Severity answers "how bad", agreement
     answers "how sure"; conflating them hides one behind the other.
  3. **Heatmap** — clusters roll up per module (directory) into a pain index
     ``severity_weight x confidence_weight``, sorted descending. This is the direct
     answer to "where does it hurt most / where is it almost fine", not a dump of
     3000 "possible issue" lines.

Input is the list of ``AuditFinding`` from normalize.py (suppressed ones excluded).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import (
    AuditFinding,
    Taxonomy,
    load_taxonomy,
)

SEV_WEIGHT = {"P0": 8.0, "P1": 4.0, "P2": 2.0, "P3": 1.0}
CONF_WEIGHT = {"high": 2.0, "candidate": 1.0}


@dataclass
class Cluster:
    findings: list[AuditFinding]
    category: int
    category_name: str
    severity: str
    confidence: str
    module: str = field(init=False, default="")
    path: str = field(init=False, default="")
    line: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        rep = self.findings[0]
        self.module, self.path, self.line = rep.module, rep.path, rep.line

    @property
    def tools(self) -> list[str]:
        return sorted({f.tool for f in self.findings})

    @property
    def pain(self) -> float:
        return SEV_WEIGHT.get(self.severity, 1.0) * CONF_WEIGHT.get(self.confidence, 1.0)


def _cluster_one_file(group: list[AuditFinding], tol: int) -> list[list[AuditFinding]]:
    """Greedily merge findings in one file whose lines fall within ``tol`` of an
    existing cluster's span. Order-independent enough for a line window."""
    clusters: list[list[AuditFinding]] = []
    for f in sorted(group, key=lambda x: x.line):
        placed = False
        for c in clusters:
            if any(abs(f.line - g.line) <= tol for g in c):
                c.append(f)
                placed = True
                break
        if not placed:
            clusters.append([f])
    return clusters


def _pick_category(members: list[AuditFinding], tax: Taxonomy) -> tuple[int, str, str]:
    """The cluster's category is its most-severe member (ties -> lowest category id),
    so a leak co-located with a generic-quality hit is ranked as a leak."""
    def key(f: AuditFinding) -> tuple[float, int]:
        return (SEV_WEIGHT.get(tax.severity_for(f.category), 1.0), -f.category)
    best = max(members, key=key)
    return best.category, best.category_name, tax.severity_for(best.category)


def score(findings: list[AuditFinding], tax: Taxonomy, line_tol: int = 3) -> dict[str, Any]:
    kept = [f for f in findings if f.scored]
    by_file: dict[str, list[AuditFinding]] = defaultdict(list)
    for f in kept:
        by_file[f.fkey].append(f)

    clusters: list[Cluster] = []
    for group in by_file.values():
        for members in _cluster_one_file(group, line_tol):
            category, name, severity = _pick_category(members, tax)
            confidence = "high" if len({m.tool for m in members}) >= 2 else "candidate"
            clusters.append(Cluster(findings=members, category=category,
                                    category_name=name, severity=severity,
                                    confidence=confidence))

    clusters.sort(key=lambda c: (-c.pain, c.module, c.path, c.line))

    heat: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pain": 0.0, "findings": 0, "high": 0, "categories": Counter()})
    for c in clusters:
        h = heat[c.module]
        h["pain"] += c.pain
        h["findings"] += 1
        h["high"] += 1 if c.confidence == "high" else 0
        h["categories"][c.category_name] += 1
    heatmap = sorted(
        ({"module": m, "pain": round(v["pain"], 2), "findings": v["findings"],
          "high_confidence": v["high"],
          "top_category": (v["categories"].most_common(1)[0][0] if v["categories"] else "")}
         for m, v in heat.items()),
        key=lambda r: (-r["pain"], r["module"]))

    return {
        "clusters": clusters,
        "heatmap": heatmap,
        "totals": {
            "clusters": len(clusters),
            "high_confidence": sum(1 for c in clusters if c.confidence == "high"),
            "candidates": sum(1 for c in clusters if c.confidence == "candidate"),
        },
        "by_category": dict(Counter(c.category_name for c in clusters)),
        "by_severity": dict(Counter(c.severity for c in clusters)),
    }


def cluster_to_dict(c: Cluster) -> dict[str, Any]:
    return {
        "path": c.path, "line": c.line, "module": c.module,
        "category": c.category, "category_name": c.category_name,
        "severity": c.severity, "confidence": c.confidence,
        "pain": round(c.pain, 2), "tools": c.tools,
        "evidence": [f"{f.tool} {f.rule}: {f.message}" for f in c.findings],
    }


def to_json(scored: dict[str, Any]) -> dict[str, Any]:
    return {
        "totals": scored["totals"],
        "by_category": scored["by_category"],
        "by_severity": scored["by_severity"],
        "heatmap": scored["heatmap"],
        "clusters": [cluster_to_dict(c) for c in scored["clusters"]],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Score normalized findings (agreement/severity/heatmap).")
    ap.add_argument("--findings", help="normalize.py --json output (findings + coverage)")
    ap.add_argument("--taxonomy", default=str(
        Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"))
    ap.add_argument("--line-tol", type=int, default=3)
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.findings:
        ap.error("--findings is required (or use --selftest)")

    tax = load_taxonomy(args.taxonomy)
    payload = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    findings = [AuditFinding(
        tool=d["tool"], path=d["path"], line=d["line"], rule=d["rule"],
        message=d.get("message", ""), category=d.get("category", 0),
        category_name=d.get("category_name", "uncategorized"),
        resource=d.get("resource"), suppressed=d.get("suppressed", False),
        suppress_reason=d.get("suppress_reason", "")) for d in payload.get("findings", [])]
    scored = score(findings, tax, args.line_tol)
    out = to_json(scored)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"totals": out["totals"], "heatmap": out["heatmap"][:10]}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Selftest                                                                      #
# --------------------------------------------------------------------------- #

def _f(tool: str, path: str, line: int, rule: str, cat: int, name: str,
       msg: str = "") -> AuditFinding:
    return AuditFinding(tool=tool, path=path, line=line, rule=rule, message=msg,
                        category=cat, category_name=name)


def _selftest() -> int:
    tax_path = Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"
    tax = load_taxonomy(tax_path)
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:  # total derives from the call count
        checks.append("" if ok else msg)

    findings = [
        # two tools at the same spot -> one high-confidence leak cluster (cat 1, P1)
        _f("own-check", "src/Util/Io.cs", 9, "OWN001", 1, "idisposable-leak"),
        _f("codeql", "src/Util/Io.cs", 10, "cs/local-not-disposed", 1, "idisposable-leak"),
        # a lone subscription leak -> candidate, also P1
        _f("own-check", "src/Vm/CustomerViewModel.cs", 12, "OWN001", 2, "subscription-leak"),
        # a lone general-quality hit -> candidate, P2 (lower pain)
        _f("codeql", "src/Util/Style.cs", 4, "S1118", 14, "general-quality"),
    ]
    scored = score(findings, tax, line_tol=3)

    check(scored["totals"]["clusters"] == 3,
          f"expected 3 clusters, got {scored['totals']['clusters']}")
    check(scored["totals"]["high_confidence"] == 1,
          f"expected 1 high-confidence cluster, got {scored['totals']['high_confidence']}")
    check(scored["totals"]["candidates"] == 2,
          f"expected 2 candidates, got {scored['totals']['candidates']}")

    top = scored["clusters"][0]
    check(top.module == "src/Util",
          f"top cluster should be the agreed leak in src/Util, got {top.module}")
    check(top.confidence == "high", "top cluster (highest pain) must be the cross-tool agreement")
    check(top.tools == ["codeql", "own-check"], f"agreed cluster tools wrong: {top.tools}")

    # heatmap orders by pain: the agreed P1 leak module outranks the P2 candidate module
    pain = {row["module"]: row["pain"] for row in scored["heatmap"]}
    # src/Util has the high-conf P1 (4*2=8) + a candidate P2 (2*1=2) = 10;
    # src/Vm has a candidate P1 (4*1=4). So src/Util must outrank src/Vm.
    check(pain.get("src/Util", 0) > pain.get("src/Vm", 0), f"heatmap pain ordering wrong: {pain}")
    check(abs(pain.get("src/Util", 0) - 10.0) <= 0.01,
          f"src/Util pain should be 10.0, got {pain.get('src/Util')}")

    # severity stays category-driven: the subscription leak is P1 even though alone
    sub = next(c for c in scored["clusters"] if c.module == "src/Vm")
    check(sub.severity == "P1", f"subscription-leak cluster should be P1, got {sub.severity}")

    js = to_json(scored)
    check(js["totals"]["clusters"] == 3 and bool(js["heatmap"]), "to_json lost totals/heatmap")
    check("evidence" in js["clusters"][0], "cluster json missing evidence")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"SCORE SELFTEST FAIL: {f}")
    print(f"score selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
