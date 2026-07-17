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
import shutil
import stat
from collections import Counter
from typing import Any

from ownlang.fix_gate import (
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
    from ownlang.fix_gate import GateError
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
