#!/usr/bin/env python3
"""resource-effects Stage 1 (research/resource-effects-v1, EXPLORATORY): the hostile oracle
controls as executable evidence on the real extractor.

corpus/re-controls/*.cs are the controls frozen in Own.NET-paperwork `paper-eval/resource-
effects/prereg-v1.json` (hostile_oracle_controls). Each is extracted with `--flow-locals` under
three keys — none, the identity ANSWER KEY (corpus/re-controls/keys/answer-key.json,
`OWEN_RE_ORACLE`), and the NAME-RULE MUTANT key generated from the fixture by
keys/gen_mutants.py (M1: Create*/Open*/New* -> fresh; M2: Delete/Close/Free/Release/Destroy ->
receiver release) — and run through the Python reference and, when `OWEN_RUST_CORE` names an
own-cli, through Rust with `OWEN_P037X_GUARDED=0` (must equal the reference's codes). The mutant
rows are RECORDED FAILURES: a name rule must produce the wrong verdict there, and a mutant row
that stopped failing is a change to classify, never a fix.

The table is the RECORD of the Stage 1 measurement (paper-eval/resource-
effects/stage1-oracle-v1.json); a row that moves is a change to classify, never one to repair
here. Codes are compared as multisets at `--severity warning`. The sub-stage 1b rows
(`OWEN_RE_MINTED_RETURN=1`) are recorded separately below.

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
_CONTROLS = os.path.join("corpus", "re-controls")
_KEYS = os.path.join(_CONTROLS, "keys")
_CODE = re.compile(r"\[(OWN\d{3})\]")

# control -> {arm: codes}; arms: "none", "key" (the identity answer key),
# "mutant" (the name-rule key)
_RECORD: dict[str, dict[str, list[str]]] = {
    # H1: a same-named first-party CreateLinkedTokenSource returning a SHARED source
    "h1-shared-createlinked": {"none": [], "key": [], "mutant": ["OWN001"]},
    # H2: Delete on a collection-like receiver is not a release of the receiver
    "h2-bucket-delete": {"none": ["OWN001"], "key": ["OWN001"], "mutant": ["OWN002"]},
    # H3: a Create*-named alias; the M1 mutant is absorbed by the argument-escape optimism
    # (recorded NOT_DISCRIMINATING for M1: the fabricated fresh result yields no false verdict)
    "h3-createfrom-alias": {"none": [], "key": [], "mutant": []},
    # H4: a conditional release named Release; the M2 mutant fabricates the release
    "h4-conditional-release": {"none": [], "key": [], "mutant": ["OWN002", "OWN003"]},
    # H5: the wrapper Drop(k) { k.Delete(); } composes through the consumer inference under the key;
    # without a key the key is kept by the caller (two FALSE OWN001 in the baseline)
    "h5-wrapper-release": {"none": ["OWN001", "OWN001"], "key": ["OWN002"]},
    # H6: a wrapper around the factory: silent under both (the bare-return rule is gated on `new`ed
    # candidates; sub-stage 1b below)
    "h6-wrapper-factory": {"none": [], "key": []},
}
# H4b: the same conditional release NAMED Close — the production name set's pre-existing behaviour,
# an observation (recorded, never repaired here)
_OBSERVATION: dict[str, list[str]] = {"h4b-conditional-close": ["OWN002", "OWN003"]}
# sub-stage 1b (OWEN_RE_MINTED_RETURN=1): control -> {arm: codes}, filled by the Stage 1 record
_RECORD_1B: dict[str, dict[str, list[str]]] = {
    "h1-shared-createlinked": {"none": [], "key": []},
    "h2-bucket-delete": {"none": ["OWN001"], "key": ["OWN001"]},
    "h3-createfrom-alias": {"none": [], "key": []},
    "h4-conditional-release": {"none": [], "key": []},
    "h5-wrapper-release": {"none": ["OWN001", "OWN001"], "key": ["OWN002"]},
    # the wrapper's factory-minted local is the transfer out: OpenLog (File.OpenRead, no key) and
    # MakeLinked (the key) both return fresh, and both callers leak (the truth)
    "h6-wrapper-factory": {"none": ["OWN001"], "key": ["OWN001", "OWN001"]},
}


# Stage 2 (OWEN_RE_MINTED_RETURN=1 OWEN_RE_BODY=1): the body-derived effects on the
# corpus/re-cfg-probe witness shapes: E2 (receiver release from a body: s15) and E1 (fresh for
# direct returns: s08b);
# the Stage 2 record is paper-eval/resource-effects/stage2-body-effects-v1.json
_RECORD_2: dict[str, list[str]] = {
    # RunUse uses c after Kill() (OWN002); RunMaybe keeps c (OWN001, the truth); Run / RunDrop clean
    "s15-receiver-release-body": ["OWN001", "OWN002"],
    # Drop1..Drop3 leak the fresh results of Make / Make2 / Make3; Drop4 (Make4: mixed) is silent
    "s08b-caller": ["OWN001", "OWN001", "OWN001"],
}
_SHAPES = os.path.join("corpus", "re-cfg-probe")


def _codes(text: str) -> list[str]:
    return sorted(_CODE.findall(text))


def _run(argv: list[str], env: dict[str, str]) -> str:
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True, env=env)
    return p.stdout + p.stderr


def _check(name: str, arm: str, want: list[str], ext_env: dict[str, str], tmp: str,
           rust: str | None, env: dict[str, str], fails: list[str],
           folder: str = _CONTROLS) -> None:
    src = os.path.join(folder, f"{name}.cs")
    facts = os.path.join(tmp, f"{name}.{arm}.json")
    try:
        subprocess.run(["dotnet", "run", "--project", _EXT, "--", "--flow-locals", src,
                        "-o", facts], cwd=_REPO, check=True, capture_output=True,
                       text=True, env={**os.environ, **ext_env})
    except subprocess.CalledProcessError as exc:
        fails.append(f"{name} [{arm}]: the extractor exited {exc.returncode}: {exc.stderr[-300:]}")
        return
    py = _codes(_run([sys.executable, "-m", "ownlang", "ownir", facts, "--severity", "warning"],
                     env))
    if collections.Counter(py) != collections.Counter(want):
        fails.append(f"{name} [{arm}]: python {py} != recorded {want}")
    if rust:
        off = _codes(_run([rust, "ownir", facts, "--severity", "warning"],
                          {**env, "OWEN_P037X_GUARDED": "0"}))
        if collections.Counter(off) != collections.Counter(py):
            fails.append(f"{name} [{arm}]: rust flag-off {off} != python {py} (parity)")


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    if not shutil.which("dotnet"):
        print("re controls: FAIL - dotnet is REQUIRED (OWN_TIERB_REQUIRED=1) and not on PATH"
              if required else "re controls: SKIP - dotnet not on PATH")
        return 1 if required else 0
    rust = os.environ.get("OWEN_RUST_CORE")
    if rust and not os.path.isfile(rust):
        rust = None
    env = {**os.environ, "PYTHONPATH": _REPO}
    for k in ("OWEN_RE_ORACLE", "OWEN_RE_MINTED_RETURN", "OWEN_RE_BODY"):
        env.pop(k, None)
        os.environ.pop(k, None)
    key = os.path.join(_REPO, _KEYS, "answer-key.json")
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, arms in sorted(_RECORD.items()):
            for arm, want in arms.items():
                ext_env = {}
                if arm == "key":
                    ext_env = {"OWEN_RE_ORACLE": key}
                elif arm == "mutant":
                    ext_env = {"OWEN_RE_ORACLE": os.path.join(_REPO, _KEYS, f"mutant-{name}.json")}
                _check(name, arm, want, ext_env, tmp, rust, env, fails)
        for name, want in sorted(_OBSERVATION.items()):
            _check(name, "none", want, {}, tmp, rust, env, fails)
        for name, arms in sorted(_RECORD_1B.items()):
            for arm, want in arms.items():
                ext_env = {"OWEN_RE_MINTED_RETURN": "1"}
                if arm == "key":
                    ext_env["OWEN_RE_ORACLE"] = key
                _check(name, f"1b-{arm}", want, ext_env, tmp, rust, env, fails)
        for name, want in sorted(_RECORD_2.items()):
            _check(name, "body", want, {"OWEN_RE_MINTED_RETURN": "1", "OWEN_RE_BODY": "1"}, tmp,
                   rust, env, fails, folder=_SHAPES)
    for f in fails:
        print(f"FAIL: {f}")
    n = (sum(len(a) for a in _RECORD.values()) + len(_OBSERVATION)
         + sum(len(a) for a in _RECORD_1B.values()) + len(_RECORD_2))
    print(f"re controls: {n} row(s), {len(fails)} failed"
          + ("" if rust else " (Rust parity not checked: OWEN_RUST_CORE unset)"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
