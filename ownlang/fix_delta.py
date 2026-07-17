"""S2 step 10 — the analyzer-delta verifier over an accepted step 8 bundle.

    python -m ownlang own-fix subscriptions verify-delta \
      --bundle <step8-bundle> --plan <validated-plan.json> \
      --candidates <candidates.json> --root <pristine-source-root> \
      --gate <step9-gate-result.json> --extractor-dll <OwnSharp.Extractor.dll> \
      --out <delta-evidence-dir> [--ref-dir <dir>]...

Step 9 proves the patch is structurally admissible and that an INDEPENDENT git applies it
to the pristine preimage. It never runs the analyzer, so it cannot tell whether the fix
removed the *leak the analyzer reports*. Step 10 does exactly that: it re-runs Own.NET's
real core analyzer (`check_facts`, which calls `check_module`) over the accepted preimage
and postimage — the analyzer running from a SNAPSHOTTED ownlang package in a fresh,
isolated subprocess, so the fingerprinted bytes are the bytes that actually run — and
proves the OWN001 leak findings changed exactly as the plan promised: the converted
candidates gone, the manual-review candidates preserved, no new OWN001 of ANY resource
lane, no unrelated OWN001 lost, and no newly-introduced OWN050.

Trust: Step 10 trusts NOTHING it is handed except the fingerprinted toolchain (the
extractor deployment, the dotnet host + selected runtime, the snapshotted ownlang package,
the generated core runner, and the Python executable + declared identity). Every byte
input is read through the same ONE snapshot boundary Step 9 uses (reject symlink/reparse,
O_NOFOLLOW, fstat, regular file, read once). It performs no git operation and never writes
the real checkout, index, or config. This module reuses the frozen Step 9 helpers by
import — it never rewrites them — and defines only its own publisher, `_publish_delta`.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from collections import Counter
from typing import Any

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

# --- failure taxonomy (the stable branch markers regressions assert on) ---
INPUT_LAYOUT = "INPUT_LAYOUT"
AUTHORITY_BINDING = "AUTHORITY_BINDING"
GATE_BINDING = "GATE_BINDING"
TOOLCHAIN_BINDING = "TOOLCHAIN_BINDING"
ANALYSIS_SCOPE = "ANALYSIS_SCOPE"
BASELINE_ANALYSIS = "BASELINE_ANALYSIS"
POSTIMAGE_ANALYSIS = "POSTIMAGE_ANALYSIS"
ANALYSIS_IDENTITY = "ANALYSIS_IDENTITY"
DELTA_MISMATCH = "DELTA_MISMATCH"
NEW_OWN001 = "NEW_OWN001"
NEW_OWN050 = "NEW_OWN050"
IDEMPOTENCE = "IDEMPOTENCE"
ISOLATION = "ISOLATION"
PUBLICATION = "PUBLICATION"
INFRASTRUCTURE = "INFRASTRUCTURE"

# The exact 17-name check set published in delta-result.json (Section 14 / LA).
_CHECK_NAMES = (
    "input_layout", "authority_binding", "gate_binding", "toolchain_binding",
    "core_analyzer_binding", "analysis_scope", "baseline_authority", "baseline_analysis",
    "postimage_analysis", "analysis_identity", "delta_subscription", "delta_core",
    "new_own001", "new_own050", "semantic_idempotence", "isolation", "publication",
)

# The core OWN001 observation key (9 fields, verbatim from the real Finding) and the
# OWN050 key (4 fields). Frozen so the runner and the parent agree byte-for-byte.
_CORE_KEY_FIELDS = ("file", "code", "component", "event", "handler", "kind",
                    "advisory", "severity", "ignore_reason")
_OWN050_KEY_FIELDS = ("file", "component", "event", "handler")
_BRIDGE_FIELDS = ("file", "component", "event", "handler")
# The 18 authoritative S0 candidate fields the baseline-authority check re-derives.
_AUTHORITY_FIELDS = (
    "finding_id", "diagnostic_code", "containing_type", "file", "enclosing_member",
    "event", "event_identity", "event_contract", "source", "source_identity",
    "source_identity_kind", "handler", "handler_identity", "handler_identity_kind",
    "occurrence_ordinal", "acquire_span", "teardown", "allowed_actions",
)

# The frozen Step 9 gate-result.json contract (fix_gate._build_evidence): the exact
# eleven top-level keys, the ten gate names, and the three git gates that alone may be
# "not_applicable" (together, exactly for an empty / manual-only patch).
_STEP9_OPERATION = "gate-subscription-fix-bundle"
_STEP9_KEYS = (
    "version", "operation", "input_bundle_sha256", "validated_plan_sha256",
    "apply_manifest_sha256", "patch_sha256", "target_api", "source_files",
    "applied_findings", "manual_review_findings", "gates",
)
_STEP9_GATE_NAMES = (
    "bundle_layout", "manifest_shape", "authority_binding", "artifact_hashes",
    "pristine_preimage", "patch_structure", "git_apply_check", "git_apply",
    "postimage_equality", "isolated_tree",
)
_STEP9_GIT_GATES = ("git_apply_check", "git_apply", "isolated_tree")


class DeltaError(Exception):
    """A controlled refusal, carrying the stable category for regression assertions."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _ckey(d: dict[str, Any]) -> str:
    """The canonical string of an observation dict — the multiset element identity."""
    return _canonical_json(d).decode("utf-8")


def _require_key(d: Any, fields: tuple[str, ...], cat: str, where: str) -> dict[str, Any]:
    """Exact-key object with string-or-null typed values; fail closed on any drift."""
    if not isinstance(d, dict):
        raise DeltaError(cat, f"{where}: must be an object")
    if set(d) != set(fields):
        raise DeltaError(cat, f"{where}: keys {sorted(d)} != {sorted(fields)}")
    return d


def _core_key(obs: Any, cat: str, where: str) -> dict[str, Any]:
    """Validate a core OWN001 observation to its exact 9-field shape and types."""
    o = _require_key(obs, _CORE_KEY_FIELDS, cat, where)
    if o["code"] != "OWN001":
        raise DeltaError(cat, f"{where}.code must be 'OWN001'")
    for k in ("file", "component", "event", "handler", "kind"):
        if not isinstance(o[k], str):
            raise DeltaError(cat, f"{where}.{k} must be a string")
    if not isinstance(o["advisory"], bool):
        raise DeltaError(cat, f"{where}.advisory must be a boolean")
    for k in ("severity", "ignore_reason"):
        if not (o[k] is None or isinstance(o[k], str)):
            raise DeltaError(cat, f"{where}.{k} must be a string or null")
    # a canonical, forward-slash target-file identity (never absolute, never escaping)
    _require_rel(o["file"], cat, f"{where}.file")
    return {k: o[k] for k in _CORE_KEY_FIELDS}


def _own050_key(obs: Any, cat: str, where: str) -> dict[str, Any]:
    o = _require_key(obs, _OWN050_KEY_FIELDS, cat, where)
    for k in _OWN050_KEY_FIELDS:
        if not isinstance(o[k], str):
            raise DeltaError(cat, f"{where}.{k} must be a string")
    _require_rel(o["file"], cat, f"{where}.file")
    return {k: o[k] for k in _OWN050_KEY_FIELDS}


def _require_rel(path: str, cat: str, where: str) -> None:
    """A canonical, root-relative, forward-slash path — no drive, no '..', no backslash."""
    if not path or path.startswith("/") or ":" in path or "\\" in path:
        raise DeltaError(cat, f"{where}: {path!r} is not a canonical relative path")
    parts = path.split("/")
    if any(seg in ("", ".", "..") for seg in parts):
        raise DeltaError(cat, f"{where}: {path!r} has an empty or dotted segment")


def _proj(obs: dict[str, Any]) -> tuple[str, ...]:
    """The 4-field bridge projection of a core observation (SUBSCRIPTION_JOIN_KEY)."""
    return tuple(obs[k] for k in _BRIDGE_FIELDS)


def _sorted_multiset(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A stable, repetition-preserving multiset serialization: sort by canonical bytes."""
    return sorted(items, key=_ckey)


def _parse_core(raw: Any, cat: str) -> dict[str, Any]:
    """Validate the closed core.json schema the fresh runner emits (LA4). `cat` is the
    per-image analysis category (BASELINE_ANALYSIS / POSTIMAGE_ANALYSIS)."""
    if not isinstance(raw, dict):
        raise DeltaError(cat, "core.json: must be an object")
    if set(raw) != {"version", "operation", "all_own001", "own050",
                    "fix_eligible_subscriptions"}:
        raise DeltaError(cat, f"core.json: keys {sorted(raw)} are not the exact schema")
    if raw["version"] != 1 or isinstance(raw["version"], bool):
        raise DeltaError(cat, "core.json.version must be 1")
    if raw["operation"] != "verify-subscription-core-observations":
        raise DeltaError(cat, "core.json.operation is wrong")
    for name in ("all_own001", "own050", "fix_eligible_subscriptions"):
        if not isinstance(raw[name], list):
            raise DeltaError(cat, f"core.json.{name} must be a list")
    all_own001 = [_core_key(o, cat, f"core.json.all_own001[{i}]")
                  for i, o in enumerate(raw["all_own001"])]
    own050 = [_own050_key(o, cat, f"core.json.own050[{i}]")
              for i, o in enumerate(raw["own050"])]
    fix_eligible = [_parse_fix_eligible(o, cat, f"core.json.fix_eligible_subscriptions[{i}]")
                    for i, o in enumerate(raw["fix_eligible_subscriptions"])]
    return {"all_own001": all_own001, "own050": own050,
            "fix_eligible_subscriptions": fix_eligible}


def _parse_fix_eligible(o: Any, cat: str, where: str) -> dict[str, Any]:
    e = _require_key(o, ("finding_id", "diagnostic_code", "bridge_key", "record"), cat, where)
    if not isinstance(e["finding_id"], str) or not isinstance(e["diagnostic_code"], str):
        raise DeltaError(cat, f"{where}: finding_id/diagnostic_code must be strings")
    bridge = _require_key(e["bridge_key"], _BRIDGE_FIELDS, cat, f"{where}.bridge_key")
    for k in _BRIDGE_FIELDS:
        if not isinstance(bridge[k], str):
            raise DeltaError(cat, f"{where}.bridge_key.{k} must be a string")
    _require_rel(bridge["file"], cat, f"{where}.bridge_key.file")
    rec = e["record"]
    if not isinstance(rec, dict) or set(rec) != set(_AUTHORITY_FIELDS):
        raise DeltaError(cat, f"{where}.record is not the exact authoritative field set")
    return {"finding_id": e["finding_id"], "diagnostic_code": e["diagnostic_code"],
            "bridge_key": {k: bridge[k] for k in _BRIDGE_FIELDS}, "record": rec}


# --- the pure delta classifier (Section 8 / LA2 / LA4) -----------------------------


def classify_delta(expected: dict[str, Any], baseline: dict[str, Any],
                   postimage: dict[str, Any]) -> dict[str, Any]:
    """The two-representation delta over already-parsed core observations. Raises
    DeltaError with the exact category on any equation or bridge violation; returns the
    baseline / postimage / delta / semantic_idempotence evidence fragments on success."""
    convert = list(expected["convert_acquire_ids"])
    manual = list(expected["manual_review_ids"])
    c_set, m_set = set(convert), set(manual)
    if len(c_set) != len(convert) or len(m_set) != len(manual):
        raise DeltaError(DELTA_MISMATCH, "expected id list has a duplicate")
    if c_set & m_set:
        raise DeltaError(DELTA_MISMATCH, "convert and manual id sets are not disjoint")
    s_set = c_set | m_set

    b_sub = _subscription_ids(baseline, BASELINE_ANALYSIS)
    p_sub = _subscription_ids(postimage, POSTIMAGE_ANALYSIS)

    # --- the bridge FIRST: every accepted id maps to exactly one baseline core
    # OWN001 observation (identity questions precede the id-set equations, so an
    # unbridged / mixed-action / ambiguous candidate fails closed as ANALYSIS_IDENTITY
    # rather than being masked by a later DELTA_MISMATCH). R_C feeds the core delta.
    r_c = _bridge_r_c(convert, manual, baseline)

    # --- subscription finding-id equations -------------------------------------
    if not s_set <= b_sub:
        raise DeltaError(DELTA_MISMATCH,
                         f"accepted ids not all baseline subscriptions: {sorted(s_set - b_sub)}")
    removed_sub = b_sub - p_sub
    preserved_sub = b_sub & p_sub
    new_sub = p_sub - b_sub
    if new_sub:
        raise DeltaError(NEW_OWN001, f"new fix-eligible subscriptions: {sorted(new_sub)}")
    if removed_sub & s_set != c_set:
        raise DeltaError(DELTA_MISMATCH,
                         "removed candidate-scoped subscriptions != the converted set")
    if preserved_sub & s_set != m_set:
        raise DeltaError(DELTA_MISMATCH,
                         "preserved candidate-scoped subscriptions != the manual-review set")
    unexpectedly_removed = (b_sub - s_set) - p_sub
    if unexpectedly_removed:
        raise DeltaError(DELTA_MISMATCH,
                         f"undeclared disappearance: {sorted(unexpectedly_removed)}")

    # --- complete core OWN001 multiset delta -----------------------------------
    b_all = Counter(_ckey(o) for o in baseline["all_own001"])
    p_all = Counter(_ckey(o) for o in postimage["all_own001"])
    new_all = p_all - b_all
    if new_all:
        raise DeltaError(NEW_OWN001, "a new core OWN001 observation appeared")
    removed_all = b_all - p_all
    if removed_all != r_c:
        raise DeltaError(DELTA_MISMATCH,
                         "removed core OWN001 observations != those authorized for conversion")

    # --- OWN050 multiset --------------------------------------------------------
    b50 = Counter(_ckey(o) for o in baseline["own050"])
    p50 = Counter(_ckey(o) for o in postimage["own050"])
    new_own050 = p50 - b50
    if new_own050:
        raise DeltaError(NEW_OWN050, "a newly-introduced OWN050 advisory appeared")

    # --- semantic idempotence ---------------------------------------------------
    still_actionable = sorted(c_set & p_sub)
    if still_actionable:
        raise DeltaError(IDEMPOTENCE, f"converted ids still actionable: {still_actionable}")

    return {
        "baseline": {
            "subscription_own001_ids": sorted(b_sub),
            "all_own001": _sorted_multiset(baseline["all_own001"]),
            "own050": _sorted_multiset(baseline["own050"]),
        },
        "postimage": {
            "subscription_own001_ids": sorted(p_sub),
            "all_own001": _sorted_multiset(postimage["all_own001"]),
            "own050": _sorted_multiset(postimage["own050"]),
        },
        "delta": {
            "removed_subscription_own001_ids": sorted(removed_sub & s_set),
            "preserved_subscription_own001_ids": sorted(preserved_sub & s_set),
            "new_subscription_own001_ids": [],
            "unexpectedly_removed_subscription_own001_ids": [],
            "removed_all_own001": _multiset_to_list(removed_all, baseline["all_own001"]),
            "new_all_own001": [],
            "new_own050": [],
        },
        "semantic_idempotence": {"converted_ids_still_actionable": [], "pass": True},
    }


def _subscription_ids(image: dict[str, Any], cat: str) -> set[str]:
    ids: list[str] = [e["finding_id"] for e in image["fix_eligible_subscriptions"]
                      if e["diagnostic_code"] == "OWN001"]
    if len(ids) != len(set(ids)):
        raise DeltaError(cat, "duplicate fix-eligible OWN001 subscription finding_id")
    return set(ids)


def _bridge_r_c(convert: list[str], manual: list[str],
                baseline: dict[str, Any]) -> Counter[str]:
    """Bridge each accepted candidate to exactly one baseline core OWN001 observation and
    return R_C, the multiset of baseline observations mapped to the converted set. Every
    ambiguity fails closed as ANALYSIS_IDENTITY (SUBSCRIPTION_JOIN_KEY)."""
    by_fid = {e["finding_id"]: e["bridge_key"] for e in baseline["fix_eligible_subscriptions"]
              if e["diagnostic_code"] == "OWN001"}
    # each 4-field projection -> the distinct full observations that project to it
    by_proj: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for obs in baseline["all_own001"]:
        by_proj.setdefault(_proj(obs), []).append(obs)

    # mixed-action under one indistinguishable bridge key -> fail closed
    action_of: dict[tuple[str, ...], set[str]] = {}
    for fid in convert + manual:
        if fid not in by_fid:
            raise DeltaError(ANALYSIS_IDENTITY,
                             f"accepted candidate {fid} has no baseline subscription fact")
        key = tuple(by_fid[fid][k] for k in _BRIDGE_FIELDS)
        action_of.setdefault(key, set()).add("convert" if fid in set(convert) else "manual")
    for key, actions in action_of.items():
        if len(actions) > 1:
            raise DeltaError(ANALYSIS_IDENTITY,
                             f"bridge key {key} mixes convert and manual candidates")

    r_c: Counter[str] = Counter()
    consumed: Counter[tuple[str, ...]] = Counter()
    for fid in convert:
        key = tuple(by_fid[fid][k] for k in _BRIDGE_FIELDS)
        matches = by_proj.get(key, [])
        distinct = {_ckey(o) for o in matches}
        if not matches:
            raise DeltaError(ANALYSIS_IDENTITY,
                             f"candidate {fid} has no baseline core OWN001 observation")
        if len(distinct) != 1:
            raise DeltaError(ANALYSIS_IDENTITY,
                             f"candidate {fid} maps to multiple distinct core observations")
        consumed[key] += 1
        if consumed[key] > len(matches):
            raise DeltaError(ANALYSIS_IDENTITY,
                             f"more converted candidates than observations for key {key}")
        r_c[_ckey(matches[0])] += 1
    return r_c


def _multiset_to_list(counter: Counter[str], pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize a multiset (keyed by canonical strings) back to sorted observation
    dicts, drawing each element's shape from the pool it was counted over."""
    shape = {_ckey(o): o for o in pool}
    out: list[dict[str, Any]] = []
    for ck in sorted(counter):
        out.extend([shape[ck]] * counter[ck])
    return out


# --- canonical evidence + atomic publication (LA3) ---------------------------------


def _publish_delta(out: str, root: str, evidence_bytes: bytes) -> str:
    """Publish delta-result.json as ONE atomic rename of a claimed private work directory
    to OUTPUT_DIR (LA3). The claimed workdir itself is the staging directory and holds
    exactly delta-result.json, so nothing runs after the rename: either OUTPUT_DIR is
    absent, or it holds the complete canonical delta-result.json. A pre-rename failure
    removes the workdir; a post-rename failure is impossible because there is none."""
    try:
        out_phys, _parent_phys, root_phys = _out_parent(out, root)
        workdir = _claim_workdir(_parent_phys)
    except GateError as exc:  # reuse the frozen helper; keep its (identical) category
        raise DeltaError(exc.category, str(exc)) from exc
    succeeded = False
    try:
        with open(os.path.join(workdir, "delta-result.json"), "wb") as fh:
            fh.write(evidence_bytes)
        parent = os.path.dirname(out_phys)
        if not os.path.isdir(parent):
            raise DeltaError(PUBLICATION, "the out-dir parent vanished before publication")
        if not _same_path(os.path.realpath(parent), os.path.dirname(out_phys)):
            raise DeltaError(PUBLICATION, "the out-dir parent moved before publication")
        if _same_or_inside(root_phys, os.path.realpath(parent)):
            raise DeltaError(PUBLICATION, "the out-dir parent now resolves inside the root")
        if os.path.exists(out_phys) or os.path.islink(out_phys):
            raise DeltaError(PUBLICATION, "the out-dir appeared before publication")
        _require_single_delta_file(workdir)
        os.rename(workdir, out_phys)
        succeeded = True
    finally:
        if not succeeded:
            shutil.rmtree(workdir, ignore_errors=True)
    return out_phys


def _require_single_delta_file(workdir: str) -> None:
    entries = list(os.scandir(workdir))
    if len(entries) != 1 or entries[0].name != "delta-result.json":
        raise DeltaError(PUBLICATION, "the staging directory is not exactly delta-result.json")
    st = entries[0].stat(follow_symlinks=False)
    if _is_link(st) or not stat.S_ISREG(st.st_mode):
        raise DeltaError(PUBLICATION, "the staged delta-result.json is not a regular file")


def canonical_evidence(evidence: dict[str, Any]) -> bytes:
    """The published bytes: canonical JSON (sorted keys, compact) + a trailing newline."""
    return _canonical_bytes(evidence)


# --- authority + OWN001-only scope guard (LA2) + exact Step 9 binding ---------------


def load_authority(plan_bytes: bytes, candidates_bytes: bytes) -> tuple[Any, Any, Any]:
    """Restate the frozen plan+candidates authority (reusing validate_gate_authority) and
    enforce the OWN001-only scope guard (LA2): every accepted candidate must carry
    diagnostic_code == 'OWN001'. An OWN014 (or any other) candidate is outside Step 10 and
    fails closed as ANALYSIS_SCOPE before any analyzer runs."""
    try:
        plan = json.loads(plan_bytes)
        candidates = json.loads(candidates_bytes)
    except ValueError as exc:
        raise DeltaError(AUTHORITY_BINDING, f"plan/candidates is not valid JSON ({exc})") from exc
    try:
        auth = validate_gate_authority(plan, candidates)
    except GateError as exc:  # the frozen validator's category IS AUTHORITY_BINDING
        raise DeltaError(exc.category, str(exc)) from exc
    for candidate in candidates["candidates"]:
        if candidate.get("diagnostic_code") != "OWN001":
            raise DeltaError(ANALYSIS_SCOPE,
                             "Step 10 verifies OWN001 subscription candidates only")
    return auth, plan, candidates


def bind_gate(gate_bytes: bytes, auth: Any, plan_bytes: bytes, manifest_bytes: bytes,
              patch_bytes: bytes, pre_sha: str, post_sha: str) -> str:
    """Bind the mandatory Step 9 evidence: validate the supplied gate-result.json to the
    exact frozen shape, reconstruct the expected object from THIS plan+candidates+bundle,
    and require both semantic equality and canonical bytes. Any deviation is GATE_BINDING.
    Returns the gate-result sha256 for the evidence."""
    cat = GATE_BINDING
    try:
        supplied = json.loads(gate_bytes)
    except ValueError as exc:
        raise DeltaError(cat, f"gate-result.json is not valid JSON ({exc})") from exc
    _validate_gate_shape(supplied, cat)
    # git gates are not_applicable exactly when the patch is empty (manual-only, C empty)
    git_status = "not_applicable" if not auth.applied else "pass"
    gates = {n: (git_status if n in _STEP9_GIT_GATES else "pass") for n in _STEP9_GATE_NAMES}
    expected = {
        "version": 1,
        "operation": _STEP9_OPERATION,
        "input_bundle_sha256": auth.input_bundle_sha256,
        "validated_plan_sha256": _sha_bytes(plan_bytes),
        "apply_manifest_sha256": _sha_bytes(manifest_bytes),
        "patch_sha256": _sha_bytes(patch_bytes),
        "target_api": {"subscribe": auth.target_subscribe},
        "source_files": [{"path": auth.rel, "pre_sha256": pre_sha, "post_sha256": post_sha}],
        "applied_findings": list(auth.applied),
        "manual_review_findings": list(auth.manual),
        "gates": gates,
    }
    if supplied != expected:
        raise DeltaError(cat, "gate-result.json does not reconstruct from plan+candidates+bundle")
    if _canonical_bytes(supplied) != gate_bytes:
        raise DeltaError(cat, "gate-result.json is not canonical bytes (sorted keys + newline)")
    return _sha_bytes(gate_bytes)


def _validate_gate_shape(supplied: Any, cat: str) -> None:
    if not isinstance(supplied, dict) or set(supplied) != set(_STEP9_KEYS):
        raise DeltaError(cat, "gate-result.json is not the exact Step 9 eleven-key set")
    gates = supplied["gates"]
    if not isinstance(gates, dict) or set(gates) != set(_STEP9_GATE_NAMES):
        raise DeltaError(cat, "gate-result.json.gates is not the exact ten-name set")
    for name, value in gates.items():
        allowed = ("pass", "not_applicable") if name in _STEP9_GIT_GATES else ("pass",)
        if value not in allowed:
            raise DeltaError(cat, f"gate-result.json.gates.{name} status {value!r} not allowed")
    if len({gates[n] for n in _STEP9_GIT_GATES}) != 1:
        raise DeltaError(cat, "gate-result.json git gates disagree (must share one status)")


# --- the fresh, snapshotted core-analyzer subprocess (LA1 / LA4 / LA5) --------------

# The deterministic runner materialized at WORK_ROOT/core/run_core.py. Its bytes are
# hashed as core_runner_sha256; it is NOT part of the ownlang fingerprint. It runs under
# `python -S -B -E` with the snapshotted ownlang package on sys.path[0], so the fingerprinted
# bytes are the bytes that actually produce the verdict. It self-fingerprints after import
# (every ownlang module must resolve physically inside the snapshot) and exits 3 on failure.
RUN_CORE_SOURCE = r'''"""Step 10 core runner — runs inside a fresh, isolated subprocess over the
snapshotted ownlang package on sys.path[0] and emits canonical core.json."""
import json
import os
import sys


def _fail_toolchain(msg):
    sys.stderr.write("run_core: toolchain: " + msg + "\n")
    raise SystemExit(3)


def _fail_analysis(msg):
    sys.stderr.write("run_core: analysis: " + msg + "\n")
    raise SystemExit(4)


def _phys_inside(child, parent):
    c = os.path.normcase(os.path.realpath(child))
    p = os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p + os.sep)


def main():
    if len(sys.argv) != 4:
        _fail_toolchain("usage: run_core.py FACTS CORE_OUT PARAMS")
    facts_path, out_path, params_path = sys.argv[1], sys.argv[2], sys.argv[3]
    pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ownlang")
    try:
        import ownlang
        import ownlang.__main__
        import ownlang.fix_candidates
        import ownlang.ownir
    except Exception as exc:
        _fail_toolchain("cannot import snapshotted ownlang: " + repr(exc))
    for mod in (ownlang, ownlang.ownir, ownlang.__main__, ownlang.fix_candidates):
        f = getattr(mod, "__file__", None)
        if not f or not os.path.isfile(f) or not _phys_inside(f, pkg):
            _fail_toolchain("import escaped the snapshot: " + str(getattr(mod, "__name__", "?")))
    try:
        with open(params_path, "rb") as fh:
            params = json.load(fh)
        with open(facts_path, "rb") as fh:
            facts = json.load(fh)
    except Exception as exc:
        _fail_analysis("cannot read inputs: " + repr(exc))
    try:
        findings = ownlang.ownir.check_facts(facts)
    except Exception as exc:
        _fail_analysis("check_facts failed: " + repr(exc))
    all_own001 = []
    own050 = []
    for fnd in findings:
        if fnd.code == "OWN001":
            all_own001.append({"file": fnd.file, "code": "OWN001", "component": fnd.component,
                               "event": fnd.event, "handler": fnd.handler, "kind": fnd.kind,
                               "advisory": bool(fnd.advisory), "severity": fnd.severity,
                               "ignore_reason": fnd.ignore_reason})
        elif fnd.code == "OWN050":
            own050.append({"file": fnd.file, "component": fnd.component,
                           "event": fnd.event, "handler": fnd.handler})
    try:
        env = ownlang.fix_candidates.collect_candidates(
            facts, params["target_subscribe"], params["class_fqn"], None, params["root"])
    except Exception as exc:
        _fail_analysis("collect_candidates failed: " + repr(exc))
    fix_eligible = []
    for c in env["candidates"]:
        src = c["source"]
        full = c["event"] if src == "this" else (src + "." + c["event"])
        fix_eligible.append({"finding_id": c["finding_id"],
                             "diagnostic_code": c["diagnostic_code"],
                             "bridge_key": {"file": c["file"],
                                            "component": c["containing_type"].rsplit(".", 1)[-1],
                                            "event": full, "handler": c["handler"]},
                             "record": c})
    core = {"version": 1, "operation": "verify-subscription-core-observations",
            "all_own001": all_own001, "own050": own050,
            "fix_eligible_subscriptions": fix_eligible}
    data = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(data + "\n")


if __name__ == "__main__":
    main()
'''


def _walk_pkg(pkg_src: str) -> list[str]:
    """Every regular package file, canonical '/'-relative, sorted by byte order — except
    __pycache__ and compiled .pyc/.pyo. Rejects any symlink/reparse or non-regular entry."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(pkg_src):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for d in dirnames:
            if _is_link(os.lstat(os.path.join(dirpath, d))):
                raise DeltaError(TOOLCHAIN_BINDING, "ownlang has a symlinked subdirectory")
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, fn)
            st = os.lstat(full)
            if _is_link(st):
                raise DeltaError(TOOLCHAIN_BINDING, f"ownlang/{fn} is a symlink / reparse point")
            if not stat.S_ISREG(st.st_mode):
                raise DeltaError(TOOLCHAIN_BINDING, f"ownlang/{fn} is not a regular file")
            out.append(os.path.relpath(full, pkg_src).replace(os.sep, "/"))
    out.sort()
    return out


def materialize_core(work: str) -> tuple[str, str, str, dict[str, Any]]:
    """Snapshot the installed ownlang package verbatim into WORK/core/ownlang and write the
    deterministic runner WORK/core/run_core.py. Returns (core_dir, runner_path,
    core_runner_sha256, core_fingerprint). The runner bytes are verified immediately after
    materialization (LA1)."""
    import ownlang as _own

    own_file = getattr(_own, "__file__", None)
    if not own_file:
        raise DeltaError(TOOLCHAIN_BINDING, "cannot locate the ownlang package")
    pkg_src = os.path.dirname(os.path.abspath(own_file))
    if _is_link(os.lstat(pkg_src)):
        raise DeltaError(TOOLCHAIN_BINDING, "the ownlang package root is a link")
    core_dir = os.path.join(work, "core")
    pkg_dst = os.path.join(core_dir, "ownlang")
    os.makedirs(pkg_dst)
    manifest: list[dict[str, str]] = []
    for rel in _walk_pkg(pkg_src):
        data = _snapshot(os.path.join(pkg_src, rel.replace("/", os.sep)),
                         TOOLCHAIN_BINDING, f"ownlang/{rel}")
        dst = os.path.join(pkg_dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        manifest.append({"path": rel, "sha256": _sha_bytes(data)})
    manifest.sort(key=lambda m: m["path"])
    runner_path = os.path.join(core_dir, "run_core.py")
    runner_bytes = RUN_CORE_SOURCE.encode("utf-8")
    with open(runner_path, "wb") as fh:
        fh.write(runner_bytes)
    core_runner_sha256 = _sha_bytes(runner_bytes)
    _verify_runner(runner_path, core_runner_sha256)
    fingerprint = {
        "ownlang_manifest_sha256": _sha_bytes(_canonical_json(manifest)),
        "ownlang_files": manifest,
        "core_runner_sha256": core_runner_sha256,
    }
    return core_dir, runner_path, core_runner_sha256, fingerprint


def _verify_runner(runner_path: str, expected_sha: str) -> None:
    """Re-read and re-hash the materialized runner; a change is TOOLCHAIN_BINDING (LA1)."""
    data = _snapshot(runner_path, TOOLCHAIN_BINDING, "run_core.py")
    if _sha_bytes(data) != expected_sha:
        raise DeltaError(TOOLCHAIN_BINDING, "core runner bytes changed (core_runner_sha256)")


def resolve_python() -> tuple[str, dict[str, Any]]:
    """Resolve, snapshot, and identify the Python executable that runs the fresh core
    subprocess (LA5). A missing / non-regular interpreter is TOOLCHAIN_BINDING."""
    exe = sys.executable
    if not exe:
        raise DeltaError(TOOLCHAIN_BINDING, "no Python executable to run the core subprocess")
    data = _snapshot(exe, TOOLCHAIN_BINDING, "python executable")
    return exe, {
        "python_executable_sha256": _sha_bytes(data),
        "python_implementation": sys.implementation.name,
        "python_version": platform.python_version(),
        "python_cache_tag": sys.implementation.cache_tag or "unknown",
    }


def _core_env(image_dir: str) -> dict[str, str]:
    """A minimal environment for the core subprocess. `-E` ignores every PYTHON* variable;
    only the host bits the interpreter needs to start are forwarded, and the caches / temp
    are redirected into the image workspace."""
    env: dict[str, str] = {}
    for k in ("SystemRoot", "SYSTEMROOT", "windir", "PATH", "HOME", "LANG", "LC_ALL"):
        if k in os.environ:
            env[k] = os.environ[k]
    env["TMPDIR"] = image_dir
    env["TEMP"] = image_dir
    env["TMP"] = image_dir
    return env


def run_core(core_dir: str, runner_path: str, python_exe: str, core_runner_sha256: str,
             image_dir: str, facts_bytes: bytes, params: dict[str, Any],
             cat: str) -> dict[str, Any]:
    """Run the fresh core subprocess over `facts_bytes` and return the parsed, schema-checked
    core.json. Re-verifies the runner bytes before launch (LA1). A self-fingerprint / import
    escape (exit 3) is TOOLCHAIN_BINDING; any other failure or a malformed core.json is the
    per-image analysis category `cat`."""
    _verify_runner(runner_path, core_runner_sha256)
    facts_path = os.path.join(image_dir, "facts.json")
    core_path = os.path.join(image_dir, "core.json")
    params_path = os.path.join(image_dir, "params.json")
    with open(facts_path, "wb") as fh:
        fh.write(facts_bytes)
    with open(params_path, "wb") as fh:
        fh.write(_canonical_json(params))
    proc = subprocess.run(
        [python_exe, "-S", "-B", "-E", runner_path, facts_path, core_path, params_path],
        cwd=core_dir, env=_core_env(image_dir), capture_output=True, text=True, check=False)
    if proc.returncode == 3:
        raise DeltaError(TOOLCHAIN_BINDING,
                         f"core runner self-fingerprint failed: {proc.stderr.strip()[:300]}")
    if proc.returncode != 0:
        raise DeltaError(cat, f"core analyzer failed (rc={proc.returncode}): "
                              f"{proc.stderr.strip()[:300]}")
    try:
        with open(core_path, "rb") as fh:
            raw = json.loads(fh.read())
    except (OSError, ValueError) as exc:
        raise DeltaError(cat, f"core.json is unreadable ({exc})") from exc
    return _parse_core(raw, cat)


def check_baseline_authority(candidates: dict[str, Any], base_core: dict[str, Any]) -> None:
    """Bind the declared closure to the accepted S0 candidates (LA/§8): every accepted
    candidate must be reproduced EXACTLY over the baseline for all 18 authoritative fields.
    A mismatch is ANALYSIS_SCOPE — it proves the declared closure is semantically compatible
    with the accepted S0 authority, not that it is historically identical."""
    recomputed = {e["finding_id"]: e["record"]
                  for e in base_core["fix_eligible_subscriptions"]}
    for c in candidates["candidates"]:
        fid = c["finding_id"]
        rec = recomputed.get(fid)
        if rec is None:
            raise DeltaError(ANALYSIS_SCOPE,
                             f"accepted candidate {fid} is not reproduced over the baseline")
        for field in _AUTHORITY_FIELDS:
            if c[field] != rec[field]:
                raise DeltaError(ANALYSIS_SCOPE,
                                 f"baseline-authority mismatch on '{field}' for {fid}")


def check_target_identity(core: dict[str, Any], rel: str, cat: str) -> None:
    """Every finding used by Step 10 must carry file == the declared target rel (LA/§3)."""
    for o in core["all_own001"]:
        if o["file"] != rel:
            raise DeltaError(cat, f"OWN001 attributed to {o['file']!r} != target {rel!r}")
    for o in core["own050"]:
        if o["file"] != rel:
            raise DeltaError(cat, f"OWN050 attributed to {o['file']!r} != target {rel!r}")
    for e in core["fix_eligible_subscriptions"]:
        if e["record"]["file"] != rel or e["bridge_key"]["file"] != rel:
            raise DeltaError(cat, f"candidate attributed to a file != target {rel!r}")
