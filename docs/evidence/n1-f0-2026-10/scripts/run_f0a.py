"""N1-F0 part A: rebuild the #417 reproductions under more CA2000 settings and collect every
diagnostic inside each buggy method (not only on the ACQ line).

usage: python -I run_f0a.py --repro <#417 repro dir> --work <scratch> --nuget <packages> --out <dir>
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
ALL = "dotnet_code_quality.CA2000.dispose_analysis_kind = AllPaths"
IPA = "dotnet_code_quality.CA2000.interprocedural_analysis_kind = "
CTOR = "dotnet_code_quality.CA2000.dispose_ownership_transfer_at_constructor = true"
CALL = "dotnet_code_quality.CA2000.dispose_ownership_transfer_at_method_call = true"
CONFIGS = {
    "A1": [ALL, IPA + "None"],
    "A2": [ALL, IPA + "NonContextSensitive"],
    "A3": [ALL, IPA + "ContextSensitive"],
    "A4": [ALL, IPA + "None", CTOR, CALL],
    "A5": [ALL, IPA + "NonContextSensitive", CTOR, CALL],
    "A6": [ALL, IPA + "ContextSensitive", CTOR, CALL],
    "K1": [],
    "K2": [ALL],
    "K3": [ALL, CTOR],
    "K4": [ALL, CALL],
    "K5": ["dotnet_code_quality.CA2000.dispose_analysis_kind = AllPathsOnlyNotDisposed"],
}
DISPOSAL_RULES = {
    "CA2000",
    "CA1001",
    "CA2213",
    "CA2215",
    "CA2216",
    "S2930",
    "S2931",
    "S3966",
    "S4487",
} | {f"IDISP{n:03d}" for n in range(1, 27)}
CLASS = re.compile(r"^\s*public (?:sealed |static )?class (\w+)")
METHOD = re.compile(r"^\s*public async ")


def buggy_method_spans(repro: str) -> dict[tuple[str, str], tuple[int, int]]:
    """(file, class) -> (first, last) line of the first `public async` method of a *Buggy class."""
    spans = {}
    for f in sorted(os.listdir(repro)):
        if not f.endswith(".cs"):
            continue
        lines = open(os.path.join(repro, f), encoding="utf-8").read().splitlines()
        cls = None
        i = 0
        while i < len(lines):
            if m := CLASS.match(lines[i]):
                cls = m.group(1)
            if cls and cls.endswith("Buggy") and METHOD.match(lines[i]) and (f, cls) not in spans:
                depth, j, opened = 0, i, False
                while j < len(lines):
                    depth += lines[j].count("{") - lines[j].count("}")
                    opened = opened or "{" in lines[j]
                    if opened and depth == 0:
                        break
                    j += 1
                spans[(f, cls)] = (i + 1, j + 1)
                i = j
            i += 1
    return spans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--nuget", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spans = buggy_method_spans(a.repro)
    os.makedirs(a.out, exist_ok=True)
    stubs = os.path.join(os.path.dirname(os.path.abspath(a.repro)), "stubs")
    shutil.rmtree(os.path.join(a.work, "stubs"), ignore_errors=True)
    shutil.copytree(stubs, os.path.join(a.work, "stubs"))
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
            f"-p:N1ErrorLog={sarif}",
            "--configfile",
            os.path.join(a.work, "nuget.config"),
        ]
        env = dict(os.environ, DOTNET_CLI_UI_LANGUAGE="en")
        p = subprocess.run(
            cmd,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        n_err = 0
        for run in json.load(open(sarif, encoding="utf-8")).get("runs", []):
            for r in run.get("results", []):
                n_err += r.get("level") == "error"
                msg = r.get("message", "")
                text = msg.get("text", "") if isinstance(msg, dict) else str(msg)
                rule = r.get("ruleId", "")
                if rule not in DISPOSAL_RULES and "dispos" not in text.lower():
                    continue
                for loc in r.get("locations", []):
                    pl = loc.get("physicalLocation") or loc.get("resultFile") or {}
                    art = pl.get("artifactLocation", {}).get("uri", "") or pl.get("uri", "")
                    uri, line = os.path.basename(art), pl.get("region", {}).get("startLine", 0)
                    for (f, cls), (lo, hi) in spans.items():
                        if f == uri and lo <= line <= hi:
                            rows.append((k, cls, uri, line, rule, text.replace("\t", " ")))
        rows.append((k, "_build", f"rc={p.returncode}", 0, f"errors={n_err}", ""))
    with open(
        os.path.join(a.out, "f0a_method_diagnostics.tsv"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write("config\tclass\tfile\tline\trule\tmessage\n")
        for r in sorted(set(rows)):
            f.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "f0a_spans.tsv"), "w", encoding="utf-8", newline="\n") as f:
        for (fn, cls), (lo, hi) in sorted(spans.items()):
            f.write(f"{fn}\t{cls}\t{lo}\t{hi}\n")
    print(open(os.path.join(a.out, "f0a_method_diagnostics.tsv"), encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
