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
A18-1F (docs/notes/p037-a18-1f-population-decomposition.md): add `--population`.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
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


# --- A18-1F: the population gate ----------------------------------------------
# Contract: docs/notes/p037-a18-1f-population-decomposition.md (pre-registered in
# e6b8dc4). Section references below (C.1-C.5, N1-N7) point into that note.

SNAPSHOT = ROOT / "docs/evidence/p037-b1/comparable-summary-rows.json"
EIGHT_ROWS = ROOT / "docs/evidence/p037-a18/eight-rows.json"
MECH = {"call": "EQUAL", "release": "CONSUMES_PARAM_FOLD", "use": "ARGUMENT_SHAPE_LOSS"}
KNOWN = {"CONSUMES_PARAM_FOLD", "ARGUMENT_SHAPE_LOSS"}


def reason_of(broken: bool, actual: str, canonical: str, sites: list[dict[str, Any]],
              witness: Any) -> str:
    """C.5: one row's normalization reason from its forward closure."""
    if broken:
        return "UNEXPLAINED"
    if actual == canonical:
        return "EQUAL"
    mechs = {s["mechanism"] for s in sites} - {"EQUAL"}
    if len(mechs) != 1 or not mechs <= KNOWN:
        return "UNEXPLAINED"
    (mech,) = mechs
    return mech if all(witness(s) for s in sites if s["mechanism"] == mech) else "UNEXPLAINED"


def population(facts: Any, rep: Any, rows: list[dict[str, Any]], probe: Any,
               rewrite: str = "all") -> list[dict[str, Any]]:
    """C.1-C.3: canonicalize every eligible forward site of every coordinate,
    run the production MOS once, attribute each row through its closure.
    `local` is #375's local-honesty rule (F0 only); `none` disables rewriting."""
    canon = copy.deepcopy(facts)
    fns = {f["name"]: f for f in canon["functions"]}
    info: dict[tuple[str, int], dict[str, Any]] = {}
    made: set[int] = set()
    for s in rep["summary"]:
        if s["method"] not in fns:
            continue
        fn = fns[s["method"]]
        node = info[(s["method"], s["index"])] = {"broken": False, "sites": [], "row": s}
        for c in (fn.get("guarded_facts") or {}).get("calls", []):
            slots = [a["param"] for a in c["args"]
                     if a["kind"] == "param" and a.get("source_param") == s["ordinal"]]
            if not slots:
                continue
            ops = [(o, i) for o, i in op_sites(fn["body"])
                   if o[i].get("line") == c["statement_line"] and names(o[i], s["param"])]
            callee = coord(rep, c["callee"], "ordinal", slots[0])
            if len(slots) != 1 or len(ops) != 1 or callee is None \
                    or id(ops[0][0][ops[0][1]]) in made:  # E1 / E2 / E3
                node["broken"] = True
                continue
            lst, i = ops[0]
            kind = lst[i]["op"]
            agrees = {"release": "must", "use": "no"}.get(kind) == callee["legacy"]
            rewritten = rewrite == "all" or (rewrite == "local" and not agrees)
            if rewritten:
                lst[i] = {"op": "call", "callee": c["callee"], "sig": c["sig"],
                          "line": c["statement_line"],
                          "args": ["_"] * callee["index"] + [s["param"]]}
                made.add(id(lst[i]))
            node["sites"].append({"at": [s["method"], s["index"]], "line": c["statement_line"],
                                  "callee": (c["callee"], callee["index"]), "op": kind,
                                  "mechanism": MECH.get(kind, "UNKNOWN"),
                                  "rewritten": rewritten})

    def witness(site: dict[str, Any]) -> bool:
        """C.4: the local witness, evaluated once and recorded on the site."""
        if "witness" not in site:
            ok = site["rewritten"] and site["op"] in ("release", "use")
            if ok and site["op"] == "use":
                ok = probe(info[tuple(site["at"])]["row"], site["line"])
            site["witness"] = ok
            if not ok and site["op"] == "use":
                site["mechanism"] = "UNKNOWN"
        return bool(site["witness"])
    after_rep, out = report(canon), []
    for r in rows:
        k = (r["method"], r["index"])
        seen, stack, sites, broken = {k}, [k], [], False
        while stack:
            node = info.get(stack.pop())
            if node is None:
                broken = True
                continue
            broken = broken or node["broken"]
            sites += node["sites"]
            for site in node["sites"]:
                if site["callee"] not in seen:
                    seen.add(site["callee"])
                    stack.append(site["callee"])
        after = coord(after_rep, r["method"], "index", r["index"])
        reason = reason_of(broken, r["legacy"], after["legacy"], sites, witness)
        out.append({**r, "canonical": after["legacy"], "guarded_after": after["guarded"],
                    "semantic_class": after["class"], "normalization_reason": reason,
                    "closure_broken": broken, "closure_sites": sites})
    return out


def coverage(rows: list[dict[str, Any]], snapshot: list[dict[str, Any]]) -> list[str]:
    """N1/N2, exact per row against the committed #376 snapshot."""
    keys = [(r["document"], r["method"], r["index"]) for r in rows]
    want = {(s["document"], s["method"], s["index"]): s for s in snapshot}
    got = collections.Counter(keys)
    bad = [f"duplicate {k}" for k, n in got.items() if n > 1]
    bad += [f"missing {k}" for k in want.keys() - got.keys()]
    bad += [f"extra {k}" for k in got.keys() - want.keys()]
    return bad + [f"drift {k}" for k, r in zip(keys, rows, strict=True) if k in want and any(
        r[f] != want[k][f] for f in ("legacy", "guarded", "class"))]


@contextlib.contextmanager
def frozen_tree() -> Iterator[tuple[Path, Path, dict[str, tuple[str, list[str]]]]]:
    commit = b1.frozen(b1.POPULATION_COMMIT)
    with tempfile.TemporaryDirectory(prefix="p037-a18-") as td:
        tree = Path(td) / "tree"
        tree.mkdir()
        archive = subprocess.run(["git", "archive", commit], cwd=ROOT, capture_output=True,
                                 check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
        yield tree, Path(td), {n: (pop, f) for pop, n, f in b1.documents(tree, commit)}


def comparable(tree: Path, work: Path, name: str, pop: str, files: list[str]) -> Any:
    """One document's facts, report, comparable rows (§B) and wrapper probe."""
    facts, rep, _ = b1.run_document(tree, files, work)
    rows = [{"population": pop, "document": name, **{k: s[k] for k in b1.COMPARABLE_KEYS}}
            for s in rep["summary"] if s["class"] != "NO_GUARDED_EVIDENCE"]

    def probe(r: Any, line: int) -> bool:
        p = shape_probe(tree, files, r, line, work)
        return bool(p["op_after"] == "release" and p["line_after"] != p["line_before"])
    return facts, rep, rows, probe


def population_run(out_path: str) -> int:
    snap = json.loads(SNAPSHOT.read_text())["rows"]
    a18_0 = {(r["doc"], r["method"]): r["canonical"]
             for r in json.loads(EIGHT_ROWS.read_text())["rows"]}
    rows: list[dict[str, Any]] = []
    with frozen_tree() as (tree, work, docs):
        for name, (pop, files) in docs.items():
            facts, rep, comp, probe = comparable(tree, work, name, pop, files)
            rows += population(facts, rep, comp, probe) if comp else []
    cov = coverage(rows, snap)
    sem = collections.Counter(r["semantic_class"] for r in rows)
    norm = collections.Counter(r["normalization_reason"] for r in rows)
    broken = [r for r in rows if r["closure_broken"]]
    moved = [r for r in rows if r["guarded_after"] != r["guarded"]]
    drift_0 = [f"{d} {m}" for (d, m), v in a18_0.items() if not any(
        (r["document"], r["method"]) == (d, m) and r["canonical"] == v for r in rows)]
    after_rewrite = sum(r["normalization_reason"] == "EQUAL" and any(
        s["op"] != "call" for s in r["closure_sites"]) for r in rows)
    verdict = ("VOID — drift against the #376 snapshot" if any(
        c.startswith("drift") for c in cov) else "FAIL — A18-1F COVERAGE BROKEN" if cov
        else "FAIL — A18-1F BROKEN CANONICALIZATION" if broken
        else "FAIL — A18-1F G MOVED UNDER CANONICALIZATION" if moved
        else "FAIL — A18-1F A18-0 EIGHT-ROW DRIFT" if drift_0
        else "FAIL — A18-1F NORMALIZATION MODEL INCOMPLETE" if norm["UNEXPLAINED"]
        else "FAIL — A18-1F SEMANTIC UNEXPLAINED" if sem["UNEXPLAINED"]
        else "PASS — A18 POPULATION DECOMPOSITION HOLDS")
    out = {"schema": "p037-a18-1f-population/1",
           "population_commit": b1.frozen(b1.POPULATION_COMMIT),
           "instrument_commit": b1.git("rev-parse", "HEAD").strip(),
           "comparable_in_snapshot": len(snap), "covered": len(rows),
           "coverage_problems": cov, "broken_closures": len(broken),
           "guarded_moved": len(moved), "a18_0_drift": drift_0,
           "semantic": dict(sem), "normalization": dict(norm),
           "equal_identity": norm["EQUAL"] - after_rewrite,
           "equal_after_rewrite": after_rewrite,
           "cross_tab": dict(collections.Counter(
               f"{r['semantic_class']} x {r['normalization_reason']}" for r in rows)),
           "result": verdict, "rows": rows}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    print(f"RESULT: {verdict}")
    return 0 if verdict.startswith("PASS") else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--population", action="store_true", help="the A18-1F population gate")
    args = ap.parse_args(argv)
    commit = b1.frozen(b1.POPULATION_COMMIT)
    if b1.git("status", "--porcelain", "--untracked-files=no").strip():
        print("REFUSED: the instrument tree is dirty; commit it first")
        return 2
    if args.population:
        return population_run(args.out)
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
