#!/usr/bin/env python3
"""
Flow-diagnostic SARIF projection (`ownlang.diag_sarif`).

The C# extractor path emits SARIF via `ownir.build_sarif`; this pins the parallel
`.own` flow-diagnostic path added so `check --format sarif` reaches GitHub code
scanning. It asserts the log shape (schema / driver / rules), that a diagnostic's
structured evidence surfaces as BOTH `relatedLocations` and an ordered `codeFlows`
slice, that an evidence-free diagnostic carries neither, the "no empty
artifactLocation.uri" invariant a code-scanning consumer requires, and the
severity->level mapping.

Run:  python tests/test_diag_sarif.py
      python tests/run_tests.py     (as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import analyze
from ownlang.cfg import build_cfg, collect_policies, collect_signatures
from ownlang.diag_sarif import build_sarif
from ownlang.diagnostics import Diagnostic
from ownlang.parser import parse


def _diags(src: str) -> list[Diagnostic]:
    mod = parse(src)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    out: list[Diagnostic] = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, pols)
        out += d1 + analyze(cfg)
    return out


def _result_for(sarif: dict, code: str) -> dict:
    for r in sarif["runs"][0]["results"]:
        if r["ruleId"] == code:
            return r
    raise AssertionError(f"no SARIF result for {code}")


def _all_uris(node: object) -> list[str]:
    """Every artifactLocation.uri anywhere in the log (for the empty-uri check)."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "artifactLocation" and isinstance(v, dict):
                out.append(v.get("uri", ""))
            else:
                out.extend(_all_uris(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_all_uris(v))
    return out


_ESCAPE = (
    "module M\n"           # 1
    "fn f() -> Buffer {\n"  # 2
    "    let b = Buffer.stack(64);\n"  # 3  <- allocated
    "    return b;\n"       # 4  <- escapes
    "}\n"                   # 5
)

_LEAK = (
    "module M\n"                              # 1
    "resource Conn { acquire open release close }\n"  # 2
    "fn f() {\n"                              # 3
    "    let c = acquire Conn(1);\n"          # 4  <- acquired
    "    use c;\n"                            # 5
    "}\n"                                     # 6
)


def run() -> int:
    fails: list[str] = []
    checks = 0

    def expect(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    esc = build_sarif(_diags(_ESCAPE), "esc.own")

    # -- log shape ----------------------------------------------------------
    expect(esc["$schema"].endswith("sarif-schema-2.1.0.json") and esc["version"]
           == "2.1.0", "SARIF log must declare the 2.1.0 schema/version")
    driver = esc["runs"][0]["tool"]["driver"]
    expect(driver["name"] == "Owen", "tool driver must be Owen")
    expect([r["id"] for r in driver["rules"]] == ["OWN015"],
           f"rules catalogue must list the codes present: {driver['rules']}")

    # -- OWN015: evidence -> relatedLocations + ordered codeFlows -----------
    r = _result_for(esc, "OWN015")
    expect(r["level"] == "error" and r["locations"][0]["physicalLocation"]["region"]
           ["startLine"] == 4, "OWN015 result anchors at the return line")
    related = [(x["physicalLocation"]["region"]["startLine"], x["message"]["text"])
               for x in r.get("relatedLocations", [])]
    expect(related == [(3, "'b' allocated here"),
                       (4, "escapes the function by return here")],
           f"OWN015 relatedLocations wrong: {related}")
    flow = [(loc["location"]["physicalLocation"]["region"]["startLine"],
             loc["location"]["message"]["text"])
            for loc in r["codeFlows"][0]["threadFlows"][0]["locations"]]
    expect(flow == related, f"OWN015 codeFlows must mirror the ordered slice: {flow}")

    # -- OWN001 leak: acquire site rides along too --------------------------
    leak = build_sarif(_diags(_LEAK), "leak.own")
    r = _result_for(leak, "OWN001")
    flow = [(loc["location"]["physicalLocation"]["region"]["startLine"],
             loc["location"]["message"]["text"])
            for loc in r["codeFlows"][0]["threadFlows"][0]["locations"]]
    expect(flow == [(4, "'c' acquired here")],
           f"OWN001 codeFlows must carry the acquire site: {flow}")

    # -- an evidence-free diagnostic carries neither key --------------------
    dbl = build_sarif(_diags(
        "module M\nresource Conn { acquire open release close }\n"
        "fn f(){ let c = acquire Conn(1); release c; release c; }\n"), "d.own")
    r = _result_for(dbl, "OWN003")
    expect("codeFlows" not in r and "relatedLocations" not in r,
           "an evidence-free diagnostic must not carry codeFlows/relatedLocations")

    # -- no empty artifactLocation.uri anywhere (code-scanning invariant) ---
    uris = _all_uris(esc) + _all_uris(leak)
    expect(uris and all(uris), f"every artifactLocation.uri must be non-empty: {uris}")

    # -- severity override sets the result level ----------------------------
    warn = build_sarif(_diags(_ESCAPE), "esc.own", severity="warning")
    expect(_result_for(warn, "OWN015")["level"] == "warning",
           "severity='warning' must set the result level to warning")

    for f in fails:
        print(f"DIAG-SARIF FAIL: {f}")
    print(f"diag_sarif: {checks - len(fails)}/{checks} SARIF projection checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
