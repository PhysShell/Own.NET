#!/usr/bin/env python3
"""
Own.NET Audit — renderers (Plan.md §3.5). Turns the scored findings + coverage
ledger into the "health anamnesis": a categorized report ranked by where it hurts
most, with an honest coverage map.

  * **Markdown** — for humans / a GitHub run summary (as oracle/mine do today).
  * **JSON** — machine-readable, for the downstream AI layer and regression diffs.
  * **merged SARIF** — one combined SARIF 2.1.0 log (audit categories as rules) so
    the findings surface in GitHub code scanning / the Security tab.
  * **HTML** — a self-contained heatmap page for browsing.

All four are views over the same scored model, not new analysis.

The coverage section is load-bearing: it states which tiers ran, which categories
are NO-TOOL / deferred-to-runtime, how many DevExpress findings were suppressed,
and which rules have no taxonomy entry yet. A clean report that hid its own gaps
would be worse than useless.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import AuditFinding, coverage, load_taxonomy, normalize_results
from score import score
from score import to_json as score_to_json

# Audit P0..P3 severities -> SARIF result levels (merged-SARIF renderer).
SEV_TO_LEVEL = {"P0": "error", "P1": "error", "P2": "warning", "P3": "note"}

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
    if len(high) > max_list:
        out.append(f"- … (+{len(high) - max_list} more)")

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
    skipped = cov.get("analysis_skipped", 0)
    if skipped:
        by = cov.get("analysis_skipped_by") or {}
        detail = ", ".join(f"{r} x{n}" for r, n in sorted(by.items()))
        out.append(f"- analysis-skipped (coverage notes, not scored): {skipped}"
                   + (f" — {detail}" if detail else ""))
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


def render_sarif(meta: dict[str, Any], cov: dict[str, Any],
                 scored: dict[str, Any]) -> dict[str, Any]:
    """One merged SARIF 2.1.0 log for GitHub code scanning (Plan.md §3.5).

    Audit categories become the SARIF rules (so the Security tab groups by our
    taxonomy, not the underlying tool ids); each scored cluster is one result, with
    the contributing tools, confidence and pain carried in properties. Suppressed
    and analysis-skipped counts ride in the run properties so the honesty ledger
    travels with the log."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for c in scored["clusters"]:
        rule_id = f"own-audit/{c.category_name}"
        level = SEV_TO_LEVEL.get(c.severity, "warning")
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": c.category_name,
                "shortDescription": {
                    "text": f"{CATEGORY_LABELS.get(c.category, c.category_name)} "
                            f"(category {c.category})"},
                "defaultConfiguration": {"level": level},
                "properties": {"category": c.category},
            }
        # A genuinely file-level finding (parse_sarif records line 0 when the
        # upstream result has no region) must STAY file-level — omit region rather
        # than fabricate a line-1 region that mis-pins the code-scanning alert.
        phys: dict[str, Any] = {"artifactLocation": {"uri": c.path}}
        if c.line >= 1:
            phys["region"] = {"startLine": c.line}
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": f"[{c.severity} · {c.confidence}] {c.category_name} — "
                                + "; ".join(f"{f.tool}:{f.rule}" for f in c.findings)},
            "locations": [{"physicalLocation": phys}],
            "properties": {"category": c.category, "categoryName": c.category_name,
                           "confidence": c.confidence, "severity": c.severity,
                           "pain": c.pain, "tools": c.tools},
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "Own.NET Audit",
                "informationUri": "https://github.com/PhysShell/Own.NET",
                "rules": list(rules.values()),
            }},
            "results": results,
            "properties": {
                "target": meta.get("target", ""),
                "commit": meta.get("commit", ""),
                "suppressed": cov.get("suppressed", 0),
                "analysisSkipped": cov.get("analysis_skipped", 0),
            },
        }],
    }


def render_html(meta: dict[str, Any], cov: dict[str, Any],
                scored: dict[str, Any], max_list: int = 200) -> str:
    """A self-contained HTML heatmap page (Plan.md §3.5) — no external assets."""
    e = html.escape
    clusters = scored["clusters"]
    high = [c for c in clusters if c.confidence == "high"]
    sev_class = {"P0": "p0", "P1": "p1", "P2": "p2", "P3": "p3"}

    rows = "\n".join(
        f"<tr><td class='mod'>{e(r['module'])}</td><td class='num'>{r['pain']}</td>"
        f"<td class='num'>{r['findings']}</td><td class='num'>{r['high_confidence']}</td>"
        f"<td>{e(r['top_category'])}</td></tr>"
        for r in scored["heatmap"][:max_list]) or \
        "<tr><td colspan='5'><em>no findings</em></td></tr>"

    def finding_li(c: Any) -> str:
        cls = sev_class.get(c.severity, "p3")
        return (f"<li><span class='sev {cls}'>{e(c.severity)}</span> "
                f"<code>{e(c.path)}:{c.line}</code> "
                f"<strong>{e(c.category_name)}</strong> "
                f"<span class='tools'>{e(', '.join(c.tools))}</span></li>")

    high_li = "\n".join(finding_li(c) for c in high[:max_list]) or "<li><em>none</em></li>"
    cand = [c for c in clusters if c.confidence == "candidate"]
    cand_li = "\n".join(finding_li(c) for c in cand[:max_list]) or "<li><em>none</em></li>"
    cand_more = (f"<li><em>+{len(cand) - max_list} more</em></li>"
                 if len(cand) > max_list else "")
    cov_rows = "".join(f"<li>{e(line.strip().removeprefix('- '))}</li>"
                       for line in _coverage_section(meta, cov, scored)
                       if line.strip() and not line.startswith("#"))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Own.NET Audit — {e(str(meta.get('target', '?')))}</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#1b1b1b;max-width:60rem}}
 h1{{font-size:1.4rem}} h2{{margin-top:1.8rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{padding:.35rem .6rem;border-bottom:1px solid #eee;text-align:left}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 td.mod{{font-family:ui-monospace,monospace}}
 code{{background:#f4f4f4;padding:.05rem .3rem;border-radius:3px}}
 ul{{list-style:none;padding-left:0}} li{{padding:.15rem 0}}
 .sev{{display:inline-block;width:1.6rem;text-align:center;border-radius:3px;color:#fff;font-size:.8rem}}
 .p0{{background:#7a0000}}.p1{{background:#c0392b}}.p2{{background:#e0820a}}.p3{{background:#888}}
 .tools{{color:#666;font-size:.85rem}} .meta{{color:#444}}
</style></head><body>
<h1>Own.NET Audit — health report — <code>{e(str(meta.get('target', '?')))}</code></h1>
<p class="meta">commit <code>{e(str(meta.get('commit', '?')))}</code> ·
 generated {e(str(meta.get('generated', '?')))} ·
 profile <code>{e(str(meta.get('profile', '?')))}</code> ·
 tools {e(', '.join(cov.get('tools') or []) or '(none)')}</p>
<p><strong>{scored['totals']['clusters']} findings</strong>
 ({scored['totals']['high_confidence']} high-confidence,
 {scored['totals']['candidates']} candidate)</p>
<h2>Where it hurts most</h2>
<table><thead><tr><th>module</th><th>pain</th><th>findings</th><th>high-conf</th>
<th>top category</th></tr></thead><tbody>
{rows}
</tbody></table>
<h2>High-confidence findings — {len(high)}</h2>
<ul>{high_li}</ul>
<h2>Candidates — {len(cand)}</h2>
<ul>{cand_li}{cand_more}</ul>
<h2>Coverage / honesty</h2>
<ul>{cov_rows}</ul>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the audit health report (markdown/json).")
    ap.add_argument("--findings", help="normalize.py --json output")
    ap.add_argument("--taxonomy", default=str(
        Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"))
    ap.add_argument("--format", choices=["markdown", "json", "sarif", "html"],
                    default="markdown")
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
    elif args.format == "sarif":
        print(json.dumps(render_sarif(meta, cov, scored), indent=2))
    elif args.format == "html":
        print(render_html(meta, cov, scored))
    else:
        print(render_markdown(meta, cov, scored))
    return 0


# --------------------------------------------------------------------------- #
# Selftest                                                                      #
# --------------------------------------------------------------------------- #

def _selftest() -> int:
    tax_path = Path(__file__).resolve().parents[1] / "static" / "taxonomy" / "categories.yml"
    tax = load_taxonomy(tax_path)
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:  # total derives from the call count
        checks.append("" if ok else msg)

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
        AuditFinding("own-check", "src/Io/Weird.cs", 5, "OWN050", "cannot verify", 0,
                     "uncategorized", note=True),
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
        check(needle in md, f"markdown missing section/marker: {needle!r}")
    check("third-party: DevExpress." in md, "coverage must report the suppressed DevExpress count")
    check("`FOO999`" in md, "coverage must surface the unmapped FOO999 rule")
    check("analysis-skipped" in md and "OWN050" in md,
          "coverage must surface analysis-skipped notes (OWN050)")
    check("src/Util" in md, "heatmap must list the worst module (src/Util)")
    # the agreed leak (high-confidence) must be the worst module, ahead of src/Vm
    util_pos, vm_pos = md.find("`src/Util`"), md.find("`src/Vm`")
    check(util_pos != -1 and not (vm_pos != -1 and util_pos > vm_pos),
          "heatmap ordering: src/Util (agreed leak) must precede src/Vm")

    js = render_json(meta, cov, scored)
    check(js["meta"]["target"] == "acme/legacy", "json lost meta")
    check(js["totals"]["high_confidence"] == 1, f"json high_confidence wrong: {js['totals']}")
    check(js["coverage"]["suppressed"] == 1, "json coverage lost suppressed count")
    check(bool(js["clusters"]) and "evidence" in js["clusters"][0],
          "json clusters missing evidence")

    # merged SARIF: 3 scored clusters -> 3 results; categories become rules; the
    # suppressed DevExpress finding is excluded from results but counted in run props.
    sa = render_sarif(meta, cov, scored)
    run = sa["runs"][0]
    check(sa["version"] == "2.1.0", "sarif version must be 2.1.0")
    check(len(run["results"]) == 3, f"sarif must have 3 results, got {len(run['results'])}")
    check(all(r["ruleId"].startswith("own-audit/") for r in run["results"]),
          "sarif results must use own-audit/<category> rule ids")
    check(all(loc["region"]["startLine"] >= 1
              for r in run["results"]
              for loc in (r["locations"][0]["physicalLocation"],) if "region" in loc),
          "sarif region startLine (when present) must be >= 1")
    # file-level findings (parse_sarif records line 0) must stay file-level — no
    # fabricated line-1 region that mis-pins the alert (Codex review on #101).
    fl = score([AuditFinding("codeql", "src/App/Asm.cs", 0, "cs/assembly", "x", 14,
                             "general-quality")], tax)
    fl_phys = render_sarif(meta, cov, fl)["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"]
    check("region" not in fl_phys, "file-level finding (line 0) must omit SARIF region")
    levels = {r["ruleId"]: r["level"] for r in run["results"]}
    check(levels.get("own-audit/idisposable-leak") == "error",
          "P1 leak must map to SARIF level error")
    check(levels.get("own-audit/uncategorized") == "note",
          "P3 uncategorized must map to SARIF level note")
    check(run["properties"]["suppressed"] == 1, "sarif run props must carry the suppressed count")
    rule_ids = {ru["id"] for ru in run["tool"]["driver"]["rules"]}
    check("own-audit/idisposable-leak" in rule_ids, "sarif driver must declare the category rules")

    # HTML: self-contained heatmap page with the worst module and the coverage ledger.
    h = render_html(meta, cov, scored)
    for needle in ("<!doctype html>", "</html>", "<table", "Own.NET Audit",
                   "Where it hurts most", "src/Util", "Coverage / honesty"):
        check(needle in h, f"html missing marker: {needle!r}")
    check("third-party: DevExpress." in h, "html coverage must report the suppressed finding")
    check("analysis-skipped" in h, "html coverage must surface analysis-skipped notes")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"REPORT SELFTEST FAIL: {f}")
    print(f"report selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
