#!/usr/bin/env python3
"""Pins the OwnTS spike end-to-end through the real core:
  - Dashboard.tsx  -> three OWN001 leaks (timer/subscribe/listener) + one EFF001
                      effect storm (unstable object dep + IO);
  - DashboardClean.tsx -> silent (cleanups + useMemo'd dep);
  - EffectStorm.tsx -> exactly two EFF001 (direct object dep + its derived alias),
                      every memo/ref/call/primitive/no-IO case staying silent.
EFF001 here is a real core verdict (ownlang/effects.py), not a frontend heuristic.
Zero deps. Run: python frontend/ownts/test_ownts.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import ownts  # noqa: E402

from ownlang.ownir import check_facts  # noqa: E402


def codes(tsx: str) -> list[str]:
    path = os.path.join(HERE, "examples", tsx)
    facts = ownts.to_ownir(ownts.extract(path), tsx, ownts.extract_effects(path))
    return [f.code for f in check_facts(facts)]


def main() -> int:
    leaky = codes("Dashboard.tsx")
    assert leaky == ["OWN001", "OWN001", "OWN001", "EFF001"], f"leaky -> {leaky}"

    clean = codes("DashboardClean.tsx")
    assert clean == [], f"clean should be silent -> {clean}"

    # resource-kind mapping is preserved through the bridge
    comps = ownts.extract(os.path.join(HERE, "examples", "Dashboard.tsx"))
    kinds = sorted(r.resource for c in comps for r in c.resources)
    assert kinds == ["subscribe", "subscription", "timer"], kinds

    # EFF001 is a real core verdict: the showcase fires on exactly the direct
    # object dep and its derived alias; memo/ref/opaque-call/primitive/no-IO are
    # all silent (the core's conservative, low-false-positive stability analysis).
    storm = codes("EffectStorm.tsx")
    assert storm == ["EFF001", "EFF001"], f"EffectStorm -> {storm}"

    # Edge cases: two same-kind timers with only one cleared -> exactly ONE OWN001
    # (per-resource cleanup matching, not kind-level); a like-named local inside an
    # effect callback must NOT shadow the memoized render-scope dep into a false
    # EFF001 (render-scope-only bindings).
    edges = codes("EffectEdges.tsx")
    assert edges == ["OWN001"], f"EffectEdges -> {edges}"

    # Parser hardening: a string with commas/braces does not truncate a body or
    # split deps; deps brackets nest (`items[0]`); a listener is released only by a
    # matching target+handler+options. -> one OWN001 (options dropped) + one EFF001.
    hardening = codes("EffectHardening.tsx")
    assert hardening == ["OWN001", "EFF001"], f"EffectHardening -> {hardening}"

    # Real-world cleanup patterns from the OSS benchmark (AbortController signal,
    # ref/pre-declared timer handles, cleanup returned from a nested block,
    # observer.subscribe released by observer.unsubscribe) must all read as released.
    real = codes("EffectRealWorld.tsx")
    assert real == [], f"EffectRealWorld should be silent -> {real}"

    # False-negative controls: a release-shaped cleanup that does NOT release THIS
    # resource (wrong AbortController, mismatched unsubscribe args, a conditionally
    # returned cleanup over an unconditional acquire) must STILL report the leak —
    # the broadened matchers must not over-suppress.
    leaks = codes("EffectLeakControl.tsx")
    assert leaks == ["OWN001"] * 4, f"EffectLeakControl -> {leaks}"

    # Transpiled-ES5 shape: `function () { … return function () { … } }`. The parser
    # handles `function` callbacks + `return function` cleanups — a matched cleanup is
    # silent, and a real capture-flag mismatch (the react-scroll-to-bottom@4.2.0 bug)
    # is caught precisely via the listener key.
    fn_cb = codes("EffectFunctionCallback.tsx")
    assert fn_cb == ["OWN001"], f"EffectFunctionCallback -> {fn_cb}"

    # an expression-bodied cleanup whose removeEventListener carries an options
    # object must parse (the `{` belongs to the call, not the cleanup block) — the
    # listener is released, so no false-positive leak.
    expr_cleanup = codes("EffectExprCleanup.tsx")
    assert expr_cleanup == [], f"EffectExprCleanup should be silent -> {expr_cleanup}"

    # addEventListener release must match the receiver and capture/options, not just
    # the handler (dropping `true` or changing the target still leaks).
    sub = next(a for a in ownts.ACQUIRES if a.resource == "subscription")

    def rel(setup: str, cleanup: str) -> bool:
        return ownts._is_released(sub, setup, setup.index(".addEventListener"), cleanup)

    assert rel('window.addEventListener("x", onX)', 'window.removeEventListener("x", onX)')
    assert rel('window.addEventListener("x", onX, true)',
               'window.removeEventListener("x", onX, true)')
    assert not rel('window.addEventListener("x", onX, true)',
                   'window.removeEventListener("x", onX)'), "dropped options must still leak"
    assert not rel('window.addEventListener("x", onX)',
                   'window.removeEventListener("x", onX, true)'), \
        "omitted capture (false) is not released by remove(..., true)"
    assert rel('window.addEventListener("x", onX, {capture: true})',
               'window.removeEventListener("x", onX, true)'), \
        "{capture:true} and true are the same listener"
    assert rel('window.addEventListener("x", onX, {passive: true})',
               'window.removeEventListener("x", onX)'), \
        "a non-capture option (passive) does not change removal identity"
    assert not rel('el.addEventListener("x", onX)',
                   'other.removeEventListener("x", onX)'), "wrong target must still leak"
    assert not rel('window.addEventListener("scroll", onX)',
                   'window.removeEventListener("resize", onX)'), \
        "a different event name is a different listener (still leaks)"
    assert rel('nodes[i].addEventListener("x", onX)',
               'nodes[i].removeEventListener("x", onX)'), "indexed receiver matches itself"
    assert not rel('nodes[i].addEventListener("x", onX)',
                   'nodes[j].removeEventListener("x", onX)'), \
        "a different index is a different target (still leaks)"

    print("OwnTS spike OK: leaky=3xOWN001+EFF001, clean=0, kinds=timer/subscribe/"
          "subscription, EffectStorm=2xEFF001, EffectEdges=1xOWN001, "
          "EffectHardening=OWN001+EFF001 (literal-proof parser + strict listener match).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
