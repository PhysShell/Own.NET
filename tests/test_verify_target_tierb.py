#!/usr/bin/env python3
"""S2 step 11 — Tier B: the FULL public CLI acceptance of the fake-target gate.

Every case runs the real pipeline end to end through the PUBLIC command line only —
never a private helper as its proof:

    real extractor -> candidates -> validate-plan -> apply (Owen rewriter) -> gate
    -> `own-fix subscriptions verify-delta` (--ref-dir wrapper closure)
    -> `own-fix subscriptions verify-target` (fixed Roslyn bind + fixed runtime probe)
    -> published target-result.json

The wrapper under test is a SEPARATELY COMPILED assembly shipped as a reference slot (a
name-only-recognized decoy cannot pass): a genuine weak wrapper is accepted; a strong decoy is
refused TARGET_RETAINS; no-op / twice-delivering / throwing wrappers are refused TARGET_BEHAVIOR;
a wrong-signature wrapper is refused WRAPPER_BINDING; a source-defined target is refused
CALLSITE_BINDING; two converted callsites onto the same wrapper pass; a net9 / missing-dependency
wrapper is refused WRAPPER_RUNTIME_UNSUPPORTED (never TARGET_RETAINS); a manual-only plan passes
with the six probe checks not_applicable; and two independent runs are byte-identical.

Gating: REQUIRED (a missing dotnet / build / execution failure is a FAILURE, not a skip) exactly
when OWN_TIERB_REQUIRED=1 — which the wpf-extractor CI job sets. In any other context it is the
explicit non-required mode and skips cleanly, so the offline suite stays green.

Run:  OWN_TIERB_REQUIRED=1 python tests/test_verify_target_tierb.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.fix_target import _CHECK_NAMES, _MANUAL_ONLY_NA

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_RW = os.path.join(_REPO, "frontend", "roslyn", "Owen.CSharp.Rewriter")
_PROBE = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.WeakTargetProbe")
_REL = "S.cs"
_FQN = "S"

# --- the pristine preimage variants ------------------------------------------------
_PRE = """using System.ComponentModel;
public class S
{
    public S(INotifyPropertyChanged a) { a.PropertyChanged += OnA; }
    void OnA(object s, PropertyChangedEventArgs e) { }
}
"""
# two DISTINCT converted callsites (a, b) both onto the same wrapper.
_PRE_TWO = """using System.ComponentModel;
public class S
{
    public S(INotifyPropertyChanged a, INotifyPropertyChanged b)
    { a.PropertyChanged += OnA; b.PropertyChanged += OnA; }
    void OnA(object s, PropertyChangedEventArgs e) { }
}
"""
# the wrapper is defined IN the source (not a reference slot) -> CALLSITE_BINDING.
_PRE_SRCDEF = """using System.ComponentModel;
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
            else mi.Invoke(t, new object?[]{s, e});
        };
        source.PropertyChanged += relay;
    }
}
public class S
{
    public S(INotifyPropertyChanged a) { a.PropertyChanged += OnA; }
    void OnA(object s, PropertyChangedEventArgs e) { }
}
"""

# --- the wrapper variants (all named WeakEvents.AddPropertyChanged) -----------------
_WEAK = """using System.ComponentModel;
public static class WeakEvents
{
    // A genuine non-retaining subscription: the subscriber is held only weakly.
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
_STRONG = """using System.ComponentModel;
public static class WeakEvents
{
    // A decoy: named like the accepted wrapper but strongly retains the subscriber.
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    { source.PropertyChanged += handler; }
}
"""
_NOOP = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
}
"""
_TWICE = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    { source.PropertyChanged += handler; source.PropertyChanged += handler; }
}
"""
_THROWING = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    { throw new System.InvalidOperationException("no target"); }
}
"""
_WRONGSIG = """using System.ComponentModel;
public static class WeakEvents
{
    // wrong shape: an extra parameter, so the accepted (INPC, PCEH) target does not exist.
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler, int extra) { }
}
"""
# net9 wrapper: correct shape and byte-valid metadata, but cannot execute under the net8 probe.
_INCOMPAT = _STRONG
# missing runtime dependency: the body calls a Helper assembly not shipped in the slot.
_HELPER = "namespace Helper { public static class Aux { public static void Touch() { } } }\n"
_MISSINGDEP = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    { Helper.Aux.Touch(); source.PropertyChanged += handler; }
}
"""

_CASES = [
    {"name": "weak", "pre": _PRE, "wrapper": _WEAK, "convert": True, "ref": True,
     "probe": True, "expect": ("pass", "converted")},
    {"name": "strong", "pre": _PRE, "wrapper": _STRONG, "convert": True, "ref": True,
     "probe": True, "expect": ("refuse", "TARGET_RETAINS")},
    {"name": "noop", "pre": _PRE, "wrapper": _NOOP, "convert": True, "ref": True,
     "probe": True, "expect": ("refuse", "TARGET_BEHAVIOR")},
    {"name": "twice", "pre": _PRE, "wrapper": _TWICE, "convert": True, "ref": True,
     "probe": True, "expect": ("refuse", "TARGET_BEHAVIOR")},
    {"name": "throwing", "pre": _PRE, "wrapper": _THROWING, "convert": True, "ref": True,
     "probe": True, "expect": ("refuse", "TARGET_BEHAVIOR")},
    {"name": "wrongsig", "pre": _PRE, "wrapper": _WRONGSIG, "convert": True, "ref": True,
     "probe": True, "expect": ("refuse", "WRAPPER_BINDING")},
    {"name": "srcdef", "pre": _PRE_SRCDEF, "wrapper": None, "convert": True, "ref": False,
     "probe": True, "expect": ("refuse", "CALLSITE_BINDING")},
    {"name": "twoconv", "pre": _PRE_TWO, "wrapper": _WEAK, "convert": True, "ref": True,
     "probe": True, "expect": ("pass", "two")},
    {"name": "incompat", "pre": _PRE, "wrapper": _INCOMPAT, "tfm": "net9.0", "convert": True,
     "ref": True, "probe": True, "expect": ("refuse", "WRAPPER_RUNTIME_UNSUPPORTED")},
    {"name": "missingdep", "pre": _PRE, "wrapper": _MISSINGDEP, "helper": _HELPER,
     "convert": True, "ref": True, "probe": True,
     "expect": ("refuse", "WRAPPER_RUNTIME_UNSUPPORTED")},
    {"name": "manual", "pre": _PRE, "wrapper": None, "convert": False, "ref": False,
     "probe": False, "expect": ("pass", "manual")},
]


class Fail(Exception):
    pass


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _run(argv: list[str], cwd: str | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, env=env)


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


def _csproj(tfm: str, helper_hint: str | None) -> str:
    ref = (f'<ItemGroup><Reference Include="Helper"><HintPath>{helper_hint}</HintPath>'
           f'</Reference></ItemGroup>') if helper_hint else ""
    return (f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            f'<TargetFramework>{tfm}</TargetFramework><Nullable>enable</Nullable>'
            f'<AssemblyName>WeakEvents</AssemblyName><Deterministic>true</Deterministic>'
            f'</PropertyGroup>{ref}</Project>')


def _build_wrapper(dotnet: str, work: str, name: str, src: str, tfm: str,
                   helper: str | None) -> str:
    """Compile a standalone WeakEvents.dll (optionally referencing a NON-shipped Helper.dll)
    and return a fresh ref-dir holding ONLY WeakEvents.dll (exactly one ordered slot)."""
    helper_hint = None
    if helper is not None:
        hd = os.path.join(work, f"h-{name}")
        os.makedirs(hd)
        with open(os.path.join(hd, "H.csproj"), "w", encoding="utf-8") as fh:
            fh.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                     f'<TargetFramework>{tfm}</TargetFramework><AssemblyName>Helper</AssemblyName>'
                     '<Deterministic>true</Deterministic></PropertyGroup></Project>')
        with open(os.path.join(hd, "H.cs"), "w", encoding="utf-8") as fh:
            fh.write(helper)
        p = _run([dotnet, "build", os.path.join(hd, "H.csproj"), "-c", "Release", "-v", "q",
                  "--nologo"])
        if p.returncode != 0:
            raise Fail(f"helper build: {p.stdout[-300:]}")
        helper_hint = os.path.join(hd, "bin", "Release", tfm, "Helper.dll")
    wd = os.path.join(work, f"w-{name}")
    os.makedirs(wd)
    with open(os.path.join(wd, "W.csproj"), "w", encoding="utf-8") as fh:
        fh.write(_csproj(tfm, helper_hint))
    with open(os.path.join(wd, "W.cs"), "w", encoding="utf-8") as fh:
        fh.write(src)
    p = _run([dotnet, "build", os.path.join(wd, "W.csproj"), "-c", "Release", "-v", "q",
              "--nologo"])
    if p.returncode != 0:
        raise Fail(f"wrapper {name} build: {p.stdout[-400:]}")
    refdir = os.path.join(work, f"ref-{name}")
    os.makedirs(refdir)
    shutil.copy(os.path.join(wd, "bin", "Release", tfm, "WeakEvents.dll"),
                os.path.join(refdir, "WeakEvents.dll"))
    return refdir


def _mkroot(work: str, name: str, cs: str) -> str:
    root = os.path.join(work, f"root-{name}")
    os.makedirs(os.path.join(root, os.path.dirname(_REL)) if os.path.dirname(_REL) else root,
                exist_ok=True)
    with open(os.path.join(root, *_REL.split("/")), "wb") as fh:
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
                  gate: str, work: str, refdir: str | None) -> str:
    out = os.path.join(work, "delta")
    argv = [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-delta",
            "--bundle", bundle, "--plan", plan, "--candidates", cands, "--root", root,
            "--gate", gate, "--extractor-dll", dll, "--out", out]
    if refdir:
        argv += ["--ref-dir", refdir]
    p = _run(argv, cwd=_REPO, env=_dotnet_env(dotnet))
    if p.returncode != 0:
        raise Fail(f"verify-delta rc={p.returncode}: {p.stderr[-500:]}")
    return os.path.join(out, "delta-result.json")


def _verify_target(dotnet: str, probe: str, bundle: str, plan: str, cands: str, root: str,
                   delta: str, out: str, refdir: str | None, ordinal: int,
                   use_probe: bool) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-target",
            "--bundle", bundle, "--root", root, "--plan", plan, "--candidates", cands,
            "--delta", delta, "--out", out]
    if use_probe:
        argv += ["--probe-dll", probe, "--wrapper-ordinal", str(ordinal)]
    if refdir:
        argv += ["--ref-dir", refdir]
    return _run(argv, cwd=_REPO, env=_dotnet_env(dotnet))


def _schema_ok(path: str, manual: bool, check, name: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    obj = json.loads(raw)
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    check(raw == canon.encode() + b"\n", f"{name}: target-result.json is canonical bytes + LF")
    check(obj.get("schema") == 1 and obj.get("operation") == "verify-target-wrapper"
          and obj.get("status") == "pass", f"{name}: schema/operation/status")
    check(set(obj["checks"]) == set(_CHECK_NAMES) and len(_CHECK_NAMES) == 11,
          f"{name}: exactly the eleven checks")
    check(obj["delta_binding"]["bound"] is True and obj["delta_binding"]["step10_status"] == "pass",
          f"{name}: delta bound")
    return obj


def run() -> int:
    required = os.environ.get("OWN_TIERB_REQUIRED") == "1"
    if not required:
        print("verify-target (Tier B): SKIP (non-required mode; set OWN_TIERB_REQUIRED=1)")
        return 0
    dotnet = _find_dotnet()
    if dotnet is None:
        print("verify-target (Tier B): FAIL — required but no dotnet host")
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
            for c in _CASES:
                _run_case(dotnet, ext, probe, work, c, check)
            _determinism(dotnet, ext, probe, work, check)
    except Fail as exc:
        fails.append(f"Tier B setup: {exc}")

    for f in fails:
        print(f"  FAIL: {f}")
    total = ok + len(fails)
    print(f"verify-target (Tier B, full CLI): {ok}/{total} checks pass")
    return 1 if fails else 0


def _chain(dotnet: str, ext: str, work: str,
           c: dict) -> tuple[str, str, str, str, str | None, str]:
    """extract -> candidates -> plan -> apply -> gate -> verify-delta; returns
    (bundle, plan, cands, delta, refdir, root)."""
    name = c["name"]
    tfm = c.get("tfm", "net8.0")
    refdir = None
    if c["wrapper"] is not None:
        refdir = _build_wrapper(dotnet, work, name, c["wrapper"], tfm, c.get("helper"))
    root = _mkroot(work, name, c["pre"])
    w = os.path.join(work, f"run-{name}")
    os.makedirs(w)
    cands = _candidates(dotnet, ext, root, w)
    plan = _plan(cands, w, c["convert"])
    bundle, gate = _apply_and_gate(cands, plan, root, w)
    delta = _verify_delta(dotnet, ext, bundle, plan, cands, root, gate, w,
                          refdir if c["ref"] else None)
    return bundle, plan, cands, delta, (refdir if c["ref"] else None), root


def _run_case(dotnet: str, ext: str, probe: str, work: str, c: dict, check) -> None:
    name = c["name"]
    try:
        bundle, plan, cands, delta, refdir, root = _chain(dotnet, ext, work, c)
    except Fail as exc:
        check(False, f"{name}: chain setup failed ({exc})")
        return
    out = os.path.join(work, f"run-{name}", "target")
    p = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, out, refdir, 0, c["probe"])
    kind, detail = c["expect"]
    if kind == "refuse":
        check(p.returncode == 2 and detail in p.stderr,
              f"{name}: expect refuse {detail} (rc={p.returncode}: {p.stderr.strip()[-160:]})")
        return
    if p.returncode != 0:
        check(False, f"{name}: expect pass ({p.stderr.strip()[-200:]})")
        return
    obj = _schema_ok(os.path.join(out, "target-result.json"), detail == "manual", check, name)
    if detail == "manual":
        na = {k for k, v in obj["checks"].items() if v == "not_applicable"}
        check(na == set(_MANUAL_ONLY_NA), f"{name}: exactly the six not_applicable")
        check(all(k not in obj for k in ("selected_wrapper", "attempts", "callsite_binding")),
              f"{name}: manual-only omits the probe fields")
    else:
        check(set(obj["checks"].values()) == {"pass"}, f"{name}: all eleven checks pass")
        check(len(obj["attempts"]) == 3, f"{name}: three probe attempts recorded")
        check(obj["selected_wrapper"]["assembly_simple_name"] == "WeakEvents",
              f"{name}: selected wrapper is WeakEvents")
        want = 2 if detail == "two" else 1
        check(obj["callsite_binding"]["converted_callsites"] == want,
              f"{name}: converted_callsites == {want}")
        check(obj["callsite_binding"]["derived_wrapper_ordinal"]
              == obj["callsite_binding"]["asserted_wrapper_ordinal"] == 0,
              f"{name}: derived == asserted ordinal 0")


def _determinism(dotnet: str, ext: str, probe: str, work: str, check) -> None:
    c = {"name": "det", "pre": _PRE, "wrapper": _WEAK, "convert": True, "ref": True,
         "probe": True, "expect": ("pass", "converted")}
    try:
        bundle, plan, cands, delta, refdir, root = _chain(dotnet, ext, work, c)
    except Fail as exc:
        check(False, f"determinism: chain setup failed ({exc})")
        return
    o1 = os.path.join(work, "det-1")
    o2 = os.path.join(work, "det-2")
    p1 = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, o1, refdir, 0, True)
    p2 = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, o2, refdir, 0, True)
    if p1.returncode != 0 or p2.returncode != 0:
        check(False, f"determinism: a run failed ({p1.returncode}/{p2.returncode})")
        return
    with open(os.path.join(o1, "target-result.json"), "rb") as fh:
        r1 = fh.read()
    with open(os.path.join(o2, "target-result.json"), "rb") as fh:
        r2 = fh.read()
    check(r1 == r2, "determinism: two independent runs are byte-identical")
    check(_sha(r1) == _sha(r2), "determinism: identical evidence sha")


if __name__ == "__main__":
    raise SystemExit(run())
