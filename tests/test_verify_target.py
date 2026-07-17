#!/usr/bin/env python3
"""S2 step 11 — the Verified Target Wrapper gate (Tier A, SDK-free).

Drives ownlang/fix_target.py without dotnet: the manual-only path is a full public
end-to-end (authority, delta binding, Step 8 bundle binding, reference-closure equality,
conditional inputs, the manual-only serializer, and atomic publication) in pure Python; the
classify precedence, the converted/manual-only serializers, the publisher, and the handler
peel are exercised over synthetic inputs. The real bind/probe over dotnet is the Tier-B job.

Run:  python tests/test_verify_target.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import fix_target as ft
from ownlang.fix_gate import _bundle_sha256, _canonical_bytes, _sha_bytes, validate_gate_authority

_EV = "System.ComponentModel.INotifyPropertyChanged.PropertyChanged"
_REL = "Own/Sample.cs"
_PRE = b"class A\n{\n    void M()\n    {\n        p.PropertyChanged += OnX;\n    }\n}\n"


def _cand(fid: str, start: int, dc: str = "OWN001", contract: str = "name_only",
          actions: list | None = None) -> dict:
    return {"finding_id": fid, "diagnostic_code": dc, "containing_type": "N.A", "file": _REL,
            "enclosing_member": "N.A..ctor(N.IPub)", "event": "PropertyChanged",
            "event_identity": _EV, "event_contract": contract, "source": "p",
            "source_identity": "p", "source_identity_kind": "computed", "handler": "OnX",
            "handler_identity": "N.A.OnX(object, ...)", "handler_identity_kind": "stable_symbol",
            "occurrence_ordinal": 0,
            "acquire_span": {"start": start, "length": 10, "start_line": 5,
                             "start_column": 9, "end_line": 5, "end_column": 19},
            "teardown": {"status": "none", "candidates": []},
            "allowed_actions": actions or ["manual_review"]}


def _cands(cs: list) -> dict:
    return {"version": 1, "operation": "fix-subscriptions",
            "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
            "selection": {"allowed_types": [{"full_name": "N.A", "file": _REL}],
                          "selected_findings": None,
                          "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                          "allow_helper_changes": False,
                                          "allow_config_changes": False,
                                          "allow_suppressions": False}},
            "source_files": [{"path": _REL, "sha256": _sha_bytes(_PRE)}], "candidates": cs}


def _plan(cands: dict, actions: list) -> dict:
    return {"version": 1, "operation": "fix-subscriptions",
            "input_bundle_sha256": _bundle_sha256(cands),
            "target_api": {"subscribe": cands["target_api"]["subscribe"]},
            "selection": {"allowed_types": [dict(cands["selection"]["allowed_types"][0])],
                          "selected_findings": cands["selection"]["selected_findings"],
                          "constraints": dict(cands["selection"]["constraints"])},
            "source_files": [dict(cands["source_files"][0])],
            "decisions": [{"finding_id": c["finding_id"], "action": actions[i],
                           "file": c["file"], "acquire_span": c["acquire_span"]}
                          for i, c in enumerate(cands["candidates"])]}


def _make_delta(cands_bytes: bytes, plan_bytes: bytes, auth, manifest_sha: str, patch_sha: str,
                pre_sha: str, post_sha: str, ref_closure: list) -> bytes:
    d = {
        "schema": 1, "operation": "verify-subscription-analyzer-delta", "status": "pass",
        "analysis_scope": {"source_file": _REL, "target_file_identity": _REL},
        "input_hashes": {
            "input_bundle_sha256": auth.input_bundle_sha256,
            "validated_plan_sha256": _sha_bytes(plan_bytes),
            "candidates_sha256": _sha_bytes(cands_bytes),
            "apply_manifest_sha256": manifest_sha, "patch_sha256": patch_sha,
            "pre_sha256": pre_sha, "post_sha256": post_sha,
        },
        "toolchain_fingerprint": {"resolved_runtime_identity": {
            "framework_name": "Microsoft.NETCore.App", "tfm": "net8.0",
            "requested_framework_version": "8.0.0", "selected_framework_version": "8.0.28",
            "runtime_manifest_sha256": "sha256:" + "0" * 64}},
        "target_api": {"subscribe": auth.target_subscribe},
        "expected": {"convert_acquire_ids": sorted(auth.applied),
                     "manual_review_ids": sorted(auth.manual)},
        "reference_closure": ref_closure,
        "checks": dict.fromkeys(ft._STEP10_CHECKS, "pass"),
    }
    return _canonical_bytes(d)


def _manual_fixture(tmp: str):
    """A manual-only chain (no dotnet): candidates all manual_review, an empty-patch bundle,
    and a delta that binds. Returns paths + bytes."""
    cands = _cands([_cand("OWN001:sha256:" + "1" * 64, 40)])
    plan = _plan(cands, ["manual_review"])
    cands_bytes = json.dumps(cands).encode()
    plan_bytes = json.dumps(plan).encode()
    auth = validate_gate_authority(plan, cands)
    root = os.path.join(tmp, "root")
    os.makedirs(os.path.join(root, os.path.dirname(_REL)))
    with open(os.path.join(root, *_REL.split("/")), "wb") as fh:
        fh.write(_PRE)
    bundle = os.path.join(tmp, "bundle")
    os.makedirs(os.path.join(bundle, "postimage", os.path.dirname(_REL)))
    with open(os.path.join(bundle, "postimage", *_REL.split("/")), "wb") as fh:
        fh.write(_PRE)  # manual-only: postimage == preimage
    with open(os.path.join(bundle, "change.patch"), "wb") as fh:
        fh.write(b"")
    manifest = b'{"manual":true}\n'
    with open(os.path.join(bundle, "apply-manifest.json"), "wb") as fh:
        fh.write(manifest)
    delta_bytes = _make_delta(cands_bytes, plan_bytes, auth, _sha_bytes(manifest),
                              _sha_bytes(b""), _sha_bytes(_PRE), _sha_bytes(_PRE), [])
    paths = {}
    for name, data in (("candidates.json", cands_bytes), ("plan.json", plan_bytes),
                       ("delta.json", delta_bytes)):
        paths[name] = os.path.join(tmp, name)
        with open(paths[name], "wb") as fh:
            fh.write(data)
    return root, bundle, paths, delta_bytes


def _attempt(**over) -> dict:
    a = {"attempt": 0, "strong_delivered_once": True, "strong_retained": True,
         "weak_control_collected": True, "delivered_count": 1, "threw_on_subscribe": False,
         "threw_on_first_raise": False, "subscriber_collected": True,
         "threw_on_post_collection_raise": False,
         "resolved_wrapper": {"ordinal": 0, "slot_sha256": "sha256:" + "a" * 64,
                              "assembly_simple_name": "WeakEvents",
                              "module_mvid": "d94f6f4c-0000-4000-8000-00000000abcd",
                              "metadata_token": "0x06000001",
                              "resolved_signature": "System.Void WeakEvents.M()"}}
    a.update(over)
    return a


_BINDING = {"resolved_wrapper": {"assembly_simple_name": "WeakEvents",
                                 "module_mvid": "d94f6f4c-0000-4000-8000-00000000abcd",
                                 "metadata_token": "0x06000001",
                                 "resolved_signature": "System.Void WeakEvents.M()"},
            "converted_callsites": 1, "derived_wrapper_ordinal": 0,
            "callsite_binding": {"all_callsites_same_symbol": True,
                                 "target_is_source_defined": False}}
_SLOTS = [{"ordinal": 0, "source_dir_ordinal": 0, "relative_path": "W.dll",
           "sha256": "sha256:" + "a" * 64}]


def _raises(cat, fn, *a) -> bool:
    try:
        fn(*a)
    except ft.TargetError as exc:
        return exc.category == cat
    return False


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

    # --- manual-only end-to-end (dotnet-free) ---------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root, bundle, paths, delta_bytes = _manual_fixture(tmp)
        outdir = os.path.join(tmp, "pub", "target")
        os.makedirs(os.path.join(tmp, "pub"))
        published = ft.run_verify_target(bundle, root, paths["plan.json"],
                                         paths["candidates.json"], paths["delta.json"], None,
                                         outdir, [], None)
        with open(os.path.join(published, "target-result.json"), "rb") as fh:
            res = json.loads(fh.read())
        check(res["status"] == "pass", "manual-only: status pass")
        na = {k for k, v in res["checks"].items() if v == "not_applicable"}
        check(na == set(ft._MANUAL_ONLY_NA), "manual-only: exactly the six not_applicable")
        check("selected_wrapper" not in res and "attempts" not in res,
              "manual-only: omits probe fields")
        check(os.listdir(published) == ["target-result.json"], "manual-only: only the artifact")

        # a manual-only plan must forbid --probe-dll / --wrapper-ordinal
        check(_raises(ft.INPUT_LAYOUT, ft.run_verify_target, bundle, root, paths["plan.json"],
                      paths["candidates.json"], paths["delta.json"], "x.dll",
                      os.path.join(tmp, "o2"), [], None),
              "manual-only + --probe-dll -> INPUT_LAYOUT")

        # tamper the delta -> DELTA_BINDING
        bad_delta = os.path.join(tmp, "baddelta.json")
        with open(bad_delta, "wb") as fh:
            fh.write(delta_bytes.replace(b'"status":"pass"', b'"status":"fail"'))
        check(_raises(ft.DELTA_BINDING, ft.run_verify_target, bundle, root, paths["plan.json"],
                      paths["candidates.json"], bad_delta, None, os.path.join(tmp, "o3"), [], None),
              "delta status fail -> DELTA_BINDING")

        # tamper the bundle postimage -> DELTA_BINDING (hash mismatch)
        with open(os.path.join(bundle, "postimage", *_REL.split("/")), "ab") as fh:
            fh.write(b"// tamper\n")
        check(_raises(ft.DELTA_BINDING, ft.run_verify_target, bundle, root, paths["plan.json"],
                      paths["candidates.json"], paths["delta.json"], None,
                      os.path.join(tmp, "o4"), [], None),
              "postimage hash mismatch -> DELTA_BINDING")

    # --- classify precedence matrix -------------------------------------------
    good = [_attempt(attempt=i) for i in range(3)]
    check(ft.classify(good, _BINDING, 0, _SLOTS) == "pass", "classify: all pass")
    retains = [_attempt(attempt=i, subscriber_collected=False) for i in range(3)]
    check(_raises(ft.TARGET_RETAINS, ft.classify, retains, _BINDING, 0, _SLOTS),
          "classify: retains -> TARGET_RETAINS")
    behav = [_attempt(attempt=i, delivered_count=0) for i in range(3)]
    check(_raises(ft.TARGET_BEHAVIOR, ft.classify, behav, _BINDING, 0, _SLOTS),
          "classify: delivered!=1 -> TARGET_BEHAVIOR")
    threw = [_attempt(attempt=i, threw_on_subscribe=True) for i in range(3)]
    check(_raises(ft.TARGET_BEHAVIOR, ft.classify, threw, _BINDING, 0, _SLOTS),
          "classify: threw on subscribe -> TARGET_BEHAVIOR")
    ctrl = [_attempt(attempt=0, strong_retained=False), _attempt(attempt=1), _attempt(attempt=2)]
    check(_raises(ft.HARNESS_INVALID, ft.classify, ctrl, _BINDING, 0, _SLOTS),
          "classify: broken strong control -> HARNESS_INVALID")
    wctrl = [_attempt(attempt=0, weak_control_collected=False), _attempt(attempt=1),
             _attempt(attempt=2)]
    check(_raises(ft.HARNESS_INVALID, ft.classify, wctrl, _BINDING, 0, _SLOTS),
          "classify: broken collectability control -> HARNESS_INVALID")
    disagree = [_attempt(attempt=0), _attempt(attempt=1, subscriber_collected=False),
                _attempt(attempt=2)]
    check(_raises(ft.HARNESS_NONDETERMINISM, ft.classify, disagree, _BINDING, 0, _SLOTS),
          "classify: disagreement -> HARNESS_NONDETERMINISM")
    ident = copy.deepcopy(good)
    ident[1]["resolved_wrapper"]["module_mvid"] = "00000000-0000-0000-0000-000000000000"
    check(_raises(ft.WRAPPER_BINDING, ft.classify, ident, _BINDING, 0, _SLOTS),
          "classify: attempt identity mismatch -> WRAPPER_BINDING")

    # --- serializers ----------------------------------------------------------
    ih = {"input_bundle_sha256": "sha256:" + "1" * 64,
          "validated_plan_sha256": "sha256:" + "1" * 64,
          "candidates_sha256": "sha256:" + "1" * 64, "apply_manifest_sha256": "sha256:" + "1" * 64,
          "patch_sha256": "sha256:" + "1" * 64, "pre_sha256": "sha256:" + "1" * 64,
          "post_sha256": "sha256:" + "1" * 64}
    delta_min = {"reference_closure": _SLOTS}
    conv = ft.build_converted_result(ih, b"x\n", delta_min, "WeakEvents.AddPropertyChanged",
                                     _SLOTS, 0, _BINDING, {"probe_deployment_manifest_sha256": "s",
                                                           "probe_runner_sha256": "s",
                                                           "probe_files": []}, "sha256:" + "0" * 64,
                                     "8.0.100", {"framework_name": "x"}, good, set(ft._CHECK_NAMES))
    check(set(conv["checks"]) == set(ft._CHECK_NAMES) and len(ft._CHECK_NAMES) == 11,
          "serializer: eleven checks (converted)")
    check(set(conv["checks"].values()) == {"pass"}, "serializer: converted all pass")
    check(conv["callsite_binding"]["asserted_wrapper_ordinal"] == 0
          and conv["callsite_binding"]["derived_wrapper_ordinal"] == 0,
          "serializer: derived == asserted ordinal recorded")
    check(len(conv["attempts"]) == 3
          and conv["probe_protocol"]["allocation_pressure_bytes_per_round"] == 4194304,
          "serializer: three attempts + fixed constants")
    check(_raises(ft.INFRASTRUCTURE, ft.build_converted_result, ih, b"x\n", delta_min, "T",
                  _SLOTS, 0, _BINDING, {"probe_deployment_manifest_sha256": "s",
                                        "probe_runner_sha256": "s", "probe_files": []},
                  "sha256:0", "8.0.100", {}, good, set(ft._CHECK_NAMES) - {"publication"}),
          "serializer: unexecuted check -> INFRASTRUCTURE")
    man = ft.build_manual_only_result(ih, b"x\n", delta_min, "T",
                                      {"input_layout", "authority_binding", "delta_binding",
                                       "reference_binding", "publication"})
    check({k for k, v in man["checks"].items() if v == "not_applicable"} == set(ft._MANUAL_ONLY_NA),
          "serializer: manual-only six not_applicable")

    # --- _publish_target ------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "root")
        pub = os.path.join(tmp, "pub")
        os.makedirs(root)
        os.makedirs(pub)
        out = os.path.join(pub, "ev")
        ft._publish_target(out, [root], b'{"ok":true}\n')
        check(os.listdir(out) == ["target-result.json"], "publish: only target-result.json")
        check([n for n in os.listdir(pub) if n.startswith(".owen-gate-")] == [],
              "publish: no workdir residue")
        check(_raises(ft.PUBLICATION, ft._publish_target, os.path.join(root, "x"), [root],
                      b'{}\n'), "publish: inside protected root -> PUBLICATION")
        # cleanup-failure normalization
        import shutil as _sh
        orig_rename, orig_rmtree = ft.os.rename, ft.shutil.rmtree

        def _boom(*_a, **_k):
            raise OSError("boom")

        try:
            ft.os.rename = _boom
            ft.shutil.rmtree = _boom
            check(_raises(ft.PUBLICATION, ft._publish_target, os.path.join(pub, "ev2"), [root],
                          b'{}\n'), "publish: cleanup failure -> PUBLICATION")
        finally:
            ft.os.rename, ft.shutil.rmtree = orig_rename, orig_rmtree
        _ = _sh

    # --- handler peel ---------------------------------------------------------
    check(ft._peel_handler("OnA") == "OnA", "peel: method group")
    check(ft._peel_handler("new PropertyChangedEventHandler(OnA)") == "OnA", "peel: new H(M)")
    check(ft._peel_handler("new(OnA)") == "OnA", "peel: new(M)")

    total = ok + bad
    print(f"verify-target (Tier A): {ok}/{total} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
