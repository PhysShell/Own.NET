#!/usr/bin/env python3
"""Assert the P-035 weak-subscribe extractor facts (run from the .NET-backed
"C# leak extractor" CI job; NOT auto-discovered by run_tests.py — it needs the SDK
to produce the facts, so it is not named ``test_*`` and takes the facts paths).

Usage:
    python tests/check_weak_subscribe_facts.py \
        <on.json> <off.json> <no_events.json> <unresolved.json> <rx_no_events.json>

  on          = WeakSubscribeAllowlistSample.cs WITH --weak-subscribe WeakEvents.AddPropertyChanged
  off         = the SAME sample with NO flag
  no_events   = the SAME sample WITH --weak-subscribe AND --no-event-leaks
  unresolved  = WeakSubscribeUnresolvedSample.cs WITH --weak-subscribe WeakEvents.AddPropertyChanged
                (the wrapper type is unresolved -> exercises the syntactic fallback)
  rx_no_events = WeakSubscribeRxNoEventsSample.cs WITH --weak-subscribe WeakBus.Subscribe
                AND --no-event-leaks (a declared `Subscribe`-named IDisposable wrapper:
                the Rx suppression must hold even with event analysis off)

Encodes the Increment-B acceptance contract at the fact level. Exits non-zero on any
violation.
"""

from __future__ import annotations

import json
import sys


def _subs(facts: dict[str, object], component: str) -> list[dict[str, object]]:
    for c in facts.get("components", []):  # type: ignore[union-attr]
        if c.get("name") == component:
            return c.get("subscriptions", []) or []
    return []


def _load(path: str) -> dict[str, object]:
    with open(path) as fh:
        return json.load(fh)


def main(
    on_path: str,
    off_path: str,
    noev_path: str,
    unres_path: str,
    rx_noev_path: str,
) -> int:
    on = _load(on_path)
    off = _load(off_path)
    noev = _load(noev_path)
    unres = _load(unres_path)
    rx_noev = _load(rx_noev_path)

    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    # #2 declared call -> exactly one first-class subscription, released True
    ws = _subs(on, "WeaklySubscribed")
    check(len(ws) == 1, f"WeaklySubscribed: expected 1 subscription, got {len(ws)}")
    check(
        len(ws) == 1 and ws[0].get("released") is True and ws[0].get("resource") == "subscription",
        "WeaklySubscribed: the one subscription must be resource=subscription, released=true",
    )

    # #4 ordinary `+=` still diagnosed (a real leak: released False)
    op = _subs(on, "OrdinaryPlusEquals")
    check(
        len(op) == 1 and op[0].get("released") is False,
        "OrdinaryPlusEquals: the ordinary += must stay one released=false subscription",
    )

    # #3 / #9 undeclared method call (same name, different type) -> no subscription fact
    check(
        _subs(on, "SameNameDifferentType") == [],
        "SameNameDifferentType: a same-named method on another type must NOT be recognised",
    )

    # #7 declared wrapper but fewer than two args -> not recognised
    check(
        _subs(on, "TooFewArgs") == [],
        "TooFewArgs: a call with <2 positional args must NOT be recognised",
    )

    # handler shape: declared wrapper, two args, but the 2nd is not a handler (an int)
    check(
        _subs(on, "NonHandlerSecondArgument") == [],
        "NonHandlerSecondArgument: a non-handler 2nd arg must NOT be minted as a subscription",
    )

    # #1 no flag -> the wrapper call is invisible, so the class carries no subscription
    check(
        _subs(off, "WeaklySubscribed") == [],
        "WeaklySubscribed (no flag): must be byte-for-byte unchanged (no subscription)",
    )
    check(
        len(_subs(off, "OrdinaryPlusEquals")) == 1,
        "OrdinaryPlusEquals (no flag): the ordinary += is unaffected by the feature",
    )

    # #2 --no-event-leaks must silence BOTH the weak detector AND the ordinary += detector
    check(
        _subs(noev, "WeaklySubscribed") == [],
        "WeaklySubscribed (--no-event-leaks): the weak detector must be off",
    )
    check(
        _subs(noev, "OrdinaryPlusEquals") == [],
        "OrdinaryPlusEquals (--no-event-leaks): the += detector must be off too",
    )

    # #8 syntax fallback for an unresolved external wrapper
    uw = _subs(unres, "UnresolvedWrapperSubscriber")
    check(
        len(uw) == 1 and uw[0].get("released") is True,
        "UnresolvedWrapperSubscriber: an unresolved External.WeakEvents.AddPropertyChanged "
        "must be recognised via the receiver-name fallback (one released=true)",
    )
    check(
        _subs(unres, "UnresolvedDifferentReceiver") == [],
        "UnresolvedDifferentReceiver: a different final receiver name must NOT match",
    )

    # Rx-collision regression (arbiter round 2): a declared `Subscribe`-named IDisposable
    # wrapper under --no-event-leaks must produce NEITHER a weak fact (the pass is off)
    # NOR an Rx dropped-token fact (the declaration suppresses it unconditionally). The OFF
    # switch must not invent a finding that event analysis suppresses.
    check(
        _subs(rx_noev, "RxCollisionSubscriber") == [],
        "RxCollisionSubscriber (declared WeakBus.Subscribe + --no-event-leaks): must have "
        "ZERO subscriptions -- no weak fact and no Rx dropped-token fact",
    )

    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print("weak-subscribe facts: all Increment-B acceptance checks pass")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(
        main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    )
