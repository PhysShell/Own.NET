#!/usr/bin/env python3
"""#263 step 7 — controls on qualification, eligibility, admissibility and binding.

    hostqual-memory-vocabulary     one closed set, three files, no drift
    hostqual-producer-schema       the duplicated schema string still equals the producer's
    hostqual-artifact-boundary     every consumed artifact is proved before it is read
    hostqual-t0-versioned          a qualification is versioned by the T0 it claims
    hostqual-ci-predicate          ci == false, not "the field is absent"
    hostqual-provisioning-shape    malformed is malformed; a boolean false is not
    hostqual-provisioning-predicate values are judged by the predicate, not the parser
    hostqual-negative-evidence     an honest no leaves a record, not a stderr line
    hostqual-campaign-link         the campaign and the freeze are joined by bytes
    hostqual-authority-states      four states, three refusals, both T0 paths
    hostqual-one-environment-id    one identity, not three strings that usually agree
    hostqual-quiesce-window        120 s means 120 s, of which 60 s is measured
    hostqual-quiesce-arithmetic    quiet passes; spike, mean, gap and rewind do not
    hostqual-identity-projection   the whole identity set is compared, not one field
    hostqual-candidate-at-start    the executable present must be the one bound
    hostqual-postflight            drift during the session is caught after it
    hostqual-one-binding           two campaign identities cannot meet in one session
    hostqual-power-ac-and-dc       compliant on AC only is not a fixed environment
    execbinding-proves-inputs      T0, digest and manifest are proved, not trusted
    execbinding-old-t0             a host qualified under another T0 cannot enter
    execbinding-verify-campaign    the verifier checks the campaign, not two hashes
    execbinding-verify-is-total    there is no partial verification under that name
    execbinding-no-overwrite       a rebuild is deliberate, never silent
    provisioning-example-validates the template still fits the schema it teaches
    control-inventory-complete     this list and the executed set are the same set
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
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "step7"))

import envcapture as ec  # noqa: E402
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


def refuses(call: Callable[[], object]) -> str | None:
    """The refusal message, or None when the call went through."""
    try:
        call()
    except hq.QualificationRefused as exc:
        return str(exc)
    return None


# --- fixtures ---------------------------------------------------------------


T0_FROZEN = "# T0\n\n```text\nStatus:\n  FROZEN.\n  collection_authorized: true\n```\n"
T0_OPEN = "# T0\n\n```text\nStatus:\n  NOT_FROZEN.\n  collection_authorized: false\n```\n"
T0_FROZEN_UNAUTHORIZED = "# T0\n\n```text\nStatus:\n  FROZEN.\n  collection_authorized: false\n```\n"
T0_OPEN_AUTHORIZED = "# T0\n\n```text\nStatus:\n  NOT_FROZEN.\n  collection_authorized: true\n```\n"

# A compliant Windows snapshot, used as a fixture on every platform so the
# Windows rules are driven on Linux too, and so these controls do not depend on
# whatever the machine running them has in its power plan.
COMPLIANT_POWER = {"platform": "windows", "plan_guid": hq.WIN_ACCEPTED_PLANS[0],
                   "processor_min_ac": 100, "processor_max_ac": 100,
                   "processor_min_dc": 100, "processor_max_dc": 100}

LINUX_CANDIDATE = b"linux candidate bytes"
WINDOWS_CANDIDATE = b"windows candidate, a different length"


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
             kernel: str = "6.1.0", schema: str | None = None) -> dict:
    return {
        "schema": hq.ENVCAPTURE_SCHEMA if schema is None else schema,
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


def t0_stub() -> dict:
    return {"commit": "c" * 40, "path": "t0.md", "blob_sha": "b" * 40,
            "sha256": "f" * 64, "status": "FROZEN"}


def qualification(stratum: str = "linux", t0: dict | None = None, **overrides) -> dict:
    doc: dict[str, object] = {
        "kind": hq.QUALIFICATION_SCHEMA, "schema": 1, "stratum": stratum,
        "t0": t0 or t0_stub(),
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


def binding_doc(linux_qual_sha: str, windows_qual_sha: str, t0: dict | None = None,
                linux_candidate: bytes = LINUX_CANDIDATE,
                windows_candidate: bytes = WINDOWS_CANDIDATE) -> dict:
    """A structurally complete binding, so a control that means to attack one
    field is not passing because the whole document was malformed."""
    block = t0 or t0_stub()
    return {
        "kind": eb.BINDING_SCHEMA, "schema": 1,
        "t0": block,
        "instrument": {"accepted_commit": "a" * 40, "harness_digest": "d" * 64},
        "workloads": {"path": eb.WORKLOAD_MANIFEST, "manifest_sha256": "9" * 64},
        "linux": {"qualification_sha256": linux_qual_sha, "environment_id": "env-1",
                  "host_fingerprint": "sha256:abc",
                  "environment_identity_sha256": hq.canonical_sha256(manifest()["identity"]),
                  "candidate_sha256": hq.sha256_bytes(linux_candidate),
                  "candidate_bytes": len(linux_candidate),
                  "memory_metric": hq.STRATUM_METRIC["linux"]},
        "windows": {"qualification_sha256": windows_qual_sha, "environment_id": "env-2",
                    "host_fingerprint": "sha256:def",
                    "environment_identity_sha256": "e" * 64,
                    "candidate_sha256": hq.sha256_bytes(windows_candidate),
                    "candidate_bytes": len(windows_candidate),
                    "memory_metric": hq.STRATUM_METRIC["windows"]},
        "bound_at": "2026-09-16T00:00:00+00:00",
    }


def write(tmp: Path, name: str, doc: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def steady(n: int = hq.QUIESCE_INTERVALS):
    series = iter([(0, 0)] + [(i, i * 100) for i in range(1, n + 1)])
    return lambda: next(series, None)


def campaign_fixture(tmp: Path, binding_sha: str, *, tamper: bool = False,
                     other_binding: bool = False):
    """A repo carrying a D7 payload and attestation, and a link that joins them."""
    # Distinct campaigns must be distinct documents: identical content committed
    # inside the same second yields the same commit sha, and the fixture would
    # then be proving only that a link equals itself.
    tag = f"camp{len(list(tmp.glob('camp*')))}"
    repo = tmp / tag
    commit = git_repo(repo, {"docs/evidence/d7-payload.json":
                             '{"kind": "d7", "campaign": "' + tag + '"}\n',
                             "docs/evidence/d7-attestation.json": '{"kind": "att"}\n'},
                      "freeze")
    payload = repo / "docs/evidence/d7-payload.json"
    attestation = repo / "docs/evidence/d7-attestation.json"
    blob = subprocess.run(["git", "-C", str(repo), "rev-parse",
                           commit + ":docs/evidence/d7-payload.json"],
                          capture_output=True, text=True, check=True).stdout.strip()
    link = {"kind": hq.CAMPAIGN_LINK_SCHEMA, "schema": 1,
            "execution_binding_sha256": "f" * 64 if other_binding else binding_sha,
            "d7_payload": {"path": "docs/evidence/d7-payload.json",
                           "sha256": hq.sha256_file(payload), "blob_sha": blob,
                           "commit": commit},
            "d7_attestation": {"path": "docs/evidence/d7-attestation.json",
                               "sha256": hq.sha256_file(attestation)},
            "recorded_at": "2026-09-17T00:00:00+00:00"}
    if tamper:                 # the freeze moved after the campaign was linked to it
        payload.write_text('{"kind": "d7", "edited": true}\n', encoding="utf-8")
    return repo, link


def session_fixture(tmp: Path, *, fresh: dict | None = None,
                    candidate: bytes = LINUX_CANDIDATE, qual: dict | None = None,
                    tamper_freeze: bool = False, other_campaign: bool = False):
    qpath = write(tmp, "q.json", qual or qualification())
    wpath = write(tmp, "qw.json", qualification("windows"))
    bpath = write(tmp, "b.json", binding_doc(hq.sha256_file(qpath), hq.sha256_file(wpath)))
    mpath = write(tmp, "m.json", fresh or manifest())
    dpath = write(tmp, "d.json", declaration())
    cpath = tmp / "cand.bin"
    cpath.write_bytes(candidate)
    quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}
    repo, link = campaign_fixture(tmp, hq.sha256_file(bpath), tamper=tamper_freeze,
                                  other_binding=other_campaign)
    lpath = write(tmp, "link.json", link)
    with fixed_power(COMPLIANT_POWER):
        record = hq.session_eligibility(bpath, qpath, mpath, dpath, cpath, lpath, repo,
                                        quiesce_result=quiet)
    return record, (bpath, qpath, mpath, dpath, cpath, lpath, repo)


# --- vocabulary, producer schema and the boundary ---------------------------


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


def control_producer_schema() -> None:
    """The duplicated constant is allowed; drifting from the producer is not."""
    if hq.ENVCAPTURE_SCHEMA != ec.SCHEMA:
        fail("hostqual-producer-schema",
             f"hostqual expects {hq.ENVCAPTURE_SCHEMA!r}, the capture tool emits {ec.SCHEMA!r}; "
             "every real manifest would be refused, or worse, a stale one accepted")
        return
    ok("hostqual-producer-schema",
       f"{hq.ENVCAPTURE_SCHEMA!r} is exactly what envcapture emits, so decoupling the tools "
       "did not decouple their agreement")


def control_artifact_boundary() -> None:
    """Every consumed artifact is proved to BE that artifact before it is read."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        good_q = write(tmp, "q.json", qualification())
        good_w = write(tmp, "qw.json", qualification("windows"))
        good_b = write(tmp, "b.json", binding_doc(hq.sha256_file(good_q),
                                                  hq.sha256_file(good_w)))
        good_m = write(tmp, "m.json", manifest())
        good_d = write(tmp, "d.json", declaration())
        cand = tmp / "c.bin"
        cand.write_bytes(LINUX_CANDIDATE)
        quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}
        crepo, link_doc = campaign_fixture(tmp, hq.sha256_file(good_b))
        good_link = write(tmp, "link.json", link_doc)

        attacks = [
            ("fake execution-binding kind",
             write(tmp, "b-kind.json", {**binding_doc(hq.sha256_file(good_q),
                                                      hq.sha256_file(good_w)),
                                        "kind": "NOT A BINDING AT ALL"}), "binding"),
            ("wrong execution-binding schema",
             write(tmp, "b-schema.json", {**binding_doc(hq.sha256_file(good_q),
                                                        hq.sha256_file(good_w)),
                                          "schema": 99}), "binding"),
            ("fake envcapture schema",
             write(tmp, "m-kind.json", manifest(schema="totally-made-up")), "manifest"),
            ("missing envcapture schema",
             write(tmp, "m-none.json", {k: v for k, v in manifest().items() if k != "schema"}),
             "manifest"),
            ("handwritten identity/provenance only",
             write(tmp, "m-hand.json", {"identity": manifest()["identity"],
                                        "provenance": {"ci": False}}), "manifest"),
            ("fake qualification kind",
             write(tmp, "q-kind.json", {**qualification(), "kind": "something else"}), "qual"),
            ("wrong qualification schema",
             write(tmp, "q-schema.json", {**qualification(), "schema": 7}), "qual"),
        ]
        for label, path, slot in attacks:
            binding = path if slot == "binding" else good_b
            qual = path if slot == "qual" else good_q
            fresh = path if slot == "manifest" else good_m
            with fixed_power(COMPLIANT_POWER):
                message = refuses(lambda: hq.session_eligibility(
                    binding, qual, fresh, good_d, cand, good_link, crepo,
                    quiesce_result=quiet))
            if message is None:
                fail("hostqual-artifact-boundary", f"{label} was consumed as a real artifact")
                return

        # The old hole, reproduced exactly: a handwritten binding-like JSON plus a
        # handwritten identity/provenance JSON must not produce an eligible session.
        forged_b = write(tmp, "forged.json", {"kind": "NOT A BINDING AT ALL",
                                              "linux": {"qualification_sha256":
                                                        hq.sha256_file(good_q),
                                                        "memory_metric":
                                                        hq.STRATUM_METRIC["linux"],
                                                        "candidate_sha256":
                                                        hq.sha256_bytes(LINUX_CANDIDATE),
                                                        "candidate_bytes": len(LINUX_CANDIDATE)}})
        forged_m = write(tmp, "forged-m.json", {"identity": manifest()["identity"],
                                                "provenance": {"ci": False}})
        with fixed_power(COMPLIANT_POWER):
            message = refuses(lambda: hq.session_eligibility(forged_b, good_q, forged_m, good_d,
                                                             cand, good_link, crepo,
                                                             quiesce_result=quiet))
        if message is None:
            fail("hostqual-artifact-boundary",
                 "the original hole is open: a handwritten binding and a handwritten manifest "
                 "produced a session")
            return

        # Postflight refuses a preflight record that is not one.
        pre, _ = session_fixture(tmp)
        bad_pre = write(tmp, "pre-kind.json", {**pre, "kind": "not a preflight"})
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        with fixed_power(COMPLIANT_POWER):
            message = refuses(lambda: hq.session_admissibility(good_b, good_q, bad_pre, good_m,
                                                               cand, probe, good_link, crepo))
        if message is None:
            fail("hostqual-artifact-boundary", "a fake preflight record was consumed")
            return
    ok("hostqual-artifact-boundary",
       "binding, qualification, manifest and preflight are each proved by kind and schema before "
       "a single field is read, and the original handwritten-JSON hole is closed")


def control_t0_versioned() -> None:
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
        if hq.bind_t0(repo, "t0.md", "0" * 40)[1]["result"] != "fail":
            fail("hostqual-t0-versioned", "a nonexistent commit was accepted")
            return
        if hq.bind_t0(repo, "nope.md", frozen_commit)[1]["result"] != "fail":
            fail("hostqual-t0-versioned", "a path absent at that commit was accepted")
            return
    ok("hostqual-t0-versioned",
       "the commit must exist, the path must exist at it, the bytes are hashed from the blob, "
       "and NOT_FROZEN refuses: reconnaissance cannot become qualification by reuse")


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


def control_provisioning_shape() -> None:
    """Malformed is malformed; `false` is not malformed."""
    for label, doc in (("a physical-host declaration", provisioning()),
                       ("a VM declaration", vm_provisioning()),
                       ("an honest negative", provisioning(dedicated_to_p022=False)),
                       ("an honest VM negative", vm_provisioning(fixed_vcpu=False))):
        if hq.validate_provisioning(doc):
            fail("hostqual-provisioning-shape",
                 f"{label} was refused as malformed: {hq.validate_provisioning(doc)}")
            return
    malformed = [
        ('the string "false" where a boolean belongs', provisioning(dedicated_to_p022="false")),
        ("a missing required boolean",
         {k: v for k, v in provisioning().items() if k != "dedicated_to_p022"}),
        ("is_vm answered with n/a", provisioning(virtualization={"is_vm": "n/a: unclear"})),
        ("a VM leaving a VM-only field out",
         provisioning(virtualization={"is_vm": True, "fixed_vcpu": True, "fixed_ram": True,
                                      "live_migration_disabled": True})),
        ("a VM answering a VM-only field with n/a", vm_provisioning(fixed_vcpu="n/a: do not ask")),
    ]
    physical_bare = provisioning()
    physical_bare["virtualization"]["fixed_vcpu"] = True
    malformed.append(("a physical host answering VM questions with bare booleans", physical_bare))
    for label, doc in malformed:
        if not hq.validate_provisioning(doc):
            fail("hostqual-provisioning-shape", f"{label} was accepted as a valid artifact")
            return
    ok("hostqual-provisioning-shape",
       "wrong types, missing keys and inapplicable answers are malformed; a boolean `false` is "
       "not, because a declaration that this host does not qualify is still a declaration")


def control_provisioning_predicate() -> None:
    if hq.provisioning_predicate(provisioning()) or hq.provisioning_predicate(vm_provisioning()):
        fail("hostqual-provisioning-predicate", "a compliant declaration failed the predicate")
        return
    for label, doc in (("dedicated_to_p022 false", provisioning(dedicated_to_p022=False)),
                       ("no_concurrent_user_workload false",
                        provisioning(no_concurrent_user_workload=False)),
                       ("hosted_ci_runner true", provisioning(hosted_ci_runner=True)),
                       ("VM fixed_vcpu false", vm_provisioning(fixed_vcpu=False)),
                       ("VM fixed_ram false", vm_provisioning(fixed_ram=False)),
                       ("VM live_migration_disabled false",
                        vm_provisioning(live_migration_disabled=False)),
                       ("VM dynamic_memory_disabled false",
                        vm_provisioning(dynamic_memory_disabled=False))):
        if not hq.provisioning_predicate(doc):
            fail("hostqual-provisioning-predicate", f"{label} satisfied the predicate")
            return
        if hq.check_single_tenant(doc, manifest())["result"] != "fail":
            fail("hostqual-provisioning-predicate", f"{label} still qualified the host")
            return
    if hq.declaration_predicate(declaration()):
        fail("hostqual-provisioning-predicate", "a compliant session declaration failed")
        return
    for key in hq.DECLARATION_REQUIRED_TRUE:
        if not hq.declaration_predicate(declaration(**{key: False})):
            fail("hostqual-provisioning-predicate", f"session declaration {key} false passed")
            return
    ok("hostqual-provisioning-predicate",
       "every required value is judged by the predicate rather than by the parser, so each "
       "failure can reach a record instead of a stream of errors")


def control_one_environment_id() -> None:
    if hq.check_single_tenant(provisioning(environment_id="env-other"),
                              manifest())["result"] != "fail":
        fail("hostqual-one-environment-id",
             "a declaration naming another environment qualified this one")
        return
    if hq.check_single_tenant(provisioning(), manifest())["result"] != "pass":
        fail("hostqual-one-environment-id", "agreeing identities were refused")
        return
    source = (ROOT / "scripts" / "step7" / "hostqual.py").read_text(encoding="utf-8")
    if "--environment-id" in source:
        fail("hostqual-one-environment-id", "the tool still accepts an independent id argument")
        return
    ok("hostqual-one-environment-id",
       "the id is the manifest's observed value and the declaration must agree with it")


def control_quiesce_window() -> None:
    slept: list[float] = []
    hq.quiesce(sleep=slept.append, counters=steady())
    if not slept or slept[0] != hq.QUIESCE_QUIET_S:
        fail("hostqual-quiesce-window", f"the quiet period was {slept[:1]}")
        return
    if sum(slept) != hq.QUIESCE_WINDOW_S:
        fail("hostqual-quiesce-window", f"the window lasted {sum(slept)}s")
        return
    if sum(slept[1:]) != hq.QUIESCE_INTERVAL_S * hq.QUIESCE_INTERVALS:
        fail("hostqual-quiesce-window", f"the measured part lasted {sum(slept[1:])}s")
        return
    ok("hostqual-quiesce-window",
       f"{hq.QUIESCE_QUIET_S}s waited quietly, then {hq.QUIESCE_INTERVALS} x "
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


def control_identity_projection() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        good, _ = session_fixture(tmp)
        if not good["eligible"]:
            fail("hostqual-identity-projection", f"a clean session was refused: {good['reasons']}")
            return
        drifted, _ = session_fixture(tmp, fresh=manifest(kernel="6.2.0"))
        if drifted["eligible"]:
            fail("hostqual-identity-projection", "a manifest whose kernel changed preflighted")
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
        swapped, _ = session_fixture(tmp, candidate=b"a different executable")
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
        pre, (bpath, qpath, mpath, dpath, cpath, lpath, crepo) = session_fixture(tmp)
        ppath = write(tmp, "pre.json", pre)
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        with fixed_power(COMPLIANT_POWER):
            clean = hq.session_admissibility(bpath, qpath, ppath, mpath, cpath, probe, lpath, crepo)
            if not clean["admissible"]:
                fail("hostqual-postflight", f"a clean attempt was refused: {clean['reasons']}")
                return
            moved = write(tmp, "after.json", manifest(kernel="6.9.9"))
            if hq.session_admissibility(bpath, qpath, ppath, moved, cpath,
                                        probe, lpath, crepo)["admissible"]:
                fail("hostqual-postflight", "an environment that changed mid-session passed")
                return
            other = tmp / "other.bin"
            other.write_bytes(b"rebuilt candidate")
            if hq.session_admissibility(bpath, qpath, ppath, mpath, other,
                                        probe, lpath, crepo)["admissible"]:
                fail("hostqual-postflight", "a candidate rebuilt mid-session passed")
                return
            if hq.session_admissibility(bpath, qpath, ppath, mpath, cpath,
                                        tmp / "absent.json", lpath, crepo)["admissible"]:
                fail("hostqual-postflight", "an attempt with no closing probe passed")
                return
        with fixed_power({**COMPLIANT_POWER, "processor_max_ac": 50}):
            if hq.session_admissibility(bpath, qpath, ppath, mpath, cpath,
                                        probe, lpath, crepo)["admissible"]:
                fail("hostqual-postflight", "power that changed during the session passed")
                return
    ok("hostqual-postflight",
       "a separate post-session pass catches identity drift, candidate drift, power drift and a "
       "missing closing probe; preflight may not certify what a session did after it started")


def control_one_binding() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        pre, (bpath, qpath, mpath, dpath, cpath, lpath, crepo) = session_fixture(tmp)
        ppath = write(tmp, "pre.json", pre)
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        original = json.loads(bpath.read_text(encoding="utf-8"))
        second = write(tmp, "b2.json", {**original, "bound_at": "a later moment"})
        with fixed_power(COMPLIANT_POWER):
            mixed = hq.session_admissibility(second, qpath, ppath, mpath, cpath, probe, lpath, crepo)
        if mixed["admissible"]:
            fail("hostqual-one-binding",
                 "a preflight from one binding and a postflight from another were admissible")
            return
    ok("hostqual-one-binding",
       "two execution_binding_sha256 values cannot meet inside one session record")


def control_power_ac_and_dc() -> None:
    if hq.check_power_policy(COMPLIANT_POWER)["result"] != "pass":
        fail("hostqual-power-ac-and-dc", "a fully compliant snapshot was refused")
        return
    for label, patch in (("DC minimum below 100", {"processor_min_dc": 5}),
                         ("DC maximum below 100", {"processor_max_dc": 50}),
                         ("AC minimum below 100", {"processor_min_ac": 5}),
                         ("an unaccepted plan",
                          {"plan_guid": "381b4222-f694-41f0-9685-ff5bb260df2e"})):
        if hq.check_power_policy({**COMPLIANT_POWER, **patch})["result"] != "fail":
            fail("hostqual-power-ac-and-dc", f"{label} was accepted")
            return
    linux_ok = {"platform": "linux", "governors": {"cpu0": "performance", "cpu1": "performance"},
                "boost": {"mechanism": "cpufreq/boost", "value": "1"}}
    if hq.check_power_policy(linux_ok)["result"] != "pass":
        fail("hostqual-power-ac-and-dc", "a compliant Linux snapshot was refused")
        return
    if hq.check_power_policy({**linux_ok,
                              "governors": {"cpu0": "performance",
                                            "cpu1": "powersave"}})["result"] != "fail":
        fail("hostqual-power-ac-and-dc", "one CPU on powersave was accepted")
        return
    if hq.check_power_policy({**linux_ok,
                              "boost": {"mechanism": None, "value": None}})["result"] != "fail":
        fail("hostqual-power-ac-and-dc", "a host with no identifiable turbo mechanism passed")
        return
    ok("hostqual-power-ac-and-dc",
       "Windows needs 100% on AC *and* DC and an accepted plan; Linux needs performance on every "
       "CPU and a turbo mechanism that can be named and rechecked")


# --- the binding -------------------------------------------------------------


def instrument_repo(tmp: Path) -> tuple[Path, str, str, str]:
    repo = tmp / "repo"
    commit = git_repo(repo, {"t0.md": T0_FROZEN,
                             eb.INSTRUMENT_SOURCES[0]: "print('instrument')\n",
                             eb.INSTRUMENT_SOURCES[1]: '{"decisive": []}\n'})
    return repo, commit, eb.harness_digest_at(repo, commit) or "", "t0.md"


def control_execbinding_proves_inputs() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = instrument_repo(tmp)
        t0 = eb.t0_at(repo, t0_path, commit)
        lin = write(tmp, "ql.json", qualification("linux", t0=t0))
        win = write(tmp, "qw.json", qualification("windows", t0=t0))
        cand_l, cand_w = tmp / "cl", tmp / "cw"
        cand_l.write_bytes(LINUX_CANDIDATE)
        cand_w.write_bytes(WINDOWS_CANDIDATE)

        binding = eb.build(repo, t0_path, commit, commit, digest,
                           {"linux": (lin, cand_l), "windows": (win, cand_w)})
        if eb.validate(binding):
            fail("execbinding-proves-inputs", f"a good binding was refused: {eb.validate(binding)}")
            return
        if any(word in json.dumps(binding)
               for word in ("governor", "power_snapshot", "predicate_detail")):
            fail("execbinding-proves-inputs", "the binding copies qualification detail")
            return
        try:
            eb.build(repo, t0_path, commit, commit, "0" * 64,
                     {"linux": (lin, cand_l), "windows": (win, cand_w)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-proves-inputs", "a digest the sources do not produce was accepted")
            return
        wrong_schema = write(tmp, "qbad.json", {**qualification("windows", t0=t0), "schema": 9})
        try:
            eb.build(repo, t0_path, commit, commit, digest,
                     {"linux": (lin, cand_l), "windows": (wrong_schema, cand_w)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-proves-inputs", "a qualification with the wrong schema was bound")
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
       "frozen formula, the manifest comes from that commit's git object, and a wrong-schema "
       "qualification or a NOT_FROZEN T0 cannot be bound")


def control_execbinding_old_t0() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = instrument_repo(tmp)
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
            fail("execbinding-old-t0", "a host qualified under an earlier T0 entered a campaign")
            return
    ok("execbinding-old-t0",
       "a qualification earned under one protocol is not evidence under another")


def control_execbinding_verify_campaign() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = instrument_repo(tmp)
        t0 = eb.t0_at(repo, t0_path, commit)
        lin = write(tmp, "ql.json", qualification("linux", t0=t0))
        win = write(tmp, "qw.json", qualification("windows", t0=t0))
        cand_l, cand_w = tmp / "cl", tmp / "cw"
        cand_l.write_bytes(LINUX_CANDIDATE)
        cand_w.write_bytes(WINDOWS_CANDIDATE)
        bpath = write(tmp, "binding.json",
                      eb.build(repo, t0_path, commit, commit, digest,
                               {"linux": (lin, cand_l), "windows": (win, cand_w)}))
        quals = {"linux": lin, "windows": win}
        cands = {"linux": cand_l, "windows": cand_w}
        if eb.verify(repo, bpath, quals, cands):
            fail("execbinding-verify-campaign",
                 f"a clean campaign failed: {eb.verify(repo, bpath, quals, cands)}")
            return

        cand_w.write_bytes(b"a replacement binary")
        if not any("candidate" in p for p in eb.verify(repo, bpath, quals, cands)):
            fail("execbinding-verify-campaign", "a replaced candidate was not caught")
            return
        cand_w.write_bytes(WINDOWS_CANDIDATE)

        write(tmp, "qw.json", qualification("windows", t0=t0, qualified_at="changed"))
        if not any("qualification" in p for p in eb.verify(repo, bpath, quals, cands)):
            fail("execbinding-verify-campaign", "a changed qualification was not caught")
            return
        write(tmp, "qw.json", qualification("windows", t0=t0))

        moved = json.loads(bpath.read_text(encoding="utf-8"))
        moved["workloads"]["manifest_sha256"] = "9" * 64
        if not any("workloads" in p
                   for p in eb.verify(repo, write(tmp, "moved.json", moved), quals, cands)):
            fail("execbinding-verify-campaign", "a changed workload manifest was not caught")
            return
        retimed = json.loads(bpath.read_text(encoding="utf-8"))
        retimed["t0"]["sha256"] = "7" * 64
        if not any("T0" in p
                   for p in eb.verify(repo, write(tmp, "retimed.json", retimed), quals, cands)):
            fail("execbinding-verify-campaign", "a changed T0 was not caught")
            return
    ok("execbinding-verify-campaign",
       "the verifier re-proves T0, instrument digest, workload manifest, both qualifications "
       "and both candidates")


def control_execbinding_verify_is_total() -> None:
    """No partial mode under this name, in the API or at the command line."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, digest, t0_path = instrument_repo(tmp)
        t0 = eb.t0_at(repo, t0_path, commit)
        lin = write(tmp, "ql.json", qualification("linux", t0=t0))
        win = write(tmp, "qw.json", qualification("windows", t0=t0))
        cand_l, cand_w = tmp / "cl", tmp / "cw"
        cand_l.write_bytes(LINUX_CANDIDATE)
        cand_w.write_bytes(WINDOWS_CANDIDATE)
        bpath = write(tmp, "binding.json",
                      eb.build(repo, t0_path, commit, commit, digest,
                               {"linux": (lin, cand_l), "windows": (win, cand_w)}))

        partial_calls = [
            ("no inputs at all", {}, {}),
            ("only Linux inputs", {"linux": lin}, {"linux": cand_l}),
            ("both qualifications, one candidate", {"linux": lin, "windows": win},
             {"linux": cand_l}),
        ]
        for label, quals, cands in partial_calls:
            problems = eb.verify(repo, bpath, quals, cands)
            if not problems:
                fail("execbinding-verify-is-total", f"{label} verified clean")
                return
            if not any("full verification requires" in p for p in problems):
                fail("execbinding-verify-is-total",
                     f"{label} produced findings instead of a refusal: {problems}")
                return

        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = eb.main(["--verify", str(bpath), "--repo", str(repo), "--linux", str(lin)])
            except SystemExit as exc:      # argparse refuses before running anything
                rc = int(exc.code or 0)
        if rc == 0 or "binding verified" in out.getvalue():
            fail("execbinding-verify-is-total",
                 "the command line accepted an incomplete verify")
            return
    ok("execbinding-verify-is-total",
       "an incomplete verify is refused by the function and by the command line; the string "
       "'binding verified' cannot be produced over a skipped component")


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


# --- the template and this file itself ---------------------------------------


def control_negative_evidence() -> None:
    """A refused host leaves a record saying so. Erasing negative attempts is how
    a laboratory ends up with machines that pass on the first try because the
    other tries were never artifacts."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit, _digest, t0_path = instrument_repo(tmp)
        mpath = write(tmp, "m.json", manifest())

        def qualify_cli(name: str, prov: dict) -> tuple[int, Path]:
            ppath = write(tmp, f"{name}-p.json", prov)
            out = tmp / f"{name}-q.json"
            with fixed_power(COMPLIANT_POWER):
                rc = hq.main(["--qualify", "--stratum", "linux", "--repo", str(repo),
                              "--t0-path", t0_path, "--t0-commit", commit,
                              "--provisioning", str(ppath), "--manifest", str(mpath),
                              "--emit", str(out)])
            return rc, out

        # N1 and N2: honest provisioning negatives
        for label, prov, expect_key in (
                ("n1", provisioning(dedicated_to_p022=False), "single_tenant"),
                ("n1b", provisioning(no_concurrent_user_workload=False), "single_tenant"),
                ("n2", vm_provisioning(fixed_vcpu=False), "single_tenant")):
            rc, out = qualify_cli(label, prov)
            if not out.is_file():
                fail("hostqual-negative-evidence",
                     f"{label}: a valid negative declaration produced no artifact at all")
                return
            record = json.loads(out.read_text(encoding="utf-8"))
            if record.get("qualified") is not False:
                fail("hostqual-negative-evidence", f"{label}: the record does not say qualified "
                     f"false: {record.get('qualified')!r}")
                return
            if record.get("predicate", {}).get(expect_key) != "fail":
                fail("hostqual-negative-evidence",
                     f"{label}: {expect_key} is {record.get('predicate', {}).get(expect_key)!r}, "
                     "so the record does not say WHY")
                return
            if rc != 1:
                fail("hostqual-negative-evidence",
                     f"{label}: exit code {rc}; a valid artifact with a negative outcome is 1")
                return

        # N4 and N5: malformed input produces no artifact and a different code
        rc, out = qualify_cli("n4", provisioning(dedicated_to_p022="false"))
        if out.is_file():
            fail("hostqual-negative-evidence", "a malformed declaration produced an artifact")
            return
        if rc != 2:
            fail("hostqual-negative-evidence",
                 f"a malformed declaration exited {rc}; malformed input is 2, not 1")
            return

        # N3: an honest session negative still records eligibility
        qpath = write(tmp, "q.json", qualification())
        wpath = write(tmp, "qw.json", qualification("windows"))
        bpath = write(tmp, "b.json", binding_doc(hq.sha256_file(qpath), hq.sha256_file(wpath)))
        dpath = write(tmp, "d.json", declaration(no_prohibited_background_job_active=False))
        cpath = tmp / "cand.bin"
        cpath.write_bytes(LINUX_CANDIDATE)
        quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}
        crepo, link_doc = campaign_fixture(tmp, hq.sha256_file(bpath))
        lpath = write(tmp, "link.json", link_doc)
        with fixed_power(COMPLIANT_POWER):
            record = hq.session_eligibility(bpath, qpath, mpath, dpath, cpath, lpath, crepo,
                                            quiesce_result=quiet)
        if record["eligible"]:
            fail("hostqual-negative-evidence", "a declared prohibited job left the session eligible")
            return
        if not any("declaration" in r for r in record["reasons"]):
            fail("hostqual-negative-evidence",
                 f"the eligibility record does not say why: {record['reasons']}")
            return
        malformed_d = write(tmp, "d-bad.json", declaration(no_campaign_workload="false"))
        with fixed_power(COMPLIANT_POWER):
            message = refuses(lambda: hq.session_eligibility(bpath, qpath, mpath, malformed_d,
                                                             cpath, lpath, crepo,
                                                             quiesce_result=quiet))
        if message is None:
            fail("hostqual-negative-evidence", "a malformed session declaration was consumed")
            return
    ok("hostqual-negative-evidence",
       "an honest negative — host, VM or session — leaves a real artifact saying qualified/"
       "eligible false and naming the reason, and exits 1; malformed input leaves nothing and "
       "exits 2. The two classes never share a code")


def control_campaign_link() -> None:
    """The join the D7 payload cannot make for itself, verified by bytes.

    `D7_PAYLOAD_BINDING_KEYS` carries no execution binding and the gate tolerates
    an unverified extra key, so without this the campaign and the freeze are two
    documents that merely hope they are about each other.
    """
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        clean, _ = session_fixture(tmp)
        if not clean["eligible"] or clean["campaign_link"]["result"] != "pass":
            fail("hostqual-campaign-link", f"a joined session was refused: {clean['reasons']}")
            return
        elsewhere, _ = session_fixture(tmp, other_campaign=True)
        if elsewhere["eligible"] or not any("another campaign" in r for r in elsewhere["reasons"]):
            fail("hostqual-campaign-link",
                 "a link naming a different execution binding was accepted")
            return
        moved, _ = session_fixture(tmp, tamper_freeze=True)
        if moved["eligible"] or not any("freeze changed" in r for r in moved["reasons"]):
            fail("hostqual-campaign-link",
                 "a D7 payload edited after the campaign was linked to it was accepted")
            return

        pre, (bpath, qpath, mpath, dpath, cpath, lpath, crepo) = session_fixture(tmp)
        ppath = write(tmp, "pre.json", pre)
        probe = tmp / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        other_repo, other_link = campaign_fixture(tmp, hq.sha256_file(bpath))
        olpath = write(tmp, "link2.json", other_link)
        with fixed_power(COMPLIANT_POWER):
            swapped = hq.session_admissibility(bpath, qpath, ppath, mpath, cpath, probe,
                                               olpath, other_repo)
        if swapped["admissible"]:
            fail("hostqual-campaign-link",
                 "an attempt changed which campaign it belonged to between preflight and "
                 "postflight")
            return
    ok("hostqual-campaign-link",
       "preflight and postflight re-prove the link by bytes: a link naming another binding, a "
       "freeze edited afterwards, and a campaign swapped mid-session each refuse")


def control_authority_states() -> None:
    """Four states, three refusals, on both paths that read T0."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo = tmp / "repo"
        states = {}
        for name, text in (("frozen_authorized", T0_FROZEN),
                           ("frozen_unauthorized", T0_FROZEN_UNAUTHORIZED),
                           ("open_unauthorized", T0_OPEN),
                           ("open_authorized", T0_OPEN_AUTHORIZED)):
            states[name] = git_repo(repo, {"t0.md": text}, name)
        expected = {"frozen_authorized": "pass", "frozen_unauthorized": "fail",
                    "open_unauthorized": "fail", "open_authorized": "fail"}
        for name, commit in states.items():
            got = hq.bind_t0(repo, "t0.md", commit)[1]["result"]
            if got != expected[name]:
                fail("hostqual-authority-states",
                     f"qualification path: {name} gave {got}, expected {expected[name]}")
                return
            refused = True
            try:
                eb.t0_at(repo, "t0.md", commit)
                refused = False
            except eb.BindingRefused:
                pass
            if refused == (expected[name] == "pass"):
                fail("hostqual-authority-states",
                     f"binding path: {name} was {'refused' if refused else 'accepted'}, "
                     f"expected {expected[name]}")
                return
    ok("hostqual-authority-states",
       "FROZEN+true proceeds; FROZEN+false, NOT_FROZEN+false and NOT_FROZEN+true each refuse, "
       "on the qualification path and on the binding path alike")


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


def control_inventory_complete() -> None:
    """The docstring inventory and the executed set are the same set.

    This class of defect has now been found twice — a list of controls that
    quietly stopped matching the controls. A control is cheaper than finding it a
    third time.
    """
    listed = set(re.findall(r"^    ([a-z0-9-]+) +\S", __doc__ or "", re.MULTILINE))
    executed = {name for name, _ in CONTROLS}
    if listed != executed:
        fail("control-inventory-complete",
             f"listed but not executed: {sorted(listed - executed)}; executed but not listed: "
             f"{sorted(executed - listed)}")
        return
    ok("control-inventory-complete",
       f"{len(executed)} controls listed, {len(executed)} executed, same names in both")


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
       "neither tool imports the instrument or the capture tool; the digest is recomputed from "
       "git objects and the producer's schema is held by a control instead of an import")


CONTROLS: list[tuple[str, Callable[[], None]]] = [
    ("hostqual-memory-vocabulary", control_memory_vocabulary),
    ("hostqual-producer-schema", control_producer_schema),
    ("hostqual-artifact-boundary", control_artifact_boundary),
    ("hostqual-t0-versioned", control_t0_versioned),
    ("hostqual-ci-predicate", control_ci_predicate),
    ("hostqual-provisioning-shape", control_provisioning_shape),
    ("hostqual-provisioning-predicate", control_provisioning_predicate),
    ("hostqual-negative-evidence", control_negative_evidence),
    ("hostqual-one-environment-id", control_one_environment_id),
    ("hostqual-quiesce-window", control_quiesce_window),
    ("hostqual-quiesce-arithmetic", control_quiesce_arithmetic),
    ("hostqual-identity-projection", control_identity_projection),
    ("hostqual-candidate-at-start", control_candidate_at_start),
    ("hostqual-postflight", control_postflight),
    ("hostqual-one-binding", control_one_binding),
    ("hostqual-power-ac-and-dc", control_power_ac_and_dc),
    ("execbinding-proves-inputs", control_execbinding_proves_inputs),
    ("execbinding-old-t0", control_execbinding_old_t0),
    ("execbinding-verify-campaign", control_execbinding_verify_campaign),
    ("execbinding-verify-is-total", control_execbinding_verify_is_total),
    ("execbinding-no-overwrite", control_execbinding_no_overwrite),
    ("hostqual-campaign-link", control_campaign_link),
    ("hostqual-authority-states", control_authority_states),
    ("provisioning-example-validates", control_provisioning_example),
    ("control-inventory-complete", control_inventory_complete),
    ("tools-do-not-import-harness", control_tools_do_not_import_harness),
]


def run() -> int:
    for name, control in CONTROLS:
        guarded(name, control)
    print()
    print(f"step 7 host qualification controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
