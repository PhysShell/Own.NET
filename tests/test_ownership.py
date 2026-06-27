#!/usr/bin/env python3
"""Unit tests for the interprocedural ownership-summary solver (P-005 D5.0).

Pure-Python, no extractor, no dotnet: hand-author method skeletons and assert the
solved Method Ownership Summaries. Exercises the transfer lattice (must/may/no/
unknown), the summary fixpoint over the call graph's SCC condensation (deep chains
resolve without a depth cap; recursion is solved, not truncated), the extern
boundary and its log, return-kind resolution (fresh/aliasOf/aliased), and the
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

    # Sparse skeleton: a wrapper `Create(cmd, reader)` lists only the disposable
    # param at logical index 1. Forwarding to arg=1 must resolve by `.index`, not by
    # tuple offset (else it falls off the end -> wrongly `unknown`). (Codex P2.)
    s = solve([
        _m("Caller", _p(0, PathAction("forward", "Create", 1), name="x")),
        _m("Create", _p(1, PathAction("dispose"), name="reader")),  # only index 1 listed
    ])
    expect(_t(s, "Caller", 0) == Transfer.MUST,
           "forward resolves the callee param by logical index, not tuple offset")

    # --- the extern boundary ------------------------------------------------
    s = solve([_m("Caller", _p(0, PathAction("forward", "Extern", 0)))])  # Extern unsummarized
    expect(_t(s, "Caller", 0) == Transfer.UNKNOWN, "forward to extern -> unknown")

    # --- deep chains: no depth cap (the SCC condensation bounds the work) -----
    # A 4-hop forward chain a former depth-3 cap would have degraded to `unknown`
    # now resolves end-to-end: the consumer at the bottom propagates up exactly.
    deep = [
        _m("A", _p(0, PathAction("forward", "B", 0))),
        _m("B", _p(0, PathAction("forward", "C", 0))),
        _m("C", _p(0, PathAction("forward", "D", 0))),
        _m("D", _p(0, PathAction("dispose"))),
    ]
    s2, log = solve_with_log(deep)
    expect(s2["A"].params[0].transfer == Transfer.MUST, "deep chain resolves (no cap)")
    expect(log == [], "a fully-summarized graph leaves nothing unresolved")

    # The log is not silent about the one residual unknown: an extern (unsummarized)
    # forward boundary is named, so a run can see exactly what it could not resolve.
    _, log2 = solve_with_log([_m("Caller", _p(0, PathAction("forward", "Extern", 0)))])
    expect(any("Extern#0" in e for e in log2), "extern forward is logged, not silent")

    # The return chase logs its extern boundary too (a separate code path from the
    # param forward above) — a forward-return to an unsummarized callee.
    s3, log3 = solve_with_log([_m("Caller", ret=ReturnSkeleton("forward", callee="Extern"))])
    expect(s3["Caller"].returns == "unknown", "forward-return to extern -> unknown")
    expect(any("return Extern" in e for e in log3), "extern forward-return is logged")

    # A deep but acyclic chain must not blow Python's recursion limit (the solver is
    # iterative end to end; a RecursionError here would, via the bridge's catch-all,
    # drop the WHOLE input's MOS to empty over one long chain). 3000 > default limit.
    N = 3000
    param_chain = [
        _m(f"L{i}", _p(0, PathAction("forward", f"L{i + 1}", 0))) for i in range(N)
    ] + [_m(f"L{N}", _p(0, PathAction("dispose")))]
    expect(_t(solve(param_chain), "L0", 0) == Transfer.MUST,
           "deep param forward chain resolves without RecursionError")
    ret_chain = [
        _m(f"R{i}", ret=ReturnSkeleton("forward", callee=f"R{i + 1}")) for i in range(N)
    ] + [_m(f"R{N}", ret=ReturnSkeleton("fresh"))]
    expect(solve(ret_chain)["R0"].returns == "fresh",
           "deep forward-return chain resolves without RecursionError")

    # --- recursion / SCC convergence ----------------------------------------
    # Mutual recursion that never disposes -> no (the cycle seeds at bottom and the
    # fixpoint settles at `no`; crucially, it terminates).
    s = solve([
        _m("F", _p(0, PathAction("forward", "G", 0))),
        _m("G", _p(0, PathAction("forward", "F", 0))),
    ])
    expect(_t(s, "F", 0) == Transfer.NO, "mutual recursion w/o dispose -> no (terminates)")

    # Self-recursion with a base-case dispose: every *terminating* path disposes (the
    # recursive edge defers, it does not keep), so the fixpoint resolves it to `must`.
    # The old depth-broken resolver injected a spurious `no` at the cycle and got the
    # weaker `may`; the least-fixpoint over the lattice is exact here.
    s = solve([
        _m("Rec", _p(0, PathAction("dispose"), PathAction("forward", "Rec", 0))),
    ])
    expect(_t(s, "Rec", 0) == Transfer.MUST, "self-recursion + base dispose -> must")

    # Mutual recursion where the only ground is a dispose deep in the cycle: the
    # fixpoint carries it across the SCC, where breaking the cycle at `no` would not.
    s = solve([
        _m("P", _p(0, PathAction("forward", "Q", 0))),
        _m("Q", _p(0, PathAction("dispose"), PathAction("forward", "P", 0))),
    ])
    expect(_t(s, "P", 0) == Transfer.MUST, "mutual recursion grounded by dispose -> must")
    expect(_t(s, "Q", 0) == Transfer.MUST, "the grounding method is must too")

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

    # an unrecognised return kind fails closed to unknown, never silently "none"
    # (which would hide owned-return info). (CodeRabbit)
    s = solve([_m("Weird", ret=ReturnSkeleton("bogus"))])
    expect(s["Weird"].returns == "unknown", "unrecognised return kind -> unknown (fail closed)")

    # forward-return of a callee's aliasOf:<i>: <i> is in the callee's param space and
    # cannot be remapped to our args without the call's arg mapping (a D5.4 concern),
    # so it degrades to unknown rather than propagating a wrong index. (Codex P2.)
    s = solve([
        _m("Outer", _p(0, name="a"), _p(1, PathAction("forward", "Inner", 0), name="b"),
           ret=ReturnSkeleton("forward", callee="Inner")),
        _m("Inner", _p(0, PathAction("return")), ret=ReturnSkeleton("aliasOf", arg=0)),
    ])
    expect(s["Outer"].returns == "unknown",
           "aliasOf through a forward-return degrades to unknown (no mis-mapped index)")

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

    # duplicate method keys must fail fast: key collision-freedom is an open design
    # question, and silently keeping the last would make summaries input-order
    # dependent and corrupt the call graph. (CodeRabbit)
    raised = False
    try:
        solve([_m("Dup", _p(0, PathAction("dispose"))), _m("Dup", _p(0, PathAction("borrow")))])
    except ValueError:
        raised = True
    expect(raised, "duplicate method keys raise ValueError (fail fast)")

    for f in fails:
        print(f"OWNERSHIP FAIL: {f}")
    print(f"ownership: {checks - len(fails)}/{checks} D5.0 summary checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
