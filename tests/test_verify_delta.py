#!/usr/bin/env python3
"""S2 step 10 — the analyzer-delta verifier (SDK-free unit + fixture tests).

This module drives `ownlang/fix_delta.py` without a live .NET SDK. The pure classifier
(the two-representation OWN001/OWN050 delta), the closed core.json schema, the atomic
publisher (LA3), the OWN001-only scope guard (LA2), the exact Step 9 gate binding, and
the reference-closure snapshot are all exercised over synthetic inputs. The end-to-end
run over the real fresh core subprocess (still no dotnet) lives in `_fixture_core`; the
real extractor run is the Tier-B CI job.

Run:  python tests/test_verify_delta.py
      python tests/run_tests.py     (auto-discovered)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import fix_delta as fd
from ownlang.fix_gate import _build_evidence, _bundle_sha256

_EV = "System.ComponentModel.INotifyPropertyChanged.PropertyChanged"
_FILE = "Own/Sample.cs"
_TYPE = "Own.Sample.TwoOnOneLine"
_FIDA = "OWN001:sha256:" + "a" * 64
_FIDB = "OWN001:sha256:" + "b" * 64
_FIDC = "OWN001:sha256:" + "c" * 64
_SPAN = {"start": 100, "length": 30, "start_line": 10, "start_column": 1,
         "end_line": 10, "end_column": 31}


def _obs(event: str = "_a.PropertyChanged", handler: str = "OnA",
         component: str = "TwoOnOneLine", file: str = _FILE, kind: str = "subscription token",
         advisory: bool = False, severity: object = "warning",
         ignore_reason: object = None) -> dict:
    return {"file": file, "code": "OWN001", "component": component, "event": event,
            "handler": handler, "kind": kind, "advisory": advisory, "severity": severity,
            "ignore_reason": ignore_reason}


def _own050(event: str = "x.Changed", handler: str = "OnX",
            component: str = "TwoOnOneLine", file: str = _FILE) -> dict:
    return {"file": file, "component": component, "event": event, "handler": handler}


def _record(fid: str, handler: str = "OnA", source: str = "_a") -> dict:
    return {"finding_id": fid, "diagnostic_code": "OWN001", "containing_type": _TYPE,
            "file": _FILE, "enclosing_member": _TYPE + ".ctor()", "event": "PropertyChanged",
            "event_identity": _EV, "event_contract": "inotify_property_changed",
            "source": source, "source_identity": _TYPE + "." + source,
            "source_identity_kind": "stable_symbol", "handler": handler,
            "handler_identity": _TYPE + "." + handler + "(object, ...)",
            "handler_identity_kind": "stable_symbol", "occurrence_ordinal": 0,
            "acquire_span": dict(_SPAN), "teardown": {"status": "none", "candidates": []},
            "allowed_actions": ["convert_acquire", "manual_review"]}


def _elig(fid: str, event: str = "_a.PropertyChanged", handler: str = "OnA",
          dc: str = "OWN001", source: str = "_a") -> dict:
    return {"finding_id": fid, "diagnostic_code": dc,
            "bridge_key": {"file": _FILE, "component": "TwoOnOneLine",
                           "event": event, "handler": handler},
            "record": _record(fid, handler, source)}


def _image(all_own001: list, own050: list, eligible: list) -> dict:
    return {"all_own001": all_own001, "own050": own050,
            "fix_eligible_subscriptions": eligible}


def _raises(cat: str, fn, *a) -> bool:
    try:
        fn(*a)
    except fd.DeltaError as exc:
        return exc.category == cat
    return False


# --- realistic plan / candidates / gate builders (slice 2) -------------------------

_REL = "Own/Sample.cs"
_PRE = b"class A\n{\n    void M()\n    {\n        p.PropertyChanged += OnX;\n    }\n}\n"
_POST = _PRE.replace(b"p.PropertyChanged += OnX;", b"WeakEvents.AddPropertyChanged(p, OnX);")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _bcand(fid: str, start: int, dc: str = "OWN001",
           contract: str = "inotify_property_changed", actions: list | None = None) -> dict:
    return {"finding_id": fid, "diagnostic_code": dc, "containing_type": "N.A", "file": _REL,
            "enclosing_member": "N.A..ctor(N.IPub)", "event": "PropertyChanged",
            "event_identity": _EV, "event_contract": contract, "source": "p",
            "source_identity": "p", "source_identity_kind": "computed", "handler": "OnX",
            "handler_identity": "N.A.OnX(object, ...)", "handler_identity_kind": "stable_symbol",
            "occurrence_ordinal": 0,
            "acquire_span": {"start": start, "length": 10, "start_line": 5,
                             "start_column": 9, "end_line": 5, "end_column": 19},
            "teardown": {"status": "none", "candidates": []},
            "allowed_actions": actions or ["convert_acquire", "manual_review"]}


def _bcands(cands: list) -> dict:
    return {"version": 1, "operation": "fix-subscriptions",
            "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
            "selection": {"allowed_types": [{"full_name": "N.A", "file": _REL}],
                          "selected_findings": None,
                          "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                          "allow_helper_changes": False,
                                          "allow_config_changes": False,
                                          "allow_suppressions": False}},
            "source_files": [{"path": _REL, "sha256": _sha(_PRE)}], "candidates": cands}


def _bplan(cands: dict, actions: list) -> dict:
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


# --- facts builders for the real fresh-core-subprocess fixture (slices 3-5) ---------

_CTYPE = "Own.Samples.TwoOnOneLine"
_CREL = "Own/Samples/TwoOnOneLine.cs"


def _cfix(handler: str = "OnA", source: str = "_a", ordinal: int = 0, start: int = 100) -> dict:
    return {"enclosing_member": _CTYPE + ".ctor()", "event_identity": _EV,
            "event_contract": "inotify_property_changed",
            "source_identity": _CTYPE + "." + source, "source_identity_kind": "stable_symbol",
            "handler_identity": _CTYPE + "." + handler + "(object, ...)",
            "handler_identity_kind": "stable_symbol", "occurrence_ordinal": ordinal,
            "span": {"start": start, "length": 30, "start_line": 10, "start_column": 1,
                     "end_line": 10, "end_column": 31},
            "teardown": {"status": "none", "candidates": []}}


def _csub(fix: dict, event: str, handler: str) -> dict:
    return {"event": event, "handler": handler, "line": 10, "released": False,
            "resource": "subscription", "source": "injected", "lambda": False, "fix": fix}


def _cfacts(subs: list) -> dict:
    comp = {"name": _CTYPE.rsplit(".", 1)[-1], "qualified_name": _CTYPE, "is_partial": False,
            "is_nested": False, "declaration_count": 1, "is_generated": False,
            "file": _CREL, "subscriptions": subs}
    return {"ownir_version": 0, "fix_candidates_version": 1, "components": [comp]}


def _mk_root(work: str) -> str:
    d = tempfile.mkdtemp(dir=work)
    src = os.path.join(d, *_CREL.split("/"))
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "wb") as fh:
        fh.write(b"// sample\nnamespace Own.Samples { class TwoOnOneLine {} }\n")
    return d


def _candidates_from(records: list) -> dict:
    return {"version": 1, "operation": "fix-subscriptions",
            "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
            "selection": {"allowed_types": [{"full_name": _CTYPE, "file": _CREL}],
                          "selected_findings": None,
                          "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                          "allow_helper_changes": False,
                                          "allow_config_changes": False,
                                          "allow_suppressions": False}},
            "source_files": [{"path": _CREL, "sha256": "sha256:" + "0" * 64}],
            "candidates": list(records)}


def _fixture_core_fails() -> tuple[int, list[str]]:
    """Drive the REAL fresh core subprocess (snapshotted ownlang, python -S -B -E) over
    synthetic --fix-candidates facts. No dotnet. Proves LA1 (runner fingerprint + verify),
    LA4 (closed core.json), the analyzer-to-id bridge, and baseline authority end to end."""
    checks = 0
    fails: list[str] = []

    def cf(cond: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(label)

    target = "WeakEvents.AddPropertyChanged"
    with tempfile.TemporaryDirectory() as work:
        core_dir, runner_path, runner_sha, core_fp = fd.materialize_core(work)
        py, pyfp = fd.resolve_python()
        cf(core_fp["core_runner_sha256"] == fd._sha_bytes(fd.RUN_CORE_SOURCE.encode("utf-8")),
           "fixture: core_runner_sha256 == hash of RUN_CORE_SOURCE")
        cf(len(pyfp["python_executable_sha256"]) == len("sha256:") + 64,
           "fixture: python executable fingerprinted")

        base_facts = _cfacts([_csub(_cfix("OnA", "_a", 0, 100), "_a.PropertyChanged", "OnA"),
                              _csub(_cfix("OnB", "_b", 1, 200), "_b.PropertyChanged", "OnB")])
        post_facts = _cfacts([_csub(_cfix("OnB", "_b", 1, 200), "_b.PropertyChanged", "OnB")])
        base_root, post_root = _mk_root(work), _mk_root(work)

        def params(root: str) -> dict:
            return {"root": root, "target_subscribe": target, "class_fqn": _CTYPE}

        base = fd.run_core(core_dir, runner_path, py, runner_sha, base_root,
                           json.dumps(base_facts).encode(), params(base_root), fd.BASELINE_ANALYSIS)
        post = fd.run_core(core_dir, runner_path, py, runner_sha, post_root,
                           json.dumps(post_facts).encode(), params(post_root),
                           fd.POSTIMAGE_ANALYSIS)
        cf(len(base["all_own001"]) == 2, "fixture: baseline has 2 OWN001")
        cf(len(post["all_own001"]) == 1, "fixture: postimage has 1 OWN001")

        recs = {e["record"]["handler"]: e for e in base["fix_eligible_subscriptions"]}
        cf(set(recs) == {"OnA", "OnB"}, "fixture: two fix-eligible subscriptions")
        fid_a, fid_b = recs["OnA"]["finding_id"], recs["OnB"]["finding_id"]
        candidates = _candidates_from([recs["OnA"]["record"], recs["OnB"]["record"]])

        fd.check_baseline_authority(candidates, base)
        fd.check_target_identity(base, _CREL)
        fd.check_target_identity(post, _CREL)
        res = fd.classify_delta({"convert_acquire_ids": [fid_a], "manual_review_ids": [fid_b]},
                                base, post)
        cf(res["delta"]["removed_subscription_own001_ids"] == [fid_a], "fixture: OnA removed")
        cf(res["delta"]["preserved_subscription_own001_ids"] == [fid_b], "fixture: OnB preserved")
        cf(len(res["delta"]["removed_all_own001"]) == 1, "fixture: exactly one core removed")

        # baseline-authority mismatch -> ANALYSIS_SCOPE
        import copy
        bad_c = copy.deepcopy(candidates)
        bad_c["candidates"][0]["enclosing_member"] = "N.Other.ctor()"
        cf(_raises(fd.ANALYSIS_SCOPE, fd.check_baseline_authority, bad_c, base),
           "fixture: baseline-authority mismatch -> ANALYSIS_SCOPE")

        # malformed facts -> BASELINE_ANALYSIS (the runner exits 4)
        junk_root = _mk_root(work)
        try:
            fd.run_core(core_dir, runner_path, py, runner_sha, junk_root, b"{ not json",
                        params(junk_root), fd.BASELINE_ANALYSIS)
            cf(False, "fixture: malformed facts -> BASELINE_ANALYSIS")
        except fd.DeltaError as exc:
            cf(exc.category == fd.BASELINE_ANALYSIS, "fixture: malformed facts -> BASELINE")

        # runner mutation -> TOOLCHAIN_BINDING (LA1), checked before launch (do this LAST)
        with open(runner_path, "ab") as fh:
            fh.write(b"# tamper\n")
        try:
            fd.run_core(core_dir, runner_path, py, runner_sha, base_root,
                        json.dumps(base_facts).encode(), params(base_root), fd.BASELINE_ANALYSIS)
            cf(False, "fixture: runner mutation -> TOOLCHAIN_BINDING")
        except fd.DeltaError as exc:
            cf(exc.category == fd.TOOLCHAIN_BINDING, "fixture: runner mutation -> TOOLCHAIN")

    return checks, fails


def _elig_k(fid: str, ordinal: int, handler: str = "OnA", event: str = "_a.PropertyChanged",
            dc: str = "OWN001") -> dict:
    """A fix-eligible record sharing the SAME bridge key K but a distinct finding_id (via a
    distinct occurrence_ordinal) — the identical-K duplicate the bridge must count."""
    e = _elig(fid, event, handler, dc=dc, source="_a")
    e["record"]["occurrence_ordinal"] = ordinal
    return e


def _amendment_regressions() -> tuple[int, list[str]]:
    """R1 (runtime selection), R3 (image bridge), R4 (core.json bytes), R5 (publish cleanup),
    R2 (toolchain / isolation mutation) — all offline (no dotnet)."""
    checks = 0
    fails: list[str] = []

    def cf(cond: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(label)

    NC = "Microsoft.NETCore.App"

    # --- R1: version parsing + runtime selection --------------------------------
    cf(fd._parse_version("8.0.28") == (8, 0, 28), "R1: parse stable version")
    cf(fd._parse_version("8.0.0-rc.1") is None, "R1: prerelease -> None")
    cf(fd._parse_version("8.0") is None, "R1: two-component -> None")
    sel, _d = fd._select_runtime(f"{NC} 8.0.28 [/p]\nMicrosoft.AspNetCore.App 8.0.28 [/q]\n",
                                 NC, "8.0.0")
    cf(sel == "8.0.28", "R1: 8.0.0 requested, only 8.0.28 -> selects 8.0.28")
    sel2, _ = fd._select_runtime(f"{NC} 8.0.5 [/a]\n{NC} 8.0.28 [/b]\n{NC} 8.0.11 [/c]\n",
                                 NC, "8.0.0")
    cf(sel2 == "8.0.28", "R1: multiple patches -> highest")
    cf(_raises(fd.TOOLCHAIN_BINDING, fd._select_runtime, f"{NC} 8.0.5 [/a]\n", NC, "8.0.10"),
       "R1: lower-than-minimum -> refuse")
    cf(_raises(fd.TOOLCHAIN_BINDING, fd._select_runtime, f"{NC} 8.1.0 [/a]\n", NC, "8.0.0"),
       "R1: different minor -> refuse")
    cf(_raises(fd.TOOLCHAIN_BINDING, fd._select_runtime, f"{NC} 8.0.0-preview.1 [/a]\n",
               NC, "8.0.0"), "R1: prerelease-only -> refuse")
    cf(_raises(fd.TOOLCHAIN_BINDING, fd._select_runtime, "", NC, "8.0.0"),
       "R1: none installed -> refuse")

    # --- R3: image-level bridge for both images / both actions ------------------
    obs_a, obs_b = _obs("_a.PropertyChanged", "OnA"), _obs("_b.PropertyChanged", "OnB")
    ea = _elig(_FIDA, "_a.PropertyChanged", "OnA", source="_a")
    eb = _elig(_FIDB, "_b.PropertyChanged", "OnB", source="_b")
    cf(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
               {"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
               _image([], [], [eb]), _image([obs_b], [], [eb])),
       "R3: manual candidate with no baseline core -> ANALYSIS_IDENTITY")
    cf(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
               {"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
               _image([obs_b], [], [eb]), _image([], [], [eb])),
       "R3: manual candidate with no postimage core -> ANALYSIS_IDENTITY")
    cf(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
               {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
               _image([obs_a], [], [ea, eb]), _image([obs_a], [], [ea, eb])),
       "R3: extra eligible fact without core -> ANALYSIS_IDENTITY")
    cf(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
               {"convert_acquire_ids": [_FIDA], "manual_review_ids": []},
               _image([obs_a, obs_a], [], [ea]), _image([], [], [])),
       "R3: surplus core observation -> ANALYSIS_IDENTITY")
    # identical-K duplicate, same action -> valid (cardinality 2 == 2)
    d1, d2 = _elig_k(_FIDA, 0), _elig_k(_FIDC, 1)
    res_dup = fd.classify_delta({"convert_acquire_ids": [_FIDA, _FIDC], "manual_review_ids": []},
                                _image([obs_a, obs_a], [], [d1, d2]), _image([], [], []))
    cf(len(res_dup["delta"]["removed_all_own001"]) == 2, "R3: identical-action duplicate group ok")
    # identical-K mixed action -> ANALYSIS_IDENTITY
    cf(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
               {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDC]},
               _image([obs_a, obs_a], [], [d1, d2]), _image([obs_a], [], [d1])),
       "R3: mixed-action collision under one K -> ANALYSIS_IDENTITY")

    # --- R4: closed core.json byte protocol -------------------------------------
    core_obj = {"version": 1, "operation": "verify-subscription-core-observations",
                "all_own001": [obs_a], "own050": [], "fix_eligible_subscriptions": [ea]}
    good = fd.canonical_evidence(core_obj)
    cf(fd._load_core(good, fd.BASELINE_ANALYSIS)["all_own001"] == [obs_a], "R4: canonical loads")
    cf(_raises(fd.BASELINE_ANALYSIS, fd._load_core, good[:-1], fd.BASELINE_ANALYSIS),
       "R4: missing trailing newline -> refuse")
    cf(_raises(fd.BASELINE_ANALYSIS, fd._load_core,
               json.dumps(core_obj, indent=2).encode() + b"\n", fd.BASELINE_ANALYSIS),
       "R4: non-canonical bytes -> refuse")
    cf(_raises(fd.BASELINE_ANALYSIS, fd._load_core,
               fd.canonical_evidence({**core_obj, "extra": 1}), fd.BASELINE_ANALYSIS),
       "R4: unknown key -> refuse")
    cf(_raises(fd.BASELINE_ANALYSIS, fd._load_core,
               fd.canonical_evidence({**core_obj, "all_own001": [{**obs_a, "advisory": "no"}]}),
               fd.BASELINE_ANALYSIS), "R4: non-bool advisory not coerced -> refuse")
    bad_rec = _record(_FIDA)
    bad_rec["occurrence_ordinal"] = "x"
    cf(_raises(fd.BASELINE_ANALYSIS, fd._load_core,
               fd.canonical_evidence({**core_obj, "fix_eligible_subscriptions":
                                      [{**ea, "record": bad_rec}]}), fd.BASELINE_ANALYSIS),
       "R4: wrong-typed record field -> refuse")

    # --- R5: publication cleanup failure -> PUBLICATION -------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root, pub = os.path.join(tmp, "root"), os.path.join(tmp, "pub")
        os.makedirs(root)
        os.makedirs(pub)
        out = os.path.join(pub, "ev")
        orig_rename, orig_rmtree = fd.os.rename, fd.shutil.rmtree

        def _boom(*_a, **_k):
            raise OSError("boom")

        try:
            fd.os.rename = _boom      # force a pre-succeeded failure
            fd.shutil.rmtree = _boom  # force the cleanup itself to fail
            cf(_raises(fd.PUBLICATION, fd._publish_delta, out, root, b'{}\n'),
               "R5: cleanup failure -> PUBLICATION")
        finally:
            fd.os.rename, fd.shutil.rmtree = orig_rename, orig_rmtree
        cf(not os.path.exists(out), "R5: no OUTPUT_DIR after a failed publish")

    # --- R2: toolchain + isolation mutation regressions -------------------------
    with tempfile.TemporaryDirectory() as work:
        _core_dir, _rp, _rs, core_fp = fd.materialize_core(work)
        pkg = os.path.join(work, "core", "ownlang")
        before = fd._manifest_sha(pkg, fd._walk_pkg(pkg), fd.TOOLCHAIN_BINDING)
        cf(before == core_fp["ownlang_manifest_sha256"], "R2: ownlang manifest reproducible")
        with open(os.path.join(pkg, "ownir.py"), "ab") as fh:
            fh.write(b"\n# mutate\n")
        after = fd._manifest_sha(pkg, fd._walk_pkg(pkg), fd.TOOLCHAIN_BINDING)
        cf(after != core_fp["ownlang_manifest_sha256"], "R2: ownlang mutation detected")

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "w")
        os.makedirs(work)
        rd = os.path.join(tmp, "refs")
        os.makedirs(rd)
        with open(os.path.join(rd, "A.dll"), "wb") as fh:
            fh.write(b"A0")
        slots, evid = fd.snapshot_reference_closure(work, [rd])
        dll = os.path.join(slots[0], "A.dll")
        with open(dll, "ab") as fh:
            fh.write(b"tamper")
        rehash = fd._sha_bytes(fd._snapshot(dll, fd.TOOLCHAIN_BINDING, "slot"))
        cf(rehash != evid[0]["sha256"], "R2: reference-slot mutation detected")

    with tempfile.TemporaryDirectory() as tmp:
        rel = "Own/Sample.cs"
        p = os.path.join(tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(p))
        with open(p, "wb") as fh:
            fh.write(b"class A {}\n")
        os.makedirs(os.path.join(tmp, ".git"))
        with open(os.path.join(tmp, ".git", "index"), "wb") as fh:
            fh.write(b"idx-v1")
        snap = fd._isolation_snapshot(tmp, rel)
        fd._isolation_verify(snap, tmp, rel)  # unchanged: must not raise
        with open(p, "ab") as fh:
            fh.write(b"// touched\n")
        cf(_raises(fd.ISOLATION, fd._isolation_verify, snap, tmp, rel),
           "R2: target-file mutation -> ISOLATION")
        with open(p, "wb") as fh:
            fh.write(b"class A {}\n")  # restore target
        with open(os.path.join(tmp, ".git", "index"), "wb") as fh:
            fh.write(b"idx-v2")
        cf(_raises(fd.ISOLATION, fd._isolation_verify, snap, tmp, rel),
           "R2: .git/index mutation -> ISOLATION")

    return checks, fails


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

    obs_a = _obs("_a.PropertyChanged", "OnA")
    obs_b = _obs("_b.PropertyChanged", "OnB")
    elig_a = _elig(_FIDA, "_a.PropertyChanged", "OnA", source="_a")
    elig_b = _elig(_FIDB, "_b.PropertyChanged", "OnB", source="_b")

    # --- mixed case: convert A gone, manual B preserved -----------------------
    base = _image([obs_a, obs_b], [], [elig_a, elig_b])
    post = _image([obs_b], [], [elig_b])
    res = fd.classify_delta({"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
                            base, post)
    check(res["delta"]["removed_subscription_own001_ids"] == [_FIDA],
          "mixed: removed == convert")
    check(res["delta"]["preserved_subscription_own001_ids"] == [_FIDB],
          "mixed: preserved == manual")
    check(res["delta"]["removed_all_own001"] == [obs_a], "mixed: removed core == R_C")
    check(res["delta"]["new_all_own001"] == [], "mixed: no new core")
    check(res["semantic_idempotence"]["pass"] is True, "mixed: idempotence passes")
    check(res["baseline"]["subscription_own001_ids"] == sorted([_FIDA, _FIDB]),
          "mixed: baseline sub ids")

    # --- all-convert: C non-empty, M empty, both leaks removed ----------------
    base_ac = _image([obs_a], [], [elig_a])
    post_ac = _image([], [], [])
    res_ac = fd.classify_delta({"convert_acquire_ids": [_FIDA], "manual_review_ids": []},
                               base_ac, post_ac)
    check(res_ac["delta"]["removed_all_own001"] == [obs_a], "all-convert: removed core == R_C")

    # --- manual-only: C empty, nothing removed --------------------------------
    res_mo = fd.classify_delta({"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
                               _image([obs_b], [], [elig_b]), _image([obs_b], [], [elig_b]))
    check(res_mo["delta"]["removed_all_own001"] == [], "manual-only: nothing removed")

    # --- converted still present -> DELTA_MISMATCH -----------------------------
    check(_raises(fd.DELTA_MISMATCH, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
                  base, _image([obs_a, obs_b], [], [elig_a, elig_b])),
          "converted-still-present -> DELTA_MISMATCH")

    # --- new subscription leak -> NEW_OWN001 -----------------------------------
    obs_c = _obs("_c.PropertyChanged", "OnC")
    elig_c = _elig(_FIDC, "_c.PropertyChanged", "OnC", source="_c")
    check(_raises(fd.NEW_OWN001, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
                  base, _image([obs_b, obs_c], [], [elig_b, elig_c])),
          "new subscription leak -> NEW_OWN001")

    # --- new non-subscription (flow-local) OWN001 -> NEW_OWN001 ----------------
    flow = _obs("local", "using", kind="flow-local")
    check(_raises(fd.NEW_OWN001, fd.classify_delta,
                  {"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
                  _image([obs_b], [], [elig_b]), _image([obs_b, flow], [], [elig_b])),
          "new flow-local OWN001 -> NEW_OWN001")

    # --- out-of-scope leak vanished -> DELTA_MISMATCH --------------------------
    check(_raises(fd.DELTA_MISMATCH, fd.classify_delta,
                  {"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
                  _image([obs_b, flow], [], [elig_b]), _image([obs_b], [], [elig_b])),
          "out-of-scope leak vanished -> DELTA_MISMATCH")

    # --- new OWN050 -> NEW_OWN050 ---------------------------------------------
    check(_raises(fd.NEW_OWN050, fd.classify_delta,
                  {"convert_acquire_ids": [], "manual_review_ids": [_FIDB]},
                  _image([obs_b], [], [elig_b]), _image([obs_b], [_own050()], [elig_b])),
          "new OWN050 -> NEW_OWN050")

    # --- bridge: accepted id with no baseline subscription -> ANALYSIS_IDENTITY -
    check(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
                  _image([obs_a, obs_b], [], [elig_b]), _image([obs_b], [], [elig_b])),
          "unbridged accepted id -> ANALYSIS_IDENTITY")

    # --- bridge: mixed-action under one indistinguishable key -> ANALYSIS_IDENTITY
    ea = _elig(_FIDA, "_a.PropertyChanged", "OnA", source="_a")
    eb = _elig(_FIDB, "_a.PropertyChanged", "OnA", source="_a")  # same bridge key as A
    check(_raises(fd.ANALYSIS_IDENTITY, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDB]},
                  _image([obs_a, _obs("_a.PropertyChanged", "OnA")], [], [ea, eb]),
                  _image([obs_a], [], [ea])),
          "mixed-action shared bridge key -> ANALYSIS_IDENTITY")

    # --- duplicate / non-disjoint expected -> DELTA_MISMATCH -------------------
    check(_raises(fd.DELTA_MISMATCH, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA, _FIDA], "manual_review_ids": []}, base, post),
          "duplicate expected id -> DELTA_MISMATCH")
    check(_raises(fd.DELTA_MISMATCH, fd.classify_delta,
                  {"convert_acquire_ids": [_FIDA], "manual_review_ids": [_FIDA]}, base, post),
          "non-disjoint expected -> DELTA_MISMATCH")

    # --- closed core.json schema ----------------------------------------------
    good_core = {"version": 1, "operation": "verify-subscription-core-observations",
                 "all_own001": [obs_a], "own050": [], "fix_eligible_subscriptions": [elig_a]}
    parsed = fd._parse_core(good_core, fd.BASELINE_ANALYSIS)
    check(parsed["all_own001"] == [obs_a], "core.json parses the good shape")
    check(_raises(fd.BASELINE_ANALYSIS, fd._parse_core,
                  {**good_core, "extra": 1}, fd.BASELINE_ANALYSIS), "core.json extra key -> refuse")
    bad_obs = {**obs_a}
    del bad_obs["advisory"]
    check(_raises(fd.BASELINE_ANALYSIS, fd._parse_core,
                  {**good_core, "all_own001": [bad_obs]}, fd.BASELINE_ANALYSIS),
          "core.json missing advisory -> refuse")
    check(_raises(fd.BASELINE_ANALYSIS, fd._parse_core,
                  {**good_core, "all_own001": [{**obs_a, "advisory": "no"}]},
                  fd.BASELINE_ANALYSIS), "core.json non-bool advisory -> refuse")
    check(_raises(fd.BASELINE_ANALYSIS, fd._parse_core,
                  {**good_core, "all_own001": [{**obs_a, "file": "/abs/x.cs"}]},
                  fd.BASELINE_ANALYSIS), "core.json absolute file -> refuse")

    # --- canonical bytes: sorted keys + trailing newline ----------------------
    ev = fd.canonical_evidence({"b": 1, "a": 2})
    check(ev == b'{"a":2,"b":1}\n', "canonical bytes: sorted keys + trailing newline")

    # --- atomic publication (LA3) ---------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "root")
        pub = os.path.join(tmp, "pub")
        os.makedirs(root)
        os.makedirs(pub)
        out = os.path.join(pub, "evidence")
        fd._publish_delta(out, root, b'{"ok":true}\n')
        names = sorted(os.listdir(out))
        check(names == ["delta-result.json"], "publish leaves only delta-result.json")
        with open(os.path.join(out, "delta-result.json"), "rb") as fh:
            check(fh.read() == b'{"ok":true}\n', "published bytes are exact")
        leftover = [n for n in os.listdir(pub) if n.startswith(".owen-gate-")]
        check(leftover == [], "publish leaves no claimed workdir")
        # a pre-existing OUTPUT_DIR -> PUBLICATION, and still no workdir residue
        check(_raises(fd.PUBLICATION, fd._publish_delta, out, root, b'{}\n'),
              "existing out -> PUBLICATION")
        check([n for n in os.listdir(pub) if n.startswith(".owen-gate-")] == [],
              "failed publish leaves no workdir")
        # OUTPUT_DIR resolving inside the source root -> PUBLICATION
        inside = os.path.join(root, "evidence")
        check(_raises(fd.PUBLICATION, fd._publish_delta, inside, root, b'{}\n'),
              "out inside root -> PUBLICATION")

    # --- slice 2: authority OWN001-only guard + exact Step 9 gate binding ------
    import copy
    fid1 = "OWN001:sha256:" + "1" * 64
    fid2 = "OWN050:sha256:" + "2" * 64  # a valid finding_id label; diagnostic_code is what matters
    cands = _bcands([_bcand(fid1, 40),
                     _bcand(fid2, 80, contract="name_only", actions=["manual_review"])])
    plan = _bplan(cands, ["convert_acquire", "manual_review"])
    auth, _p, _c = fd.load_authority(json.dumps(plan).encode(), json.dumps(cands).encode())
    check(auth.applied == [fid1] and auth.manual == [fid2], "authority: OWN001 candidates load")

    cands014 = _bcands([_bcand(fid1, 40, dc="OWN014", contract="name_only",
                               actions=["manual_review"])])
    plan014 = _bplan(cands014, ["manual_review"])
    check(_raises(fd.ANALYSIS_SCOPE, fd.load_authority,
                  json.dumps(plan014).encode(), json.dumps(cands014).encode()),
          "OWN014 candidate -> ANALYSIS_SCOPE")

    mani, patch = b"manifest-bytes", b"patch-bytes"
    plan_bytes = json.dumps(plan).encode()
    pre_sha, post_sha = _sha(_PRE), _sha(_POST)
    gate_bytes = _build_evidence(auth, _REL, plan_bytes, mani, patch, pre_sha, post_sha, "pass")

    def bg(gb: bytes):
        return fd.bind_gate(gb, auth, plan_bytes, mani, patch, pre_sha, post_sha)

    check(bg(gate_bytes) == fd._sha_bytes(gate_bytes), "gate: frozen evidence binds")

    # manual-only: the three git gates are not_applicable, C empty
    cands_m = _bcands([_bcand(fid2, 80, contract="name_only", actions=["manual_review"])])
    plan_m = _bplan(cands_m, ["manual_review"])
    auth_m, _, _ = fd.load_authority(json.dumps(plan_m).encode(), json.dumps(cands_m).encode())
    plan_m_bytes = json.dumps(plan_m).encode()
    gate_m = _build_evidence(auth_m, _REL, plan_m_bytes, mani, patch, pre_sha, post_sha,
                             "not_applicable")
    check(bool(fd.bind_gate(gate_m, auth_m, plan_m_bytes, mani, patch, pre_sha, post_sha)),
          "gate: manual-only not_applicable binds")

    good = json.loads(gate_bytes)

    def _canon(obj) -> bytes:
        return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8") + b"\n")

    def tam(mut) -> bytes:
        g = copy.deepcopy(good)
        mut(g)
        return _canon(g)

    check(_raises(fd.GATE_BINDING, bg,
                  tam(lambda g: g["gates"].__setitem__("bundle_layout", "fail"))),
          "gate: fail status -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg, tam(lambda g: g.__setitem__("surprise", 1))),
          "gate: unknown top-level key -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg, tam(lambda g: g["gates"].pop("git_apply"))),
          "gate: missing gate -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg,
                  tam(lambda g: g["target_api"].__setitem__("subscribe", "X.Y"))),
          "gate: wrong target -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg,
                  tam(lambda g: g["gates"].__setitem__("bundle_layout", "not_applicable"))),
          "gate: not_applicable on a non-git gate -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg,
                  tam(lambda g: g["gates"].__setitem__("git_apply", "not_applicable"))),
          "gate: split git-gate statuses -> GATE_BINDING")
    check(_raises(fd.GATE_BINDING, bg, json.dumps(good, indent=2).encode("utf-8") + b"\n"),
          "gate: non-canonical bytes -> GATE_BINDING")

    # --- slice 6: reference-closure snapshot + evidence assembly + bundle layout
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "w")
        os.makedirs(work)
        r0, r1 = os.path.join(tmp, "r0"), os.path.join(tmp, "r1")
        os.makedirs(os.path.join(r0, "sub"))
        os.makedirs(r1)
        for p, data in ((os.path.join(r0, "B.dll"), b"B0"),
                        (os.path.join(r0, "sub", "A.dll"), b"A0"),
                        (os.path.join(r0, "note.txt"), b"skip"),
                        (os.path.join(r1, "C.dll"), b"C1")):
            with open(p, "wb") as fh:
                fh.write(data)
        slots, ev = fd.snapshot_reference_closure(work, [r0, r1])
        check([e["relative_path"] for e in ev] == ["B.dll", "sub/A.dll", "C.dll"],
              "ref closure: caller-dir then byte-order")
        check([e["source_dir_ordinal"] for e in ev] == [0, 0, 1], "ref closure: dir ordinals")
        check(all(len(os.listdir(s)) == 1 for s in slots), "ref closure: one dll per slot")
        check(os.listdir(slots[1]) == ["A.dll"], "ref closure: original basename preserved")

    classified = {"baseline": {"subscription_own001_ids": [], "all_own001": [], "own050": []},
                  "postimage": {"subscription_own001_ids": [], "all_own001": [], "own050": []},
                  "delta": {"removed_all_own001": []},
                  "semantic_idempotence": {"converted_ids_still_actionable": [], "pass": True}}
    ev = fd.build_evidence("Own/X.cs", "N.X", 2, {"a": 1}, {"b": 2}, {"c": 3}, [], "T",
                           {"convert_acquire_ids": [], "manual_review_ids": []}, classified,
                           set(fd._CHECK_NAMES))
    check(set(ev["checks"]) == set(fd._CHECK_NAMES) and len(fd._CHECK_NAMES) == 17,
          "evidence: exactly seventeen check names")
    # an unexecuted check must NOT be published (R2)
    check(_raises(fd.INFRASTRUCTURE, fd.build_evidence, "Own/X.cs", "N.X", 0, {}, {}, {}, [],
                  "T", {"convert_acquire_ids": [], "manual_review_ids": []}, classified,
                  set(fd._CHECK_NAMES) - {"isolation"}),
          "evidence: unexecuted check -> INFRASTRUCTURE")
    check(all(v == "pass" for v in ev["checks"].values()), "evidence: every check passes")
    check(ev["schema"] == 1 and ev["operation"] == "verify-subscription-analyzer-delta",
          "evidence: schema + operation")
    check(ev["analysis_scope"]["closure_kind"] == "single-file+refdirs",
          "evidence: closure_kind with ref dirs")
    canon = fd.canonical_evidence(ev)
    check(canon.endswith(b"\n") and b'"schema":1' in canon, "evidence: canonical bytes")

    with tempfile.TemporaryDirectory() as tmp:
        b = os.path.join(tmp, "bundle")
        os.makedirs(b)
        with open(os.path.join(b, "change.patch"), "wb") as fh:
            fh.write(b"")
        check(_raises(fd.INPUT_LAYOUT, fd._require_bundle_layout, b),
              "bundle layout incomplete -> INPUT_LAYOUT")

    # --- R1-R5 amendment regressions (offline) --------------------------------
    achecks, afails = _amendment_regressions()
    ok += achecks - len(afails)
    bad += len(afails)
    for f in afails:
        print(f"  FAIL: {f}")

    # --- slices 3-5: the real fresh core subprocess (no dotnet) ---------------
    fchecks, ffails = _fixture_core_fails()
    ok += fchecks - len(ffails)
    bad += len(ffails)
    for f in ffails:
        print(f"  FAIL: {f}")

    total = ok + bad
    print(f"verify-delta (unit + fixture): {ok}/{total} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
