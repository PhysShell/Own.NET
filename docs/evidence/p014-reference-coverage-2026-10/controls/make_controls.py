# ruff: noqa: E501, RUF005  (control sources are inline C# one-liners)
"""Build the synthetic controls K1-K7 (00-preregistration.md §4) into <out>/K<n>/ as
{sources/, refs_A.txt, refs_B.txt, refs_C.txt}. Library DLLs are emitted by the instrument (`emit`).

usage: python -I make_controls.py --tool <p014bind.dll> --tpa <NETCore.App impl dir> --refpack <ref dir> --out <dir>
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess

LIB_V1 = "namespace Lib { public class Api { public static int V1Only() => 1; public event System.EventHandler? Changed; public int Count; } }"
LIB_V2 = "namespace Lib { public class Api { public static int V2Only() => 2; public event System.EventHandler? Changed; public int Count; } }"
PKG_NET8 = (
    'namespace Pkg { public static class Tfm { public static string Net8Only() => "net8"; } }'
)
PKG_NS20 = (
    'namespace Pkg { public static class Tfm { public static string Ns20Only() => "ns20"; } }'
)

SOURCES = {
    "K1": {
        "a.cs": "using System.Collections.Generic; class K1 { int M() { var l = new List<int>(); l.Add(1); return l.Count; } }"
    },
    "K2": {"a.cs": "class K2 { int M() => Lib.Api.V2Only(); }"},
    "K3": {"a.cs": "class K3 { string M() => Pkg.Tfm.Net8Only(); }"},
    "K4": {
        "p1/a.cs": "namespace Dup { public class T { public void One() {} } }",
        "p2/b.cs": "namespace Dup { public class T { public void Two() {} } }",
        "use.cs": "class K4 { void M() { new Dup.T().One(); } }",
    },
    "K5": {"a.cs": "class K5 { void M(Lib.Api a) { a.Changed += (s, e) => { }; a.Count += 1; } }"},
    "K6": {"a.cs": "class K6 { void M() { Missing.Thing.Do(); var x = new Missing.Thing(); } }"},
    "K7": {
        "a.cs": "class K7 { void M() {\n#if NET8_0\n System.Console.WriteLine(1);\n#else\n NotDefinedWithoutDefines();\n#endif\n} }"
    },
}


def emit(tool: str, refpack: str, name: str, src: str, out_dll: str, version: str) -> None:
    os.makedirs(os.path.dirname(out_dll), exist_ok=True)
    srcf = out_dll + ".src.cs"
    open(srcf, "w", encoding="utf-8").write(src)
    subprocess.run(["dotnet", tool, "emit", name, version, srcf, out_dll, refpack], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--tpa", required=True)
    ap.add_argument("--refpack", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tpa = sorted(glob.glob(os.path.join(a.tpa, "*.dll")))
    rp = sorted(glob.glob(os.path.join(a.refpack, "*.dll")))
    libs = os.path.join(a.out, "_libs")
    emit(a.tool, a.refpack, "Lib", LIB_V1, os.path.join(libs, "v1", "Lib.dll"), "1.0.0.0")
    emit(a.tool, a.refpack, "Lib", LIB_V2, os.path.join(libs, "v2", "Lib.dll"), "2.0.0.0")
    emit(
        a.tool,
        a.refpack,
        "Pkg",
        PKG_NET8,
        os.path.join(libs, "pkg", "lib", "net8.0", "Pkg.dll"),
        "1.0.0.0",
    )
    emit(
        a.tool,
        a.refpack,
        "Pkg",
        PKG_NS20,
        os.path.join(libs, "pkg", "lib", "netstandard2.0", "Pkg.dll"),
        "1.0.0.0",
    )
    v1, v2 = os.path.join(libs, "v1", "Lib.dll"), os.path.join(libs, "v2", "Lib.dll")
    p8 = os.path.join(libs, "pkg", "lib", "net8.0", "Pkg.dll")
    p20 = os.path.join(libs, "pkg", "lib", "netstandard2.0", "Pkg.dll")
    # mode A mimics the extractor: TPA + recursive first-filename-wins over the extra folders (ordinal sort);
    # mode B is the manifest-selected set: reference pack + exactly the assets the manifest names.
    refs = {
        "K1": (tpa, rp),
        "K2": (
            tpa + [v1],
            rp + [v2],
        ),  # ordinal sort puts v1/ before v2/: A gets v1; manifest names v2
        "K3": (tpa + [p8 if p8 < p20 else p20], rp + [p8]),
        "K4": (tpa, rp),
        "K5": (tpa + [v2], rp + [v2]),
        "K6": (tpa, rp),
        "K7": (tpa, rp),
    }
    for k, files in SOURCES.items():
        d = os.path.join(a.out, k)
        for rel, text in files.items():
            p = os.path.join(d, "sources", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(text)
        ra, rb = refs[k]
        for mode, lst in (("A", ra), ("B", rb), ("C", ra)):
            open(os.path.join(d, f"refs_{mode}.txt"), "w", encoding="utf-8").write(
                "\n".join(lst) + "\n"
            )
        open(os.path.join(d, "sources.txt"), "w", encoding="utf-8").write(
            "\n".join(sorted(glob.glob(os.path.join(d, "sources", "**", "*.cs"), recursive=True)))
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
