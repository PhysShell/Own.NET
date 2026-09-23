#!/usr/bin/env python3
"""Phase-B provenance contract for P-037 step evidence (B1).

Same PURPOSE as scripts/p037_evidence.py's own module docstring (a
differential -- or here, a baseline -- can only carry its claim when it
measured ONE frozen population with ONE qualified instrument in ONE
qualified execution environment, and only the declared treatment moved),
but NOT that module repointed at a different epoch record: p037_evidence.py
hardcodes `EPOCH = "a2d"` and `EPOCH_RECORD_PATH = "docs/evidence/p037-a2d-
epoch.json"` at module scope, and eleven of its functions (epoch_record,
closure_problems, evidence_fields, record_problems, provenance_problems,
comparison_problems, instrument_pathspec, instrument_manifest, ...) read
those constants directly -- there is no parameter that redirects them, and
that module is ITSELF one of a2d's own INSTRUMENT_PATHS, pinned by
tests/test_p037_evidence.py's fourteen negative controls. Phase B is also a
DIFFERENT SHAPE: Rust-only (no python door), a different crate
(rust/crates/own-bridge/, not rust/crates/own-ir/), and its treatment
carve-out is inside files that also hold frozen items -- p037_b_production_
diff_gate.py, not file-level pathspec diffing, is the authoritative
boundary there; this module's own TREATMENT_PATHS is deliberately the same
coarse, file-level unit p037-b-epoch.json's candidate_scope names (mos.rs,
lower.rs, in full), exactly as a2d's own TREATMENT_PATHS is wider than its
door and the *door gate* is the boundary within it.

This module therefore does NOT edit p037_evidence.py (Strategy A: a new,
sibling contract owning epoch b's own closure) -- it IMPORTS that module's
generic, parameter-driven mechanics unchanged: population materialization
(population_fields/materialize_population/population_intact/analysis_paths/
acquire_population/release_population), execution-profile capture
(execution_profile/rust_identity/_dotnet_runtimes), artifact build/seal
(build_rust_artifact/artifact_problems/seal_artifact/executed_artifact_
problems/new_take_dir/finalize_run), environment sanitization (sanitized_
env/reference_contamination/clean_reference_profile/reference_profile_
problems), git plumbing (commit_exists/resolve_commit/is_ancestor/
paths_differ/tree_is_dirty/current_commit) and manifest digesting
(analysis_manifest/support_manifest/_manifest_digest) -- none of which read
EPOCH/EPOCH_RECORD_PATH/INSTRUMENT_PATHS/TREATMENT_PATHS internally. Zero
bytes of p037_evidence.py move for this module to exist.

Snapshot validity vocabulary matches p037_evidence.py's own (record_
problems: one record is self-consistent at its own commit; provenance_
problems: ...and fresh at a given HEAD). comparison_problems has no B1
equivalent here: B1 takes a BASELINE (R_B), not a before/after pair -- a
Phase-B comparison function is a later, B-after-time addition, built once
there is a second take to compare against the first.

Run:  python scripts/p037_evidence_b.py profile
      python scripts/p037_evidence_b.py identity [--commit <rev>]
      python scripts/p037_evidence_b.py population --source repo|corpus [--commit <rev>]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Reused verbatim from p037_evidence.py -- generic, parameter-driven, no a2d
# module constant read by any of these names. See module docstring.
import p037_evidence as ev  # noqa: E402

EvidenceRefused = ev.EvidenceRefused

EPOCH = "b"
EPOCH_RECORD_PATH = "docs/evidence/p037-b-epoch.json"

FACT_DIFF_POLICIES: frozenset[str] = frozenset({"not_applicable_pre_treatment"})

# What we measure WITH: the same broad roots a2d measured with (this crate's
# whole rust/ tree, ownlang/, the extractor, the shared p037_* scripts),
# minus the Phase-B treatment carve-out -- mirroring a2d's own
# INSTRUMENT_PATHS/INSTRUMENT_CARVE_OUTS/TREATMENT_PATHS shape exactly, one
# level down: own-bridge's mos.rs/lower.rs are now the carved-out door,
# where own-ir's whole crate was a2d's.
INSTRUMENT_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    ev.OWN_CHECK_PATH,
    "scripts/p037_evidence.py",
    "scripts/p037_evidence_b.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
    "scripts/p037_b_production_diff_gate.py",
)

INSTRUMENT_CARVE_OUTS: tuple[str, ...] = (
    "rust/crates/own-bridge/src/mos.rs",
    "rust/crates/own-bridge/src/lower.rs",
)

TREATMENT_PATHS: tuple[str, ...] = INSTRUMENT_CARVE_OUTS

SUBJECT_PATHS: tuple[str, ...] = INSTRUMENT_PATHS

RUNTIME_REPO_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    ev.OWN_CHECK_PATH,
    "scripts/p037_evidence.py",
    "scripts/p037_evidence_b.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
    "scripts/p037_b_production_diff_gate.py",
)

# a2d's own CORPUS_DIRS plus the fact-shape census -- section 7 of the B1
# brief names both the bakeoff controls and the fact-shape census as
# populations to freeze; a2d's list never needed the census because A2.1/
# A2.2 already anchored it directly.
CORPUS_DIRS: tuple[str, ...] = (*ev.CORPUS_DIRS, "corpus/p037-shapes")
REPO_TREE_DIRS: tuple[str, ...] = ev.REPO_TREE_DIRS


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _covered(path: str, roots: Any) -> bool:
    p = _norm(path)
    for root in roots:
        r = _norm(root)
        if p == r or p.startswith(r + "/"):
            return True
    return False


def epoch_record(commit: str = "HEAD", *, repo: Path = ROOT) -> dict[str, Any]:
    """The frozen Phase-B epoch record as committed at ``commit``, never the
    working copy. Refused unless it names epoch 'b' and a non-empty
    environment id."""
    proc = ev._git("show", f"{commit}:{EPOCH_RECORD_PATH}", repo=repo)
    if proc.returncode != 0:
        raise EvidenceRefused(
            f"no epoch record {EPOCH_RECORD_PATH} at {commit[:12]}: a {EPOCH} take needs one")
    try:
        doc = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceRefused(f"epoch record at {commit[:12]} is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise EvidenceRefused(f"epoch record at {commit[:12]} is not an object")
    if doc.get("epoch") != EPOCH:
        raise EvidenceRefused(
            f"epoch record at {commit[:12]} names epoch {doc.get('epoch')!r}; this module "
            f"measures {EPOCH!r} and nothing else")
    env = doc.get("environment", {})
    if not isinstance(env, dict) or not env.get("id"):
        raise EvidenceRefused(f"epoch record at {commit[:12]} names no environment id")
    return doc


def environment_id(commit: str = "HEAD", *, repo: Path = ROOT) -> str:
    return str(epoch_record(commit, repo=repo)["environment"]["id"])


def _record_closure_problems(doc: dict[str, Any]) -> list[str]:
    gate = doc.get("production_diff_gate", {})
    rust = gate.get("rust", {}) if isinstance(gate, dict) else {}
    recorded_unit = rust.get("unit") if isinstance(rust, dict) else None
    if recorded_unit != "rust/crates/own-bridge/":
        return [f"the epoch record's production_diff_gate.rust.unit "
                f"{recorded_unit!r} differs from this module's own"]
    return []


def closure_problems(*, repo: Path = ROOT) -> list[str]:
    """Static self-check: every repo-local runtime path is in the closure,
    the carve-outs are treatment under instrument roots, and HEAD's epoch
    record agrees with this module on the production-diff gate's unit."""
    problems: list[str] = []
    for path in RUNTIME_REPO_PATHS:
        if not _covered(path, SUBJECT_PATHS):
            problems.append(
                f"runtime path {path!r} is outside SUBJECT_PATHS; a measurement "
                "could change without invalidating its evidence")
        if ev._git("cat-file", "-e", f"HEAD:{_norm(path)}", repo=repo).returncode != 0:
            problems.append(
                f"runtime path {path!r} is declared but does not exist in HEAD; "
                "a misspelled dependency would otherwise protect an empty path")
    if len(set(SUBJECT_PATHS)) != len(SUBJECT_PATHS):
        problems.append("SUBJECT_PATHS contains duplicate entries")
    for carve in INSTRUMENT_CARVE_OUTS:
        if not _covered(carve, INSTRUMENT_PATHS):
            problems.append(f"carve-out {carve!r} lies under no instrument root")
        if carve not in TREATMENT_PATHS:
            problems.append(f"carve-out {carve!r} is not declared as treatment")
    for path in TREATMENT_PATHS:
        if not _covered(path, SUBJECT_PATHS):
            problems.append(f"treatment path {path!r} is outside SUBJECT_PATHS")
    try:
        problems.extend(_record_closure_problems(epoch_record("HEAD", repo=repo)))
    except EvidenceRefused as exc:
        problems.append(str(exc))
    return problems


def evidence_fields(
    input_roots: tuple[str, ...],
    *,
    population_commit: str = "HEAD",
    source_commit: str | None = None,
    repo: Path = ROOT,
) -> dict[str, Any]:
    """Provenance fields of a Phase-B snapshot taken at ``source_commit``
    (HEAD). Mirrors p037_evidence.evidence_fields's own shape and field
    names exactly, so p037_mos_snapshot.py/p037_verdict_snapshot.py's
    existing `take()` bodies can build a record from either module by
    calling the same-named function."""
    problems = closure_problems(repo=repo)
    if problems:
        raise EvidenceRefused("; ".join(problems))
    source = ev.resolve_commit(source_commit or "HEAD", repo=repo)
    dirty = ev.tree_is_dirty(repo=repo)
    population = ev.population_fields(population_commit, input_roots, repo=repo)
    if not ev.is_ancestor(population["population_commit"], source, repo=repo):
        raise EvidenceRefused(
            f"population commit {population['population_commit'][:12]} is not an ancestor "
            f"of (or equal to) source commit {source[:12]}")
    record = epoch_record(source, repo=repo)
    return {
        "source_commit": source,
        "dirty": dirty,
        "is_evidence": not dirty,
        "epoch": EPOCH,
        "environment_id": str(record["environment"]["id"]),
        "epoch_record": {
            "path": EPOCH_RECORD_PATH,
            "blob": ev._git_text(
                "rev-parse", f"{source}:{EPOCH_RECORD_PATH}", repo=repo),
        },
        "instrument_paths": list(INSTRUMENT_PATHS),
        "instrument_carve_outs": list(INSTRUMENT_CARVE_OUTS),
        "treatment_paths": list(TREATMENT_PATHS),
        "instrument_identity": ev.instrument_manifest(
            source, repo=repo) and ev._manifest_digest(
            ev.instrument_manifest(source, repo=repo)),
        **population,
    }


def record_problems(record: dict[str, Any], *, repo: Path = ROOT) -> list[str]:
    """Self-consistency of one Phase-B evidence record at its OWN source
    commit -- same clauses as p037_evidence.record_problems, epoch 'b'."""
    problems: list[str] = []
    source = record.get("source_commit")
    if not isinstance(source, str) or not source:
        return ["evidence records no source_commit"]
    if record.get("dirty") is not False:
        problems.append("evidence was taken on a dirty tree")
    if record.get("is_evidence") is not True:
        problems.append("record does not mark itself is_evidence=true")
    if record.get("post_run_dirty"):
        problems.append("the tree was dirty after the measurement")
    if record.get("post_run_population_intact") is not True:
        problems.append(
            "record does not attest that the population stayed intact through the run")
    epoch = record.get("epoch")
    if epoch is None:
        problems.append(f"record carries no epoch: it predates {EPOCH} and is not eligible")
    elif epoch != EPOCH:
        problems.append(f"record names epoch {epoch!r}, not {EPOCH!r}")
    if not ev.commit_exists(source, repo=repo):
        return [*problems, f"source commit {source[:12]} is not present in this checkout"]
    if not isinstance(record.get("instrument_carve_outs"), list) or (
            set(record["instrument_carve_outs"]) != set(INSTRUMENT_CARVE_OUTS)):
        problems.append("record's instrument_carve_outs differs from this module's own")
    env_id = record.get("environment_id")
    try:
        want_env = environment_id(source, repo=repo)
    except EvidenceRefused as exc:
        problems.append(str(exc))
    else:
        if env_id != want_env:
            problems.append(
                f"record names environment {env_id!r}, not the epoch record's {want_env!r}")
    root = record.get("materialized_root")
    if isinstance(root, str) and root:
        tampered = ev.population_intact(record, Path(root), repo=repo)
        problems.extend(tampered)
    return problems


def provenance_problems(
    record: dict[str, Any], *, against: str = "HEAD", repo: Path = ROOT
) -> list[str]:
    """Whether ``record`` is fresh evidence at ``against``: self-valid, an
    ancestor, and neither instrument nor treatment moved in between."""
    problems = [*closure_problems(repo=repo), *record_problems(record, repo=repo)]
    source = record.get("source_commit")
    if not isinstance(source, str) or not source or not ev.commit_exists(source, repo=repo):
        return problems
    if not ev.commit_exists(against, repo=repo):
        return [*problems, f"comparison commit {against!r} is not present in this checkout"]
    if not ev.is_ancestor(source, against, repo=repo):
        problems.append(
            f"source commit {source[:12]} is not an ancestor of {against}; "
            "the evidence describes a history this tree does not contain")
        return problems
    try:
        pathspec = [*INSTRUMENT_PATHS, *(f":(exclude){c}" for c in INSTRUMENT_CARVE_OUTS)]
        if ev.paths_differ(source, against, pathspec, repo=repo):
            problems.append(
                f"the measurement instrument changed between {source[:12]} and {against}; "
                "re-take the evidence")
    except EvidenceRefused as exc:
        problems.append(str(exc))
    return problems


# --------------------------------------------------------------------------- CLI


def _cli_identity(commit: str) -> int:
    problems = closure_problems()
    for problem in problems:
        print(f"CLOSURE PROBLEM: {problem}", file=sys.stderr)
    if problems:
        return 2
    try:
        record = epoch_record(commit)
    except EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "epoch": EPOCH,
        "environment_id": record["environment"]["id"],
        "instrument_paths": list(INSTRUMENT_PATHS),
        "instrument_carve_outs": list(INSTRUMENT_CARVE_OUTS),
        "treatment_paths": list(TREATMENT_PATHS),
    }, indent=1, sort_keys=True))
    return 0


def _cli_population(source: str, commit: str, materialize: bool, cleanup: bool) -> int:
    roots = {"corpus": CORPUS_DIRS, "repo": REPO_TREE_DIRS}[source]
    fields = ev.population_fields(commit, roots)
    analysis = fields["analysis_manifest"]
    print(json.dumps({"population_commit": fields["population_commit"],
                      "files": len(analysis), "digest": ev._manifest_digest(analysis)},
                     indent=1, sort_keys=True))
    if not materialize:
        return 0
    root = ev.materialize_population(fields)
    print(f"materialized at {root}")
    if cleanup:
        import shutil as _shutil
        _shutil.rmtree(root, ignore_errors=True)
        print("cleaned up")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile")
    p.set_defaults(func=lambda _a: (
        print(json.dumps(ev.execution_profile(include_rust=shutil.which("cargo") is not None),
                         indent=1, sort_keys=True)), 0)[1])

    p = sub.add_parser("identity")
    p.add_argument("--commit", default="HEAD")
    p.set_defaults(func=lambda a: _cli_identity(a.commit))

    p = sub.add_parser("population")
    p.add_argument("--source", choices=("repo", "corpus"), required=True)
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--materialize", action="store_true")
    p.add_argument("--cleanup", action="store_true")
    p.set_defaults(func=lambda a: _cli_population(a.source, a.commit, a.materialize, a.cleanup))

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
