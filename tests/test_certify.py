#!/usr/bin/env python3
"""S2 step 12 — Final Evidence Certification (Tier A, SDK-free).

Drives ownlang/fix_certify.py without dotnet: a complete, internally-consistent six-artifact
evidence chain (candidates, validated plan, step 8 bundle, step 9 gate-result, step 10
delta-result, step 11 target-result) plus a reference closure is synthesized in pure Python for
the converted, manual-only and mixed cases, and `own-fix subscriptions certify` is proven to bind
it into one deterministic certification-result.json — or to refuse with exactly one stable
category on any tampered artifact. The real Steps 8-11 producers over dotnet are the Tier B job.

Run:  python tests/test_certify.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import fix_certify as fc
from ownlang.fix_bundle import build_manifest, canonical_patch, manifest_bytes
from ownlang.fix_delta import _STEP9_GATE_NAMES, _STEP9_GIT_GATES, _sorted_multiset
from ownlang.fix_gate import (
    _bundle_sha256,
    _canonical_bytes,
    _canonical_json,
    _sha_bytes,
    validate_gate_authority,
)
from ownlang.fix_target import _attempt_verdict

_REL = "Own/Sample.cs"
_FQN = "N.A"
_SUB = "WeakEvents.AddPropertyChanged"
_PRE = b"class A\n{\n    void M(IPub a)\n    {\n        a.PropertyChanged += OnX;\n    }\n}\n"
_POST = (b"class A\n{\n    void M(IPub a)\n    {\n        WeakEvents.AddPropertyChanged(a, OnX);"
         b"\n    }\n}\n")


# --- candidate / plan builders ------------------------------------------------------


def _cand(fid: str, start: int, handler: str, contract: str, actions: list[str]) -> dict:
    return {"finding_id": fid, "diagnostic_code": "OWN001", "containing_type": _FQN, "file": _REL,
            "enclosing_member": "N.A.M(N.IPub)", "event": "PropertyChanged",
            "event_identity": "System.ComponentModel.INotifyPropertyChanged.PropertyChanged",
            "event_contract": contract, "source": "a", "source_identity": "a",
            "source_identity_kind": "computed", "handler": handler,
            "handler_identity": f"N.A.{handler}(object, ...)",
            "handler_identity_kind": "stable_symbol", "occurrence_ordinal": 0,
            "acquire_span": {"start": start, "length": 24, "start_line": 5, "start_column": 9,
                             "end_line": 5, "end_column": 33},
            "teardown": {"status": "none", "candidates": []}, "allowed_actions": actions}


def _cands(cs: list[dict]) -> dict:
    return {"version": 1, "operation": "fix-subscriptions", "target_api": {"subscribe": _SUB},
            "selection": {"allowed_types": [{"full_name": _FQN, "file": _REL}],
                          "selected_findings": None,
                          "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                          "allow_helper_changes": False,
                                          "allow_config_changes": False,
                                          "allow_suppressions": False}},
            "source_files": [{"path": _REL, "sha256": _sha_bytes(_PRE)}], "candidates": cs}


def _plan(cands: dict, actions: list[str]) -> dict:
    return {"version": 1, "operation": "fix-subscriptions",
            "input_bundle_sha256": _bundle_sha256(cands),
            "target_api": {"subscribe": _SUB},
            "selection": {"allowed_types": [dict(cands["selection"]["allowed_types"][0])],
                          "selected_findings": cands["selection"]["selected_findings"],
                          "constraints": dict(cands["selection"]["constraints"])},
            "source_files": [dict(cands["source_files"][0])],
            "decisions": [{"finding_id": c["finding_id"], "action": actions[i],
                           "file": c["file"], "acquire_span": c["acquire_span"]}
                          for i, c in enumerate(cands["candidates"])]}


def _obs(handler: str) -> dict:
    return {"file": _REL, "code": "OWN001", "component": "A", "event": "PropertyChanged",
            "handler": handler, "kind": "subscription", "advisory": False,
            "severity": None, "ignore_reason": None}


# --- runtime / toolchain fingerprints (self-consistent digests) ---------------------


def _mfp(files: list[dict]) -> str:
    return _sha_bytes(_canonical_json(files))


_EXT_FILES = [{"path": "OwnSharp.Extractor.dll", "sha256": "sha256:" + "1" * 64}]
_OWNLANG_FILES = [{"path": "ownlang/__init__.py", "sha256": "sha256:" + "2" * 64},
                  {"path": "ownlang/ownir.py", "sha256": "sha256:" + "3" * 64}]
_PROBE_FILES = [{"path": "OwnSharp.WeakTargetProbe.dll", "sha256": "sha256:" + "4" * 64}]
_RID = {"framework_name": "Microsoft.NETCore.App", "tfm": "net8.0",
        "requested_framework_version": "8.0.0", "selected_framework_version": "8.0.28",
        "runtime_manifest_sha256": "sha256:" + "5" * 64}
_CORE_ANALYZER = {"ownlang_manifest_sha256": _mfp(_OWNLANG_FILES), "ownlang_files": _OWNLANG_FILES,
                  "core_runner_sha256": "sha256:" + "6" * 64,
                  "python_executable_sha256": "sha256:" + "7" * 64,
                  "python_implementation": "cpython", "python_version": "3.13.0",
                  "python_cache_tag": "cpython-313"}
_WRAP_MVID = "d94f6f4c-0000-4000-8000-00000000abcd"
_WRAP_TOKEN = "0x06000001"
_WRAP_SIG = "System.Void WeakEvents.AddPropertyChanged(...)"
_WRAP_ASM = "WeakEvents"
_WRAP_DLL = b"MZ-weak-events-wrapper-assembly-bytes\n"


def _attempt(ordinal: int, **over: object) -> dict:
    a = {"attempt": ordinal, "strong_delivered_once": True, "strong_retained": True,
         "weak_control_collected": True, "delivered_count": 1, "threw_on_subscribe": False,
         "threw_on_first_raise": False, "subscriber_collected": True,
         "threw_on_post_collection_raise": False}
    a.update(over)
    a["verdict"] = _attempt_verdict(a)
    return a


# --- the full chain builder ---------------------------------------------------------


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class Chain:
    """A mutable, internally-consistent six-artifact evidence chain. Fields are Python objects;
    ``materialize`` serializes them to a fresh directory tree and returns the certify arguments."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        if kind == "converted":
            cs = [_cand("OWN001:sha256:" + "a" * 64, 40, "OnX", "inotify_property_changed",
                        ["convert_acquire", "manual_review"])]
            actions = ["convert_acquire"]
        elif kind == "manual":
            cs = [_cand("OWN001:sha256:" + "b" * 64, 40, "OnX", "name_only", ["manual_review"])]
            actions = ["manual_review"]
        elif kind == "mixed":
            cs = [_cand("OWN001:sha256:" + "a" * 64, 40, "OnX", "inotify_property_changed",
                        ["convert_acquire", "manual_review"]),
                  _cand("OWN001:sha256:" + "c" * 64, 80, "OnY", "name_only", ["manual_review"])]
            actions = ["convert_acquire", "manual_review"]
        else:
            raise ValueError(kind)
        self.cands = _cands(cs)
        self.plan = _plan(self.cands, actions)
        self.cands_bytes = json.dumps(self.cands, indent=2).encode()
        self.plan_bytes = json.dumps(self.plan, indent=2).encode()
        self.auth = validate_gate_authority(self.plan, self.cands)
        self.rel = self.auth.rel
        self.converted = bool(self.auth.applied)

        pre = _PRE
        post = _POST if self.converted else _PRE
        self.postimage = post
        self.patch = canonical_patch(self.rel, pre, post)
        man = build_manifest(self.plan, _sha_bytes(self.plan_bytes), self.rel,
                             _sha_bytes(pre), post, self.patch)
        self.manifest_data = manifest_bytes(man)

        cb = self.auth.input_bundle_sha256
        pb = _sha_bytes(self.plan_bytes)
        cs_sha = _sha_bytes(self.cands_bytes)
        mb = _sha_bytes(self.manifest_data)
        pa = _sha_bytes(self.patch)
        pre_sha = _sha_bytes(pre)
        po = _sha_bytes(post)
        self.pre_sha = pre_sha
        self._h = {"input_bundle_sha256": cb, "validated_plan_sha256": pb,
                   "candidates_sha256": cs_sha, "apply_manifest_sha256": mb, "patch_sha256": pa,
                   "pre_sha256": pre_sha, "post_sha256": po}

        git = "pass" if self.converted else "not_applicable"
        gates = dict.fromkeys(_STEP9_GATE_NAMES, "pass")
        for g in _STEP9_GIT_GATES:
            gates[g] = git
        gate = {"version": 1, "operation": "gate-subscription-fix-bundle",
                "input_bundle_sha256": cb, "validated_plan_sha256": pb,
                "apply_manifest_sha256": mb, "patch_sha256": pa,
                "target_api": {"subscribe": _SUB},
                "source_files": [{"path": self.rel, "pre_sha256": pre_sha, "post_sha256": po}],
                "applied_findings": list(self.auth.applied),
                "manual_review_findings": list(self.auth.manual), "gates": gates}
        self.gate_bytes = _canonical_bytes(gate)
        gb = _sha_bytes(self.gate_bytes)

        convert_ids = sorted(self.auth.applied)
        manual_ids = sorted(self.auth.manual)
        handler_of = {c["finding_id"]: c["handler"] for c in self.cands["candidates"]}
        base_obs = [_obs(handler_of[c["finding_id"]]) for c in self.cands["candidates"]]
        post_obs = [_obs(handler_of[fid]) for fid in manual_ids]
        removed_obs = [_obs(handler_of[fid]) for fid in convert_ids]
        ref_count = 1 if self.converted else 0
        self.ref_slots = ([("WeakEvents.dll", _WRAP_DLL)] if self.converted else [])
        ref_closure = [{"ordinal": i, "source_dir_ordinal": i,
                        "relative_path": name, "sha256": _sha_bytes(data)}
                       for i, (name, data) in enumerate(self.ref_slots)]
        self.ref_closure = ref_closure

        self.delta = {
            "schema": 1, "operation": "verify-subscription-analyzer-delta", "status": "pass",
            "analysis_scope": {
                "source_file": self.rel, "selected_class": _FQN,
                "closure_kind": "single-file+refdirs" if ref_count else "single-file",
                "reference_dir_count": ref_count, "target_file_identity": self.rel},
            "input_hashes": dict(self._h),
            "gate_binding": {"gate_result_sha256": gb, "step9_operation":
                             "gate-subscription-fix-bundle", "step9_version": 1,
                             "git_gates_status": git, "bound": True},
            "toolchain_fingerprint": {
                "extractor_deployment_manifest_sha256": _mfp(_EXT_FILES),
                "extractor_files": _EXT_FILES, "dotnet_host_sha256": "sha256:" + "8" * 64,
                "dotnet_version": "8.0.100", "resolved_runtime_identity": dict(_RID),
                "core_analyzer": dict(_CORE_ANALYZER)},
            "reference_closure": ref_closure, "target_api": {"subscribe": _SUB},
            "expected": {"convert_acquire_ids": convert_ids, "manual_review_ids": manual_ids},
            "baseline": {"subscription_own001_ids": sorted(c["finding_id"]
                                                           for c in self.cands["candidates"]),
                         "all_own001": _sorted_multiset(base_obs), "own050": []},
            "postimage": {"subscription_own001_ids": manual_ids,
                          "all_own001": _sorted_multiset(post_obs), "own050": []},
            "delta": {"removed_subscription_own001_ids": convert_ids,
                      "preserved_subscription_own001_ids": manual_ids,
                      "new_subscription_own001_ids": [],
                      "unexpectedly_removed_subscription_own001_ids": [],
                      "removed_all_own001": _sorted_multiset(removed_obs),
                      "new_all_own001": [], "new_own050": []},
            "semantic_idempotence": {"converted_ids_still_actionable": [], "pass": True},
            "checks": dict.fromkeys((
                "input_layout", "authority_binding", "gate_binding", "toolchain_binding",
                "core_analyzer_binding", "analysis_scope", "baseline_authority",
                "baseline_analysis", "postimage_analysis", "analysis_identity",
                "delta_subscription", "delta_core", "new_own001", "new_own050",
                "semantic_idempotence", "isolation", "publication"), "pass"),
        }
        self.delta_bytes = _canonical_bytes(self.delta)
        db = _sha_bytes(self.delta_bytes)

        delta_binding = {"delta_result_sha256": db,
                         "step10_operation": "verify-subscription-analyzer-delta",
                         "step10_status": "pass", "bound": True}
        if self.converted:
            attempts = [_attempt(i) for i in range(3)]
            self.target = {
                "schema": 1, "operation": "verify-target-wrapper", "status": "pass",
                "input_hashes": dict(self._h), "delta_binding": delta_binding,
                "target_api": {"subscribe": _SUB}, "reference_closure": ref_closure,
                "callsite_binding": {"converted_callsites": len(convert_ids),
                                     "all_callsites_same_symbol": True,
                                     "target_is_source_defined": False,
                                     "derived_wrapper_ordinal": 0, "asserted_wrapper_ordinal": 0},
                "selected_wrapper": {
                    "ordinal": 0, "relative_path": ref_closure[0]["relative_path"],
                    "sha256": ref_closure[0]["sha256"], "assembly_simple_name": _WRAP_ASM,
                    "module_mvid": _WRAP_MVID, "metadata_token": _WRAP_TOKEN,
                    "resolved_signature": _WRAP_SIG},
                "probe_toolchain_fingerprint": {
                    "probe_deployment_manifest_sha256": _mfp(_PROBE_FILES),
                    "probe_runner_sha256": "sha256:" + "9" * 64, "probe_files": _PROBE_FILES,
                    "dotnet_host_sha256": "sha256:" + "8" * 64, "dotnet_version": "8.0.100"},
                "probe_runtime_identity": {
                    "framework_name": "Microsoft.NETCore.App", "tfm": "net8.0",
                    "requested_framework_version": "8.0.0", "selected_framework_version": "8.0.28",
                    "selected_runtime_manifest_sha256": "sha256:" + "5" * 64},
                "probe_protocol": {"attempt_count": 3, "collection_rounds": 5,
                                   "allocation_pressure_bytes_per_round": 4194304,
                                   "child_timeout_seconds": 30, "stdout_limit_bytes": 65536,
                                   "stderr_limit_bytes": 65536, "probe_result_limit_bytes": 65536,
                                   "delivered_count_required": 1},
                "attempts": attempts,
                "checks": dict.fromkeys((
                    "input_layout", "authority_binding", "delta_binding", "reference_binding",
                    "probe_toolchain_binding", "wrapper_binding", "harness_controls",
                    "target_behavior", "target_nonretention", "harness_determinism",
                    "publication"), "pass")}
        else:
            na = ("probe_toolchain_binding", "wrapper_binding", "harness_controls",
                  "target_behavior", "target_nonretention", "harness_determinism")
            checks = {n: ("not_applicable" if n in na else "pass") for n in (
                "input_layout", "authority_binding", "delta_binding", "reference_binding",
                "probe_toolchain_binding", "wrapper_binding", "harness_controls",
                "target_behavior", "target_nonretention", "harness_determinism", "publication")}
            self.target = {"schema": 1, "operation": "verify-target-wrapper", "status": "pass",
                           "input_hashes": dict(self._h), "delta_binding": delta_binding,
                           "target_api": {"subscribe": _SUB}, "reference_closure": ref_closure,
                           "checks": checks}

    def materialize(self, root: str) -> dict:
        # Inputs live under <root>/in; the published output goes to <root>/out, which is therefore
        # physically outside every protected input root (bundle / ref-dirs / input-file parents).
        indir = os.path.join(root, "in")
        os.makedirs(indir, exist_ok=True)
        bundle = os.path.join(indir, "bundle")
        _write(os.path.join(bundle, "apply-manifest.json"), self.manifest_data)
        _write(os.path.join(bundle, "change.patch"), self.patch)
        _write(os.path.join(bundle, "postimage", *self.rel.split("/")), self.postimage)
        paths = {"plan": os.path.join(indir, "plan.json"),
                 "candidates": os.path.join(indir, "candidates.json"),
                 "gate": os.path.join(indir, "gate.json"),
                 "delta": os.path.join(indir, "delta.json"),
                 "target": os.path.join(indir, "target.json")}
        _write(paths["plan"], self.plan_bytes)
        _write(paths["candidates"], self.cands_bytes)
        _write(paths["gate"], self.gate_bytes)
        _write(paths["delta"], _canonical_bytes(self.delta))
        _write(paths["target"], _canonical_bytes(self.target))
        ref_dirs = []
        for i, (name, data) in enumerate(self.ref_slots):
            rd = os.path.join(indir, f"ref-{i}")
            _write(os.path.join(rd, name), data)
            ref_dirs.append(rd)
        out = os.path.join(root, "out", "cert")
        os.makedirs(os.path.join(root, "out"), exist_ok=True)
        return {"bundle": bundle, "out": out, "ref_dirs": ref_dirs, **paths}


def _run(a: dict) -> str:
    return fc.run_certify(a["plan"], a["candidates"], a["bundle"], a["gate"], a["delta"],
                          a["target"], a["out"], a["ref_dirs"])


def _raises(cat: str, a: dict) -> bool:
    try:
        _run(a)
    except fc.CertifyError as exc:
        return exc.category == cat
    return False


# --- Tier A: core certification contract --------------------------------------------


def run() -> int:
    ok = 0
    bad = 0

    def check(cond: bool, label: str) -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"  FAIL: {label}")

    _core_pass(check)
    _byte_forms(check)
    _basic_refusals(check)
    _publication(check)
    _deep_representable(check)
    _isolation(check)

    total = ok + bad
    print(f"certify (Tier A): {ok}/{total} checks pass")
    return 1 if bad else 0


def _cert(a: dict) -> dict:
    published = _run(a)
    with open(os.path.join(published, "certification-result.json"), "rb") as fh:
        return json.loads(fh.read())


def _core_pass(check) -> None:
    for kind, ck in (("converted", "converted"), ("manual", "manual_only"), ("mixed", "converted")):
        with tempfile.TemporaryDirectory() as tmp:
            a = Chain(kind).materialize(tmp)
            res = _cert(a)
            check(res["status"] == "evidence_complete", f"{kind}: status evidence_complete")
            check(res["chain_kind"] == ck, f"{kind}: chain_kind {ck}")
            check(res["operation"] == "certify-subscription-fix-chain", f"{kind}: operation")
            check(set(res["artifact_hashes"]) == {
                "candidates_sha256", "validated_plan_sha256", "apply_manifest_sha256",
                "patch_sha256", "post_sha256", "gate_result_sha256", "delta_result_sha256",
                "target_result_sha256"}, f"{kind}: artifact_hashes exactly eight")
            check(set(res["semantic_hashes"]) == {"input_bundle_sha256"},
                  f"{kind}: semantic_hashes exactly one")
            check(res["preimage_binding"] == {
                "mode": "cross_artifact_only", "bytes_supplied": False,
                "pre_sha256": Chain(kind).pre_sha}, f"{kind}: preimage_binding block")
            check(res["certification"]["claims"] == list(fc._CLAIMS),
                  f"{kind}: exact claims array")
            check("steps_8_11_gates_satisfied" not in json.dumps(res),
                  f"{kind}: no steps_8_11_gates_satisfied anywhere")
            check(set(res["checks"]) == set(fc._CHECK_NAMES) and len(fc._CHECK_NAMES) == 12,
                  f"{kind}: exactly the twelve checks")
            raw = open(os.path.join(a["out"], "certification-result.json"), "rb").read()
            canon = _canonical_bytes(res)
            check(raw == canon, f"{kind}: certification-result.json is canonical bytes + LF")
            check(os.listdir(a["out"]) == ["certification-result.json"],
                  f"{kind}: only the artifact")
            if ck == "converted":
                wid = res["target_binding"]["wrapper_identity"]
                check(wid["assembly_simple_name"] == _WRAP_ASM,
                      f"{kind}: wrapper identity recorded")
                check(res["certification"]["converted_callsites"] == len(Chain(kind).auth.applied),
                      f"{kind}: converted_callsites")
            else:
                check(res["target_binding"]["wrapper_identity"] is None,
                      f"{kind}: manual wrapper_identity null")
                check(res["checks"]["wrapper_identity"] == "not_applicable",
                      f"{kind}: manual wrapper_identity check not_applicable")


def _byte_forms(check) -> None:
    # indented (default), compact, and CRLF candidate/plan encodings all certify when the whole
    # downstream chain was produced from those exact bytes.
    for label, enc in (("indented", lambda o: json.dumps(o, indent=2).encode()),
                       ("compact", lambda o: json.dumps(o, separators=(",", ":")).encode()),
                       ("crlf",
                        lambda o: json.dumps(o, indent=2).encode().replace(b"\n", b"\r\n"))):
        with tempfile.TemporaryDirectory() as tmp:
            base = Chain("converted")
            c = _reencode(enc(base.cands), enc(base.plan), "converted")
            a = c.materialize(tmp)
            try:
                _run(a)
                check(True, f"byte-form {label}: certifies")
            except fc.CertifyError as exc:
                check(False, f"byte-form {label}: {exc.category}: {exc}")


def _reencode(cands_bytes: bytes, plan_bytes: bytes, kind: str) -> Chain:
    """A Chain whose whole downstream chain binds the given (re-encoded) candidate/plan bytes."""
    c = Chain(kind)
    c.cands_bytes = cands_bytes
    c.plan_bytes = plan_bytes
    # candidates canonical-object digest is unchanged (semantic), but the file-byte digests change.
    cs_sha = _sha_bytes(cands_bytes)
    pb = _sha_bytes(plan_bytes)
    man = build_manifest(c.plan, pb, c.rel, c.pre_sha, c.postimage, c.patch)
    c.manifest_data = manifest_bytes(man)
    mb = _sha_bytes(c.manifest_data)
    c._h["validated_plan_sha256"] = pb
    c._h["candidates_sha256"] = cs_sha
    c._h["apply_manifest_sha256"] = mb
    git = "pass" if c.converted else "not_applicable"
    gates = dict.fromkeys(_STEP9_GATE_NAMES, "pass")
    for g in _STEP9_GIT_GATES:
        gates[g] = git
    gate = {"version": 1, "operation": "gate-subscription-fix-bundle",
            "input_bundle_sha256": c._h["input_bundle_sha256"], "validated_plan_sha256": pb,
            "apply_manifest_sha256": mb, "patch_sha256": c._h["patch_sha256"],
            "target_api": {"subscribe": _SUB},
            "source_files": [{"path": c.rel, "pre_sha256": c.pre_sha,
                              "post_sha256": c._h["post_sha256"]}],
            "applied_findings": list(c.auth.applied),
            "manual_review_findings": list(c.auth.manual), "gates": gates}
    c.gate_bytes = _canonical_bytes(gate)
    gb = _sha_bytes(c.gate_bytes)
    c.delta["input_hashes"] = dict(c._h)
    c.delta["gate_binding"]["gate_result_sha256"] = gb
    c.delta_bytes = _canonical_bytes(c.delta)
    db = _sha_bytes(c.delta_bytes)
    c.target["input_hashes"] = dict(c._h)
    c.target["delta_binding"]["delta_result_sha256"] = db
    return c


def _basic_refusals(check) -> None:
    # semantic authority change -> AUTHORITY_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        c = Chain("converted")
        c.cands["target_api"]["subscribe"] = "Evil.Add"
        c.cands_bytes = json.dumps(c.cands, indent=2).encode()
        a = c.materialize(tmp)
        check(_raises(fc.AUTHORITY_BINDING, a), "semantic authority change -> AUTHORITY_BINDING")
    # duplicate JSON object key in candidates -> AUTHORITY_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["candidates"], "rb") as fh:
            raw = fh.read()
        dup = raw.replace(b'"version": 1,', b'"version": 1,\n  "version": 1,', 1)
        with open(a["candidates"], "wb") as fh:
            fh.write(dup)
        check(_raises(fc.AUTHORITY_BINDING, a), "duplicate candidates key -> AUTHORITY_BINDING")
    # malformed candidates JSON -> AUTHORITY_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["candidates"], "wb") as fh:
            fh.write(b"{not json")
        check(_raises(fc.AUTHORITY_BINDING, a), "malformed candidates -> AUTHORITY_BINDING")
    # malformed bundle (patch byte change) -> BUNDLE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(os.path.join(a["bundle"], "change.patch"), "ab") as fh:
            fh.write(b"// x\n")
        check(_raises(fc.BUNDLE_BINDING, a), "patch byte change -> BUNDLE_BINDING")
    # postimage byte change -> BUNDLE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(os.path.join(a["bundle"], "postimage", *_REL.split("/")), "ab") as fh:
            fh.write(b"// x\n")
        check(_raises(fc.BUNDLE_BINDING, a), "postimage byte change -> BUNDLE_BINDING")
    # validated-plan whitespace changed, not rebuilt -> BUNDLE_BINDING (plan-byte digest drift)
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["plan"], "rb") as fh:
            raw = fh.read()
        with open(a["plan"], "wb") as fh:
            fh.write(raw + b" ")
        check(_raises(fc.BUNDLE_BINDING, a),
              "plan whitespace change (no rebuild) -> BUNDLE_BINDING")
    # candidates whitespace changed, not rebuilt -> DELTA_BINDING (candidates-byte digest drift)
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["candidates"], "rb") as fh:
            raw = fh.read()
        with open(a["candidates"], "wb") as fh:
            fh.write(raw + b" ")
        check(_raises(fc.DELTA_BINDING, a),
              "candidates whitespace change (no rebuild) -> DELTA_BINDING")
    # malformed gate -> GATE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["gate"], "wb") as fh:
            fh.write(b"{}\n")
        check(_raises(fc.GATE_BINDING, a), "malformed gate -> GATE_BINDING")
    # malformed delta -> DELTA_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["delta"], "wb") as fh:
            fh.write(b"{}\n")
        check(_raises(fc.DELTA_BINDING, a), "malformed delta -> DELTA_BINDING")
    # malformed target -> TARGET_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["target"], "wb") as fh:
            fh.write(b"{}\n")
        check(_raises(fc.TARGET_BINDING, a), "malformed target -> TARGET_BINDING")
    # foreign gate (from another chain) -> GATE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        other = Chain("mixed")
        with open(a["gate"], "wb") as fh:
            fh.write(other.gate_bytes)
        check(_raises(fc.GATE_BINDING, a), "foreign gate -> GATE_BINDING")
    # foreign delta -> DELTA_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        other = Chain("mixed")
        with open(a["delta"], "wb") as fh:
            fh.write(_canonical_bytes(other.delta))
        check(_raises(fc.DELTA_BINDING, a), "foreign delta -> DELTA_BINDING")
    # foreign target -> TARGET_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        other = Chain("mixed")
        with open(a["target"], "wb") as fh:
            fh.write(_canonical_bytes(other.target))
        check(_raises(fc.TARGET_BINDING, a), "foreign target -> TARGET_BINDING")
    # variant mismatch: converted plan, manual-only target -> TARGET_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        man = Chain("manual")
        t = dict(man.target)
        with open(a["target"], "wb") as fh:
            fh.write(_canonical_bytes(t))
        check(_raises(fc.TARGET_BINDING, a), "converted plan + manual target -> TARGET_BINDING")
    # reference: extra ref-dir / wrong count -> REFERENCE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("manual").materialize(tmp)
        extra = os.path.join(tmp, "extra-ref")
        _write(os.path.join(extra, "Z.dll"), b"MZ")
        a["ref_dirs"] = [extra]
        check(_raises(fc.REFERENCE_BINDING, a), "ref count mismatch -> REFERENCE_BINDING")
    # reference content mismatch -> REFERENCE_BINDING
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(os.path.join(a["ref_dirs"][0], "WeakEvents.dll"), "wb") as fh:
            fh.write(b"DIFFERENT")
        check(_raises(fc.REFERENCE_BINDING, a), "ref content mismatch -> REFERENCE_BINDING")


def _publication(check) -> None:
    # an existing OUTPUT_DIR is refused and left unchanged
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        os.makedirs(a["out"])
        with open(os.path.join(a["out"], "sentinel"), "wb") as fh:
            fh.write(b"keep")
        check(_raises(fc.PUBLICATION, a), "existing OUTPUT_DIR -> PUBLICATION")
        check(os.listdir(a["out"]) == ["sentinel"], "existing OUTPUT_DIR left unchanged")
    # a refusal leaves an absent OUTPUT_DIR absent
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        with open(a["gate"], "wb") as fh:
            fh.write(b"{}\n")
        _raises(fc.GATE_BINDING, a)
        check(not os.path.exists(a["out"]), "refusal leaves OUTPUT_DIR absent")


# Deep representable + isolation groups are populated in the next commit.
def _deep_representable(check) -> None:
    return


def _isolation(check) -> None:
    return


if __name__ == "__main__":
    raise SystemExit(run())
