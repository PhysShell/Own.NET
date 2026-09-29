#!/usr/bin/env python3
"""P-037-X Stage 7 (research/p037-max-v1, EXPLORATORY): the six frozen TypeScript twins (Group E
of Own.NET-paperwork paper-eval/prereg/p037-max-v1.json, copied byte for byte under
corpus/p037x-controls/ownts/) and the two Stage 7 controls, through the twin-only OwnTS
functions[] emitter (frontend/ownts/ownts_p037x.py) and the UNCHANGED core.

Every document runs through the Python reference (the legacy path) and, when `OWEN_RUST_CORE`
names an own-cli, through Rust with `OWEN_P037X_GUARDED=0` (must equal the reference's codes)
and `=1` (the frozen guarded outcome). Architecture evidence only: never TypeScript support.

REQUIRED VS SKIPPED — as tests/test_p037x_controls.py: required exactly when
OWN_TIERB_REQUIRED=1 for the Rust arm; the Python arm always runs (no dotnet involved).
"""

from __future__ import annotations

import collections
import os
import re
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EMIT = os.path.join(_REPO, "frontend", "ownts", "ownts_p037x.py")
_TS = os.path.join("corpus", "p037x-controls", "ownts")
_CODE = re.compile(r"\[(OWN\d{3})\]")

# document -> (emitter flags, legacy codes = Python == Rust flag off, Rust flag on)
_RECORD: dict[str, tuple[list[str], list[str], list[str]]] = {
    "e1-guarded-release-bug": ([], ["OWN051"], ["OWN001"]),     # §8 row 1: `true` keeps -> leak
    "e2-guarded-release-safe": ([], ["OWN051"], []),            # `false` closes -> clean
    "e3-wrapper-id-bug": ([], ["OWN051"], ["OWN001"]),          # row 7: the id edge, one hop up
    "e4-wrapper-id-safe": ([], ["OWN051"], []),
    "e5-wrapper-neg-bug": ([], ["OWN051"], ["OWN001"]),         # row 8: the neg edge
    "e6-wrapper-neg-safe": ([], ["OWN051"], []),
    "x7-c1-opaque-flag": ([], ["OWN051"], ["OWN051"]),          # an opaque guard is the join
    # X7-C2: e1's facts without params[].ordinal — the driver's A17 allowlist knows C# type
    # names only, so the coordinate answers ordinal_map and the legacy reading stands
    "x7-c2-no-ordinal": (["--no-ordinal"], ["OWN051"], ["OWN051"]),
}
_SOURCE = {"x7-c2-no-ordinal": "e1-guarded-release-bug"}


def _codes(text: str) -> list[str]:
    return sorted(_CODE.findall(text))


def _run(argv: list[str], env: dict[str, str]) -> str:
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True, env=env)
    return p.stdout + p.stderr


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    rust = os.environ.get("OWEN_RUST_CORE")
    if rust and not os.path.isfile(rust):
        rust = None
    if required and not rust:
        print("p037x ownts: FAIL - OWEN_RUST_CORE is REQUIRED (OWN_TIERB_REQUIRED=1) and unset")
        return 1
    env = {**os.environ, "PYTHONPATH": _REPO}
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, (flags, legacy, guarded) in sorted(_RECORD.items()):
            src = os.path.join(_TS, f"{_SOURCE.get(name, name)}.ts")
            facts = os.path.join(tmp, f"{name}.json")
            emit = subprocess.run([sys.executable, _EMIT, src, "-o", facts, *flags],
                                  cwd=_REPO, capture_output=True, text=True)
            if emit.returncode != 0:
                fails.append(f"{name}: the emitter exited {emit.returncode}: {emit.stderr[-300:]}")
                continue
            py = _codes(_run([sys.executable, "-m", "ownlang", "ownir", facts,
                              "--severity", "warning"], env))
            if collections.Counter(py) != collections.Counter(legacy):
                fails.append(f"{name}: python {py} != recorded legacy {legacy}")
            if rust:
                off = _codes(_run([rust, "ownir", facts, "--severity", "warning"],
                                  {**env, "OWEN_P037X_GUARDED": "0"}))
                on = _codes(_run([rust, "ownir", facts, "--severity", "warning"],
                                 {**env, "OWEN_P037X_GUARDED": "1"}))
                if collections.Counter(off) != collections.Counter(py):
                    fails.append(f"{name}: rust flag-off {off} != python {py} (parity)")
                if collections.Counter(on) != collections.Counter(guarded):
                    fails.append(f"{name}: rust flag-on {on} != recorded guarded {guarded}")
    for f in fails:
        print(f"FAIL: {f}")
    print(f"p037x ownts: {len(_RECORD)} document(s), {len(fails)} failed"
          + ("" if rust else " (Rust opt-in path not checked: OWEN_RUST_CORE unset)"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
