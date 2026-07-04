#!/usr/bin/env python3
"""
Canonical CFG JSON seam (P-022 migration step 0, `ownlang.cfg_json`).

This is the CFG-layer contract the Rust-port differential oracle diffs against,
so the test pins the *shape*, not just "it emits something":

  1. the versioned envelope (`ownlang_cfg_version`) and per-function fields;
  2. the symbol table: first-appearance order, params first, and — the part a
     port gets wrong first — **identity structure**: a borrow binding is a
     distinct symbol row from its owner, and an instruction referencing the
     same symbol twice yields the same index;
  3. the instruction `op` vocabulary for a fixture exercising every variant the
     surface language can produce from source today;
  4. determinism: two projections of the same module are deeply equal, and the
     dumped JSON (sorted keys) is byte-identical.

Run:  python tests/test_cfg_json.py
      python tests/run_tests.py     (as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.cfg import build_cfg, collect_kinds, collect_policies, collect_signatures
from ownlang.cfg_json import CFG_JSON_VERSION, module_cfg_json
from ownlang.parser import parse

_SRC = (
    "module M\n"                                        # 1
    "resource Conn { kind \"connection token\" acquire open release close }\n"  # 2
    "extern fn Store(consume Conn);\n"                  # 3
    "fn f(n: int) {\n"                                  # 4
    "    let c = acquire Conn(1);\n"                    # 5
    "    if (n) {\n"                                    # 6
    "        borrow c as r { use r; }\n"                # 7
    "    }\n"                                           # 8
    "    let d = move c;\n"                             # 9
    "    Store(d);\n"                                   # 10
    "    return;\n"                                     # 11
    "}\n"
    "fn g(n: int) {\n"                                  # 13
    "    let b = Buffer.scratch(n);\n"                  # 14
    "    release b;\n"                                  # 15
    "}\n"                                               # 16
)


def _doc() -> dict:
    mod = parse(_SRC)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    kinds = collect_kinds(mod)
    cfgs = [build_cfg(fn, rnames, sigs, pols, kinds)[0] for fn in mod.functions]
    return module_cfg_json(cfgs)


def run() -> int:
    fails: list[str] = []
    checks = 0

    def expect(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    doc = _doc()

    # -- envelope ------------------------------------------------------------
    expect(doc["ownlang_cfg_version"] == CFG_JSON_VERSION == 0,
           f"version envelope wrong: {doc.get('ownlang_cfg_version')!r}")
    expect([f["name"] for f in doc["functions"]] == ["f", "g"],
           "functions must appear in module order")

    f = doc["functions"][0]
    expect(set(f) == {"name", "entry", "has_return_type", "params", "symbols",
                      "blocks"},
           f"per-function field set drifted: {sorted(f)}")

    # -- symbol table: params first, identity preserved ----------------------
    syms = f["symbols"]
    expect(f["params"] == [0] and syms[0]["name"] == "n"
           and syms[0]["kind"] == "plain",
           f"param must be symbol 0: {f['params']} / {syms[:1]}")
    by_name = {s["name"]: i for i, s in enumerate(syms)}
    expect({"n", "c", "r", "d"} <= set(by_name),
           f"expected symbols missing from table: {sorted(by_name)}")
    expect(syms[by_name["r"]]["kind"] == "borrow"
           and syms[by_name["c"]]["kind"] == "owned",
           "borrow binding must be a distinct row with kind=borrow")
    # resource kinds must ride the seam (the CLI path passes collect_kinds;
    # dropping it would null the field for every kind-tagged resource).
    expect(syms[by_name["c"]]["resource_kind"] == "connection token",
           f"resource_kind must survive projection: {syms[by_name['c']]}")

    # -- op vocabulary + same-symbol references share an index ---------------
    ops = [i for b in f["blocks"] for i in b["instrs"]]
    op_names = [i["op"] for i in ops]
    for expected in ("acquire", "borrow_start", "use", "borrow_end",
                     "move_into", "invoke", "return"):
        expect(expected in op_names, f"op {expected!r} missing: {op_names}")
    bs = next(i for i in ops if i["op"] == "borrow_start")
    be = next(i for i in ops if i["op"] == "borrow_end")
    expect(bs["owner"] == be["owner"] == by_name["c"]
           and bs["binding"] == be["binding"] == by_name["r"],
           "borrow start/end must reference the same owner/binding indices")
    mv = next(i for i in ops if i["op"] == "move_into")
    expect(mv["src"] == by_name["c"] and mv["dst"] == by_name["d"],
           f"move_into must link src=c dst=d by index: {mv}")
    inv = next(i for i in ops if i["op"] == "invoke")
    expect(inv["callee"] == "Store"
           and inv["args"] == [{"sym": by_name["d"], "effect": "consume"}],
           f"invoke args must carry (sym index, effect): {inv}")

    # -- buffers ride along on the second function ---------------------------
    g = doc["functions"][1]
    ab = next(i for b in g["blocks"] for i in b["instrs"]
              if i["op"] == "acquire_buffer")
    expect(ab["buffer"]["mode"] == "scratch" and ab["buffer"]["line"] == 14,
           f"acquire_buffer must carry the resolved policy: {ab['buffer']}")

    # -- determinism ----------------------------------------------------------
    expect(_doc() == doc, "two projections of the same module must be equal")
    dump = json.dumps(doc, indent=2, sort_keys=True)
    expect(dump == json.dumps(_doc(), indent=2, sort_keys=True),
           "sorted-key dumps must be byte-identical")

    for msg in fails:
        print(f"CFG-JSON FAIL: {msg}")
    print(f"cfg_json: {checks - len(fails)}/{checks} CFG-seam checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
