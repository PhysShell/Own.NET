#!/usr/bin/env python3
"""P-037 A2.2-5: the mutation campaign's manifest and recorded report are what they say.

Runs no tool. Pins that the committed corpus/p037-mutation files equal a
regeneration (the generator is the source of truth), that every declared mutant
carries the campaign's rule (it must compile, the forbidden kill reasons are
declared, its expected outcome is preregistered and, for a producer mutant, an
exact expected RED map on existing witnesses), that every producer patch anchor
still occurs exactly once in the production extractor (a moved anchor is a
campaign that silently mutates nothing), and that report.json was recorded for
THIS manifest and THIS production tree with every acceptance criterion met: no
survivor, no forbidden kill reason, every outcome the preregistered one, no
path in the record. The campaign itself (dotnet) runs in CI beside the oracle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_mutation_campaign as campaign  # noqa: E402

SOURCE_OPERATORS = {"REMOVE_HANDLE", "ADD_PARENTHESES", "PERTURB_BINDING", "DISTINGUISH_NESTED"}
REPAIRS_REVERTED = {"A2.2-4R1", "A2.2-4R2", "A2.2-4R3", "A2.2-4R5", "A2.2-4R6"}

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def run() -> int:
    check("mutation-campaign-static", campaign.check_static() == 0,
          "the manifest, its preconditions or the recorded report failed (see above)")
    manifest: dict[str, Any] = json.loads(campaign.MANIFEST.read_text(encoding="utf-8"))
    mutants: list[dict[str, Any]] = manifest["mutants"]
    by_id = {str(m["id"]): m for m in mutants}

    check("three-surfaces-declared",
          {m["surface"] for m in mutants} == {"source", "producer", "taxonomy"},
          f"surfaces {sorted({m['surface'] for m in mutants})}")
    ops = {m["operator"] for m in mutants if m["surface"] == "source"}
    check("four-frozen-source-operators", ops == SOURCE_OPERATORS,
          f"operators {sorted(ops)}")
    check("perturb-binding-has-its-expanded-params-twin",
          "M3-perturb-binding-params" in by_id and "M3-perturb-binding-named" in by_id,
          "PERTURB_BINDING needs the named form and the expanded-params form")
    reverts = {str(m["reverts"]).split(" ")[0] for m in mutants if m["surface"] == "producer"}
    check("every-production-repair-has-a-regression-mutant", reverts == REPAIRS_REVERTED,
          f"reverted {sorted(reverts)}, expected {sorted(REPAIRS_REVERTED)}")
    rule = str(manifest.get("rule", ""))
    check("rule-forbids-mutation-vandalism",
          {"build_failure", "extractor_crash", "unrelated_check_failure"} <= set(campaign.FORBIDDEN)
          and all(m.get("forbidden_kill_reasons") == campaign.FORBIDDEN for m in mutants)
          and "forbidden" in rule and "valid C#" in rule,
          "every mutant must declare the forbidden kill reasons and the rule must say so")
    outcomes_ok = {"green", "killed", "unclassified"}
    check("every-mutant-preregisters-its-outcome",
          all(m.get("expected") in outcomes_ok for m in mutants),
          f"{[m['id'] for m in mutants if m.get('expected') not in outcomes_ok]}")
    check("source-metamorphs-carry-both-designs-and-obligations",
          all(m.get("base_design") and m.get("mutant_design") and len(m.get("obligations", [])) >= 3
              for m in mutants if m["surface"] == "source"),
          "a source metamorph needs a base design, a mutant design and obligations")
    check("taxonomy-mutant-expects-unclassified-in-three-places",
          all(set(m["expected_failures"]) == {"freeze_test", "hostile_test", "oracle_driver"}
              for m in mutants if m["surface"] == "taxonomy"),
          "the taxonomy mutant must be caught by the freeze test, the hostile test and the driver")

    if not campaign.REPORT.exists():
        check("report-recorded", False, "corpus/p037-mutation/report.json is missing")
    else:
        text = campaign.REPORT.read_text(encoding="utf-8")
        report: dict[str, Any] = json.loads(text)
        results: dict[str, Any] = report.get("mutants", {})
        totals: dict[str, Any] = report.get("totals", {})
        check("report-no-survivor-no-forbidden-reason",
              totals.get("survived") == 0 and totals.get("forbidden") == 0
              and totals.get("mutants") == len(mutants),
              f"totals {totals}")
        producers = [results.get(mid, {}) for mid, m in by_id.items() if m["surface"] == "producer"]
        check("producer-kills-are-the-preregistered-reason",
              bool(producers) and all(r.get("outcome") == "killed"
                                      and r.get("kill_reason") == "preregistered"
                                      and r.get("observed_red") == r.get("expected_red")
                                      for r in producers),
              f"{[(r.get('outcome'), r.get('kill_reason')) for r in producers]}")
        taxonomy = [(mid, results.get(mid, {})) for mid, m in by_id.items()
                    if m["surface"] == "taxonomy"]
        check("taxonomy-reads-unclassified-not-reclassified",
              bool(taxonomy) and all(
                  r.get("outcome") == "unclassified"
                  and all(by_id[mid]["remove_exclusion"] in detail
                          for detail in r.get("failures", {}).get("oracle_driver", {}).values())
                  and r.get("failures", {}).get("oracle_driver")
                  for mid, r in taxonomy),
              f"{[(mid, r.get('outcome')) for mid, r in taxonomy]}")
        metamorphs = {mid: r for mid, r in results.items()
                      if by_id.get(mid, {}).get("surface") == "source"}
        not_green = [(mid, r.get("outcome")) for mid, r in metamorphs.items()
                     if r.get("outcome") != "green"]
        check("metamorphs-green-with-every-obligation",
              all(r.get("outcome") == "green" and all(o.get("ok") for o in r.get("obligations", []))
                  for r in metamorphs.values()),
              f"{not_green}")
        check("report-carries-no-path",
              "/tmp/" not in text and "/home/" not in text and "<work>" not in text
              and "C:\\\\" not in text,
              "a deterministic record names no directory")
        check("report-tree-restored-and-oracle-green",
              report.get("acceptance", {}).get("production_tree_restored") is True
              and report.get("acceptance", {}).get("ordinary_oracle_red_free") is True
              and report.get("acceptance", {}).get("no_open_finding") is True,
              f"acceptance {report.get('acceptance')}")

    if _failures:
        print(f"RESULT: {len(_failures)} mutation-campaign check(s) failed")
        return 1
    print(f"RESULT: mutation campaign consistent over {len(mutants)} mutant(s) "
          f"({sum(m['surface'] == 'source' for m in mutants)} source, "
          f"{sum(m['surface'] == 'producer' for m in mutants)} producer, "
          f"{sum(m['surface'] == 'taxonomy' for m in mutants)} taxonomy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
