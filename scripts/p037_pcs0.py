#!/usr/bin/env python3
"""P-037 PCS-0: the producer canonical shadow on the eight A18-0 rows.

Contract: docs/notes/p037-pcs0-producer-canonical-shadow.md. L_actual and G are
own-guarded-report on the extractor's ordinary facts, L_canonical the same report on its
--p037-canonical-shadow document. No population run.

Run:  python scripts/p037_pcs0.py --out docs/evidence/p037-pcs0/eight-rows.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_a18_decompose as a18  # noqa: E402
import p037_b1_shadow as b1  # noqa: E402


def extract(tree: Path, files: list[str]) -> dict[str, Any]:
    """Both documents and their reports; `-o` is also extracted without the flag."""
    with tempfile.TemporaryDirectory(prefix="p037-pcs0-") as td:
        plain, facts, shadow = (Path(td) / n for n in ("plain.json", "facts.json", "shadow.json"))
        cmd = ["dotnet", str(b1.EXTRACTOR), *files, "--flow-locals", "-o"]
        for tail in ([str(plain)], [str(facts), "--p037-canonical-shadow", str(shadow)]):
            subprocess.run(cmd + tail, cwd=tree, check=True, capture_output=True,
                           env=b1.ev.sanitized_env())
        docs = {"facts": json.loads(facts.read_text()),
                "shadow_facts": json.loads(shadow.read_text())}
        return {**docs, "actual": a18.report(docs["facts"]),
                "shadow": a18.report(docs["shadow_facts"]),
                "o_identical": plain.read_bytes() == facts.read_bytes()}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    out_path = ap.parse_args(argv).out
    if b1.git("status", "--porcelain", "--untracked-files=no").strip():
        print("REFUSED: the instrument tree is dirty; commit it first")
        return 2
    commit = b1.frozen(b1.POPULATION_COMMIT)
    want = json.loads((ROOT / "docs/evidence/p037-a18/eight-rows.json").read_text())["rows"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="p037-pcs0-tree-") as td:
        archive = subprocess.run(["git", "archive", commit], cwd=ROOT, capture_output=True,
                                 check=True)
        subprocess.run(["tar", "-x", "-C", td], input=archive.stdout, check=True)
        docs = {name: files for _, name, files in b1.documents(Path(td), commit)}
        for w in want:
            run = extract(Path(td), docs[w["doc"]])
            a, c = (a18.coord(run[k], w["method"], "index", w["index"])
                    for k in ("actual", "shadow"))
            got = (a["legacy"], c["legacy"], a["guarded"], c["guarded"], c["class"],
                   run["o_identical"])
            want_ = (w["actual"], w["canonical"], w["guarded"], w["guarded"], "EQUAL", True)
            rows.append({"doc": w["doc"], "method": w["method"], "L_actual": got[0],
                         "L_canonical": got[1], "G": got[2], "G_shadow": got[3],
                         "semantic_class": got[4], "o_identical": got[5], "match": got == want_})
    ok = len(rows) == 8 and all(r["match"] for r in rows)
    verdict = ("PASS — PCS-0 A18-0 8/8 REPRODUCED" if ok
               else "FAIL — PCS-0 PRODUCER-SHADOW APPROACH KILLED")
    doc = {"schema": "p037-pcs0-eight-rows/1", "population_commit": commit,
           "instrument_commit": b1.git("rev-parse", "HEAD").strip(),
           "extractor_sha256": b1.sha(b1.EXTRACTOR), "rows": rows, "result": verdict}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
