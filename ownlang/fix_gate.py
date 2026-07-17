"""S2 step 9 — the structural self-gate over a canonical step 8 bundle.

    python -m ownlang own-fix subscriptions gate \
      --bundle <step8-bundle> --plan <validated-plan.json> \
      --candidates <candidates.json> --root <pristine-source-root> --out <gate-out>

Step 9 proves not that the patch came from OUR generator, but that it is structurally
admissible and that its SEMANTICS hold when an INDEPENDENT Git applies it to a pristine
preimage in a hermetic throwaway repository. It never touches the real checkout, index or
config, never applies to a real tree, runs no model, no o7, no analyzer, no target tests.

Trust: Step 9 trusts NOTHING it is handed. The manifest is a claim to be re-derived from
the plan (actions, in candidate order) and the hash-bound candidates (identity); the
patch, postimage and preimage are re-hashed over bytes read exactly once; `git` from the
host PATH is the independent applier. The six external byte inputs — plan, candidates,
manifest, patch, postimage, pristine source — are each read through ONE snapshot boundary
(reject symlink/reparse, open O_NOFOLLOW where available, fstat the handle, require a
regular file, read once) and every hash / parse / materialization runs over those memory
bytes. There is no second read, so there is no TOCTOU between checking and using a file.

Concurrent mutation of the input directories by another privileged process is NOT in the
threat model; a pre-planted malicious filesystem entry or tampered bytes IS.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from typing import Any

from ownlang.fix_candidates import (
    CollectError,
    _require_canonical_relpath,
    _require_finding_id,
    _require_sha256,
)

# --- failure taxonomy (the stable branch markers regressions assert on) ---
BUNDLE_LAYOUT = "BUNDLE_LAYOUT"
MANIFEST_SHAPE = "MANIFEST_SHAPE"
AUTHORITY_BINDING = "AUTHORITY_BINDING"
HASH_MISMATCH = "HASH_MISMATCH"
PRISTINE_SOURCE = "PRISTINE_SOURCE"
PATCH_STRUCTURE = "PATCH_STRUCTURE"
APPLY_CHECK = "APPLY_CHECK"
APPLY_MISMATCH = "APPLY_MISMATCH"
ISOLATION = "ISOLATION"
PUBLICATION = "PUBLICATION"
INFRASTRUCTURE = "INFRASTRUCTURE"

_GATE_NAMES = (
    "bundle_layout", "manifest_shape", "authority_binding", "artifact_hashes",
    "pristine_preimage", "patch_structure", "git_apply_check", "git_apply",
    "postimage_equality", "isolated_tree",
)

_ACTIONS = ("convert_acquire", "manual_review")
_CONTRACTS = ("inotify_property_changed", "name_only", "other", "unresolved")
# The frozen S0 span shape: absolute (start,length) + 1-based line/column, all ints.
_SPAN_KEYS = ("start", "length", "start_line", "start_column", "end_line", "end_column")
# The frozen S0 candidate shape — enforced exactly so no unknown field can ride a
# self-consistent, re-hashed bundle past the gate (amendment 2: known fields only).
_CANDIDATE_KEYS = (
    "finding_id", "diagnostic_code", "containing_type", "file", "enclosing_member",
    "event", "event_identity", "event_contract", "source", "source_identity",
    "source_identity_kind", "handler", "handler_identity", "handler_identity_kind",
    "occurrence_ordinal", "acquire_span", "teardown", "allowed_actions",
)


class GateError(Exception):
    """A controlled refusal, carrying the stable category for regression assertions."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


# --- bytes / hashing / canonical JSON (independent of step 8) ----------------------


def _sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_json(obj: Any) -> bytes:
    """Canonical JSON bytes — the shared serialization. The FILE artifacts (manifest,
    evidence) add a trailing newline (see `_canonical_bytes`); the bundle HASH does not."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _canonical_bytes(obj: Any) -> bytes:
    return _canonical_json(obj) + b"\n"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _same_path(a: str, b: str) -> bool:
    """Platform-aware path equality — the SAME rule as _same_or_inside (normcase is
    identity on POSIX, case-fold on Windows), so `C:\\R\\x` and `c:\\r\\x` compare equal on
    Windows. A raw string `==` would give a casing-only false refusal."""
    return _norm(a) == _norm(b)


def _same_or_inside(parent: str, path: str) -> bool:
    """Is `path` the directory `parent` itself, or under it? Both must be physical.
    Case sensitivity is a PLATFORM property (normcase is identity on POSIX), so `C:\\Repo`
    and `c:\\repo` are one directory on Windows and two elsewhere."""
    p = _norm(parent)
    c = _norm(path)
    if c == p:
        return True
    return c.startswith(p if p.endswith(os.sep) else p + os.sep)


# --- the one snapshot boundary (amendment 3) ---------------------------------------

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _is_link(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    # Windows junctions / reparse points are not S_ISLNK.
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _snapshot(path: str, category: str, what: str) -> bytes:
    """Read a regular file's bytes exactly once. Reject a symlink/reparse point, open
    O_NOFOLLOW where the platform has it, fstat the OPEN handle, require a regular file,
    then read. Every later operation runs over the returned bytes, never the file."""
    try:
        lst = os.lstat(path)
    except OSError as exc:
        raise GateError(category, f"{what}: cannot stat ({exc.strerror or exc})") from exc
    if _is_link(lst):
        raise GateError(category, f"{what}: is a symlink / reparse point")
    try:
        fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    except OSError as exc:
        raise GateError(category, f"{what}: cannot open ({exc.strerror or exc})") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise GateError(category, f"{what}: is not a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        raise GateError(category, f"{what}: cannot read ({exc.strerror or exc})") from exc
    finally:
        os.close(fd)
    return b"".join(chunks)


def _load_json(data: bytes, category: str, what: str) -> Any:
    try:
        return json.loads(data)
    except ValueError as exc:
        raise GateError(category, f"{what}: not valid JSON ({exc})") from exc


# --- typed accessors, category-tagged ----------------------------------------------


def _obj(v: Any, cat: str, where: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise GateError(cat, f"{where}: must be an object")
    return v


def _need(obj: dict[str, Any], name: str, cat: str, where: str) -> Any:
    if name not in obj:
        raise GateError(cat, f"{where}: missing '{name}'")
    return obj[name]


def _s(obj: dict[str, Any], name: str, cat: str, where: str) -> str:
    v = _need(obj, name, cat, where)
    if not isinstance(v, str):
        raise GateError(cat, f"{where}.{name}: must be a string")
    return v


def _int(obj: dict[str, Any], name: str, cat: str, where: str) -> int:
    v = _need(obj, name, cat, where)
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise GateError(cat, f"{where}.{name}: must be a non-negative int")
    return v


def _list(obj: dict[str, Any], name: str, cat: str, where: str) -> list[Any]:
    v = _need(obj, name, cat, where)
    if not isinstance(v, list):
        raise GateError(cat, f"{where}.{name}: must be an array")
    return v


def _exact(obj: dict[str, Any], cat: str, where: str, *keys: str) -> None:
    have = set(obj)
    want = set(keys)
    if have != want:
        raise GateError(cat, f"{where}: key set {sorted(have)} != {sorted(want)}")


def _sha(obj: dict[str, Any], name: str, cat: str, where: str) -> str:
    v = _s(obj, name, cat, where)
    try:
        _require_sha256(v, f"{where}.{name}")
    except CollectError as exc:
        raise GateError(cat, str(exc)) from exc
    return v


def _relpath(v: str, cat: str, where: str) -> None:
    try:
        _require_canonical_relpath(v, where)
    except CollectError as exc:
        raise GateError(cat, str(exc)) from exc


# --- the strict authority validator (amendments 1 & 2; no filesystem I/O) -----------


class GateAuthority:
    """The verified authority context, derived ONLY from plan + candidates (no I/O). rel
    is the canonical source path; applied/manual are the finding ids in candidate order;
    pre_sha256 / target_subscribe / input_bundle_sha256 come from the hash-bound bundle."""

    __slots__ = ("applied", "input_bundle_sha256", "manual", "pre_sha256", "rel",
                 "selected_findings", "target_subscribe")

    def __init__(self, rel: str, target_subscribe: str, pre_sha256: str,
                 input_bundle_sha256: str, applied: list[str], manual: list[str],
                 selected_findings: list[str] | None) -> None:
        self.rel = rel
        self.target_subscribe = target_subscribe
        self.pre_sha256 = pre_sha256
        self.input_bundle_sha256 = input_bundle_sha256
        self.applied = applied
        self.manual = manual
        self.selected_findings = selected_findings


def _bundle_sha256(candidates: dict[str, Any]) -> str:
    # The step 8 input-bundle hash is over canonical JSON with NO trailing newline.
    return _sha_bytes(_canonical_json(candidates))


def _span(obj: dict[str, Any], name: str, cat: str, where: str) -> tuple[int, ...]:
    """The frozen 6-key int span. Returns the values as a tuple for exact comparison."""
    sp = _obj(_need(obj, name, cat, where), cat, f"{where}.{name}")
    _exact(sp, cat, f"{where}.{name}", *_SPAN_KEYS)
    return tuple(_int(sp, k, cat, f"{where}.{name}") for k in _SPAN_KEYS)


def _validate_teardown(td: Any, cat: str, where: str) -> None:
    """The frozen teardown block: status vocabulary + exact-key candidates with a span."""
    t = _obj(td, cat, f"{where}.teardown")
    _exact(t, cat, f"{where}.teardown", "status", "candidates")
    if _s(t, "status", cat, f"{where}.teardown") not in ("none", "exact", "ambiguous"):
        raise GateError(cat, f"{where}.teardown: unknown status")
    for i, tc_any in enumerate(_list(t, "candidates", cat, f"{where}.teardown")):
        tctx = f"{where}.teardown.candidates[{i}]"
        tc = _obj(tc_any, cat, tctx)
        _exact(tc, cat, tctx, "source", "handler", "match", "span")
        _s(tc, "source", cat, tctx)
        _s(tc, "handler", cat, tctx)
        _s(tc, "match", cat, tctx)
        _span(tc, "span", cat, tctx)


def _check_constraints(cons: dict[str, Any], cat: str, where: str) -> None:
    _exact(cons, cat, where, "max_types_changed", "max_files_changed",
           "allow_helper_changes", "allow_config_changes", "allow_suppressions")
    if (_int(cons, "max_types_changed", cat, where) != 1
            or _int(cons, "max_files_changed", cat, where) != 1):
        raise GateError(cat, f"{where}: changes exactly one type in one file")
    for k in ("allow_helper_changes", "allow_config_changes", "allow_suppressions"):
        if cons.get(k) is not False:
            raise GateError(cat, f"{where}.{k} must be false")


def _validate_candidates(bundle: dict[str, Any], cat: str) -> dict[str, Any]:
    """The frozen candidates envelope, returning the derived facts the plan is checked
    against. Exact key sets on every object; the permission tiering; one type / one file."""
    _exact(bundle, cat, "candidates", "version", "operation", "target_api", "selection",
           "source_files", "candidates")
    if bundle["version"] != 1 or isinstance(bundle["version"], bool):
        raise GateError(cat, "candidates.version must be 1")
    if bundle["operation"] != "fix-subscriptions":
        raise GateError(cat, "candidates.operation must be 'fix-subscriptions'")
    b_target = _obj(bundle["target_api"], cat, "candidates.target_api")
    _exact(b_target, cat, "candidates.target_api", "subscribe")
    target_subscribe = _s(b_target, "subscribe", cat, "candidates.target_api")

    b_sel = _obj(bundle["selection"], cat, "candidates.selection")
    _exact(b_sel, cat, "candidates.selection", "allowed_types", "selected_findings",
           "constraints")
    b_types = _list(b_sel, "allowed_types", cat, "candidates.selection")
    if len(b_types) != 1:
        raise GateError(cat, "candidates.selection.allowed_types needs exactly one entry")
    b_type = _obj(b_types[0], cat, "candidates.selection.allowed_types[0]")
    _exact(b_type, cat, "candidates.selection.allowed_types[0]", "full_name", "file")
    type_name = _s(b_type, "full_name", cat, "candidates.selection.allowed_types[0]")
    type_file = _s(b_type, "file", cat, "candidates.selection.allowed_types[0]")
    _relpath(type_file, cat, "candidates.selection.allowed_types[0].file")
    _check_constraints(_obj(b_sel["constraints"], cat, "candidates.selection.constraints"),
                       cat, "candidates.selection.constraints")

    b_files = _list(bundle, "source_files", cat, "candidates")
    if len(b_files) != 1:
        raise GateError(cat, "candidates.source_files needs exactly one entry")
    b_src = _obj(b_files[0], cat, "candidates.source_files[0]")
    _exact(b_src, cat, "candidates.source_files[0]", "path", "sha256")
    src_path = _s(b_src, "path", cat, "candidates.source_files[0]")
    _relpath(src_path, cat, "candidates.source_files[0].path")
    pre_sha256 = _sha(b_src, "sha256", cat, "candidates.source_files[0]")
    if type_file != src_path:
        raise GateError(cat, f"selected type file '{type_file}' != source '{src_path}'")

    cands = _list(bundle, "candidates", cat, "candidates")
    if not cands:
        raise GateError(cat, "candidates: the bundle is empty")
    ids: list[str] = []
    id_set: set[str] = set()
    allowed_by_id: dict[str, list[str]] = {}
    span_by_id: dict[str, tuple[int, ...]] = {}
    for index, c_any in enumerate(cands):
        where = f"candidates[{index}]"
        c = _obj(c_any, cat, where)
        _exact(c, cat, where, *_CANDIDATE_KEYS)
        fid = _s(c, "finding_id", cat, where)
        try:
            _require_finding_id(fid, where)
        except CollectError as exc:
            raise GateError(cat, str(exc)) from exc
        if fid in id_set:
            raise GateError(cat, f"{where}: duplicate finding_id {fid}")
        id_set.add(fid)
        ids.append(fid)
        # EVERY string field the frozen S0 candidate carries — not just the identity
        # subset — so a wrong-typed field on a re-hashed bundle cannot ride through.
        for k in ("diagnostic_code", "enclosing_member", "event", "event_identity",
                  "source", "source_identity", "source_identity_kind",
                  "handler", "handler_identity", "handler_identity_kind"):
            _s(c, k, cat, where)
        _int(c, "occurrence_ordinal", cat, where)
        _validate_teardown(c["teardown"], cat, where)
        if _s(c, "containing_type", cat, where) != type_name:
            raise GateError(cat, f"{where}: outside the selected type {type_name}")
        if _s(c, "file", cat, where) != src_path:
            raise GateError(cat, f"{where}: outside the selected file {src_path}")
        contract = _s(c, "event_contract", cat, where)
        if contract not in _CONTRACTS:
            raise GateError(cat, f"{where}: unknown event_contract '{contract}'")
        span_by_id[fid] = _span(c, "acquire_span", cat, where)
        actions = _list(c, "allowed_actions", cat, where)
        if not actions:
            raise GateError(cat, f"{where}: allowed_actions must be non-empty")
        seen: set[str] = set()
        for a in actions:
            if not isinstance(a, str) or a not in _ACTIONS:
                raise GateError(cat, f"{where}: unknown action in allowed_actions")
            if a in seen:
                raise GateError(cat, f"{where}: duplicate action in allowed_actions")
            seen.add(a)
        if "convert_acquire" in seen and contract != "inotify_property_changed":
            raise GateError(cat, f"{where}: convert_acquire not permitted for '{contract}'")
        allowed_by_id[fid] = list(actions)

    selected = b_sel["selected_findings"]
    if selected is not None:
        if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected):
            raise GateError(cat, "selection.selected_findings must be null or a string array")
        if len(set(selected)) != len(selected) or set(selected) != id_set:
            raise GateError(cat, "selection.selected_findings does not name the candidates")

    return {
        "target_subscribe": target_subscribe, "type_name": type_name,
        "type_file": type_file, "src_path": src_path, "pre_sha256": pre_sha256,
        "ids": ids, "allowed_by_id": allowed_by_id, "span_by_id": span_by_id,
        "selected": selected,
    }


def validate_gate_authority(validated_plan: Any, candidates: Any) -> GateAuthority:
    """Restate the FROZEN envelope the rewriter holds — a hash proves only that the two
    files agree with each other, never that they obey policy. Pure: no filesystem I/O."""
    cat = AUTHORITY_BINDING
    plan = _obj(validated_plan, cat, "plan")
    bundle = _obj(candidates, cat, "candidates")
    facts = _validate_candidates(bundle, cat)
    src_path = facts["src_path"]
    ids = facts["ids"]

    _exact(plan, cat, "plan", "version", "operation", "input_bundle_sha256", "target_api",
           "selection", "source_files", "decisions")
    if plan["version"] != 1 or isinstance(plan["version"], bool):
        raise GateError(cat, "plan.version must be 1")
    if plan["operation"] != "fix-subscriptions":
        raise GateError(cat, "plan.operation must be 'fix-subscriptions'")
    input_bundle_sha256 = _sha(plan, "input_bundle_sha256", cat, "plan")
    if input_bundle_sha256 != _bundle_sha256(bundle):
        raise GateError(cat, "plan.input_bundle_sha256 does not bind these candidates")

    p_target = _obj(plan["target_api"], cat, "plan.target_api")
    _exact(p_target, cat, "plan.target_api", "subscribe")
    if _s(p_target, "subscribe", cat, "plan.target_api") != facts["target_subscribe"]:
        raise GateError(cat, "plan.target_api.subscribe != the candidates bundle")

    p_sel = _obj(plan["selection"], cat, "plan.selection")
    _exact(p_sel, cat, "plan.selection", "allowed_types", "selected_findings", "constraints")
    p_types = _list(p_sel, "allowed_types", cat, "plan.selection")
    if len(p_types) != 1:
        raise GateError(cat, "plan.selection.allowed_types needs exactly one entry")
    p_type = _obj(p_types[0], cat, "plan.selection.allowed_types[0]")
    _exact(p_type, cat, "plan.selection.allowed_types[0]", "full_name", "file")
    if (_s(p_type, "full_name", cat, "plan.selection.allowed_types[0]") != facts["type_name"]
            or _s(p_type, "file", cat, "plan.selection.allowed_types[0]") != facts["type_file"]):
        raise GateError(cat, "plan.selection.allowed_types != the candidates bundle")
    _check_constraints(_obj(p_sel["constraints"], cat, "plan.selection.constraints"),
                       cat, "plan.selection.constraints")
    if p_sel["selected_findings"] != facts["selected"]:
        raise GateError(cat, "plan.selection.selected_findings != the candidates bundle")

    p_files = _list(plan, "source_files", cat, "plan")
    if len(p_files) != 1:
        raise GateError(cat, "plan.source_files needs exactly one entry")
    p_src = _obj(p_files[0], cat, "plan.source_files[0]")
    _exact(p_src, cat, "plan.source_files[0]", "path", "sha256")
    if _s(p_src, "path", cat, "plan.source_files[0]") != src_path:
        raise GateError(cat, "plan.source_files[0].path != the candidates bundle")
    if _s(p_src, "sha256", cat, "plan.source_files[0]") != facts["pre_sha256"]:
        raise GateError(cat, "plan.source_files[0].sha256 != the candidates bundle")

    decisions = _list(plan, "decisions", cat, "plan")
    if len(decisions) != len(ids):
        raise GateError(cat, f"plan.decisions covers {len(decisions)} of {len(ids)}")
    applied: list[str] = []
    manual: list[str] = []
    for index, d_any in enumerate(decisions):
        where = f"plan.decisions[{index}]"
        d = _obj(d_any, cat, where)
        _exact(d, cat, where, "finding_id", "action", "file", "acquire_span")
        fid = _s(d, "finding_id", cat, where)
        if fid != ids[index]:
            raise GateError(cat, f"{where}: {fid} out of candidate order (want {ids[index]})")
        action = _s(d, "action", cat, where)
        if action not in _ACTIONS:
            raise GateError(cat, f"{where}: out-of-scope action '{action}'")
        if action not in facts["allowed_by_id"][fid]:
            raise GateError(cat, f"{where}: action '{action}' not allowed for {fid}")
        if _s(d, "file", cat, where) != src_path:
            raise GateError(cat, f"{where}: file != the selected source file")
        if _span(d, "acquire_span", cat, where) != facts["span_by_id"][fid]:
            raise GateError(cat, f"{where}: acquire_span != the candidate")
        (applied if action == "convert_acquire" else manual).append(fid)

    return GateAuthority(src_path, facts["target_subscribe"], facts["pre_sha256"],
                         input_bundle_sha256, applied, manual, facts["selected"])


# --- manifest shape (its own gate + category) --------------------------------------


def _finding_list(m: dict[str, Any], name: str, cat: str) -> list[str]:
    values = _list(m, name, cat, "manifest")
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            raise GateError(cat, f"manifest.{name}: must be a list of strings")
        try:
            _require_finding_id(v, f"manifest.{name}")
        except CollectError as exc:
            raise GateError(cat, str(exc)) from exc
        if v in seen:
            raise GateError(cat, f"manifest.{name}: duplicate finding_id {v}")
        seen.add(v)
    return values


def validate_manifest_shape(manifest: Any) -> tuple[str, str, str, str]:
    """Exact top-level shape of apply-manifest.json, independent of the plan. Returns
    (rel, pre_sha256, post_sha256, patch_sha256)."""
    cat = MANIFEST_SHAPE
    m = _obj(manifest, cat, "manifest")
    _exact(m, cat, "manifest", "version", "operation", "input_bundle_sha256",
           "validated_plan_sha256", "target_api", "source_files", "applied_findings",
           "manual_review_findings", "patch_sha256")
    if m["version"] != 1 or isinstance(m["version"], bool):
        raise GateError(cat, "manifest.version must be 1")
    if m["operation"] != "apply-subscription-fixes":
        raise GateError(cat, "manifest.operation must be 'apply-subscription-fixes'")
    _sha(m, "input_bundle_sha256", cat, "manifest")
    _sha(m, "validated_plan_sha256", cat, "manifest")
    patch_sha = _sha(m, "patch_sha256", cat, "manifest")
    t = _obj(m["target_api"], cat, "manifest.target_api")
    _exact(t, cat, "manifest.target_api", "subscribe")
    _s(t, "subscribe", cat, "manifest.target_api")
    files = _list(m, "source_files", cat, "manifest")
    if len(files) != 1:
        raise GateError(cat, "manifest.source_files needs exactly one entry")
    src = _obj(files[0], cat, "manifest.source_files[0]")
    _exact(src, cat, "manifest.source_files[0]", "path", "pre_sha256", "post_sha256")
    rel = _s(src, "path", cat, "manifest.source_files[0]")
    _relpath(rel, cat, "manifest.source_files[0].path")
    pre_sha = _sha(src, "pre_sha256", cat, "manifest.source_files[0]")
    post_sha = _sha(src, "post_sha256", cat, "manifest.source_files[0]")
    applied = _finding_list(m, "applied_findings", cat)
    manual = _finding_list(m, "manual_review_findings", cat)
    if set(applied) & set(manual):
        raise GateError(cat, "manifest: applied and manual_review findings overlap")
    return rel, pre_sha, post_sha, patch_sha


# --- the strict step 8 patch language (amendment 7) --------------------------------


def _records(data: bytes) -> list[bytes]:
    """LF-terminated records; a CR is ordinary content. Every record MUST end in LF —
    step 8's canonical_patch emits only LF-terminated records."""
    recs: list[bytes] = []
    i = 0
    n = len(data)
    while i < n:
        j = data.find(b"\n", i)
        if j < 0:
            raise GateError(PATCH_STRUCTURE, "patch has an unterminated final line")
        recs.append(data[i:j])
        i = j + 1
    return recs


def _posint(text: bytes) -> int:
    if not text or not text.isdigit():
        raise GateError(PATCH_STRUCTURE, "malformed hunk number")
    return int(text)


def _range(text: bytes) -> tuple[int, int]:
    parts = text.split(b",")
    if len(parts) == 1:
        return _posint(parts[0]), 1
    if len(parts) == 2:
        return _posint(parts[0]), _posint(parts[1])
    raise GateError(PATCH_STRUCTURE, "malformed hunk range")


def parse_step8_patch(patch: bytes, rel: str, preimage: bytes) -> None:
    """Refuse anything outside the frozen step 8 grammar: one file header whose three
    paths are BYTE-EQUAL to `rel` (so a quoted/escaped or alternate path will not match),
    hunks whose arithmetic is consistent and whose old ranges lie within the preimage,
    context/`-`/`+` body lines and the no-newline marker — and NOTHING else."""
    if patch == b"":
        return  # the empty patch; the caller checks applied_findings == []
    rb = rel.encode("utf-8")
    recs = _records(patch)
    if len(recs) < 4:
        raise GateError(PATCH_STRUCTURE, "patch is too short for a single-file diff")
    if recs[0] != b"diff --git a/" + rb + b" b/" + rb:
        raise GateError(PATCH_STRUCTURE, "patch: 'diff --git' header is not the allowed path")
    if recs[1] != b"--- a/" + rb:
        raise GateError(PATCH_STRUCTURE, "patch: '---' header is not the allowed path")
    if recs[2] != b"+++ b/" + rb:
        raise GateError(PATCH_STRUCTURE, "patch: '+++' header is not the allowed path")

    pre_lines = preimage.count(b"\n")
    if preimage and not preimage.endswith(b"\n"):
        pre_lines += 1
    i = 3
    prev_old_end = 0
    saw_hunk = False
    saw_marker = False   # FILE-level: a no-newline marker means EOF-without-newline, so no
    while i < len(recs):  # further hunk may follow it — the marked line is the file's last.
        rec = recs[i]
        if not (rec.startswith(b"@@ -") and rec.endswith(b" @@")):
            raise GateError(PATCH_STRUCTURE, f"patch: expected a hunk header, got {rec[:40]!r}")
        if saw_marker:
            raise GateError(PATCH_STRUCTURE, "patch: a hunk after a no-newline-at-EOF marker")
        body = rec[len(b"@@ -"):-len(b" @@")]
        try:
            old_part, new_part = body.split(b" +", 1)
        except ValueError as exc:
            raise GateError(PATCH_STRUCTURE, "patch: malformed hunk header") from exc
        old_start, old_len = _range(old_part)
        _new_start, new_len = _range(new_part)
        # Range bounds, including the zero-length (pure-insertion) case: a 0-length old
        # range names the line BEFORE it (0..pre_lines); a non-zero range is 1-based and
        # must lie within the preimage.
        if old_len > 0:
            if old_start < 1 or old_start + old_len - 1 > pre_lines:
                raise GateError(PATCH_STRUCTURE, "patch: a hunk range is outside the preimage")
        elif old_start > pre_lines:
            raise GateError(PATCH_STRUCTURE, "patch: an insertion range is past the preimage")
        if old_start < prev_old_end:
            raise GateError(PATCH_STRUCTURE, "patch: hunks not increasing / non-overlapping")
        prev_old_end = old_start + old_len
        saw_hunk = True
        i += 1
        ctx = minus = plus = 0
        old_closed = new_closed = False   # a no-newline marker closes a side; once each
        last_head: bytes | None = None    # the head of the last body line (None after a marker)
        while i < len(recs) and not (recs[i].startswith(b"@@ -")
                                     and recs[i].endswith(b" @@")):
            line = recs[i]
            if line == b"\\ No newline at end of file":
                # Must sit immediately after an eligible body line, mark the LAST line of
                # its side(s), and appear at most once per side. A context line is on both
                # sides; a `-` line only old; a `+` line only new.
                if last_head is None:
                    raise GateError(PATCH_STRUCTURE, "patch: no-newline marker not after a line")
                marks_old = last_head in (b" ", b"-")
                marks_new = last_head in (b" ", b"+")
                if (marks_old and old_closed) or (marks_new and new_closed):
                    raise GateError(PATCH_STRUCTURE, "patch: duplicate no-newline marker")
                old_closed = old_closed or marks_old
                new_closed = new_closed or marks_new
                saw_marker = True
                last_head = None
                i += 1
                continue
            if not line or line[:1] not in (b" ", b"-", b"+"):
                raise GateError(PATCH_STRUCTURE, f"patch: illegal hunk line {line[:40]!r}")
            head = line[:1]
            # A line of a side already closed by a marker means the marker did not mark the
            # LAST line of that side.
            if head in (b" ", b"-") and old_closed:
                raise GateError(PATCH_STRUCTURE, "patch: old-side line after a no-newline marker")
            if head in (b" ", b"+") and new_closed:
                raise GateError(PATCH_STRUCTURE, "patch: new-side line after a no-newline marker")
            if head == b" ":
                ctx += 1
            elif head == b"-":
                minus += 1
            else:
                plus += 1
            last_head = head
            i += 1
        if ctx + minus != old_len or ctx + plus != new_len:
            raise GateError(PATCH_STRUCTURE, "patch: hunk line counts disagree with header")
        if minus == 0 and plus == 0:
            raise GateError(PATCH_STRUCTURE, "patch: a hunk changes nothing")
    if not saw_hunk:
        raise GateError(PATCH_STRUCTURE, "patch: the file header carries no hunk")


# --- the pristine source verifier (platform-aware physical) -------------------------


def verify_pristine(root: str, rel: str, expected_pre_sha: str) -> bytes:
    """Find `rel` under the physical `root`, confined platform-aware and symlink-aware,
    read its bytes ONCE, and require sha == the manifest's pre_sha256. os.path.realpath
    resolves every intermediate symlink physically, so an intermediate-symlink escape is
    caught by confinement; a symlink AT the leaf is refused outright. The isolated tree is
    later built from THESE bytes — no second read, so no TOCTOU."""
    cat = PRISTINE_SOURCE
    try:
        root_phys = os.path.realpath(root)
    except OSError as exc:
        raise GateError(cat, f"cannot resolve --root ({exc.strerror or exc})") from exc
    if not os.path.isdir(root_phys):
        raise GateError(cat, f"--root '{root}' is not a directory")
    joined = os.path.join(root_phys, *rel.split("/"))
    try:
        leaf = os.lstat(joined)
    except OSError as exc:
        raise GateError(cat, f"source '{rel}' not found ({exc.strerror or exc})") from exc
    if _is_link(leaf):
        raise GateError(cat, f"source '{rel}' is a symlink / reparse point")
    src_phys = os.path.realpath(joined)
    if not _same_or_inside(root_phys, src_phys):
        raise GateError(cat, f"source '{rel}' resolves outside the root")
    data = _snapshot(src_phys, cat, f"source '{rel}'")
    if _sha_bytes(data) != expected_pre_sha:
        raise GateError(cat, f"STALE PREIMAGE / PRISTINE SOURCE MISMATCH for {rel}")
    return data


# --- the hermetic throwaway repository (amendments 5 & 6) ---------------------------


def _git_env(home: str, xdg: str, empty_global: str) -> dict[str, str]:
    """A minimal ALLOWLIST env — not the inherited environment with dangerous GIT_* keys
    guessed at and stripped. Anything not listed here is simply absent from git's world."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LC_ALL": "C",
        "LANG": "C",
        "HOME": home,
        "XDG_CONFIG_HOME": xdg,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": empty_global,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if os.name == "nt":
        for key in ("SystemRoot", "ComSpec", "PATHEXT", "TEMP", "TMP",
                    "SystemDrive", "windir"):
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
    return env


def _git(args: list[str], cwd: str, env: dict[str, str],
         stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
           "-c", "core.safecrlf=false", *args]
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, input=stdin,
                              capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GateError(INFRASTRUCTURE, "git is not available on PATH") from exc
    except OSError as exc:
        raise GateError(INFRASTRUCTURE, f"cannot run git ({exc.strerror or exc})") from exc
    return proc.returncode, proc.stdout, proc.stderr


def _walk_worktree(repo: str) -> set[str]:
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(repo):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            seen.add(os.path.relpath(full, repo).replace("\\", "/"))
    return seen


def apply_in_throwaway(workdir: str, rel: str, preimage: bytes, postimage: bytes,
                       patch: bytes, post_sha256: str) -> None:
    """Build a throwaway repo containing ONLY the preimage (from bytes already read), give
    it a baseline index via `git add`, apply the patch with a hermetic Git, and prove that
    exactly `rel` changed to the exact postimage — index, config and the real checkout all
    untouched. `git apply` runs without --index, so the index must stay byte-identical."""
    home = os.path.join(workdir, "home")
    xdg = os.path.join(workdir, "xdg")
    empty_global = os.path.join(workdir, "gitconfig-none")
    template = os.path.join(workdir, "git-template")
    repo = os.path.join(workdir, "pristine")
    for d in (home, xdg, template, repo):
        os.makedirs(d)
    with open(empty_global, "wb"):
        pass
    env = _git_env(home, xdg, empty_global)

    rc, _o, err = _git(["init", "-q", f"--template={template}", "."], repo, env)
    if rc != 0:
        raise GateError(INFRASTRUCTURE,
                        "git init failed: " + err.decode("utf-8", "replace").strip())

    target = os.path.join(repo, *rel.split("/"))
    if not _same_or_inside(os.path.realpath(repo),
                           os.path.realpath(os.path.dirname(target))):
        raise GateError(ISOLATION, "the preimage path escapes the throwaway repo")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(preimage)

    rc, _o, err = _git(["add", "--", rel], repo, env)
    if rc != 0:
        raise GateError(INFRASTRUCTURE,
                        "git add failed: " + err.decode("utf-8", "replace").strip())

    index_path = os.path.join(repo, ".git", "index")
    config_path = os.path.join(repo, ".git", "config")
    with open(index_path, "rb") as fh:
        index_before = fh.read()
    with open(config_path, "rb") as fh:
        config_before = fh.read()

    rc, _o, _e = _git(["apply", "--check", "--whitespace=nowarn", "-"], repo, env, stdin=patch)
    if rc != 0:
        raise GateError(APPLY_CHECK, "git apply --check refused the patch")
    rc, _o, _e = _git(["apply", "--whitespace=nowarn", "-"], repo, env, stdin=patch)
    if rc != 0:
        raise GateError(APPLY_MISMATCH, "git apply failed after --check passed")

    rc, out, _e = _git(["diff-files", "--name-only", "-z"], repo, env)
    if rc != 0 or out != rel.encode("utf-8") + b"\0":
        raise GateError(ISOLATION, f"the tree does not show exactly '{rel}' modified")
    rc, out, _e = _git(["ls-files", "--others", "-z"], repo, env)
    if rc != 0 or out != b"":
        raise GateError(ISOLATION, "an unexpected untracked file appeared")

    seen = _walk_worktree(repo)
    if seen != {rel}:
        raise GateError(ISOLATION, f"the worktree holds {sorted(seen)}, want ['{rel}']")

    with open(index_path, "rb") as fh:
        if fh.read() != index_before:
            raise GateError(ISOLATION, "git apply mutated the temporary index")
    with open(config_path, "rb") as fh:
        if fh.read() != config_before:
            raise GateError(ISOLATION, "git apply mutated the temporary config")

    with open(target, "rb") as fh:
        applied = fh.read()
    if applied != postimage:
        raise GateError(APPLY_MISMATCH, "the applied file != postimage/<rel>")
    if _sha_bytes(applied) != post_sha256:
        raise GateError(APPLY_MISMATCH, "applied file sha != manifest post_sha256")


# --- publication (the step 8 protocol, reused) -------------------------------------


def _out_parent(out: str, root: str) -> tuple[str, str, str]:
    """(out_phys, parent_phys, root_phys). The out-dir must be fresh and PHYSICALLY off the
    source tree — its parent is resolved and confined here, and re-proven immediately
    before the publishing rename."""
    out_abs = os.path.abspath(out)
    name = os.path.basename(out_abs.rstrip(os.sep))
    if not name:
        raise GateError(PUBLICATION, f"--out {out!r}: not a directory name")
    parent = os.path.dirname(out_abs.rstrip(os.sep))
    if not os.path.isdir(parent):
        raise GateError(PUBLICATION, f"--out {out!r}: parent directory does not exist")
    parent_phys = os.path.realpath(parent)
    root_phys = os.path.realpath(root)
    if _same_or_inside(root_phys, parent_phys):
        raise GateError(PUBLICATION, f"--out {out!r} resolves inside the source root")
    out_phys = os.path.join(parent_phys, name)
    if os.path.exists(out_phys) or os.path.islink(out_phys):
        raise GateError(PUBLICATION, f"--out {out!r} already exists")
    return out_phys, parent_phys, root_phys


def _claim_workdir(parent_phys: str) -> str:
    """CLAIM an unpredictable working directory: create it here and now (owner-only on
    POSIX, as part of the mkdir), then PROVE we own it — not a link/reparse, resolving to
    itself under a PLATFORM-AWARE comparison, and empty. A name that is merely checked and
    then written into is a window; this closes it. If any proof AFTER the mkdir fails, the
    directory we just created is removed before raising — no leftover."""
    import shutil

    for _ in range(8):
        path = os.path.join(parent_phys, f".owen-gate-{os.urandom(16).hex()}")
        if os.path.exists(path) or os.path.islink(path):
            continue
        try:
            os.mkdir(path, mode=0o700)
        except FileExistsError:
            continue
        except OSError as exc:
            raise GateError(PUBLICATION,
                            f"cannot claim a work directory ({exc.strerror or exc})") from exc
        try:
            lst = os.lstat(path)
            if _is_link(lst):
                raise GateError(PUBLICATION, "the claimed work directory is a link")
            if not stat.S_ISDIR(lst.st_mode) or not _same_path(os.path.realpath(path), path) \
                    or not _same_or_inside(parent_phys, os.path.realpath(path)):
                raise GateError(PUBLICATION,
                                "the claimed work directory does not resolve to itself")
            if any(os.scandir(path)):
                raise GateError(PUBLICATION, "the claimed work directory is not empty")
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return path
    raise GateError(PUBLICATION, "could not claim a work directory")


def _publish(staging: str, out_phys: str, evidence: bytes, root_phys: str) -> None:
    os.makedirs(staging)
    with open(os.path.join(staging, "gate-result.json"), "wb") as fh:
        fh.write(evidence)
    # Re-prove the destination against the filesystem AS IT IS NOW, right before the rename.
    parent = os.path.dirname(out_phys)
    if not os.path.isdir(parent):
        raise GateError(PUBLICATION, "the out-dir parent vanished before publication")
    if not _same_path(os.path.realpath(parent), os.path.dirname(out_phys)) \
            or _same_or_inside(root_phys, os.path.realpath(parent)):
        raise GateError(PUBLICATION, "the out-dir parent changed to resolve inside the root")
    if os.path.exists(out_phys) or os.path.islink(out_phys):
        raise GateError(PUBLICATION, "the out-dir appeared before publication")
    try:
        os.rename(staging, out_phys)
    except OSError as exc:
        raise GateError(PUBLICATION,
                        f"cannot publish evidence ({exc.strerror or exc})") from exc


# --- bundle-layout helpers ---------------------------------------------------------


def _lentry(path: str, what: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise GateError(BUNDLE_LAYOUT, f"{what}: cannot stat ({exc.strerror or exc})") from exc


def _require_top_level(bundle: str) -> None:
    try:
        names = set(os.listdir(bundle))
    except OSError as exc:
        raise GateError(BUNDLE_LAYOUT, f"cannot list --bundle ({exc.strerror or exc})") from exc
    if names != {"change.patch", "apply-manifest.json", "postimage"}:
        raise GateError(BUNDLE_LAYOUT, f"bundle holds {sorted(names)}, want "
                        "['apply-manifest.json', 'change.patch', 'postimage']")
    for f in ("change.patch", "apply-manifest.json"):
        st = _lentry(os.path.join(bundle, f), f)
        if _is_link(st):
            raise GateError(BUNDLE_LAYOUT, f"{f}: is a symlink / reparse point")
        if not stat.S_ISREG(st.st_mode):
            raise GateError(BUNDLE_LAYOUT, f"{f}: is not a regular file")
    pst = _lentry(os.path.join(bundle, "postimage"), "postimage")
    if _is_link(pst) or not stat.S_ISDIR(pst.st_mode):
        raise GateError(BUNDLE_LAYOUT, "postimage: is not a real directory")


def _walk_tree(root: str, what: str) -> tuple[set[str], set[str]]:
    """Every entry under `root` must be a real directory or a regular file — no symlinks,
    reparse points, fifos, sockets or devices. Returns (dir paths, file paths), both
    `/`-joined and relative to `root`, so the caller can require an EXACT layout (extra or
    hidden empty directories are a violation, not just extra files)."""
    dirs: set[str] = set()
    files: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise GateError(BUNDLE_LAYOUT, f"{what}: cannot scan ({exc.strerror or exc})") from exc
        for entry in entries:
            st = _lentry(entry.path, entry.path)
            rel = os.path.relpath(entry.path, root).replace("\\", "/")
            if _is_link(st):
                raise GateError(BUNDLE_LAYOUT, f"{what}: '{entry.name}' is a symlink/reparse")
            if stat.S_ISDIR(st.st_mode):
                dirs.add(rel)
                stack.append(entry.path)
            elif stat.S_ISREG(st.st_mode):
                files.add(rel)
            else:
                raise GateError(BUNDLE_LAYOUT,
                                f"{what}: '{entry.name}' is not a regular file or dir")
    return dirs, files


# --- evidence + orchestration ------------------------------------------------------


def _build_evidence(auth: GateAuthority, rel: str, plan_bytes: bytes,
                    manifest_bytes: bytes, patch_bytes: bytes, pre_sha: str,
                    post_sha: str, git_gates: str) -> bytes:
    gates = dict.fromkeys(_GATE_NAMES, "pass")
    gates["git_apply_check"] = git_gates
    gates["git_apply"] = git_gates
    gates["isolated_tree"] = git_gates
    evidence = {
        "version": 1,
        "operation": "gate-subscription-fix-bundle",
        "input_bundle_sha256": auth.input_bundle_sha256,
        "validated_plan_sha256": _sha_bytes(plan_bytes),
        "apply_manifest_sha256": _sha_bytes(manifest_bytes),
        "patch_sha256": _sha_bytes(patch_bytes),
        "target_api": {"subscribe": auth.target_subscribe},
        "source_files": [{"path": rel, "pre_sha256": pre_sha, "post_sha256": post_sha}],
        "applied_findings": auth.applied,
        "manual_review_findings": auth.manual,
        "gates": gates,
    }
    return _canonical_bytes(evidence)


def run_gate(bundle: str, plan_path: str, candidates_path: str, root: str, out: str) -> str:
    """Gate a canonical step 8 bundle and publish gate-result.json. Returns the published
    path; raises GateError (no output, source untouched) on any refusal."""
    import shutil

    # [1] bundle layout — the bundle root itself must not be a symlink/reparse (lstat
    # BEFORE realpath), then exact entry types + the full postimage subtree.
    blst = _lentry(bundle, "--bundle")
    if _is_link(blst):
        raise GateError(BUNDLE_LAYOUT, "--bundle is a symlink / reparse point")
    if not stat.S_ISDIR(blst.st_mode):
        raise GateError(BUNDLE_LAYOUT, "--bundle is not a directory")
    bundle_phys = os.path.realpath(bundle)
    _require_top_level(bundle_phys)
    postimage_root = os.path.join(bundle_phys, "postimage")
    post_dirs, post_leaves = _walk_tree(postimage_root, "postimage")

    # [2] snapshot the inputs that do NOT need rel (each read exactly once).
    manifest_bytes = _snapshot(os.path.join(bundle_phys, "apply-manifest.json"),
                               BUNDLE_LAYOUT, "apply-manifest.json")
    patch_bytes = _snapshot(os.path.join(bundle_phys, "change.patch"),
                            BUNDLE_LAYOUT, "change.patch")
    plan_bytes = _snapshot(plan_path, AUTHORITY_BINDING, "--plan")
    cand_bytes = _snapshot(candidates_path, AUTHORITY_BINDING, "--candidates")

    # [3] manifest shape → rel.
    manifest = _load_json(manifest_bytes, MANIFEST_SHAPE, "apply-manifest.json")
    rel, m_pre, m_post, m_patch = validate_manifest_shape(manifest)

    # [4] bundle layout, final: the postimage subtree is EXACTLY rel's ancestor dirs plus
    # rel — no extra, hidden or empty directory rides through.
    parts = rel.split("/")
    expected_dirs = {"/".join(parts[:i]) for i in range(1, len(parts))}
    if post_leaves != {rel} or post_dirs != expected_dirs:
        raise GateError(BUNDLE_LAYOUT, f"postimage layout {sorted(post_dirs | post_leaves)} "
                        f"!= exactly {sorted(expected_dirs | {rel})}")
    postimage_bytes = _snapshot(os.path.join(postimage_root, *rel.split("/")),
                                BUNDLE_LAYOUT, f"postimage/{rel}")

    # [5] authority: pure plan + candidates; the manifest is re-derived, never trusted.
    plan = _load_json(plan_bytes, AUTHORITY_BINDING, "--plan")
    candidates = _load_json(cand_bytes, AUTHORITY_BINDING, "--candidates")
    auth = validate_gate_authority(plan, candidates)
    if rel != auth.rel:
        raise GateError(AUTHORITY_BINDING, "manifest source path != plan/candidates")

    # [6] pristine preimage — read once; the isolated tree is built from THESE bytes.
    preimage_bytes = verify_pristine(root, rel, auth.pre_sha256)

    # [7] artifact hashes — recompute over the bytes read in [2]-[6].
    if _sha_bytes(patch_bytes) != m_patch:
        raise GateError(HASH_MISMATCH, "recomputed patch_sha256 != the manifest")
    if _sha_bytes(postimage_bytes) != m_post:
        raise GateError(HASH_MISMATCH, "recomputed post_sha256 != the manifest")
    if m_pre != auth.pre_sha256:
        raise GateError(HASH_MISMATCH, "manifest pre_sha256 != plan/candidates")

    # [8] the manifest must BE the canonical projection of plan + candidates + real bytes.
    expected_manifest = _canonical_bytes({
        "version": 1,
        "operation": "apply-subscription-fixes",
        "input_bundle_sha256": auth.input_bundle_sha256,
        "validated_plan_sha256": _sha_bytes(plan_bytes),
        "target_api": {"subscribe": auth.target_subscribe},
        "source_files": [{"path": rel, "pre_sha256": auth.pre_sha256,
                          "post_sha256": _sha_bytes(postimage_bytes)}],
        "applied_findings": auth.applied,
        "manual_review_findings": auth.manual,
        "patch_sha256": _sha_bytes(patch_bytes),
    })
    if manifest_bytes != expected_manifest:
        raise GateError(MANIFEST_SHAPE,
                        "manifest is not the canonical projection of plan/candidates/bytes")

    # [9] patch structure (frozen step 8 language).
    empty_patch = patch_bytes == b""
    if empty_patch and auth.applied:
        raise GateError(PATCH_STRUCTURE, "empty patch valid only when no convert_acquire")
    if not empty_patch and not auth.applied:
        raise GateError(PATCH_STRUCTURE, "a non-empty patch needs a convert_acquire")
    parse_step8_patch(patch_bytes, rel, preimage_bytes)

    # [10] apply semantics + publication.
    out_phys, parent_phys, root_phys = _out_parent(out, root)
    workdir = _claim_workdir(parent_phys)
    staging = os.path.join(workdir, "staging")
    try:
        if empty_patch:
            # manual-only: pre == post == the pristine bytes; Git is not run.
            if postimage_bytes != preimage_bytes:
                raise GateError(APPLY_MISMATCH, "empty patch needs postimage == preimage")
            if m_pre != m_post:
                raise GateError(APPLY_MISMATCH, "empty patch needs pre_sha256 == post_sha256")
            git_gates = "not_applicable"
        else:
            apply_in_throwaway(workdir, rel, preimage_bytes, postimage_bytes,
                               patch_bytes, m_post)
            git_gates = "pass"

        evidence = _build_evidence(auth, rel, plan_bytes, manifest_bytes, patch_bytes,
                                   m_pre, m_post, git_gates)
        _publish(staging, out_phys, evidence, root_phys)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    shutil.rmtree(workdir, ignore_errors=True)
    return out_phys
