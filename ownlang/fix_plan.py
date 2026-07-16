"""S1 — the invoke planner's Own.NET half: render a prompt + a per-candidate JSON
Schema from a candidates.json, and validate the (UNTRUSTED) o7-invoke fix-plan back
against it. No source is touched, no model text is trusted, and Own.NET never calls
o7 — a thin orchestration script wires render -> o7 invoke -> validate.

The model's authority is minimal by construction: for each candidate finding it
returns exactly one `{finding_id, action}` and nothing else. `action` is constrained
per-finding to that candidate's own allowed_actions (S1 = convert_acquire on a proven
INotifyPropertyChanged contract, else manual_review). No spans, no code, no patches,
no free text — the schema and the validator both use additionalProperties:false, and
validate-plan re-derives every non-action field (file / span / target / SHA) from the
candidates bundle so the executable plan carries nothing the model authored.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ownlang.fix_candidates import S1_ACTIONS, CollectError, validate_candidates_bundle


class PlanError(Exception):
    """A malformed candidates bundle or an untrusted fix-plan that fails validation."""


def _canonical_bytes(obj: Any) -> bytes:
    """Order-independent canonical JSON bytes (for the input-bundle hash)."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def bundle_sha256(bundle: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(bundle)).hexdigest()


_PROMPT_HEADER = (
    "You are choosing a remediation action for each event-subscription leak below.\n"
    "For EACH finding, choose exactly one action from that finding's own allowed list.\n"
    "convert_acquire means: convert the subscription to the project's weak wrapper.\n"
    "manual_review means: leave it for a human.\n\n"
    "Output ONLY a single JSON object and NOTHING else — no prose, no markdown, no code\n"
    "fences, no headings, no explanation before or after. The object must be exactly:\n"
    '  {"version": 1, "decisions": [ {"finding_id": "<id>", "action": "<action>"}, ... ]}\n'
    "with one decision per finding and no other fields.\n\n"
)


def render(bundle: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (prompt, schema) for `o7 invoke`. Both are byte-deterministic. The prompt
    is a minimal projection of the candidates (no source, no spans, no SHA, no absolute
    paths); the schema binds each finding id (as a `const`) to ITS OWN allowed actions."""
    validate_candidates_bundle(bundle)
    candidates = bundle["candidates"]

    lines = [_PROMPT_HEADER]
    for c in candidates:
        lines.append(f"Finding: {c['finding_id']}")
        lines.append(f"Event contract: {c['event_contract']}")
        lines.append(f"Event: {c['event']}")
        lines.append(f"Source: {c['source']}")
        lines.append(f"Handler: {c['handler']}")
        lines.append(f"Teardown status: {c['teardown']['status']}")
        lines.append("Allowed actions:")
        for action in c["allowed_actions"]:
            lines.append(f"- {action}")
        lines.append("")
    prompt = "\n".join(lines)

    decision_schemas = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["finding_id", "action"],
            "properties": {
                "finding_id": {"const": c["finding_id"]},
                "action": {"enum": list(c["allowed_actions"])},
            },
        }
        for c in candidates
    ]
    count = len(candidates)
    # A zero-candidate bundle is legitimate (a class with no unreleased subscriptions).
    # An empty `oneOf` is not valid Draft 2020-12, so emit `items: false` (a 0-length
    # array is the only valid instance) instead of `{"oneOf": []}`.
    if count == 0:
        decisions_schema: dict[str, Any] = {
            "type": "array", "minItems": 0, "maxItems": 0, "items": False,
        }
    else:
        decisions_schema = {
            "type": "array", "minItems": count, "maxItems": count,
            "items": {"oneOf": decision_schemas},
        }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "decisions"],
        "properties": {"version": {"const": 1}, "decisions": decisions_schema},
    }
    return prompt, schema


def validate_plan(bundle: dict[str, Any], plan: Any) -> dict[str, Any]:
    """Validate the UNTRUSTED fix-plan against the candidates bundle and materialize the
    executable validated plan. A full bijection between candidate and decision finding
    ids is required; `action` is the only model-authored field; every other field is
    copied from the candidates. Raises PlanError on any violation."""
    # The function contract is "raises PlanError"; a malformed candidates bundle raises
    # CollectError, so normalize it here rather than leak a second exception type to the
    # CLI (which would surface as an uncontrolled traceback).
    try:
        validate_candidates_bundle(bundle)
    except CollectError as exc:
        raise PlanError(f"invalid candidates bundle: {exc}") from exc

    if not isinstance(plan, dict):
        raise PlanError("fix-plan must be an object")
    extra_top = sorted(set(plan) - {"version", "decisions"})
    if extra_top:
        raise PlanError(f"fix-plan has unknown field(s): {extra_top}")
    if plan.get("version") != 1 or isinstance(plan.get("version"), bool):
        raise PlanError("fix-plan version must be integer 1")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list):
        raise PlanError("fix-plan decisions must be a list")

    candidate_by_id = {c["finding_id"]: c for c in bundle["candidates"]}
    action_by_id: dict[str, str] = {}
    for i, d in enumerate(decisions):
        dctx = f"decisions[{i}]"
        if not isinstance(d, dict):
            raise PlanError(f"{dctx}: must be an object")
        extra = sorted(set(d) - {"finding_id", "action"})
        if extra:
            raise PlanError(f"{dctx}: unknown field(s) {extra} (only finding_id + action allowed)")
        fid = d.get("finding_id")
        action = d.get("action")
        if not isinstance(fid, str) or not isinstance(action, str):
            raise PlanError(f"{dctx}: finding_id and action must be strings")
        if fid not in candidate_by_id:
            raise PlanError(f"{dctx}: unknown finding_id {fid!r}")
        if fid in action_by_id:
            raise PlanError(f"{dctx}: duplicate finding_id {fid!r}")
        if action not in S1_ACTIONS:
            raise PlanError(f"{dctx}: out-of-scope action {action!r}")
        if action not in candidate_by_id[fid]["allowed_actions"]:
            raise PlanError(f"{dctx}: action {action!r} is not allowed for {fid!r}")
        action_by_id[fid] = action

    missing = set(candidate_by_id) - set(action_by_id)
    if missing:
        raise PlanError(f"fix-plan is missing a decision for: {sorted(missing)}")

    # Materialize deterministically in the candidates' own order; every field except
    # `action` is re-derived from the bundle, so nothing the model authored survives.
    materialized = [
        {
            "finding_id": c["finding_id"],
            "action": action_by_id[c["finding_id"]],
            "file": c["file"],
            "acquire_span": c["acquire_span"],
        }
        for c in bundle["candidates"]
    ]
    # Canonical projection: rebuild target_api / selection / source_files from their
    # KNOWN keys (validated above) rather than copying the input dicts, so no unknown
    # nested field the model or an edited bundle slipped in can ride into the executable
    # artifact. input_bundle_sha256 still hashes the ORIGINAL input bytes.
    the_type = bundle["selection"]["allowed_types"][0]
    the_source = bundle["source_files"][0]
    return {
        "version": 1,
        "operation": "fix-subscriptions",
        "input_bundle_sha256": bundle_sha256(bundle),
        "target_api": {"subscribe": bundle["target_api"]["subscribe"]},
        "selection": {
            "allowed_types": [{"full_name": the_type["full_name"], "file": the_type["file"]}],
            "selected_findings": bundle["selection"].get("selected_findings"),
            "constraints": {
                "max_types_changed": 1,
                "max_files_changed": 1,
                "allow_helper_changes": False,
                "allow_config_changes": False,
                "allow_suppressions": False,
            },
        },
        "source_files": [{"path": the_source["path"], "sha256": the_source["sha256"]}],
        "decisions": materialized,
    }
