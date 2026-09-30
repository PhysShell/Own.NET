#!/usr/bin/env python3
"""resource-effects Stage 7 (research/resource-effects-v1, EXPLORATORY): the effect-model seam on the
OwnTS twin emitter. corpus/re-controls/ownts/e7-*.ts are the twins frozen in Own.NET-paperwork
`paper-eval/resource-effects/stage7-seam-prereg-v1.json`; each is emitted under four arms (no effects,
the MODELLED key, the same rows as SUGGESTED, SUGGESTED with --trust-all) and run through the Python
reference and, when `OWEN_RUST_CORE` names an own-cli, through Rust (parity). The table is the RECORD
of the Stage 7 measurement; a row that moves is a change to classify, never one to repair here.
A seam proof for one shape, never TypeScript support. Always runs (no external toolchain)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EMIT = os.path.join(_REPO, "frontend", "ownts", "ownts_p037x.py")
_TWINS = os.path.join(_REPO, "corpus", "re-controls", "ownts")
_KEYS = os.path.join(_REPO, "corpus", "re-controls", "keys")
_CODE = re.compile(r"\[(OWN\d{3})\]")

# arm -> emitter options
_ARMS: dict[str, list[str]] = {
    "none": [],
    "model": ["--effects", os.path.join(_KEYS, "effects-ts.json")],
    "suggested": ["--effects", os.path.join(_KEYS, "effects-ts-suggested.json")],
    "trustall": ["--effects", os.path.join(_KEYS, "effects-ts-suggested.json"), "--trust-all"],
}
# twin -> arm -> codes
_RECORD: dict[str, dict[str, list[str]]] = {
    "e7-effects-bug": {"none": [], "model": ["OWN001"], "suggested": [], "trustall": ["OWN001"]},
    "e7-effects-safe": {"none": [], "model": [], "suggested": [], "trustall": []},
}


def _run(argv: list[str], env: dict[str, str]) -> str:
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True, env=env)
    return p.stdout + p.stderr


def run() -> int:
    env = {**os.environ, "PYTHONPATH": _REPO}
    rust = os.environ.get("OWEN_RUST_CORE")
    if rust and not os.path.isfile(rust):
        rust = None
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for twin, arms in sorted(_RECORD.items()):
            for arm, want in arms.items():
                facts = os.path.join(tmp, f"{twin}.{arm}.json")
                subprocess.run([sys.executable, _EMIT, os.path.join(_TWINS, f"{twin}.ts"),
                                "-o", facts, *_ARMS[arm]], cwd=_REPO, check=True,
                               capture_output=True, text=True)
                py = sorted(_CODE.findall(_run([sys.executable, "-m", "ownlang", "ownir", facts,
                                                 "--severity", "warning"], env)))
                if py != sorted(want):
                    fails.append(f"{twin} [{arm}]: python {py} != recorded {want}")
                if rust:
                    rs = sorted(_CODE.findall(_run([rust, "ownir", facts, "--severity", "warning"],
                                                   {**env, "OWEN_P037X_GUARDED": "0"})))
                    if rs != py:
                        fails.append(f"{twin} [{arm}]: rust {rs} != python {py} (parity)")
    for f in fails:
        print(f"FAIL: {f}")
    n = sum(len(a) for a in _RECORD.values())
    print(f"re ownts seam: {n} row(s), {len(fails)} failed"
          + ("" if rust else " (Rust parity not checked: OWEN_RUST_CORE unset)"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
