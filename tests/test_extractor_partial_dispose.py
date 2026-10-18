#!/usr/bin/env python3
"""Own.NET#410 - a field released in ANOTHER partial file of its class, at teardown, is no leak.

THE DEFECT

OWN001 [disposable field] looked for `_f.Dispose()` only inside the ONE class declaration that
declares the field, and `*.Designer.cs` files are never parsed (IsGenerated). A WinForms field
disposed in the designer `Dispose(bool)` (gitextensions RepoObjectsTree, FormAddToGitIgnore), or
a field declared in `Foo.ContextMenu.cs` and disposed in `Foo.cs` (FileStatusList, rabbitmq
Connection, garnet ClusterManager, honua FileBackedLicenseService), was reported never disposed.

WHAT THIS TEST PINS (each a separate PASS/KILL criterion of the fix)

  S   silent: the release in another partial file runs at this object's teardown - Dispose(),
      a helper Dispose() provably calls, a lambda wired to our own `Disposed`, a null check of
      the field, and the designer `if (disposing) { _f.Dispose(); }`.
  W   still OWN001: the release is not proven to run at teardown - an uncalled method, a flag
      guard, a lambda on ANOTHER object's `Disposed`, an unwired lambda, the finalizer branch
      (`!disposing`, else), a designer helper / lambda, a release-and-recreate on a recovery
      path (garnet resetHandler) - or it is not THIS field (another class, another instance,
      another field, a shadowing local in a partial or designer file, a designer file of another
      namespace).
  D   a designer file is evidence only: an undisposed field it declares produces no record.

Both with and without --flow-locals. REQUIRED VS SKIPPED: as tests/test_extractor_columns.py -
required when OWN_TIERB_REQUIRED=1, a clean, explained skip when dotnet is absent.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_extractor_partial_dispose.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")

_MAIN = """using System.ComponentModel;
using System.IO;

namespace Repro;

public partial class {cls} : Component
{{
    private readonly MemoryStream _f = new();
    private bool _enabled;
    public void Touch() {{ _f.WriteByte(1); _enabled = !_enabled; }}
}}
"""
_PART = "namespace {ns};\n\npartial class {cls}\n{{\n{body}\n}}\n"

_DISPOSING = ("    protected override void Dispose(bool disposing)\n    {{\n        {stmt}\n"
              "        base.Dispose(disposing);\n    }}")


def _disposing(stmt: str) -> str:
    return _DISPOSING.format(stmt=stmt)


# case -> (part file suffix, body, expect OWN001 on _f)
_CASES: dict[str, tuple[str, str, bool]] = {
    "P1Dispose": (".Part.cs", "    public void Dispose() => _f.Dispose();", False),
    "P2Uncalled": (".Part.cs", "    private void UnusedCleanup() => _f.Dispose();", True),
    "P3Flag": (".Part.cs", "    public void Dispose() { if (_enabled) _f.Dispose(); }", True),
    "P4Helper": (".Part.cs",
                 "    public void Dispose() => Cleanup();\n"
                 "    private void Cleanup() => _f.Dispose();", False),
    "P5OwnDisposed": (".Part.cs",
                      "    public {cls}() { Disposed += (s, e) => { _f.Dispose(); }; }", False),
    "P6NullCheck": (".Part.cs",
                    "    public void Dispose() { if (_f != null) _f.Dispose(); }", False),
    "P7OtherDisposed": (".Part.cs",
                        "    public {cls}(Component other)\n"
                        "        { other.Disposed += (s, e) => _f.Dispose(); }", True),
    "P8UnwiredLambda": (".Part.cs",
                        "    public void Dispose()\n"
                        "        { System.Action a = () => _f.Dispose(); }", True),
    "P9RecoveryRecreate": (".Part.cs",
                           "    public void Recover()\n    {\n        _f.Dispose();\n"
                           "        _f2 = new System.IO.MemoryStream();\n    }\n"
                           "    private System.IO.MemoryStream? _f2;", True),
    "D1Designer": (".Designer.cs", _disposing("if (disposing) { _f.Dispose(); }"), False),
    "D2DesignerUnused": (".Designer.cs", "    private void Unused() { _f.Dispose(); }", True),
    "D3DesignerFinalizer": (".Designer.cs", _disposing("if (!disposing) { _f.Dispose(); }"), True),
    "D4DesignerElse": (".Designer.cs",
                       _disposing("if (disposing) { } else { _f.Dispose(); }"), True),
    "D5DesignerFlag": (".Designer.cs", _disposing("if (_enabled) _f.Dispose();"), True),
    "D6DesignerLambda": (".Designer.cs",
                         _disposing("System.Action a = () => _f.Dispose();"), True),
    "C1OtherInstance": (".Part.cs",
                        "    public static void Kill({cls} other) => other._f.Dispose();", True),
    "C6PartialShadowLocal": (".Part.cs",
                             "    public void Dispose()\n"
                             "        { var _f = new System.IO.MemoryStream(); _f.Dispose(); }",
                             True),
    "C2ShadowLocal": (".Designer.cs",
                      _disposing("var _f = new System.IO.MemoryStream(); "
                                 "if (disposing) _f.Dispose();"), True),
}

_UNRELATED = """using System.IO;

namespace Repro;

public class C3Unrelated
{
    private readonly MemoryStream _f = new();
    public void Dispose() => _f.Dispose();
}
"""

# extra sources: file name -> text
_EXTRA = {
    # C3: a same-named field of ANOTHER class, disposed at that class's own teardown
    "C3OtherClass.cs": _MAIN.format(cls="C3OtherClass"),
    "C3Unrelated.cs": _UNRELATED,
    # C4: the designer releases ANOTHER field
    "C4WrongField.cs": _MAIN.format(cls="C4WrongField"),
    "C4WrongField.Designer.cs": _PART.format(
        ns="Repro", cls="C4WrongField",
        body="    private readonly System.IO.MemoryStream _other = new();\n"
             + _disposing("if (disposing) _other.Dispose();")),
    # C5: a designer file of ANOTHER namespace
    "C5OtherNs.cs": _MAIN.format(cls="C5OtherNs"),
    "C5OtherNs.Designer.cs": _PART.format(
        ns="Elsewhere", cls="C5OtherNs",
        body=_disposing("if (disposing) _f.Dispose();").replace("override ", "")),
    # D: a designer-declared undisposed field must not become a finding
    "D7DesignerOnly.cs": _MAIN.format(cls="D7DesignerOnly"),
    "D7DesignerOnly.Designer.cs": _PART.format(
        ns="Repro", cls="D7DesignerOnly",
        body="    private readonly System.IO.MemoryStream _designerLeak = new();\n"
             "    public void Touch2() => _designerLeak.WriteByte(1);"),
}
_EXPECT_EXTRA = {"C3OtherClass": True, "C4WrongField": True, "C5OtherNs": True}

_FIELD = re.compile(
    r"IDisposable field '(\w+)' \(type '[^']*'\) is never disposed .{0,3}its owner '(\w+)'")


def _write(src: str) -> None:
    for cls, (suffix, body, _) in _CASES.items():
        with open(os.path.join(src, cls + ".cs"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_MAIN.format(cls=cls))
        with open(os.path.join(src, cls + suffix), "w", encoding="utf-8", newline="\n") as f:
            f.write(_PART.format(ns="Repro", cls=cls, body=body.replace("{cls}", cls)))
    for name, text in _EXTRA.items():
        with open(os.path.join(src, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def _run(src: str, work: str, flow: bool, fails: list[str]) -> None:
    tag = "--flow-locals" if flow else "plain"
    facts = os.path.join(work, f"facts-{tag}.json")
    args = ["dotnet", "run", "--project", _EXT, "--", src, "-o", facts]
    if flow:
        args.append("--flow-locals")
    ext = subprocess.run(args, cwd=_REPO, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if ext.returncode != 0 or not os.path.exists(facts):
        fails.append(f"[{tag}] extractor rc={ext.returncode}")
        return
    with open(facts, encoding="utf-8") as f:
        doc = json.load(f)
    for comp in doc.get("components", []):
        from_designer = str(comp.get("file", "")).endswith(".Designer.cs")
        for rec in comp.get("subscriptions", []):
            if rec.get("event") == "_designerLeak" or from_designer:
                fails.append(f"[{tag}] D a designer file became a source of facts: "
                             f"{comp.get('name')}")
    env = dict(os.environ, PYTHONPATH=_REPO)
    core = subprocess.run([sys.executable, "-m", "ownlang", "ownir", facts,
                           "--severity", "warning"],
                          cwd=_REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    warned = {owner for fld, owner in _FIELD.findall(core.stdout) if fld == "_f"}
    expect = {cls: e for cls, (_, _, e) in _CASES.items()} | _EXPECT_EXTRA
    for cls, e in expect.items():
        if (cls in warned) != e:
            kind = "W lost OWN001 (unproven release credited)" if e else "S still OWN001"
            fails.append(f"[{tag}] {cls}: {kind}")


def run() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if not shutil.which("dotnet"):
        if os.environ.get("OWN_TIERB_REQUIRED") == "1":
            print("extractor partial dispose: FAIL - dotnet is REQUIRED here "
                  "(OWN_TIERB_REQUIRED=1) and is not on PATH")
            return 1
        print("extractor partial dispose: SKIP - dotnet not on PATH")
        return 0
    fails: list[str] = []
    work = tempfile.mkdtemp(prefix="own410-")
    try:
        src = os.path.join(work, "src")
        os.makedirs(src)
        _write(src)
        for flow in (True, False):
            _run(src, work, flow, fails)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        print("extractor partial dispose: FAIL")
        for f in fails:
            print("  -", f)
        return 1
    n = len(_CASES) + len(_EXPECT_EXTRA)
    print(f"extractor partial dispose: OK ({n} cases + designer-evidence check, "
          "plain and --flow-locals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
