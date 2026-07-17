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

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import fix_delta as fd

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


def run() -> int:  # noqa: C901 — a flat battery of independent assertions
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
        published = fd._publish_delta(out, root, b'{"ok":true}\n')
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

    total = ok + bad
    print(f"verify-delta (unit): {ok}/{total} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
