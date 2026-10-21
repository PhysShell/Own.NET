"""P-014 bounded design, falsifier F-D1a (read-only, research only).

For one project.assets.json target, list package compile assets whose file name collides with a
framework reference-pack DLL, and name the winner under the dotnet/sdk conflict order
(package overrides -> higher AssemblyVersion -> ...). Reads the assets, the local packs'
FrameworkList.xml / PackageOverrides.txt and the cached package DLLs' metadata; builds nothing.

usage: python -I d1_conflicts.py <assets> <tfm> <pack-version> <Pack1,Pack2,...>
"""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

NUGET = os.path.expanduser("~/.nuget/packages")
PACKS = r"C:\Program Files\dotnet\packs"
BAD = ("MISSING", "ERR")


def pack_info(name: str, ver: str) -> tuple[dict[str, str], dict[str, str]]:
    data = os.path.join(PACKS, name, ver, "data")
    framework: dict[str, str] = {}
    flist = os.path.join(data, "FrameworkList.xml")
    if os.path.exists(flist):
        for f in ET.parse(flist).getroot():
            if f.get("Type", "Managed") == "Managed" and f.get("AssemblyName"):
                framework[f.get("AssemblyName", "").lower()] = f.get("AssemblyVersion", "")
    overrides: dict[str, str] = {}
    po = os.path.join(data, "PackageOverrides.txt")
    if os.path.exists(po):
        with open(po) as fh:
            for line in fh:
                if "|" in line:
                    n, v = line.strip().split("|")
                    overrides[n.lower()] = v
    return framework, overrides


def vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def assembly_versions(paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    ps = (
        "foreach($p in $input){ try{ $n=[Reflection.AssemblyName]::GetAssemblyName($p);"
        ' "$p|$($n.Version)" }catch{ "$p|ERR" } }'
    )
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", ps],
        input="\n".join(paths), capture_output=True, text=True, check=False,
    ).stdout
    return dict(line.rsplit("|", 1) for line in out.splitlines() if "|" in line)


def winner(pkg_ver: str, pkg_av: str, fw_av: str, override: str | None) -> str:
    if override is not None and vt(pkg_ver) <= vt(override):
        return "framework"
    if pkg_av in BAD:
        return "?"
    return "package" if vt(pkg_av) > vt(fw_av) else "framework(tie/lower)"


def main() -> None:
    assets, tfm, pack_ver, packs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    with open(assets, encoding="utf-8") as fh:
        doc = json.load(fh)
    framework: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for p in packs.split(","):
        a, b = pack_info(p, pack_ver)
        framework.update(a)
        overrides.update(b)
    rows = []
    for key, entry in doc["targets"][tfm].items():
        if entry.get("type") != "package":
            continue
        pid, pver = key.split("/")
        for c in entry.get("compile") or {}:
            name = os.path.basename(c)
            if name == "_._" or name[:-4].lower() not in framework:
                continue
            path = os.path.join(NUGET, pid.lower(), pver.lower(), c)
            fw_av = framework[name[:-4].lower()]
            rows.append((pid, pver, name, fw_av, overrides.get(pid.lower()), path))
    av = assembly_versions([r[5] for r in rows if os.path.exists(r[5])])
    for pid, pver, name, fw_av, ovr, path in rows:
        pkg_av = av.get(path, "MISSING")
        print(f"{pid}/{pver}\t{name}\tpkgAV={pkg_av}\tfwAV={fw_av}\toverride={ovr}"
              f"\t-> {winner(pver, pkg_av, fw_av, ovr)}")


if __name__ == "__main__":
    main()
