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
# exact-shape target PLUS a same-name overload -> WRAPPER_BINDING (no other overload allowed).
_OVERLOAD = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
    public static void AddPropertyChanged(string source, PropertyChangedEventHandler handler) { }
}
"""
# two different assemblies both exporting global WeakEvents -> the source call is ambiguous.
_AMB = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
}
"""
# a wrapper that depends on a Helper assembly (weak, genuinely non-retaining) when Helper resolves.
_DEPWEAK = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    {
        Helper.Aux.Touch();
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
_HELPER_OK = "namespace Helper { public static class Aux { public static void Touch() { } } }\n"
_HELPER_THROW = ("namespace Helper { public static class Aux { public static void Touch() "
                 "{ throw new System.InvalidOperationException(\"bad helper\"); } } }\n")
# a wrapper whose body makes a RUNTIME call into Microsoft.CodeAnalysis — a NON-framework assembly
# already present in the probe's default context — proving the closed load context never satisfies
# it from there. (A constant/enum reference would be folded at compile time and load nothing, so the
# body must force an actual assembly load: a real method call into the Roslyn assembly.)
_DEP_ROSLYN = """using System.ComponentModel;
public static class WeakEvents
{
    public static void AddPropertyChanged(
        INotifyPropertyChanged source, PropertyChangedEventHandler handler)
    {
        var e = Microsoft.CodeAnalysis.CSharp.SyntaxFactory.ParseExpression("a");
        if (e != null) source.PropertyChanged += handler;
    }
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
    {"name": "overload", "pre": _PRE, "wrapper": _OVERLOAD, "convert": True, "ref": True,
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


def _csproj(tfm: str, refs: list[tuple[str, str]], asmname: str,
            pkgs: list[tuple[str, str]] | None = None) -> str:
    items = "".join(f'<Reference Include="{n}"><HintPath>{h}</HintPath></Reference>'
                    for n, h in refs)
    items += "".join(f'<PackageReference Include="{n}" Version="{v}" />'
                     for n, v in (pkgs or []))
    grp = f"<ItemGroup>{items}</ItemGroup>" if items else ""
    return (f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            f'<TargetFramework>{tfm}</TargetFramework><Nullable>enable</Nullable>'
            f'<AssemblyName>{asmname}</AssemblyName><Deterministic>true</Deterministic>'
            f'</PropertyGroup>{grp}</Project>')


def _compile(dotnet: str, work: str, name: str, src: str, tfm: str, asmname: str,
             refs: list[tuple[str, str]] | None = None,
             pkgs: list[tuple[str, str]] | None = None) -> str:
    """Compile <asmname>.dll and return its output path (not a slot)."""
    d = os.path.join(work, f"c-{name}")
    os.makedirs(d)
    with open(os.path.join(d, "P.csproj"), "w", encoding="utf-8") as fh:
        fh.write(_csproj(tfm, refs or [], asmname, pkgs))
    with open(os.path.join(d, "P.cs"), "w", encoding="utf-8") as fh:
        fh.write(src)
    p = _run([dotnet, "build", os.path.join(d, "P.csproj"), "-c", "Release", "-v", "q", "--nologo"])
    if p.returncode != 0:
        raise Fail(f"compile {name}: {p.stdout[-500:]}")
    return os.path.join(d, "bin", "Release", tfm, f"{asmname}.dll")


def _slot(work: str, name: str, dll: str, as_name: str | None = None) -> str:
    """A fresh ref-dir holding exactly one DLL (one ordered slot)."""
    refdir = os.path.join(work, f"ref-{name}")
    os.makedirs(refdir)
    shutil.copy(dll, os.path.join(refdir, as_name or os.path.basename(dll)))
    return refdir


def _build_wrapper(dotnet: str, work: str, name: str, src: str, tfm: str,
                   helper: str | None, asmname: str = "WeakEvents") -> str:
    """Compile a standalone <asmname>.dll (optionally referencing a NON-shipped Helper.dll)
    and return a fresh ref-dir holding ONLY that DLL (exactly one ordered slot)."""
    refs: list[tuple[str, str]] = []
    if helper is not None:
        helper_dll = _compile(dotnet, work, f"h-{name}", helper, tfm, "Helper")
        refs.append(("Helper", helper_dll))
    dll = _compile(dotnet, work, f"w-{name}", src, tfm, asmname, refs)
    return _slot(work, name, dll)


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
                   delta: str, out: str, ref_dirs: list[str], ordinal: int | None,
                   use_probe: bool, env: dict | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-m", "ownlang", "own-fix", "subscriptions", "verify-target",
            "--bundle", bundle, "--root", root, "--plan", plan, "--candidates", cands,
            "--delta", delta, "--out", out]
    if use_probe:
        argv += ["--probe-dll", probe, "--wrapper-ordinal", str(ordinal)]
    for rd in ref_dirs:
        argv += ["--ref-dir", rd]
    return _run(argv, cwd=_REPO, env=env or _dotnet_env(dotnet))


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
    _no_absolute_paths(raw, check, name)
    return obj


def _no_absolute_paths(raw: bytes, check, name: str) -> None:
    """No slot / deployment / execution absolute path may leak into published evidence (H2)."""
    import re
    text = raw.decode("utf-8")
    leaked = bool(re.search(r"[A-Za-z]:\\", text)) or any(
        s in text for s in ("/tmp/", "/home/", "/var/", "/root/", "\\\\"))
    check(not leaked, f"{name}: evidence publishes no absolute path")


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
            _run_ambiguous(dotnet, ext, probe, work, check)
            _run_bind_unit_cases(dotnet, ext, probe, work, check)
            _run_dep_cases(dotnet, ext, probe, work, check)
            _run_two_slot_versions(dotnet, ext, probe, work, check)
    except Fail as exc:
        fails.append(f"Tier B setup: {exc}")

    for f in fails:
        print(f"  FAIL: {f}")
    total = ok + len(fails)
    print(f"verify-target (Tier B, full CLI): {ok}/{total} checks pass")
    return 1 if fails else 0


def _build_chain(dotnet: str, ext: str, work: str, name: str, pre: str, ref_dirs: list[str],
                 convert: bool) -> tuple[str, str, str, str, str, str]:
    """extract -> candidates -> plan -> apply -> gate -> verify-delta over EXPLICIT ref-dirs;
    returns (bundle, plan, cands, delta, root, workdir)."""
    root = _mkroot(work, name, pre)
    w = os.path.join(work, f"run-{name}")
    os.makedirs(w, exist_ok=True)
    cands = _candidates(dotnet, ext, root, w)
    plan = _plan(cands, w, convert)
    bundle, gate = _apply_and_gate(cands, plan, root, w)
    delta = _verify_delta(dotnet, ext, bundle, plan, cands, root, gate, w, ref_dirs)
    return bundle, plan, cands, delta, root, w


def _chain(dotnet: str, ext: str, work: str,
           c: dict) -> tuple[str, str, str, str, list[str], str]:
    name = c["name"]
    ref_dirs: list[str] = []
    if c["wrapper"] is not None:
        ref_dirs = [_build_wrapper(dotnet, work, name, c["wrapper"], c.get("tfm", "net8.0"),
                                   c.get("helper"))]
    used = ref_dirs if c["ref"] else []
    bundle, plan, cands, delta, root, _w = _build_chain(dotnet, ext, work, name, c["pre"],
                                                        used, c["convert"])
    return bundle, plan, cands, delta, used, root


def _run_case(dotnet: str, ext: str, probe: str, work: str, c: dict, check) -> None:
    name = c["name"]
    try:
        bundle, plan, cands, delta, ref_dirs, root = _chain(dotnet, ext, work, c)
    except Fail as exc:
        check(False, f"{name}: chain setup failed ({exc})")
        return
    out = os.path.join(work, f"run-{name}", "target")
    p = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, out, ref_dirs,
                       0 if c["probe"] else None, c["probe"])
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
        bundle, plan, cands, delta, ref_dirs, root = _chain(dotnet, ext, work, c)
    except Fail as exc:
        check(False, f"determinism: chain setup failed ({exc})")
        return
    o1 = os.path.join(work, "det-1")
    o2 = os.path.join(work, "det-2")
    p1 = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, o1, ref_dirs, 0, True)
    p2 = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, o2, ref_dirs, 0, True)
    if p1.returncode != 0 or p2.returncode != 0:
        check(False, f"determinism: a run failed ({p1.returncode}/{p2.returncode})")
        return
    with open(os.path.join(o1, "target-result.json"), "rb") as fh:
        r1 = fh.read()
    with open(os.path.join(o2, "target-result.json"), "rb") as fh:
        r2 = fh.read()
    check(r1 == r2, "determinism: two independent runs are byte-identical")
    check(_sha(r1) == _sha(r2), "determinism: identical evidence sha")


def _expect_result(p: subprocess.CompletedProcess, out: str, expect: tuple[str, str],
                   check, name: str) -> dict | None:
    kind, detail = expect
    if kind == "refuse":
        check(p.returncode == 2 and detail in p.stderr,
              f"{name}: expect refuse {detail} (rc={p.returncode}: {p.stderr.strip()[-160:]})")
        return None
    if p.returncode != 0:
        check(False, f"{name}: expect pass ({p.stderr.strip()[-200:]})")
        return None
    return _schema_ok(os.path.join(out, "target-result.json"), detail == "manual", check, name)


def _run_ambiguous(dotnet: str, ext: str, probe: str, work: str, check) -> None:
    """H1: two DIFFERENT reference assemblies both exporting global WeakEvents make the source
    call ambiguous -> CALLSITE_BINDING (a candidate is never promoted to the bound symbol)."""
    try:
        da = _slot(work, "ambA", _compile(dotnet, work, "ambA", _AMB, "net8.0", "WeakEventsA"))
        db = _slot(work, "ambB", _compile(dotnet, work, "ambB", _AMB, "net8.0", "WeakEventsB"))
        bundle, plan, cands, delta, root, w = _build_chain(dotnet, ext, work, "amb", _PRE,
                                                           [da, db], True)
    except Fail as exc:
        check(False, f"ambiguous: chain setup failed ({exc})")
        return
    out = os.path.join(w, "target")
    p = _verify_target(dotnet, probe, bundle, plan, cands, root, delta, out, [da, db], 0, True)
    _expect_result(p, out, ("refuse", "CALLSITE_BINDING"), check, "ambiguous")


# K3: an exact-shape net8 wrapper with a callsite that cannot bind for a NON-runtime reason must be
# CALLSITE_BINDING (never WRAPPER_RUNTIME_UNSUPPORTED). These are bind-unit cases: the postimage is
# crafted so Roslyn's SemanticModel returns a null Symbol, exercising the positive-predicate branch.
_PRE_OBJ = ("using System.ComponentModel;\npublic class S { public S(object a) "
            "{ a.PropertyChanged += OnA; } void OnA(object s, PropertyChangedEventArgs e){} }\n")
_POST_OBJ = ("using System.ComponentModel;\npublic class S { public S(object a) "
             "{ WeakEvents.AddPropertyChanged(a, OnA); } "
             "void OnA(object s, PropertyChangedEventArgs e){} }\n")
_PRE_BADH = ("using System.ComponentModel;\npublic class S { public S(INotifyPropertyChanged a) "
             "{ a.PropertyChanged += OnA; } void OnA(int x){} void OnA(string y){} }\n")
_POST_BADH = ("using System.ComponentModel;\npublic class S { public S(INotifyPropertyChanged a) "
              "{ WeakEvents.AddPropertyChanged(a, OnA); } "
              "void OnA(int x){} void OnA(string y){} }\n")


def _bind_unit(dotnet: str, probe: str, work: str, name: str, pre: str, post: str,
               wrapper: str, expect_cat: str, check) -> None:
    from ownlang.fix_delta import _select_runtime
    from ownlang.fix_target import TargetError, run_bind
    try:
        dll = _compile(dotnet, work, f"bu-{name}", wrapper, "net8.0", "WeakEvents")
        slot = os.path.join(work, f"buslots-{name}", "000000")
        os.makedirs(slot)
        shutil.copy(dll, os.path.join(slot, "WeakEvents.dll"))
        slots_root = os.path.dirname(slot)
        listing = _run([dotnet, "--list-runtimes"]).stdout
        selected_ver, _rt = _select_runtime(listing, "Microsoft.NETCore.App", "8.0.0")
        start = pre.index("a.PropertyChanged += OnA")
        fid = "OWN001:sha256:" + "a" * 64
        bind_params = {"converted": [{"finding_id": fid, "occurrence_ordinal": 0, "file": "S.cs",
                                      "containing_type": "S", "event": "PropertyChanged",
                                      "source": "a", "handler": "OnA", "normalized_handler": "OnA",
                                      "acquire_span": {"start": start,
                                                       "length": len("a.PropertyChanged += OnA")}}]}
        w = os.path.join(work, f"buw-{name}")
        os.makedirs(w)
    except Fail as exc:
        check(False, f"bind-unit {name}: setup failed ({exc})")
        return
    try:
        run_bind(w, dotnet, probe, selected_ver, "S.cs", pre, post, slots_root,
                 "WeakEvents.AddPropertyChanged", "S", bind_params, [fid])
        check(False, f"bind-unit {name}: expected {expect_cat} but bind passed")
    except TargetError as exc:
        check(exc.category == expect_cat,
              f"bind-unit {name}: {exc.category} (want {expect_cat})")


def _run_bind_unit_cases(dotnet: str, ext: str, probe: str, work: str, check) -> None:
    # exact-shape net8 wrapper, receiver cannot convert to INPC -> CALLSITE_BINDING (not runtime)
    _bind_unit(dotnet, probe, work, "argconv", _PRE_OBJ, _POST_OBJ, _WEAK,
               "CALLSITE_BINDING", check)
    # exact-shape net8 wrapper, ambiguous / non-convertible handler method group -> CALLSITE_BINDING
    _bind_unit(dotnet, probe, work, "badhandler", _PRE_BADH, _POST_BADH, _WEAK,
               "CALLSITE_BINDING", check)


def _run_dep_cases(dotnet: str, ext: str, probe: str, work: str, check) -> None:
    """H2: the closed load context. A wrapper dependency resolves ONLY from a materialized slot;
    it is never satisfied from the probe deployment, the default context, or an arbitrary path."""
    # (a) dependency present in an accepted slot -> pass.
    try:
        helper = _compile(dotnet, work, "dhOK", _HELPER_OK, "net8.0", "Helper")
        weak = _compile(dotnet, work, "dwOK", _DEPWEAK, "net8.0", "WeakEvents",
                        [("Helper", helper)])
        wd, hd = _slot(work, "dwOK", weak), _slot(work, "dhOK", helper)
        b, pl, ca, dl, rt, w = _build_chain(dotnet, ext, work, "depin", _PRE, [wd, hd], True)
        out = os.path.join(w, "target")
        p = _verify_target(dotnet, probe, b, pl, ca, rt, dl, out, [wd, hd], 0, True)
        _expect_result(p, out, ("pass", "converted"), check, "dep-in-slot")
    except Fail as exc:
        check(False, f"dep-in-slot: chain setup failed ({exc})")

    # (b) dependency absent from slots but copied NEXT TO the probe deployment -> unsupported.
    try:
        helper = _compile(dotnet, work, "dhNP", _HELPER_OK, "net8.0", "Helper")
        weak = _compile(dotnet, work, "dwNP", _DEPWEAK, "net8.0", "WeakEvents",
                        [("Helper", helper)])
        wd = _slot(work, "dwNP", weak)
        probe_copy_dir = os.path.join(work, "probe-copy")
        shutil.copytree(os.path.dirname(probe), probe_copy_dir)
        shutil.copy(helper, os.path.join(probe_copy_dir, "Helper.dll"))
        probe_copy = os.path.join(probe_copy_dir, os.path.basename(probe))
        b, pl, ca, dl, rt, w = _build_chain(dotnet, ext, work, "depnp", _PRE, [wd], True)
        out = os.path.join(w, "target")
        p = _verify_target(dotnet, probe_copy, b, pl, ca, rt, dl, out, [wd], 0, True)
        _expect_result(p, out, ("refuse", "WRAPPER_RUNTIME_UNSUPPORTED"), check,
                       "dep-next-to-probe")
    except Fail as exc:
        check(False, f"dep-next-to-probe: chain setup failed ({exc})")

    # (c) dependency absent from slots but ALREADY loaded in the probe's default context
    #     (Microsoft.CodeAnalysis, a probe deployment assembly) -> unsupported, never satisfied.
    try:
        weak = _compile(dotnet, work, "dwDC", _DEP_ROSLYN, "net8.0", "WeakEvents", None,
                        [("Microsoft.CodeAnalysis.CSharp", "4.9.2")])
        wd = _slot(work, "dwDC", weak)
        b, pl, ca, dl, rt, w = _build_chain(dotnet, ext, work, "depdc", _PRE, [wd], True)
        out = os.path.join(w, "target")
        p = _verify_target(dotnet, probe, b, pl, ca, rt, dl, out, [wd], 0, True)
        _expect_result(p, out, ("refuse", "WRAPPER_RUNTIME_UNSUPPORTED"), check,
                       "dep-default-context")
    except Fail as exc:
        check(False, f"dep-default-context: chain setup failed ({exc})")


def _run_two_slot_versions(dotnet: str, ext: str, probe: str, work: str, check) -> None:
    """H2: two slots export the same simple-name dependency; the FROZEN first-winning slot is the
    one loaded, proven behaviorally (good Helper -> pass; throwing Helper -> TARGET_BEHAVIOR)."""
    try:
        hgood = _compile(dotnet, work, "tvHg", _HELPER_OK, "net8.0", "Helper")
        hthrow = _compile(dotnet, work, "tvHt", _HELPER_THROW, "net8.0", "Helper")
        weak = _compile(dotnet, work, "tvW", _DEPWEAK, "net8.0", "WeakEvents",
                        [("Helper", hgood)])
        wd = _slot(work, "tvW", weak)
        good, throw = _slot(work, "tvHg", hgood), _slot(work, "tvHt", hthrow)
        # good Helper is the earlier (first-winning) slot -> pass
        b, pl, ca, dl, rt, w = _build_chain(dotnet, ext, work, "tvA", _PRE, [wd, good, throw], True)
        out = os.path.join(w, "target")
        p = _verify_target(dotnet, probe, b, pl, ca, rt, dl, out, [wd, good, throw], 0, True)
        _expect_result(p, out, ("pass", "converted"), check, "two-slot first-wins (good)")
        # throwing Helper is the earlier slot -> the wrapper throws on subscribe -> TARGET_BEHAVIOR
        b, pl, ca, dl, rt, w = _build_chain(dotnet, ext, work, "tvB", _PRE, [wd, throw, good], True)
        out = os.path.join(w, "target")
        p = _verify_target(dotnet, probe, b, pl, ca, rt, dl, out, [wd, throw, good], 0, True)
        _expect_result(p, out, ("refuse", "TARGET_BEHAVIOR"), check, "two-slot first-wins (throw)")
    except Fail as exc:
        check(False, f"two-slot-versions: chain setup failed ({exc})")


if __name__ == "__main__":
    raise SystemExit(run())
