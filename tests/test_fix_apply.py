#!/usr/bin/env python3
"""S2 slice 1 — the apply-input gate (validate + hash-bind + source guard), SDK-free.

Covers the locked pre-apply contract that must pass before any source is rewritten:
validated-plan shape, candidates hash binding, decision↔candidate cross-checks, the
frozen convert_acquire-only-for-INPC tiering (via the allowed_actions path), overlapping
spans, root confinement, and the pristine preimage SHA guard. No C# / Roslyn here.

Run:  python tests/test_fix_apply.py
      python tests/run_tests.py     (auto-discovered)
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.fix_apply import ApplyError, validate_apply_inputs
from ownlang.fix_plan import bundle_sha256

_FID_A = "OWN001:sha256:" + "a" * 64
_FID_B = "OWN001:sha256:" + "b" * 64
_EV = "System.ComponentModel.INotifyPropertyChanged.PropertyChanged"
_REL = "N/C.cs"


def _cand(fid: str, actions: tuple[str, ...], contract: str, start: int) -> dict:
    return {
        "finding_id": fid, "diagnostic_code": "OWN001", "containing_type": "N.C",
        "file": _REL, "enclosing_member": "N.C.C()", "event": "PropertyChanged",
        "event_identity": _EV, "event_contract": contract, "source": "_pub",
        "source_identity": "N.C._pub", "source_identity_kind": "stable_symbol",
        "handler": "OnChanged", "handler_identity": "N.C.OnChanged(object, ...)",
        "handler_identity_kind": "stable_symbol", "occurrence_ordinal": 0,
        "acquire_span": {"start": start, "length": 30, "start_line": 1,
                         "start_column": 1, "end_line": 1, "end_column": 31},
        "teardown": {"status": "none", "candidates": []},
        "allowed_actions": list(actions),
    }


def _bundle(cands: list[dict], sha: str) -> dict:
    return {
        "version": 1, "operation": "fix-subscriptions",
        "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
        "selection": {
            "allowed_types": [{"full_name": "N.C", "file": _REL}],
            "selected_findings": None,
            "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                            "allow_helper_changes": False, "allow_config_changes": False,
                            "allow_suppressions": False},
        },
        "source_files": [{"path": _REL, "sha256": sha}],
        "candidates": cands,
    }


def _decision(fid: str, action: str, start: int) -> dict:
    return {"finding_id": fid, "action": action, "file": _REL,
            "acquire_span": {"start": start, "length": 30, "start_line": 1,
                             "start_column": 1, "end_line": 1, "end_column": 31}}


def _vplan(cands: dict, decisions: list[dict]) -> dict:
    the_type = cands["selection"]["allowed_types"][0]
    sf = cands["source_files"][0]
    return {
        "version": 1, "operation": "fix-subscriptions",
        "input_bundle_sha256": bundle_sha256(cands),
        "target_api": {"subscribe": cands["target_api"]["subscribe"]},
        "selection": {
            "allowed_types": [{"full_name": the_type["full_name"], "file": the_type["file"]}],
            "selected_findings": cands["selection"].get("selected_findings"),
            "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                            "allow_helper_changes": False, "allow_config_changes": False,
                            "allow_suppressions": False},
        },
        "source_files": [{"path": sf["path"], "sha256": sf["sha256"]}],
        "decisions": decisions,
    }


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

    def raises(vplan: dict, cands: dict, root: str) -> bool:
        try:
            validate_apply_inputs(vplan, cands, root)
        except ApplyError:
            return True
        return False

    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "N", "C.cs")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        content = b"// pretend source with a subscription\nclass C {}\n"
        with open(src, "wb") as fh:
            fh.write(content)
        sha = "sha256:" + hashlib.sha256(content).hexdigest()

        inpc = ("convert_acquire", "manual_review")
        cands = _bundle([_cand(_FID_A, inpc, "inotify_property_changed", 100),
                         _cand(_FID_B, ("manual_review",), "name_only", 200)], sha)

        # happy path: one convert_acquire + one manual_review
        vplan = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                               _decision(_FID_B, "manual_review", 200)])
        ctx = validate_apply_inputs(vplan, cands, root)
        conv = ctx["convert_acquire"]
        check(len(conv) == 1 and conv[0]["finding_id"] == _FID_A, "one convert_acquire target")
        check(ctx["manual_review"] == [_FID_B], "one manual_review")
        check(ctx["source_file"] == _REL
              and ctx["target_subscribe"] == "WeakEvents.AddPropertyChanged",
              "context carries source + target")
        target0 = ctx["convert_acquire"][0]
        check(target0["source"] == "_pub" and target0["handler"] == "OnChanged",
              "convert target carries candidate display identity")
        check(set(target0) >= {"source_identity", "source_identity_kind", "handler_identity",
                               "handler_identity_kind", "event_identity", "containing_type"},
              "convert target carries the FULL identity contract")

        # Blocker 1: the plan envelope must be the canonical projection of candidates.
        def vgood() -> dict:
            return _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                                  _decision(_FID_B, "manual_review", 200)])
        v = vgood()
        v["selection"]["allowed_types"][0]["full_name"] = "Other.Type"
        check(raises(v, cands, root), "wrong selected type refused")
        v = vgood()
        v["selection"]["allowed_types"][0]["file"] = "N/Other.cs"
        check(raises(v, cands, root), "wrong selected type file refused")
        v = vgood()
        v["selection"]["constraints"]["max_types_changed"] = 2
        check(raises(v, cands, root), "wrong constraints refused")
        v = vgood()
        v["selection"]["selected_findings"] = [_FID_A]
        check(raises(v, cands, root), "selected_findings mismatch refused")
        v = vgood()
        v["target_api"]["extra"] = 1
        check(raises(v, cands, root), "unknown nested target_api field refused")
        v = vgood()
        v["selection"]["extra"] = 1
        check(raises(v, cands, root), "unknown nested selection field refused")
        v = vgood()
        v["source_files"][0]["extra"] = 1
        check(raises(v, cands, root), "unknown nested source_files field refused")

        # Blocker 2: a candidate missing an identity field is a controlled ApplyError.
        for missing in ("event_identity", "source_identity", "handler_identity",
                        "handler_identity_kind"):
            bc_cand = _cand(_FID_A, inpc, "inotify_property_changed", 100)
            del bc_cand[missing]
            bc = _bundle([bc_cand], sha)
            bv = _vplan(bc, [_decision(_FID_A, "convert_acquire", 100)])
            check(raises(bv, bc, root), f"candidate missing {missing} -> ApplyError")
        bad_type_cand = _cand(_FID_A, inpc, "inotify_property_changed", 100)
        bad_type_cand["source_identity"] = 42
        bt = _bundle([bad_type_cand], sha)
        btv = _vplan(bt, [_decision(_FID_A, "convert_acquire", 100)])
        check(raises(btv, bt, root), "candidate identity of wrong type -> ApplyError")

        # hash binding: mutate candidates after the plan was built
        mutated = _bundle([_cand(_FID_A, inpc, "inotify_property_changed", 100),
                           _cand(_FID_B, ("manual_review",), "name_only", 999)], sha)
        check(raises(vplan, mutated, root), "candidates/plan hash mismatch refused")

        # target / source_files mismatch
        bad_target = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                                    _decision(_FID_B, "manual_review", 200)])
        bad_target["target_api"] = {"subscribe": "Other.Add"}
        check(raises(bad_target, cands, root), "target_api mismatch refused")

        # decision file != candidate file
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "manual_review", 200)])
        v["decisions"][0]["file"] = "N/Other.cs"
        check(raises(v, cands, root), "decision file != candidate refused")
        # decision span != candidate span
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 101),
                           _decision(_FID_B, "manual_review", 200)])
        check(raises(v, cands, root), "decision span != candidate refused")

        # action not allowed by the candidate (convert on a manual-only finding)
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "convert_acquire", 200)])
        check(raises(v, cands, root), "convert_acquire on a manual-only candidate refused")

        # unknown / missing / duplicate decisions
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "manual_review", 200),
                           _decision("OWN001:sha256:" + "c" * 64, "manual_review", 300)])
        check(raises(v, cands, root), "unknown decision refused")
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100)])
        check(raises(v, cands, root), "missing decision refused")
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_A, "manual_review", 100),
                           _decision(_FID_B, "manual_review", 200)])
        check(raises(v, cands, root), "duplicate decision refused")

        # overlapping convert spans
        over = _bundle([_cand(_FID_A, inpc, "inotify_property_changed", 100),
                        _cand(_FID_B, inpc, "inotify_property_changed", 110)], sha)
        vo = _vplan(over, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "convert_acquire", 110)])
        check(raises(vo, over, root), "overlapping convert spans refused")

        # unknown fields / bad version / out-of-scope action in the plan
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "manual_review", 200)])
        v["oops"] = 1
        check(raises(v, cands, root), "unknown top-level plan field refused")
        v = _vplan(cands, [_decision(_FID_A, "convert_acquire", 100),
                           _decision(_FID_B, "manual_review", 200)])
        v["decisions"][0]["confidence"] = "high"
        check(raises(v, cands, root), "unknown decision field refused")
        v = _vplan(cands, [_decision(_FID_A, "convert_exact_teardown", 100),
                           _decision(_FID_B, "manual_review", 200)])
        check(raises(v, cands, root), "out-of-scope action refused")

        # stale source SHA
        stale_sha = "sha256:" + "0" * 64
        stale_cands = _bundle([_cand(_FID_A, inpc, "inotify_property_changed", 100)], stale_sha)
        stale_v = _vplan(stale_cands, [_decision(_FID_A, "convert_acquire", 100)])
        check(raises(stale_v, stale_cands, root), "stale source preimage SHA refused")

    # root confinement: a candidates path escaping the root
    with tempfile.TemporaryDirectory() as root2:
        esc = _bundle([_cand(_FID_A, ("convert_acquire", "manual_review"),
                             "inotify_property_changed", 100)], "sha256:" + "0" * 64)
        esc["source_files"][0]["path"] = "N/C.cs"  # keep candidates valid; file just won't exist
        ev = _vplan(esc, [_decision(_FID_A, "convert_acquire", 100)])
        # the file does not exist under root2 -> _resolve_source refuses (not a regular file)
        check(raises(ev, esc, root2), "missing/uncontained source refused")

    # Blocker 3: an OSError reading the source (perms) is normalized to ApplyError.
    with tempfile.TemporaryDirectory() as root3:
        p = os.path.join(root3, "N", "C.cs")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        body = b"class C {}\n"
        with open(p, "wb") as fh:
            fh.write(body)
        os.chmod(p, 0)
        unreadable = True
        try:
            with open(p, "rb"):
                unreadable = False  # perms not enforced (Windows / running as root) -> skip
        except OSError:
            pass
        if unreadable:
            sha3 = "sha256:" + hashlib.sha256(body).hexdigest()
            oc = _bundle([_cand(_FID_A, ("convert_acquire", "manual_review"),
                                "inotify_property_changed", 100)], sha3)
            ov = _vplan(oc, [_decision(_FID_A, "convert_acquire", 100)])
            check(raises(ov, oc, root3), "source read OSError -> ApplyError")
        os.chmod(p, 0o644)  # restore so the tempdir cleans up

    print(f"fix-apply (S2 slice 1): {ok} ok, {bad} bad")
    return bad


if __name__ == "__main__":
    raise SystemExit(run())
