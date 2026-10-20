"""N1 competitor gate: build the reproductions under K1-K5 and collect every diagnostic on an
acquisition line (`// ACQ:<Id>`), per class (Buggy / Fixed / Control).

usage: python -I run_gate.py --repro <dir> --work <scratch> --nuget <packages> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess

BASE = [
    "root = true",
    "",
    "[*.cs]",
    "dotnet_analyzer_diagnostic.severity = warning",
    "dotnet_diagnostic.CA2000.severity = warning",
]
CONFIGS = {
    "K1": [],
    "K2": ["dotnet_code_quality.CA2000.dispose_analysis_kind = AllPaths"],
    "K3": [
        "dotnet_code_quality.CA2000.dispose_analysis_kind = AllPaths",
        "dotnet_code_quality.CA2000.dispose_ownership_transfer_at_constructor = true",
    ],
    "K4": [
        "dotnet_code_quality.CA2000.dispose_analysis_kind = AllPaths",
        "dotnet_code_quality.CA2000.dispose_ownership_transfer_at_method_call = true",
    ],
    "K5": ["dotnet_code_quality.CA2000.dispose_analysis_kind = AllPathsOnlyNotDisposed"],
}
ACQ = re.compile(r"//\s*ACQ:([\w-]+)")
CLASS = re.compile(r"^\s*public (?:sealed |static )?class (\w+)")


def acquisition_lines(repro: str) -> dict[tuple[str, int], tuple[str, str]]:
    """(file, line) -> (marker id, enclosing class)."""
    res = {}
    for f in sorted(os.listdir(repro)):
        if not f.endswith(".cs"):
            continue
        cls = "?"
        for i, line in enumerate(open(os.path.join(repro, f), encoding="utf-8"), 1):
            if m := CLASS.match(line):
                cls = m.group(1)
            if m := ACQ.search(line):
                res[(f, i)] = (m.group(1), cls)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--nuget", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    acq = acquisition_lines(a.repro)
    os.makedirs(a.out, exist_ok=True)
    rows = []
    for k, extra in CONFIGS.items():
        work = os.path.join(a.work, k)
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(a.repro, work)
        with open(os.path.join(work, ".editorconfig"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(BASE + extra) + "\n")
        sarif = os.path.join(work, "out.sarif")
        cmd = [
            "dotnet",
            "build",
            "-c",
            "Release",
            "-nologo",
            "-v",
            "q",
            f"-p:NuGetRoot={a.nuget}",
            f"-p:ErrorLog={sarif},version=2.1",
            "--configfile",
            os.path.join(a.work, "nuget.config"),
        ]
        p = subprocess.run(
            cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        log = json.load(open(sarif, encoding="utf-8"))
        n_err, n_all = 0, 0
        for run in log.get("runs", []):
            for r in run.get("results", []):
                n_all += 1
                if r.get("level") == "error":
                    n_err += 1
                for loc in r.get("locations", []):
                    pl = loc.get("physicalLocation", {})
                    uri = os.path.basename(pl.get("artifactLocation", {}).get("uri", ""))
                    line = pl.get("region", {}).get("startLine", 0)
                    if (uri, line) in acq:
                        mid, cls = acq[(uri, line)]
                        msg = r.get("message", {})
                        text = msg.get("text", "") if isinstance(msg, dict) else str(msg)
                        rows.append(
                            (k, mid, cls, uri, line, r.get("ruleId", ""), text.replace("\t", " "))
                        )
        rows.append(
            (k, "_build", f"rc={p.returncode}", "", n_err, f"errors={n_err}", f"results={n_all}")
        )
    with open(os.path.join(a.out, "acq_diagnostics.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("config\tid\tclass\tfile\tline\trule\tmessage\n")
        for r in sorted(set(rows)):
            f.write("\t".join(map(str, r)) + "\n")
    print(open(os.path.join(a.out, "acq_diagnostics.tsv"), encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
