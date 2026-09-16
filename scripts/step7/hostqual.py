#!/usr/bin/env python3
"""P-022 / #263 — step 7: host qualification, session eligibility, admissibility.

Three questions, three artifacts, never merged:

  QUALIFICATION  does this environment satisfy the host predicate of a NAMED,
                 FROZEN T0? A qualification that floats free of T0 says only
                 "this host passed some predicate once", which is a content-
                 addressed chain with the causation removed from the middle.
  ELIGIBILITY    is this session, on that qualified host, able to start NOW?
  ADMISSIBILITY  did the attempt that ran remain the one that was authorised?

This tool does NOT own the execution binding — that is `execbinding.py`. A
utility that checks a CPU governor must not become the root of campaign
identity.

Artifact validity is not predicate outcome, and the exit codes say which is
which:

    0   a valid artifact, and the answer is yes
    1   a valid artifact, and the answer is no — the record EXISTS and says so
    2   a malformed input or an operational misuse; no record is produced

A declaration of `false` is evidence, not damage. Only a document that is not the
artifact it claims to be — wrong kind, wrong schema, a missing key, the string
"false" where a boolean belongs — is refused before a record exists.

Two classes of evidence, kept apart because only one of them is proof:

  DECLARED         provisioning and per-session operator facts. A guest OS
                   cannot establish them. Content-addressed, shape- and
                   value-checked, and never called machine proof.
  MACHINE-OBSERVED what a checker asserts here and now.

Usage:
    hostqual.py --qualify --stratum linux --t0-path <p> --t0-commit <sha> \\
        --provisioning <p.json> --manifest <m.json> --emit <q.json>
    hostqual.py --session-preflight --binding <b.json> --qualification <q.json> \\
        --manifest <fresh.json> --declaration <d.json> --candidate <bin> \\
        --campaign-link <link.json> --emit <e.json>
    hostqual.py --session-postflight --binding <b.json> --qualification <q.json> \\
        --preflight <e.json> --manifest <after.json> --candidate <bin> \\
        --closing-probe <probe.json> --campaign-link <link.json> --emit <a.json>
    hostqual.py --selftest
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

import execbinding as eb  # sibling tool: one validator per artifact type, not five call sites

QUALIFICATION_SCHEMA = "own.net/p022/host-qualification"
ELIGIBILITY_SCHEMA = "own.net/p022/session-eligibility"
ADMISSIBILITY_SCHEMA = "own.net/p022/session-admissibility"
PROVISIONING_SCHEMA = "own.net/p022/host-provisioning"
DECLARATION_SCHEMA = "own.net/p022/session-declaration"
# The producer's own schema string, duplicated rather than imported so this tool
# stays independent of the capture tool. `hostqual-producer-schema` proves the
# copy still equals what envcapture emits, so the decoupling cannot rot quietly.
ENVCAPTURE_SCHEMA = "p022-263a-step7-environment-identity"
# The join the accepted D7 payload cannot make for itself: its binding keys are
# python_reference_commit, python_reference_tree, harness_digest, harness_version
# and workload_manifest_sha256 — no execution binding among them, and the gate
# tolerates an extra key without ever verifying it. This artifact ties the
# campaign to the freeze by exact bytes, and the session gates below refuse
# without it, so evidence produced outside a campaign cannot become admissible.
CAMPAIGN_LINK_SCHEMA = "own.net/p022/campaign-link"
SCHEMA_VERSION = 1

# The closed memory vocabulary, declared rather than imported so this tool never
# reaches into the frozen instrument; `hostqual-memory-vocabulary` proves the
# copies agree, so a drift is a test failure and not a mislabelled campaign.
MEMORY_METRIC_RESIDENT = "max_process_peak_resident"
MEMORY_METRIC_COMMIT = "max_process_peak_commit"
STRATUM_METRIC = {"linux": MEMORY_METRIC_RESIDENT, "windows": MEMORY_METRIC_COMMIT}

PREDICATE_KEYS = ("t0", "environment_identity", "ci", "single_tenant", "power_policy",
                  "required_memory_metric")

# Quiesce: 120 s without campaign workload, of which the final 60 s is measured.
QUIESCE_QUIET_S = 60            # unmeasured, but really waited
QUIESCE_INTERVAL_S = 5
QUIESCE_INTERVALS = 12          # 12 x 5 s = the measured final minute
QUIESCE_WINDOW_S = QUIESCE_QUIET_S + QUIESCE_INTERVAL_S * QUIESCE_INTERVALS
QUIESCE_MEAN_MAX = 0.05
QUIESCE_INTERVAL_MAX = 0.20

PROVISIONING_REQUIRED_TRUE = ("dedicated_to_p022", "no_concurrent_user_workload")
PROVISIONING_REQUIRED_FALSE = ("hosted_ci_runner",)
PROVISIONING_VM_BOOLEANS = ("fixed_vcpu", "fixed_ram", "live_migration_disabled",
                            "dynamic_memory_disabled")
PROVISIONING_STRINGS = ("environment_id", "host_fingerprint", "operator", "recorded_at")
DECLARATION_REQUIRED_TRUE = ("no_campaign_workload", "no_interactive_user_workload",
                             "no_prohibited_background_job_active")

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


def canonical_sha256(value: object) -> str:
    """A content-addressed projection of a JSON value.

    Used for the environment identity block: not a second copy of the facts, a
    hash OF the authoritative ones, so a drift anywhere in the set is one
    comparison rather than a list of fields someone has to remember to extend.
    """
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8"))


def _git(repo: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except (OSError, ValueError):
        return 127, b""
    return proc.returncode, proc.stdout


def _console_encoding() -> str:
    """The encoding a console tool's bytes arrive in.

    `text=True` would decode with the locale's ANSI code page while a console
    tool writes in the console output code page; on a non-English Windows the
    two disagree and an identity-bearing value becomes mojibake that moves with
    the ambient code page.
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


# --- the boundary: parse bytes, prove the artifact, then read semantics ------


def validate_manifest(doc: object) -> list[str]:
    """An environment manifest is what the capture tool emitted, not any JSON
    that happens to carry an `identity` key. Inferring a type from the presence
    of two keys is how a hand-written file becomes campaign evidence."""
    if not isinstance(doc, dict):
        return ["the environment manifest is not a JSON object"]
    problems = []
    if doc.get("schema") != ENVCAPTURE_SCHEMA:
        problems.append(f"schema is {doc.get('schema')!r}, not {ENVCAPTURE_SCHEMA!r}")
    if not isinstance(doc.get("identity"), dict) or not doc.get("identity"):
        problems.append("identity is missing or empty")
    provenance = doc.get("provenance")
    if not isinstance(provenance, dict):
        problems.append("provenance is missing")
    elif not isinstance(provenance.get("ci"), bool):
        problems.append("provenance.ci is missing or not a boolean")
    return problems


# One validator, owned by the module that binds campaigns, reused here. Two
# copies of the same rules is how a qualification passes one consumer and fails
# the next.
validate_qualification = eb.validate_qualification


def validate_binding(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["the execution binding is not a JSON object"]
    problems = []
    if doc.get("kind") != eb.BINDING_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {eb.BINDING_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    return problems + eb.validate(doc)


def validate_eligibility(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["the preflight record is not a JSON object"]
    problems = []
    if doc.get("kind") != ELIGIBILITY_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {ELIGIBILITY_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    for key in ("execution_binding_sha256", "qualification_sha256",
                "environment_identity_sha256"):
        if not doc.get(key):
            problems.append(f"{key} is missing")
    if not isinstance(doc.get("power_snapshot"), dict):
        problems.append("power_snapshot is missing")
    if not isinstance(doc.get("eligible"), bool):
        problems.append("eligible is not a boolean")
    return problems


# --- T0: a qualification is versioned by the protocol it claims to satisfy ---


def t0_status(text: str) -> dict[str, object]:
    """FROZEN / NOT_FROZEN and the authorization flag, read from the status block."""
    frozen = re.search(r"^\s*(NOT_FROZEN|FROZEN)\.?\s*$", text, re.MULTILINE)
    authorized = re.search(r"^\s*collection_authorized:\s*(true|false)\s*$", text, re.MULTILINE)
    return {"frozen": bool(frozen and frozen.group(1) == "FROZEN"),
            "declared": frozen.group(1) if frozen else "<no status line>",
            "collection_authorized": (authorized.group(1) == "true") if authorized else None}


def bind_t0(repo: Path, path: str, commit: str) -> tuple[dict[str, object], dict[str, object]]:
    """Prove the T0 the caller names, then read its status from those exact bytes."""
    rc, _ = _git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    if rc != 0:
        return {}, check("t0", False, f"commit {commit} does not exist in {repo}")
    rc, blob_sha = _git(repo, "rev-parse", f"{commit}:{path}")
    if rc != 0:
        return {}, check("t0", False, f"{path} does not exist at {commit}")
    rc, raw = _git(repo, "cat-file", "blob", f"{commit}:{path}")
    if rc != 0:
        return {}, check("t0", False, f"the blob at {commit}:{path} could not be read")
    status = t0_status(raw.decode("utf-8", "replace"))
    block = {"commit": commit, "path": path, "blob_sha": blob_sha.decode().strip(),
             "sha256": sha256_bytes(raw), "status": status["declared"],
             "collection_authorized": status["collection_authorized"]}
    # The two fields are one authority state, and three of its four combinations
    # are refusals (R15). `FROZEN + false` is the one a reader assumes is fine:
    # the protocol is fixed, so surely work may proceed — but the owner has not
    # authorised collection, and a flag the tooling ignores is decoration.
    frozen, authorized = bool(status["frozen"]), status["collection_authorized"]
    if not frozen and authorized is True:
        return block, check("t0", False,
                            f"T0 at {commit}:{path} declares {status['declared']} while claiming "
                            "collection_authorized: true. An authorisation without a fixed "
                            "protocol is a contradiction, and honouring the flag over the "
                            "contract is how a tool starts arguing with its own rules")
    if not frozen:
        return block, check("t0", False,
                            f"T0 at {commit}:{path} declares {status['declared']}. A host cannot "
                            "be qualified against a protocol whose predicate may still change; "
                            "work done against it stays exploratory")
    if authorized is not True:
        return block, check("t0", False,
                            f"T0 at {commit}:{path} is FROZEN but collection_authorized is "
                            f"{json.dumps(authorized)}. The freeze is the owner's authorising "
                            "act and carries both; without it no collection is authorised, "
                            "however qualified the host")
    return block, check("t0", True,
                        f"T0 {block['blob_sha'][:12]} at {commit} is FROZEN and "
                        "collection_authorized: true — necessary, and not sufficient: "
                        "qualification, binding and preflight may each still refuse")


# --- the declared evidence ---------------------------------------------------


def _declared_na(value: object) -> bool:
    return isinstance(value, str) and value.startswith("n/a: ") and len(value) > 5


def validate_provisioning(doc: dict) -> list[str]:
    """SHAPE only.

    Artifact validity is not predicate outcome. `dedicated_to_p022: false` is not
    a damaged document — it is a perfectly good declaration that this host does
    not qualify, and it has to survive long enough to become a record. Discarding
    it before the artifact exists erases the negative attempts, and a laboratory
    where every machine passes first time because the other tries "were not
    artifacts" is not one anybody should trust.

    So the string "false" is malformed and the boolean `false` is evidence.
    """
    problems: list[str] = []
    if doc.get("kind") != PROVISIONING_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {PROVISIONING_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    for key in PROVISIONING_STRINGS:
        if not isinstance(doc.get(key), str) or not doc.get(key):
            problems.append(f"{key} is missing or not a non-empty string")
    for key in PROVISIONING_REQUIRED_TRUE + PROVISIONING_REQUIRED_FALSE:
        if not isinstance(doc.get(key), bool):
            problems.append(f"{key} must be a boolean, got {doc.get(key, '<missing>')!r}")

    virt = doc.get("virtualization")
    if not isinstance(virt, dict):
        return problems + ["virtualization is missing"]
    is_vm = virt.get("is_vm")
    if not isinstance(is_vm, bool):
        return problems + [f"virtualization.is_vm must be a real boolean, got {is_vm!r}: "
                           "whether this is a VM is not a question a host may decline"]
    # Applicability is shape; the answers themselves are the predicate's business.
    for key in PROVISIONING_VM_BOOLEANS:
        value = virt.get(key, "<missing>")
        if is_vm and not isinstance(value, bool):
            problems.append(f"virtualization.{key} must be a boolean on a VM, got {value!r}")
        elif not is_vm and not _declared_na(value):
            problems.append(f"virtualization.{key} must be an explicit 'n/a: <reason>' on a "
                            f"physical host, got {value!r}")
    return problems


def provisioning_predicate(doc: dict) -> list[str]:
    """VALUE. Every failure here becomes `qualified: false` in a real artifact."""
    failures: list[str] = []
    for key in PROVISIONING_REQUIRED_TRUE:
        if doc.get(key) is not True:
            failures.append(f"{key} is declared false")
    for key in PROVISIONING_REQUIRED_FALSE:
        if doc.get(key) is not False:
            failures.append(f"{key} is declared true")
    virt = doc.get("virtualization") or {}
    if virt.get("is_vm") is True:
        for key in PROVISIONING_VM_BOOLEANS:
            if virt.get(key) is not True:
                failures.append(f"virtualization.{key} is declared false; a VM that cannot "
                                "promise it is not a measurement host")
    return failures


def validate_declaration(doc: dict) -> list[str]:
    """SHAPE only, for the same reason as the provisioning declaration."""
    problems: list[str] = []
    if doc.get("kind") != DECLARATION_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {DECLARATION_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    for key in ("operator", "recorded_at"):
        if not isinstance(doc.get(key), str) or not doc.get(key):
            problems.append(f"{key} is missing or not a non-empty string")
    for key in DECLARATION_REQUIRED_TRUE:
        if not isinstance(doc.get(key), bool):
            problems.append(f"{key} must be a boolean, got {doc.get(key, '<missing>')!r}")
    return problems


def declaration_predicate(doc: dict) -> list[str]:
    """VALUE. An operator who truthfully says a workload is running gets an
    `eligible: false` record, not an error message and no evidence at all."""
    return [f"{key} is declared false" for key in DECLARATION_REQUIRED_TRUE
            if doc.get(key) is not True]


def validate_campaign_link(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["the campaign link is not a JSON object"]
    problems = []
    if doc.get("kind") != CAMPAIGN_LINK_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {CAMPAIGN_LINK_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    if not doc.get("execution_binding_sha256"):
        problems.append("execution_binding_sha256 is missing")
    for side, keys in (("d7_payload", ("path", "sha256", "blob_sha", "commit")),
                       ("d7_attestation", ("path", "sha256"))):
        block = doc.get(side)
        if not isinstance(block, dict):
            problems.append(f"{side} is missing")
            continue
        problems.extend(f"{side}.{k} is missing" for k in keys if not block.get(k))
    return problems


def check_campaign_link(link: dict, binding_path: Path, repo: Path) -> dict[str, object]:
    """Does this campaign link actually join THIS binding to the freeze on disk?

    Every field is re-proved against bytes: the binding's own hash, the D7
    payload's hash and its blob at the named commit, the attestation's hash. A
    link that names a different campaign — or a payload that has since changed —
    fails here, before a clock exists.
    """
    if link.get("execution_binding_sha256") != sha256_file(binding_path):
        return check("campaign_link", False,
                     "the campaign link names a different execution binding; this session "
                     "belongs to another campaign, or to none")
    for side in ("d7_payload", "d7_attestation"):
        named = link[side]
        path = repo / str(named["path"])
        if not path.is_file():
            return check("campaign_link", False,
                         f"{side} is absent at {named['path']}: the freeze the link names is "
                         "not on disk")
        if sha256_file(path) != named["sha256"]:
            return check("campaign_link", False,
                         f"{side} at {named['path']} does not hash to what the link names; "
                         "the freeze changed after the campaign was linked to it")
    payload = link["d7_payload"]
    rc, blob = _git(repo, "rev-parse", f"{payload['commit']}:{payload['path']}")
    if rc != 0 or blob.decode().strip() != payload["blob_sha"]:
        return check("campaign_link", False,
                     "the D7 payload blob at the named commit is not the one the link names")
    return check("campaign_link", True,
                 f"execution binding {str(link['execution_binding_sha256'])[:12]} is joined to "
                 f"the D7 payload {str(payload['sha256'])[:12]} at {str(payload['commit'])[:12]} "
                 "and to its attestation, by exact bytes")


ARTIFACT_VALIDATORS = {
    "campaign link": validate_campaign_link,
    "environment manifest": validate_manifest,
    "host qualification": validate_qualification,
    "execution binding": validate_binding,
    "session eligibility": validate_eligibility,
    "host provisioning": validate_provisioning,
    "session declaration": validate_declaration,
}


def load_artifact(path: Path, kind: str) -> dict:
    """Parse, prove, then hand over.

    One validator per artifact type rather than an ad-hoc `if doc.get("kind")` at
    five call sites, and no path that reads a field before the type is
    established.
    """
    validator = ARTIFACT_VALIDATORS[kind]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QualificationRefused(f"{path} is not readable JSON: {exc}") from exc
    problems = validator(doc)
    if problems:
        raise QualificationRefused(
            f"{path} does not validate as a {kind}: " + "; ".join(problems))
    return doc


def check_single_tenant(provisioning: dict, manifest: dict) -> dict[str, object]:
    failures = provisioning_predicate(provisioning)
    if failures:
        return check("single_tenant", False,
                     "the provisioning declaration is valid evidence that this host does not "
                     "qualify: " + "; ".join(failures))
    identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    mismatch = [k for k in ("environment_id", "host_fingerprint")
                if observed(identity, k) != provisioning.get(k)]
    if mismatch:
        return check("single_tenant", False,
                     f"provisioning and manifest disagree on {mismatch}; the declaration "
                     "describes a different machine than the one captured")
    return check("single_tenant", True,
                 "provisioning validates by shape and by value and names this machine; it is "
                 "declared evidence and is never called machine proof")


def observed(identity: dict, field: str) -> object:
    entry = identity.get(field)
    if isinstance(entry, dict) and entry.get("status") == "observed":
        return entry.get("value")
    return None


# --- the machine-observed predicate -----------------------------------------


def check_ci(manifest: dict) -> dict[str, object]:
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or "ci" not in provenance:
        return check("ci", False, "the manifest carries no provenance.ci field")
    value = provenance["ci"]
    if not isinstance(value, bool):
        return check("ci", False, f"provenance.ci is {type(value).__name__}, not a boolean")
    return check("ci", value is False, f"manifest.provenance.ci == {json.dumps(value)}")


def power_snapshot() -> dict[str, object]:
    """A structured, comparable snapshot — not prose.

    Preflight and postflight compare these by equality, so the shape has to be
    the evidence rather than a sentence a human would have to re-read.
    """
    if os.name == "nt":
        active = _tool(["powercfg", "/getactivescheme"])
        guids = re.findall(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                           active[1]) if active and active[0] == 0 else []
        snap: dict[str, object] = {"platform": "windows",
                                   "plan_guid": guids[0].lower() if guids else None}
        for label, setting in (("min", WIN_PROCTHROTTLEMIN), ("max", WIN_PROCTHROTTLEMAX)):
            ac, dc = _win_indices(setting)
            snap[f"processor_{label}_ac"] = ac
            snap[f"processor_{label}_dc"] = dc
        return snap
    governors = {}
    for cpu in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
        value = _text(str(cpu / "cpufreq" / "scaling_governor"))
        if value:
            governors[cpu.name] = value
    boost: dict[str, object] = {"mechanism": None, "value": None}
    for mechanism, path in (("intel_pstate/no_turbo",
                             "/sys/devices/system/cpu/intel_pstate/no_turbo"),
                            ("cpufreq/boost", "/sys/devices/system/cpu/cpufreq/boost")):
        value = _text(path)
        if value is not None:
            boost = {"mechanism": mechanism, "value": value}
            break
    return {"platform": "linux", "governors": governors, "boost": boost}


def _win_indices(setting_guid: str) -> tuple[int | None, int | None]:
    """(AC, DC) setting indices, by GUID and by position.

    The block ends with the two current indices, AC then DC; everything before
    them describes the possible RANGE. A first-match parse reads the range's
    minimum as the current setting, which is how an earlier version of this tool
    reported 0% on a machine pinned at 100%. Labels are never parsed: on this
    machine every one of them is localized.
    """
    found = _tool(["powercfg", "/query", "SCHEME_CURRENT", WIN_SUB_PROCESSOR, setting_guid])
    if not found or found[0] != 0:
        return None, None
    indices = re.findall(r"0x([0-9a-fA-F]{8})", found[1])
    if len(indices) < 2:
        return None, None
    return int(indices[-2], 16), int(indices[-1], 16)


def check_power_policy(snapshot: dict[str, object]) -> dict[str, object]:
    if snapshot.get("platform") == "windows":
        plan = snapshot.get("plan_guid")
        if plan not in WIN_ACCEPTED_PLANS:
            return check("power_policy", False,
                         f"active plan {plan} is neither High Performance nor Ultimate")
        states = {k: snapshot.get(k) for k in ("processor_min_ac", "processor_max_ac",
                                               "processor_min_dc", "processor_max_dc")}
        wrong = {k: v for k, v in states.items() if v != WIN_REQUIRED_STATE}
        if wrong:
            return check("power_policy", False,
                         f"processor state must be {WIN_REQUIRED_STATE}% on AC *and* DC; got "
                         f"{wrong}. A machine that is compliant while plugged in and changes "
                         "policy when the power source does is not a fixed environment")
        return check("power_policy", True, f"plan {plan}, AC and DC processor state min=max=100%")
    governors = snapshot.get("governors") or {}
    if not governors:
        return check("power_policy", False,
                     "no cpufreq/scaling_governor on any CPU; the frequency policy is not "
                     "observable here, so this host is not eligible")
    wrong = sorted(c for c, g in governors.items() if g != "performance")
    if wrong:
        return check("power_policy", False, f"governor is not 'performance' on {wrong}")
    boost = snapshot.get("boost") or {}
    if not boost.get("mechanism"):
        return check("power_policy", False,
                     "no turbo/boost mechanism could be identified, so its state cannot be "
                     "recorded or rechecked through the session")
    return check("power_policy", True,
                 f"governor=performance on all {len(governors)} CPUs; "
                 f"{boost['mechanism']}={boost['value']}")


def check_memory_metric(stratum: str) -> dict[str, object]:
    expected = STRATUM_METRIC[stratum]
    if stratum == "linux":
        available, mechanism = hasattr(os, "wait4"), "posix os.wait4 (ru_maxrss)"
    else:
        available, mechanism = os.name == "nt", "win32 job object (PeakProcessMemoryUsed)"
    if not available:
        return check("required_memory_metric", False,
                     f"stratum {stratum} requires {expected} via {mechanism}, which this host "
                     "does not provide")
    return check("required_memory_metric", True, f"{expected} via {mechanism}")


# --- quiesce -----------------------------------------------------------------


def _cpu_counters() -> tuple[int, int] | None:
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
    raw = _text("/proc/stat")
    line = (raw or "").splitlines()[0] if raw else ""
    if not line.startswith("cpu "):
        return None
    fields = [int(x) for x in line.split()[1:] if x.isdigit()]
    if len(fields) < 5:
        return None
    total = sum(fields)
    return total - (fields[3] + fields[4]), total     # idle + iowait


def quiesce(sleep=time.sleep, counters=_cpu_counters,
            intervals: int = QUIESCE_INTERVALS) -> dict[str, object]:
    """120 s without campaign workload, of which the final 60 s is measured.

    The quiet minute is waited, not asserted. An earlier version declared a
    120 s window and sampled immediately for 60 s, which turned the constant
    into documentation.
    """
    sleep(QUIESCE_QUIET_S)
    samples: list[float] = []
    previous = counters()
    if previous is None:
        return {"eligible": False, "reason": "the CPU counter could not be read at all",
                "quiet_seconds": QUIESCE_QUIET_S, "samples": [], "mean": None, "max": None}
    for _ in range(intervals):
        sleep(QUIESCE_INTERVAL_S)
        current = counters()
        if current is None:
            return {"eligible": False, "reason": "a CPU sample could not be read",
                    "quiet_seconds": QUIESCE_QUIET_S, "samples": samples,
                    "mean": None, "max": None}
        d_busy, d_total = current[0] - previous[0], current[1] - previous[1]
        previous = current
        if d_total <= 0 or d_busy < 0:
            return {"eligible": False,
                    "reason": f"the CPU counter did not advance sanely (busy {d_busy}, "
                              f"total {d_total})",
                    "quiet_seconds": QUIESCE_QUIET_S, "samples": samples,
                    "mean": None, "max": None}
        samples.append(d_busy / d_total)
    mean, worst = sum(samples) / len(samples), max(samples)
    result = {"quiet_seconds": QUIESCE_QUIET_S, "samples": samples, "mean": mean, "max": worst}
    if mean >= QUIESCE_MEAN_MAX:
        return {**result, "eligible": False,
                "reason": f"mean utilisation {mean:.4f} is not below {QUIESCE_MEAN_MAX}"}
    if worst > QUIESCE_INTERVAL_MAX:
        return {**result, "eligible": False,
                "reason": f"an interval reached {worst:.4f}, above {QUIESCE_INTERVAL_MAX}"}
    return {**result, "eligible": True, "reason": ""}


# --- the three records -------------------------------------------------------


def qualify(stratum: str, repo: Path, t0_path: str, t0_commit: str,
            provisioning_path: Path, manifest_path: Path) -> dict[str, object]:
    if stratum not in STRATUM_METRIC:
        raise QualificationRefused(f"unknown stratum {stratum!r}")
    provisioning = load_artifact(provisioning_path, "host provisioning")
    manifest = load_artifact(manifest_path, "environment manifest")
    identity = manifest["identity"]

    t0_block, t0_check = bind_t0(repo, t0_path, t0_commit)
    environment_id = observed(identity, "environment_id")
    id_check = check("environment_identity", bool(environment_id),
                     f"environment_id {environment_id!r} is the manifest's own observed value; "
                     "the provisioning declaration must agree with it and there is no third "
                     "string to disagree with either")
    snapshot = power_snapshot()
    checks = [t0_check, id_check, check_ci(manifest),
              check_single_tenant(provisioning, manifest), check_power_policy(snapshot),
              check_memory_metric(stratum)]
    by_name = {str(c["check"]): c for c in checks}
    missing = [k for k in PREDICATE_KEYS if k not in by_name]
    if missing:
        raise QualificationRefused(f"the predicate did not produce {missing}")
    return {
        "kind": QUALIFICATION_SCHEMA,
        "schema": SCHEMA_VERSION,
        "stratum": stratum,
        "t0": t0_block,
        "environment_id": environment_id,
        "host_fingerprint": observed(identity, "host_fingerprint"),
        "environment_identity_sha256": canonical_sha256(identity),
        "provisioning": {"sha256": sha256_file(provisioning_path)},
        "environment_manifest": {"sha256": sha256_file(manifest_path)},
        "qualification_tool": {"sha256": sha256_file(Path(__file__).resolve())},
        "power_snapshot": snapshot,
        "predicate": {name: by_name[name]["result"] for name in PREDICATE_KEYS},
        "predicate_detail": {name: by_name[name]["detail"] for name in PREDICATE_KEYS},
        "memory_metric": STRATUM_METRIC[stratum],
        "qualified": all(c["result"] == "pass" for c in checks),
        "qualified_at": _now(),
        "not_a_session_certificate": (
            "this proves the host satisfies the predicate of the named frozen T0 against the "
            "bytes named here; the fitness of any particular session is proved again"),
    }


def _candidate_check(binding_block: dict, candidate_path: Path) -> dict[str, object]:
    raw = candidate_path.read_bytes()
    digest, size = sha256_bytes(raw), len(raw)
    if digest != binding_block.get("candidate_sha256") or size != binding_block.get(
            "candidate_bytes"):
        return check("candidate", False,
                     f"the executable present is {digest[:12]} / {size} B; the campaign is bound "
                     f"to {str(binding_block.get('candidate_sha256'))[:12]} / "
                     f"{binding_block.get('candidate_bytes')} B")
    return check("candidate", True, f"{digest[:12]} / {size} B, as bound")


def session_eligibility(binding_path: Path, qualification_path: Path, manifest_path: Path,
                        declaration_path: Path, candidate_path: Path,
                        campaign_link_path: Path, repo: Path,
                        quiesce_result: dict[str, object] | None = None) -> dict[str, object]:
    binding = load_artifact(binding_path, "execution binding")
    qualification = load_artifact(qualification_path, "host qualification")
    manifest = load_artifact(manifest_path, "environment manifest")
    declaration = load_artifact(declaration_path, "session declaration")
    link = load_artifact(campaign_link_path, "campaign link")
    stratum = str(qualification["stratum"])
    bound = binding[stratum]
    identity = manifest["identity"]
    reasons: list[str] = []

    if not qualification.get("qualified"):
        reasons.append("the referenced qualification does not say qualified")
    if bound.get("qualification_sha256") != sha256_file(qualification_path):
        reasons.append("the execution binding does not name this qualification; a qualified "
                       "host outside this campaign may not be substituted into it")
    if bound.get("memory_metric") != qualification.get("memory_metric"):
        reasons.append("the binding and the qualification disagree about the memory metric")

    joined = check_campaign_link(link, binding_path, repo)
    if joined["result"] != "pass":
        reasons.append(str(joined["detail"]))

    declared = declaration_predicate(declaration)
    if declared:
        reasons.append("the session declaration says this moment is not measurable: "
                       + "; ".join(declared))

    ci = check_ci(manifest)
    snapshot = power_snapshot()
    power = check_power_policy(snapshot)
    for result in (ci, power):
        if result["result"] != "pass":
            reasons.append(str(result["detail"]))
    if snapshot != qualification.get("power_snapshot"):
        reasons.append("the power state is not the one this host was qualified with")

    live_identity = canonical_sha256(identity)
    if live_identity != qualification.get("environment_identity_sha256"):
        reasons.append("the fresh manifest's identity block does not hash to the qualified "
                       "environment identity; something in the identity set moved")

    candidate = _candidate_check(bound, candidate_path)
    if candidate["result"] != "pass":
        reasons.append(str(candidate["detail"]))

    result = quiesce_result if quiesce_result is not None else quiesce()
    if not result.get("eligible"):
        reasons.append(f"quiesce: {result.get('reason')}")

    return {
        "kind": ELIGIBILITY_SCHEMA,
        "schema": SCHEMA_VERSION,
        "stratum": stratum,
        "execution_binding_sha256": sha256_file(binding_path),
        "qualification_sha256": sha256_file(qualification_path),
        "fresh_environment_manifest_sha256": sha256_file(manifest_path),
        "environment_identity_sha256": live_identity,
        "session_declaration_sha256": sha256_file(declaration_path),
        "campaign_link_sha256": sha256_file(campaign_link_path),
        "campaign_link": joined,
        "power_snapshot": snapshot,
        "candidate": candidate,
        "ci": ci,
        "quiesce": result,
        "eligible": not reasons,
        "reasons": reasons,
        "recorded_at": _now(),
        "note": ("a refusal here means the session does not start, which is not INVALID: no "
                 "clock has run, so there is no evidence to damage and no retry to spend"),
    }


def session_admissibility(binding_path: Path, qualification_path: Path, preflight_path: Path,
                          manifest_path: Path, candidate_path: Path,
                          closing_probe_path: Path, campaign_link_path: Path,
                          repo: Path) -> dict[str, object]:
    """Did the attempt that ran remain the one that was authorised?

    Separate from preflight on purpose: preflight may not certify what a session
    did after it started, and an attempt that drifted mid-flight has to be
    caught by evidence taken after it, not before.
    """
    binding = load_artifact(binding_path, "execution binding")
    qualification = load_artifact(qualification_path, "host qualification")
    preflight = load_artifact(preflight_path, "session eligibility")
    manifest = load_artifact(manifest_path, "environment manifest")
    link = load_artifact(campaign_link_path, "campaign link")
    stratum = str(qualification["stratum"])
    bound = binding[stratum]
    identity = manifest["identity"]
    binding_sha = sha256_file(binding_path)
    reasons: list[str] = []

    if not preflight.get("eligible"):
        reasons.append("the preflight for this session did not declare it eligible")
    seen = {preflight.get("execution_binding_sha256"), binding_sha}
    if len(seen) != 1:
        reasons.append("the preflight and this binding are two different campaign identities; "
                       "a changed binding is a different campaign, never a newer one")
    if preflight.get("qualification_sha256") != sha256_file(qualification_path):
        reasons.append("the preflight was taken against a different qualification")
    joined = check_campaign_link(link, binding_path, repo)
    if joined["result"] != "pass":
        reasons.append(str(joined["detail"]))
    if preflight.get("campaign_link_sha256") != sha256_file(campaign_link_path):
        reasons.append("the preflight and this pass name different campaign links; an "
                       "attempt cannot change which campaign it belongs to mid-session")

    snapshot = power_snapshot()
    if snapshot != preflight.get("power_snapshot"):
        reasons.append("the power state changed during the session")
    live_identity = canonical_sha256(identity)
    if live_identity != preflight.get("environment_identity_sha256"):
        reasons.append("the environment identity changed during the session")
    candidate = _candidate_check(bound, candidate_path)
    if candidate["result"] != "pass":
        reasons.append("the candidate changed during the session: " + str(candidate["detail"]))
    if not closing_probe_path.is_file():
        reasons.append("no closing noise probe evidence was supplied")

    return {
        "kind": ADMISSIBILITY_SCHEMA,
        "schema": SCHEMA_VERSION,
        "stratum": stratum,
        "execution_binding_sha256": binding_sha,
        "qualification_sha256": sha256_file(qualification_path),
        "preflight_sha256": sha256_file(preflight_path),
        "campaign_link_sha256": sha256_file(campaign_link_path),
        "campaign_link": joined,
        "post_environment_manifest_sha256": sha256_file(manifest_path),
        "environment_identity_sha256": live_identity,
        "power_snapshot": snapshot,
        "candidate": candidate,
        "closing_probe_sha256": (sha256_file(closing_probe_path)
                                 if closing_probe_path.is_file() else None),
        "admissible": not reasons,
        "reasons": reasons,
        "recorded_at": _now(),
        "note": ("drift found here is an INVALID attempt under T0-6, which is not the same as a "
                 "session that never started"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualify", action="store_true")
    parser.add_argument("--session-preflight", action="store_true")
    parser.add_argument("--session-postflight", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--stratum", choices=sorted(STRATUM_METRIC))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--t0-path")
    parser.add_argument("--t0-commit")
    parser.add_argument("--provisioning", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--closing-probe", type=Path)
    parser.add_argument("--campaign-link", type=Path)
    parser.add_argument("--emit", type=Path)
    args = parser.parse_args(argv)

    if args.selftest:
        print(json.dumps({"tool_sha256": sha256_file(Path(__file__).resolve()),
                          "strata": STRATUM_METRIC, "predicate_keys": list(PREDICATE_KEYS),
                          "quiesce": {"window_s": QUIESCE_WINDOW_S,
                                      "quiet_s": QUIESCE_QUIET_S,
                                      "intervals": QUIESCE_INTERVALS,
                                      "interval_s": QUIESCE_INTERVAL_S,
                                      "mean_max": QUIESCE_MEAN_MAX,
                                      "interval_max": QUIESCE_INTERVAL_MAX}}, indent=2))
        return 0

    def require(flag: str, names: tuple[str, ...]) -> None:
        absent = [n for n in names if getattr(args, n.replace("-", "_")) is None]
        if absent:
            parser.error(f"--{flag} requires {['--' + n for n in absent]}")

    try:
        if args.qualify:
            require("qualify", ("stratum", "t0-path", "t0-commit", "provisioning", "manifest"))
            record = qualify(args.stratum, args.repo, args.t0_path, args.t0_commit,
                             args.provisioning, args.manifest)
            ok = bool(record["qualified"])
        elif args.session_preflight:
            require("session-preflight",
                    ("binding", "qualification", "manifest", "declaration", "candidate",
                     "campaign-link"))
            record = session_eligibility(args.binding, args.qualification, args.manifest,
                                         args.declaration, args.candidate, args.campaign_link,
                                         args.repo)
            ok = bool(record["eligible"])
        elif args.session_postflight:
            require("session-postflight",
                    ("binding", "qualification", "preflight", "manifest", "candidate",
                     "closing-probe", "campaign-link"))
            record = session_admissibility(args.binding, args.qualification, args.preflight,
                                           args.manifest, args.candidate, args.closing_probe,
                                           args.campaign_link, args.repo)
            ok = bool(record["admissible"])
        else:
            parser.error("choose --qualify, --session-preflight, --session-postflight "
                         "or --selftest")
    except QualificationRefused as exc:
        # An input that is not the artifact it claims to be is an operator error,
        # never a session that merely failed a predicate. It gets its own exit
        # code so a caller cannot read it as "measured, and not eligible".
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.emit:
        args.emit.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
