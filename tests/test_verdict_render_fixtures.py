#!/usr/bin/env python3
"""BR-V9 fixtures (P-022 #259 checkpoint 5.3) — the bridge's rendered surfaces.

Each golden `tests/fixtures/verdict_renders/<case>.renders.json` pins what a
consumer SEES for one facts document: `ownir.render_finding` in the human,
GitHub-annotation and MSBuild formats (plus one format it does not know, so the
fallback is rendered rather than assumed), each at both host severities, and
`ownir.build_sarif` as the one SARIF 2.1.0 log per run, also at both. The
emitter is `ownlang/renders.py`, an observer that calls the production
renderers and records what they returned.

This is the surface checkpoint 4 carried as "deferred" and checkpoint 5.0's
inventory reported as having no fixture family at all. The Rust `own-bridge`
replays every case with zero Python and must reproduce the bytes
(`rust/crates/own-bridge/tests/renders.rs`).

Cases are listed, never swept: one exists to exercise a BR-V9 rule, so the
manifest names the ledger rows each one pins and the surface inventory reports
a row nobody pins. Rendering the whole verdict corpus at two severities would
freeze megabytes to prove less.

Beyond the goldens, two properties are asserted here because they are claims
about the surface rather than about one case:

* **determinism** — every case renders byte-identically twice;
* **no `subject` leaks** — `ownir.Finding` carries no diagnostic `subject`, so
  no rendered surface can serialize one. The checkpoint-4 note promised to
  re-check that once the bridge grew render and SARIF paths; this checks the
  rendered BYTES rather than restating the promise.

* Python is authoritative: `python tests/test_verdict_render_fixtures.py --write`
  regenerates every golden.

Run:  python tests/test_verdict_render_fixtures.py            (verify)
      python tests/test_verdict_render_fixtures.py --write    (regenerate)
      python tests/run_tests.py                               (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from verdict_render_census import Plan, goldens_on_disk, plan

from ownlang.renders import RENDERS_VERSION, render_renders

# Every `own_diagnostics` subject would look like this if one ever reached a
# rendered surface: the bridge's own `subject`-free `Finding` is what makes it
# impossible, and this is the string that would give it away.
SUBJECT_MARKERS = ('"subject"', "'subject'")


def _plan() -> Plan:
    p = plan()
    problems = list(p.problems)
    if p.renders_version != RENDERS_VERSION:
        problems.append(f"manifest renders_version {p.renders_version!r} != "
                        f"emitter RENDERS_VERSION {RENDERS_VERSION}")
    return Plan(p.cases, p.renders_version, tuple(problems))


def _project(facts_path: str) -> str:
    with open(facts_path, encoding="utf-8") as f:
        facts = json.load(f)
    return render_renders(facts)


def run() -> int:
    p = _plan()
    fails = list(p.problems)
    if not p.cases and not fails:
        fails.append("no cases planned (an empty ledger proves nothing)")
    for case in sorted(p.cases):
        rendered = _project(p.facts_path(case))
        if _project(p.facts_path(case)) != rendered:
            fails.append(f"{case}: projection is non-deterministic")
            continue
        for marker in SUBJECT_MARKERS:
            if marker in rendered:
                fails.append(f"{case}: a rendered surface carries {marker} — the bridge's "
                             f"Finding has no diagnostic subject and no output may invent "
                             f"one (the checkpoint-4 subject tail, re-checked here)")
        golden = p.golden_path(case)
        if not os.path.exists(golden):
            fails.append(f"{case}: golden missing; regenerate with "
                         f"'python tests/test_verdict_render_fixtures.py --write'")
            continue
        with open(golden, encoding="utf-8") as f:
            actual = f.read()
        if actual != rendered:
            fails.append(f"{case}: golden is stale (a rendering changed); regenerate with "
                         f"'python tests/test_verdict_render_fixtures.py --write' and "
                         f"re-run the Rust side (cd rust && cargo test)")
    for orphan in sorted(goldens_on_disk() - set(p.cases)):
        fails.append(f"{orphan}: orphaned golden (not a planned case); remove it or "
                     f"restore the case (manifest/facts)")
    if fails:
        for f_ in fails:
            print(f"FAIL: verdict render fixture {f_}")
        return 1
    print(f"verdict renders (BR-V9) fixtures OK: {len(p.cases)} cases verified in sync")
    return 0


def write() -> int:
    """Regenerate every planned case. Regeneration never accepts a shrunken or
    inconsistent ledger (the same rule the other fixture families hold)."""
    p = _plan()
    if p.problems:
        for problem in p.problems:
            print(f"ERROR: {problem}")
        return 1
    for case in sorted(p.cases):
        out = p.golden_path(case)
        with open(out, "w", encoding="utf-8") as f:
            f.write(_project(p.facts_path(case)))
        print(f"wrote {out}")
    for orphan in sorted(goldens_on_disk() - set(p.cases)):
        path = p.golden_path(orphan)
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
