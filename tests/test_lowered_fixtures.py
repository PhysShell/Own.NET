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
* `manifest.json` is the FROZEN case ledger: verify mode requires
  manifest == facts == goldens exactly, so a MISSING golden, a STALE golden
  (byte mismatch), an ORPHANED golden, a deleted facts+golden PAIR, or an
  unlisted facts file are each a red build — the fixture family cannot
  silently rot (or shrink) in any direction. `--write` refuses to regenerate
  a shrunken contract for the same reason.
* The Rust side holds up its half of the contract (#300/#301): `own-lowered`
  parses and re-emits every shared golden byte-exactly through its typed
  model, and `own-bridge` CONSTRUCTS the same documents from each
  `rust_replay: true` case's `<case>.facts.json`, reproducing the golden
  byte-for-byte (`rust/crates/own-bridge/tests/replay.rs`). A
  `rust_replay: false` case is a Python-only behavior snapshot pinning an
  open decision (its `decision` field names it, e.g. OD-2/#294) and imposes
  nothing on Rust until that decision lands. Python stays authoritative at
  generation time (`--write`); the goldens are frozen inputs the Rust suites
  verify without Python present (the zero-Python steady state).

Run:  python tests/test_lowered_fixtures.py            (verify)
      python tests/test_lowered_fixtures.py --write    (regenerate)
      python tests/run_tests.py                        (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.lowered import LOWERED_VERSION, render_lowered

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "lowered")
MANIFEST = os.path.join(FIXDIR, "manifest.json")


def _manifest() -> tuple[list[str], list[str]]:
    """(manifest case names sorted, manifest problems). The manifest is the
    FROZEN case ledger: the harness requires manifest == facts == goldens
    exactly, so deleting a facts+golden PAIR (which the per-file checks alone
    cannot see) is a red build, not a quietly shrunken contract."""
    problems: list[str] = []
    if not os.path.exists(MANIFEST):
        return [], [f"manifest missing: {MANIFEST}"]
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("lowered_version") != LOWERED_VERSION:
        problems.append(
            f"manifest lowered_version {data.get('lowered_version')!r} != "
            f"emitter LOWERED_VERSION {LOWERED_VERSION}")
    names: list[str] = []
    for c in data.get("cases", []):
        name = c.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"manifest case without a name: {c!r}")
            continue
        if not isinstance(c.get("rust_replay"), bool):
            problems.append(f"manifest case '{name}': rust_replay must be a bool")
        rules = c.get("rules")
        if not (isinstance(rules, list) and rules
                and all(isinstance(r, str) and r for r in rules)):
            problems.append(f"manifest case '{name}': 'rules' must be a "
                            f"non-empty array of non-empty strings")
        if c.get("rust_replay") is False and not c.get("decision"):
            problems.append(f"manifest case '{name}': a Python-only case must "
                            f"name the open decision it pins ('decision')")
        names.append(name)
    if len(set(names)) != len(names):
        problems.append("manifest contains duplicate case names")
    return sorted(names), problems


def _facts_cases() -> list[str]:
    """Case names present on disk, sorted — one per `<case>.facts.json`."""
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
    manifest_cases, fails = _manifest()
    facts_cases = _facts_cases()
    for missing in sorted(set(manifest_cases) - set(facts_cases)):
        fails.append(f"{missing}: in the manifest but its facts file is gone — "
                     f"removing a case is a contract change; edit "
                     f"manifest.json deliberately")
    for unlisted in sorted(set(facts_cases) - set(manifest_cases)):
        fails.append(f"{unlisted}: facts file not in manifest.json — add the "
                     f"case to the ledger (name, rules, rust_replay)")
    cases = sorted(set(manifest_cases) & set(facts_cases))
    if not cases and not fails:
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
    for orphan in sorted(_goldens() - set(manifest_cases)):
        fails.append(f"{orphan}: orphaned golden (not in the manifest); remove "
                     f"it or restore the case in manifest.json + facts")
    if fails:
        for f_ in fails:
            print(f"FAIL: lowered fixture {f_}")
        return 1
    n_err = sum(1 for c in cases
                if json.loads(_project(c)).get("error") is not None)
    print(f"lowered (Layer 2) fixtures OK: {len(cases)} cases "
          f"({n_err} rejections, {len(cases) - n_err} lowerings) verified in sync")
    return 0


def write() -> int:
    """Regenerate goldens for every MANIFEST case. Regeneration never accepts a
    shrunken contract: a manifest case whose facts file is missing (or a facts
    file missing from the manifest) is an error, not a skip."""
    manifest_cases, problems = _manifest()
    facts_cases = _facts_cases()
    for missing in sorted(set(manifest_cases) - set(facts_cases)):
        problems.append(f"cannot regenerate '{missing}': facts file missing "
                        f"for a manifest case")
    for unlisted in sorted(set(facts_cases) - set(manifest_cases)):
        problems.append(f"cannot regenerate: '{unlisted}.facts.json' is not "
                        f"in manifest.json")
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        return 1
    for case in manifest_cases:
        out = os.path.join(FIXDIR, f"{case}.golden.json")
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(case))
        print(f"wrote {out}")
    for orphan in sorted(_goldens() - set(manifest_cases)):
        path = os.path.join(FIXDIR, f"{orphan}.golden.json")
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
