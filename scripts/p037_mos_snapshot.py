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

A2.0 hardening (scripts/p037_evidence.py holds the contract): a snapshot
analyses a FROZEN population materialized from a named commit, never the working
tree; runs only the qualified own-shadow-engine build; removes OWN_EXTRA_REF_DIRS
from the extractor's environment and reads its stderr for the attestation that
no extra reference was loaded; records the execution profile; checks the tree
clean before and after; and refuses to write evidence into a tracked location.

Usage:
  p037_mos_snapshot.py take    --source repo --out /scratch/mos-repo.json
  p037_mos_snapshot.py take    --source repo --population-commit <T> --out ...
  p037_mos_snapshot.py compare --before base.json --after new.json [--against <T>]
  p037_mos_snapshot.py verify  snapshot.json [--against <T>]
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

import p037_evidence as ev  # noqa: E402
from shadow_compare import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionFailure,
    engine_identity,
    run_port,
    run_reference,
)

from ownlang.repro import ENGINE_PYTHON, ENGINE_RUST, hash_bytes  # noqa: E402

SCHEMA = "p037-mos-snapshot/2"
SOURCES: dict[str, tuple[str, ...]] = {
    "corpus": ev.CORPUS_DIRS,
    "repo": ev.REPO_TREE_DIRS,
}


class ReferenceContamination(RuntimeError):
    """The extractor attested that it loaded references from the environment."""

    def __init__(self, document: str, lines: list[str]) -> None:
        super().__init__(f"{document}: the extractor loaded extra references: {lines}")
        self.lines = lines


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


def extract_facts(paths: list[Path], document: str) -> bytes:
    """One extractor execution; the emitted facts are the bytes both engines see.

    The child environment is sanitized (no OWN_EXTRA_REF_DIRS) and the
    launcher's stderr, which carries the extractor's own messages, is read for
    the line the extractor prints when it did widen its reference set.
    """
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
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, check=False, env=ev.sanitized_env()
        )
        stderr = proc.stderr.decode("utf-8", "replace")
        contamination = ev.reference_contamination(stderr)
        if contamination:
            raise ReferenceContamination(document, contamination)
        if proc.returncode != 0:
            raise RuntimeError(
                f"extractor/launcher failed for {document}: "
                f"exit {proc.returncode}; stderr={stderr[-800:]}"
            )
        try:
            return facts.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"no emitted facts for {document}: {exc}") from exc


def source_documents(
    source: str, files: list[Path], root: Path
) -> list[tuple[str, list[Path]]]:
    """The two independent source semantics.

    The labelled corpus is a set of independent programs and is therefore
    measured one file at a time, matching its verdict labels. The repository
    tree is one program: all tracked C# files are handed to one Roslyn
    compilation so inter-file calls and summaries remain observable. Document
    ids are population-relative, so they are identical across a pair.
    """
    if source == "corpus":
        return [(path.relative_to(root).as_posix(), [path]) for path in files]
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


def _refuse(problems: list[str]) -> None:
    if problems:
        raise ev.EvidenceRefused("; ".join(problems))


def take(source: str, out: Path, timeout: float, population_commit: str) -> int:
    roots = SOURCES[source]
    try:
        _refuse(ev.scratch_problems(out))
        provenance = ev.evidence_fields(roots, population_commit=population_commit)
        if provenance["dirty"]:
            raise ev.EvidenceRefused("the tree is dirty before the run; evidence starts clean")
        profile = ev.execution_profile(include_rust=True)
        artifact = ev.build_rust_artifact("own-shadow", "own-shadow-engine")
        _refuse(ev.artifact_problems(artifact))
        adapter = engine_identity(str(artifact["executable"]))
        if adapter["sha256"] != artifact["sha256"]:
            raise ev.EvidenceRefused("the adapter about to run is not the qualified build")
        lease = ev.acquire_population(ev.materialization_root(
            provenance["population_commit"], provenance["analysis_manifest_sha256"]))
    except (RuntimeError, SystemExit, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    try:
        return _measure(source, out, timeout, provenance, profile, artifact, adapter)
    finally:
        ev.release_population(lease)


def _measure(
    source: str,
    out: Path,
    timeout: float,
    provenance: dict[str, Any],
    profile: dict[str, Any],
    artifact: dict[str, Any],
    adapter: dict[str, Any],
) -> int:
    try:
        root = ev.materialize_population(provenance)
        _refuse(ev.external_ancestor_problems(root))
        files = ev.analysis_paths(provenance, root)
    except ev.EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    documents = source_documents(source, files, root)
    reference_profile = ev.clean_reference_profile()
    snapshot: dict[str, Any] = {
        "schema": SCHEMA,
        "source": source,
        **provenance,
        "materialization_root": root.relative_to(ROOT).as_posix(),
        "execution_profile": profile,
        "artifacts": {"own-shadow-engine": artifact},
        "reference_profile": reference_profile,
        "documents": {},
    }
    failures: list[str] = []
    parity_moved: list[str] = []
    for i, (doc_id, paths) in enumerate(documents, 1):
        rels = [path.relative_to(root).as_posix() for path in paths]
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
        except ReferenceContamination as exc:
            reference_profile["observed_extra_reference_lines"] = (
                int(reference_profile["observed_extra_reference_lines"]) + len(exc.lines)
            )
            failures.append(f"{doc_id}: {exc}")
            record = {"inputs": rels, "error": str(exc)}
        except (RuntimeError, ExecutionFailure) as exc:
            failures.append(f"{doc_id}: {exc}")
            record = {"inputs": rels, "error": str(exc)}
        snapshot["documents"][doc_id] = record
        print(
            f"  [{i:3}/{len(documents)}] {doc_id} ({len(paths)} source file(s))",
            flush=True,
        )

    tampered = ev.population_intact(provenance, root)
    snapshot["post_run_population_intact"] = not tampered
    if tampered:
        snapshot["is_evidence"] = False
        snapshot["population_tampered"] = tampered
    if ev.tree_is_dirty():
        snapshot["is_evidence"] = False
        snapshot["post_run_dirty"] = True
    if failures or parity_moved:
        snapshot["is_evidence"] = False
    if failures:
        snapshot["failures"] = failures
    if parity_moved:
        snapshot["cross_engine_mismatches"] = parity_moved

    out.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"snapshot: {len(documents)} document(s) / {len(files)} source file(s), source={source}, "
        f"population={provenance['population_commit'][:12]}, "
        f"cross-engine mismatches={len(parity_moved)}, failures={len(failures)}, "
        f"at {snapshot['source_commit'][:7]}"
        f"{'' if snapshot['is_evidence'] else ' (NOT evidence)'}"
    )
    print(f"wrote {out}")
    return 0 if snapshot["is_evidence"] else 1


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RuntimeError(f"{path}: not a {SCHEMA} document")
    return data


def _snapshot_problems(record: dict[str, Any]) -> list[str]:
    """The documents measured are exactly the frozen population, all of them."""
    problems: list[str] = []
    manifest = record.get("analysis_manifest")
    if not isinstance(manifest, list):
        return ["snapshot carries no analysis_manifest list"]
    expected = {
        entry["path"]
        for entry in manifest
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    documents = record.get("documents")
    if not isinstance(documents, dict):
        return ["snapshot carries no documents object"]
    seen: list[str] = []
    for doc_id, doc in documents.items():
        if not isinstance(doc, dict):
            problems.append(f"document {doc_id!r} is not an object")
            continue
        inputs = doc.get("inputs")
        if not isinstance(inputs, list) or not all(isinstance(x, str) for x in inputs):
            problems.append(f"document {doc_id!r} carries no valid inputs list")
            continue
        seen.extend(str(x) for x in inputs)
        if "error" in doc:
            problems.append(f"document {doc_id!r} records an execution error")
    if len(seen) != len(set(seen)):
        problems.append("a source input appears in more than one MOS document")
    if set(seen) != expected:
        problems.append("MOS document inputs do not equal the frozen population manifest")
    if "own-shadow-engine" not in (record.get("artifacts") or {}):
        problems.append("snapshot names no qualified own-shadow-engine artifact")
    return problems


def compare(before: Path, after: Path, against: str) -> int:
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
    if a.get("source") != b.get("source"):
        problems.append(f"sources differ ({a.get('source')!r} vs {b.get('source')!r})")
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
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
        + f" — source={a.get('source')}, population={str(a.get('population_commit'))[:12]}, "
          f"documents={len(names)}, facts_moved={len(moved['facts'])}, "
          f"python_mos_moved={len(moved[ENGINE_PYTHON])}, "
          f"rust_mos_moved={len(moved[ENGINE_RUST])}, "
          f"after_parity_moved={len(after_parity)}"
    )
    return 1 if failed else 0


def verify(path: Path, against: str) -> int:
    try:
        record = _load(path)
        problems = [
            *ev.provenance_problems(record, against=against),
            *_snapshot_problems(record),
        ]
    except (OSError, ValueError, RuntimeError, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"FAIL[provenance]: {problem}")
        return 1
    print(
        f"OK: {path} is fresh evidence at {against}; source={record['source_commit'][:12]}, "
        f"population={record['population_commit'][:12]}, "
        f"inputs={len(record['analysis_manifest'])}, "
        f"support={len(record['support_manifest'])}"
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("take")
    t.add_argument("--source", required=True, choices=tuple(SOURCES))
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--population-commit", default="HEAD",
                   help="the commit whose blobs are analysed (default HEAD; the after "
                        "side of a pair names the baseline's commit)")
    t.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--against", default="HEAD",
                   help="the commit the after side must be fresh at (default HEAD)")
    v = sub.add_parser("verify")
    v.add_argument("snapshot", type=Path)
    v.add_argument("--against", default="HEAD")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "take":
        return take(args.source, args.out, args.timeout, args.population_commit)
    if args.cmd == "compare":
        return compare(args.before, args.after, args.against)
    if args.cmd == "verify":
        return verify(args.snapshot, args.against)
    ap.error("one command is required (or --selftest)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
