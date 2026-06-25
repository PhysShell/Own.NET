#!/usr/bin/env python3
"""
Own.NET Audit — runtime ingest bridge (Plan.md §4 → §3.5).

Converts the leak-harness's JSON result into SARIF so runtime findings flow through
the *same* ``normalize → score → report`` pipeline as the static tiers — runtime is
not a separate report, it's more tools feeding one model. The pay-off: a
runtime-confirmed leak that lands in the same file as a static finding clusters
with it → **high confidence** (the static→runtime confirmation in Plan.md §3.5,
e.g. own-check OWN014 + leak-harness on ``VideoSource.xaml.cs:123``).

The C# harnesses (``audit/runtime/LeakHarness/`` and ``DuplicateDetector/``, Windows
/ build-required) write the JSON; this bridge is pure Python and gates on Linux CI,
like the aggregation selftests.

Usage:
  ingest.py --leak-harness result.json [--out leak-harness.sarif]
  ingest.py --duplicate-detector result.json [--out duplicate-detector.sarif]
  ingest.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_AGG = Path(__file__).resolve().parent.parent / "aggregate"
sys.path.insert(0, str(_AGG))
from normalize import load_taxonomy, normalize_results, parse_sarif  # noqa: E402
from score import score  # noqa: E402

DEFAULT_TAXONOMY = (Path(__file__).resolve().parent.parent
                    / "static" / "taxonomy" / "categories.yml")


def _runtime_sarif(tool: str, findings: list[dict[str, Any]],
                   run_props: dict[str, Any], level: str) -> dict[str, Any]:
    """Build a SARIF 2.1.0 log from already-normalized runtime findings. Each finding
    is ``{rule, message, uri, line, properties}``; a ``line < 1`` stays file-level (no
    region) rather than fabricate line 1. The ``level`` is cosmetic for code scanning
    — score.py derives severity from the taxonomy category, not the SARIF level."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for f in findings:
        rule_id = f["rule"]
        rules.setdefault(rule_id, {"id": rule_id, "name": rule_id,
                                   "defaultConfiguration": {"level": level}})
        phys: dict[str, Any] = {"artifactLocation": {"uri": f["uri"]}}
        if f["line"] >= 1:
            phys["region"] = {"startLine": f["line"]}
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": f["message"]},
            "locations": [{"physicalLocation": phys}],
            "properties": f.get("properties", {}),
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": tool,
                "informationUri": "https://github.com/PhysShell/Own.NET",
                "rules": list(rules.values()),
            }},
            "results": results,
            "properties": run_props,
        }],
    }


def _location(f: dict[str, Any]) -> tuple[str, int]:
    """A finding's (uri, line). parse_sarif drops results with NO location, so always
    carry an artifactLocation: the source file when known, else the type as a
    synthetic uri (type-based findings like duplicate-immutable have no source line)."""
    return (f.get("location") or f.get("type") or "runtime", int(f.get("line", 0) or 0))


_SLUG_RE = re.compile(r"[^0-9A-Za-z._-]+")


def _synthetic_uri(scheme: str, type_name: str, value: str, index: int) -> str:
    """A UNIQUE synthetic uri for a runtime finding with no source line — a heap-wide
    duplicate group (``heap://``), a storming property (``inpc://``). Without a
    distinct uri every such finding would share the same ``(basename, line)`` and the
    scorer would collapse Country/Currency or Total/Subtotal into a single cluster,
    corrupting totals/heatmap and hiding distinct remediation items (Codex review on
    #103). The ``index`` guarantees uniqueness even when two display values share a
    prefix; the slug keeps the path readable. All findings of one ``scheme://<type>``
    roll up under one heatmap module, so it still buckets them together."""
    typ = (type_name or "runtime").replace("\\", ".").replace("/", ".")
    slug = _SLUG_RE.sub("_", value or "").strip("_")[:40] or "value"
    return f"{scheme}://{typ}/{index:04d}-{slug}"


def leak_harness_to_sarif(result: dict[str, Any]) -> dict[str, Any]:
    """Leak-harness JSON → SARIF. Only ``leaked: true`` findings (the deterministic
    growth assertion tripped) become results; a clean loop is evidence of *no* leak."""
    suffix = (f" [scenario: {result.get('scenario', '?')}, "
              f"x{result.get('iterations', '?')} iterations]")
    findings = []
    for f in result.get("findings", []):
        if not f.get("leaked"):
            continue
        uri, line = _location(f)
        findings.append({
            "rule": f.get("rule", "RUNTIME-LEAK"),
            "message": f.get("message", "") + suffix,
            "uri": uri, "line": line,
            "properties": {k: f[k] for k in
                           ("type", "baseline", "final", "growthPerIteration", "threshold")
                           if k in f},
        })
    return _runtime_sarif(
        result.get("tool", "leak-harness"), findings,
        {"target": result.get("target", ""), "commit": result.get("commit", ""),
         "scenario": result.get("scenario", ""), "iterations": result.get("iterations", 0)},
        level="error")


def duplicate_detector_to_sarif(result: dict[str, Any]) -> dict[str, Any]:
    """Duplicate-immutable-detector JSON → SARIF (Plan.md §2 cat. 11, the project's
    "gold"). Findings are type/value-based (a heap full of identical 'Country'
    strings), so they have no source line — file-level, level ``warning`` (a P2
    memory/perf finding, not a correctness error). A finding with ``report: false``
    (below the wasted-bytes threshold) is dropped."""
    findings = []
    for f in result.get("findings", []):
        if not f.get("report", True):
            continue
        # heap-wide duplicate groups have no source line; synthesize a UNIQUE uri per
        # value so distinct groups stay distinct clusters (see _synthetic_uri). Always
        # file-level (line 0) -> no fabricated region.
        uri = _synthetic_uri("heap", str(f.get("type", "")), str(f.get("value", "")),
                             len(findings))
        findings.append({
            "rule": f.get("rule", "RUNTIME-DUP-IMMUTABLE"),
            "message": f.get("message", ""),
            "uri": uri, "line": 0,
            "properties": {k: f[k] for k in
                           ("type", "value", "count", "bytesPerInstance", "wastedBytes")
                           if k in f},
        })
    return _runtime_sarif(
        result.get("tool", "duplicate-detector"), findings,
        {"target": result.get("target", ""), "commit": result.get("commit", ""),
         "minWastedBytes": result.get("minWastedBytes", 0)},
        level="warning")


def propertychanged_storm_to_sarif(result: dict[str, Any]) -> dict[str, Any]:
    """PropertyChanged-storm profiler JSON → SARIF (Plan.md §2 cat. 6, §4.3). The
    profiler counts, over one user operation, how often each property raises
    PropertyChanged and how many of those raises carry no value change (a missing
    equality guard). A property over its per-operation threshold is a storm. When the
    instrumentation resolved a source file the finding keeps it — so a storm clusters
    with a static ``INPC0xx`` hit (cat. 5) in the same file → high confidence (§3.5);
    otherwise we synthesize a unique per-property uri so distinct storming properties
    stay distinct clusters. ``report: false`` (below threshold) is dropped; level
    ``warning`` (a P2 perf finding, not a correctness error)."""
    findings = []
    for f in result.get("findings", []):
        if not f.get("report", True):
            continue
        # A source location is usable for clustering ONLY when the line is resolved
        # (>= 1). The C# falls back to line 0 when only the file is known; writing the
        # bare file at line 0 would collapse every file-only storm into one cluster and
        # could false-match a static finding on lines 1-3 (Codex review on #104). In
        # that case keep a unique per-property synthetic uri instead.
        loc = f.get("location")
        line = int(f.get("line", 0) or 0)
        if loc and line >= 1:
            uri = str(loc)
        else:
            uri = _synthetic_uri("inpc", str(f.get("type", "")),
                                 str(f.get("property", "")), len(findings))
            line = 0
        findings.append({
            "rule": f.get("rule", "RUNTIME-PROPCHANGED-STORM"),
            "message": f.get("message", ""),
            "uri": uri, "line": line,
            "properties": {k: f[k] for k in
                           ("type", "property", "raises", "redundantRaises",
                            "perOperation", "threshold")
                           if k in f},
        })
    return _runtime_sarif(
        result.get("tool", "propertychanged-storm"), findings,
        {"target": result.get("target", ""), "commit": result.get("commit", ""),
         "scenario": result.get("scenario", ""), "operations": result.get("operations", 0)},
        level="warning")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert a runtime tool's JSON result to SARIF.")
    # exactly one source tool — reject both so a stray flag fails fast instead of
    # silently converting the wrong file (CodeRabbit review on #103).
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--leak-harness", help="leak-harness result JSON")
    src.add_argument("--duplicate-detector", help="duplicate-immutable-detector result JSON")
    src.add_argument("--propertychanged-storm", help="PropertyChanged-storm profiler result JSON")
    ap.add_argument("--out", default="", help="output SARIF (defaults per tool under artifacts/)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.leak_harness:
        result = json.loads(Path(args.leak_harness).read_text(encoding="utf-8"))
        sarif = leak_harness_to_sarif(result)
        default_out = "artifacts/own-audit/leak-harness.sarif"
    elif args.duplicate_detector:
        result = json.loads(Path(args.duplicate_detector).read_text(encoding="utf-8"))
        sarif = duplicate_detector_to_sarif(result)
        default_out = "artifacts/own-audit/duplicate-detector.sarif"
    elif args.propertychanged_storm:
        result = json.loads(Path(args.propertychanged_storm).read_text(encoding="utf-8"))
        sarif = propertychanged_storm_to_sarif(result)
        default_out = "artifacts/own-audit/propertychanged-storm.sarif"
    else:
        ap.error("one of --leak-harness / --duplicate-detector / "
                 "--propertychanged-storm is required (or --selftest)")

    out = Path(args.out or default_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "results": len(sarif["runs"][0]["results"])}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Selftest — embedded fixtures; proves runtime findings flow into the pipeline  #
# and confirm static findings (Plan.md §3.5). Pure Python, gates on Linux CI.   #
# --------------------------------------------------------------------------- #

def _sample_result() -> dict[str, Any]:
    return {
        "tool": "leak-harness", "scenario": "open-close-declaration",
        "target": "acme/LegacyApp", "commit": "deadbeef", "iterations": 10,
        "findings": [
            # a confirmed subscription leak, correlated to its source line
            {"rule": "RUNTIME-LEAK-SUBSCRIPTION", "type": "Acme.Vm.DeclarationViewModel",
             "location": "src/Vm/DeclarationViewModel.cs", "line": 123,
             "baseline": 1, "final": 11, "growthPerIteration": 1.0, "threshold": 0.5,
             "leaked": True, "message": "retained instances grew 1->11 over 10 cycles"},
            # a type-based duplicate-immutable finding — no source line (file-level)
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String",
             "location": "Acme.Ref.Country", "line": 0,
             "baseline": 0, "final": 48211, "leaked": True,
             "message": "48211 duplicate 'Country' strings on the heap"},
            # a clean loop — NOT a finding, must be dropped
            {"rule": "RUNTIME-LEAK-TIMER", "type": "Acme.Vm.CleanTimerViewModel",
             "location": "src/Vm/CleanTimerViewModel.cs", "line": 40,
             "baseline": 1, "final": 1, "growthPerIteration": 0.0, "threshold": 0.5,
             "leaked": False, "message": "stable across 10 cycles"},
        ],
    }


def _selftest() -> int:
    tax = load_taxonomy(DEFAULT_TAXONOMY)
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    sarif = leak_harness_to_sarif(_sample_result())
    run = sarif["runs"][0]
    results = run["results"]

    check(sarif["version"] == "2.1.0", "sarif version must be 2.1.0")
    check(run["tool"]["driver"]["name"] == "leak-harness", "driver name must be leak-harness")
    check(len(results) == 2, f"only leaked findings become results: expected 2, got {len(results)}")
    rule_ids = {r["ruleId"] for r in results}
    check(rule_ids == {"RUNTIME-LEAK-SUBSCRIPTION", "RUNTIME-DUP-IMMUTABLE"},
          f"unexpected rule ids: {rule_ids}")
    # source-located finding keeps its region; the type-based one stays file-level
    by_rule = {r["ruleId"]: r for r in results}
    sub_loc = by_rule["RUNTIME-LEAK-SUBSCRIPTION"]["locations"][0]["physicalLocation"]
    dup_loc = by_rule["RUNTIME-DUP-IMMUTABLE"]["locations"][0]["physicalLocation"]
    check(sub_loc.get("region", {}).get("startLine") == 123,
          "subscription leak must keep its source line")
    check("region" not in dup_loc, "type-based duplicate finding must stay file-level (no region)")
    check(run["properties"]["scenario"] == "open-close-declaration", "scenario lost from run props")

    # runtime findings flow through the static taxonomy: correct categories.
    findings = normalize_results(parse_sarif(json.dumps(sarif), "leak-harness", []), tax)
    cat = {f.rule: (f.category, f.category_name) for f in findings}
    check(cat.get("RUNTIME-LEAK-SUBSCRIPTION") == (2, "subscription-leak"),
          f"runtime subscription leak -> category 2, got {cat.get('RUNTIME-LEAK-SUBSCRIPTION')}")
    check(cat.get("RUNTIME-DUP-IMMUTABLE") == (11, "duplicate-immutable"),
          f"runtime duplicate-immutable -> category 11, got {cat.get('RUNTIME-DUP-IMMUTABLE')}")

    # Plan.md §3.5: a runtime-confirmed leak in the same file as a static finding
    # clusters with it -> high confidence (static->runtime confirmation).
    static_sarif = json.dumps({"version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "Own.NET"}},
        "results": [{"ruleId": "OWN014", "level": "warning",
                     "message": {"text": "region escape: subscribes to AppEventBus, no -="},
                     "locations": [{"physicalLocation": {
                         "artifactLocation": {"uri": "src/Vm/DeclarationViewModel.cs"},
                         "region": {"startLine": 122}}}]}]}]})
    both = (normalize_results(parse_sarif(static_sarif, "own-check", []), tax)
            + normalize_results(parse_sarif(json.dumps(sarif), "leak-harness", []), tax))
    scored = score(both, tax, line_tol=3)
    confirmed = [c for c in scored["clusters"]
                 if c.confidence == "high" and set(c.tools) == {"own-check", "leak-harness"}]
    check(len(confirmed) == 1,
          f"static OWN014 + runtime leak in the same file must form 1 high-confidence cluster, "
          f"got {[(c.module, c.tools, c.confidence) for c in scored['clusters']]}")

    # Duplicate-immutable detector (cat. 11, the project's "gold"): type/value-based,
    # file-level, level warning; a below-threshold finding (report:false) is dropped.
    # The real C# emits NO source location (heap-wide groups), so the bridge must
    # synthesize a UNIQUE per-value uri — else distinct values (Country, Currency)
    # collapse into one cluster, corrupting totals/heatmap (Codex review on #103).
    dup = duplicate_detector_to_sarif({
        "tool": "duplicate-detector", "target": "acme/LegacyApp", "minWastedBytes": 65536,
        "findings": [
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String", "value": "Country",
             "count": 48211, "bytesPerInstance": 36, "wastedBytes": 1735560, "report": True,
             "message": "48211 duplicate 'Country' strings (~1.7 MB wasted)"},
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String", "value": "Currency",
             "count": 31002, "bytesPerInstance": 38, "wastedBytes": 1178038, "report": True,
             "message": "31002 duplicate 'Currency' strings (~1.1 MB wasted)"},
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String", "value": "x",
             "count": 3, "wastedBytes": 108, "report": False, "message": "below threshold"},
        ]})
    dres = dup["runs"][0]["results"]
    check(len(dres) == 2, f"below-threshold dup finding must be dropped: got {len(dres)}")
    check(all(r["level"] == "warning" for r in dres),
          "duplicate-immutable must be SARIF level warning (P2)")
    check(all("region" not in r["locations"][0]["physicalLocation"] for r in dres),
          "type-based duplicate finding must stay file-level (no region)")
    uris = {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in dres}
    check(len(uris) == 2, f"each duplicate value needs a unique synthetic uri, got {uris}")
    check(dres[0]["properties"].get("wastedBytes") == 1735560,
          "duplicate finding must carry wastedBytes in properties")
    dnorm = normalize_results(parse_sarif(json.dumps(dup), "duplicate-detector", []), tax)
    dcat = {f.rule: (f.category, f.category_name) for f in dnorm}
    check(dcat.get("RUNTIME-DUP-IMMUTABLE") == (11, "duplicate-immutable"),
          f"duplicate-immutable -> category 11, got {dcat.get('RUNTIME-DUP-IMMUTABLE')}")
    # distinct over-threshold values must NOT collapse into a single cluster.
    dscored = score(dnorm, tax, line_tol=3)
    check(dscored["totals"]["clusters"] == 2,
          f"Country and Currency must stay 2 separate clusters, got "
          f"{dscored['totals']['clusters']}")
    check(dscored["by_category"].get("duplicate-immutable") == 2,
          f"both duplicate values must count under category 11, got {dscored['by_category']}")

    # PropertyChanged-storm profiler (cat. 6): per-operation raise frequency. A storm
    # with a resolved source file keeps its line (so it clusters with a static INPC0xx
    # hit in the same file); storms with no source line get unique per-property uris so
    # distinct properties stay distinct clusters; below-threshold is dropped.
    storm = propertychanged_storm_to_sarif({
        "tool": "propertychanged-storm", "target": "acme/LegacyApp",
        "scenario": "open-declaration", "operations": 1,
        "findings": [
            {"rule": "RUNTIME-PROPCHANGED-STORM", "type": "Acme.Vm.DeclarationViewModel",
             "property": "Total", "location": "src/Vm/DeclarationViewModel.cs", "line": 88,
             "raises": 4200, "redundantRaises": 3990, "perOperation": 4200.0,
             "threshold": 50, "report": True,
             "message": "Total raised PropertyChanged 4200x/op (3990 with no value change)"},
            {"rule": "RUNTIME-PROPCHANGED-STORM", "type": "Acme.Vm.DeclarationViewModel",
             "property": "Subtotal", "raises": 900, "redundantRaises": 880,
             "perOperation": 900.0, "threshold": 50, "report": True,
             "message": "Subtotal raised PropertyChanged 900x/op (880 with no value change)"},
            # file resolved but LINE unresolved (C# falls back to 0): must NOT use the
            # bare file uri — keep a synthetic uri so it can't collapse/false-match.
            {"rule": "RUNTIME-PROPCHANGED-STORM", "type": "Acme.Vm.DeclarationViewModel",
             "property": "Discount", "location": "src/Vm/DeclarationViewModel.cs", "line": 0,
             "raises": 700, "redundantRaises": 690, "perOperation": 700.0,
             "threshold": 50, "report": True,
             "message": "Discount raised PropertyChanged 700x/op (file known, line unresolved)"},
            {"rule": "RUNTIME-PROPCHANGED-STORM", "type": "Acme.Vm.DeclarationViewModel",
             "property": "Title", "raises": 2, "redundantRaises": 0, "perOperation": 2.0,
             "threshold": 50, "report": False, "message": "below threshold"},
        ]})
    sres = storm["runs"][0]["results"]
    check(len(sres) == 3, f"below-threshold storm must be dropped: got {len(sres)}")
    check(all(r["level"] == "warning" for r in sres),
          "propertychanged-storm must be SARIF level warning (P2)")
    located = [r for r in sres
               if r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
               == "src/Vm/DeclarationViewModel.cs"]
    check(len(located) == 1
          and located[0]["locations"][0]["physicalLocation"].get("region", {})
          .get("startLine") == 88,
          "only the line-resolved storm keeps the bare source file (line>=1)")
    # the file-only (line 0) storm falls back to a synthetic inpc:// uri, no region.
    file_only = [r for r in sres if "Discount" in r["message"]["text"]]
    check(len(file_only) == 1
          and file_only[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
          .startswith("inpc://")
          and "region" not in file_only[0]["locations"][0]["physicalLocation"],
          "a file-only storm (line 0) must fall back to a synthetic inpc:// uri")
    suris = {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in sres}
    check(len(suris) == 3, f"distinct storming properties need distinct uris, got {suris}")
    snorm = normalize_results(parse_sarif(json.dumps(storm), "propertychanged-storm", []), tax)
    scat = {f.rule: (f.category, f.category_name) for f in snorm}
    check(scat.get("RUNTIME-PROPCHANGED-STORM") == (6, "propertychanged-storm"),
          f"propertychanged-storm -> category 6, got {scat.get('RUNTIME-PROPCHANGED-STORM')}")
    # Plan §3.5: the located storm + a static INPC0xx in the same file -> high confidence.
    inpc_sarif = json.dumps({"version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": "Own.NET"}}, "results": [
            {"ruleId": "INPC003", "level": "warning",
             "message": {"text": "raise PropertyChanged without an equality check"},
             "locations": [{"physicalLocation": {
                 "artifactLocation": {"uri": "src/Vm/DeclarationViewModel.cs"},
                 "region": {"startLine": 87}}}]}]}]})
    both_s = normalize_results(parse_sarif(inpc_sarif, "own-check", []), tax) + snorm
    sscored = score(both_s, tax, line_tol=3)
    confirmed_s = [c for c in sscored["clusters"] if c.confidence == "high"
                   and set(c.tools) == {"own-check", "propertychanged-storm"}]
    check(len(confirmed_s) == 1,
          f"static INPC0xx + runtime storm in the same file must form 1 high-confidence "
          f"cluster, got {[(c.module, c.tools, c.confidence) for c in sscored['clusters']]}")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"INGEST SELFTEST FAIL: {f}")
    print(f"ingest selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
