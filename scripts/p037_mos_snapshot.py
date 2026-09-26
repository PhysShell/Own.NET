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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import p037_b_classifier  # noqa: E402
import p037_evidence as ev  # noqa: E402
import p037_evidence_b  # noqa: E402
from shadow_compare import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionFailure,
    engine_identity,
    run_port,
    run_reference,
)

from ownlang.repro import ENGINE_PYTHON, ENGINE_RUST, hash_bytes  # noqa: E402

SCHEMA = "p037-mos-snapshot/2"
SOURCE_NAMES: tuple[str, ...] = ("corpus", "repo")
# Epoch is explicit and required, matching p037_verdict_snapshot.py's own
# "ENGINE is explicit and required" precedent -- never an implicit "current
# epoch", branch-name inference or a silently-read env var (P-037 Phase B
# prompt, section on epoch-aware tooling). main() rebinds the module-global
# `ev` to the selected module before calling take()/_measure()/compare()/
# verify()/extract_facts() below; their bodies read `ev.*` at call time and
# are otherwise UNCHANGED for either epoch.
EPOCH_MODULES: dict[str, Any] = {"a2d": ev, "b": p037_evidence_b}


def _sources(epoch_mod: Any) -> dict[str, tuple[str, ...]]:
    return {"corpus": epoch_mod.CORPUS_DIRS, "repo": epoch_mod.REPO_TREE_DIRS}


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


def divergence_status(epoch: str, legacy_surface: dict[str, Any],
                      new_surface: dict[str, Any]) -> dict[str, Any]:
    """Whether one CAPTURED SURFACE's divergence from a REFERENCE surface
    counts against `is_evidence`, epoch-aware (B1-F2-F4/B1-F2-F4-R1).

    Generic over WHICH TWO surfaces are compared -- named `legacy_surface`/
    `new_surface`, not `py_surface`/`rs_surface`, because B1-F2-F4-R1 reuses
    this one function for TWO axes: `_measure()` and `compare()`'s
    after-parity loop call it intra-document (Python plays `legacy_surface`,
    Rust plays `new_surface`); `compare()`'s before/after loop calls it
    inter-snapshot (before-Rust plays `legacy_surface`, after-Rust plays
    `new_surface`) -- see p037_b_classifier.explain_divergence's own
    docstring for the same genericity one layer down. Either way the
    question is identical: does `new_surface` diverge from `legacy_surface`,
    and if so is the WHOLE divergence explained by a classified witness.

    epoch 'a2d': byte-for-byte the ORIGINAL, unconditional policy -- ANY
    divergence is unexplained. A1/A2's own contract is zero MOS movement,
    full stop; there is no legitimate reason for either axis to differ, so
    this module must never even ATTEMPT to explain one away here.

    epoch 'b': the accepted post-Stage-3 contract (docs/evidence/
    p037-b-epoch.json's prerequisite_discharged.engine_scope_consequence;
    p037_controls.py's own docstring, "both agreeing is an OBSERVATION, not
    a contract") means Python (legacy/reference/rollback) is EXPECTED to
    diverge from Rust (sole guarded-summary authority) on the treatment
    slice, and Rust's own before/after movement is expected once a
    treatment lands. A divergence is therefore CAPTURED, explained via
    p037_b_classifier.derive_document_witnesses/explain_divergence against
    the two whole summaries documents, and accepted as evidence ONLY when
    every last byte of the difference is accounted for by a witness
    classified into one of the three closed classes -- never merely "the
    engines disagree, and Phase B expects that now". An unexplained
    divergence (any UNCLASSIFIED witness, or a difference outside what any
    witness can explain at all -- see explain_divergence's own docstring)
    still fails the snapshot, exactly as it always did.
    """
    if legacy_surface == new_surface:
        return {"moved": False}
    if epoch != "b":
        return {"moved": True}
    legacy_doc = (legacy_surface.get("document")
                 if legacy_surface.get("status") == "produced" else None)
    new_doc = new_surface.get("document") if new_surface.get("status") == "produced" else None
    if not isinstance(legacy_doc, dict) or not isinstance(new_doc, dict):
        return {"moved": True, "reason": "one or both sides refused; no document to explain"}
    explanation = p037_b_classifier.explain_divergence(legacy_doc, new_doc)
    return {"moved": not explanation["explained"], "classified_divergence": explanation}


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


def take(epoch: str, source: str, out: Path, timeout: float, population_commit: str) -> int:
    roots = _sources(ev)[source]
    try:
        _refuse(ev.scratch_problems(out))
        provenance = ev.evidence_fields(roots, population_commit=population_commit)
        if provenance["dirty"]:
            raise ev.EvidenceRefused("the tree is dirty before the run; evidence starts clean")
        profile = ev.execution_profile(include_rust=True)
        artifact = ev.build_rust_artifact("own-shadow", "own-shadow-engine")
        _refuse(ev.artifact_problems(artifact))
        lease = ev.acquire_population(ev.materialization_root(
            provenance["population_commit"], provenance["analysis_manifest_sha256"]))
    except (RuntimeError, SystemExit, ev.EvidenceRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    take_dir = ev.new_take_dir()
    try:
        return _measure(epoch, source, out, timeout, provenance, profile, artifact, take_dir)
    finally:
        ev.release_population(lease)
        shutil.rmtree(take_dir, ignore_errors=True)


def _measure(
    epoch: str,
    source: str,
    out: Path,
    timeout: float,
    provenance: dict[str, Any],
    profile: dict[str, Any],
    artifact: dict[str, Any],
    take_dir: Path,
) -> int:
    try:
        # The run executes the SEALED copy only; target/release/ is shared and
        # any later cargo build may rewrite it mid-run.
        ev.seal_artifact(artifact, take_dir)
        adapter = engine_identity(str(artifact["executed"]["sealed_path"]))
        if adapter["sha256"] != artifact["sha256"]:
            raise ev.EvidenceRefused("the adapter about to run is not the qualified build")
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
    failed_ids: set[str] = set()
    parity_moved: list[str] = []
    classified_divergences: dict[str, Any] = {}
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
            status = divergence_status(epoch, py_surface, rs_surface)
            if status["moved"]:
                parity_moved.append(doc_id)
            if "classified_divergence" in status:
                record["classified_divergence"] = status["classified_divergence"]
                classified_divergences[doc_id] = status["classified_divergence"]
        except ReferenceContamination as exc:
            reference_profile["observed_extra_reference_lines"] = (
                int(reference_profile["observed_extra_reference_lines"]) + len(exc.lines)
            )
            failures.append(f"{doc_id}: {exc}")
            failed_ids.add(doc_id)
            record = {"inputs": rels, "error": str(exc)}
        except (RuntimeError, ExecutionFailure) as exc:
            failures.append(f"{doc_id}: {exc}")
            failed_ids.add(doc_id)
            record = {"inputs": rels, "error": str(exc)}
        snapshot["documents"][doc_id] = record
        print(
            f"  [{i:3}/{len(documents)}] {doc_id} ({len(paths)} source file(s))",
            flush=True,
        )

    ev.finalize_run(snapshot, provenance, root)
    if failures or parity_moved:
        snapshot["is_evidence"] = False
    if failures:
        snapshot["failures"] = failures
    if parity_moved:
        snapshot["cross_engine_mismatches"] = parity_moved
    if classified_divergences:
        snapshot["classified_divergences"] = classified_divergences
    if epoch == "b":
        # B1-F2-F4 §4: the Python rollback contract, named and counted, not
        # left for a reader to infer from set differences. "rollback still
        # works" (Python stays exact on the unaffected sample) is a
        # different claim from "rollback produces new Rust semantics"
        # (never required, never measured here): a document belongs to
        # EXACTLY one bucket -- exact (no divergence at all), classified
        # (a treatment-slice divergence every witness explained), or
        # unexplained (counted in cross_engine_mismatches above, already
        # failing is_evidence).
        explained_ids = set(classified_divergences) - set(parity_moved)
        exact_ids = (set(snapshot["documents"]) - set(classified_divergences)
                    - set(parity_moved) - failed_ids)
        snapshot["python_rollback_observation"] = {
            "unaffected_sample_exact": len(exact_ids),
            "treatment_slice_classified": len(explained_ids),
            "unexplained": len(set(parity_moved)),
            "extraction_failed": len(failed_ids),
        }

    out.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"snapshot: {len(documents)} document(s) / {len(files)} source file(s), source={source}, "
        f"population={provenance['population_commit'][:12]}, "
        f"cross-engine mismatches={len(parity_moved)}, "
        f"classified divergences={len(classified_divergences)}, failures={len(failures)}, "
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


def _compare_documents(
    epoch: str, a_documents: dict[str, Any], b_documents: dict[str, Any]
) -> dict[str, Any]:
    """The epoch-aware before/after decision over two snapshots' `documents`
    maps alone (B1-F2-F4-R1) -- factored out of `compare()` so it is
    directly unit-testable without fabricating a full provenance-carrying
    snapshot pair (population/source commit, analysis manifest, artifacts,
    ...) for every scenario; `compare()` itself only adds the I/O,
    provenance checks, printing and exit code around this pure function.

    Two independent axes, both epoch-aware, matching `divergence_status()`'s
    own dual reuse:

    - Python axis (legacy/reference/rollback): under epoch b, movement is
      accepted ONLY as a direct mechanical consequence of the raw `facts`
      hash ALSO moving on the same document -- never independently. Epoch
      a2d keeps the original unconditional zero-movement policy.
    - Rust axis (sole P-037 semantic authority): under epoch b, movement is
      accepted only when `divergence_status()`/`explain_divergence()`
      explains the WHOLE before/after difference, with before-Rust as the
      reference ("legacy") role and after-Rust as the value a `guarded`
      field must justify -- the SAME whole-document classifier discipline
      already required for intra-after divergence (`after_parity` below),
      never a separate, looser rule for this axis. Epoch a2d never attempts
      this either.

    `after_parity`/`after_parity_classified` are the AFTER snapshot's OWN
    intra-document Python-vs-Rust divergence, unchanged from B1-F2-F4.
    """
    moved: dict[str, list[str]] = {ENGINE_PYTHON: [], ENGINE_RUST: [], "facts": []}
    rust_moved_classified: list[str] = []
    python_moved_rollback: list[str] = []
    names = sorted(set(a_documents) | set(b_documents))
    for rel in names:
        left = a_documents.get(rel)
        right = b_documents.get(rel)
        if not isinstance(left, dict) or not isinstance(right, dict):
            moved[ENGINE_PYTHON].append(rel)
            moved[ENGINE_RUST].append(rel)
            moved["facts"].append(rel)
            continue
        facts_moved = left.get("facts") != right.get("facts")
        if facts_moved:
            moved["facts"].append(rel)

        left_py, right_py = left.get(ENGINE_PYTHON), right.get(ENGINE_PYTHON)
        if left_py != right_py:
            if (epoch != "b" or not facts_moved
                    or not isinstance(left_py, dict) or not isinstance(right_py, dict)):
                moved[ENGINE_PYTHON].append(rel)
            else:
                python_moved_rollback.append(rel)

        left_rust, right_rust = left.get(ENGINE_RUST), right.get(ENGINE_RUST)
        if left_rust != right_rust:
            if (epoch != "b"
                    or not isinstance(left_rust, dict) or not isinstance(right_rust, dict)):
                moved[ENGINE_RUST].append(rel)
            else:
                status = divergence_status(epoch, left_rust, right_rust)
                if status["moved"]:
                    moved[ENGINE_RUST].append(rel)
                else:
                    rust_moved_classified.append(rel)

    after_parity: list[str] = []
    after_parity_classified: list[str] = []
    for rel, rec in b_documents.items():
        if not isinstance(rec, dict):
            continue
        py_surface, rs_surface = rec.get(ENGINE_PYTHON), rec.get(ENGINE_RUST)
        if py_surface == rs_surface:
            continue
        if not isinstance(py_surface, dict) or not isinstance(rs_surface, dict):
            after_parity.append(rel)
            continue
        status = divergence_status(epoch, py_surface, rs_surface)
        if status["moved"]:
            after_parity.append(rel)
        else:
            after_parity_classified.append(rel)

    failed = bool(moved[ENGINE_PYTHON] or moved[ENGINE_RUST] or after_parity)
    return {
        "names": names,
        "moved": moved,
        "python_moved_rollback": python_moved_rollback,
        "rust_moved_classified": rust_moved_classified,
        "after_parity": after_parity,
        "after_parity_classified": after_parity_classified,
        "failed": failed,
    }


def compare(epoch: str, before: Path, after: Path, against: str) -> int:
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

    result = _compare_documents(epoch, a.get("documents", {}), b.get("documents", {}))
    moved, names = result["moved"], result["names"]
    python_moved_rollback = result["python_moved_rollback"]
    rust_moved_classified = result["rust_moved_classified"]
    after_parity = result["after_parity"]
    after_parity_classified = result["after_parity_classified"]

    for engine in (ENGINE_PYTHON, ENGINE_RUST):
        for rel in moved[engine]:
            print(f"  MOVED[{engine}] {rel}")
    for rel in python_moved_rollback:
        print(f"  MOVED[{ENGINE_PYTHON}, ROLLBACK] {rel}")
    for rel in rust_moved_classified:
        print(f"  MOVED[{ENGINE_RUST}, CLASSIFIED] {rel}")
    for rel in moved["facts"]:
        print(f"  FACT-DIFF {rel}")
    for rel in after_parity:
        print(f"  PARITY-DIFF[after] {rel}")
    for rel in after_parity_classified:
        print(f"  PARITY-DIFF[after, CLASSIFIED] {rel}")

    failed = result["failed"]
    print(
        "RESULT: "
        + ("MOVED" if failed else "UNCHANGED")
        + f" — source={a.get('source')}, population={str(a.get('population_commit'))[:12]}, "
          f"documents={len(names)}, facts_moved={len(moved['facts'])}, "
          f"python_mos_moved={len(moved[ENGINE_PYTHON])}, "
          f"python_mos_moved_rollback={len(python_moved_rollback)}, "
          f"rust_mos_moved={len(moved[ENGINE_RUST])}, "
          f"rust_mos_moved_classified={len(rust_moved_classified)}, "
          f"after_parity_moved={len(after_parity)}, "
          f"after_parity_classified={len(after_parity_classified)}"
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

    # --- B1-F2-F4: divergence_status() epoch-aware policy ---
    identical = {"status": "produced", "document": {
        "summaries": [{"method": "M", "params": [{"index": 0, "transfer": "may"}]}],
        "unresolved": [], "degraded": None,
    }}
    twin2 = json.loads(json.dumps(identical))
    status = divergence_status("a2d", identical, twin2)
    if status["moved"]:
        print("FAIL[selftest]: identical surfaces reported as moved")
        return 1

    diverged = json.loads(json.dumps(identical))
    diverged["document"]["summaries"][0]["params"][0]["transfer"] = "must"

    status = divergence_status("a2d", identical, diverged)
    if not status["moved"] or "classified_divergence" in status:
        print(f"FAIL[selftest]: epoch a2d must reject ANY divergence unconditionally: {status}")
        return 1

    status = divergence_status("b", identical, diverged)
    if not status["moved"]:
        print(f"FAIL[selftest]: epoch b with no guarded field must still be unexplained: {status}")
        return 1
    if "classified_divergence" not in status:
        print(f"FAIL[selftest]: epoch b must attempt and record classification: {status}")
        return 1

    justified = json.loads(json.dumps(diverged))
    justified["document"]["summaries"][0]["params"][0]["guarded"] = {
        "shape": "split", "selection": "unselected", "selection_license": None,
        "finalized_cells": {"pos": "must", "neg": "must"}, "collapsed": "must",
    }
    status = divergence_status("b", identical, justified)
    if status["moved"]:
        print(f"FAIL[selftest]: epoch b with a classified, fully-explained divergence "
             f"must be accepted: {status}")
        return 1

    refused = {"status": "refused", "error": "solver failed"}
    status = divergence_status("b", identical, refused)
    if not status["moved"]:
        print("FAIL[selftest]: epoch b cannot classify a refused engine as explained")
        return 1

    print("OK: divergence_status() is epoch-aware (a2d unconditional, b classified)")

    # --- B1-F2-F4-R1: _compare_documents(), the before/after MOS decision.
    # An independent review found compare() classified intra-after
    # divergence (above) but still used bare, epoch-blind inequality for
    # its OWN before/after axis -- so a real R_B-vs-B_after comparison would
    # have reported MOVED/failure even when the movement was fully
    # classified. These three scenarios are the ones that review required. ---
    def _rust_doc(transfer: str, guarded: dict[str, Any] | None = None,
                  unresolved: list[str] | None = None) -> dict[str, Any]:
        param: dict[str, Any] = {"index": 0, "transfer": transfer}
        if guarded is not None:
            param["guarded"] = guarded
        return {"status": "produced", "document": {
            "summaries": [{"method": "M", "params": [param]}],
            "unresolved": list(unresolved or []), "degraded": None,
        }}

    py_unmoved = _rust_doc("may")
    before_doc = {"inputs": ["m.cs"], "facts": "F1",
                 ENGINE_PYTHON: py_unmoved, ENGINE_RUST: _rust_doc("may")}
    refined_guard = {"shape": "split", "selection": "unselected", "selection_license": None,
                     "finalized_cells": {"pos": "must", "neg": "must"}, "collapsed": "must"}

    # Scenario 1: classified B refinement -- Rust alone moves may -> must,
    # justified by a split-summary guarded field (SUMMARY_REFINEMENT).
    # Python and the raw facts hash stay byte-identical.
    after_classified = {"inputs": ["m.cs"], "facts": "F1", ENGINE_PYTHON: py_unmoved,
                       ENGINE_RUST: _rust_doc("must", guarded=refined_guard)}
    r = _compare_documents("b", {"m.cs": before_doc}, {"m.cs": after_classified})
    if r["failed"] or "m.cs" not in r["rust_moved_classified"]:
        print(f"FAIL[selftest]: epoch b must PASS a classified Rust refinement: {r}")
        return 1
    r = _compare_documents("a2d", {"m.cs": before_doc}, {"m.cs": after_classified})
    if not r["failed"] or "m.cs" not in r["moved"][ENGINE_RUST]:
        print(f"FAIL[selftest]: epoch a2d must reject the SAME movement unconditionally: {r}")
        return 1
    print("OK: _compare_documents() PASSes a classified Rust refinement under epoch b, "
         "FAILs the identical movement under epoch a2d")

    # Scenario 2: the SAME transfer movement with no guarded field to
    # justify it -- classify() has nothing to work with (UNCLASSIFIED),
    # must still FAIL even under epoch b.
    after_unclassified = {"inputs": ["m.cs"], "facts": "F1", ENGINE_PYTHON: py_unmoved,
                         ENGINE_RUST: _rust_doc("must")}
    r = _compare_documents("b", {"m.cs": before_doc}, {"m.cs": after_unclassified})
    if not r["failed"] or "m.cs" not in r["moved"][ENGINE_RUST]:
        print(f"FAIL[selftest]: an unclassified Rust refinement must FAIL under epoch b: {r}")
        return 1
    print("OK: _compare_documents() FAILs an unclassified Rust before/after movement")

    # Scenario 3: the SAME classified transfer movement PLUS an unrelated
    # residual movement (unresolved[] gains an entry) -- explain_divergence's
    # whole-document discipline must refuse this exactly as it already does
    # for intra-after divergence; a classified witness never excuses a
    # difference outside what it names.
    after_residual = {"inputs": ["m.cs"], "facts": "F1", ENGINE_PYTHON: py_unmoved,
                     ENGINE_RUST: _rust_doc("must", guarded=refined_guard,
                                           unresolved=["SomeExtern"])}
    r = _compare_documents("b", {"m.cs": before_doc}, {"m.cs": after_residual})
    if not r["failed"] or "m.cs" not in r["moved"][ENGINE_RUST]:
        print(f"FAIL[selftest]: a classified change plus an unrelated residual movement "
             f"must still FAIL: {r}")
        return 1
    print("OK: _compare_documents() FAILs a classified change riding alongside an "
         "unrelated residual movement")

    # Python axis: legacy/reference/rollback engine. Movement with the raw
    # facts hash UNCHANGED must FAIL (never an independent legacy movement);
    # movement WITH the facts hash also moving is the accepted mechanical
    # rollback consequence -- but only under epoch b, never a2d.
    py_moved_alone = {"inputs": ["m.cs"], "facts": "F1", ENGINE_PYTHON: _rust_doc("no")}
    r = _compare_documents("b", {"m.cs": before_doc}, {"m.cs": py_moved_alone})
    if "m.cs" not in r["moved"][ENGINE_PYTHON]:
        print(f"FAIL[selftest]: Python moving with facts UNCHANGED must FAIL under epoch b: {r}")
        return 1
    py_moved_with_facts = {"inputs": ["m.cs"], "facts": "F2", ENGINE_PYTHON: _rust_doc("no")}
    r = _compare_documents("b", {"m.cs": before_doc}, {"m.cs": py_moved_with_facts})
    if "m.cs" in r["moved"][ENGINE_PYTHON] or "m.cs" not in r["python_moved_rollback"]:
        print(f"FAIL[selftest]: Python moving WITH facts must be accepted as rollback: {r}")
        return 1
    r = _compare_documents("a2d", {"m.cs": before_doc}, {"m.cs": py_moved_with_facts})
    if "m.cs" not in r["moved"][ENGINE_PYTHON]:
        print(f"FAIL[selftest]: epoch a2d must reject Python movement even WITH facts moving: {r}")
        return 1
    print("OK: _compare_documents() gates Python before/after movement on the raw facts "
         "hash also moving, only under epoch b")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("take")
    t.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    t.add_argument("--source", required=True, choices=SOURCE_NAMES)
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--population-commit", default="HEAD",
                   help="the commit whose blobs are analysed (default HEAD; the after "
                        "side of a pair names the baseline's commit)")
    t.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    c = sub.add_parser("compare")
    c.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--against", default="HEAD",
                   help="the commit the after side must be fresh at (default HEAD)")
    v = sub.add_parser("verify")
    v.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    v.add_argument("snapshot", type=Path)
    v.add_argument("--against", default="HEAD")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd in ("take", "compare", "verify"):
        global ev
        ev = EPOCH_MODULES[args.epoch]
    if args.cmd == "take":
        return take(args.epoch, args.source, args.out, args.timeout, args.population_commit)
    if args.cmd == "compare":
        return compare(args.epoch, args.before, args.after, args.against)
    if args.cmd == "verify":
        return verify(args.snapshot, args.against)
    ap.error("one command is required (or --selftest)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
