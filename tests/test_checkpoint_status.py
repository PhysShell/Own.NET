#!/usr/bin/env python3
"""Gate: the generated checkpoint status fragments equal their projection, and
every recorded mutation campaign can still be replayed.

`docs/generated/p022-cp4-*.md`, `docs/generated/p022-cp5-*.md` and
`docs/generated/p022-shadow-*.md` are rendered from the evidence in the tree by
`scripts/render_checkpoint_status.py` (the verdict ledger census through
`tests/verdict_census.py`; the cp5 surface inventory through
`tests/verdict_surface_inventory.py`; the step-7a
census through `tests/shadow_census.py`; every recorded mutation campaign
through `scripts/mutate_campaign.py`). This module runs its `--check`
in-process, so a change to the evidence without regenerating the fragments — or
a campaign result that no longer matches its definition, was taken on a dirty
tree, missed a required catcher, or names a commit this tree does not descend
from — turns the existing Python gate red on every interpreter the suite runs
on. Regenerate with `python scripts/render_checkpoint_status.py`.

The second gate is deliberately separate from the first. A fragment's content
never depends on HEAD (that is what makes a recorded run stay valid across an
unrelated refactor), but a campaign *definition* is replay instructions, and
those rot: a mutation is an exact rewrite of a production file, so when that
code moves the pattern silently matches nothing and the definition describes a
tree that no longer exists. `--validate` re-anchors every mutation against the
current tree without running anything; it caught two rotted anchors when an
earlier checkpoint reshaped a surface a previous campaign had measured. A
failure here does not falsify the recorded evidence — it says the campaign can
no longer be re-run as written, and the definition needs re-anchoring.

Run:  python tests/test_checkpoint_status.py
      python tests/run_tests.py            (runs it in the suite)
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from mutate_campaign import CampaignError, load_definition, validate  # noqa: E402
from render_checkpoint_status import (  # noqa: E402
    CAMPAIGN,
    CENSUS_MD,
    CP5_CAMPAIGNS,
    CP5_MUTATIONS_MD,
    INVENTORY_MD,
    MUTATIONS_MD,
    SHADOW_CAMPAIGNS,
    SHADOW_CENSUS_MD,
    SHADOW_MUTATIONS_MD,
    check,
)

EVIDENCE = os.path.join(ROOT, "docs", "evidence")
# Every campaign definition in the tree, gated for replayability. A campaign
# nobody listed is a campaign nobody re-anchors.
DEFINITIONS = (CAMPAIGN,
               *(os.path.join(EVIDENCE, f"{campaign}.json")
                 for _, campaign in (*CP5_CAMPAIGNS, *SHADOW_CAMPAIGNS)))


def _anchors() -> list[str]:
    problems: list[str] = []
    for path in DEFINITIONS:
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if not os.path.exists(path):
            problems.append(f"{rel}: missing — every campaign this gate lists must exist")
            continue
        try:
            definition = load_definition(path)
        except (CampaignError, OSError, ValueError) as e:
            problems.append(f"{rel}: unreadable: {e}")
            continue
        problems.extend(f"{rel}: {p}" for p in validate(definition))
    return problems


def run() -> int:
    problems = check()
    for p in problems:
        print(f"FAIL[checkpoint-status]: {p}")
    anchors = _anchors()
    for p in anchors:
        print(f"FAIL[campaign-anchor]: {p} — the definition no longer applies to this "
              f"tree; re-anchor it (the recorded result stays valid for the commit it names)")
    if problems or anchors:
        return 1
    print(f"checkpoint status fragments OK: {CENSUS_MD}, {INVENTORY_MD}, {MUTATIONS_MD}, "
          f"{CP5_MUTATIONS_MD}, {SHADOW_CENSUS_MD}, {SHADOW_MUTATIONS_MD} in sync with "
          f"the evidence; "
          f"{len(DEFINITIONS)} campaign definitions still anchor")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
