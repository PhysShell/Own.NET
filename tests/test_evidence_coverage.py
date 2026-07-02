#!/usr/bin/env python3
"""
Evidence coverage for flow diagnostics (execution-surfaces ADR §3/§5).

The `diagnostics.Evidence` machinery (structured secondary locations rendered as
`note:` lines / SARIF codeFlows) existed but no flow diagnostic populated it —
every finding shipped `evidence == ()`. This pins the first three producers wired
into `ownlang/analysis.py`, one per acceptance class:

  * OWN015 — a stack-backed buffer escapes by return  (escape / lifetime)
  * OWN016 — a stack-backed buffer consumed into a longer-lived owner  (escape)
  * OWN005 — use / return after move                  (use-after-move)

Two contracts per code:
  1. the structured slice: `Diagnostic.evidence` carries the exact
     (line, role, label) steps for the acquire->escape / move->use path;
  2. the human render: `Diagnostic.render()` appends those steps as ordered
     `note:` lines after the header (the presentation the CLI already emits).

Plus the merge-point honesty check: a resource moved at different lines on
different paths and used after the merge is labelled "one of several paths",
never a single line only one path took — and the empty-evidence invariant still
holds for a finding with no slice (OWN001 leak).

Run:  python tests/test_evidence_coverage.py
      python tests/run_tests.py     (as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import analyze
from ownlang.cfg import build_cfg, collect_policies, collect_signatures
from ownlang.diagnostics import Diagnostic
from ownlang.parser import parse


def _diags(src: str) -> list[Diagnostic]:
    """Full parse -> CFG -> analyze pipeline, flattened to one diagnostic list."""
    mod = parse(src)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    out: list[Diagnostic] = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, pols)
        out += d1 + analyze(cfg)
    return out


def _pick(src: str, code: str) -> Diagnostic:
    for d in _diags(src):
        if d.code == code:
            return d
    raise AssertionError(f"expected a {code} diagnostic, got "
                         f"{sorted({d.code for d in _diags(src)})}")


# --- fixtures (line numbers matter: they are the evidence anchors) ----------

_OWN015 = (
    "module M\n"           # 1
    "fn f() -> Buffer {\n"  # 2
    "    let b = Buffer.stack(64);\n"  # 3  <- allocated
    "    return b;\n"       # 4  <- escapes
    "}\n"                   # 5
)

_OWN016 = (
    "module M\n"                        # 1
    "extern fn Store(consume Buffer);\n"  # 2
    "fn f(n: int) {\n"                  # 3
    "    let b = Buffer.scratch(n);\n"  # 4  <- allocated
    "    Store(b);\n"                   # 5  <- consumed
    "}\n"                               # 6
)

_OWN005 = (
    "module M\n"                              # 1
    "resource Conn { acquire open release close }\n"  # 2
    "fn f() {\n"                              # 3
    "    let c = acquire Conn(1);\n"          # 4
    "    let d = move c;\n"                   # 5  <- moved
    "    use c;\n"                            # 6  <- use after move
    "    release d;\n"                        # 7
    "}\n"                                     # 8
)

# a second move of an already-moved handle is itself an OWN005; the *later*
# use-after-move must still be explained by the FIRST (real) move site, not by
# the failed second move (Codex P2 regression).
_OWN005_DOUBLE = (
    "module M\n"                              # 1
    "resource Conn { acquire open release close }\n"  # 2
    "fn f() {\n"                              # 3
    "    let a = acquire Conn(1);\n"          # 4
    "    let b = move a;\n"                   # 5  <- the real move
    "    let c = move a;\n"                   # 6  <- failed second move (OWN005)
    "    use a;\n"                            # 7  <- use after move (OWN005)
    "    release b;\n"                        # 8
    "    release c;\n"                        # 9
    "}\n"                                     # 10
)

# moved on both arms at *different* lines, then used after the merge: the move
# site is genuinely one-of-N, so the evidence must not name a single path's line
# as if it were certain.
_OWN005_MERGE = (
    "module M\n"                              # 1
    "resource Conn { acquire open release close }\n"  # 2
    "fn f(n: int) {\n"                        # 3
    "    let c = acquire Conn(1);\n"          # 4
    "    if (n) {\n"                          # 5
    "        let x = move c;\n"               # 6
    "    } else {\n"                          # 7
    "        let y = move c;\n"               # 8
    "    }\n"                                 # 9
    "    use c;\n"                            # 10 <- use after move (either path)
    "}\n"                                     # 11
)


def run() -> int:
    fails: list[str] = []
    checks = 0

    def expect(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    # -- OWN015: acquire -> escape, both steps present and ordered -----------
    d = _pick(_OWN015, "OWN015")
    steps = [(e.line, e.role, e.label) for e in d.evidence]
    expect(steps == [
        (3, "acquired", "'b' allocated here"),
        (4, "escaped", "escapes the function by return here"),
    ], f"OWN015 evidence slice wrong: {steps}")
    rendered = d.render("<input>")
    expect(rendered.splitlines()[1:] == [
        "  note: 'b' allocated here at <input>:3",
        "  note: escapes the function by return here at <input>:4",
    ], f"OWN015 render notes wrong:\n{rendered}")

    # -- OWN016: acquire -> consumed-by-call --------------------------------
    d = _pick(_OWN016, "OWN016")
    steps = [(e.line, e.role, e.label) for e in d.evidence]
    expect(steps == [
        (4, "acquired", "'b' allocated here"),
        (5, "consumed", "consumed by 'Store' here"),
    ], f"OWN016 evidence slice wrong: {steps}")

    # -- OWN005: exact move site --------------------------------------------
    d = _pick(_OWN005, "OWN005")
    steps = [(e.line, e.role, e.label) for e in d.evidence]
    expect(steps == [(5, "moved", "moved here")],
           f"OWN005 evidence slice wrong: {steps}")
    rendered = d.render("<input>")
    expect(rendered.splitlines()[-1] == "  note: moved here at <input>:5",
           f"OWN005 render note wrong:\n{rendered}")

    # -- OWN005 double move: later use is explained by the FIRST move site ---
    own005 = [d for d in _diags(_OWN005_DOUBLE) if d.code == "OWN005"]
    use_after = [d for d in own005 if d.line == 7]
    expect(len(use_after) == 1
           and [(e.line, e.label) for e in use_after[0].evidence]
           == [(5, "moved here")],
           "use-after-move must point at the first (real) move site, not the "
           f"failed second move: "
           f"{[(d.line, [(e.line, e.label) for e in d.evidence]) for d in own005]}")

    # -- OWN005 at a merge: the move site is one-of-N, labelled honestly ----
    d = _pick(_OWN005_MERGE, "OWN005")
    expect(len(d.evidence) == 1 and not d.evidence[0].label.endswith("here")
           and "one of several paths" in d.evidence[0].label,
           f"OWN005 merge evidence should be marked inexact: "
           f"{[(e.line, e.label) for e in d.evidence]}")

    # -- empty-evidence invariant: a leak (OWN001) carries no slice ---------
    d = _pick("module M\nfn f(n: int){ let b = Buffer.scratch(n); }\n", "OWN001")
    expect(d.evidence == (), "OWN001 leak must not carry evidence (unchanged)")
    expect("\n  note:" not in d.render("<input>"),
           "a diagnostic with no evidence must render without note: lines")

    for f in fails:
        print(f"EVIDENCE FAIL: {f}")
    print(f"evidence: {checks - len(fails)}/{checks} evidence-coverage checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
