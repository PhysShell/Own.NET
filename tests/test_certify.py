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
from ownlang import fix_delta as fd
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

# The contract's expected published values, stated LITERALLY in the test (never imported from the
# module under test, so a simultaneous drift of production + test cannot self-confirm an amnesia).
_EXPECT_CLAIMS = ["evidence_chain_hash_bound_and_canonical",
                  "representable_internal_invariants_revalidated",
                  "upstream_pass_results_bound_not_reexecuted",
                  "preimage_digest_cross_artifact_bound_bytes_not_supplied"]
_EXPECT_CHECKS = {"input_layout", "authority_binding", "bundle_binding", "gate_binding",
                  "delta_binding", "target_binding", "reference_binding", "preimage_binding",
                  "chain_consistency", "canonical_serialization", "wrapper_identity", "publication"}

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
    # event is the bridge-key event: source "a" + "." + candidate event "PropertyChanged", and
    # component is the candidate's containing_type simple name "A" — exactly what the frozen core
    # runner derives, so the Step-12-local R_C bridge maps each candidate onto its observation.
    return {"file": _REL, "code": "OWN001", "component": "A", "event": "a.PropertyChanged",
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
    """A mutable, internally-consistent six-artifact evidence chain. The PRIMITIVES (candidate/plan
    bytes, patch, postimage, ref slots) are set in __init__; ``_seal`` recomputes every downstream
    hash, the gate, the delta and the target from those primitives, so a test can tamper a primitive
    and re-seal to get a still-hash-consistent chain. ``materialize`` serializes to a fresh tree."""

    def __init__(self, kind: str, empty_refs: int = 0) -> None:
        self.kind = kind
        self.empty_refs = empty_refs
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
        self.pre = _PRE
        self.pre_sha = _sha_bytes(self.pre)
        self.postimage = _POST if self.converted else _PRE
        self.patch = canonical_patch(self.rel, self.pre, self.postimage)
        self.ref_slots = [("WeakEvents.dll", _WRAP_DLL)] if self.converted else []
        self._seal()

    def _seal(self) -> None:
        """Recompute the manifest, the seven hashes, the gate, the delta and the target from the
        current primitive bytes — so a mutation of a primitive stays internally hash-consistent."""
        cb = _bundle_sha256(self.cands)
        pb = _sha_bytes(self.plan_bytes)
        man = build_manifest(self.plan, pb, self.rel, self.pre_sha, self.postimage, self.patch)
        self.manifest_data = manifest_bytes(man)
        po = _sha_bytes(self.postimage)
        self._h = {"input_bundle_sha256": cb, "validated_plan_sha256": pb,
                   "candidates_sha256": _sha_bytes(self.cands_bytes),
                   "apply_manifest_sha256": _sha_bytes(self.manifest_data),
                   "patch_sha256": _sha_bytes(self.patch), "pre_sha256": self.pre_sha,
                   "post_sha256": po}

        git = "pass" if self.converted else "not_applicable"
        gates = dict.fromkeys(_STEP9_GATE_NAMES, "pass")
        for g in _STEP9_GIT_GATES:
            gates[g] = git
        gate = {"version": 1, "operation": "gate-subscription-fix-bundle",
                "input_bundle_sha256": cb, "validated_plan_sha256": pb,
                "apply_manifest_sha256": self._h["apply_manifest_sha256"],
                "patch_sha256": self._h["patch_sha256"], "target_api": {"subscribe": _SUB},
                "source_files": [{"path": self.rel, "pre_sha256": self.pre_sha, "post_sha256": po}],
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
        ref_count = len(self.ref_slots) + self.empty_refs
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
                    "probe_runner_sha256": _PROBE_FILES[0]["sha256"], "probe_files": _PROBE_FILES,
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
                "attempts": [_attempt(i) for i in range(3)],
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
        for j in range(self.empty_refs):
            rd = os.path.join(indir, f"ref-empty-{j}")
            os.makedirs(rd, exist_ok=True)
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
    except Exception:
        return False  # any uncaught exception is a wrong outcome (e.g. a leaked UnicodeEncodeError)
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
    _defect_regressions(check)
    _r_round(check)
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
            check(res["certification"]["claims"] == _EXPECT_CLAIMS,
                  f"{kind}: exact claims array")
            check("steps_8_11_gates_satisfied" not in json.dumps(res),
                  f"{kind}: no steps_8_11_gates_satisfied anywhere")
            check(set(res["checks"]) == _EXPECT_CHECKS and len(res["checks"]) == 12,
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
    """A Chain whose whole downstream chain binds the given (re-encoded) candidate/plan bytes. The
    candidates canonical-object digest is unchanged (semantic), but the file-byte digests change, so
    re-sealing rebuilds every downstream hash from the actual bytes."""
    c = Chain(kind)
    c.cands_bytes = cands_bytes
    c.plan_bytes = plan_bytes
    c._seal()
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


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _sync_delta(c: Chain) -> None:
    """Keep the target bound to the (possibly mutated) delta so a delta mutation surfaces as a
    delta-representable refusal, not an incidental target hash mismatch."""
    c.target["delta_binding"]["delta_result_sha256"] = _sha_bytes(_canonical_bytes(c.delta))


def _mut(check, kind: str, label: str, expect: str, mut) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        c = Chain(kind)
        mut(c)
        _sync_delta(c)
        a = c.materialize(tmp)
        check(_raises(expect, a), label)


def _deep_representable(check) -> None:
    # OBS001.advisory: a genuine boolean certifies; a string or null is DELTA_BINDING.
    with tempfile.TemporaryDirectory() as tmp:
        c = Chain("converted")
        c.delta["baseline"]["all_own001"][0]["advisory"] = False
        _sync_delta(c)
        a = c.materialize(tmp)
        try:
            _run(a)
            check(True, "advisory false certifies")
        except fc.CertifyError as exc:
            check(False, f"advisory false: {exc.category}")

    def set_adv(v):
        def _f(c: Chain) -> None:
            c.delta["baseline"]["all_own001"][0]["advisory"] = v
        return _f
    _mut(check, "converted", 'advisory "false" (string) -> DELTA_BINDING', fc.DELTA_BINDING,
         set_adv("false"))
    _mut(check, "converted", "advisory null -> DELTA_BINDING", fc.DELTA_BINDING, set_adv(None))

    # a violated Step 10 subscription equation -> DELTA_BINDING.
    def break_eq(c: Chain) -> None:
        c.delta["delta"]["removed_subscription_own001_ids"] = []
    _mut(check, "converted", "removed-subscription equation violated -> DELTA_BINDING",
         fc.DELTA_BINDING, break_eq)

    # a core-multiset equation: a new postimage OWN001 that was never in the baseline.
    def new_core(c: Chain) -> None:
        c.delta["postimage"]["all_own001"] = _sorted_multiset([_obs("Ghost")])
    _mut(check, "converted", "new postimage OWN001 -> DELTA_BINDING", fc.DELTA_BINDING, new_core)

    # deterministic observation ordering: baseline.all_own001 not in canonical order.
    def unsorted(c: Chain) -> None:
        c.delta["baseline"]["all_own001"] = list(reversed(c.delta["baseline"]["all_own001"]))
    _mut(check, "mixed", "unsorted baseline observations -> DELTA_BINDING", fc.DELTA_BINDING,
         unsorted)

    # the self-describing toolchain-manifest digests (O4).
    def bad_ext(c: Chain) -> None:
        c.delta["toolchain_fingerprint"]["extractor_deployment_manifest_sha256"] = \
            "sha256:" + "0" * 64
    _mut(check, "converted", "extractor manifest digest mismatch -> DELTA_BINDING",
         fc.DELTA_BINDING, bad_ext)

    def bad_ownlang(c: Chain) -> None:
        c.delta["toolchain_fingerprint"]["core_analyzer"]["ownlang_manifest_sha256"] = \
            "sha256:" + "0" * 64
    _mut(check, "converted", "ownlang manifest digest mismatch -> DELTA_BINDING",
         fc.DELTA_BINDING, bad_ownlang)

    def bad_probe(c: Chain) -> None:
        c.target["probe_toolchain_fingerprint"]["probe_deployment_manifest_sha256"] = \
            "sha256:" + "0" * 64
    _mut(check, "converted", "probe manifest digest mismatch -> TARGET_BINDING",
         fc.TARGET_BINDING, bad_probe)

    # converted-target controls + the recomputed attempt verdict.
    def deliver_two(c: Chain) -> None:
        c.target["attempts"][0]["delivered_count"] = 2  # verdict field left stale at "pass"
    _mut(check, "converted", "attempt delivered_count 2 (rehashed) -> TARGET_BINDING",
         fc.TARGET_BINDING, deliver_two)

    def broken_control(c: Chain) -> None:
        c.target["attempts"][1]["strong_retained"] = False
    _mut(check, "converted", "broken strong control -> TARGET_BINDING", fc.TARGET_BINDING,
         broken_control)

    def verdict_mismatch(c: Chain) -> None:
        c.target["attempts"][2]["verdict"] = "TARGET_RETAINS"  # fields still say pass
    _mut(check, "converted", "published verdict != recomputed -> TARGET_BINDING",
         fc.TARGET_BINDING, verdict_mismatch)

    # converted callsite / selected-wrapper invariants.
    def bad_callsites(c: Chain) -> None:
        c.target["callsite_binding"]["all_callsites_same_symbol"] = False
    _mut(check, "converted", "all_callsites_same_symbol false -> TARGET_BINDING",
         fc.TARGET_BINDING, bad_callsites)

    def bad_ordinal(c: Chain) -> None:
        c.target["callsite_binding"]["derived_wrapper_ordinal"] = 1
    _mut(check, "converted", "derived != asserted ordinal -> TARGET_BINDING", fc.TARGET_BINDING,
         bad_ordinal)

    def bad_wrapper_sha(c: Chain) -> None:
        c.target["selected_wrapper"]["sha256"] = "sha256:" + "e" * 64
    _mut(check, "converted", "selected wrapper sha != slot -> TARGET_BINDING", fc.TARGET_BINDING,
         bad_wrapper_sha)


def _bound(tmp: str, c: Chain | None = None):
    """Materialize a (converted, by default) chain and bind it up to the reference closure,
    returning the exact argument vector fc.revalidate_certification_inputs is called with."""
    if c is None:
        c = Chain("converted")
    a = c.materialize(tmp)
    pb, cb = _read(a["plan"]), _read(a["candidates"])
    gb, dbb, tbb = _read(a["gate"]), _read(a["delta"]), _read(a["target"])
    binfo = fc.bind_certification_bundle(a["bundle"], c.rel, c.plan, pb, c.pre_sha, c.converted)
    work = os.path.join(tmp, "revwork")
    os.makedirs(work)
    slot_dirs, slot_ev = fd.snapshot_reference_closure(work, a["ref_dirs"])
    args = (a["plan"], a["candidates"], a["gate"], a["delta"], a["target"], binfo["bundle_phys"],
            c.rel, a["ref_dirs"], pb, cb, gb, dbb, tbb, binfo["manifest_data"],
            binfo["patch_bytes"], binfo["postimage_bytes"], work, slot_dirs, slot_ev)
    return c, a, args, binfo


def _raises_call(cat: str, fn, *a) -> bool:
    try:
        fn(*a)
    except fc.CertifyError as exc:
        return exc.category == cat
    except Exception:
        return False
    return False


def _isolation(check) -> None:
    # the no-drift baseline passes.
    with tempfile.TemporaryDirectory() as tmp:
        _c, _a, args, _b = _bound(tmp)
        try:
            fc.revalidate_certification_inputs(*args)
            check(True, "revalidate: no drift passes")
        except fc.CertifyError as exc:
            check(False, f"revalidate: false drift ({exc.category})")

    # a plain input file changing after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp)
        with open(a["delta"], "ab") as fh:
            fh.write(b" ")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "input byte drift after binding -> ISOLATION")

    # the ORIGINAL bundle manifest changing after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp)
        with open(os.path.join(a["bundle"], "apply-manifest.json"), "ab") as fh:
            fh.write(b" ")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "original manifest drift -> ISOLATION")

    # a decoy file added to the original bundle after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp)
        with open(os.path.join(a["bundle"], "decoy.txt"), "wb") as fh:
            fh.write(b"x")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "original bundle decoy file -> ISOLATION")

    # an original --ref-dir DLL changing after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp)
        with open(os.path.join(a["ref_dirs"][0], "WeakEvents.dll"), "ab") as fh:
            fh.write(b"X")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "original ref-dir DLL drift -> ISOLATION")

    # a DLL removed from an original --ref-dir after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp)
        os.remove(os.path.join(a["ref_dirs"][0], "WeakEvents.dll"))
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "original ref-dir DLL removed -> ISOLATION")

    # a materialized reference slot changing after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, _a, args, _b = _bound(tmp)
        slot_dirs = args[17]
        with open(os.path.join(slot_dirs[0], "WeakEvents.dll"), "ab") as fh:
            fh.write(b"X")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "materialized slot drift -> ISOLATION")

    # a DLL added to an ORIGINALLY-EMPTY --ref-dir after binding is ISOLATION.
    with tempfile.TemporaryDirectory() as tmp:
        _c, a, args, _b = _bound(tmp, Chain("converted", empty_refs=1))
        empty = next(d for d in a["ref_dirs"] if "ref-empty" in d)
        with open(os.path.join(empty, "Sneaky.dll"), "wb") as fh:
            fh.write(b"MZ")
        check(_raises_call(fc.ISOLATION, fc.revalidate_certification_inputs, *args),
              "DLL added to an originally-empty ref-dir -> ISOLATION")


def _mut_primitive(check, kind: str, label: str, expect: str, mut) -> None:
    """Mutate a PRIMITIVE (patch / postimage) then re-seal, so the tampered chain stays internally
    hash-consistent and only the intended representable invariant is violated."""
    with tempfile.TemporaryDirectory() as tmp:
        c = Chain(kind)
        mut(c)
        c._seal()
        a = c.materialize(tmp)
        check(_raises(expect, a), label)


def _surrogate_case(check, which: str, expect: str) -> None:
    """Inject a lone surrogate into an existing string of one artifact, written ascii-escaped (valid
    JSON bytes that parse back to a lone-surrogate str). The certifier must refuse in the artifact's
    own binding category, never leak a UnicodeEncodeError out as INFRASTRUCTURE."""
    with tempfile.TemporaryDirectory() as tmp:
        c = Chain("converted")
        a = c.materialize(tmp)
        source = {"candidates": c.cands_bytes, "gate": c.gate_bytes,
                  "delta": c.delta_bytes, "target": _canonical_bytes(c.target)}[which]
        obj = json.loads(source)
        obj["target_api"]["subscribe"] = obj["target_api"]["subscribe"] + "\ud800"
        data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        with open(a[which], "wb") as fh:
            fh.write(data)
        check(_raises(expect, a), f"lone surrogate in {which} -> {expect}")


def _defect_regressions(check) -> None:
    # --- delta.gate_binding is a closed schema (bound / step9_operation / step9_version) ---
    def gb_set(key, value):
        def _f(c: Chain) -> None:
            c.delta["gate_binding"][key] = value
        return _f
    _mut(check, "converted", "gate_binding bound=false -> DELTA_BINDING", fc.DELTA_BINDING,
         gb_set("bound", False))
    _mut(check, "converted", "gate_binding wrong step9_operation -> DELTA_BINDING",
         fc.DELTA_BINDING, gb_set("step9_operation", "x"))
    _mut(check, "converted", "gate_binding step9_version=2 -> DELTA_BINDING", fc.DELTA_BINDING,
         gb_set("step9_version", 2))
    _mut(check, "converted", "gate_binding extra key -> DELTA_BINDING", fc.DELTA_BINDING,
         gb_set("forged", True))

    # --- target.delta_binding is a closed schema ---
    def tdb_extra(c: Chain) -> None:
        c.target["delta_binding"]["forged"] = True
    _mut(check, "converted", "target.delta_binding extra key -> TARGET_BINDING", fc.TARGET_BINDING,
         tdb_extra)

    # --- Step 10 toolchain scalar types ---
    def tfp_set(path, value):
        def _f(c: Chain) -> None:
            node = c.delta["toolchain_fingerprint"]
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = value
        return _f
    _mut(check, "converted", "core_runner_sha256=null -> DELTA_BINDING", fc.DELTA_BINDING,
         tfp_set(["core_analyzer", "core_runner_sha256"], None))
    _mut(check, "converted", "python_version=[] -> DELTA_BINDING", fc.DELTA_BINDING,
         tfp_set(["core_analyzer", "python_version"], []))
    _mut(check, "converted", "dotnet_version=int -> DELTA_BINDING", fc.DELTA_BINDING,
         tfp_set(["dotnet_version"], 1))
    _mut(check, "converted", "dotnet_host_sha256 malformed -> DELTA_BINDING", fc.DELTA_BINDING,
         tfp_set(["dotnet_host_sha256"], "nothex"))

    # --- canonical-rel path in the self-manifests (recompute the digest so ONLY rel is wrong) ---
    def ext_rel(c: Chain) -> None:
        files = [{"path": "../evil.dll", "sha256": "sha256:" + "1" * 64}]
        c.delta["toolchain_fingerprint"]["extractor_files"] = files
        c.delta["toolchain_fingerprint"]["extractor_deployment_manifest_sha256"] = _mfp(files)
    _mut(check, "converted", "extractor_files non-canonical path -> DELTA_BINDING",
         fc.DELTA_BINDING, ext_rel)

    def probe_rel(c: Chain) -> None:
        files = [{"path": "../evil.dll", "sha256": "sha256:" + "4" * 64}]
        ptf = c.target["probe_toolchain_fingerprint"]
        ptf["probe_files"] = files
        ptf["probe_deployment_manifest_sha256"] = _mfp(files)
        ptf["probe_runner_sha256"] = files[0]["sha256"]
    _mut(check, "converted", "probe_files non-canonical path -> TARGET_BINDING", fc.TARGET_BINDING,
         probe_rel)

    # --- probe_runner_sha256 must be a probe deployment file digest ---
    def probe_runner_foreign(c: Chain) -> None:
        c.target["probe_toolchain_fingerprint"]["probe_runner_sha256"] = "sha256:" + "e" * 64
    _mut(check, "converted", "probe_runner not in probe_files -> TARGET_BINDING", fc.TARGET_BINDING,
         probe_runner_foreign)

    # --- Step 11 runtime identity must equal the Step 10 runtime identity ---
    def rt_sha(c: Chain) -> None:
        c.target["probe_runtime_identity"]["selected_runtime_manifest_sha256"] = \
            "sha256:" + "e" * 64
    _mut(check, "converted", "probe runtime manifest != Step 10 -> TARGET_BINDING",
         fc.TARGET_BINDING, rt_sha)

    def rt_fw(c: Chain) -> None:
        c.target["probe_runtime_identity"]["framework_name"] = "Other.App"
    _mut(check, "converted", "probe runtime framework != Step 10 -> TARGET_BINDING",
         fc.TARGET_BINDING, rt_fw)

    # --- selected_wrapper.ordinal must be an exact int (the False == 0 trap) ---
    def bool_ordinal(c: Chain) -> None:
        c.target["selected_wrapper"]["ordinal"] = False
    _mut(check, "converted", "selected_wrapper.ordinal=false -> TARGET_BINDING", fc.TARGET_BINDING,
         bool_ordinal)

    # --- a manual-only chain must be a real no-op bundle ---
    def manual_nonempty_patch(c: Chain) -> None:
        c.patch = b"diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b\n"
    _mut_primitive(check, "manual", "manual-only nonempty patch -> BUNDLE_BINDING",
                   fc.BUNDLE_BINDING, manual_nonempty_patch)

    def manual_post_ne_pre(c: Chain) -> None:
        c.postimage = _PRE + b"// drift\n"
        c.patch = b""
    _mut_primitive(check, "manual", "manual-only post != pre -> BUNDLE_BINDING", fc.BUNDLE_BINDING,
                   manual_post_ne_pre)

    # --- a lone surrogate is refused in the artifact's own source-specific category ---
    _surrogate_case(check, "candidates", fc.AUTHORITY_BINDING)
    _surrogate_case(check, "gate", fc.GATE_BINDING)
    _surrogate_case(check, "delta", fc.DELTA_BINDING)
    _surrogate_case(check, "target", fc.TARGET_BINDING)


def _r2_args(tmp: str):
    """The `_revalidate_originals` argument vector (the originals-only boundary) built from a bound
    converted chain, with a fresh scratch dir for the ref-dir closure re-derivation."""
    c, a, args, _b = _bound(tmp)
    scratch = os.path.join(tmp, "r2reval")
    return c, a, (*args[:16], args[18], scratch)


def _r_round(check) -> None:
    # R1: removed_all_own001 must equal the bridge-authorized R_C — an unrelated (non-subscription)
    # core OWN001 that also disappeared, honestly listed and matching baseline - postimage, must
    # still be refused because it is not authorized for conversion.
    def unrelated_removed(c: Chain) -> None:
        ghost = _obs("GhostUnrelated")
        c.delta["baseline"]["all_own001"] = _sorted_multiset(
            [*c.delta["baseline"]["all_own001"], ghost])
        c.delta["delta"]["removed_all_own001"] = _sorted_multiset(
            [*c.delta["delta"]["removed_all_own001"], ghost])
    _mut(check, "converted", "unrelated OWN001 also removed -> DELTA_BINDING (R_C authorization)",
         fc.DELTA_BINDING, unrelated_removed)

    # R2 (originals-only boundary): a no-drift baseline passes; an original input / bundle / ref-dir
    # drift is ISOLATION. (Guarded on the boundary function so this reports one red rather than
    # aborting when the function is absent.)
    if not hasattr(fc, "_revalidate_originals"):
        check(False, "R2 originals: _revalidate_originals boundary not implemented")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            _c, _a, oargs = _r2_args(tmp)
            try:
                fc._revalidate_originals(*oargs)
                check(True, "R2 originals: no drift passes")
            except Exception as exc:
                check(False, f"R2 originals: false drift ({exc})")
        for label, drifter in (
            ("candidates", lambda a: a["candidates"]),
            ("bundle patch", lambda a: os.path.join(a["bundle"], "change.patch")),
            ("ref-dir DLL", lambda a: os.path.join(a["ref_dirs"][0], "WeakEvents.dll")),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                _c, a, oargs = _r2_args(tmp)
                with open(drifter(a), "ab") as fh:
                    fh.write(b"X")
                check(_raises_call(fc.ISOLATION, fc._revalidate_originals, *oargs),
                      f"R2 originals: {label} drift -> ISOLATION")

    # R2 (wired): a privileged mutation of an authoritative input AFTER the first revalidation but
    # before the rename is caught by the pre-rename boundary — proved end to end by mutating an
    # input from inside a publish wrapper.
    with tempfile.TemporaryDirectory() as tmp:
        a = Chain("converted").materialize(tmp)
        real_pub = fc.publish_certification

        def wrap(out, protected, ev, pre_rename=None):
            with open(a["delta"], "ab") as fh:
                fh.write(b" ")
            if pre_rename is None:
                return real_pub(out, protected, ev)
            return real_pub(out, protected, ev, pre_rename)
        try:
            fc.publish_certification = wrap
            check(_raises(fc.ISOLATION, a),
                  "R2: input drift before the rename -> ISOLATION (pre-rename boundary)")
        finally:
            fc.publish_certification = real_pub


if __name__ == "__main__":
    raise SystemExit(run())
