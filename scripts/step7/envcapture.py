#!/usr/bin/env python3
"""#263-A step 7 — the measurement-free environment identity manifest.

Step 7 may not start a clock until two dedicated measurement environments exist
and the execution binding is frozen against them. This module produces the input
to that binding: one manifest per host, recording WHAT the machine is, and
nothing about how fast it is.

It therefore contains **no clock and no resource observation**. There is no
`perf_counter`, no `monotonic`, no `wait4`, no `getrusage`, no timing of the
subprocesses it uses to read tool versions. `memory_bytes` is how much RAM the
machine HAS, never how much anything used.

It is deliberately **self-contained**: it does not import `perf_baseline`. If it
did, "this file starts no clock" would stop being provable by reading this file,
and the audit would have to follow an import into the instrument that exists to
start clocks. Independence is the point, not duplication for its own sake.

Two field classes, and the split is the owner's ruling rather than a convenience:

  IDENTITY    what makes two runs the same measurement environment. Any change
              after the first measurement invalidates that stratum.
  PROVENANCE  runner name, workflow and job ids, timestamp, CI flag. Recorded
              faithfully, never identity. A new runner allocation is not a new
              machine, and `RUNNER_NAME` changing is not environment drift.

Every identity field is one of exactly two shapes, so "unknown" can never arrive
disguised as a value:

    {"status": "observed",    "value": <non-empty, non-bool>}
    {"status": "unavailable", "reason": <non-empty string>}

An empty string, a zero, a bare boolean, a missing key and a silent absence are
all refused. That distinction is the whole reason this file has a schema at all.

A caveat recorded rather than papered over: `host_fingerprint` hashes the
running system's machine id. Inside a container that is the CONTAINER's identity,
not the host's, which is one more reason the collection runs on a dedicated
machine rather than in CI. The manifest records `ci` and `runner_name` in
provenance so a manifest taken on a hosted runner cannot later pass itself off
as one taken on a measurement host.

Usage:
    python scripts/step7/envcapture.py --environment-id <id> --emit <path.json>
    python scripts/step7/envcapture.py --selftest
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

SCHEMA = "p022-263a-step7-environment-identity"

# Identity-bearing. Ordered; the manifest is written in this order and the order
# is part of the schema so a reordered file is a changed file.
IDENTITY_FIELDS: tuple[str, ...] = (
    "environment_id",
    "host_fingerprint",
    "os_build",
    "kernel",
    "cpu_model",
    "logical_cpu_count",
    "memory_bytes",
    "virtualization",
    "power_policy",
    "python",
    "rustc",
    "dotnet",
)

# Provenance only. Present in every manifest, never compared for drift.
PROVENANCE_FIELDS: tuple[str, ...] = (
    "timestamp_utc",
    "runner_name",
    "workflow_run_id",
    "job_id",
    "ci",
)

OBSERVED = "observed"
UNAVAILABLE = "unavailable"

# environment_id is assigned by the owner, not discovered. Its absence is an
# operator error, never an unobservable property of the machine, so it is the
# one field for which `unavailable` is itself a refusal.
ASSIGNED_FIELDS: frozenset[str] = frozenset({"environment_id"})


class CaptureRefused(Exception):
    """Raised by name. A caller that reads through gets an exception, not a manifest."""


def observed(value: object) -> dict[str, object]:
    return {"status": OBSERVED, "value": value}


def unavailable(reason: str) -> dict[str, object]:
    return {"status": UNAVAILABLE, "reason": reason}


# --- reading the machine, never timing it ----------------------------------


def _text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _tool(argv: list[str]) -> tuple[int, str] | None:
    """Run a version query. NOT timed, and no shell.

    Returns (returncode, stdout+stderr) or None when the tool is absent. The
    return code is handed back because `systemd-detect-virt` reports "none" with
    a non-zero exit, and reading that as a failure would turn a real answer into
    an unavailable.
    """
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return None
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _host_fingerprint() -> dict[str, object]:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        raw = _text(path)
        if raw and raw.strip():
            digest = hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()
            return observed(f"sha256:{digest}")
    if os.name == "nt":
        found = _windows_machine_guid()
        if found:
            digest = hashlib.sha256(found.encode("utf-8")).hexdigest()
            return observed(f"sha256:{digest}")
        return unavailable("HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid unreadable")
    return unavailable("no /etc/machine-id, no /var/lib/dbus/machine-id, not Windows")


def _windows_machine_guid() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg  # Windows-only; imported where it exists
    except ImportError:
        return None
    try:
        # winreg exists only on Windows, so the Linux stubs carry none of these
        # names. Ignored per-attribute with the reason, not by silencing the file.
        key = winreg.OpenKey(  # type: ignore[attr-defined]  # Windows-only stub
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]  # Windows-only stub
            r"SOFTWARE\Microsoft\Cryptography")
        with key:
            value, _kind = winreg.QueryValueEx(  # type: ignore[attr-defined]  # Windows-only
                key, "MachineGuid")
    except OSError:
        return None
    return str(value) if value else None


def _os_build() -> dict[str, object]:
    if os.name == "nt":
        release, version, csd, ptype = platform.win32_ver()
        parts = [p for p in (release, version, csd, ptype) if p]
        if parts:
            return observed("Windows " + " ".join(parts))
        return unavailable("platform.win32_ver() returned nothing")
    raw = _text("/etc/os-release")
    if raw:
        fields: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                fields[key.strip()] = val.strip().strip('"')
        name = fields.get("PRETTY_NAME") or fields.get("NAME")
        build = fields.get("VERSION_ID") or fields.get("BUILD_ID")
        if name:
            return observed(f"{name} (VERSION_ID={build})" if build else name)
    system = platform.system()
    if system:
        return observed(system)
    return unavailable("no /etc/os-release and platform.system() is empty")


def _kernel() -> dict[str, object]:
    release, version = platform.release(), platform.version()
    if release or version:
        return observed(f"{release} {version}".strip())
    return unavailable("platform.release() and platform.version() are both empty")


def _cpu_model() -> dict[str, object]:
    raw = _text("/proc/cpuinfo")
    if raw:
        for line in raw.splitlines():
            if line.lower().startswith("model name"):
                _, _, value = line.partition(":")
                if value.strip():
                    return observed(value.strip())
    if os.name == "nt":
        found = _tool(["wmic", "cpu", "get", "name"])
        if found and found[0] == 0:
            lines = [ln.strip() for ln in found[1].splitlines() if ln.strip()]
            if len(lines) > 1:
                return observed(lines[1])
    processor = platform.processor()
    if processor:
        return observed(processor)
    return unavailable("no model name in /proc/cpuinfo and platform.processor() is empty")


def _logical_cpu_count() -> dict[str, object]:
    count = os.cpu_count()
    if isinstance(count, int) and count > 0:
        return observed(count)
    return unavailable("os.cpu_count() returned no usable count")


def _memory_bytes() -> dict[str, object]:
    """Installed RAM. NOT a usage measurement; nothing here observes consumption."""
    raw = _text("/proc/meminfo")
    if raw:
        for line in raw.splitlines():
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return observed(int(parts[1]) * 1024)
    if os.name == "nt":
        total = _windows_total_ram()
        if total:
            return observed(total)
        return unavailable("GlobalMemoryStatusEx did not report a total")
    return unavailable("no MemTotal in /proc/meminfo and not Windows")


def _windows_total_ram() -> int | None:
    if os.name != "nt":
        return None
    import ctypes  # only needed on the Windows path

    class _Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = _Status()
    status.dwLength = ctypes.sizeof(_Status)
    try:
        # ctypes.windll is defined only on Windows; same treatment as above.
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.ullTotalPhys) or None


def _virtualization() -> dict[str, object]:
    """Exact, or explicitly classified. Never a guessed 'probably bare metal'."""
    found = _tool(["systemd-detect-virt"])
    if found is not None:
        # Exit 1 with "none" is the tool answering, not failing.
        answer = found[1].strip()
        if answer and "\n" not in answer:
            return observed(answer)
    vendor = (_text("/sys/class/dmi/id/sys_vendor") or "").strip()
    product = (_text("/sys/class/dmi/id/product_name") or "").strip()
    if vendor or product:
        return observed(f"dmi sys_vendor={vendor or '?'} product_name={product or '?'}")
    return unavailable("systemd-detect-virt absent or unclear and no DMI identity under /sys")


def _power_policy() -> dict[str, object]:
    governor = _text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if governor and governor.strip():
        return observed(f"cpufreq scaling_governor={governor.strip()}")
    if os.name == "nt":
        found = _tool(["powercfg", "/getactivescheme"])
        if found and found[0] == 0 and found[1].strip():
            return observed(found[1].strip())
        return unavailable("powercfg /getactivescheme produced no active scheme")
    return unavailable(
        "no /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor on this host; CPU "
        "frequency policy is not observable here")


def _python() -> dict[str, object]:
    return observed(f"{platform.python_implementation()} "
                    f"{sys.version.replace(chr(10), ' ').strip()}")


def _version_of(name: str, argv: list[str]) -> dict[str, object]:
    found = _tool(argv)
    if found is None:
        return unavailable(f"{name} is not on PATH")
    code, text = found
    if code != 0 or not text:
        return unavailable(f"{' '.join(argv)} exited {code} without a version")
    return observed("; ".join(line.strip() for line in text.splitlines() if line.strip()))


# --- the manifest -----------------------------------------------------------


def _refuse_drift(what: str, declared: tuple[str, ...], collected: Mapping[str, object]) -> None:
    """A declared field with no collector is a schema that lies about itself."""
    missing = [name for name in declared if name not in collected]
    extra = [name for name in collected if name not in declared]
    if missing or extra:
        raise CaptureRefused(
            f"{what}: the declared schema and the collected fields disagree — "
            f"declared with no collector: {missing or 'none'}; "
            f"collected but undeclared: {extra or 'none'}")


def capture(environment_id: str) -> dict[str, object]:
    """Build one host's manifest. Starts no clock and observes no resource use."""
    if not isinstance(environment_id, str) or not environment_id.strip():
        raise CaptureRefused(
            "environment_id is assigned by the owner and must be a non-empty string; "
            "it is not discoverable, so there is nothing to fall back to")
    identity: dict[str, object] = {
        "environment_id": observed(environment_id.strip()),
        "host_fingerprint": _host_fingerprint(),
        "os_build": _os_build(),
        "kernel": _kernel(),
        "cpu_model": _cpu_model(),
        "logical_cpu_count": _logical_cpu_count(),
        "memory_bytes": _memory_bytes(),
        "virtualization": _virtualization(),
        "power_policy": _power_policy(),
        "python": _python(),
        "rustc": _version_of("rustc", ["rustc", "--version", "--verbose"]),
        "dotnet": _version_of("dotnet", ["dotnet", "--version"]),
    }
    # The declared schema and the collectors above can drift apart. Projecting one
    # through the other would then die with a KeyError, which is a traceback rather
    # than a refusal, so the mismatch is named instead.
    _refuse_drift("identity", IDENTITY_FIELDS, identity)

    stamp = datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()
    provenance: dict[str, object] = {
        "timestamp_utc": stamp,
        "runner_name": os.environ.get("RUNNER_NAME") or None,
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID") or None,
        "job_id": os.environ.get("GITHUB_JOB") or None,
        "ci": bool(os.environ.get("CI")),
    }
    _refuse_drift("provenance", PROVENANCE_FIELDS, provenance)
    return {
        "schema": SCHEMA,
        "measurement_free": True,
        "identity": {k: identity[k] for k in IDENTITY_FIELDS},
        "provenance": {k: provenance[k] for k in PROVENANCE_FIELDS},
        "note": ("identity fields decide whether two runs share one measurement "
                 "environment; provenance fields never do. This manifest contains no "
                 "timing and no resource observation."),
    }


def field_problems(name: str, field: object) -> list[str]:
    """The two-shape contract, checked rather than described."""
    if not isinstance(field, Mapping):
        return [f"{name}: expected an object with a status, got {type(field).__name__}"]
    status = field.get("status")
    if status == OBSERVED:
        problems = []
        if "reason" in field:
            problems.append(f"{name}: observed fields carry no reason")
        if "value" not in field:
            problems.append(f"{name}: observed with no value")
            return problems
        value = field["value"]
        # bool IS an int in Python, so an unchecked numeric test would accept True.
        if isinstance(value, bool):
            problems.append(f"{name}: a boolean is not an identity value")
        elif isinstance(value, str) and not value.strip():
            problems.append(f"{name}: observed with an empty string, which is not an observation")
        elif isinstance(value, int) and value <= 0:
            problems.append(f"{name}: observed with {value}, and zero is not a measurement")
        elif value is None:
            problems.append(f"{name}: observed with null; absence is 'unavailable' with a reason")
        elif not isinstance(value, str | int):
            problems.append(f"{name}: value is {type(value).__name__}, not a string or a count")
        return problems
    if status == UNAVAILABLE:
        if name in ASSIGNED_FIELDS:
            return [f"{name}: assigned by the owner, so it can never be unavailable"]
        reason = field.get("reason")
        if "value" in field:
            return [f"{name}: unavailable fields carry no value"]
        if not isinstance(reason, str) or not reason.strip():
            return [f"{name}: unavailable with no stated reason"]
        return []
    return [f"{name}: status {status!r} is neither {OBSERVED!r} nor {UNAVAILABLE!r}"]


def validate(manifest: object) -> list[str]:
    """Pure. Returns every problem, so one fixture reports all of them at once."""
    if not isinstance(manifest, Mapping):
        return [f"manifest: expected an object, got {type(manifest).__name__}"]
    problems: list[str] = []
    if manifest.get("schema") != SCHEMA:
        problems.append(f"schema: expected {SCHEMA!r}, got {manifest.get('schema')!r}")
    identity = manifest.get("identity")
    provenance = manifest.get("provenance")
    if not isinstance(identity, Mapping):
        problems.append("identity: missing or not an object")
    else:
        for name in IDENTITY_FIELDS:
            if name not in identity:
                problems.append(f"identity.{name}: missing; a silent absence is not 'unavailable'")
            else:
                problems.extend(field_problems(f"identity.{name}", identity[name]))
        for name in identity:
            if name not in IDENTITY_FIELDS:
                problems.append(f"identity.{name}: not a declared identity field")
    if not isinstance(provenance, Mapping):
        problems.append("provenance: missing or not an object")
    else:
        for name in PROVENANCE_FIELDS:
            if name not in provenance:
                problems.append(f"provenance.{name}: missing")
        for name in provenance:
            if name not in PROVENANCE_FIELDS:
                problems.append(f"provenance.{name}: not a declared provenance field")
            elif name in IDENTITY_FIELDS:
                problems.append(f"provenance.{name}: is an identity field and must not be here")
    return problems


def identity_drift(earlier: Mapping[str, object], later: Mapping[str, object]) -> tuple[str, ...]:
    """Identity fields that differ. Provenance is never consulted.

    A field compares whole: a status that moved from observed to unavailable, or
    a reason that changed, is drift. Reading only `value` would let a field go
    dark between runs without anyone noticing.
    """
    a, b = earlier.get("identity"), later.get("identity")
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        raise CaptureRefused("both manifests must carry an identity object to be compared")
    return tuple(name for name in IDENTITY_FIELDS if a.get(name) != b.get(name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--environment-id", help="owner-assigned stable identifier")
    parser.add_argument("--emit", type=Path, help="write the manifest here")
    parser.add_argument("--selftest", action="store_true",
                        help="capture this host and validate it, writing nothing")
    args = parser.parse_args(argv)

    if args.selftest:
        manifest = capture("selftest-not-a-measurement-environment")
        problems = validate(manifest)
        for problem in problems:
            print(f"FAIL: {problem}")
        print(json.dumps({"identity": manifest["identity"]}, indent=2, sort_keys=False))
        return 1 if problems else 0

    if not args.environment_id:
        print("refused: --environment-id is required and is assigned by the owner", file=sys.stderr)
        return 2
    try:
        manifest = capture(args.environment_id)
    except CaptureRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    problems = validate(manifest)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    text = json.dumps(manifest, indent=2, sort_keys=False) + "\n"
    if args.emit:
        args.emit.write_text(text, encoding="utf-8")
        print(f"wrote {args.emit}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
