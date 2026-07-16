#!/usr/bin/env python3
"""P-035 / minimal P-015 config carrier — the Python-side (SDK-free) tests.

Covers the `own-check --config own.toml` -> `[weak-subscription].subscribe` reader
(`ownlang/config.py`): a well-formed table yields the declared "SimpleType.Method"
names; an absent table is "no declaration" (not an error); a MALFORMED table is a
HARD error (acceptance #10), never a silent skip.

The extractor's facts-level behaviour (a declared call becomes one released
subscription; an undeclared call / `+=` are unaffected) needs the .NET SDK and is
asserted in the "C# leak extractor" CI job, not here.

Run:  python tests/test_weak_subscribe.py
      python tests/run_tests.py     (auto-discovered)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.config import ConfigError, load_weak_subscribe


def _load(text: str) -> list[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
        fh.write(text)
        path = fh.name
    try:
        return load_weak_subscribe(path)
    finally:
        os.unlink(path)


def _must_raise(text: str) -> bool:
    try:
        _load(text)
    except ConfigError:
        return True
    return False


def run() -> int:
    ok = 0
    bad = 0

    def check(cond: bool, label: str) -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"  FAIL: {label}")

    # --- well-formed ---
    check(
        _load('[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n')
        == ["WeakEvents.AddPropertyChanged"],
        "single declared pair is returned",
    )
    check(
        _load(
            "[weak-subscription]\n"
            'subscribe = ["WeakEvents.AddPropertyChanged", "Bus.SubscribeWeak"]\n'
        )
        == ["WeakEvents.AddPropertyChanged", "Bus.SubscribeWeak"],
        "multiple declared pairs preserved in order",
    )

    # --- absent / empty == "no declaration", NOT an error ---
    check(_load("") == [], "empty file -> no declaration")
    check(_load("[other]\nx = 1\n") == [], "no [weak-subscription] -> no declaration")
    check(
        _load("[weak-subscription]\nsubscribe = []\n") == [],
        "empty subscribe list -> no declaration",
    )

    # --- malformed -> HARD error (acceptance #10) ---
    check(_must_raise("this is = not : toml ["), "invalid TOML is a hard error")
    check(
        _must_raise("[weak-subscription]\nsubscribe = 42\n"),
        "subscribe not a list is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribe = ["not_dotted"]\n'),
        "entry without a dot is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribe = ["A.B.C"]\n'),
        "namespace-qualified (two dots) entry is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribe = [".Method"]\n'),
        "empty type part is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribe = ["Type."]\n'),
        "empty method part is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribe = ["Weak Events.Add"]\n'),
        "non-identifier (space) is a hard error",
    )
    check(
        _must_raise('[weak-subscription]\nsubscribes = ["WeakEvents.Add"]\n'),
        "misspelled key (`subscribes`) is a hard error, not silently ignored",
    )
    check(
        _must_raise("[weak-subscription]\nsubscribe = [1, 2]\n"),
        "non-string list entries are a hard error",
    )

    def _absent_raises() -> bool:
        try:
            load_weak_subscribe(
                os.path.join(tempfile.gettempdir(), "own-no-such-config-xyz.toml")
            )
        except ConfigError:
            return True
        return False

    check(_absent_raises(), "absent config file is a hard error")

    total = ok + bad
    print(f"weak-subscribe config: {ok}/{total} checks pass")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
