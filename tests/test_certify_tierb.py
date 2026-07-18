#!/usr/bin/env python3
"""S2 step 12 — Tier B: the FULL public CLI acceptance of Final Evidence Certification.

Every case runs the real pipeline end to end through the PUBLIC command line only — never a
private helper as its proof:

    real extractor -> candidates -> validate-plan -> apply (Owen rewriter) -> gate
    -> `own-fix subscriptions verify-delta` (--ref-dir wrapper closure)
    -> `own-fix subscriptions verify-target` (fixed Roslyn bind + fixed runtime probe)
    -> `own-fix subscriptions certify`
    -> published certification-result.json

A genuine converted chain (a real weak wrapper shipped as a reference slot) and a manual-only
chain both certify with status evidence_complete; the published claims never assert
steps_8_11_gates_satisfied; and two independent Step 12 runs over fresh workspaces are
byte-identical while the repository (source / index / config / branch / worktree) is untouched.

Gating: REQUIRED (a missing dotnet / build / execution failure is a FAILURE, not a skip) exactly
when OWN_TIERB_REQUIRED=1 — which the wpf-extractor CI job sets. In any other context it is the
explicit non-required mode and skips cleanly, so the offline suite stays green.

Run:  OWN_TIERB_REQUIRED=1 python tests/test_certify_tierb.py
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

from ownlang.fix_certify import _CHECK_NAMES, _CLAIMS

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_RW = os.path.join(_REPO, "frontend", "roslyn", "Owen.CSharp.Rewriter")
_PROBE = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.WeakTargetProbe")
_REL = "S.cs"
_FQN = "S"

_PRE = """using System.ComponentModel;
public class S
{
    public S(INotifyPropertyChanged a) { a.PropertyChanged += OnA; }
    void OnA(object s, PropertyChangedEventArgs e) { }
}
"""
_WEAK = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    {
        var wr = new System.WeakReference(handler.Target);
        var mi = handler.Method;
        PropertyChangedEventHandler? relay = null;
        relay = (s, e) =>
        {
            var t = wr.Target;
            if (t == null) source.PropertyChanged -= relay;
            else mi.Invoke(t, new object?[] { s, e });
        };
        source.PropertyChanged += relay;
    }
}
"""

_CASES = [
    {"name": "converted", "wrapper": _WEAK, "convert": True, "chain_kind": "converted"},
    {"name": "manual", "wrapper": None, "convert": False, "chain_kind": "manual_only"},
]


class Fail(Exception):
    pass


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _run(argv: list[str], cwd: str | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, env=env,
                          encoding="utf-8", errors="replace")


def _py(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "ownlang", *args], cwd=cwd or _REPO)


def _find_dotnet() -> str | None:
    return shutil.which("dotnet") or (r"C:\Program Files\dotnet\dotnet.exe"
                                      if os.path.isfile(r"C:\Program Files\dotnet\dotnet.exe")
                                      else None)


def _dotnet_env(dotnet: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(dotnet) + os.pathsep + env.get("PATH", "")
    return env


def _build(dotnet: str) -> tuple[str, str]:
    for proj in (_EXT, _RW, _PROBE):
        p = _run([dotnet, "build", proj, "-c", "Release", "-v", "q", "--nologo"])
        if p.returncode != 0:
            raise Fail(f"build {proj}: {p.stdout[-400:]}{p.stderr[-400:]}")
    ext = glob.glob(os.path.join(_EXT, "bin", "*", "*", "ownsharp-extract.dll"))
    probe = glob.glob(os.path.join(_PROBE, "bin", "*", "net8.0", "OwnSharp.WeakTargetProbe.dll"))
    if not ext or not probe:
        raise Fail("extractor/probe DLL not found after build")
    return ext[0], probe[0]


def _csproj(asmname: str) -> str:
    return ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable>'
            '<LangVersion>latest</LangVersion>'
            f'<AssemblyName>{asmname}</AssemblyName><Deterministic>true</Deterministic>'
            '</PropertyGroup></Project>')


def _compile(dotnet: str, work: str, name: str, src: str, asmname: str) -> str:
    d = os.path.join(work, f"c-{name}")
    os.makedirs(d)
    with open(os.path.join(d, "P.csproj"), "w", encoding="utf-8") as fh:
        fh.write(_csproj(asmname))
    with open(os.path.join(d, "P.cs"), "w", encoding="utf-8") as fh:
        fh.write(src)
    p = _run([dotnet, "build", os.path.join(d, "P.csproj"), "-c", "Release", "-v", "q", "--nologo"])
    if p.returncode != 0:
        raise Fail(f"compile {name}: {p.stdout[-500:]}")
    return os.path.join(d, "bin", "Release", "net8.0", f"{asmname}.dll")


def _slot(work: str, name: str, dll: str) -> str:
    refdir = os.path.join(work, f"ref-{name}")
    os.makedirs(refdir)
    shutil.copy(dll, os.path.join(refdir, os.path.basename(dll)))
    return refdir


def _mkroot(work: str, name: str, cs: str) -> str:
    root = os.path.join(work, f"root-{name}")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, _REL), "wb") as fh:
        fh.write(cs.replace("\r\n", "\n").encode("utf-8"))
    return root


def _candidates(dotnet: str, dll: str, root: str, work: str) -> str:
    facts = os.path.join(work, "fc.json")
    p = _run([dotnet, "exec", dll, "extract", _REL, "--out", facts, "--fix-candidates",
              "--weak-subscribe", "WeakEvents.AddPropertyChanged"], cwd=root)
    if p.returncode != 0:
        raise Fail(f"extract: {p.stderr[-300:]}")
    own = os.path.join(work, "own.toml")
    with open(own, "w", encoding="utf-8") as fh:
        fh.write('[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n')
    cands = os.path.join(work, "candidates.json")
    p = _py(["own-fix", "subscriptions", "candidates", facts, "--config", own,
             "--class", _FQN, "--output", cands, "--root", root])
    if p.returncode != 0:
        raise Fail(f"candidates: {p.stderr[-300:]}")
    return cands


def _plan(cands: str, work: str, convert: bool) -> str:
    from ownlang.fix_plan import validate_plan
    with open(cands, encoding="utf-8") as fh:
        c = json.load(fh)
    action = "convert_acquire" if convert else "manual_review"
    decisions = [{"finding_id": x["finding_id"], "action": action} for x in c["candidates"]]
    plan = os.path.join(work, "plan.json")
    with open(plan, "w", encoding="utf-8") as fh:
        json.dump(validate_plan(c, {"version": 1, "decisions": decisions}), fh)
    return plan


def _apply_and_gate(cands: str, plan: str, root: str, work: str) -> tuple[str, str]:
    bundle = os.path.join(work, "bundle")
    rewriter = f'dotnet run --project "{_RW.replace(os.sep, "/")}" -c Release --no-build --'
    p = _py(["own-fix", "subscriptions", "apply", "--plan", plan, "--candidates", cands,
             "--root", root, "--out", bundle, "--rewriter", rewriter])
    if p.returncode != 0:
        raise Fail(f"apply: {p.stderr[-400:]}")
    gate_out = os.path.join(work, "gate")
    p = _py(["own-fix", "subscriptions", "gate", "--bundle", bundle, "--plan", plan,
             "--candidates", cands, "--root", root, "--out", gate_out])
    if p.returncode != 0:
        raise Fail(f"gate: {p.stderr[-400:]}")
    return bundle, os.path.join(gate_out, "gate-result.json")


def _verify_delta(dotnet: str, dll: str, bundle: str, plan: str, cands: str, root: str,
                  gate: str, work: str, ref_dirs: list[str]) -> str:
    out = os.path.join(work, "delta")
    argv = [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-delta",
            "--bundle", bundle, "--plan", plan, "--candidates", cands, "--root", root,
            "--gate", gate, "--extractor-dll", dll, "--out", out]
    for rd in ref_dirs:
        argv += ["--ref-dir", rd]
    p = _run(argv, cwd=_REPO, env=_dotnet_env(dotnet))
    if p.returncode != 0:
        raise Fail(f"verify-delta rc={p.returncode}: {p.stderr[-500:]}")
    return os.path.join(out, "delta-result.json")


def _verify_target(dotnet: str, probe: str, bundle: str, plan: str, cands: str, root: str,
                   delta: str, work: str, ref_dirs: list[str], convert: bool) -> str:
    out = os.path.join(work, "target")
    argv = [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-target",
            "--bundle", bundle, "--root", root, "--plan", plan, "--candidates", cands,
            "--delta", delta, "--out", out]
    if convert:
        argv += ["--probe-dll", probe, "--wrapper-ordinal", "0"]
    for rd in ref_dirs:
        argv += ["--ref-dir", rd]
    p = _run(argv, cwd=_REPO, env=_dotnet_env(dotnet))
    if p.returncode != 0:
        raise Fail(f"verify-target rc={p.returncode}: {p.stderr[-500:]}")
    return os.path.join(out, "target-result.json")


def _certify(plan: str, cands: str, bundle: str, gate: str, delta: str, target: str, out: str,
             ref_dirs: list[str]) -> subprocess.CompletedProcess:
    argv = ["own-fix", "subscriptions", "certify", "--plan", plan, "--candidates", cands,
            "--bundle", bundle, "--gate", gate, "--delta", delta, "--target", target, "--out", out]
    for rd in ref_dirs:
        argv += ["--ref-dir", rd]
    return _py(argv)


def _chain(dotnet: str, ext: str, probe: str, work: str, c: dict) -> dict:
    """extract -> candidates -> plan -> apply -> gate -> verify-delta -> verify-target."""
    name = c["name"]
    w = os.path.join(work, f"run-{name}")
    os.makedirs(w, exist_ok=True)
    ref_dirs: list[str] = []
    if c["wrapper"] is not None:
        ref_dirs = [_slot(work, name, _compile(dotnet, work, f"w-{name}", c["wrapper"],
                                               "WeakEvents"))]
    root = _mkroot(work, name, _PRE)
    cands = _candidates(dotnet, ext, root, w)
    plan = _plan(cands, w, c["convert"])
    bundle, gate = _apply_and_gate(cands, plan, root, w)
    delta = _verify_delta(dotnet, ext, bundle, plan, cands, root, gate, w, ref_dirs)
    target = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, w, ref_dirs,
                            c["convert"])
    return {"plan": plan, "cands": cands, "bundle": bundle, "gate": gate, "delta": delta,
            "target": target, "ref_dirs": ref_dirs, "w": w}


def _no_absolute_paths(raw: bytes, check, name: str) -> None:
    text = raw.decode("utf-8")
    leaked = bool(re.search(r"[A-Za-z]:\\", text)) or any(
        s in text for s in ("/tmp/", "/home/", "/var/", "/root/", "\\\\"))
    check(not leaked, f"{name}: evidence publishes no absolute path")


def _schema_ok(path: str, chain_kind: str, check, name: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    obj = json.loads(raw)
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    check(raw == canon.encode() + b"\n", f"{name}: certification-result.json is canonical bytes")
    check(obj.get("schema") == 1 and obj.get("operation") == "certify-subscription-fix-chain"
          and obj.get("status") == "evidence_complete", f"{name}: schema/operation/status")
    check(obj.get("chain_kind") == chain_kind, f"{name}: chain_kind {chain_kind}")
    check(set(obj["checks"]) == set(_CHECK_NAMES) and len(_CHECK_NAMES) == 12,
          f"{name}: exactly the twelve checks")
    check(obj["certification"]["claims"] == list(_CLAIMS), f"{name}: exact claims array")
    check("steps_8_11_gates_satisfied" not in raw.decode("utf-8"),
          f"{name}: no steps_8_11_gates_satisfied in the published evidence")
    check(set(obj["artifact_hashes"]) == {
        "candidates_sha256", "validated_plan_sha256", "apply_manifest_sha256", "patch_sha256",
        "post_sha256", "gate_result_sha256", "delta_result_sha256", "target_result_sha256"},
        f"{name}: eight artifact_hashes")
    check(set(obj["semantic_hashes"]) == {"input_bundle_sha256"}, f"{name}: one semantic_hash")
    check(obj["preimage_binding"] == {"mode": "cross_artifact_only", "bytes_supplied": False,
                                      "pre_sha256": obj["preimage_binding"]["pre_sha256"]},
          f"{name}: cross-artifact preimage binding, bytes not supplied")
    _no_absolute_paths(raw, check, name)
    return obj


def _git(args: list[str]) -> str:
    return _run(["git", *args], cwd=_REPO).stdout.strip()


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    if not required:
        print("certify (Tier B): SKIP (non-required mode; set OWN_TIERB_REQUIRED=1)")
        return 0
    dotnet = _find_dotnet()
    if dotnet is None:
        print("certify (Tier B): FAIL — required but no dotnet host")
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
        ext, probe = _build(dotnet)
        with tempfile.TemporaryDirectory() as work:
            head_before = _git(["rev-parse", "HEAD"])
            status_before = _git(["status", "--porcelain"])
            for c in _CASES:
                _run_case(dotnet, ext, probe, work, c, check)
            check(_git(["rev-parse", "HEAD"]) == head_before,
                  "no branch / HEAD movement across certification")
            check(_git(["status", "--porcelain"]) == status_before,
                  "no source / index / worktree mutation across certification")
    except Fail as exc:
        fails.append(f"Tier B setup: {exc}")

    for f in fails:
        print(f"  FAIL: {f}")
    total = ok + len(fails)
    print(f"certify (Tier B, full CLI): {ok}/{total} checks pass")
    return 1 if fails else 0


def _run_case(dotnet: str, ext: str, probe: str, work: str, c: dict, check) -> None:
    name = c["name"]
    try:
        chain = _chain(dotnet, ext, probe, work, c)
    except Fail as exc:
        check(False, f"{name}: chain setup failed ({exc})")
        return
    out1 = os.path.join(chain["w"], "cert-1")
    out2 = os.path.join(chain["w"], "cert-2")
    p1 = _certify(chain["plan"], chain["cands"], chain["bundle"], chain["gate"], chain["delta"],
                  chain["target"], out1, chain["ref_dirs"])
    if p1.returncode != 0:
        check(False, f"{name}: certify rc={p1.returncode} ({p1.stderr.strip()[-200:]})")
        return
    obj = _schema_ok(os.path.join(out1, "certification-result.json"), c["chain_kind"], check, name)
    if c["convert"]:
        check(obj["target_binding"]["wrapper_identity"]["assembly_simple_name"] == "WeakEvents",
              f"{name}: wrapper identity is WeakEvents")
        check(obj["certification"]["converted_callsites"] == 1, f"{name}: one converted callsite")
    else:
        check(obj["target_binding"]["wrapper_identity"] is None,
              f"{name}: manual-only wrapper_identity is null")
    p2 = _certify(chain["plan"], chain["cands"], chain["bundle"], chain["gate"], chain["delta"],
                  chain["target"], out2, chain["ref_dirs"])
    if p2.returncode != 0:
        check(False, f"{name}: second certify rc={p2.returncode} ({p2.stderr.strip()[-200:]})")
        return
    with open(os.path.join(out1, "certification-result.json"), "rb") as fh:
        r1 = fh.read()
    with open(os.path.join(out2, "certification-result.json"), "rb") as fh:
        r2 = fh.read()
    check(r1 == r2, f"{name}: two independent runs are byte-identical")
    check(_sha(r1) == _sha(r2), f"{name}: identical certification evidence sha")


if __name__ == "__main__":
    raise SystemExit(run())
