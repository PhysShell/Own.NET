#!/usr/bin/env python3
"""P-037 A18: the three-way decomposition, A18-0 (the eight B1 UNEXPLAINED rows)
and A18-1 (`--population`, `--selftest`: docs/notes/p037-a18-population-decomposition.md).

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
      python scripts/p037_a18_decompose.py --selftest
      python scripts/p037_a18_decompose.py --population --out docs/evidence/p037-a18/population.json
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


def ops_at(fn: Any, line: Any, p: str) -> list[tuple[list[Any], int]]:
    return [(lst, i) for lst, i in op_sites(fn["body"])
            if lst[i].get("line") == line and names(lst[i], p)]


def locate(facts: Any, row: Any) -> tuple[Any, Any, list[tuple[list[Any], int]]]:
    """The row's function, its one forwarding sidecar call, and the legacy ops on
    the parameter at that call's statement line."""
    fn = next(f for f in facts["functions"] if f["name"] == row["method"])
    calls = [c for c in (fn.get("guarded_facts") or {}).get("calls", [])
             if any(a["kind"] == "param" and a.get("source_param") == row["ordinal"]
                    for a in c["args"])]
    call = calls[0] if len(calls) == 1 else None
    return fn, call, ops_at(fn, call["statement_line"] if call else None, row["param"])


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
    ops = ops_at(fn, line, row["param"])
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


# ---------------------------------------------------------------------------
# A18-1: the population gate
# ---------------------------------------------------------------------------

LOCAL = {"release": "must", "use": "no"}  # a legacy op's own local value


def reason_of(actual: str, canonical: str, mechs: set[str], broken: bool) -> str:
    """The normalization column: only the pre-registered reasons."""
    if broken:
        return "UNEXPLAINED"
    if canonical == actual:
        return "EQUAL"
    if len(mechs) == 1 and mechs <= {"CONSUMES_PARAM_FOLD", "ARGUMENT_SHAPE_LOSS"}:
        return next(iter(mechs))
    return "UNEXPLAINED"


def population(facts: Any, rep: Any, rows: list[dict[str, Any]], probe: Any,
               rewrite: bool = True) -> list[dict[str, Any]]:
    """One document: normalize every locally non-honest forwarding site of every
    comparable row, run the production MOS once, attribute through closures."""
    canon = copy.deepcopy(facts)
    fns = {f["name"]: f for f in canon["functions"]}
    info: dict[tuple[str, int], dict[str, Any]] = {}
    for r in rows:
        entry: dict[str, Any] = {"broken": False, "sites": []}
        fn = fns[r["method"]]
        for c in (fn.get("guarded_facts") or {}).get("calls", []):
            slots = [a["param"] for a in c["args"]
                     if a["kind"] == "param" and a.get("source_param") == r["ordinal"]]
            if not slots:
                continue
            ops, callee = ops_at(fn, c["statement_line"], r["param"]), coord(
                rep, c["callee"], "ordinal", slots[0])
            if len(ops) != 1 or callee is None:
                entry["broken"] = True
                continue
            lst, i = ops[0]
            kind, mech = lst[i]["op"], None
            if LOCAL.get(kind, callee["legacy"]) != callee["legacy"]:
                mech = ("CONSUMES_PARAM_FOLD" if kind == "release" else
                        "ARGUMENT_SHAPE_LOSS" if probe(r, c["statement_line"]) else "UNKNOWN")
                if rewrite:  # the A18-0 honest positional forward
                    lst[i] = {"op": "call", "callee": c["callee"], "sig": c["sig"], "line": c[
                        "statement_line"], "args": ["_"] * callee["index"] + [r["param"]]}
            entry["sites"].append({"callee": (c["callee"], callee["index"]), "op": kind,
                                   "line": c["statement_line"], "mechanism": mech})
        info[(r["method"], r["index"])] = entry
    after_rep = report(canon)
    out = []
    for r in rows:
        k = (r["method"], r["index"])
        seen, stack, mechs = {k}, [k], set()
        while stack:
            for site in info.get(stack.pop(), {"sites": []})["sites"]:
                mechs |= {site["mechanism"]} - {None}
                if site["callee"] not in seen:
                    seen.add(site["callee"])
                    stack.append(site["callee"])
        after = coord(after_rep, r["method"], "index", r["index"])
        reason = reason_of(r["actual"], after["legacy"], mechs, info[k]["broken"])
        out.append({**r, "canonical": after["legacy"], "guarded_after": after["guarded"],
                    "semantic_class": after["class"], "normalization_reason": reason,
                    "closure_mechanisms": sorted(mechs), "sites": info[k]["sites"],
                    "equal_kind": (("identity" if not mechs else "after_rewrite")
                                   if reason == "EQUAL" else None)})
    return out


def coverage(rows: list[dict[str, Any]], expected: dict[str, dict[str, int]],
             committed: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """N1 (missing/duplicate) and N2 (drift) against B1's committed evidence."""
    bad = []
    keys = [(r["doc"], r["method"], r["index"]) for r in rows]
    if len(set(keys)) != len(keys):
        bad.append(("duplicate", "a comparable row occurs twice"))
    got: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for r in rows:
        got[r["pop"]][r["b1_class"]] += 1
    for pop in set(expected) | set(got):
        want = {c: n for c, n in expected.get(pop, {}).items() if c != "NO_GUARDED_EVIDENCE"}
        if dict(got[pop]) != want:
            kind = "drift" if sum(got[pop].values()) == sum(want.values()) else "missing"
            bad.append((kind, f"{pop}: {dict(got[pop])} != B1 {want}"))
    index = {(r["doc"], r["method"], r["index"]): r for r in rows}
    for u in committed:
        hit = index.get((u["doc"], u["method"], u["index"]))
        if hit is None:
            bad.append(("missing", f"committed row absent: {u['doc']} {u['method']}"))
        elif (hit["actual"], hit["guarded"]) != (u["legacy"], u["guarded"]):
            bad.append(("drift", f"committed row drifted: {u['doc']} {u['method']}"))
    return bad


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


def comparable(tree: Path, work: Path, name: str, pop: str, files: list[str]
               ) -> tuple[Any, Any, list[dict[str, Any]], Any]:
    facts, rep, _ = b1.run_document(tree, files, work)
    rows = [{"doc": name, "pop": pop, "method": s["method"], "index": s["index"],
             "ordinal": s["ordinal"], "param": s["param"], "actual": s["legacy"],
             "guarded": s["guarded"], "b1_class": s["class"]}
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
        outer = [r for r in rows if r["method"] == "ShapeForwardBare.Outer"]
        on = population(facts, rep, outer, probe)[0]["normalization_reason"]
        off = population(facts, rep, outer, probe, rewrite=False)[0]["normalization_reason"]
        check(f"F1  a fold row without its rewrite stops being a fold ({on} -> {off})",
              on == "CONSUMES_PARAM_FOLD" and off != on)
        facts, rep, rows, probe = comparable(tree, work, "arg-cast-and-bang",
                                             *docs["arg-cast-and-bang"])
        cast = [r for r in rows if r["method"] == "ShapeCastBang.Cast"]
        broken = copy.deepcopy(facts)
        fn = next(f for f in broken["functions"] if f["name"] == "ShapeCastBang.Cast")
        for c in fn["guarded_facts"]["calls"]:
            c["statement_line"] += 100
        got = population(broken, rep, cast, probe)[0]["normalization_reason"]
        check(f"F2  a broken sidecar-to-forward link is UNEXPLAINED, not a fold ({got})",
              got == "UNEXPLAINED")
        check("F3  actual=unknown, canonical=must, no mechanism is UNEXPLAINED",
              reason_of("unknown", "must", set(), False) == "UNEXPLAINED")
        sem = population(facts, rep, cast, probe, rewrite=False)[0]["semantic_class"]
        check(f"F4  G=may vs L_canonical=no is semantic UNEXPLAINED ({sem})",
              sem == "UNEXPLAINED")
        base = population(facts, rep, rows, probe)
        want = {"p037-shapes": dict(collections.Counter(r["b1_class"] for r in base))}
        check("F5' the coverage check passes on a complete set", not coverage(base, want, []))
        check("F5  a deleted comparable row fails coverage", bool(coverage(base[1:], want, [])))
        check("F6  a duplicated comparable row fails coverage",
              bool(coverage([*base, base[0]], want, [])))
    print(f"RESULT: {'all falsifiers fire' if not fails else f'{fails} falsifier(s) missed'}")
    return 1 if fails else 0


def population_run(out_path: str) -> int:
    ev = json.loads(EVIDENCE.read_text())
    expected = {k.split("/", 1)[1]: v for k, v in ev["counts"].items()
                if k.startswith("summary/")}
    committed = [u for u in ev["unexplained"] if u["level"] == "summary"]
    rows: list[dict[str, Any]] = []
    with frozen_tree() as (tree, work, docs):
        for name, (pop, files) in docs.items():
            facts, rep, comp, probe = comparable(tree, work, name, pop, files)
            if comp:
                rows += population(facts, rep, comp, probe)
    sem = collections.Counter(r["semantic_class"] for r in rows)
    norm = collections.Counter(r["normalization_reason"] for r in rows)
    cross = collections.Counter(f"{r['semantic_class']} x {r['normalization_reason']}"
                                for r in rows)
    cov = coverage(rows, expected, committed)
    drift = [msg for kind, msg in cov if kind == "drift"]
    moved = [r for r in rows if r["guarded_after"] != r["guarded"]]
    verdict = ("VOID — B1 instrument drift" if drift else
               "FAIL — A18-1 COVERAGE BROKEN" if cov or moved else
               "FAIL — A18-1 NORMALIZATION MODEL INCOMPLETE" if norm["UNEXPLAINED"] else
               "FAIL — A18-1 SEMANTIC UNEXPLAINED" if sem["UNEXPLAINED"] else
               "PASS — A18 POPULATION DECOMPOSITION HOLDS")
    out = {"schema": "p037-a18-population/1", "population_commit": b1.frozen(b1.POPULATION_COMMIT),
           "instrument_commit": b1.git("rev-parse", "HEAD").strip(),
           "comparable_expected": sum(n for v in expected.values() for c, n in v.items()
                                      if c != "NO_GUARDED_EVIDENCE"),
           "covered": len(rows), "coverage_problems": cov, "guarded_moved": len(moved),
           "semantic": dict(sem), "normalization": dict(norm),
           "equal_kind": dict(collections.Counter(r["equal_kind"] for r in rows
                                                  if r["equal_kind"])),
           "cross_tab": dict(cross), "rows": rows, "result": verdict}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    print(f"RESULT: {verdict}")
    return 0 if verdict.startswith("PASS") else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--population", action="store_true")
    ap.add_argument("--selftest", action="store_true")
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
