#!/usr/bin/env python3
"""The frozen verdict surface of `check_facts` — #259 cp4's parity oracle.

cp2 froze the lowering (`tests/fixtures/lowered/`) and cp3 froze the MOS
summaries. Neither says what the analysis *decides*. `tests/test_ownir.py`
exercises that in 3000+ lines of hand-written assertions, but those are Python
asserting Python: they cannot be replayed by a port, which is what a parity
checkpoint needs. This file is the missing artifact, in the same shape as the
other two — Python authors it, the Rust side replays it with zero Python.

## What is compared, and at which granularity

`check_facts` composes several analyses that reach a verdict by different
routes, so they are frozen as **separate channels** rather than one flat list.
A single list would let a finding move between mechanisms without the golden
noticing, which is the whole failure this checkpoint exists to catch.

    core        (line, code)          the `.own` check surface over the
                                      lowered module — the granularity
                                      `own-analysis` itself compares at
    di          (file, line, code)    fact-driven, and multi-file by nature:
                                      a registration site and a consuming
                                      constructor are different files
    effects     (file, line, code)    fact-driven, same reason
    protocols   (file, line, code)    fact-driven, same reason
    advisories  (file, line, code)    NOT leak verdicts (excluded from the
                                      exit code); a channel of their own so
                                      "we stopped emitting one" cannot read
                                      as "we fixed something"

The channel set is **measured, not assumed**. An earlier plan had three
channels; the corpus turned out to produce `OBL001` and an `OWN050` advisory
too, so filing them under `core` would have hidden two mechanisms inside a
third. Routing is by mechanism — the `advisory` flag first, then the code
family — never by "which list did Python happen to append it to".

Ordering is preserved as a LIST. `check_facts` emits in a defined order and
BR-V8 fixes the final sort; comparing as sets would drop that entirely.

## The channel the corpus could not reach

`effects` is empty for all 22 `.facts.json` fixtures: none of them produces
`EFF001`. An empty expectation is satisfied by a port that never calls the
effect analysis at all, so the hole was recorded here rather than left to be
found when somebody read `0 == 0` as evidence — and then closed with a
synthetic witness rather than left recorded.

The witness is deliberately an **OwnIR -> `check_facts`** document and not the
fact-level one from #214. `EFF001` and `DI001`-`005` are already frozen at fact
level by `tests/test_di_eff_fact_parity.py` and replayed with zero Python by
`rust/crates/own-analysis/tests/fact_parity.rs`, so the ANALYSIS was never the
gap. The gap was the COMPOSITION — that `check_facts` feeds the effect analysis
from a document and merges its verdicts into the combined surface — and
re-proving the analysis here would have left it exactly where it was.

## Which channels GATE cp4, and which are only observed

Freezing five channels is not the same as owing five channels, and the
difference has to be written down here or the artifact will quietly widen the
checkpoint that consumes it.

    core + di + effects     cp4's gating channels — #259 cp4 is
                            ownership/lifetime/buffer/effect/DI wiring
    protocols + advisories  frozen OBSERVATIONS, consumed by the later full
                            bridge/verdict parity (cp5)

They are frozen now anyway, because a channel that exists in the golden cannot
later vanish from the surface unnoticed — which is worth more than the cost of
carrying two rows the current checkpoint does not gate on. What must not happen
is the reverse: a green five-channel replay read as "cp4 done", turning analysis
wiring into half of cp5 by accident.

## Why the synthetic cases are in the SAME inventory

The coordinate witnesses below are not a side test. They are normative: they
pin the *language* the verdict surface must be able to represent, which is
what the port has to satisfy. Kept in one list with the fixture cases so they
cannot be regenerated separately and drift apart.

Run:  python tests/test_ownir_verdict_fixtures.py           (verify)
      python tests/test_ownir_verdict_fixtures.py --write   (regenerate)
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownir import check_facts

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(HERE, "fixtures", "ownir")
GOLDEN = os.path.join(FIXTURE_DIR, "verdicts.json")

VERDICTS_VERSION = 1

# The band the strict door accepts for a source coordinate after #326
# (spec/OwnIR.md §4.2). Measured against `check_facts`, which preserves every
# one of them verbatim on the verdict surface — no clamp, no normalisation, no
# rejection. Frozen as controls so a port cannot narrow the range quietly.
I64_MIN = -9223372036854775808
I64_MAX = 9223372036854775807
U32_MAX = 4294967295
COORD_BAND = [
    ("i64-min", I64_MIN),
    ("negative", -1),
    ("zero", 0),
    ("one", 1),
    ("u32-max", U32_MAX),
    ("above-u32", U32_MAX + 1),
    ("i64-max", I64_MAX),
]


def _channel(code: str, advisory: bool) -> str:
    """Route a finding to its channel by MECHANISM.

    The `advisory` flag comes first on purpose: an advisory is not a leak
    verdict (it is excluded from the exit code), and that is a property of the
    finding rather than of its code family. Routing on the code prefix alone
    would file `OWN050` under `core` and lose the distinction.
    """
    if advisory:
        return "advisories"
    if code.startswith("DI"):
        return "di"
    if code.startswith("EFF"):
        return "effects"
    if code.startswith("OBL"):
        return "protocols"
    return "core"


CHANNELS = ("core", "di", "effects", "protocols", "advisories")


def _verdicts(facts: dict[str, Any]) -> dict[str, list[Any]]:
    """Run the reference and split its findings into the frozen channels.

    Every channel is present in the result even when empty — an absent key and
    an empty list are the same evidence to a reader and very different evidence
    to a generator that forgot to emit one.
    """
    out: dict[str, list[Any]] = {c: [] for c in CHANNELS}
    for f in check_facts(facts):
        channel = _channel(f.code, f.advisory)
        if channel == "core":
            out[channel].append([f.line, f.code])
        else:
            out[channel].append([f.file, f.line, f.code])
    return out


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _coordinate_witnesses() -> list[dict[str, Any]]:
    """Synthetic documents pinning the representable coordinate range.

    Two families, and the distinction between them is the argument:

    * `services[].line` is **validated** by the strict door, and §4.2 declares
      the signed-64 range legal there. A port that cannot carry the value has
      narrowed a language the door accepts — this is the load-bearing witness.
    * `subscriptions[].line` is validated *nowhere* (§4.2 records it as an open
      contract question, and both implementations agree). It is kept as a
      second family because the tolerant path must not diverge either, but it
      is deliberately NOT the primary argument: a rule proven only on an
      unvalidated field proves the wrong thing.
    """
    cases: list[dict[str, Any]] = []
    for label, line in COORD_BAND:
        cases.append({
            "name": f"coord-service-line-{label}",
            "origin": "witness",
            "family": "services[].line (validated, spec/OwnIR.md §4.2)",
            "document": {
                "module": "M",
                "services": [
                    {"name": "Sing", "lifetime": "singleton", "file": "S.cs",
                     "line": line, "deps": ["Scop"]},
                    {"name": "Scop", "lifetime": "scoped", "file": "S.cs",
                     "line": 2},
                ],
            },
        })
        cases.append({
            "name": f"coord-subscription-line-{label}",
            "origin": "witness",
            "family": "subscriptions[].line (validated nowhere — §4.2)",
            "document": {
                "module": "M",
                "components": [
                    {"name": "Vm", "file": "Vm.cs", "subscriptions": [
                        {"event": "bus.X", "handler": "h", "line": line,
                         "released": False, "resource": "subscription",
                         "source": "injected"}]},
                ],
            },
        })
    return cases


def _composition_witnesses() -> list[dict[str, Any]]:
    """Documents that close a channel the fixture corpus leaves empty.

    `effects` was 0 across all 22 fixtures, and an empty expectation is
    satisfied by a port that never calls the effect analysis at all. That was
    recorded as a known hole rather than fixed, and it stayed a hole for
    exactly as long as it took to write the composition it would have let
    through.

    This is deliberately an **OwnIR → `check_facts`** witness and not the
    fact-level one from #214: `di_eff_fact_parity` already proves the effect
    ANALYSIS, and re-proving it here would leave the actual gap — that the
    composition feeds it — untouched.
    """
    return [{
        "name": "composition-effect-storm",
        "origin": "witness",
        "family": "effects channel (OwnIR -> check_facts -> EFF001)",
        "document": {
            "ownir_version": 0,
            "module": "M",
            "effects": [{
                "component": "A",
                "file": "A.tsx",
                "line": 10,
                "io": True,
                "deps": ["opts"],
                "bindings": [
                    {"name": "opts", "init": "object", "refs": [], "line": 1},
                ],
            }],
        },
    }]


def build() -> dict[str, Any]:
    """Author the golden from the tree — the fixture set is DISCOVERED.

    The inventory is a glob, never a hand-maintained list: a list is a second
    place to forget a file, and a `.facts.json` that stops being replayed is
    exactly the loss this artifact exists to make loud.
    """
    cases: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.facts.json"))):
        source = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            facts = json.load(fh)
        case: dict[str, Any] = {
            "name": source[: -len(".facts.json")],
            "origin": "fixture",
            "source": source,
            # The input's identity travels with its expectation. Without it a
            # renamed or edited fixture can keep a matching verdict list and
            # the golden reports agreement about a document that no longer
            # exists in that form.
            "sha256": _sha256(path),
        }
        case.update(_verdicts(facts))
        cases.append(case)

    for witness in _composition_witnesses() + _coordinate_witnesses():
        case = dict(witness)
        case.update(_verdicts(witness["document"]))
        cases.append(case)

    return {"verdicts_version": VERDICTS_VERSION, "cases": cases}


def _render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def _fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def run(write: bool = False) -> int:
    fresh = build()
    if write:
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            fh.write(_render(fresh))
        print(f"wrote {GOLDEN}")
        return 0

    failures = 0
    if not os.path.exists(GOLDEN):
        return _fail(f"{GOLDEN} is missing; regenerate with --write")
    with open(GOLDEN, encoding="utf-8") as fh:
        frozen = json.load(fh)

    if frozen.get("verdicts_version") != VERDICTS_VERSION:
        failures += _fail(
            f"verdicts_version is {frozen.get('verdicts_version')!r}, this "
            f"generator writes {VERDICTS_VERSION}")

    # ---- inventory guard: the frozen set and the tree must be the same set --
    # Checked as a SET EQUALITY, not a count. Equal counts with one file
    # renamed is the exact shape of a silent loss.
    frozen_fixtures = {c["source"] for c in frozen.get("cases", [])
                       if c.get("origin") == "fixture"}
    tree_fixtures = {os.path.basename(p)
                     for p in glob.glob(os.path.join(FIXTURE_DIR, "*.facts.json"))}
    for missing in sorted(tree_fixtures - frozen_fixtures):
        failures += _fail(
            f"{missing} exists in the tree and has no frozen verdict — a new "
            f"fixture must join the oracle, or it is a document the port is "
            f"never asked about")
    for orphan in sorted(frozen_fixtures - tree_fixtures):
        failures += _fail(
            f"{orphan} is frozen but no longer in the tree — a renamed or "
            f"deleted fixture leaves its expectation behind, which then agrees "
            f"with nothing")

    if _render(frozen) != _render(fresh):
        failures += _fail(
            "the frozen verdicts are stale (the reference decides differently "
            "now); regenerate with --write and re-run the Rust replay")

    if failures:
        return 1

    counts = {c: sum(len(case[c]) for case in fresh["cases"]) for c in CHANNELS}
    fixtures = sum(1 for c in fresh["cases"] if c["origin"] == "fixture")
    coord = sum(1 for c in fresh["cases"] if c.get("family", "").startswith("services") or c.get("family", "").startswith("subscriptions"))
    comp = sum(1 for c in fresh["cases"] if c["origin"] == "witness") - coord
    print(
        f"ownir verdict oracle OK: {len(fresh['cases'])} cases "
        f"({fixtures} fixtures / {coord} coordinate / {comp} composition witnesses); "
        f"channels " + ", ".join(f"{k}={v}" for k, v in counts.items())
        + (" — WARNING: the effects channel is empty, so a port that never "
           "calls the effect analysis would replay this clean"
           if counts["effects"] == 0 else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(write="--write" in sys.argv))
