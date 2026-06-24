#!/usr/bin/env python3
"""
Own.NET Audit — renderers (Plan.md §3.5). Turns the scored findings + coverage
ledger into the "health anamnesis": a categorized report ranked by where it hurts
most, with an honest coverage map.

  * **Markdown** — for humans / a GitHub run summary (as oracle/mine do today).
  * **JSON** — machine-readable, for the downstream AI layer and regression diffs.

HTML and merged-SARIF renderers are deferred (Plan.md §3.5) — they are additional
views over the same scored model, not new analysis.

The coverage section is load-bearing: it states which tiers ran, which categories
are NO-TOOL / deferred-to-runtime, how many DevExpress findings were suppressed,
and which rules have no taxonomy entry yet. A clean report that hid its own gaps
would be worse than useless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import AuditFinding, coverage, load_taxonomy, normalize_results
from score import score
from score import to_json as score_to_json

# Human labels for the Plan.md §2 categories, used in the coverage section.
CATEGORY_LABELS = {
    1: "IDisposable leak", 2: "event/subscription leak & region escape",
    3: "timer leak", 4: "DependencyPropertyDescriptor.AddValueChanged leak",
    5: "INPC correctness", 6: "PropertyChanged storms", 7: "WPF binding errors",
    8: "broken virtualization", 9: "Freezable / per-instance brushes",
    10: "allocations in converters/getters", 11: "duplicated immutable data",
    12: "heavy reference data / LOH / Gen2", 13: "cross-thread / ObjectDisposedException",
    14: "general bugs / perf / best-practice", 15: "architecture metrics",
}


def render_markdown(meta: dict[str, Any], cov: dict[str, Any],
                    scored: dict[str, Any], max_list: int = 40) -> str:
    clusters = scored["clusters"]
    high = [c for c in clusters if c.confidence == "high"]
    candidates = [c for c in clusters if c.confidence == "candidate"]
    out: list[str] = [
        f"# Own.NET Audit — health report — `{meta.get('target', '?')}`",
        "",
        f"- commit: `{meta.get('commit', '?')}`",
        f"- generated: {meta.get('generated', '?')}",
        f"- profile: `{meta.get('profile', '?')}`",
        f"- tools run: {', '.join(cov.get('tools') or []) or '(none)'}",
        f"- tiers: {meta.get('tiers', '?')}",
        f"- match: basename + line within ±{meta.get('line_tol', 3)}",
        "",
        f"**{scored['totals']['clusters']} findings** "
        f"({scored['totals']['high_confidence']} high-confidence, "
        f"{scored['totals']['candidates']} candidate). "
        "High-confidence = flagged by ≥2 independent tools at the same spot.",
        "",
        "## Where it hurts most",
        "",
        "Modules ranked by pain index (severity weighted by cross-tool agreement, "
        "summed). "
        "This is the triage order — top is worst, bottom is almost fine.",
        "",
        "| module | pain | findings | high-conf | top category |",
        "|---|---:|---:|---:|---|",
    ]
    for row in scored["heatmap"][:max_list]:
        out.append(f"| `{row['module']}` | {row['pain']} | {row['findings']} | "
                   f"{row['high_confidence']} | {row['top_category']} |")
    if not scored["heatmap"]:
        out.append("| _(no findings)_ | | | | |")

    out += ["", f"## High-confidence findings — {len(high)} (≥2 tools agree)", ""]
    out += ["_(none)_"] if not high else [
        f"- `{c.path}:{c.line}` **[{c.severity} · {c.category_name}]** "
        f"— {', '.join(c.tools)}" for c in high[:max_list]
    ]

    out += ["", f"## Candidates — {len(candidates)} (single tool: unique catch or possible FP)", ""]
    out += ["_(none)_"] if not candidates else [
        f"- `{c.path}:{c.line}` **[{c.severity} · {c.category_name}]** "
        f"({c.tools[0]})" for c in candidates[:max_list]
    ]
    if len(candidates) > max_list:
        out.append(f"- … (+{len(candidates) - max_list} more)")

    out += _coverage_section(meta, cov, scored)
    out += [
        "", "## How to read this", "",
        "- **Where it hurts most** is the triage order: fix top modules first.",
        "- **High-confidence** = two independent tools flag the same spot — start here.",
        "- **Candidates** are single-tool: either a unique own-check catch (the leak "
        "classes the oracles can't express) or a possible false positive to harden.",
        "- **Coverage** is the honesty map: NO-TOOL categories are deferred to the "
        "runtime layer, not silently \"clean\"; suppressed DevExpress findings are "
        "counted, not hidden; unmapped rules are pending taxonomy, not lost.",
        "",
    ]
    return "\n".join(out)


def _coverage_section(meta: dict[str, Any], cov: dict[str, Any],
                      scored: dict[str, Any]) -> list[str]:
    out: list[str] = ["", "## Coverage / honesty", ""]
    out.append(f"- findings ingested: {cov.get('total', 0)} "
               f"(kept {cov.get('kept', 0)}, suppressed {cov.get('suppressed', 0)})")
    if cov.get("suppressed_by"):
        for reason, n in sorted(cov["suppressed_by"].items()):
            out.append(f"  - suppressed — {reason}: {n}")
    no_tool = meta.get("no_tool_static") or []
    if no_tool:
        labels = ", ".join(f"{c} ({CATEGORY_LABELS.get(c, '?')})" for c in no_tool)
        out.append(f"- **NO-TOOL (static)** → deferred to runtime layer: {labels}")
    unmapped = cov.get("uncategorized_rules") or {}
    if unmapped:
        shown = ", ".join(f"`{r}` x{n}" for r, n in sorted(unmapped.items()))
        out.append(f"- unmapped rules (pending taxonomy, not dropped): {shown}")
    else:
        out.append("- unmapped rules: none — every flagged rule is categorized")
    by_sev = scored.get("by_severity") or {}
    if by_sev:
        out.append("- by severity: "
                   + ", ".join(f"{k}={by_sev[k]}" for k in sorted(by_sev)))
    return out


def render_json(meta: dict[str, Any], cov: dict[str, Any],
                scored: dict[str, Any]) -> dict[str, Any]:
    return {"meta": meta, "coverage": cov, **score_to_json(scored)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the audit health report (markdown/json).")
    ap.add_argument("--findings", help="normalize.py --json output")
    ap.add_argument("--taxonomy", default=str(
        Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"))
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--target", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--line-tol", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.findings:
        ap.error("--findings is required (or use --selftest)")

    tax = load_taxonomy(args.taxonomy)
    payload = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    cov = payload.get("coverage") or {}
    findings = [AuditFinding(
        tool=d["tool"], path=d["path"], line=d["line"], rule=d["rule"],
        message=d.get("message", ""), category=d.get("category", 0),
        category_name=d.get("category_name", "uncategorized"),
        resource=d.get("resource")) for d in payload.get("findings", [])]
    scored = score(findings, tax, args.line_tol)
    meta = {"target": args.target, "commit": args.commit, "line_tol": args.line_tol}
    if args.format == "json":
        print(json.dumps(render_json(meta, cov, scored), indent=2))
    else:
        print(render_markdown(meta, cov, scored))
    return 0


# --------------------------------------------------------------------------- #
# Selftest                                                                      #
# --------------------------------------------------------------------------- #

def _selftest() -> int:
    tax_path = Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"
    tax = load_taxonomy(tax_path)
    fails: list[str] = []

    findings = normalize_results([], tax)  # start empty, then add concrete ones
    findings += [
        AuditFinding("own-check", "src/Util/Io.cs", 9, "OWN001", "leak", 1, "idisposable-leak"),
        AuditFinding("codeql", "src/Util/Io.cs", 10, "cs/local-not-disposed", "nd", 1,
                     "idisposable-leak"),
        AuditFinding("own-check", "src/Vm/Customer.cs", 12, "OWN001", "sub", 2,
                     "subscription-leak", resource="subscription token"),
        AuditFinding("codeql", "DevExpress.Xpf/G.cs", 4, "cs/empty-block", "x", 0,
                     "uncategorized", suppressed=True, suppress_reason="third-party: DevExpress."),
        AuditFinding("codeql", "src/Util/Misc.cs", 3, "FOO999", "y", 0, "uncategorized"),
    ]
    cov = coverage(findings)
    scored = score(findings, tax)
    meta = {"target": "acme/legacy", "commit": "abc123", "generated": "2026-06-24",
            "profile": "desktop-wpf", "tiers": "build-free", "line_tol": 3,
            "no_tool_static": [6, 11]}

    md = render_markdown(meta, cov, scored)
    for needle in ("# Own.NET Audit — health report", "## Where it hurts most",
                   "## High-confidence findings", "## Candidates",
                   "## Coverage / honesty", "NO-TOOL", "How to read"):
        if needle not in md:
            fails.append(f"markdown missing section/marker: {needle!r}")
    if "third-party: DevExpress." not in md:
        fails.append("coverage must report the suppressed DevExpress count")
    if "`FOO999`" not in md:
        fails.append("coverage must surface the unmapped FOO999 rule")
    if "src/Util" not in md:
        fails.append("heatmap must list the worst module (src/Util)")
    # the agreed leak (high-confidence) must be the worst module, ahead of src/Vm
    util_pos, vm_pos = md.find("`src/Util`"), md.find("`src/Vm`")
    if util_pos == -1 or (vm_pos != -1 and util_pos > vm_pos):
        fails.append("heatmap ordering: src/Util (agreed leak) must precede src/Vm")

    js = render_json(meta, cov, scored)
    if js["meta"]["target"] != "acme/legacy":
        fails.append("json lost meta")
    if js["totals"]["high_confidence"] != 1:
        fails.append(f"json high_confidence wrong: {js['totals']}")
    if js["coverage"]["suppressed"] != 1:
        fails.append("json coverage lost suppressed count")
    if not js["clusters"] or "evidence" not in js["clusters"][0]:
        fails.append("json clusters missing evidence")

    total = 13
    for f in fails:
        print(f"REPORT SELFTEST FAIL: {f}")
    print(f"report selftest: {total - len(fails)}/{total} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
