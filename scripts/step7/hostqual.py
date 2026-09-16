#!/usr/bin/env python3
"""P-022 / #263 — step 7: host qualification and session eligibility.

Two questions, deliberately never merged into one artifact:

  QUALIFICATION  does this environment satisfy the T0-7 host predicate?
  SESSION        is this session, on that qualified host, eligible to start NOW?

A qualification is not a certificate of perpetual quiet. It proves the host can
satisfy the predicate and names the bytes it was proved against; the current
fitness of a particular session is proved again, per session, or "a fresh
manifest per session" becomes decorative paperwork.

This tool does NOT own the execution binding. Qualification answers "is this one
environment fit"; the binding answers "which Linux and Windows environments,
which candidates and which instrument form this campaign". A utility that checks
a CPU governor must not become the root of campaign identity — see
``execbinding.py``.

It carries no Rust-vs-Python number, starts no clock over a candidate, and
produces no measurement. The CPU sampling below is environment observation for
eligibility: it never times, and never touches, the thing under test.

Two classes of evidence, kept apart because only one of them is proof:

  DECLARED         provisioning facts a guest OS cannot establish — dedication,
                   hypervisor configuration, that no one else is using the box.
                   Recorded, content-addressed, and never called machine proof.
  MACHINE-OBSERVED what a checker actually asserts here and now.

Usage:
    python scripts/step7/hostqual.py --qualify --stratum linux \\
        --environment-id <id> --provisioning <p.json> --manifest <m.json> \\
        --emit <out.json>
    python scripts/step7/hostqual.py --session-preflight --binding <b.json> \\
        --qualification <q.json> --manifest <fresh.json> --emit <out.json>
    python scripts/step7/hostqual.py --selftest
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

QUALIFICATION_SCHEMA = "own.net/p022/host-qualification"
SESSION_SCHEMA = "own.net/p022/session-eligibility"
PROVISIONING_SCHEMA = "own.net/p022/host-provisioning"
SCHEMA_VERSION = 1

# The closed memory vocabulary. Declared here rather than imported so this tool
# does not reach into the frozen harness; `hostqual-memory-vocabulary` proves the
# two sets are identical, so a drift between them is a test failure and not a
# surprise in the field.
MEMORY_METRIC_RESIDENT = "max_process_peak_resident"
MEMORY_METRIC_COMMIT = "max_process_peak_commit"
STRATUM_METRIC = {"linux": MEMORY_METRIC_RESIDENT, "windows": MEMORY_METRIC_COMMIT}

PREDICATE_KEYS = ("ci", "single_tenant", "power_policy", "required_memory_metric")

# Quiesce, exactly as T0-7 fixes it. No cadence is left to a reader.
QUIESCE_WINDOW_S = 120
QUIESCE_INTERVAL_S = 5
QUIESCE_INTERVALS = 12          # the final 60 s
QUIESCE_MEAN_MAX = 0.05
QUIESCE_INTERVAL_MAX = 0.20

# Provisioning keys. A key that does not apply is present with an explicit
# "n/a: <reason>", never missing: an absent declaration is not a declaration.
PROVISIONING_BOOLEANS = ("dedicated_to_p022", "no_concurrent_user_workload",
                         "hosted_ci_runner", "prohibited_background_declared_inactive")
PROVISIONING_VM_BOOLEANS = ("is_vm", "fixed_vcpu", "fixed_ram",
                            "live_migration_disabled", "dynamic_memory_disabled")
PROVISIONING_STRINGS = ("environment_id", "host_fingerprint", "operator", "recorded_at")

# Windows processor-state settings, by GUID so no localized label is parsed.
WIN_SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
WIN_PROCTHROTTLEMIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"
WIN_PROCTHROTTLEMAX = "bc5038f7-23e0-4960-96da-33abaf5935ec"
WIN_REQUIRED_STATE = 100
WIN_ACCEPTED_PLANS = ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",   # High performance
                      "e9a42b02-d5df-448d-aa00-03f14749eb61")  # Ultimate Performance


class QualificationRefused(Exception):
    """Raised by name. A caller that reads through gets an exception, not a record."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _console_encoding() -> str:
    """The encoding a console tool's bytes arrive in.

    `text=True` would decode with the locale's ANSI code page while a console
    tool writes in the console output code page; on a non-English Windows the
    two disagree and the value becomes mojibake that moves with the ambient code
    page. Same defect, same fix as the capture tool's.
    """
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only
            for query in ("GetConsoleOutputCP", "GetOEMCP"):
                code_page = getattr(kernel32, query)()
                if code_page:
                    return f"cp{code_page}"
        except (AttributeError, OSError, ValueError):
            pass
    return "utf-8"


def _tool(argv: list[str]) -> tuple[int, str] | None:
    try:
        proc = subprocess.run(argv, capture_output=True, check=False)
    except (OSError, ValueError):
        return None
    enc = _console_encoding()
    return proc.returncode, (proc.stdout.decode(enc, "replace")
                             + proc.stderr.decode(enc, "replace")).strip()


def _text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def check(name: str, ok: bool, detail: str) -> dict[str, object]:
    return {"check": name, "result": "pass" if ok else "fail", "detail": detail}


# --- the predicate, one function per clause ---------------------------------


def check_ci(manifest: dict) -> dict[str, object]:
    """`ci == false`, not "the field is absent".

    The capture tool writes `ci` as a boolean on every manifest, so a predicate
    demanding its absence could never be satisfied by any real manifest.
    """
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or "ci" not in provenance:
        return check("ci", False, "the manifest carries no provenance.ci field")
    value = provenance["ci"]
    if not isinstance(value, bool):
        return check("ci", False, f"provenance.ci is {type(value).__name__}, not a boolean")
    return check("ci", value is False, f"manifest.provenance.ci == {json.dumps(value)}")


def validate_provisioning(doc: dict) -> list[str]:
    problems: list[str] = []
    if doc.get("kind") != PROVISIONING_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {PROVISIONING_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    for key in PROVISIONING_STRINGS:
        if not isinstance(doc.get(key), str) or not doc.get(key):
            problems.append(f"{key} is missing or not a non-empty string")
    for key in PROVISIONING_BOOLEANS:
        problems.extend(_declared_problem(key, doc.get(key, "<missing>")))
    virt = doc.get("virtualization")
    if not isinstance(virt, dict):
        problems.append("virtualization is missing")
    else:
        for key in PROVISIONING_VM_BOOLEANS:
            problems.extend(_declared_problem(f"virtualization.{key}",
                                              virt.get(key, "<missing>")))
    return problems


def _declared_problem(key: str, value: object) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, str) and value.startswith("n/a: ") and len(value) > 5:
        return []
    return [f"{key} must be a boolean or an explicit 'n/a: <reason>', got {value!r}"]


def check_single_tenant(provisioning: dict, manifest: dict) -> dict[str, object]:
    """Declared provisioning, shape-checked; runtime invariants, machine-checked.

    The declaration is never called proof. A guest operating system cannot look
    at a hypervisor and establish that no neighbour arrived on the same iron, and
    a checker that claimed otherwise would be security theatre in a lab coat.
    """
    problems = validate_provisioning(provisioning)
    if problems:
        return check("single_tenant", False,
                     "the provisioning declaration does not validate: " + "; ".join(problems))
    declared_false = [k for k in ("dedicated_to_p022", "no_concurrent_user_workload")
                      if provisioning.get(k) is False]
    if declared_false:
        return check("single_tenant", False,
                     f"provisioning declares {declared_false} false")
    if provisioning.get("hosted_ci_runner") is True:
        return check("single_tenant", False,
                     "provisioning declares a hosted CI runner, which is not measurement-grade")
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        return check("single_tenant", False, "the manifest carries no identity block")
    mismatch = [k for k in ("environment_id", "host_fingerprint")
                if _observed(identity, k) != provisioning.get(k)]
    if mismatch:
        return check("single_tenant", False,
                     f"provisioning and manifest disagree on {mismatch}; the declaration "
                     "describes a different machine than the one captured")
    return check("single_tenant", True,
                 "provisioning declaration validates and names this machine; runtime "
                 "invariants are recorded for the session checks to compare against")


def _observed(identity: dict, field: str) -> object:
    entry = identity.get(field)
    if isinstance(entry, dict) and entry.get("status") == "observed":
        return entry.get("value")
    return None


def check_power_policy() -> dict[str, object]:
    return _power_windows() if os.name == "nt" else _power_linux()


def _power_linux() -> dict[str, object]:
    governors: dict[str, str] = {}
    root = Path("/sys/devices/system/cpu")
    for cpu in sorted(root.glob("cpu[0-9]*")):
        value = _text(str(cpu / "cpufreq" / "scaling_governor"))
        if value:
            governors[cpu.name] = value
    if not governors:
        return check("power_policy", False,
                     "no cpufreq/scaling_governor on any CPU; the frequency policy is not "
                     "observable here, so this host is not eligible")
    wrong = {c: g for c, g in governors.items() if g != "performance"}
    if wrong:
        return check("power_policy", False, f"governor is not 'performance' on {sorted(wrong)}")
    boost = _turbo_linux()
    if boost is None:
        return check("power_policy", False,
                     "no turbo/boost mechanism could be identified (neither "
                     "intel_pstate/no_turbo nor cpufreq/boost); the state cannot be recorded "
                     "or rechecked, so this host is not eligible")
    return check("power_policy", True,
                 f"governor=performance on all {len(governors)} CPUs; {boost}")


def _turbo_linux() -> str | None:
    no_turbo = _text("/sys/devices/system/cpu/intel_pstate/no_turbo")
    if no_turbo is not None:
        return f"intel_pstate/no_turbo={no_turbo}"
    boost = _text("/sys/devices/system/cpu/cpufreq/boost")
    if boost is not None:
        return f"cpufreq/boost={boost}"
    return None


def _power_windows() -> dict[str, object]:
    active = _tool(["powercfg", "/getactivescheme"])
    if not active or active[0] != 0:
        return check("power_policy", False, "powercfg /getactivescheme produced no scheme")
    guids = re.findall(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", active[1])
    if not guids:
        return check("power_policy", False, f"no scheme GUID in powercfg output: {active[1]!r}")
    plan = guids[0].lower()
    if plan not in WIN_ACCEPTED_PLANS:
        return check("power_policy", False,
                     f"active plan {plan} is neither High Performance nor Ultimate Performance")
    states: dict[str, int] = {}
    for label, setting in (("minimum", WIN_PROCTHROTTLEMIN), ("maximum", WIN_PROCTHROTTLEMAX)):
        value = _win_ac_index(setting)
        if value is None:
            return check("power_policy", False,
                         f"the AC {label} processor state could not be read from powercfg")
        states[label] = value
    wrong = {k: v for k, v in states.items() if v != WIN_REQUIRED_STATE}
    if wrong:
        return check("power_policy", False,
                     f"processor state must be {WIN_REQUIRED_STATE}% on AC; got {wrong}")
    return check("power_policy", True,
                 f"active plan {plan}, AC processor state min=max={WIN_REQUIRED_STATE}%")


def _win_ac_index(setting_guid: str) -> int | None:
    """The AC setting index, read by GUID and by position.

    Parsed as hexadecimal indices rather than by label: the labels are localized,
    and a checker that greps English prose fails on a Russian Windows for a
    reason that has nothing to do with the machine.
    """
    found = _tool(["powercfg", "/query", "SCHEME_CURRENT", WIN_SUB_PROCESSOR, setting_guid])
    if not found or found[0] != 0:
        return None
    indices = re.findall(r"0x([0-9a-fA-F]{8})", found[1])
    # The block ends with the two current indices, AC then DC. Everything before
    # them describes the possible RANGE — minimum, maximum, increment — and a
    # first-match parse reads the range's minimum as the current setting, which
    # is how this returned 0% on a machine pinned at 100%.
    if len(indices) < 2:
        return None
    return int(indices[-2], 16)


def check_memory_metric(stratum: str) -> dict[str, object]:
    """The stratum's memory metric must exist as a mechanism on this host.

    A host on which the required primary metric has no mechanism is not eligible;
    T0-4 case A says such a session never starts, rather than starting and then
    failing.
    """
    expected = STRATUM_METRIC[stratum]
    if stratum == "linux":
        available = hasattr(os, "wait4")
        mechanism = "posix os.wait4 (ru_maxrss)"
    else:
        available = os.name == "nt"
        mechanism = "win32 job object (PeakProcessMemoryUsed)"
    if not available:
        return check("required_memory_metric", False,
                     f"stratum {stratum} requires {expected} via {mechanism}, which this host "
                     "does not provide")
    return check("required_memory_metric", True, f"{expected} via {mechanism}")


# --- quiesce, sampled exactly ------------------------------------------------


def _cpu_counters() -> tuple[int, int] | None:
    """(busy, total) from the platform's own aggregate counter."""
    if os.name == "nt":
        idle, kernel, user = (ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong())
        try:
            ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        except (AttributeError, OSError):
            return None
        if not ok:
            return None
        total = kernel.value + user.value          # kernel time includes idle
        return total - idle.value, total
    line = _text("/proc/stat")
    if not line or not line.startswith("cpu "):
        first = (line or "").splitlines()[0] if line else ""
        if not first.startswith("cpu "):
            return None
        line = first
    fields = [int(x) for x in line.split()[1:] if x.isdigit()]
    if len(fields) < 5:
        return None
    total = sum(fields)
    idle = fields[3] + fields[4]                   # idle + iowait
    return total - idle, total


def quiesce(sleep=time.sleep, counters=_cpu_counters,
            intervals: int = QUIESCE_INTERVALS) -> dict[str, object]:
    """The final 60 s of the window, as twelve 5 s intervals.

    A missing sample, a counter that went backwards or a zero denominator is
    NOT_ELIGIBLE, never a skipped interval: an unreadable machine is not a quiet
    machine.
    """
    samples: list[float] = []
    previous = counters()
    if previous is None:
        return {"eligible": False, "reason": "the CPU counter could not be read at all",
                "samples": [], "mean": None, "max": None}
    for _ in range(intervals):
        sleep(QUIESCE_INTERVAL_S)
        current = counters()
        if current is None:
            return {"eligible": False, "reason": "a CPU sample could not be read",
                    "samples": samples, "mean": None, "max": None}
        d_busy, d_total = current[0] - previous[0], current[1] - previous[1]
        previous = current
        if d_total <= 0 or d_busy < 0:
            return {"eligible": False,
                    "reason": f"the CPU counter did not advance sanely (busy {d_busy}, "
                              f"total {d_total})",
                    "samples": samples, "mean": None, "max": None}
        samples.append(d_busy / d_total)
    mean = sum(samples) / len(samples)
    worst = max(samples)
    if mean >= QUIESCE_MEAN_MAX:
        return {"eligible": False, "reason": f"mean utilisation {mean:.4f} is not below "
                f"{QUIESCE_MEAN_MAX}", "samples": samples, "mean": mean, "max": worst}
    if worst > QUIESCE_INTERVAL_MAX:
        return {"eligible": False, "reason": f"an interval reached {worst:.4f}, above "
                f"{QUIESCE_INTERVAL_MAX}", "samples": samples, "mean": mean, "max": worst}
    return {"eligible": True, "reason": "", "samples": samples, "mean": mean, "max": worst}


# --- the two records ---------------------------------------------------------


def qualify(stratum: str, environment_id: str, provisioning_path: Path,
            manifest_path: Path) -> dict[str, object]:
    if stratum not in STRATUM_METRIC:
        raise QualificationRefused(f"unknown stratum {stratum!r}")
    provisioning = json.loads(provisioning_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    checks = [check_ci(manifest),
              check_single_tenant(provisioning, manifest),
              check_power_policy(),
              check_memory_metric(stratum)]
    by_name = {c["check"]: c for c in checks}
    missing = [k for k in PREDICATE_KEYS if k not in by_name]
    if missing:
        raise QualificationRefused(f"the predicate did not produce {missing}")
    qualified = all(c["result"] == "pass" for c in checks)
    return {
        "kind": QUALIFICATION_SCHEMA,
        "schema": SCHEMA_VERSION,
        "stratum": stratum,
        "environment_id": environment_id,
        "host_fingerprint": _observed(identity, "host_fingerprint"),
        "provisioning": {"sha256": sha256_file(provisioning_path)},
        "environment_manifest": {"sha256": sha256_file(manifest_path)},
        "qualification_tool": {"sha256": sha256_file(Path(__file__).resolve())},
        "predicate": {name: by_name[name]["result"] for name in PREDICATE_KEYS},
        "predicate_detail": {name: by_name[name]["detail"] for name in PREDICATE_KEYS},
        "memory_metric": STRATUM_METRIC[stratum],
        "qualified": qualified,
        "qualified_at": _now(),
        "not_a_session_certificate": (
            "this record proves the host can satisfy the predicate against the bytes named "
            "above; the fitness of any particular session is proved again, per session"),
    }


def session_eligibility(binding_path: Path, qualification_path: Path, manifest_path: Path,
                        quiesce_result: dict[str, object] | None = None) -> dict[str, object]:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stratum = str(qualification.get("stratum"))
    reasons: list[str] = []

    if not qualification.get("qualified"):
        reasons.append("the referenced qualification does not say qualified")
    bound = (binding.get(stratum) or {}) if isinstance(binding.get(stratum), dict) else {}
    if bound.get("qualification_sha256") != sha256_file(qualification_path):
        reasons.append("the execution binding does not name this qualification; a qualified "
                       "host that is not part of this campaign may not be substituted into it")
    if bound.get("memory_metric") != qualification.get("memory_metric"):
        reasons.append("the binding and the qualification disagree about the memory metric")

    ci = check_ci(manifest)
    if ci["result"] != "pass":
        reasons.append(str(ci["detail"]))
    power = check_power_policy()
    if power["result"] != "pass":
        reasons.append(str(power["detail"]))

    identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    if _observed(identity, "host_fingerprint") != qualification.get("host_fingerprint"):
        reasons.append("the fresh manifest is not the machine this qualification describes")

    result = quiesce_result if quiesce_result is not None else quiesce()
    if not result.get("eligible"):
        reasons.append(f"quiesce: {result.get('reason')}")

    return {
        "kind": SESSION_SCHEMA,
        "schema": SCHEMA_VERSION,
        "stratum": stratum,
        "execution_binding_sha256": sha256_file(binding_path),
        "qualification_sha256": sha256_file(qualification_path),
        "fresh_environment_manifest_sha256": sha256_file(manifest_path),
        "power_policy": power,
        "ci": ci,
        "quiesce": result,
        "eligible": not reasons,
        "reasons": reasons,
        "recorded_at": _now(),
        "note": ("eligibility is not a measurement and not a verdict: a refusal here means the "
                 "session does not start, which is not INVALID, because no clock has run"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualify", action="store_true")
    parser.add_argument("--session-preflight", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--stratum", choices=sorted(STRATUM_METRIC))
    parser.add_argument("--environment-id")
    parser.add_argument("--provisioning", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--emit", type=Path)
    args = parser.parse_args(argv)

    if args.selftest:
        print(json.dumps({"tool_sha256": sha256_file(Path(__file__).resolve()),
                          "strata": STRATUM_METRIC,
                          "quiesce": {"window_s": QUIESCE_WINDOW_S,
                                      "intervals": QUIESCE_INTERVALS,
                                      "interval_s": QUIESCE_INTERVAL_S,
                                      "mean_max": QUIESCE_MEAN_MAX,
                                      "interval_max": QUIESCE_INTERVAL_MAX},
                          "predicate_keys": list(PREDICATE_KEYS)}, indent=2))
        return 0

    if args.qualify:
        for name in ("stratum", "environment_id", "provisioning", "manifest"):
            if getattr(args, name) is None:
                parser.error(f"--qualify requires --{name.replace('_', '-')}")
        record = qualify(args.stratum, args.environment_id, args.provisioning, args.manifest)
    elif args.session_preflight:
        for name in ("binding", "qualification", "manifest"):
            if getattr(args, name) is None:
                parser.error(f"--session-preflight requires --{name}")
        record = session_eligibility(args.binding, args.qualification, args.manifest)
    else:
        parser.error("choose --qualify, --session-preflight or --selftest")

    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.emit:
        args.emit.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    ok = bool(record.get("qualified") if args.qualify else record.get("eligible"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
