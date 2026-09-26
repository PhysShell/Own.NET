#!/usr/bin/env python3
"""P-037 Phase B / B1-F2-F4: the delegation-closure control, as machine evidence.

B1-F2-F3b's accepted architecture (docs/notes/p037-formal-kernel.md, the
B1-F2-F4 section) rests on one empirical claim: every `release` op the
extractor's legacy `ConsumeReleaseArgs`/`ConsumesParam` interprocedural
shortcut fabricates at a call site already has a corresponding, honestly
emitted `guarded_facts.calls[]` entry on the SAME caller, at the SAME site
-- so B2.1a can turn that fabrication into a `use` unconditionally, and
B2.1b/c's Rust solver can read the sidecar to decide the real answer,
without the extractor ever inspecting a guard.

That claim was first measured with a scratch, never-committed prototype
(a before/after diff over a patched extractor) and reported 40/40 -- real,
but not machine evidence: nobody but the author could re-derive it, and
the population was hand-picked. This module is the governed replacement,
built to run against the UNMODIFIED, frozen extractor, over the FULL
population, deriving its own count.

WHY NO EXTRACTOR PATCH IS NEEDED. A release op carries only `{var, line}`
-- no provenance tag -- so the original prototype toggled
`ConsumeReleaseArgs` and watched which releases flipped to `use`. That
technique cannot be committed (a permanent tool cannot keep patching and
reverting frozen production source on every run, and doing so would be
exactly the kind of instrument/treatment confusion this project's own
governance forbids). It is also unnecessary: a legacy-fabricated release
can be identified STRUCTURALLY, from one unmodified extraction, because a
release with no interprocedural cause (a direct `s.Dispose()`/`s.Close()`)
can never correlate with an ELIGIBLE `guarded_facts.calls[]` entry at all
-- that sidecar records calls where a value is passed AS AN ARGUMENT,
never a receiver-based call on the resource itself (confirmed directly
against `corpus/p037-shapes/extension-receiver`: `CallReleasesReceiver` is
untouched by this seam and that fixture's own `Caller` carries a `use`,
never a `release`, at its call site). So the checked population is derived
in two independent steps, never assumed:

1. STRUCTURAL candidacy: a `release(var=V, line=L)` inside a `functions[]`
   body is a candidate iff the SAME function's `guarded_facts.calls[]`
   contains at least one ELIGIBLE entry whose `statement_line == L` --
   independent of whether that entry actually names V. ELIGIBLE means
   `form == "statement"` and no `call_kind` (a plain method-call statement,
   never a call nested in a declaration's initializer or a larger
   expression, never object_creation/delegate_invocation/
   constructor_initializer) -- the ONLY shape ConsumeReleaseArgs/
   ConsumesParam/EmitFlowExpr ever fabricate a release for. This
   eligibility filter is not a simplification for convenience; it is a
   correction found the hard way, against the real, full population:
   `corpus/p037-shapes/sidecar-ctorinit-base` packs `var f = new
   Forwarding(r); f.Dispose();` onto ONE physical source line, so the
   direct `f.Dispose()` release shares its line with an unrelated
   initializer-form, object_creation-kind call (`new Forwarding(r)`,
   A2.2-4R5's own new ctor-initializer territory, which ConsumeReleaseArgs
   never reasons about at all) -- without the eligibility filter that
   coincidence read as a false MISSING on the first full-population run.
   A release with zero co-located ELIGIBLE calls is excluded outright: it
   cannot be call-derived, by construction.
2. IDENTITY verification: among a candidate's co-located eligible calls,
   exactly one must name V as an argument -- `kind: "var"` matched by
   `name`, or `kind: "param"` resolved through the CALLER's own declared
   `params[]` ordinal (both forms measured directly against
   `corpus/p036-bakeoff/guarded-consume-wrapper-forward`, which uses
   `kind: "param"` for its wrapper's forwarded receiver AND flag). Zero
   matches is MISSING; more than one is AMBIGUOUS; this module never
   guesses past either.

Every reported site carries its full available identity (statement_line,
the call's own site line/column, callee, sig) rather than a bare line
number, precisely because a bare line is not always enough to disambiguate
(step 1's own eligibility filter exists for that reason) -- a genuine
ambiguity is reported with everything available, never silently narrowed
to "first match wins".

BOTH GUARDED-FACT LOCATIONS. `functions[].guarded_facts` and
`guarded_functions[].guarded_facts` are unified into one per-identity view
(docs/notes/p037-formal-kernel.md §10.6.6: "Phase B builds one
guarded-method view from functions[].guarded_facts plus
guarded_functions[].guarded_facts"). A release-emitting caller is always
found in `functions[]` (an orphan carrier entry has no `body` at all -- it
exists precisely FOR methods the legacy pass never flow-analysed), so
`guarded_functions[]`-hosted calls can never correlate to a release; this
module asserts that structural fact rather than silently ignoring the
carrier, and separately counts such calls so a future reader sees the
exclusion, not an absence.

NOT PART OF THE PASS/FAIL VERDICT: calls whose caller-side argument has no
matching release at all (`calls_without_release`). A known example is
already on record (extension-receiver's pre-existing `CallReleasesReceiver`
gap, explicitly "not A1's to fix"); this module reports the bucket for
visibility, exactly so a real future regression there is not mistaken for
noise, but does not fail the control on it -- that gap belongs to a
different, frozen mechanism this seam never touches.

Run:  python scripts/p037_delegation_closure.py check
      python scripts/p037_delegation_closure.py selftest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import p037_evidence_b as evb  # noqa: E402

CORPUS_DIRS: tuple[str, ...] = evb.CORPUS_DIRS
REPO_TREE_DIRS: tuple[str, ...] = evb.REPO_TREE_DIRS

SCHEMA = "p037-delegation-closure/1"


class DerivationRefused(RuntimeError):
    """The population or a document is off-contract; refused, not guessed past."""


# --------------------------------------------------------------------------- extraction


def _extract(paths: list[Path], doc_id: str, *, repo: Path = ROOT) -> dict[str, Any]:
    """One extractor execution, `--engine python` (facts are engine-independent;
    this avoids requiring a built Rust candidate for a facts-only control)."""
    if not paths:
        raise DerivationRefused(f"{doc_id}: zero source files")
    with tempfile.TemporaryDirectory(prefix="p037-delegation-closure-") as td:
        facts = Path(td) / "facts.json"
        cmd = [
            "bash", str(repo / "scripts" / "own-check.sh"),
            "--engine", "python", "--format", "human", "--severity", "warning",
            "--emit-facts", str(facts),
            "--", *(str(p) for p in paths),
        ]
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):
            raise DerivationRefused(
                f"{doc_id}: extractor/launcher failed, exit {proc.returncode}\n"
                f"{proc.stderr[-2000:]}")
        try:
            return json.loads(facts.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DerivationRefused(f"{doc_id}: no emitted facts: {exc}") from exc


def population_documents(*, repo: Path = ROOT) -> list[tuple[str, list[Path]]]:
    """[(doc_id, paths)]: one entry per corpus file (never batched -- several
    corpus/p036-bakeoff fixtures share top-level class names with no
    namespace, and batching them into one Roslyn compilation corrupts symbol
    resolution; this bug was already found and fixed once this session), plus
    one entry for the whole repo tree (one compilation, because it is one
    program) -- exactly p037_mos_snapshot.py's own `source_documents()` split."""
    docs: list[tuple[str, list[Path]]] = []
    corpus_files: list[Path] = []
    for d in CORPUS_DIRS:
        corpus_files.extend(sorted((repo / d).rglob("*.cs")))
    for path in corpus_files:
        docs.append((path.relative_to(repo).as_posix(), [path]))
    repo_files: list[Path] = []
    for d in REPO_TREE_DIRS:
        proc = subprocess.run(["git", "ls-files", d], cwd=repo, capture_output=True,
                              text=True, check=True)
        repo_files.extend(repo / p for p in proc.stdout.splitlines() if p.endswith(".cs"))
    if repo_files:
        docs.append(("repo-tree", repo_files))
    return docs


# --------------------------------------------------------------------------- matching


def _identity(rec: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (rec.get("file"), rec.get("name"), rec.get("sig"))


def _flatten_body(ops: list[Any]) -> list[dict[str, Any]]:
    """Leaf ops in source order; `if` recurses into `then`/`else` (the only
    nesting construct this vocabulary has -- census_match.py's own `flat()`,
    proven against the full R_B population in B1-F2-F3b)."""
    out: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        if op.get("op") == "if":
            out.extend(_flatten_body(op.get("then", []) or []))
            out.extend(_flatten_body(op.get("else", []) or []))
        else:
            out.append(op)
    return out


def _site_identity(call: dict[str, Any]) -> dict[str, Any]:
    site = call.get("site") if isinstance(call.get("site"), dict) else {}
    return {
        "statement_line": call.get("statement_line"),
        "site_line": site.get("line"),
        "site_column": site.get("column"),
        "callee": call.get("callee"),
        "sig": call.get("sig"),
    }


def _eligible(call: dict[str, Any]) -> bool:
    """A plain method-call statement -- the ONLY shape ConsumeReleaseArgs/
    ConsumesParam/EmitFlowExpr ever fabricate a release for. See the module
    docstring's step 1 for the real (not hypothetical) collision this
    filter exists to prevent."""
    return (bool(call.get("first_party")) and call.get("callee") is not None
           and call.get("form") == "statement" and call.get("call_kind") is None)


def _arg_identity_names(call: dict[str, Any], caller_params: list[dict[str, Any]]) -> set[str]:
    """Every name this call's `var`/`param`-kind arguments resolve to, given
    the CALLER's own declared `params[]` for ordinal resolution."""
    names: set[str] = set()
    for arg in call.get("args", []) or []:
        if not isinstance(arg, dict):
            continue
        kind = arg.get("kind")
        if kind == "var" and isinstance(arg.get("name"), str):
            names.add(arg["name"])
        elif kind == "param":
            ordinal = arg.get("source_param")
            if isinstance(ordinal, int) and 0 <= ordinal < len(caller_params):
                p = caller_params[ordinal]
                if isinstance(p, dict) and isinstance(p.get("name"), str):
                    names.add(p["name"])
    return names


def build_guarded_view(
    doc: dict[str, Any], doc_id: str
) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    """The unified per-identity guarded-method view (docs/notes/
    p037-formal-kernel.md §10.6.6): `functions[]` entries (which carry a
    body, hence can host a release) and `guarded_functions[]` entries
    (orphans; no body, so their own calls[] can never correlate to a
    release -- asserted, not assumed, by `orphan_hosted_calls` below).
    Refuses a document where the same identity appears in both, per the
    producer's own §5.3 contract."""
    view: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for fn in doc.get("functions", []) or []:
        if not isinstance(fn, dict):
            continue
        key = _identity(fn)
        if key in view:
            raise DerivationRefused(f"{doc_id}: duplicate functions[] identity {key!r}")
        view[key] = {"kind": "functions", "record": fn}
    for orphan in doc.get("guarded_functions", []) or []:
        if not isinstance(orphan, dict):
            continue
        key = _identity(orphan)
        if key in view:
            raise DerivationRefused(
                f"{doc_id}: identity {key!r} appears in both functions[] and "
                "guarded_functions[] (producer defect, spec/OwnIR.md §5.3)")
        view[key] = {"kind": "guarded_functions", "record": orphan}
    return view


def check_document(doc: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """One document's contribution: covered/missing/ambiguous release sites,
    plus the two informational buckets (orphan_hosted_calls,
    calls_without_release) documented in the module docstring."""
    view = build_guarded_view(doc, doc_id)
    covered: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    orphan_hosted_calls: list[dict[str, Any]] = []
    calls_without_release: list[dict[str, Any]] = []

    for key, entry in view.items():
        rec = entry["record"]
        gf = rec.get("guarded_facts")
        calls = gf.get("calls", []) if isinstance(gf, dict) else []
        if entry["kind"] == "guarded_functions":
            for call in calls:
                if isinstance(call, dict) and _eligible(call) and \
                        any(isinstance(a, dict) and a.get("kind") in ("var", "param")
                            for a in call.get("args", []) or []):
                    orphan_hosted_calls.append({"doc": doc_id, "caller": list(key),
                                                "call": _site_identity(call)})
            continue  # no body: structurally cannot host a release

        params = rec.get("params") or []
        body_ops = _flatten_body(rec.get("body", []) or [])
        releases = [op for op in body_ops if op.get("op") == "release"
                   and isinstance(op.get("var"), str) and isinstance(op.get("line"), int)]

        # See _eligible()'s docstring and the module docstring's step 1 for
        # why "eligible" excludes non-statement / non-plain calls.
        relevant_calls = [c for c in calls if isinstance(c, dict) and _eligible(c)]

        matched_release_ids: set[int] = set()
        for rel_op in releases:
            var, line = rel_op["var"], rel_op["line"]
            co_located = [c for c in relevant_calls if c.get("statement_line") == line]
            if not co_located:
                continue  # excluded: no possible interprocedural cause at this line
            matches = [c for c in co_located if var in _arg_identity_names(c, params)]
            record = {"doc": doc_id, "caller": list(key), "var": var, "line": line,
                      "matches": [_site_identity(c) for c in matches]}
            if not matches:
                missing.append(record)
            elif len(matches) > 1:
                ambiguous.append(record)
            else:
                covered.append(record)
                matched_release_ids.add(id(matches[0]))

        for call in relevant_calls:
            if id(call) in matched_release_ids:
                continue
            names = _arg_identity_names(call, params)
            if not names:
                continue  # a bool_const/null_literal/object_creation/opaque/call_result-only
                          # call has no candidate identity to look for at all
            calls_without_release.append({"doc": doc_id, "caller": list(key),
                                          "call": _site_identity(call), "names": sorted(names)})

    return {"covered": covered, "missing": missing, "ambiguous": ambiguous,
            "orphan_hosted_calls": orphan_hosted_calls,
            "calls_without_release": calls_without_release}


# --------------------------------------------------------------------------- check


def check(*, repo: Path = ROOT) -> dict[str, Any]:
    documents = population_documents(repo=repo)
    covered: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    orphan_hosted_calls: list[dict[str, Any]] = []
    calls_without_release: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, (doc_id, paths) in enumerate(documents, 1):
        try:
            doc = _extract(paths, doc_id, repo=repo)
            result = check_document(doc, doc_id)
        except DerivationRefused as exc:
            errors.append(str(exc))
            continue
        covered.extend(result["covered"])
        missing.extend(result["missing"])
        ambiguous.extend(result["ambiguous"])
        orphan_hosted_calls.extend(result["orphan_hosted_calls"])
        calls_without_release.extend(result["calls_without_release"])
        print(f"  [{i:3}/{len(documents)}] {doc_id} ({len(paths)} source file(s))", flush=True)

    total = len(covered) + len(missing) + len(ambiguous)
    return {
        "schema": SCHEMA,
        "documents": len(documents),
        "total": total,
        "covered": len(covered),
        "missing": missing,
        "ambiguous": ambiguous,
        "orphan_hosted_calls": len(orphan_hosted_calls),
        "calls_without_release": calls_without_release,
        "errors": errors,
        "ok": not errors and not missing and not ambiguous,
    }


def print_report(rep: dict[str, Any]) -> None:
    print(f"\nDELEGATION CLOSURE: documents={rep['documents']}")
    print(f"total = {rep['total']}")
    print(f"covered = {rep['covered']}")
    print(f"missing = {len(rep['missing'])}")
    print(f"ambiguous = {len(rep['ambiguous'])}")
    print(f"orphan-hosted calls (structurally excluded) = {rep['orphan_hosted_calls']}")
    print(f"calls without a release (informational, not a failure) = "
          f"{len(rep['calls_without_release'])}")
    for r in rep["calls_without_release"]:
        print(f"  no-release: {r}")
    if rep["errors"]:
        print(f"\n{len(rep['errors'])} extraction error(s):")
        for e in rep["errors"]:
            print(f"  {e}")
    if rep["missing"]:
        print("\n--- MISSING ---")
        for r in rep["missing"]:
            print(f"  {r}")
    if rep["ambiguous"]:
        print("\n--- AMBIGUOUS ---")
        for r in rep["ambiguous"]:
            print(f"  {r}")
    print(f"\nRESULT: {'covered == total, 0 missing, 0 ambiguous' if rep['ok'] else 'FAILED'}")


# --------------------------------------------------------------------------- selftest

_failures = 0


def _check(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def _fn(name: str, file: str, sig: str, params: list[dict[str, Any]] | None,
       body: list[Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "file": file, "sig": sig, "params": params, "body": body,
           "guarded_facts": {"version": 1, "calls": calls, "guards": []}}


def _call(line: int, callee: str, sig: str, args: list[dict[str, Any]],
         first_party: bool = True, form: str = "statement",
         call_kind: str | None = None) -> dict[str, Any]:
    return {"site": {"line": line, "column": 9}, "statement_line": line, "form": form,
           "callee": callee, "sig": sig, "first_party": first_party, "args": args,
           "call_kind": call_kind}


def selftest() -> int:
    # --- synthetic: var-kind covered ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "s", "line": 1}, {"op": "release", "var": "s", "line": 2}],
            [_call(2, "Callee", "System.IO.Stream", [{"param": 0, "kind": "var", "name": "s"}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("var-kind-covered",
          len(r["covered"]) == 1 and not r["missing"] and not r["ambiguous"], r)

    # --- synthetic: param-kind covered (wrapper forwarding, no acquire) ---
    doc = {"functions": [
        _fn("Outer", "f.cs", "", [{"name": "s", "line": 1}],
            [{"op": "release", "var": "s", "line": 3}],
            [_call(3, "Inner", "System.IO.Stream",
                  [{"param": 0, "kind": "param", "source_param": 0}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("param-kind-covered",
          len(r["covered"]) == 1 and not r["missing"] and not r["ambiguous"], r)

    # --- synthetic: excluded (direct dispose, no co-located call at all) ---
    doc = {"functions": [
        _fn("Direct", "f.cs", "", [{"name": "s", "line": 1}],
            [{"op": "release", "var": "s", "line": 2}], []),
    ]}
    r = check_document(doc, "synthetic")
    _check("direct-dispose-excluded-not-missing",
          not r["covered"] and not r["missing"] and not r["ambiguous"], r)

    # --- synthetic: missing (a co-located call exists but names a different var) ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "s", "line": 1}, {"op": "release", "var": "s", "line": 2}],
            [_call(2, "Callee", "System.String", [{"param": 0, "kind": "var", "name": "other"}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("mismatched-arg-is-missing", len(r["missing"]) == 1 and not r["covered"], r)

    # --- synthetic: ambiguous (two co-located calls both naming the released var) ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "s", "line": 1}, {"op": "release", "var": "s", "line": 2}],
            [_call(2, "A", "System.String", [{"param": 0, "kind": "var", "name": "s"}]),
             _call(2, "B", "System.String", [{"param": 0, "kind": "var", "name": "s"}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("two-co-located-matches-is-ambiguous", len(r["ambiguous"]) == 1 and not r["covered"], r)

    # --- synthetic: non-first-party / unresolved co-located calls never count ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "s", "line": 1}, {"op": "release", "var": "s", "line": 2}],
            [_call(2, None, None, [{"param": 0, "kind": "var", "name": "s"}], first_party=False)]),
    ]}
    r = check_document(doc, "synthetic")
    _check("non-first-party-call-excludes", not r["covered"] and not r["missing"], r)

    # --- synthetic: orphan-hosted call is tallied separately, never covered/missing ---
    doc = {"guarded_functions": [
        {"name": "Orphan", "file": "f.cs", "sig": "", "guarded_facts": {
            "version": 1, "guards": [],
            "calls": [_call(5, "Callee", "System.String",
                            [{"param": 0, "kind": "var", "name": "s"}])]}},
    ]}
    r = check_document(doc, "synthetic")
    _check("orphan-hosted-call-is-separate-bucket",
          len(r["orphan_hosted_calls"]) == 1 and not r["covered"] and not r["missing"], r)

    # --- synthetic: a call with no matching release is informational, not missing ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "s", "line": 1}, {"op": "use", "var": "s", "line": 2}],
            [_call(2, "Callee", "System.String", [{"param": 0, "kind": "var", "name": "s"}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("call-without-release-is-informational-not-missing",
          len(r["calls_without_release"]) == 1 and not r["missing"] and not r["covered"], r)

    # --- synthetic: duplicate identity across functions[]/guarded_functions[] is refused ---
    doc = {"functions": [_fn("Dup", "f.cs", "", None, [], [])],
          "guarded_functions": [{"name": "Dup", "file": "f.cs", "sig": "",
                                 "guarded_facts": {"version": 1, "calls": [], "guards": []}}]}
    try:
        check_document(doc, "synthetic")
        _check("duplicate-identity-is-refused", False, "did not raise")
    except DerivationRefused:
        _check("duplicate-identity-is-refused", True)

    # --- if/then/else flattening handles nesting ---
    doc = {"functions": [
        _fn("Nested", "f.cs", "", None,
            [{"op": "if", "line": 1, "then": [{"op": "release", "var": "s", "line": 2}],
              "else": [{"op": "release", "var": "t", "line": 3}]}],
            [_call(2, "A", "", [{"param": 0, "kind": "var", "name": "s"}]),
             _call(3, "B", "", [{"param": 0, "kind": "var", "name": "t"}])]),
    ]}
    r = check_document(doc, "synthetic")
    _check("nested-if-then-else-both-found", len(r["covered"]) == 2, r)

    # --- synthetic: a direct-dispose release sharing its line with an
    # unrelated initializer-form/object_creation call must be EXCLUDED, not
    # MISSING -- the exact corpus/p037-shapes/sidecar-ctorinit-base
    # collision this module's eligibility filter was built to survive. ---
    doc = {"functions": [
        _fn("Caller", "f.cs", "", None,
            [{"op": "acquire", "var": "f", "line": 1}, {"op": "release", "var": "f", "line": 1}],
            [_call(1, "Forwarding..ctor", "System.IO.MemoryStream",
                  [{"param": 0, "kind": "var", "name": "r"}],
                  form="initializer", call_kind="object_creation")]),
    ]}
    r = check_document(doc, "synthetic")
    _check("same-line-ineligible-call-excludes-not-missing",
          not r["covered"] and not r["missing"] and not r["ambiguous"], r)
    _check("ineligible-call-not-in-calls-without-release-either",
          not r["calls_without_release"], r)

    # --- live-source: the real sidecar-ctorinit-base fixture, per-file,
    # reproducing the exact collision above on real extractor output. ---
    try:
        path = ROOT / "corpus" / "p037-shapes" / "sidecar-ctorinit-base" / "case.cs"
        doc = _extract([path], "sidecar-ctorinit-base/case.cs")
        result = check_document(doc, "sidecar-ctorinit-base/case.cs")
        _check("live-sidecar-ctorinit-base-excludes-not-missing",
              not result["covered"] and not result["missing"] and not result["ambiguous"], result)
    except DerivationRefused as exc:
        _check("live-sidecar-ctorinit-base-excludes-not-missing", False, str(exc))

    # --- live-source integration: the four canonical guarded-consume fixtures,
    # measured PER FILE (never batched -- these share class names across
    # before.cs/after.cs with no namespace) ---
    live_ok = True
    live_detail = ""
    try:
        names = ("guarded-consume-flag-branch", "guarded-consume-early-return",
                "guarded-consume-negation-wrapper", "guarded-consume-wrapper-forward")
        live_covered = live_missing = live_ambiguous = 0
        for name in names:
            for side in ("before", "after"):
                path = ROOT / "corpus" / "p036-bakeoff" / name / f"{side}.cs"
                if not path.is_file():
                    continue
                doc = _extract([path], f"{name}/{side}.cs")
                result = check_document(doc, f"{name}/{side}.cs")
                live_covered += len(result["covered"])
                live_missing += len(result["missing"])
                live_ambiguous += len(result["ambiguous"])
        live_detail = f"covered={live_covered} missing={live_missing} ambiguous={live_ambiguous}"
        # flag-branch and early-return each have one chained call (Leak/Fine ->
        # Close): 1 covered site per file, 4 files, = 4. negation-wrapper and
        # wrapper-forward each chain TWO calls (Outer -> Inner, Leak/Fine ->
        # Outer): 2 covered sites per file, 4 files, = 8. Total 12 -- verified
        # directly against each file's own facts, not assumed.
        live_ok = live_covered == 12 and live_missing == 0 and live_ambiguous == 0
    except DerivationRefused as exc:
        live_ok = False
        live_detail = str(exc)
    _check("live-canonical-fixtures-12-covered-0-missing-0-ambiguous", live_ok, live_detail)

    # --- live-source: extension-receiver is excluded (Caller has no release,
    # only a use -- CallReleasesReceiver's own gap, out of this seam's scope) ---
    try:
        path = ROOT / "corpus" / "p037-shapes" / "extension-receiver" / "case.cs"
        doc = _extract([path], "extension-receiver/case.cs")
        result = check_document(doc, "extension-receiver/case.cs")
        _check("live-extension-receiver-contributes-nothing-to-verdict",
              not result["covered"] and not result["missing"] and not result["ambiguous"], result)
    except DerivationRefused as exc:
        _check("live-extension-receiver-contributes-nothing-to-verdict", False, str(exc))

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-delegation-closure selftest: all checks pass")
    return 0


# --------------------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    rep = check()
    print_report(rep)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
