#!/usr/bin/env python3
"""S0 Part B — the `own-fix subscriptions candidates` collector (SDK-free tests).

Drives `ownlang/fix_candidates.py` + `ownlang/config.py::load_target_subscribe` over
SYNTHETIC fix-candidate facts (no .NET SDK): finding-id line-independence, the
partial/nested/generated and unknown/wrong-class hard rejections, deterministic
ordering, per-file SHA-256, the convert_acquire-only-for-INotifyPropertyChanged
permission, released-is-not-a-leak, and target-API pinning. The end-to-end run over
the real extractor facts lives in the "C# leak extractor" CI job.

Run:  python tests/test_fix_candidates.py
      python tests/run_tests.py     (auto-discovered)
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.config import ConfigError, load_target_subscribe
from ownlang.fix_candidates import CollectError, collect_candidates, finding_id

_EV = "System.ComponentModel.INotifyPropertyChanged.PropertyChanged"


def _fix(**kw: object) -> dict:
    f = {
        "enclosing_member": "N.C.C()",
        "event_identity": _EV,
        "event_contract": "inotify_property_changed",
        "source_identity": "N.C._pub",
        "source_identity_kind": "stable_symbol",
        "handler_identity": "N.C.OnChanged(object, ...)",
        "handler_identity_kind": "stable_symbol",
        "occurrence_ordinal": 0,
        "span": {"start": 100, "length": 30, "start_line": 1,
                 "start_column": 1, "end_line": 1, "end_column": 31},
        "teardown": {"status": "none", "candidates": []},
    }
    f.update(kw)
    return f


def _sub(fix: dict | None, released: bool = False, event: str = "_pub.PropertyChanged",
         handler: str = "OnChanged", resource: str = "subscription") -> dict:
    s = {"event": event, "handler": handler, "line": 1, "released": released,
         "resource": resource, "source": "injected", "lambda": False}
    if fix is not None:
        s["fix"] = fix
    return s


def _facts(subs: list[dict], qn: str = "N.C", file: str = "N/C.cs",
           is_partial: bool = False, is_nested: bool = False, is_generated: bool = False,
           extra: list[dict] | None = None) -> dict:
    comp = {"name": qn.rsplit(".", 1)[-1], "qualified_name": qn, "is_partial": is_partial,
            "is_nested": is_nested, "declaration_count": 1, "is_generated": is_generated,
            "file": file, "subscriptions": subs}
    return {"ownir_version": 0, "fix_candidates_version": 1,
            "components": [comp, *(extra or [])]}


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

    def raises(fn: object, *a: object) -> bool:
        try:
            fn(*a)  # type: ignore[operator]
        except CollectError:
            return True
        return False

    # A real source file so the per-file SHA can be computed + verified.
    with tempfile.TemporaryDirectory() as root:
        src_rel = "N/C.cs"
        src_abs = os.path.join(root, src_rel)
        os.makedirs(os.path.dirname(src_abs), exist_ok=True)
        content = b"// pretend source\nclass C {}\n"
        with open(src_abs, "wb") as fh:
            fh.write(content)

        # --- finding_id is line-independent (span/line are not constituents) ---
        env_a = collect_candidates(_facts([_sub(_fix())]),
                                   "WeakEvents.AddPropertyChanged", "N.C", None, root)
        env_b = collect_candidates(_facts([_sub(_fix(span={"start": 999, "length": 30,
                                   "start_line": 42, "start_column": 1,
                                   "end_line": 42, "end_column": 31}))]),
                                   "WeakEvents.AddPropertyChanged", "N.C", None, root)
        check(
            env_a["candidates"][0]["finding_id"] == env_b["candidates"][0]["finding_id"],
            "finding_id is line/span-independent",
        )
        # ... and it IS the versioned SHA over the constituents.
        check(
            env_a["candidates"][0]["finding_id"]
            == finding_id("N.C", "N.C.C()", _EV, "N.C._pub", "N.C.OnChanged(object, ...)", 0),
            "finding_id matches the versioned formula",
        )

        # --- convert_acquire only for a proven INotifyPropertyChanged contract ---
        inpc = collect_candidates(_facts([_sub(_fix())]),
                                  "WeakEvents.AddPropertyChanged", "N.C", None, root)
        check(
            inpc["candidates"][0]["allowed_actions"] == ["convert_acquire", "manual_review"],
            "INPC contract -> convert_acquire + manual_review",
        )
        name_only = collect_candidates(_facts([_sub(_fix(event_contract="name_only"))]),
                                       "WeakEvents.AddPropertyChanged", "N.C", None, root)
        check(
            name_only["candidates"][0]["allowed_actions"] == ["manual_review"],
            "name_only contract -> manual_review only",
        )

        # --- released subscription is not a leak -> not a candidate ---
        rel = collect_candidates(_facts([_sub(_fix(), released=True)]),
                                 "WeakEvents.AddPropertyChanged", "N.C", None, root)
        check(len(rel["candidates"]) == 0, "released subscription is not a candidate")

        # --- per-file SHA-256 recorded + correct ---
        want_sha = "sha256:" + hashlib.sha256(content).hexdigest()
        check(
            inpc["source_files"][0]["path"] == "N/C.cs"
            and inpc["source_files"][0]["sha256"] == want_sha,
            "source file SHA-256 recorded and correct",
        )

        # --- target_api pinned from config (never the first of a list) ---
        check(
            inpc["target_api"] == {"subscribe": "WeakEvents.AddPropertyChanged"},
            "target_api pinned",
        )

        # --- partial / nested / generated -> hard error ---
        check(raises(collect_candidates, _facts([_sub(_fix())], is_partial=True),
                     "W.X", "N.C", None, root), "partial type refused")
        check(raises(collect_candidates, _facts([_sub(_fix())], is_nested=True),
                     "W.X", "N.C", None, root), "nested type refused")
        check(raises(collect_candidates, _facts([_sub(_fix())], is_generated=True),
                     "W.X", "N.C", None, root), "generated type refused")
        # two declarations with the same FQN (partial split) -> ambiguous
        dup = _facts([_sub(_fix())])
        dup["components"].append(dict(dup["components"][0]))
        check(raises(collect_candidates, dup, "W.X", "N.C", None, root),
              "duplicate FQN declarations refused")
        # missing class
        check(raises(collect_candidates, _facts([_sub(_fix())]), "W.X", "N.Missing", None, root),
              "unknown class refused")

        # --- unknown finding-id -> hard error ---
        check(
            raises(collect_candidates, _facts([_sub(_fix())]), "W.X", "N.C",
                   ["OWN001:sha256:deadbeef"], root),
            "unknown finding-id refused",
        )

        # --- deterministic ordering (by file, span.start, id) ---
        two = _facts([
            _sub(_fix(occurrence_ordinal=1,
                      span={"start": 300, "length": 10, "start_line": 3, "start_column": 1,
                            "end_line": 3, "end_column": 11})),
            _sub(_fix(occurrence_ordinal=0,
                      span={"start": 100, "length": 10, "start_line": 1, "start_column": 1,
                            "end_line": 1, "end_column": 11})),
        ])
        e1 = collect_candidates(two, "WeakEvents.AddPropertyChanged", "N.C", None, root)
        starts = [c["acquire_span"]["start"] for c in e1["candidates"]]
        check(starts == sorted(starts) == [100, 300], "candidates ordered by span.start")

    # --- config: target-API pinning rules ---
    def _pin(text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            return load_target_subscribe(path)
        finally:
            os.unlink(path)

    def _pin_raises(text: str) -> bool:
        try:
            _pin(text)
        except ConfigError:
            return True
        return False

    check(
        _pin('[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n')
        == "WeakEvents.AddPropertyChanged",
        "single subscribe entry is the target",
    )
    check(
        _pin('[weak-subscription]\ntarget = "WeakEvents.AddPropertyChanged"\n'
             'subscribe = ["A.B", "C.D"]\n') == "WeakEvents.AddPropertyChanged",
        "explicit target wins over the subscribe list",
    )
    check(
        _pin_raises('[weak-subscription]\nsubscribe = ["A.B", "C.D"]\n'),
        "several subscribe entries with no target -> hard error (no silent first-pick)",
    )
    check(_pin_raises("[other]\nx = 1\n"), "no [weak-subscription] table -> hard error")

    print(f"fix-candidates collector: {ok} ok, {bad} bad")
    return bad


if __name__ == "__main__":
    raise SystemExit(run())
