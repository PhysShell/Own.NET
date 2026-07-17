#!/usr/bin/env python3
"""S2 step 10 — Tier B: the FULL public CLI acceptance (R7).

This exercises the real pipeline end to end through the PUBLIC command line only —
never classify_delta / run_core / a private helper as its proof:

    real extractor -> candidates -> validate-plan -> apply (Owen rewriter) -> gate
    -> `own-fix subscriptions verify-delta` (copied extractor deployment, amended runtime
       resolver, real Roslyn extraction, real fresh snapshotted Python core)
    -> published delta-result.json

Cases: all-convert, manual-only, mixed; deterministic byte-identical evidence across two
independent invocations; a NEW_OWN001 refusal (a forged postimage that introduces a leak);
an OWN014 refusal (ANALYSIS_SCOPE); and full published-schema validation.

Gating: this is REQUIRED (a missing dotnet / extractor / execution failure is a FAILURE,
not a skip) exactly when OWN_TIERB_REQUIRED=1 — which the wpf-extractor CI job sets. In any
other context (the Tier-A `tests (pyX)` job, the pack job, a local no-dotnet run) it is the
explicit non-required mode and skips cleanly, so the offline suite stays green.

Run:  OWN_TIERB_REQUIRED=1 python tests/test_verify_delta_tierb.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.fix_delta import _CHECK_NAMES

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_RW = os.path.join(_REPO, "frontend", "roslyn", "Owen.CSharp.Rewriter")
_REL = "Own/Samples/S.cs"
_FQN = "Own.Samples.S"

_TWO_LEAKS = """using System.ComponentModel;
namespace Own.Samples {
    static class WeakEvents {
        public static void AddPropertyChanged(
            INotifyPropertyChanged s, PropertyChangedEventHandler h) {}
    }
    public class S {
        public S(INotifyPropertyChanged a, INotifyPropertyChanged b) {
            a.PropertyChanged += OnA; b.PropertyChanged += OnB;
        }
        void OnA(object s, PropertyChangedEventArgs e) {}
        void OnB(object s, PropertyChangedEventArgs e) {}
    }
}
"""


class Fail(Exception):
    pass


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _run(argv: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


def _py(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "ownlang", *args], cwd=cwd or _REPO)


def _find_dotnet() -> str | None:
    return shutil.which("dotnet") or (r"C:\Program Files\dotnet\dotnet.exe"
                                      if os.path.isfile(r"C:\Program Files\dotnet\dotnet.exe")
                                      else None)


def _build(dotnet: str) -> str:
    for proj in (_EXT, _RW):
        p = _run([dotnet, "build", proj, "-c", "Release", "-v", "q", "--nologo"])
        if p.returncode != 0:
            raise Fail(f"build {proj}: {p.stdout[-400:]}{p.stderr[-400:]}")
    dlls = glob.glob(os.path.join(_EXT, "bin", "*", "*", "ownsharp-extract.dll"))
    if not dlls:
        raise Fail("extractor DLL not found after build")
    return dlls[0]


def _mkroot(cs: str) -> str:
    root = tempfile.mkdtemp()
    p = os.path.join(root, *_REL.split("/"))
    os.makedirs(os.path.dirname(p))
    with open(p, "wb") as fh:  # binary LF: no newline translation, so the forge stays clean
        fh.write(cs.replace("\r\n", "\n").encode("utf-8"))
    return root


_ONE_LEAK = """using System.ComponentModel;
namespace Own.Samples {
    static class WeakEvents {
        public static void AddPropertyChanged(
            INotifyPropertyChanged s, PropertyChangedEventHandler h) {}
    }
    public class S {
        public S(INotifyPropertyChanged a, INotifyPropertyChanged c) {
            a.PropertyChanged += OnA;
        }
        void OnA(object s, PropertyChangedEventArgs e) {}
    }
}
"""


def _step8_patch(pre_bytes: bytes, post_bytes: bytes) -> bytes:
    """A minimal, grammar-valid step-8 patch (preimage -> postimage): our own header lines
    plus git's hunk body with any function-context heading stripped from the @@ headers."""
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "a"), os.path.join(d, "b")
        with open(a, "wb") as fh:
            fh.write(pre_bytes)
        with open(b, "wb") as fh:
            fh.write(post_bytes)
        diff = _run(["git", "-c", "core.autocrlf=false", "diff", "--no-index", "--no-color", a, b])
    lines = diff.stdout.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith("@@")), None)
    if start is None:
        raise Fail("git diff produced no hunk")
    body = []
    for ln in lines[start:]:
        if ln.startswith("@@"):
            ln = re.sub(r"^(@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@).*\n?$", r"\1\n", ln)
        body.append(ln)
    header = f"diff --git a/{_REL} b/{_REL}\n--- a/{_REL}\n+++ b/{_REL}\n"
    return header.encode() + "".join(body).encode()


def _candidates(dotnet: str, dll: str, root: str, work: str) -> str:
    facts = os.path.join(work, "fc.json")
    p = _run([dotnet, "exec", dll, "extract", _REL, "--out", facts, "--fix-candidates",
              "--weak-subscribe", "WeakEvents.AddPropertyChanged"], cwd=root)
    if p.returncode != 0:
        raise Fail(f"extract: {p.stderr[-400:]}")
    own = os.path.join(work, "own.toml")
    with open(own, "w", encoding="utf-8") as fh:
        fh.write('[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n')
    cands = os.path.join(work, "candidates.json")
    p = _py(["own-fix", "subscriptions", "candidates", facts, "--config", own,
             "--class", _FQN, "--output", cands, "--root", root])
    if p.returncode != 0:
        raise Fail(f"candidates: {p.stderr[-400:]}")
    return cands


def _plan(cands: str, work: str, convert: set[str]) -> str:
    from ownlang.fix_plan import validate_plan
    with open(cands, encoding="utf-8") as fh:
        c = json.load(fh)
    decisions = [{"finding_id": x["finding_id"],
                  "action": "convert_acquire" if x["handler"] in convert else "manual_review"}
                 for x in c["candidates"]]
    plan = os.path.join(work, "plan.json")
    with open(plan, "w", encoding="utf-8") as fh:
        json.dump(validate_plan(c, {"version": 1, "decisions": decisions}), fh)
    return plan


def _apply_and_gate(dotnet: str, cands: str, plan: str, root: str, work: str,
                    tag: str) -> tuple[str, str]:
    bundle = os.path.join(work, f"bundle-{tag}")
    # the rewriter command is split with POSIX shell rules, so quote the (possibly-spaced)
    # project path and use forward slashes; `dotnet` resolves from PATH (as in CI).
    rewriter = f'dotnet run --project "{_RW.replace(os.sep, "/")}" -c Release --no-build --'
    p = _py(["own-fix", "subscriptions", "apply", "--plan", plan, "--candidates", cands,
             "--root", root, "--out", bundle, "--rewriter", rewriter])
    if p.returncode != 0:
        raise Fail(f"apply: {p.stderr[-400:]}")
    gate_out = os.path.join(work, f"gate-{tag}")
    p = _py(["own-fix", "subscriptions", "gate", "--bundle", bundle, "--plan", plan,
             "--candidates", cands, "--root", root, "--out", gate_out])
    if p.returncode != 0:
        raise Fail(f"gate: {p.stderr[-400:]}")
    return bundle, os.path.join(gate_out, "gate-result.json")


def _verify(dotnet: str, dll: str, bundle: str, plan: str, cands: str, root: str,
            gate: str, out: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(dotnet) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-delta",
         "--bundle", bundle, "--plan", plan, "--candidates", cands, "--root", root,
         "--gate", gate, "--extractor-dll", dll, "--out", out],
        cwd=_REPO, capture_output=True, text=True, check=False, env=env)


def _schema_ok(path: str) -> None:
    with open(path, "rb") as fh:
        raw = fh.read()
    obj = json.loads(raw)
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if raw != canon.encode() + b"\n":
        raise Fail("delta-result.json is not canonical bytes + trailing newline")
    if obj["schema"] != 1 or obj["operation"] != "verify-subscription-analyzer-delta":
        raise Fail("delta-result.json schema/operation wrong")
    if set(obj["checks"]) != set(_CHECK_NAMES) or set(obj["checks"].values()) != {"pass"}:
        raise Fail("delta-result.json checks are not the exact 17-name all-pass set")
    rid = obj["toolchain_fingerprint"]["resolved_runtime_identity"]
    if "requested_framework_version" not in rid or "selected_framework_version" not in rid:
        raise Fail("resolved_runtime_identity missing requested/selected versions")


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    if not required:
        print("verify-delta (Tier B): SKIP (non-required mode; set OWN_TIERB_REQUIRED=1)")
        return 0
    dotnet = _find_dotnet()
    if dotnet is None:
        print("verify-delta (Tier B): FAIL — required but no dotnet host")
        return 1

    ok = 0
    fails: list[str] = []

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        if cond:
            ok += 1
        else:
            fails.append(label)

    try:
        dll = _build(dotnet)
        # convert one candidate to obtain a NON-empty selected runtime (--fx-version) and a
        # real patch, and materialize the chain once per case.
        with tempfile.TemporaryDirectory() as work:
            root = _mkroot(_TWO_LEAKS)
            cands = _candidates(dotnet, dll, root, work)

            for tag, convert in (("mixed", {"OnA"}), ("allconv", {"OnA", "OnB"}),
                                 ("manual", set())):
                plan = _plan(cands, work, convert)
                bundle, gate = _apply_and_gate(dotnet, cands, plan, root, work, tag)
                out = os.path.join(work, f"delta-{tag}")
                p = _verify(dotnet, dll, bundle, plan, cands, root, gate, out)
                check(p.returncode == 0, f"Tier B: {tag} verify-delta exits 0 ({p.stderr[-200:]})")
                if p.returncode == 0:
                    _schema_ok(os.path.join(out, "delta-result.json"))
                    check(True, f"Tier B: {tag} published schema valid")

            # determinism: two independent invocations of the mixed case -> identical bytes
            plan = _plan(cands, work, {"OnA"})
            bundle, gate = _apply_and_gate(dotnet, cands, plan, root, work, "det")
            b1, b2 = os.path.join(work, "d1"), os.path.join(work, "d2")
            _verify(dotnet, dll, bundle, plan, cands, root, gate, b1)
            _verify(dotnet, dll, bundle, plan, cands, root, gate, b2)
            with open(os.path.join(b1, "delta-result.json"), "rb") as fh:
                r1 = fh.read()
            with open(os.path.join(b2, "delta-result.json"), "rb") as fh:
                r2 = fh.read()
            check(r1 == r2, "Tier B: two invocations produce byte-identical evidence")

            # OWN014 refusal: forge a candidate's diagnostic_code -> ANALYSIS_SCOPE
            _own014_case(dotnet, dll, root, work, check)
            # NEW_OWN001 / NEW_OWN050 refusals: forge a postimage that introduces the anomaly
            _forged_refusal(dotnet, dll, work, _POST_NEW_OWN001, "NEW_OWN001", "n1", check)
            _forged_refusal(dotnet, dll, work, _POST_NEW_OWN050, "NEW_OWN050", "n5", check)

            shutil.rmtree(root, ignore_errors=True)
    except Fail as exc:
        fails.append(f"Tier B setup: {exc}")

    for f in fails:
        print(f"  FAIL: {f}")
    total = ok + len(fails)
    print(f"verify-delta (Tier B, full CLI): {ok}/{total} checks pass")
    return 1 if fails else 0


def _own014_case(dotnet: str, dll: str, root: str, work: str, check) -> None:
    """A legal-but-out-of-scope OWN014 candidate must be refused ANALYSIS_SCOPE by the CLI."""
    from ownlang.fix_plan import validate_plan
    cands = _candidates(dotnet, dll, root, work)
    with open(cands, encoding="utf-8") as fh:
        c = json.load(fh)
    c["candidates"] = [c["candidates"][0]]
    c["candidates"][0]["diagnostic_code"] = "OWN014"
    c["candidates"][0]["event_contract"] = "name_only"
    c["candidates"][0]["allowed_actions"] = ["manual_review"]
    c["selection"]["selected_findings"] = None
    cpath = os.path.join(work, "cand014.json")
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(c, fh)
    decisions = [{"finding_id": c["candidates"][0]["finding_id"], "action": "manual_review"}]
    plan = os.path.join(work, "plan014.json")
    with open(plan, "w", encoding="utf-8") as fh:
        json.dump(validate_plan(c, {"version": 1, "decisions": decisions}), fh)
    bundle, gate = _apply_and_gate(dotnet, cpath, plan, root, work, "014")
    out = os.path.join(work, "delta014")
    p = _verify(dotnet, dll, bundle, plan, cpath, root, gate, out)
    check(p.returncode == 2 and "ANALYSIS_SCOPE" in p.stderr,
          f"Tier B: OWN014 candidate -> ANALYSIS_SCOPE ({p.stderr[-160:]})")


_POST_NEW_OWN001 = _ONE_LEAK.replace(
    "a.PropertyChanged += OnA;",
    "WeakEvents.AddPropertyChanged(a, OnA); c.PropertyChanged += OnA;")
_POST_NEW_OWN050 = _ONE_LEAK.replace(
    "public class S {", "public class S {\n        private ExternalThing _ext;").replace(
    "a.PropertyChanged += OnA;",
    "WeakEvents.AddPropertyChanged(a, OnA); _ext.Changed += OnA;")


def _forged_refusal(dotnet: str, dll: str, work: str, post_text: str, expect: str,
                    tag: str, check) -> None:
    """Build a forged-but-gate-valid bundle FROM SCRATCH whose postimage converts the
    candidate AND introduces the anomaly (`post_text`). The gate binds it (it never
    analyzes); verify-delta must refuse with `expect`."""
    from ownlang.fix_gate import _bundle_sha256
    lroot = _mkroot(_ONE_LEAK)
    try:
        cands = _candidates(dotnet, dll, lroot, work)
        plan = _plan(cands, work, {"OnA"})
        with open(cands, encoding="utf-8") as fh:
            c = json.load(fh)
        fid = c["candidates"][0]["finding_id"]
        pre_bytes = _ONE_LEAK.replace("\r\n", "\n").encode()
        post_bytes = post_text.replace("\r\n", "\n").encode()
        patch_bytes = _step8_patch(pre_bytes, post_bytes)
        bundle = os.path.join(work, f"bundle-{tag}")
        os.makedirs(os.path.join(bundle, "postimage", os.path.dirname(_REL)))
        with open(os.path.join(bundle, "postimage", *_REL.split("/")), "wb") as fh:
            fh.write(post_bytes)
        with open(os.path.join(bundle, "change.patch"), "wb") as fh:
            fh.write(patch_bytes)
        with open(plan, "rb") as fh:
            validated_plan_sha256 = _sha(fh.read())
        m = {"version": 1, "operation": "apply-subscription-fixes",
             "input_bundle_sha256": _bundle_sha256(c),
             "validated_plan_sha256": validated_plan_sha256,
             "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
             "source_files": [{"path": _REL, "pre_sha256": _sha(pre_bytes),
                               "post_sha256": _sha(post_bytes)}],
             "patch_sha256": _sha(patch_bytes), "applied_findings": [fid],
             "manual_review_findings": []}
        with open(os.path.join(bundle, "apply-manifest.json"), "wb") as fh:
            fh.write(json.dumps(m, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode() + b"\n")
        gate_out = os.path.join(work, f"gate-{tag}")
        p = _py(["own-fix", "subscriptions", "gate", "--bundle", bundle, "--plan", plan,
                 "--candidates", cands, "--root", lroot, "--out", gate_out])
        if p.returncode != 0:
            check(False, f"Tier B: {expect} forged bundle failed to gate ({p.stderr[-200:]})")
            return
        out = os.path.join(work, f"delta-{tag}")
        p = _verify(dotnet, dll, bundle, plan, cands, lroot,
                    os.path.join(gate_out, "gate-result.json"), out)
        check(p.returncode == 2 and expect in p.stderr,
              f"Tier B: forged postimage -> {expect} ({p.stderr[-160:]})")
    finally:
        shutil.rmtree(lroot, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run())
