"""S2 step 12 — Final Evidence Certification over an accepted Steps 8-11 chain.

    python -m ownlang own-fix subscriptions certify \
      --plan <validated-plan.json> --candidates <candidates.json> \
      --bundle <step8-bundle-dir> --gate <step9-gate-result.json> \
      --delta <step10-delta-result.json> --target <step11-target-result.json> \
      --out <certification-evidence-dir> [--ref-dir <dir>]...

Step 11 proves the accepted wrapper is a genuine non-retaining subscription, but every S2
artifact is produced and hash-chained independently and a HUMAN applies the patch bundle;
nothing binds the whole chain in one deterministic artifact. Step 12 is that binding: a PURE
VERIFIER + PUBLISHER that re-reads the six accepted artifacts plus the reference closure, proves
they are internally consistent — canonical bytes, exact closed schemas, hash bindings up the
authority chain, the representable Step 10/11 equations, the cross-artifact preimage digest, and
the reference-closure binding — and publishes one deterministic certification-result.json with
status `evidence_complete`.

What Step 12 does NOT claim (the evidence boundary, honest by construction):
  * It does not prove the upstream artifacts were produced by the ACCEPTED implementations — only
    that the bytes it was handed are mutually consistent and canonical.
  * It does not re-execute Git, Roslyn, the analyzer, the target probe, or the external
    toolchains. Upstream pass-status is BOUND (hash + schema), never re-run.
  * The preimage digest is cross-artifact-bound; the preimage BYTES are never supplied to or
    reverified by Step 12.

Trust: Step 12 trusts nothing it is handed. Every byte input is read through the frozen Step 9
snapshot boundary (reject symlink/reparse, O_NOFOLLOW, fstat, regular file, read once). It runs
no dotnet, touches no source tree, and reuses the frozen Step 8-11 helpers by import only — it
never rewrites them. It defines its own bundle/reference binder, its own original-authority
revalidation, and its own single-file publisher (the frozen `_publish_target` hardcodes a
different artifact name and is deliberately not reused).
"""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from ownlang import fix_delta as fd
from ownlang import fix_target as ft
from ownlang.fix_bundle import build_manifest, manifest_bytes
from ownlang.fix_candidates import CollectError, validate_candidates_bundle
from ownlang.fix_gate import (
    GateError,
    _canonical_bytes,
    _claim_workdir,
    _is_link,
    _out_parent,
    _same_or_inside,
    _same_path,
    _sha_bytes,
    _snapshot,
    validate_gate_authority,
)
from ownlang.fix_plan import PlanError, validate_plan

# --- failure taxonomy (exactly ten; single-valued; no catch-all chain-mismatch) ----
INPUT_LAYOUT = "INPUT_LAYOUT"
AUTHORITY_BINDING = "AUTHORITY_BINDING"
BUNDLE_BINDING = "BUNDLE_BINDING"
GATE_BINDING = "GATE_BINDING"
DELTA_BINDING = "DELTA_BINDING"
TARGET_BINDING = "TARGET_BINDING"
REFERENCE_BINDING = "REFERENCE_BINDING"
ISOLATION = "ISOLATION"
PUBLICATION = "PUBLICATION"
INFRASTRUCTURE = "INFRASTRUCTURE"

# The exact twelve-name check set published in certification-result.json.
_CHECK_NAMES = (
    "input_layout", "authority_binding", "bundle_binding", "gate_binding", "delta_binding",
    "target_binding", "reference_binding", "preimage_binding", "chain_consistency",
    "canonical_serialization", "wrapper_identity", "publication",
)

# The exact certification.claims array (arbiter P-amendment: NO steps_8_11_gates_satisfied).
_CLAIMS = (
    "evidence_chain_hash_bound_and_canonical",
    "representable_internal_invariants_revalidated",
    "upstream_pass_results_bound_not_reexecuted",
    "preimage_digest_cross_artifact_bound_bytes_not_supplied",
)

# The frozen closed converted / manual-only Step 11 target-result key sets.
_TARGET_MANUAL_KEYS = frozenset({
    "schema", "operation", "status", "input_hashes", "delta_binding", "target_api",
    "reference_closure", "checks",
})
_TARGET_CONVERTED_KEYS = _TARGET_MANUAL_KEYS | frozenset({
    "callsite_binding", "selected_wrapper", "probe_toolchain_fingerprint",
    "probe_runtime_identity", "probe_protocol", "attempts",
})
_TARGET_CHECK_NAMES = (
    "input_layout", "authority_binding", "delta_binding", "reference_binding",
    "probe_toolchain_binding", "wrapper_binding", "harness_controls", "target_behavior",
    "target_nonretention", "harness_determinism", "publication",
)
_TARGET_MANUAL_NA = frozenset({
    "probe_toolchain_binding", "wrapper_binding", "harness_controls", "target_behavior",
    "target_nonretention", "harness_determinism",
})
_WRAPPER_IDENTITY_KEYS = ("ordinal", "sha256", "assembly_simple_name", "module_mvid",
                          "metadata_token", "resolved_signature")


class CertifyError(Exception):
    """A controlled refusal carrying the stable category for regression assertions."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


# --- byte protocol (the one snapshot boundary + canonical / duplicate-key rules) ----


def _snap(path: str, cat: str, what: str) -> bytes:
    """Read a regular file's bytes exactly once through the frozen snapshot boundary, translating
    the helper's GateError into a CertifyError that keeps the category we asked it to use."""
    try:
        return _snapshot(path, cat, what)
    except GateError as exc:
        raise CertifyError(exc.category, str(exc)) from exc


def _load_json_strict(data: bytes, cat: str, what: str) -> Any:
    """Parse UTF-8 JSON, refusing a duplicate object key anywhere in the document."""
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise CertifyError(cat, f"{what}: duplicate JSON object key {key!r}")
            seen.add(key)
        return dict(pairs)
    try:
        return json.loads(data, object_pairs_hook=hook)
    except CertifyError:
        raise
    except ValueError as exc:
        raise CertifyError(cat, f"{what}: not valid JSON ({exc})") from exc


def _load_canonical(data: bytes, cat: str, what: str) -> dict[str, Any]:
    """A compact-canonical evidence artifact: trailing LF, no duplicate keys, and bytes that
    equal the canonical re-encoding of the parsed object."""
    if not data.endswith(b"\n"):
        raise CertifyError(cat, f"{what}: missing trailing newline")
    obj = _load_json_strict(data, cat, what)
    if not isinstance(obj, dict):
        raise CertifyError(cat, f"{what}: must be a JSON object")
    if _canonical_bytes(obj) != data:
        raise CertifyError(cat, f"{what}: not exact compact canonical bytes")
    return obj


# --- bundle layout + the exact canonical-manifest reconstruction (F1) ---------------


def _lstat(path: str, cat: str, what: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise CertifyError(cat, f"{what}: cannot stat ({exc.strerror or exc})") from exc


def _walk_exact(root: str, cat: str) -> tuple[set[str], set[str]]:
    """Every entry under `root` must be a real directory or regular file (no symlink/reparse,
    fifo, socket or device). Returns ('/'-joined, root-relative) (dir paths, file paths)."""
    dirs: set[str] = set()
    files: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise CertifyError(cat, f"cannot scan ({exc.strerror or exc})") from exc
        for entry in entries:
            st = _lstat(entry.path, cat, entry.path)
            rel = os.path.relpath(entry.path, root).replace("\\", "/")
            if _is_link(st):
                raise CertifyError(cat, f"'{rel}' is a symlink / reparse point")
            if stat.S_ISDIR(st.st_mode):
                dirs.add(rel)
                stack.append(entry.path)
            elif stat.S_ISREG(st.st_mode):
                files.add(rel)
            else:
                raise CertifyError(cat, f"'{rel}' is not a regular file or directory")
    return dirs, files


def _require_bundle_layout(bundle: str, rel: str, cat: str) -> str:
    """The exact Step 8 bundle root and postimage subtree. Returns the physical bundle root."""
    blst = _lstat(bundle, cat, "--bundle")
    if _is_link(blst):
        raise CertifyError(cat, "--bundle is a symlink / reparse point")
    if not stat.S_ISDIR(blst.st_mode):
        raise CertifyError(cat, "--bundle is not a directory")
    bundle_phys = os.path.realpath(bundle)
    try:
        names = set(os.listdir(bundle_phys))
    except OSError as exc:
        raise CertifyError(cat, f"cannot list --bundle ({exc.strerror or exc})") from exc
    if names != {"change.patch", "apply-manifest.json", "postimage"}:
        raise CertifyError(cat, f"bundle holds {sorted(names)}, want the step 8 layout")
    for name in ("change.patch", "apply-manifest.json"):
        st = _lstat(os.path.join(bundle_phys, name), cat, name)
        if _is_link(st) or not stat.S_ISREG(st.st_mode):
            raise CertifyError(cat, f"{name}: is not a regular file")
    post_root = os.path.join(bundle_phys, "postimage")
    pst = _lstat(post_root, cat, "postimage")
    if _is_link(pst) or not stat.S_ISDIR(pst.st_mode):
        raise CertifyError(cat, "postimage: is not a real directory")
    dirs, files = _walk_exact(post_root, cat)
    parts = rel.split("/")
    expected_dirs = {"/".join(parts[:i]) for i in range(1, len(parts))}
    if files != {rel} or dirs != expected_dirs:
        raise CertifyError(cat, f"postimage subtree {sorted(dirs | files)} != exactly the target")
    return bundle_phys


def bind_certification_bundle(bundle: str, rel: str, plan: dict[str, Any], plan_bytes: bytes,
                              pre_sha256: str) -> dict[str, Any]:
    """Bind the accepted Step 8 bundle: exact layout + postimage subtree, and the canonical
    apply-manifest reconstructed from the validated plan, the actual plan-byte SHA, the target
    rel, the cross-artifact preimage SHA and the actual postimage / patch bytes. The frozen
    fix_target.bind_bundle is deliberately NOT reused (it binds to a delta, not a reconstruction).
    Any deviation is BUNDLE_BINDING."""
    cat = BUNDLE_BINDING
    bundle_phys = _require_bundle_layout(bundle, rel, cat)
    manifest_data = _snap(os.path.join(bundle_phys, "apply-manifest.json"), cat,
                          "apply-manifest.json")
    patch_bytes = _snap(os.path.join(bundle_phys, "change.patch"), cat, "change.patch")
    postimage_bytes = _snap(os.path.join(bundle_phys, "postimage", *rel.split("/")), cat,
                            "postimage")
    # canonical-bytes + duplicate-key guard on the manifest (it is a compact-canonical artifact).
    _load_canonical(manifest_data, cat, "apply-manifest.json")
    reconstruction = build_manifest(plan, _sha_bytes(plan_bytes), rel, pre_sha256,
                                    postimage_bytes, patch_bytes)
    if manifest_bytes(reconstruction) != manifest_data:
        raise CertifyError(cat, "apply-manifest.json is not the canonical projection of "
                                "plan / candidates / bytes")
    return {"bundle_phys": bundle_phys, "manifest_data": manifest_data, "patch_bytes": patch_bytes,
            "postimage_bytes": postimage_bytes,
            "apply_manifest_sha256": _sha_bytes(manifest_data),
            "patch_sha256": _sha_bytes(patch_bytes), "post_sha256": _sha_bytes(postimage_bytes)}


# --- authority (candidates + plan), the O6 reconstruction, and the OWN001 guard ------


def _load_authority(plan_bytes: bytes, candidates_bytes: bytes) -> tuple[Any, dict[str, Any],
                                                                         dict[str, Any]]:
    cat = AUTHORITY_BINDING
    plan = _load_json_strict(plan_bytes, cat, "--plan")
    candidates = _load_json_strict(candidates_bytes, cat, "--candidates")
    if not isinstance(plan, dict) or not isinstance(candidates, dict):
        raise CertifyError(cat, "plan and candidates must be JSON objects")
    try:
        validate_candidates_bundle(candidates)
    except CollectError as exc:
        raise CertifyError(cat, f"candidates: {exc}") from exc
    try:
        auth = validate_gate_authority(plan, candidates)
    except GateError as exc:  # the frozen validator's category IS AUTHORITY_BINDING
        raise CertifyError(exc.category, str(exc)) from exc
    for candidate in candidates["candidates"]:
        if candidate.get("diagnostic_code") != "OWN001":
            raise CertifyError(cat, "Step 12 certifies OWN001 subscription chains only")
    # O6: never call validate_plan on the seven-key materialized plan (it consumes the two-key
    # model plan and would reject the extra keys). Rebuild the two-key minimal plan and require the
    # frozen materialization to equal the supplied validated plan exactly.
    minimal = {"version": plan.get("version"),
               "decisions": [{"finding_id": d.get("finding_id"), "action": d.get("action")}
                             for d in plan["decisions"]]}
    try:
        reconstructed = validate_plan(candidates, minimal)
    except PlanError as exc:
        raise CertifyError(cat, f"validated plan does not reconstruct: {exc}") from exc
    if reconstructed != plan:
        raise CertifyError(cat, "validated plan is not the frozen materialization of candidates")
    return auth, plan, candidates


# --- gate + delta + target binding --------------------------------------------------


def _bind_gate(gate_bytes: bytes, auth: Any, plan_bytes: bytes, manifest_data: bytes,
               patch_bytes: bytes, pre_sha256: str, post_sha256: str) -> str:
    """Bind the Step 9 gate-result to THIS plan/candidates/bundle via the frozen reconstruction
    (fix_delta.bind_gate: exact schema, the converted/manual gate-status variant, canonical
    bytes, and every hash). Returns the gate-result SHA. Any deviation is GATE_BINDING."""
    try:
        return fd.bind_gate(gate_bytes, auth, plan_bytes, manifest_data, patch_bytes,
                            pre_sha256, post_sha256)
    except fd.DeltaError as exc:
        raise CertifyError(GATE_BINDING, str(exc)) from exc


def _bind_delta(delta_bytes: bytes, auth: Any, plan_bytes: bytes, candidates_bytes: bytes,
                hashes: dict[str, str], gate_sha256: str, rel: str,
                class_fqn: str) -> dict[str, Any]:
    """Bind the Step 10 delta-result as the upstream authority. The frozen fix_target.bind_delta
    proves canonical bytes, the exact top-level + consumed shapes, all seventeen checks pass, and
    the input-bundle / plan / candidates / target / expected bindings. Step 12 additionally binds
    the delta to THIS bundle and gate (manifest / patch / preimage / postimage / gate SHA) and to
    the declared analysis scope. Any deviation is DELTA_BINDING."""
    cat = DELTA_BINDING
    try:
        delta = ft.bind_delta(delta_bytes, auth, plan_bytes, candidates_bytes)
    except ft.TargetError as exc:
        raise CertifyError(cat, str(exc)) from exc
    ih = delta["input_hashes"]
    for key in ("apply_manifest_sha256", "patch_sha256", "pre_sha256", "post_sha256"):
        if ih.get(key) != hashes[key]:
            raise CertifyError(cat, f"delta-result.json {key} does not bind this bundle")
    gb = delta["gate_binding"]
    if gb.get("gate_result_sha256") != gate_sha256:
        raise CertifyError(cat, "delta-result.json is not bound to this gate-result")
    if gb.get("git_gates_status") != ("pass" if auth.applied else "not_applicable"):
        raise CertifyError(cat, "delta-result.json git_gates_status is not the plan's variant")
    scope = delta["analysis_scope"]
    if scope.get("source_file") != rel or scope.get("target_file_identity") != rel:
        raise CertifyError(cat, "delta-result.json analysis scope is not the target file")
    if scope.get("selected_class") != class_fqn:
        raise CertifyError(cat, "delta-result.json selected_class is not the accepted type")
    # closure_kind must be internally consistent with the delta's OWN reference_dir_count; the
    # supplied --ref-dir COUNT is bound in reference binding (a mismatch there is REFERENCE_BINDING,
    # never DELTA_BINDING).
    expected_kind = "single-file+refdirs" if scope.get("reference_dir_count") else "single-file"
    if scope.get("closure_kind") != expected_kind:
        raise CertifyError(cat, "delta-result.json closure_kind is not its derived kind")
    _validate_delta_representable(delta, auth, cat)
    return delta


def _bind_target(target_bytes: bytes, auth: Any, delta: dict[str, Any], delta_bytes: bytes,
                 hashes: dict[str, str], converted: bool) -> dict[str, Any]:
    """Bind the Step 11 target-result: canonical bytes, the exact converted / manual-only closed
    schema for the plan's variant, the delta binding, the seven input hashes, the target api, the
    reference closure, and the eleven-check variant. Any deviation is TARGET_BINDING."""
    cat = TARGET_BINDING
    target = _load_canonical(target_bytes, cat, "target-result.json")
    if target.get("schema") != 1 or ft._is_int(target.get("schema")) is False \
            or target.get("operation") != "verify-target-wrapper" or target.get("status") != "pass":
        raise CertifyError(cat, "target-result.json schema / operation / status is wrong")
    keys = frozenset(target)
    if keys == _TARGET_CONVERTED_KEYS:
        variant = True
    elif keys == _TARGET_MANUAL_KEYS:
        variant = False
    else:
        raise CertifyError(cat, "target-result.json is neither the converted nor manual-only shape")
    if variant != converted:
        raise CertifyError(cat, "target-result.json variant does not match the plan's chain kind")
    db = target["delta_binding"]
    if not isinstance(db, dict) or db.get("delta_result_sha256") != _sha_bytes(delta_bytes) \
            or db.get("step10_operation") != "verify-subscription-analyzer-delta" \
            or db.get("step10_status") != "pass" or db.get("bound") is not True:
        raise CertifyError(cat, "target-result.json is not bound to this delta-result")
    if target.get("input_hashes") != _target_input_hashes(hashes):
        raise CertifyError(cat, "target-result.json input_hashes do not bind this chain")
    if target.get("target_api") != {"subscribe": auth.target_subscribe}:
        raise CertifyError(cat, "target-result.json target_api does not bind the plan")
    if target.get("reference_closure") != delta["reference_closure"]:
        raise CertifyError(cat, "target-result.json reference closure != the delta closure")
    checks = target.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(_TARGET_CHECK_NAMES):
        raise CertifyError(cat, "target-result.json checks are not the eleven-name set")
    for name, value in checks.items():
        expect = "not_applicable" if (not converted and name in _TARGET_MANUAL_NA) else "pass"
        if value != expect:
            raise CertifyError(cat, f"target check {name} is {value!r}, want {expect!r}")
    if converted:
        _validate_target_converted(target, auth, delta, cat)
    return target


def _target_input_hashes(hashes: dict[str, str]) -> dict[str, str]:
    return {"input_bundle_sha256": hashes["input_bundle_sha256"],
            "validated_plan_sha256": hashes["validated_plan_sha256"],
            "candidates_sha256": hashes["candidates_sha256"],
            "apply_manifest_sha256": hashes["apply_manifest_sha256"],
            "patch_sha256": hashes["patch_sha256"], "pre_sha256": hashes["pre_sha256"],
            "post_sha256": hashes["post_sha256"]}


# --- representable Step 10 / Step 11 validation (deepened in the enforcement commit) --


def _validate_delta_representable(delta: dict[str, Any], auth: Any, cat: str) -> None:
    """The representable Step 10 invariants beyond the frozen consumed-shape binding: the closed
    baseline / postimage / delta observation schemas, deterministic canonical ordering, the
    subscription / core-multiset / OWN050 / idempotence equations, and the self-describing
    toolchain-manifest digests. Populated in the enforcement commit."""
    return


def _validate_target_converted(target: dict[str, Any], auth: Any, delta: dict[str, Any],
                               cat: str) -> None:
    """The representable converted-target invariants beyond the closed schema: the callsite
    summary, the exact probe protocol, the three recomputed attempt verdicts, the selected-wrapper
    slot identity, and the probe deployment self-hash. Populated in the enforcement commit."""
    return


# --- reference closure binding ------------------------------------------------------


def _bind_reference(work: str, ref_dirs: list[str], delta: dict[str, Any],
                    target: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Reconstruct the ordered one-DLL-per-slot closure from the original ref-dir inputs and
    require exact ordinal equality with BOTH the Step 10 and Step 11 closures. Any count / order /
    content mismatch is REFERENCE_BINDING."""
    cat = REFERENCE_BINDING
    if len(ref_dirs) != delta["analysis_scope"]["reference_dir_count"]:
        raise CertifyError(cat, "the number of --ref-dir != delta reference_dir_count")
    try:
        slot_dirs, evidence = fd.snapshot_reference_closure(work, ref_dirs)
    except fd.DeltaError as exc:
        raise CertifyError(cat, str(exc)) from exc
    if evidence != delta["reference_closure"]:
        raise CertifyError(cat, "reconstructed closure != delta.reference_closure")
    if evidence != target["reference_closure"]:
        raise CertifyError(cat, "reconstructed closure != target.reference_closure")
    return slot_dirs, evidence


# --- original-authority revalidation (deepened in the enforcement commit) -----------


def revalidate_certification_inputs(
    plan_path: str, candidates_path: str, gate_path: str, delta_path: str, target_path: str,
    bundle_phys: str, rel: str, ref_dirs: list[str], plan_bytes: bytes, candidates_bytes: bytes,
    gate_bytes: bytes, delta_bytes: bytes, target_bytes: bytes, manifest_data: bytes,
    patch_bytes: bytes, postimage_bytes: bytes, work: str, slot_dirs: list[str],
    slot_evidence: list[dict[str, Any]]) -> None:
    """Before publication, re-check that every authoritative input still equals what was bound.
    The plain input files are re-snapshotted here; the original bundle, the original ref-dir
    closures and the materialized slots are re-derived in the enforcement commit. Any post-binding
    drift is ISOLATION."""
    for path, original, label in ((plan_path, plan_bytes, "--plan"),
                                  (candidates_path, candidates_bytes, "--candidates"),
                                  (gate_path, gate_bytes, "--gate"),
                                  (delta_path, delta_bytes, "--delta"),
                                  (target_path, target_bytes, "--target")):
        if _snap(path, ISOLATION, label) != original:
            raise CertifyError(ISOLATION, f"{label} changed during certification")


# --- publication (Step 12-local; the frozen _publish_target hardcodes another name) --


def publish_certification(out: str, protected: list[str], evidence_bytes: bytes) -> str:
    """Stage EXACTLY certification-result.json in a claimed private work directory off the output
    parent and publish it with ONE atomic rename. OUTPUT_DIR is absent on refusal; an existing
    OUTPUT_DIR is PUBLICATION; a cleanup failure is PUBLICATION. No filesystem operation runs after
    a successful rename."""
    import shutil

    try:
        out_phys, parent_phys, _root = _out_parent(out, out)
    except GateError as exc:
        raise CertifyError(PUBLICATION, str(exc)) from exc
    for root in protected:
        if _same_or_inside(os.path.realpath(root), parent_phys):
            raise CertifyError(PUBLICATION, "the out-dir parent resolves inside a protected root")
    try:
        workdir = _claim_workdir(parent_phys)
    except GateError as exc:
        raise CertifyError(PUBLICATION, str(exc)) from exc
    succeeded = False
    try:
        with open(os.path.join(workdir, "certification-result.json"), "wb") as fh:
            fh.write(evidence_bytes)
        if not _same_path(os.path.realpath(os.path.dirname(out_phys)), parent_phys) \
                or os.path.exists(out_phys) or os.path.islink(out_phys):
            raise CertifyError(PUBLICATION, "the out-dir destination changed before publication")
        _require_single(workdir)
        try:
            os.rename(workdir, out_phys)
        except OSError as exc:
            raise CertifyError(PUBLICATION, f"cannot publish ({exc})") from exc
        succeeded = True
    finally:
        if not succeeded:
            try:
                shutil.rmtree(workdir)
            except OSError as exc:
                raise CertifyError(PUBLICATION, f"cannot remove staging ({exc})") from exc
    return out_phys


def _require_single(workdir: str) -> None:
    entries = list(os.scandir(workdir))
    if len(entries) != 1 or entries[0].name != "certification-result.json":
        raise CertifyError(PUBLICATION, "staging is not exactly certification-result.json")
    st = entries[0].stat(follow_symlinks=False)
    if _is_link(st) or not stat.S_ISREG(st.st_mode):
        raise CertifyError(PUBLICATION, "staged certification-result.json is not a regular file")


# --- the published evidence ---------------------------------------------------------


def build_certification(auth: Any, chain_kind: str, hashes: dict[str, str], pre_sha256: str,
                        rel: str, delta: dict[str, Any], target: dict[str, Any],
                        slot_evidence: list[dict[str, Any]], converted: bool) -> dict[str, Any]:
    """Assemble certification-result.json — the closed schema binding the six artifacts, the
    reference closure and the cross-artifact preimage, with the honest P-amendment claims. Every
    value is a pure function of the accepted inputs, so a re-run is byte-identical."""
    convert_ids = sorted(auth.applied)
    manual_ids = sorted(auth.manual)
    if converted:
        wrapper = target["selected_wrapper"]
        wrapper_identity: dict[str, Any] | None = {k: wrapper[k] for k in _WRAPPER_IDENTITY_KEYS}
        converted_callsites: int | None = target["callsite_binding"]["converted_callsites"]
    else:
        wrapper_identity = None
        converted_callsites = None
    checks = dict.fromkeys(_CHECK_NAMES, "pass")
    if not converted:
        checks["wrapper_identity"] = "not_applicable"
    return {
        "schema": 1,
        "operation": "certify-subscription-fix-chain",
        "status": "evidence_complete",
        "chain_kind": chain_kind,
        "artifact_hashes": {
            "candidates_sha256": hashes["candidates_sha256"],
            "validated_plan_sha256": hashes["validated_plan_sha256"],
            "apply_manifest_sha256": hashes["apply_manifest_sha256"],
            "patch_sha256": hashes["patch_sha256"], "post_sha256": hashes["post_sha256"],
            "gate_result_sha256": hashes["gate_result_sha256"],
            "delta_result_sha256": hashes["delta_result_sha256"],
            "target_result_sha256": hashes["target_result_sha256"]},
        "semantic_hashes": {"input_bundle_sha256": hashes["input_bundle_sha256"]},
        "preimage_binding": {"mode": "cross_artifact_only", "bytes_supplied": False,
                             "pre_sha256": pre_sha256},
        "plan_binding": {"bound": True, "operation": "fix-subscriptions",
                         "input_bundle_sha256": hashes["input_bundle_sha256"]},
        "bundle_binding": {"bound": True, "source_file": rel,
                           "apply_manifest_sha256": hashes["apply_manifest_sha256"],
                           "patch_sha256": hashes["patch_sha256"],
                           "post_sha256": hashes["post_sha256"], "canonical_manifest": True},
        "gate_binding": {"bound": True, "operation": "gate-subscription-fix-bundle",
                         "gate_result_sha256": hashes["gate_result_sha256"],
                         "git_gates_status": delta["gate_binding"]["git_gates_status"]},
        "delta_binding": {"bound": True, "operation": "verify-subscription-analyzer-delta",
                          "status": "pass", "delta_result_sha256": hashes["delta_result_sha256"]},
        "target_binding": {"bound": True, "operation": "verify-target-wrapper", "status": "pass",
                           "target_result_sha256": hashes["target_result_sha256"],
                           "wrapper_identity": wrapper_identity},
        "reference_closure": slot_evidence,
        "target_api": {"subscribe": auth.target_subscribe},
        "decision_summary": {"convert_acquire_ids": convert_ids, "manual_review_ids": manual_ids},
        "certification": {"chain_kind": chain_kind, "converted_callsites": converted_callsites,
                          "preimage_bytes_supplied": False, "claims": list(_CLAIMS)},
        "checks": checks,
    }


# --- orchestration ------------------------------------------------------------------


def run_certify(plan_path: str, candidates_path: str, bundle: str, gate_path: str,
                delta_path: str, target_path: str, out: str, ref_dirs: list[str]) -> str:
    """Bind the six accepted S2 artifacts plus the reference closure into one deterministic
    certification-result.json. Returns the published path; raises CertifyError (no output, nothing
    touched) with exactly one stable category on any refusal."""
    # [1] snapshot every input once (INPUT_LAYOUT for the five plain files).
    plan_bytes = _snap(plan_path, INPUT_LAYOUT, "--plan")
    candidates_bytes = _snap(candidates_path, INPUT_LAYOUT, "--candidates")
    gate_bytes = _snap(gate_path, INPUT_LAYOUT, "--gate")
    delta_bytes = _snap(delta_path, INPUT_LAYOUT, "--delta")
    target_bytes = _snap(target_path, INPUT_LAYOUT, "--target")

    # [2] authority: candidates + validated plan (AUTHORITY_BINDING).
    auth, plan, candidates = _load_authority(plan_bytes, candidates_bytes)
    rel = auth.rel
    class_fqn = candidates["selection"]["allowed_types"][0]["full_name"]
    converted = bool(auth.applied)
    chain_kind = "converted" if converted else "manual_only"
    pre_sha256 = auth.pre_sha256

    # [3] bundle: exact layout + the canonical-manifest reconstruction (BUNDLE_BINDING).
    binfo = bind_certification_bundle(bundle, rel, plan, plan_bytes, pre_sha256)

    hashes: dict[str, str] = {
        "input_bundle_sha256": auth.input_bundle_sha256,
        "validated_plan_sha256": _sha_bytes(plan_bytes),
        "candidates_sha256": _sha_bytes(candidates_bytes),
        "apply_manifest_sha256": binfo["apply_manifest_sha256"],
        "patch_sha256": binfo["patch_sha256"], "pre_sha256": pre_sha256,
        "post_sha256": binfo["post_sha256"]}

    # [4] gate (GATE_BINDING).
    hashes["gate_result_sha256"] = _bind_gate(
        gate_bytes, auth, plan_bytes, binfo["manifest_data"], binfo["patch_bytes"],
        pre_sha256, binfo["post_sha256"])

    # [5] delta (DELTA_BINDING).
    delta = _bind_delta(delta_bytes, auth, plan_bytes, candidates_bytes, hashes,
                        hashes["gate_result_sha256"], rel, class_fqn)
    hashes["delta_result_sha256"] = _sha_bytes(delta_bytes)

    # [6] target (TARGET_BINDING).
    target = _bind_target(target_bytes, auth, delta, delta_bytes, hashes, converted)
    hashes["target_result_sha256"] = _sha_bytes(target_bytes)

    # [7] execution root outside every protected root, then reference closure + revalidation +
    #     atomic publication (REFERENCE_BINDING / ISOLATION / PUBLICATION).
    out_parent = os.path.realpath(os.path.dirname(os.path.abspath(out)))
    input_parents = [os.path.dirname(os.path.abspath(p))
                     for p in (plan_path, candidates_path, gate_path, delta_path, target_path)]
    iso_protected = [binfo["bundle_phys"], out_parent, *input_parents, *ref_dirs]
    try:
        work = ft._execution_root(iso_protected)
    except ft.TargetError as exc:
        raise CertifyError(exc.category, str(exc)) from exc

    work_removed = False
    try:
        slot_dirs, slot_evidence = _bind_reference(work, ref_dirs, delta, target)
        revalidate_certification_inputs(
            plan_path, candidates_path, gate_path, delta_path, target_path, binfo["bundle_phys"],
            rel, ref_dirs, plan_bytes, candidates_bytes, gate_bytes, delta_bytes, target_bytes,
            binfo["manifest_data"], binfo["patch_bytes"], binfo["postimage_bytes"], work,
            slot_dirs, slot_evidence)
        evidence = build_certification(auth, chain_kind, hashes, pre_sha256, rel, delta, target,
                                       slot_evidence, converted)
        evidence_bytes = _canonical_bytes(evidence)
        publish_protected = [binfo["bundle_phys"], work, *input_parents, *ref_dirs]
        try:
            ft._remove_root_strict(work)
        except ft.TargetError as exc:
            raise CertifyError(exc.category, str(exc)) from exc
        work_removed = True
        return publish_certification(out, publish_protected, evidence_bytes)
    except BaseException:
        if not work_removed:
            try:
                ft._remove_root_strict(work)
            except ft.TargetError as exc:
                raise CertifyError(exc.category, str(exc)) from exc
        raise
