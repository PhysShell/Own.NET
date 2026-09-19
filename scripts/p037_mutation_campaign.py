#!/usr/bin/env python3
"""P-037 A2.2-5: the mutation campaign against the completeness oracle.

A2.2-4 built an independent completeness oracle (frontend/roslyn/OwnSharp.Oracle,
scripts/p037_completeness_oracle.py) and A2.2-4R repaired what it found. A2.2-5
asks the one question left about the control itself: can it still catch those
defects, and does it read the MEANING of a call site rather than its spelling?

The rule, before anything else: a mutant is KILLED only when it stays valid C#,
the extractor runs to completion, and the oracle (or the frozen-vocabulary
infrastructure) raises exactly the preregistered RED / mismatch. A compile
failure, an extractor crash, an oracle crash or an unrelated check failing is a
FORBIDDEN kill reason: it fails the campaign and never counts as a catch. (Any
analyzer looks excellent against a deleted semicolon; that is mutation
vandalism, not mutation testing.)

Three surfaces, one manifest (corpus/p037-mutation/manifest.json, written by
`generate` from the definitions below, never by hand):

  source     four frozen rewrites of a base program, each with a contract on
             what the facts and the oracle must do (`expected: green`):
             M1 REMOVE_HANDLE       Sink(r) -> Sink(Stream.Null); r.Dispose()
                                    the record stays in its carrier, the call
                                    fact disappears, no stale var(r) anywhere
             M2 ADD_PARENTHESES     Sink(r) -> Sink((((r))))
                                    same symbol, ordinal, representation,
                                    callee / sig / call_kind; only the source
                                    coordinate may move
             M3 PERTURB_BINDING     Take(first: r, second: q) ->
                                    Take(second: r, first: q), and the
                                    expanded-params twin TakeP(r, q) ->
                                    TakeP(q, r): the ordinals swap by DECLARED
                                    parameter, never by source position
             M4 DISTINGUISH_NESTED  Use(r) -> Use(Wrap(r))
                                    inner captured, outer nested_call_result,
                                    the outer site gets no var(r)
  producer   five compile-valid reversions of the A2.2-4R repairs, applied to a
             COPY of the extractor and built there, each to be killed by the
             witness its repair left behind, by the RED kind the findings ledger
             pinned before the repair (`expected: killed`):
             K-SHADOW     handle lookup by spelling again      fact_binds_other_symbol
             K-PARAMS     no ParamArray-element recovery       lost / false relevance
             K-COND-RECV  no MemberBinding receiver            occurrence_not_captured
             K-CTORINIT   no constructor_initializer fact      occurrence_not_captured
             K-MEMBER     guarded-only members: class/block    occurrence_not_captured
  taxonomy   `predicate_result` removed from the registry: the freeze test, the
             hostile-census test and the oracle driver must all go red as
             UNCLASSIFIED (the shape has no frozen name), never by folding the
             shape into a neighbouring name (`expected: unclassified`). A future
             `other_expression` bucket dies here.

Acceptance (`run`, the whole list or nothing): every declared mutant exercised
exactly once; every C# mutant compiles; every source metamorph stays GREEN under
its design and its obligations; every producer mutant is killed by exactly its
preregistered RED map; the taxonomy mutant reads unclassified; no survivor; no
unexpected kill reason; the production tree is byte-identical after the
campaign; the ordinary oracle reads RED 0 on every campaign input and the
findings ledger has no open finding. Nothing mutated is ever written into the
production tree: mutated sources, the extractor copy and every JSON live in a
temporary directory.

The result is corpus/p037-mutation/report.json, deterministic (no paths, no
times): `run --record` writes it, `run` re-runs the campaign and demands the
same report (the provenance block excepted), tests/test_p037_mutation_campaign.py
holds it to the manifest and to the production digest without dotnet.

Usage:
  p037_mutation_campaign.py generate            # (re)write manifest.json and sources/
  p037_mutation_campaign.py check               # drift + preconditions + report, no dotnet
  p037_mutation_campaign.py run [--record] [--keep DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import p037_completeness_oracle as oracle

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "corpus" / "p037-mutation"
MANIFEST = OUT / "manifest.json"
SOURCES = OUT / "sources"
REPORT = OUT / "report.json"
EXTRACTOR = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor"
ORACLE = ROOT / "frontend" / "roslyn" / "OwnSharp.Oracle"
PROGRAM = EXTRACTOR / "Program.cs"
REGISTRY = ROOT / "corpus" / "p037-relevance" / "registry.json"
PROBE = ROOT / "corpus" / "p037-relevance" / "probe" / "case.cs"
PROBE_EXPECTED = ROOT / "corpus" / "p037-relevance" / "probe" / "expected.json"
FINDINGS = ROOT / "corpus" / "p037-relevance" / "oracle_findings.json"
HOSTILE = ROOT / "corpus" / "p037-hostile"
SHAPES = ROOT / "corpus" / "p037-shapes"
TESTS = ROOT / "tests"
SCHEMA = "p037-mutation-campaign/1"
HEADER = ("// GENERATED by scripts/p037_mutation_campaign.py "
          "(P-037 A2.2-5 mutation campaign); do not edit.")
PRELUDE = ["using System;", "using System.IO;", ""]
FORBIDDEN = ["build_failure", "compile_error", "extractor_crash", "oracle_crash",
             "unrelated_check_failure"]
ONC = "occurrence_not_captured"
BASELINE_INPUTS = ["hostile", "probe", "shape:sidecar-ctorinit-base",
                   "shape:orphan-expression-bodied", "shape:orphan-struct-method"]

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


# ---- the definitions (the manifest is written from these) ----

def cap(symbol: str, kind: str = "invocation", ordinal: int = 0, expected: str = "var",
        **extra: Any) -> dict[str, Any]:
    return {"symbol": symbol, "verdict": "captured", "site_kind": kind, "ordinal": ordinal,
            "expected": expected, **extra}


def exc(symbol: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"symbol": symbol, "verdict": "excluded", "explanation": name, **extra}


def program(cls: str, why: str, members: list[str]) -> str:
    return "\n".join([HEADER, f"// {why}", *PRELUDE, f"static class {cls}", "{",
                      *[f"    {m}" for m in members], "}", ""])


SINK = "static void Sink(Stream s, bool leaveOpen) { }"
KEEP = exc("keep", "receiver_not_summary_parameter")
RECEIVER = "receiver_not_summary_parameter"


def var(name: str) -> dict[str, str]:
    return {"kind": "var", "name": name}


OPAQUE = {"kind": "opaque"}


def source_mutants() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(mid: str, operator: str, cls: str, why: str, members: list[str], member: str,
            find: str, replace: str, base: dict[str, Any], mutant: dict[str, Any],
            obligations: list[dict[str, Any]]) -> None:
        out.append({
            "id": mid, "surface": "source", "operator": operator,
            "source": f"sources/{mid}.cs", "member": member,
            "patch": {"find": find, "replace": replace},
            "must_compile": True, "expected": "green",
            "base_design": base, "mutant_design": mutant,
            "obligations": [{"kind": "design", "side": "base"},
                            {"kind": "design", "side": "mutant"}, *obligations],
            "forbidden_kill_reasons": FORBIDDEN,
            "_program": program(cls, why, members),
        })

    m = "static void M() { var r = new MemoryStream(); var keep = new MemoryStream(); "
    add("M1-remove-handle", "REMOVE_HANDLE", "Mut_M1_RemoveHandle",
        "M1 REMOVE_HANDLE base: a handle flows into Sink; the mutant passes Stream.Null "
        "instead and disposes the handle itself",
        [SINK, m + "Sink(r, true); keep.Dispose(); }"], "Mut_M1_RemoveHandle.M",
        "Sink(r, true); keep.Dispose();",
        "Sink(Stream.Null, true); r.Dispose(); keep.Dispose();",
        {"carrier": "functions", "occurrences": [cap("r"), KEEP]},
        {"carrier": "functions", "occurrences": [exc("r", RECEIVER), KEEP]},
        [{"kind": "carrier_unchanged"},
         {"kind": "fact", "side": "base", "callee": "Mut_M1_RemoveHandle.Sink",
          "args": {"0": var("r"), "1": {"kind": "bool_const", "value": True}}},
         {"kind": "no_fact", "side": "mutant", "callee": "Mut_M1_RemoveHandle.Sink"},
         {"kind": "no_handle_fact_for", "side": "mutant", "symbol": "r"}])
    add("M2-add-parentheses", "ADD_PARENTHESES", "Mut_M2_AddParentheses",
        "M2 ADD_PARENTHESES base: a bare handle argument; the mutant wraps it in four "
        "pairs of parentheses",
        [SINK, m + "Sink(r, true); keep.Dispose(); }"], "Mut_M2_AddParentheses.M",
        "Sink(r, true)", "Sink((((r))), true)",
        {"carrier": "functions", "occurrences": [cap("r"), KEEP]},
        {"carrier": "functions", "occurrences": [cap("r"), KEEP]},
        [{"kind": "carrier_unchanged"},
         {"kind": "fact_equal_modulo_site", "callee": "Mut_M2_AddParentheses.Sink"},
         {"kind": "occurrence_equal", "symbol": "r"}])
    mq = ("static void M() { var r = new MemoryStream(); var q = new MemoryStream(); "
          "var keep = new MemoryStream(); ")
    add("M3-perturb-binding-named", "PERTURB_BINDING", "Mut_M3_PerturbBindingNamed",
        "M3 PERTURB_BINDING base: two handles bound by name to two declared parameters; "
        "the mutant swaps the names, not the positions",
        ["static void Take(Stream first, Stream second) { }",
         mq + "Take(first: r, second: q); keep.Dispose(); }"],
        "Mut_M3_PerturbBindingNamed.M",
        "Take(first: r, second: q)", "Take(second: r, first: q)",
        {"carrier": "functions", "occurrences": [cap("r"), cap("q", ordinal=1), KEEP]},
        {"carrier": "functions", "occurrences": [cap("r", ordinal=1), cap("q"), KEEP]},
        [{"kind": "carrier_unchanged"},
         {"kind": "fact", "side": "base", "callee": "Mut_M3_PerturbBindingNamed.Take",
          "args": {"0": var("r"), "1": var("q")}},
         {"kind": "fact", "side": "mutant", "callee": "Mut_M3_PerturbBindingNamed.Take",
          "args": {"0": var("q"), "1": var("r")}}])
    add("M3-perturb-binding-params", "PERTURB_BINDING", "Mut_M3_PerturbBindingParams",
        "M3 PERTURB_BINDING, expanded-params twin: the first position is a declared "
        "parameter, the second an expanded params element; the mutant swaps the handles",
        ["static void TakeP(Stream first, params Stream[] rest) { }",
         mq + "TakeP(r, q); keep.Dispose(); }"],
        "Mut_M3_PerturbBindingParams.M",
        "TakeP(r, q)", "TakeP(q, r)",
        {"carrier": "functions",
         "occurrences": [cap("r"), cap("q", ordinal=1, expected="opaque"), KEEP]},
        {"carrier": "functions",
         "occurrences": [cap("q"), cap("r", ordinal=1, expected="opaque"), KEEP]},
        [{"kind": "carrier_unchanged"},
         {"kind": "fact", "side": "base", "callee": "Mut_M3_PerturbBindingParams.TakeP",
          "args": {"0": var("r"), "1": OPAQUE}},
         {"kind": "fact", "side": "mutant", "callee": "Mut_M3_PerturbBindingParams.TakeP",
          "args": {"0": var("q"), "1": OPAQUE}}])
    add("M4-distinguish-nested", "DISTINGUISH_NESTED", "Mut_M4_DistinguishNested",
        "M4 DISTINGUISH_NESTED base: a handle flows into Use directly; the mutant passes "
        "it through Wrap first",
        ["static Stream Wrap(Stream s) { return s; }", "static void Use(Stream s) { }",
         m + "Use(r); keep.Dispose(); }"],
        "Mut_M4_DistinguishNested.M",
        "Use(r);", "Use(Wrap(r));",
        {"carrier": "functions", "occurrences": [cap("r"), KEEP]},
        {"carrier": "functions",
         "occurrences": [cap("r", enclosing=["nested_call_result"]), KEEP]},
        [{"kind": "carrier_unchanged"},
         {"kind": "fact", "side": "base", "callee": "Mut_M4_DistinguishNested.Use",
          "args": {"0": var("r")}},
         {"kind": "fact", "side": "mutant", "callee": "Mut_M4_DistinguishNested.Wrap",
          "args": {"0": var("r")}},
         {"kind": "no_handle_fact_at", "side": "mutant",
          "callee": "Mut_M4_DistinguishNested.Use", "symbol": "r"}])
    return out


def producer_mutants() -> list[dict[str, Any]]:
    def mutant(mid: str, reverts: str, what: str, find: str, replace: str,
               inputs: list[str], expected_red: dict[str, Any],
               witnesses: list[str]) -> dict[str, Any]:
        return {"id": mid, "surface": "producer", "reverts": reverts, "what": what,
                "patch": {"file": "frontend/roslyn/OwnSharp.Extractor/Program.cs",
                          "find": find, "replace": replace, "occurrences": 1},
                "must_compile": True, "expected": "killed", "inputs": inputs,
                "expected_red": expected_red, "witnesses": witnesses,
                "forbidden_kill_reasons": FORBIDDEN}

    return [
        mutant("K-SHADOW", "A2.2-4R1 (F-SHADOW)",
               "the sidecar's local-reference lookup matches candidates by spelling again",
               "return handles.Contains(lr.Local)",
               "return handles.Any(h => h.Name == lr.Local.Name)",
               ["hostile", "probe"],
               {"hostile": {"shadow-sibling-scopes": {"fact_binds_other_symbol": 1},
                            "shadow-sibling-scopes-reversed": {"fact_binds_other_symbol": 1},
                            "shadow-lambda-local": {"fact_binds_other_symbol": 1}},
                "probe": {}},
               ["shadow-sibling-scopes", "shadow-sibling-scopes-reversed",
                "shadow-lambda-local"]),
        mutant("K-PARAMS", "A2.2-4R2 (F-PARAMS-ELEMENT)",
               "an expanded params element is classified from its bare syntax again "
               "(no ParamArray-element recovery)",
               "return element ?? model.GetOperation(expression);",
               "return model.GetOperation(expression);",
               ["hostile", "probe"],
               {"hostile": {"pw-ctor-boxing-params-orphan-local":
                            {"fact_without_relevant_occurrence": 1},
                            "pw-del-parens-params-record-local": {ONC: 1},
                            "pw-ext-user-implicit-params-record-param":
                            {"fact_without_relevant_occurrence": 1},
                            "pw-inv-bang-params-orphan-local": {ONC: 1}},
                "probe": {}},
               ["pw-ctor-boxing-params-orphan-local", "pw-del-parens-params-record-local",
                "pw-ext-user-implicit-params-record-param", "pw-inv-bang-params-orphan-local"]),
        mutant("K-COND-RECV", "A2.2-4R3 (F-CONDITIONAL-RECEIVER)",
               "the reduced receiver under `?.` (a MemberBinding) is dropped again",
               "MemberBindingExpressionSyntax =>\n                    "
               "inv.Ancestors().OfType<ConditionalAccessExpressionSyntax>()"
               ".FirstOrDefault()?.Expression,",
               "MemberBindingExpressionSyntax => null,",
               ["hostile", "probe"],
               {"hostile": {"ext-conditional-access": {ONC: 1}}, "probe": {}},
               ["ext-conditional-access"]),
        mutant("K-CTORINIT", "A2.2-4R5 (F-CTOR-INIT)",
               "no constructor_initializer fact is emitted (the initializer's nested calls "
               "are still walked)",
               "if (member is ConstructorDeclarationSyntax { Initializer: { } init })",
               "if (member is ConstructorDeclarationSyntax { Initializer: { } init } "
               "&& init.Kind() == SyntaxKind.None)",
               ["hostile", "probe", "shape:sidecar-ctorinit-base"],
               {"hostile": {"vocab-constructor-initializer": {ONC: 1},
                            "ctorinit-named-transparent": {ONC: 1}},
                "probe": {ONC: 1},
                "shape:sidecar-ctorinit-base": {ONC: 1}},
               ["vocab-constructor-initializer", "ctorinit-named-transparent"]),
        mutant("K-MEMBER", "A2.2-4R6 (F-MEMBER)",
               "the guarded-only member enumeration is restricted to class members with a "
               "block body again, the legacy loop's own domain, so nothing reaches the orphan "
               "carrier through it",
               "foreach (var (member, body) in GuardedOnlyMembers(root))",
               "foreach (var (member, body) in GuardedOnlyMembers(root)"
               ".Where(mb => mb.member.Parent is ClassDeclarationSyntax "
               "&& mb.member is BaseMethodDeclarationSyntax { Body: not null }))",
               ["hostile", "probe", "shape:orphan-expression-bodied",
                "shape:orphan-struct-method"],
               {"hostile": {"member-expression-bodied": {ONC: 1}, "member-struct": {ONC: 1},
                            "member-record": {ONC: 1}, "member-accessor": {ONC: 1},
                            "member-default-interface-method": {ONC: 1},
                            "member-record-struct": {ONC: 1}},
                "probe": {ONC: 1},
                "shape:orphan-expression-bodied": {ONC: 1},
                "shape:orphan-struct-method": {ONC: 1}},
               ["member-expression-bodied", "member-struct", "member-record",
                "member-accessor", "member-default-interface-method",
                "member-record-struct"]),
    ]


def taxonomy_mutants() -> list[dict[str, Any]]:
    return [{
        "id": "T-PREDICATE-RESULT", "surface": "taxonomy",
        "what": "predicate_result removed from the registry's exclusions; the shape "
                "`Use6(r != null)` keeps its occurrences and loses its name",
        "remove_exclusion": "predicate_result",
        "must_stay_well_formed": True, "expected": "unclassified",
        "baseline_probe_row": {"PredicateResult": "excluded:predicate_result"},
        "oracle_inputs": ["probe", "hostile"],
        "expected_failures": {
            "freeze_test": {"failing_checks": ["classification-valid", "registry-non-vacuous"],
                            "must_name": ["classification-valid"]},
            "hostile_test": {"failing_checks": ["designs-use-frozen-vocabulary"],
                             "must_name": ["designs-use-frozen-vocabulary"]},
            "oracle_driver": {"failing_checks": ["oracle-exclusions-frozen[hostile]",
                                                 "oracle-exclusions-frozen[probe]"],
                              "must_name": ["oracle-exclusions-frozen[hostile]",
                                            "oracle-exclusions-frozen[probe]"]}},
        "forbidden_kill_reasons": FORBIDDEN,
    }]


def generate_all() -> tuple[dict[str, str], dict[str, Any]]:
    sources: dict[str, str] = {}
    mutants: list[dict[str, Any]] = []
    for mut in source_mutants():
        sources[f"{mut['id']}.cs"] = mut.pop("_program")
        mutants.append(mut)
    mutants += producer_mutants()
    mutants += taxonomy_mutants()
    manifest = {
        "schema": SCHEMA,
        "generator": "scripts/p037_mutation_campaign.py",
        "rule": ("A mutant is killed only when it stays valid C#, the extractor runs to "
                 "completion and the oracle (or the frozen-vocabulary infrastructure) raises "
                 "exactly the preregistered RED / mismatch. A compile failure, an extractor "
                 "crash, an oracle crash or an unrelated check failing is a forbidden kill "
                 "reason: it fails the campaign and never counts as a catch."),
        "forbidden_kill_reasons": FORBIDDEN,
        "baseline_inputs": BASELINE_INPUTS,
        "mutants": mutants,
    }
    return sources, manifest


def write(sources: dict[str, str], manifest: dict[str, Any], root: Path) -> None:
    (root / "sources").mkdir(parents=True, exist_ok=True)
    for old in (root / "sources").glob("*.cs"):
        if old.name not in sources:
            old.unlink()
    for name, src in sources.items():
        (root / "sources" / name).write_text(src, encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n",
                                        encoding="utf-8")


# ---- digests and provenance ----

def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def production_files() -> list[Path]:
    files = [EXTRACTOR / "Program.cs", EXTRACTOR / "OwnSharp.Extractor.csproj",
             ORACLE / "Program.cs", ORACLE / "OwnSharp.Oracle.csproj",
             REGISTRY, PROBE, PROBE_EXPECTED, FINDINGS, HOSTILE / "expected.json",
             *sorted((HOSTILE / "cases").glob("*.cs")), *sorted(SHAPES.glob("*/case.cs")),
             TESTS / "test_p037_relevance_freeze.py", TESTS / "test_p037_hostile_census.py",
             ROOT / "scripts" / "p037_completeness_oracle.py",
             ROOT / "scripts" / "p037_hostile_census.py"]
    return files


def production_digest() -> str:
    h = hashlib.sha256()
    for f in production_files():
        h.update(str(f.relative_to(ROOT)).encode("utf-8") + b"\0")
        h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False, cwd=ROOT)
    return proc.stdout.strip() if proc.returncode == 0 else ""


# ---- report helpers ----

def red_kinds(report: dict[str, Any]) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(report.get("red_kinds", {}).items())}


def red_by_case(report: dict[str, Any], cases: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in report.get("red", []):
        member = str(r.get("member", ""))
        case = next((n for n, c in cases.items()
                     if member.startswith(c["member"].split(".M")[0] + ".")), None)
        key = case or f"unattributed:{member}"
        out.setdefault(key, {})
        out[key][str(r["kind"])] = out[key].get(str(r["kind"]), 0) + 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def observed_red(name: str, report: dict[str, Any], cases: dict[str, Any]) -> dict[str, Any]:
    return red_by_case(report, cases) if name == "hostile" else red_kinds(report)


def member_record(facts: dict[str, Any], member: str) -> tuple[str, dict[str, Any] | None]:
    for carrier in ("functions", "guarded_functions"):
        for rec in facts.get(carrier, []):
            if rec.get("name") == member:
                return carrier, rec
    return "none", None


def calls_of(rec: dict[str, Any] | None) -> list[dict[str, Any]]:
    if rec is None:
        return []
    gf = rec.get("guarded_facts") or {}
    return list(gf.get("calls", []))


def args_view(call: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(a.get("param")): {k: v for k, v in a.items() if k != "param"}
            for a in call.get("args", [])}


def fact_view(call: dict[str, Any]) -> dict[str, Any]:
    v = {k: val for k, val in call.items() if k not in ("site", "statement_line")}
    v["args"] = args_view(call)
    return v


def handle_args(call: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    return [a for a in call.get("args", [])
            if a.get("kind") in ("var", "param") and a.get("name") == symbol]


def design_problems(report: dict[str, Any], member: str, design: dict[str, Any]) -> list[str]:
    members = {str(m["member"]): m for m in report.get("members", [])}
    m = members.get(member)
    if m is None:
        return [f"member {member} not in the oracle report"]
    observed = [oracle._occ_view(o) for o in m.get("occurrences", [])]
    designed = [oracle._design_view(o) for o in design["occurrences"]]
    problems: list[str] = []
    if len(observed) != len(designed):
        return [f"{len(observed)} universe occurrence(s) observed, {len(designed)} designed: "
                f"{observed}"]
    for i, (o, d) in enumerate(zip(observed, designed, strict=True)):
        for k, want in d.items():
            if o.get(k) != want:
                problems.append(f"occurrence {i} ({o.get('symbol')}) {k}={o.get(k)!r}, "
                                f"designed {want!r}")
    if m.get("carrier") != design["carrier"]:
        problems.append(f"carrier {m.get('carrier')!r}, designed {design['carrier']!r}")
    red = red_kinds(report)
    if red:
        problems.append(f"RED {red}")
    return problems


def occurrence_view(report: dict[str, Any], member: str, symbol: str) -> dict[str, Any] | None:
    for m in report.get("members", []):
        if m.get("member") != member:
            continue
        for o in m.get("occurrences", []):
            if o.get("symbol") == symbol:
                return oracle._occ_view(o)
    return None


# ---- the campaign ----

class Campaign:
    def __init__(self, manifest: dict[str, Any], work: Path) -> None:
        self.manifest = manifest
        self.work = work
        self.extractor: Path | None = None
        self.oracle_dll: Path | None = None
        self.hostile_cases: dict[str, Any] = json.loads(
            (HOSTILE / "expected.json").read_text(encoding="utf-8"))["cases"]
        self.baseline: dict[str, dict[str, Any]] = {}

    def sanitized(self, text: str) -> str:
        return text.replace(str(self.work), "<work>").replace(str(ROOT), "<root>")

    def campaign_input(self, name: str) -> tuple[str, list[Path]]:
        only = {name[len("shape:"):]} if name.startswith("shape:") else {name}
        found = [(n, p) for n, p in oracle.inputs(only) if n == name]
        if len(found) != 1:
            raise RuntimeError(f"{name!r} is not one campaign input")
        return found[0]

    def analyse(self, extractor: Path, name: str, paths: list[Path],
                where: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extractor then oracle over one input; raises the forbidden reasons by name."""
        assert self.oracle_dll is not None
        where.mkdir(parents=True, exist_ok=True)
        facts = where / "facts.json"
        try:
            oracle.run_extractor(extractor, paths, facts)
        except RuntimeError as ex:
            raise RuntimeError(f"extractor_crash: {self.sanitized(str(ex))[:300]}") from ex
        try:
            _, report = oracle.run_oracle(self.oracle_dll, paths, facts, where / "oracle.json")
        except RuntimeError as ex:
            raise RuntimeError(f"oracle_crash: {self.sanitized(str(ex))[:300]}") from ex
        if report.get("compile_errors"):
            raise RuntimeError(f"compile_error: {name}: "
                               f"{self.sanitized(str(report.get('compile_error_examples')))[:300]}")
        facts_doc: dict[str, Any] = json.loads(facts.read_text(encoding="utf-8"))
        return report, facts_doc

    # -- baseline --

    def run_baseline(self) -> dict[str, Any]:
        assert self.extractor is not None
        out: dict[str, Any] = {}
        for name in self.manifest["baseline_inputs"]:
            _, paths = self.campaign_input(name)
            report, _ = self.analyse(self.extractor, name, paths,
                                     self.work / "baseline" / name.replace(":", "-"))
            self.baseline[name] = report
            out[name] = {"universe_occurrences": report["summary"]["universe_occurrences"],
                         "red": red_kinds(report)}
        return out

    # -- source metamorphs --

    def run_source(self, mut: dict[str, Any]) -> dict[str, Any]:
        assert self.extractor is not None
        result: dict[str, Any] = {"surface": "source", "operator": mut["operator"],
                                  "expected": mut["expected"], "outcome": "",
                                  "obligations": []}
        base_src = (OUT / mut["source"]).read_text(encoding="utf-8")
        find = mut["patch"]["find"]
        if base_src.count(find) != 1:
            result["outcome"] = "failed:precondition"
            result["detail"] = f"patch anchor occurs {base_src.count(find)} time(s), not once"
            return result
        mutant_src = base_src.replace(find, mut["patch"]["replace"])
        sides: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for side, src in (("base", base_src), ("mutant", mutant_src)):
            where = self.work / "source" / mut["id"] / side
            where.mkdir(parents=True, exist_ok=True)
            cs = where / "case.cs"
            cs.write_text(src, encoding="utf-8")
            try:
                sides[side] = self.analyse(self.extractor, f"{mut['id']}/{side}", [cs], where)
            except RuntimeError as ex:
                reason, _, detail = str(ex).partition(": ")
                result["outcome"] = f"failed:{reason}"
                result["detail"] = f"{side}: {detail}"
                return result
        member = str(mut["member"])
        carriers = {side: member_record(facts, member)[0] for side, (_, facts) in sides.items()}
        result["carrier"] = carriers
        for ob in mut["obligations"]:
            name, ok, detail = self.obligation(ob, mut, sides, member)
            result["obligations"].append({"name": name, "ok": ok, "detail": detail})
        result["outcome"] = "green" if all(o["ok"] for o in result["obligations"]) \
            else "failed:obligation"
        return result

    def obligation(self, ob: dict[str, Any], mut: dict[str, Any],
                   sides: dict[str, tuple[dict[str, Any], dict[str, Any]]],
                   member: str) -> tuple[str, bool, str]:
        kind = str(ob["kind"])
        side = str(ob.get("side", ""))
        if kind == "design":
            problems = design_problems(sides[side][0], member, mut[f"{side}_design"])
            return f"design:{side}", not problems, "; ".join(problems) or "reads as designed"
        if kind == "carrier_unchanged":
            cb = member_record(sides["base"][1], member)[0]
            cm = member_record(sides["mutant"][1], member)[0]
            return kind, cb == cm and cb != "none", f"base {cb}, mutant {cm}"
        calls = {s: calls_of(member_record(f, member)[1]) for s, (_, f) in sides.items()}
        callee = str(ob.get("callee", ""))
        if kind == "fact":
            hits = [c for c in calls[side] if c.get("callee") == callee]
            if len(hits) != 1:
                return f"fact:{side}:{callee}", False, f"{len(hits)} fact(s) at {callee}"
            got = args_view(hits[0])
            want = dict(ob["args"])
            return f"fact:{side}:{callee}", got == want, f"args {got}" if got == want \
                else f"args {got}, contracted {want}"
        if kind == "no_fact":
            hits = [c for c in calls[side] if c.get("callee") == callee]
            return f"no_fact:{side}:{callee}", not hits, \
                f"{len(hits)} fact(s) at {callee}" if hits else "no fact at the site"
        if kind == "no_handle_fact_for":
            symbol = str(ob["symbol"])
            stale = [c.get("callee") for c in calls[side] if handle_args(c, symbol)]
            return f"no_handle_fact_for:{side}:{symbol}", not stale, \
                f"stale var/param({symbol}) at {stale}" if stale else f"no var/param({symbol})"
        if kind == "no_handle_fact_at":
            symbol = str(ob["symbol"])
            hits = [c for c in calls[side] if c.get("callee") == callee]
            stale = [c for c in hits if handle_args(c, symbol)]
            return f"no_handle_fact_at:{side}:{callee}:{symbol}", not stale, \
                (f"{len(hits)} fact(s) at {callee}, {len(stale)} carrying var/param({symbol})")
        if kind == "fact_equal_modulo_site":
            fb = [fact_view(c) for c in calls["base"] if c.get("callee") == callee]
            fm = [fact_view(c) for c in calls["mutant"] if c.get("callee") == callee]
            sb = [c.get("site") for c in calls["base"] if c.get("callee") == callee]
            sm = [c.get("site") for c in calls["mutant"] if c.get("callee") == callee]
            ok = len(fb) == 1 and fb == fm
            return f"fact_equal_modulo_site:{callee}", ok, \
                (f"equal; site {'moved' if sb != sm else 'unchanged'}" if ok
                 else f"base {fb}, mutant {fm}")
        if kind == "occurrence_equal":
            symbol = str(ob["symbol"])
            vb = occurrence_view(sides["base"][0], member, symbol)
            vm = occurrence_view(sides["mutant"][0], member, symbol)
            ok = vb is not None and vb == vm
            return f"occurrence_equal:{symbol}", ok, f"{vb}" if ok else f"base {vb}, mutant {vm}"
        return kind, False, f"unknown obligation kind {kind!r}"

    # -- producer mutants --

    def run_producer(self, mut: dict[str, Any], pristine: str, copy_dir: Path) -> dict[str, Any]:
        result: dict[str, Any] = {"surface": "producer", "reverts": mut["reverts"],
                                  "expected": mut["expected"], "outcome": "",
                                  "expected_red": mut["expected_red"]}
        find = str(mut["patch"]["find"])
        if pristine.count(find) != int(mut["patch"]["occurrences"]):
            result["outcome"] = "failed:precondition"
            result["detail"] = f"patch anchor occurs {pristine.count(find)} time(s)"
            return result
        (copy_dir / "Program.cs").write_text(pristine.replace(find, mut["patch"]["replace"]),
                                            encoding="utf-8")
        try:
            dll = oracle.build(copy_dir, "ownsharp-extract.dll")
        except RuntimeError as ex:
            result["outcome"] = "failed:build_failure"
            result["detail"] = self.sanitized(str(ex))[-600:]
            return result
        finally:
            pass
        result["build"] = "ok"
        observed: dict[str, Any] = {}
        mismatches: dict[str, list[str]] = {}
        for name in mut["inputs"]:
            _, paths = self.campaign_input(name)
            try:
                where = self.work / "producer" / mut["id"] / name.replace(":", "-")
                report, _ = self.analyse(dll, name, paths, where)
            except RuntimeError as ex:
                reason, _, detail = str(ex).partition(": ")
                result["outcome"] = f"failed:{reason}"
                result["detail"] = f"{name}: {detail}"
                return result
            observed[name] = observed_red(name, report, self.hostile_cases)
            if name == "hostile":
                bad = [case for case, design in self.hostile_cases.items()
                       if design_problems_case(report, case, design)]
                mismatches[name] = sorted(bad)
        result["observed_red"] = observed
        result["hostile_design_mismatches"] = mismatches.get("hostile", [])
        killed = any(observed.values())
        exact = observed == mut["expected_red"]
        witnessed = all(w in observed.get("hostile", {}) for w in mut["witnesses"])
        if exact and witnessed:
            result["outcome"] = "killed"
            result["kill_reason"] = "preregistered"
        elif not killed:
            result["outcome"] = "survived"
        else:
            result["outcome"] = "killed:unexpected_reason"
        return result

    # -- the taxonomy mutant --

    def run_taxonomy(self, mut: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"surface": "taxonomy", "expected": mut["expected"],
                                  "outcome": "", "removed": mut["remove_exclusion"]}
        name = str(mut["remove_exclusion"])
        registry: dict[str, Any] = json.loads(REGISTRY.read_text(encoding="utf-8"))
        if name not in registry.get("exclusions", {}):
            result["outcome"] = "failed:precondition"
            result["detail"] = f"{name} is not a registry exclusion"
            return result
        del registry["exclusions"][name]
        where = self.work / "taxonomy" / mut["id"]
        where.mkdir(parents=True, exist_ok=True)
        mutated = where / "registry.json"
        mutated.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        json.loads(mutated.read_text(encoding="utf-8"))       # must stay well-formed
        # The baseline reading of the shape, before its name is removed.
        probe_expected: dict[str, Any] = json.loads(PROBE_EXPECTED.read_text(encoding="utf-8"))
        readings = oracle.probe_readings(self.baseline["probe"],
                                         set(probe_expected.get("helpers", [])))
        baseline_rows = {row: readings.get(row) for row in mut["baseline_probe_row"]}
        result["baseline_probe_row"] = baseline_rows
        components: dict[str, dict[str, str]] = {
            "freeze_test": run_test_module(TESTS / "test_p037_relevance_freeze.py",
                                           "p037_mut_freeze", mutated),
            "hostile_test": run_test_module(TESTS / "test_p037_hostile_census.py",
                                            "p037_mut_hostile", mutated),
            "oracle_driver": self.driver_failures(mut, mutated),
        }
        result["failures"] = components
        problems: list[str] = []
        if baseline_rows != mut["baseline_probe_row"]:
            problems.append(f"baseline reads {baseline_rows}")
        for comp, want in mut["expected_failures"].items():
            got = components[comp]
            if sorted(got) != sorted(want["failing_checks"]):
                problems.append(f"{comp}: failing {sorted(got)}, expected "
                                f"{sorted(want['failing_checks'])}")
            for c in want["must_name"]:
                if name not in got.get(c, ""):
                    problems.append(f"{comp}: {c} does not name {name}")
        if not problems:
            result["outcome"] = "unclassified"
        elif not any(components.values()):
            result["outcome"] = "silent"
        else:
            result["outcome"] = "reclassified_or_other"
        if problems:
            result["detail"] = "; ".join(problems)
        return result

    def driver_failures(self, mut: dict[str, Any], mutated: Path) -> dict[str, str]:
        frozen = oracle.frozen_exclusions(mutated)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for name in mut["oracle_inputs"]:
                oracle.check_exclusions_frozen(name, self.baseline[name], frozen)
        oracle._failures.clear()
        return parse_failures(buf.getvalue())


def design_problems_case(report: dict[str, Any], case: str, design: dict[str, Any]) -> list[str]:
    member_name = str(design["member"])
    if design.get("member_override"):
        member_name = member_name.rsplit(".M", 1)[0] + str(design["member_override"])
    problems = design_problems(report, member_name, design)
    return [p for p in problems if not p.startswith("RED ")]


def parse_failures(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("FAIL["):
            name, _, detail = line[len("FAIL["):].partition("]: ")
            out[name] = detail
    return out


def run_test_module(path: Path, name: str, registry: Path) -> dict[str, str]:
    """Run a standalone test module in-process against a mutated registry; its FAIL lines."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod: Any = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod.REGISTRY = registry
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.run()
    return parse_failures(buf.getvalue())


def run_campaign(manifest: dict[str, Any], work: Path) -> dict[str, Any]:
    before = {str(p.relative_to(ROOT)): sha256_of(p.read_bytes())
              for p in (PROGRAM, REGISTRY, ORACLE / "Program.cs")}
    status_before = sorted(git("status", "--porcelain").splitlines())
    campaign = Campaign(manifest, work)
    campaign.extractor = oracle.build(EXTRACTOR, "ownsharp-extract.dll")
    campaign.oracle_dll = oracle.build(ORACLE, "ownsharp-oracle.dll")
    results: dict[str, Any] = {}
    baseline = campaign.run_baseline()
    pristine = PROGRAM.read_text(encoding="utf-8")
    copy_dir = work / "producer" / "OwnSharp.Extractor"
    copy_dir.mkdir(parents=True, exist_ok=True)
    for item in EXTRACTOR.iterdir():
        if item.name in ("bin", "obj"):
            continue
        if item.is_dir():
            shutil.copytree(item, copy_dir / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, copy_dir / item.name)
    exercised: dict[str, int] = {}
    for mut in manifest["mutants"]:
        mid = str(mut["id"])
        exercised[mid] = exercised.get(mid, 0) + 1
        if mut["surface"] == "source":
            results[mid] = campaign.run_source(mut)
        elif mut["surface"] == "producer":
            results[mid] = campaign.run_producer(mut, pristine, copy_dir)
            (copy_dir / "Program.cs").write_text(pristine, encoding="utf-8")
        elif mut["surface"] == "taxonomy":
            results[mid] = campaign.run_taxonomy(mut)
        else:
            results[mid] = {"surface": mut["surface"], "outcome": "failed:unknown_surface"}
        print(f"  {mid}: {results[mid]['outcome']}")
    after = {str(p.relative_to(ROOT)): sha256_of(p.read_bytes())
             for p in (PROGRAM, REGISTRY, ORACLE / "Program.cs")}
    status_after = sorted(git("status", "--porcelain").splitlines())
    ledger: dict[str, Any] = json.loads(FINDINGS.read_text(encoding="utf-8"))
    outcomes = {mid: str(r["outcome"]) for mid, r in results.items()}
    by_surface = {s: [mid for mid, m in ((str(m["id"]), m) for m in manifest["mutants"])
                      if m["surface"] == s] for s in ("source", "producer", "taxonomy")}
    acceptance = {
        "every_mutant_exercised_once": all(n == 1 for n in exercised.values())
        and set(exercised) == {str(m["id"]) for m in manifest["mutants"]},
        "every_mutant_compiles": not any(o.startswith("failed:build_failure")
                                         or o.startswith("failed:compile_error")
                                         for o in outcomes.values()),
        "source_metamorphs_green": all(outcomes[m] == "green" for m in by_surface["source"]),
        "producer_mutants_killed_by_preregistered_reason":
            all(outcomes[m] == "killed" for m in by_surface["producer"]),
        "taxonomy_mutant_unclassified":
            all(outcomes[m] == "unclassified" for m in by_surface["taxonomy"]),
        "no_survivor": not any(o.startswith("survived") for o in outcomes.values()),
        "no_unexpected_kill_reason": not any(":unexpected" in o or o.startswith("failed:")
                                             or o in ("silent", "reclassified_or_other")
                                             for o in outcomes.values()),
        "production_tree_restored": before == after and status_before == status_after,
        "ordinary_oracle_red_free": all(not b["red"] for b in baseline.values()),
        "no_open_finding": not ledger.get("findings"),
    }
    acceptance["all"] = all(acceptance.values())
    return {
        "schema": SCHEMA,
        "manifest_sha256": sha256_of(MANIFEST.read_bytes()),
        "production_digest": production_digest(),
        "provenance": {"base_sha": git("rev-parse", "HEAD"),
                       "pending_paths": status_before},
        "baseline": baseline,
        "mutants": results,
        "totals": {"mutants": len(results),
                   **{k: sum(1 for o in outcomes.values() if o == k)
                      for k in ("green", "killed", "unclassified")},
                   "survived": sum(1 for o in outcomes.values() if o.startswith("survived")),
                   "forbidden": sum(1 for o in outcomes.values() if o.startswith("failed:"))},
        "acceptance": acceptance,
    }


def comparable(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k != "provenance"}


# ---- check (no dotnet) ----

def check_static() -> int:
    sources, manifest = generate_all()
    with tempfile.TemporaryDirectory(prefix="p037-mutation-") as td:
        write(sources, manifest, Path(td))
        fresh = Path(td)
        problems: list[str] = []
        committed = {p.name for p in SOURCES.glob("*.cs")} if SOURCES.exists() else set()
        generated = {p.name for p in (fresh / "sources").glob("*.cs")}
        for n in sorted(committed - generated):
            problems.append(f"stale committed source {n}")
        for n in sorted(generated - committed):
            problems.append(f"missing committed source {n}")
        for n in sorted(generated & committed):
            if (SOURCES / n).read_bytes() != (fresh / "sources" / n).read_bytes():
                problems.append(f"source {n} differs from a regeneration")
        if not MANIFEST.exists() or MANIFEST.read_bytes() != (fresh / "manifest.json").read_bytes():
            problems.append("manifest.json differs from a regeneration")
    check("mutation-manifest-drift", not problems, "; ".join(problems))

    program = PROGRAM.read_text(encoding="utf-8")
    registry: dict[str, Any] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    hostile: dict[str, Any] = json.loads((HOSTILE / "expected.json").read_text(encoding="utf-8"))
    cases: dict[str, Any] = hostile["cases"]
    shapes = {f"shape:{p.parent.name}" for p in SHAPES.glob("*/case.cs")}
    pre: list[str] = []
    ids = [str(m["id"]) for m in manifest["mutants"]]
    if len(ids) != len(set(ids)):
        pre.append("duplicate mutant ids")
    for mut in manifest["mutants"]:
        mid = mut["id"]
        if mut.get("forbidden_kill_reasons") != FORBIDDEN:
            pre.append(f"{mid}: forbidden kill reasons not declared")
        if mut["surface"] == "source":
            src = sources[f"{mid}.cs"]
            if src.count(mut["patch"]["find"]) != 1:
                pre.append(f"{mid}: patch anchor not exactly once in its source")
            if not mut.get("must_compile") or mut.get("expected") != "green":
                pre.append(f"{mid}: a source metamorph must compile and stay green")
        elif mut["surface"] == "producer":
            count = program.count(mut["patch"]["find"])
            if count != mut["patch"]["occurrences"]:
                pre.append(f"{mid}: patch anchor occurs {count} time(s) in Program.cs")
            if not mut.get("must_compile") or mut.get("expected") != "killed":
                pre.append(f"{mid}: a producer mutant must compile and be killed")
            for w in mut["witnesses"]:
                if w not in cases:
                    pre.append(f"{mid}: witness {w} is not a hostile case")
                if not mut["expected_red"].get("hostile", {}).get(w):
                    pre.append(f"{mid}: witness {w} has no expected RED")
            for name in mut["inputs"]:
                if name not in ("hostile", "probe") and name not in shapes:
                    pre.append(f"{mid}: input {name} does not exist")
                if name not in mut["expected_red"]:
                    pre.append(f"{mid}: input {name} has no expected RED map")
            for case in mut["expected_red"].get("hostile", {}):
                if case not in cases:
                    pre.append(f"{mid}: expected RED on unknown case {case}")
        elif mut["surface"] == "taxonomy":
            if mut["remove_exclusion"] not in registry.get("exclusions", {}):
                pre.append(f"{mid}: {mut['remove_exclusion']} is not a registry exclusion")
            if mut.get("expected") != "unclassified":
                pre.append(f"{mid}: a taxonomy mutant must read unclassified")
    check("mutation-manifest-preconditions", not pre, "; ".join(pre))

    rep: list[str] = []
    if not REPORT.exists():
        rep.append("report.json is missing: run `p037_mutation_campaign.py run --record`")
    else:
        report: dict[str, Any] = json.loads(REPORT.read_text(encoding="utf-8"))
        if report.get("schema") != SCHEMA:
            rep.append(f"report schema {report.get('schema')!r}")
        if report.get("manifest_sha256") != sha256_of(MANIFEST.read_bytes()):
            rep.append("report.json was recorded for another manifest")
        if report.get("production_digest") != production_digest():
            rep.append("report.json was recorded for another production tree "
                       "(extractor, oracle, registry, probe, ledger, census): re-record")
        if set(report.get("mutants", {})) != set(ids):
            rep.append("report.json does not cover exactly the manifest's mutants")
        acc = report.get("acceptance", {})
        if not acc.get("all"):
            rep.append(f"acceptance not met: {[k for k, v in acc.items() if not v]}")
        for mid, r in report.get("mutants", {}).items():
            if r.get("outcome") != r.get("expected"):
                rep.append(f"{mid}: outcome {r.get('outcome')!r}, expected {r.get('expected')!r}")
        if not report.get("provenance", {}).get("base_sha"):
            rep.append("report.json carries no base sha")
    check("mutation-report-consistent", not rep, "; ".join(rep))
    if _failures:
        print(f"RESULT: {len(_failures)} mutation-campaign check(s) failed")
        return 1
    print(f"RESULT: mutation campaign manifest consistent over {len(ids)} mutant(s)")
    return 0


# ---- driver ----

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("generate", "check", "run"))
    ap.add_argument("--record", action="store_true", help="run: write report.json")
    ap.add_argument("--keep", default="", help="run: directory to keep the work in")
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        sources, manifest = generate_all()
        write(sources, manifest, OUT)
        print(f"generated {len(manifest['mutants'])} mutant(s) into {OUT.relative_to(ROOT)}")
        return 0
    if args.cmd == "check":
        return check_static()
    doc: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        print(f"manifest schema {doc.get('schema')!r} != {SCHEMA}", file=sys.stderr)
        return 2
    keep = Path(args.keep) if args.keep else None
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p037-mutation-") as td:
        work = keep or Path(td)
        report = run_campaign(doc, work)
        if keep:
            (keep / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                              encoding="utf-8")
    acc = report["acceptance"]
    for name, ok in acc.items():
        if name != "all":
            check(f"acceptance:{name}", bool(ok),
                  "; ".join(f"{mid}: {r['outcome']} ({r.get('detail', '')})"
                            for mid, r in report["mutants"].items()
                            if r["outcome"] != r.get("expected"))[:1200])
    if args.record:
        REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {REPORT.relative_to(ROOT)} at {report['provenance']['base_sha'][:7]}")
    else:
        committed: dict[str, Any] = json.loads(REPORT.read_text(encoding="utf-8")) \
            if REPORT.exists() else {}
        same = comparable(committed) == comparable(report)
        detail = ""
        if not same:
            diff = [k for k in set(comparable(committed)) | set(comparable(report))
                    if comparable(committed).get(k) != comparable(report).get(k)]
            per = [mid for mid in report["mutants"]
                   if committed.get("mutants", {}).get(mid) != report["mutants"][mid]]
            detail = f"differing keys {sorted(diff)}; differing mutants {per}"
        check("campaign-equals-recorded-report", same, detail)
    if _failures:
        print(f"RESULT: {len(_failures)} mutation-campaign check(s) failed")
        return 1
    t = report["totals"]
    print(f"RESULT: mutation campaign accepted: {t['green']} metamorph(s) green, "
          f"{t['killed']} producer mutant(s) killed by their preregistered reason, "
          f"{t['unclassified']} taxonomy mutant(s) unclassified, {t['survived']} survivor(s), "
          f"{t['forbidden']} forbidden kill reason(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
