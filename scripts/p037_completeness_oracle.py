#!/usr/bin/env python3
"""P-037 A2.2-4: run the completeness oracle and hold it to the frozen expectations.

The oracle (frontend/roslyn/OwnSharp.Oracle) reads the extractor's facts.json
and the same C# inputs and answers, per candidate occurrence at a call-related
site, "captured by an actual guarded fact XOR excluded by exactly one frozen
named exclusion" (docs/notes/p037-formal-kernel.md §10.6.1). This driver runs
the extractor and the oracle over

  * every shape of corpus/p037-shapes (one compilation each),
  * the relevance probe corpus/p037-relevance/probe/case.cs,
  * the repository's own samples frontend/roslyn/samples (one compilation),
  * the generated hostile census corpus/p037-hostile/cases (one compilation),

and checks three things by name:

  1. RED is exactly what the findings ledger expects. An input that is not in
     corpus/p037-relevance/oracle_findings.json must be RED-free; an input that
     is must raise exactly the RED kinds and counts pinned there, each tied to
     a classified finding (§10.1). Nothing is "known flaky": an unexpected RED
     fails, and so does an expected RED that stops appearing (a finding that
     silently closed is a treatment nobody measured).
  2. Every relevance-probe row reads as its frozen class says: captured for
     direct / transparent / may-value / call-like, excluded by exactly its named
     exclusion for indirect. `record` writes the observed reading into the
     probe's `a2_2_4_oracle` column; `check` demands the live reading equals it.
  3. Every hostile case's designed classification (corpus/p037-hostile/
     expected.json) is what the oracle observes: verdict, exclusion name, site
     kind, declared ordinal, representation, nesting, enclosing nested calls,
     and the carrier production delivered the record in.

Both projects are built once (`dotnet build`) and the DLLs are invoked directly,
so the ~180 runs stay a few minutes. Needs dotnet on PATH or DOTNET_ROOT.

Usage:
  p037_completeness_oracle.py check  [--only NAME,...] [--keep DIR]
  p037_completeness_oracle.py record [--only NAME,...]   # the probe column only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SHAPES = ROOT / "corpus" / "p037-shapes"
PROBE = ROOT / "corpus" / "p037-relevance" / "probe" / "case.cs"
PROBE_EXPECTED = ROOT / "corpus" / "p037-relevance" / "probe" / "expected.json"
FINDINGS = ROOT / "corpus" / "p037-relevance" / "oracle_findings.json"
SAMPLES = ROOT / "frontend" / "roslyn" / "samples"
HOSTILE = ROOT / "corpus" / "p037-hostile"
EXTRACTOR = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor"
ORACLE = ROOT / "frontend" / "roslyn" / "OwnSharp.Oracle"
ORACLE_SCHEMA = "p037-completeness-oracle/1"
PROBE_COLUMN = "a2_2_4_oracle"
RELEVANT_CLASSES = {"direct", "transparent", "may_value", "call_like"}

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def build(project: Path, dll: str) -> Path:
    cmd = ["dotnet", "build", str(project / f"{project.name}.csproj"), "-c", "Debug",
           "--nologo", "-v", "q"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"dotnet build {project.name} failed:\n"
                           f"{proc.stdout[-1500:]}\n{proc.stderr[-500:]}")
    out = project / "bin" / "Debug" / "net8.0" / dll
    if not out.exists():
        raise RuntimeError(f"built {project.name} but {out} is missing")
    return out


def run_extractor(dll: Path, inputs: list[Path], out: Path) -> None:
    cmd = ["dotnet", str(dll), *(str(p) for p in inputs), "--flow-locals", "-o", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"extractor failed ({proc.returncode}): {proc.stderr.strip()[-600:]}")


def run_oracle(dll: Path, inputs: list[Path], facts: Path, out: Path) -> tuple[int, dict[str, Any]]:
    cmd = ["dotnet", str(dll), *(str(p) for p in inputs),
           "--facts", str(facts), "-o", str(out), "--quiet"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    if proc.returncode not in (0, 1) or not out.exists():
        raise RuntimeError(f"oracle failed ({proc.returncode}): {proc.stderr.strip()[-600:]}")
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    if report.get("schema") != ORACLE_SCHEMA:
        raise RuntimeError(f"oracle report schema {report.get('schema')!r} != {ORACLE_SCHEMA}")
    return proc.returncode, report


def inputs(only: set[str]) -> list[tuple[str, list[Path]]]:
    docs: list[tuple[str, list[Path]]] = []
    for case in sorted(SHAPES.glob("*/case.cs")):
        name = f"shape:{case.parent.name}"
        if not only or name in only or case.parent.name in only:
            docs.append((name, [case]))
    if not only or "probe" in only:
        docs.append(("probe", [PROBE]))
    if not only or "samples" in only:
        docs.append(("samples", sorted(SAMPLES.glob("*.cs"))))
    if (HOSTILE / "cases").exists() and (not only or "hostile" in only):
        docs.append(("hostile", sorted((HOSTILE / "cases").glob("*.cs"))))
    return docs


def load_findings() -> dict[str, Any]:
    if not FINDINGS.exists():
        return {"findings": {}, "expected_red": {}}
    doc: dict[str, Any] = json.loads(FINDINGS.read_text(encoding="utf-8"))
    return doc


# ---- 1. RED against the ledger ----

def check_red(name: str, report: dict[str, Any], ledger: dict[str, Any]) -> None:
    expected: dict[str, int] = dict(ledger.get("expected_red", {}).get(name, {}).get("red", {}))
    observed: dict[str, int] = dict(report.get("red_kinds", {}))
    if name == "hostile":
        # Hostile REDs are pinned per case (check_hostile); here only the total is tied back.
        return
    detail = "; ".join(
        f"{r.get('kind')} {r.get('member')} {r.get('file')}:"
        f"{r.get('at') or r.get('site') or ''} — {r.get('detail')}"
        for r in report.get("red", [])[:6])
    check(f"oracle-red[{name}]", observed == expected,
          f"observed {observed} expected {expected}; {detail}")


# ---- 2. the probe column ----

def probe_readings(report: dict[str, Any], helpers: set[str]) -> dict[str, str]:
    """The oracle's reading of each probe row: the verdict of the row's handle (`r`, else `p`)."""
    out: dict[str, str] = {}
    for m in report.get("members", []):
        member = str(m.get("member", ""))
        if not member.startswith("Probe.") or member.count(".") != 1:
            continue
        row = member.split(".", 1)[1]
        if row in helpers:
            continue
        occs = [o for o in m.get("occurrences", []) if o.get("symbol") in ("r", "p")]
        by_symbol = {o["symbol"]: o for o in occs}
        o = by_symbol.get("r") or by_symbol.get("p")
        if o is None:
            out[row] = "no_occurrence"
            continue
        verdict = str(o.get("verdict"))
        reading = verdict if verdict == "captured" else f"{verdict}:{o.get('explanation')}"
        if verdict == "captured":
            reading += f":{o.get('site_kind')}"
            if o.get("enclosing_sites"):
                reading += "+" + "+".join(sorted({e["explanation"] for e in o["enclosing_sites"]}))
        out[row] = reading
    return out


def check_probe(report: dict[str, Any], record: bool) -> None:
    expected: dict[str, Any] = json.loads(PROBE_EXPECTED.read_text(encoding="utf-8"))
    helpers = set(expected.get("helpers", []))
    methods: dict[str, Any] = expected["methods"]
    readings = probe_readings(report, helpers)
    problems: list[str] = []
    for row, entry in methods.items():
        reading = readings.get(row, "no_member")
        cls = entry.get("class")
        if cls in RELEVANT_CLASSES:
            site_kind = {"object_creation": "object_creation",
                         "delegate_invocation": "delegate_invocation"}
            want = "captured:" + site_kind.get(str(entry.get("form", "")), "invocation")
        elif entry.get("exclusion") == "nested_call_result":
            # The one indirect exclusion that owns a fact of its own: the handle is captured by
            # the INNER call and the outer call is what nested_call_result names.
            want = "captured:invocation+nested_call_result"
        else:
            want = f"excluded:{entry.get('exclusion')}"
        ok = reading == want
        if not ok:
            problems.append(f"{row}: oracle reads {reading!r}, the frozen class says {want!r}")
    check("probe-rows-read-as-frozen", not problems, "; ".join(problems))
    if record:
        for row in methods:
            methods[row][PROBE_COLUMN] = readings.get(row, "no_member")
        expected[f"{PROBE_COLUMN}_note"] = (
            "The completeness oracle's live reading of each row (A2.2-4): the verdict of the "
            "row's handle occurrence, `captured:<site kind>[+enclosing exclusions]` or "
            "`excluded:<named exclusion>`. Recorded by scripts/p037_completeness_oracle.py "
            "record and held equal by check; the oracle is checked against the class, never "
            "the other way round.")
        PROBE_EXPECTED.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {PROBE_COLUMN} for {len(methods)} probe row(s)")
        return
    stale = [row for row, e in methods.items()
             if e.get(PROBE_COLUMN) != readings.get(row, "no_member")]
    check("probe-column-recorded-equals-live", not stale,
          f"rows whose {PROBE_COLUMN} differs from the live reading: {stale} (run `record`)")


# ---- 3. the hostile census against its design ----

def _occ_view(o: dict[str, Any]) -> dict[str, Any]:
    v: dict[str, Any] = {"symbol": o.get("symbol"), "verdict": o.get("verdict")}
    if o.get("verdict") != "captured":
        v["explanation"] = o.get("explanation")
    if o.get("site_kind") is not None:
        v["site_kind"] = o.get("site_kind")
        v["ordinal"] = o.get("ordinal")
    if o.get("expected") is not None:
        v["expected"] = o.get("expected")
    if o.get("nested_function"):
        v["nested_function"] = True
    v["enclosing"] = sorted({e["explanation"] for e in o.get("enclosing_sites", [])})
    return v


def _design_view(d: dict[str, Any]) -> dict[str, Any]:
    v = dict(d)
    v.setdefault("enclosing", [])
    v["enclosing"] = sorted(v["enclosing"])
    return v


def check_hostile(report: dict[str, Any]) -> None:
    expected: dict[str, Any] = json.loads((HOSTILE / "expected.json").read_text(encoding="utf-8"))
    cases: dict[str, Any] = expected["cases"]
    members: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for m in report.get("members", []):
        key = str(m["member"])
        if key in members:
            duplicates.add(key)
        members[key] = m
    red_by_case: dict[str, dict[str, int]] = {}
    unattributed: list[str] = []
    for r in report.get("red", []):
        member = str(r.get("member", ""))
        case = next((n for n, c in cases.items()
                     if member.startswith(c["member"].split(".M")[0] + ".")), None)
        if case is None:
            unattributed.append(f"{r.get('kind')} {member}")
            continue
        red_by_case.setdefault(case, {})
        red_by_case[case][str(r["kind"])] = red_by_case[case].get(str(r["kind"]), 0) + 1
    check("hostile-red-attributed", not unattributed, "; ".join(unattributed))
    check("hostile-compiles", report.get("compile_errors") == 0,
          f"{report.get('compile_errors')} compile error(s): "
          f"{report.get('compile_error_examples')}")
    ledger = load_findings().get("findings", {})
    problems: list[str] = []
    for name, design in cases.items():
        member_name = design["member"]
        if design.get("member_override"):
            member_name = member_name.rsplit(".M", 1)[0] + design["member_override"]
        m = members.get(member_name)
        if m is None:
            problems.append(f"{name}: member {member_name} not in the oracle report")
            continue
        if member_name in duplicates:
            problems.append(f"{name}: member {member_name} is overloaded; "
                            "a designed member must be unique")
            continue
        observed = [_occ_view(o) for o in m.get("occurrences", [])]
        designed = [_design_view(o) for o in design["occurrences"]]
        # A designed occurrence is compared on the keys it names; the oracle must have exactly
        # as many universe occurrences, in source order.
        if len(observed) != len(designed):
            problems.append(f"{name}: {len(observed)} universe occurrence(s) observed, "
                            f"{len(designed)} designed: {observed}")
            continue
        for i, (o, d) in enumerate(zip(observed, designed, strict=True)):
            for k, want in d.items():
                if o.get(k) != want:
                    problems.append(f"{name}: occurrence {i} ({o.get('symbol')}) "
                                    f"{k}={o.get(k)!r}, designed {want!r}")
        if m.get("carrier") != design["carrier"]:
            problems.append(f"{name}: carrier {m.get('carrier')!r}, designed {design['carrier']!r}")
        red = red_by_case.get(name, {})
        if red != design.get("red", {}):
            problems.append(f"{name}: RED {red}, designed {design.get('red', {})}")
        if design.get("red") and design.get("finding") not in ledger:
            problems.append(f"{name}: expects RED but names finding {design.get('finding')!r} "
                            f"absent from {FINDINGS.name}")
    check("hostile-cases-read-as-designed", not problems, "; ".join(problems[:12]))


# ---- driver ----

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("check", "record"))
    ap.add_argument("--only", default="",
                    help="comma-separated: shape names, probe, samples, hostile")
    ap.add_argument("--keep", default="", help="directory to keep every facts/oracle JSON in")
    args = ap.parse_args(argv)
    only = {n for n in args.only.split(",") if n}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if not os.environ.get("DOTNET_ROOT") and not any(
            os.access(os.path.join(p, "dotnet"), os.X_OK) for p in path_dirs):
        print("dotnet is not on PATH and DOTNET_ROOT is unset: the extractor cannot run",
              file=sys.stderr)
        return 2
    extractor = build(EXTRACTOR, "ownsharp-extract.dll")
    oracle = build(ORACLE, "ownsharp-oracle.dll")
    ledger = load_findings()
    for fid, f in ledger.get("findings", {}).items():
        check(f"finding-classified[{fid}]", bool(f.get("class")) and bool(f.get("title")),
              "a finding needs a §10.1 class and a title")
    keep = Path(args.keep) if args.keep else None
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p037-oracle-") as td:
        work = keep or Path(td)
        for name, paths in inputs(only):
            tag = name.replace(":", "-")
            facts = work / f"{tag}.facts.json"
            out = work / f"{tag}.oracle.json"
            try:
                run_extractor(extractor, paths, facts)
                rc, report = run_oracle(oracle, paths, facts, out)
            except RuntimeError as ex:
                check(f"oracle-run[{name}]", False, str(ex))
                continue
            summary = report.get("summary", {})
            print(f"  {name}: {summary.get('universe_occurrences')} universe occurrence(s), "
                  f"{summary.get('captured')} captured, {summary.get('excluded')} excluded, "
                  f"{summary.get('not_call_related')} not call-related, "
                  f"RED {summary.get('red')} (rc {rc})")
            check_red(name, report, ledger)
            if name == "probe":
                check_probe(report, record=args.cmd == "record")
            if name == "hostile":
                check_hostile(report)
    for name in ledger.get("expected_red", {}):
        if only and name not in only and not name.startswith("shape:"):
            continue
        check(f"ledger-input-exists[{name}]", any(n == name for n, _ in inputs(set())),
              f"{FINDINGS.name} pins an input that no longer exists")
    if _failures:
        print(f"RESULT: {len(_failures)} completeness-oracle check(s) failed")
        return 1
    print("RESULT: completeness oracle green against the ledger, the probe and the hostile census")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
