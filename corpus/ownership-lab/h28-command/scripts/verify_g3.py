#!/usr/bin/env python3
"""G3 gate: production C# extractor -> OwnIR -> summaries -> production-core verdict.

Requires the .NET 8 SDK and a successful restore of OwnSharp.Extractor. This is the
end-to-end check that the manual .own reduction cannot provide. It writes the source
facts, solved summaries, SARIF diagnostics and command log into ../evidence/.

Expected OWN001 acquisition anchors (line numbers are derived from the named methods,
not duplicated as magic constants):
  B: command only; C: command only; E: command + reader; F: command;
  H: command; I: command. A, D and G: clean.

Exit non-zero on any mismatch. A missing SDK/restore is a SKIP in run.sh, and the
strict runtime-required/all-required gates convert that SKIP into a failing status.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / "fx" / "CommandDispose.cs"
EXTRACTOR = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor"
DLL = EXTRACTOR / "bin" / "Release" / "net8.0" / "ownsharp-extract.dll"
EVIDENCE = HERE / "evidence"
FACTS = EVIDENCE / "g3-CommandDispose.facts.json"
SUMMARIES = EVIDENCE / "g3-CommandDispose.summaries.json"
SARIF = EVIDENCE / "g3-CommandDispose.sarif.json"
LOG = EVIDENCE / "g3-CommandDispose.log"


def run(label: str, argv: list[str], *,
        expected: set[int] | None = None) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(argv)}\n")
        f.write(f"# exit={p.returncode}\n")
        if p.stdout:
            f.write(p.stdout)
            if not p.stdout.endswith("\n"):
                f.write("\n")
        if p.stderr:
            f.write("# stderr\n" + p.stderr)
            if not p.stderr.endswith("\n"):
                f.write("\n")
    if expected is not None and p.returncode not in expected:
        raise RuntimeError(f"{label}: exit {p.returncode}, expected {sorted(expected)}; "
                           f"stderr tail: {p.stderr[-1200:]}")
    return p


def source_anchor(method: str, fragment: str) -> int:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if f" {method}(" in line)
    except StopIteration as e:
        raise RuntimeError(f"fixture method not found: {method}") from e
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].lstrip().startswith("public static ")), len(lines))
    for i in range(start, end):
        if fragment in lines[i]:
            return i + 1
    raise RuntimeError(f"anchor {fragment!r} not found in {method}")


def diagnostics(doc: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for run_doc in doc.get("runs", []):
        for finding in run_doc.get("results", []):
            locations = finding.get("locations", [])
            if not locations:
                continue
            physical = locations[0].get("physicalLocation", {})
            line = physical.get("region", {}).get("startLine")
            if isinstance(line, int):
                result.add((str(finding.get("ruleId", "")), line))
    return result


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    LOG.write_text("# G3: current production Roslyn extractor -> OwnIR summaries -> core\n",
                   encoding="utf-8")
    run("build extractor", ["dotnet", "build", str(EXTRACTOR), "-c", "Release",
                            "--no-restore", "--nologo", "-v", "q"], expected={0})
    if not DLL.exists():
        raise RuntimeError(f"extractor DLL missing after successful build: {DLL}")
    run("extract C# fixture", ["dotnet", str(DLL), str(SOURCE), "--flow-locals",
                               "-o", str(FACTS)], expected={0})
    if not FACTS.exists():
        raise RuntimeError("extractor exited successfully but did not write its OwnIR facts")
    summaries = run("solve summaries", [sys.executable, "-m", "ownlang", "summaries",
                                        str(FACTS)], expected={0})
    SUMMARIES.write_text(summaries.stdout, encoding="utf-8")

    # OwnIR has a non-zero exit when it emits active OWN001 findings. Exit 0 or 1 are
    # both structurally valid here; SARIF parsing plus exact finding anchors is the verdict.
    core = run("check OwnIR", [sys.executable, "-m", "ownlang", "ownir", str(FACTS),
                               "--format", "sarif", "--verbosity", "verbose"],
               expected={0, 1})
    try:
        sarif_doc = json.loads(core.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"core stdout is not SARIF JSON: {core.stdout[:500]!r}") from e
    SARIF.write_text(json.dumps(sarif_doc, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")

    expected: set[tuple[str, int]] = set()
    for method in ("B_load_neither_disposed", "C_reader_disposed_command_not",
                   "F_reader_closed_command_not", "H_prepared_command_not_disposed",
                   "I_table_is_dispose_optional"):
        expected.add(("OWN001", source_anchor(method, "var command = connection.CreateCommand();")))
    for fragment in ("var command = connection.CreateCommand();",
                     "var reader = command.ExecuteReader();"):
        expected.add(("OWN001", source_anchor("E_no_load_both_leak", fragment)))

    actual = diagnostics(sarif_doc)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        print("FAIL G3: extracted C# verdict differs from the source-reading prediction.")
        print(f"  expected OWN001 anchors: {sorted(expected)}")
        print(f"  actual diagnostic anchors: {sorted(actual)}")
        print(f"  missing: {missing}; extra: {extra}")
        return 1

    print("PASS G3: production C# -> OwnIR -> summaries -> core matches the fixture contract.")
    print(f"  facts   : {FACTS.relative_to(ROOT)}")
    print(f"  summaries: {SUMMARIES.relative_to(ROOT)}")
    print(f"  SARIF   : {SARIF.relative_to(ROOT)}")
    print(f"  findings: {sorted(actual)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as e:
        print(f"FAIL G3: {e}", file=sys.stderr)
        sys.exit(1)
