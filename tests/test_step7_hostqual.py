#!/usr/bin/env python3
"""#263 step 7 — controls on qualification, eligibility, admissibility and binding.

    hostqual-memory-vocabulary     one closed set, three files, no drift
    hostqual-t0-versioned          a qualification is versioned by the T0 it claims
    hostqual-ci-predicate          ci == false, not "the field is absent"
    hostqual-provisioning-values   shape AND value; a VM that promises nothing fails
    hostqual-one-environment-id    one identity, not three strings that usually agree
    hostqual-quiesce-window        120 s means 120 s, of which 60 s is measured
    hostqual-quiesce-arithmetic    quiet passes; spike, mean, gap and rewind do not
    hostqual-identity-projection   the whole identity set is compared, not one field
    hostqual-candidate-at-start    the executable present must be the one bound
    hostqual-postflight            drift during the session is caught after it
    hostqual-one-binding           two campaign identities cannot meet in one session
    execbinding-proves-inputs      T0, digest and manifest are proved, not trusted
    execbinding-old-t0             a host qualified under another T0 cannot enter
    execbinding-verify-campaign    the verifier checks the campaign, not two hashes
    execbinding-no-overwrite       a rebuild is deliberate, never silent
    provisioning-example-validates the template still fits the schema it teaches
    tools-do-not-import-harness    qualification never reaches into the instrument

Git-dependent controls build a throwaway repository, so T0 and instrument
identity are proved against real objects rather than mocked strings.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_step7_hostqual.py
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "step7"))

import execbinding as eb  # noqa: E402
import hostqual as hq  # noqa: E402
import perf_baseline as pb  # noqa: E402

EXAMPLE = ROOT / "scripts" / "step7" / "examples" / "host-provisioning.example.json"

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def guarded(check: str, control: Callable[[], None]) -> None:
    try:
        control()
    except Exception as exc:  # a crashing control is a finding, not a traceback
        fail(check, f"the control raised {type(exc).__name__}: {exc}")


# --- fixtures ---------------------------------------------------------------


T0_FROZEN = "# T0\n\n```text\nStatus:\n  FROZEN.\n  collection_authorized: true\n```\n"
T0_OPEN = "# T0\n\n```text\nStatus:\n  NOT_FROZEN.\n  collection_authorized: false\n```\n"

# A compliant Windows snapshot, used as a fixture on every platform so the
# Windows rules are driven on Linux too — and so these controls do not depend on
# whatever the machine running them happens to have in its power plan.
COMPLIANT_POWER = {"platform": "windows", "plan_guid": hq.WIN_ACCEPTED_PLANS[0],
                   "processor_min_ac": 100, "processor_max_ac": 100,
                   "processor_min_dc": 100, "processor_max_dc": 100}


@contextlib.contextmanager
def fixed_power(snapshot: dict):
    original = hq.power_snapshot
    hq.power_snapshot = lambda: dict(snapshot)  # type: ignore[assignment]
    try:
        yield
    finally:
        hq.power_snapshot = original  # type: ignore[assignment]


def git_repo(tmp: Path, files: dict[str, str], message: str = "fixture") -> str:
    tmp.mkdir(parents=True, exist_ok=True)
    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(tmp), *args], capture_output=True, check=True)
    if not (tmp / ".git").exists():
        run("init", "-q")
        run("config", "user.email", "control@example.invalid")
        run("config", "user.name", "control")
    for name, text in files.items():
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", message)
    return subprocess.run(["git", "-C", str(tmp), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def manifest(ci: bool = False, fingerprint: str = "sha256:abc", environment_id: str = "env-1",
             kernel: str = "6.1.0") -> dict:
    return {
        "identity": {
            "environment_id": {"status": "observed", "value": environment_id},
            "host_fingerprint": {"status": "observed", "value": fingerprint},
            "kernel": {"status": "observed", "value": kernel},
        },
        "provenance": {"ci": ci, "timestamp_utc": "2026-09-16T00:00:00+00:00"},
    }


def provisioning(**overrides: object) -> dict:
    doc: dict[str, object] = {
        "kind": hq.PROVISIONING_SCHEMA, "schema": 1,
        "environment_id": "env-1", "host_fingerprint": "sha256:abc",
        "operator": "owner", "recorded_at": "2026-09-16T00:00:00+00:00",
        "dedicated_to_p022": True, "no_concurrent_user_workload": True,
        "hosted_ci_runner": False,
        "virtualization": {"is_vm": False,
                           "fixed_vcpu": "n/a: physical",
                           "fixed_ram": "n/a: physical",
                           "live_migration_disabled": "n/a: physical",
                           "dynamic_memory_disabled": "n/a: physical"},
    }
    doc.update(overrides)
    return doc


def vm_provisioning(**virt_overrides: object) -> dict:
    virt = {"is_vm": True, "fixed_vcpu": True, "fixed_ram": True,
            "live_migration_disabled": True, "dynamic_memory_disabled": True}
    virt.update(virt_overrides)
    return provisioning(virtualization=virt)


def declaration(**overrides: object) -> dict:
    doc: dict[str, object] = {
        "kind": hq.DECLARATION_SCHEMA, "schema": 1,
        "no_campaign_workload": True, "no_interactive_user_workload": True,
        "no_prohibited_background_job_active": True,
        "operator": "owner", "recorded_at": "2026-09-16T00:00:00+00:00"}
    doc.update(overrides)
    return doc


def qualification(stratum: str = "linux", t0: dict | None = None, **overrides) -> dict:
    doc: dict[str, object] = {
        "kind": "own.net/p022/host-qualification", "schema": 1, "stratum": stratum,
        "t0": t0 or {"commit": "c" * 40, "path": "t0.md", "blob_sha": "b" * 40,
                     "sha256": "f" * 64, "status": "FROZEN"},
        "environment_id": "env-1", "host_fingerprint": "sha256:abc",
        "environment_identity_sha256": hq.canonical_sha256(manifest()["identity"]),
        "provisioning": {"sha256": "0" * 64},
        "environment_manifest": {"sha256": "1" * 64},
        "qualification_tool": {"sha256": "2" * 64},
        "power_snapshot": dict(COMPLIANT_POWER),
        "predicate": {k: "pass" for k in hq.PREDICATE_KEYS},
        "memory_metric": hq.STRATUM_METRIC[stratum],
        "qualified": True, "qualified_at": "2026-09-16T00:00:00+00:00"}
    doc.update(overrides)
    return doc


def write(tmp: Path, name: str, doc: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def steady(n: int = hq.QUIESCE_INTERVALS):
    series = iter([(0, 0)] + [(i, i * 100) for i in range(1, n + 1)])
    return lambda: next(series, None)


# --- vocabulary and T0 -------------------------------------------------------


def control_memory_vocabulary() -> None:
    if set(hq.STRATUM_METRIC.values()) != pb.MEMORY_METRICS:
        fail("hostqual-memory-vocabulary", "hostqual and the instrument disagree")
        return
    if hq.STRATUM_METRIC != eb.STRATUM_METRIC:
        fail("hostqual-memory-vocabulary", "the two tools map strata differently")
        return
    if hq.STRATUM_METRIC["linux"] == hq.STRATUM_METRIC["windows"]:
        fail("hostqual-memory-vocabulary", "both strata map to one metric")
        return
    ok("hostqual-memory-vocabulary",
       "the closed set is identical in hostqual, execbinding and the instrument")


def control_t0_versioned() -> None:
    """A qualification claims to satisfy T0-7, so it cannot float free of T0."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo = tmp / "repo"
        open_commit = git_repo(repo, {"t0.md": T0_OPEN}, "t0 open")
        frozen_commit = git_repo(repo, {"t0.md": T0_FROZEN}, "t0 frozen")

        block, result = hq.bind_t0(repo, "t0.md", open_commit)
        if result["result"] != "fail" or "NOT_FROZEN" not in str(result["detail"]):
            fail("hostqual-t0-versioned", f"a NOT_FROZEN T0 was accepted: {result}")
            return
        block, result = hq.bind_t0(repo, "t0.md", frozen_commit)
        if result["result"] != "pass":
            fail("hostqual-t0-versioned", f"a FROZEN T0 was refused: {result}")
            return
        for field in ("commit", "blob_sha", "sha256", "path"):
            if not block.get(field):
                fail("hostqual-t0-versioned", f"the bound T0 block has no {field}")
                return
        missing_commit = hq.bind_t0(repo, "t0.md", "0" * 40)[1]
        if missing_commit["result"] != "fail":
            fail("hostqual-t0-versioned", "a nonexistent commit was accepted")
            return
        wrong_path = hq.bind_t0(repo, "nope.md", frozen_commit)[1]
        if wrong_path["result"] != "fail":
            fail("hostqual-t0-versioned", "a path absent at that commit was accepted")
            return
    ok("hostqual-t0-versioned",
       "the commit must exist, the path must exist at it, the bytes are hashed from the blob, "
       "and NOT_FROZEN refuses: reconnaissance cannot become qualification by reuse")


# --- declared evidence -------------------------------------------------------


def control_ci_predicate() -> None:
    if hq.check_ci(manifest(ci=False))["result"] != "pass":
        fail("hostqual-ci-predicate", "ci false was refused")
        return
    if hq.check_ci(manifest(ci=True))["result"] != "fail":
        fail("hostqual-ci-predicate", "ci true was accepted")
        return
    absent = manifest()
    del absent["provenance"]["ci"]
    if hq.check_ci(absent)["result"] != "fail":
        fail("hostqual-ci-predicate", "a manifest with no ci field was accepted")
        return
    wrong = manifest()
    wrong["provenance"]["ci"] = "false"
    if hq.check_ci(wrong)["result"] != "fail":
        fail("hostqual-ci-predicate", "the string 'false' passed as a boolean")
        return
    ok("hostqual-ci-predicate", "ci == false; absent or non-boolean is refused")


def control_provisioning_values() -> None:
    """Shape was never the question. The values are the declaration."""
    if hq.validate_provisioning(provisioning()):
        fail("hostqual-provisioning-values", "a valid physical-host declaration was refused")
        return
    if hq.validate_provisioning(vm_provisioning()):
        fail("hostqual-provisioning-values", "a valid VM declaration was refused")
        return

    cases = [
        ("dedicated_to_p022 false", provisioning(dedicated_to_p022=False)),
        ("no_concurrent_user_workload false", provisioning(no_concurrent_user_workload=False)),
        ("hosted_ci_runner true", provisioning(hosted_ci_runner=True)),
        ("VM fixed_vcpu false", vm_provisioning(fixed_vcpu=False)),
        ("VM fixed_ram false", vm_provisioning(fixed_ram=False)),
        ("VM live_migration_disabled false", vm_provisioning(live_migration_disabled=False)),
        ("VM dynamic_memory_disabled false", vm_provisioning(dynamic_memory_disabled=False)),
        ("VM answering n/a", vm_provisioning(fixed_vcpu="n/a: do not ask")),
        ("is_vm as n/a", provisioning(virtualization={"is_vm": "n/a: unclear"})),
    ]
    for label, doc in cases:
        if not hq.validate_provisioning(doc):
            fail("hostqual-provisioning-values", f"{label} was accepted")
            return
    physical_hole = provisioning()
    physical_hole["virtualization"]["fixed_vcpu"] = True
    if not hq.validate_provisioning(physical_hole):
        fail("hostqual-provisioning-values",
             "a physical host answering the VM questions with bare booleans was accepted")
        return
    ok("hostqual-provisioning-values",
       "every required boolean is checked by VALUE: a VM that cannot promise fixed vCPU, fixed "
       "RAM, no live migration or no dynamic memory fails, and 'n/a' is unavailable to it")


def control_one_environment_id() -> None:
    mismatch = hq.check_single_tenant(provisioning(environment_id="env-other"), manifest())
    if mismatch["result"] != "fail":
        fail("hostqual-one-environment-id",
             "a declaration naming another environment qualified this one")
        return
    agree = hq.check_single_tenant(provisioning(), manifest())
    if agree["result"] != "pass":
        fail("hostqual-one-environment-id", f"agreeing identities were refused: {agree}")
        return
    source = (ROOT / "scripts" / "step7" / "hostqual.py").read_text(encoding="utf-8")
    if "--environment-id" in source:
        fail("hostqual-one-environment-id",
             "the tool still accepts an independent --environment-id; that is a third string "
             "that only happens to agree while everyone behaves")
        return
    ok("hostqual-one-environment-id",
       "the id is the manifest's observed value, the declaration must agree with it, and there "
       "is no third source to disagree with either")


# --- quiesce -----------------------------------------------------------------


def control_quiesce_window() -> None:
    """120 s means 120 s. A constant that nobody waits for is documentation."""
    slept: list[float] = []
    hq.quiesce(sleep=slept.append, counters=steady())
    total = sum(slept)
    if not slept or slept[0] != hq.QUIESCE_QUIET_S:
        fail("hostqual-quiesce-window",
             f"the quiet period was {slept[:1]}, expected a first wait of {hq.QUIESCE_QUIET_S}s")
        return
    if total != hq.QUIESCE_WINDOW_S:
        fail("hostqual-quiesce-window",
             f"the window lasted {total}s, not {hq.QUIESCE_WINDOW_S}s; sampling the final "
             "minute immediately turns the other minute into a comment")
        return
    measured = sum(slept[1:])
    if measured != hq.QUIESCE_INTERVAL_S * hq.QUIESCE_INTERVALS:
        fail("hostqual-quiesce-window", f"the measured part lasted {measured}s")
        return
    ok("hostqual-quiesce-window",
       f"{hq.QUIESCE_QUIET_S}s waited quietly, then {hq.QUIESCE_INTERVALS} intervals of "
       f"{hq.QUIESCE_INTERVAL_S}s = {hq.QUIESCE_WINDOW_S}s in total")


def control_quiesce_arithmetic() -> None:
    def counters(series):
        it = iter(series)
        return lambda: next(it, None)

    if not hq.quiesce(sleep=lambda _s: None, counters=steady())["eligible"]:
        fail("hostqual-quiesce-arithmetic", "a 1% machine was refused")
        return
    spike = [(0, 0)] + [(i * 30 if i == 4 else i, i * 100)
                        for i in range(1, hq.QUIESCE_INTERVALS + 1)]
    busy = [(0, 0)] + [(i * 10, i * 100) for i in range(1, hq.QUIESCE_INTERVALS + 1)]
    short = [(0, 0)] + [(i, i * 100) for i in range(1, 4)]
    rewind = [(0, 0), (5, 100), (1, 50)]
    for label, series in (("a 20% spike", spike), ("a 10% mean", busy),
                          ("a missing sample", short), ("a rewound counter", rewind)):
        if hq.quiesce(sleep=lambda _s: None, counters=counters(series))["eligible"]:
            fail("hostqual-quiesce-arithmetic", f"{label} was accepted")
            return
    ok("hostqual-quiesce-arithmetic",
       "quiet passes; a spike over 20%, a 10% mean, a missing sample and a rewound counter "
       "each refuse rather than skip")


# --- session identity --------------------------------------------------------


def _session(tmp: Path, *, fresh: dict | None = None, candidate: bytes = b"candidate",
             bound_candidate: bytes = b"candidate", qual: dict | None = None):
    qualification_doc = qual or qualification()
    qpath = write(tmp, "q.json", qualification_doc)
    binding = {"linux": {"qualification_sha256": hq.sha256_file(qpath),
                         "memory_metric": hq.STRATUM_METRIC["linux"],
                         "candidate_sha256": hq.sha256_bytes(bound_candidate),
                         "candidate_bytes": len(bound_candidate)}}
    bpath = write(tmp, "b.json", binding)
    mpath = write(tmp, "m.json", fresh or manifest())
    dpath = write(tmp, "d.json", declaration())
    cpath = tmp / "cand.bin"
    cpath.write_bytes(candidate)
    quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}
    with fixed_power(COMPLIANT_POWER):
        record = hq.session_eligibility(bpath, qpath, mpath, dpath, cpath, quiesce_result=quiet)
    return record, (bpath, qpath, mpath, dpath, cpath)


def control_identity_projection() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        good, _ = _session(tmp)
        if not good["eligible"]:
            fail("hostqual-identity-projection", f"a clean session was refused: {good['reasons']}")
            return
        drifted, _ = _session(tmp, fresh=manifest(kernel="6.2.0"))
        if drifted["eligible"]:
            fail("hostqual-identity-projection",
                 "a manifest whose kernel changed still preflighted; only host_fingerprint was "
                 "being compared and the rest of the identity set walked through")
            return
        if not any("identity" in r for r in drifted["reasons"]):
            fail("hostqual-identity-projection", f"refused for the wrong reason: {drifted}")
            return
    ok("hostqual-identity-projection",
       "the whole identity block is compared as one content-addressed projection, so a changed "
       "kernel, CPU, RAM or toolchain cannot walk past a matching fingerprint")


def control_candidate_at_start() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        swapped, _ = _session(tmp, candidate=b"a different executable")
        if swapped["eligible"]:
            fail("hostqual-candidate-at-start", "a substituted candidate preflighted")
            return
        if not any("bound to" in r for r in swapped["reasons"]):
            fail("hostqual-candidate-at-start", f"refused for the wrong reason: {swapped}")
            return
    ok("hostqual-candidate-at-start",
       "the executable that will run is hashed and compared to the bound candidate before the "
       "clock, not assumed from the path it was found at")


def control_postflight() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        pre, (bpath, qpath, mpath, dpath, cpath) = _session(tmp)
        ppath = write(tmp, "pre.json", pre)
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")

        with fixed_power(COMPLIANT_POWER):
            clean = hq.session_admissibility(bpath, qpath, ppath, mpath, cpath, probe)
        if not clean["admissible"]:
            fail("hostqual-postflight", f"a clean attempt was refused: {clean['reasons']}")
            return

        moved = write(tmp, "after.json", manifest(kernel="6.9.9"))
        with fixed_power(COMPLIANT_POWER):
            drifted = hq.session_admissibility(bpath, qpath, ppath, moved, cpath, probe)
        if drifted["admissible"]:
            fail("hostqual-postflight", "an environment that changed mid-session was admissible")
            return

        other = tmp / "other.bin"
        other.write_bytes(b"rebuilt candidate")
        with fixed_power(COMPLIANT_POWER):
            rebuilt = hq.session_admissibility(bpath, qpath, ppath, mpath, other, probe)
        if rebuilt["admissible"]:
            fail("hostqual-postflight", "a candidate rebuilt mid-session was admissible")
            return

        with fixed_power(COMPLIANT_POWER):
            missing_probe = hq.session_admissibility(bpath, qpath, ppath, mpath, cpath,
                                                     tmp / "absent.json")
        if missing_probe["admissible"]:
            fail("hostqual-postflight", "an attempt with no closing probe was admissible")
            return
    ok("hostqual-postflight",
       "a separate post-session pass catches identity drift, candidate drift and a missing "
       "closing probe; preflight may not certify what a session did after it started")


def control_one_binding() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        pre, (bpath, qpath, mpath, dpath, cpath) = _session(tmp)
        ppath = write(tmp, "pre.json", pre)
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        second = write(tmp, "b2.json", {**json.loads(bpath.read_text(encoding="utf-8")),
                                        "bound_at": "later"})
        with fixed_power(COMPLIANT_POWER):
            mixed = hq.session_admissibility(second, qpath, ppath, mpath, cpath, probe)
        if mixed["admissible"]:
            fail("hostqual-one-binding",
                 "a preflight from one binding and a postflight from another were admissible; "
                 "a changed binding is a different campaign, never a newer one")
            return
    ok("hostqual-one-binding",
       "two execution_binding_sha256 values cannot meet inside one session record")


# --- the binding -------------------------------------------------------------


def _instrument_repo(tmp: Path) -> tuple[Path, str, str, str]:
    """A throwaway repo carrying a T0 and the two instrument sources."""
    repo = tmp / "repo"
    commit = git_repo(repo, {"t0.md": T0_FROZEN,
                             eb.INSTRUMENT_SOURCES[0]: "print('instrument')\n",
                             eb.INSTRUMENT_SOURCES[1]: '{"decisive": []}\n'})
    digest = eb.harness_digest_at(repo, commit)
    return repo, commit, digest or "", "t0.md"


def control_execbinding_proves_inputs() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = _instrument_repo(tmp)
        t0 = eb.t0_at(repo, t0_path, commit)
        lin = write(tmp, "ql.json", qualification("linux", t0=t0))
        win = write(tmp, "qw.json", qualification("windows", t0=t0))
        cand_l, cand_w = tmp / "cl", tmp / "cw"
        cand_l.write_bytes(b"linux")
        cand_w.write_bytes(b"windows-longer")

        binding = eb.build(repo, t0_path, commit, commit, digest,
                           {"linux": (lin, cand_l), "windows": (win, cand_w)})
        if eb.validate(binding):
            fail("execbinding-proves-inputs", f"a good binding was refused: {eb.validate(binding)}")
            return
        blob = json.dumps(binding)
        if any(word in blob for word in ("governor", "power_snapshot", "predicate_detail")):
            fail("execbinding-proves-inputs", "the binding copies qualification detail")
            return

        try:
            eb.build(repo, t0_path, commit, commit, "0" * 64,
                     {"linux": (lin, cand_l), "windows": (win, cand_w)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-proves-inputs",
                 "a harness digest the sources do not produce was accepted as a string")
            return

        open_commit = git_repo(repo, {"t0.md": T0_OPEN}, "reopen")
        try:
            eb.t0_at(repo, "t0.md", open_commit)
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-proves-inputs", "a NOT_FROZEN T0 was bound")
            return
    ok("execbinding-proves-inputs",
       "the harness digest is recomputed from the instrument sources at the bound commit by the "
       "frozen formula, the manifest comes from the same commit's git object, and a NOT_FROZEN "
       "T0 cannot be bound")


def control_execbinding_old_t0() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = _instrument_repo(tmp)
        old_t0 = eb.t0_at(repo, t0_path, commit)
        newer = git_repo(repo, {"t0.md": T0_FROZEN + "\nAmended.\n"}, "t0 amended")
        lin = write(tmp, "ql.json", qualification("linux", t0=old_t0))
        win = write(tmp, "qw.json", qualification("windows", t0=old_t0))
        cand = tmp / "c"
        cand.write_bytes(b"x")
        try:
            eb.build(repo, t0_path, newer, commit, digest,
                     {"linux": (lin, cand), "windows": (win, cand)})
        except eb.BindingRefused as exc:
            if "qualified against T0" not in str(exc):
                fail("execbinding-old-t0", f"refused for the wrong reason: {exc}")
                return
        else:
            fail("execbinding-old-t0",
                 "a host qualified under an earlier T0 entered a campaign bound to a newer one")
            return
    ok("execbinding-old-t0",
       "a qualification earned under one protocol is not evidence under another")


def control_execbinding_verify_campaign() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = _instrument_repo(tmp)
        t0 = eb.t0_at(repo, t0_path, commit)
        lin = write(tmp, "ql.json", qualification("linux", t0=t0))
        win = write(tmp, "qw.json", qualification("windows", t0=t0))
        cand_l, cand_w = tmp / "cl", tmp / "cw"
        cand_l.write_bytes(b"linux")
        cand_w.write_bytes(b"windows-longer")
        binding = eb.build(repo, t0_path, commit, commit, digest,
                           {"linux": (lin, cand_l), "windows": (win, cand_w)})
        bpath = write(tmp, "binding.json", binding)
        quals = {"linux": lin, "windows": win}
        cands = {"linux": cand_l, "windows": cand_w}

        if eb.verify(repo, bpath, quals, cands):
            fail("execbinding-verify-campaign",
                 f"a clean campaign failed verification: {eb.verify(repo, bpath, quals, cands)}")
            return

        cand_w.write_bytes(b"a replacement binary")
        if not any("candidate" in p for p in eb.verify(repo, bpath, quals, cands)):
            fail("execbinding-verify-campaign", "a replaced candidate was not caught")
            return
        cand_w.write_bytes(b"windows-longer")

        write(tmp, "qw.json", qualification("windows", t0=t0, qualified_at="changed"))
        if not any("qualification" in p for p in eb.verify(repo, bpath, quals, cands)):
            fail("execbinding-verify-campaign", "a changed qualification was not caught")
            return
        write(tmp, "qw.json", qualification("windows", t0=t0))

        moved = json.loads(bpath.read_text(encoding="utf-8"))
        moved["workloads"]["manifest_sha256"] = "9" * 64
        moved_path = write(tmp, "moved.json", moved)
        if not any("workloads" in p for p in eb.verify(repo, moved_path, quals, cands)):
            fail("execbinding-verify-campaign", "a changed workload manifest was not caught")
            return

        retimed = json.loads(bpath.read_text(encoding="utf-8"))
        retimed["t0"]["sha256"] = "7" * 64
        retimed_path = write(tmp, "retimed.json", retimed)
        if not any("T0" in p for p in eb.verify(repo, retimed_path, quals, cands)):
            fail("execbinding-verify-campaign", "a changed T0 was not caught")
            return
    ok("execbinding-verify-campaign",
       "the verifier re-proves T0, instrument digest, workload manifest, both qualifications "
       "and both candidates — not two hashes with a confident docstring")


def control_execbinding_no_overwrite() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        existing = tmp / "binding.json"
        existing.write_text("{}", encoding="utf-8")
        noise = io.StringIO()
        with contextlib.redirect_stderr(noise):
            rc = eb.main(["--emit", str(existing)])
        if rc != 2 or "refused" not in noise.getvalue():
            fail("execbinding-no-overwrite", f"overwriting returned {rc}")
            return
        if existing.read_text(encoding="utf-8") != "{}":
            fail("execbinding-no-overwrite", "the existing binding was modified")
            return
    ok("execbinding-no-overwrite", "a rebuild before the first clock is deliberate, never silent")


# --- the template ------------------------------------------------------------


def control_provisioning_example() -> None:
    if not EXAMPLE.is_file():
        fail("provisioning-example-validates", f"{EXAMPLE} is missing")
        return
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    problems = hq.validate_provisioning(doc)
    if problems:
        fail("provisioning-example-validates",
             f"the template no longer validates under the rules it teaches: {problems}")
        return
    if "evidence" in EXAMPLE.parts:
        fail("provisioning-example-validates", "the template lives under an evidence directory")
        return
    marker = json.dumps(doc)
    if "EXAMPLE / NOT EVIDENCE" not in marker:
        fail("provisioning-example-validates", "the template does not say it is not evidence")
        return
    if "n/a: " not in marker or "is_vm" not in marker:
        fail("provisioning-example-validates",
             "the template does not show the n/a-versus-required-boolean rule")
        return
    ok("provisioning-example-validates",
       "the template validates under the same rules, says EXAMPLE / NOT EVIDENCE, shows the "
       "physical-host form and explains the VM one, and sits outside docs/evidence/")


def control_power_ac_and_dc() -> None:
    """Both AC and DC, so a machine cannot be compliant only while plugged in."""
    if hq.check_power_policy(COMPLIANT_POWER)["result"] != "pass":
        fail("hostqual-power-ac-and-dc", "a fully compliant snapshot was refused")
        return
    for label, patch in (("DC minimum below 100", {"processor_min_dc": 5}),
                         ("DC maximum below 100", {"processor_max_dc": 50}),
                         ("AC minimum below 100", {"processor_min_ac": 5}),
                         ("an unaccepted plan", {"plan_guid": "381b4222-f694-41f0-9685-ff5bb260df2e"})):
        if hq.check_power_policy({**COMPLIANT_POWER, **patch})["result"] != "fail":
            fail("hostqual-power-ac-and-dc", f"{label} was accepted")
            return
    linux_ok = {"platform": "linux", "governors": {"cpu0": "performance", "cpu1": "performance"},
                "boost": {"mechanism": "cpufreq/boost", "value": "1"}}
    if hq.check_power_policy(linux_ok)["result"] != "pass":
        fail("hostqual-power-ac-and-dc", "a compliant Linux snapshot was refused")
        return
    mixed = {**linux_ok, "governors": {"cpu0": "performance", "cpu1": "powersave"}}
    if hq.check_power_policy(mixed)["result"] != "fail":
        fail("hostqual-power-ac-and-dc", "one CPU on powersave was accepted")
        return
    unknown_boost = {**linux_ok, "boost": {"mechanism": None, "value": None}}
    if hq.check_power_policy(unknown_boost)["result"] != "fail":
        fail("hostqual-power-ac-and-dc", "a host with no identifiable turbo mechanism passed")
        return
    ok("hostqual-power-ac-and-dc",
       "Windows needs 100% on AC *and* DC and an accepted plan; Linux needs performance on every "
       "CPU and a turbo mechanism that can be named and rechecked")


def control_tools_do_not_import_harness() -> None:
    for name in ("hostqual.py", "execbinding.py"):
        tree = ast.parse((ROOT / "scripts" / "step7" / name).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        reached = [m for m in imported if m.split(".")[0] in ("perf_baseline", "envcapture")]
        if reached:
            fail("tools-do-not-import-harness", f"{name} imports {reached}")
            return
    ok("tools-do-not-import-harness",
       "neither tool imports the instrument; the digest is recomputed from git objects by the "
       "frozen formula rather than by asking the thing under proof")


def run() -> int:
    guarded("hostqual-memory-vocabulary", control_memory_vocabulary)
    guarded("hostqual-t0-versioned", control_t0_versioned)
    guarded("hostqual-ci-predicate", control_ci_predicate)
    guarded("hostqual-provisioning-values", control_provisioning_values)
    guarded("hostqual-one-environment-id", control_one_environment_id)
    guarded("hostqual-quiesce-window", control_quiesce_window)
    guarded("hostqual-quiesce-arithmetic", control_quiesce_arithmetic)
    guarded("hostqual-identity-projection", control_identity_projection)
    guarded("hostqual-candidate-at-start", control_candidate_at_start)
    guarded("hostqual-postflight", control_postflight)
    guarded("hostqual-one-binding", control_one_binding)
    guarded("execbinding-proves-inputs", control_execbinding_proves_inputs)
    guarded("execbinding-old-t0", control_execbinding_old_t0)
    guarded("execbinding-verify-campaign", control_execbinding_verify_campaign)
    guarded("execbinding-no-overwrite", control_execbinding_no_overwrite)
    guarded("provisioning-example-validates", control_provisioning_example)
    guarded("hostqual-power-ac-and-dc", control_power_ac_and_dc)
    guarded("tools-do-not-import-harness", control_tools_do_not_import_harness)
    print()
    print(f"step 7 host qualification controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
