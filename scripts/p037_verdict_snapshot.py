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

Capture transport (schema `p037-verdict-snapshot/4`; chosen over the other
two candidates in `docs/evidence/p037-b-epoch.json`'s own amendment entry):
a real future producer attaches ONE optional SARIF `properties` key,
`p037_call_site_witness: {"version": 1, "witness": <CALL_SITE_WITNESS>}`, to
the one SARIF *result* whose location is the witness's own call site --
`run_one()`'s SARIF parsing (factored into `_parse_sarif_doc()`, directly
testable on a hand-built SARIF document, never only through the subprocess)
already reads this key on EVERY result, TODAY, validates it via
`clf.check_call_site_witness()`, and stores whatever verified list results as
`snap["files"][rel]["call_site_witnesses"]` -- a STANDARD field of every
snapshot from this schema on, `[]` where no producer populates it (every
snapshot today; the real B2.1b/c-R1 producer does not exist yet, see
p037_b_classifier.py's own docstring point 5). Fail-closed, pinned by
selftest(): absent key, wrong/missing `version`, or a witness failing
`check_call_site_witness()` all degrade to "no witness for this result",
never a crash and never a guessed witness. Preregistered, not implemented:
`rust/crates/own-bridge/src/verdict.rs`'s `Finding` (no call-site/callee/
guarded/lowered field today) and `src/render.rs`'s `Properties` (a closed,
4-field struct, no generic bag) are BOTH frozen files today -- populating
this key for real requires a SEPARATE, later boundary amendment authorizing
both as treatment-mutable, which this task does not perform or assume.

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
SCHEMA = "p037-verdict-snapshot/4"
VERDICT_LEVELS = ("error", "warning")
CALL_SITE_WITNESS_PROPERTY = "p037_call_site_witness"
CALL_SITE_WITNESS_VERSION = 1
# Epoch is explicit and required -- same precedent this module's own
# docstring already states for ENGINE, extended to epoch selection (P-037
# Phase B: never an implicit "current epoch", branch-name inference or a
# silently-read env var). main() rebinds the module-global `ev` to the
# selected module before calling take()/_measure()/compare()/verify()/
# run_one() below; their bodies read `ev.*` at call time and are otherwise
# UNCHANGED for either epoch.
EPOCH_MODULES: dict[str, Any] = {"a2d": ev, "b": p037_evidence_b}


def _extract_call_site_witness(res: dict[str, Any]) -> dict[str, Any] | None:
    """One SARIF result's own `properties.p037_call_site_witness`, if
    present and well-formed -- fail-closed (item D): absent, the wrong
    `version`, a non-object payload, or a witness `check_call_site_witness()`
    itself refuses all degrade to `None` (no witness for this result), never
    a crash and never a guessed witness. No production emitter populates
    this key yet (see this module's own docstring) -- every real SARIF
    result today lacks `properties` entirely, or lacks this key within it,
    so this function returns `None` for all of them, unconditionally."""
    props = res.get("properties")
    if not isinstance(props, dict):
        return None
    payload = props.get(CALL_SITE_WITNESS_PROPERTY)
    if not isinstance(payload, dict) or payload.get("version") != CALL_SITE_WITNESS_VERSION:
        return None
    witness = payload.get("witness")
    if not isinstance(witness, dict):
        return None
    try:
        clf.check_call_site_witness(witness)
    except clf.WitnessError:
        return None
    return witness


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
            witness = _extract_call_site_witness(res)
            if witness is not None:
                witnesses.append(witness)
    findings.sort(key=lambda f: (f["line"], f["code"], f["level"]))
    return findings, witnesses


def run_one(path: Path, engine: str, env: dict[str, str]) -> dict[str, Any]:
    """One file through the launcher; SARIF in, (exit, findings,
    call_site_witnesses) out."""
    cmd = [str(ROOT / "scripts" / "own-check.sh"), "--engine", engine,
           "--format", "sarif", "--severity", "warning", "--", str(path)]
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


_AFTER_ANCHOR_CODE: dict[str, tuple[str, str] | None] = {
    # lowered -> (code, sarif level) the AFTER snapshot must independently
    # show at the witness's own site.line for that lowering, or None if this
    # lowering has no fixed, derivable signature (own-cli's own, already-
    # frozen OWN051 message format is the only one this module knows how to
    # check without inventing a second reading of "consume"/"borrow").
    "plain": ("OWN051", "note"),
    "consume": None,
    "borrow": None,
}


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
) -> dict[str, Any] | None:
    """Independently verifies one call-site witness against the REAL
    before/after records for the SAME file -- never trusts a claimed
    correlation (see module docstring: observation binding, not permission
    naming). Returns `None` (explains nothing) unless ALL of: the witness is
    schema-valid; it classifies into a CLOSED class; the AFTER record
    carries the signature `lowered` derives (today only `plain` ->
    `OWN051`/`note`) at EXACTLY `witness.site.line`, with a message
    containing both `callee` and `resource_name`; and, if
    `resource_acquire_site` is given, the BEFORE record carries SOME
    finding at that exact line whose message contains `resource_name` (a
    given, uncorrelatable acquire site is a hard failure, not a skipped
    check -- item D's fail-closed rule). On success, returns the single
    derived `after_key` and the single derived `before_key` (or `None` if no
    acquire site was claimed) plus the classification -- never a witness-
    supplied key of any kind."""
    try:
        clf.check_call_site_witness(witness)
    except clf.WitnessError:
        return None
    classification = clf.classify_call_site(witness)
    if classification["class"] not in clf.CLOSED_CLASSES:
        return None
    anchor = _AFTER_ANCHOR_CODE.get(witness["lowered"])
    if anchor is None:
        return None
    code, sarif_level = anchor
    site = witness["site"]
    after_key = _finding_at(after_rec, site["line"], code, sarif_level,
                            (witness["callee"], witness["resource_name"]))
    if after_key is None:
        return None
    before_key = None
    acquire = witness.get("resource_acquire_site")
    if acquire is not None:
        before_key = _finding_containing_at_line(before_rec, acquire["line"],
                                                  (witness["resource_name"],))
        if before_key is None:
            return None  # a claimed acquire site that does not correlate is a hard failure
    return {"witness": witness, "classification": classification,
           "before_key": before_key, "after_key": after_key}


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
        verified = [v for w in (rb.get("call_site_witnesses") or [])
                   if isinstance(w, dict) and (v := _verify_call_site_witness(w, ra, rb))]
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

_U1_WITNESS: dict[str, Any] = {
    "kind": "call_site", "callee": "ShapeU1.Inner", "callee_param": 0,
    "site": {"file": "U1.cs", "line": 16, "column": 9},
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


def _sarif_doc(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"runs": [{"results": results}]}


def _sarif_result(line: int, code: str, level: str, message: str,
                  witness: dict[str, Any] | None = None,
                  witness_version: int = CALL_SITE_WITNESS_VERSION) -> dict[str, Any]:
    res: dict[str, Any] = {
        "ruleId": code, "level": level, "message": {"text": message},
        "locations": [{"physicalLocation": {"region": {"startLine": line}}}],
    }
    if witness is not None:
        res["properties"] = {
            CALL_SITE_WITNESS_PROPERTY: {"version": witness_version, "witness": witness},
        }
    return res


def _u1_before_rec() -> dict[str, Any]:
    findings, witnesses = _parse_sarif_doc(_sarif_doc(
        [_sarif_result(14, "OWN001", "warning", _U1_BEFORE_MESSAGE)]))
    return {"exit": 1, "findings": findings, "call_site_witnesses": witnesses}


def _u1_after_rec(**overrides: Any) -> dict[str, Any]:
    """The real, future-shaped AFTER capture: one SARIF result (the real
    OWN051) carrying the properties-bag witness, parsed through the REAL
    `_parse_sarif_doc()` -- never a hand-built `call_site_witnesses` list."""
    witness = {**_U1_WITNESS, **overrides.pop("witness_overrides", {})}
    extra_results = overrides.pop("extra_results", [])
    findings, witnesses = _parse_sarif_doc(_sarif_doc([
        _sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE, witness=witness,
                     **overrides),
        *extra_results,
    ]))
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

    v = _verify_call_site_witness(after["call_site_witnesses"][0], before, after)
    _vfail(failures, "e2e-classifies-a-real-captured-witness",
          v is not None and v["classification"]["class"] == clf.CONDITIONALITY_HONESTY, v)
    _vfail(failures, "e2e-derives-the-real-after-key",
          v is not None and v["after_key"] == (16, "OWN051", "note"), v)
    _vfail(failures, "e2e-derives-the-real-before-key",
          v is not None and v["before_key"] == (14, "OWN001", "warning"), v)

    # item D.1 -- absent witness: an AFTER record with no properties bag at
    # all carries no witnesses, exactly today's every real snapshot.
    plain_after = {"exit": 0, "findings": [{"line": 16, "code": "OWN051", "level": "note",
                                           "message": _U1_AFTER_MESSAGE}],
                  "call_site_witnesses": []}
    _vfail(failures, "absent-witness-list-is-empty",
          plain_after["call_site_witnesses"] == [])

    # item D.2 -- malformed witness (fails check_call_site_witness): parsed
    # out during _parse_sarif_doc itself, never reaches verification at all.
    malformed = _sarif_doc([_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE,
                                          witness={"not": "a real witness"})])
    _, malformed_witnesses = _parse_sarif_doc(malformed)
    _vfail(failures, "malformed-witness-never-parsed-out", malformed_witnesses == [])

    # item D.3 -- cannot be correlated uniquely: resource_acquire_site is
    # given but the BEFORE record has nothing at that line mentioning the
    # resource -- hard failure, not a skipped check.
    uncorrelated_before = {"exit": 0, "findings": [], "call_site_witnesses": []}
    v_uncorrelated = _verify_call_site_witness(
        after["call_site_witnesses"][0], uncorrelated_before, after)
    _vfail(failures, "uncorrelatable-acquire-site-fails-closed", v_uncorrelated is None,
          v_uncorrelated)

    # item D.4 -- unsupported producer/output version: version 2 (this
    # module only understands version 1) is treated as absent, not guessed.
    unsupported = _sarif_doc([_sarif_result(16, "OWN051", "note", _U1_AFTER_MESSAGE,
                                            witness=_U1_WITNESS, witness_version=2)])
    _, unsupported_witnesses = _parse_sarif_doc(unsupported)
    _vfail(failures, "unsupported-version-fails-closed", unsupported_witnesses == [])

    # an UNCLASSIFIED witness (uncond shape) explains nothing even though
    # the real AFTER message still matches -- classify_call_site() itself
    # is the gate, not merely finding a message match.
    uncond_after = _u1_after_rec(
        witness_overrides={"guarded": {"shape": "uncond", "finalized_cells": None,
                                      "collapsed": "may"}})
    v_uncond = _verify_call_site_witness(
        uncond_after["call_site_witnesses"][0], before, uncond_after)
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
               if (r := _verify_call_site_witness(w, before, after_plus_unrelated_line))]
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
                  if (r := _verify_call_site_witness(w, before, after_plus_same_line))]
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
    v_wrong_code = _verify_call_site_witness(_U1_WITNESS, before, after_wrong_code_at_site)
    _vfail(failures, "hostile-e4-witness-cannot-rename-what-is-actually-at-its-own-site",
          v_wrong_code is None, v_wrong_code)

    # item H: cross-file/cross-site substitution -- U1's own witness
    # verified against an unrelated file/resource's AFTER record (same
    # line/code, different callee/resource in the message) must fail.
    cross_file_after = {"exit": 0,
        "findings": [{"line": 16, "code": "OWN051", "level": "note",
                     "message": "cannot verify whether 'ShapeU2.Outer' takes ownership of 't' "
                               "(inferred contract: may); optimistically assuming it does"}],
        "call_site_witnesses": [_U1_WITNESS]}
    v_cross = _verify_call_site_witness(_U1_WITNESS, before, cross_file_after)
    _vfail(failures, "hostile-cross-file-substitution-fails-closed", v_cross is None, v_cross)

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
