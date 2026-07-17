"""S2 step 11 — the Verified Target Wrapper gate (the fake-target gate).

    python -m ownlang own-fix subscriptions verify-target \
      --bundle <step8-bundle> --root <pristine-source-root> --plan <validated-plan.json> \
      --candidates <candidates.json> --delta <step10-delta-result.json> \
      --probe-dll <OwnSharp.WeakTargetProbe.dll> --out <target-evidence-dir> \
      [--ref-dir <dir>]... --wrapper-ordinal <N>

Step 10 proves the analyzer stops reporting OWN001 for a converted subscription, but the
analyzer recognizes the replacement wrapper BY NAME only. Step 11 proves the wrapper the
accepted Step 8 postimage actually calls is a genuine non-retaining subscription: it runs a
fixed Roslyn `bind` over the pristine preimage + the accepted postimage (per-finding callsite
bijection), then a fixed runtime `probe` (three fresh isolated children) that loads the derived
wrapper from its exact materialized slot, runs a runtime-compatibility preflight, and proves
the subscriber becomes GC-collectable after a subscribe-then-drop. A wrapper that retains the
subscriber is a fake target and is refused TARGET_RETAINS.

Step 11 reuses the frozen Step 8/9/10 helpers by import and touches NO frozen artifact.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Any, cast

from ownlang.fix_delta import (
    _hash_resolved,
    _manifest_sha,
    _read_runtimeconfig,
    _resolve_dotnet_host,
    _runtime_manifest,
    _select_runtime,
    _walk_regular_files,
)
from ownlang.fix_gate import (
    GateError,
    _canonical_bytes,
    _canonical_json,
    _claim_workdir,
    _is_link,
    _out_parent,
    _same_or_inside,
    _same_path,
    _sha_bytes,
    _snapshot,
    validate_gate_authority,
)

# --- failure taxonomy --------------------------------------------------------------
INPUT_LAYOUT = "INPUT_LAYOUT"
AUTHORITY_BINDING = "AUTHORITY_BINDING"
DELTA_BINDING = "DELTA_BINDING"
REFERENCE_BINDING = "REFERENCE_BINDING"
TOOLCHAIN_BINDING = "TOOLCHAIN_BINDING"
CALLSITE_BINDING = "CALLSITE_BINDING"
WRAPPER_BINDING = "WRAPPER_BINDING"
WRAPPER_RUNTIME_UNSUPPORTED = "WRAPPER_RUNTIME_UNSUPPORTED"
HARNESS_INVALID = "HARNESS_INVALID"
TARGET_BEHAVIOR = "TARGET_BEHAVIOR"
TARGET_RETAINS = "TARGET_RETAINS"
HARNESS_NONDETERMINISM = "HARNESS_NONDETERMINISM"
ISOLATION = "ISOLATION"
PUBLICATION = "PUBLICATION"
INFRASTRUCTURE = "INFRASTRUCTURE"

_CHECK_NAMES = (
    "input_layout", "authority_binding", "delta_binding", "reference_binding",
    "probe_toolchain_binding", "wrapper_binding", "harness_controls", "target_behavior",
    "target_nonretention", "harness_determinism", "publication",
)
_MANUAL_ONLY_NA = (
    "probe_toolchain_binding", "wrapper_binding", "harness_controls", "target_behavior",
    "target_nonretention", "harness_determinism",
)
_STEP10_CHECKS = (
    "input_layout", "authority_binding", "gate_binding", "toolchain_binding",
    "core_analyzer_binding", "analysis_scope", "baseline_authority", "baseline_analysis",
    "postimage_analysis", "analysis_identity", "delta_subscription", "delta_core",
    "new_own001", "new_own050", "semantic_idempotence", "isolation", "publication",
)
_ATTEMPT_COUNT = 3
_COLLECTION_ROUNDS = 5
_ALLOC_PER_ROUND = 4194304
_CHILD_TIMEOUT_SECONDS = 30
_OUT_LIMIT = 65536


class TargetError(Exception):
    """A controlled refusal carrying the stable category for regression assertions."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _canonical(obj: dict[str, Any]) -> bytes:
    return _canonical_bytes(obj)


# --- authority + delta + bundle + reference binding (F1, F2) ------------------------


def load_authority(plan_bytes: bytes, candidates_bytes: bytes) -> tuple[Any, Any, Any]:
    try:
        plan = json.loads(plan_bytes)
        candidates = json.loads(candidates_bytes)
    except ValueError as exc:
        raise TargetError(AUTHORITY_BINDING, f"plan/candidates not valid JSON ({exc})") from exc
    try:
        auth = validate_gate_authority(plan, candidates)
    except GateError as exc:
        raise TargetError(exc.category, str(exc)) from exc
    for c in candidates["candidates"]:
        if c.get("diagnostic_code") != "OWN001":
            raise TargetError(AUTHORITY_BINDING, "candidates carry a non-OWN001 diagnostic")
    return auth, plan, candidates


def bind_delta(delta_bytes: bytes, auth: Any, plan_bytes: bytes,
               candidates_bytes: bytes) -> dict[str, Any]:
    """Bind the Step 10 delta-result.json as the upstream authority (canonical bytes, exact
    schema, all seventeen checks pass, hashes/target/expected bound to THESE inputs)."""
    cat = DELTA_BINDING
    if not delta_bytes.endswith(b"\n"):
        raise TargetError(cat, "delta-result.json is missing its trailing newline")
    try:
        d = json.loads(delta_bytes)
    except ValueError as exc:
        raise TargetError(cat, f"delta-result.json is not valid JSON ({exc})") from exc
    if _canonical_bytes(d) != delta_bytes:
        raise TargetError(cat, "delta-result.json is not canonical bytes")
    if d.get("schema") != 1 or d.get("operation") != "verify-subscription-analyzer-delta" \
            or d.get("status") != "pass":
        raise TargetError(cat, "delta-result.json schema/operation/status is wrong")
    checks = d.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(_STEP10_CHECKS) \
            or set(checks.values()) != {"pass"}:
        raise TargetError(cat, "delta-result.json checks are not the seventeen all-pass set")
    ih = d.get("input_hashes", {})
    if ih.get("input_bundle_sha256") != auth.input_bundle_sha256 \
            or ih.get("validated_plan_sha256") != _sha_bytes(plan_bytes) \
            or ih.get("candidates_sha256") != _sha_bytes(candidates_bytes):
        raise TargetError(cat, "delta-result.json is not bound to these plan/candidates")
    if d.get("target_api", {}).get("subscribe") != auth.target_subscribe:
        raise TargetError(cat, "delta-result.json target_api does not bind the plan")
    if d.get("expected", {}).get("convert_acquire_ids") != sorted(auth.applied) \
            or d.get("expected", {}).get("manual_review_ids") != sorted(auth.manual):
        raise TargetError(cat, "delta-result.json expected ids do not bind the plan")
    return cast("dict[str, Any]", d)


def bind_bundle(bundle: str, root: str, rel: str, delta: dict[str, Any]) -> dict[str, str]:
    """Validate the frozen Step 8 bundle layout and bind its four hashes to the delta (F1)."""
    cat = DELTA_BINDING
    try:
        names = set(os.listdir(bundle))
    except OSError as exc:
        raise TargetError(cat, f"cannot list --bundle ({exc})") from exc
    if names != {"change.patch", "apply-manifest.json", "postimage"}:
        raise TargetError(cat, f"--bundle holds {sorted(names)}, not the step 8 layout")
    manifest = _snapshot(os.path.join(bundle, "apply-manifest.json"), cat, "apply-manifest.json")
    patch = _snapshot(os.path.join(bundle, "change.patch"), cat, "change.patch")
    postimage = _snapshot(os.path.join(bundle, "postimage", *rel.split("/")), cat, "postimage")
    preimage = _snapshot(os.path.join(root, *rel.split("/")), cat, "preimage")
    ih = delta["input_hashes"]
    if _sha_bytes(manifest) != ih["apply_manifest_sha256"] \
            or _sha_bytes(patch) != ih["patch_sha256"] \
            or _sha_bytes(preimage) != ih["pre_sha256"] \
            or _sha_bytes(postimage) != ih["post_sha256"]:
        raise TargetError(cat, "step 8 bundle hashes do not bind the delta")
    scope = delta.get("analysis_scope", {})
    if scope.get("source_file") != rel or scope.get("target_file_identity") != rel:
        raise TargetError(cat, "target rel does not equal the frozen Step 10 analysis scope")
    return {"preimage": preimage.decode("utf-8"), "postimage": postimage.decode("utf-8"),
            "apply_manifest_sha256": ih["apply_manifest_sha256"],
            "patch_sha256": ih["patch_sha256"],
            "pre_sha256": ih["pre_sha256"], "post_sha256": ih["post_sha256"]}


def reference_closure(work: str, ref_dirs: list[str],
                      delta: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Materialize the ordered one-DLL-per-slot closure and require semantic equality with
    delta.reference_closure (REFERENCE_BINDING)."""
    from ownlang.fix_delta import snapshot_reference_closure
    try:
        slot_dirs, evidence = snapshot_reference_closure(work, ref_dirs)
    except Exception as exc:  # fix_delta raises DeltaError(ANALYSIS_SCOPE/INPUT_LAYOUT)
        cat = getattr(exc, "category", REFERENCE_BINDING)
        raise TargetError(REFERENCE_BINDING if cat == "ANALYSIS_SCOPE" else INPUT_LAYOUT,
                          str(exc)) from exc
    if evidence != delta.get("reference_closure"):
        raise TargetError(REFERENCE_BINDING,
                          "reconstructed closure != delta.reference_closure")
    return slot_dirs, evidence


# --- probe toolchain + runtime (G2) ------------------------------------------------


def snapshot_probe_deployment(work: str, probe_dll: str) -> tuple[str, dict[str, Any]]:
    """Snapshot the whole probe deployment into WORK/probe and return the copied DLL path +
    the probe fingerprint. Execute the COPY (TOCTOU-closed)."""
    dll_abs = os.path.abspath(probe_dll)
    src = os.path.dirname(dll_abs)
    name = os.path.basename(dll_abs)
    if _is_link(os.lstat(src)):
        raise TargetError(TOOLCHAIN_BINDING, "the probe deployment root is a link")
    dst_root = os.path.join(work, "probe")
    os.makedirs(dst_root)
    manifest: list[dict[str, str]] = []
    for rel in _walk_regular_files(src, TOOLCHAIN_BINDING):
        data = _snapshot(os.path.join(src, rel.replace("/", os.sep)),
                         TOOLCHAIN_BINDING, f"probe {rel}")
        dst = os.path.join(dst_root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        manifest.append({"path": rel, "sha256": _sha_bytes(data)})
    manifest.sort(key=lambda m: m["path"])
    if name not in {m["path"] for m in manifest}:
        raise TargetError(TOOLCHAIN_BINDING, f"the probe DLL {name!r} is not in its deployment")
    fingerprint = {
        "probe_deployment_manifest_sha256": _sha_bytes(_canonical_json(manifest)),
        "probe_runner_sha256": _sha_bytes(_snapshot(os.path.join(dst_root, name),
                                                    TOOLCHAIN_BINDING, "probe runner")),
        "probe_files": manifest,
    }
    return os.path.join(dst_root, name), fingerprint


def resolve_probe_runtime(dll_dst: str, dotnet_host: str,
                          delta: dict[str, Any]) -> tuple[dict[str, Any], str, str, str, str]:
    """Select the runtime with the accepted Step 10 policy and require it to MATCH the runtime
    Step 10 recorded (G2.2). Returns (probe_runtime_identity, dotnet_version, dotnet_host_sha256,
    selected_version, rt_dir)."""
    tfm, fname, fver = _read_runtimeconfig(dll_dst)
    dotnet_host_sha = _hash_resolved(dotnet_host, TOOLCHAIN_BINDING, "dotnet host")
    from ownlang.fix_delta import _run_capture
    dotnet_version = _run_capture([dotnet_host, "--version"], TOOLCHAIN_BINDING,
                                  "dotnet --version").strip()
    listing = _run_capture([dotnet_host, "--list-runtimes"], TOOLCHAIN_BINDING,
                           "dotnet --list-runtimes")
    selected_ver, rt_dir = _select_runtime(listing, fname, fver)
    if not os.path.isdir(rt_dir):
        raise TargetError(TOOLCHAIN_BINDING, "the selected runtime directory does not exist")
    identity = {"framework_name": fname, "tfm": tfm, "requested_framework_version": fver,
                "selected_framework_version": selected_ver,
                "selected_runtime_manifest_sha256": _runtime_manifest(rt_dir)}
    step10 = delta.get("toolchain_fingerprint", {}).get("resolved_runtime_identity", {})
    for k in ("framework_name", "tfm", "requested_framework_version",
              "selected_framework_version", "selected_runtime_manifest_sha256"):
        s10 = step10.get("runtime_manifest_sha256" if k == "selected_runtime_manifest_sha256"
                         else k)
        if identity[k] != s10:
            raise TargetError(TOOLCHAIN_BINDING,
                              f"probe runtime {k} does not match the Step 10 runtime")
    return identity, dotnet_version, dotnet_host_sha, selected_ver, rt_dir


# --- bind-params + the Roslyn bind subprocess (G1) ---------------------------------


def _peel_handler(handler: str) -> str:
    """The frozen Step 8 handler peel + whitespace normalization, mirrored for bind-params:
    `new H(M)` / `new(M)` -> M, then collapse whitespace."""
    import re
    s = handler.strip()
    while True:
        m = re.fullmatch(r"new\s+[^\s(]+\s*\(\s*(.*)\s*\)", s) or re.fullmatch(
            r"new\s*\(\s*(.*)\s*\)", s)
        if not m:
            break
        s = m.group(1).strip()
    return " ".join(s.split())


def build_bind_params(candidates: Any, convert_ids: list[str], rel: str) -> dict[str, Any]:
    by_id = {c["finding_id"]: c for c in candidates["candidates"]}
    conv: list[dict[str, Any]] = []
    for fid in convert_ids:
        c = by_id[fid]
        conv.append({
            "finding_id": fid,
            "occurrence_ordinal": c["occurrence_ordinal"],
            "file": rel,
            "containing_type": c["containing_type"],
            "event": c["event"],
            "source": c["source"],
            "handler": c["handler"],
            "normalized_handler": _peel_handler(c["handler"]),
            "acquire_span": {"start": c["acquire_span"]["start"],
                             "length": c["acquire_span"]["length"]},
        })
    return {"converted": conv}


_BIND_EXIT = {11: CALLSITE_BINDING, 12: WRAPPER_BINDING, 13: TOOLCHAIN_BINDING,
              14: WRAPPER_RUNTIME_UNSUPPORTED}


def run_bind(work: str, dotnet_host: str, probe_dll: str, selected_ver: str, rel: str,
             preimage: str, postimage: str, slots_dir: str, target: str,
             selected_class: str, bind_params: dict[str, Any]) -> dict[str, Any]:
    core = os.path.join(work, "bind")
    os.makedirs(core, exist_ok=True)
    pre_path = os.path.join(core, "pre.cs")
    post_path = os.path.join(core, "post.cs")
    params_path = os.path.join(core, "bind-params.json")
    out_path = os.path.join(core, "binding-result.json")
    with open(pre_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(preimage)
    with open(post_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(postimage)
    with open(params_path, "wb") as fh:
        fh.write(_canonical_json(bind_params))
    argv = [dotnet_host, "exec", "--fx-version", selected_ver, "--roll-forward", "Disable",
            probe_dll, "bind", "--preimage", pre_path, "--postimage", post_path,
            "--slots-dir", slots_dir, "--target", target, "--selected-class", selected_class,
            "--source-file", rel, "--bind-params", params_path, "--out", out_path]
    proc = subprocess.run(argv, cwd=core, env=_probe_env(work, core),
                          capture_output=True, text=True, check=False)
    if proc.returncode in _BIND_EXIT:
        raise TargetError(_BIND_EXIT[proc.returncode], f"bind: {proc.stderr.strip()[:300]}")
    if proc.returncode != 0:
        raise TargetError(INFRASTRUCTURE, f"bind failed (rc={proc.returncode}): "
                                          f"{proc.stderr.strip()[:300]}")
    try:
        with open(out_path, "rb") as fh:
            raw = fh.read()
        binding = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise TargetError(INFRASTRUCTURE, f"binding-result.json unreadable ({exc})") from exc
    if _canonical_bytes(binding) != raw:
        raise TargetError(INFRASTRUCTURE, "binding-result.json is not canonical bytes")
    return cast("dict[str, Any]", binding)


def _probe_env(work: str, cwd_dir: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for k in ("SystemRoot", "SYSTEMROOT", "windir", "PATH", "LANG", "LC_ALL"):
        if k in os.environ:
            env[k] = os.environ[k]
    home = os.path.join(work, "home")
    env["HOME"] = home
    env["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    env["TMPDIR"] = cwd_dir
    env["TEMP"] = cwd_dir
    env["TMP"] = cwd_dir
    return env


# --- the probe subprocess + classification (G3, G4, F4, F5) -------------------------

_PROBE_KEYS = ("version", "operation", "attempt", "strong_delivered_once", "strong_retained",
               "weak_control_collected", "delivered_count", "threw_on_subscribe",
               "threw_on_first_raise", "subscriber_collected", "threw_on_post_collection_raise",
               "resolved_wrapper")
_RESOLVED_KEYS = ("ordinal", "slot_sha256", "assembly_simple_name", "module_mvid",
                  "metadata_token", "resolved_signature")


def run_probe_attempt(work: str, dotnet_host: str, probe_dll: str, selected_ver: str,
                      wrapper_ordinal: int, slots_dir: str, target: str, attempt: int,
                      runtime_dir: str) -> tuple[int, dict[str, Any] | None]:
    adir = os.path.join(work, f"attempt-{attempt}")
    os.makedirs(adir, exist_ok=True)
    out_path = os.path.join(adir, "probe-result.json")
    argv = [dotnet_host, "exec", "--fx-version", selected_ver, "--roll-forward", "Disable",
            probe_dll, "probe", "--wrapper-ordinal", str(wrapper_ordinal),
            "--slots-dir", slots_dir, "--runtime-dir", runtime_dir, "--attempt", str(attempt),
            "--target", target, "--out", out_path]
    try:
        proc = subprocess.run(argv, cwd=os.path.join(work, "probe"), env=_probe_env(work, adir),
                              capture_output=True, timeout=_CHILD_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise TargetError(INFRASTRUCTURE, f"probe attempt {attempt} timed out") from None
    if len(proc.stdout) > _OUT_LIMIT or len(proc.stderr) > _OUT_LIMIT:
        raise TargetError(INFRASTRUCTURE, f"probe attempt {attempt} output overflow")
    if proc.returncode == 10:
        return 10, None
    if proc.returncode != 0:
        raise TargetError(INFRASTRUCTURE, f"probe attempt {attempt} rc={proc.returncode}")
    try:
        with open(out_path, "rb") as fh:
            raw = fh.read()
        if len(raw) > _OUT_LIMIT:
            raise TargetError(INFRASTRUCTURE, "probe-result.json too large")
        obj = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise TargetError(INFRASTRUCTURE, f"probe-result.json unreadable ({exc})") from exc
    if _canonical_bytes(obj) != raw:
        raise TargetError(INFRASTRUCTURE, "probe-result.json is not canonical bytes")
    _validate_probe_result(obj, attempt)
    return 0, obj


def _validate_probe_result(obj: Any, attempt: int) -> None:
    if not isinstance(obj, dict) or set(obj) != set(_PROBE_KEYS):
        raise TargetError(INFRASTRUCTURE, "probe-result.json is not the exact schema")
    if obj["version"] != 1 or obj["operation"] != "weak-target-probe" or obj["attempt"] != attempt:
        raise TargetError(INFRASTRUCTURE, "probe-result.json version/operation/attempt wrong")
    for k in ("strong_delivered_once", "strong_retained", "weak_control_collected",
              "threw_on_subscribe", "threw_on_first_raise", "subscriber_collected",
              "threw_on_post_collection_raise"):
        if not isinstance(obj[k], bool):
            raise TargetError(INFRASTRUCTURE, f"probe-result.{k} must be a boolean")
    if not isinstance(obj["delivered_count"], int) or isinstance(obj["delivered_count"], bool):
        raise TargetError(INFRASTRUCTURE, "probe-result.delivered_count must be an int")
    rw = obj["resolved_wrapper"]
    if not isinstance(rw, dict) or set(rw) != set(_RESOLVED_KEYS):
        raise TargetError(INFRASTRUCTURE, "probe-result.resolved_wrapper is not the exact schema")


def _attempt_verdict(p: dict[str, Any]) -> str:
    if p["threw_on_subscribe"] or p["threw_on_first_raise"] \
            or p["threw_on_post_collection_raise"] or p["delivered_count"] != 1:
        return "TARGET_BEHAVIOR"
    if not p["subscriber_collected"]:
        return "TARGET_RETAINS"
    return "pass"


def classify(attempts: list[dict[str, Any]], binding: dict[str, Any],
             wrapper_ordinal: int, slot_evidence: list[dict[str, Any]]) -> str:
    """Return the final target verdict ('pass') or raise the refusal per the exact F5
    precedence, after the G3 actually-loaded identity cross-check."""
    b = binding["resolved_wrapper"]
    slot = slot_evidence[wrapper_ordinal]
    for p in attempts:
        rw = p["resolved_wrapper"]
        if rw["ordinal"] != wrapper_ordinal or rw["slot_sha256"] != slot["sha256"] \
                or rw["assembly_simple_name"] != b["assembly_simple_name"] \
                or rw["module_mvid"] != b["module_mvid"] \
                or rw["metadata_token"] != b["metadata_token"] \
                or rw["resolved_signature"] != b["resolved_signature"]:
            raise TargetError(WRAPPER_BINDING, "an attempt loaded a different wrapper identity")
    # 2. controls
    for p in attempts:
        if not (p["strong_delivered_once"] and p["strong_retained"]
                and p["weak_control_collected"]):
            raise TargetError(HARNESS_INVALID, "a strong/collectability control failed")
    # 3-7. target verdicts
    verdicts = [_attempt_verdict(p) for p in attempts]
    if len(set(verdicts)) != 1:
        raise TargetError(HARNESS_NONDETERMINISM, f"attempts disagree: {verdicts}")
    v = verdicts[0]
    if v == "TARGET_BEHAVIOR":
        raise TargetError(TARGET_BEHAVIOR, "the wrapper did not deliver exactly once / threw")
    if v == "TARGET_RETAINS":
        raise TargetError(TARGET_RETAINS, "the wrapper retained the subscriber (fake target)")
    return "pass"


# --- publication (F7, G5) ----------------------------------------------------------


def _publish_target(out: str, protected: list[str], evidence_bytes: bytes) -> str:
    from ownlang.fix_gate import PUBLICATION as _P
    try:
        out_phys, parent_phys, _root_phys = _out_parent(out, out)  # root==out: only the
        # existence/off-parent checks matter; the protected-root exclusion is explicit below.
    except GateError as exc:
        raise TargetError(exc.category if exc.category != _P else PUBLICATION, str(exc)) from exc
    for root in protected:
        if _same_or_inside(os.path.realpath(root), parent_phys):
            raise TargetError(PUBLICATION,
                              "the out-dir parent resolves inside a protected root")
    workdir = _claim_workdir(parent_phys)
    succeeded = False
    try:
        with open(os.path.join(workdir, "target-result.json"), "wb") as fh:
            fh.write(evidence_bytes)
        if not _same_path(os.path.realpath(os.path.dirname(out_phys)), parent_phys) \
                or os.path.exists(out_phys) or os.path.islink(out_phys):
            raise TargetError(PUBLICATION, "the out-dir destination changed before publication")
        _require_single(workdir)
        try:
            os.rename(workdir, out_phys)
        except OSError as exc:
            raise TargetError(PUBLICATION, f"cannot publish ({exc})") from exc
        succeeded = True
    finally:
        if not succeeded:
            try:
                shutil.rmtree(workdir)
            except OSError as exc:
                raise TargetError(PUBLICATION, f"cannot remove staging ({exc})") from exc
    return out_phys


def _require_single(workdir: str) -> None:
    entries = list(os.scandir(workdir))
    if len(entries) != 1 or entries[0].name != "target-result.json":
        raise TargetError(PUBLICATION, "staging is not exactly target-result.json")
    st = entries[0].stat(follow_symlinks=False)
    if _is_link(st) or not stat.S_ISREG(st.st_mode):
        raise TargetError(PUBLICATION, "staged target-result.json is not a regular file")


# --- target-result serializers + orchestration -------------------------------------


def _delta_binding_block(delta_bytes: bytes) -> dict[str, Any]:
    return {"delta_result_sha256": _sha_bytes(delta_bytes),
            "step10_operation": "verify-subscription-analyzer-delta",
            "step10_status": "pass", "bound": True}


def build_manual_only_result(input_hashes: dict[str, Any], delta_bytes: bytes,
                             delta: dict[str, Any], target: str,
                             checks_passed: set[str]) -> dict[str, Any]:
    if checks_passed != {"input_layout", "authority_binding", "delta_binding",
                         "reference_binding", "publication"}:
        raise TargetError(INFRASTRUCTURE, "manual-only executed-check set is incomplete")
    checks = {n: "not_applicable" if n in _MANUAL_ONLY_NA else "pass" for n in _CHECK_NAMES}
    return {"schema": 1, "operation": "verify-target-wrapper", "status": "pass",
            "input_hashes": input_hashes, "delta_binding": _delta_binding_block(delta_bytes),
            "target_api": {"subscribe": target}, "reference_closure": delta["reference_closure"],
            "checks": checks}


def build_converted_result(input_hashes: dict[str, Any], delta_bytes: bytes,
                           delta: dict[str, Any], target: str, slot_evidence: list[dict[str, Any]],
                           wrapper_ordinal: int, binding: dict[str, Any], probe_fp: dict[str, Any],
                           dotnet_host_sha: str, dotnet_version: str,
                           runtime_identity: dict[str, Any], attempts: list[dict[str, Any]],
                           checks_passed: set[str]) -> dict[str, Any]:
    if checks_passed != set(_CHECK_NAMES):
        raise TargetError(INFRASTRUCTURE,
                          f"refusing to publish unexecuted checks: "
                          f"{sorted(set(_CHECK_NAMES) - checks_passed)}")
    b = binding["resolved_wrapper"]
    slot = slot_evidence[wrapper_ordinal]
    attempt_rows = [{
        "attempt": p["attempt"], "strong_delivered_once": p["strong_delivered_once"],
        "strong_retained": p["strong_retained"],
        "weak_control_collected": p["weak_control_collected"],
        "delivered_count": p["delivered_count"], "threw_on_subscribe": p["threw_on_subscribe"],
        "threw_on_first_raise": p["threw_on_first_raise"],
        "subscriber_collected": p["subscriber_collected"],
        "threw_on_post_collection_raise": p["threw_on_post_collection_raise"],
        "verdict": _attempt_verdict(p),
    } for p in attempts]
    return {
        "schema": 1, "operation": "verify-target-wrapper", "status": "pass",
        "input_hashes": input_hashes,
        "delta_binding": _delta_binding_block(delta_bytes),
        "target_api": {"subscribe": target},
        "reference_closure": delta["reference_closure"],
        "callsite_binding": {
            "converted_callsites": binding["converted_callsites"],
            "all_callsites_same_symbol": binding["callsite_binding"]["all_callsites_same_symbol"],
            "target_is_source_defined": binding["callsite_binding"]["target_is_source_defined"],
            "derived_wrapper_ordinal": binding["derived_wrapper_ordinal"],
            "asserted_wrapper_ordinal": wrapper_ordinal,
        },
        "selected_wrapper": {
            "ordinal": wrapper_ordinal, "relative_path": slot["relative_path"],
            "sha256": slot["sha256"], "assembly_simple_name": b["assembly_simple_name"],
            "module_mvid": b["module_mvid"], "metadata_token": b["metadata_token"],
            "resolved_signature": b["resolved_signature"],
        },
        "probe_toolchain_fingerprint": {**probe_fp, "dotnet_host_sha256": dotnet_host_sha,
                                        "dotnet_version": dotnet_version},
        "probe_runtime_identity": runtime_identity,
        "probe_protocol": {
            "attempt_count": _ATTEMPT_COUNT, "collection_rounds": _COLLECTION_ROUNDS,
            "allocation_pressure_bytes_per_round": _ALLOC_PER_ROUND,
            "child_timeout_seconds": _CHILD_TIMEOUT_SECONDS, "stdout_limit_bytes": _OUT_LIMIT,
            "stderr_limit_bytes": _OUT_LIMIT, "probe_result_limit_bytes": _OUT_LIMIT,
            "delivered_count_required": 1,
        },
        "attempts": attempt_rows,
        "checks": dict.fromkeys(_CHECK_NAMES, "pass"),
    }


def _revalidate(work: str, probe_fp: dict[str, Any], slot_evidence: list[dict[str, Any]],
                slot_dirs: list[str], rt_dir: str, runtime_identity: dict[str, Any]) -> None:
    pdir = os.path.join(work, "probe")
    if _manifest_sha(pdir, _walk_regular_files(pdir, TOOLCHAIN_BINDING), TOOLCHAIN_BINDING) \
            != probe_fp["probe_deployment_manifest_sha256"]:
        raise TargetError(TOOLCHAIN_BINDING, "the materialized probe deployment changed")
    for i, ev in enumerate(slot_evidence):
        dll = os.path.join(slot_dirs[i], ev["relative_path"].rsplit("/", 1)[-1])
        if _sha_bytes(_snapshot(dll, REFERENCE_BINDING, "slot")) != ev["sha256"]:
            raise TargetError(REFERENCE_BINDING, "a materialized reference slot changed")
    if _runtime_manifest(rt_dir) != runtime_identity["selected_runtime_manifest_sha256"]:
        raise TargetError(TOOLCHAIN_BINDING, "the selected runtime changed")


def run_verify_target(bundle: str, root: str, plan_path: str, candidates_path: str,
                      delta_path: str, probe_dll: str | None, out: str, ref_dirs: list[str],
                      wrapper_ordinal: int | None) -> str:
    passed: set[str] = set()
    plan_bytes = _snapshot(plan_path, INPUT_LAYOUT, "--plan")
    candidates_bytes = _snapshot(candidates_path, INPUT_LAYOUT, "--candidates")
    delta_bytes = _snapshot(delta_path, INPUT_LAYOUT, "--delta")
    auth, _plan, candidates = load_authority(plan_bytes, candidates_bytes)
    passed.add("authority_binding")
    convert_ids = list(auth.applied)
    converted = bool(convert_ids)
    if converted and (probe_dll is None or wrapper_ordinal is None):
        raise TargetError(INPUT_LAYOUT, "converted plan needs --probe-dll and --wrapper-ordinal")
    if not converted and (probe_dll is not None or wrapper_ordinal is not None):
        raise TargetError(INPUT_LAYOUT, "manual-only plan forbids --probe-dll/--wrapper-ordinal")

    delta = bind_delta(delta_bytes, auth, plan_bytes, candidates_bytes)
    rel = auth.rel
    bundle_info = bind_bundle(bundle, root, rel, delta)
    passed.add("input_layout")
    passed.add("delta_binding")
    target = auth.target_subscribe
    input_hashes = {
        "input_bundle_sha256": auth.input_bundle_sha256,
        "validated_plan_sha256": _sha_bytes(plan_bytes),
        "candidates_sha256": _sha_bytes(candidates_bytes),
        "apply_manifest_sha256": bundle_info["apply_manifest_sha256"],
        "patch_sha256": bundle_info["patch_sha256"],
        "pre_sha256": bundle_info["pre_sha256"], "post_sha256": bundle_info["post_sha256"],
    }

    work = tempfile.mkdtemp(prefix="owen-target-")
    try:
        slot_dirs, slot_evidence = reference_closure(work, ref_dirs, delta)
        passed.add("reference_binding")
        protected = [root, bundle, work, *ref_dirs]
        if probe_dll is not None:
            protected.append(os.path.dirname(os.path.abspath(probe_dll)))

        if not converted:
            passed.add("publication")
            evidence = build_manual_only_result(input_hashes, delta_bytes, delta, target, passed)
            return _publish_target(out, protected, _canonical(evidence))

        assert probe_dll is not None and wrapper_ordinal is not None
        probe_dll_dst, probe_fp = snapshot_probe_deployment(work, probe_dll)
        try:
            dotnet_host = _resolve_dotnet_host()
        except Exception as exc:
            raise TargetError(INFRASTRUCTURE, str(exc)) from exc
        runtime_identity, dotnet_version, dotnet_host_sha, selected_ver, rt_dir = \
            resolve_probe_runtime(probe_dll_dst, dotnet_host, delta)
        passed.add("probe_toolchain_binding")

        class_fqn = candidates["selection"]["allowed_types"][0]["full_name"]
        bind_params = build_bind_params(candidates, convert_ids, rel)
        slots_root = os.path.join(work, "references")
        binding = run_bind(work, dotnet_host, probe_dll_dst, selected_ver, rel,
                           bundle_info["preimage"], bundle_info["postimage"], slots_root,
                           target, class_fqn, bind_params)
        if binding["converted_callsites"] != len(convert_ids):
            raise TargetError(CALLSITE_BINDING, "bound callsite count != converted candidates")
        if not (0 <= wrapper_ordinal < len(slot_evidence)):
            raise TargetError(INPUT_LAYOUT, "--wrapper-ordinal is out of range")
        if binding["derived_wrapper_ordinal"] != wrapper_ordinal:
            raise TargetError(INPUT_LAYOUT, "--wrapper-ordinal != the derived ordinal")

        attempts: list[dict[str, Any]] = []
        for k in range(_ATTEMPT_COUNT):
            rc, res = run_probe_attempt(work, dotnet_host, probe_dll_dst, selected_ver,
                                        wrapper_ordinal, slots_root, target, k, rt_dir)
            if rc == 10:
                raise TargetError(WRAPPER_RUNTIME_UNSUPPORTED,
                                  "the wrapper cannot execute under the fixed probe runtime")
            assert res is not None
            attempts.append(res)
        classify(attempts, binding, wrapper_ordinal, slot_evidence)
        passed.update({"wrapper_binding", "harness_controls", "target_behavior",
                       "target_nonretention", "harness_determinism"})

        _revalidate(work, probe_fp, slot_evidence, slot_dirs, rt_dir, runtime_identity)
        passed.add("publication")
        evidence = build_converted_result(input_hashes, delta_bytes, delta, target, slot_evidence,
                                           wrapper_ordinal, binding, probe_fp, dotnet_host_sha,
                                           dotnet_version, runtime_identity, attempts, passed)
        evidence_bytes = _canonical(evidence)
        try:
            shutil.rmtree(work)  # G5: remove EXECUTION_WORK_ROOT before public publication
        except OSError as exc:
            raise TargetError(PUBLICATION, f"cannot remove the work root ({exc})") from exc
        return _publish_target(out, protected, evidence_bytes)
    finally:
        shutil.rmtree(work, ignore_errors=True)

