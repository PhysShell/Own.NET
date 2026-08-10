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

## What the corpus could not reach

The 22 `.facts.json` fixtures are a historical corpus, not a designed one, so
what they observe is an accident. Measured: `effects` reached **nothing**, and
`di` reached **`DI001` only** — seven of its eight cases being one coordinate
band walked through the same code. That is a healthy-looking `di=9` covering
one mechanism out of five.

An empty (or single-code) expectation is satisfied by a port that never wires
the input behind the missing codes. Six of the eleven fields the DI adapter
builds — `weak_deps`, `disposable`, `root_resolves`, `root_resolve_sites`,
`scope_cached`, `scope_cache_sites` — feed `DI002`-`DI005` and were invisible
to every frozen case, so a composition that dropped all six replayed the whole
set clean. Same shape as the `effects` hole, six fields wide.

`disposable` is the sharpest of them and worth naming: there is no typed
`disposable` on `own_ir::Service`, so it arrives through the flattened `extra`
map and an adapter reading only the named fields loses it with no compile
error. The reference is `s.get("disposable") is True` — the JSON boolean and
nothing else, so a string `"false"` must not coerce.

The rule the witnesses below are built to, and the guards enforce:

    every adapter input able to change a frozen-shaped (path, line, code)
    verdict must have a witness that DIES when that input is dropped or
    swapped for a plausible neighbour

`REQUIRED_CODES` makes the coverage half of that mechanical (a hard failure,
not the warning the `effects` hole got), and `DISCRIMINATING_PAIRS` makes the
dying half mechanical for the pairs that straddle a boundary.

Every witness is deliberately an **OwnIR -> `check_facts`** document and not
the fact-level one from #214. `EFF001` and `DI001`-`005` are already frozen at
fact level by `tests/test_di_eff_fact_parity.py` and replayed with zero Python
by `rust/crates/own-analysis/tests/fact_parity.rs`, so the ANALYSIS was never
the gap. The gap is the TRANSPORT — that `check_facts` builds each analysis
input from the ORIGINAL facts and merges the verdicts — and re-proving the
analysis here would leave it exactly where it was. The case shapes are taken
from those fact-level fixtures on purpose: same semantics, one floor up.

The two shapes are NOT interchangeable, which is itself a witnessed trap:
`root_resolve_sites` is a list of OBJECTS on the OwnIR wire and a list of
`(type, file, line)` TRIPLES at the fact-level boundary. A composition that
reused the fact-level shape parses every field as absent and loses the site
silently — the `-site-primary` witnesses die on exactly that.

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

# The verdict codes cp4's gating channels must actually EXHIBIT, each with the
# adapter input it is the only observer of. A code missing here means the
# frozen set cannot tell a composition that wires that input from one that
# silently drops it — the failure this artifact exists to prevent, and the one
# it already made once with `effects` reading 0.
#
# Checked as a hard failure rather than a warning: the effects hole was a
# warning for exactly as long as it took to write the code it let through.
REQUIRED_CODES = {
    "DI001": "services[].deps + lifetime (the registration graph)",
    "DI002": "services[].weak_deps",
    "DI003": "services[].disposable — untyped, arrives via the flattened extra",
    "DI004": "services[].root_resolves + root_resolve_sites",
    "DI005": "services[].scope_cached + scope_cache_sites",
    "EFF001": "effects[].deps + io + bindings[].init",
}

# Witness pairs that must DISAGREE, named by case. Each pair varies exactly one
# input across the `>= 1` site sentinel (line 1 vs line 0) and must land on a
# different `(path, line)`. A pair whose halves agree has stopped being
# evidence — the boundary it was built to hold would be gone with the frozen
# file still green.
DISCRIMINATING_PAIRS = (
    ("composition-di004-site-primary", "composition-di004-site-fallback", "di"),
    ("composition-di005-site-primary", "composition-di005-site-fallback", "di"),
    ("composition-effect-storm", "composition-effect-opaque-call-silent", "effects"),
    ("composition-effect-storm", "composition-effect-no-io-silent", "effects"),
    ("composition-effect-storm", "composition-effect-no-deps-silent", "effects"),
)


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


def _service(name: str, lifetime: str, line: int, **extra: Any) -> dict[str, Any]:
    """One `services[]` record at `reg.cs:<line>`."""
    return {"name": name, "lifetime": lifetime, "file": "reg.cs", "line": line,
            **extra}


def _site(type_name: str, file: str, line: int) -> dict[str, Any]:
    """One `root_resolve_sites[]` / `scope_cache_sites[]` entry.

    An OBJECT, because that is the OwnIR wire shape (`spec/OwnIR.md` §4.2,
    `own_ir::Site`) and what `_resolve_sites` parses. The fact-level fixtures in
    `di_eff_fact_parity.json` carry the same information as a `(type, file,
    line)` TRIPLE, because they enter at the analysis boundary, below this
    adapter. A composition that reused the fact-level shape here would read
    every field as absent and silently lose the site — which is exactly the
    seam these witnesses exist to hold.
    """
    return {"type": type_name, "file": file, "line": line}


def _composition_witnesses() -> list[dict[str, Any]]:
    """Documents that close what the fixture corpus cannot observe.

    The rule, stated once so the list below can be checked against it:

    > every adapter input able to change a frozen-shaped verdict
    > `(path, line, code)` must have a witness that DIES when that input is
    > dropped or swapped for a plausible neighbour.

    The corpus does not satisfy it. Measured over the 22 `.facts.json`
    fixtures plus the coordinate band: `di` reaches **DI001 only**, and
    `effects` reached nothing at all until the storm witness below. Six of the
    eleven fields the DI adapter builds — `weak_deps`, `disposable`,
    `root_resolves`, `root_resolve_sites`, `scope_cached`, `scope_cache_sites`
    — feed DI002-DI005 and are invisible to every frozen case, so a
    composition that never wires them replays the whole corpus clean. That is
    the same hole the effects channel had, six fields wide.

    Each witness is an **OwnIR → `check_facts`** document, never a fact-level
    one. `di_eff_fact_parity.json` + `own-analysis/tests/fact_parity.rs`
    already prove the ANALYSIS with zero Python; what is unproven is the
    TRANSPORT — that the composition builds the analysis input from the
    ORIGINAL facts. Re-proving the analysis here would leave the gap exactly
    where it is. The case SHAPES are taken from those fact-level fixtures on
    purpose: same semantics, one floor up.
    """
    return [
        # ---- effects: one positive, three negatives -------------------------
        # A single positive proves the channel is connected and nothing more.
        # `deps`, `io`, `bindings[].init` and the lines are four separate wires;
        # a lamp on one end of the bundle does not tell them apart. Each
        # negative below flips exactly ONE of them and must go silent.
        {
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
        },
        {
            # `init` alone differs: an opaque call is UNKNOWN stability, not
            # unstable, so the storm must not fire. Pins that `bindings[].init`
            # reaches the analysis as a value rather than as a presence flag.
            "name": "composition-effect-opaque-call-silent",
            "origin": "witness",
            "family": "effects channel (bindings[].init: call -> no verdict)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "effects": [{
                    "component": "A", "file": "A.tsx", "line": 10,
                    "io": True, "deps": ["opts"],
                    "bindings": [
                        {"name": "opts", "init": "call", "refs": [], "line": 1},
                    ],
                }],
            },
        },
        {
            # `io` alone differs. EFF001 is gated on the effect doing IO; an
            # adapter that dropped the flag would default it and fire here.
            "name": "composition-effect-no-io-silent",
            "origin": "witness",
            "family": "effects channel (io: false -> no verdict)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "effects": [{
                    "component": "A", "file": "A.tsx", "line": 10,
                    "io": False, "deps": ["opts"],
                    "bindings": [
                        {"name": "opts", "init": "object", "refs": [], "line": 1},
                    ],
                }],
            },
        },
        {
            # `deps` alone differs: the unstable binding still exists, but no
            # effect depends on it. An adapter that lost `deps` and re-derived
            # the dependency set from `bindings` would fire here.
            "name": "composition-effect-no-deps-silent",
            "origin": "witness",
            "family": "effects channel (deps: [] -> no verdict)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "effects": [{
                    "component": "A", "file": "A.tsx", "line": 10,
                    "io": True, "deps": [],
                    "bindings": [
                        {"name": "opts", "init": "object", "refs": [], "line": 1},
                    ],
                }],
            },
        },

        # ---- di: one witness per unobservable input -------------------------
        {
            # `weak_deps` — a weakly-held scoped service is still a captive.
            # The ONLY input that distinguishes DI002 from silence.
            "name": "composition-di002-weak-deps",
            "origin": "witness",
            "family": "di channel (services[].weak_deps -> DI002)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, weak_deps=["Db"]),
                    _service("Db", "scoped", 6),
                ],
            },
        },
        {
            # `disposable` — and it is the sharpest of the six. There is no
            # typed `disposable` on `own_ir::Service`: the field lands in the
            # flattened `extra` map, so an adapter reading only the named
            # fields loses it with no compile error. The reference is
            # `s.get("disposable") is True` — JSON `true` and nothing else.
            "name": "composition-di003-transient-disposable",
            "origin": "witness",
            "family": "di channel (services[].disposable -> DI003)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, deps=["Conn"]),
                    _service("Conn", "transient", 6, disposable=True),
                ],
            },
        },
        {
            # DI004 primary: the call site WINS over the registration. Site
            # line is exactly 1 — the first value that satisfies the `>= 1`
            # sentinel — and the site file differs from the registration file,
            # so an adapter that anchored at the registration is visible in the
            # frozen `(path, line, code)` and not only in the line.
            "name": "composition-di004-site-primary",
            "origin": "witness",
            "family": "di channel (root_resolve_sites line 1 -> site anchor)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, root_resolves=["Conn"],
                             root_resolve_sites=[_site("Conn", "call.cs", 1)]),
                    _service("Conn", "transient", 6, disposable=True),
                ],
            },
        },
        {
            # DI004 fallback: the same document with the site line at 0 — the
            # last value the sentinel rejects. The verdict must move back to
            # the registration. Together with the case above this pins the
            # BOUNDARY of `>= 1`, which is a switch, not a range: the signed
            # carrier is already proven by the coordinate band, and walking
            # i64::MIN..MAX here would measure with a ruler what needs a
            # switch.
            "name": "composition-di004-site-fallback",
            "origin": "witness",
            "family": "di channel (root_resolve_sites line 0 -> registration anchor)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, root_resolves=["Conn"],
                             root_resolve_sites=[_site("Conn", "call.cs", 0)]),
                    _service("Conn", "transient", 6, disposable=True),
                ],
            },
        },
        {
            # DI005 primary — the field-store site, same sentinel, a different
            # pair of inputs (`scope_cached` + `scope_cache_sites`). Kept
            # separate from DI004 rather than assumed symmetric: two mechanisms
            # that happen to share a predicate are still two mechanisms.
            "name": "composition-di005-site-primary",
            "origin": "witness",
            "family": "di channel (scope_cache_sites line 1 -> site anchor)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, scope_cached=["Db"],
                             scope_cache_sites=[_site("Db", "store.cs", 1)]),
                    _service("Db", "scoped", 6),
                ],
            },
        },
        {
            "name": "composition-di005-site-fallback",
            "origin": "witness",
            "family": "di channel (scope_cache_sites line 0 -> registration anchor)",
            "document": {
                "ownir_version": 0,
                "module": "M",
                "services": [
                    _service("App", "singleton", 5, scope_cached=["Db"],
                             scope_cache_sites=[_site("Db", "store.cs", 0)]),
                    _service("Db", "scoped", 6),
                ],
            },
        },
    ]


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

    # ---- observability guard: the gating channels must EXHIBIT each code ----
    # Freezing a channel is not the same as observing it. Every code below is
    # the only frozen consequence of some adapter input, so its absence means
    # the port can drop that input and still replay clean.
    seen_codes = {row[-1]
                  for case in frozen.get("cases", [])
                  for channel in ("core", "di", "effects")
                  for row in case.get(channel, [])}
    for code, holds in sorted(REQUIRED_CODES.items()):
        if code not in seen_codes:
            failures += _fail(
                f"no frozen case exhibits {code} — nothing observes "
                f"{holds}, so a composition that never wires it replays this "
                f"set clean (the `effects` hole, again)")

    # ---- discrimination guard: a witness pair must actually disagree --------
    by_name = {c["name"]: c for c in frozen.get("cases", [])}
    for primary, fallback, channel in DISCRIMINATING_PAIRS:
        a, b = by_name.get(primary), by_name.get(fallback)
        if a is None or b is None:
            failures += _fail(
                f"the {primary} / {fallback} pair is incomplete — one half "
                f"alone pins nothing")
            continue
        if a.get(channel) == b.get(channel):
            failures += _fail(
                f"{primary} and {fallback} agree on `{channel}` "
                f"({a.get(channel)!r}) — the pair varies one input across a "
                f"boundary and must land differently, or it has stopped being "
                f"evidence")

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
    # The observed code inventory is printed, not just the row counts: a
    # channel's SIZE says how much it saw, and only its code set says what it
    # is able to tell apart. `di=9` read as coverage is what left DI002-DI005
    # unobserved behind a healthy-looking number.
    observed = sorted({row[-1]
                       for case in fresh["cases"]
                       for channel in ("core", "di", "effects")
                       for row in case[channel]})
    print(
        f"ownir verdict oracle OK: {len(fresh['cases'])} cases "
        f"({fixtures} fixtures / {coord} coordinate / {comp} composition witnesses); "
        f"channels " + ", ".join(f"{k}={v}" for k, v in counts.items())
        + f"; codes {', '.join(observed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(write="--write" in sys.argv))
