#!/usr/bin/env python3
"""
`explain` command tests (the diagnostic-catalogue side of the CLI).

Pins the contract of `python -m ownlang explain`:

  1. A known code prints its title and long-form what/why/fix; a code with only a
     title (no long-form) still answers with the title.
  2. An all-unknown request exits 2 (a typo'd code must not silently succeed); a
     mix of known + unknown still exits 0.
  3. `--json` harvests every distinct code from a findings array AND a SARIF log
     (`ruleId`), de-duped, in first-seen order, and unions with command-line codes.
  4. The DI catalogue the bridge emits (DI001-005) is covered, so a real run's
     codes are all explainable.

Run:  python tests/test_explain.py
      python tests/run_tests.py     (folded into the suite aggregator)
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.__main__ import _codes_from_json, _explain_one, cmd_explain, main
from ownlang.diagnostics import EXPLANATIONS, TITLES


def _rc(*args: object) -> int:
    """Call cmd_explain/main with stdout+stderr muted, returning only the exit code —
    keeps the suite output clean (the printed explanations are exercised elsewhere)."""
    fn, fnargs = args[0], args[1:]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*fnargs)  # type: ignore[operator,no-any-return]


def _explain_text() -> list[str]:
    """Cases on the pure `_explain_one` text builder."""
    fails: list[str] = []
    one = _explain_one("OWN001")
    if "OWN001:" not in one or "Fix:" not in one:
        fails.append("OWN001 explanation should carry the title and a Fix line")
    # case-insensitive code input
    if _explain_one("own001") != one:
        fails.append("explain should be case-insensitive on the code")
    # a title-only code (no long-form) still answers with the title
    titleonly = next((c for c in TITLES if c not in EXPLANATIONS), None)
    if titleonly is not None:
        out = _explain_one(titleonly)
        if not out.startswith(f"{titleonly}:") or TITLES[titleonly] not in out:
            fails.append(f"title-only code {titleonly} should fall back to its title")
    # an unknown code is named as such, not a crash
    if "unknown" not in _explain_one("OWN999"):
        fails.append("unknown code should be reported as unknown")
    return fails


def _exit_codes() -> list[str]:
    """`cmd_explain` exit-code contract."""
    fails: list[str] = []
    if _rc(cmd_explain, ["OWN001"], None) != 0:
        fails.append("a known code should exit 0")
    if _rc(cmd_explain, [], None) != 2:
        fails.append("no codes and no --json should exit 2")
    if _rc(cmd_explain, ["OWN999"], None) != 2:
        fails.append("an all-unknown request should exit 2")
    if _rc(cmd_explain, ["OWN001", "OWN999"], None) != 0:
        fails.append("a mix of known + unknown should exit 0")
    return fails


def _json_harvest() -> list[str]:
    """`--json` code harvesting from findings arrays and SARIF logs."""
    fails: list[str] = []
    findings = [{"code": "OWN050", "file": "a.cs", "line": 3},
                {"code": "OWN001", "file": "b.cs", "line": 9},
                {"code": "OWN001", "file": "c.cs", "line": 1}]  # dup -> collapsed
    got = _codes_from_json(findings)
    if got != ["OWN050", "OWN001"]:
        fails.append(f"findings harvest should be first-seen, de-duped; got {got}")
    sarif = {"runs": [{"results": [{"ruleId": "DI004"}, {"ruleId": "OWN001"}]}]}
    got = _codes_from_json(sarif)
    if got != ["DI004", "OWN001"]:
        fails.append(f"SARIF ruleId harvest failed; got {got}")
    # a non-code 'code' value (e.g. an HTTP code) must not be harvested
    if _codes_from_json({"code": "404"}) != []:
        fails.append("a non-diagnostic 'code' value must not be harvested")

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(findings, f)
        if _rc(cmd_explain, [], p) != 0:
            fails.append("--json over real findings should exit 0")
        # an unreadable / missing file is a usage error
        if _rc(cmd_explain, [], os.path.join(d, "nope.json")) != 2:
            fails.append("--json on a missing file should exit 2")
        # a JSON with no codes is a usage error, not a silent success
        empty = os.path.join(d, "empty.json")
        with open(empty, "w", encoding="utf-8") as f:
            json.dump({"unrelated": 1}, f)
        if _rc(cmd_explain, [], empty) != 2:
            fails.append("--json with no codes should exit 2")
    return fails


def _di_catalogue() -> list[str]:
    """Every DI code the bridge emits is explainable (title at minimum)."""
    fails = [f"{c} has no title" for c in ("DI001", "DI002", "DI003", "DI004", "DI005")
             if c not in TITLES]
    return fails


def _dispatch() -> list[str]:
    """The `main` arg parser routes `explain` (incl. --json=VALUE form)."""
    fails: list[str] = []
    if _rc(main, ["explain", "OWN001"]) != 0:
        fails.append("main(['explain','OWN001']) should exit 0")
    if _rc(main, ["explain"]) != 2:
        fails.append("main(['explain']) with no code should exit 2")
    return fails


def run() -> int:
    """Run every explain case; return 0/1."""
    fails: list[str] = []
    fails += _explain_text()
    fails += _exit_codes()
    fails += _json_harvest()
    fails += _di_catalogue()
    fails += _dispatch()
    for f in fails:
        print(f"EXPLAIN FAIL: {f}")
    print(f"explain: {'PASS' if not fails else 'FAIL'} "
          f"(text + exit codes + --json harvest + DI catalogue + dispatch)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
