#!/usr/bin/env python3
"""Assert the P-035 weak-subscribe extractor facts (run from the .NET-backed
"C# leak extractor" CI job; NOT auto-discovered by run_tests.py — it needs the SDK
to produce the facts, so it is not named ``test_*`` and takes the two facts paths).

Usage:
    python tests/check_weak_subscribe_facts.py <facts_on.json> <facts_off.json>

  facts_on  = extractor over WeakSubscribeAllowlistSample.cs WITH
              --weak-subscribe "WeakEvents.AddPropertyChanged"
  facts_off = the SAME sample with NO flag.

Encodes the Increment-B acceptance contract at the fact level. Exits non-zero on any
violation.
"""

from __future__ import annotations

import json
import sys


def _subs(facts: dict, component: str) -> list[dict]:
    for c in facts.get("components", []):
        if c.get("name") == component:
            return c.get("subscriptions", []) or []
    return []


def main(on_path: str, off_path: str) -> int:
    with open(on_path) as fh:
        on = json.load(fh)
    with open(off_path) as fh:
        off = json.load(fh)

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

    # #1 no flag -> the wrapper call is invisible, so the class carries no subscription
    check(
        _subs(off, "WeaklySubscribed") == [],
        "WeaklySubscribed (no flag): must be byte-for-byte unchanged (no subscription)",
    )
    check(
        len(_subs(off, "OrdinaryPlusEquals")) == 1,
        "OrdinaryPlusEquals (no flag): the ordinary += is unaffected by the feature",
    )

    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print("weak-subscribe facts: all Increment-B acceptance checks pass")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
