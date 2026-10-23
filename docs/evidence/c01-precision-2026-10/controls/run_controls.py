"""Score the C01-PRECISION-1 control pairs on the REAL extractor + Python core against the
`// EXPECT before=<R> after=<R>` markers fixed in each file before the patch.

Usage (repo root, dotnet + python on PATH, extractor already built):
    python docs/evidence/c01-precision-2026-10/controls/run_controls.py <before|after> <out.json>

Per control file: extractor over [Common.cs, file] -> `python -m ownlang ownir --format sarif`,
then every result located in that file. A result on a marked line must equal the marker for the
phase; a result on an unmarked line, or a marked line without its result, is a mismatch.
`none` = no result on that line.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

phase, out_path = sys.argv[1], sys.argv[2]
assert phase in ("before", "after")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
EXTRACTOR = os.path.join(REPO, "frontend", "roslyn", "OwnSharp.Extractor")
MARK = re.compile(r"//\s*EXPECT\s+before=(\S+)\s+after=(\S+)")


def results_in(sarif: dict, name: str) -> list[dict]:
    out = []
    for r in sarif["runs"][0]["results"]:
        uri = r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        if os.path.basename(uri) == name:
            out.append(r)
    return out


def run_case(f: str) -> dict:
    path = os.path.join(HERE, f)
    expect = {}
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        m = MARK.search(line)
        if m:
            expect[i] = m.group(1 if phase == "before" else 2)
    with tempfile.TemporaryDirectory() as td:
        facts = os.path.join(td, "facts.json")
        ex = subprocess.run(["dotnet", "run", "--project", EXTRACTOR, "--no-build", "--",
                             os.path.join(HERE, "Common.cs"), path, "-o", facts],
                            capture_output=True, text=True, cwd=REPO)
        if ex.returncode != 0:
            return {"file": f, "error": f"extractor rc={ex.returncode}: {ex.stderr[-400:]}",
                    "rows": [{"ok": False}]}
        core = subprocess.run(
            [sys.executable, "-m", "ownlang", "ownir", facts, "--format", "sarif"],
            capture_output=True, text=True, cwd=REPO)
        mine = results_in(json.loads(core.stdout), f)
    got: dict[int, list[str]] = {}
    for r in mine:
        got.setdefault(r["locations"][0]["physicalLocation"]["region"]["startLine"], []).append(
            r["ruleId"])
    rows = []
    for line in sorted(set(expect) | set(got)):
        exp = expect.get(line, "UNMARKED")
        g = sorted(got.get(line, [])) or ["none"]
        rows.append({"line": line, "expected": exp, "got": g, "ok": g == [exp]})
    return {"file": f, "rows": rows, "messages": [r["message"]["text"] for r in mine]}


files = sorted(f for f in os.listdir(HERE) if re.match(r"[FN]\d", f) and f.endswith(".cs"))
report: dict = {"phase": phase, "cases": [], "mismatches": 0}
for f in files:
    case = run_case(f)
    report["cases"].append(case)
    bad = sum(1 for r in case["rows"] if not r["ok"])
    report["mismatches"] += bad
    detail = "; ".join(f"L{r['line']} exp={r['expected']} got={','.join(r['got'])}"
                       for r in case["rows"] if "line" in r) or case.get("error", "")
    print(f"{'MISMATCH' if bad else 'ok':8} {f:44} {detail}")
json.dump(report, open(out_path, "w"), indent=1)
print(f"controls[{phase}]: {len(files)} files, {report['mismatches']} mismatch(es)")
sys.exit(1 if report["mismatches"] else 0)
