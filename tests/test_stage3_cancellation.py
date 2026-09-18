#!/usr/bin/env python3
"""#262 Stage 3 — cancellation/interruption, MEASURED on this platform.

This is a **reliability** control, not a benchmark. Nothing here times anything
or compares engines for speed, and the workload below is sized only to leave a
window in which an interrupt can arrive while the engine is genuinely running.
The performance gates of #262 are deferred by owner for the Stage-3 decision;
this file makes no performance claim and none may be read out of it.

## Why measured, and why so little is contracted

#262's ruling is explicit: *the Windows and Linux reference behaviour is
measured first; 130 is not invented as a universal contract.* The two platforms
do not even offer the same mechanism — POSIX has `SIGINT`, Windows has console
control events — and a process that dies **by a signal** does not have an exit
code at all in the sense a process that `exit()`s does. Writing `130` into a
contract would be inventing a number for one platform and asserting it about
the other.

So this control separates two things that are easy to conflate:

    INVARIANT  — asserted on every platform, because the evidence supports it
    DISPOSITION — measured and RECORDED per platform, never asserted

The invariants are the ones a cutover actually depends on:

1. **it terminates.** An interrupted engine must not hang. A launcher cannot
   rescue a child that never dies.
2. **it is never a verdict.** Not exit 0 and not exit 1. This is the one that
   matters: `owen check` maps 0 to "clean" and 1 to "findings", so an interrupt
   that produced either would turn a cancelled run into an ANSWER — silently
   clean code, or silently a finding — and neither was ever computed.
3. **it publishes no verdict surface.** No `ok` line, no findings summary. A
   partially written verdict is still a verdict to whatever reads it.

The disposition — died by signal N, or exited with code C — is whatever this
platform does, printed and returned so the recording job carries it. That is
the part the decision packet quotes, per platform, from a run that happened.

## The window, and why a missed one is a failure

An interrupt delivered after the process already exited measures nothing, and
would "pass" every assertion above for the wrong reason. So the control proves
it interrupted a LIVE process, and escalates the workload when it did not. If
no attempt lands on a live process the control FAILS rather than reporting a
green it did not earn — a zero-window measurement is not evidence.

Run:  python tests/test_stage3_cancellation.py
      python tests/run_tests.py            (in the suite)

Environment:
    OWEN_RUST_CORE          the production candidate; without it the Rust leg
                            reports NOT APPLICABLE rather than passing
    OWEN_STAGE3_REQUIRE=1   turn every skip into a failure (CI sets this: in a
                            job that exists to provide the toolchain, a skip is
                            indistinguishable from a pass)
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

IS_WINDOWS = os.name == "nt"

# The verdict exit codes. An interrupted run reaching either of these is the
# defect this whole file exists to catch.
VERDICT_EXITS = (0, 1)

# How long the child must already have been running when the interrupt is sent.
# Not a performance number: it is the smallest dwell that makes "the process was
# alive" an observation rather than a race.
DWELL_SECONDS = 0.5

# How long the child is then given to die. Generous on purpose — the assertion
# is "it terminates", and a slow death is not a hang.
DEATH_TIMEOUT_SECONDS = 30.0

# Workload sizes, in components, tried in order until one leaves a window.
# Escalating rather than fixing one size is what keeps this control working on a
# faster machine than the one it was written on.
WORKLOAD_LADDER = (200_000, 600_000, 1_500_000)


def _fail(msg: str, *, check: str) -> int:
    print(f"FAIL[{check}]: {msg}")
    return 1


def _write_workload(path: str, components: int) -> None:
    """A large but entirely ORDINARY document. Nothing hostile: the point is a
    run long enough to interrupt, not a parser stress case."""
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"ownir_version": 0, "components": [')
        for i in range(components):
            if i:
                f.write(",")
            f.write(json.dumps({
                "name": f"C{i}", "file": f"f{i}.cs", "line": 1, "kind": "class",
                "subscriptions": [{"resource": "e", "event": "E",
                                   "file": f"f{i}.cs", "line": 2, "column": 3}],
            }))
        f.write("]}")


def _spawn(argv: list[str], cwd: str | None) -> subprocess.Popen[bytes]:
    """Spawn in its own group so the interrupt reaches the child and NOT this
    test process — on either platform.

    The two spellings are not interchangeable and neither is optional: without
    a new group the interrupt would land on this test as well, and a control
    that kills its own runner reports nothing.
    """
    env = dict(os.environ, PYTHONPATH=_ROOT)
    if IS_WINDOWS:
        return subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)


def _interrupt(proc: subprocess.Popen[bytes]) -> str:
    """Send this platform's interrupt, and NAME it.

    The two are not the same event and the record must not pretend they are.
    On Windows a parent cannot deliver Ctrl-C to a specific child group — the
    event a new process group can be sent is CTRL_BREAK — so that is what is
    sent, and that is what the disposition below is a measurement of.
    """
    if IS_WINDOWS:
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        return "CTRL_BREAK_EVENT"
    os.killpg(os.getpgid(proc.pid), signal.SIGINT)
    return "SIGINT"


def _describe(returncode: int) -> tuple[str, str, int]:
    """(how, human, raw) for a finished child. A negative returncode is Python's
    spelling of "died by signal N" and is NOT an exit code."""
    if returncode < 0:
        name = signal.Signals(-returncode).name
        return "signal", f"died by signal {-returncode} ({name})", -returncode
    return "exit", f"exited with code {returncode}", returncode


def _measure(label: str, argv: list[str], cwd: str | None,
             workload: str) -> tuple[int, dict[str, object] | None]:
    """One engine, interrupted while running. Returns (failures, record)."""
    failures = 0
    for components in WORKLOAD_LADDER:
        _write_workload(workload, components)
        proc = _spawn([*argv, workload], cwd)
        time.sleep(DWELL_SECONDS)
        if proc.poll() is not None:
            # No window: the run finished before the interrupt. Drain it and
            # escalate rather than measuring a corpse.
            proc.communicate()
            continue
        mechanism = _interrupt(proc)
        try:
            out, err = proc.communicate(timeout=DEATH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return _fail(
                f"{label}: still running {DEATH_TIMEOUT_SECONDS:.0f}s after "
                f"{mechanism} — an interrupted engine must terminate",
                check="cancellation-terminates"), None

        how, human, raw = _describe(proc.returncode)
        stdout = out.decode("utf-8", "replace")

        # INVARIANT 2 — never a verdict.
        if how == "exit" and raw in VERDICT_EXITS:
            failures += _fail(
                f"{label}: {human} after {mechanism} — {raw} is a VERDICT code "
                f"({'clean' if raw == 0 else 'findings'}), so a cancelled run "
                f"would be published as an answer nobody computed",
                check="cancellation-is-not-a-verdict")
        # INVARIANT 3 — no verdict surface.
        for marker, what in ((": ok — ", "an ok line"), (" finding", "a findings summary")):
            if marker in stdout:
                failures += _fail(
                    f"{label}: stdout carries {what} after {mechanism}: "
                    f"{stdout[:200]!r}", check="cancellation-publishes-nothing")

        record = {
            "engine": label,
            "mechanism": mechanism,
            "how": how,
            "raw": raw,
            "human": human,
            "workload_components": components,
            "stdout_bytes": len(out),
            "stderr_bytes": len(err),
        }
        print(f"  measured[{label}]: {mechanism} -> {human}; "
              f"stdout {len(out)}b, stderr {len(err)}b "
              f"(workload {components} components)")
        return failures, record

    return _fail(
        f"{label}: no workload in {WORKLOAD_LADDER} left a window — every "
        f"attempt finished within {DWELL_SECONDS}s, so nothing was interrupted "
        f"and nothing was measured",
        check="cancellation-window"), None


def run() -> int:
    require = os.environ.get("OWEN_STAGE3_REQUIRE") == "1"
    failures = 0
    records: list[dict[str, object]] = []

    print(f"cancellation, measured on {platform.system()} "
          f"({platform.machine()}), python {platform.python_version()}")

    tmp = tempfile.mkdtemp(prefix="owen-stage3-cancel-")
    workload = os.path.join(tmp, "cancel.facts.json")
    try:
        # The REFERENCE. Always available: it is this repository.
        f, record = _measure("python reference",
                             [sys.executable, "-m", "ownlang", "ownir"],
                             _ROOT, workload)
        failures += f
        if record:
            records.append(record)

        # The CANDIDATE — the binary the cutover makes default.
        core = os.environ.get("OWEN_RUST_CORE")
        if not core or not os.path.isfile(core):
            msg = ("skip[cancellation-rust]: no OWEN_RUST_CORE — the candidate "
                   "leg measured nothing")
            print(msg)
            if require:
                failures += _fail(
                    "OWEN_STAGE3_REQUIRE=1 but OWEN_RUST_CORE is unset or not a "
                    "file: in a job that exists to provide the candidate, a skip "
                    "is indistinguishable from a pass",
                    check="cancellation-rust")
        else:
            f, record = _measure("rust own-cli", [core, "ownir"], None, workload)
            failures += f
            if record:
                records.append(record)
    finally:
        try:
            os.unlink(workload)
        except OSError:
            pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass

    # The DISPOSITION, emitted as a machine-readable line so the recording job
    # carries the measurement rather than a reader transcribing it from prose.
    print("STAGE3-CANCELLATION-RECORD " + json.dumps(
        {"platform": platform.system(), "engines": records}, sort_keys=True))

    if failures:
        return 1
    print(
        f"stage-3 cancellation OK: {len(records)} engine(s) interrupted while "
        f"genuinely running on {platform.system()}; each terminated, none "
        f"returned a verdict code (0/1), none published an ok line or a "
        f"findings summary. The per-platform disposition above is RECORDED, "
        f"not contracted — #262 forbids inventing a universal 130")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
