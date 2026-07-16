"""S0 Part B — the `own-fix subscriptions candidates` collector (analysis-only).

Reads the extractor's `--fix-candidates` facts and, for ONE fully-qualified class,
emits a deterministic `candidates.json`: a selection-request safety envelope plus a
candidate bundle per eligible leaky subscription. It changes no source. The heavy
C# semantics (spans, INotifyPropertyChanged classification, symbol-based teardown,
conservative source/handler identity) are already in the `fix` block; this module
only assembles, identifies, filters and orders.

Locked contract (arbiter):
  * `--class` is an EXACT fully-qualified name; a partial / nested / generated / or
    ambiguously-resolved type is a hard error.
  * finding_id is line-independent and versioned:
        SHA256(version . containing_type . enclosing_member . event_identity .
               source_identity . handler_identity . occurrence_ordinal)
    (NUL-separated) — the span/line are location metadata, never in the id.
  * the target subscribe API is PINNED from config (never the first of a list).
  * S0 permits only `convert_acquire` (INotifyPropertyChanged contract only) and
    `manual_review`; `convert_exact_teardown` is deferred to S2 with a pinned remove
    API, so teardown metadata is carried but never a conversion permission.
  * candidates are deterministically ordered and every source file gets a SHA-256.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

_FINDING_ID_VERSION = "own-fix-subscription-v1"
_CONSTRAINTS: dict[str, object] = {
    "max_types_changed": 1,
    "max_files_changed": 1,
    "allow_helper_changes": False,
    "allow_config_changes": False,
    "allow_suppressions": False,
}


class CollectError(Exception):
    """A candidate-collection request that cannot be honoured (bad class, unknown
    finding id, unreadable source). Callers surface it as a hard (non-zero) error."""


_FIX_VERSION = 1
# The only remediation actions S1 exposes. `convert_exact_teardown` and the rest of the
# arbiter enum are deferred (S2), so a candidate's allowed_actions is a subset of this.
S1_ACTIONS = ("convert_acquire", "manual_review")


def _field(obj: dict[str, Any], key: str, kind: str, ctx: str) -> Any:
    """Fetch `obj[key]`, hard-failing (CollectError) on a missing key or a value of the
    wrong JSON kind — so malformed external facts surface as a controlled error, never a
    KeyError/TypeError traceback. `int` deliberately excludes `bool`."""
    if key not in obj:
        raise CollectError(f"{ctx}: missing field {key!r}")
    v = obj[key]
    ok = {
        "str": isinstance(v, str),
        "int": isinstance(v, int) and not isinstance(v, bool),
        "bool": isinstance(v, bool),
        "list": isinstance(v, list),
        "dict": isinstance(v, dict),
    }[kind]
    if not ok:
        raise CollectError(f"{ctx}: field {key!r} must be {kind}, got {type(v).__name__}")
    return v


_SPAN_INTS = ("start", "length", "start_line", "start_column", "end_line", "end_column")


def _validate_span(span: Any, ctx: str) -> None:
    if not isinstance(span, dict):
        raise CollectError(f"{ctx}: span must be an object")
    for k in _SPAN_INTS:
        _field(span, k, "int", f"{ctx}.span")


def _validate_teardown(td: Any, ctx: str) -> None:
    if not isinstance(td, dict):
        raise CollectError(f"{ctx}: teardown must be an object")
    status = _field(td, "status", "str", f"{ctx}.teardown")
    if status not in ("none", "exact", "ambiguous"):
        raise CollectError(f"{ctx}.teardown: unknown status {status!r}")
    for i, cand in enumerate(_field(td, "candidates", "list", f"{ctx}.teardown")):
        cctx = f"{ctx}.teardown.candidates[{i}]"
        if not isinstance(cand, dict):
            raise CollectError(f"{cctx}: must be an object")
        _field(cand, "source", "str", cctx)
        _field(cand, "handler", "str", cctx)
        _field(cand, "match", "str", cctx)
        _validate_span(cand.get("span"), cctx)


_FIX_STR_FIELDS = (
    "enclosing_member",
    "event_identity",
    "event_contract",
    "source_identity",
    "source_identity_kind",
    "handler_identity",
    "handler_identity_kind",
)


def _validate_fix(fx: Any, ctx: str) -> None:
    """Narrow shape check of the `fix` block this collector consumes / republishes — not
    a full JSON Schema, only the S0 contract."""
    if not isinstance(fx, dict):
        raise CollectError(f"{ctx}: fix must be an object")
    for k in _FIX_STR_FIELDS:
        _field(fx, k, "str", ctx)
    _field(fx, "occurrence_ordinal", "int", ctx)
    _validate_span(fx.get("span"), ctx)
    _validate_teardown(fx.get("teardown"), ctx)


def _validate_version(facts: dict[str, Any]) -> None:
    v = facts.get("fix_candidates_version")
    if not (isinstance(v, int) and not isinstance(v, bool) and v == _FIX_VERSION):
        raise CollectError(
            f"facts fix_candidates_version must be integer {_FIX_VERSION} (got {v!r}) — "
            f"produce facts with a compatible --fix-candidates extractor"
        )
    if not isinstance(facts.get("components"), list):
        raise CollectError("facts.components must be a list")


def _resolve_source(root: str, rel: str) -> tuple[str, str]:
    """Canonicalize a facts-supplied source path and CONFINE it to `root`. Returns
    (canonical root-relative path with `/`, absolute real path). A `..` escape, an
    absolute path outside `root`, a symlink pointing out, or a non-regular file are all
    hard errors — `file` arrives from external facts and flows into the public envelope,
    so it must never reference anything outside the selected repo."""
    root_real = os.path.realpath(root)
    joined = rel if os.path.isabs(rel) else os.path.join(root_real, rel)
    src_real = os.path.realpath(joined)
    try:
        common = os.path.commonpath([root_real, src_real])
    except ValueError as exc:  # different drives / mixed forms
        raise CollectError(f"source path {rel!r} is not inside the root {root!r}") from exc
    if common != root_real:
        raise CollectError(f"source path {rel!r} escapes the root {root!r}")
    if not os.path.isfile(src_real):
        raise CollectError(f"source path {rel!r} is not a regular file")
    canonical = os.path.relpath(src_real, root_real).replace("\\", "/")
    return canonical, src_real


def finding_id(
    containing_type: str,
    enclosing_member: str,
    event_identity: str,
    source_identity: str,
    handler_identity: str,
    occurrence_ordinal: int,
) -> str:
    """Versioned, LINE-INDEPENDENT identity. Only semantic constituents — inserting a
    blank line (which shifts span/line) must not change it."""
    payload = "\0".join(
        [
            _FINDING_ID_VERSION,
            containing_type,
            enclosing_member,
            event_identity,
            source_identity,
            handler_identity,
            str(occurrence_ordinal),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"OWN001:sha256:{digest}"


def _sha_of(abs_path: str) -> str:
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise CollectError(f"cannot read source file {abs_path!r}: {exc}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _resolve_class(facts: dict[str, Any], class_fqn: str) -> dict[str, Any]:
    comps = [
        c
        for c in facts["components"]
        if isinstance(c, dict) and c.get("qualified_name") == class_fqn
    ]
    if not comps:
        raise CollectError(
            f"class {class_fqn!r} not found — scan with --fix-candidates and pass an "
            f"exact fully-qualified name"
        )
    if len(comps) > 1:
        raise CollectError(
            f"class {class_fqn!r} resolves to {len(comps)} declarations (partial); "
            f"refusing an ambiguous type"
        )
    comp: dict[str, Any] = comps[0]
    cctx = f"component {class_fqn}"
    _field(comp, "file", "str", cctx)
    _field(comp, "subscriptions", "list", cctx)
    for flag, why in (
        ("is_partial", "partial"),
        ("is_nested", "nested"),
        ("is_generated", "generated"),
    ):
        if _field(comp, flag, "bool", cctx):
            raise CollectError(f"class {class_fqn!r} is {why}; refused by MVP policy")
    return comp


def _bundle(
    sub: dict[str, Any], fx: dict[str, Any], class_fqn: str, file_rel: str
) -> dict[str, Any]:
    event_full = sub["event"]
    event_name = fx["event_identity"].rsplit(".", 1)[-1]
    source_display = event_full[: event_full.rfind(".")] if "." in event_full else "this"
    contract = fx["event_contract"]
    diagnostic = "OWN014" if sub["resource"] == "capture" else "OWN001"
    # convert_acquire is permitted ONLY for a proven INotifyPropertyChanged contract;
    # everything else (name_only / other / unresolved) is manual_review. Teardown
    # conversion is NOT offered in S0 regardless of an `exact` status.
    actions = (
        ["convert_acquire", "manual_review"]
        if contract == "inotify_property_changed"
        else ["manual_review"]
    )
    return {
        "finding_id": finding_id(
            class_fqn,
            fx["enclosing_member"],
            fx["event_identity"],
            fx["source_identity"],
            fx["handler_identity"],
            fx["occurrence_ordinal"],
        ),
        "diagnostic_code": diagnostic,
        "containing_type": class_fqn,
        "file": file_rel,
        "enclosing_member": fx["enclosing_member"],
        "event": event_name,
        "event_identity": fx["event_identity"],
        "event_contract": contract,
        "source": source_display,
        "source_identity": fx["source_identity"],
        "source_identity_kind": fx["source_identity_kind"],
        "handler": sub["handler"],
        "handler_identity": fx["handler_identity"],
        "handler_identity_kind": fx["handler_identity_kind"],
        "occurrence_ordinal": fx["occurrence_ordinal"],
        "acquire_span": fx["span"],
        "teardown": fx["teardown"],
        "allowed_actions": actions,
    }


def collect_candidates(
    facts: dict[str, Any],
    target_subscribe: str,
    class_fqn: str,
    finding_ids: list[str] | None,
    root: str = ".",
) -> dict[str, Any]:
    """Build the candidates.json envelope for `class_fqn`. `finding_ids=None` selects
    every eligible candidate; a list filters to those exact ids and hard-fails if any
    is unknown (or belongs to another class)."""
    _validate_version(facts)
    comp = _resolve_class(facts, class_fqn)
    # ONE canonical, root-confined path for the whole class — reused in every bundle,
    # in allowed_types, in the sort key, and in source_files.
    class_file, class_abs = _resolve_source(root, comp["file"])

    bundles: list[dict[str, Any]] = []
    for index, sub in enumerate(comp["subscriptions"]):
        sctx = f"{class_fqn}.subscriptions[{index}]"
        if not isinstance(sub, dict):
            raise CollectError(f"{sctx}: must be an object")
        fx = sub.get("fix")
        if fx is None:
            continue  # not a fix-eligible acquire (timer / nested / unresolved lane)
        if _field(sub, "released", "bool", sctx):
            continue  # a released subscription is not a leak, so not a candidate
        _field(sub, "event", "str", sctx)
        _field(sub, "handler", "str", sctx)
        _field(sub, "resource", "str", sctx)
        _validate_fix(fx, sctx)
        bundles.append(_bundle(sub, fx, class_fqn, class_file))

    available = {b["finding_id"] for b in bundles}
    if finding_ids is not None:
        missing = [fid for fid in finding_ids if fid not in available]
        if missing:
            raise CollectError(
                f"finding id(s) not found in class {class_fqn}: {', '.join(missing)}"
            )
        wanted = set(finding_ids)
        bundles = [b for b in bundles if b["finding_id"] in wanted]

    # Deterministic ordering: by file, then acquire start offset, then id (a stable
    # tie-break for two acquires that somehow share a start).
    bundles.sort(key=lambda b: (b["file"], b["acquire_span"]["start"], b["finding_id"]))

    source_files = [{"path": class_file, "sha256": _sha_of(class_abs)}]

    return {
        "version": 1,
        "operation": "fix-subscriptions",
        "target_api": {"subscribe": target_subscribe},
        "selection": {
            "allowed_types": [{"full_name": class_fqn, "file": class_file}],
            "selected_findings": list(finding_ids) if finding_ids is not None else None,
            "constraints": dict(_CONSTRAINTS),
        },
        "source_files": source_files,
        "candidates": bundles,
    }


# --- shared candidates.json validator (reused by S1 render + validate-plan) ---

_HEX = set("0123456789abcdef")


def _require_sha256(v: str, ctx: str) -> None:
    if not (v.startswith("sha256:") and len(v) == len("sha256:") + 64
            and all(ch in _HEX for ch in v[len("sha256:"):])):
        raise CollectError(f"{ctx}: {v!r} is not a 'sha256:<64hex>' value")


def _require_finding_id(v: str, ctx: str) -> None:
    parts = v.split(":sha256:")
    if (len(parts) != 2 or not parts[0].startswith("OWN") or len(parts[1]) != 64
            or any(ch not in _HEX for ch in parts[1])):
        raise CollectError(f"{ctx}: malformed finding_id {v!r}")


def _require_canonical_relpath(v: str, ctx: str) -> None:
    if v.startswith("/") or "\\" in v or (len(v) > 1 and v[1] == ":") or ".." in v.split("/"):
        raise CollectError(f"{ctx}: {v!r} is not a canonical root-relative path")


def validate_candidates_bundle(bundle: Any) -> None:
    """Validate a candidates.json (S0 output) against the contract S1's `render` and
    `validate-plan` both consume — version/operation, the pinned target, the S0 selection
    envelope (one type, one file), canonical root-relative source paths + SHA shape,
    unique finding ids, S1-only allowed_actions, and candidate file/type containment.
    Raises CollectError on any violation. Shared so the two commands never drift."""
    if not isinstance(bundle, dict):
        raise CollectError("candidates: bundle must be an object")
    if bundle.get("version") != 1 or isinstance(bundle.get("version"), bool):
        raise CollectError("candidates: version must be integer 1")
    if bundle.get("operation") != "fix-subscriptions":
        raise CollectError("candidates: operation must be 'fix-subscriptions'")

    target = _field(bundle, "target_api", "dict", "candidates")
    _field(target, "subscribe", "str", "candidates.target_api")

    sel = _field(bundle, "selection", "dict", "candidates")
    allowed_types = _field(sel, "allowed_types", "list", "candidates.selection")
    type_names = set()
    for i, t in enumerate(allowed_types):
        tctx = f"candidates.selection.allowed_types[{i}]"
        if not isinstance(t, dict):
            raise CollectError(f"{tctx}: must be an object")
        type_names.add(_field(t, "full_name", "str", tctx))
        _require_canonical_relpath(_field(t, "file", "str", tctx), tctx)
    cons = _field(sel, "constraints", "dict", "candidates.selection")
    if cons.get("max_types_changed") != 1 or cons.get("max_files_changed") != 1:
        raise CollectError(
            "candidates.selection.constraints: max_types_changed/max_files_changed must be 1"
        )
    for k in ("allow_helper_changes", "allow_config_changes", "allow_suppressions"):
        if cons.get(k) is not False:
            raise CollectError(f"candidates.selection.constraints.{k} must be false")

    source_paths = set()
    for i, sf in enumerate(_field(bundle, "source_files", "list", "candidates")):
        sctx = f"candidates.source_files[{i}]"
        if not isinstance(sf, dict):
            raise CollectError(f"{sctx}: must be an object")
        path = _field(sf, "path", "str", sctx)
        _require_canonical_relpath(path, sctx)
        _require_sha256(_field(sf, "sha256", "str", sctx), sctx)
        source_paths.add(path)

    seen_ids: set[str] = set()
    for i, c in enumerate(_field(bundle, "candidates", "list", "candidates")):
        cctx = f"candidates.candidates[{i}]"
        if not isinstance(c, dict):
            raise CollectError(f"{cctx}: must be an object")
        fid = _field(c, "finding_id", "str", cctx)
        _require_finding_id(fid, cctx)
        if fid in seen_ids:
            raise CollectError(f"{cctx}: duplicate finding_id {fid!r}")
        seen_ids.add(fid)
        ctype = _field(c, "containing_type", "str", cctx)
        cfile = _field(c, "file", "str", cctx)
        _require_canonical_relpath(cfile, cctx)
        for k in ("event", "event_contract", "source", "handler"):
            _field(c, k, "str", cctx)
        _validate_span(c.get("acquire_span"), cctx)
        _validate_teardown(c.get("teardown"), cctx)
        actions = _field(c, "allowed_actions", "list", cctx)
        if not actions or any(a not in S1_ACTIONS for a in actions):
            raise CollectError(
                f"{cctx}: allowed_actions must be a non-empty subset of {list(S1_ACTIONS)}"
            )
        if cfile not in source_paths:
            raise CollectError(f"{cctx}: file {cfile!r} is not in source_files")
        if ctype not in type_names:
            raise CollectError(
                f"{cctx}: containing_type {ctype!r} is not in selection.allowed_types"
            )
