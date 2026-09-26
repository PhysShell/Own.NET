#!/usr/bin/env python3
"""P-037 Phase B: the mechanical production-diff gate on the mos.rs/lower.rs seam.

Mirrors scripts/p037_door_diff_gate.py's design (P-037 A2.2-D) but is NOT that
gate reused with a different record: A2.2-D's `Policy`/`load_policy` require a
python door, a rust door and a spec unit all at once (own-ir's exact shape),
and Phase B has none of those -- it is Rust-only (docs/evidence/p037-b-epoch
.json's own `engine_scope_consequence`), touches a different crate
(rust/crates/own-bridge/, not rust/crates/own-ir/), and the a2d gate's own
non-registration fields are pinned by tests/test_p037_a2d_epoch.py against
T_D -- editing that module to fit a second, unrelated shape would either
loosen a pinned a2d field or bolt Phase-B vocabulary onto a closed epoch's
own instrument. This module IMPORTS p037_door_diff_gate's generic, policy-
driven primitives (rust_items/classify_chars/compare_rust/compare_items,
snapshot/Tree/Entry, the git plumbing, IDENTICAL/WITHIN_ALLOWLIST/VIOLATION)
unchanged -- compare_rust takes a Policy value and never reads a2d's own
module constants -- and supplies a Phase-B-shaped Policy and a Phase-B
record reader instead. Zero bytes of p037_door_diff_gate.py move for this.

The scope, corrected against source (not copied from the epoch record's
first-draft candidate_scope): `lower_fn_params` alone only computes a
parameter's OWN type-shape from its OWN function's MethodSummary; a CALL
SITE's argument is matched against the CALLEE's summary, and the may/unknown
optimistic-default (OWN051) decision made, in `unverified_transfer_calls` /
`kill_sites_for_unverified` and the advisory-minting block inside
`lower_full` -- none of which lower_fn_params touches or calls. A guard-
aware call-site selection cannot land without also touching those three.
The corrected scope is recorded in docs/evidence/p037-b-epoch.json's
`treatment.candidate_scope` and in formal-kernel.md's own B1 section, not
just here.

Unit: rust/crates/own-bridge/. Frozen files (byte-identical): Cargo.toml,
src/ast.rs, src/lib.rs, src/render.rs, src/verdict.rs. Mutable by item:
src/mos.rs (every item except the two purely graph-topological helpers
`fn call_graph` / `fn sccs`, which touch no Transfer/join semantics at
all), src/lower.rs (exactly `fn lower_fn_params`, `fn
unverified_transfer_calls`, `fn kill_sites_for_unverified`, `fn lower_full`;
lower.rs's other 69 top-level items stay frozen at item granularity) and
(B1-F2-F4) src/dump.rs (exactly `fn dump_summaries`; its three other items
-- `fn escape_py`, `fn emit`, `fn pad`, plus its `use` statements and inner
attribute -- stay frozen at item granularity, same discipline as
lower.rs's other 69).

B1-F2-F4 widens dump.rs from a frozen file to an item-level mutable file
because it was found holding a real blocker: `dump_summaries` calls legacy
`build_skeletons(raw_fns)` reading ONLY `functions[]`, while `OwnIr` (the
whole root it already receives) also carries `guarded_functions[]` -- the
orphan carrier A2.2-3P built precisely for methods with guarded facts but
no `functions[]` record (docs/notes/p037-formal-kernel.md §10.6.6: "Phase
B builds one guarded-method view from functions[].guarded_facts plus
guarded_functions[].guarded_facts"). A Phase-B production solver that ever
reads `guarded_functions[]` while its OWN summary-evidence dump does not
would silently measure a different universe than production computes --
forbidden by the same "the instrument must see what production sees" rule
this whole gate exists to enforce. Widening the file to item granularity
(not unfreezing it wholesale) keeps `dump_summaries` the only surface the
eventual fix may touch; `escape_py`/`emit`/`pad` are pure JSON-emission
helpers with no summary semantics of their own and have no reason to move.

tests/ is a control (free to move, watched, never gates the verdict).
registered_new_items is empty in B1 by design: B1 does not yet know what new
production items the first treatment will need, and a treatment registers
its own new items in the SAME commit that defines them, exactly as A2.2-D's
gate already requires of the door commit.

Verdicts: IDENTICAL, WITHIN_ALLOWLIST, VIOLATION, REFUSED (exit 2) -- same
four as the door gate. B1 itself must measure IDENTICAL against 5571ba4
(the closed Phase-B entry-gate head): B1 adds tooling, ledgers and a formal-
note section, and touches no byte of rust/crates/own-bridge/.

Run:  python scripts/p037_b_production_diff_gate.py check --reference <sha> [--head <sha>]
      python scripts/p037_b_production_diff_gate.py selftest
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Reused verbatim from the A2.2-D gate -- generic, Policy-driven, no a2d
# module constant read by any of these names. See module docstring.
from p037_door_diff_gate import (  # noqa: E402
    IDENTICAL,
    VIOLATION,
    WITHIN,
    WORKTREE,
    Policy,
    Refused,
    UnitReport,
    compare_rust,
    memory_tree,
    resolve,
    rust_items,
    snapshot,
)

SCHEMA = "p037-b-production-diff-gate/1"
DEFAULT_RECORD = "docs/evidence/p037-b-epoch.json"
UNIT = "rust/crates/own-bridge/"

FROZEN_FILES: tuple[str, ...] = (
    "Cargo.toml",
    "src/ast.rs",
    "src/lib.rs",
    "src/render.rs",
    "src/verdict.rs",
)

# Every top-level item in mos.rs today except the two pure graph-topology
# helpers, derived by running p037_door_diff_gate.rust_items() over the live
# file and dropping `fn call_graph`/`fn sccs` -- not hand-typed from memory.
MOS_MUTABLE_ITEMS: tuple[str, ...] = (
    "inner_attribute #![allow( clippy::expect_used, clippy::indexing_slicing, "
    "clippy::too_many_lines, clippy::redundant_pub_crate )]",
    "use std::collections::{BTreeMap, BTreeSet, HashMap}",
    "enum Transfer",
    "fn join",
    "impl Transfer",
    "enum PathAction",
    "enum ReturnSkeleton",
    "struct ParamSkeleton",
    "struct MethodSkeleton",
    "struct ParamSummary",
    "struct MethodSummary",
    "type Mos",
    "type ParamKey",
    "fn solve_with_log",
    "fn solve",
)

LOWER_MUTABLE_ITEMS: tuple[str, ...] = (
    "fn lower_fn_params",
    "fn unverified_transfer_calls",
    "fn kill_sites_for_unverified",
    "fn lower_full",
)

# B1-F2-F4: dump.rs's own single mutable item -- `dump_summaries` is the
# ONLY function in this file that reads `functions[]`/`guarded_functions[]`
# at all; `escape_py`/`emit`/`pad` are pure JSON-serialization helpers with
# no summary-construction semantics, and have no reason to be part of the
# eventual fix.
DUMP_MUTABLE_ITEMS: tuple[str, ...] = (
    "fn dump_summaries",
)


def _b_policy(rs: dict[str, Any]) -> Policy:
    """Build a Policy from docs/evidence/p037-b-epoch.json's own
    `production_diff_gate.rust` section (passed in directly) -- no python/spec
    unit, both left as inert empty values compare_rust never reads."""
    mutable_items = {str(k): tuple(v) for k, v in rs.get("mutable_items", {}).items()}
    registered_items = {str(k): tuple(v) for k, v in rs.get("registered_new_items", {}).items()}
    unknown = sorted(set(registered_items) - set(mutable_items))
    if unknown:
        raise Refused(f"rust.registered_new_items names files outside mutable_items: {unknown}")
    return Policy(
        python_unit="", python_mutable=(), python_helpers=(),
        rust_unit=str(rs["unit"]),
        rust_mutable_files=tuple(rs.get("mutable_files", ())),
        rust_mutable_items=mutable_items,
        rust_registered_items=registered_items,
        rust_frozen_files=tuple(rs.get("frozen_files", ())),
        rust_controls=tuple(rs.get("controls", ())),
        spec_unit="", spec_mutable_files=(),
        fact_diff="", digest="",
    )


def frozen_policy() -> dict[str, Any]:
    """The B1 production_diff_gate.rust section this module ships with --
    the same object docs/evidence/p037-b-epoch.json's production_diff_gate.rust
    must equal, so the record and this module cannot silently drift apart."""
    return {
        "unit": UNIT,
        "mutable_files": [],
        "mutable_items": {
            "src/mos.rs": list(MOS_MUTABLE_ITEMS),
            "src/lower.rs": list(LOWER_MUTABLE_ITEMS),
            "src/dump.rs": list(DUMP_MUTABLE_ITEMS),
        },
        "registered_new_items": {},
        "frozen_files": list(FROZEN_FILES),
        "controls": ["tests/"],
    }


# Everything EXCEPT registered_new_items: the boundary itself. A treatment
# commit registers its own new items (growing registered_new_items in the
# SAME commit that defines them, by design -- see the module docstring),
# but it may never widen unit/mutable_files/mutable_items/frozen_files/
# controls, because those are the boundary a registration is measured
# against. Named here, not left implicit, because check() enforces exactly
# this split below.
IMMUTABLE_POLICY_FIELDS: tuple[str, ...] = (
    "unit", "mutable_files", "mutable_items", "frozen_files", "controls",
)


def policy_drift(record_rust: dict[str, Any]) -> list[str]:
    """Refuses a record whose IMMUTABLE_POLICY_FIELDS disagree with this
    module's own frozen_policy() -- catches a real self-authorization hole:
    check() used to read its allowlist from `record_rust` at whatever HEAD
    it was checking, so a single commit could widen mutable_items AND make
    the newly-widened item's change in the same breath, and the gate would
    validate the change against the very permission that commit just wrote.
    frozen_policy() is this module's OWN hardcoded reference; this file
    (scripts/p037_b_production_diff_gate.py) is itself one of Phase B's
    INSTRUMENT_PATHS, so widening frozen_policy() to match a self-serving
    epoch-record edit would change these bytes too and surface as
    instrument drift under p037_evidence_b.provenance_problems() -- the
    check does not have to re-implement that detection, only refuse to
    treat an unpinned record as authoritative in the meantime."""
    frozen = frozen_policy()
    problems = []
    for field in IMMUTABLE_POLICY_FIELDS:
        if record_rust.get(field) != frozen[field]:
            problems.append(
                f"production_diff_gate.rust.{field} differs from this module's own "
                f"frozen_policy(): record={record_rust.get(field)!r} frozen={frozen[field]!r}")
    return problems


def load_record(rev: str, record_path: str, repo: Path = ROOT) -> dict[str, Any]:
    if rev == WORKTREE:
        text = (repo / record_path).read_text(encoding="utf-8")
    else:
        from p037_door_diff_gate import _show  # deliberately narrow, WORKTREE-only import
        text = _show(rev, record_path, repo).decode("utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise Refused(f"{record_path}: not an object")
    return doc


def gate_b(ref_tree: dict[str, Any], head_tree: dict[str, Any], pol: Policy) -> UnitReport:
    return compare_rust(ref_tree, head_tree, pol)


def check(reference: str, head: str, record_path: str = DEFAULT_RECORD,
          repo: Path = ROOT) -> dict[str, Any]:
    ref_sha = resolve(reference, repo)
    head_sha = resolve(head, repo)
    if ref_sha == WORKTREE:
        raise Refused("the reference must be a commit")
    doc = load_record(head_sha, record_path, repo)
    if doc.get("epoch") != "b":
        raise Refused(f"{record_path} at {head_sha[:12]} names epoch {doc.get('epoch')!r}, "
                      "not 'b'; this gate measures Phase B only")
    gate_section = doc.get("production_diff_gate")
    if not isinstance(gate_section, dict) or not isinstance(gate_section.get("rust"), dict):
        raise Refused(f"{record_path}: no production_diff_gate.rust section")
    drift = policy_drift(gate_section["rust"])
    if drift:
        raise Refused("; ".join(drift))
    pol = _b_policy(gate_section["rust"])
    ref_tree = snapshot(ref_sha, [pol.rust_unit], repo)
    head_tree = snapshot(head_sha, [pol.rust_unit], repo)
    unit = gate_b(ref_tree, head_tree, pol)
    return {
        "schema": SCHEMA,
        "reference": ref_sha,
        "head": head_sha,
        "record": f"{head_sha}:{record_path}",
        "verdict": unit.verdict,
        "unit": unit.as_dict(),
    }


def print_report(rep: dict[str, Any]) -> None:
    unit = rep["unit"]
    print(f"unit {unit['unit']}: {unit['verdict']}")
    for line in unit["allowed"]:
        print(f"  allowed: {line}")
    for line in unit["violations"]:
        print(f"  VIOLATION: {line}")
    for line in unit["controls_moved"]:
        print(f"  control moved: {line}")
    print(f"RESULT: p037-b-production-diff-gate {rep['verdict']} "
          f"reference={rep['reference'][:12]} head={rep['head'][:12]}")


# --------------------------------------------------------------------------- selftest

_failures = 0


def _selfcheck(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def _mem_policy(**overrides: Any) -> Policy:
    base: dict[str, Any] = {
        "python_unit": "", "python_mutable": (), "python_helpers": (),
        "rust_unit": "crate/",
        "rust_mutable_files": (),
        "rust_mutable_items": {"src/lib.rs": ("fn mutable_fn",)},
        "rust_registered_items": {},
        "rust_frozen_files": ("src/frozen.rs",),
        "rust_controls": ("tests/",),
        "spec_unit": "", "spec_mutable_files": (),
        "fact_diff": "", "digest": "",
    }
    base.update(overrides)
    return Policy(**base)


_REF_LIB = "fn mutable_fn() -> i32 { 1 }\nfn frozen_fn() -> i32 { 2 }\n"


def selftest() -> int:
    """Adversarial self-tests over synthetic in-memory trees (never the real
    files), plus two sanity checks that this module's frozen item lists still
    parse cleanly against the LIVE mos.rs/lower.rs -- so a future edit to
    either file that silently renames one of the named items is caught here,
    not discovered only when the gate refuses a real commit."""
    ref = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    pol = _mem_policy()

    rep = compare_rust(ref, ref, pol)
    _selfcheck("identical-head-is-identical", rep.verdict == IDENTICAL, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB.replace("mutable_fn() -> i32 { 1 }",
                                             "mutable_fn() -> i32 { 99 }"),
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("mutable-item-change-is-within-allowlist", rep.verdict == WITHIN, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB.replace("frozen_fn() -> i32 { 2 }",
                                             "frozen_fn() -> i32 { 3 }"),
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("unnamed-item-in-mutable-file-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() { /* changed */ }\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("frozen-file-change-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t2() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("control-file-change-does-not-violate",
              rep.verdict == IDENTICAL and bool(rep.controls_moved), rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
        "crate/src/new.rs": "pub fn new_thing() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("unregistered-new-production-file-is-violation", rep.verdict == VIOLATION,
              rep.as_dict())

    # registration is for a NEW ITEM inside an ALREADY-mutable file (not for a
    # whole new file appearing out of nowhere -- that needs rust_mutable_files,
    # which B1's own policy leaves empty by design; see module docstring).
    head_new_item = memory_tree({
        "crate/src/lib.rs": _REF_LIB + "fn brand_new() -> i32 { 7 }\n",
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head_new_item, pol)
    _selfcheck("unregistered-new-item-in-mutable-file-is-violation", rep.verdict == VIOLATION,
              rep.as_dict())
    reg_pol = _mem_policy(rust_registered_items={"src/lib.rs": ("fn brand_new",)})
    rep = compare_rust(ref, head_new_item, reg_pol)
    _selfcheck("registered-new-item-in-mutable-file-is-allowed", rep.verdict == WITHIN,
              rep.as_dict())

    # --- B1-F2-F4: dump.rs's own item-granularity hostile tests, on a
    # dedicated synthetic fixture shaped like the real file (one mutable
    # summary function plus frozen helpers), proving the widening is exactly
    # `fn dump_summaries` and nothing more. ---
    _REF_DUMP = (
        "pub(crate) fn dump_summaries(facts: &OwnIr) -> Result<String, BridgeError> {\n"
        "    Ok(String::new())\n"
        "}\n"
        "fn escape_py(s: &str, out: &mut String) {\n"
        "    out.push_str(s);\n"
        "}\n"
        "fn emit(v: &Value, indent: usize, out: &mut String) {\n"
        "    out.push_str(\"{}\");\n"
        "}\n"
        "fn pad(n: usize, out: &mut String) {\n"
        "    for _ in 0..n { out.push(' '); }\n"
        "}\n"
    )
    dump_ref = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/src/dump.rs": _REF_DUMP,
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    dump_pol = _mem_policy(rust_mutable_items={"src/lib.rs": ("fn mutable_fn",),
                                              "src/dump.rs": ("fn dump_summaries",)})

    rep = compare_rust(dump_ref, dump_ref, dump_pol)
    _selfcheck("dump-identical-is-identical", rep.verdict == IDENTICAL, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/src/dump.rs": _REF_DUMP.replace("Ok(String::new())", "Ok(\"{}\".to_owned())"),
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(dump_ref, head, dump_pol)
    _selfcheck("dump-summaries-movement-is-allowed", rep.verdict == WITHIN, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/src/dump.rs": _REF_DUMP.replace(
            "out.push_str(s);", "out.push_str(s); out.push(' ');"),
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(dump_ref, head, dump_pol)
    _selfcheck("dump-another-existing-fn-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/src/lib.rs": _REF_LIB,
        "crate/src/frozen.rs": "pub fn frozen() {}\n",
        "crate/src/dump.rs": _REF_DUMP + "fn new_helper() -> i32 { 1 }\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(dump_ref, head, dump_pol)
    _selfcheck("dump-new-unregistered-helper-is-violation", rep.verdict == VIOLATION, rep.as_dict())
    dump_reg_pol = _mem_policy(
        rust_mutable_items={"src/lib.rs": ("fn mutable_fn",),
                            "src/dump.rs": ("fn dump_summaries",)},
        rust_registered_items={"src/dump.rs": ("fn new_helper",)})
    rep = compare_rust(dump_ref, head, dump_reg_pol)
    _selfcheck("dump-registered-new-helper-is-allowed", rep.verdict == WITHIN, rep.as_dict())

    # whole-file / policy widening: a head trying to also move `emit` without
    # ever registering it (already covered above), AND a policy that widens
    # dump.rs to file-level mutability instead of item-level must be refused
    # by policy_drift(), not silently accepted -- the real hostile case for
    # "the whole file becomes mutable" is exactly this module's own
    # frozen_policy() disagreeing with a record that tried it.
    tampered = copy.deepcopy(frozen_policy())
    tampered["mutable_files"] = ["src/dump.rs"]
    _selfcheck("dump-whole-file-widening-is-policy-drift", bool(policy_drift(tampered)),
              policy_drift(tampered))

    # --- policy-drift hostile tests: the self-authorization hole check()
    # used to have, where the allowlist was read from the very commit it
    # was checking, so a treatment could widen mutable_items and use the
    # widened permission in the same breath. Every IMMUTABLE_POLICY_FIELDS
    # entry must refuse a lone change; only registered_new_items may move
    # alone. ---
    frozen = frozen_policy()

    tampered = copy.deepcopy(frozen)
    tampered["mutable_items"]["src/mos.rs"] = [*tampered["mutable_items"]["src/mos.rs"],
                                               "fn smuggled_in_the_same_commit"]
    _selfcheck("policy-drift-catches-added-mutable-item", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["frozen_files"] = tampered["frozen_files"][:-1]
    _selfcheck("policy-drift-catches-removed-frozen-file", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["unit"] = "rust/crates/own-ir/"
    _selfcheck("policy-drift-catches-changed-unit", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["controls"] = []
    _selfcheck("policy-drift-catches-emptied-controls", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["registered_new_items"] = {"src/mos.rs": ["fn brand_new_registered"]}
    _selfcheck("policy-drift-allows-registered-new-items-alone", not policy_drift(tampered),
              policy_drift(tampered))

    _selfcheck("policy-drift-clean-on-frozen-policy-itself", not policy_drift(frozen),
              policy_drift(frozen))

    mos_src = (ROOT / "rust" / "crates" / "own-bridge" / "src" / "mos.rs").read_text(
        encoding="utf-8")
    mos_items = {it.key for it in rust_items(mos_src, "mos.rs")}
    expected_mos = set(MOS_MUTABLE_ITEMS) | {"fn call_graph", "fn sccs"}
    _selfcheck("mos-item-list-matches-live-source", mos_items == expected_mos,
              f"live-only={sorted(mos_items - expected_mos)} "
              f"expected-only={sorted(expected_mos - mos_items)}")

    lower_src = (ROOT / "rust" / "crates" / "own-bridge" / "src" / "lower.rs").read_text(
        encoding="utf-8")
    lower_items = {it.key for it in rust_items(lower_src, "lower.rs")}
    missing = set(LOWER_MUTABLE_ITEMS) - lower_items
    _selfcheck("lower-mutable-items-exist-in-live-source", not missing, missing)

    dump_src = (ROOT / "rust" / "crates" / "own-bridge" / "src" / "dump.rs").read_text(
        encoding="utf-8")
    dump_items = {it.key for it in rust_items(dump_src, "dump.rs")}
    expected_dump_frozen = {"fn escape_py", "fn emit", "fn pad"}
    missing_dump_mutable = set(DUMP_MUTABLE_ITEMS) - dump_items
    _selfcheck("dump-mutable-item-exists-in-live-source", not missing_dump_mutable,
              missing_dump_mutable)
    _selfcheck("dump-frozen-helpers-still-present-in-live-source",
              expected_dump_frozen <= dump_items,
              expected_dump_frozen - dump_items)
    _selfcheck("dump-mutable-and-frozen-items-are-disjoint",
              not (set(DUMP_MUTABLE_ITEMS) & expected_dump_frozen),
              (DUMP_MUTABLE_ITEMS, expected_dump_frozen))

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-production-diff-gate selftest: all checks pass")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        rep = check(args.reference, args.head, args.record)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print_report(rep)
    if args.require == "identical":
        return 0 if rep["verdict"] == IDENTICAL else 1
    return 0 if rep["verdict"] in (IDENTICAL, WITHIN) else 1


def _cmd_frozen_policy(_: argparse.Namespace) -> int:
    print(json.dumps(frozen_policy(), indent=2, sort_keys=True))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check")
    p.add_argument("--reference", required=True)
    p.add_argument("--head", default="HEAD")
    p.add_argument("--record", default=DEFAULT_RECORD)
    p.add_argument("--require", choices=("identical", "allowlist"), default="identical")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("frozen-policy",
                       help="print the production_diff_gate.rust object this module ships with")
    p.set_defaults(func=_cmd_frozen_policy)

    p = sub.add_parser("selftest")
    p.set_defaults(func=lambda _a: selftest())

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
