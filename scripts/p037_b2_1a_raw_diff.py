#!/usr/bin/env python3
"""P-037 B2.1a governed raw-fact evidence: the before/after diff
`first_semantic_hypothesis.facts_expectation.verified_by` (docs/evidence/
p037-b-epoch.json) requires, plus the narrow, CI-facing transitional gate
`ci_transition_plan.b2_1a_gate` preregisters.

B2.1a's only authorized change is EmitFlowExpr degrading a legacy
ConsumeReleaseArgs/ConsumesParam-fabricated `release(var, line)` into
`use(var, the SAME line)`, uniformly and unconditionally, for every such
call site in the FULL frozen population -- never a sample. This module
proves that is the ONLY thing that moved, two ways:

* `snapshot`/`diff`: a one-time, full-population (real-world, wpf, di,
  fixtures, p036-bakeoff, p037-shapes, repo-tree -- the same 193 documents
  scripts/p037_delegation_closure.py's own population_documents() walks,
  never batched: several p036-bakeoff fixtures share unnamespaced
  top-level class names, and batching them corrupts Roslyn symbol
  resolution) before/after raw-facts comparison. Every leaf difference is
  classified as either the one AUTHORIZED shape (an op's `op` field
  flipping release->use, same `var`, same `line`, nothing else on the op
  different) or a VIOLATION naming exactly which `never` rule it breaks --
  never silently accepted, never repaired around.
* `gate`: fast, wired into CI, no historical snapshot needed. Asserts the
  raw-fact contract holds RIGHT NOW for the eight fixtures
  ci_transition_plan.b2_1a_gate names (the four F3-S* canonical-family
  before/after pairs, corpus/p036-bakeoff/guarded-consume-*, plus the four
  G-V4/legacy-honesty corpus/p036-bakeoff controls already governed by
  scripts/p037_controls.py's own expected.json): the named call site no
  longer carries a fabricated release, and the caller method is still
  admitted to functions[] (tracking survived). This is deliberately
  narrower than "the verdict is fully A1-correct" (checkable
  independently, per the epoch record) -- it does NOT read or touch
  corpus/p036-bakeoff/*/expected.json's own current/post_a1 layers, and it
  does NOT edit scripts/p037_controls.py.

Non-goals, explicitly: no Rust production change, no guard-aware
reasoning, no repair of anything this module finds. A VIOLATION is
reported and the run exits non-zero; it is never patched around here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import p037_evidence_b as evb  # noqa: E402

CORPUS_DIRS: tuple[str, ...] = evb.CORPUS_DIRS
REPO_TREE_DIRS: tuple[str, ...] = evb.REPO_TREE_DIRS

SCHEMA = "p037-b2-1a-raw-diff/1"

# The eight fixtures ci_transition_plan.b2_1a_gate names. The four F3-S*
# pairs have no expected.json (they are before/after transform pairs, not
# single-verdict controls) so their call-site line/var/caller identity is
# recorded here, read directly from the committed .cs source (verified by
# hand against the actual file text, not guessed): each is one call, at
# the local `s`, inside the file's own `Leak`/`Fine` method, to a
# first-party consumer the flow-insensitive ConsumeReleaseArgs/
# ConsumesParam check already recognizes today. The four G-V4/legacy-
# honesty controls DO have expected.json (governed by
# scripts/p037_controls.py); this table still names them, reusing their
# own recorded `call_site_line` rather than a second hardcoded copy, so
# there is exactly one place either number can drift from the source.
GATE_FIXTURES: tuple[dict[str, Any], ...] = (
    {"file": "corpus/p036-bakeoff/guarded-consume-early-return/before.cs",
     "caller": "GuardedEarlyReturn.Leak", "var": "s", "line": 19},
    {"file": "corpus/p036-bakeoff/guarded-consume-early-return/after.cs",
     "caller": "GuardedEarlyReturn.Fine", "var": "s", "line": 19},
    {"file": "corpus/p036-bakeoff/guarded-consume-flag-branch/before.cs",
     "caller": "Guarded.Leak", "var": "s", "line": 26},
    {"file": "corpus/p036-bakeoff/guarded-consume-flag-branch/after.cs",
     "caller": "Guarded.Fine", "var": "s", "line": 21},
    {"file": "corpus/p036-bakeoff/guarded-consume-negation-wrapper/before.cs",
     "caller": "GuardedNegation.Leak", "var": "s", "line": 25},
    {"file": "corpus/p036-bakeoff/guarded-consume-negation-wrapper/after.cs",
     "caller": "GuardedNegation.Fine", "var": "s", "line": 25},
    {"file": "corpus/p036-bakeoff/guarded-consume-wrapper-forward/before.cs",
     "caller": "GuardedWrapper.Leak", "var": "s", "line": 26},
    {"file": "corpus/p036-bakeoff/guarded-consume-wrapper-forward/after.cs",
     "caller": "GuardedWrapper.Fine", "var": "s", "line": 25},
)
GATE_CONTROLS: tuple[str, ...] = (
    "gv4-control-aliased-self-null",
    "gv4-control-mutated-guard",
    "gv4-control-ref-alias-guard",
    "legacy-honesty-else-unresolved-forward",
)


class Refused(RuntimeError):
    """The population, an extraction, or a comparison is off-contract."""


# --------------------------------------------------------------------------- population


def population_documents(*, repo: Path = ROOT) -> list[tuple[str, list[Path]]]:
    """[(doc_id, paths)] -- one entry per corpus file, NEVER batched, plus one
    for the whole repo tree. Exactly scripts/p037_delegation_closure.py's own
    population_documents(): duplicated here deliberately rather than imported,
    matching this codebase's existing pattern of each control tool walking
    CORPUS_DIRS/REPO_TREE_DIRS independently (scripts/p037_mos_snapshot.py
    has its own source_documents() split the same way) -- never sharing a
    private helper across sibling control scripts."""
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


def extract(paths: list[Path], doc_id: str, *, repo: Path = ROOT) -> dict[str, Any]:
    """One extractor execution, `--engine python` (facts are engine-independent
    -- own-check.sh's own docs: `--emit-facts` copies what the extractor
    produced, before either engine runs -- so this needs no built Rust
    candidate)."""
    if not paths:
        raise Refused(f"{doc_id}: zero source files")
    with tempfile.TemporaryDirectory(prefix="p037-b2-1a-raw-diff-") as td:
        facts = Path(td) / "facts.json"
        cmd = [
            "bash", str(repo / "scripts" / "own-check.sh"),
            "--engine", "python", "--format", "human", "--severity", "warning",
            "--emit-facts", str(facts),
            "--", *(str(p) for p in paths),
        ]
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):
            raise Refused(f"{doc_id}: extractor/launcher failed, exit {proc.returncode}\n"
                          f"{proc.stderr[-2000:]}")
        try:
            result: dict[str, Any] = json.loads(facts.read_text(encoding="utf-8"))
            return result
        except OSError as exc:
            raise Refused(f"{doc_id}: no emitted facts: {exc}") from exc


def snapshot(*, jobs: int, repo: Path = ROOT) -> dict[str, Any]:
    """{doc_id: facts} for the full population, extracted with `jobs`-way
    concurrency (independent subprocesses; never batching several corpus
    files into ONE own-check.sh call -- that is the correctness rule
    concurrency must not touch, and does not: each parallel call still
    covers exactly one population_documents() entry)."""
    docs = population_documents(repo=repo)
    out: dict[str, Any] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(extract, paths, doc_id, repo=repo): doc_id
                  for doc_id, paths in docs}
        done = 0
        for fut in as_completed(futures):
            doc_id = futures[fut]
            done += 1
            try:
                out[doc_id] = fut.result()
            except Refused as exc:
                errors.append(str(exc))
            print(f"  [{done:3}/{len(docs)}] {doc_id}", file=sys.stderr)
    if errors:
        raise Refused("extraction failures:\n" + "\n".join(errors))
    if set(out) != {doc_id for doc_id, _ in docs}:
        raise Refused("population mismatch between requested and extracted documents")
    return out


# --------------------------------------------------------------------------- classification


def _fn_identity(fn: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (fn.get("file"), fn.get("name"), fn.get("sig"))


def _classify_body(before: list[Any], after: list[Any]) -> tuple[int, list[str]]:
    """(authorized_count, violations) for one function's op list. The only
    authorized shape: same length, and at every differing position the op's
    `op` field alone flips release->use with `var`/`line` (and every other
    key) unchanged -- never a reordering, insertion, or deletion, since
    B2.1a relabels an existing node in place and never adds or removes one."""
    if len(before) != len(after):
        return 0, [f"body length changed: {len(before)} ops -> {len(after)} ops "
                   f"(a release disappeared or an op was added/removed, "
                   f"not degraded in place)"]
    authorized = 0
    violations: list[str] = []
    for i, (b, a) in enumerate(zip(before, after, strict=True)):
        if b == a:
            continue
        b_rest = {k: v for k, v in b.items() if k != "op"}
        a_rest = {k: v for k, v in a.items() if k != "op"}
        if b.get("op") == "release" and a.get("op") == "use" and b_rest == a_rest:
            authorized += 1
            continue
        violations.append(f"op[{i}] changed outside the authorized shape: {b} -> {a}")
    return authorized, violations


def classify(before: dict[str, Any], after: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """One document's before/after facts -> {authorized, violations,
    admission_ok}. `violations` entries name the specific `never` rule each
    one breaks; an empty list is the only passing outcome for this document."""
    violations: list[str] = []
    authorized = 0

    def fn_map(doc: dict[str, Any], key: str) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
        return {_fn_identity(fn): fn for fn in doc.get(key, [])}

    for key, has_body in (("functions", True), ("guarded_functions", False)):
        before_map = fn_map(before, key)
        after_map = fn_map(after, key)
        if set(before_map) != set(after_map):
            missing = set(before_map) - set(after_map)
            extra = set(after_map) - set(before_map)
            violations.append(
                f"{doc_id}: {key}[] admission changed -- missing={sorted(map(str, missing))} "
                f"extra={sorted(map(str, extra))}")
            continue
        for ident, before_fn in before_map.items():
            after_fn = after_map[ident]
            if not has_body:
                if before_fn != after_fn:
                    violations.append(f"{doc_id}: {key}[] entry {ident} changed: "
                                      f"{before_fn} -> {after_fn}")
                continue
            before_rest = {k: v for k, v in before_fn.items() if k != "body"}
            after_rest = {k: v for k, v in after_fn.items() if k != "body"}
            if before_rest != after_rest:
                violations.append(f"{doc_id}: {key}[] entry {ident} changed outside body "
                                  f"(guarded_facts/params/sig/etc.): {before_rest} -> {after_rest}")
            n_auth, body_violations = _classify_body(
                before_fn.get("body", []), after_fn.get("body", []))
            authorized += n_auth
            violations.extend(f"{doc_id}: {key}[] entry {ident}: {v}" for v in body_violations)

    _skip = ("functions", "guarded_functions")
    before_remainder = {k: v for k, v in before.items() if k not in _skip}
    after_remainder = {k: v for k, v in after.items() if k not in _skip}
    if before_remainder != after_remainder:
        violations.append(f"{doc_id}: document fields outside functions[]/guarded_functions[] "
                          f"changed (components/services/effects/protocols/stats/etc.): "
                          f"{before_remainder} -> {after_remainder}")

    return {"authorized": authorized, "violations": violations}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """The full-population report: per-document classification plus totals."""
    if set(before) != set(after):
        raise Refused(f"snapshot population mismatch: before={sorted(before)} "
                      f"after={sorted(after)}")
    per_doc: dict[str, Any] = {}
    total_authorized = 0
    total_violations = 0
    changed_files = 0
    for doc_id in sorted(before):
        result = classify(before[doc_id], after[doc_id], doc_id)
        per_doc[doc_id] = result
        total_authorized += result["authorized"]
        total_violations += len(result["violations"])
        if result["authorized"] or result["violations"]:
            changed_files += 1
    return {
        "schema": SCHEMA,
        "documents_compared": len(before),
        "changed_files": changed_files,
        "authorized_movements": total_authorized,
        "violations": total_violations,
        "clean": total_violations == 0,
        "per_document": per_doc,
    }


# --------------------------------------------------------------------------- gate


def _release_lines(facts: dict[str, Any]) -> set[int]:
    out: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("op") == "release" and isinstance(node.get("line"), int):
                out.add(int(node["line"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(facts)
    return out


def _fn_present(facts: dict[str, Any], name: str) -> bool:
    return any(fn.get("name") == name for fn in facts.get("functions", []))


def gate(*, repo: Path = ROOT) -> tuple[bool, list[str]]:
    """The narrow, CI-facing transitional control: at the CURRENT checkout
    (no historical snapshot needed), for each of the eight named fixtures,
    the call site no longer fabricates a release AND the caller is still
    admitted to functions[] (tracking survived the cut). Deliberately does
    not read or assert anything about corpus/p036-bakeoff/*/expected.json's
    own current/post_a1 layers -- that is scripts/p037_controls.py's
    question, checkable independently, and this control must never edit or
    duplicate it."""
    lines: list[str] = []
    all_ok = True
    for spec in GATE_FIXTURES:
        facts = extract([repo / spec["file"]], spec["file"], repo=repo)
        fabricated = spec["line"] in _release_lines(facts)
        present = _fn_present(facts, spec["caller"])
        ok = not fabricated and present
        all_ok &= ok
        lines.append(f"{'ok' if ok else 'MISMATCH':8} {spec['file']:58} "
                     f"fabricated={fabricated} (want False)  "
                     f"{spec['caller']} admitted={present} (want True)")
    for name in GATE_CONTROLS:
        control_dir = ROOT / "corpus" / "p036-bakeoff" / name
        spec_doc = json.loads((control_dir / "expected.json").read_text(encoding="utf-8"))
        call_site_line = int(spec_doc["call_site_line"])
        facts = extract([control_dir / "control.cs"], name, repo=repo)
        fabricated = call_site_line in _release_lines(facts)
        ok = not fabricated
        all_ok &= ok
        lines.append(f"{'ok' if ok else 'MISMATCH':8} {name:58} "
                     f"fabricated at line {call_site_line}={fabricated} (want False)")
    return all_ok, lines


# --------------------------------------------------------------------------- selftest

_failures = 0


def _check(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def _doc(fns: list[dict[str, Any]], **rest: Any) -> dict[str, Any]:
    return {"functions": fns, "services": [], **rest}


def _fn(name: str, body: list[dict[str, Any]], guarded_facts: dict[str, Any] | None = None,
       file: str = "f.cs", sig: str = "T") -> dict[str, Any]:
    out: dict[str, Any] = {"file": file, "name": name, "sig": sig, "body": body}
    if guarded_facts is not None:
        out["guarded_facts"] = guarded_facts
    return out


def selftest() -> int:
    """Synthetic before/after fact pairs proving classify()/diff() accept only
    the exact authorized shape and refuse everything else -- proven against
    fabricated dicts, the same discipline p037_b_classifier.py's own synthetic
    witnesses used before ever touching a real document."""
    rel = {"op": "release", "var": "s", "line": 19}
    use = {"op": "use", "var": "s", "line": 19}
    acquire = {"op": "acquire", "var": "s", "line": 17, "column": 13, "kind": "disposable"}

    # authorized: one release -> use, same var/line, nothing else on the op.
    before = _doc([_fn("M.Leak", [acquire, rel])])
    after = _doc([_fn("M.Leak", [acquire, use])])
    result = classify(before, after, "doc")
    _check("authorized-release-to-use-is-accepted",
          result["authorized"] == 1 and not result["violations"], result)

    # violation: the release just disappears (length shrinks) instead of degrading.
    before = _doc([_fn("M.Leak", [acquire, rel])])
    after = _doc([_fn("M.Leak", [acquire])])
    result = classify(before, after, "doc")
    _check("release-disappearing-outright-is-refused",
          result["authorized"] == 0 and len(result["violations"]) == 1
          and "length changed" in result["violations"][0], result)

    # violation: same length, but the flipped op carries an EXTRA/different field
    # too (not a pure op-label relabel) -- must not be waved through as authorized.
    before = _doc([_fn("M.Leak", [acquire, rel])])
    sneaky_use = {"op": "use", "var": "s", "line": 19, "column": 5}
    after = _doc([_fn("M.Leak", [acquire, sneaky_use])])
    result = classify(before, after, "doc")
    _check("release-to-use-with-an-extra-field-is-refused",
          result["authorized"] == 0 and len(result["violations"]) == 1, result)

    # violation: an unrelated op (acquire) changes -- never authorized, whatever it is.
    before = _doc([_fn("M.Leak", [acquire, rel])])
    moved_acquire = {**acquire, "line": 18}
    after = _doc([_fn("M.Leak", [moved_acquire, use])])
    result = classify(before, after, "doc")
    _check("an-unrelated-op-changing-is-refused",
          result["authorized"] == 1 and len(result["violations"]) == 1, result)

    # violation: functions[] admission changes (a method vanishes).
    before = _doc([_fn("M.Leak", [acquire, rel]), _fn("M.Other", [])])
    after = _doc([_fn("M.Leak", [acquire, use])])
    result = classify(before, after, "doc")
    _check("functions-admission-change-is-refused",
          len(result["violations"]) == 1 and "admission changed" in result["violations"][0],
          result)

    # violation: guarded_facts (a non-body field) changes alongside a legitimate flip.
    gf1 = {"version": 1, "calls": [], "guards": []}
    gf2 = {"version": 1, "calls": [{"site": {"line": 1, "column": 1}}], "guards": []}
    before = _doc([_fn("M.Leak", [acquire, rel], guarded_facts=gf1)])
    after = _doc([_fn("M.Leak", [acquire, use], guarded_facts=gf2)])
    result = classify(before, after, "doc")
    _check("guarded-facts-change-is-refused",
          any("outside body" in v for v in result["violations"]), result)

    # violation: guarded_functions[] entry content changes (no body to inspect at all).
    orphan1 = {"file": "f.cs", "name": "M.Orphan", "sig": "T", "guarded_facts": gf1}
    orphan2 = {"file": "f.cs", "name": "M.Orphan", "sig": "T", "guarded_facts": gf2}
    before = _doc([_fn("M.Leak", [acquire, rel])], guarded_functions=[orphan1])
    after = _doc([_fn("M.Leak", [acquire, use])], guarded_functions=[orphan2])
    result = classify(before, after, "doc")
    _check("guarded-functions-entry-change-is-refused",
          any("guarded_functions[]" in v for v in result["violations"]), result)

    # violation: a document-level field outside functions[]/guarded_functions[] changes.
    before = _doc([_fn("M.Leak", [acquire, rel])], services=[{"name": "Svc"}])
    after = _doc([_fn("M.Leak", [acquire, use])], services=[])
    result = classify(before, after, "doc")
    _check("document-level-remainder-change-is-refused",
          any("outside functions" in v for v in result["violations"]), result)

    # the real, current head's own gate must pass cleanly against a live checkout
    # only when actually run (needs the extractor) -- not exercised here; `gate`
    # and `snapshot`/`diff` end-to-end correctness is proven by the governed run
    # itself, per this module's own docstring, not by this fast synthetic pass.

    print(f"RESULT: p037-b2-1a-raw-diff selftest: "
         f"{'all checks pass' if _failures == 0 else f'{_failures} FAILURE(S)'}")
    return 0 if _failures == 0 else 1


# --------------------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="extract raw facts for the full frozen population")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--jobs", type=int, default=8)

    p = sub.add_parser("diff", help="classify a before/after snapshot pair")
    p.add_argument("--before", required=True, type=Path)
    p.add_argument("--after", required=True, type=Path)
    p.add_argument("--report", type=Path, default=None)

    sub.add_parser("gate", help="fast CI check: the 8 named fixtures' raw-fact contract, now")
    sub.add_parser("selftest", help="pure, synthetic classifier self-check (no extractor needed)")

    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()

    if args.cmd == "snapshot":
        try:
            snap = snapshot(jobs=args.jobs)
        except Refused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        args.out.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {args.out} ({len(snap)} document(s))")
        return 0

    if args.cmd == "diff":
        try:
            before = json.loads(args.before.read_text(encoding="utf-8"))
            after = json.loads(args.after.read_text(encoding="utf-8"))
            report = diff(before, after)
        except Refused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        if args.report:
            args.report.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
        print(f"documents_compared={report['documents_compared']} "
             f"changed_files={report['changed_files']} "
             f"authorized_movements={report['authorized_movements']} "
             f"violations={report['violations']}")
        if not report["clean"]:
            for _doc_id, result in sorted(report["per_document"].items()):
                for v in result["violations"]:
                    print(f"VIOLATION: {v}", file=sys.stderr)
        print("RESULT:", "clean -- only the authorized release->use shape moved"
             if report["clean"] else "VIOLATIONS FOUND -- see above, not repaired here")
        return 0 if report["clean"] else 1

    ok, lines = gate()
    for line in lines:
        print(line)
    print("RESULT:", "all 8 fixtures show the post-B2.1a raw-fact contract"
         if ok else "mismatch — the B2.1a raw-fact contract does not hold")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
