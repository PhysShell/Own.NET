#!/usr/bin/env python3
"""P-037 Phase B (CH3-8): the mechanical production-diff gate on the
own-cli/src/ownir.rs seam.

A genuinely NEW governance surface, not an extension of
scripts/p037_b_production_diff_gate.py: that module's own `unit` is
`rust/crates/own-bridge/` and its `Policy` is built from
`docs/evidence/p037-b-epoch.json`'s `production_diff_gate.rust` section
specifically -- bolting a second crate's policy onto that one object would
either widen a pinned Rust-crate shape with an unrelated CLI-crate meaning
or force one section to describe two units, both worse than a sibling
module. This module IMPORTS `p037_door_diff_gate`'s generic, policy-driven
primitives (rust_items/compare_rust/Policy/memory_tree/snapshot/the git
plumbing/IDENTICAL/WITHIN_ALLOWLIST/VIOLATION) unchanged -- the exact same
reuse `p037_b_production_diff_gate.py` already established -- and supplies
a CLI-shaped Policy and record reader instead. Zero bytes of
p037_door_diff_gate.py or p037_b_production_diff_gate.py move for this
module to exist.

WHY this surface exists at all: CH3-8's selected run-level evidence
transport needs own-cli's `check()`/`display()` to call the new
evidence-aware own-bridge surface instead of the old one (see
docs/evidence/p037-b-epoch.json's own `ch3_8_run_level_supersession` and
this repo's PoC report) -- own-cli is NOT a2d's own instrument (Phase-B's
whole closure is a SEPARATE contract, scripts/p037_evidence_b.py, see that
module's own docstring), but it previously had NO carve-out at all inside
Phase B's `INSTRUMENT_PATHS` (the unqualified `"rust/"` entry there covers
it with no exception), so any edit was, until now, a treatment nobody could
make without moving the instrument out from under itself with no gate
policing what changed. This module is that gate; `p037_evidence_b.py`'s own
INSTRUMENT_CARVE_OUTS/TREATMENT_PATHS name exactly `rust/crates/own-cli/
src/ownir.rs` to match it (see that module's own docstring for why the
carve-out is the ONE FILE, not the whole crate).

Unit: rust/crates/own-cli/. Frozen files (byte-identical): Cargo.toml,
src/main.rs, src/faults.rs, src/pyrepr.rs, src/sarif.rs, src/text.rs, and
every top-level item in src/ownir.rs EXCEPT the two named below. Mutable by
item: src/ownir.rs (exactly `fn check`, `fn display` -- confirmed by running
this module's own rust_items() over the live file: 20 top-level items
total, the other 18 -- `struct Parsed`, `fn parse`, `fn run`, `fn refusal`,
`fn strict_door_refusal`, `mod tests`, every `use`/`const`, etc. -- stay
frozen at item granularity, same discipline as
p037_b_production_diff_gate.py's own lower.rs/verdict.rs/render.rs blocks).

`fn check` reads the incoming facts and (in the selected design) calls the
new evidence-aware own-bridge entry point exactly once; `fn display` (in
the selected design, per the PoC's own boundary-shrink pass) stays the OLD,
unchanged-signature compatibility wrapper `mod tests` already calls, over a
new `fn display_with_p037_evidence` that does the one real rendering
decision. Both of those NEW items -- `fn display_with_p037_evidence` and
whatever `fn check` itself needs to grow -- are `registered_new_items` for
the SAME treatment commit that introduces them, never pre-named here: this
module ships with `registered_new_items` empty, exactly the discipline
p037_b_production_diff_gate.py already established for B1 and CH3-8 restates
for lower.rs's `struct CallSiteWitnessFact` and friends. `tests/` is a
control (free to move, watched, never gates the verdict) -- both
`tests/faults.rs` and `tests/replay.rs`.

Verdicts: IDENTICAL, WITHIN_ALLOWLIST, VIOLATION, REFUSED (exit 2) -- same
four as p037_b_production_diff_gate.py and the a2d door gate. This module
must measure IDENTICAL against this amendment's own head: CH3-8 is a
zero-production-semantics commit, and moves zero bytes of
rust/crates/own-cli/.

Run:  python scripts/p037_b_cli_diff_gate.py check --reference <sha> [--head <sha>]
      python scripts/p037_b_cli_diff_gate.py selftest
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

SCHEMA = "p037-b-cli-diff-gate/1"
DEFAULT_RECORD = "docs/evidence/p037-b-epoch.json"
UNIT = "rust/crates/own-cli/"

FROZEN_FILES: tuple[str, ...] = (
    "Cargo.toml",
    "src/main.rs",
    "src/faults.rs",
    "src/pyrepr.rs",
    "src/sarif.rs",
    "src/text.rs",
)

# CH3-8: own-cli's own two mutable items -- `fn check` is the only call site
# of the (selected-design) evidence-aware own-bridge entry point, and `fn
# display` is the old, signature-unchanged compatibility wrapper the PoC's
# own boundary-shrink pass proved suffices to keep `mod tests` byte-for-byte
# untouched. Every other item in ownir.rs (`struct Parsed`, `fn parse`,
# `fn run`, `fn refusal`, `fn strict_door_refusal`, `fn usage_error`, `fn
# docstring_usage`, `fn json_wrapper`, `mod tests`, every `use`/`const`)
# stays frozen at item granularity -- confirmed disjoint below.
OWNIR_MUTABLE_ITEMS: tuple[str, ...] = (
    "fn check",
    "fn display",
)


def _cli_policy(cs: dict[str, Any]) -> Policy:
    """Build a Policy from docs/evidence/p037-b-epoch.json's own
    `production_diff_gate.cli` section (passed in directly) -- no python/spec
    unit, both left as inert empty values compare_rust never reads."""
    mutable_items = {str(k): tuple(v) for k, v in cs.get("mutable_items", {}).items()}
    registered_items = {str(k): tuple(v) for k, v in cs.get("registered_new_items", {}).items()}
    unknown = sorted(set(registered_items) - set(mutable_items))
    if unknown:
        raise Refused(f"cli.registered_new_items names files outside mutable_items: {unknown}")
    return Policy(
        python_unit="", python_mutable=(), python_helpers=(),
        rust_unit=str(cs["unit"]),
        rust_mutable_files=tuple(cs.get("mutable_files", ())),
        rust_mutable_items=mutable_items,
        rust_registered_items=registered_items,
        rust_frozen_files=tuple(cs.get("frozen_files", ())),
        rust_controls=tuple(cs.get("controls", ())),
        spec_unit="", spec_mutable_files=(),
        fact_diff="", digest="",
    )


def frozen_policy() -> dict[str, Any]:
    """The CH3-8 production_diff_gate.cli section this module ships with --
    the same object docs/evidence/p037-b-epoch.json's production_diff_gate.cli
    must equal, so the record and this module cannot silently drift apart."""
    return {
        "unit": UNIT,
        "mutable_files": [],
        "mutable_items": {
            "src/ownir.rs": list(OWNIR_MUTABLE_ITEMS),
        },
        "registered_new_items": {},
        "frozen_files": list(FROZEN_FILES),
        "controls": ["tests/"],
    }


# Everything EXCEPT registered_new_items: the boundary itself. Same split
# p037_b_production_diff_gate.py's own IMMUTABLE_POLICY_FIELDS enforces, and
# for the identical reason -- see that module's own policy_drift() docstring.
IMMUTABLE_POLICY_FIELDS: tuple[str, ...] = (
    "unit", "mutable_files", "mutable_items", "frozen_files", "controls",
)


def policy_drift(record_cli: dict[str, Any]) -> list[str]:
    """Refuses a record whose IMMUTABLE_POLICY_FIELDS disagree with this
    module's own frozen_policy() -- the same self-authorization hole
    p037_b_production_diff_gate.py's own policy_drift() closes, ported here
    because this is a second, independent gate module with its own
    hardcoded reference. This file (scripts/p037_b_cli_diff_gate.py) is
    itself one of Phase B's INSTRUMENT_PATHS, so a self-serving edit here
    would move these bytes too and surface as instrument drift under
    p037_evidence_b.provenance_problems()."""
    frozen = frozen_policy()
    problems = []
    for field in IMMUTABLE_POLICY_FIELDS:
        if record_cli.get(field) != frozen[field]:
            problems.append(
                f"production_diff_gate.cli.{field} differs from this module's own "
                f"frozen_policy(): record={record_cli.get(field)!r} frozen={frozen[field]!r}")
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


def gate_cli(ref_tree: dict[str, Any], head_tree: dict[str, Any], pol: Policy) -> UnitReport:
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
    if not isinstance(gate_section, dict) or not isinstance(gate_section.get("cli"), dict):
        raise Refused(f"{record_path}: no production_diff_gate.cli section")
    drift = policy_drift(gate_section["cli"])
    if drift:
        raise Refused("; ".join(drift))
    pol = _cli_policy(gate_section["cli"])
    ref_tree = snapshot(ref_sha, [pol.rust_unit], repo)
    head_tree = snapshot(head_sha, [pol.rust_unit], repo)
    unit = gate_cli(ref_tree, head_tree, pol)
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
    print(f"RESULT: p037-b-cli-diff-gate {rep['verdict']} "
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
        "rust_mutable_items": {"src/ownir.rs": tuple(OWNIR_MUTABLE_ITEMS)},
        "rust_registered_items": {},
        "rust_frozen_files": ("src/main.rs",),
        "rust_controls": ("tests/",),
        "spec_unit": "", "spec_mutable_files": (),
        "fact_diff": "", "digest": "",
    }
    base.update(overrides)
    return Policy(**base)


# A dedicated synthetic fixture shaped like the real file: two mutable
# functions (`check`/`display`) plus several frozen siblings (`parse`,
# `run`, `refusal`, `mod tests`) -- proving the widening is exactly those
# two and nothing more, the same discipline
# p037_b_production_diff_gate.py's own dump.rs/verdict.rs/render.rs blocks
# use.
_REF_OWNIR = (
    "struct Parsed {\n"
    "    format: String,\n"
    "}\n"
    "fn parse(args: &[String]) -> Result<Parsed, i32> {\n"
    "    Ok(Parsed { format: String::from(\"human\") })\n"
    "}\n"
    "fn refusal(path: &str, message: &str) -> String {\n"
    "    format!(\"{path}: error: {message}\\n\")\n"
    "}\n"
    "fn check(path: &str) -> i32 {\n"
    "    0\n"
    "}\n"
    "fn display(path: &str, format: &str) -> String {\n"
    "    format.to_owned()\n"
    "}\n"
    "fn run(args: &[String]) -> i32 {\n"
    "    check(\"f\")\n"
    "}\n"
    "#[cfg(test)]\n"
    "mod tests {\n"
    "    #[test]\n"
    "    fn t() {}\n"
    "}\n"
)


def selftest() -> int:
    """Adversarial self-tests over synthetic in-memory trees (never the real
    files), plus a sanity check that this module's frozen item list still
    parses cleanly against the LIVE ownir.rs -- so a future edit that
    silently renames `check`/`display` is caught here, not discovered only
    when the gate refuses a real commit."""
    ref = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR,
        "crate/src/main.rs": "fn main() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    pol = _mem_policy()

    rep = compare_rust(ref, ref, pol)
    _selfcheck("identical-head-is-identical", rep.verdict == IDENTICAL, rep.as_dict())

    # the two approved items move freely.
    for label, replacement in (
        ("check", ("fn check(path: &str) -> i32 {\n    0\n}\n",
                   "fn check(path: &str) -> i32 {\n    let _ = path;\n    0\n}\n")),
        ("display", ("fn display(path: &str, format: &str) -> String {\n"
                     "    format.to_owned()\n}\n",
                     "fn display(path: &str, format: &str) -> String {\n"
                     "    let _ = path;\n    format.to_owned()\n}\n")),
    ):
        head = memory_tree({
            "crate/src/ownir.rs": _REF_OWNIR.replace(*replacement),
            "crate/src/main.rs": "fn main() {}\n",
            "crate/tests/t.rs": "#[test]\nfn t() {}\n",
        })
        rep = compare_rust(ref, head, pol)
        _selfcheck(f"approved-{label}-edit-is-allowed", rep.verdict == WITHIN, rep.as_dict())

    # required hostile case: an unrelated fn in ownir.rs changed -> violation.
    head = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR.replace(
            "fn refusal(path: &str, message: &str) -> String {\n"
            "    format!(\"{path}: error: {message}\\n\")\n}\n",
            "fn refusal(path: &str, message: &str) -> String {\n"
            "    format!(\"{path}: ERROR: {message}\\n\")\n}\n"),
        "crate/src/main.rs": "fn main() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("unrelated-fn-in-ownir-changed-is-violation", rep.verdict == VIOLATION,
              rep.as_dict())

    # required hostile case: a test-module edit, not authorized, -> violation.
    head = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR.replace(
            "    fn t() {}\n", "    fn t2() {}\n"),
        "crate/src/main.rs": "fn main() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("unauthorized-test-module-edit-in-mutable-file-is-violation",
              rep.verdict == VIOLATION, rep.as_dict())

    # required hostile case: another own-cli source file changed -> violation
    # (it is frozen, not merely absent from mutable_items).
    head = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR,
        "crate/src/main.rs": "fn main() { println!(\"hi\"); }\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("other-own-cli-source-file-changed-is-violation", rep.verdict == VIOLATION,
              rep.as_dict())

    # required hostile case: a genuinely new, unregistered top-level item in
    # the mutable file -> violation; the SAME item, registered, is allowed.
    head_new_item = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR + "fn display_with_p037_evidence() -> i32 { 1 }\n",
        "crate/src/main.rs": "fn main() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(ref, head_new_item, pol)
    _selfcheck("new-unregistered-top-level-item-is-violation", rep.verdict == VIOLATION,
              rep.as_dict())
    reg_pol = _mem_policy(
        rust_registered_items={"src/ownir.rs": ("fn display_with_p037_evidence",)})
    rep = compare_rust(ref, head_new_item, reg_pol)
    _selfcheck("registered-treatment-time-new-item-is-allowed", rep.verdict == WITHIN,
              rep.as_dict())

    # required hostile case: Cargo.toml changed -> violation (frozen file).
    head = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR,
        "crate/src/main.rs": "fn main() {}\n",
        "crate/Cargo.toml": "[package]\nname = \"own-cli\"\nversion = \"0.2.0\"\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    cargo_pol = _mem_policy(rust_frozen_files=("src/main.rs", "Cargo.toml"))
    cargo_ref = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR,
        "crate/src/main.rs": "fn main() {}\n",
        "crate/Cargo.toml": "[package]\nname = \"own-cli\"\nversion = \"0.1.0\"\n",
        "crate/tests/t.rs": "#[test]\nfn t() {}\n",
    })
    rep = compare_rust(cargo_ref, head, cargo_pol)
    _selfcheck("cargo-toml-changed-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    # required: a control-file (tests/) edit never violates.
    head = memory_tree({
        "crate/src/ownir.rs": _REF_OWNIR,
        "crate/src/main.rs": "fn main() {}\n",
        "crate/tests/t.rs": "#[test]\nfn t2() {}\n",
    })
    rep = compare_rust(ref, head, pol)
    _selfcheck("control-file-change-does-not-violate",
              rep.verdict == IDENTICAL and bool(rep.controls_moved), rep.as_dict())

    # policy-drift hostile tests: the self-authorization hole
    # p037_b_production_diff_gate.py's own check() was fixed against, ported
    # here for this second, independent gate module.
    frozen = frozen_policy()

    tampered = copy.deepcopy(frozen)
    tampered["mutable_items"]["src/ownir.rs"] = [
        *tampered["mutable_items"]["src/ownir.rs"], "fn smuggled_in_the_same_commit"]
    _selfcheck("policy-drift-catches-added-mutable-item", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["mutable_files"] = ["src/ownir.rs"]
    _selfcheck("policy-drift-catches-whole-file-widening", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["unit"] = "rust/crates/own-bridge/"
    _selfcheck("policy-drift-catches-changed-unit", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["controls"] = []
    _selfcheck("policy-drift-catches-emptied-controls", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["registered_new_items"] = {"src/ownir.rs": ["fn brand_new_registered"]}
    _selfcheck("policy-drift-allows-registered-new-items-alone", not policy_drift(tampered),
              policy_drift(tampered))

    _selfcheck("policy-drift-clean-on-frozen-policy-itself", not policy_drift(frozen),
              policy_drift(frozen))

    ownir_src = (ROOT / "rust" / "crates" / "own-cli" / "src" / "ownir.rs").read_text(
        encoding="utf-8")
    ownir_items = {it.key for it in rust_items(ownir_src, "ownir.rs")}
    missing = set(OWNIR_MUTABLE_ITEMS) - ownir_items
    _selfcheck("ownir-mutable-items-exist-in-live-source", not missing, missing)

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-cli-diff-gate selftest: all checks pass")
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

    p = sub.add_parser("frozen-policy")
    p.set_defaults(func=_cmd_frozen_policy)

    p = sub.add_parser("selftest")
    p.set_defaults(func=lambda _args: selftest())

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
