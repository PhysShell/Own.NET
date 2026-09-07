#!/usr/bin/env python3
"""The sweep interpreter's own controls (P-022 step 7a, #260 final acceptance).

`tests/shadow_sweep.py` is what decides whether a recorded sweep run is
EVIDENCE. It is therefore the thing that must not be able to degrade into
"read the file and print OK": every rule it states gets a pair here that breaks
exactly that rule, and is reported for it.

The pairs are synthetic on purpose. A control built from the committed run
would agree with it by construction — including on the day the committed run is
wrong — and it could not construct the failures at all, because a recorded run
that skipped a target is precisely the file that must never exist in the tree.

`provenance_problems` is exercised separately from the rest: it is the one rule
whose answer depends on the checkout rather than on the pair, so a control that
folded it in would be reporting on git rather than on the interpreter.

Run:  python tests/test_shadow_sweep.py
      python tests/run_tests.py          (auto-discovered with every other test_*.py)
"""

from __future__ import annotations

import copy
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shadow_sweep import TARGET_FIELDS, compute_sweep_summary

PIN = "a" * 40
RAW = "b" * 64
CANON = "c" * 64
ADAPTER = "d" * 64
COMMAND = "scripts/own-check.sh --emit-facts <FACTS> -- targets/T"


def _definition() -> dict[str, Any]:
    return {
        "schema": 1,
        "sweep": "p022-shadow-sweep",
        "driver_version": 2,
        "targets": [{"target": "T", "pinned_commit": PIN}],
        "documents": [{
            "id": "T.repo", "target": "T", "target_commit": PIN,
            "extraction_mode": "directory-walk", "extraction_command": COMMAND,
            "timeout_seconds": 600.0,
        }],
    }


def _target_row(**over: int) -> dict[str, Any]:
    row: dict[str, Any] = {"target": "T", **dict.fromkeys(TARGET_FIELDS, 0)}
    row.update({"documents_extracted": 1, "compare_attempted": 1, "agreed": 1})
    row.update(over)
    return row


def _result(source_commit: str) -> dict[str, Any]:
    row = _target_row()
    return {
        "schema": 1,
        "sweep": "p022-shadow-sweep",
        "source_commit": source_commit,
        "recorded_at": "2026-09-07T00:00:00Z",
        "host": "test",
        "workflow_run_url": None,
        "driver_version": 2,
        "adapters": [{"sha256": ADAPTER, "bytes": 1024}],
        "documents": [{
            "id": "T.repo", "target": "T", "target_commit": PIN,
            "extraction_mode": "directory-walk", "extraction_command": COMMAND,
            "facts_sha256": RAW,
            "raw": {"algorithm": "sha256", "digest": RAW, "bytes": 10},
            "canonical": {"algorithm": "sha256", "digest": CANON, "bytes": 10},
            "outcome": "agreed", "timeout_seconds": 600.0,
            "reduction_outcome": "identical",
            "declared_boundary_observations": 0,
            "acceptance_unexplained_observations": 0,
            "derived_outcome": "equal", "wall_clock_seconds": 0.1,
        }],
        "targets": [row],
        "totals": {name: int(row[name]) for name in TARGET_FIELDS},
    }


def _head() -> str:
    """A commit this checkout really contains, so that the POSITIVE control is
    not silently failing on provenance and passing on everything else."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        done = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def run() -> int:
    fails: list[str] = []
    head = _head()

    def problems(mutate: Any) -> list[str]:
        definition, result = _definition(), _result(head)
        mutate(definition, result)
        return compute_sweep_summary(definition, result).problems

    def expect(label: str, needle: str, mutate: Any) -> None:
        found = problems(mutate)
        if not any(needle in p for p in found):
            fails.append(f"{label}: the interpreter did not report it "
                         f"(expected {needle!r}); it said {found}")

    # THE POSITIVE control, and it comes first: a pair with nothing wrong must
    # produce NO problems. Without it every assertion below is satisfied by an
    # interpreter that reports everything about everything.
    if head:
        clean = problems(lambda d, r: None)
        if clean:
            fails.append(f"a clean pair was reported as having problems: {clean}")
    else:
        print("shadow sweep interpreter: the positive control is SKIPPED — this "
              "is not a git checkout, so no commit can play the part of a valid "
              "provenance")

    # 1. #250's fifth failure mode, in both of its shapes.
    expect("an empty run", "compared zero of them",
           lambda d, r: (r.update(documents=[], targets=[],
                                  totals=dict.fromkeys(TARGET_FIELDS, 0))))
    expect("a target with nothing compared", "ZERO documents compared",
           lambda d, r: (r["targets"].__setitem__(
               0, _target_row(compare_attempted=0, agreed=0)),
               r["totals"].update(compare_attempted=0, agreed=0),
               r.update(documents=[])))

    # 2. The denominator is the DEFINITION's, in both directions.
    expect("a declared document the run does not carry",
           "absent from the run",
           lambda d, r: d["documents"].append(
               {**d["documents"][0], "id": "T.sln"}))
    expect("a measured document the definition does not declare",
           "not declared by the definition",
           lambda d, r: r["documents"].append(
               {**r["documents"][0], "id": "T.sln"}))
    expect("a declared target missing from the run",
           "a skipped target is not a passed repository",
           lambda d, r: d["targets"].append({"target": "U",
                                             "pinned_commit": PIN}))

    # 3. A run that measured SOMETHING, but not this.
    expect("a document measured at another commit", "target_commit=",
           lambda d, r: r["documents"][0].update(target_commit="f" * 40))
    expect("a document measured in another mode", "extraction_mode=",
           lambda d, r: r["documents"][0].update(extraction_mode="solution"))
    expect("a document measured by another command", "extraction_command=",
           lambda d, r: r["documents"][0].update(extraction_command="cat"))

    # 4. The outcome, and the outcome hiding inside an outcome.
    expect("a document that did not agree", "Only 'agreed' is an outcome",
           lambda d, r: r["documents"][0].update(outcome="diverged"))
    expect("an unexplained observation inside an agreed document",
           "acceptance-unexplained observation(s) in a document recorded as",
           lambda d, r: r["documents"][0].update(
               acceptance_unexplained_observations=1))

    # 5. The engine and the driver the run cannot name.
    expect("a run that names no adapter", "names no adapter at all",
           lambda d, r: r.update(adapters=[]))
    expect("an adapter named by something that is not a digest",
           "a path is not an identity",
           lambda d, r: r.update(adapters=[{"sha256": "release", "bytes": 0}]))
    expect("a driver version the definition does not expect",
           "the definition expects",
           lambda d, r: r.update(driver_version=1))
    expect("a document with no raw byte identity", "no raw byte identity",
           lambda d, r: r["documents"][0].update(raw={}))

    # 6. A total that is not the sum of its parts is a number somebody typed.
    expect("totals that disagree with the per-target rows",
           "is a number somebody typed",
           lambda d, r: r["totals"].update(agreed=7))

    # 7. Provenance, on its own: a commit this checkout does not contain.
    if head:
        definition, result = _definition(), _result("0" * 40)
        found = compute_sweep_summary(definition, result).problems
        if not any("does not exist in this repository" in p for p in found):
            fails.append(f"a run naming a commit this repository does not "
                         f"contain was accepted: {found}")

    # 8. The positive control must not be an accident of a shallow definition:
    #    a SECOND document, declared and measured, must also come back clean.
    if head:
        definition, result = _definition(), _result(head)
        second_def = copy.deepcopy(definition["documents"][0])
        second_res = copy.deepcopy(result["documents"][0])
        second_def["id"] = second_res["id"] = "T.sln"
        second_def["extraction_mode"] = second_res["extraction_mode"] = "solution"
        definition["documents"].append(second_def)
        result["documents"].append(second_res)
        result["targets"][0]["documents_extracted"] = 2
        result["targets"][0]["compare_attempted"] = 2
        result["targets"][0]["agreed"] = 2
        result["totals"]["documents_extracted"] = 2
        result["totals"]["compare_attempted"] = 2
        result["totals"]["agreed"] = 2
        found = compute_sweep_summary(definition, result).problems
        if found:
            fails.append(f"a clean two-document pair was reported as having "
                         f"problems: {found}")

    if fails:
        for f in fails:
            print(f"FAIL[shadow-sweep-interpreter]: {f}")
        return 1
    print("shadow sweep interpreter OK: 16 controls held (the empty run and the "
          "target with nothing compared, the denominator in both directions, a "
          "document measured at another commit / mode / command, a divergence "
          "and an unexplained observation hidden inside an agreed document, an "
          "unnameable adapter and driver, a missing raw identity, typed totals, "
          "a foreign provenance, and two positive controls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
