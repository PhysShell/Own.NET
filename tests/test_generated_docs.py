#!/usr/bin/env python3
"""Gate the generated status surfaces and the mutation-campaign evidence.

Three things go stale silently and were doing so before this existed:

1. **A generated document drifts from its evidence.** `docs/generated/` is
   rendered by `scripts/render_checkpoint_status.py` out of committed
   artifacts; if a fixture changes and nobody re-renders, the document keeps
   asserting the old count. P-022's status block already carries a rule about
   hand-typed numbers drifting twice — this makes the rule executable.
2. **A campaign definition stops applying.** A mutation is an exact text edit
   to a production file; when that code moves, the edit silently matches
   nothing (or matches twice) and the recorded result describes a tree that no
   longer exists. `--check` re-anchors every edit without running anything.
3. **A recorded campaign result contradicts itself.** The result is written by
   a script but committed as a file, so it is editable; the totals are
   re-derived from the rows here, and the harness-honesty control is required
   to be present and clean. A campaign whose control was dirty measured a
   pre-existing red build, and every row in it is worthless.

Deliberately NOT gated: re-running the campaign. Mutating the tree and running
every layer takes minutes and cannot be a per-commit gate — so what is gated
is that the definition still applies and the recorded result is coherent, and
the note says the run is recorded rather than reproduced.

Run:  python tests/test_generated_docs.py
      python tests/run_tests.py           (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# One campaign per checkpoint: each stays frozen at what it measured, so a
# later checkpoint cannot quietly restate an earlier one's numbers. Adding a
# checkpoint means adding its pair here — a directory nobody listed is a
# directory nobody gates.
_DATA = ("p022-shadow-infra-checkpoint1-data", "p022-shadow-infra-checkpoint2-data")
CAMPAIGNS = tuple(os.path.join(ROOT, "docs", "notes", d, "mutations.json")
                  for d in _DATA)
RESULTS = tuple(os.path.join(ROOT, "docs", "notes", d, "campaign.json")
                for d in _DATA)


def _check_generated() -> list[str]:
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts",
                                      "render_checkpoint_status.py"), "--check"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    if proc.returncode == 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _check_campaign_definitions() -> list[str]:
    # Imported here, not at module scope: sys.path is extended above.
    from mutate_campaign import check_definition

    problems: list[str] = []
    for path in CAMPAIGNS:
        if not os.path.exists(path):
            problems.append(f"campaign definition missing: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            campaign = json.load(f)
        problems += [f"{os.path.basename(path)}: {p}"
                     for p in check_definition(campaign)]
    return problems


def _check_campaign_results() -> list[str]:
    problems: list[str] = []
    for path in RESULTS:
        name = os.path.basename(path)
        if not os.path.exists(path):
            problems.append(f"campaign result missing: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
        rows = result.get("mutations", [])
        if not rows:
            problems.append(f"{name}: no mutation rows")
            continue
        counted = {
            "mutations": sum(1 for r in rows
                             if not r["status"].startswith("control_")),
            "caught": sum(1 for r in rows if r["status"] == "caught"),
            "survived": sum(1 for r in rows if r["status"] == "survived"),
            "compile_errors": sum(1 for r in rows if r["status"] == "compile_error"),
            "control_clean": sum(1 for r in rows if r["status"] == "control_clean"),
        }
        if result.get("totals") != counted:
            problems.append(f"{name}: totals {result.get('totals')} do not match the "
                            f"rows {counted} — the result was edited by hand")
        if counted["control_clean"] != 1:
            problems.append(
                f"{name}: needs exactly one CLEAN harness-honesty control; a dirty "
                f"control means the campaign measured a pre-existing red build and "
                f"every row in it is worthless")
        for row in rows:
            if row["status"] == "caught" and not row["caught_by"]:
                problems.append(f"{name}: {row['id']} is 'caught' with no catcher")
            if row["status"] == "survived" and row["caught_by"]:
                problems.append(f"{name}: {row['id']} is 'survived' with catchers")
            if row["status"] == "control_clean" and row["caught_by"]:
                problems.append(f"{name}: {row['id']} is a clean control with catchers")
        ids = [r["id"] for r in rows]
        if len(set(ids)) != len(ids):
            problems.append(f"{name}: duplicate mutation ids")
    return problems


def run() -> int:
    fails = _check_generated() + _check_campaign_definitions() + _check_campaign_results()
    if fails:
        for f_ in fails:
            print(f"FAIL[generated-docs]: {f_}")
        return 1
    print(f"generated docs + campaign evidence OK: "
          f"{len(CAMPAIGNS)} campaign definition(s) still anchored, "
          f"{len(RESULTS)} recorded result(s) internally consistent, "
          f"docs/generated in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
