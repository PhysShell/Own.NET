#!/usr/bin/env python3
"""The first-run failure contract of `python -m ownlang` (alpha gate A1).

An internal crash of any command exits 70 (EX_SOFTWARE) with ONE actionable
line — never a traceback a first-time user has to parse, and never an exit
code a caller could mistake for findings (1) or clean (0): pre-A1 a core
crash exited 1, and `owen check` without `--fail-on-finding` mapped that to
a CLEAN scan. `OWNLANG_DEBUG=1` prints the full traceback but KEEPS exit 70
(a re-raise would exit 1 and reopen the same hole). Deliberate contract
errors keep their own codes (spec/CLI.md).

Run:  python tests/test_cli_contract.py
      python tests/run_tests.py            (runs it in the suite)
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_CRASH_DRIVER = """
import sys; sys.path.insert(0, {root!r})
from unittest import mock
import ownlang.__main__ as m
with mock.patch.object(m, "main", side_effect=RuntimeError("synthetic crash")):
    sys.exit(m.run(["ownir", "x.json"]))
"""


def _crash(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    root = os.path.join(os.path.dirname(__file__), "..")
    env = {k: v for k, v in os.environ.items() if k != "OWNLANG_DEBUG"}
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", _CRASH_DRIVER.format(root=root)],
        capture_output=True, text=True, env=env, check=False)


def run() -> int:
    fails: list[str] = []
    checks = 0

    # 1. Internal crash -> exit 70, one polite line, no traceback.
    checks += 1
    r = _crash({})
    if r.returncode != 70:
        fails.append(f"internal crash must exit 70 (EX_SOFTWARE), got {r.returncode}")
    if "Traceback" in r.stderr:
        fails.append("internal crash must not print a raw traceback by default")
    if "ownlang: internal error" not in r.stderr:
        fails.append(f"expected the polite one-liner, got: {r.stderr!r}")

    # 2. OWNLANG_DEBUG=1 -> full traceback, exit STILL 70 (never 1).
    checks += 1
    r = _crash({"OWNLANG_DEBUG": "1"})
    if r.returncode != 70:
        fails.append(f"debug crash must still exit 70, got {r.returncode} — "
                     f"exit 1 reads as findings and owen maps it to clean")
    if "Traceback" not in r.stderr:
        fails.append("OWNLANG_DEBUG=1 must print the full traceback")

    # 3. A missing facts file is a deliberate contract error (2), politely.
    checks += 1
    r = subprocess.run(
        [sys.executable, "-m", "ownlang", "ownir", "/no/such/facts.json"],
        capture_output=True, text=True, check=False,
        cwd=os.path.join(os.path.dirname(__file__), ".."))
    if r.returncode != 2 or "Traceback" in r.stderr or "cannot read" not in r.stderr:
        fails.append(f"missing facts must be a polite exit 2, got rc {r.returncode}: "
                     f"{r.stderr!r}")

    # 4. Usage errors keep exit 2 (the catch-all must not swallow them).
    checks += 1
    r = subprocess.run(
        [sys.executable, "-m", "ownlang", "no-such-command"],
        capture_output=True, text=True, check=False,
        cwd=os.path.join(os.path.dirname(__file__), ".."))
    if r.returncode != 2:
        fails.append(f"unknown command must stay exit 2, got {r.returncode}")

    if fails:
        for f in fails:
            print(f"FAIL: cli contract {f}")
        return 1
    print(f"cli first-run contract OK: {checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
