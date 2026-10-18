#!/usr/bin/env python3
"""Join each round's findings with its sample index and labels -> data/r<N>/findings.tsv.

Prints the tally. Warnings are numbered in probe output order (F1.. for round 1, G1.. for round 2),
the numbering the labels use. The join fails loudly if a label's repo/path does not match the
warning it is attached to.
Usage: python scripts/findings_table.py
"""

from __future__ import annotations

import collections
import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read_tsv(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if line.strip()]


def main() -> int:
    for rnd, prefix in (("r1", "F"), ("r2", "G")):
        base = os.path.join(ROOT, "data", rnd)
        index = read_tsv(os.path.join(base, "index.tsv"))
        _header, *labels = read_tsv(os.path.join(base, "labels.tsv"))
        jpath = os.path.join(base, "findings.json")
        with open(jpath, encoding="utf-8") as f:
            data = json.load(f)
        found = data["findings"]
        for w in found:
            w["file"] = w["file"].replace("\\", "/")
        with open(jpath, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        if len(found) != len(labels):
            raise SystemExit(f"{rnd}: {len(found)} warnings but {len(labels)} labels")
        rows = []
        for n, (w, lab) in enumerate(zip(found, labels, strict=True), 1):
            wid, repo, path, label, reason = lab
            m = re.search(r"(\d+)\.cs$", w["file"])
            if m is None:
                raise SystemExit(f"{rnd}: unexpected file {w['file']}")
            num = int(m.group(1))
            irepo, ipath, sha = index[num - 1]
            if wid != f"{prefix}{n}" or (irepo, ipath) != (repo, path):
                raise SystemExit(f"{rnd}: label {wid} does not match warning {n} ({irepo} {ipath})")
            rows.append(
                [
                    wid,
                    repo,
                    path,
                    sha,
                    str(w["line"]),
                    str(w["acquired_line"]),
                    str(w["event_line"]),
                    w["event_kind"],
                    w["use"],
                    w["event"],
                    label,
                    reason,
                ]
            )
        with open(os.path.join(base, "findings.tsv"), "w", encoding="utf-8", newline="\n") as f:
            f.write(
                "\t".join(
                    [
                        "id",
                        "repo",
                        "path",
                        "blob_sha",
                        "use_line",
                        "acquired_line",
                        "event_line",
                        "event_kind",
                        "use",
                        "event",
                        "label",
                        "reason",
                    ]
                )
                + "\n"
            )
            for r in rows:
                f.write("\t".join(r) + "\n")
        tally = collections.Counter(r[10] for r in rows)
        tp, fp, unc = tally["TP"], tally["FP"], tally["UNCLEAR"]
        print(
            f"{rnd}: sites={data['sites']} warnings={len(rows)} files={len(index)} "
            f"repos={len({r[0] for r in index})} TP={tp} FP={fp} UNCLEAR={unc} "
            f"precision={tp / (tp + fp):.0%} conservative={tp / len(rows):.0%} "
            f"TP repos={len({r[1] for r in rows if r[10] == 'TP'})}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
