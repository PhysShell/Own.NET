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

Captured at ``--severity note``, which is strictly more information than the
verdict threshold: every finding is recorded WITH its level, so a comparison
can be read at verdict level (error/warning) or including advisories. That
separation is load-bearing for A1 — an ``OWN051`` that appears where a
fabricated ``release`` used to sit is the LEGACY_HONESTY class arriving, not a
regression, and a snapshot that had thrown the advisories away could not tell
the two apart.

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
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIRS = ("corpus/real-world", "corpus/wpf", "corpus/di", "corpus/fixtures",
               "corpus/p036-bakeoff")
VERDICT_LEVELS = ("error", "warning")


def corpus_files(dirs: tuple[str, ...]) -> list[Path]:
    """Every .cs file under the named corpus directories, repo-relative, sorted."""
    out: list[Path] = []
    for d in dirs:
        out.extend(sorted((ROOT / d).rglob("*.cs")))
    return sorted(set(out))


def git(*args: str) -> str:
    proc = subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def run_one(path: Path, engine: str) -> dict[str, Any]:
    """One file through the launcher; SARIF in, (exit, findings) out."""
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", "note", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
    files = corpus_files(dirs)
    if not files:
        print("no corpus files found", file=sys.stderr)
        return 2
    dirty = bool(git("status", "--porcelain"))
    snap: dict[str, Any] = {
        "schema": "p037-verdict-snapshot/1",
        "engine": engine,
        "source_commit": git("rev-parse", "HEAD"),
        "dirty": dirty,
        "is_evidence": not dirty,
        "corpus": list(dirs),
        "files": {},
    }
    for i, f in enumerate(files, 1):
        rel = f.relative_to(ROOT).as_posix()
        snap["files"][rel] = run_one(f, engine)
        n = len(snap["files"][rel]["findings"])
        print(f"  [{i:3}/{len(files)}] {rel}  ({n} finding(s))", flush=True)
    out.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(r["findings"]) for r in snap["files"].values())
    broken = [k for k, r in snap["files"].items() if "parse_error" in r]
    print(f"\nsnapshot: {len(files)} file(s), {total} finding(s), engine={engine}, "
          f"at {snap['source_commit'][:7]}{' (DIRTY — not evidence)' if dirty else ''}")
    if broken:
        print(f"WARNING: {len(broken)} file(s) produced unparsable SARIF: {broken[:5]}")
    print(f"wrote {out}")
    return 0


def key_set(rec: dict[str, Any], level: str) -> set[tuple[int, str, str]]:
    return {(f["line"], f["code"], f["level"]) for f in rec["findings"]
            if level == "all" or f["level"] in VERDICT_LEVELS}


def compare(before: Path, after: Path, level: str) -> int:
    a: dict[str, Any] = json.loads(before.read_text(encoding="utf-8"))
    b: dict[str, Any] = json.loads(after.read_text(encoding="utf-8"))
    if a["engine"] != b["engine"]:
        print(f"REFUSED: engines differ ({a['engine']} vs {b['engine']}). A snapshot "
              f"comparison across engines measures the engine, not the change.",
              file=sys.stderr)
        return 2
    print(f"comparing engine={a['engine']} at {a['source_commit'][:7]} -> "
          f"{b['source_commit'][:7]}, level={level}")
    for name, snap in (("before", a), ("after", b)):
        if snap.get("dirty"):
            print(f"  NOTE: the {name} snapshot was taken on a DIRTY tree — not evidence")
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
    args = ap.parse_args(argv)
    if args.cmd == "take":
        dirs = tuple(args.corpus) if args.corpus else CORPUS_DIRS
        return take(args.engine, args.out, dirs)
    return compare(args.before, args.after, args.level)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
