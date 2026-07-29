#!/usr/bin/env python3
"""Own.NET#317 - the Roslyn extractor really emits a source COLUMN, on the right node.

The bridge half of #317 (ownlang/ownir.py, tests/test_ownir_column.py) proves that a
`column` in the facts survives to SARIF `region.startColumn`. It cannot prove that any
column ever ARRIVES: every fixture it reads is hand-written. This file closes that gap
from the other side - it runs the real extractor over a real C# file and asserts the
coordinates it produced.

WHAT IS ACTUALLY BEING TESTED

Not "a column is present". A column that was always 1, or always the indentation, or
always the first site on the line, would satisfy that and be useless. The fixture
(frontend/roslyn/samples/ColumnAnchorsSample.cs) puts TWO anchor sites on ONE line in
each family, so the assertion is that the two differ, and differ by exactly the amount
the source text says they should. That is the property the OwnAudit occurrence anchor
needs: a column earns its place only by telling two findings on one line apart.

Both extractor modes are covered, because the two paths mint their coordinate in
different code:

  * default              -> `local-disposable` records (the flat D1 detector)
  * --flow-locals        -> `acquire` flow ops (the path-sensitive detector)

and the `+=` subscription pair, which is emitted in both.

REQUIRED VS SKIPPED

`dotnet` is not present in every environment this suite runs in (the Tier-A `tests (pyX)`
job, the pack job, an offline checkout). The convention already in use here - see
tests/test_verify_delta_tierb.py - is that such a test is REQUIRED exactly when
OWN_TIERB_REQUIRED=1, which the wpf-extractor CI job sets, and skips cleanly otherwise.
A skip prints why; it never prints a pass it did not earn.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_extractor_columns.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_SAMPLE_REL = os.path.join("frontend", "roslyn", "samples", "ColumnAnchorsSample.cs")
_SAMPLE = os.path.join(_REPO, _SAMPLE_REL)

# The expected coordinates, as 1-based (line, column) pairs.
#
# These were read off the fixture's text, not off an extractor run: `column` is
# `LinePosition.Character + 1`, and `Character` is the count of UTF-16 code units before
# the node's first token on its line. For an ASCII, tab-free line that is simply the
# 1-based index of the character - which `_assert_fixture_is_plain_ascii` below enforces
# so the arithmetic stays true. The pairs are stated here so a wrong emitted column fails
# LOUDLY rather than being absorbed by a regenerated expectation.
_SUBSCRIPTIONS = [("src.Alpha", 30, 9), ("src.Beta", 30, 31)]
_LOCALS = [("first", 51, 13), ("second", 51, 45)]


def _fail(fails: list[str], msg: str) -> None:
    fails.append(msg)


def _assert_fixture_is_plain_ascii(fails: list[str]) -> None:
    """The expected columns are arithmetic on the fixture's text; keep that arithmetic true.

    A tab does not expand (Roslyn counts it as one unit, an editor shows eight), and an
    astral character counts as two UTF-16 units while reading as one. Either would make
    the constants above a claim about this file's encoding rather than about the
    extractor - so the fixture is held to ASCII, and the hold is checked, not assumed.
    """
    raw = open(_SAMPLE, "rb").read()
    if b"\t" in raw:
        _fail(fails, f"{_SAMPLE_REL} contains a TAB; the expected columns assume none")
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:
        _fail(fails, f"{_SAMPLE_REL} is not plain ASCII ({exc}); the expected columns "
                     "assume one UTF-16 code unit per character")


def _extract(flags: list[str]) -> dict:
    """Run the real extractor over the fixture and return its facts."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "facts.json")
        subprocess.run(
            ["dotnet", "run", "--project", _EXT, "--"] + flags + [_SAMPLE_REL, "-o", out],
            cwd=_REPO, check=True, capture_output=True, text=True)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)


def _subscriptions(facts: dict) -> list[dict]:
    return [s for c in facts.get("components", []) for s in c.get("subscriptions", [])]


def _flow_ops(facts: dict) -> list[dict]:
    return [op for f in facts.get("functions", []) for op in f.get("body", [])]


def _check_pairs(fails: list[str], label: str, got: list[dict],
                 expected: list[tuple[str, int, int]], key: str) -> None:
    """Every expected site is present exactly once, at exactly its (line, column)."""
    for name, line, col in expected:
        hits = [r for r in got if str(r.get(key, "")) == name]
        if len(hits) != 1:
            _fail(fails, f"{label}: expected exactly one record for {name!r}, got {len(hits)}")
            continue
        r = hits[0]
        if r.get("line") != line:
            _fail(fails, f"{label}: {name!r} line is {r.get('line')!r}, expected {line}")
        if "column" not in r:
            _fail(fails, f"{label}: {name!r} carries NO column - the extractor is still "
                         "line-only on this path")
        elif r["column"] != col:
            _fail(fails, f"{label}: {name!r} column is {r['column']!r}, expected {col}")

    # The whole point of the fixture: the pair shares a line and is told apart by the
    # column alone. Asserted separately from the exact values, so a uniform-but-wrong
    # column (always 1, always the indentation) cannot pass by accident even if the
    # constants above were ever loosened.
    cols = [r.get("column") for name, _, _ in expected
            for r in got if str(r.get(key, "")) == name]
    if len(cols) == 2 and cols[0] == cols[1]:
        _fail(fails, f"{label}: both sites report column {cols[0]!r}; a column that does "
                     "not discriminate two findings on one line is decoration")


def run() -> int:
    if not shutil.which("dotnet"):
        msg = "extractor columns: SKIP - dotnet not on PATH"
        if os.environ.get("OWN_TIERB_REQUIRED") == "1":
            print("extractor columns: FAIL - dotnet is REQUIRED here "
                  "(OWN_TIERB_REQUIRED=1) and is not on PATH")
            return 1
        print(msg)
        return 0

    fails: list[str] = []
    _assert_fixture_is_plain_ascii(fails)

    try:
        default = _extract([])
        flow = _extract(["--flow-locals"])
    except subprocess.CalledProcessError as exc:
        print(f"extractor columns: FAIL - the extractor exited {exc.returncode}\n"
              f"{exc.stdout}\n{exc.stderr}")
        return 1

    # `+=` subscriptions: emitted in both modes, and identical in both - the event
    # detector is not gated on --flow-locals, so a difference here would be a bug in
    # something other than this change.
    for label, facts in (("default", default), ("--flow-locals", flow)):
        _check_pairs(fails, f"subscription ({label})", _subscriptions(facts),
                     _SUBSCRIPTIONS, "event")

    # D1 local-disposable records: default mode only (--flow-locals supersedes them).
    d1 = [s for s in _subscriptions(default) if s.get("resource") == "local-disposable"]
    _check_pairs(fails, "local-disposable", d1, _LOCALS, "event")
    if [s for s in _subscriptions(flow) if s.get("resource") == "local-disposable"]:
        _fail(fails, "--flow-locals must suppress the flat D1 records; it did not, and "
                     "the two detectors would double-report")

    # Flow acquires: --flow-locals only.
    acquires = [op for op in _flow_ops(flow) if op.get("op") == "acquire"]
    _check_pairs(fails, "flow acquire", acquires, _LOCALS, "var")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"extractor columns: {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
