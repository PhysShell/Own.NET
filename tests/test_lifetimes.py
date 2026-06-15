#!/usr/bin/env python3
"""
Lifetime-region analysis tests (the `lifetimes` module, slice #2).

Pins the region-escape theorem and the structural validation of the lifetime
order. Each case is a tiny module paired with the exact set of error codes it
must produce, so the WPF "zombie ViewModel" check can never quietly drift.

The headline case: a ViewModel (short lifetime) strongly subscribed to an
App-lifetime source is promoted to App and leaks -> OWN014; the same subscription
to an equal-or-shorter-lived source is clean (no promotion).

Run:  python tests/test_lifetimes.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.lexer import LexError
from ownlang.lifetimes import check_lifetimes
from ownlang.parser import ParseError, parse

# (name, source, expected sorted error codes)
CASES: list[tuple[str, str, list[str]]] = [
    (
        "escape_to_app",
        """
        module M
        lifetime App;
        lifetime Window < App;
        lifetime ViewModel < Window;
        fn VM(bus: EventBus lifetime App) lifetime ViewModel {
            subscribe self to bus;
        }
        """,
        ["OWN014"],
    ),
    (
        "escape_transitive",   # ViewModel < Window < App, subscribe straight to App
        """
        module M
        lifetime App;
        lifetime Window < App;
        lifetime ViewModel < Window;
        fn VM(bus: EventBus lifetime App) lifetime ViewModel {
            subscribe self to bus;
        }
        """,
        ["OWN014"],
    ),
    (
        "same_lifetime_ok",    # capture by an equal-lifetime source -> no promotion
        """
        module M
        lifetime App;
        lifetime ViewModel < App;
        fn ParentVM(child: ChildVM lifetime ViewModel) lifetime ViewModel {
            subscribe self to child;
        }
        """,
        [],
    ),
    (
        "shorter_source_ok",   # source is shorter-lived than self -> fine
        """
        module M
        lifetime App;
        lifetime Window < App;
        fn AppService(view: View lifetime Window) lifetime App {
            subscribe self to view;
        }
        """,
        [],
    ),
    (
        "no_annotations_skipped",   # without lifetimes, the analysis is a no-op
        """
        module M
        fn VM(bus: EventBus) {
            subscribe self to bus;
        }
        """,
        [],
    ),
    (
        "unannotated_self_skipped",  # source tagged but self is not -> cannot compare
        """
        module M
        lifetime App;
        fn VM(bus: EventBus lifetime App) {
            subscribe self to bus;
        }
        """,
        [],
    ),
    (
        "cyclic_order",
        """
        module M
        lifetime A < B;
        lifetime B < A;
        """,
        ["OWN036", "OWN036"],
    ),
    (
        "undefined_longer",
        """
        module M
        lifetime A < Nope;
        """,
        ["OWN030"],
    ),
    (
        "undefined_param_lifetime",
        """
        module M
        lifetime App;
        fn VM(bus: EventBus lifetime Bogus) lifetime App {
            subscribe self to bus;
        }
        """,
        ["OWN030"],
    ),
    (
        "redefined_lifetime",
        """
        module M
        lifetime App;
        lifetime App;
        """,
        ["OWN031"],
    ),
]


def _codes(src: str) -> list[str]:
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["PARSE_ERROR"]
    return sorted(d.code for d in check_lifetimes(mod))


def run() -> int:
    """Run every region case against its expected codes; return 0/1."""
    fails: list[str] = []
    matched = 0
    for name, src, want in CASES:
        got = _codes(src)
        if got == sorted(want):
            matched += 1
        else:
            fails.append(f"{name}: expected {sorted(want)}, got {got}")

    # the headline OWN014 must name the source, the captured object and BOTH
    # lifetimes, and place a caret under the source in the `subscribe` line.
    escape_src = CASES[0][1]
    diags = check_lifetimes(parse(escape_src))
    headline = next((d for d in diags if d.code == "OWN014"), None)
    if headline is None:
        fails.append("escape_to_app: expected an OWN014 headline diagnostic")
    else:
        pretty = headline.render_pretty("m.own", escape_src)
        for needed in ("bus", "App", "VM", "ViewModel", "^"):
            if needed not in pretty:
                fails.append(f"escape message missing {needed!r}")

    for f in fails:
        print(f"LIFETIMES FAIL: {f}")
    print(f"lifetimes: {matched}/{len(CASES)} region cases match expected codes")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
