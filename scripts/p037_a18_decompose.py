#!/usr/bin/env python3
"""P-037 A18-0: the three-way decomposition of the eight B1 UNEXPLAINED rows.

Contract: docs/notes/p037-a18-legacy-decomposition.md (pre-registered in
ccde27c). For exactly the eight rows committed in B1's evidence, from the
frozen population and the unchanged B1 instrument:

  L_actual     the production MOS (own-bridge) on the facts as emitted
  G            the guarded shadow on the same facts
  L_canonical  the same production MOS with the row's one legacy op at the
               forwarding call's line rewritten to the honest forward

Each row gets one deterministic normalization reason (CONSUMES_PARAM_FOLD or
ARGUMENT_SHAPE_LOSS, never a P-037 class) and that reason's executable
witness.

Run:  python scripts/p037_a18_decompose.py --out docs/evidence/p037-a18/eight-rows.json
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_b1_shadow as b1  # noqa: E402

EVIDENCE = ROOT / "docs/evidence/p037-b1/shadow-run.json"


def report(facts: Any) -> Any:
    run = subprocess.run([str(b1.REPORT_BIN)], input=json.dumps(facts).encode(),
                         capture_output=True, check=True)
    return json.loads(run.stdout)


def coord(rep: Any, method: str, key: str, value: int) -> Any:
    rows = [s for s in rep["summary"] if s["method"] == method and s[key] == value]
    return rows[0] if len(rows) == 1 else None


def op_sites(body: list[Any]) -> list[tuple[list[Any], int]]:
    """Every op as (containing list, position), pre-order."""
    out = []
    for i, op in enumerate(body):
        out.append((body, i))
        for k in ("then", "else", "body"):
            out += op_sites(op.get(k) or [])
    return out


def names(op: Any, p: str) -> bool:
    return p in (op.get("var"), op.get("src"), op.get("result")) or p in (op.get("args") or [])


def locate(facts: Any, row: Any) -> tuple[Any, Any, list[tuple[list[Any], int]]]:
    """The row's function, its one forwarding sidecar call, and the legacy ops on
    the parameter at that call's statement line."""
    fn = next(f for f in facts["functions"] if f["name"] == row["method"])
    calls = [c for c in (fn.get("guarded_facts") or {}).get("calls", [])
             if any(a["kind"] == "param" and a.get("source_param") == row["ordinal"]
                    for a in c["args"])]
    call = calls[0] if len(calls) == 1 else None
    line = call["statement_line"] if call else None
    ops = [(lst, i) for lst, i in op_sites(fn["body"])
           if lst[i].get("line") == line and names(lst[i], row["param"])]
    return fn, call, ops


def decompose(facts: Any, rep: Any, row: Any) -> dict[str, Any]:
    _, call, ops = locate(facts, row)
    if call is None or len(ops) != 1:
        return {"reason": None, "why": "no single forwarding call / legacy op"}
    kind = ops[0][0][ops[0][1]]["op"]
    slot = next(a["param"] for a in call["args"]
                if a["kind"] == "param" and a.get("source_param") == row["ordinal"])
    callee = coord(rep, call["callee"], "ordinal", slot)
    if callee is None:
        return {"reason": None, "why": "callee coordinate not in the B1 report"}
    reason = ("CONSUMES_PARAM_FOLD" if kind == "release" and callee["legacy"] != "must" else
              "ARGUMENT_SHAPE_LOSS" if kind == "use" and callee["legacy"] != "no" else None)
    canon = copy.deepcopy(facts)
    lst, i = locate(canon, row)[2][0]
    lst[i] = {"op": "call", "callee": call["callee"], "sig": call["sig"],
              "args": ["_"] * callee["index"] + [row["param"]], "line": call["statement_line"]}
    after = coord(report(canon), row["method"], "index", row["index"])
    return {"reason": reason, "legacy_op": kind, "callee": call["callee"],
            "callee_actual": callee["legacy"], "line": call["statement_line"],
            "canonical": after["legacy"], "guarded_after_rewrite": after["guarded"],
            "canonical_class": after["class"]}


UNWRAP = [(re.compile(r"\(\s*[\w.]+\s*\)\s*(?=\w)"), ""), (re.compile(r"(\w)!(?!=)"), r"\1")]


def shape_probe(tree: Path, files: list[str], row: Any, line: int, work: Path) -> dict[str, Any]:
    """ARGUMENT_SHAPE_LOSS witness: the frozen source with the value-preserving
    wrapper removed on that one line re-extracts to a fold (`release`)."""
    src = next(tree / f for f in files if row["method"].split(".")[0] in (tree / f).read_text())
    text = src.read_text()
    lines = text.split("\n")
    old = lines[line - 1]
    for pat, rep_ in UNWRAP:
        lines[line - 1] = pat.sub(rep_, lines[line - 1])
    src.write_text("\n".join(lines))
    try:
        facts, rep, _ = b1.run_document(tree, files, work)
    finally:
        src.write_text(text)
    ops = locate(facts, row)[2]
    return {"line_before": old.strip(), "line_after": lines[line - 1].strip(),
            "op_after": ops[0][0][ops[0][1]]["op"] if len(ops) == 1 else None,
            "actual_after": coord(rep, row["method"], "index", row["index"])["legacy"]}


def witnessed(d: dict[str, Any], row: dict[str, Any]) -> bool:
    moved = d["canonical"] != row["actual"]
    if d["reason"] == "CONSUMES_PARAM_FOLD":
        return moved and bool(d["callee_actual"] != "must")
    if d["reason"] == "ARGUMENT_SHAPE_LOSS":
        probe = d.get("probe") or {}
        return moved and probe.get("op_after") == "release" and probe["line_after"] != \
            probe["line_before"]
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    commit = b1.frozen(b1.POPULATION_COMMIT)
    if b1.git("status", "--porcelain", "--untracked-files=no").strip():
        print("REFUSED: the instrument tree is dirty; commit it first")
        return 2
    b1_rows = [u for u in json.loads(EVIDENCE.read_text())["unexplained"]
               if u["level"] == "summary"]
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="p037-a18-") as td:
        tree, work = Path(td) / "tree", Path(td)
        tree.mkdir()
        archive = subprocess.run(["git", "archive", commit], cwd=ROOT, capture_output=True,
                                 check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
        docs = {name: files for _, name, files in b1.documents(tree, commit)}
        for u in b1_rows:
            facts, rep, _ = b1.run_document(tree, docs[u["doc"]], work)
            now = coord(rep, u["method"], "index", u["index"])
            row = {"doc": u["doc"], "method": u["method"], "index": u["index"],
                   "ordinal": u["ordinal"], "param": u["param"], "actual": now["legacy"],
                   "guarded": now["guarded"],
                   "void": now["legacy"] != u["legacy"] or now["guarded"] != u["guarded"]}
            d = decompose(facts, rep, row)
            if d["reason"] == "ARGUMENT_SHAPE_LOSS":
                d["probe"] = shape_probe(tree, docs[u["doc"]], row, d["line"], work)
            row.update(d)
            row["witness"] = witnessed(d, row)
            rows.append(row)
    ok = [r for r in rows if not r["void"] and r["reason"] and r["witness"]
          and r["guarded"] == r["canonical"] == r["guarded_after_rewrite"]]
    kill = [r for r in rows if r["guarded"] != r.get("canonical")]
    verdict = ("VOID — instrument drift" if any(r["void"] for r in rows) else
               "FAIL — A18 DECOMPOSITION REFUTED" if kill or len(ok) != 8 or len(rows) != 8
               else "PASS — A18 8-ROW DECOMPOSITION HOLDS")
    out = {"schema": "p037-a18-eight-rows/1", "population_commit": commit,
           "instrument_commit": b1.git("rev-parse", "HEAD").strip(), "rows_checked": len(rows),
           "g_equals_canonical": sum(r["guarded"] == r.get("canonical") for r in rows),
           "deterministic_reason": sum(bool(r["reason"]) for r in rows),
           "witnessed": sum(r["witness"] for r in rows), "rows": rows, "result": verdict}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        print(f"  {r['doc']} {r['method']}: L_actual={r['actual']} L_canonical="
              f"{r.get('canonical')} G={r['guarded']} reason={r['reason']} "
              f"witness={r['witness']}")
    print(f"RESULT: {verdict}")
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
