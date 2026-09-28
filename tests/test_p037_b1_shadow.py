"""P-037 B1: the shadow driver's refusals (G14) and the A14 side-report
schema (G15), docs/notes/p037-phase-b1-shadow.md §C. No dotnet needed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import p037_b1_shadow as b1

GOOD = {"schema": "p037-dispatch-side-report/1", "measurement_only": True,
        "observed_targets_are_exhaustive": False,
        "calls": [{"caller": "U.Go", "site": {"line": 3, "column": 5}, "callee": "B.Shut",
                   "dispatch": "open", "observed_targets": ["A.Shut", "B.Shut"]},
                  {"caller": "U.Go", "site": {"line": 4, "column": 5}, "callee": "U.H",
                   "dispatch": "exact", "observed_targets": []}]}


def _with(**edit: object) -> dict[str, object]:
    doc: dict[str, object] = {**GOOD, "calls": [dict(c) for c in GOOD["calls"]]}  # type: ignore[attr-defined]
    for k, v in edit.items():
        if k.startswith("call_"):
            doc["calls"][0][k[5:]] = v  # type: ignore[index]
        else:
            doc[k] = v
    return doc


def run() -> int:
    fails = 0

    def check(label: str, ok: bool) -> None:
        nonlocal fails
        print(f"{'ok ' if ok else 'MISS'} {label}")
        fails += not ok

    check("G15' a measurement-only side report validates", not b1.validate_side_report(GOOD))
    check("G15 an open call marked safe is rejected",
          bool(b1.validate_side_report(_with(call_safe=True))))
    check("G15 a side report carrying a summary class is rejected",
          bool(b1.validate_side_report(_with(call_class="EQUAL"))))
    check("G15 an open call relabelled as a third dispatch value is rejected",
          bool(b1.validate_side_report(_with(call_dispatch="closed"))))
    check("G15 observed targets claimed exhaustive are rejected",
          bool(b1.validate_side_report(_with(observed_targets_are_exhaustive=True))))
    try:
        b1.frozen("HEAD")
        check("G14 a run over a drifted population is refused", False)
    except b1.Refused:
        check("G14 a run over a drifted population is refused", True)
    check("G14' the frozen population commit is accepted",
          b1.frozen(b1.POPULATION_COMMIT).startswith(b1.POPULATION_COMMIT))
    print(f"p037 b1 shadow driver: {'PASS' if not fails else 'FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
