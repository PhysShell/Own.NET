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
        uri, line = _location(f)
        findings.append({
            "rule": f.get("rule", "RUNTIME-DUP-IMMUTABLE"),
            "message": f.get("message", ""),
            "uri": uri, "line": line,
            "properties": {k: f[k] for k in
                           ("type", "value", "count", "bytesPerInstance", "wastedBytes")
                           if k in f},
        })
    return _runtime_sarif(
        result.get("tool", "duplicate-detector"), findings,
        {"target": result.get("target", ""), "commit": result.get("commit", ""),
         "minWastedBytes": result.get("minWastedBytes", 0)},
        level="warning")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert a runtime tool's JSON result to SARIF.")
    ap.add_argument("--leak-harness", help="leak-harness result JSON")
    ap.add_argument("--duplicate-detector", help="duplicate-immutable-detector result JSON")
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
    else:
        ap.error("one of --leak-harness / --duplicate-detector is required (or --selftest)")

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
    dup = duplicate_detector_to_sarif({
        "tool": "duplicate-detector", "target": "acme/LegacyApp", "minWastedBytes": 65536,
        "findings": [
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String", "value": "Country",
             "count": 48211, "bytesPerInstance": 36, "wastedBytes": 1735560,
             "location": "Acme.Ref.CountryTable", "line": 0, "report": True,
             "message": "48211 duplicate 'Country' strings (~1.7 MB wasted)"},
            {"rule": "RUNTIME-DUP-IMMUTABLE", "type": "System.String", "value": "x",
             "count": 3, "wastedBytes": 108, "report": False, "message": "below threshold"},
        ]})
    dres = dup["runs"][0]["results"]
    check(len(dres) == 1, f"below-threshold dup finding must be dropped: got {len(dres)}")
    check(dres[0]["level"] == "warning", "duplicate-immutable must be SARIF level warning (P2)")
    check("region" not in dres[0]["locations"][0]["physicalLocation"],
          "type-based duplicate finding must stay file-level (no region)")
    check(dres[0]["properties"].get("wastedBytes") == 1735560,
          "duplicate finding must carry wastedBytes in properties")
    dcat = {f.rule: (f.category, f.category_name)
            for f in normalize_results(parse_sarif(json.dumps(dup), "duplicate-detector", []), tax)}
    check(dcat.get("RUNTIME-DUP-IMMUTABLE") == (11, "duplicate-immutable"),
          f"duplicate-immutable -> category 11, got {dcat.get('RUNTIME-DUP-IMMUTABLE')}")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"INGEST SELFTEST FAIL: {f}")
    print(f"ingest selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
