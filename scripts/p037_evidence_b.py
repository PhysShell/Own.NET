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
own units name (mos.rs, lower.rs, dump.rs, and the whole extractor
directory, each in full), exactly as a2d's own TREATMENT_PATHS is wider
than its doors and the *door gate* is the boundary within them.

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
import copy
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
# silently underneath an unchanged digest. B1-F2-F4 adds
# p037_b_classifier.py for the identical reason: scripts/p037_mos_snapshot.
# py's epoch-b is_evidence decision now calls its derive_document_witnesses/
# explain_divergence directly (divergence_status()), so a change to the
# classifier's class rules or its witness-derivation adapter can change
# whether a Phase-B snapshot counts as evidence -- exactly the kind of
# correctness this closure exists to pin. p037_delegation_closure.py is
# deliberately NOT here: it is a standalone control (like
# p037_proof_boundary.py, also not here) that never feeds is_evidence for
# any OTHER tool's snapshot, so its own correctness is not load-bearing for
# this closure the way the classifier's now is.
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
    "scripts/p037_b_classifier.py",
    # CH3-8: the new own-cli item-level gate joins for the same reason
    # p037_b_production_diff_gate.py/p037_b_extractor_diff_gate.py/
    # p037_b_classifier.py already did -- its own correctness is load-
    # bearing for the boundary claim it polices, so a change to it must
    # move instrument_identity, not drift silently underneath an unchanged
    # digest.
    "scripts/p037_b_cli_diff_gate.py",
)

# B1-F2: the extractor joins mos.rs/lower.rs as a second carve-out. Carved
# out WHOLE (the same directory-level unit p037_b_extractor_diff_gate.py's
# own UNIT constant names), not just its three mutable methods -- exactly
# how mos.rs/lower.rs are carved out whole even though only four of their
# functions are actually mutable under p037_b_production_diff_gate.py.
# Path-level provenance carve-out + item-level production diff gate is the
# actual permitted semantic boundary; this tuple is only the first half.
#
# B1-F2-F4-R2: dump.rs joins them. B1-F2-F4 had already widened
# p037_b_production_diff_gate.py to make `fn dump_summaries` mutable (the
# future B2.1b/c guarded-summary path must see the same guarded-method
# universe production does, including guarded_functions[]), but this
# module's own carve-out was never updated to match -- so a Phase-B R_B
# taken against the unfixed closure would have carried dump.rs's blob
# inside instrument_identity, and the very treatment this project's own
# production gate already authorizes would itself have moved the
# instrument out from under any future R_B-vs-B_after comparison
# (comparison_problems() correctly refuses an instrument_identity
# mismatch -- see its own selftest coverage -- so that comparison would
# have been refused no matter how correct the eventual solver was).
# Carved out WHOLE, same discipline as mos.rs/lower.rs and for the same
# reason: NOT because every byte of dump.rs may change -- the production
# gate still freezes it at item granularity (`fn dump_summaries` alone;
# `fn escape_py`/`fn emit`/`fn pad`, the file's `use` statements, and every
# other, unregistered item stay frozen there) -- but because path-level
# provenance carve-out plus item-level production diff gate, TOGETHER, are
# what actually bounds the permitted semantic surface. Carving out only
# the one mutable function would still need the same item gate to police
# what may move within it, while leaving the frozen remainder inside the
# instrument for no protective purpose.
# CH3-3/CH3-4: verdict.rs/render.rs join the carve-outs, for the SAME two
# reasons dump.rs did (B1-F2-F4-R2, above) -- not because every byte of
# either file may change (p037_b_production_diff_gate.py still freezes
# each at item granularity: exactly `struct Finding`/`impl Finding`/`fn
# transfer_note` in verdict.rs, `struct Properties`/`fn sarif_result` in
# render.rs; every other item in either file stays frozen) but because
# path-level provenance carve-out plus item-level production diff gate,
# TOGETHER, are what bounds the permitted surface -- and because leaving
# them out here the moment production_diff_gate.rust.mutable_items grows
# a "src/verdict.rs"/"src/render.rs" key is now a MISSING-carve-out defect
# _record_closure_problems (below) refuses generically, the same class of
# defect B1-F2-F4-R2 fixed for dump.rs. Mechanically required, not assumed:
# derived by reading production_diff_gate.rust.mutable_items's own new
# keys, not chosen independently of it.
# CH3-8: rust/crates/own-cli/src/ownir.rs joins -- the ONE FILE, not the
# whole own-cli crate. own-cli was previously inside the instrument with no
# carve-out at all (the unqualified "rust/" entry in INSTRUMENT_PATHS
# covered it with no exception), so it could not be touched by any
# treatment without silently moving the instrument out from under itself.
# The new scripts/p037_b_cli_diff_gate.py (added to INSTRUMENT_PATHS above)
# is the item-level policeman INSIDE this one carved-out file -- exactly
# the same two-part shape (path-level provenance carve-out + item-level
# production diff gate) every other carve-out in this tuple already uses;
# see that gate's own module docstring for why the file, not the crate, is
# the unit carved out here.
INSTRUMENT_CARVE_OUTS: tuple[str, ...] = (
    "rust/crates/own-bridge/src/mos.rs",
    "rust/crates/own-bridge/src/lower.rs",
    "rust/crates/own-bridge/src/dump.rs",
    "rust/crates/own-bridge/src/verdict.rs",
    "rust/crates/own-bridge/src/render.rs",
    "frontend/roslyn/OwnSharp.Extractor/",
    "rust/crates/own-cli/src/ownir.rs",
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
    "scripts/p037_b_classifier.py",
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
    """Cross-check ALL THREE item-level gates' units against the epoch
    record -- not just the Rust one. A record whose production_diff_gate.
    extractor (or, since CH3-8, .cli) is missing or names a different unit
    is exactly the same self-authorization hole B1-F1 found and fixed for
    the Rust side (check() must never trust a recorded allowlist the module
    itself did not also hard-code), now closed for the extractor and the
    CLI gate from the start.

    B1-F2-F4-R2 adds a third, GENERIC check, closing the CLASS of defect the
    dump.rs omission belonged to rather than only that one instance: every
    file `production_diff_gate.rust` names as carrying a mutable item
    (`mutable_items`) or being wholly mutable (`mutable_files`), plus the
    extractor's own whole-unit carve-out and (since CH3-8) every file
    `production_diff_gate.cli` names the same way, is DERIVED from the
    epoch record already in hand and required to equal `INSTRUMENT_CARVE_OUTS` (hence
    `TREATMENT_PATHS`, the same tuple) EXACTLY -- not a subset check. A
    future item added to `mutable_items` with no matching carve-out (the
    dump.rs defect, generalized to any filename) is refused as MISSING; a
    carve-out left behind after its last mutable item is retired is refused
    as EXCESS -- an unjustified exclusion is also a false claim about what
    the instrument does not need to see, not merely over-caution.
    `production_diff_gate.rust.controls` (e.g. `tests/`) is deliberately
    EXCLUDED from this derivation: it names files the item-level PRODUCTION
    gate already permits to move for a different reason entirely (test/
    control churn, never Phase-B treatment provenance) -- folding it in
    would either wrongly demand `tests/` be carved out of the instrument or
    let a real treatment addition hide behind the controls list. No new
    runtime import of either diff-gate module is needed or added: their own
    `mutable_items`/`mutable_files`/`unit` are already present in the epoch
    record `epoch_record()` reads from the frozen commit, which is what
    this function is handed -- the gate modules themselves are not imported
    or executed here. The derived-set comparison only runs once both units
    are already confirmed correct above; a wrong unit is reported as that
    one root problem, not as a cascade of "everything is missing" noise
    computed from a bogus prefix."""
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
    # CH3-8: a third item-level gate, same cross-check as rust/extractor
    # above -- see scripts/p037_b_cli_diff_gate.py's own module docstring.
    cli = gate.get("cli", {}) if isinstance(gate, dict) else {}
    recorded_cli_unit = cli.get("unit") if isinstance(cli, dict) else None
    if recorded_cli_unit != "rust/crates/own-cli/":
        problems.append(f"the epoch record's production_diff_gate.cli.unit "
                        f"{recorded_cli_unit!r} differs from this module's own")

    if (recorded_unit == "rust/crates/own-bridge/"
            and recorded_extractor_unit == "frontend/roslyn/OwnSharp.Extractor/"
            and recorded_cli_unit == "rust/crates/own-cli/"):
        expected_carve_outs: set[str] = {recorded_extractor_unit}
        mutable_items = rust.get("mutable_items", {})
        if isinstance(mutable_items, dict):
            expected_carve_outs.update(
                recorded_unit + name for name in mutable_items if isinstance(name, str))
        mutable_files = rust.get("mutable_files", [])
        if isinstance(mutable_files, list):
            expected_carve_outs.update(
                recorded_unit + name for name in mutable_files if isinstance(name, str))
        # CH3-8: the CLI gate's own mutable_items/mutable_files derive their
        # OWN expected carve-outs the identical way, rooted at
        # recorded_cli_unit rather than recorded_unit -- a second unit, same
        # derivation, not a special case.
        cli_mutable_items = cli.get("mutable_items", {})
        if isinstance(cli_mutable_items, dict):
            expected_carve_outs.update(
                recorded_cli_unit + name for name in cli_mutable_items if isinstance(name, str))
        cli_mutable_files = cli.get("mutable_files", [])
        if isinstance(cli_mutable_files, list):
            expected_carve_outs.update(
                recorded_cli_unit + name for name in cli_mutable_files if isinstance(name, str))
        actual_carve_outs = set(INSTRUMENT_CARVE_OUTS)
        for path in sorted(expected_carve_outs - actual_carve_outs):
            problems.append(
                f"production_diff_gate authorizes {path!r} as a mutable treatment "
                "file/unit, but it is not in INSTRUMENT_CARVE_OUTS -- it would still "
                "be inside the Phase-B instrument closure")
        for path in sorted(actual_carve_outs - expected_carve_outs):
            problems.append(
                f"INSTRUMENT_CARVE_OUTS carves out {path!r}, but no production_diff_gate "
                "mutable_items/mutable_files/unit entry justifies it any more")
    return problems


def closure_problems(*, repo: Path = ROOT) -> list[str]:
    """Static self-check: every repo-local runtime path is in the closure,
    the carve-outs are treatment under instrument roots, HEAD's epoch
    record agrees with this module on all three production-diff gates' units,
    and (see _record_closure_problems) the epoch record's own mutable-item/
    mutable-file/unit declarations derive EXACTLY this module's
    INSTRUMENT_CARVE_OUTS -- catching a future widened allowlist with no
    matching carve-out generically, not only by filename."""
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
        "subject_paths": list(SUBJECT_PATHS),
        "instrument_identity": instrument_identity(source, repo=repo),
        **population,
    }


def record_problems(record: dict[str, Any], *, repo: Path = ROOT) -> list[str]:
    """Self-consistency of one Phase-B evidence record at its OWN source
    commit -- ported clause for clause from p037_evidence.record_problems
    (CH3-12, R1-review of 460557e: the prior version of this function
    claimed that parity in its own docstring but actually implemented only
    a small subset -- instrument_paths/treatment_paths/subject_paths exact
    equality were never checked at all (only instrument_carve_outs, and
    only as a SET, which also tolerates a reordered/duplicated closure);
    input_roots was never validated; instrument_identity(source) was never
    cross-checked against the recorded value (comparison_problems's own
    before==after check cannot catch two independently forged-but-equal
    digests); population_commit existence/ancestry was never checked;
    analysis_manifest/support_manifest were never re-derived from the
    population commit, nor their sha256 fields checked against the carried
    manifest; reference_profile/execution_profile were never checked;
    artifacts were never validated at all). Ported below using the SAME
    pure, parameter-driven ev.* helpers the generic function itself calls
    (population_fields/analysis_manifest/support_manifest/_manifest_
    entries/_manifest_digest/reference_profile_problems/commit_exists/
    is_ancestor -- confirmed against this module's own top docstring: none
    of these read EPOCH/INSTRUMENT_PATHS/TREATMENT_PATHS internally), and
    this module's OWN environment_id()/instrument_identity() (the two
    that ARE epoch-coupled, already defined above for exactly that reason,
    already used by evidence_fields()).

    One intentional divergence from the generic function, named explicitly
    rather than silently kept: the old `materialized_root`/`population_
    intact()` branch is REMOVED, not merely renamed to the field verdict
    snapshots actually write (`materialization_root`) -- it was dead code
    (that typo'd field name is never written, so the branch never ran) and
    reintroducing it correctly would still make historical validation
    depend on an ephemeral materialized directory that need not still
    exist. Population integrity is proven durably instead, exactly as the
    generic function proves it: by re-deriving analysis_manifest/support_
    manifest from the population commit and checking their digests -- both
    already ported above, no separate directory inspection needed."""
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
        problems.append(
            f"record carries no epoch: it predates {EPOCH} and is not eligible in it, "
            "as a before side or otherwise")
    elif epoch != EPOCH:
        problems.append(f"record names epoch {epoch!r}, not {EPOCH!r}")
    env_id = record.get("environment_id")
    if not isinstance(env_id, str) or not env_id:
        problems.append("record carries no environment_id")
    if record.get("instrument_paths") != list(INSTRUMENT_PATHS):
        problems.append("recorded instrument_paths differ from this tool's instrument closure")
    if record.get("instrument_carve_outs") != list(INSTRUMENT_CARVE_OUTS):
        problems.append("recorded instrument_carve_outs differ from this tool's")
    if record.get("treatment_paths") != list(TREATMENT_PATHS):
        problems.append("recorded treatment_paths differ from this tool's treatment closure")
    if record.get("subject_paths") != list(SUBJECT_PATHS):
        problems.append("recorded subject_paths differ from this tool's measurement closure")

    roots_raw = record.get("input_roots")
    roots: tuple[str, ...] = ()
    if (
        isinstance(roots_raw, list)
        and roots_raw
        and all(isinstance(x, str) and x for x in roots_raw)
    ):
        roots = tuple(str(x) for x in roots_raw)
    else:
        problems.append("record carries no valid input_roots")

    if not ev.commit_exists(source, repo=repo):
        return [*problems, f"source commit {source[:12]} is not present in this checkout"]

    try:
        expected_env = environment_id(source, repo=repo)
    except EvidenceRefused as exc:
        problems.append(str(exc))
    else:
        if isinstance(env_id, str) and env_id and env_id != expected_env:
            problems.append(
                f"record names environment {env_id!r}, not the epoch record's "
                f"{expected_env!r} at its source commit")
    try:
        identity = instrument_identity(source, repo=repo)
    except EvidenceRefused as exc:
        problems.append(str(exc))
    else:
        if record.get("instrument_identity") != identity:
            problems.append(
                "recorded instrument_identity is not the instrument closure's digest at the "
                "source commit")

    population = record.get("population_commit")
    if not isinstance(population, str) or not ev.commit_exists(population, repo=repo):
        problems.append("record names no population_commit present in this checkout")
    else:
        if not ev.is_ancestor(population, source, repo=repo):
            problems.append(
                f"population commit {population[:12]} is not an ancestor of (or equal to) "
                f"source commit {source[:12]}")
        try:
            recorded_analysis = ev._manifest_entries(record, "analysis_manifest")
            recorded_support = ev._manifest_entries(record, "support_manifest")
        except EvidenceRefused as exc:
            problems.append(str(exc))
        else:
            if roots:
                try:
                    analysis = ev.analysis_manifest(population, roots, repo=repo)
                    support = ev.support_manifest(population, analysis, repo=repo)
                except EvidenceRefused as exc:
                    problems.append(str(exc))
                else:
                    if recorded_analysis != analysis:
                        problems.append(
                            "recorded analysis_manifest does not match the population "
                            "commit's exact C# input set")
                    if recorded_support != support:
                        problems.append(
                            "recorded support_manifest does not match the population "
                            "commit's semantic support closure")
            if record.get("analysis_manifest_sha256") != ev._manifest_digest(recorded_analysis):
                problems.append("analysis_manifest_sha256 does not name the carried manifest")
            if record.get("support_manifest_sha256") != ev._manifest_digest(recorded_support):
                problems.append("support_manifest_sha256 does not name the carried manifest")

    problems.extend(ev.reference_profile_problems(record))

    profile = record.get("execution_profile")
    if not isinstance(profile, dict) or not profile:
        problems.append("record carries no execution_profile")

    artifacts = record.get("artifacts", {})
    if not isinstance(artifacts, dict):
        problems.append("artifacts is not an object")
    else:
        for name, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                problems.append(f"artifact {name!r} is not an object")
                continue
            if artifact.get("source_commit") != source:
                problems.append(
                    f"artifact {name!r} was not built from the record's source commit")
            if artifact.get("dirty") is not False:
                problems.append(f"artifact {name!r} was built on a dirty tree")
            if not isinstance(artifact.get("sha256"), str):
                problems.append(f"artifact {name!r} carries no sha256")
            executed = artifact.get("executed")
            if not isinstance(executed, dict):
                problems.append(f"artifact {name!r} carries no executed attestation")
            else:
                if executed.get("sha256") != artifact.get("sha256"):
                    problems.append(
                        f"artifact {name!r} executed a file other than the qualified build")
                if executed.get("post_run_intact") is not True:
                    problems.append(
                        f"artifact {name!r} does not attest it stayed intact through the run")
    return problems


def comparison_problems(
    before: dict[str, Any], after: dict[str, Any], *, against: str = "HEAD", repo: Path = ROOT
) -> list[str]:
    """Differential eligibility for a Phase-B before/after pair -- the B-after
    counterpart p037_evidence.py's own module docstring names as "a later,
    B-after-time addition, built once there is a second take to compare
    against the first" (B1-F2-F4: that time is now, for scripts/
    p037_mos_snapshot.py's `compare --epoch b` to work at all instead of
    raising AttributeError on a module with no such function). Mirrors
    p037_evidence.comparison_problems's own checks exactly, substituting
    this module's own record_problems/provenance_problems/EPOCH and its own
    instrument pathspec (INSTRUMENT_PATHS minus INSTRUMENT_CARVE_OUTS, the
    same construction provenance_problems already uses inline) for
    p037_evidence's a2d-scoped equivalents -- none of `ev.commit_exists`/
    `ev.is_ancestor`/`ev.paths_differ` are epoch-coupled (see this module's
    own docstring's list of the ~11 that are), so they are called directly."""
    problems = [f"before: {p}" for p in record_problems(before, repo=repo)]
    problems += [f"after: {p}" for p in provenance_problems(after, against=against, repo=repo)]
    if before.get("epoch") != EPOCH or after.get("epoch") != EPOCH:
        problems.append(
            f"before/after are not both {EPOCH!r} records; no record of another epoch is "
            "compared with one of this epoch")
    if (not isinstance(before.get("environment_id"), str)
            or before.get("environment_id") != after.get("environment_id")):
        problems.append(
            "before/after environment ids differ; a comparison is taken on one environment")
    if before.get("instrument_identity") != after.get("instrument_identity"):
        problems.append("before/after instrument identities differ")

    before_source = before.get("source_commit")
    after_source = after.get("source_commit")
    if (isinstance(before_source, str) and isinstance(after_source, str)
            and ev.commit_exists(before_source, repo=repo)
            and ev.commit_exists(after_source, repo=repo)):
        if not ev.is_ancestor(before_source, after_source, repo=repo):
            problems.append(
                f"before source {before_source[:12]} is not an ancestor of "
                f"after source {after_source[:12]}")
        else:
            try:
                pathspec = [*INSTRUMENT_PATHS, *(f":(exclude){c}" for c in INSTRUMENT_CARVE_OUTS)]
                if ev.paths_differ(before_source, after_source, pathspec, repo=repo):
                    problems.append(
                        "the measurement instrument differs between before and after; "
                        "only the treatment may move across a comparison")
            except EvidenceRefused as exc:
                problems.append(str(exc))

    if before.get("population_commit") != after.get("population_commit"):
        problems.append("before/after name different frozen populations")
    if before.get("input_roots") != after.get("input_roots"):
        problems.append("before/after input_roots differ")
    if before.get("analysis_manifest") != after.get("analysis_manifest"):
        problems.append("before/after primary population manifests differ")
    if before.get("support_manifest") != after.get("support_manifest"):
        problems.append("before/after semantic support manifests differ")

    before_profile = before.get("execution_profile")
    after_profile = after.get("execution_profile")
    if (isinstance(before_profile, dict) and isinstance(after_profile, dict)
            and before_profile and after_profile and before_profile != after_profile):
        problems.append("before/after execution profiles differ")
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
    module's own, exactly as it already did for the Rust gate).

    B1-F2-F4-R2 adds a third family, the same general shape again: B1-F2-F4
    widened p037_b_production_diff_gate.py to make dump.rs's own
    `dump_summaries` an authorized B2.1b/c treatment item, but this
    module's INSTRUMENT_CARVE_OUTS was never updated to match, so dump.rs
    silently stayed inside the Phase-B instrument closure -- a real defect,
    not a hypothetical one, since a fresh R_B taken before this fix would
    have made the already-authorized dump_summaries treatment itself move
    instrument_identity. Proven the same way as the extractor family: the
    carve-out is declared (and therefore also TREATMENT_PATHS, which is
    literally the same tuple), the file is structurally absent from
    instrument_manifest() at HEAD (never inferred from the carve-out
    declaration alone -- the manifest is rebuilt and inspected directly),
    and an UNRELATED, still-frozen own-bridge file stays present, proving
    the fix removed exactly the one path, not the whole directory."""
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

    # B1-F2-F4-R2: dump.rs must be a declared carve-out/treatment path AND
    # structurally absent from the manifest built at HEAD -- not merely
    # declared, since instrument_manifest() is what instrument_identity()
    # actually hashes. mos.rs/lower.rs are re-asserted alongside it (the
    # exact three files p037_b_production_diff_gate.py's own item gate
    # polices) so a future regression narrowing the carve-out back down is
    # caught here too, not only in that other module's own selftest.
    dump_path = "rust/crates/own-bridge/src/dump.rs"
    mos_path = "rust/crates/own-bridge/src/mos.rs"
    lower_path = "rust/crates/own-bridge/src/lower.rs"
    _selfcheck("dump-rs-is-a-declared-carve-out",
              dump_path in INSTRUMENT_CARVE_OUTS, INSTRUMENT_CARVE_OUTS)
    _selfcheck("dump-rs-is-declared-treatment",
              dump_path in TREATMENT_PATHS, TREATMENT_PATHS)
    _selfcheck("dump-rs-is-excluded-from-the-instrument-manifest-at-head",
              dump_path not in manifest_paths, manifest_paths)
    _selfcheck("mos-rs-and-lower-rs-are-also-excluded-from-the-instrument-manifest",
              mos_path not in manifest_paths and lower_path not in manifest_paths,
              manifest_paths)
    # An unrelated, still-frozen own-bridge file must remain IN the
    # manifest -- proving the fix removed exactly the three treatment
    # files, never the whole rust/crates/own-bridge/ directory. CH3-4:
    # this used to name verdict.rs, before verdict.rs/render.rs themselves
    # joined the carve-outs; src/lib.rs is one of the three files that
    # actually stays frozen (Cargo.toml, src/ast.rs, src/lib.rs).
    unrelated_frozen = "rust/crates/own-bridge/src/lib.rs"
    _selfcheck("an-unrelated-frozen-own-bridge-file-stays-in-the-instrument-manifest",
              unrelated_frozen in manifest_paths, manifest_paths)

    b_id = instrument_identity("HEAD")
    a2d_id = ev.instrument_identity("HEAD")
    _selfcheck("phase-b-identity-differs-from-a2d-identity-at-head",
              b_id != a2d_id, (b_id, a2d_id))

    # B1-F2-F4: comparison_problems() exists at all (calling it used to raise
    # AttributeError -- p037_mos_snapshot.py's `compare --epoch b` and
    # `verify`'s sibling machinery both need it) and correctly refuses the
    # epoch-b-specific hostile cases without touching git or the filesystem.
    base_record: dict[str, Any] = {
        "epoch": EPOCH, "environment_id": "P037_B_MEASUREMENT_M3",
        "instrument_identity": "deadbeef", "source_commit": "0" * 40,
        "population_commit": "1" * 40, "input_roots": ["corpus"],
        "analysis_manifest": [], "support_manifest": [], "execution_profile": {},
        "dirty": False, "is_evidence": True, "post_run_dirty": False,
        "post_run_population_intact": True,
        "instrument_carve_outs": list(INSTRUMENT_CARVE_OUTS),
    }
    wrong_epoch = dict(base_record, epoch="a2d")
    problems = comparison_problems(wrong_epoch, base_record)
    _selfcheck("comparison-problems-catches-epoch-mismatch",
              any("not both" in p for p in problems), problems)

    wrong_env = dict(base_record, environment_id="SOME_OTHER_ENV")
    problems = comparison_problems(wrong_env, base_record)
    _selfcheck("comparison-problems-catches-environment-mismatch",
              any("environment ids differ" in p for p in problems), problems)

    wrong_instrument = dict(base_record, instrument_identity="cafef00d")
    problems = comparison_problems(wrong_instrument, base_record)
    _selfcheck("comparison-problems-catches-instrument-identity-mismatch",
              any("instrument identities differ" in p for p in problems), problems)

    # B1-F2-F4-R2: the GENERIC carve-out/mutable-item invariant, proven
    # against a DEEP COPY of the real, committed epoch record (never a
    # hand-built shape that could silently drift from the real one) --
    # closing the CLASS of defect the dump.rs omission belonged to, not
    # only that one filename. See _record_closure_problems's own docstring.
    real_doc = epoch_record("HEAD")
    _selfcheck("current-real-epoch-record-closes-cleanly",
              not _record_closure_problems(real_doc), _record_closure_problems(real_doc))

    # CH3-8: the record committed at HEAD predates this amendment's own
    # supersession of CH3-3's item set AND the brand-new production_diff_
    # gate.cli section, so the check above is EXPECTED to stay green only
    # once the epoch record itself is updated in the SAME commit as this
    # module (production_diff_gate.{rust,cli} and this module's own
    # INSTRUMENT_CARVE_OUTS are a matched pair, same discipline as both
    # diff-gate modules' own policy_drift()). Proven here instead, on a deep
    # copy of the real record patched EXACTLY the shape this amendment
    # records (never a hand-invented one), that the module's ALREADY-
    # updated INSTRUMENT_CARVE_OUTS and that intended future record shape
    # close cleanly TOGETHER -- the actual end-to-end coherence proof, ahead
    # of the commit that makes it the live one.
    future_doc = copy.deepcopy(real_doc)
    future_doc["production_diff_gate"]["rust"]["mutable_items"]["src/lower.rs"] = [
        "fn lower_fn_params", "fn unverified_transfer_calls",
        "fn kill_sites_for_unverified", "fn lower_full", "struct Lowering"]
    future_doc["production_diff_gate"]["rust"]["mutable_items"]["src/verdict.rs"] = [
        "impl Finding", "fn check_facts"]
    future_doc["production_diff_gate"]["rust"]["mutable_items"]["src/render.rs"] = [
        "struct Run", "fn build_sarif"]
    future_doc["production_diff_gate"]["rust"]["frozen_files"] = [
        f for f in future_doc["production_diff_gate"]["rust"]["frozen_files"]
        if f not in ("src/render.rs", "src/verdict.rs")]
    future_doc["production_diff_gate"]["cli"] = {
        "unit": "rust/crates/own-cli/",
        "mutable_files": [],
        "mutable_items": {"src/ownir.rs": ["fn check", "fn display"]},
        "registered_new_items": {},
        "frozen_files": ["Cargo.toml", "src/main.rs", "src/faults.rs",
                         "src/pyrepr.rs", "src/sarif.rs", "src/text.rs"],
        "controls": ["tests/"],
    }
    _selfcheck("ch3-8-amended-epoch-record-shape-closes-cleanly-with-live-module",
              not _record_closure_problems(future_doc), _record_closure_problems(future_doc))

    # CH3-8: the three required own-cli closure hostile cases (a CLI-gate
    # mutable item with no matching carve-out; the real own-cli carve-out
    # with no matching CLI-gate mutable_items entry backing it; a unit
    # mismatch), each proven on `future_doc` (the shape that otherwise
    # closes cleanly, per the check directly above) so the failure is
    # attributable to the ONE hostile change and nothing else.
    cli_hostile_missing = copy.deepcopy(future_doc)
    cli_hostile_missing["production_diff_gate"]["cli"]["mutable_items"][
        "src/hypothetical_unauthorized.rs"] = ["fn foo"]
    problems = _record_closure_problems(cli_hostile_missing)
    _selfcheck("cli-mutable-item-with-no-matching-carve-out-is-refused",
              any("own-cli/src/hypothetical_unauthorized.rs" in p
                  and "is not in INSTRUMENT_CARVE_OUTS" in p for p in problems),
              problems)

    cli_hostile_excess = copy.deepcopy(future_doc)
    del cli_hostile_excess["production_diff_gate"]["cli"]["mutable_items"]["src/ownir.rs"]
    problems = _record_closure_problems(cli_hostile_excess)
    _selfcheck("cli-carve-out-with-no-backing-mutable-item-is-refused",
              any("own-cli/src/ownir.rs" in p and "no production_diff_gate" in p
                  for p in problems),
              problems)

    cli_hostile_unit = copy.deepcopy(future_doc)
    cli_hostile_unit["production_diff_gate"]["cli"]["unit"] = "rust/crates/own-bridge/"
    problems = _record_closure_problems(cli_hostile_unit)
    _selfcheck("cli-unit-mismatch-is-refused",
              any("production_diff_gate.cli.unit" in p for p in problems), problems)

    # CH3-4: this was `src/render.rs` before render.rs itself joined
    # INSTRUMENT_CARVE_OUTS as a REAL, legitimate entry -- reusing it here
    # now would silently stop testing the missing-carve-out case (the real
    # entry would just get overwritten with a fake item list, and the path
    # would still be correctly carved out for its own real reason). A name
    # that can never legitimately appear in either list stays a true
    # negative regardless of which files are carved out this month.
    #
    # CH3-8: built on `future_doc` (the shape that closes cleanly, proven
    # directly above), not `real_doc` -- `real_doc` still lacks
    # production_diff_gate.cli entirely (this amendment's own epoch-record
    # commit has not landed yet), so the three-way unit check would refuse
    # it on the CLI mismatch alone and never reach the rust-side derivation
    # this test means to isolate. Same fix applies to both tests below.
    hostile_missing = copy.deepcopy(future_doc)
    hostile_missing["production_diff_gate"]["rust"]["mutable_items"][
        "src/hypothetical_unauthorized.rs"] = ["fn foo"]
    problems = _record_closure_problems(hostile_missing)
    _selfcheck("hostile-mutable-item-with-no-matching-carve-out-is-refused",
              any("hypothetical_unauthorized.rs" in p and "is not in INSTRUMENT_CARVE_OUTS" in p
                  for p in problems),
              problems)

    hostile_excess = copy.deepcopy(future_doc)
    del hostile_excess["production_diff_gate"]["rust"]["mutable_items"]["src/dump.rs"]
    problems = _record_closure_problems(hostile_excess)
    _selfcheck("hostile-excess-carve-out-with-no-backing-mutable-item-is-refused",
              any("dump.rs" in p and "no production_diff_gate" in p for p in problems),
              problems)

    # --- CH3-12 (R1-review of 460557e, items 16/17): record_problems() was
    # just ported clause-for-clause from the generic p037_evidence.record_
    # problems (see this function's own docstring) after the review found it
    # had claimed that parity without implementing it -- a hand-built
    # "invalid record" fixture compared only to another hand-built one would
    # risk re-committing exactly that mistake (both sides could drift from
    # what a REAL take actually produces without either test noticing). So
    # the base fixture below is the REAL current helper's own output --
    # `evidence_fields()` called against live HEAD, the same call `take()`
    # itself makes -- with only the handful of fields a full `_measure()` run
    # adds afterwards (execution_profile/reference_profile/artifacts/
    # post_run_*) filled in from the same real, parameter-driven ev.*
    # helpers `_measure()` itself uses. `dirty`/`is_evidence` are forced
    # rather than read from the live tree's actual state, because THIS
    # selftest routinely runs on a dirty tree mid-repair -- record_problems()
    # itself never re-derives "dirty" from git (that would check validation-
    # time state, not take-time state), it only checks the field says
    # `False`, so overriding it here is a fixture choice, not a cheat past
    # the function under test. One mutation per test, per field, proving
    # each ported clause is independently load-bearing -- never two
    # hand-crafted invalid records compared only to each other.
    _valid_provenance = evidence_fields(CORPUS_DIRS, population_commit="HEAD")
    _valid_record: dict[str, Any] = {
        **_valid_provenance,
        "dirty": False,
        "is_evidence": True,
        "post_run_dirty": False,
        "post_run_population_intact": True,
        "execution_profile": ev.execution_profile(include_rust=False),
        "reference_profile": {ev.EXTRA_REF_ENV: ev.REFERENCE_PROFILE_CLEAN,
                              "observed_extra_reference_lines": 0},
        "artifacts": {},
    }
    _selfcheck("real-valid-record-passes-record-problems-cleanly",
              record_problems(_valid_record) == [], record_problems(_valid_record))

    _wrong_identity = {**_valid_record, "instrument_identity": "deadbeef"}
    problems = record_problems(_wrong_identity)
    _selfcheck("hostile-wrong-instrument-identity",
              any("recorded instrument_identity is not the instrument closure" in p
                  for p in problems),
              problems)

    _wrong_instrument_paths = {**_valid_record, "instrument_paths": ["not/a/real/path"]}
    problems = record_problems(_wrong_instrument_paths)
    _selfcheck("hostile-wrong-instrument-paths",
              any("recorded instrument_paths differ" in p for p in problems), problems)

    _missing_treatment_paths = {k: v for k, v in _valid_record.items() if k != "treatment_paths"}
    problems = record_problems(_missing_treatment_paths)
    _selfcheck("hostile-missing-treatment-paths",
              any("recorded treatment_paths differ" in p for p in problems), problems)

    _wrong_subject_paths = {**_valid_record, "subject_paths": ["not/a/real/path"]}
    problems = record_problems(_wrong_subject_paths)
    _selfcheck("hostile-wrong-subject-paths",
              any("recorded subject_paths differ" in p for p in problems), problems)

    _invalid_input_roots = {**_valid_record, "input_roots": []}
    problems = record_problems(_invalid_input_roots)
    _selfcheck("hostile-invalid-input-roots",
              any("no valid input_roots" in p for p in problems), problems)

    _nonexistent_population = {**_valid_record, "population_commit": "0" * 40}
    problems = record_problems(_nonexistent_population)
    _selfcheck("hostile-nonexistent-population-commit",
              any("no population_commit present" in p for p in problems), problems)

    # population stays the real, current HEAD (a real, existing commit) but
    # source moves to HEAD's own parent -- population is then a DESCENDANT
    # of source, never its ancestor, without needing any commit outside this
    # branch's own linear history.
    _ancestor_hostile = {**_valid_record, "source_commit": ev.resolve_commit("HEAD~1")}
    problems = record_problems(_ancestor_hostile)
    _selfcheck("hostile-population-commit-not-ancestor-of-source",
              any("is not an ancestor of" in p for p in problems), problems)

    _tampered_analysis = {**_valid_record,
                          "analysis_manifest": [{"path": "fake.cs", "blob": "0" * 40}]}
    problems = record_problems(_tampered_analysis)
    _selfcheck("hostile-tampered-analysis-manifest",
              any("recorded analysis_manifest does not match" in p for p in problems), problems)

    _wrong_analysis_digest = {**_valid_record, "analysis_manifest_sha256": "deadbeef" * 8}
    problems = record_problems(_wrong_analysis_digest)
    _selfcheck("hostile-wrong-analysis-manifest-sha256",
              any("analysis_manifest_sha256 does not name the carried manifest" in p
                  for p in problems),
              problems)

    _tampered_support = {**_valid_record,
                         "support_manifest": [{"path": "fake.xaml", "blob": "0" * 40,
                                               "mechanism": "sibling-xaml"}]}
    problems = record_problems(_tampered_support)
    _selfcheck("hostile-tampered-support-manifest",
              any("recorded support_manifest does not match" in p for p in problems), problems)

    _wrong_support_digest = {**_valid_record, "support_manifest_sha256": "cafebabe" * 8}
    problems = record_problems(_wrong_support_digest)
    _selfcheck("hostile-wrong-support-manifest-sha256",
              any("support_manifest_sha256 does not name the carried manifest" in p
                  for p in problems),
              problems)

    _empty_profile = {**_valid_record, "execution_profile": {}}
    problems = record_problems(_empty_profile)
    _selfcheck("hostile-empty-execution-profile",
              any("carries no execution_profile" in p for p in problems), problems)

    _good_artifact: dict[str, Any] = {
        "source_commit": _valid_record["source_commit"], "dirty": False, "sha256": "a" * 64,
        "executed": {"sha256": "a" * 64, "post_run_intact": True},
    }
    _base_with_artifact = {**_valid_record, "artifacts": {"own-cli": _good_artifact}}
    _selfcheck("real-valid-record-plus-one-good-artifact-passes-cleanly",
              record_problems(_base_with_artifact) == [], record_problems(_base_with_artifact))

    _artifact_wrong_source = {**_base_with_artifact,
                              "artifacts": {"own-cli": {**_good_artifact,
                                                        "source_commit": "1" * 40}}}
    problems = record_problems(_artifact_wrong_source)
    _selfcheck("hostile-artifact-source-commit-mismatch",
              any("was not built from the record's source commit" in p for p in problems),
              problems)

    _artifact_dirty = {**_base_with_artifact,
                       "artifacts": {"own-cli": {**_good_artifact, "dirty": True}}}
    problems = record_problems(_artifact_dirty)
    _selfcheck("hostile-artifact-dirty-true",
              any("was built on a dirty tree" in p for p in problems), problems)

    _artifact_wrong_executed_sha = {
        **_base_with_artifact,
        "artifacts": {"own-cli": {**_good_artifact,
                                  "executed": {"sha256": "b" * 64, "post_run_intact": True}}},
    }
    problems = record_problems(_artifact_wrong_executed_sha)
    _selfcheck("hostile-artifact-executed-sha256-mismatch",
              any("executed a file other than the qualified build" in p for p in problems),
              problems)

    _artifact_not_intact = {
        **_base_with_artifact,
        "artifacts": {"own-cli": {**_good_artifact,
                                  "executed": {"sha256": "a" * 64, "post_run_intact": False}}},
    }
    problems = record_problems(_artifact_not_intact)
    _selfcheck("hostile-artifact-post-run-intact-false",
              any("does not attest it stayed intact through the run" in p for p in problems),
              problems)

    # item 17: pairwise equality is not authenticity. Both sides carry the
    # SAME forged value, so the (pre-existing) before==after equality check
    # in comparison_problems() cannot see anything wrong -- only because
    # record_problems() now independently recomputes and cross-checks each
    # side's own value does the forgery surface, on BOTH sides, not just one.
    _forged_identity_pair_problems = comparison_problems(
        {**_valid_record, "instrument_identity": "deadbeefdeadbeef"},
        {**_valid_record, "instrument_identity": "deadbeefdeadbeef"},
    )
    _selfcheck(
        "pairwise-equal-but-forged-instrument-identity-still-refused-on-both-sides",
        any(p.startswith("before: recorded instrument_identity is not")
            for p in _forged_identity_pair_problems)
        and any(p.startswith("after: recorded instrument_identity is not")
                for p in _forged_identity_pair_problems),
        _forged_identity_pair_problems)

    _forged_digest_pair_problems = comparison_problems(
        {**_valid_record, "analysis_manifest_sha256": "cafecafe" * 8},
        {**_valid_record, "analysis_manifest_sha256": "cafecafe" * 8},
    )
    _selfcheck(
        "pairwise-equal-but-forged-analysis-digest-still-refused-on-both-sides",
        any(p.startswith("before: analysis_manifest_sha256 does not name")
            for p in _forged_digest_pair_problems)
        and any(p.startswith("after: analysis_manifest_sha256 does not name")
                for p in _forged_digest_pair_problems),
        _forged_digest_pair_problems)

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
