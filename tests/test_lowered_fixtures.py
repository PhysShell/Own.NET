#!/usr/bin/env python3
"""Layer 2 parity fixtures (P-022 #259) — the normalized lowered representation.

Each `tests/fixtures/lowered/<case>.facts.json` is a MINIMAL OwnIR facts
document pinning one lowering family from `spec/BridgeBehaviorMatrix.md`
(routing R1-R6, handle counters, hoisting and its negative gates, kill-on-
rebind, untrack/kill-sites, call shapes, alias_join, fail-loud vocabulary, ...).
Its committed sibling `<case>.golden.json` is the canonical Layer 2 projection
(`ownlang/lowered.py`) of what `to_module()` lowered — the seam where a wrong
lowering is visible BEFORE any analysis runs (spec/Bridge.md §6, layer 2).

* Python is authoritative: `python tests/test_lowered_fixtures.py --write`
  regenerates every golden from its facts file (and removes a golden whose
  facts file is gone, with a notice). Regeneration is deterministic.
* Verify mode (`run()`, part of `python tests/run_tests.py`) fails on a
  MISSING golden, a STALE golden (byte mismatch), or an ORPHANED golden — a
  fixture family cannot silently rot in any direction.
* The Rust `own-bridge` (#259) will replay the same `<case>.facts.json`
  inputs and must reproduce each golden byte-for-byte; until it exists this
  suite is the Python-side half of that contract (zero-Python steady state:
  once the Rust emitter lands and is authoritative, these goldens are frozen
  inputs it replays without Python present).

Run:  python tests/test_lowered_fixtures.py            (verify)
      python tests/test_lowered_fixtures.py --write    (regenerate)
      python tests/run_tests.py                        (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.lowered import render_lowered

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "lowered")


def _cases() -> list[str]:
    """Case names, sorted — one per `<case>.facts.json`."""
    if not os.path.isdir(FIXDIR):
        return []
    return sorted(n[:-len(".facts.json")] for n in os.listdir(FIXDIR)
                  if n.endswith(".facts.json"))


def _goldens() -> set[str]:
    if not os.path.isdir(FIXDIR):
        return set()
    return {n[:-len(".golden.json")] for n in os.listdir(FIXDIR)
            if n.endswith(".golden.json")}


def _project(case: str) -> str:
    with open(os.path.join(FIXDIR, f"{case}.facts.json"), encoding="utf-8") as f:
        facts = json.load(f)
    return render_lowered(facts)


def run() -> int:
    cases = _cases()
    fails: list[str] = []
    if not cases:
        fails.append(f"no *.facts.json under {FIXDIR}")
    for case in cases:
        golden_path = os.path.join(FIXDIR, f"{case}.golden.json")
        expected = _project(case)
        # determinism: the same facts must render byte-identically on re-run.
        if _project(case) != expected:
            fails.append(f"{case}: projection is non-deterministic")
            continue
        if not os.path.exists(golden_path):
            fails.append(f"{case}: golden missing; regenerate with "
                         f"'python tests/test_lowered_fixtures.py --write'")
            continue
        with open(golden_path, encoding="utf-8") as f:
            actual = f.read()
        if actual != expected:
            fails.append(f"{case}: golden is stale (the lowering or the "
                         f"projection changed); regenerate with "
                         f"'python tests/test_lowered_fixtures.py --write'")
    for orphan in sorted(_goldens() - set(cases)):
        fails.append(f"{orphan}: orphaned golden (no facts file); remove it or "
                     f"restore {orphan}.facts.json")
    if fails:
        for f_ in fails:
            print(f"FAIL: lowered fixture {f_}")
        return 1
    n_err = sum(1 for c in cases
                if json.loads(_project(c)).get("error") is not None)
    print(f"lowered (Layer 2) fixtures OK: {len(cases)} cases "
          f"({n_err} rejections, {len(cases) - n_err} lowerings) verified in sync")
    return 0


def write() -> None:
    os.makedirs(FIXDIR, exist_ok=True)
    for case in _cases():
        out = os.path.join(FIXDIR, f"{case}.golden.json")
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(case))
        print(f"wrote {out}")
    for orphan in sorted(_goldens() - set(_cases())):
        path = os.path.join(FIXDIR, f"{orphan}.golden.json")
        os.remove(path)
        print(f"removed orphaned {path}")


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        write()
        raise SystemExit(0)
    raise SystemExit(run())
