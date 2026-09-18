#!/usr/bin/env python3
"""#262 Stage 3 — the rollback path, and the four states it is easy to conflate.

Stage 3 moved the public default to Rust. #262 requires that the way back is
**documented, explicit and tested**, and that it is never automatic:

    Rollback must be a documented engine selection or package patch, not a
    hidden automatic fallback. A Rust failure must remain observable.

The whole content of this file is that "explicit" and "automatic" are
different, and that proving the first does not prove the absence of the second.
A launcher with a hidden fallback passes any test that only ever asks for
Python on purpose -- it would answer correctly every time. So the states are
driven apart:

    1  default, candidate fine            -> RUST runs
    2  Python explicitly selected         -> PYTHON runs
    3  candidate BROKEN, nothing asked    -> VISIBLE FAILURE
    4  candidate BROKEN, Python asked     -> PYTHON runs

3 and 4 are the pair that matters and they are one flag apart. A hidden
fallback makes 3 look like 4: the user gets an answer, from an engine they did
not choose, and nothing says so. 1 and 2 together are what makes 3 and 4 mean
anything -- without them a launcher that simply never worked would pass 3.

The rollback is also proved to be a rollback rather than merely A path: in
state 4 the finding Python produces is compared against the finding Rust
produced in state 1, over the same sample, because a rollback that answered
something else would not be a rollback.

Run:  python tests/test_stage3_rollback.py
      python tests/run_tests.py            (in the suite)

Environment:
    OWEN_RUST_CORE              the production candidate (required to measure)
    OWEN_STAGE1_LAUNCHER_DLL    the built `ownsharp.dll` (the `owen` launcher)
    OWEN_STAGE3_REQUIRE=1       turn every skip into a failure
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

SAMPLE_CS = """using System.IO;
public class Leaky
{
    public void Run()
    {
        var s = new MemoryStream();
        s.WriteByte(1);
    }
}
"""

# The one finding every state below is measured against.
EXPECT_CODE = b"OWN001"

# D3.1: a candidate that cannot be resolved or started is a CONFIGURATION
# error, in the same tier as a usage mistake. Never 3 (Python-specific), never
# 5 (Owen's own internal failure), and never a verdict.
CONFIG_ERROR = 2


def _fail(msg: str, *, check: str) -> int:
    print(f"FAIL[{check}]: {msg}")
    return 1


def _skip(check: str, why: str) -> None:
    print(f"skip[{check}]: {why}")


def _bash() -> str:
    return os.environ.get("OWEN_BASH", "bash")


def _launcher() -> str | None:
    dll = os.environ.get("OWEN_STAGE1_LAUNCHER_DLL")
    return dll if dll and os.path.isfile(dll) else None


def _core() -> str | None:
    core = os.environ.get("OWEN_RUST_CORE")
    return core if core and os.path.isfile(core) else None


def _surfaces(sample: Path) -> list[tuple[str, list[str], list[str]]]:
    """(name, argv for a DEFAULT run, argv for an EXPLICIT PYTHON run).

    Both shell surfaces and the launcher are driven, because "the rollback
    works" is a claim about the launcher surfaces a user actually has, and
    Stage 3 moved all of them together.
    """
    out: list[tuple[str, list[str], list[str]]] = [
        ("own-check.sh",
         [_bash(), str(Path(_ROOT) / "scripts/own-check.sh"), "--format", "human",
          "--", str(sample)],
         [_bash(), str(Path(_ROOT) / "scripts/own-check.sh"), "--format", "human",
          "--engine", "python", "--", str(sample)]),
    ]
    dll = _launcher()
    if dll is not None:
        out.append((
            "owen",
            ["dotnet", dll, "check", "--format", "human", str(sample)],
            ["dotnet", dll, "check", "--format", "human", "--engine", "python", str(sample)]))
    return out


def _run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, cwd=_ROOT,
                          env=dict(os.environ, **env), check=False)


def run() -> int:
    require = os.environ.get("OWEN_STAGE3_REQUIRE") == "1"
    core = _core()
    if core is None:
        _skip("stage3-rollback", "no OWEN_RUST_CORE, so no state could be measured")
        if require:
            return _fail("OWEN_STAGE3_REQUIRE=1 but OWEN_RUST_CORE is unset or not a file",
                         check="stage3-rollback")
        return 0
    if shutil.which("dotnet") is None:
        _skip("stage3-rollback", "no dotnet, so no surface could be run")
        if require:
            return _fail("OWEN_STAGE3_REQUIRE=1 but dotnet is not available",
                         check="stage3-rollback")
        return 0

    failures = 0
    with tempfile.TemporaryDirectory(prefix="owen-stage3-rollback-") as td:
        sample = Path(td) / "sample"
        sample.mkdir()
        (sample / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")

        # A candidate that EXISTS and cannot possibly run. Deliberately not a
        # missing path: "broken" and "absent" reach the same tier by design, and
        # the harder of the two to get right is the one that is there.
        broken = Path(td) / "not-a-core"
        broken.write_text("this is not an executable image\n", encoding="utf-8")
        broken.chmod(0o755)

        good = {"OWEN_RUST_CORE": core}
        bad = {"OWEN_RUST_CORE": str(broken)}

        for name, default_argv, python_argv in _surfaces(sample):
            # STATE 1 — the default, everything fine. Rust runs.
            r1 = _run(default_argv, good)
            if EXPECT_CODE not in r1.stdout:
                failures += _fail(
                    f"{name}: the DEFAULT run produced no {EXPECT_CODE.decode()} "
                    f"(exit {r1.returncode}) — state 1 is the baseline the others are "
                    f"measured against",
                    check="rollback-state-1-default-is-rust")
                continue

            # STATE 2 — Python explicitly selected. It runs, and it AGREES.
            r2 = _run(python_argv, good)
            if EXPECT_CODE not in r2.stdout:
                failures += _fail(
                    f"{name}: the explicit rollback produced no {EXPECT_CODE.decode()} "
                    f"(exit {r2.returncode}) — the documented way back does not work",
                    check="rollback-state-2-explicit-python")
            elif r2.stdout != r1.stdout:
                # Not a parity gate (that is #260's job over the whole matrix) —
                # a rollback-specific one: the way back must lead to the same
                # answer, or it is a different product rather than a rollback.
                failures += _fail(
                    f"{name}: the rollback's verdict differs from the default's on the same "
                    f"sample.\n    default: {r1.stdout!r}\n    rollback: {r2.stdout!r}",
                    check="rollback-state-2-agrees")

            # STATE 3 — candidate broken, NOTHING asked for. Visible failure.
            r3 = _run(default_argv, bad)
            merged3 = (r3.stdout + r3.stderr).decode("utf-8", "replace")
            if EXPECT_CODE in r3.stdout:
                failures += _fail(
                    f"{name}: a broken candidate with NO rollback requested still produced a "
                    f"verdict — something fell back to Python automatically, which no stage "
                    f"of #262 allows",
                    check="rollback-state-3-no-automatic-fallback")
            elif r3.returncode != CONFIG_ERROR:
                failures += _fail(
                    f"{name}: a broken candidate exited {r3.returncode}, expected the "
                    f"configuration-error tier {CONFIG_ERROR} (not 3 — that is "
                    f"Python-specific; not 5 — that is an internal failure)",
                    check="rollback-state-3-no-automatic-fallback")
            elif "did not fall back to Python" not in merged3:
                failures += _fail(
                    f"{name}: the failure does not DENY a Python fallback in as many words, so "
                    f"a reader cannot tell state 3 from a silent one",
                    check="rollback-state-3-no-automatic-fallback")

            # STATE 4 — candidate broken AND Python asked for. Python runs.
            # One flag away from state 3, and the whole point of keeping them
            # apart: this must work even though the candidate is unusable,
            # because the rollback does not depend on the thing being rolled
            # back from.
            r4 = _run(python_argv, bad)
            if EXPECT_CODE not in r4.stdout:
                failures += _fail(
                    f"{name}: the rollback did not run with a BROKEN candidate present "
                    f"(exit {r4.returncode}) — the way back must not depend on the engine it "
                    f"is a way back from. stderr: "
                    f"{r4.stderr.decode('utf-8', 'replace')[:300]}",
                    check="rollback-state-4-works-when-rust-is-broken")
            elif r4.stdout != r1.stdout:
                failures += _fail(
                    f"{name}: the rollback under a broken candidate answered differently from "
                    f"the default's baseline", check="rollback-state-4-works-when-rust-is-broken")

            if not failures:
                print(f"  ok[{name}]: default=Rust; explicit python agrees; broken candidate "
                      f"fails visibly (exit {r3.returncode}); explicit python still runs")

    if failures:
        return 1
    print(
        "stage-3 rollback OK: on every launcher surface the four states stay distinct — the "
        "default runs Rust, an explicit --engine python runs the reference and agrees with it, "
        "a broken candidate with nothing asked for is a visible configuration error that denies "
        "a fallback in as many words, and an explicit --engine python still runs when the "
        "candidate is broken. No state produced an answer from an engine nobody selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
