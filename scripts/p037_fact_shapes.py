#!/usr/bin/env python3
"""The P-037 FACT-SHAPE census: what the extractor emits for shapes A1.1 touches.

`corpus/p037-shapes/<shape>/case.cs` is one minimal program per C# shape the
A1.1 steps are known to be sensitive to; `expected.json` beside it records what
the facts must look like and what the verdict must be.

WHY A SECOND CENSUS EXISTS. The 137-file verdict corpus reported UNCHANGED for
a version of A1.1-a1 that turned six CI jobs red: it contains no method that
returns its own disposable parameter, and the repository's own tree does. The
corpus is labelled for VERDICTS; these steps change the FACT SURFACE.

    verdict coverage != syntax / fact-shape coverage

Two hundred more random C# files would not have closed that gap. One fixture
per shape does, and it fails by NAME instead of as a number that moved.

STATUS per shape:

* ``anchored``   — the facts are what they must stay. A change is a regression.
* ``pending_a2`` — the shape belongs to a step that has not landed. The record
  pins TODAY's facts anyway, so the diff a2 produces is visible per shape
  rather than aggregated away, and ``a2_contract`` states in prose what a2 owes.

ENGINE is explicit (#262 Stage 3): the verdict layer is engine-visible, and a
bare invocation resolves the Rust candidate or exits 2 having measured nothing.
The FACT layer is engine-independent by construction — it is the extractor's
output, read before any engine runs.

Usage:
  p037_fact_shapes.py check  [--engine rust|python|both] [--only NAME,...]
  p037_fact_shapes.py record [--only NAME,...]   # regenerate expected.json facts
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
SCHEMA = "p037-fact-shape/1"


def extractor_facts(case: Path, out: Path) -> tuple[int, str]:
    """Run the Roslyn extractor alone — no engine, no verdict."""
    cmd = ["dotnet", "run", "--project",
           str(ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor"), "--",
           str(case), "--flow-locals", "-o", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    return proc.returncode, proc.stderr.strip()[-400:]


def flatten(nodes: list[Any]) -> list[str]:
    """A body's ops as stable strings, recursing into branch and loop bodies.

    Deliberately lossy in one direction only: it keeps op, subject and line, and
    it keeps NESTING as an explicit `then:`/`else:` prefix, so a fact that moves
    between branches is a difference rather than a coincidence.
    """
    out: list[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        subject = n.get("var") if n.get("var") is not None else n.get("callee")
        head = f"{n.get('op')}:{subject}@{n.get('line')}"
        extras = []
        if "args" in n:
            extras.append(f"args={n.get('args')}")
        if "arg_bindings" in n:          # a2
            extras.append(f"arg_bindings={n.get('arg_bindings')}")
        if "guard" in n:                 # a2
            extras.append(f"guard={n.get('guard')}")
        if extras:
            head += "[" + " ".join(extras) + "]"
        out.append(head)
        for key in ("then", "else", "body"):
            inner = n.get(key)
            if isinstance(inner, list):
                out.extend(f"{key}:{s}" for s in flatten(inner))
    return out


def observe_facts(case: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        facts = Path(tmp) / "facts.json"
        rc, err = extractor_facts(case, facts)
        if rc != 0 or not facts.exists():
            return {"extractor_failed": {"rc": rc, "stderr_tail": err}}
        doc: dict[str, Any] = json.loads(facts.read_text(encoding="utf-8"))
    return {
        fn["name"]: {
            "params": fn.get("params"),
            "body": flatten(fn.get("body", [])),
            # P-037 A2.1: the guarded-fact sidecar, whole. It is the fact surface a2
            # exists to add, so it is pinned per shape exactly like the body ops.
            "guarded_facts": fn.get("guarded_facts"),
        }
        for fn in doc.get("functions", [])
    }


def observe_verdict(case: Path, engine: str) -> list[str]:
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", "warning", str(case)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [f"UNREADABLE-SARIF rc={proc.returncode} {proc.stderr.strip()[-200:]}"]
    out: list[str] = []
    for run in doc.get("runs", []):
        for r in run.get("results", []):
            loc = (r.get("locations") or [{}])[0]
            line = loc.get("physicalLocation", {}).get("region", {}).get("startLine", 0)
            out.append(f"{r.get('ruleId')}:{r.get('level')}@{line}")
    return sorted(out)


def _subset(expected: Any, observed: Any) -> bool:
    """`expected` is contained in `observed`: dicts by key, lists element-wise, scalars ==."""
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(
            k in observed and _subset(v, observed[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(observed, list) and len(expected) == len(observed)
                and all(_subset(e, o) for e, o in zip(expected, observed, strict=True)))
    return bool(expected == observed)


def a2_problems(spec: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """The a2 CONTRACT of a shape, checked by name rather than by blob equality.

    `facts` already pins the whole sidecar byte for byte; `a2_expect` states what
    the contract prose promised, so a shape that drifts fails with the promise
    it broke in the message, not with a JSON diff someone has to interpret.
    """
    problems: list[str] = []
    for exp in spec.get("a2_expect", []):
        fn = exp.get("function")
        rec = facts.get(fn) if isinstance(fn, str) else None
        if rec is None:
            problems.append(f"{fn}: no function record")
            continue
        gf = rec.get("guarded_facts")
        if exp.get("guarded_facts") == "absent":
            if gf is not None:
                problems.append(
                    f"{fn}: expected NO guarded_facts (absence is the signal), got some")
            continue
        if exp.get("guards") == "absent" and gf is not None and gf.get("guards"):
            problems.append(f"{fn}: expected no eligible guard, got {gf.get('guards')}")
        if exp.get("calls") == "absent" and gf is not None and gf.get("calls"):
            problems.append(f"{fn}: expected no relevant call, got {gf.get('calls')}")
        for key, want in (("call", exp.get("call")), ("guard", exp.get("guard"))):
            if want is None:
                continue
            pool = (gf or {}).get(key + "s") or []
            hits = [c for c in pool if _subset(want, c)]
            if len(hits) != 1:
                problems.append(
                    f"{fn}: expected exactly one {key} matching {json.dumps(want)}, "
                    f"found {len(hits)} in {json.dumps(pool)}")
    return problems


def cases(only: set[str]) -> list[Path]:
    return sorted(p for p in SHAPES.iterdir()
                  if p.is_dir() and (p / "case.cs").exists()
                  and (not only or p.name in only))


def record(only: set[str]) -> int:
    for c in cases(only):
        spec_path = c / "expected.json"
        spec: dict[str, Any] = (json.loads(spec_path.read_text(encoding="utf-8"))
                                if spec_path.exists() else {})
        spec.setdefault("schema", SCHEMA)
        spec.setdefault("shape", c.name)
        spec.setdefault("status", "pending_a2")
        spec.setdefault("why", "TODO: why this shape is in the census")
        spec["facts"] = observe_facts(c / "case.cs")
        spec["verdict"] = {e: observe_verdict(c / "case.cs", e) for e in ("rust", "python")}
        spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"recorded {c.name}: {len(spec['facts'])} function record(s), "
              f"verdict rust={spec['verdict']['rust']}")
    return 0


def check(only: set[str], engines: list[str]) -> int:
    failures = 0
    for c in cases(only):
        spec_path = c / "expected.json"
        if not spec_path.exists():
            print(f"MISSING  {c.name}: no expected.json (run `record` and annotate it)")
            failures += 1
            continue
        spec: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
        tag = "anchor" if spec.get("status") == "anchored" else "pending-a2"
        facts = observe_facts(c / "case.cs")
        ok = facts == spec["facts"]
        if not ok:
            failures += 1
            print(f"FACTS MOVED  {c.name}  [{tag}]")
            for k in sorted(set(facts) | set(spec["facts"])):
                if facts.get(k) != spec["facts"].get(k):
                    print(f"    {k}")
                    print(f"      recorded: {json.dumps(spec['facts'].get(k))}")
                    print(f"      observed: {json.dumps(facts.get(k))}")
        for e in engines:
            got = observe_verdict(c / "case.cs", e)
            want = spec["verdict"][e]
            if got != want:
                failures += 1
                ok = False
                print(f"VERDICT MOVED  {c.name}  [{tag}] engine={e}: "
                      f"recorded {want}, observed {got}")
        contract = a2_problems(spec, facts)
        for problem in contract:
            print(f"    a2 contract: {problem}")
        if contract:
            ok = False
            failures += 1
        if ok:
            print(f"ok  {c.name:28} [{tag}] {len(facts)} record(s), "
                  f"{len(spec.get('a2_expect', []))} contract check(s)")
    total = len(cases(only))
    if failures:
        print(f"\nRESULT: {failures} difference(s) over {total} shape(s). A shape that "
              f"moved without a step meaning to move it is a regression; a shape a step "
              f"MEANT to move is re-recorded deliberately, never quietly.")
        return 1
    print(f"\nRESULT: all {total} shape(s) match their recorded facts and verdicts")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record"):
        p = sub.add_parser(name)
        p.add_argument("--only", default="", help="comma-separated shape names")
        if name == "check":
            p.add_argument("--engine", default="both",
                           choices=("rust", "python", "both"))
    args = ap.parse_args(argv)
    only = {n for n in args.only.split(",") if n}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if not os.environ.get("DOTNET_ROOT") and not any(
            os.access(os.path.join(p, "dotnet"), os.X_OK) for p in path_dirs):
        print("dotnet is not on PATH and DOTNET_ROOT is unset: the extractor cannot run",
              file=sys.stderr)
        return 2
    if args.cmd == "record":
        return record(only)
    engines = ["rust", "python"] if args.engine == "both" else [args.engine]
    return check(only, engines)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
