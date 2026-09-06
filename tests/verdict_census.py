#!/usr/bin/env python3
"""The Layer 3 verdict ledger, interpreted once (P-022 #259 checkpoint 4).

`tests/fixtures/verdicts/manifest.json` plus the `<case>.verdicts.json`
goldens are checkpoint 4's evidence. This module is the ONE place that reads
them into a case plan and a census, so the fixture harness
(`tests/test_verdict_fixtures.py`) and the checkpoint status renderer
(`scripts/render_checkpoint_status.py`) cannot disagree about what the tree
contains: every cp4 number a status surface shows is computed here from the
tree, never typed into a document (P-022's status-drift rule, written for
exactly the stale census this replaces).

Pure: no `ownlang` import and no side effects — the harness projects facts
through `ownlang.verdicts` itself and compares; this module only reads what
is committed. Held to `mypy --strict` (see `files` in pyproject.toml).

* `plan()` — the case plan: the swept corpora (discovered, never listed), the
  synthetic cases (listed exhaustively in the manifest), the Rust exclusion
  ledger, and every ledger problem found on the way (a duplicate name, a
  facts file without a manifest entry, an exclusion naming a phantom case).
* `compute_verdict_census()` — the counts: goldens by origin, Python's
  refusals and findings over all of them, the exclusions grouped by the
  ledger's own executable expectation, and the replayed set's refusals and
  findings. It refuses (`CensusError`) rather than count over a plan with
  problems, a missing or orphaned golden, or a malformed one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
FIXDIR = os.path.join(HERE, "fixtures", "verdicts")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
# The swept corpora, in a fixed order (a name collision across them is a
# ledger problem, not a silent shadowing).
CORPORA: tuple[tuple[str, str], ...] = (
    ("ownir", os.path.join(HERE, "fixtures", "ownir")),
    ("lowered", os.path.join(HERE, "fixtures", "lowered")),
    ("summaries", os.path.join(HERE, "fixtures", "summaries")),
)
SYNTHETIC = "synthetic"
REFUSALS = ("bridge", "door")
FACTS_SUFFIX = ".facts.json"
GOLDEN_SUFFIX = ".verdicts.json"


@dataclass(frozen=True)
class Exclusion:
    """One `rust_replay_excluded` entry: a case whose golden is Python's truth
    but which the Rust core refuses by a declared boundary, with the
    executable expectation the Rust replay asserts."""

    name: str
    reason: str
    rust_refusal: str
    rust_error_contains: str | None

    @property
    def expectation(self) -> tuple[str, str | None]:
        """The ledger's own key for this exclusion — what the replay executes."""
        return (self.rust_refusal, self.rust_error_contains)


@dataclass(frozen=True)
class Manifest:
    verdicts_version: int | None
    synthetic: tuple[str, ...]
    excluded: dict[str, Exclusion]
    problems: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """name -> facts path, name -> origin (a corpus label or `synthetic`), the
    exclusion ledger, the manifest's surface version, and the ledger problems."""

    cases: dict[str, str]
    origin: dict[str, str]
    excluded: dict[str, Exclusion]
    verdicts_version: int | None
    problems: tuple[str, ...]


def read_manifest(path: str = MANIFEST) -> Manifest:
    problems: list[str] = []
    if not os.path.exists(path):
        return Manifest(None, (), {}, (f"manifest missing: {path}",))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return Manifest(None, (), {}, (f"manifest is not a JSON object: {path}",))
    raw_version = data.get("verdicts_version")
    version: int | None = None
    if isinstance(raw_version, int) and not isinstance(raw_version, bool):
        version = raw_version
    if version is None:
        problems.append(f"manifest verdicts_version must be an integer, got {raw_version!r}")
    excluded: dict[str, Exclusion] = {}
    raw_excluded = data.get("rust_replay_excluded", [])
    if not isinstance(raw_excluded, list):
        problems.append("manifest rust_replay_excluded must be an array")
        raw_excluded = []
    for e in raw_excluded:
        if not isinstance(e, dict):
            problems.append(f"rust_replay_excluded entry must be an object: {e!r}")
            continue
        name, reason, refusal = e.get("name"), e.get("reason"), e.get("rust_refusal")
        if not (isinstance(name, str) and name and isinstance(reason, str) and reason):
            problems.append(f"rust_replay_excluded entry needs a non-empty name "
                            f"and reason: {e!r}")
            continue
        if not (isinstance(refusal, str) and refusal in REFUSALS):
            problems.append(f"rust_replay_excluded '{name}': rust_refusal must be "
                            f"one of {REFUSALS}, got {refusal!r}")
            refusal = str(refusal)
        contains = e.get("rust_error_contains")
        if contains is not None and not (isinstance(contains, str) and contains):
            problems.append(f"rust_replay_excluded '{name}': rust_error_contains "
                            f"must be a non-empty string when present")
            contains = None
        if name in excluded:
            problems.append(f"rust_replay_excluded lists '{name}' twice")
        excluded[name] = Exclusion(name, reason, refusal, contains)
    names: list[str] = []
    raw_cases = data.get("cases", [])
    if not isinstance(raw_cases, list):
        problems.append("manifest cases must be an array")
        raw_cases = []
    for c in raw_cases:
        if not isinstance(c, dict):
            problems.append(f"manifest case must be an object: {c!r}")
            continue
        name = c.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"manifest case without a name: {c!r}")
            continue
        rules = c.get("rules")
        if not (isinstance(rules, list) and rules
                and all(isinstance(r, str) and r for r in rules)):
            problems.append(f"manifest case '{name}': 'rules' must be a "
                            f"non-empty array of non-empty strings")
        names.append(name)
    if len(set(names)) != len(names):
        problems.append("manifest contains duplicate case names")
    return Manifest(version, tuple(sorted(names)), excluded, tuple(problems))


def disk_cases(directory: str, suffix: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(n[:-len(suffix)] for n in os.listdir(directory) if n.endswith(suffix))


def plan(manifest_path: str = MANIFEST, fixdir: str = FIXDIR,
         corpora: tuple[tuple[str, str], ...] = CORPORA) -> Plan:
    """The full case plan. The corpora are swept automatically; the synthetic
    cases must match the manifest exactly; names must be unique across all
    sources (one golden tree serves them all); every exclusion must name a
    planned case."""
    manifest = read_manifest(manifest_path)
    problems = list(manifest.problems)
    cases: dict[str, str] = {}
    origin: dict[str, str] = {}
    for label, directory in corpora:
        for name in disk_cases(directory, FACTS_SUFFIX):
            if name in cases:
                problems.append(f"case name '{name}' exists in BOTH the "
                                f"{origin[name]} and {label} corpora — names must "
                                f"be unique across the swept corpora")
                continue
            cases[name] = os.path.join(directory, f"{name}{FACTS_SUFFIX}")
            origin[name] = label
    local = disk_cases(fixdir, FACTS_SUFFIX)
    for missing in sorted(set(manifest.synthetic) - set(local)):
        problems.append(f"manifest case '{missing}' has no facts file "
                        f"({missing}{FACTS_SUFFIX}) under fixtures/verdicts")
    for unlisted in sorted(set(local) - set(manifest.synthetic)):
        problems.append(f"'{unlisted}{FACTS_SUFFIX}' is not in manifest.json — "
                        f"add the case to the ledger (name, rules)")
    for name in manifest.synthetic:
        if name in cases:
            problems.append(f"synthetic case '{name}' shadows a swept corpus "
                            f"case name ({origin[name]})")
        else:
            cases[name] = os.path.join(fixdir, f"{name}{FACTS_SUFFIX}")
            origin[name] = SYNTHETIC
    for phantom in sorted(set(manifest.excluded) - set(cases)):
        problems.append(f"rust_replay_excluded names '{phantom}', which is not a "
                        f"planned case")
    return Plan(cases, origin, dict(manifest.excluded), manifest.verdicts_version,
                tuple(problems))


def goldens_on_disk(fixdir: str = FIXDIR) -> set[str]:
    return set(disk_cases(fixdir, GOLDEN_SUFFIX))


class CensusError(Exception):
    """The tree is not in a state a census may be taken over; `problems` says why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Census:
    """Checkpoint 4's measured census, computed from the tree.

    `goldens` is Python's complete truth (every planned case has one);
    `python_refusals`/`python_findings` count over all of them. `excluded` are
    the declared Rust exclusions, grouped by the ledger's executable
    expectation `(rust_refusal, rust_error_contains)`; `replayed` = goldens -
    excluded, with the refusals and findings the Rust replay compares.
    """

    goldens: int
    by_origin: tuple[tuple[str, int], ...]
    python_refusals: int
    python_findings: int
    excluded: int
    excluded_by_expectation: tuple[tuple[str, str | None, int], ...]
    replayed: int
    replayed_refusals: int
    replayed_findings: int


def _read_golden(path: str, version: int | None) -> tuple[bool, int] | str:
    """(is_refusal, finding count), or a problem string."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        return f"{path}: unreadable golden: {e}"
    if not isinstance(doc, dict):
        return f"{path}: golden is not a JSON object"
    if doc.get("verdicts_version") != version:
        return (f"{path}: golden verdicts_version {doc.get('verdicts_version')!r} != "
                f"manifest verdicts_version {version!r}")
    error = doc.get("error")
    findings = doc.get("findings")
    if isinstance(error, str) and findings is None:
        return (True, 0)
    if error is None and isinstance(findings, list):
        return (False, len(findings))
    return f"{path}: a golden carries either findings or an error"


def compute_verdict_census(p: Plan | None = None, fixdir: str = FIXDIR) -> Census:
    """Count the tree. Raises `CensusError` on any ledger problem, a missing or
    orphaned golden, or a malformed one — a census over a broken tree is the
    stale number this module exists to prevent."""
    if p is None:
        p = plan(fixdir=fixdir)
    problems = list(p.problems)
    on_disk = goldens_on_disk(fixdir)
    planned = set(p.cases)
    for missing in sorted(planned - on_disk):
        problems.append(f"{missing}: golden missing")
    for orphan in sorted(on_disk - planned):
        problems.append(f"{orphan}: orphaned golden (not a planned case)")
    if not planned and not problems:
        problems.append("no cases planned")
    if problems:
        raise CensusError(problems)

    by_origin: dict[str, int] = {label: 0 for label, _ in CORPORA}
    by_origin[SYNTHETIC] = 0
    for name in p.cases:
        by_origin[p.origin[name]] = by_origin.get(p.origin[name], 0) + 1

    python_refusals = python_findings = 0
    replayed = replayed_refusals = replayed_findings = 0
    for name in sorted(p.cases):
        got = _read_golden(os.path.join(fixdir, f"{name}{GOLDEN_SUFFIX}"), p.verdicts_version)
        if isinstance(got, str):
            problems.append(got)
            continue
        is_refusal, count = got
        python_refusals += 1 if is_refusal else 0
        python_findings += count
        if name in p.excluded:
            continue
        replayed += 1
        replayed_refusals += 1 if is_refusal else 0
        replayed_findings += count
    if problems:
        raise CensusError(problems)

    grouped: dict[tuple[str, str | None], int] = {}
    for ex in p.excluded.values():
        grouped[ex.expectation] = grouped.get(ex.expectation, 0) + 1
    by_expectation = tuple(
        (refusal, contains, n)
        for (refusal, contains), n in sorted(
            grouped.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
    )
    return Census(
        goldens=len(p.cases),
        by_origin=tuple(by_origin.items()),
        python_refusals=python_refusals,
        python_findings=python_findings,
        excluded=len(p.excluded),
        excluded_by_expectation=by_expectation,
        replayed=replayed,
        replayed_refusals=replayed_refusals,
        replayed_findings=replayed_findings,
    )
