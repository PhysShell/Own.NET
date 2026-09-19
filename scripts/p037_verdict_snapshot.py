#!/usr/bin/env python3
"""Snapshot every verdict the C# corpus produces, and diff two snapshots.

P-037 A1.1 changes the FACT SURFACE the Roslyn extractor emits before it
changes any semantics (#304, the A1.1-a1/a2 sequence). Each of those steps
carries the same obligation — *richer facts, same verdicts* — and an obligation
nobody can check is a wish. This is the checker.

Method, deliberately the same as ``scripts/benchmark.py``: one ``own-check``
run per FILE, never per directory. A directory run compiles the case's
``before.cs`` and ``after.cs`` into one compilation, where each can resolve the
other's symbols; the per-file runs are what the corpus was labelled against, so
a snapshot taken any other way would measure a different program.

Captured at ``--severity warning``, the most inclusive threshold the launcher
offers (``--severity`` takes ``error|warning`` and nothing else; there is no
``note`` level on that flag, and asking for one is a usage error that exits 2
having analysed nothing). Whatever the core reports at that threshold is
recorded WITH its level, advisories included if they ride along, so a
comparison can be read at verdict level (error/warning) or over everything.
That separation is load-bearing for A1 — an ``OWN051`` appearing where a
fabricated ``release`` used to sit is the LEGACY_HONESTY class arriving, not a
regression, and a snapshot that had collapsed the levels could not tell the two
apart.

ENGINE is explicit and required (#262 Stage 3). A bare invocation resolves the
Rust candidate and exits 2 on a machine without one, and the A1.1 change is in
the EXTRACTOR — shared by both engines — so a snapshot that did not name its
engine would not say which half of the seam it had measured.

A2.0 hardening (scripts/p037_evidence.py holds the contract): the files
measured are the FROZEN population materialized from a named commit, never the
working tree; the Rust engine is the qualified own-cli build and nothing else
(OWEN_RUST_CORE is set to exactly that executable, never inherited);
OWN_EXTRA_REF_DIRS is removed from the launcher's environment and the
extractor's stderr is read for the attestation that no extra reference was
loaded; the execution profile is recorded; the tree is checked clean before and
after; evidence is never written into a tracked location.

Usage:
  p037_verdict_snapshot.py take    --engine rust --out /scratch/verdict-rust.json
  p037_verdict_snapshot.py take    --engine rust --population-commit <T> --out ...
  p037_verdict_snapshot.py compare --before base.json --after new.json [--against <T>]
  p037_verdict_snapshot.py compare --before base.json --after new.json --level all
  p037_verdict_snapshot.py verify  snapshot.json [--against <T>]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import p037_evidence as ev

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "p037-verdict-snapshot/3"
VERDICT_LEVELS = ("error", "warning")


def run_one(path: Path, engine: str, env: dict[str, str]) -> dict[str, Any]:
    """One file through the launcher; SARIF in, (exit, findings) out."""
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", "warning", "--", str(path)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False, env=env)
    findings: list[dict[str, Any]] = []
    parse_error = ""
    try:
        doc = json.loads(proc.stdout)
        for run in doc.get("runs", []):
            for res in run.get("results", []):
                loc = (res.get("locations") or [{}])[0]
                region = loc.get("physicalLocation", {}).get("region", {})
                findings.append({
                    "code": res.get("ruleId", "?"),
                    "level": res.get("level", "?"),
                    "line": region.get("startLine", 0),
                })
    except json.JSONDecodeError as exc:
        # Not silently swallowed: a file whose SARIF did not parse is recorded
        # as such, so it can never be mistaken for a file with no findings.
        parse_error = f"{type(exc).__name__}: {exc}"
    findings.sort(key=lambda f: (f["line"], f["code"], f["level"]))
    rec: dict[str, Any] = {"exit": proc.returncode, "findings": findings}
    if parse_error:
        rec["parse_error"] = parse_error
        rec["stderr_tail"] = proc.stderr.strip()[-400:]
    contamination = ev.reference_contamination(proc.stderr)
    if contamination:
        rec["reference_contamination"] = contamination
    return rec


def _refuse(problems: list[str]) -> None:
    if problems:
        raise ev.EvidenceRefused("; ".join(problems))


def take(engine: str, out: Path, dirs: tuple[str, ...], population_commit: str) -> int:
    try:
        _refuse(ev.scratch_problems(out))
        provenance = ev.evidence_fields(dirs, population_commit=population_commit)
        if provenance["dirty"]:
            raise ev.EvidenceRefused("the tree is dirty before the run; evidence starts clean")
        profile = ev.execution_profile(include_rust=engine == "rust")
        artifacts: dict[str, Any] = {}
        if engine == "rust":
            artifact = ev.build_rust_artifact("own-cli", "own-cli")
            _refuse(ev.artifact_problems(artifact))
            artifacts["own-cli"] = artifact
        lease = ev.acquire_population(ev.materialization_root(
            provenance["population_commit"], provenance["analysis_manifest_sha256"]))
    except ev.EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    take_dir = ev.new_take_dir()
    try:
        return _measure(engine, out, dirs, provenance, profile, artifacts, take_dir)
    finally:
        ev.release_population(lease)
        shutil.rmtree(take_dir, ignore_errors=True)


def _measure(
    engine: str,
    out: Path,
    dirs: tuple[str, ...],
    provenance: dict[str, Any],
    profile: dict[str, Any],
    artifacts: dict[str, Any],
    take_dir: Path,
) -> int:
    overrides: dict[str, str] = {}
    try:
        for artifact in artifacts.values():
            # The launcher runs the SEALED copy only; target/release/ is shared
            # and any later cargo build may rewrite it mid-run.
            ev.seal_artifact(artifact, take_dir)
            overrides["OWEN_RUST_CORE"] = str(artifact["executed"]["sealed_path"])
        root = ev.materialize_population(provenance)
        _refuse(ev.external_ancestor_problems(root))
        files = ev.analysis_paths(provenance, root)
    except ev.EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    env = ev.sanitized_env(**overrides)
    reference_profile = ev.clean_reference_profile()
    snap: dict[str, Any] = {
        "schema": SCHEMA,
        "engine": engine,
        **provenance,
        "materialization_root": root.relative_to(ROOT).as_posix(),
        "execution_profile": profile,
        "artifacts": artifacts,
        "reference_profile": reference_profile,
        "corpus": list(dirs),
        "files": {},
    }
    for i, f in enumerate(files, 1):
        rel = f.relative_to(root).as_posix()
        rec = run_one(f, engine, env)
        snap["files"][rel] = rec
        if "reference_contamination" in rec:
            reference_profile["observed_extra_reference_lines"] = (
                int(reference_profile["observed_extra_reference_lines"])
                + len(rec["reference_contamination"])
            )
        n = len(rec["findings"])
        print(f"  [{i:3}/{len(files)}] {rel}  ({n} finding(s))", flush=True)
    broken = [k for k, r in snap["files"].items()
              if "parse_error" in r or "reference_contamination" in r]
    ev.finalize_run(snap, provenance, root)
    if broken:
        # A snapshot with an unreadable run is not a snapshot with fewer findings.
        # The first version of this tool asked for a `--severity note` that does
        # not exist, every run exited 2 having analysed nothing, and the result
        # was a confident, entirely empty baseline. Fail closed: a run that could
        # not be read cannot be evidence, and the exit code has to say so.
        snap["is_evidence"] = False
        snap["unreadable"] = broken
    out.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(r["findings"]) for r in snap["files"].values())
    print(f"\nsnapshot: {len(files)} file(s), {total} finding(s), engine={engine}, "
          f"population={provenance['population_commit'][:12]}, "
          f"at {snap['source_commit'][:7]}"
          f"{'' if snap['is_evidence'] else ' (NOT evidence)'}")
    print(f"wrote {out}")
    if broken:
        print(f"\nREFUSED as evidence: {len(broken)}/{len(files)} file(s) produced "
              f"unparsable SARIF or loaded extra references. First few: {broken[:5]}",
              file=sys.stderr)
        for k in broken[:3]:
            print(f"  {k}: exit={snap['files'][k]['exit']} "
                  f"{snap['files'][k].get('stderr_tail', '')[:160]}", file=sys.stderr)
        return 1
    return 0 if snap["is_evidence"] else 1


def key_set(rec: dict[str, Any], level: str) -> set[tuple[int, str, str]]:
    return {(f["line"], f["code"], f["level"]) for f in rec["findings"]
            if level == "all" or f["level"] in VERDICT_LEVELS}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RuntimeError(f"{path}: not a {SCHEMA} document (older schemas carry no "
                           "A2.0 provenance closure)")
    return data


def _snapshot_problems(record: dict[str, Any]) -> list[str]:
    """The files measured are exactly the frozen population, all readable."""
    manifest = record.get("analysis_manifest")
    if not isinstance(manifest, list):
        return ["snapshot carries no analysis_manifest list"]
    expected = {
        entry["path"]
        for entry in manifest
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    files = record.get("files")
    if not isinstance(files, dict):
        return ["snapshot carries no files object"]
    problems: list[str] = []
    if set(files) != expected:
        problems.append("snapshot file keys do not equal the frozen population manifest")
    if record.get("unreadable"):
        problems.append("snapshot contains unreadable runs")
    if any(isinstance(r, dict) and "reference_contamination" in r for r in files.values()):
        problems.append("a run loaded references from the environment")
    if record.get("engine") == "rust" and "own-cli" not in (record.get("artifacts") or {}):
        problems.append("a rust snapshot names no qualified own-cli artifact")
    return problems


def verify(path: Path, against: str) -> int:
    try:
        snap = _load(path)
        problems = [
            *ev.provenance_problems(snap, against=against),
            *_snapshot_problems(snap),
        ]
    except (OSError, ValueError, RuntimeError, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"FAIL[provenance]: {problem}")
        return 1
    print(
        f"OK: {path} is fresh evidence at {against}; "
        f"source={snap['source_commit'][:12]}, population={snap['population_commit'][:12]}, "
        f"inputs={len(snap['analysis_manifest'])}, support={len(snap['support_manifest'])}"
    )
    return 0


def compare(before: Path, after: Path, level: str, against: str) -> int:
    try:
        a, b = _load(before), _load(after)
        problems = [
            *ev.comparison_problems(a, b, against=against),
            *(f"before: {p}" for p in _snapshot_problems(a)),
            *(f"after: {p}" for p in _snapshot_problems(b)),
        ]
    except (OSError, ValueError, RuntimeError, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if a["engine"] != b["engine"]:
        problems.append(f"engines differ ({a['engine']} vs {b['engine']}); a comparison "
                        "across engines measures the engine, not the change")
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        return 2
    print(f"comparing engine={a['engine']} at {a['source_commit'][:7]} -> "
          f"{b['source_commit'][:7]}, population={a['population_commit'][:12]}, level={level}")
    moved = 0
    for rel in sorted(set(a["files"]) | set(b["files"])):
        ra, rb = a["files"].get(rel), b["files"].get(rel)
        if ra is None or rb is None:
            print(f"  FILE {'ADDED' if ra is None else 'REMOVED'}: {rel}")
            moved += 1
            continue
        ka, kb = key_set(ra, level), key_set(rb, level)
        exit_moved = ra["exit"] != rb["exit"]
        if ka == kb and not exit_moved:
            continue
        moved += 1
        print(f"  MOVED {rel}")
        if exit_moved:
            print(f"      exit {ra['exit']} -> {rb['exit']}")
        for f in sorted(ka - kb):
            print(f"      - {f[1]} {f[2]} @{f[0]}")
        for f in sorted(kb - ka):
            print(f"      + {f[1]} {f[2]} @{f[0]}")
    files = len(set(a["files"]) | set(b["files"]))
    if moved == 0:
        print(f"\nRESULT: UNCHANGED — {files} file(s), no verdict moved at level={level}")
        return 0
    print(f"\nRESULT: {moved} of {files} file(s) MOVED at level={level} — "
          f"every one needs a declared class, or it is a defect")
    return 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="record a snapshot")
    t.add_argument("--engine", required=True, choices=("rust", "python"))
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--corpus", action="append", default=None, metavar="DIR")
    t.add_argument("--population-commit", default="HEAD",
                   help="the commit whose blobs are analysed (default HEAD; the after "
                        "side of a pair names the baseline's commit)")
    c = sub.add_parser("compare", help="diff two snapshots")
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--level", default="verdict", choices=("verdict", "all"),
                   help="verdict = error/warning only (default); all = advisories too")
    c.add_argument("--against", default="HEAD",
                   help="the commit the after side must be fresh at (default HEAD)")
    v = sub.add_parser("verify", help="prove a snapshot is still fresh evidence at a commit")
    v.add_argument("snapshot", type=Path)
    v.add_argument("--against", default="HEAD")
    args = ap.parse_args(argv)
    if args.cmd == "take":
        dirs = tuple(args.corpus) if args.corpus else ev.CORPUS_DIRS
        return take(args.engine, args.out, dirs, args.population_commit)
    if args.cmd == "verify":
        return verify(args.snapshot, args.against)
    return compare(args.before, args.after, args.level, args.against)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
