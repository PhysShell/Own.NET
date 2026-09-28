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

Amendment (post-B1, the CONDITIONALITY_HONESTY finding -- see
docs/evidence/p037-b-epoch.json's appended supersession entry): U1's own
measured shape (scripts/p037_b_classifier.py's call-site witness) proved a
real verdict movement can exist with no (method,param) SUMMARY coordinate at
all, so `compare()` cannot lean on `p037_mos_snapshot.py`'s document-level
classification for it -- the classification has to be checked against the
VERDICT movement directly, AND the instrument must already know where a real
capture would deliver that witness from, before T_B is named, or naming T_B
now would freeze a thermometer with no wire yet attached.

Capture transport (schema `p037-verdict-snapshot/5`; superseding schema `/4`'s
per-result design -- see `docs/evidence/p037-b-epoch.json`'s
`ch3_8_run_level_supersession` entry for the full falsification-and-
supersession account, and this repository's PoC report for the measured
proof this transport survives it): a real future producer attaches ONE
`properties` key on the RUN, `p037_call_site_witnesses` (plural), a plain
array of `<CALL_SITE_WITNESS>` objects -- never wrapped in a per-item
version envelope, since the whole SNAPSHOT is versioned by `SCHEMA` above.
`run_one()`'s SARIF parsing (factored into `_parse_sarif_doc()`, directly
testable on a hand-built SARIF document, never only through the subprocess)
reads this key on EVERY run, TODAY, validates each array entry via
`clf.check_call_site_witness()`, and stores whatever verified list results as
`snap["files"][rel]["call_site_witnesses"]` -- a STANDARD field of every
snapshot from this schema on, `[]` where no producer populates it (every
snapshot today; the real B2.1b/c-R1 producer does not exist yet, see
p037_b_classifier.py's own docstring point 5). Fail-closed, pinned by
selftest(): a missing/non-list key, or an array entry failing
`check_call_site_witness()`, degrades that ONE entry to absent, never a
crash and never a guessed witness, and never poisons the other entries in
the same array. Representable even when `run["results"] == []` -- the exact
shape schema `/4`'s per-result carrier could not express (AR2). Schema `/4`'s
OLD per-result reader is REMOVED, not kept as a silent second accepted
transport: no governed R_B was ever taken against it (T_B/R_B have stayed
unretaken through this whole amendment arc), so there is no real backward-
compatibility need, and one transport is safer than two. Preregistered, not
implemented: `rust/crates/own-bridge/src/verdict.rs`/`src/render.rs`'s exact
new items are authorized as mutable by `production_diff_gate.rust`
(CH3-8's own item set; see that record's own supersession note) -- this
task does not implement the producer or assume its existence.

A witness is NEVER trusted at face value, and neither is a CLAIMED
correlation to a diagnostic key -- a structurally valid witness must not be
able to excuse an unrelated diagnostic merely by naming its key (a small
permission system is exactly the shape that turns into a hole). Instead,
`_verify_call_site_witness()` DERIVES the expected signature from the
witness's OWN semantic fields alone and independently confirms it against
the REAL captured SARIF message text, never the witness's own claim: for
`lowered == "plain"` (the only shape a call-site witness reaches
CONDITIONALITY_HONESTY through), the AFTER snapshot must carry an
`OWN051`/`note` finding at EXACTLY `witness.site.line` whose message
contains BOTH `witness.callee` and `witness.resource_name` -- own-cli's own
OWN051 message names both, by construction, so this is checking real,
already-produced text, not a schema the witness invented. If
`witness.resource_acquire_site` is given, the BEFORE snapshot must
symmetrically carry SOME finding at that line whose message contains
`resource_name`; that finding's own key becomes the (single, derived, never
witness-named) removed key. Verification fails -- the witness explains
NOTHING -- if either anchor is absent, mismatched, or (for the acquire site)
uncorrelatable; there is no partial credit and no fallback that accepts a
movement merely because "this looks like P-037" (item D's four fail-closed
cases, each pinned by a dedicated selftest case). One classified, VERIFIED
call excuses only the exact keys its own anchors independently confirm,
never the rest of a file's diff, and a file with zero witnesses -- every
snapshot today -- behaves exactly as before this amendment: MOVED,
unconditionally.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import p037_b_classifier as clf
import p037_evidence as ev
import p037_evidence_b

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "p037-verdict-snapshot/5"
VERDICT_LEVELS = ("error", "warning")
# CH3-8: run-level, plural -- schema /4's per-result singular
# `p037_call_site_witness` is retired with it (see module docstring).
RUN_LEVEL_WITNESS_PROPERTY = "p037_call_site_witnesses"
# Epoch is explicit and required -- same precedent this module's own
# docstring already states for ENGINE, extended to epoch selection (P-037
# Phase B: never an implicit "current epoch", branch-name inference or a
# silently-read env var). main() rebinds the module-global `ev` to the
# selected module before calling take()/_measure()/compare()/verify()/
# run_one() below; their bodies read `ev.*` at call time and are otherwise
# UNCHANGED for either epoch.
EPOCH_MODULES: dict[str, Any] = {"a2d": ev, "b": p037_evidence_b}

# R1-review of 20b09c9: the ONE named source of truth for the `--severity`
# threshold run_one() invokes with, so observation-binding anchors below
# cannot silently drift from the actual governed measurement command --
# never a literal "warning" duplicated ad hoc at each anchor site. Confirmed
# mechanically, not assumed, against the frozen rust/crates/own-bridge/src/
# render.rs::sarif_level (`if severity == "warning" || f.severity ==
# Some("warning") { "warning" } else { "error" }`, advisories always
# "note" regardless): a real `own-check.sh --engine rust --format sarif
# --severity warning` run against an unambiguous real leak fixture
# (scratchpad, this repair) rendered its OWN001 at level "warning", never
# "error" -- the host severity, at this threshold, only ever lowers a
# non-advisory finding's level, it never leaves it at the tool's own
# internal default ("error", own-cli's own `parse()`).
_RUN_ONE_SEVERITY = "warning"


def _extract_run_level_witnesses(run: dict[str, Any]) -> list[dict[str, Any]]:
    """One SARIF run's own `properties.p037_call_site_witnesses[]`, filtered
    to well-formed entries -- fail-closed (item D, ported to the run-level
    carrier): a missing key, a non-list payload, a non-object array entry,
    or an entry `check_call_site_witness()` itself refuses is DROPPED (that
    ONE witness is absent), never a crash, never a guessed witness, and
    never poisons the other witnesses in the same array. Representable even
    when `run["results"] == []` -- the exact shape schema `/4`'s per-result
    carrier could not express (AR2; see module docstring). No production
    emitter populates this key yet (see this module's own docstring) --
    every real SARIF run today lacks `properties` entirely, or lacks this
    key within it, so this function returns `[]` for all of them,
    unconditionally."""
    props = run.get("properties")
    if not isinstance(props, dict):
        return []
    raw = props.get(RUN_LEVEL_WITNESS_PROPERTY)
    if not isinstance(raw, list):
        return []
    witnesses: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            clf.check_call_site_witness(item)
        except clf.WitnessError:
            continue
        witnesses.append(item)
    return witnesses


def _parse_sarif_doc(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The pure, directly-testable half of `run_one()`: an already-parsed
    SARIF document in, `(findings, call_site_witnesses)` out. Kept separate
    from the subprocess invocation so a hand-built SARIF document (a
    zero-semantics fixture at the INSTRUMENT boundary -- see this module's
    own docstring and item C of the amendment this satisfies) can drive the
    exact same parsing/validation/storage path a real capture will, without
    faking `compare()`'s own governed provenance gate, which is an
    orthogonal concern this function has no part in."""
    findings: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    for run in doc.get("runs", []):
        for res in run.get("results", []):
            loc = (res.get("locations") or [{}])[0]
            region = loc.get("physicalLocation", {}).get("region", {})
            findings.append({
                "code": res.get("ruleId", "?"),
                "level": res.get("level", "?"),
                "line": region.get("startLine", 0),
                "message": (res.get("message") or {}).get("text", ""),
            })
        witnesses.extend(_extract_run_level_witnesses(run))
    findings.sort(key=lambda f: (f["line"], f["code"], f["level"]))
    return findings, witnesses


def run_one(path: Path, engine: str, env: dict[str, str]) -> dict[str, Any]:
    """One file through the launcher; SARIF in, (exit, findings,
    call_site_witnesses) out."""
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", _RUN_ONE_SEVERITY, "--", str(path)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False, env=env)
    findings: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    parse_error = ""
    try:
        doc = json.loads(proc.stdout)
        findings, witnesses = _parse_sarif_doc(doc)
    except json.JSONDecodeError as exc:
        # Not silently swallowed: a file whose SARIF did not parse is recorded
        # as such, so it can never be mistaken for a file with no findings.
        parse_error = f"{type(exc).__name__}: {exc}"
    rec: dict[str, Any] = {
        "exit": proc.returncode, "findings": findings, "call_site_witnesses": witnesses,
    }
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


_AFTER_ANCHOR: dict[str, tuple[str, str, str, bool] | None] = {
    # lowered -> (code, sarif level, anchor point, must_contain_callee) the
    # AFTER snapshot must independently show for that lowering, or None if
    # this lowering has no fixed, derivable ADDED-side signature.
    #
    # The anchor point is NOT the same coordinate for every lowering,
    # checked against real captured text, not assumed by analogy: "site" is
    # the call site itself (`witness.site.line` -- U1's own measured
    # OWN051, which own-cli anchors at the call); "acquire" is the
    # resource's OWN acquire site (`witness.resource_acquire_site.line` --
    # AR1's own measured OWN001, which own-cli anchors where the resource
    # was created, e.g. `var s = File.OpenRead(...)`, not where it was
    # passed to the guarded callee). An "acquire"-anchored lowering with no
    # `resource_acquire_site` at all has no line to check and cannot be
    # explained this way -- not a skipped check, there is genuinely nothing
    # to anchor to.
    #
    # must_contain_callee is ALSO not uniform, checked against real
    # captured text, not assumed: U1's own OWN051 message names both the
    # callee and the resource ("cannot verify whether 'ShapeU1.Inner' takes
    # ownership of 's'..."), but AR1's own OWN001 message names ONLY the
    # resource ("IDisposable local 's' is never disposed (leak)...") -- a
    # generic local-leak diagnostic that does not know or care which
    # downstream call (mis)handled it. Requiring the callee in `borrow`'s
    # own match would make a REAL, correctly-measured AR1 movement
    # unmatchable, which is exactly the kind of assumed-not-measured defect
    # this whole file's own discipline exists to catch.
    # R1-review of 20b09c9: this was hand-typed "error" -- plausible by
    # analogy to a generic notion of "leak severity", but never checked
    # against the actual governed run_one() profile. A real
    # `own-check.sh --engine rust --format sarif --severity warning` run
    # (this repair's own scratch measurement, an unambiguous real leak
    # fixture) renders a real, non-advisory OWN001 at level "warning", not
    # "error" -- confirmed against the frozen render.rs::sarif_level, which
    # forces every non-advisory finding to the host `--severity` value once
    # that value is itself "warning" (own-cli's own internal default,
    # "error", only survives when no `--severity` override is given at
    # all -- run_one() always gives one). _RUN_ONE_SEVERITY is the one named
    # source of truth for that value, never a literal duplicated here.
    "plain": ("OWN051", "note", "site", True),
    "borrow": ("OWN001", _RUN_ONE_SEVERITY, "acquire", False),
    # "consume": no measured before/after shape exists for a consume-lowered
    # call site yet (AR1/AR2 both measured a Borrow selection) -- left
    # unmapped rather than invented; see _verify_call_site_witness's own
    # docstring and item 12's own closing rule (UNCLASSIFIED, not a guess,
    # until a real measurement extends this).
    "consume": None,
}

# CH3-8: AR2's own measured shape -- a REMOVED explanation, for a lowering
# whose AFTER-added anchor above does not correlate at all (e.g. because the
# correct Borrow selection removed a fabricated double-dispose rather than
# adding a leak: AR2's own `results == []`). Bounded to exactly this one
# measured lowering, never a second, invented "any code disappears" rule --
# extending it to "consume" needs its own measurement first, the same
# discipline `_AFTER_ANCHOR` above already states.
#
# R1-review of 20b09c9: this was a frozenset (`{"borrow"}`), and
# _verify_call_site_witness() paired it with `_finding_containing_at_line`
# -- ANY finding (any code, any level) at the acquire line whose message
# contains the resource name. Too permissive: a real Borrow witness could
# then excuse an UNRELATED same-line, same-resource diagnostic it never
# actually explains. AR2 measured exactly ONE removal shape -- a real
# OWN003 at the acquire site, at the governed `--severity warning` level --
# so this is now a dict, mirroring `_AFTER_ANCHOR`'s own (code, level)
# precision, checked with the SAME exact-match `_finding_at` the ADDED
# branch already uses, never the broad line-only primitive.
_BEFORE_REMOVED_ANCHOR: dict[str, tuple[str, str] | None] = {
    "borrow": ("OWN003", _RUN_ONE_SEVERITY),
}


def _quoted_identifier(value: str) -> str:
    """The exact quoted-token form every frozen diagnostic template uses for
    an identifier (own-cli's own OWN001/OWN003: `local '{name}'`; OWN051:
    `'{callee}' takes ownership of '{arg}'`) -- R1-review of b31e7a0: a bare
    `resource_name`/`callee` substring check is unsound for a real
    single-letter resource (`"s"` is a substring of "disposed"/"resource"/
    "disposable", so a message about a DIFFERENT resource can still contain
    it) and for a prefix-sharing callee name (`ShapeU1.Inner` is a substring
    of `ShapeU1.InnerExtra`). A C# identifier cannot itself contain `'`, so
    the quoted token is a strictly stronger, still-substring, still
    real-template-grounded boundary -- never a general prose parser."""
    return f"'{value}'"


def _finding_at(rec: dict[str, Any], line: int, code: str, level: str,
                must_contain: tuple[str, ...]) -> tuple[int, str, str] | None:
    """The `(line, code, level)` key of a finding actually present in `rec`
    at exactly `line`/`code`/`level`, whose own MESSAGE TEXT (produced by
    the real analysis, never claimed by a witness) contains every string in
    `must_contain` -- or `None` if no such finding exists. This is the
    observation-binding primitive: it looks at what the snapshot itself
    recorded, never at what a witness merely asserts."""
    for f in rec.get("findings", []) or []:
        if (f.get("line"), f.get("code"), f.get("level")) != (line, code, level):
            continue
        message = f.get("message", "")
        if all(s in message for s in must_contain):
            return (line, code, level)
    return None


def _finding_containing_at_line(rec: dict[str, Any], line: int,
                                must_contain: tuple[str, ...]) -> tuple[int, str, str] | None:
    """Like `_finding_at`, but for the BEFORE/legacy side, where the witness
    does not (and structurally cannot, per its own frozen schema) name a
    fixed code -- legacy's own diagnostic vocabulary at an acquire site is
    broad (OWN001, OWN003, ...). Still anchored to a REAL finding's own
    message text at an EXACT line the witness names, never to a claimed
    key."""
    for f in rec.get("findings", []) or []:
        if f.get("line") != line:
            continue
        message = f.get("message", "")
        if all(s in message for s in must_contain):
            return (f.get("line"), f.get("code"), f.get("level"))
    return None


def _verify_call_site_witness(
    witness: dict[str, Any], before_rec: dict[str, Any], after_rec: dict[str, Any],
    expected_file: str,
) -> dict[str, Any] | None:
    """Independently verifies one call-site witness against the REAL
    before/after records for the SAME file -- never trusts a claimed
    correlation (see module docstring: observation binding, not permission
    naming). Returns `None` (explains nothing) unless the witness is
    schema-valid, it classifies into a CLOSED class, its OWN claimed
    `site.file` is the file actually being compared, AND one of two
    independently-observed shapes holds:

    FILE IDENTITY (R1-review of 20b09c9, corrected again by the review of
    b31e7a0): `witness["site"]["file"]` must equal `expected_file` --
    reconstructed by `compare()`, NEVER the snapshot's own bare per-file key
    (`rel`) by itself. Mechanically derived from committed source, not a
    future producer's choice: the frozen extractor's `Rel(path)` (Program.cs)
    is `Path.GetRelativePath(Directory.GetCurrentDirectory(), path)`; `own-
    check.sh` never changes directory; `run_one()` invokes it with
    `cwd=ROOT` and an ABSOLUTE `path` under `ROOT/<materialization_root>/
    <rel>` (`ev.materialize_population`/`analysis_paths`). So the one
    spelling any OwnIR-derived `file` field (and, by the same construction,
    a real future call-site witness's own `site.file`) can carry is
    `<materialization_root>/<rel>`, exactly -- bare `rel` alone (what
    b31e7a0 actually checked) is a DIFFERENT, shorter string a real witness
    would never produce, confirmed by walking the actual path arithmetic,
    not assumed by analogy to `compare()`'s own per-file loop key. own-cli's
    SARIF `artifactLocation.uri` is a separate, own-check.sh-internal
    materialization-path artifact (confirmed by a real scratch run) and is
    never the source of `expected_file` either. Checked BEFORE either shape
    below: a witness naming a different file must not explain a movement in
    this one, however well every other field lines up -- exact string
    equality, no basename or suffix matching.

    ADDED (every lowering with an `_AFTER_ANCHOR` entry -- today `plain`
    and, since CH3-8, `borrow`/AR1's own measured shape): the AFTER record
    carries that lowering's fixed signature, at the coordinate `_AFTER_
    ANCHOR` names for it (`site.line` for `plain`; `resource_acquire_site.
    line` for `borrow` -- checked against real captured text, NOT the same
    coordinate for both: own-cli anchors OWN051 at the call and OWN001 at
    the resource's own acquire site), with a message containing the
    QUOTED-IDENTIFIER-TOKEN form (`_quoted_identifier()`, R1-review of
    b31e7a0) of both `callee` and `resource_name` -- never a bare substring
    check, which a real single-letter `resource_name` like AR1/AR2's own
    "s" cannot survive (it is a substring of "disposed"/"resource"/
    "disposable" regardless of which local the message actually names).
    For a `site`-anchored lowering ONLY, if
    `resource_acquire_site` is ALSO given, the BEFORE record must
    independently correlate too -- a claimed acquire site that does not
    correlate is a hard failure, never a skipped check (item D's fail-closed
    rule); an `acquire`-anchored lowering has no SEPARATE before-side
    correlation to demand on top of its own anchor (AR1's own measured
    shape has no before-side finding at all -- it is a genuinely NEW leak,
    not a movement with two sides).

    REMOVED (CH3-8, bounded to `_BEFORE_REMOVED_ANCHOR` -- today only
    `borrow`/AR2's own measured shape, the AR2 kill-gate itself: a run-level
    witness can exist with NO after-side finding at all, `run["results"] ==
    []`): only tried when ADDED does not correlate, and only when
    `resource_acquire_site` is given -- the BEFORE record must carry a
    finding at that EXACT line, EXACT code, EXACT level (R1-review of
    20b09c9: was any code/any level via `_finding_containing_at_line`, which
    let an unrelated same-line same-resource diagnostic be silently
    legalized away by a witness that never actually explained it; now the
    same exact-match `_finding_at` the ADDED branch already uses) whose
    message contains `resource_name`'s own quoted-identifier-token form
    (same `_quoted_identifier()`, same reasoning). A witness satisfying
    NEITHER shape
    explains nothing: UNCLASSIFIED is the correct outcome for a real future
    movement outside these two measured signatures, not an invitation to
    widen this function in advance (item 12's own closing rule).

    On success, returns the single derived `after_key` and/or `before_key`
    (never both `None`, never a witness-supplied key of any kind) plus the
    classification."""
    try:
        clf.check_call_site_witness(witness)
    except clf.WitnessError:
        return None
    classification = clf.classify_call_site(witness)
    if classification["class"] not in clf.CLOSED_CLASSES:
        return None
    if witness["site"]["file"] != expected_file:
        return None
    lowered = witness["lowered"]
    site = witness["site"]
    acquire = witness.get("resource_acquire_site")

    after_key = None
    anchor = _AFTER_ANCHOR.get(lowered)
    if anchor is not None:
        code, sarif_level, anchor_point, must_contain_callee = anchor
        anchor_line = site["line"] if anchor_point == "site" else (
            acquire["line"] if acquire is not None else None)
        if anchor_line is not None:
            quoted_resource = _quoted_identifier(witness["resource_name"])
            must_contain = ((_quoted_identifier(witness["callee"]), quoted_resource)
                           if must_contain_callee else (quoted_resource,))
            after_key = _finding_at(after_rec, anchor_line, code, sarif_level, must_contain)

    if after_key is not None:
        if anchor is not None and anchor[2] == "site" and acquire is not None:
            before_key = _finding_containing_at_line(
                before_rec, acquire["line"], (_quoted_identifier(witness["resource_name"]),))
            if before_key is None:
                return None  # a claimed acquire site that does not correlate is a hard failure
            return {"witness": witness, "classification": classification,
                   "before_key": before_key, "after_key": after_key}
        return {"witness": witness, "classification": classification,
               "before_key": None, "after_key": after_key}

    removed_anchor = _BEFORE_REMOVED_ANCHOR.get(lowered)
    if removed_anchor is not None and acquire is not None:
        code, sarif_level = removed_anchor
        before_key = _finding_at(before_rec, acquire["line"], code, sarif_level,
                                 (_quoted_identifier(witness["resource_name"]),))
        if before_key is not None:
            return {"witness": witness, "classification": classification,
                   "before_key": before_key, "after_key": None}
    return None


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
    # R1-review of b31e7a0 (F2.5): witness file binding below reconstructs
    # the producer's own path spelling from the AFTER snapshot's
    # `materialization_root` -- fail closed on a missing/malformed value
    # rather than silently falling back to a shorter, wrong string
    # (`_snapshot_problems()` does not already check this field).
    after_root = b.get("materialization_root")
    if not isinstance(after_root, str) or not after_root:
        problems.append("after: snapshot carries no materialization_root for witness "
                        "file binding")
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        return 2
    print(f"comparing engine={a['engine']} at {a['source_commit'][:7]} -> "
          f"{b['source_commit'][:7]}, population={a['population_commit'][:12]}, level={level}")
    moved = 0
    classified = 0
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
        removed, added = ka - kb, kb - ka
        # R1-review of b31e7a0 (F2): the producer-native file spelling a real
        # witness's own `site.file` would carry is `<materialization_root>/
        # <rel>` (Program.cs's `Rel()` against `run_one()`'s own `cwd=ROOT`
        # and absolute, materialized input path), never bare `rel` alone.
        expected_witness_file = f"{after_root}/{rel}"
        verified = [v for w in (rb.get("call_site_witnesses") or [])
                   if isinstance(w, dict)
                   and (v := _verify_call_site_witness(w, ra, rb, expected_witness_file))]
        explained_removed = {v["before_key"] for v in verified if v["before_key"]} & removed
        explained_added = {v["after_key"] for v in verified if v["after_key"]} & added
        unexplained_removed = removed - explained_removed
        unexplained_added = added - explained_added
        # exit is a pure function of the SAME findings list key_set() already
        # reads (verdict-level: any error/warning present); once every
        # removed/added key at this level is independently classified, an
        # exit-code movement is that classification's own direct
        # consequence, not a second, separately-unexplained fact.
        if not unexplained_removed and not unexplained_added and (removed or added):
            classified += 1
            suffix = f", exit {ra['exit']} -> {rb['exit']}" if exit_moved else ""
            used = [v for v in verified
                   if v["before_key"] in explained_removed or v["after_key"] in explained_added]
            print(f"  CLASSIFIED {rel}  ({len(used)} call-site witness(es){suffix})")
            for v in used:
                print(f"      {v['classification']['class']}: {v['witness']['callee']} -- "
                      f"{v['classification']['reason']}")
            continue
        moved += 1
        print(f"  MOVED {rel}")
        if exit_moved:
            print(f"      exit {ra['exit']} -> {rb['exit']}")
        for f in sorted(unexplained_removed):
            print(f"      - {f[1]} {f[2]} @{f[0]}")
        for f in sorted(unexplained_added):
            print(f"      + {f[1]} {f[2]} @{f[0]}")
        for f in sorted(explained_removed):
            print(f"      - {f[1]} {f[2]} @{f[0]}  (classified, see above)")
        for f in sorted(explained_added):
            print(f"      + {f[1]} {f[2]} @{f[0]}  (classified, see above)")
    files = len(set(a["files"]) | set(b["files"]))
    if moved == 0 and classified == 0:
        print(f"\nRESULT: UNCHANGED — {files} file(s), no verdict moved at level={level}")
        return 0
    if moved == 0:
        print(f"\nRESULT: CLASSIFIED — {classified} of {files} file(s) moved at level={level}, "
              f"every movement named by a CLOSED-class call-site witness")
        return 0
    print(f"\nRESULT: {moved} of {files} file(s) MOVED at level={level}"
          f"{f' ({classified} more fully classified)' if classified else ''} — "
          f"every unclassified one needs a declared class, or it is a defect")
    return 1


# --------------------------------------------------------------------------- selftest
#
# `compare()`'s own outer shell (`ev.comparison_problems`/`provenance_
# problems`) is not exercised here: it correctly refuses any hand-built
# snapshot that is not real, governed evidence (dirty-tree, epoch,
# environment_id, instrument-closure and population checks all fire on a
# synthetic document) -- that refusal is the provenance gate working, not a
# reason to weaken it or fabricate a fake "real" snapshot just to exercise
# this amendment. What IS exercised here, end to end, through the REAL
# functions `run_one()` itself calls (never a hand-written stand-in): a
# realistic SARIF document (U1's own real, previously-measured message
# text) carrying a properties-bag witness, through `_parse_sarif_doc()`,
# through `_verify_call_site_witness()` against a matching BEFORE record --
# no witness dict is ever handed directly to `compare()` or injected past
# the parsing layer. This is the "closest directly-testable _measure/
# run_one path" the pre-T_B closure gate asks for.

# R1-review of b31e7a0 (F2): every test witness's `site.file` -- and every
# direct `_verify_call_site_witness()` call's own `expected_file` argument --
# now carries the REAL producer-native spelling `compare()` itself
# reconstructs (`<materialization_root>/<rel>`), never a bare filename.
# `_TEST_MATERIALIZATION_ROOT` is a realistic, clearly-synthetic stand-in for
# `ev.materialization_root()`'s own shape (`.p037-population/<40-char
# population commit>/<16-char digest prefix>`), fixed once here so every
# fixture below composes it identically.
_TEST_MATERIALIZATION_ROOT = (
    ".p037-population/1111111111111111111111111111111111abcd/deadbeefcafebabe")


def _witness_file(rel: str) -> str:
    return f"{_TEST_MATERIALIZATION_ROOT}/{rel}"


_U1_WITNESS: dict[str, Any] = {
    "kind": "call_site", "callee": "ShapeU1.Inner", "callee_param": 0,
    "site": {"file": _witness_file("U1.cs"), "line": 16, "column": 9},
    "resource_name": "s", "resource_acquire_site": {"line": 14},
    "guarded": {"shape": "split", "finalized_cells": {"pos": "no", "neg": "must"},
               "collapsed": "may"},
    "selection": "unselected", "lowered": "plain",
}
# The REAL messages own-cli produced for this exact fixture (measured
# earlier against the held R1 treatment, own-check.sh --format human;
# reproduced here verbatim as SARIF `message.text` -- not invented prose).
_U1_BEFORE_MESSAGE = "IDisposable local 's' is never disposed (leak) [resource: disposable]"
_U1_AFTER_MESSAGE = ("cannot verify whether 'ShapeU1.Inner' takes ownership of 's' "
                    "(inferred contract: may); optimistically assuming it does "
                    "— 's' is not checked past this call [resource: ownership transfer]")


def _sarif_doc(results: list[dict[str, Any]], *,
              witnesses: list[Any] | None = None,
              witnesses_present: bool = True) -> dict[str, Any]:
    """One SARIF run with `results` and, since CH3-8, the RUN-level
    `properties.p037_call_site_witnesses[]` -- `witnesses_present=False`
    reproduces a run with no properties bag at all (item D.1's own shape,
    every real SARIF document before a producer exists); `witnesses=None`
    with `witnesses_present=True` reproduces the property present but
    empty (every real snapshot today, once a producer exists but this file
    has no guarded call site)."""
    run: dict[str, Any] = {"results": results}
    if witnesses_present:
        run["properties"] = {RUN_LEVEL_WITNESS_PROPERTY: witnesses if witnesses is not None else []}
    return {"runs": [run]}


def _sarif_result(line: int, code: str, level: str, message: str) -> dict[str, Any]:
    return {
        "ruleId": code, "level": level, "message": {"text": message},
        "locations": [{"physicalLocation": {"region": {"startLine": line}}}],
    }


def _u1_before_rec() -> dict[str, Any]:
    findings, witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(14, "OWN001", "warning", _U1_BEFORE_MESSAGE)], witnesses_present=False))
    return {"exit": 1, "findings": findings, "call_site_witnesses": witnesses}


def _u1_after_rec(**overrides: Any) -> dict[str, Any]:
    """The real, future-shaped AFTER capture: a SARIF run (the real OWN051
    result, `results` possibly empty per AR2's own measured shape) carrying
    the RUN-level witness array, parsed through the REAL `_parse_sarif_doc()`
    -- never a hand-built `call_site_witnesses` list."""
    witness = {**_U1_WITNESS, **overrides.pop("witness_overrides", {})}
    extra_results = overrides.pop("extra_results", [])
    extra_witnesses = overrides.pop("extra_witnesses", [])
    base_results = overrides.pop(
        "results", [_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE)])
    findings, witnesses = _parse_sarif_doc(_sarif_doc(
        [*base_results, *extra_results],
        witnesses=[witness, *extra_witnesses]))
    return {"exit": 0, "findings": findings, "call_site_witnesses": witnesses}


def _vfail(_failures: list[str], name: str, ok: bool, detail: object = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def selftest() -> int:
    failures: list[str] = []

    before, after = _u1_before_rec(), _u1_after_rec()
    _vfail(failures, "parse-sarif-doc-extracts-the-real-witness",
          len(after["call_site_witnesses"]) == 1, after)

    v = _verify_call_site_witness(after["call_site_witnesses"][0], before, after,
                                  _witness_file("U1.cs"))
    _vfail(failures, "e2e-classifies-a-real-captured-witness",
          v is not None and v["classification"]["class"] == clf.CONDITIONALITY_HONESTY, v)
    _vfail(failures, "e2e-derives-the-real-after-key",
          v is not None and v["after_key"] == (16, "OWN051", "note"), v)
    _vfail(failures, "e2e-derives-the-real-before-key",
          v is not None and v["before_key"] == (14, "OWN001", "warning"), v)

    # item D.1 -- absent witness: an AFTER run with no properties bag at
    # all carries no witnesses, exactly today's every real snapshot, through
    # the REAL _parse_sarif_doc() path (never a hand-built list).
    _, no_props_witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE)], witnesses_present=False))
    _vfail(failures, "absent-properties-bag-is-empty", no_props_witnesses == [])

    # item D.1b (CH3-8) -- the property present but empty: the exact shape
    # AR1/AR2's own hostile-plain control measured for a file with no
    # guarded call site at all (results present, zero witnesses).
    _, empty_prop_witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE)], witnesses=[]))
    _vfail(failures, "empty-witnesses-property-is-empty", empty_prop_witnesses == [])

    # item D.1c (CH3-8) -- a non-list property value (e.g. the old schema/4
    # shape's own singular object, or any other malformed payload) is
    # treated as absent, not guessed or partially read.
    _, non_list_witnesses = _parse_sarif_doc({"runs": [{
        "results": [_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE)],
        "properties": {RUN_LEVEL_WITNESS_PROPERTY: {"version": 1, "witness": _U1_WITNESS}},
    }]})
    _vfail(failures, "non-list-witnesses-property-fails-closed", non_list_witnesses == [])

    # item D.2 -- malformed witness (fails check_call_site_witness): DROPPED
    # during _parse_sarif_doc itself, never reaches verification at all, and
    # never poisons a well-formed witness in the SAME array.
    malformed = _sarif_doc([_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE)],
                           witnesses=[{"not": "a real witness"}, _U1_WITNESS])
    _, malformed_witnesses = _parse_sarif_doc(malformed)
    _vfail(failures, "malformed-witness-never-parsed-out-others-survive",
          malformed_witnesses == [_U1_WITNESS], malformed_witnesses)

    # item D.3 -- cannot be correlated uniquely: resource_acquire_site is
    # given but the BEFORE record has nothing at that line mentioning the
    # resource -- hard failure, not a skipped check.
    uncorrelated_before = {"exit": 0, "findings": [], "call_site_witnesses": []}
    v_uncorrelated = _verify_call_site_witness(
        after["call_site_witnesses"][0], uncorrelated_before, after, _witness_file("U1.cs"))
    _vfail(failures, "uncorrelatable-acquire-site-fails-closed", v_uncorrelated is None,
          v_uncorrelated)

    # an UNCLASSIFIED witness (uncond shape) explains nothing even though
    # the real AFTER message still matches -- classify_call_site() itself
    # is the gate, not merely finding a message match.
    uncond_after = _u1_after_rec(
        witness_overrides={"guarded": {"shape": "uncond", "finalized_cells": None,
                                      "collapsed": "may"}})
    v_uncond = _verify_call_site_witness(
        uncond_after["call_site_witnesses"][0], before, uncond_after, _witness_file("U1.cs"))
    _vfail(failures, "uncond-witness-is-unclassified-and-explains-nothing", v_uncond is None,
          v_uncond)

    # --- item E: a witness must not be able to authorize an arbitrary
    # diagnostic merely by naming it -- there is no naming here anymore
    # (before_key/after_key are DERIVED), so these pin that the derivation
    # itself stays scoped to real, matching content. ---

    # E.1 (repeated for clarity): valid witness + the real, expected P-037
    # movement -- accepted (already proven above by e2e-classifies-...).
    _vfail(failures, "hostile-e1-valid-witness-accepted",
          v is not None and v["classification"]["class"] == clf.CONDITIONALITY_HONESTY, v)

    # E.2: an unrelated diagnostic change at ANOTHER line must stay
    # unexplained -- simulate compare()'s own set arithmetic directly.
    after_plus_unrelated_line = _u1_after_rec(
        extra_results=[_sarif_result(99, "OWN002", "warning", "unrelated finding")])
    added = {(16, "OWN051", "note"), (99, "OWN002", "warning")}
    verified = [r for w in after_plus_unrelated_line["call_site_witnesses"]
               if (r := _verify_call_site_witness(
                   w, before, after_plus_unrelated_line, _witness_file("U1.cs")))]
    explained_added = {r["after_key"] for r in verified if r["after_key"]} & added
    _vfail(failures, "hostile-e2-unrelated-diagnostic-another-line-stays-unexplained",
          explained_added == {(16, "OWN051", "note")}
          and (99, "OWN002", "warning") not in explained_added, explained_added)

    # E.3: an unrelated diagnostic change at the SAME line (16) -- SARIF
    # allows more than one result per line -- must ALSO stay unexplained;
    # only the exact (line, code, level) the anchor derives is ever matched.
    after_plus_same_line = _u1_after_rec(
        extra_results=[_sarif_result(16, "OWN999", "warning", "unrelated same-line finding")])
    added_same_line = {(16, "OWN051", "note"), (16, "OWN999", "warning")}
    verified_sl = [r for w in after_plus_same_line["call_site_witnesses"]
                  if (r := _verify_call_site_witness(
                      w, before, after_plus_same_line, _witness_file("U1.cs")))]
    explained_sl = {r["after_key"] for r in verified_sl if r["after_key"]} & added_same_line
    _vfail(failures, "hostile-e3-unrelated-diagnostic-same-line-stays-unexplained",
          explained_sl == {(16, "OWN051", "note")}
          and (16, "OWN999", "warning") not in explained_sl, explained_sl)

    # E.4: there is no `explains_added`-style field left for a witness to
    # rename -- the equivalent attack is the REAL after-content at the
    # witness's own site simply not being the derived signature (a
    # coincidental unrelated code at that exact line, no real OWN051 at
    # all); the anchor derivation, not a claim, decides, so this fails too.
    after_wrong_code_at_site = {"exit": 0,
        "findings": [{"line": 16, "code": "OWN002", "level": "warning",
                     "message": "an unrelated diagnostic that happens to share the line"}],
        "call_site_witnesses": [_U1_WITNESS]}
    v_wrong_code = _verify_call_site_witness(_U1_WITNESS, before, after_wrong_code_at_site,
                                             _witness_file("U1.cs"))
    _vfail(failures, "hostile-e4-witness-cannot-rename-what-is-actually-at-its-own-site",
          v_wrong_code is None, v_wrong_code)

    # item H, CORRECTED (R1-review of 20b09c9): the ORIGINAL version of this
    # test was labelled cross-file/cross-site but never varied `site.file`
    # at all -- it substituted an unrelated MESSAGE (different callee/
    # resource) at the SAME line, same file. Kept, renamed accurately: still
    # a real, useful message-content correlation control, just not what its
    # own name claimed.
    same_site_wrong_message_after = {"exit": 0,
        "findings": [{"line": 16, "code": "OWN051", "level": "note",
                     "message": "cannot verify whether 'ShapeU2.Outer' takes ownership of 't' "
                               "(inferred contract: may); optimistically assuming it does"}],
        "call_site_witnesses": [_U1_WITNESS]}
    v_wrong_message = _verify_call_site_witness(_U1_WITNESS, before, same_site_wrong_message_after,
                                                _witness_file("U1.cs"))
    _vfail(failures, "hostile-same-site-unrelated-message-content-fails-closed",
          v_wrong_message is None, v_wrong_message)

    # item H, REAL cross-file substitution (R4, R1-review of 20b09c9): the
    # SAME witness, SAME before/after records (a genuinely matching site,
    # line, resource, callee, message) explains nothing when the file
    # actually being compared is NOT the one the witness itself claims --
    # checked via `expected_file`, never via message content or line, which
    # a same-named coincidence elsewhere could still satisfy.
    v_other_file = _verify_call_site_witness(_U1_WITNESS, before, after, "OTHER.cs")
    _vfail(failures, "hostile-real-cross-file-substitution-fails-closed",
          v_other_file is None, v_other_file)
    _vfail(failures, "real-cross-file-control-the-same-witness-classifies-for-its-own-file",
          v is not None and v["classification"]["class"] == clf.CONDITIONALITY_HONESTY, v)

    # F1.4 (R1-review of b31e7a0): the callee token must also be an exact
    # quoted match, not a bare-substring prefix -- a message naming
    # 'ShapeU1.InnerExtra' must not be read as also naming 'ShapeU1.Inner'.
    after_wrong_callee_prefix = {"exit": 0,
        "findings": [{"line": 16, "code": "OWN051", "level": "note",
                     "message": "cannot verify whether 'ShapeU1.InnerExtra' takes "
                               "ownership of 's' (inferred contract: may); optimistically "
                               "assuming it does"}],
        "call_site_witnesses": [_U1_WITNESS]}
    v_wrong_callee_prefix = _verify_call_site_witness(
        _U1_WITNESS, before, after_wrong_callee_prefix, _witness_file("U1.cs"))
    _vfail(failures, "hostile-callee-prefix-does-not-match-a-longer-similar-name",
          v_wrong_callee_prefix is None, v_wrong_callee_prefix)

    # F2.4 (R1-review of b31e7a0): the file-identity check against every
    # wrong shape a bare `rel` (b31e7a0's own actual rule), a basename, or a
    # same-suffix path under a DIFFERENT materialization root could produce
    # -- none of these is the real producer-native spelling, only the exact
    # `<materialization_root>/<rel>` reconstruction is. Uses a witness whose
    # own `rel` carries a subdirectory (`corpus/x/U1.cs`) specifically so
    # "bare rel" and "basename alone" are two genuinely different strings,
    # not the same accidental one; `before`/`after` are U1's own real
    # records, which correlate purely on line/code/message, never on file,
    # so they compose freely with this dedicated witness.
    _witness_subdir_rel = "corpus/x/U1.cs"
    _witness_with_subdir_file = {**_U1_WITNESS,
                                 "site": {**_U1_WITNESS["site"],
                                          "file": _witness_file(_witness_subdir_rel)}}
    v_subdir_correct = _verify_call_site_witness(
        _witness_with_subdir_file, before, after, _witness_file(_witness_subdir_rel))
    _vfail(failures, "file-identity-correct-reconstructed-path-classifies",
          v_subdir_correct is not None
          and v_subdir_correct["classification"]["class"] == clf.CONDITIONALITY_HONESTY,
          v_subdir_correct)
    v_subdir_rel_alone = _verify_call_site_witness(
        _witness_with_subdir_file, before, after, _witness_subdir_rel)
    _vfail(failures, "hostile-file-identity-bare-rel-alone-fails",
          v_subdir_rel_alone is None, v_subdir_rel_alone)
    v_subdir_basename = _verify_call_site_witness(
        _witness_with_subdir_file, before, after, "U1.cs")
    _vfail(failures, "hostile-file-identity-basename-alone-fails",
          v_subdir_basename is None, v_subdir_basename)
    _other_materialization_root = (
        ".p037-population/2222222222222222222222222222222222dcba/fadedcafebabebeef")
    v_subdir_other_root = _verify_call_site_witness(
        _witness_with_subdir_file, before, after,
        f"{_other_materialization_root}/{_witness_subdir_rel}")
    _vfail(failures, "hostile-file-identity-same-suffix-under-another-root-fails",
          v_subdir_other_root is None, v_subdir_other_root)
    v_subdir_other_rel = _verify_call_site_witness(
        _witness_with_subdir_file, before, after, _witness_file("corpus/y/U1.cs"))
    _vfail(failures, "hostile-file-identity-different-rel-under-the-same-root-fails",
          v_subdir_other_rel is None, v_subdir_other_rel)

    # --- CH3-8: AR1/AR2's own measured shapes, through the SAME real
    # _parse_sarif_doc()/_verify_call_site_witness() path U1 used above --
    # never hand-injected witnesses. Message text is REAL, previously
    # measured against the held R1 treatment (AR1) and against d69a6ed, the
    # pre-B2.1a commit (AR2's own state-A false positive) -- reproduced
    # verbatim, not invented prose, the same discipline _U1_BEFORE_MESSAGE/
    # _U1_AFTER_MESSAGE already state. ---
    _AR1_WITNESS: dict[str, Any] = {
        "kind": "call_site", "callee": "ShapeAR1.Inner", "callee_param": 0,
        "site": {"file": _witness_file("case.cs"), "line": 16, "column": 9},
        "resource_name": "s", "resource_acquire_site": {"line": 14},
        "guarded": {"shape": "split", "finalized_cells": {"pos": "no", "neg": "must"},
                   "collapsed": "may"},
        "selection": "pos", "selection_license": {"kind": "bool_const", "value": True},
        "lowered": "borrow",
    }
    _AR1_AFTER_MESSAGE = "IDisposable local 's' is never disposed (leak) [resource: disposable]"
    ar1_before: dict[str, Any] = {"exit": 0, "findings": [], "call_site_witnesses": []}
    ar1_findings, ar1_witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(14, "OWN001", _RUN_ONE_SEVERITY, _AR1_AFTER_MESSAGE)],
        witnesses=[_AR1_WITNESS]))
    ar1_after: dict[str, Any] = {
        "exit": 1, "findings": ar1_findings, "call_site_witnesses": ar1_witnesses}
    _vfail(failures, "run-level-ar1-witness-is-extracted-even-with-a-real-result-present",
          len(ar1_after["call_site_witnesses"]) == 1, ar1_after)
    v_ar1 = _verify_call_site_witness(ar1_after["call_site_witnesses"][0], ar1_before, ar1_after,
                                      _witness_file("case.cs"))
    _vfail(failures, "run-level-ar1-is-application-refinement-explaining-real-own001-addition",
          v_ar1 is not None and v_ar1["classification"]["class"] == clf.APPLICATION_REFINEMENT
          and v_ar1["after_key"] == (14, "OWN001", _RUN_ONE_SEVERITY)
          and v_ar1["before_key"] is None,
          v_ar1)

    # F1.3 (R1-review of b31e7a0): the same real AR1 witness/after-record,
    # but an OWN001 naming a DIFFERENT resource ('other', not 's') at the
    # SAME acquire line -- must stay unexplained despite the bare letter
    # "s" appearing many times in the surrounding English prose.
    ar1_after_wrong_resource: dict[str, Any] = {
        "exit": 1,
        "findings": [{"line": 14, "code": "OWN001", "level": _RUN_ONE_SEVERITY,
                     "message": "IDisposable local 'other' is never disposed (leak) "
                               "[resource: disposable]"}],
        "call_site_witnesses": ar1_after["call_site_witnesses"],
    }
    v_ar1_wrong_resource = _verify_call_site_witness(
        ar1_after["call_site_witnesses"][0], ar1_before, ar1_after_wrong_resource,
        _witness_file("case.cs"))
    _vfail(failures, "hostile-ar1-own001-wrong-resource-stays-unexplained",
          v_ar1_wrong_resource is None, v_ar1_wrong_resource)

    _AR2_WITNESS: dict[str, Any] = {
        "kind": "call_site", "callee": "ShapeAR2.Inner", "callee_param": 0,
        "site": {"file": _witness_file("case.cs"), "line": 15, "column": 9},
        "resource_name": "s", "resource_acquire_site": {"line": 14},
        "guarded": {"shape": "split", "finalized_cells": {"pos": "no", "neg": "must"},
                   "collapsed": "may"},
        "selection": "pos", "selection_license": {"kind": "bool_const", "value": True},
        "lowered": "borrow",
    }
    _AR2_BEFORE_MESSAGE = "IDisposable local 's' is disposed more than once [resource: disposable]"
    ar2_before_findings, _ = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(14, "OWN003", _RUN_ONE_SEVERITY, _AR2_BEFORE_MESSAGE)],
        witnesses_present=False))
    ar2_before: dict[str, Any] = {
        "exit": 1, "findings": ar2_before_findings, "call_site_witnesses": []}
    # AR2's own kill-gate shape: `results == []`, the exact document the
    # per-result-only schema/4 transport could not carry a witness on at
    # all -- the run-level property is still present and non-empty.
    ar2_after_findings, ar2_after_witnesses = _parse_sarif_doc(_sarif_doc(
        [], witnesses=[_AR2_WITNESS]))
    ar2_after: dict[str, Any] = {
        "exit": 0, "findings": ar2_after_findings,
        "call_site_witnesses": ar2_after_witnesses}
    _vfail(failures, "run-level-ar2-witness-survives-an-empty-results-array",
          ar2_after["findings"] == [] and len(ar2_after["call_site_witnesses"]) == 1, ar2_after)
    v_ar2 = _verify_call_site_witness(ar2_after["call_site_witnesses"][0], ar2_before, ar2_after,
                                      _witness_file("case.cs"))
    _vfail(failures, "run-level-ar2-is-application-refinement-explaining-real-own003-removal",
          v_ar2 is not None and v_ar2["classification"]["class"] == clf.APPLICATION_REFINEMENT
          and v_ar2["before_key"] == (14, "OWN003", _RUN_ONE_SEVERITY)
          and v_ar2["after_key"] is None,
          v_ar2)

    # hostile (AR-shaped): witness absent entirely -- an empty run-level
    # array explains nothing, even against the identical before/after pair.
    _ar2_no_witness_findings, ar2_no_witness = _parse_sarif_doc(_sarif_doc([], witnesses=[]))
    _vfail(failures, "hostile-ar-witness-absent-is-unexplained", ar2_no_witness == [])

    # hostile (AR-shaped): a malformed run-level witness (fails
    # check_call_site_witness) is dropped during parsing, never reaches
    # verification, and does not resurrect AR2's own real removal either.
    _ar2_malformed_findings, ar2_malformed_witnesses = _parse_sarif_doc(_sarif_doc(
        [], witnesses=[{"kind": "call_site", "site": {"file": "x", "line": 1, "column": 1}}]))
    _vfail(failures, "hostile-ar-malformed-run-level-witness-is-dropped",
          ar2_malformed_witnesses == [])

    # R5 (R1-review of 20b09c9): a malformed witness sharing a run-level
    # array with an otherwise WELL-FORMED one must not poison that sibling's
    # own explanation. `malformed-witness-never-parsed-out-others-survive`
    # (item D.2, above) already proves the parsed LIST survives; this proves
    # the survivor still classifies and explains its own real movement end
    # to end, through the same array a malformed entry shares.
    _, ar1_mixed_witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(14, "OWN001", _RUN_ONE_SEVERITY, _AR1_AFTER_MESSAGE)],
        witnesses=[{"kind": "call_site", "site": {"file": "x", "line": 1, "column": 1}},
                  _AR1_WITNESS]))
    _vfail(failures, "malformed-sibling-does-not-poison-a-well-formed-witness-in-the-same-array",
          ar1_mixed_witnesses == [_AR1_WITNESS], ar1_mixed_witnesses)
    ar1_after_mixed = {**ar1_after, "call_site_witnesses": ar1_mixed_witnesses}
    v_ar1_mixed = _verify_call_site_witness(ar1_mixed_witnesses[0], ar1_before, ar1_after_mixed,
                                            _witness_file("case.cs"))
    _vfail(failures, "malformed-sibling-does-not-poison-the-survivors-own-classification",
          v_ar1_mixed is not None
          and v_ar1_mixed["classification"]["class"] == clf.APPLICATION_REFINEMENT, v_ar1_mixed)

    # hostile (AR-shaped): an invalid selection_license (missing `kind`) is
    # refused at the schema level, never silently classified either way.
    ar1_bad_license = {**_AR1_WITNESS, "selection_license": {"value": True}}
    try:
        clf.check_call_site_witness(ar1_bad_license)
        _vfail(failures, "hostile-ar-invalid-selection-license-is-refused", False,
              "did not raise")
    except clf.WitnessError:
        _vfail(failures, "hostile-ar-invalid-selection-license-is-refused", True)

    # hostile (AR-shaped): the selected-cell/lowered mismatch -- classify_
    # call_site() itself rejects this (own tests in p037_b_classifier.py),
    # so _verify_call_site_witness must also explain nothing for it, end to
    # end, through the real SARIF-document path.
    ar1_mismatched = {**_AR1_WITNESS, "lowered": "consume"}
    v_ar1_mismatch = _verify_call_site_witness(ar1_mismatched, ar1_before, ar1_after,
                                               _witness_file("case.cs"))
    _vfail(failures, "hostile-ar-selected-cell-lowered-mismatch-is-unexplained",
          v_ar1_mismatch is None, v_ar1_mismatch)

    # hostile (AR-shaped): a same-resource-looking diagnostic at a DIFFERENT
    # line than the witness's own acquire site must not correlate --
    # _finding_at only ever matches its own exact line.
    ar2_other_file_before = {"exit": 1,
        "findings": [{"line": 99, "code": "OWN003", "level": _RUN_ONE_SEVERITY,
                     "message": "IDisposable local 's' is disposed more than once "
                               "[resource: disposable]"}],
        "call_site_witnesses": []}
    v_ar2_other_file = _verify_call_site_witness(
        ar2_after["call_site_witnesses"][0], ar2_other_file_before, ar2_after,
        _witness_file("case.cs"))
    _vfail(failures, "hostile-ar-same-resource-wrong-line-stays-unexplained",
          v_ar2_other_file is None, v_ar2_other_file)

    # R2 (R1-review of 20b09c9): the REMOVED-branch anchor used to accept
    # ANY finding at the acquire line mentioning the resource name -- an
    # unrelated diagnostic sharing that line and resource must NOT be
    # legalized away by AR2's own real Borrow-removal witness. Only an
    # EXACT (code, level) match, per `_BEFORE_REMOVED_ANCHOR`, explains a
    # removal now.
    ar2_before_same_line_unrelated = {"exit": 1,
        "findings": [{"line": 14, "code": "OWN002", "level": "warning",
                     "message": "an unrelated finding mentioning 's' at the same acquire line"}],
        "call_site_witnesses": []}
    v_ar2_same_line_wrong_code = _verify_call_site_witness(
        ar2_after["call_site_witnesses"][0], ar2_before_same_line_unrelated, ar2_after,
        _witness_file("case.cs"))
    _vfail(failures, "hostile-ar2-same-line-unrelated-code-stays-unexplained",
          v_ar2_same_line_wrong_code is None, v_ar2_same_line_wrong_code)

    # R2.2/F1 (R1-review of b31e7a0): OWN003, same line, but naming a
    # DIFFERENT resource -- must also stay unexplained. AR2's own real
    # resource_name is the single letter "s": a plain substring check
    # (`"s" in message`) would match this message anyway ("disposed",
    # "resource", "disposable" all contain the bare letter), which is
    # exactly the defect the quoted-identifier-token correlation
    # (`_quoted_identifier`) fixes -- `"'s'"` is NOT a substring of a message
    # naming `'other'`, so this now uses AR2's REAL witness/resource_name
    # directly, no synthetic multi-character stand-in needed.
    ar2_before_wrong_resource = {"exit": 1,
        "findings": [{"line": 14, "code": "OWN003", "level": _RUN_ONE_SEVERITY,
                     "message": "IDisposable local 'other' is disposed more than once "
                               "[resource: disposable]"}],
        "call_site_witnesses": []}
    v_ar2_wrong_resource = _verify_call_site_witness(
        ar2_after["call_site_witnesses"][0], ar2_before_wrong_resource, ar2_after,
        _witness_file("case.cs"))
    _vfail(failures, "hostile-ar2-own003-wrong-resource-stays-unexplained",
          v_ar2_wrong_resource is None, v_ar2_wrong_resource)

    # hostile (AR-shaped): extra unrelated movement alongside a valid
    # classified one -- compare()'s own set arithmetic (simulated directly,
    # the same pattern hostile-e2/e3 above already use) must still call the
    # OTHER key unexplained even though AR1's own key IS explained.
    ar1_after_plus_unrelated: dict[str, Any] = {
        "exit": 1,
        "findings": [*ar1_after["findings"],
                    {"line": 50, "code": "OWN002", "level": "warning",
                     "message": "an unrelated finding elsewhere in the same file"}],
        "call_site_witnesses": ar1_after["call_site_witnesses"],
    }
    added_ar1_plus = {(14, "OWN001", _RUN_ONE_SEVERITY), (50, "OWN002", "warning")}
    verified_ar1_plus = [
        r for w in ar1_after_plus_unrelated["call_site_witnesses"]
        if (r := _verify_call_site_witness(
            w, ar1_before, ar1_after_plus_unrelated, _witness_file("case.cs")))
    ]
    explained_ar1_plus = ({r["after_key"] for r in verified_ar1_plus if r["after_key"]}
                          & added_ar1_plus)
    unexplained_ar1_plus = added_ar1_plus - explained_ar1_plus
    _vfail(failures, "hostile-ar-extra-unrelated-movement-stays-unexplained-overall",
          explained_ar1_plus == {(14, "OWN001", _RUN_ONE_SEVERITY)}
          and unexplained_ar1_plus == {(50, "OWN002", "warning")}, unexplained_ar1_plus)

    if failures:
        print(f"RESULT: {len(failures)} check(s) failed")
        return 1
    print("RESULT: p037-verdict-snapshot selftest: all checks pass")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="record a snapshot")
    t.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    t.add_argument("--engine", required=True, choices=("rust", "python"))
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--corpus", action="append", default=None, metavar="DIR")
    t.add_argument("--population-commit", default="HEAD",
                   help="the commit whose blobs are analysed (default HEAD; the after "
                        "side of a pair names the baseline's commit)")
    c = sub.add_parser("compare", help="diff two snapshots")
    c.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--level", default="verdict", choices=("verdict", "all"),
                   help="verdict = error/warning only (default); all = advisories too")
    c.add_argument("--against", default="HEAD",
                   help="the commit the after side must be fresh at (default HEAD)")
    v = sub.add_parser("verify", help="prove a snapshot is still fresh evidence at a commit")
    v.add_argument("--epoch", required=True, choices=tuple(EPOCH_MODULES))
    v.add_argument("snapshot", type=Path)
    v.add_argument("--against", default="HEAD")
    sub.add_parser("selftest", help="regression-test the amendment's own classification logic")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    global ev
    ev = EPOCH_MODULES[args.epoch]
    if args.cmd == "take":
        dirs = tuple(args.corpus) if args.corpus else ev.CORPUS_DIRS
        return take(args.engine, args.out, dirs, args.population_commit)
    if args.cmd == "verify":
        return verify(args.snapshot, args.against)
    return compare(args.before, args.after, args.level, args.against)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
