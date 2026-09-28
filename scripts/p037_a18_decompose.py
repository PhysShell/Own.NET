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

A18-1R (docs/notes/p037-a18-1r-population-decomposition.md): `--selftest`, `--population`.

Run:  python scripts/p037_a18_decompose.py --out docs/evidence/p037-a18/eight-rows.json
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
    fn = next(f for f in facts["functions"] if f["name"] == row["method"])
    ops = [(o, i) for o, i in op_sites(fn["body"]) if o[i].get("line") == line
           and names(o[i], row["param"])]
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


# --- A18-1R: the population gate -----------------------------------------------

SNAPSHOT = ROOT / "docs/evidence/p037-b1/comparable-summary-rows.json"
MECH = {"call": "EQUAL", "release": "CONSUMES_PARAM_FOLD", "use": "ARGUMENT_SHAPE_LOSS"}


def reason_of(broken: bool, actual: str, canonical: str, mechs: set[str]) -> str:
    if broken:
        return "UNEXPLAINED"
    if actual == canonical:
        return "EQUAL"
    known = {"CONSUMES_PARAM_FOLD", "ARGUMENT_SHAPE_LOSS"}
    return next(iter(mechs)) if len(mechs) == 1 and mechs <= known else "UNEXPLAINED"


def population(facts: Any, rep: Any, rows: list[dict[str, Any]], probe: Any,
               rewrite: str = "all") -> list[dict[str, Any]]:
    """Canonicalize every eligible forward of every G coordinate (`local` is
    #375's local-honesty rule, `none` disables it), run the production MOS
    once, and attribute each row through its forward closure."""
    canon = copy.deepcopy(facts)
    fns = {f["name"]: f for f in canon["functions"]}
    info: dict[tuple[str, int], dict[str, Any]] = {}
    for s in rep["summary"]:
        if s.get("guarded") is None or s["method"] not in fns:
            continue
        fn, sites, broken = fns[s["method"]], [], False
        for c in (fn.get("guarded_facts") or {}).get("calls", []):
            slot = next((a["param"] for a in c["args"] if a["kind"] == "param"
                         and a.get("source_param") == s["ordinal"]), None)
            if slot is None:
                continue
            ops = [(o, i) for o, i in op_sites(fn["body"]) if o[i].get("line") ==
                   c["statement_line"] and names(o[i], s["param"])]
            callee = coord(rep, c["callee"], "ordinal", slot)
            if len(ops) != 1 or callee is None:
                broken = True
                continue
            lst, i = ops[0]
            kind = lst[i]["op"]
            mech = MECH.get(kind, "UNKNOWN")
            if mech == "ARGUMENT_SHAPE_LOSS" and not probe(s, c["statement_line"]):
                mech = "UNKNOWN"
            agrees = {"release": "must", "use": "no"}.get(kind) == callee["legacy"]
            if rewrite == "all" or (rewrite == "local" and not agrees):
                lst[i] = {"op": "call", "callee": c["callee"], "sig": c["sig"], "line": c[
                    "statement_line"], "args": ["_"] * callee["index"] + [s["param"]]}
            sites.append({"callee": (c["callee"], callee["index"]), "op": kind,
                          "line": c["statement_line"], "mechanism": mech})
        info[(s["method"], s["index"])] = {"broken": broken, "sites": sites}
    after_rep, out = report(canon), []
    for r in rows:
        k = (r["method"], r["index"])
        seen, stack, mechs, rewrites = {k}, [k], set(), 0
        while stack:
            for site in info.get(stack.pop(), {"sites": []})["sites"]:
                mechs.add(site["mechanism"])
                rewrites += site["op"] != "call"
                if site["callee"] not in seen:
                    seen.add(site["callee"])
                    stack.append(site["callee"])
        after = coord(after_rep, r["method"], "index", r["index"])
        broken = info.get(k, {"broken": True})["broken"]
        out.append({**r, "canonical": after["legacy"], "guarded_after": after["guarded"],
                    "semantic_class": after["class"], "closure_rewrites": rewrites,
                    "closure_mechanisms": sorted(mechs - {"EQUAL"}),
                    "normalization_reason": reason_of(broken, r["legacy"], after["legacy"],
                                                      mechs - {"EQUAL"})})
    return out


def coverage(rows: list[dict[str, Any]], snapshot: list[dict[str, Any]]) -> list[str]:
    """N1/N2, exact per row against the committed B1 snapshot."""
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
    facts, rep, _ = b1.run_document(tree, files, work)
    rows = [{"population": pop, "document": name, **{k: s[k] for k in b1.COMPARABLE_KEYS}}
            for s in rep["summary"] if s["class"] != "NO_GUARDED_EVIDENCE"]

    def probe(r: Any, line: int) -> bool:
        p = shape_probe(tree, files, r, line, work)
        return bool(p["op_after"] == "release" and p["line_after"] != p["line_before"])
    return facts, rep, rows, probe


def selftest() -> int:
    fails = 0

    def check(label: str, ok: bool) -> None:
        nonlocal fails
        print(f"{'ok ' if ok else 'MISS'} {label}")
        fails += not ok
    with frozen_tree() as (tree, work, docs):
        facts, rep, rows, probe = comparable(tree, work, "guard-forward-bare",
                                             *docs["guard-forward-bare"])
        b = next(f for f in facts["functions"] if f["name"] == "ShapeForwardBare.Outer")
        a = {**copy.deepcopy(b), "name": "F0.A"}  # B's own fold, retargeted at B
        a["guarded_facts"]["guards"] = []
        a["guarded_facts"]["calls"][0].update(callee=b["name"], sig=b["sig"])
        a["guarded_facts"]["calls"][0]["args"][1] = {"param": 1, "kind": "bool_const",
                                                     "value": True}
        f0 = {**facts, "functions": [*facts["functions"], a]}
        rep0 = report(f0)
        pick = [{"document": "F0", **{k: s[k] for k in b1.COMPARABLE_KEYS}}
                for s in rep0["summary"] if s["method"] in ("F0.A", b["name"])]
        new = {r["method"]: r for r in population(f0, rep0, pick, probe)}
        old = {r["method"]: r for r in population(f0, rep0, pick, probe, rewrite="local")}
        b_act, b_can = new[b["name"]]["legacy"], new[b["name"]]["canonical"]
        check(f"F0  A reads B_canonical ({new['F0.A']['canonical']} == {b_can} != {b_act}); "
              f"the old local rule does not ({old['F0.A']['canonical']})",
              new["F0.A"]["canonical"] == b_can != b_act == old["F0.A"]["canonical"])
        outer = [r for r in rows if r["method"] == b["name"]]
        on = population(facts, rep, outer, probe)[0]["normalization_reason"]
        off = population(facts, rep, outer, probe, rewrite="none")[0]["normalization_reason"]
        check(f"F1  a fold row without canonicalization stops being a fold ({on} -> {off})",
              on == "CONSUMES_PARAM_FOLD" != off)
        facts, rep, rows, probe = comparable(tree, work, "arg-cast-and-bang",
                                             *docs["arg-cast-and-bang"])
        cast = [r for r in rows if r["method"] == "ShapeCastBang.Cast"]
        broken = copy.deepcopy(facts)
        for fn in broken["functions"]:
            for c in (fn.get("guarded_facts") or {}).get("calls", []):
                c["statement_line"] += 100 * (fn["name"] == "ShapeCastBang.Cast")
        got = population(broken, rep, cast, probe)[0]["normalization_reason"]
        check(f"F2  a broken sidecar-to-forward link is UNEXPLAINED ({got})", got == "UNEXPLAINED")
        check("F3  actual=unknown, canonical=must, no mechanism is UNEXPLAINED",
              reason_of(False, "unknown", "must", set()) == "UNEXPLAINED")
        sem = population(facts, rep, cast, probe, rewrite="none")[0]["semantic_class"]
        check(f"F4  G=may vs L_canonical=no is semantic UNEXPLAINED ({sem})", sem == "UNEXPLAINED")
        snap = [s for s in json.loads(SNAPSHOT.read_text())["rows"]
                if s["document"] == "arg-cast-and-bang"]
        base = population(facts, rep, rows, probe)
        check("F5' the coverage check passes on the complete set", not coverage(base, snap))
        check("F5  a deleted row fails coverage", bool(coverage(base[1:], snap)))
        check("F6  a duplicated row fails coverage", bool(coverage([*base, base[0]], snap)))
    print(f"RESULT: {'all falsifiers fire' if not fails else f'{fails} falsifier(s) missed'}")
    return 1 if fails else 0


def population_run(out_path: str) -> int:
    snap = json.loads(SNAPSHOT.read_text())["rows"]
    a18_0 = {(r["doc"], r["method"]): r["canonical"] for r in json.loads(
        (ROOT / "docs/evidence/p037-a18/eight-rows.json").read_text())["rows"]}
    rows: list[dict[str, Any]] = []
    with frozen_tree() as (tree, work, docs):
        for name, (pop, files) in docs.items():
            facts, rep, comp, probe = comparable(tree, work, name, pop, files)
            rows += population(facts, rep, comp, probe) if comp else []
    cov = coverage(rows, snap)
    sem = collections.Counter(r["semantic_class"] for r in rows)
    norm = collections.Counter(r["normalization_reason"] for r in rows)
    moved = [r for r in rows if r["guarded_after"] != r["guarded"]]
    drift_0 = [k for k, v in a18_0.items() if any(
        (r["document"], r["method"]) == k and r["canonical"] != v for r in rows)]
    verdict = ("VOID — drift against the B1 snapshot" if any(c.startswith("drift") for c in cov)
               else "FAIL — A18-1R COVERAGE BROKEN" if cov or moved or drift_0
               else "FAIL — A18-1R NORMALIZATION MODEL INCOMPLETE" if norm["UNEXPLAINED"]
               else "FAIL — A18-1R SEMANTIC UNEXPLAINED" if sem["UNEXPLAINED"]
               else "PASS — A18 POPULATION DECOMPOSITION HOLDS")
    out = {"schema": "p037-a18-1r-population/1",
           "population_commit": b1.frozen(b1.POPULATION_COMMIT),
           "instrument_commit": b1.git("rev-parse", "HEAD").strip(),
           "comparable_in_snapshot": len(snap), "covered": len(rows),
           "coverage_problems": cov, "guarded_moved": len(moved), "a18_0_drift": drift_0,
           "semantic": dict(sem), "normalization": dict(norm),
           "equal_with_value_neutral_rewrites": sum(
               r["normalization_reason"] == "EQUAL" and r["closure_rewrites"] > 0 for r in rows),
           "cross_tab": dict(collections.Counter(
               f"{r['semantic_class']} x {r['normalization_reason']}" for r in rows)),
           "result": verdict, "rows": rows}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    return 0 if verdict.startswith("PASS") else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--population", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    commit = b1.frozen(b1.POPULATION_COMMIT)
    if b1.git("status", "--porcelain", "--untracked-files=no").strip() or not args.out:
        print("REFUSED: needs --out and a clean instrument tree (commit it first)")
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
