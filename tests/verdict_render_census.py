#!/usr/bin/env python3
"""The rendered-surface ledger, interpreted once (P-022 #259 checkpoint 5.3).

`tests/fixtures/verdict_renders/manifest.json` plus the `<case>.renders.json`
goldens are checkpoint 5.3's evidence. This module is the ONE place that reads
them, so the fixture harness (`tests/test_verdict_render_fixtures.py`), the
surface inventory (`tests/verdict_surface_inventory.py`) and the Rust replay's
Python-side counterpart cannot disagree about what the tree contains.

Unlike the verdict family, nothing here is swept: a rendered-surface case
exists to exercise a BR-V9 rule, so it is listed with the rules it pins and a
rule with no case is a hole the inventory reports rather than a case nobody
noticed. Every case carries its own facts document beside the manifest — the
verdict corpus is not re-rendered wholesale, because rendering 79 documents at
two severities would freeze megabytes to prove what a handful of targeted
documents prove better.

Pure: no `ownlang` import and no side effects. Held to `mypy --strict`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
FIXDIR = os.path.join(HERE, "fixtures", "verdict_renders")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
FACTS_SUFFIX = ".facts.json"
GOLDEN_SUFFIX = ".renders.json"


@dataclass(frozen=True)
class Case:
    name: str
    rules: tuple[str, ...]
    #: the BR-V9 ledger rows this case is the control for.
    pins: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    cases: dict[str, Case]
    renders_version: int | None
    problems: tuple[str, ...]

    def facts_path(self, name: str) -> str:
        return os.path.join(FIXDIR, f"{name}{FACTS_SUFFIX}")

    def golden_path(self, name: str) -> str:
        return os.path.join(FIXDIR, f"{name}{GOLDEN_SUFFIX}")


def _stems(suffix: str) -> set[str]:
    if not os.path.isdir(FIXDIR):
        return set()
    return {n[: -len(suffix)] for n in os.listdir(FIXDIR) if n.endswith(suffix)}


def plan(manifest_path: str = MANIFEST) -> Plan:
    """The case plan, with every ledger problem found on the way: a case with no
    facts, a facts file no case lists, a duplicate name, a case pinning nothing."""
    problems: list[str] = []
    if not os.path.exists(manifest_path):
        return Plan({}, None, (f"manifest missing: {manifest_path}",))
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return Plan({}, None, (f"manifest is not a JSON object: {manifest_path}",))
    raw_version = data.get("renders_version")
    version: int | None = None
    if isinstance(raw_version, int) and not isinstance(raw_version, bool):
        version = raw_version
    else:
        problems.append(f"manifest renders_version must be an integer, got {raw_version!r}")
    cases: dict[str, Case] = {}
    raw_cases = data.get("cases", [])
    if not isinstance(raw_cases, list):
        problems.append("manifest cases must be an array")
        raw_cases = []
    for c in raw_cases:
        if not isinstance(c, dict):
            problems.append(f"manifest case must be an object: {c!r}")
            continue
        name = c.get("name")
        rules, pins = c.get("rules"), c.get("pins")
        if not (isinstance(name, str) and name):
            problems.append(f"manifest case without a name: {c!r}")
            continue
        if not (isinstance(rules, list) and rules
                and all(isinstance(r, str) and r for r in rules)):
            problems.append(f"manifest case '{name}': 'rules' must be a non-empty array "
                            f"of non-empty strings")
            rules = []
        if not (isinstance(pins, list) and pins
                and all(isinstance(p, str) and p for p in pins)):
            problems.append(f"manifest case '{name}': 'pins' must name at least one BR-V9 "
                            f"ledger row — a rendered case that pins nothing is a golden "
                            f"nobody can read a claim off")
            pins = []
        if name in cases:
            problems.append(f"manifest lists case '{name}' twice")
        cases[name] = Case(name, tuple(rules), tuple(pins))
    on_disk = _stems(FACTS_SUFFIX)
    for missing in sorted(set(cases) - on_disk):
        problems.append(f"case '{missing}' has no facts file ({missing}{FACTS_SUFFIX})")
    for unlisted in sorted(on_disk - set(cases)):
        problems.append(f"'{unlisted}{FACTS_SUFFIX}' is not in manifest.json — add the case "
                        f"to the ledger (name, rules, pins)")
    return Plan(cases, version, tuple(problems))


def goldens_on_disk() -> set[str]:
    return _stems(GOLDEN_SUFFIX)


def pinned_rows(p: Plan | None = None) -> dict[str, tuple[str, ...]]:
    """BR-V9 ledger row -> the cases that pin it, from the manifest alone. The
    ledger of rows lives in `verdict_surface_inventory`; this is the other half
    of the join, and keeping them apart is what lets the inventory report a row
    nobody pins."""
    if p is None:
        p = plan()
    out: dict[str, list[str]] = {}
    for case in p.cases.values():
        for row in case.pins:
            out.setdefault(row, []).append(case.name)
    return {row: tuple(sorted(names)) for row, names in out.items()}
