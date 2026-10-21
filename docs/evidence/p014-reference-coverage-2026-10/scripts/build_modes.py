# ruff: noqa: E501  (research script; long docstring/comment lines)
"""Build the per-project input lists for modes A, B and C (00-preregistration.md §2) and a reference manifest.

usage: python -I build_modes.py --research <direction-research root> --out <dir>
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re

DOTNET = r"C:\Program Files\dotnet"
TPA = os.path.join(DOTNET, "shared", "Microsoft.NETCore.App", "8.0.31")
GCACHE = os.path.join(os.environ["USERPROFILE"], ".nuget", "packages")
PROJECTS = [
    (
        "P1",
        "repos/sweep/Flow-Launcher__Flow.Launcher/Flow.Launcher/Flow.Launcher.csproj",
        "net9.0-windows10.0.19041.0",
    ),
    ("P2", "repos/sweep/git-ecosystem__git-credential-manager/src/Core/Core.csproj", "net10.0"),
    (
        "P3",
        "repos/sweep/nats-io__nats.net/src/NATS.Client.JetStream/NATS.Client.JetStream.csproj",
        "net8.0",
    ),
    (
        "P4",
        "evidence/pairs/BoBoBaSs84_BB84.IPTV__36/base/src/BB84.IPTV.M3U.Editor/"
        "BB84.IPTV.M3U.Editor.csproj",
        "net10.0",
    ),
    (
        "P5",
        "evidence/pairs/MERURUXD_FluentFlyout__3/base/FluentFlyoutWPF/FluentFlyout.csproj",
        "net10.0-windows10.0.22000.0",
    ),
]
SDK_USINGS = [
    "System",
    "System.Collections.Generic",
    "System.IO",
    "System.Linq",
    "System.Net.Http",
    "System.Threading",
    "System.Threading.Tasks",
]


def pack_version(tfm: str) -> tuple[str, bool]:
    """reference-pack version for a TFM, and whether it is exact."""
    if tfm.startswith("net8.0"):
        return "8.0.31", True
    if tfm.startswith("net10.0"):
        return "10.0.12", True
    return "10.0.12", False  # net9.0: no 9.0 pack on this host (TFM-APPROX)


def implicit_usings(csproj: str) -> bool:
    d, texts = os.path.dirname(csproj), []
    texts.append(open(csproj, encoding="utf-8", errors="replace").read())
    while True:
        p = os.path.join(d, "Directory.Build.props")
        if os.path.exists(p):
            texts.append(open(p, encoding="utf-8", errors="replace").read())
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return any(
        re.search(r"<ImplicitUsings>\s*(enable|true)\s*</ImplicitUsings>", t, re.I) for t in texts
    )


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    manifest = []
    for pid, rel, tfm in PROJECTS:
        csproj = os.path.join(a.research, rel)
        pdir = os.path.dirname(csproj)
        out = os.path.join(a.out, pid)
        os.makedirs(out, exist_ok=True)
        srcs = sorted(
            f
            for f in glob.glob(os.path.join(pdir, "**", "*.cs"), recursive=True)
            if not re.search(r"[\\/](bin|obj)[\\/]", os.path.relpath(f, pdir))
        )
        open(os.path.join(out, "sources.txt"), "w", encoding="utf-8").write("\n".join(srcs) + "\n")
        # A: the extractor process's TPA (net8.0.31 implementation) + project bin/ (first filename wins)
        refs_a = sorted(glob.glob(os.path.join(TPA, "*.dll")))
        names = {os.path.basename(p).lower() for p in refs_a}
        bin_dir = os.path.join(pdir, "bin")
        if os.path.isdir(bin_dir):
            for p in sorted(glob.glob(os.path.join(bin_dir, "**", "*.dll"), recursive=True)):
                if os.path.basename(p).lower() not in names:
                    refs_a.append(p)
                    names.add(os.path.basename(p).lower())
        # B: TFM reference packs + manifest-selected compile assets
        assets_path = os.path.join(pdir, "obj", "project.assets.json")
        if not os.path.exists(
            assets_path
        ):  # e.g. an out/obj/<Project>/ layout: match by projectPath
            repo_root = os.path.join(a.research, *rel.split("/")[:3])
            for cand in glob.glob(
                os.path.join(repo_root, "**", "project.assets.json"), recursive=True
            ):
                pp = json.load(open(cand, encoding="utf-8"))["project"]["restore"]["projectPath"]
                if os.path.normcase(os.path.basename(pp)) == os.path.normcase(
                    os.path.basename(csproj)
                ):
                    assets_path = cand
                    break
        assets = json.load(open(assets_path, encoding="utf-8"))
        ver, exact = pack_version(tfm)
        fw = assets["project"]["frameworks"]
        fkey = next(
            k for k in fw if tfm.startswith(k) or k.startswith(tfm.split("-")[0]) or k == tfm
        )
        fwrefs = sorted(fw[fkey].get("frameworkReferences", {}).keys())
        packs = ["Microsoft.NETCore.App.Ref"] + [
            {
                "Microsoft.NETCore.App": "Microsoft.NETCore.App.Ref",
                "Microsoft.AspNetCore.App": "Microsoft.AspNetCore.App.Ref",
                "Microsoft.WindowsDesktop.App": "Microsoft.WindowsDesktop.App.Ref",
                "Microsoft.WindowsDesktop.App.WPF": "Microsoft.WindowsDesktop.App.Ref",
                "Microsoft.WindowsDesktop.App.WindowsForms": "Microsoft.WindowsDesktop.App.Ref",
            }.get(f, f)
            for f in fwrefs
        ]
        refs_b, missing_packs, missing_pkgs, pkg_rows = [], [], [], []
        moniker = "net" + ver.split(".")[0] + ".0"
        for pk in dict.fromkeys(packs):
            if pk == "Microsoft.Windows.SDK.NET.Ref.Windows":
                # NuGet-delivered Windows projection: the package version matching the TFM's platform version
                plat = tfm.split("-windows")[1] if "-windows" in tfm else ""
                plat = ".".join(plat.split(".")[:3])
                cands = sorted(
                    glob.glob(os.path.join(GCACHE, "microsoft.windows.sdk.net.ref", plat + ".*"))
                )
                libs = (
                    sorted(glob.glob(os.path.join(cands[-1], "lib", "net*", "*.dll")))
                    if cands
                    else []
                )
                if libs:
                    refs_b += libs
                    pkg_rows += [
                        (
                            "Microsoft.Windows.SDK.NET.Ref/" + os.path.basename(cands[-1]),
                            os.path.relpath(p, cands[-1]),
                            sha(p),
                        )
                        for p in libs
                    ]
                else:
                    missing_packs.append(f"{pk} ({plat})")
                continue
            d = os.path.join(DOTNET, "packs", pk, ver, "ref", moniker)
            if os.path.isdir(d):
                refs_b += sorted(glob.glob(os.path.join(d, "*.dll")))
            else:
                missing_packs.append(f"{pk}/{ver}")
        tkey = next(
            k
            for k in assets["targets"]
            if "/" not in k and (k == tfm or k.startswith(fkey) or tfm.startswith(k.split("-")[0]))
        )
        # pre-registration §2: no package assembly replaces a framework assembly of the same name
        # (MSBuild's package/framework conflict resolution); such assets are skipped and counted
        fw_names = {os.path.basename(p).lower() for p in refs_b}
        fw_conflicts = []
        for lib, info in assets["targets"][tkey].items():
            if info.get("type") != "package":
                continue
            name, v = lib.split("/")
            root = os.path.join(GCACHE, name.lower(), v.lower())
            comp = [c for c in info.get("compile", {}) if not c.endswith("_._")]
            if not os.path.isdir(root):
                if comp:
                    missing_pkgs.append(lib)
                continue
            for c in comp:
                p = os.path.join(root, c)
                if os.path.basename(p).lower() in fw_names:
                    fw_conflicts.append(f"{lib}:{c}")
                    continue
                if os.path.exists(p):
                    refs_b.append(p)
                    pkg_rows.append((lib, c, sha(p)))
        # C: A + SDK default global usings when the project enables them
        iu = implicit_usings(csproj)
        cextra = os.path.join(out, "ImplicitUsings.g.cs")
        open(cextra, "w", encoding="utf-8").write(
            "".join(f"global using global::{u};\n" for u in SDK_USINGS)
            if iu
            else "// ImplicitUsings off\n"
        )
        for m, lst in (("A", refs_a), ("B", refs_b), ("C", refs_a)):
            open(os.path.join(out, f"refs_{m}.txt"), "w", encoding="utf-8").write(
                "\n".join(lst) + "\n"
            )
        with open(os.path.join(out, "manifest_B.tsv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("package\tcompile_asset\tsha256_16\n")
            for r in pkg_rows:
                f.write("\t".join(r) + "\n")
        manifest.append(
            {
                "id": pid,
                "project": rel,
                "tfm": tfm,
                "assets": os.path.relpath(assets_path, a.research),
                "assets_target": tkey,
                "pack_version": ver,
                "pack_exact": exact,
                "framework_references": fwrefs,
                "missing_packs": missing_packs,
                "missing_packages_with_compile_assets": missing_pkgs,
                "sources": len(srcs),
                "refs_A": len(refs_a),
                "refs_B": len(refs_b),
                "framework_conflicts_skipped": len(fw_conflicts),
                "bin_present": os.path.isdir(bin_dir),
                "implicit_usings": iu,
            }
        )
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8"), indent=1)
    for m in manifest:
        print(json.dumps(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
