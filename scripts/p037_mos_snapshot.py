#!/usr/bin/env python3
"""P-037 level-2 evidence: whole MOS snapshots over two independent C# sources.

This tool deliberately reuses P-022's capture protocol on both engines. It does
not implement a second summaries reader or a second Rust dump path:

* facts are extracted once through ``own-check.sh --emit-facts``;
* Python is captured through ``ownlang.repro.capture`` (via run_reference);
* Rust is captured through the existing dev-only ``own-shadow-engine`` adapter;
* one ``summary_surface`` function reads the identical layer envelope from both.

A2 requires richer facts with ZERO MOS movement. The comparison is therefore
whole-document equality, not a projection to transfer: returns/source/degraded/
unresolved are part of the summary surface and a1 already demonstrated why a
returns-shape change cannot be treated as decoration.
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
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from ownlang.repro import ENGINE_PYTHON, ENGINE_RUST, hash_bytes  # noqa: E402

import p037_evidence as ev  # noqa: E402
from shadow_compare import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionFailure,
    engine_identity,
    resolve_engine_binary,
    run_port,
    run_reference,
)

SCHEMA = "p037-mos-snapshot/1"
SOURCES: dict[str, tuple[str, ...]] = {
    "corpus": ev.CORPUS_DIRS,
    "repo": ev.REPO_TREE_DIRS,
}


def _bash() -> str:
    if os.name != "nt":
        return "bash"
    for candidate in (
        os.environ.get("SHELL"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("p037_mos_snapshot requires a real bash (Git Bash on Windows)")


def source_files(roots: tuple[str, ...]) -> list[Path]:
    return ev.input_paths(roots)


def extract_facts(paths: list[Path], document: str) -> bytes:
    """One extractor execution; the emitted facts are the bytes both engines see."""
    if not paths:
        raise RuntimeError(f"{document}: zero source files")
    with tempfile.TemporaryDirectory(prefix="p037-mos-") as td:
        facts = Path(td) / "facts.json"
        cmd = [
            _bash(), str(ROOT / "scripts" / "own-check.sh"),
            "--engine", "python",
            "--format", "sarif",
            "--severity", "warning",
            "--emit-facts", str(facts),
            "--", *(str(path) for path in paths),
        ]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"extractor/launcher failed for {document}: "
                f"exit {proc.returncode}; stderr={proc.stderr.decode('utf-8', 'replace')[-800:]}"
            )
        try:
            return facts.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"no emitted facts for {document}: {exc}") from exc


def source_documents(source: str, files: list[Path]) -> list[tuple[str, list[Path]]]:
    """The two independent source semantics.

    The labelled corpus is a set of independent programs and is therefore
    measured one file at a time, matching its verdict labels. The repository
    tree is one program: all 81 tracked C# files are handed to one Roslyn
    compilation so inter-file calls and summaries remain observable.
    """
    if source == "corpus":
        return [(path.relative_to(ROOT).as_posix(), [path]) for path in files]
    if source == "repo":
        return [("repo-tree", files)]
    raise RuntimeError(f"unknown source {source!r}")


def summary_surface(entry: dict[str, Any]) -> dict[str, Any]:
    """The one reader for either engine's capture-format summaries layer."""
    layers = entry.get("layers")
    if not isinstance(layers, list):
        raise RuntimeError(f"engine {entry.get('id')!r} capture has no layers array")
    matches = [layer for layer in layers
               if isinstance(layer, dict) and layer.get("layer") == "summaries"]
    if len(matches) != 1:
        raise RuntimeError(
            f"engine {entry.get('id')!r} capture has {len(matches)} summaries layers, expected one"
        )
    layer = matches[0]
    status = layer.get("status")
    if status == "produced":
        document = layer.get("document")
        if not isinstance(document, dict):
            raise RuntimeError("produced summaries layer carries no document object")
        return {"status": "produced", "document": document}
    if status == "refused":
        return {"status": "refused", "error": layer.get("error")}
    raise RuntimeError(f"summaries layer has unknown status {status!r}")


def capture_pair(raw: bytes, adapter: dict[str, Any], timeout: float
                 ) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = run_reference(raw)
    py = reference.get("entry")
    if not isinstance(py, dict):
        raise RuntimeError(
            "Python capture refused emitted OwnIR: "
            f"{reference.get('canonical_error')}"
        )
    port = run_port(raw, adapter, timeout)
    envelope = port.get("envelope")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("engine"), dict):
        raise RuntimeError("Rust adapter returned no engine capture")
    rs = envelope["engine"]
    identity = hash_bytes(raw)
    for name, entry in ((ENGINE_PYTHON, py), (ENGINE_RUST, rs)):
        if entry.get("consumed") != identity:
            raise RuntimeError(f"{name} capture does not attest the exact emitted facts bytes")
    return py, rs


def take(source: str, out: Path, engine_binary: str | None, timeout: float) -> int:
    roots = SOURCES[source]
    try:
        provenance = ev.evidence_fields(roots)
        files = source_files(roots)
        binary = resolve_engine_binary(engine_binary)
        adapter = engine_identity(binary)
    except (RuntimeError, SystemExit, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if not files:
        print(f"REFUSED: source {source!r} contains zero committed C# files", file=sys.stderr)
        return 2
    absent = [p for p in files if not p.is_file()]
    if absent:
        print(
            f"REFUSED: {len(absent)} committed input(s) are absent from the working tree; "
            f"first: {absent[0].relative_to(ROOT)}",
            file=sys.stderr,
        )
        return 2

    documents = source_documents(source, files)
    snapshot: dict[str, Any] = {
        "schema": SCHEMA,
        "source": source,
        **provenance,
        "adapter": {"sha256": adapter["sha256"], "bytes": adapter["bytes"]},
        "documents": {},
    }
    failures: list[str] = []
    parity_moved: list[str] = []
    for i, (doc_id, paths) in enumerate(documents, 1):
        rels = [path.relative_to(ROOT).as_posix() for path in paths]
        try:
            raw = extract_facts(paths, doc_id)
            py, rs = capture_pair(raw, adapter, timeout)
            py_surface = summary_surface(py)
            rs_surface = summary_surface(rs)
            record = {
                "inputs": rels,
                "facts": hash_bytes(raw),
                ENGINE_PYTHON: py_surface,
                ENGINE_RUST: rs_surface,
            }
            if py_surface != rs_surface:
                parity_moved.append(doc_id)
        except (RuntimeError, ExecutionFailure) as exc:
            failures.append(f"{doc_id}: {exc}")
            record = {"inputs": rels, "error": str(exc)}
        snapshot["documents"][doc_id] = record
        print(
            f"  [{i:3}/{len(documents)}] {doc_id} ({len(paths)} source file(s))",
            flush=True,
        )

    if failures or parity_moved:
        snapshot["is_evidence"] = False
    if failures:
        snapshot["failures"] = failures
    if parity_moved:
        snapshot["cross_engine_mismatches"] = parity_moved

    out.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"snapshot: {len(documents)} document(s) / {len(files)} source file(s), source={source}, "
        f"cross-engine mismatches={len(parity_moved)}, failures={len(failures)}, "
        f"at {snapshot['source_commit'][:7]}"
    )
    print(f"wrote {out}")
    return 0 if not failures and not parity_moved else 1


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RuntimeError(f"{path}: not a {SCHEMA} document")
    return data


def compare(before: Path, after: Path) -> int:
    try:
        a, b = _load(before), _load(after)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if a.get("source") != b.get("source"):
        print(
            f"REFUSED: sources differ ({a.get('source')!r} vs {b.get('source')!r})",
            file=sys.stderr,
        )
        return 2

    moved: dict[str, list[str]] = {ENGINE_PYTHON: [], ENGINE_RUST: [], "facts": []}
    names = sorted(set(a.get("documents", {})) | set(b.get("documents", {})))
    for rel in names:
        left = a.get("documents", {}).get(rel)
        right = b.get("documents", {}).get(rel)
        if not isinstance(left, dict) or not isinstance(right, dict):
            moved[ENGINE_PYTHON].append(rel)
            moved[ENGINE_RUST].append(rel)
            moved["facts"].append(rel)
            continue
        if left.get("facts") != right.get("facts"):
            moved["facts"].append(rel)
        for engine in (ENGINE_PYTHON, ENGINE_RUST):
            if left.get(engine) != right.get(engine):
                moved[engine].append(rel)

    after_parity = [
        rel for rel, rec in b.get("documents", {}).items()
        if isinstance(rec, dict) and rec.get(ENGINE_PYTHON) != rec.get(ENGINE_RUST)
    ]

    for engine in (ENGINE_PYTHON, ENGINE_RUST):
        for rel in moved[engine]:
            print(f"  MOVED[{engine}] {rel}")
    for rel in moved["facts"]:
        print(f"  FACT-DIFF {rel}")
    for rel in after_parity:
        print(f"  PARITY-DIFF[after] {rel}")

    failed = bool(moved[ENGINE_PYTHON] or moved[ENGINE_RUST] or after_parity)
    print(
        "RESULT: "
        + ("MOVED" if failed else "UNCHANGED")
        + f" — source={a.get('source')}, documents={len(names)}, "
          f"facts_moved={len(moved['facts'])}, "
          f"python_mos_moved={len(moved[ENGINE_PYTHON])}, "
          f"rust_mos_moved={len(moved[ENGINE_RUST])}, "
          f"after_parity_moved={len(after_parity)}"
    )
    return 1 if failed else 0


def verify(path: Path) -> int:
    try:
        record = _load(path)
        problems = ev.provenance_problems(record)
    except (OSError, ValueError, RuntimeError, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"FAIL[provenance]: {problem}")
        return 1
    print(
        f"OK: {path} is fresh evidence at HEAD; source={record['source_commit'][:12]}, "
        f"inputs={len(record['input_manifest'])}"
    )
    return 0


def selftest() -> int:
    base = {
        "id": "synthetic",
        "layers": [
            {"layer": "lowered", "status": "produced", "document": {}},
            {"layer": "summaries", "status": "produced", "document": {
                "functions": [{
                    "name": "F", "params": [{"index": 0, "transfer": "may"}],
                    "returns": {"owned": False, "source": None},
                    "degraded": False, "unresolved": [],
                }]
            }},
            {"layer": "verdicts", "status": "produced", "document": {}},
        ],
    }
    twin = json.loads(json.dumps(base))
    if summary_surface(base) != summary_surface(twin):
        print("FAIL[selftest]: identical captures differ")
        return 1
    twin["layers"][1]["document"]["functions"][0]["returns"]["owned"] = True
    if summary_surface(base) == summary_surface(twin):
        print("FAIL[selftest]: whole-document reader missed returns.owned movement")
        return 1
    twin = json.loads(json.dumps(base))
    twin["layers"][1]["document"]["functions"][0]["unresolved"].append("Extern")
    if summary_surface(base) == summary_surface(twin):
        print("FAIL[selftest]: whole-document reader missed unresolved movement")
        return 1
    print("OK: whole summaries document is the level-2 comparison surface")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("take")
    t.add_argument("--source", required=True, choices=tuple(SOURCES))
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--engine-binary")
    t.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    v = sub.add_parser("verify")
    v.add_argument("snapshot", type=Path)
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "take":
        return take(args.source, args.out, args.engine_binary, args.timeout)
    if args.cmd == "compare":
        return compare(args.before, args.after)
    if args.cmd == "verify":
        return verify(args.snapshot)
    ap.error("one command is required (or --selftest)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
