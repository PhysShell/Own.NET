#!/usr/bin/env python3
"""Filter the direction-research ledger to confirmed product-code fix records (Phase 0, section 1).

Usage: python extract.py <records.jsonl> <out.tsv>
The ledger is private research data (PhysShell/ownnet-direction-research,
evidence/ledger/records.jsonl); its filtered output is committed as data/eligible.tsv.
Confirmed = github_pr_fix, ground truth at least patch_supported, impact evidence of an
observable effect, product code.
"""

from __future__ import annotations

import collections
import json
import sys

EFFECT = ("issue_report", "profiler_or_dump", "test", "maintainer_statement")
WEAK = ("candidate", "rejected", "unresolved")
COLUMNS = (
    "record_id",
    "category",
    "repository",
    "source_url",
    "ground_truth_level",
    "impact_evidence",
    "impact",
    "root_cause",
    "ownnet_result",
)


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    fixes = [r for r in recs if r["source_type"] == "github_pr_fix"]
    keep = [
        r
        for r in fixes
        if r["ground_truth_level"] not in WEAK
        and r["impact_evidence"] in EFFECT
        and r["product_code"] is True
    ]
    keep.sort(key=lambda r: (r["category"], r["record_id"]))
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in keep:
            f.write("\t".join(str(r[c]).replace("\t", " ") for c in COLUMNS) + "\n")
    owners = {r["repository"].split("/")[0] for r in keep}
    print(f"fix records {len(fixes)}, eligible {len(keep)}, owners {len(owners)}")
    print(collections.Counter(r["category"] for r in keep).most_common(12))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
