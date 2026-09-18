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

A snapshot records the commit it was taken at and whether the tree was dirty.
A dirty snapshot is not evidence and says so in its own payload; it is still
written, because the inner development loop needs it.

Usage:
  p037_verdict_snapshot.py take    --engine rust --out base.json
  p037_verdict_snapshot.py compare --before base.json --after new.json
  p037_verdict_snapshot.py compare --before base.json --after new.json --level all
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import p037_evidence as ev

ROOT = Path(__file__).resolve().parent.parent
VERDICT_LEVELS = ("error", "warning")


def corpus_files(dirs: tuple[str, ...]) -> list[Path]:
    """The exact committed C# denominator named by the provenance manifest."""
    return ev.input_paths(dirs)


def run_one(path: Path, engine: str, rust_core: str | None) -> dict[str, Any]:
    """One file through the launcher; SARIF in, (exit, findings) out."""
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", "warning", str(path)]
    env = os.environ.copy()
    if rust_core is not None:
        env["OWEN_RUST_CORE"] = rust_core
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
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
    return rec


def take(engine: str, out: Path, dirs: tuple[str, ...]) -> int:
    try:
        candidate = (
            ev.build_rust_binary("own-cli", "own-cli")
            if engine == "rust"
            else None
        )
        toolchains = ev.tool_versions(include_rust=engine == "rust")
        provenance = ev.evidence_fields(dirs)
        files = corpus_files(dirs)
    except ev.EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if not files:
        print("no committed corpus files found", file=sys.stderr)
        return 2
    rust_core = str(candidate["path"]) if candidate is not None else None
    snap: dict[str, Any] = {
        "schema": "p037-verdict-snapshot/2",
        "engine": engine,
        **provenance,
        "toolchains": toolchains,
        **(
            {
                "rust_candidate": {
                    "repo_path": candidate["repo_path"],
                    "sha256": candidate["sha256"],
                    "bytes": candidate["bytes"],
                    "build": candidate["build"],
                }
            }
            if candidate is not None
            else {}
        ),
        "corpus": list(dirs),
        "files": {},
    }
    dirty = bool(snap["dirty"])
    for i, f in enumerate(files, 1):
        rel = f.relative_to(ROOT).as_posix()
        snap["files"][rel] = run_one(f, engine, rust_core)
        n = len(snap["files"][rel]["findings"])
        print(f"  [{i:3}/{len(files)}] {rel}  ({n} finding(s))", flush=True)
    broken = [k for k, r in snap["files"].items() if "parse_error" in r]
    if ev.tree_is_dirty():
        snap["is_evidence"] = False
        snap["post_run_dirty"] = True
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
          f"at {snap['source_commit'][:7]}{' (DIRTY — not evidence)' if dirty else ''}")
    print(f"wrote {out}")
    if broken:
        print(f"\nREFUSED as evidence: {len(broken)}/{len(files)} file(s) produced "
              f"unparsable SARIF. First few: {broken[:5]}", file=sys.stderr)
        for k in broken[:3]:
            print(f"  {k}: exit={snap['files'][k]['exit']} "
                  f"{snap['files'][k].get('stderr_tail','')[:160]}", file=sys.stderr)
        return 1
    return 0


def verify(path: Path) -> int:
    try:
        snap: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {path}: {exc}", file=sys.stderr)
        return 2
    if snap.get("schema") != "p037-verdict-snapshot/2":
        print(
            f"REFUSED: {path}: schema {snap.get('schema')!r} has no A2.0 provenance closure",
            file=sys.stderr,
        )
        return 2
    try:
        problems = ev.provenance_problems(snap)
    except ev.EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"FAIL[provenance]: {problem}")
        return 1
    print(
        f"OK: {path} is fresh evidence at HEAD; "
        f"source={snap['source_commit'][:12]}, inputs={len(snap['input_manifest'])}"
    )
    return 0


def key_set(rec: dict[str, Any], level: str) -> set[tuple[int, str, str]]:
    return {(f["line"], f["code"], f["level"]) for f in rec["findings"]
            if level == "all" or f["level"] in VERDICT_LEVELS}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "p037-verdict-snapshot/2":
        raise RuntimeError(f"{path}: not a p037-verdict-snapshot/2 document")
    return data


def _snapshot_problems(record: dict[str, Any]) -> list[str]:
    manifest = record.get("input_manifest")
    if not isinstance(manifest, list):
        return ["snapshot carries no input_manifest list"]
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
        problems.append("snapshot file keys do not equal the recorded input manifest")
    if record.get("unreadable"):
        problems.append("snapshot contains unreadable runs")
    return problems


def compare(before: Path, after: Path, level: str) -> int:
    try:
        a, b = _load(before), _load(after)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    problems = [
        *ev.comparison_problems(a, b),
        *(f"before: {p}" for p in _snapshot_problems(a)),
        *(f"after: {p}" for p in _snapshot_problems(b)),
    ]
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        return 2
    if a["engine"] != b["engine"]:
        print(f"REFUSED: engines differ ({a['engine']} vs {b['engine']}). A snapshot "
              f"comparison across engines measures the engine, not the change.",
              file=sys.stderr)
        return 2
    print(f"comparing engine={a['engine']} at {a['source_commit'][:7]} -> "
          f"{b['source_commit'][:7]}, level={level}")
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
    c = sub.add_parser("compare", help="diff two snapshots")
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--level", default="verdict", choices=("verdict", "all"),
                   help="verdict = error/warning only (default); all = advisories too")
    v = sub.add_parser("verify", help="prove a snapshot is still fresh evidence at HEAD")
    v.add_argument("snapshot", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "take":
        dirs = tuple(args.corpus) if args.corpus else ev.CORPUS_DIRS
        return take(args.engine, args.out, dirs)
    if args.cmd == "verify":
        return verify(args.snapshot)
    return compare(args.before, args.after, args.level)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
