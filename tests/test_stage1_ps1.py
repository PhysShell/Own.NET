#!/usr/bin/env python3
"""#262 Stage 1 — `scripts/own-check.ps1`'s engine contract, driven.

Why this exists as its own harness. `tests/test_stage1_engine.py` drives the
`owen` launcher and `own-check.sh`; the PowerShell surface was only ever
touched by a CI smoke step (healthy `-Engine rust`, and a NONEXISTENT
OWEN_RUST_CORE). That is real coverage, but it never reaches compare,
agreement replay, an existing-but-unstartable candidate, or execution-failure
evidence — which is exactly why three PowerShell defects sat green through a
16/16 mutation campaign. Absence of a control is not evidence of correctness,
and a campaign can only prove what some control actually observes.

The controls here are the PowerShell halves of the ratified rulings:

    ps1-absolute-locator      D3    a relative but existing locator is refused
    ps1-not-started-is-2      D3.1  an existing file the loader will not start
                                    is a configuration error (2), not 5
    ps1-agreement-replays     D4.1a agreement replays the reference's RAW bytes
                                    on BOTH streams, not a re-encoded stdout
    ps1-failure-evidence      D4.1c the reproduction evidence it names still
                                    exists after the process exits

Platform. These drive `pwsh`, which runs on Linux too, and every control here
is written to be platform-neutral so it can be developed and debugged
anywhere. That convenience does NOT make a Linux run acceptable as evidence: a
mutation whose target is `scripts/own-check.ps1` is only `caught` when a
WINDOWS PowerShell catcher observes the mutant and fails. The campaign that
owns these mutants therefore runs on a Windows runner
(`.github/workflows/ci.yml`, the `stage1-ps1-mutations` job), and a Linux run
of this file is a developer convenience, never the record.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_stage1_ps1.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CS = """using System;
using System.IO;

public class Leaky
{
    public void Run()
    {
        var s = new FileStream("x.txt", FileMode.OpenOrCreate);
        Console.WriteLine(s.Length);
    }
}
"""

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []
_SKIPS: list[tuple[str, str]] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]{': ' + detail if detail else ''}")


def skip(check: str, why: str) -> None:
    """Under OWEN_STAGE1_REQUIRE a skip is a failure: the job that sets it
    exists to supply the toolchain, so a control that could not run there is a
    denominator that quietly shrank."""
    if os.environ.get("OWEN_STAGE1_REQUIRE") == "1":
        fail(check, f"required control could not run: {why}")
        return
    _SKIPS.append((check, why))
    print(f"skip[{check}]: {why}")


def tail(r: subprocess.CompletedProcess[bytes], limit: int = 400) -> str:
    err = r.stderr.decode("utf-8", "replace").strip()
    out = r.stdout.decode("utf-8", "replace").strip()
    parts = []
    if err:
        parts.append(f"stderr: …{err[-limit:]}")
    if out:
        parts.append(f"stdout: …{out[-limit:]}")
    return " | ".join(parts) or "(both streams empty)"


# --- toolchain -------------------------------------------------------------


def pwsh_exe() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def rust_core() -> str | None:
    p = os.environ.get("OWEN_RUST_CORE")
    return p if p and Path(p).is_file() else None


def stub_exe(tmp: Path) -> str | None:
    """The controllable native candidate, shared with the other harness."""
    supplied = os.environ.get("OWEN_STAGE1_STUB")
    if supplied and Path(supplied).is_file():
        return supplied
    if shutil.which("rustc") is None:
        return None
    out = tmp / ("stage1-stub.exe" if os.name == "nt" else "stage1-stub")
    if out.is_file():
        return str(out)
    r = subprocess.run(
        ["rustc", "-O", str(ROOT / "tests/helpers/stage1_stub.rs"), "-o", str(out)],
        capture_output=True, check=False)
    return str(out) if r.returncode == 0 and out.is_file() else None


def run_ps1(args: list[str], env: dict[str, str] | None = None,
            cwd: str | None = None) -> subprocess.CompletedProcess[bytes] | None:
    """Drive own-check.ps1, capturing RAW bytes — the replay contract is about
    bytes, so the harness must not decode on the way in either."""
    pwsh = pwsh_exe()
    if pwsh is None:
        return None
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-File", str(ROOT / "scripts/own-check.ps1"), *args],
        capture_output=True, env=e, cwd=cwd or str(ROOT), check=False)


# --- controls --------------------------------------------------------------


def control_absolute_locator(sample: Path, tmp: Path) -> None:
    """D3: a relative locator resolves against the working directory, so the
    same variable would select different binaries from different places."""
    check = "ps1-absolute-locator"
    core = rust_core()
    if core is None:
        skip(check, "no OWEN_RUST_CORE")
        return
    workdir = tmp / "ps1-relative-cwd"
    workdir.mkdir(exist_ok=True)
    local = workdir / ("own-cli.exe" if os.name == "nt" else "own-cli")
    shutil.copy2(core, local)
    if os.name != "nt":
        local.chmod(0o755)

    problems = []
    for engine in ("rust", "compare"):
        r = run_ps1(["-Engine", engine, "-Format", "human", str(sample)],
                    env={"OWEN_RUST_CORE": f".{os.sep}{local.name}"}, cwd=str(workdir))
        if r is None:
            skip(check, "no pwsh")
            return
        merged = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode != 2:
            problems.append(f"{engine}: exit {r.returncode}, expected 2 [{tail(r)}]")
        elif "absolute" not in merged:
            problems.append(f"{engine}: refused without naming the absolute requirement")
        if b"OWN001" in r.stdout:
            problems.append(f"{engine}: produced a verdict for a relative locator")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "a relative but existing locator is refused with exit 2")


def control_not_started_is_2(sample: Path, tmp: Path) -> None:
    """D3.1: a candidate that EXISTS but the loader will not start never got to
    run, so it is on the locator's side of the seam — exit 2, not 5.

    This is the case the CI smoke step could not reach: it used a NONEXISTENT
    path, which `Test-Path` rejects long before any spawn.
    """
    check = "ps1-not-started-is-2"
    unstartable = tmp / "not-a-program.txt"
    unstartable.write_text("this is text, not an executable image\n", encoding="utf-8")

    problems = []
    for engine in ("rust", "compare"):
        r = run_ps1(["-Engine", engine, "-Format", "human", str(sample)],
                    env={"OWEN_RUST_CORE": str(unstartable.resolve())})
        if r is None:
            skip(check, "no pwsh")
            return
        merged = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode == 5:
            problems.append(f"{engine}: exit 5 — a candidate that never started was reported as "
                            "an internal failure instead of a configuration error")
        elif r.returncode != 2:
            problems.append(f"{engine}: exit {r.returncode}, expected 2 [{tail(r)}]")
        elif "could not be started" not in merged:
            problems.append(f"{engine}: exit 2 without saying the candidate could not be started")
        if b"OWN001" in r.stdout:
            problems.append(f"{engine}: produced a verdict — Python answered for the candidate")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "an existing-but-unstartable candidate is exit 2 on both engine paths")


def control_agreement_replays_bytes(sample: Path, tmp: Path) -> None:
    """D4.1(a): on agreement the external result is the REFERENCE's — its raw
    bytes, on both streams.

    Agreement is manufactured deliberately: the candidate is handed the exact
    bytes the Python reference produces for this input, so the two engines
    genuinely agree. That is the only way to reach this branch on Windows,
    where a real candidate diverges from the reference on CRLF alone — and the
    branch has to be right for when it becomes reachable, not merely for as
    long as it is rare.
    """
    check = "ps1-agreement-replays"
    stub = stub_exe(tmp)
    if stub is None:
        skip(check, "no native stub (set OWEN_STAGE1_STUB or provide rustc)")
        return
    if shutil.which("dotnet") is None or shutil.which("python") is None:
        skip(check, "no dotnet/python")
        return

    # Extract once, then ask the reference what it says about those facts.
    facts = tmp / "agree.facts.json"
    ex = subprocess.run(
        [str(ROOT / "scripts/own-check.sh"), "--emit-facts", str(facts), "--", str(sample)],
        capture_output=True, check=False, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    if not facts.is_file():
        skip(check, f"could not extract facts to drive the reference [{tail(ex)}]")
        return
    ref = subprocess.run(
        ["python", "-m", "ownlang", "ownir", str(facts),
         "--format", "human", "--severity", "error", "--verbosity", "normal"],
        capture_output=True, check=False, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)})

    env = {"OWEN_RUST_CORE": stub,
           "STAGE1_STUB_EXIT": str(ref.returncode)}
    out_file = tmp / "ref.out.bin"
    err_file = tmp / "ref.err.bin"
    out_file.write_bytes(ref.stdout)
    err_file.write_bytes(ref.stderr)
    env["STAGE1_STUB_STDOUT_FILE"] = str(out_file)
    env["STAGE1_STUB_STDERR_FILE"] = str(err_file)

    r = run_ps1(["-Engine", "compare", "-Format", "human", str(sample)], env=env)
    if r is None:
        skip(check, "no pwsh")
        return
    if r.returncode not in (0, 1):
        skip(check, f"the engines did not agree, so the replay branch was not reached "
                    f"(exit {r.returncode}) [{tail(r)}]")
        return

    problems = []
    if r.stdout != ref.stdout:
        problems.append(f"stdout replay is not byte-faithful: {len(r.stdout)} bytes replayed vs "
                        f"{len(ref.stdout)} from the reference")
    if ref.stderr and r.stderr != ref.stderr:
        problems.append(f"stderr replay is not byte-faithful: {len(r.stderr)} bytes replayed vs "
                        f"{len(ref.stderr)} from the reference (a dropped stderr reads as a "
                        "silent run)")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"agreement replays the reference's raw bytes on both streams "
                  f"({len(ref.stdout)} out, {len(ref.stderr)} err)")


def control_failure_evidence_exists(sample: Path, tmp: Path) -> None:
    """D4.1(c): the reproduction evidence a failure NAMES has to survive it.

    Pointing a reader at a directory and deleting it on the way out is worse
    than naming nothing: the message reads as reproducible and is not.
    """
    check = "ps1-failure-evidence"
    stub = stub_exe(tmp)
    if stub is None:
        skip(check, "no native stub (set OWEN_STAGE1_STUB or provide rustc)")
        return
    r = run_ps1(["-Engine", "compare", "-Format", "human", str(sample)],
                env={"OWEN_RUST_CORE": stub, "STAGE1_STUB_EXIT": "42"})
    if r is None:
        skip(check, "no pwsh")
        return
    merged = (r.stdout + r.stderr).decode("utf-8", "replace")
    if r.returncode != 5:
        fail(check, f"a compare execution failure exited {r.returncode}, expected 5 [{tail(r)}]")
        return

    problems = []
    if "42" not in merged:
        problems.append("the raw candidate status is not retained in the diagnostic")
    # Whatever the message advertises as evidence must still be there. A path
    # is only acceptable if it survives; otherwise the message must carry the
    # reproduction inline.
    named = [tok.strip().rstrip(".,") for tok in merged.replace("\n", " ").split()
             if ("owen-compare-" in tok)]
    missing = [n for n in named if not Path(n).exists()]
    if missing:
        problems.append(f"names evidence that no longer exists after exit: {missing[:2]}")
    if not named and "sha256" not in merged:
        problems.append("names neither a surviving artifact directory nor an inline "
                        "reproduction (input digest)")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "the advertised reproduction evidence survives the process")


# --- harness ---------------------------------------------------------------


def run() -> int:
    if pwsh_exe() is None:
        skip("ps1-harness", "no pwsh on this machine")
        print("\nstage-1 ps1 controls: no PowerShell available")
        return 1 if _FAILURES else 0

    with tempfile.TemporaryDirectory(prefix="owen-stage1-ps1-") as td:
        tmp = Path(td)
        sample_dir = tmp / "sample"
        sample_dir.mkdir()
        (sample_dir / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")

        control_absolute_locator(sample_dir, tmp)
        control_not_started_is_2(sample_dir, tmp)
        control_agreement_replays_bytes(sample_dir, tmp)
        control_failure_evidence_exists(sample_dir, tmp)

    print()
    print(f"stage-1 ps1 controls: {len(_PASSES)} passed, {len(_FAILURES)} failed, "
          f"{len(_SKIPS)} skipped")
    for name, why in _SKIPS:
        print(f"    skip {name}: {why}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
