#!/usr/bin/env python3
"""Layer 3 parity fixtures (P-022 #259) — the normalized verdict list.

Each golden `tests/fixtures/verdicts/<case>.verdicts.json` pins what the OwnIR
bridge CONCLUDES for one facts document: the complete `check_facts()` finding
list in the bridge's own order (`ownlang/verdicts.py`, every `Finding` member),
or the `OwnIRError` text when the bridge refuses the document. This is the
outer contract of spec/Bridge.md §6 (layer 3), the seam #259 checkpoints 4
and 5 are measured at: the Rust `own-bridge` replays the same facts through
`own_bridge::check_facts` with zero Python and must agree — on identity,
anchor, kind and tiering at checkpoint 4; on messages and evidence too at
checkpoint 5. The golden always carries every member; a replay declares what
it compares.

Three case sources, one golden tree:

* **The swept facts corpora** — every `<case>.facts.json` under
  `tests/fixtures/ownir`, `tests/fixtures/lowered` and
  `tests/fixtures/summaries` is swept automatically (no per-case listing to
  forget), through the TOLERANT door (`json.load` + `check_facts`, the path
  `test_ownir.py` and every embedder take — never `load()`, which would turn
  `tolerant_unknown_kind` and the map-or-raise cases into load-time refusals
  and hide the door the bridge actually guards).
* **Synthetic verdict cases** — `tests/fixtures/verdicts/<case>.facts.json`,
  listed exhaustively in the manifest's `cases` ledger (name + the BR rules
  pinned), targeting verdict-mapping behavior the swept corpora do not reach:
  EFF001 and DI001-005 through real `services[]`/`effects[]` blocks, the DI004
  call-site and DI005 store-site anchors, duplicate-site last-wins, multi-file
  ordering, tiering and suppression, the OWN051 owned-local gate, the pooled
  view anchor, and the declared-boundary controls below.
* **The Rust exclusion ledger** — `rust_replay_excluded` names the cases whose
  golden is Python's truth but which the Rust core REFUSES by a declared
  boundary (a coordinate outside the core's `u32` line domain; a shape the
  typed Rust door rejects before the bridge runs — #294 OD-1). It named a
  third until #259 checkpoint 4b — a protocol-bearing document, refused while
  the OBL analysis had no port — and both such documents are now promoted.
  Each entry carries its reason
  and an executable expectation (`rust_refusal`: `bridge` or `door`, plus an
  error substring) that the Rust replay asserts, so an exclusion cannot rot
  into a coverage hole: the day Rust accepts one, its suite goes red demanding
  promotion. Python renders these like every other case — the ledger is a
  statement about the port, never about the reference.

* Python is authoritative: `python tests/test_verdict_fixtures.py --write`
  regenerates every golden. Regeneration is deterministic, and verify mode
  renders each case twice.
* The Rust side holds up its half in `rust/crates/own-bridge/tests/verdicts.rs`.

Run:  python tests/test_verdict_fixtures.py            (verify)
      python tests/test_verdict_fixtures.py --write    (regenerate)
      python tests/run_tests.py                        (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The ledger is interpreted ONCE, in tests/verdict_census.py (shared with the
# checkpoint status renderer): the plan, the exclusion ledger and the census
# come from there; this harness only projects facts and compares.
from verdict_census import (
    FIXDIR,
    GOLDEN_SUFFIX,
    CensusError,
    Plan,
    compute_verdict_census,
    goldens_on_disk,
    plan,
)

from ownlang.verdicts import VERDICTS_VERSION, render_verdicts


def _plan() -> Plan:
    p = plan()
    problems = list(p.problems)
    if p.verdicts_version != VERDICTS_VERSION:
        problems.append(
            f"manifest verdicts_version {p.verdicts_version!r} != "
            f"emitter VERDICTS_VERSION {VERDICTS_VERSION}")
    return Plan(p.cases, p.origin, p.excluded, p.verdicts_version, tuple(problems))


def _project(facts_path: str) -> str:
    with open(facts_path, encoding="utf-8") as f:
        facts = json.load(f)
    return render_verdicts(facts)


def run() -> int:
    p = _plan()
    fails = list(p.problems)
    if not p.cases and not fails:
        fails.append("no cases planned (no facts under the corpora / fixtures/verdicts)")
    for case, facts_path in sorted(p.cases.items()):
        golden_path = os.path.join(FIXDIR, f"{case}{GOLDEN_SUFFIX}")
        expected = _project(facts_path)
        # determinism: the same facts must render byte-identically on re-run.
        if _project(facts_path) != expected:
            fails.append(f"{case}: projection is non-deterministic")
            continue
        if not os.path.exists(golden_path):
            fails.append(f"{case}: golden missing; regenerate with "
                         f"'python tests/test_verdict_fixtures.py --write'")
            continue
        with open(golden_path, encoding="utf-8") as f:
            actual = f.read()
        if actual != expected:
            fails.append(f"{case}: golden is stale (a verdict, an anchor or the "
                         f"projection changed); regenerate with "
                         f"'python tests/test_verdict_fixtures.py --write' and "
                         f"re-run the Rust side (cd rust && cargo test)")
            continue
    for orphan in sorted(goldens_on_disk() - set(p.cases)):
        fails.append(f"{orphan}: orphaned golden (not a planned case); remove "
                     f"it or restore the case (manifest/facts)")
    if not fails:
        # Every golden above is byte-equal to its projection, so the census
        # over the committed goldens is the census over Python's truth.
        try:
            census = compute_verdict_census(p)
        except CensusError as e:
            fails.extend(e.problems)
    if fails:
        for f_ in fails:
            print(f"FAIL: verdict fixture {f_}")
        return 1
    print(f"verdicts (Layer 3) fixtures OK: {census.goldens} cases "
          f"({census.python_refusals} refusals, {census.python_findings} findings; "
          f"{census.excluded} declared Rust exclusions, {census.replayed} replayed by Rust) "
          f"verified in sync")
    return 0


def write() -> int:
    """Regenerate goldens for every planned case. Regeneration never accepts
    a shrunken or inconsistent ledger (same rule as the Layer 2 family)."""
    p = _plan()
    if p.problems:
        for problem in p.problems:
            print(f"ERROR: {problem}")
        return 1
    for case, facts_path in sorted(p.cases.items()):
        out = os.path.join(FIXDIR, f"{case}{GOLDEN_SUFFIX}")
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(facts_path))
        print(f"wrote {out}")
    for orphan in sorted(goldens_on_disk() - set(p.cases)):
        path = os.path.join(FIXDIR, f"{orphan}{GOLDEN_SUFFIX}")
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
