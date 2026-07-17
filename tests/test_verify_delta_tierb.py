#!/usr/bin/env python3
"""S2 step 10 — Tier B: the REAL Roslyn extractor -> real fresh core subprocess -> delta.

This is the only tier that proves the analyzer-semantic claim with the real extractor. It
runs the checked-in OwnSharp.Extractor over a baseline (two INotifyPropertyChanged `+=`
leaks) and a postimage (one converted to the accepted weak wrapper), then drives the same
snapshotted-ownlang fresh core subprocess Step 10 uses and asserts the OWN001 delta
(converted gone, manual preserved). It needs dotnet; when dotnet is absent (the Tier-A
`tests (pyX)` job) it SKIPS cleanly so the offline suite stays green. CI runs it in the
`wpf-extractor` job.

NOTE: this drives the extractor via `dotnet exec <dll>` / `dotnet run --project` directly,
NOT through fix_delta.run_verify_delta's resolve_runtime — see the PR's limitation note on
the locked DOTNET_ROLL_FORWARD=Disable + exact-version rule (a runtimeconfig pinned at
x.0.0 has no exact installed match when only patch runtimes exist).

Run:  python tests/test_verify_delta_tierb.py
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import fix_delta as fd

_REL = "Own/Samples/TwoOnOneLine.cs"
_FQN = "Own.Samples.TwoOnOneLine"
_TARGET = "WeakEvents.AddPropertyChanged"

_BASE_CS = """using System.ComponentModel;
namespace Own.Samples {
    public class TwoOnOneLine {
        public TwoOnOneLine(INotifyPropertyChanged a, INotifyPropertyChanged b) {
            a.PropertyChanged += OnA; b.PropertyChanged += OnB;
        }
        void OnA(object s, PropertyChangedEventArgs e) {}
        void OnB(object s, PropertyChangedEventArgs e) {}
    }
}
"""

_POST_CS = """using System.ComponentModel;
namespace Own.Samples {
    static class WeakEvents {
        public static void AddPropertyChanged(
            INotifyPropertyChanged s, PropertyChangedEventHandler h) {}
    }
    public class TwoOnOneLine {
        public TwoOnOneLine(INotifyPropertyChanged a, INotifyPropertyChanged b) {
            WeakEvents.AddPropertyChanged(a, OnA); b.PropertyChanged += OnB;
        }
        void OnA(object s, PropertyChangedEventArgs e) {}
        void OnB(object s, PropertyChangedEventArgs e) {}
    }
}
"""


def _find_dotnet() -> str | None:
    host = shutil.which("dotnet")
    if host:
        return host
    default = r"C:\Program Files\dotnet\dotnet.exe"
    return default if os.path.isfile(default) else None


def _find_extractor_dll(repo: str) -> str | None:
    hits = glob.glob(os.path.join(repo, "frontend", "roslyn", "OwnSharp.Extractor",
                                  "bin", "*", "*", "ownsharp-extract.dll"))
    return hits[0] if hits else None


def _extract(dotnet: str, dll: str | None, proj: str, image_dir: str) -> bytes:
    """Run the real extractor over the materialized target file, return facts.json bytes."""
    common = ["extract", _REL, "--out", "facts.json", "--fix-candidates",
              "--weak-subscribe", _TARGET]
    if dll is not None:
        argv = [dotnet, "exec", dll, *common]
    else:
        argv = [dotnet, "run", "--project", proj, "-c", "Release", "--", *common]
    proc = subprocess.run(argv, cwd=image_dir, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"extractor rc={proc.returncode}: {proc.stderr.strip()[:400]}")
    with open(os.path.join(image_dir, "facts.json"), "rb") as fh:
        return fh.read()


def run() -> int:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dotnet = _find_dotnet()
    if dotnet is None:
        print("verify-delta (Tier B): SKIP (no dotnet host)")
        return 0
    dll = _find_extractor_dll(repo)
    proj = os.path.join(repo, "frontend", "roslyn", "OwnSharp.Extractor")

    ok = 0
    bad = 0

    def check(cond: bool, label: str) -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"  FAIL: {label}")

    with tempfile.TemporaryDirectory() as work:
        base_root = os.path.join(work, "base")
        post_root = os.path.join(work, "post")
        for root, src in ((base_root, _BASE_CS), (post_root, _POST_CS)):
            path = os.path.join(root, *_REL.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src)
        try:
            base_facts = _extract(dotnet, dll, proj, base_root)
            post_facts = _extract(dotnet, dll, proj, post_root)
        except (RuntimeError, OSError) as exc:
            print(f"verify-delta (Tier B): SKIP (extractor unavailable: {exc})")
            return 0

        core_dir, runner_path, runner_sha, _fp = fd.materialize_core(work)
        py, _pyfp = fd.resolve_python()

        def analyze(root: str, facts: bytes, cat: str) -> dict:
            img = tempfile.mkdtemp(dir=work)
            params = {"root": root, "target_subscribe": _TARGET, "class_fqn": _FQN}
            return fd.run_core(core_dir, runner_path, py, runner_sha, img, facts, params, cat)

        base = analyze(base_root, base_facts, fd.BASELINE_ANALYSIS)
        post = analyze(post_root, post_facts, fd.POSTIMAGE_ANALYSIS)

        check(sorted(o["handler"] for o in base["all_own001"]) == ["OnA", "OnB"],
              "Tier B: real baseline has OnA + OnB OWN001")
        check([o["handler"] for o in post["all_own001"]] == ["OnB"],
              "Tier B: real postimage has only OnB (OnA converted)")

        recs = {e["record"]["handler"]: e for e in base["fix_eligible_subscriptions"]}
        check(set(recs) == {"OnA", "OnB"}, "Tier B: two real fix-eligible subscriptions")
        fid_a, fid_b = recs["OnA"]["finding_id"], recs["OnB"]["finding_id"]
        candidates = {"version": 1, "operation": "fix-subscriptions",
                      "target_api": {"subscribe": _TARGET},
                      "selection": {"allowed_types": [{"full_name": _FQN, "file": _REL}],
                                    "selected_findings": None,
                                    "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                                    "allow_helper_changes": False,
                                                    "allow_config_changes": False,
                                                    "allow_suppressions": False}},
                      "source_files": [{"path": _REL, "sha256": "sha256:" + "0" * 64}],
                      "candidates": [recs["OnA"]["record"], recs["OnB"]["record"]]}
        fd.check_baseline_authority(candidates, base)
        fd.check_target_identity(base, _REL, fd.BASELINE_ANALYSIS)
        fd.check_target_identity(post, _REL, fd.POSTIMAGE_ANALYSIS)
        res = fd.classify_delta({"convert_acquire_ids": [fid_a], "manual_review_ids": [fid_b]},
                                base, post)
        check(res["delta"]["removed_subscription_own001_ids"] == [fid_a],
              "Tier B: real converted OnA removed")
        check(res["delta"]["preserved_subscription_own001_ids"] == [fid_b],
              "Tier B: real manual OnB preserved")

    total = ok + bad
    print(f"verify-delta (Tier B, real extractor+core): {ok}/{total} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
