#!/usr/bin/env python3
"""MOS summaries parity fixtures (P-022, roadmap stage 1) — the `summaries` dump.

Each golden `tests/fixtures/summaries/<case>.summaries.json` pins the EXACT
stdout bytes of `python -m ownlang summaries <facts>` (the document from
`ownlang.ownir.dump_summaries`, serialized `json.dumps(indent=2,
sort_keys=True)` + the trailing newline `print` appends). This is the parity
artifact spec/Inference.md §8 names: the Rust port of the inference layer is
diffed against it at the SUMMARY level — finer than diffing final diagnostics,
where an inference bug can hide behind an unrelated silence.

Two case sources, one golden tree:

* **The frozen facts corpus** — every `tests/fixtures/lowered/<case>.facts.json`
  is swept automatically (no per-case listing to forget), EXCEPT the names in
  the manifest's `excluded_lowered` ledger. An exclusion must both exist in the
  lowered corpus and still FAIL `load()` (the summaries door): the day the door
  starts accepting it, this suite goes red demanding promotion to a golden —
  an exclusion cannot silently rot into a coverage hole. Today the only entry
  is `tolerant_unknown_kind` (its facts carry an unknown resource kind, which
  Python rejects at `load()` while Rust rejects at `lower()` — the #294 door
  placement; the lowered family pins that rejection text byte-for-byte).
* **Synthetic MOS cases** — `tests/fixtures/summaries/<case>.facts.json`, listed
  exhaustively in the manifest's `cases` ledger (name + the INF rules pinned),
  targeting solver/dump behavior the lowered corpus does not reach: SCC cycles,
  return-forward chains and cycles, the extern-boundary log, overload-merge
  tie-breaks, the sig-key vocabulary, the `degraded` branch, sink channels,
  explicit effects, and non-ASCII escaping (the dump serializes with
  `ensure_ascii`, unlike the Layer 2 surface).

* Python is authoritative: `python tests/test_summaries_fixtures.py --write`
  regenerates every golden. Regeneration is deterministic, and verify mode
  re-dumps each case with `functions[]` REVERSED — INF-R1 (byte-identical
  under input permutation) is checked on every case, not on a sample.
* The Rust side holds up its half in
  `rust/crates/own-bridge/tests/summaries.rs`: `own_bridge::dump_summaries`
  must reproduce every golden byte-for-byte from the same facts, without
  Python present (the zero-Python steady state).

Run:  python tests/test_summaries_fixtures.py            (verify)
      python tests/test_summaries_fixtures.py --write    (regenerate)
      python tests/run_tests.py                          (runs it in the suite)
"""

from __future__ import annotations

import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownir import OWNIR_VERSION, OwnIRError, dump_summaries, load

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "summaries")
LOWDIR = os.path.join(os.path.dirname(__file__), "fixtures", "lowered")
MANIFEST = os.path.join(FIXDIR, "manifest.json")


def _render(facts: dict) -> str:
    """The golden bytes: exactly what `python -m ownlang summaries` prints —
    `json.dumps(dump_summaries(facts), indent=2, sort_keys=True)` plus the
    newline `print` appends. `sort_keys` (with the default `ensure_ascii`)
    is the CLI's frozen output contract — NOT the Layer 2 family's
    `ensure_ascii=False` convention — so non-ASCII pins as `\\uXXXX`."""
    return json.dumps(dump_summaries(facts), indent=2, sort_keys=True) + "\n"


def _manifest() -> tuple[list[str], dict[str, str], list[str]]:
    """(synthetic case names sorted, excluded_lowered name->reason, problems)."""
    problems: list[str] = []
    if not os.path.exists(MANIFEST):
        return [], {}, [f"manifest missing: {MANIFEST}"]
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("ownir_version") != OWNIR_VERSION:
        problems.append(
            f"manifest ownir_version {data.get('ownir_version')!r} != "
            f"OWNIR_VERSION {OWNIR_VERSION}")
    excluded: dict[str, str] = {}
    for e in data.get("excluded_lowered", []):
        name, reason = e.get("name"), e.get("reason")
        if not (isinstance(name, str) and name
                and isinstance(reason, str) and reason):
            problems.append(f"excluded_lowered entry needs a non-empty name "
                            f"and reason: {e!r}")
            continue
        if name in excluded:
            problems.append(f"excluded_lowered lists '{name}' twice")
        excluded[name] = reason
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


def _plan() -> tuple[dict[str, str], list[str]]:
    """The full case plan: name -> facts path, plus ledger problems. The
    lowered corpus is swept automatically (minus the audited exclusions); the
    synthetic cases must match the manifest ledger exactly; the two name
    spaces must not collide (one golden tree serves both)."""
    synthetic, excluded, problems = _manifest()
    lowered = _disk_cases(LOWDIR, ".facts.json")
    local = _disk_cases(FIXDIR, ".facts.json")
    for phantom in sorted(set(excluded) - set(lowered)):
        problems.append(f"excluded_lowered names '{phantom}', which has no "
                        f"facts file in the lowered corpus")
    for name in sorted(excluded):
        if name not in lowered:
            continue
        try:
            load(os.path.join(LOWDIR, f"{name}.facts.json"))
        except OwnIRError:
            pass  # still rejected at the door — the exclusion holds
        else:
            problems.append(
                f"'{name}' is excluded_lowered but load() now ACCEPTS its "
                f"facts — the exclusion has rotted; promote the case to a "
                f"golden (remove the exclusion and --write)")
    for missing in sorted(set(synthetic) - set(local)):
        problems.append(f"manifest case '{missing}' has no facts file "
                        f"({missing}.facts.json) under fixtures/summaries")
    for unlisted in sorted(set(local) - set(synthetic)):
        problems.append(f"'{unlisted}.facts.json' is not in manifest.json — "
                        f"add the case to the ledger (name, rules)")
    plan: dict[str, str] = {}
    for name in lowered:
        if name not in excluded:
            plan[name] = os.path.join(LOWDIR, f"{name}.facts.json")
    for name in synthetic:
        if name in plan:
            problems.append(f"case name '{name}' exists in BOTH the lowered "
                            f"corpus and fixtures/summaries — one golden tree "
                            f"serves both, so names must be unique")
        elif name in _disk_cases(LOWDIR, ".facts.json"):
            problems.append(f"synthetic case '{name}' shadows a lowered "
                            f"corpus case name")
        else:
            plan[name] = os.path.join(FIXDIR, f"{name}.facts.json")
    return plan, problems


def _goldens() -> set[str]:
    if not os.path.isdir(FIXDIR):
        return set()
    return {n[:-len(".summaries.json")] for n in os.listdir(FIXDIR)
            if n.endswith(".summaries.json")}


def _project(facts_path: str) -> tuple[str, str]:
    """(golden bytes, permuted-input bytes) — the second dump runs with
    `functions[]` reversed, so INF-R1 (byte-identical under input
    permutation) is enforced per case, not per sample."""
    facts = load(facts_path)
    expected = _render(facts)
    permuted = copy.deepcopy(facts)
    fns = permuted.get("functions")
    if isinstance(fns, list):
        fns.reverse()
    return expected, _render(permuted)


def run() -> int:
    plan, fails = _plan()
    if not plan and not fails:
        fails.append(f"no cases planned (no facts under {LOWDIR} / {FIXDIR})")
    for case, facts_path in sorted(plan.items()):
        golden_path = os.path.join(FIXDIR, f"{case}.summaries.json")
        try:
            expected, permuted = _project(facts_path)
        except OwnIRError as e:
            fails.append(f"{case}: load() rejected its facts ({e}) — a "
                         f"rejected case must be in excluded_lowered, not "
                         f"silently skipped")
            continue
        if permuted != expected:
            fails.append(f"{case}: dump is not byte-identical under "
                         f"functions[] permutation (INF-R1)")
            continue
        if not os.path.exists(golden_path):
            fails.append(f"{case}: golden missing; regenerate with "
                         f"'python tests/test_summaries_fixtures.py --write'")
            continue
        with open(golden_path, encoding="utf-8") as f:
            actual = f.read()
        if actual != expected:
            fails.append(f"{case}: golden is stale (the solver or the dump "
                         f"changed); regenerate with "
                         f"'python tests/test_summaries_fixtures.py --write'")
    for orphan in sorted(_goldens() - set(plan)):
        fails.append(f"{orphan}: orphaned golden (not a planned case); remove "
                     f"it or restore the case (manifest/facts)")
    if fails:
        for f_ in fails:
            print(f"FAIL: summaries fixture {f_}")
        return 1
    n_degraded = 0
    for facts_path in plan.values():
        if json.loads(_project(facts_path)[0]).get("degraded") is not None:
            n_degraded += 1
    print(f"summaries (MOS parity) fixtures OK: {len(plan)} cases "
          f"({n_degraded} degraded, {len(plan) - n_degraded} solved) "
          f"verified in sync")
    return 0


def write() -> int:
    """Regenerate goldens for every planned case. Regeneration never accepts
    a shrunken or inconsistent ledger (same rule as the lowered family)."""
    plan, problems = _plan()
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        return 1
    for case, facts_path in sorted(plan.items()):
        out = os.path.join(FIXDIR, f"{case}.summaries.json")
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(facts_path)[0])
        print(f"wrote {out}")
    for orphan in sorted(_goldens() - set(plan)):
        path = os.path.join(FIXDIR, f"{orphan}.summaries.json")
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
