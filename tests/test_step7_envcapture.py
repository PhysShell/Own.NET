#!/usr/bin/env python3
"""#263-A step 7 — controls on the measurement-free environment identity manifest.

The capture tool exists so the execution binding can name two real machines. It
must therefore be provably free of clocks, and its "unknown" must never be able
to arrive dressed as a value.

    envcapture-schema            the declared key set, enforced both ways
    envcapture-field-contract    observed/unavailable, with no third state
    envcapture-identity-split    provenance can never become identity
    envcapture-assigned-id       an owner-assigned id cannot be 'unavailable'
    envcapture-drift             provenance moves freely; identity never does
    envcapture-no-measurement    no clock, no resource observation, by AST
    envcapture-reason-fits-platform  an 'unavailable' reason names THIS platform
    envcapture-windows-fixture   the schema holds off Linux; the capture path does not
    envcapture-frozen-untouched  this addition moved none of the three frozen digests
    envcapture-ci-provenance     a CI-taken manifest says so and cannot hide it

`envcapture-no-measurement` walks the AST rather than the text, because this
module's own docstring names `perf_counter` and `wait4` to say it does not use
them. A text scan would read the prose and call that a finding, which is the
same defect as a check reading a proxy for the thing it checks.

`envcapture-frozen-untouched` is the one that protects everything already
accepted: adding a file under `scripts/calibration/` or `scripts/training/`
would move a digest that steps 4, 5 and 6 are bound to.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_step7_envcapture.py
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "step7"))
sys.path.insert(0, str(ROOT / "tests"))

import envcapture as ec  # noqa: E402
import perf_baseline as pb  # noqa: E402
from test_calibration_freeze import implementation_digest  # noqa: E402

SOURCE = ROOT / "scripts" / "step7" / "envcapture.py"
FREEZE = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-policy-freeze.json"
PREREG = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-training-preregistration.json"

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def _live() -> dict[str, object]:
    return ec.capture("control-fixture-not-a-measurement-environment")


# --- the declared shape -----------------------------------------------------


def control_schema() -> None:
    manifest = _live()
    problems = ec.validate(manifest)
    if problems:
        fail("envcapture-schema", f"the live capture does not validate: {'; '.join(problems)}")
        return

    # Driven both ways: an extra key and a missing key must each be refused.
    extra = copy.deepcopy(manifest)
    extra["identity"]["cpu_temperature"] = ec.observed("41C")  # type: ignore[index]
    if not ec.validate(extra):
        fail("envcapture-schema", "an undeclared identity field was accepted")
        return
    missing = copy.deepcopy(manifest)
    del missing["identity"]["kernel"]  # type: ignore[union-attr]
    if not ec.validate(missing):
        fail("envcapture-schema", "a missing identity field was accepted as if absent meant fine")
        return
    wrong_schema = copy.deepcopy(manifest)
    wrong_schema["schema"] = "something-else"
    if not ec.validate(wrong_schema):
        fail("envcapture-schema", "a foreign schema name was accepted")
        return
    ok("envcapture-schema",
       f"{len(ec.IDENTITY_FIELDS)} identity and {len(ec.PROVENANCE_FIELDS)} provenance fields, "
       "with an extra key, a missing key and a foreign schema each refused")


def control_field_contract() -> None:
    """Zero, empty and boolean are the three ways 'unknown' sneaks in as a value."""
    cases: tuple[tuple[str, object], ...] = (
        ("empty string", {"status": "observed", "value": ""}),
        ("whitespace", {"status": "observed", "value": "   "}),
        ("zero count", {"status": "observed", "value": 0}),
        ("negative count", {"status": "observed", "value": -1}),
        ("bare true", {"status": "observed", "value": True}),
        ("bare false", {"status": "observed", "value": False}),
        ("null value", {"status": "observed", "value": None}),
        ("observed with no value", {"status": "observed"}),
        ("observed carrying a reason", {"status": "observed", "value": "x", "reason": "y"}),
        ("unavailable with no reason", {"status": "unavailable"}),
        ("unavailable with empty reason", {"status": "unavailable", "reason": ""}),
        ("unavailable carrying a value", {"status": "unavailable", "reason": "r", "value": "v"}),
        ("unknown status", {"status": "probably", "value": "x"}),
        ("no status at all", {"value": "x"}),
        ("not an object", "just a string"),
    )
    missed = [name for name, field in cases if not ec.field_problems("identity.cpu_model", field)]
    if missed:
        fail("envcapture-field-contract",
             f"accepted as a valid field: {', '.join(missed)}")
        return
    good = ec.field_problems("identity.cpu_model", ec.observed("Xeon"))
    good += ec.field_problems("identity.power_policy", ec.unavailable("no cpufreq on this host"))
    if good:
        fail("envcapture-field-contract", f"refused a well-formed field: {'; '.join(good)}")
        return
    ok("envcapture-field-contract",
       f"{len(cases)} malformed fields refused, including bare true and false, since a bool "
       "IS an int in Python and an unguarded numeric test would have taken them")


def control_identity_split() -> None:
    overlap = set(ec.IDENTITY_FIELDS) & set(ec.PROVENANCE_FIELDS)
    if overlap:
        fail("envcapture-identity-split", f"declared in both classes: {sorted(overlap)}")
        return
    for name in ("runner_name", "workflow_run_id", "job_id", "timestamp_utc", "ci"):
        if name in ec.IDENTITY_FIELDS:
            fail("envcapture-identity-split",
                 f"{name} is identity-bearing, which the owner's ruling forbids")
            return
    smuggled = copy.deepcopy(_live())
    smuggled["identity"]["runner_name"] = ec.observed("GitHub Actions 7")  # type: ignore[index]
    if not ec.validate(smuggled):
        fail("envcapture-identity-split", "runner_name was accepted as an identity field")
        return
    ok("envcapture-identity-split",
       "runner name, workflow and job ids, timestamp and the CI flag are provenance only; "
       "promoting runner_name into identity is refused")


def control_assigned_id() -> None:
    unavailable_id = {"status": "unavailable", "reason": "nobody told us"}
    if not ec.field_problems("environment_id", unavailable_id):
        fail("envcapture-assigned-id",
             "environment_id was allowed to be unavailable, so a binding could name no environment")
        return
    refused = []
    for bad in ("", "   "):
        try:
            ec.capture(bad)
        except ec.CaptureRefused:
            refused.append(bad)
        except Exception as exc:  # a crash is not a refusal
            fail("envcapture-assigned-id",
                 f"capture({bad!r}) raised {type(exc).__name__} instead of refusing by name")
            return
    if len(refused) != 2:
        fail("envcapture-assigned-id", "capture() accepted an empty environment_id")
        return
    ok("envcapture-assigned-id",
       "an owner-assigned id cannot be 'unavailable' and an empty one is refused by name, "
       "not by crash")


def control_drift() -> None:
    first = _live()
    # A new allocation: every provenance field differs, nothing about the machine did.
    reallocated = copy.deepcopy(first)
    reallocated["provenance"] = {  # type: ignore[index]
        "timestamp_utc": "2030-01-01T00:00:00+00:00",
        "runner_name": "a completely different runner",
        "workflow_run_id": "999999",
        "job_id": "another-job",
        "ci": True,
    }
    drift = ec.identity_drift(first, reallocated)
    if drift:
        fail("envcapture-drift",
             f"a new runner allocation was read as environment drift: {drift}")
        return

    moved = copy.deepcopy(first)
    moved["identity"]["cpu_model"] = ec.observed("a different CPU")  # type: ignore[index]
    if ec.identity_drift(first, moved) != ("cpu_model",):
        fail("envcapture-drift", "a changed cpu_model was not reported as drift")
        return

    went_dark = copy.deepcopy(first)
    went_dark["identity"]["rustc"] = ec.unavailable("toolchain removed")  # type: ignore[index]
    if "rustc" not in ec.identity_drift(first, went_dark):
        fail("envcapture-drift",
             "a field that went from observed to unavailable was not drift, so an "
             "environment could go dark between runs unnoticed")
        return

    reworded = copy.deepcopy(first)
    reworded["identity"]["power_policy"] = ec.unavailable("a different reason")  # type: ignore[index]
    if "power_policy" not in ec.identity_drift(first, reworded):
        fail("envcapture-drift", "a changed unavailable reason was not reported as drift")
        return

    try:
        ec.identity_drift({}, first)
    except ec.CaptureRefused:
        pass
    except Exception as exc:  # a crash is not a refusal
        fail("envcapture-drift",
             f"comparing a manifest with no identity raised {type(exc).__name__}, not a refusal")
        return
    else:
        fail("envcapture-drift", "a manifest with no identity object compared as if it had one")
        return
    ok("envcapture-drift",
       "a whole new runner allocation is not drift; a changed CPU, a field going dark and a "
       "reworded reason all are; an identity-less manifest is refused by name")


# --- no clock, proved by reading the code rather than the prose -------------


FORBIDDEN_ATTRS = frozenset({
    "perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns",
    "process_time", "process_time_ns", "thread_time", "thread_time_ns",
    "clock_gettime", "clock_gettime_ns", "wait4", "wait3", "getrusage", "times",
})
FORBIDDEN_MODULES = frozenset({"time", "timeit", "resource"})


def measurement_capabilities(tree: ast.AST) -> tuple[str, ...]:
    """Written once, used twice: on the real module and on a mutated copy.

    Walks the AST, so the docstring naming these APIs in order to disclaim them
    is not mistaken for using them.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names
                      if a.name.split(".")[0] in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_MODULES:
                found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            found.append(f"call to .{node.attr}()")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_ATTRS:
            found.append(f"reference to {node.id}")
    return tuple(sorted(set(found)))


def control_no_measurement() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    live = measurement_capabilities(ast.parse(text))
    if live:
        fail("envcapture-no-measurement",
             f"the capture tool can reach a clock or resource accounting: {', '.join(live)}")
        return

    # The mutation is the proof. Without it this control is a claim.
    mutated = text + ("\n\ndef _smuggled() -> float:\n"
                      "    import time\n"
                      "    return time.perf_counter()\n")
    if not measurement_capabilities(ast.parse(mutated)):
        fail("envcapture-no-measurement",
             "the scanner did not catch a smuggled time.perf_counter(), so its silence on the "
             "real module proves nothing")
        return

    manifest = _live()
    leaked = [k for k in manifest["identity"]  # type: ignore[union-attr]
              if any(w in k for w in ("elapsed", "duration", "nanos", "seconds", "rss", "usage"))]
    if leaked:
        fail("envcapture-no-measurement",
             f"the manifest carries observation-shaped fields: {leaked}")
        return
    ok("envcapture-no-measurement",
       f"no clock and no resource accounting reachable in {SOURCE.name}, proved by AST rather "
       "than by text so its own disclaimer is not a finding; a smuggled perf_counter is caught; "
       "and memory_bytes is installed RAM, not consumption")


# --- off Linux, and the frozen digests -------------------------------------


WINDOWS_FIXTURE: dict[str, object] = {
    "schema": ec.SCHEMA,
    "measurement_free": True,
    "identity": {
        "environment_id": {"status": "observed", "value": "p022-win-01"},
        "host_fingerprint": {"status": "observed", "value": "sha256:" + "b" * 64},
        "os_build": {"status": "observed",
                     "value": "Windows 10 10.0.20348 SP0 Multiprocessor Free"},
        "kernel": {"status": "observed", "value": "10 10.0.20348"},
        "cpu_model": {"status": "observed", "value": "AMD EPYC 7763 64-Core Processor"},
        "logical_cpu_count": {"status": "observed", "value": 8},
        "memory_bytes": {"status": "observed", "value": 34359738368},
        "virtualization": {"status": "observed", "value": "microsoft"},
        "power_policy": {"status": "observed", "value": "High performance"},
        "python": {"status": "observed", "value": "CPython 3.11.9 (tags/v3.11.9) [MSC v.1938]"},
        "rustc": {"status": "observed", "value": "rustc 1.94.1; host: x86_64-pc-windows-msvc"},
        "dotnet": {"status": "observed", "value": "8.0.404"},
    },
    "provenance": {
        "timestamp_utc": "2026-09-13T00:00:00+00:00",
        "runner_name": None,
        "workflow_run_id": None,
        "job_id": None,
        "ci": False,
    },
    "note": "fixture",
}


# Mechanism names that exist on one platform only. A reason naming the other
# platform's mechanisms is a false statement about what was tried.
POSIX_ONLY = ("/sys/", "/proc/", "systemd-detect-virt", "scaling_governor", "cpufreq")
WINDOWS_ONLY = ("powercfg", "Win32_", "MachineGuid", "GlobalMemoryStatusEx",
                "powershell", "pwsh")


def foreign_mechanisms(reason: str, *, on_windows: bool) -> tuple[str, ...]:
    """Written once, used twice: on the live manifest and on a synthetic reason."""
    foreign = POSIX_ONLY if on_windows else WINDOWS_ONLY
    return tuple(token for token in foreign if token in reason)


def control_reason_fits_platform() -> None:
    """An 'unavailable' reason must describe THIS platform's mechanisms.

    The first Windows CI run of this tool reported `virtualization` unavailable
    because "systemd-detect-virt absent ... and no DMI identity under /sys" —
    true of every Windows machine ever built, and silent about the fact that
    nothing Windows-specific had been tried at all. A stated reason that names
    the wrong operating system is worse than no reason, because it reads as
    though a probe ran.
    """
    on_windows = os.name == "nt"
    manifest = _live()
    problems: list[str] = []
    for name, field in manifest["identity"].items():  # type: ignore[union-attr]
        if field.get("status") != ec.UNAVAILABLE:
            continue
        found = foreign_mechanisms(str(field.get("reason", "")), on_windows=on_windows)
        if found:
            problems.append(f"{name} blames {', '.join(found)}")
    if problems:
        fail("envcapture-reason-fits-platform",
             f"on {'Windows' if on_windows else 'POSIX'}, "
             + "; ".join(problems))
        return

    # The scanner must actually catch the defect that prompted it, or its silence
    # on the live manifest proves nothing.
    regression = "systemd-detect-virt absent or unclear and no DMI identity under /sys"
    if not foreign_mechanisms(regression, on_windows=True):
        fail("envcapture-reason-fits-platform",
             "the scanner does not catch the exact Windows reason that prompted it")
        return
    if foreign_mechanisms(regression, on_windows=False):
        fail("envcapture-reason-fits-platform",
             "the scanner calls a POSIX reason foreign on POSIX")
        return
    ok("envcapture-reason-fits-platform",
       f"every unavailable reason on {'Windows' if on_windows else 'POSIX'} names a mechanism "
       "that exists here, and the Windows virtualization reason that shipped in the first "
       "version is still caught")


def control_windows_fixture() -> None:
    problems = ec.validate(WINDOWS_FIXTURE)
    if problems:
        fail("envcapture-windows-fixture",
             f"a well-formed Windows manifest was refused: {problems}")
        return
    other = copy.deepcopy(WINDOWS_FIXTURE)
    other["identity"]["power_policy"] = ec.observed("Balanced")  # type: ignore[index]
    if ec.identity_drift(WINDOWS_FIXTURE, other) != ("power_policy",):
        fail("envcapture-windows-fixture", "a changed Windows power policy was not drift")
        return
    ok("envcapture-windows-fixture",
       "the schema and the drift rule hold on a non-Linux manifest. This fixture does not run "
       "the Windows capture path; the CI selftest on windows-latest does, and its first run "
       "returned the registry fingerprint, powercfg and GlobalMemoryStatusEx but no "
       "virtualization, which is what added the CIM query. What stays unverified is capture on "
       "a DEDICATED Windows host, since a hosted runner is not one")


def _git(*args: str) -> tuple[int, bytes]:
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    return proc.returncode, proc.stdout


def _root_digest(root: str) -> str | None:
    rc, out = _git("ls-tree", "-r", "--long", "-z", "HEAD", "--", root)
    if rc != 0:
        return None
    entries = []
    for record in out.decode("utf-8").split("\0"):
        if not record.strip():
            continue
        meta, path = record.split("\t", 1)
        _mode, _kind, sha, _size = meta.split()
        if path.endswith(".py"):
            entries.append((path, _git("cat-file", "blob", sha)[1]))
    return implementation_digest(entries) if entries else None


def control_frozen_untouched() -> None:
    """Adding this tool must not move a digest steps 4, 5 and 6 are bound to."""
    problems: list[str] = []
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    bindings = prereg["bindings"]

    live_harness = pb.harness_digest()
    if live_harness != freeze["measurement_harness_digest"]:
        problems.append(f"the live harness now hashes to {live_harness[:12]}, not the frozen one")

    policy = _root_digest(freeze["policy_source_root"])
    if policy != freeze["policy_implementation_digest"]:
        problems.append(f"scripts/calibration/ now hashes to {policy and policy[:12]}")
    scope = _root_digest(bindings["training_scope_root"])
    if scope != bindings["training_scope_implementation_digest"]:
        problems.append(f"scripts/training/ now hashes to {scope and scope[:12]}")

    if str(SOURCE.relative_to(ROOT)).replace(os.sep, "/").startswith(
            (freeze["policy_source_root"], bindings["training_scope_root"])):
        problems.append("the capture tool was placed inside a frozen root")

    if problems:
        fail("envcapture-frozen-untouched", "; ".join(problems))
    else:
        ok("envcapture-frozen-untouched",
           "the capture tool lives outside all three frozen source sets, so the harness digest "
           "and the step-4 and step-6 digests are exactly what steps 4, 5 and 6 were accepted on")


def control_ci_provenance() -> None:
    """A manifest taken on a hosted runner must say so rather than look host-taken."""
    saved = {k: os.environ.get(k) for k in ("CI", "RUNNER_NAME", "GITHUB_RUN_ID", "GITHUB_JOB")}
    try:
        os.environ.update({"CI": "true", "RUNNER_NAME": "GitHub Actions 3",
                           "GITHUB_RUN_ID": "34701945292", "GITHUB_JOB": "perf-instrument"})
        manifest = ec.capture("would-be-environment")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    prov = manifest["provenance"]
    missing = [k for k, want in (("ci", True), ("runner_name", "GitHub Actions 3"),
                                 ("workflow_run_id", "34701945292"),
                                 ("job_id", "perf-instrument"))
               if prov.get(k) != want]  # type: ignore[union-attr]
    if missing:
        fail("envcapture-ci-provenance",
             f"a manifest captured on a hosted runner did not record {missing}")
        return
    ok("envcapture-ci-provenance",
       "a manifest taken on a hosted runner records the runner, run and job and sets ci true, "
       "so it cannot later be presented as taken on a dedicated measurement host")


def guard_failure(control: Callable[[], None]) -> str | None:
    """Run a control; return the message a failure should carry, or None.

    Split from `guarded` so the probe below can exercise it WITHOUT printing a
    `FAIL[` line. The first version reported through `fail()` and then deleted
    the entry from the list — which left a literal `FAIL[envcapture-guard-fixture]`
    in every green CI log, exactly the string this repository's mutation scorer
    keys on. A green run must not print a failure.
    """
    try:
        control()
    except Exception as exc:  # the point is that nothing escapes
        return (f"the control raised {type(exc).__name__}: {exc}. A control that crashes "
                "before reporting is a traceback, not a finding")
    return None


def guarded(name: str, control: Callable[[], None]) -> None:
    """Report an escaping exception instead of dying of it.

    Recorded eight times in this PR now: a control that crashes before reporting
    is a traceback, not a finding, and the run that dies on control one never
    reaches control three. The mutation that exposed this instance promoted
    `runner_name` into IDENTITY_FIELDS, which killed the fixture builder before
    `envcapture-identity-split` — the control that owns exactly that defect —
    could say a word.
    """
    message = guard_failure(control)
    if message is not None:
        fail(name, message)


def control_guard_reports() -> None:
    """The guard is the durable answer to a defect recorded eight times. Prove it.

    A scratchpad campaign that once watched a crash get reported is not a
    regression catcher; restoring the bare call in `run()` has to fail here.
    """
    def always_raises() -> None:
        raise RuntimeError("a control that dies before reporting")

    try:
        message = guard_failure(always_raises)
    except Exception as exc:  # nothing may escape, including from the guard
        fail("envcapture-guard-reports",
             f"guard_failure() let {type(exc).__name__} escape, so one crashing control still "
             "kills every control after it")
        return
    if message is None:
        fail("envcapture-guard-reports", "a raising control was reported as clean")
        return
    if "RuntimeError" not in message:
        fail("envcapture-guard-reports",
             f"the report does not name the exception type: {message!r}")
        return
    if guard_failure(lambda: None) is not None:
        fail("envcapture-guard-reports", "a clean control was reported as a failure")
        return
    ok("envcapture-guard-reports",
       "a control that raises is reported by name and the run continues, a clean one is not, "
       "and this probe prints no FAIL line of its own on a green run")


def run() -> int:
    guarded("envcapture-guard-reports", control_guard_reports)
    guarded("envcapture-schema", control_schema)
    guarded("envcapture-field-contract", control_field_contract)
    guarded("envcapture-identity-split", control_identity_split)
    guarded("envcapture-assigned-id", control_assigned_id)
    guarded("envcapture-drift", control_drift)
    guarded("envcapture-no-measurement", control_no_measurement)
    guarded("envcapture-reason-fits-platform", control_reason_fits_platform)
    guarded("envcapture-windows-fixture", control_windows_fixture)
    guarded("envcapture-frozen-untouched", control_frozen_untouched)
    guarded("envcapture-ci-provenance", control_ci_provenance)
    print()
    print(f"step 7 environment capture controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
