#!/usr/bin/env python3
"""Gate: the generated checkpoint status fragments equal their projection.

`docs/generated/p022-cp4-*.md` are rendered from the evidence in the tree by
`scripts/render_checkpoint_status.py` (the verdict ledger census through
`tests/verdict_census.py`; the recorded mutation campaign through
`scripts/mutate_campaign.py`). This module runs its `--check` in-process, so
a change to the evidence without regenerating the fragments — or a campaign
result that no longer matches its definition — turns the existing Python
gate red on every interpreter the suite runs on. Regenerate with
`python scripts/render_checkpoint_status.py`.

Run:  python tests/test_checkpoint_status.py
      python tests/run_tests.py            (runs it in the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from render_checkpoint_status import CENSUS_MD, MUTATIONS_MD, check


def run() -> int:
    problems = check()
    for p in problems:
        print(f"FAIL: checkpoint status {p}")
    if problems:
        return 1
    print(f"checkpoint status fragments OK: {CENSUS_MD}, {MUTATIONS_MD} in sync with the evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
