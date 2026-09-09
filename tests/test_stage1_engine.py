#!/usr/bin/env python3
"""#262 Stage 1 — the launcher's engine-selection contract, measured.

Stage 1 makes the Rust core *selectable* by the launcher while Python stays the
default and the reference. That is a claim about a seam, and a seam is proved
by driving it, not by reading it: every check below runs a real launcher
against a real candidate binary and asserts on the observable result — the exit
code, the streams, the evidence file.

The fifteen ratified adversarial controls, each named by the misreading it
catches:

    default-stays-python      the default silently becomes Rust
    rust-actually-runs-rust   explicit Rust selection actually runs Python
    rust-failure-no-fallback  a Rust failure runs Python
    unexpected-rc-maps-to-5   an unexpected rc escapes as itself instead of 5
    raw-rc-retained           the raw rc is lost from the evidence
    rc70-is-not-a-verdict     rc 70 is read as a finding or as clean
    no-selector-in-own-cli    engine selection leaks into `own-cli`
    compare-extracts-once     compare extracts twice
    compare-same-input        compare feeds the engines different bytes and
                              still reports agreement
    compare-no-substitution   one compare engine fails and the other's answer
                              is used
    compare-zero-document     a zero-document compare passes
    candidate-identity        a stale binary stands in without its recorded
                              identity changing
    divergence-is-5           a divergence is exposed as a normal result, or as
                              exit 1, instead of 5
    exec-failure-is-5         a compare execution failure exits anything but 5,
                              or omits failure evidence
    bad-locator-is-2          an invalid OWEN_RUST_CORE produces anything other
                              than exit 2, falls back to Python, or is mapped
                              to 3 or 5

Failures print `FAIL[<check>]: <detail>` so a mutation campaign names the CHECK
that caught it rather than whichever case tripped first, and the run never
stops at the first failure — a campaign needs every catcher a mutation trips,
not the earliest one.

Forcing the failures uses #261's own off-by-default `fault-injection` feature
(`OWN_CLI_FAULT_PANIC`, `OWN_CLI_FAULT_ABORT`) against the REAL production
binary rather than a stub that only resembles one: a control that proves a
mock's behaviour proves nothing about the candidate. A stub is used for exactly
one case — pinning an arbitrary exit code such as 42, which no fault the real
binary offers produces on purpose.

Toolchain. These controls need a built `own-cli` and a built launcher; the
environment names them:

    OWEN_RUST_CORE              the production candidate (required)
    OWEN_STAGE1_RUST_FAULT      an `own-cli` built --features fault-injection
    OWEN_STAGE1_LAUNCHER_DLL    the built `ownsharp.dll` (the `owen` launcher)
    OWEN_STAGE1_REQUIRE=1       every toolchain-dependent control MUST run

`OWEN_STAGE1_REQUIRE=1` is the zero-denominator guard: without it a machine
lacking the toolchain skips and says so, but in CI — where the job exists to
provide that toolchain — a skip is indistinguishable from a pass, so the flag
turns every skip into a failure.

Run:  python tests/test_stage1_engine.py
      python tests/run_tests.py            (in the suite)
"""

from __future__ import annotations

import hashlib
import json
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

# A syntactically valid C# file with nothing an analysis can be about: it
# produces an OwnIR document whose collections are all empty, which is the
# zero-document case compare must refuse rather than call agreement.
EMPTY_CS = """namespace Nothing
{
}
"""

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []
_SKIPS: list[tuple[str, str]] = []
_NOT_APPLICABLE: list[tuple[str, str]] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]{': ' + detail if detail else ''}")


def skip(check: str, why: str) -> None:
    """A skip is a real outcome, not a quiet pass — and under
    OWEN_STAGE1_REQUIRE it is a failure, because the job that sets that flag
    exists precisely to make the control runnable."""
    if os.environ.get("OWEN_STAGE1_REQUIRE") == "1":
        fail(check, f"required control could not run: {why}")
        return
    _SKIPS.append((check, why))
    print(f"skip[{check}]: {why}")


def not_applicable(check: str, why: str) -> None:
    """A control that CANNOT exist on this platform, as opposed to one that
    could not run here.

    The difference is not bookkeeping. `skip()` means the toolchain was
    missing, and under OWEN_STAGE1_REQUIRE that is a failure because the CI job
    exists to supply it. This means the control is not a question this platform
    can be asked — a synthetic candidate binary needs a shebang, and Windows
    has none — so requiring it would only produce a red job that no amount of
    correct code could turn green. It is still printed, and still counted
    separately, so a control cannot quietly disappear behind it.
    """
    _NOT_APPLICABLE.append((check, why))
    print(f"n/a[{check}]: {why}")


# --- toolchain -------------------------------------------------------------


def rust_core() -> str | None:
    p = os.environ.get("OWEN_RUST_CORE")
    return p if p and Path(p).is_file() else None


def rust_fault_core() -> str | None:
    p = os.environ.get("OWEN_STAGE1_RUST_FAULT")
    return p if p and Path(p).is_file() else None


def launcher_dll() -> str | None:
    p = os.environ.get("OWEN_STAGE1_LAUNCHER_DLL")
    if p and Path(p).is_file():
        return p
    for cfg in ("Release", "Debug"):
        cand = ROOT / "frontend/roslyn/OwnSharp.Cli/bin" / cfg / "net8.0/ownsharp.dll"
        if cand.is_file():
            return str(cand)
    return None


def have_dotnet() -> bool:
    return shutil.which("dotnet") is not None


def bash_exe() -> str:
    """The bash that can actually run `own-check.sh`.

    On a Windows runner `bash` on PATH is `C:\\Windows\\System32\\bash.exe` —
    the WSL launcher, not a shell. With no distribution installed it prints
    "You can resolve this by installing a distribution..." to stderr in UTF-16
    and exits 1, which arrives here as a plausible-looking script failure and
    is nothing of the kind. Git for Windows ships the bash that own-check.sh is
    written for, so it is named explicitly and System32 is refused outright.

    This is a HARNESS concern, not a product one: a Windows user running
    own-check.sh does so from a git-bash prompt, where `bash` is already the
    right one.
    """
    if os.name != "nt":
        return "bash"
    candidates = [
        os.environ.get("SHELL"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ]
    for cand in candidates:
        if cand and "system32" not in cand.lower() and Path(cand).is_file():
            return cand
    return "bash"


def run_own_check(args: list[str], env: dict[str, str] | None = None,
                  cwd: str | None = None) -> subprocess.CompletedProcess[bytes]:
    """own-check.sh, with raw bytes: the compare contract is about bytes."""
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        [bash_exe(), str(ROOT / "scripts/own-check.sh"), *args],
        capture_output=True, env=e, cwd=cwd or str(ROOT), check=False)


def run_owen(args: list[str], env: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess[bytes] | None:
    dll = launcher_dll()
    if dll is None or not have_dotnet():
        return None
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        ["dotnet", dll, "check", *args],
        capture_output=True, env=e, cwd=str(ROOT), check=False)


def tail(r: subprocess.CompletedProcess[bytes], limit: int = 500) -> str:
    """The child's own words, for a failure message.

    A control that says only "expected 2, got 1" hands the reader a number and
    keeps the reason to itself — and when the failure happens on a platform the
    author cannot reproduce, that reason is the whole diagnosis.
    """
    err = r.stderr.decode("utf-8", "replace").strip()
    out = r.stdout.decode("utf-8", "replace").strip()
    parts = []
    if err:
        parts.append(f"stderr: …{err[-limit:]}")
    if out:
        parts.append(f"stdout: …{out[-limit:]}")
    return " | ".join(parts) or "(both streams empty)"


def write_stub(path: Path, exit_code: int, stdout: str = "", stderr: str = "") -> Path:
    """A candidate that exits with a chosen code. Unix only — the real
    fault-injection binary covers both platforms for the cases it can force."""
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' {json.dumps(stdout)}\n"
        f"printf '%s' {json.dumps(stderr)} >&2\n"
        f"exit {exit_code}\n",
        encoding="utf-8")
    path.chmod(0o755)
    return path


# --- the controls ----------------------------------------------------------


def control_bad_locator_is_2(sample: Path, tmp: Path) -> None:
    """D3.1: a missing/empty/nonexistent/non-file/non-executable
    OWEN_RUST_CORE, for --engine rust|compare, is exit 2 — never 3 (that is
    Python-specific), never 5 (that is an internal failure), and never a
    fallback that quietly produces a Python answer."""
    check = "bad-locator-is-2"
    not_exec = tmp / "not-executable"
    not_exec.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    not_exec.chmod(0o644)
    a_dir = tmp / "a-directory"
    a_dir.mkdir(exist_ok=True)

    cases = {
        "unset": None,
        "empty": "",
        "nonexistent": str(tmp / "definitely-absent"),
        "directory": str(a_dir),
        "non-executable": str(not_exec),
    }
    problems = []
    # D2: the locator contract is ONE contract, so it is driven on BOTH the
    # shell surface and the `owen` launcher. Testing only the shell would let
    # the launcher's own exit code drift freely — which is exactly what a
    # campaign mutation of that constant proved.
    surfaces: list[tuple[str, object]] = [("own-check.sh", "shell")]
    if launcher_dll() is not None and have_dotnet():
        surfaces.append(("owen", "launcher"))
    else:
        skip(check + "/owen", "no built launcher/dotnet")

    for surface_name, kind in surfaces:
        for engine in ("rust", "compare"):
            for name, value in cases.items():
                env = {"OWEN_RUST_CORE": value} if value is not None else {}
                e = dict(os.environ)
                e.update(env)
                if value is None:
                    e.pop("OWEN_RUST_CORE", None)
                if kind == "shell":
                    r = subprocess.run(
                        [bash_exe(), str(ROOT / "scripts/own-check.sh"),
                         "--engine", engine, "--", str(sample)],
                        capture_output=True, env=e, cwd=str(ROOT), check=False)
                else:
                    r = subprocess.run(
                        ["dotnet", str(launcher_dll()), "check", "--engine", engine, str(sample)],
                        capture_output=True, env=e, cwd=str(ROOT), check=False)
                where = f"{surface_name}/{engine}/{name}"
                if r.returncode != 2:
                    problems.append(f"{where}: exit {r.returncode}, expected 2 "
                                    "(not 3 — that is Python-specific; not 5 — that is an "
                                    "internal failure)")
                merged = (r.stdout + r.stderr).decode("utf-8", "replace")
                # A fallback would have produced a verdict; the diagnostic must
                # also say, in as many words, that no fallback happened.
                if "finding" in merged and "OWEN_RUST_CORE" not in merged:
                    problems.append(f"{where}: produced a verdict — looks like a fallback")
                if r.returncode == 2 and "did not fall back to Python" not in merged:
                    problems.append(f"{where}: diagnostic does not deny a Python fallback")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"{len(cases) * 2 * len(surfaces)} invalid-locator cases all exit 2, no fallback")


def control_default_stays_python(sample: Path) -> None:
    """D1: the default engine is Python. Proved NEGATIVELY and positively: a
    default run with a deliberately unusable Python must fail on Python (the
    launcher's exit 3), which it cannot do if the default silently moved to
    Rust; and it must not produce a Rust-only success."""
    check = "default-stays-python"
    r = run_owen(["--format", "human", str(sample)],
                 env={"OWEN_PYTHON": "/definitely/not/a/python"})
    if r is None:
        skip(check, "no built launcher/dotnet")
        return
    if r.returncode != 3:
        fail(check, f"default run with a broken OWEN_PYTHON exited {r.returncode}, expected 3 "
                    "(the default engine is not Python any more, or Python is no longer resolved "
                    "for it)")
        return
    ok(check, "the default still resolves Python and fails on it (exit 3)")


def control_rust_actually_runs_rust(sample: Path) -> None:
    """Explicit Rust selection must actually run Rust. Proved by breaking
    Python so thoroughly that a Python run could not succeed, and requiring the
    Rust run to succeed anyway — which also proves the launcher did not resolve
    Python or unpack the vendored core for a Rust-only invocation."""
    check = "rust-actually-runs-rust"
    core = rust_core()
    if core is None:
        skip(check, "no OWEN_RUST_CORE")
        return
    r = run_owen(["--engine", "rust", "--format", "human", str(sample)],
                 env={"OWEN_RUST_CORE": core, "OWEN_PYTHON": "/definitely/not/a/python"})
    if r is None:
        skip(check, "no built launcher/dotnet")
        return
    if r.returncode == 3:
        fail(check, "explicit --engine rust exited 3 (no usable Python) — the Rust path "
                    "still resolves Python")
        return
    if r.returncode not in (0, 1):
        fail(check, f"explicit --engine rust exited {r.returncode} with a broken OWEN_PYTHON; "
                    f"stderr={r.stderr.decode('utf-8', 'replace')[:400]}")
        return
    if b"OWN001" not in r.stdout:
        fail(check, "explicit --engine rust produced no finding for a known-leaky sample")
        return
    ok(check, "Rust ran and produced the verdict with Python unusable")


def control_rust_failure_no_fallback(sample: Path) -> None:
    """A Rust failure is never a Python success. The candidate is forced to
    fail; the launcher must not answer with Python's verdict."""
    check = "rust-failure-no-fallback"
    fault = rust_fault_core()
    if fault is None:
        skip(check, "no OWEN_STAGE1_RUST_FAULT")
        return
    r = run_owen(["--engine", "rust", "--format", "human", str(sample)],
                 env={"OWEN_RUST_CORE": fault, "OWN_CLI_FAULT_PANIC": "1"})
    if r is None:
        skip(check, "no built launcher/dotnet")
        return
    problems = []
    if r.returncode in (0, 1):
        problems.append(f"owen: a forced Rust failure exited {r.returncode} — a verdict was "
                        "produced despite the engine failing (a fallback, or the failure was "
                        "swallowed)")
    elif r.returncode != 5:
        problems.append(f"owen: a forced Rust failure exited {r.returncode}, expected public 5")
    if b"OWN001" in r.stdout:
        problems.append("owen: a forced Rust failure still produced findings — Python answered "
                        "for Rust")

    # The same contract on the shell surface (D2): one contract, both surfaces.
    r2 = run_own_check(["--engine", "rust", "--format", "human", "--", str(sample)],
                       env={"OWEN_RUST_CORE": fault, "OWN_CLI_FAULT_PANIC": "1"})
    if r2.returncode in (0, 1):
        problems.append(f"own-check.sh: a forced Rust failure exited {r2.returncode} — a verdict "
                        f"was produced despite the engine failing [{tail(r2)}]")
    elif r2.returncode != 5:
        problems.append(f"own-check.sh: a forced Rust failure exited {r2.returncode}, expected "
                        f"public 5 [{tail(r2)}]")
    if b"OWN001" in r2.stdout:
        problems.append("own-check.sh: a forced Rust failure still produced findings — Python "
                        "answered for Rust")

    if problems:
        fail(check, "; ".join(problems))
        return
    ok(check, "a forced Rust failure produces no verdict on either launcher surface")


def control_rc70_is_not_a_verdict(sample: Path) -> None:
    """rc 70 is the engines' shared internal-error code: known, still a
    failure. Reading it as findings (1) or as clean (0) is the bug."""
    check = "rc70-is-not-a-verdict"
    fault = rust_fault_core()
    if fault is None:
        skip(check, "no OWEN_STAGE1_RUST_FAULT")
        return
    # The forced panic is #261's measured rc-70 path.
    raw = subprocess.run([fault, "ownir", "--format", "human", "/nonexistent-facts.json"],
                         capture_output=True, check=False,
                         env={**os.environ, "OWN_CLI_FAULT_PANIC": "1"})
    if raw.returncode != 70:
        skip(check, f"the fault build did not produce rc 70 (got {raw.returncode})")
        return
    r = run_owen(["--engine", "rust", "--format", "human", str(sample)],
                 env={"OWEN_RUST_CORE": fault, "OWN_CLI_FAULT_PANIC": "1"})
    if r is None:
        skip(check, "no built launcher/dotnet")
        return
    if r.returncode in (0, 1):
        fail(check, f"a Rust child rc 70 surfaced as {r.returncode} — read as "
                    f"{'clean' if r.returncode == 0 else 'findings'} instead of a failure")
        return
    if r.returncode != 5:
        # Anything else means 70 was treated as a legal engine result and
        # passed through, rather than taking Owen's internal-error path.
        fail(check, f"a Rust child rc 70 surfaced as {r.returncode}, expected public 5 "
                    "(70 is a known failure, never a verdict)")
        return
    ok(check, "a Rust child rc 70 takes the public internal-error path (exit 5)")


def control_unexpected_rc_and_raw_retention(sample: Path, tmp: Path) -> None:
    """An unexpected child status maps to public 5, and the RAW status is
    retained in the diagnostic report's typed `child_exit_code` (D5).

    The unexpected status is forced with #261's own `OWN_CLI_FAULT_ABORT` — an
    uncatchable termination in the REAL candidate — rather than with a stub
    that merely exits with a chosen number. That buys two things: the control
    runs on Windows as well as Linux (a shebang stub does not), and what it
    proves is a property of the binary the launcher will actually spawn. The
    exact raw status is whatever the OS reports for an aborted process, which
    differs by platform and is deliberately NOT contracted (#261's ruling); the
    control measures it first and then requires the report to carry that same
    value.
    """
    map_check, keep_check = "unexpected-rc-maps-to-5", "raw-rc-retained"
    fault = rust_fault_core()
    if fault is None:
        skip(map_check, "no OWEN_STAGE1_RUST_FAULT")
        skip(keep_check, "no OWEN_STAGE1_RUST_FAULT")
        return

    # What does an aborted candidate actually exit with here? Measured, not
    # assumed — and if it lands inside the legal set the control cannot speak.
    probe = subprocess.run([fault, "ownir", "--format", "human", str(tmp / "no-such-facts.json")],
                           capture_output=True, check=False,
                           env={**os.environ, "OWN_CLI_FAULT_ABORT": "1"})
    # Three conventions for the same death, none of them wrong:
    #
    #   Unix, Python subprocess   -6            the negative signal number
    #   Unix, .NET / any shell    134           128 + signal
    #   Windows, Python           3221226505    0xC0000409, unsigned
    #   Windows, .NET             -1073740791   the same bits, signed int32
    #
    # The launcher records what .NET observed, so the expectation is
    # translated into .NET's convention rather than the launcher being asked
    # to adopt Python's. Both translations are measured facts about the
    # runtimes, not fudge factors: the signal form is mapped to 128+signal,
    # and an unsigned 32-bit status is reinterpreted as signed.
    raw = probe.returncode
    if raw < 0 and raw >= -128:          # a Unix signal number
        raw = 128 - raw
    elif raw > 0x7FFFFFFF:               # an unsigned Windows status
        raw -= 0x100000000
    if raw in (0, 1, 2):
        skip(map_check, f"the forced abort produced a legal engine exit ({raw})")
        skip(keep_check, f"the forced abort produced a legal engine exit ({raw})")
        return

    report = Path.home() / ".owen/diag/last-failure.json"
    if report.exists():
        report.unlink()
    r = run_owen(["--engine", "rust", "--format", "human", str(sample)],
                 env={"OWEN_RUST_CORE": fault, "OWN_CLI_FAULT_ABORT": "1"})
    if r is None:
        skip(map_check, "no built launcher/dotnet")
        skip(keep_check, "no built launcher/dotnet")
        return

    if r.returncode == raw:
        fail(map_check, f"an unexpected child rc {raw} escaped as the public exit {raw}")
    elif r.returncode != 5:
        fail(map_check,
             f"an unexpected child rc {raw} surfaced as {r.returncode}, expected public 5")
    else:
        ok(map_check, f"an unexpected child rc {raw} maps to public exit 5")

    if not report.exists():
        fail(keep_check, "no diagnostic report was written for an unexpected child status")
        return
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(keep_check, f"the diagnostic report is unreadable: {exc}")
        return
    if "child_exit_code" not in data:
        fail(keep_check, "the report has no `child_exit_code` field (D5)")
        return
    if not isinstance(data["child_exit_code"], int):
        fail(keep_check, f"`child_exit_code` is {data['child_exit_code']!r}, not a typed integer")
        return
    if data["child_exit_code"] != raw:
        fail(keep_check, f"`child_exit_code` is {data['child_exit_code']}, expected the raw {raw}")
        return
    if data.get("schema") != 2:
        fail(keep_check, f"the report schema is {data.get('schema')!r}, expected 2 (D5 bumped it)")
        return
    ok(keep_check, f"the raw {raw} is retained as a typed child_exit_code, schema 2")


def control_no_selector_in_own_cli() -> None:
    """C-4: `own-cli` presents ONE engine and knows nothing of Python. Engine
    selection must not have leaked into it — neither as an accepted flag nor as
    a source-level concept.

    Note what is deliberately NOT asserted: that the word "python" is absent
    from `own-cli`'s output. Its usage text is the REFERENCE's module
    docstring, frozen byte for byte as #261's C-1 measured it, and that
    docstring says `python -m ownlang ...` because that is what the reference
    prints. Failing on that string would be a control that fires on the
    contract being kept.
    """
    check = "no-selector-in-own-cli"
    core = rust_core()
    if core is None:
        skip(check, "no OWEN_RUST_CORE")
        return
    problems = []

    # An engine selector must not be ACCEPTED. `own-cli` treats it as an
    # unknown argument (the reference's own behaviour: a second positional),
    # which is a usage error — never a selection.
    r = subprocess.run([core, "ownir", "--engine", "python", "/nonexistent.json"],
                       capture_output=True, check=False)
    if r.returncode == 0:
        problems.append("`own-cli ownir --engine python` succeeded — it accepts a selector")

    # And it must not be a source-level concept: no engine environment
    # variable, no selection branch. Comments explaining what `own-cli` is NOT
    # are exactly where this boundary is documented, so they are excluded.
    crate = ROOT / "rust/crates/own-cli/src"
    for path in sorted(crate.rglob("*.rs")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("//", "//!", "///", "*", "#!")):
                continue
            for needle in ("OWEN_RUST_CORE", "OWEN_PYTHON", "OWN_PYTHON"):
                if needle in stripped:
                    problems.append(f"{path.name} reads {needle!r} in code: {stripped[:80]}")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "own-cli accepts no engine selector and reads no engine environment")


def control_compare_same_input_and_extract_once(sample: Path, tmp: Path) -> None:
    """D4/#260: compare extracts ONCE and hands both engines byte-identical
    input derived from that one capture.

    Extraction count is measured behaviourally, with a `dotnet` shim first on
    PATH that records every invocation: the extractor is driven through
    `dotnet run`, so counting those invocations counts extractions. Same-input
    is measured by the launcher's own refusal to report a comparison whose two
    engine inputs do not hash to the capture.
    """
    once_check, same_check = "compare-extracts-once", "compare-same-input"
    core = rust_core()
    if core is None or not have_dotnet():
        skip(once_check, "no OWEN_RUST_CORE/dotnet")
        skip(same_check, "no OWEN_RUST_CORE/dotnet")
        return

    shim_dir = tmp / "shim"
    shim_dir.mkdir(exist_ok=True)
    tally = tmp / "dotnet-invocations.log"
    if tally.exists():
        tally.unlink()
    real_dotnet = shutil.which("dotnet")
    (shim_dir / "dotnet").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {json.dumps(str(tally))}\n'
        f'exec {json.dumps(str(real_dotnet))} "$@"\n',
        encoding="utf-8")
    (shim_dir / "dotnet").chmod(0o755)

    env = {"OWEN_RUST_CORE": core, "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH','')}"}
    r = run_own_check(["--engine", "compare", "--format", "human", "--", str(sample)], env=env)
    # 0/1 = agreement, 5 = divergence or execution failure. ALL THREE mean the
    # compare ran, and the extraction happened before any of them, so the count
    # below is measurable in every case.
    #
    # On native Windows a divergence here is EXPECTED, not a defect: the Python
    # reference writes CRLF where the Rust core writes LF, so the two engines'
    # bytes differ on every run — #262's declared Windows A/B/C behaviour
    # change, measured. Requiring agreement on that platform would be requiring
    # the parity #262 explicitly does not claim.
    if r.returncode not in (0, 1, 5):
        fail(once_check, f"compare over a healthy sample exited {r.returncode}, so it never "
                         f"reached extraction [{tail(r)}]")
        fail(same_check, "compare never ran, so same-input could not be observed")
        return

    lines = tally.read_text(encoding="utf-8").splitlines() if tally.exists() else []
    extractions = [ln for ln in lines if "OwnSharp.Extractor" in ln]
    if not lines:
        # The shim never intercepted anything, yet the compare itself
        # succeeded — so `dotnet` was resolved past it (git-bash on Windows
        # prefers `dotnet.exe` to an extensionless script). That is the
        # INSTRUMENT failing, not the contract: reporting "0 extractions"
        # would accuse the launcher of a fault the measurement cannot see.
        not_applicable(once_check,
                       "the PATH shim did not intercept `dotnet` on this platform, so extraction "
                       "count could not be measured (the compare itself succeeded)")
    elif len(extractions) != 1:
        fail(once_check,
             f"compare invoked the extractor {len(extractions)} times, expected exactly 1")
    else:
        ok(once_check, "compare extracted exactly once")

    # Same-input, MEASURED at the candidate rather than inferred from the
    # launcher's own bookkeeping: a stub candidate records the sha256 of the
    # file it was actually handed, and that digest must equal the capture
    # digest the launcher attests in its evidence. If compare ever fed the two
    # engines different bytes, these two values part company.
    if os.name == "nt":
        not_applicable(same_check, "needs a recording stub candidate with a shebang; Unix-only. "
                                   "The launcher code that materialises and verifies the two "
                                   "engine inputs is platform-independent and is measured on the "
                                   "Linux leg")
        return
    seen = tmp / "candidate-saw.sha256"
    recorder = tmp / "recording-core"
    recorder.write_text(
        "#!/usr/bin/env bash\n"
        "# args: ownir <facts> --format F --severity S\n"
        f"sha256sum < \"$2\" | cut -d' ' -f1 > {json.dumps(str(seen))}\n"
        "exit 0\n",
        encoding="utf-8")
    recorder.chmod(0o755)

    evidence = Path.home() / ".owen/compare/last-compare.json"
    if evidence.exists():
        evidence.unlink()
    r2 = run_owen(["--engine", "compare", "--format", "human", str(sample)],
                  env={"OWEN_RUST_CORE": str(recorder)})
    if r2 is None:
        skip(same_check, "no built launcher/dotnet")
        return
    if not seen.exists():
        fail(same_check, "the candidate was never handed an input file to record")
        return
    if not evidence.exists():
        fail(same_check, "the compare run wrote no evidence to attest the capture digest")
        return
    try:
        recorded = json.loads(evidence.read_text(encoding="utf-8"))
        attested = (recorded.get("input") or {}).get("sha256")
    except (OSError, json.JSONDecodeError) as exc:
        fail(same_check, f"the compare evidence is unreadable: {exc}")
        return
    candidate_saw = seen.read_text(encoding="utf-8").strip()
    if candidate_saw != attested:
        fail(same_check, f"the candidate was handed bytes hashing to {candidate_saw}, but the "
                         f"launcher attested the capture as {attested} — the engines did not "
                         "receive the same input")
        return
    ok(same_check, f"the candidate received exactly the attested capture ({candidate_saw[:16]}…)")


def control_compare_zero_document(tmp: Path) -> None:
    """A compare that judged nothing agrees about nothing: a zero-document run
    is a failure, not an agreement — a zero denominator wearing a pass."""
    check = "compare-zero-document"
    core = rust_core()
    if core is None or not have_dotnet():
        skip(check, "no OWEN_RUST_CORE/dotnet")
        return
    empty_dir = tmp / "empty-sample"
    empty_dir.mkdir(exist_ok=True)
    (empty_dir / "Nothing.cs").write_text(EMPTY_CS, encoding="utf-8")
    runs = [("own-check.sh",
             run_own_check(["--engine", "compare", "--format", "human", "--", str(empty_dir)],
                           env={"OWEN_RUST_CORE": core}))]
    # D2 again: the guard belongs to both surfaces, and a C#-side mutation is
    # invisible to a shell-only control.
    owen = run_owen(["--engine", "compare", "--format", "human", str(empty_dir)],
                    env={"OWEN_RUST_CORE": core})
    if owen is not None:
        runs.append(("owen", owen))
    else:
        skip(check + "/owen", "no built launcher/dotnet")

    problems = []
    for where, r in runs:
        merged = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode == 4:
            # Exit 4 (no supported input) is a different, legitimate refusal:
            # the sample never reached the engines, so the control cannot speak.
            skip(check, f"{where}: the sample was rejected as unsupported input before the "
                        "engines ran")
            return
        if r.returncode in (0, 1):
            problems.append(f"{where}: a zero-document compare exited {r.returncode} — it "
                            f"passed instead of failing [{tail(r)}]")
        elif r.returncode != 5:
            problems.append(f"{where}: a zero-document compare exited {r.returncode}, expected 5 "
                            f"[{tail(r)}]")
        elif "nothing to analyse" not in merged:
            problems.append(f"{where}: a zero-document compare failed without saying why")
    if problems:
        fail(check, "; ".join(problems))
        return
    ok(check, "a zero-document compare fails (exit 5) and says so, on every surface")


def control_compare_failure_and_divergence(sample: Path, tmp: Path) -> None:
    """D4.1 (b)/(c): a divergence and an execution failure both exit 5 with
    evidence, and neither ever substitutes one engine's answer for the
    other's."""
    div_check = "divergence-is-5"
    exec_check = "exec-failure-is-5"
    sub_check = "compare-no-substitution"
    if os.name == "nt":
        for c in (div_check, exec_check, sub_check):
            not_applicable(c, "needs a synthetic candidate with chosen output; a shebang stub "
                              "is Unix-only, and the launcher cannot spawn a .cmd. The C# and "
                              "bash logic under test is platform-independent and is measured on "
                              "the Linux leg")
        return
    if not have_dotnet():
        for c in (div_check, exec_check, sub_check):
            skip(c, "no dotnet")
        return

    # (b) divergence. The candidate answers LEGALLY and with the SAME exit code
    # the reference produces (1 = findings on this leaky sample), differing only
    # in the bytes. That is deliberate: a stub that also differed in its exit
    # code would let a compare that had stopped comparing stdout still look
    # correct, because the exit-code check alone would flag the divergence.
    diverging = write_stub(tmp / "diverging-core", 1, stdout="a different answer\n")
    div_runs = [("own-check.sh",
                 run_own_check(["--engine", "compare", "--format", "human", "--", str(sample)],
                               env={"OWEN_RUST_CORE": str(diverging)}))]
    owen_div = run_owen(["--engine", "compare", "--format", "human", str(sample)],
                        env={"OWEN_RUST_CORE": str(diverging)})
    if owen_div is not None:
        div_runs.append(("owen", owen_div))
    else:
        skip(div_check + "/owen", "no built launcher/dotnet")

    div_problems, sub_problems = [], []
    for where, r in div_runs:
        merged = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode == 1:
            div_problems.append(f"{where}: a compare divergence exited 1 — in public Owen that "
                                "already means findings")
        elif r.returncode != 5:
            div_problems.append(f"{where}: a compare divergence exited {r.returncode}, "
                                "expected public 5")
        elif "divergence" not in merged:
            div_problems.append(f"{where}: a compare divergence exited 5 without an actionable "
                                "diagnostic")
        elif "sha256" not in merged:
            div_problems.append(f"{where}: a compare divergence produced no reproduction "
                                "evidence (no input digest)")
        # D4.1 (b) is stricter than "do not prefer the candidate": when the
        # engines disagree, NO engine's verdict is exposed as the authoritative
        # result. Owen cannot honestly emit one answer while its reference and
        # its candidate contradict each other, so falling back on "Python is
        # the reference, trust it" is the same failure as trusting the
        # candidate — it just feels safer.
        if b"a different answer" in r.stdout:
            sub_problems.append(f"{where}: the candidate's answer was exposed as the result of "
                                "a diverging compare")
        if b"OWN001" in r.stdout:
            sub_problems.append(f"{where}: the reference's verdict was exposed as the result of "
                                "a diverging compare — D4.1(b) exposes NEITHER engine's")
    if div_problems:
        fail(div_check, "; ".join(div_problems))
    else:
        ok(div_check, "a divergence in the bytes alone is public exit 5 with reproduction "
                      "evidence, on every surface")

    # (c) execution failure: a candidate that produces no verdict at all.
    crashing = write_stub(tmp / "crashing-core", 42, stderr="forced execution failure\n")
    exec_runs = [("own-check.sh",
                  run_own_check(["--engine", "compare", "--format", "human", "--", str(sample)],
                                env={"OWEN_RUST_CORE": str(crashing)}))]
    owen_exec = run_owen(["--engine", "compare", "--format", "human", str(sample)],
                         env={"OWEN_RUST_CORE": str(crashing)})
    if owen_exec is not None:
        exec_runs.append(("owen", owen_exec))
    else:
        skip(exec_check + "/owen", "no built launcher/dotnet")

    exec_problems = []
    for where, r in exec_runs:
        merged = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode != 5:
            exec_problems.append(f"{where}: a compare execution failure exited {r.returncode}, "
                                 "expected public 5")
        elif "execution failure" not in merged:
            exec_problems.append(f"{where}: a compare execution failure exited 5 without an "
                                 "actionable diagnostic")
        elif "42" not in merged:
            exec_problems.append(f"{where}: a compare execution failure did not retain the raw "
                                 "Rust child status")
        if b"OWN001" in r.stdout:
            sub_problems.append(f"{where}: Python's verdict was exposed after the candidate "
                                "failed the compare")
    if exec_problems:
        fail(exec_check, "; ".join(exec_problems))
    else:
        ok(exec_check, "a compare execution failure is public exit 5 with failure evidence, on "
                       "every surface")

    if sub_problems:
        fail(sub_check, "; ".join(sub_problems))
    else:
        ok(sub_check, "no engine's answer was exposed on divergence or on failure")


def control_candidate_identity(sample: Path, tmp: Path) -> None:
    """D3: the candidate's identity is recorded, so a wrong or stale binary
    cannot stand in without the evidence changing."""
    check = "candidate-identity"
    core = rust_core()
    if core is None or not have_dotnet():
        skip(check, "no OWEN_RUST_CORE/dotnet")
        return
    evidence = Path.home() / ".owen/compare/last-compare.json"
    if evidence.exists():
        evidence.unlink()
    r = run_owen(["--engine", "compare", "--format", "human", str(sample)],
                 env={"OWEN_RUST_CORE": core})
    if r is None:
        skip(check, "no built launcher/dotnet")
        return
    if not evidence.exists():
        fail(check, "a compare run wrote no evidence file")
        return
    try:
        data = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(check, f"the compare evidence is unreadable: {exc}")
        return
    recorded = (data.get("rust_core") or {}).get("sha256")
    actual = hashlib.sha256(Path(core).read_bytes()).hexdigest()
    if recorded != actual:
        fail(check, f"the evidence records candidate sha256 {recorded!r}, the binary that ran "
                    f"hashes to {actual}")
        return
    if not (data.get("input") or {}).get("sha256"):
        fail(check, "the compare evidence records no input digest — the same-input claim is "
                    "unattested")
        return
    if (data.get("rust_core") or {}).get("bytes") != Path(core).stat().st_size:
        fail(check, "the evidence's recorded candidate byte length does not match the binary")
        return
    ok(check, "the compare evidence records the candidate's sha256 and byte length")


# --- harness ---------------------------------------------------------------


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="owen-stage1-") as td:
        tmp = Path(td)
        sample_dir = tmp / "sample"
        sample_dir.mkdir()
        (sample_dir / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")

        # No fail-fast: every control runs, so a campaign sees every catcher a
        # mutation trips rather than only the first.
        control_bad_locator_is_2(sample_dir, tmp)
        control_no_selector_in_own_cli()
        control_default_stays_python(sample_dir)
        control_rust_actually_runs_rust(sample_dir)
        control_rust_failure_no_fallback(sample_dir)
        control_rc70_is_not_a_verdict(sample_dir)
        control_unexpected_rc_and_raw_retention(sample_dir, tmp)
        control_compare_same_input_and_extract_once(sample_dir, tmp)
        control_compare_zero_document(tmp)
        control_compare_failure_and_divergence(sample_dir, tmp)
        control_candidate_identity(sample_dir, tmp)

    print()
    print(f"stage-1 engine controls: {len(_PASSES)} passed, "
          f"{len(_FAILURES)} failed, {len(_SKIPS)} skipped, "
          f"{len(_NOT_APPLICABLE)} not applicable on this platform")
    for name, why in _NOT_APPLICABLE:
        print(f"    n/a {name}: {why}")
    if _SKIPS:
        print("  skipped (set OWEN_STAGE1_REQUIRE=1 to make these failures):")
        for name, why in _SKIPS:
            print(f"    {name}: {why}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
