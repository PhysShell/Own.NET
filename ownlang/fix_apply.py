"""S2 slice 1 — the strict apply-input gate: validate the S1 validated-plan.json, bind
it by hash to its candidates.json, cross-check every decision against its candidate, and
guard the source file (SHA + root confinement). NOTHING here parses C# or writes a byte;
it is the untrusted-input gate that must pass before the (later-slice) `Owen.CSharp.Rewriter`
is allowed to touch source.

Two hash-bound inputs (arbiter): the validated-plan is the sole authority for `action`;
the candidates bundle is the untrusted-but-hash-bound source of the syntax/semantic
context (event / source / handler identity, containing type) the rewriter's span-node
guard needs. `bundle_sha256(candidates) == validated_plan.input_bundle_sha256` binds them.
A stale source, an escaping path, a decision that disagrees with its candidate, or a
convert_acquire on a non-INotifyPropertyChanged contract is a hard refusal.
"""

from __future__ import annotations

import hashlib
from itertools import pairwise
from typing import Any

from ownlang.fix_candidates import (
    S1_ACTIONS,
    CollectError,
    _field,
    _require_canonical_relpath,
    _require_finding_id,
    _require_sha256,
    _resolve_source,
    _validate_span,
    validate_candidates_bundle,
)
from ownlang.fix_plan import bundle_sha256

_PLAN_KEYS = {
    "version", "operation", "input_bundle_sha256", "target_api",
    "selection", "source_files", "decisions",
}
_DECISION_KEYS = {"finding_id", "action", "file", "acquire_span"}


class ApplyError(Exception):
    """A malformed / unbound / stale apply input. A hard, controlled refusal — never a
    traceback, never a partial apply."""


def validate_validated_plan(plan: Any) -> None:
    """Validate the shape of an S1 validated-plan.json (fix_plan.validate_plan's output).
    Raises ApplyError on any violation."""
    if not isinstance(plan, dict):
        raise ApplyError("validated-plan must be an object")
    unknown = sorted(set(plan) - _PLAN_KEYS)
    if unknown:
        raise ApplyError(f"validated-plan has unknown field(s): {unknown}")
    if plan.get("version") != 1 or isinstance(plan.get("version"), bool):
        raise ApplyError("validated-plan version must be integer 1")
    if plan.get("operation") != "fix-subscriptions":
        raise ApplyError("validated-plan operation must be 'fix-subscriptions'")
    try:
        _require_sha256(
            _field(plan, "input_bundle_sha256", "str", "validated-plan"),
            "validated-plan.input_bundle_sha256",
        )
        _field(_field(plan, "target_api", "dict", "validated-plan"), "subscribe", "str",
               "validated-plan.target_api")
        sel = _field(plan, "selection", "dict", "validated-plan")
        at = _field(sel, "allowed_types", "list", "validated-plan.selection")
        if len(at) != 1:
            raise ApplyError("validated-plan.selection.allowed_types must have exactly one entry")
        sfs = _field(plan, "source_files", "list", "validated-plan")
        if len(sfs) != 1:
            raise ApplyError("validated-plan.source_files must have exactly one entry")
        sf = sfs[0]
        if not isinstance(sf, dict):
            raise ApplyError("validated-plan.source_files[0] must be an object")
        _require_canonical_relpath(_field(sf, "path", "str", "validated-plan.source_files[0]"),
                                   "validated-plan.source_files[0]")
        _require_sha256(_field(sf, "sha256", "str", "validated-plan.source_files[0]"),
                        "validated-plan.source_files[0]")
        for i, d in enumerate(_field(plan, "decisions", "list", "validated-plan")):
            dctx = f"validated-plan.decisions[{i}]"
            if not isinstance(d, dict):
                raise ApplyError(f"{dctx}: must be an object")
            extra = sorted(set(d) - _DECISION_KEYS)
            if extra:
                raise ApplyError(f"{dctx}: unknown field(s) {extra}")
            _require_finding_id(_field(d, "finding_id", "str", dctx), dctx)
            action = _field(d, "action", "str", dctx)
            if action not in S1_ACTIONS:
                raise ApplyError(f"{dctx}: out-of-scope action {action!r}")
            _require_canonical_relpath(_field(d, "file", "str", dctx), dctx)
            _validate_span(d.get("acquire_span"), dctx)
    except CollectError as exc:
        raise ApplyError(f"validated-plan: {exc}") from exc


def _sha_file(abs_path: str) -> str:
    with open(abs_path, "rb") as fh:
        return "sha256:" + hashlib.sha256(fh.read()).hexdigest()


def validate_apply_inputs(
    validated_plan: dict[str, Any], candidates: dict[str, Any], root: str
) -> dict[str, Any]:
    """Run the full S2 pre-apply gate over the two hash-bound inputs + the source root.
    Returns an apply CONTEXT (the convert_acquire targets with their candidate identities,
    the manual_review ids, the source path, the target API) once every guard passes.
    Raises ApplyError on any violation — no source is read for rewriting, only hashed."""
    validate_validated_plan(validated_plan)
    try:
        validate_candidates_bundle(candidates)
    except CollectError as exc:
        raise ApplyError(f"invalid candidates bundle: {exc}") from exc

    # Hash binding: the candidates are the plan's own input.
    if bundle_sha256(candidates) != validated_plan["input_bundle_sha256"]:
        raise ApplyError("candidates sha256 does not match validated-plan.input_bundle_sha256")
    if validated_plan["target_api"] != candidates["target_api"]:
        raise ApplyError("validated-plan.target_api does not match candidates.target_api")
    if validated_plan["source_files"] != candidates["source_files"]:
        raise ApplyError("validated-plan.source_files does not match candidates.source_files")

    candidate_by_id = {c["finding_id"]: c for c in candidates["candidates"]}
    seen: set[str] = set()
    convert: list[dict[str, Any]] = []
    manual: list[str] = []
    for d in validated_plan["decisions"]:
        fid = d["finding_id"]
        if fid not in candidate_by_id:
            raise ApplyError(f"decision {fid!r} is not a candidate")
        if fid in seen:
            raise ApplyError(f"duplicate decision {fid!r}")
        seen.add(fid)
        c = candidate_by_id[fid]
        if d["file"] != c["file"]:
            raise ApplyError(f"{fid}: decision file != candidate file")
        if d["acquire_span"] != c["acquire_span"]:
            raise ApplyError(f"{fid}: decision acquire_span != candidate acquire_span")
        if d["action"] not in c["allowed_actions"]:
            raise ApplyError(f"{fid}: action {d['action']!r} not allowed by candidate")
        if d["action"] == "convert_acquire":
            if c["event_contract"] != "inotify_property_changed":
                raise ApplyError(
                    f"{fid}: convert_acquire requires an inotify_property_changed contract"
                )
            convert.append({
                "finding_id": fid,
                "file": c["file"],
                "acquire_span": c["acquire_span"],
                "containing_type": c["containing_type"],
                "event": c["event"],
                "event_identity": c["event_identity"],
                "source": c["source"],
                "handler": c["handler"],
            })
        else:
            manual.append(fid)
    missing = set(candidate_by_id) - seen
    if missing:
        raise ApplyError(f"missing decisions for: {sorted(missing)}")

    # convert_acquire edit spans must not overlap.
    ranges = sorted(
        (e["acquire_span"]["start"], e["acquire_span"]["start"] + e["acquire_span"]["length"])
        for e in convert
    )
    for (_, end_a), (start_b, _) in pairwise(ranges):
        if start_b < end_a:
            raise ApplyError("overlapping convert_acquire spans")

    # Source guard: confine to root, then match the pristine preimage SHA.
    source = candidates["source_files"][0]
    try:
        canonical, abs_path = _resolve_source(root, source["path"])
    except CollectError as exc:
        raise ApplyError(f"source path: {exc}") from exc
    if _sha_file(abs_path) != source["sha256"]:
        raise ApplyError(f"STALE SOURCE / PREIMAGE MISMATCH for {canonical}")

    return {
        "source_file": canonical,
        "target_subscribe": validated_plan["target_api"]["subscribe"],
        "convert_acquire": convert,
        "manual_review": manual,
    }
