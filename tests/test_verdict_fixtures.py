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
  boundary (a protocol-bearing document: the OBL analysis is not wired; a
  coordinate outside the core's `u32` line domain; a shape the typed Rust door
  rejects before the bridge runs — #294 OD-1). Each entry carries its reason
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

from ownlang.verdicts import VERDICTS_VERSION, render_verdicts

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "verdicts")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
# The swept corpora, in a fixed order (a name collision across them is a
# ledger problem, not a silent shadowing).
CORPORA = (
    ("ownir", os.path.join(os.path.dirname(__file__), "fixtures", "ownir")),
    ("lowered", os.path.join(os.path.dirname(__file__), "fixtures", "lowered")),
    ("summaries", os.path.join(os.path.dirname(__file__), "fixtures", "summaries")),
)
_REFUSALS = ("bridge", "door")


def _manifest() -> tuple[list[str], dict[str, dict[str, object]], list[str]]:
    """(synthetic case names sorted, rust_replay_excluded name->entry, problems)."""
    problems: list[str] = []
    if not os.path.exists(MANIFEST):
        return [], {}, [f"manifest missing: {MANIFEST}"]
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("verdicts_version") != VERDICTS_VERSION:
        problems.append(
            f"manifest verdicts_version {data.get('verdicts_version')!r} != "
            f"emitter VERDICTS_VERSION {VERDICTS_VERSION}")
    excluded: dict[str, dict[str, object]] = {}
    for e in data.get("rust_replay_excluded", []):
        name, reason, refusal = e.get("name"), e.get("reason"), e.get("rust_refusal")
        if not (isinstance(name, str) and name
                and isinstance(reason, str) and reason):
            problems.append(f"rust_replay_excluded entry needs a non-empty name "
                            f"and reason: {e!r}")
            continue
        if refusal not in _REFUSALS:
            problems.append(f"rust_replay_excluded '{name}': rust_refusal must be "
                            f"one of {_REFUSALS}, got {refusal!r}")
        contains = e.get("rust_error_contains")
        if contains is not None and not (isinstance(contains, str) and contains):
            problems.append(f"rust_replay_excluded '{name}': rust_error_contains "
                            f"must be a non-empty string when present")
        if name in excluded:
            problems.append(f"rust_replay_excluded lists '{name}' twice")
        excluded[name] = e
    names: list[str] = []
    for c in data.get("cases", []):
        name = c.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"manifest case without a name: {c!r}")
            continue
        rules = c.get("rules")
        if not (isinstance(rules, list) and rules
                and all(isinstance(r, str) and r for r in rules)):
            problems.append(f"manifest case '{name}': 'rules' must be a "
                            f"non-empty array of non-empty strings")
        names.append(name)
    if len(set(names)) != len(names):
        problems.append("manifest contains duplicate case names")
    return sorted(names), excluded, problems


def _disk_cases(directory: str, suffix: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(n[:-len(suffix)] for n in os.listdir(directory)
                  if n.endswith(suffix))


def _plan() -> tuple[dict[str, str], dict[str, dict[str, object]], list[str]]:
    """The full case plan: name -> facts path, the exclusion ledger, and the
    ledger problems. The corpora are swept automatically; the synthetic cases
    must match the manifest exactly; names must be unique across all sources
    (one golden tree serves them all); every exclusion must name a planned case."""
    synthetic, excluded, problems = _manifest()
    plan: dict[str, str] = {}
    origin: dict[str, str] = {}
    for label, directory in CORPORA:
        for name in _disk_cases(directory, ".facts.json"):
            if name in plan:
                problems.append(f"case name '{name}' exists in BOTH the "
                                f"{origin[name]} and {label} corpora — names must "
                                f"be unique across the swept corpora")
                continue
            plan[name] = os.path.join(directory, f"{name}.facts.json")
            origin[name] = label
    local = _disk_cases(FIXDIR, ".facts.json")
    for missing in sorted(set(synthetic) - set(local)):
        problems.append(f"manifest case '{missing}' has no facts file "
                        f"({missing}.facts.json) under fixtures/verdicts")
    for unlisted in sorted(set(local) - set(synthetic)):
        problems.append(f"'{unlisted}.facts.json' is not in manifest.json — "
                        f"add the case to the ledger (name, rules)")
    for name in synthetic:
        if name in plan:
            problems.append(f"synthetic case '{name}' shadows a swept corpus "
                            f"case name ({origin[name]})")
        else:
            plan[name] = os.path.join(FIXDIR, f"{name}.facts.json")
    for phantom in sorted(set(excluded) - set(plan)):
        problems.append(f"rust_replay_excluded names '{phantom}', which is not a "
                        f"planned case")
    return plan, excluded, problems


def _goldens() -> set[str]:
    if not os.path.isdir(FIXDIR):
        return set()
    return {n[:-len(".verdicts.json")] for n in os.listdir(FIXDIR)
            if n.endswith(".verdicts.json")}


def _project(facts_path: str) -> str:
    with open(facts_path, encoding="utf-8") as f:
        facts = json.load(f)
    return render_verdicts(facts)


def run() -> int:
    plan, excluded, fails = _plan()
    if not plan and not fails:
        fails.append("no cases planned (no facts under the corpora / fixtures/verdicts)")
    n_refused = 0
    n_findings = 0
    for case, facts_path in sorted(plan.items()):
        golden_path = os.path.join(FIXDIR, f"{case}.verdicts.json")
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
        doc = json.loads(expected)
        if doc.get("error") is not None:
            n_refused += 1
        else:
            n_findings += len(doc["findings"])
    for orphan in sorted(_goldens() - set(plan)):
        fails.append(f"{orphan}: orphaned golden (not a planned case); remove "
                     f"it or restore the case (manifest/facts)")
    if fails:
        for f_ in fails:
            print(f"FAIL: verdict fixture {f_}")
        return 1
    print(f"verdicts (Layer 3) fixtures OK: {len(plan)} cases ({n_refused} refusals, "
          f"{n_findings} findings; {len(excluded)} declared Rust exclusions) "
          f"verified in sync")
    return 0


def write() -> int:
    """Regenerate goldens for every planned case. Regeneration never accepts
    a shrunken or inconsistent ledger (same rule as the Layer 2 family)."""
    plan, _excluded, problems = _plan()
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        return 1
    for case, facts_path in sorted(plan.items()):
        out = os.path.join(FIXDIR, f"{case}.verdicts.json")
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(facts_path))
        print(f"wrote {out}")
    for orphan in sorted(_goldens() - set(plan)):
        path = os.path.join(FIXDIR, f"{orphan}.verdicts.json")
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
