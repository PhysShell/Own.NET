#!/usr/bin/env python3
"""
Own.NET Audit — runtime ingest bridge (Plan.md §4 → §3.5).

Converts the leak-harness's JSON result into SARIF so runtime findings flow through
the *same* ``normalize → score → report`` pipeline as the static tiers — runtime is
not a separate report, it's more tools feeding one model. The pay-off: a
runtime-confirmed leak that lands in the same file as a static finding clusters
with it → **high confidence** (the static→runtime confirmation in Plan.md §3.5,
e.g. own-check OWN014 + leak-harness on ``VideoSource.xaml.cs:123``).

The C# leak-harness (``audit/runtime/LeakHarness/``, Windows / build-required) runs
the deterministic GC+snapshot loop and writes the JSON; this bridge is pure Python
and gates on Linux CI, like the aggregation selftests.

Usage:
  ingest.py --leak-harness result.json --out artifacts/own-audit/leak-harness.sarif
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


def leak_harness_to_sarif(result: dict[str, Any]) -> dict[str, Any]:
    """Turn one leak-harness JSON result into a SARIF 2.1.0 log. Only findings with
    ``leaked: true`` (the deterministic growth assertion tripped) become results; a
    clean iteration loop is evidence of *no* leak, not a finding."""
    tool = result.get("tool", "leak-harness")
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for f in result.get("findings", []):
        if not f.get("leaked"):
            continue
        rule_id = f.get("rule", "RUNTIME-LEAK")
        rules.setdefault(rule_id, {"id": rule_id, "name": rule_id,
                                   "defaultConfiguration": {"level": "error"}})
        # A type-based finding (e.g. duplicate-immutable) may have no source line;
        # keep it file-level (no region) rather than fabricate line 1. parse_sarif
        # drops results with NO location, so always carry at least an artifactLocation
        # (the source file when known, else the type as a synthetic uri).
        uri = f.get("location") or f.get("type") or "runtime"
        phys: dict[str, Any] = {"artifactLocation": {"uri": uri}}
        line = int(f.get("line", 0) or 0)
        if line >= 1:
            phys["region"] = {"startLine": line}
        msg = (f.get("message", "")
               + f" [scenario: {result.get('scenario', '?')}, "
               + f"x{result.get('iterations', '?')} iterations]")
        results.append({
            "ruleId": rule_id,
            "level": "error",
            "message": {"text": msg},
            "locations": [{"physicalLocation": phys}],
            "properties": {k: f[k] for k in
                           ("type", "baseline", "final", "growthPerIteration", "threshold")
                           if k in f},
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
            "properties": {
                "target": result.get("target", ""),
                "commit": result.get("commit", ""),
                "scenario": result.get("scenario", ""),
                "iterations": result.get("iterations", 0),
            },
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert a leak-harness JSON result to SARIF.")
    ap.add_argument("--leak-harness", help="leak-harness result JSON")
    ap.add_argument("--out", default="artifacts/own-audit/leak-harness.sarif")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.leak_harness:
        ap.error("--leak-harness is required (or use --selftest)")

    result = json.loads(Path(args.leak_harness).read_text(encoding="utf-8"))
    sarif = leak_harness_to_sarif(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    n = len(sarif["runs"][0]["results"])
    print(json.dumps({"out": str(out), "leaked_findings": n}, indent=2))
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

    fails = [c for c in checks if c]
    for f in fails:
        print(f"INGEST SELFTEST FAIL: {f}")
    print(f"ingest selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
