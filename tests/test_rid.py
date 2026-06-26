#!/usr/bin/env python3
"""
D5.4 step 0 — the RID (resource-id) indirection layer.

Resource state in the core flow analysis (`ownlang/analysis.py`) now lives on a
**RID**, an obligation a *handle* (a local/param `Symbol`) denotes through
`State.handle_rid`. Step 0 is a deliberate *no-op*: every handle maps 1:1 to its
own RID, keyed by the originating symbol's identity (`RID == id(sym)`), so the
analysis is byte-for-byte the pre-RID behaviour. The whole green corpus is the
behaviour-preservation proof; these checks pin the new *layer* directly so D5.4
step 1 (`alias_join`: a second handle joins an existing RID) builds on a tested
invariant rather than re-deriving it.

What is locked here:
  * `rid_of` defaults to `id(sym)` for an un-minted handle (the 1:1 identity).
  * `mint` records the handle->RID mapping and returns `id(sym)`.
  * `_join_handle_rid` unions agreeing maps and *asserts* on a conflicting one
    (the step-0 single-mapping invariant — the analogue of `join`'s loan assert).
  * end-to-end: a 1:1 acquire still leaks (OWN001) when dropped and stays silent
    when released — i.e. routing every `var` access through the RID layer changed
    no observable behaviour.

Run:  python tests/test_rid.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import State, _join_handle_rid, analyze
from ownlang.cfg import Kind, Symbol, build_cfg, collect_signatures
from ownlang.diagnostics import Severity
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

_PRELUDE = (
    "module Rid\n"
    "resource Conn { acquire open release close }\n"
)


def _codes(body: str) -> set[str]:
    """Error codes for one function body (Conn prelude prepended)."""
    try:
        mod = parse(_PRELUDE + body)
    except (ParseError, LexError):
        return {"OWN020"}
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    out: set[str] = set()
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        out |= {d.code for d in (d1 + d2) if d.severity == Severity.ERROR}
    return out


def _check(name: str, ok: bool, detail: str = "") -> int:
    mark = "ok  " if ok else "FAIL"
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"  {mark} {name}{suffix}")
    return 0 if ok else 1


def run() -> int:
    print("rid (D5.4 step 0 — RID indirection):")
    fails = 0

    # -- rid_of: an un-minted handle denotes its own resource (1:1 identity) ----
    st = State()
    a = Symbol("a", Kind.OWNED, 1)
    fails += _check("rid_of defaults to id(sym)",
                    st.rid_of(a) == id(a) and not st.handle_rid,
                    "un-minted handle should resolve to id(sym) without recording")

    # -- mint: records the mapping, returns id(sym), stays 1:1 -----------------
    rid = st.mint(a)
    fails += _check("mint returns id(sym) and records it",
                    rid == id(a) and st.handle_rid[id(a)] == id(a)
                    and st.rid_of(a) == id(a))

    b = Symbol("b", Kind.OWNED, 2)
    fails += _check("distinct handles mint distinct RIDs",
                    st.mint(b) != rid and st.rid_of(b) != st.rid_of(a),
                    "1:1 means no two un-aliased handles share a RID")

    # -- copy carries the handle->RID map --------------------------------------
    st2 = st.copy()
    fails += _check("copy() preserves handle_rid",
                    st2.handle_rid == st.handle_rid
                    and st2.handle_rid is not st.handle_rid)

    # -- _join_handle_rid: agreeing maps union; conflicting maps assert ---------
    left = {id(a): id(a)}
    right = {id(b): id(b)}
    merged = _join_handle_rid(left, right)
    fails += _check("_join_handle_rid unions disjoint maps",
                    merged == {id(a): id(a), id(b): id(b)})

    overlap = _join_handle_rid({id(a): id(a)}, {id(a): id(a)})
    fails += _check("_join_handle_rid keeps an agreeing shared mapping",
                    overlap == {id(a): id(a)})

    conflicted = False
    try:
        # the same handle resolving to two different RIDs violates the step-0
        # single-mapping invariant — must be loud, not silently merged.
        _join_handle_rid({id(a): id(a)}, {id(a): id(b)})
    except AssertionError:
        conflicted = True
    fails += _check("_join_handle_rid asserts on a conflicting mapping",
                    conflicted, "a handle -> two RIDs must raise, not pick a side")

    # -- end-to-end behaviour is unchanged by the indirection ------------------
    leak = _codes("fn f(){ let c = acquire Conn(1); }")
    fails += _check("1:1 acquire still leaks (OWN001)",
                    leak == {"OWN001"}, f"got {leak}")

    clean = _codes("fn f(){ let c = acquire Conn(1); release c; }")
    fails += _check("1:1 acquire+release stays silent",
                    clean == set(), f"got {clean}")

    double = _codes("fn f(){ let c = acquire Conn(1); release c; release c; }")
    fails += _check("1:1 double-release still OWN003",
                    "OWN003" in double, f"got {double}")

    # Return/escape path: the refactor routes the Return state-write and
    # leak_check's `exclude` through rid_of, so cover them directly. Returning an
    # owned resource escapes its RID (clean); a *sibling* RID left owned still
    # leaks — proving the exclude spares only the returned RID, not all of them.
    escape = _codes("fn f() -> Conn { let c = acquire Conn(1); return c; }")
    fails += _check("returning an owned resource escapes clean",
                    escape == set(), f"got {escape}")

    leak_before_ret = _codes(
        "fn f() -> Conn { let a = acquire Conn(1); let c = acquire Conn(1); "
        "return c; }")
    fails += _check("a sibling RID still leaks before return (OWN001)",
                    leak_before_ret == {"OWN001"}, f"got {leak_before_ret}")

    n = 13
    print(f"rid: {n - fails}/{n} RID-layer checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
