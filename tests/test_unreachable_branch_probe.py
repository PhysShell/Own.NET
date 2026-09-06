#!/usr/bin/env python3
"""The oracle probe for branches no facts document can reach (P-022 #259 cp5).

A handful of BR-V4 wordings are unreachable end to end. The routing table never
mints a handle that would take them, or the analysis never reports a verdict
that would select them, so no facts document — synthetic or otherwise —
produces one. They are still the reference's wordings, and the port carries
controls for each; the question this module answers is **where those controls'
expected text comes from**.

Not from reading `ownlang/ownir.py`. From the reference itself: `check_facts`
is run with its lowering and its core substituted, so the oracle can be asked
about a state its own inputs cannot construct. That is a *probe*, not a
fixture, and the distinction is worth keeping straight:

* it proves the reference's wording for a given handle record and diagnostic;
* it proves **nothing** about reachability, ordering, or the pipeline around
  the branch — the substitution removes exactly those;
* so it cannot replace a golden anywhere a golden is possible, and it is used
  only where one is not.

`tests/fixtures/unreachable_branches.json` is the recorded answer. The Rust
controls read it (`own-bridge/src/verdict.rs`, `own-analysis/src/effect.rs`)
rather than carrying their own copy of the text, so "the oracle said so" is a
re-runnable fact and the two sides cannot drift into agreeing with each other
instead of with Python.

Run:  python tests/test_unreachable_branch_probe.py            (verify)
      python tests/test_unreachable_branch_probe.py --write    (re-probe)
      python tests/run_tests.py                                (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ownlang.__main__ as driver
import ownlang.ownir as ownir
from ownlang.diagnostics import Diagnostic
from ownlang.effects import EffectStorm

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "unreachable_branches.json")
# Bump when a probe is added, removed or re-shaped; the Rust controls read the
# same file and assert the same version.
PROBE_VERSION = 1


def _probe(handles: dict[str, dict[str, Any]], diags: list[Diagnostic]) -> list[str]:
    """Run `check_facts` over a hand-built lowering and a hand-built core
    result, and return the messages it synthesized.

    Both seams are restored in a `finally`, so a failure here cannot leak a
    patched module into another test in the same process.
    """
    original_to_module, original_check = ownir.to_module, driver.check_module
    ownir.to_module = lambda facts, notes=None, advisories=None: (None, handles)
    driver.check_module = lambda module: diags
    try:
        return [f.message for f in ownir.check_facts({"module": "Probe"})]
    finally:
        ownir.to_module, driver.check_module = original_to_module, original_check


def _record(**over: Any) -> dict[str, Any]:
    return {"component": "C.M", "file": "A.cs", **over}


def probe_all() -> dict[str, str]:
    """Every unreachable wording, keyed by the control that carries it."""
    out: dict[str, str] = {}

    # The two flow-local fallbacks: a code with no wording of its own keeps the
    # CORE diagnostic's message after a colon. Unreachable because the nine-op
    # OwnIR flow vocabulary raises only codes that HAVE a wording.
    handles = {
        "loc_0": _record(resource="flow-local", event="s", line=4, pool=False,
                         ever_released=False),
        "loc_1": _record(resource="flow-local", event="s", line=4, pool=True,
                         ever_released=False),
    }
    diags = [Diagnostic("OWN005", "moved 's' at A.cs:9", 9, subject=f"{h}#4")
             for h in ("loc_0", "loc_1")]
    plain, pooled = _probe(handles, diags)
    out["flow_local_fallback_plain"] = plain
    out["flow_local_fallback_pooled"] = pooled

    # The DI lifetime phrases the engine cannot select: `transient` is the
    # shortest region, so no subscriber it could outlive exists, and a lifetime
    # outside the three never reaches `di_source_life` at all.
    handles = {
        f"cap_{i}": _record(file="Vm.cs", component="Vm", event="src.E", handler="OnE",
                            line=7, source="injected", source_type="Src",
                            di_source_life=life)
        for i, life in enumerate(("transient", "gremlin"))
    }
    diags = [Diagnostic("OWN014", "escape", 7, subject=f"cap_{i}#7") for i in range(2)]
    transient, unknown = _probe(handles, diags)
    out["own014_di_transient"] = transient
    out["own014_di_unknown_lifetime"] = unknown

    # The capture route's named-source origin: routing R3 mints a handle only
    # for a source with a declared capture region, and `static` is the only one.
    handles = {"cap_0": _record(file="Vm.cs", component="Vm", resource="capture",
                                event="svc.E", handler="OnE", line=9,
                                source="container")}
    diags = [Diagnostic("OWN014", "escape", 9, subject="cap_0#9")]
    (named,) = _probe(handles, diags)
    out["own014_capture_named_source"] = named

    # The effect message's `via` clause, guarded on a chain longer than one hop.
    # Unreachable because a storm only words "derives from" when it walked at
    # least one reference, which makes the chain two entries or more. No
    # substitution needed: the dataclass is the reference's own value.
    out["eff001_single_hop_chain_has_no_via"] = EffectStorm(
        component="W", dep="cfg", origin="opts", origin_kind="object",
        file="W.tsx", line=5, decl_line=2, path=("opts",)).message
    out["eff001_multi_hop_chain_has_via"] = EffectStorm(
        component="W", dep="cfg", origin="opts", origin_kind="object",
        file="W.tsx", line=5, decl_line=2, path=("cfg", "opts")).message
    return out


def _document() -> dict[str, Any]:
    return {
        "comment": ("GENERATED by tests/test_unreachable_branch_probe.py --write; do not "
                    "edit. The REFERENCE's own message text for branches no facts document "
                    "can reach, obtained by running check_facts with its lowering and core "
                    "substituted. The Rust controls read this file instead of carrying "
                    "their own copy of the text."),
        "probe_version": PROBE_VERSION,
        "messages": probe_all(),
    }


def render() -> str:
    return json.dumps(_document(), indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    fails: list[str] = []
    rendered = render()
    if render() != rendered:
        fails.append("the probe is not deterministic")
    if not os.path.exists(FIXTURE):
        fails.append("fixture missing; re-probe with "
                     "'python tests/test_unreachable_branch_probe.py --write'")
    else:
        with open(FIXTURE, encoding="utf-8") as f:
            committed = f.read()
        if committed != rendered:
            fails.append("fixture is stale — the reference's wording for an unreachable "
                         "branch changed (a BR-V4 contract change), or the probe did; "
                         "re-probe with 'python tests/test_unreachable_branch_probe.py "
                         "--write' and re-run the Rust side (cd rust && cargo test)")
    # A probe that reported nothing would pass every check above.
    if not fails and not json.loads(rendered)["messages"]:
        fails.append("the probe produced no messages")
    if fails:
        for f_ in fails:
            print(f"FAIL: unreachable-branch probe {f_}")
        return 1
    print(f"unreachable-branch probe OK: {len(json.loads(rendered)['messages'])} "
          f"reference wordings recorded")
    return 0


def write() -> int:
    with open(FIXTURE, "w", encoding="utf-8") as f:
        f.write(render())
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
