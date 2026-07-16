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


def _norm(path: str) -> str:
    """Repo-relative, forward-slash form."""
    return path.replace("\\", "/")


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


def _sha_file(root: str, rel: str) -> str:
    full = os.path.join(root, rel)
    try:
        with open(full, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise CollectError(f"cannot read source file {rel!r} (under {root!r}): {exc}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _resolve_class(facts: dict[str, Any], class_fqn: str) -> dict[str, Any]:
    comps = [
        c
        for c in facts.get("components", [])
        if c.get("qualified_name") == class_fqn
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
    for flag, why in (
        ("is_partial", "partial"),
        ("is_nested", "nested"),
        ("is_generated", "generated"),
    ):
        if comp.get(flag):
            raise CollectError(f"class {class_fqn!r} is {why}; refused by MVP policy")
    return comp


def _bundle(
    comp: dict[str, Any], sub: dict[str, Any], fx: dict[str, Any], class_fqn: str
) -> dict[str, Any]:
    event_full = sub.get("event", "")
    event_name = fx["event_identity"].rsplit(".", 1)[-1]
    source_display = event_full[: event_full.rfind(".")] if "." in event_full else "this"
    contract = fx["event_contract"]
    diagnostic = "OWN014" if sub.get("resource") == "capture" else "OWN001"
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
        "file": _norm(comp.get("file", "")),
        "enclosing_member": fx["enclosing_member"],
        "event": event_name,
        "event_identity": fx["event_identity"],
        "event_contract": contract,
        "source": source_display,
        "source_identity": fx["source_identity"],
        "source_identity_kind": fx["source_identity_kind"],
        "handler": sub.get("handler", ""),
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
    comp = _resolve_class(facts, class_fqn)

    bundles: list[dict[str, Any]] = []
    for sub in comp.get("subscriptions") or []:
        fx = sub.get("fix")
        if not fx:
            continue  # not a fix-eligible acquire (timer / nested / unresolved lane)
        if sub.get("released"):
            continue  # a released subscription is not a leak, so not a candidate
        bundles.append(_bundle(comp, sub, fx, class_fqn))

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

    class_file = _norm(comp.get("file", ""))
    file_paths = sorted({b["file"] for b in bundles} | {class_file})
    source_files = [{"path": p, "sha256": _sha_file(root, p)} for p in file_paths]

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
