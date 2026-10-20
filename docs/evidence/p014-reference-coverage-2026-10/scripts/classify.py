# ruff: noqa: E501  (research script; long docstring/comment lines)
"""R2: per-site A/B/C comparison (00-preregistration.md §3) and the fixed review sample.

usage: python -I classify.py --proj <dir with P*/out/sites.tsv> --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random

SEED = 20261021


def strip_asm(sym: str) -> str:
    """symbol description without the containing-assembly part (impl vs reference assembly differ by design)."""
    return sym.rsplit("|", 1)[0] if sym else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proj", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    table, sample_rows, recovered_rows = [], [], []
    for pid in sorted(d for d in os.listdir(a.proj) if d.startswith("P")):
        path = os.path.join(a.proj, pid, "out", "sites.tsv")
        rows = list(
            csv.DictReader(open(path, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        )
        for kind in ("call", "type", "plus_eq"):
            ks = [r for r in rows if r["kind"] == kind]
            ok = {"call": "resolved", "type": "resolved", "plus_eq": "event"}[kind]
            rec_b = [r for r in ks if r["A"] != ok and r["B"] == ok]
            rec_ref = [r for r in rec_b if r["C"] != ok]  # credited to references
            rec_src = [r for r in rec_b if r["C"] == ok]  # also fixed by implicit usings
            only_c = [r for r in ks if r["A"] != ok and r["C"] == ok and r["B"] != ok]
            lost = [r for r in ks if r["A"] == ok and r["B"] != ok]
            changed = [
                r
                for r in ks
                if r["A"] == ok and r["B"] == ok and strip_asm(r["A_sym"]) != strip_asm(r["B_sym"])
            ]
            still = [r for r in ks if r["A"] != ok and r["B"] != ok and r["C"] != ok]
            amb_b = [r for r in ks if r["B"].startswith("ambiguous")]
            table.append(
                {
                    "project": pid,
                    "kind": kind,
                    "sites": len(ks),
                    "A_ok": sum(r["A"] == ok for r in ks),
                    "B_ok": sum(r["B"] == ok for r in ks),
                    "C_ok": sum(r["C"] == ok for r in ks),
                    "recovered_by_refs": len(rec_ref),
                    "recovered_also_by_usings": len(rec_src),
                    "fixed_by_usings_only": len(only_c),
                    "lost_in_B": len(lost),
                    "symbol_changed": len(changed),
                    "still_unresolved": len(still),
                    "B_ambiguous": len(amb_b),
                    "recovered_by_refs_pct": round(100 * len(rec_ref) / len(ks), 1) if ks else 0,
                }
            )
            for r in rec_ref:
                recovered_rows.append({"project": pid, **r})
            if kind == "call" and rec_ref:
                rnd = random.Random(f"{SEED}-{pid}")
                for r in rnd.sample(rec_ref, min(10, len(rec_ref))):
                    sample_rows.append({"project": pid, **r})
            for r in lost + changed:
                recovered_rows.append({"project": pid, "note": "LOST_OR_CHANGED", **r})
    with open(os.path.join(a.out, "r2_summary.tsv"), "w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(table)
    keys = [
        "project",
        "note",
        "file",
        "line",
        "col",
        "kind",
        "expr",
        "A",
        "A_sym",
        "B",
        "B_sym",
        "C",
    ]
    for name, rows in (
        ("r2_recovered_and_changed.tsv", recovered_rows),
        ("r2_review_sample.tsv", sample_rows),
    ):
        with open(os.path.join(a.out, name), "w", encoding="utf-8", newline="\n") as f:
            w = csv.DictWriter(f, fieldnames=keys, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    for t in table:
        print(json.dumps(t))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
