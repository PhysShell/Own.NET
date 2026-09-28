#!/usr/bin/env python3
"""P-037 B1: the first guarded shadow run over the frozen population.

Contract: docs/notes/p037-phase-b1-shadow.md (§B N5/N6, §E). Every input is
read from git at the frozen population commit and nothing else (G14). Per
document the extractor runs once with the opt-in A14 side report, and
`own-guarded-report` reads the facts on stdin (R-1). The run aggregates:

* the summary and application class counts and the NO_GUARDED_EVIDENCE census;
* every UNEXPLAINED row, tagged with whether its legacy value comes from the
  extractor's `ConsumesParam` fold (information only, never a class);
* the A14 exposure metrics (side report joined to the shadow rows);
* the R record-absence metrics.

Run:  python scripts/p037_b1_shadow.py --out docs/evidence/p037-b1-shadow.json
      (needs dotnet, a built extractor and `cargo build --release -p own-shadow`)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_evidence as ev  # noqa: E402

POPULATION_COMMIT = "571669e"
EXTRACTOR = ROOT / "frontend/roslyn/OwnSharp.Extractor/bin/Debug/net8.0/ownsharp-extract.dll"
REPORT_BIN = ROOT / "rust/target/release/own-guarded-report"
CORPUS = ("corpus/real-world", "corpus/wpf", "corpus/di", "corpus/fixtures", "corpus/p036-bakeoff")
CONTROLS = ("guarded-consume-", "gv4-control-", "legacy-honesty-")
SIDE_KEYS = {"caller", "site", "callee", "dispatch", "observed_targets"}
COMPARABLE_KEYS = ("method", "index", "ordinal", "param", "legacy", "guarded", "class")


class Refused(RuntimeError):
    """The run cannot be a measurement of the frozen population."""


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout


def frozen(commit: str) -> str:
    """G14: only the frozen population commit is a measurement."""
    want = git("rev-parse", f"{POPULATION_COMMIT}^{{commit}}").strip()
    got = git("rev-parse", f"{commit}^{{commit}}").strip()
    if got != want:
        raise Refused(f"population commit {commit} is not the frozen {POPULATION_COMMIT}; "
                      "population drift is not a measurement (G14)")
    return want


def validate_side_report(doc: Any) -> list[str]:
    """G15: the side report is measurement only, never a conclusion."""
    if not isinstance(doc, dict):
        return ["side report is not an object"]
    bad = []
    if doc.get("schema") != "p037-dispatch-side-report/1":
        bad.append("schema")
    if doc.get("measurement_only") is not True or doc.get("observed_targets_are_exhaustive") \
            is not False:
        bad.append("the report must say measurement_only and not exhaustive")
    if set(doc) != {"schema", "measurement_only", "observed_targets_are_exhaustive", "calls"}:
        bad.append(f"unexpected top-level keys {sorted(set(doc))}")
    for c in doc.get("calls") or []:
        if not isinstance(c, dict) or set(c) != SIDE_KEYS:
            bad.append(f"call keys {sorted(c) if isinstance(c, dict) else c!r}")
        elif c["dispatch"] not in ("exact", "open"):
            bad.append(f"dispatch {c['dispatch']!r}")
        elif c["dispatch"] == "exact" and c["observed_targets"]:
            bad.append("an exact call carries observed targets")
    return bad


def documents(tree: Path, commit: str) -> list[tuple[str, str, list[str]]]:
    """(population, document, files) in §E order, from the tree at `commit`."""
    def cs(*roots: str) -> list[str]:
        out = git("ls-tree", "-r", "--name-only", commit, "--", *roots).split()
        return sorted(p for p in out if p.endswith(".cs"))
    docs = [("repo", "frontend+audit", cs("frontend", "audit"))]
    docs += [("corpus", f, [f]) for f in cs(*CORPUS)]
    shapes = sorted({p.split("/")[2] for p in cs("corpus/p037-shapes")})
    docs += [("p037-shapes", s, cs(f"corpus/p037-shapes/{s}")) for s in shapes]
    docs.append(("b0-probes", "probes", cs("docs/evidence/p037-b0-probes")))
    for _, _, files in docs:
        for f in files:
            if not (tree / f).is_file():
                raise Refused(f"{f} is not materialized")
    return docs


def run_document(tree: Path, files: list[str], work: Path) -> tuple[Any, Any, Any]:
    facts, side = work / "facts.json", work / "dispatch.json"
    cmd = ["dotnet", str(EXTRACTOR), *files, "--flow-locals", "-o", str(facts),
           "--dispatch-report", str(side)]
    x = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, check=False,
                       env=ev.sanitized_env())
    if x.returncode != 0 or ev.reference_contamination(x.stderr):
        raise Refused(f"extractor failed on {files[:2]}: {x.stderr.strip()[-400:]}")
    rep = subprocess.run([str(REPORT_BIN)], input=facts.read_bytes(), capture_output=True,
                         check=False)
    if rep.returncode != 0:
        raise Refused(f"own-guarded-report failed: {rep.stderr.decode()[-400:]}")
    return (json.loads(facts.read_text(encoding="utf-8")), json.loads(rep.stdout),
            json.loads(side.read_text(encoding="utf-8")))


def folded(fn: dict[str, Any], var: str, line: int) -> bool:
    """The legacy body releases `var` at a line where a sidecar call takes it."""
    ops, stack = [], list(fn.get("body") or [])
    while stack:
        op = stack.pop()
        ops.append(op)
        stack += [*op.get("then", []), *op.get("else", []), *op.get("body", [])]
    return any(o.get("op") == "release" and o.get("var") == var and o.get("line") == line
               for o in ops)


def analyse(docs: list[tuple[str, str, Any, Any, Any]]) -> dict[str, Any]:
    count: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    unexplained: list[dict[str, Any]] = []
    a14: collections.Counter[str] = collections.Counter()
    r_callees: set[str] = set()
    for pop, name, facts, rep, side in docs:
        fns = {f["name"]: f for f in facts.get("functions", [])}
        coords = {(s["method"], s["ordinal"]): s for s in rep["summary"]}
        for s in rep["summary"]:
            count[f"summary/{pop}"][s["class"]] += 1
            count["summary"][s["class"]] += 1
            if s.get("reason"):
                count["nge/summary"][s["reason"]] += 1
            if s["class"] == "UNEXPLAINED":
                calls = (fns[s["method"]].get("guarded_facts") or {}).get("calls", [])
                lines = [c["statement_line"] for c in calls
                         if any(a.get("source_param") == s["ordinal"] for a in c["args"])]
                fold = any(folded(fns[s["method"]], s["param"], ln) for ln in lines)
                unexplained.append({"level": "summary", "doc": name, **s, "legacy_fold": fold})
        for a in rep["application"]:
            count[f"application/{pop}"][a["class"]] += 1
            count["application"][a["class"]] += 1
            if a.get("reason"):
                count["nge/application"][a["reason"]] += 1
            if a.get("reason") == "callee_no_record" and a["first_party"]:
                r_callees.add(a["callee"])
            if a["class"] == "UNEXPLAINED":
                var = a["handle"].split(":", 1)[1] if a["handle"].startswith("var:") else \
                    fns[a["caller"]]["params"][int(a["handle"].split(":")[1])]["name"]
                fold = folded(fns[a["caller"]], var, a["statement_line"])
                unexplained.append({"level": "application", "doc": name, **a, "legacy_fold": fold})
        sites = collections.defaultdict(list)
        for a in rep["application"]:
            sites[(a["caller"], a["site"]["line"], a["site"]["column"])].append(a)
        for c in side["calls"]:
            a14["relevant_calls"] += 1
            a14[c["dispatch"]] += 1
            rows = sites.get((c["caller"], c["site"]["line"], c["site"]["column"]), [])
            if c["dispatch"] != "open":
                continue
            a14["open_in_guarded_chain"] += any(r["in_chain"] for r in rows)
            values = []
            for slot in {r["slot"] for r in rows}:
                targets = [coords.get((t, slot)) for t in [c["callee"], *c["observed_targets"]]]
                values.append([(x.get("guarded"), x.get("shape"), str(x.get("cells")))
                               if x else None for x in targets])
            a14["open_observed_targets_differ"] += any(len(set(v)) > 1 for v in values)
            a14["kill_witness_static_must_observed_not"] += any(
                v[0] is not None and v[0][0] == "must"
                and any(x is None or x[0] != "must" for x in v[1:]) for v in values)
    r_direct = count["nge/summary"]["callee_no_record"]
    r_via = count["nge/summary"]["via:callee_no_record"]
    eligible = count["summary"]["EQUAL"] + count["summary"]["SUMMARY_REFINEMENT"] + \
        count["summary"]["LEGACY_HONESTY"] + count["summary"]["UNEXPLAINED"] + r_direct + r_via
    return {
        "counts": {k: dict(sorted(v.items())) for k, v in sorted(count.items())},
        "unexplained": unexplained,
        "a14": dict(a14),
        "r": {"first_party_callees_without_record": sorted(r_callees),
              "coordinates_ending_at_r": r_direct, "coordinates_tainted_by_r": r_via,
              "share_of_eligible_chains_broken_by_r":
                  round((r_direct + r_via) / eligible, 4) if eligible else None},
    }


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", default=POPULATION_COMMIT)
    ap.add_argument("--out", required=True)
    # A18 evidence completion (case 4): the per-row comparable summary rows,
    # opt-in; without it the --out document is byte-identical.
    ap.add_argument("--comparable-rows-out")
    args = ap.parse_args(argv)
    try:
        commit = frozen(args.commit)
        if git("status", "--porcelain", "--untracked-files=no").strip():
            raise Refused("the instrument tree is dirty; commit it first")
        for p in (EXTRACTOR, REPORT_BIN):
            if not p.is_file():
                raise Refused(f"{p} is not built")
        with tempfile.TemporaryDirectory(prefix="p037-b1-") as td:
            tree = Path(td) / "tree"
            tree.mkdir()
            archive = subprocess.run(["git", "archive", commit], cwd=ROOT, capture_output=True,
                                     check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
            rows = []
            for pop, name, files in documents(tree, commit):
                facts, rep, side = run_document(tree, files, Path(td))
                if problems := validate_side_report(side):
                    raise Refused(f"{name}: side report {problems}")
                if rep.get("static_dispatch_conditional") is not True:
                    raise Refused(f"{name}: report is not static-dispatch conditional (A14)")
                rows.append((pop, name, facts, rep, side))
                print(f"  {pop}/{name}: {len(rep['summary'])} coordinates, "
                      f"{len(rep['application'])} sites", file=sys.stderr)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    result = analyse(rows)
    controls = [r for r in result["unexplained"] if any(c in r["doc"] for c in CONTROLS)]
    out = {
        "schema": "p037-b1-shadow-run/1",
        "population_commit": commit,
        "instrument_commit": git("rev-parse", "HEAD").strip(),
        "toolchain": {"dotnet": git_free(["dotnet", "--version"]),
                      "rustc": git_free(["rustc", "--version"])},
        "instrument": {"extractor_sha256": sha(EXTRACTOR), "report_sha256": sha(REPORT_BIN)},
        "documents": {pop: sum(1 for r in rows if r[0] == pop) for pop in dict.fromkeys(
            r[0] for r in rows)},
        "static_dispatch_conditional": True,
        **result,
        "unexplained_in_p037_controls": len(controls),
    }
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    if args.comparable_rows_out:
        comparable = sorted(
            ({"population": pop, "document": name, **{k: s[k] for k in COMPARABLE_KEYS}}
             for pop, name, _, rep, _ in rows for s in rep["summary"]
             if s["class"] != "NO_GUARDED_EVIDENCE"),
            key=lambda r: (r["population"], r["document"], r["method"], r["index"]))
        snap = {"schema": "p037-b1-comparable-rows/1",
                **{k: out[k] for k in ("population_commit", "instrument_commit", "toolchain",
                                       "instrument")},
                "counts": dict(collections.Counter(r["class"] for r in comparable)),
                "rows": comparable}
        Path(args.comparable_rows_out).write_text(json.dumps(snap, indent=1) + "\n",
                                                  encoding="utf-8")
    unexplained = sum(1 for _ in result["unexplained"])
    print(json.dumps({k: out[k] for k in ("documents", "counts", "a14", "r")}, indent=1))
    print(f"RESULT: {'FAIL' if unexplained else 'PASS'}: UNEXPLAINED = {unexplained}")
    return 1 if unexplained else 0


def git_free(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=False).stdout.strip()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
