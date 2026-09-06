#!/usr/bin/env python3
"""Compute the P-022 step 7a (shadow-mode infrastructure) census from evidence.

The counterpart to `tests/verdict_census.py` for the #260/#269 slice: the one
interpretation of the committed reproduction artifacts, traces and reductions,
so the status renderer and any test that quotes a number read the same thing.
Nothing here interprets a mutation campaign — that is
`scripts/mutate_campaign.summarize()`, and interpreting it twice is how two
documents come to disagree about one run.

What it deliberately does NOT compute: a divergence counter over the same-input
layer. That classification is enforced by a **gate** — the port asserts
per-document equality of the canonical identity and byte-exact equality of
every artifact and trace, so a non-zero counter there is not representable as a
passing build. The reduction layer is different: those counters ARE computed,
by the reducer, and this reads them off the committed reductions.

Run:  python tests/shadow_census.py     (prints the computed census as JSON)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXDIR = os.path.join(ROOT, "tests", "fixtures", "repro")
RUST_TESTS = ("repro.rs", "engine.rs", "trace.rs", "reduce.rs")
CLASSES = ("left-only", "right-only", "changed", "ordering-only",
           "status", "projection", "unexplained")


class ShadowCensusError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class ShadowCensus:
    """Every figure the step-7a status surfaces may show, and nothing else."""

    documents: int = 0
    by_corpus: tuple[tuple[str, int], ...] = ()
    domain_refusals: int = 0
    artifacts: int = 0
    structural_controls: int = 0
    domain_backstop_controls: int = 0
    engines: tuple[tuple[str, int, int, int, int], ...] = ()
    status_differs: tuple[tuple[str, str, str], ...] = ()
    trace_layers: int = 0
    trace_steps: int = 0
    stable_id_steps: int = 0
    reductions: int = 0
    identical: int = 0
    scope: tuple[str, ...] = ()
    by_class: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    gates: tuple[tuple[str, str], ...] = ()


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rust_test_names() -> tuple[tuple[str, str], ...]:
    """The gates' own test names, read from the source. A renamed or deleted
    test makes the census stale, so a document cannot go on naming a gate that
    no longer exists."""
    out: list[tuple[str, str]] = []
    for target in RUST_TESTS:
        path = os.path.join(ROOT, "rust", "crates", "own-shadow", "tests", target)
        with open(path, encoding="utf-8") as f:
            source = f.read()
        out += [(target, name) for name in sorted(
            re.findall(r"#\[test\][^\n]*\n(?:\s*#\[[^\n]*\n)*fn (\w+)\(", source))]
    return tuple(out)


def compute_shadow_census() -> ShadowCensus:
    problems: list[str] = []
    for name in ("digests.json", "manifest.json"):
        if not os.path.exists(os.path.join(FIXDIR, name)):
            problems.append(f"missing evidence: tests/fixtures/repro/{name}")
    if problems:
        raise ShadowCensusError(problems)

    import test_repro_fixtures as harness

    digests = _load(os.path.join(FIXDIR, "digests.json"))
    manifest = _load(os.path.join(FIXDIR, "manifest.json"))
    documents = digests["documents"]

    per_corpus: dict[str, int] = {}
    for record in documents:
        per_corpus[record["corpus"]] = per_corpus.get(record["corpus"], 0) + 1

    # Per-engine, per-status accounting over the committed artifacts, plus the
    # layer envelopes where the two engines' STATUS differs. That last number is
    # the closest thing this slice has to a cross-engine measurement, and it is
    # structural: no layer's content is compared here.
    tallies: dict[str, dict[str, int]] = {}
    projections: dict[str, dict[str, int]] = {}
    differs: list[tuple[str, str, str]] = []
    for entry in manifest["artifacts"]:
        artifact = _load(os.path.join(FIXDIR, f"{entry['name']}.repro.json"))
        by_layer: dict[str, dict[str, str]] = {}
        for engine in artifact["engines"]:
            eid = engine["id"]
            tally = tallies.setdefault(eid, {"produced": 0, "refused": 0})
            proj = projections.setdefault(eid, {"full": 0, "partial": 0})
            for layer in engine["layers"]:
                tally[layer["status"]] = tally.get(layer["status"], 0) + 1
                kind = layer["projection"]["kind"]
                proj[kind] = proj.get(kind, 0) + 1
                by_layer.setdefault(layer["layer"], {})[eid] = layer["status"]
        for layer_name, statuses in sorted(by_layer.items()):
            if len(set(statuses.values())) > 1:
                shown = ", ".join(f"{e}: {s}" for e, s in sorted(statuses.items()))
                differs.append((entry["name"], layer_name, shown))

    trace_layers = trace_steps = stable_ids = 0
    for entry in manifest["artifacts"]:
        path = os.path.join(FIXDIR, f"{entry['name']}.trace.json")
        if not os.path.exists(path):
            continue
        for trace in _load(path)["traces"]:
            for layer in trace["layers"]:
                trace_layers += 1
                trace_steps += len(layer["steps"])
                stable_ids += sum(1 for s in layer["steps"]
                                  if s["id"].startswith("handles["))

    by_class = dict.fromkeys(CLASSES, 0)
    reductions = identical = 0
    scope: tuple[str, ...] = ()
    for entry in manifest["artifacts"]:
        path = os.path.join(FIXDIR, f"{entry['name']}.reduction.json")
        if not os.path.exists(path):
            continue
        reduction = _load(path)
        reductions += 1
        scope = tuple(reduction["scope"])
        if reduction["outcome"] == "identical":
            identical += 1
        for name, count in reduction.get("classification", {}).items():
            if name not in by_class:
                problems.append(f"{entry['name']}.reduction.json: unknown class {name!r}")
                continue
            by_class[name] += count
    if problems:
        raise ShadowCensusError(problems)

    return ShadowCensus(
        documents=len(documents),
        by_corpus=tuple(sorted(per_corpus.items())),
        domain_refusals=len(manifest["domain_refusals"]),
        artifacts=len(manifest["artifacts"]),
        structural_controls=harness.STRUCTURAL_CONTROL_COUNT,
        domain_backstop_controls=harness.DOMAIN_BACKSTOP_COUNT,
        engines=tuple((eid, t["produced"], t["refused"],
                       projections[eid]["full"], projections[eid]["partial"])
                      for eid, t in sorted(tallies.items())),
        status_differs=tuple(differs),
        trace_layers=trace_layers,
        trace_steps=trace_steps,
        stable_id_steps=stable_ids,
        reductions=reductions,
        identical=identical,
        scope=scope,
        by_class=by_class,
        gates=_rust_test_names(),
    )


def main() -> int:
    """A hand run: print what the committed evidence says, without the renderer
    in the way. The gate is `tests/test_checkpoint_status.py`."""
    try:
        census = compute_shadow_census()
    except ShadowCensusError as e:
        for p in e.problems:
            print(f"FAIL[shadow-census]: {p}")
        return 1
    print(f"shadow census OK: {census.documents} documents, {census.artifacts} artifacts, "
          f"{census.reductions} reductions, {len(census.gates)} named gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
