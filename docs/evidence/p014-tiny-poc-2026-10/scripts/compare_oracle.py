"""P-014 Tiny PoC: compare the instrument's reference manifest with the SDK oracle (K3, K8a-c, K9).

The oracle is `dotnet msbuild <fixture> -t:FindReferenceAssembliesForReferences
-getItem:ReferencePathWithRefAssemblies` on my own synthetic fixtures, restored offline from
the global packages folder. Both sides are reduced to (normalised path, assembly version);
equal sets = PASS.

usage: python -I compare_oracle.py <oracle.json> <sidecar.json> <dotnet-root> <nuget-root>
"""

import json
import re
import sys


def norm(path: str, dotnet: str, nuget: str) -> str:
    p = path.replace("\\", "/")
    for root, tag in ((dotnet, "<dotnet>"), (nuget, "<nuget>")):
        r = root.replace("\\", "/").rstrip("/")
        if p.lower().startswith(r.lower()):
            p = tag + p[len(r) :]
    return p.lower()


def oracle_version(item: dict) -> str:
    # package references carry no AssemblyVersion metadata; their identity is in FusionName
    if item.get("AssemblyVersion"):
        return str(item["AssemblyVersion"])
    m = re.search(r"Version=([0-9.]+)", item.get("FusionName") or "")
    return m.group(1) if m else ""


def main() -> int:
    oracle_path, sidecar_path, dotnet, nuget = sys.argv[1:5]
    with open(oracle_path, encoding="utf-8-sig") as fh:
        oracle = json.load(fh)["Items"]["ReferencePathWithRefAssemblies"]
    with open(sidecar_path, encoding="utf-8") as fh:
        unit = json.load(fh)["units"][0]
    want = {(norm(i["FullPath"], dotnet, nuget), oracle_version(i)) for i in oracle}
    have = {(m["path"].lower(), m.get("assembly_version") or "") for m in unit["manifest"]}
    only_oracle = sorted(want - have)
    only_instrument = sorted(have - want)
    ok = not only_oracle and not only_instrument and not unit["tie_framework_assumed"]
    print(
        json.dumps(
            {
                "pass": ok,
                "oracle_refs": len(want),
                "instrument_refs": len(have),
                "only_oracle": only_oracle,
                "only_instrument": only_instrument,
                "conflicts": unit["conflicts"],
                "tie_framework_assumed": unit["tie_framework_assumed"],
                "unit_status": unit["unit_status"],
                "reasons": unit["reasons"],
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
