#!/usr/bin/env python3
"""Unit tests for the interprocedural ownership-summary solver (P-005 D5.0).

Pure-Python, no extractor, no dotnet: hand-author method skeletons and assert the
solved Method Ownership Summaries. Exercises the transfer lattice (must/may/no/
unknown), the depth-capped bottom-up resolution, recursion/SCC convergence, the
extern boundary, return-kind resolution (fresh/aliasOf/aliased), and the
`summaries[]` serialization.

Run:  python tests/test_ownership.py
      python tests/run_tests.py   (as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownership import (
    MethodSkeleton,
    ParamSkeleton,
    PathAction,
    ReturnSkeleton,
    Transfer,
    join,
    solve,
    solve_with_log,
)


def _p(index, *paths, name="s", disposable=True, escapes=False):
    return ParamSkeleton(index, name, disposable, tuple(paths), escapes)


def _m(key, *params, ret=None):
    return MethodSkeleton(key, tuple(params), ret or ReturnSkeleton())


def _t(summaries, key, i):
    return summaries[key].params[i].transfer


def run() -> int:
    fails: list[str] = []
    checks = 0

    def expect(cond, msg):
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    # --- the join lattice ---------------------------------------------------
    expect(join(Transfer.MUST, Transfer.MUST) == Transfer.MUST, "must|must=must")
    expect(join(Transfer.NO, Transfer.NO) == Transfer.NO, "no|no=no")
    expect(join(Transfer.MUST, Transfer.NO) == Transfer.MAY, "must|no=may")
    expect(join(Transfer.NO, Transfer.MUST) == Transfer.MAY, "join is commutative")
    expect(join(Transfer.MUST, Transfer.MAY) == Transfer.MAY, "must|may=may")
    expect(join(Transfer.MAY, Transfer.NO) == Transfer.MAY, "may|no=may")
    expect(join(Transfer.MUST, Transfer.UNKNOWN) == Transfer.UNKNOWN, "unknown absorbs (must)")
    expect(join(Transfer.NO, Transfer.UNKNOWN) == Transfer.UNKNOWN, "unknown absorbs (no)")

    # --- direct local evidence ----------------------------------------------
    s = solve([_m("Sink", _p(0, PathAction("dispose")))])
    expect(_t(s, "Sink", 0) == Transfer.MUST, "direct dispose -> must")

    s = solve([_m("Log", _p(0, PathAction("borrow")))])
    expect(_t(s, "Log", 0) == Transfer.NO, "borrow -> no")

    s = solve([_m("Noop", _p(0))])  # no paths recorded
    expect(_t(s, "Noop", 0) == Transfer.NO, "no actions -> kept (no)")

    s = solve([_m("Adopt", _p(0, PathAction("adopt")))])
    expect(_t(s, "Adopt", 0) == Transfer.MUST, "store in owning field -> must")

    # a non-disposable param is never a transfer
    s = solve([_m("F", _p(0, name="n", disposable=False))])
    expect(_t(s, "F", 0) == Transfer.NO, "non-disposable param -> no")

    # --- partial (path-dependent) consume -> may ----------------------------
    s = solve([_m("Maybe", _p(0, PathAction("dispose"), PathAction("borrow")))])
    expect(_t(s, "Maybe", 0) == Transfer.MAY, "dispose on one path, keep on other -> may")

    # --- interprocedural forwarding -----------------------------------------
    # Caller forwards its arg to a must-consumer -> must.
    s = solve([
        _m("Caller", _p(0, PathAction("forward", "Sink", 0))),
        _m("Sink", _p(0, PathAction("dispose"))),
    ])
    expect(_t(s, "Caller", 0) == Transfer.MUST, "forward to a consumer -> must")

    # Caller forwards to a borrow-only callee -> no.
    s = solve([
        _m("Caller", _p(0, PathAction("forward", "Reader", 0))),
        _m("Reader", _p(0, PathAction("borrow"))),
    ])
    expect(_t(s, "Caller", 0) == Transfer.NO, "forward to a borrower -> no")

    # A two-hop chain within the default cap resolves.
    s = solve([
        _m("A", _p(0, PathAction("forward", "B", 0))),
        _m("B", _p(0, PathAction("forward", "C", 0))),
        _m("C", _p(0, PathAction("dispose"))),
    ])
    expect(_t(s, "A", 0) == Transfer.MUST, "2-hop forward chain resolves to must")

    # --- the extern boundary ------------------------------------------------
    s = solve([_m("Caller", _p(0, PathAction("forward", "Extern", 0)))])  # Extern unsummarized
    expect(_t(s, "Caller", 0) == Transfer.UNKNOWN, "forward to extern -> unknown")

    # --- depth cap ----------------------------------------------------------
    chain = [
        _m("A", _p(0, PathAction("forward", "B", 0))),
        _m("B", _p(0, PathAction("forward", "C", 0))),
        _m("C", _p(0, PathAction("dispose"))),
    ]
    s2, log = solve_with_log(chain, cap=2)
    expect(s2["A"].params[0].transfer == Transfer.UNKNOWN, "chain past cap=2 -> unknown")
    expect(any("C#0" in e for e in log), "depth cap is logged, not silent")

    # --- recursion / SCC convergence ----------------------------------------
    # Mutual recursion that never disposes -> no (and, crucially, terminates).
    s = solve([
        _m("F", _p(0, PathAction("forward", "G", 0))),
        _m("G", _p(0, PathAction("forward", "F", 0))),
    ])
    expect(_t(s, "F", 0) == Transfer.NO, "mutual recursion w/o dispose -> no (terminates)")

    # Self-recursion with a base-case dispose: provable on some but not all paths
    # through the recursion -> may (precision-safe; never a hard must).
    s = solve([
        _m("Rec", _p(0, PathAction("dispose"), PathAction("forward", "Rec", 0))),
    ])
    expect(_t(s, "Rec", 0) == Transfer.MAY, "self-recursion + base dispose -> may")

    # --- return-kind resolution ---------------------------------------------
    s = solve([_m("Factory", ret=ReturnSkeleton("fresh"))])
    expect(s["Factory"].returns == "fresh", "fresh return")

    s = solve([_m("Wrap", _p(0, PathAction("return")), ret=ReturnSkeleton("aliasOf", arg=0))])
    expect(s["Wrap"].returns == "aliasOf:0", "aliasOf return kind")
    expect(_t(s, "Wrap", 0) == Transfer.MUST, "an aliased-out param also leaves the caller")

    s = solve([_m("Getter", ret=ReturnSkeleton("aliased"))])
    expect(s["Getter"].returns == "aliased", "aliased (borrowed) return")

    # forward-return: returns the result of a fresh factory -> fresh
    s = solve([
        _m("Make", ret=ReturnSkeleton("forward", callee="Inner")),
        _m("Inner", ret=ReturnSkeleton("fresh")),
    ])
    expect(s["Make"].returns == "fresh", "forward-return propagates fresh")

    s = solve([_m("Void")])
    expect(s["Void"].returns == "none", "no owned return -> none")

    # --- serialization ------------------------------------------------------
    s = solve([
        _m("Acme.Io.Copy",
           _p(0, PathAction("dispose"), name="src"),
           _p(1, PathAction("borrow"), name="dst"),
           ret=ReturnSkeleton("none")),
    ])
    d = s["Acme.Io.Copy"].to_dict()
    expect(d["method"] == "Acme.Io.Copy", "to_dict carries the method key")
    expect(d["params"][0]["transfer"] == "must", "to_dict serializes transfer value")
    expect(d["params"][1]["transfer"] == "no", "to_dict serializes the second param")
    expect(d["returns"] == {"owned": "none"}, "to_dict serializes the return")
    expect(d["source"] == "inferred", "to_dict defaults source to inferred")

    for f in fails:
        print(f"OWNERSHIP FAIL: {f}")
    print(f"ownership: {checks - len(fails)}/{checks} D5.0 summary checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
