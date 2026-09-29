#!/usr/bin/env python3
"""P-037-X (research/p037-max-v1, EXPLORATORY): the hostile controls of the pre-registered
sub-stages 2b and 2c as executable evidence, on the real extractor.

corpus/p037x-controls/*.cs are the controls frozen in Own.NET-paperwork
`paper-eval/p037-max/stage2b-prereg-v1.json` and `stage2c-prereg-v1.json`. Each is extracted
with `--flow-locals` and run through the Python reference (the legacy path, which the guarded
opt-in never touches) and, when `OWEN_RUST_CORE` names an own-cli, through Rust with
`OWEN_P037X_GUARDED=0` (must equal the reference's codes) and `=1` (the frozen guarded outcome).

The table below is the RECORD of the sub-stage measurements; a row that moves is a change to
classify, never one to repair here. Codes are compared as multisets at `--severity warning`.

REQUIRED VS SKIPPED — the tests/test_extractor_columns.py convention: required exactly when
OWN_TIERB_REQUIRED=1, a clean printed skip otherwise.
"""

from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_CONTROLS = os.path.join("corpus", "p037x-controls")
_CODE = re.compile(r"\[(OWN\d{3})\]")

# control -> (legacy codes = Python == Rust flag off, Rust flag on)
_RECORD: dict[str, tuple[list[str], list[str]]] = {
    # Stage 2b: driver fidelity
    "x2b-c1-leaf-if-nonparam": (["OWN051"], ["OWN051"]),      # NGE stays; never consume
    "x2b-c2-leaf-while": ([], []),
    # the guarded caller selects by its constant; the consumer caller consumes
    "x2b-c3-overloads": (["OWN051"], []),
    # Conflict -> Uncond(may) -> plain + OWN051, never consume
    "x2b-c4-two-guards-conflict": (["OWN051"], ["OWN051"]),
    "x2b-c5-irrelevant-guard": (["OWN051", "OWN051"], []),
    "x2b-c7-merging-guard": (["OWN051"], []),
    # Stage 2c: initializer-form argument use
    "x2c-c1-init-use-after-handoff": (["OWN002"], ["OWN002"]),  # a TRUE use after the handoff
    "x2c-c2-init-use-before-dispose": ([], []),
    "x2c-c3-init-fresh-result-leaked": (["OWN001"], ["OWN001"]),  # the leaked fresh result only
    "x2c-c4-init-use-in-guarded-callee": ([], []),
    # Stage 2d: the legacy borrow at a call line without a coordinate
    # M = Split(g) [must, no]: true consumes, false borrows, an opaque guard -> plain + OWN051
    "x2d-c1-guard-else-external-forward": (["OWN051", "OWN051", "OWN051"], ["OWN051"]),
    "x2d-c2-external-use-then-guarded-release": (["OWN051", "OWN051"], []),
    "x2d-c3-two-forwards-one-path": ([], []),                     # multi_action stays; legacy no
    # the callee's own use after dispose, on both engines
    "x2d-c4-release-then-external-use": (["OWN002"], ["OWN002"]),
    "x2d-c5-sig-conflict-forward": ([], []),                      # callee_sig stays; legacy consume
}


def _codes(text: str) -> list[str]:
    return sorted(_CODE.findall(text))


def _run(argv: list[str], env: dict[str, str]) -> str:
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True, env=env)
    return p.stdout + p.stderr


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    if not shutil.which("dotnet"):
        print("p037x controls: FAIL - dotnet is REQUIRED (OWN_TIERB_REQUIRED=1) and not on PATH"
              if required else "p037x controls: SKIP - dotnet not on PATH")
        return 1 if required else 0
    rust = os.environ.get("OWEN_RUST_CORE")
    if rust and not os.path.isfile(rust):
        rust = None
    env = {**os.environ, "PYTHONPATH": _REPO}
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, (legacy, guarded) in sorted(_RECORD.items()):
            src = os.path.join(_CONTROLS, f"{name}.cs")
            facts = os.path.join(tmp, f"{name}.json")
            try:
                subprocess.run(["dotnet", "run", "--project", _EXT, "--", "--flow-locals", src,
                                "-o", facts], cwd=_REPO, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                fails.append(f"{name}: the extractor exited {exc.returncode}: {exc.stderr[-300:]}")
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
    print(f"p037x controls: {len(_RECORD)} control(s), {len(fails)} failed"
          + ("" if rust else " (Rust opt-in path not checked: OWEN_RUST_CORE unset)"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
