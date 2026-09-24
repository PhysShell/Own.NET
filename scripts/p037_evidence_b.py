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
DIFFERENT SHAPE: two treatment units, not one -- rust/crates/own-bridge/'s
mos.rs/lower.rs (item-level boundary: p037_b_production_diff_gate.py) and,
since B1-F2, frontend/roslyn/OwnSharp.Extractor/'s three-function legacy-
consume-shortcut seam (item-level boundary: p037_b_extractor_diff_gate.py)
-- neither is a python door, and both carve-outs sit inside a unit that
also holds frozen items, so file-level pathspec diffing alone is never the
authoritative boundary for either; this module's own TREATMENT_PATHS is
deliberately the same coarse, file/directory-level union both item gates'
own units name (mos.rs, lower.rs, and the whole extractor directory, each
in full), exactly as a2d's own TREATMENT_PATHS is wider than its doors and
the *door gate* is the boundary within them.

B1 originally classified the whole extractor as measurement INSTRUMENT
with no carve-out at all, even though the frozen A1 acceptance matrix
(docs/notes/p037-formal-kernel.md #8.1, items 5 and 8) requires an eventual
extractor-side semantic change there -- a treatment surface cannot
simultaneously be frozen measurement instrument. B1-F2 is the repair: this
module's own INSTRUMENT_CARVE_OUTS/TREATMENT_PATHS now carve the whole
extractor directory out, the same way mos.rs/lower.rs already were,
relying on p037_b_extractor_diff_gate.py to close the resulting hole at
item granularity. This module still does NOT change what the extractor
does -- see that gate's own module docstring for the exact seam and the
standing prohibition on a second guarded-summary engine written inside
Roslyn.

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

# Re-exported verbatim so this module is a full drop-in for `ev` wherever a
# caller's code (unchanged) reaches for one of these names -- see
# scripts/p037_mos_snapshot.py and scripts/p037_verdict_snapshot.py's
# --epoch dispatch, which rebinds their module-global `ev` to this module or
# to p037_evidence and calls the same, already-written take()/_measure()
# bodies either way. None of these read EPOCH/EPOCH_RECORD_PATH/
# INSTRUMENT_PATHS internally (see module docstring), so aliasing them here
# moves zero bytes of logic and adds none.
scratch_problems = ev.scratch_problems
execution_profile = ev.execution_profile
build_rust_artifact = ev.build_rust_artifact
artifact_problems = ev.artifact_problems
acquire_population = ev.acquire_population
release_population = ev.release_population
materialization_root = ev.materialization_root
new_take_dir = ev.new_take_dir
seal_artifact = ev.seal_artifact
materialize_population = ev.materialize_population
external_ancestor_problems = ev.external_ancestor_problems
analysis_paths = ev.analysis_paths
sanitized_env = ev.sanitized_env
clean_reference_profile = ev.clean_reference_profile
finalize_run = ev.finalize_run
reference_contamination = ev.reference_contamination

EPOCH = "b"
EPOCH_RECORD_PATH = "docs/evidence/p037-b-epoch.json"

FACT_DIFF_POLICIES: frozenset[str] = frozenset({"not_applicable_pre_treatment"})

# What we measure WITH: the same broad roots a2d measured with (this crate's
# whole rust/ tree, ownlang/, the extractor, the shared p037_* scripts),
# minus the Phase-B treatment carve-outs -- mirroring a2d's own
# INSTRUMENT_PATHS/INSTRUMENT_CARVE_OUTS/TREATMENT_PATHS shape exactly, one
# level down: own-bridge's mos.rs/lower.rs and (since B1-F2) the whole
# extractor directory are now the carved-out doors, where own-ir's whole
# crate was a2d's. p037_b_extractor_diff_gate.py is listed here for the
# same reason p037_b_production_diff_gate.py already was: this Phase-B
# governance script's own correctness is load-bearing for the boundary
# claim, so a change to it must move instrument_identity, not drift
# silently underneath an unchanged digest.
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
    "scripts/p037_b_extractor_diff_gate.py",
)

# B1-F2: the extractor joins mos.rs/lower.rs as a second carve-out. Carved
# out WHOLE (the same directory-level unit p037_b_extractor_diff_gate.py's
# own UNIT constant names), not just its three mutable methods -- exactly
# how mos.rs/lower.rs are carved out whole even though only four of their
# functions are actually mutable under p037_b_production_diff_gate.py.
# Path-level provenance carve-out + item-level production diff gate is the
# actual permitted semantic boundary; this tuple is only the first half.
INSTRUMENT_CARVE_OUTS: tuple[str, ...] = (
    "rust/crates/own-bridge/src/mos.rs",
    "rust/crates/own-bridge/src/lower.rs",
    "frontend/roslyn/OwnSharp.Extractor/",
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
    "scripts/p037_b_extractor_diff_gate.py",
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


def instrument_manifest(commit: str, *, repo: Path = ROOT) -> list[dict[str, str]]:
    """Phase B's OWN instrument closure at ``commit`` -- this module's
    INSTRUMENT_PATHS minus INSTRUMENT_CARVE_OUTS, mirroring p037_evidence.
    instrument_manifest's shape exactly but over Phase B's own paths, not
    a2d's. `ev.instrument_manifest`/`ev.instrument_identity` are NOT reused
    here (unlike the pure helpers this module imports elsewhere): both read
    p037_evidence's own module-level INSTRUMENT_PATHS/INSTRUMENT_CARVE_OUTS
    directly, with no parameter to redirect them -- they are two of the
    ~11 epoch-coupled functions this module's own docstring already lists
    as NOT safe to import unchanged. Built instead from `_tree_blobs`/
    `_sorted_entries`, which take their paths as arguments and read no
    module constant of either module's."""
    blobs = ev._tree_blobs(ev.resolve_commit(commit, repo=repo), INSTRUMENT_PATHS, repo=repo)
    return ev._sorted_entries(
        {"path": path, "blob": blob}
        for path, blob in blobs.items()
        if not _covered(path, INSTRUMENT_CARVE_OUTS)
    )


def instrument_identity(commit: str, *, repo: Path = ROOT) -> str:
    """One digest of Phase B's OWN instrument closure at ``commit``."""
    return ev._manifest_digest(instrument_manifest(commit, repo=repo))


def _record_closure_problems(doc: dict[str, Any]) -> list[str]:
    """Cross-check BOTH item-level gates' units against the epoch record --
    not just the Rust one. A record whose production_diff_gate.extractor is
    missing or names a different unit is exactly the same self-
    authorization hole B1-F1 found and fixed for the Rust side (check() must
    never trust a recorded allowlist the module itself did not also
    hard-code), now closed for the extractor from the start."""
    problems: list[str] = []
    gate = doc.get("production_diff_gate", {})
    rust = gate.get("rust", {}) if isinstance(gate, dict) else {}
    recorded_unit = rust.get("unit") if isinstance(rust, dict) else None
    if recorded_unit != "rust/crates/own-bridge/":
        problems.append(f"the epoch record's production_diff_gate.rust.unit "
                        f"{recorded_unit!r} differs from this module's own")
    extractor = gate.get("extractor", {}) if isinstance(gate, dict) else {}
    recorded_extractor_unit = extractor.get("unit") if isinstance(extractor, dict) else None
    if recorded_extractor_unit != "frontend/roslyn/OwnSharp.Extractor/":
        problems.append(f"the epoch record's production_diff_gate.extractor.unit "
                        f"{recorded_extractor_unit!r} differs from this module's own")
    return problems


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
        "instrument_identity": instrument_identity(source, repo=repo),
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


# --------------------------------------------------------------------------- selftest

_failures = 0


def _selfcheck(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def selftest() -> int:
    """Regression cover for the instrument_manifest()/instrument_identity()
    bug found after naming T_B/R_B at 2ed4d92: evidence_fields() had called
    `ev.instrument_manifest`/`ev._manifest_digest` directly, which read
    p037_evidence.py's OWN module-level INSTRUMENT_PATHS (a2d's closure)
    with no parameter to redirect them -- so every Phase-B snapshot's
    recorded instrument_identity was actually a2d's digest, structurally
    insensitive to any Phase-B-only file such as scripts/p037_b_
    production_diff_gate.py. Caught by a surprising measurement, not
    predicted: fixing the gate's self-authorization hole (a change to a
    Phase-B-only instrument path) did not move the recorded instrument_
    identity at all, which is what led here.

    These checks are deliberately timeless rather than pinned to the two
    specific commits that exposed the bug (git history does not move, but
    a test that only compares two named-forever SHAs never re-proves the
    PROPERTY on any later commit) -- they check, at whatever HEAD this
    runs on, that Phase B's own closure structurally differs from a2d's
    and that the two identities computed from it actually differ, which
    is the general shape of guarantee the bug violated.

    B1-F2 adds a second family: the extractor carve-out. (a) a Phase-B-only
    INSTRUMENT file (this module's own governance script) is present by
    name, not by fragile positional indexing into INSTRUMENT_PATHS; (b) an
    authorized TREATMENT item -- anything under the whole carved-out
    extractor directory, which is where the three mutable methods
    p037_b_extractor_diff_gate.py actually polices live -- never appears in
    instrument_manifest() at all, so a future edit there cannot masquerade
    as instrument drift; (c) the unrelated-item protection itself is the
    extractor gate's OWN job, proven by that module's own selftest() (18
    hostile cases including the 6 named in the B1-F2 brief), not
    re-proven here -- this module only proves the two are correctly WIRED
    together (the carve-out exists, and closure_problems() cross-checks the
    epoch record's production_diff_gate.extractor.unit against this
    module's own, exactly as it already did for the Rust gate)."""
    own_only = "scripts/p037_b_production_diff_gate.py"
    _selfcheck("phase-b-instrument-paths-include-b-production-diff-gate",
              own_only in INSTRUMENT_PATHS, INSTRUMENT_PATHS)
    _selfcheck("a2d-instrument-paths-do-not-include-it", own_only not in ev.INSTRUMENT_PATHS,
              ev.INSTRUMENT_PATHS)

    extractor_gate = "scripts/p037_b_extractor_diff_gate.py"
    _selfcheck("phase-b-instrument-paths-include-extractor-diff-gate",
              extractor_gate in INSTRUMENT_PATHS, INSTRUMENT_PATHS)
    _selfcheck("a2d-instrument-paths-do-not-include-the-extractor-gate",
              extractor_gate not in ev.INSTRUMENT_PATHS, ev.INSTRUMENT_PATHS)

    extractor_unit = "frontend/roslyn/OwnSharp.Extractor/"
    _selfcheck("extractor-directory-is-a-declared-carve-out",
              extractor_unit in INSTRUMENT_CARVE_OUTS, INSTRUMENT_CARVE_OUTS)

    manifest = instrument_manifest("HEAD")
    manifest_paths = [e["path"] for e in manifest]
    _selfcheck("phase-b-manifest-at-head-contains-the-b-only-file",
              any(p == own_only for p in manifest_paths), manifest_paths)
    _selfcheck("phase-b-manifest-excludes-the-whole-extractor-carve-out",
              not any(_covered(p, (extractor_unit,)) for p in manifest_paths),
              [p for p in manifest_paths if _covered(p, (extractor_unit,))])

    b_id = instrument_identity("HEAD")
    a2d_id = ev.instrument_identity("HEAD")
    _selfcheck("phase-b-identity-differs-from-a2d-identity-at-head",
              b_id != a2d_id, (b_id, a2d_id))

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-evidence-b selftest: all checks pass")
    return 0


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

    p = sub.add_parser("selftest")
    p.set_defaults(func=lambda _a: selftest())

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
