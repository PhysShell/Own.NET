#!/usr/bin/env python3
"""Mutation campaign runner — replicable evidence for the P-022 discipline.

Rule 2 of the discipline: a test is evidence only once its mutation fails
through the production surface. Rule 3: no fail-fast — every catching layer
is recorded. This runner turns a campaign from a session's scratch script
into something the tree carries and anyone can replay:

* a **definition** (`docs/evidence/<campaign>.json`) lists the mutations —
  a regex that must match its target file exactly once, the replacement, the
  rule it attacks, and the tests expected to catch it;
* a **result** (`docs/evidence/<campaign>.result.json`) is raw facts only:
  per-mutation outcome, every catching test, elapsed time, and provenance
  (the commit the run was taken on, the sha256 of the definition it ran, the
  packages tested). Counts are derived by the renderer
  (`scripts/render_checkpoint_status.py`), so the campaign is interpreted
  once.

Each mutation is applied to a pristine copy of the file and restored from
memory (never `git checkout`), the tests of every workspace package run with
`--no-fail-fast`, and the outcome is one of:

    caught            at least one test failed
    survived          the mutated tree passed (a gap — or, for the control, the point)
    compile-error     the mutation did not compile: no evidence, never "caught"
    invalid-mutation  the pattern did not match exactly once, or the rewrite
                      left the file unchanged (a mutation that mutates nothing)
    runner-error      cargo failed without a parseable test failure

`M00` is the honesty control: the UNMUTATED tree must pass. If it does not,
the run is void and no result is written — a campaign that reports "caught"
over a red baseline has measured nothing.

A campaign is not a steady-state gate: it runs by hand, on a clean tree, and
the renderer shows its provenance beside its numbers.

Usage:
  python scripts/mutate_campaign.py --campaign docs/evidence/p022-cp4-mutations.json --validate
  python scripts/mutate_campaign.py --campaign docs/evidence/p022-cp4-mutations.json --run
      [--result PATH] [--allow-dirty]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = 1
OUTCOMES = ("caught", "survived", "compile-error", "invalid-mutation", "runner-error")
_RUNNING = re.compile(r"^\s+Running (?:unittests )?(\S+) \(\S+\)$")
_DOCTESTS = re.compile(r"^\s+Doc-tests (\S+)$")
_FAILED = re.compile(r"^test (.+?) \.\.\. FAILED$")


@dataclass(frozen=True)
class Mutation:
    id: str
    description: str
    target: str
    pattern: str
    replacement: str
    expected_catchers: tuple[str, ...]
    rule: str | None = None


@dataclass(frozen=True)
class Definition:
    campaign: str
    description: str
    workspace: str
    control_id: str
    control_description: str
    mutations: tuple[Mutation, ...]
    path: str
    sha256: str


@dataclass(frozen=True)
class Outcome:
    id: str
    outcome: str
    catchers: tuple[str, ...]
    elapsed_seconds: float
    detail: str = ""
    expected_catchers_hit: bool | None = None


@dataclass(frozen=True)
class Result:
    campaign: str
    definition_sha256: str
    source_commit: str
    dirty: bool
    recorded_at: str
    packages: tuple[str, ...]
    control: Outcome
    mutations: tuple[Outcome, ...]


@dataclass
class Summary:
    """The renderer's view of a campaign: counts derived from raw outcomes."""

    total: int = 0
    caught: int = 0
    survived: int = 0
    compile_error: int = 0
    invalid: int = 0
    runner_error: int = 0
    expected_catchers_missed: tuple[str, ...] = ()
    control_ok: bool = False
    definition_matches: bool = False
    dirty: bool = False
    source_commit: str = ""
    problems: tuple[str, ...] = ()


class CampaignError(Exception):
    pass


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _str(obj: dict[str, object], key: str, where: str) -> str:
    v = obj.get(key)
    if not isinstance(v, str) or not v:
        raise CampaignError(f"{where}: '{key}' must be a non-empty string")
    return v


def load_definition(path: str) -> Definition:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise CampaignError(f"{path}: not a JSON object")
    if data.get("schema") != SCHEMA:
        raise CampaignError(f"{path}: schema {data.get('schema')!r} != {SCHEMA}")
    control = data.get("control")
    if not isinstance(control, dict):
        raise CampaignError(f"{path}: 'control' must be an object")
    raw = data.get("mutations")
    if not isinstance(raw, list) or not raw:
        raise CampaignError(f"{path}: 'mutations' must be a non-empty array")
    mutations: list[Mutation] = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise CampaignError(f"{path}: mutations[{i}] is not an object")
        where = f"{path}: mutations[{i}]"
        mid = _str(m, "id", where)
        catchers = m.get("expected_catchers")
        if not (isinstance(catchers, list) and catchers
                and all(isinstance(c, str) and "::" in c for c in catchers)):
            raise CampaignError(f"{where} ({mid}): 'expected_catchers' must be a non-empty "
                                f"array of '<package>/<target>::<test>' strings")
        rule = m.get("rule")
        if rule is not None and not isinstance(rule, str):
            raise CampaignError(f"{where} ({mid}): 'rule' must be a string when present")
        mutations.append(Mutation(
            id=mid,
            description=_str(m, "description", where),
            target=_str(m, "target", where),
            pattern=_str(m, "pattern", where),
            replacement=str(m.get("replacement", "")),
            expected_catchers=tuple(str(c) for c in catchers),
            rule=rule,
        ))
    ids = [m.id for m in mutations]
    control_id = _str(control, "id", f"{path}: control")
    if len(set(ids)) != len(ids) or control_id in ids:
        raise CampaignError(f"{path}: mutation ids must be unique and distinct from the control")
    return Definition(
        campaign=_str(data, "campaign", path),
        description=_str(data, "description", path),
        workspace=_str(data, "workspace", path),
        control_id=control_id,
        control_description=_str(control, "description", f"{path}: control"),
        mutations=tuple(mutations),
        path=path,
        sha256=_sha256(path),
    )


def _outcome_from(obj: object, where: str) -> Outcome:
    if not isinstance(obj, dict):
        raise CampaignError(f"{where}: not an object")
    outcome = _str(obj, "outcome", where)
    if outcome not in OUTCOMES:
        raise CampaignError(f"{where}: unknown outcome {outcome!r}")
    catchers = obj.get("catchers", [])
    if not (isinstance(catchers, list) and all(isinstance(c, str) for c in catchers)):
        raise CampaignError(f"{where}: 'catchers' must be an array of strings")
    elapsed = obj.get("elapsed_seconds", 0.0)
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
        raise CampaignError(f"{where}: 'elapsed_seconds' must be a number")
    hit = obj.get("expected_catchers_hit")
    if hit is not None and not isinstance(hit, bool):
        raise CampaignError(f"{where}: 'expected_catchers_hit' must be a boolean when present")
    return Outcome(
        id=_str(obj, "id", where),
        outcome=outcome,
        catchers=tuple(str(c) for c in catchers),
        elapsed_seconds=float(elapsed),
        detail=str(obj.get("detail", "")),
        expected_catchers_hit=hit,
    )


def load_result(path: str) -> Result:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise CampaignError(f"{path}: not a JSON object")
    if data.get("schema") != SCHEMA:
        raise CampaignError(f"{path}: schema {data.get('schema')!r} != {SCHEMA}")
    raw = data.get("mutations")
    if not isinstance(raw, list):
        raise CampaignError(f"{path}: 'mutations' must be an array")
    packages = data.get("packages", [])
    if not (isinstance(packages, list) and all(isinstance(p, str) for p in packages)):
        raise CampaignError(f"{path}: 'packages' must be an array of strings")
    dirty = data.get("dirty", False)
    if not isinstance(dirty, bool):
        raise CampaignError(f"{path}: 'dirty' must be a boolean")
    return Result(
        campaign=_str(data, "campaign", path),
        definition_sha256=_str(data, "definition_sha256", path),
        source_commit=_str(data, "source_commit", path),
        dirty=dirty,
        recorded_at=_str(data, "recorded_at", path),
        packages=tuple(str(p) for p in packages),
        control=_outcome_from(data.get("control"), f"{path}: control"),
        mutations=tuple(_outcome_from(m, f"{path}: mutations[{i}]") for i, m in enumerate(raw)),
    )


def summarize(definition: Definition, result: Result) -> Summary:
    """Derive the counts a status surface may show — the one interpretation of
    a recorded run. Problems make the summary unusable as evidence."""
    s = Summary(
        total=len(definition.mutations),
        control_ok=(result.control.id == definition.control_id
                    and result.control.outcome == "survived"),
        definition_matches=(result.definition_sha256 == definition.sha256
                            and result.campaign == definition.campaign),
        dirty=result.dirty,
        source_commit=result.source_commit,
    )
    problems: list[str] = []
    if not s.definition_matches:
        problems.append("the recorded result was taken over a different campaign "
                        "definition (sha256 or campaign name differs) — re-run the campaign")
    if not s.control_ok:
        problems.append(f"the honesty control {definition.control_id} did not survive "
                        f"the unmutated tree — the run measured nothing")
    if result.dirty:
        problems.append("the result was recorded on a dirty tree — not evidence")
    recorded = {o.id: o for o in result.mutations}
    missing = [m.id for m in definition.mutations if m.id not in recorded]
    extra = [i for i in recorded if i not in {m.id for m in definition.mutations}]
    if missing or extra:
        problems.append(f"result/definition mutation sets differ (missing {missing}, "
                        f"unknown {extra})")
    missed: list[str] = []
    for m in definition.mutations:
        o = recorded.get(m.id)
        if o is None:
            continue
        if o.outcome == "caught":
            s.caught += 1
            if not set(m.expected_catchers) <= set(o.catchers):
                missed.append(m.id)
        elif o.outcome == "survived":
            s.survived += 1
        elif o.outcome == "compile-error":
            s.compile_error += 1
        elif o.outcome == "invalid-mutation":
            s.invalid += 1
        else:
            s.runner_error += 1
    s.expected_catchers_missed = tuple(missed)
    s.problems = tuple(problems)
    return s


# --- running ---------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def workspace_packages(workspace: str) -> list[str]:
    """Every workspace member, from cargo itself — never a typed list."""
    out = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=os.path.join(ROOT, workspace), check=True, capture_output=True, text=True,
    ).stdout
    meta = json.loads(out)
    members = {str(m) for m in meta.get("workspace_members", [])}
    names = [str(p["name"]) for p in meta.get("packages", []) if str(p.get("id")) in members]
    if not names:
        raise CampaignError(f"cargo metadata lists no workspace members under {workspace}")
    return sorted(names)


def parse_test_output(package: str, out: str) -> tuple[list[str], bool]:
    """(catching test ids, compile error seen) from cargo's merged output."""
    catchers: list[str] = []
    target = "?"
    for line in out.splitlines():
        m = _RUNNING.match(line)
        if m:
            target = m.group(1)
            continue
        m = _DOCTESTS.match(line)
        if m:
            target = "doc"
            continue
        m = _FAILED.match(line)
        if m:
            catchers.append(f"{package}/{target}::{m.group(1)}")
    compile_error = ("could not compile" in out) or bool(re.search(r"^error\[E\d+\]", out, re.M))
    return catchers, compile_error


def run_tests(workspace: str, packages: list[str]) -> tuple[list[str], bool, list[str]]:
    """Run every package's tests, no fail-fast, streams merged so `Running`
    headers (stderr) and results (stdout) keep their interleaving.
    Returns (catchers, compile error seen, unparsed failures)."""
    catchers: list[str] = []
    compile_error = False
    unparsed: list[str] = []
    for pkg in packages:
        r = subprocess.run(["cargo", "test", "-p", pkg, "--no-fail-fast"],
                           cwd=os.path.join(ROOT, workspace),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        found, ce = parse_test_output(pkg, r.stdout)
        catchers.extend(found)
        compile_error = compile_error or ce
        if r.returncode != 0 and not found and not ce:
            unparsed.append(f"{pkg}: cargo test exited {r.returncode} without a parseable "
                            f"failure:\n" + "\n".join(r.stdout.splitlines()[-15:]))
    return catchers, compile_error, unparsed


def apply(m: Mutation, pristine: str) -> tuple[str, str | None]:
    """(mutated text, problem) — the pattern must match exactly once and change something."""
    try:
        new, n = re.subn(m.pattern, m.replacement, pristine)
    except re.error as e:
        return pristine, f"pattern does not compile: {e}"
    if n != 1:
        return pristine, f"pattern matched {n} times (must be exactly 1)"
    if new == pristine:
        return pristine, "rewrite leaves the file unchanged (not a mutation)"
    return new, None


def validate(definition: Definition) -> list[str]:
    problems: list[str] = []
    for m in definition.mutations:
        path = os.path.join(ROOT, m.target)
        if not os.path.isfile(path):
            problems.append(f"{m.id}: target does not exist: {m.target}")
            continue
        with open(path, encoding="utf-8") as f:
            pristine = f.read()
        _, problem = apply(m, pristine)
        if problem:
            problems.append(f"{m.id}: {problem}")
    return problems


def _classify(catchers: list[str], compile_error: bool, unparsed: list[str]) -> tuple[str, str]:
    if compile_error:
        return "compile-error", ""
    if catchers:
        return "caught", ""
    if unparsed:
        return "runner-error", "\n".join(unparsed)
    return "survived", ""


def run_campaign(definition: Definition, allow_dirty: bool) -> Result:
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    if dirty and not allow_dirty:
        raise CampaignError("the tree has uncommitted changes to tracked files; a result must "
                            "name the commit it describes (commit first, or --allow-dirty "
                            "for a dev run whose result is NOT evidence)")
    commit = _git("rev-parse", "HEAD")
    packages = workspace_packages(definition.workspace)
    targets = sorted({m.target for m in definition.mutations})
    pristine: dict[str, str] = {}
    for t in targets:
        with open(os.path.join(ROOT, t), encoding="utf-8") as f:
            pristine[t] = f.read()

    def restore() -> None:
        for t, text in pristine.items():
            with open(os.path.join(ROOT, t), "w", encoding="utf-8") as f:
                f.write(text)

    print(f"{definition.control_id}: {definition.control_description}", flush=True)
    t0 = time.monotonic()
    catchers, ce, unparsed = run_tests(definition.workspace, packages)
    outcome, detail = _classify(catchers, ce, unparsed)
    control = Outcome(definition.control_id, outcome, tuple(catchers),
                      round(time.monotonic() - t0, 1), detail)
    print(f"  -> {outcome} ({len(catchers)} failing test(s))", flush=True)
    if outcome != "survived":
        raise CampaignError(f"the unmutated tree did not pass ({outcome}): the run is void")

    outcomes: list[Outcome] = []
    try:
        for m in definition.mutations:
            print(f"{m.id}: {m.description}", flush=True)
            mutated, problem = apply(m, pristine[m.target])
            if problem:
                outcomes.append(Outcome(m.id, "invalid-mutation", (), 0.0, problem, None))
                print(f"  -> invalid-mutation: {problem}", flush=True)
                continue
            with open(os.path.join(ROOT, m.target), "w", encoding="utf-8") as f:
                f.write(mutated)
            t0 = time.monotonic()
            try:
                catchers, ce, unparsed = run_tests(definition.workspace, packages)
            finally:
                restore()
            outcome, detail = _classify(catchers, ce, unparsed)
            hit = set(m.expected_catchers) <= set(catchers) if outcome == "caught" else None
            outcomes.append(Outcome(m.id, outcome, tuple(sorted(catchers)),
                                    round(time.monotonic() - t0, 1), detail, hit))
            expected = "" if hit is None else (
                ", expected catchers " + ("hit" if hit else "MISSED"))
            print(f"  -> {outcome} ({len(catchers)} test(s){expected})", flush=True)
            for c in sorted(catchers):
                print(f"       {c}", flush=True)
    finally:
        restore()
    for t, text in pristine.items():
        with open(os.path.join(ROOT, t), encoding="utf-8") as f:
            if f.read() != text:
                raise CampaignError(f"{t} was not restored to its pristine content")
    return Result(
        campaign=definition.campaign,
        definition_sha256=definition.sha256,
        source_commit=commit + ("-dirty" if dirty else ""),
        dirty=dirty,
        recorded_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        packages=tuple(packages),
        control=control,
        mutations=tuple(outcomes),
    )


def _outcome_json(o: Outcome) -> dict[str, object]:
    d: dict[str, object] = {
        "id": o.id, "outcome": o.outcome, "catchers": list(o.catchers),
        "elapsed_seconds": round(o.elapsed_seconds, 1),
    }
    if o.expected_catchers_hit is not None:
        d["expected_catchers_hit"] = o.expected_catchers_hit
    if o.detail:
        d["detail"] = o.detail
    return d


def write_result(result: Result, definition: Definition, path: str) -> None:
    doc: dict[str, object] = {
        "schema": SCHEMA,
        "comment": ("Recorded mutation-campaign run (scripts/mutate_campaign.py --run). Raw "
                    "facts only: outcomes, catchers, provenance. Counts are derived by "
                    "scripts/render_checkpoint_status.py; regenerate this file by re-running "
                    "the campaign, never by hand."),
        "campaign": result.campaign,
        "definition": os.path.relpath(definition.path, ROOT).replace(os.sep, "/"),
        "definition_sha256": result.definition_sha256,
        "source_commit": result.source_commit,
        "dirty": result.dirty,
        "recorded_at": result.recorded_at,
        "packages": list(result.packages),
        "command": "cargo test -p <package> --no-fail-fast, for every workspace member",
        "control": _outcome_json(result.control),
        "mutations": [_outcome_json(o) for o in result.mutations],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", required=True, help="campaign definition JSON")
    ap.add_argument("--validate", action="store_true",
                    help="check every mutation applies exactly once to the current tree")
    ap.add_argument("--run", action="store_true", help="run the campaign and record the result")
    ap.add_argument("--result", help="result path (default: <campaign>.result.json)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="dev run on a dirty tree; the result is marked and is not evidence")
    args = ap.parse_args(argv)
    try:
        definition = load_definition(args.campaign)
        problems = validate(definition)
        for p in problems:
            print(f"INVALID: {p}")
        if problems:
            return 1
        print(f"campaign {definition.campaign}: {len(definition.mutations)} mutations apply "
              f"exactly once each (sha256 {definition.sha256[:12]})")
        if not args.run:
            return 0
        result = run_campaign(definition, args.allow_dirty)
    except CampaignError as e:
        print(f"ERROR: {e}")
        return 1
    out = args.result or (args.campaign[:-5] + ".result.json"
                          if args.campaign.endswith(".json") else args.campaign + ".result.json")
    write_result(result, definition, out)
    s = summarize(definition, result)
    print(f"\n{definition.campaign} @ {result.source_commit[:12]}: {s.caught}/{s.total} caught, "
          f"{s.survived} survived, {s.compile_error} compile-error, {s.invalid} invalid, "
          f"{s.runner_error} runner-error; expected catchers missed: "
          f"{list(s.expected_catchers_missed) or 'none'}")
    print(f"wrote {out}")
    return 0 if not s.problems else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
