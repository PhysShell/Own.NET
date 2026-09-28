#!/usr/bin/env python3
"""P-037 Phase B0: the formal/production proof-boundary audit.

Contract: docs/notes/p037-phase-b-proof-boundary.md (pre-registered §§A-D).
Manifest: formal/p037-kernel/proof-boundary.json.

What is derived from source, never copied into the manifest as a number:

* the Kani harness inventory (every ``#[kani::proof]`` under the kernel);
* the fast / heavy CI partition (the harness loops of ``ci.yml`` job
  ``formal-p037`` and ``formal-p037-gate.yml`` job ``heavy-kani``);
* the assumptions a harness actually stands on (assumption-bearing generators
  and predicates in its body, mapped by ``DERIVED`` below);
* the production-seam negative controls: no production file may call a
  schedule-taking kernel API (#368), and no production file that imports the
  kernel may lower or collapse cells except through ``apply`` (F2).

Modes::

    --check      audit the tree; RESULT: PASS | FAIL (exit 0 | 1)
    --selftest   the cheap falsifiers F1-F4 and F6-F10 as in-memory mutants
    --mutants    F5 (and the #368 witness) as real `cargo test` runs on a
                 temporary copy of the kernel crate; needs cargo

Stdlib only. A new generic verification framework is out of budget by rule.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "formal" / "p037-kernel"
MANIFEST = KERNEL / "proof-boundary.json"
LIB = KERNEL / "src" / "lib.rs"
SCHEMA = "p037-proof-boundary/1"

# The two CI surfaces and the job whose harness loop each owns.
CI_SETS = {
    "fast": (ROOT / ".github" / "workflows" / "ci.yml", "formal-p037"),
    "heavy": (ROOT / ".github" / "workflows" / "formal-p037-gate.yml", "heavy-kani"),
}

CLASSES = {"PRODUCTION_GUARANTOR", "OUTSIDE_KANI_BOUNDARY"}
MECHANISMS = {"producer_invariant", "runtime_validation", "construction_by_api",
              "negative_control"}
# A mechanism that claims to hold in production must be pinned at the
# production seam, not only inside the formal crate.
NEEDS_PRODUCTION_CONTROL = {"producer_invariant", "negative_control"}
SEAMS = {"production", "kernel", "manifest"}
CONTROL_KINDS = {"kani_harness", "cargo_test", "census_shape", "p037_control",
                 "checker_rule", "test_script", "source_precedent"}
FAIRNESS_CONTRACTS = {"A_CONSTRUCTION", "B_VALIDATION", "C_BLOCKER"}
R_FORBIDDEN = {"no_effects", "borrow", "unconditional", "guard_irrelevant", "must",
               "id", "neg", "eligible_guard"}
REQUIRED_ASSUMPTIONS = {f"A{i}" for i in range(1, 13)}
# The negative controls B0 must map by name (the owner's list).
REQUIRED_CONTROLS = {
    "gv4-mutated-guard", "gv4-ref-alias-guard", "gv4-aliased-self-null",
    "legacy-honesty-unresolved-forward", "finalize-before-apply-witness",
    "unfair-schedule-witness-368", "record-absence-boundary",
}
VAGUE = re.compile(r"\b(assumed|obvious(ly)?|somehow|frontend handles|normally does|"
                   r"kernel correctness|well_formed somehow|roslyn knows)\b", re.I)

# Assumption-bearing tokens in a harness body -> the assumptions it stands on.
DERIVED: list[tuple[re.Pattern[str], set[str]]] = [
    (re.compile(r"\bany_(small_)?system\s*\("), {"WF", "A12"}),
    (re.compile(r"\bany_(small_)?election_system\s*\("), {"EWF", "A12"}),
    (re.compile(r"\bany_schedule\s*\("), {"A7"}),
    (re.compile(r"\bany_state_diagonal_where_uncond\s*\("), {"A3"}),
    (re.compile(r"\brelease_cells_have_no_edges\s*\("), {"A4"}),
    (re.compile(r"\bno_unknown_seed\s*\("), {"A10"}),
    (re.compile(r"\bPartialLocalRelease\b"), {"A4"}),
    (re.compile(r"kani::assume\([^;]*is_diag"), {"A3"}),
]

# Production-seam negative controls (N6 / N7), scanned over the production tree.
PRODUCTION_ROOTS = ("rust", "ownlang", "frontend")
PRODUCTION_SUFFIXES = {".rs", ".py", ".cs"}
SKIP_DIRS = {"target", "bin", "obj", "node_modules", "__pycache__", ".git"}
SCHEDULE_API = re.compile(r"\b(solve_with|elect_with|lfp_chaotic)\s*\(")
KERNEL_IMPORT = re.compile(r"\bp037_kernel\b")
DIRECT_LOWER = re.compile(r"\.collapse\s*\(\s*\)|\blower\s*\(")


@dataclass
class Tree:
    """Everything the audit reads, so the selftest can mutate it in memory."""

    manifest: dict[str, Any]
    source: dict[str, str]              # harness -> body text
    ci: dict[str, list[str]]            # "fast" / "heavy" -> harness names
    ci_runs_harness: dict[str, bool]    # the loop actually calls cargo kani
    lib: str
    production: dict[str, str]          # repo-relative path -> text
    root: Path = ROOT


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def err(self, msg: str) -> None:
        self.errors.append(msg)


# ---------------------------------------------------------------------------
# reading the tree
# ---------------------------------------------------------------------------

def _body_from(text: str, start: int) -> str:
    """The brace-balanced body of the item whose signature starts at `start`."""
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return text[start:]


def source_harnesses(src: Path = KERNEL / "src") -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(src.rglob("*.rs")):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"#\[kani::proof\]", text):
            fn = re.compile(r"\bfn\s+([a-z0-9_]+)\s*\(").search(text, m.end())
            if fn is None:
                continue
            name = fn.group(1)
            if name in out:
                out[name + "#dup"] = ""
            out[name] = _body_from(text, fn.start())
    return out


def ci_harnesses(path: Path, job: str) -> tuple[list[str], bool]:
    """The harness names in the `for h in ...; do` loop of `job`."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(job)}:\s*$", text, re.M)
    if m is None:
        return [], False
    rest = text[m.end():]
    nxt = re.search(r"^  \S", rest, re.M)
    block = rest[:nxt.start()] if nxt else rest
    loop = re.search(r"for\s+h\s+in(.*?);\s*do(.*?)done", block, re.S)
    if loop is None:
        return [], False
    names = re.findall(r"[a-z][a-z0-9_]+", loop.group(1).replace("\\", " "))
    runs = bool(re.search(r'cargo kani --harness "\$h"', loop.group(2)))
    return names, runs


def production_texts(root: Path = ROOT) -> dict[str, str]:
    out: dict[str, str] = {}
    for top in PRODUCTION_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in PRODUCTION_SUFFIXES:
                continue
            if SKIP_DIRS & set(f.relative_to(root).parts):
                continue
            try:
                out[f.relative_to(root).as_posix()] = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
    return out


def load_tree() -> Tree:
    ci: dict[str, list[str]] = {}
    runs: dict[str, bool] = {}
    for key, (path, job) in CI_SETS.items():
        ci[key], runs[key] = ci_harnesses(path, job)
    return Tree(
        manifest=json.loads(MANIFEST.read_text(encoding="utf-8")),
        source=source_harnesses(),
        ci=ci,
        ci_runs_harness=runs,
        lib=LIB.read_text(encoding="utf-8"),
        production=production_texts(),
    )


# ---------------------------------------------------------------------------
# the audit
# ---------------------------------------------------------------------------

def _texts(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in _texts(v)]
    if isinstance(obj, list):
        return [t for v in obj for t in _texts(v)]
    return []


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _exists(tree: Tree, rel: str, symbol: str | None) -> bool:
    p = tree.root / rel
    if not p.exists():
        return False
    if symbol is None:
        return True
    if p.is_dir():
        return (p / symbol).exists()
    return symbol in p.read_text(encoding="utf-8")


def audit(tree: Tree) -> Report:
    r = Report()
    m = tree.manifest
    if m.get("schema") != SCHEMA:
        r.err(f"manifest schema must be {SCHEMA!r}")

    # N1 — inventory and CI partition, all derived
    src = set(tree.source)
    dups = sorted(n for n in src if n.endswith("#dup"))
    for d in dups:
        r.err(f"N1 duplicate harness name in source: {d[:-4]}")
    src -= set(dups)
    fast, heavy = set(tree.ci.get("fast", [])), set(tree.ci.get("heavy", []))
    for key in ("fast", "heavy"):
        if not tree.ci_runs_harness.get(key):
            r.err(f"N1 the {key} CI loop does not run `cargo kani --harness \"$h\"`")
    missing = sorted(src - (fast | heavy))
    extra = sorted((fast | heavy) - src)
    overlap = sorted(fast & heavy)
    for n in missing:
        r.err(f"N1 missing: source harness {n} is in no CI set")
    for n in extra:
        r.err(f"N1 extra: CI names {n}, which is no #[kani::proof] in the kernel")
    for n in overlap:
        r.err(f"N1 overlap: {n} is in both fast and heavy")
    r.stats.update(source=len(src), fast=len(fast), heavy=len(heavy),
                   missing=len(missing), extra=len(extra), overlap=len(overlap))

    # N4 — the bounded adapter, checked against lib.rs
    b = m.get("bounded_adapter", {})
    for const in ("MAX_COORDS", "MAX_EDGES"):
        lm = re.search(rf"pub const {const}: usize = (\d+);", tree.lib)
        if lm is None or b.get("kani", {}).get(const) != int(lm.group(1)):
            r.err(f"N4 bounded_adapter.kani.{const} does not match lib.rs")
    if b.get("production") != "dynamic":
        r.err("N4 bounded_adapter.production must be 'dynamic'")
    if b.get("kani_proves_production_bound") is not False:
        r.err("N4 kani_proves_production_bound must be false")

    assumptions = {a.get("id"): a for a in m.get("assumptions", [])}
    controls = {c.get("id"): c for c in m.get("controls", [])}

    # controls first: they are what everything else points at
    for cid, c in controls.items():
        if c.get("kind") not in CONTROL_KINDS:
            r.err(f"control {cid}: kind must be one of {sorted(CONTROL_KINDS)}")
        if c.get("seam") not in SEAMS:
            r.err(f"control {cid}: seam must be one of {sorted(SEAMS)}")
        path = c.get("path", "")
        if not _nonempty(path) or not _exists(tree, path, c.get("symbol")):
            r.err(f"F4 control {cid}: {path!r} / {c.get('symbol')!r} does not exist")
        if c.get("seam") == "production" and path.startswith("formal/"):
            r.err(f"control {cid}: a formal-crate witness is not a production-seam control")
        if not _nonempty(c.get("what")):
            r.err(f"control {cid}: says nothing about what it pins")
    for cid in sorted(REQUIRED_CONTROLS - set(controls)):
        r.err(f"required negative control not mapped: {cid}")

    # N2 — every harness has a human claim, a concrete subject, its assumptions
    hs = {h.get("name"): h for h in m.get("harnesses", [])}
    if set(hs) != src:
        for n in sorted(src - set(hs)):
            r.err(f"N2 harness {n} has no manifest entry")
        for n in sorted(set(hs) - src):
            r.err(f"N2 manifest names {n}, which is no harness")
    for name, h in sorted(hs.items()):
        if name not in src:
            continue
        want_ci = "fast" if name in fast else "heavy" if name in heavy else None
        if h.get("ci") != want_ci:
            r.err(f"N2 {name}: ci is {h.get('ci')!r}, the workflows say {want_ci!r}")
        if not _nonempty(h.get("claim")) or VAGUE.search(h.get("claim", "")):
            r.err(f"N2 {name}: missing or vague claim")
        subj = h.get("subject") or []
        if not subj:
            r.err(f"N2 {name}: no production subject")
        for s in subj:
            fn = s.split("::")[-1]
            if not re.search(rf"\bfn {re.escape(fn)}\b", tree.lib):
                r.err(f"N2 {name}: subject {s} is no kernel function")
        declared = set(h.get("assumptions") or [])
        for a in sorted(declared - set(assumptions)):
            r.err(f"N2 {name}: assumption {a} is not in the manifest")
        body = tree.source.get(name, "")
        needed: set[str] = set()
        for pat, ids in DERIVED:
            if pat.search(body):
                needed |= ids
        for a in sorted(needed - declared):
            r.err(f"F10 {name}: stands on {a} (derived from its body) but does not declare it")

    # N3 / N5 — every assumption classified, every guarantor concrete
    for aid in sorted(REQUIRED_ASSUMPTIONS - set(assumptions)):
        r.err(f"N3 required assumption {aid} is not in the manifest")
    unclassified = 0
    for aid, a in sorted(assumptions.items()):
        cls = a.get("class")
        for t in _texts(a):
            if (vm := VAGUE.search(t)) is not None:
                r.err(f"N3 {aid}: vague wording: {vm.group(0)!r}")
                break
        if not _nonempty(a.get("statement")):
            r.err(f"N3 {aid}: no statement")
        if cls not in CLASSES:
            unclassified += 1
            r.err(f"F3 {aid}: class must be exactly one of {sorted(CLASSES)}")
            continue
        refs = a.get("controls") if cls == "PRODUCTION_GUARANTOR" else a.get("controlled_by")
        if not refs:
            r.err(f"N3 {aid}: names no control")
        for cid in refs or []:
            if cid not in controls:
                r.err(f"N3 {aid}: control {cid} is not in the manifest")
        if cls == "PRODUCTION_GUARANTOR":
            g = a.get("guarantor") or {}
            if g.get("mechanism") not in MECHANISMS:
                r.err(f"N3 {aid}: guarantor.mechanism must be one of {sorted(MECHANISMS)}")
            for k in ("what", "consumer", "on_violation"):
                if not _nonempty(g.get(k)):
                    r.err(f"N3 {aid}: guarantor.{k} is missing")
            where = g.get("where") or {}
            if not _nonempty(where.get("path")) or not _exists(
                    tree, where.get("path", ""), where.get("symbol")):
                r.err(f"F4 {aid}: guarantor.where {where} does not exist")
            if g.get("mechanism") in NEEDS_PRODUCTION_CONTROL and not any(
                    controls.get(c, {}).get("seam") == "production" for c in refs or []):
                r.err(f"N3 {aid}: a {g.get('mechanism')} needs a production-seam control")
        else:
            for k in ("not_proved", "why_outside"):
                if not _nonempty(a.get(k)):
                    r.err(f"N3 {aid}: {k} is missing")
        if a.get("blocker"):
            r.blockers.append(f"{aid}: {a['blocker']}")
    r.stats["unclassified"] = unclassified

    # N6 — the application order, as a manifest pin (F5 proper is --mutants)
    order = assumptions.get("A8", {}).get("order") or []
    try:
        if not (order.index("solve") < order.index("fin")
                < order.index("select_or_collapse") < order.index("lower")):
            r.err("N6 A8.order must put fin before select/collapse and lower")
    except ValueError:
        r.err("N6 A8.order must name solve, fin, select_or_collapse, lower")

    # N7 — fairness is a contract, never the caller's job
    a7 = assumptions.get("A7", {})
    if a7.get("fairness_contract") not in FAIRNESS_CONTRACTS:
        r.err(f"N7 A7.fairness_contract must be one of {sorted(FAIRNESS_CONTRACTS)}")
    r.stats["fairness"] = a7.get("fairness_contract")

    # N8 — R stays fail-closed
    a11 = assumptions.get("A11", {})
    if a11.get("interpretation") != "NO_GUARDED_EVIDENCE":
        r.err("N8 A11.interpretation must be NO_GUARDED_EVIDENCE")
    if not R_FORBIDDEN <= set(a11.get("forbidden_interpretations") or []):
        r.err(f"N8 A11.forbidden_interpretations must include {sorted(R_FORBIDDEN)}")
    if "record-absence-boundary" not in (a11.get("controlled_by") or []):
        r.err("N8 A11 must be controlled by record-absence-boundary")

    # production-seam negative controls (F8 / F9)
    # Scoped to files that name the kernel crate: `own-analysis` has its own,
    # unrelated `solve_with` (a worklist dataflow solver over a `Schedule`
    # enum), which the first run of this audit flagged by name alone.
    for rel, text in sorted(tree.production.items()):
        if not KERNEL_IMPORT.search(text):
            continue
        for mm in SCHEDULE_API.finditer(text):
            r.err(f"F8 {rel}: production calls the schedule-taking {mm.group(1)} (#368)")
        if DIRECT_LOWER.search(text):
            r.err(f"F9 {rel}: imports the kernel and lowers/collapses cells outside `apply`")
    return r


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def print_report(r: Report, tree: Tree) -> int:
    s = r.stats
    print(f"HARNESS INVENTORY: {s.get('source')} source / {s.get('fast')} fast + "
          f"{s.get('heavy')} heavy / {s.get('missing')} missing / {s.get('extra')} extra / "
          f"{s.get('overlap')} overlap")
    print(f"UNCLASSIFIED ASSUMPTIONS: {s.get('unclassified')}")
    print(f"#368: {s.get('fairness')}")
    obligations = [a["id"] for a in tree.manifest.get("assumptions", [])
                   if a.get("b1_obligation")]
    phase_c = [a["id"] for a in tree.manifest.get("assumptions", [])
               if a.get("phase_c_obligation")]
    print(f"B1 ENTRY OBLIGATIONS: {len(obligations)} ({', '.join(obligations)})")
    print(f"PHASE-C OBLIGATIONS: {len(phase_c)} ({', '.join(phase_c)})")
    for e in r.errors:
        print(f"  ERROR {e}")
    for b in r.blockers:
        print(f"  BLOCKER {b}")
    if r.errors or r.blockers:
        print("RESULT: FAIL — PHASE B BLOCKED")
        return 1
    print("RESULT: PASS — PROOF BOUNDARY CLOSED FOR PHASE B SHADOW")
    return 0


def _mutant(tree: Tree, fn: Any) -> Tree:
    t = copy.deepcopy(tree)
    fn(t)
    return t


def _assumption(t: Tree, aid: str) -> dict[str, Any]:
    for a in t.manifest["assumptions"]:
        if a["id"] == aid:
            return a  # type: ignore[no-any-return]
    raise KeyError(aid)


def selftest() -> int:
    base = load_tree()
    fails = 0

    def expect(label: str, tree: Tree, needle: str) -> None:
        nonlocal fails
        r = audit(tree)
        hit = any(needle in e for e in r.errors) or any(needle in b for b in r.blockers)
        print(f"{'ok ' if hit else 'MISS'} {label}")
        if not hit:
            fails += 1
            for e in r.errors:
                print(f"      {e}")

    r0 = audit(base)
    print(f"{'ok ' if not r0.errors else 'MISS'} baseline tree audits clean")
    fails += bool(r0.errors)
    a_fast = sorted(base.ci["fast"])[0]
    expect("F1a drop a real harness from the fast set",
           _mutant(base, lambda t: t.ci["fast"].remove(a_fast)), "N1 missing")
    expect("F1b a CI set names a fake harness",
           _mutant(base, lambda t: t.ci["heavy"].append("k99_fake_harness")), "N1 extra")
    expect("F1c the loop no longer runs cargo kani",
           _mutant(base, lambda t: t.ci_runs_harness.__setitem__("heavy", False)),
           "does not run")
    expect("F2  one harness in fast AND heavy",
           _mutant(base, lambda t: t.ci["heavy"].append(a_fast)), "N1 overlap")
    expect("F3a an assumption with no class",
           _mutant(base, lambda t: _assumption(t, "A4").pop("class")), "F3 A4")
    expect("F3b a vague guarantor",
           _mutant(base, lambda t: _assumption(t, "A1")["guarantor"].__setitem__(
               "what", "the frontend handles this")), "vague")
    expect("F4a a guarantor path that does not exist",
           _mutant(base, lambda t: _assumption(t, "A1")["guarantor"]["where"].__setitem__(
               "path", "frontend/roslyn/NoSuchFile.cs")), "F4 A1")
    expect("F4b a control symbol that does not exist",
           _mutant(base, lambda t: t.manifest["controls"][0].__setitem__(
               "symbol", "no_such_symbol_anywhere_xyz")), "F4 control")
    expect("F6  R absence read as a borrow",
           _mutant(base, lambda t: _assumption(t, "A11").__setitem__(
               "interpretation", "borrow")), "N8")
    expect("F7  fairness left to the caller",
           _mutant(base, lambda t: _assumption(t, "A7").__setitem__(
               "fairness_contract", "caller passes a fair schedule")), "N7")
    expect("F8  production calls solve_with",
           _mutant(base, lambda t: t.production.__setitem__(
               "rust/crates/own-bridge/src/guarded.rs",
               "use p037_kernel::solve_with;\nfn f() { solve_with(&s, &[0]); }")), "F8")
    r_same_name = audit(_mutant(base, lambda t: t.production.__setitem__(
        "rust/crates/own-analysis/src/other.rs",
        "fn f() { solve_with(graph, analysis, Schedule::Rpo); }")))
    ok = not any("F8" in e for e in r_same_name.errors)
    print(f"{'ok ' if ok else 'MISS'} F8' an unrelated same-named solve_with stays green")
    fails += not ok
    expect("F9  production collapses raw cells outside apply",
           _mutant(base, lambda t: t.production.__setitem__(
               "rust/crates/own-bridge/src/guarded.rs",
               "use p037_kernel::{lower, Cells};\nfn f(c: Cells) { lower(c.collapse()); }")),
           "F9")
    well_formed_user = next(n for n, h in sorted(base.source.items())
                            if re.search(r"\bany_system\s*\(", h))
    expect(f"F10 {well_formed_user} stops declaring WF",
           _mutant(base, lambda t: next(h for h in t.manifest["harnesses"]
                                        if h["name"] == well_formed_user)
                   ["assumptions"].remove("WF")), "F10")
    expect("F-app A8.order with apply before fin",
           _mutant(base, lambda t: _assumption(t, "A8").__setitem__(
               "order", ["solve", "select_or_collapse", "lower", "fin"])), "N6")
    expect("F-bound a claimed production-size Kani bound",
           _mutant(base, lambda t: t.manifest["bounded_adapter"].__setitem__(
               "kani_proves_production_bound", True)), "N4")
    expect("F-seam a formal-crate witness relabelled as production",
           _mutant(base, lambda t: next(c for c in t.manifest["controls"]
                                        if c["id"] == "finalize-before-apply-witness")
                   .__setitem__("seam", "production")), "not a production-seam")
    expect("F-blocker a recorded blocker fails the gate",
           _mutant(base, lambda t: _assumption(t, "A15").__setitem__(
               "blocker", "synthetic")), "A15: synthetic")
    print(f"RESULT: {'all falsifiers fire' if not fails else f'{fails} falsifier(s) missed'}")
    return 1 if fails else 0


# F5: the kernel's application must finalize first. Each mutant removes one
# finalization from lib.rs in a temp copy; the named tests must then FAIL.
KERNEL_MUTANTS = [
    ("F5a apply stops finalizing", "let c = solved.fin();", "let c = solved;",
     "k7_"),
    ("F5b lower stops finalizing", "match t.fin() {", "match t {",
     "k7_"),
]


def mutants() -> int:
    cargo = shutil.which("cargo")
    if cargo is None:
        print("REFUSED: cargo is not on PATH; --mutants needs it")
        return 2
    fails = 0
    witness = subprocess.run([cargo, "test", "--release", "issue_368"], cwd=KERNEL,
                             capture_output=True, text=True, check=False)
    ok = witness.returncode == 0 and "1 passed" in witness.stdout
    print(f"{'ok ' if ok else 'MISS'} F7  the #368 witness holds on the real kernel")
    fails += not ok
    base_run = subprocess.run([cargo, "test", "--release", "k7"], cwd=KERNEL,
                              capture_output=True, text=True, check=False)
    ok = base_run.returncode == 0
    print(f"{'ok ' if ok else 'MISS'} F5  the finalize-before-apply controls pass unmutated")
    fails += not ok
    with tempfile.TemporaryDirectory(prefix="p037-b0-") as tmp:
        crate = Path(tmp) / "p037-kernel"
        shutil.copytree(KERNEL, crate, ignore=shutil.ignore_patterns("target"))
        lib = crate / "src" / "lib.rs"
        pristine = lib.read_text(encoding="utf-8")
        for label, old, new, test in KERNEL_MUTANTS:
            if pristine.count(old) != 1:
                print(f"MISS {label}: the mutation site {old!r} is not unique")
                fails += 1
                continue
            lib.write_text(pristine.replace(old, new), encoding="utf-8")
            run = subprocess.run(
                [cargo, "test", "--release", test],
                cwd=crate, capture_output=True, text=True, check=False)
            # killed = a matching test PANICKED; a compile error is not a kill
            out = run.stdout + run.stderr
            died = sorted(set(re.findall(r"^---- (\S+) stdout ----$", out, re.M)))
            red = run.returncode != 0 and "test result: FAILED" in out and any(
                d.split("::")[-1].startswith(test) for d in died)
            print(f"{'ok ' if red else 'MISS'} {label}: killed by {', '.join(died) or 'nothing'}")
            fails += not red
        lib.write_text(pristine, encoding="utf-8")
    print(f"RESULT: {'every kernel mutant is killed' if not fails else f'{fails} miss(es)'}")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--mutants", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.mutants:
        return mutants()
    tree = load_tree()
    return print_report(audit(tree), tree)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
