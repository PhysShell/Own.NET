#!/usr/bin/env python3
"""S1 — render + validate-plan (the invoke planner's Own.NET half), SDK-free tests.

Covers the locked acceptance set: the untrusted fix-plan validator (bijection, per-
candidate action permission, out-of-scope / unknown-field / malformed rejection), the
deterministic render + per-candidate `oneOf` schema, provenance-free materialization
that copies every non-action field from the candidates, the canned o7-result fixture,
a mock-glue chain, and CLI atomicity (a failed validate leaves no output). The live
`o7 invoke` smoke is a separate, documented one-shot (scripts/own-fix-plan.sh), not run
here so the suite stays offline.

Run:  python tests/test_fix_plan.py
      python tests/run_tests.py     (auto-discovered)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.__main__ import main
from ownlang.fix_candidates import CollectError
from ownlang.fix_plan import PlanError, bundle_sha256, render, validate_plan

_FID_A = "OWN001:sha256:" + "a" * 64
_FID_B = "OWN001:sha256:" + "b" * 64
_EV = "System.ComponentModel.INotifyPropertyChanged.PropertyChanged"


def _cand(fid: str, actions: tuple[str, ...] = ("convert_acquire", "manual_review"),
          contract: str = "inotify_property_changed", start: int = 100) -> dict:
    return {
        "finding_id": fid, "diagnostic_code": "OWN001", "containing_type": "N.C",
        "file": "N/C.cs", "enclosing_member": "N.C.C()", "event": "PropertyChanged",
        "event_identity": _EV, "event_contract": contract, "source": "_pub",
        "source_identity": "N.C._pub", "source_identity_kind": "stable_symbol",
        "handler": "OnChanged", "handler_identity": "N.C.OnChanged(object, ...)",
        "handler_identity_kind": "stable_symbol", "occurrence_ordinal": 0,
        "acquire_span": {"start": start, "length": 30, "start_line": 1,
                         "start_column": 1, "end_line": 1, "end_column": 31},
        "teardown": {"status": "none", "candidates": []},
        "allowed_actions": list(actions),
    }


def _bundle(cands: list[dict], **over: object) -> dict:
    b = {
        "version": 1, "operation": "fix-subscriptions",
        "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
        "selection": {
            "allowed_types": [{"full_name": "N.C", "file": "N/C.cs"}],
            "selected_findings": None,
            "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                            "allow_helper_changes": False, "allow_config_changes": False,
                            "allow_suppressions": False},
        },
        "source_files": [{"path": "N/C.cs", "sha256": "sha256:" + "0" * 64}],
        "candidates": cands,
    }
    b.update(over)
    return b


def _plan(decisions: list[dict], version: object = 1) -> dict:
    return {"version": version, "decisions": decisions}


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

    def plan_raises(bundle: dict, plan: object) -> bool:
        try:
            validate_plan(bundle, plan)
        except (PlanError, CollectError):
            return True
        return False

    # 1-2. valid convert_acquire / manual_review
    b1 = _bundle([_cand(_FID_A)])
    v = validate_plan(b1, _plan([{"finding_id": _FID_A, "action": "convert_acquire"}]))
    check(v["decisions"][0]["action"] == "convert_acquire", "valid convert_acquire")
    v = validate_plan(b1, _plan([{"finding_id": _FID_A, "action": "manual_review"}]))
    check(v["decisions"][0]["action"] == "manual_review", "valid manual_review")

    # 3. full bijection over two candidates
    b2 = _bundle([_cand(_FID_A, start=100), _cand(_FID_B, start=200)])
    v = validate_plan(b2, _plan([{"finding_id": _FID_A, "action": "manual_review"},
                                 {"finding_id": _FID_B, "action": "convert_acquire"}]))
    check(len(v["decisions"]) == 2, "full bijection accepted")

    # 4. unknown id
    check(plan_raises(b1, _plan([{"finding_id": _FID_B, "action": "manual_review"}])),
          "unknown finding_id refused")
    # 5. missing id (two candidates, one decision)
    check(plan_raises(b2, _plan([{"finding_id": _FID_A, "action": "manual_review"}])),
          "missing decision refused")
    # 6. duplicate id
    check(plan_raises(b1, _plan([{"finding_id": _FID_A, "action": "manual_review"},
                                 {"finding_id": _FID_A, "action": "convert_acquire"}])),
          "duplicate decision refused")
    # 7. action not allowed for this candidate (name_only -> manual_review only)
    b_no = _bundle([_cand(_FID_A, actions=("manual_review",), contract="name_only")])
    check(plan_raises(b_no, _plan([{"finding_id": _FID_A, "action": "convert_acquire"}])),
          "action not in candidate allowed_actions refused")
    # 8. out-of-scope action
    check(plan_raises(b1, _plan([{"finding_id": _FID_A, "action": "convert_exact_teardown"}])),
          "out-of-scope action refused")
    # 9 + 11. unknown / code-carrying fields
    check(plan_raises(b1, _plan([{"finding_id": _FID_A, "action": "manual_review",
                                  "confidence": "high"}])), "unknown field refused")
    check(plan_raises(b1, _plan([{"finding_id": _FID_A, "action": "manual_review",
                                  "patch": "diff --git ..."}])), "code/patch payload refused")
    # 10. malformed plan
    check(plan_raises(b1, "not a plan"), "non-object plan refused")
    check(plan_raises(b1, _plan([{"finding_id": _FID_A, "action": "manual_review"}], version=2)),
          "wrong plan version refused")
    check(plan_raises(b1, {"version": 1, "decisions": "x", "extra": 1}),
          "unknown top-level field refused")

    # 12-13. invalid candidates bundle
    check(plan_raises(_bundle([_cand(_FID_A)], version=2),
                      _plan([{"finding_id": _FID_A, "action": "manual_review"}])),
          "invalid candidates version refused")
    check(plan_raises(_bundle([_cand(_FID_A), _cand(_FID_A)]),
                      _plan([{"finding_id": _FID_A, "action": "manual_review"}])),
          "duplicate candidate ids refused")

    # 14. schema binds each id to ITS OWN allowed actions
    _, schema = render(b_no)
    one = schema["properties"]["decisions"]["items"]["oneOf"][0]
    check(one["properties"]["finding_id"]["const"] == _FID_A
          and one["properties"]["action"]["enum"] == ["manual_review"]
          and one["additionalProperties"] is False,
          "schema binds id -> its own allowed actions")
    dec = schema["properties"]["decisions"]
    check(dec["minItems"] == dec["maxItems"] == 1, "schema pins decision count")

    # 15-16. deterministic render bytes
    p1, s1 = render(b2)
    p2, s2 = render(b2)
    check(p1 == p2, "deterministic prompt bytes")
    check(json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True),
          "deterministic schema bytes")
    check("_pub" in p1 and "OnChanged" in p1, "prompt carries the finding's display names")
    # The finding_id (which legitimately contains "sha256:") is in the prompt; what must
    # NOT leak is the source path, the raw span, or the internal symbol identities.
    check("acquire_span" not in p1 and "source_identity" not in p1 and "N/C.cs" not in p1,
          "prompt omits path / span / identity internals")

    # 17. deterministic validated bytes regardless of model decision ORDER
    fwd = validate_plan(b2, _plan([{"finding_id": _FID_A, "action": "manual_review"},
                                   {"finding_id": _FID_B, "action": "convert_acquire"}]))
    rev = validate_plan(b2, _plan([{"finding_id": _FID_B, "action": "convert_acquire"},
                                   {"finding_id": _FID_A, "action": "manual_review"}]))
    check(json.dumps(fwd, sort_keys=True) == json.dumps(rev, sort_keys=True),
          "validated plan is order-independent")
    check([d["finding_id"] for d in fwd["decisions"]] == [_FID_A, _FID_B],
          "validated decisions are in candidates order")

    # 18. every non-action field is copied from the candidates, not the model
    v = validate_plan(b1, _plan([{"finding_id": _FID_A, "action": "convert_acquire"}]))
    d0 = v["decisions"][0]
    check(v["target_api"] == b1["target_api"] and v["selection"] == b1["selection"]
          and v["source_files"] == b1["source_files"]
          and d0["file"] == "N/C.cs" and d0["acquire_span"] == b1["candidates"][0]["acquire_span"]
          and set(d0) == {"finding_id", "action", "file", "acquire_span"},
          "non-action fields copied from candidates only")
    # 19. input_bundle_sha256
    check(v["input_bundle_sha256"] == bundle_sha256(b1), "input_bundle_sha256 correct")

    # 20. canned o7-result fixture -> expected validated plan
    fx = os.path.join(
        os.path.dirname(__file__), "fixtures", "o7-invoke", "subscription-fix-plan-v1"
    )
    with open(os.path.join(fx, "candidates.json"), encoding="utf-8") as fh:
        fx_cands = json.load(fh)
    with open(os.path.join(fx, "o7-result.json"), encoding="utf-8") as fh:
        fx_result = json.load(fh)
    with open(os.path.join(fx, "expected-validated-plan.json"), encoding="utf-8") as fh:
        fx_expected = json.load(fh)
    check(validate_plan(fx_cands, fx_result) == fx_expected,
          "canned o7-result -> expected validated plan")

    # 21-22. CLI atomicity + mock glue (render -> canned result -> validate) via main()
    with tempfile.TemporaryDirectory() as d:
        cpath = os.path.join(d, "candidates.json")
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump(b1, fh)
        # a failing validate leaves NO output file
        badplan = os.path.join(d, "bad.json")
        with open(badplan, "w", encoding="utf-8") as fh:
            json.dump(_plan([{"finding_id": _FID_B, "action": "manual_review"}]), fh)
        outp = os.path.join(d, "validated.json")
        rc = main(["own-fix", "subscriptions", "validate-plan", cpath, badplan, "--output", outp])
        check(rc == 2 and not os.path.exists(outp), "failed validate leaves no output (atomic)")
        # mock glue: render (schema/prompt) then feed a canned matching plan through validate
        pr = os.path.join(d, "prompt.txt")
        sc = os.path.join(d, "schema.json")
        rc_r = main(
            ["own-fix", "subscriptions", "render", cpath, "--prompt", pr, "--schema", sc]
        )
        check(rc_r == 0, "render CLI ok")
        goodplan = os.path.join(d, "good.json")
        with open(goodplan, "w", encoding="utf-8") as fh:
            json.dump(_plan([{"finding_id": _FID_A, "action": "convert_acquire"}]), fh)
        rc = main(["own-fix", "subscriptions", "validate-plan", cpath, goodplan, "--output", outp])
        check(rc == 0 and os.path.exists(outp), "mock glue: render + validate CLI ok")

    print(f"fix-plan (S1): {ok} ok, {bad} bad")
    return bad


if __name__ == "__main__":
    raise SystemExit(run())
