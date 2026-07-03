#!/usr/bin/env python3
"""
Exact differential oracle — the Rust-migration parity harness (P-022).

NOT `oracle_compare.py`. That script is a *cross-tool* fuzzy matcher (leak-class
only, ±N-line tolerance, coarse severity buckets) for comparing against external
tools with different conventions. This harness answers a different question —
"is the candidate implementation **byte-for-value identical** to the reference
on the same input?" — so it is exact by construction:

  1. **exit/crash gate first**: statuses must match and neither side may have
     crashed (a Python traceback / Rust panic has no SARIF representation, so
     an output-only diff would score a crash as "no findings = parity");
  2. **canonicalize, then diff**: JSON streams are parsed and re-dumped with
     sorted keys (formatting-independent, nothing semantic dropped); the input
     path is normalized to `<input>` on every stream; trailing whitespace is
     not significant;
  3. **stderr is compared too** (machine-format summaries live there), and a
     non-JSON stdout is compared as normalized text.

Modes:
  compare   run reference and candidate on one input, diff every surface
  snapshot  run the reference over a corpus, write golden snapshots + manifest
            keyed by (corpus hash, reference commit)
  verify    run the candidate against existing snapshots; fails on divergence
            AND on a stale manifest (either key changed -> regenerate first)

Usage:
  oracle_exact.py compare  FILE --ref "python -m ownlang" --cand "<binary>"
                           [--surface "check --format sarif"] [--surface ...]
  oracle_exact.py snapshot DIR --out SNAPDIR --ref "python -m ownlang"
                           [--surface ...] [--ext .own]
  oracle_exact.py verify   SNAPDIR --cand "<binary>"
  oracle_exact.py --selftest

zero-dependency: stdlib only, like the rest of scripts/. Default surfaces are
the frozen contracts: `check --format sarif` (verdict seam) and
`cfg --format json` (CFG seam).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

DEFAULT_SURFACES = ["check --format sarif", "cfg --format json"]

# Crash signatures the exit gate refuses to diff past: a traceback/panic is a
# harness failure, not a comparable output.
_CRASH_MARKS = ("Traceback (most recent call last)", "panicked at", "RUST_BACKTRACE")


def _canon_text(text: str, input_path: str) -> str:
    """Normalize a non-JSON stream: input path -> <input>, strip trailing
    whitespace per line and trailing newlines. Nothing semantic is dropped."""
    text = text.replace(input_path, "<input>")
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).rstrip("\n")


def _canon_stream(text: str, input_path: str) -> str:
    """Canonicalize one output stream. If the whole stream parses as JSON it is
    re-dumped with sorted keys (formatting-independent); otherwise it is
    normalized as text. Path normalization applies in both cases."""
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            doc = json.loads(stripped)
        except json.JSONDecodeError:
            return _canon_text(text, input_path)
        canon = json.dumps(doc, indent=2, sort_keys=True)
        return _canon_text(canon, input_path)
    return _canon_text(text, input_path)


def _run(cmd: str, surface: str, input_path: str) -> dict[str, str | int]:
    """Run `<cmd> <surface-args> <input>` and capture the full observable
    record: exit status + canonicalized stdout/stderr + a crash flag."""
    argv = shlex.split(cmd) + shlex.split(surface) + [input_path]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    crashed = any(m in proc.stderr for m in _CRASH_MARKS)
    return {
        "status": proc.returncode,
        "stdout": _canon_stream(proc.stdout, input_path),
        "stderr": _canon_text(proc.stderr, input_path),
        "crashed": int(crashed),
    }


def _diff_records(ref: dict, cand: dict, label: str) -> list[str]:
    """Exact comparison of two observable records; the exit/crash gate runs
    before any output diff (per P-022)."""
    problems: list[str] = []
    if ref["crashed"] or cand["crashed"]:
        who = "reference" if ref["crashed"] else "candidate"
        problems.append(f"{label}: {who} CRASHED — refusing to diff output")
        return problems
    if ref["status"] != cand["status"]:
        problems.append(
            f"{label}: exit status differs (ref={ref['status']} "
            f"cand={cand['status']}) — gate failed, output diff skipped")
        return problems
    for stream in ("stdout", "stderr"):
        if ref[stream] != cand[stream]:
            problems.append(f"{label}: {stream} differs")
    return problems


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=False)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _corpus_files(root: Path, ext: str) -> list[Path]:
    return sorted(p for p in root.rglob(f"*{ext}") if p.is_file())


def _corpus_hash(files: list[Path], root: Path) -> str:
    """One hash over (relpath, content-hash) pairs — either a file edit or an
    add/remove changes it, which is exactly the snapshot-staleness key."""
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(root)).encode())
        h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
    return h.hexdigest()


def _slug(rel: str, surface: str) -> str:
    safe = rel.replace("/", "__").replace("\\", "__")
    surf = surface.split()[0]
    return f"{safe}.{surf}.json"


def cmd_compare(args: argparse.Namespace) -> int:
    problems: list[str] = []
    for surface in args.surface or DEFAULT_SURFACES:
        ref = _run(args.ref, surface, args.input)
        cand = _run(args.cand, surface, args.input)
        problems += _diff_records(ref, cand, f"{args.input} [{surface}]")
    for p in problems:
        print(f"DIVERGENCE: {p}")
    if not problems:
        print(f"parity: {args.input} identical on "
              f"{len(args.surface or DEFAULT_SURFACES)} surface(s)")
    return 1 if problems else 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    root = Path(args.corpus)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = _corpus_files(root, args.ext)
    if not files:
        print(f"no *{args.ext} files under {root}", file=sys.stderr)
        return 2
    surfaces = args.surface or DEFAULT_SURFACES
    for f in files:
        rel = str(f.relative_to(root))
        for surface in surfaces:
            rec = _run(args.ref, surface, str(f))
            rec["file"] = rel
            rec["surface"] = surface
            (out / _slug(rel, surface)).write_text(
                json.dumps(rec, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
    manifest = {
        "corpus_root": str(root),
        "corpus_ext": args.ext,
        "corpus_hash": _corpus_hash(files, root),
        "reference_commit": _git_commit(),
        "surfaces": surfaces,
        "files": [str(f.relative_to(root)) for f in files],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"snapshotted {len(files)} file(s) x {len(surfaces)} surface(s) "
          f"-> {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    snap = Path(args.snapshots)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    root = Path(manifest["corpus_root"])
    files = _corpus_files(root, manifest["corpus_ext"])
    # Staleness gate: EITHER key changing (corpus hash / reference commit)
    # means the snapshots must be regenerated, not silently diffed against.
    now_hash = _corpus_hash(files, root)
    if now_hash != manifest["corpus_hash"]:
        print("STALE SNAPSHOTS: the corpus changed since `snapshot` ran "
              "(corpus_hash mismatch). Regenerate before verifying.",
              file=sys.stderr)
        return 2
    problems: list[str] = []
    for rel in manifest["files"]:
        for surface in manifest["surfaces"]:
            rec_path = snap / _slug(rel, surface)
            ref = json.loads(rec_path.read_text(encoding="utf-8"))
            cand = _run(args.cand, surface, str(root / rel))
            problems += _diff_records(ref, cand, f"{rel} [{surface}]")
    for p in problems:
        print(f"DIVERGENCE: {p}")
    total = len(manifest["files"]) * len(manifest["surfaces"])
    if not problems:
        print(f"parity: {total} record(s) identical "
              f"(reference commit {manifest['reference_commit'][:12]})")
    return 1 if problems else 0


# ---------------------------------------------------------------------------


def _selftest() -> int:
    """Self-contained proof the harness can (a) see parity when both sides are
    the same implementation and (b) see a divergence when they are not."""
    import tempfile

    fails: list[str] = []
    py = f"{shlex.quote(sys.executable)} -m ownlang"

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        leak = tdp / "leak.own"
        leak.write_text(
            "module M\nresource Conn { acquire open release close }\n"
            "fn f() {\n    let c = acquire Conn(1);\n    use c;\n}\n",
            encoding="utf-8")
        clean = tdp / "clean.own"
        clean.write_text("module M\nfn f() {\n}\n", encoding="utf-8")

        # (a) same implementation on both sides => parity on every surface.
        ns = argparse.Namespace(input=str(leak), ref=py, cand=py, surface=None)
        if cmd_compare(ns) != 0:
            fails.append("self-parity must hold (python vs python)")

        # (b) records for different inputs must diverge (stdout + status).
        r1 = _run(py, "check --format sarif", str(leak))
        r2 = _run(py, "check --format sarif", str(clean))
        if not _diff_records(r1, r2, "x"):
            fails.append("distinct inputs must produce a divergence")

        # (c) crash gate: a crashed record refuses the output diff.
        crashed = dict(r1, crashed=1)
        d = _diff_records(crashed, r1, "x")
        if not (d and "CRASHED" in d[0]):
            fails.append("crash gate must trip before any output diff")

        # (d) canonicalization: key order / path spelling are not divergences.
        a = _canon_stream('{"b": 1, "a": [1, 2]}', "/x")
        b = _canon_stream('{\n  "a": [1, 2],\n  "b": 1\n}', "/x")
        if a != b:
            fails.append("JSON canonicalization must ignore formatting/order")

        # (e) snapshot -> verify round-trip is parity; corpus edit -> stale.
        snapdir = tdp / "snaps"
        ns = argparse.Namespace(corpus=str(tdp), out=str(snapdir), ref=py,
                                surface=["check --format sarif"], ext=".own")
        if cmd_snapshot(ns) != 0:
            fails.append("snapshot must succeed")
        nv = argparse.Namespace(snapshots=str(snapdir), cand=py)
        if cmd_verify(nv) != 0:
            fails.append("verify vs the same implementation must be parity")
        clean.write_text("module M\nfn g() {\n}\n", encoding="utf-8")
        if cmd_verify(nv) != 2:
            fails.append("a corpus edit must make snapshots STALE (rc 2)")

    for f in fails:
        print(f"ORACLE-EXACT SELFTEST FAIL: {f}")
    print(f"oracle_exact selftest: {'FAIL' if fails else 'PASS'}")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="mode", required=True)

    c = sub.add_parser("compare", help="diff candidate vs reference on one input")
    c.add_argument("input")
    c.add_argument("--ref", required=True, help="reference command prefix")
    c.add_argument("--cand", required=True, help="candidate command prefix")
    c.add_argument("--surface", action="append",
                   help=f"CLI surface to diff (default: {DEFAULT_SURFACES})")

    s = sub.add_parser("snapshot", help="write golden snapshots of the reference")
    s.add_argument("corpus", help="corpus root directory")
    s.add_argument("--out", required=True)
    s.add_argument("--ref", required=True)
    s.add_argument("--surface", action="append")
    s.add_argument("--ext", default=".own")

    v = sub.add_parser("verify", help="diff the candidate against snapshots")
    v.add_argument("snapshots", help="snapshot directory (with manifest.json)")
    v.add_argument("--cand", required=True)

    args = ap.parse_args(argv)
    if args.mode == "compare":
        return cmd_compare(args)
    if args.mode == "snapshot":
        return cmd_snapshot(args)
    return cmd_verify(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
