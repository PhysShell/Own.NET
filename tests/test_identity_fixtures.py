#!/usr/bin/env python3
"""Routing identity: the ordered `(line, code, subject)` surface of `check`.

#214 froze `own-analysis` on `(line, code)` (`tests/fixtures/diag_parity.json`)
and deliberately deferred `subject`/`resource_kind`/Evidence to a later layer.
That was right: there was no consumer. #259 cp4 is the first, and it does not
need the *presentation* half — it needs the **identity** half.

## Two things called `subject`

1. an internal identity carrier — which handle a computed diagnostic is about,
   so a consumer can keep the analysis-selected primary C# anchor. cp4 cannot
   be built without it;
2. a public field of the final `Finding`, compared alongside message, severity,
   `resource_kind` and ordered Evidence. That is cp5.

This artifact freezes (1) and nothing else. It does not extend
`diag_parity.json` — the #214 oracle keeps its exact shape — and it compares no
`Finding`.

## Why it is authored at the ANALYSIS level, not through OwnIR

A cp4 replay could reach 51/51 by GUESSING the handle bridge-side — deriving
it from the lowering it already performed — and never prove that the analyzer
carries identity at all. This surface is `.own` source → `check_module`, with
no bridge in the picture, so a port cannot satisfy it by reconstructing from
somewhere else. The composition's own replay then rests on identity that was
proven independently.

## The shape

    [line, code, subject]      subject is a STRING or an explicit null

An explicit `null` because "carries no identity" is a real, load-bearing state
(the resolver diagnostics have none), and an absent key would let a port that
never stamps anything look identical to one that correctly stamps nothing.

Order is frozen as a LIST, exactly as `diag_parity` does: `_collect` returns
`check_module`'s diagnostics already sorted by `(line, code)` with a stable
intra-tie order, and list position IS the contract.

## The defect this is aimed at

`Symbol.origin` (`own_cfg`) already carries `name#line` and already survives
move/alias — the information reaches the analysis and is discarded there.
Python uses exactly that: ownership diagnostics take `sym.origin`, and lifetime
`OWN014` takes `source#line`.

A port that instead builds `format!("{current_name}#{diagnostic_line}")` looks
extremely plausible and is NOT equivalent: after a move or an alias join the
current name is not the origin name, and the diagnostic line is not the origin
line. The curated pair below separates those two, because the corpus alone does
not: both halves report a leak, and only the moved one has an origin name
that differs from the reported name.

Run:  python tests/test_identity_fixtures.py           (verify)
      python tests/test_identity_fixtures.py --write   (regenerate)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.__main__ import _collect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "identity_parity.json")

CORPUS_DIRS = ("corpus", "examples")

# Curated sources the corpus does not produce, each isolating one way an
# identity can be got wrong. Kept here rather than in the corpus because they
# are contract probes, not programs anyone would write.
_CURATED: tuple[tuple[str, str], ...] = (
    (
        # A move renames the handle: the leak is reported on `b`, whose origin
        # is still `a`'s acquire site. A subject built from the CURRENT name
        # would say `b#...`; one built from the DIAGNOSTIC line would carry the
        # wrong line. Both look right and neither is.
        "curated/move-keeps-origin.own",
        "module MoveOrigin\n"
        "\n"
        "resource R {\n"
        "    acquire New\n"
        "    release Dispose\n"
        "}\n"
        "\n"
        "fn F(x: int) {\n"
        "    let a = acquire R(x);\n"
        "    let b = move a;\n"
        "    use b;\n"
        "}\n",
    ),
    (
        # No move: the same shape with the origin and the current name equal,
        # so the pair separates "carries the origin" from "carries the name".
        "curated/plain-keeps-origin.own",
        "module PlainOrigin\n"
        "\n"
        "resource R {\n"
        "    acquire New\n"
        "    release Dispose\n"
        "}\n"
        "\n"
        "fn F(x: int) {\n"
        "    let a = acquire R(x);\n"
        "    use a;\n"
        "}\n",
    ),
    (
        # OWN014 region escape — the lifetime family, whose subject is
        # `source#line` and not an ownership symbol at all. Without it the
        # artifact would prove one family and imply the other.
        "curated/region-escape.own",
        "module RegionEscape\n"
        "\n"
        "lifetime Process;\n"
        "lifetime Window < Process;\n"
        "\n"
        "fn Dialog(systemEvents: SystemEvents lifetime Process) lifetime Window {\n"
        "    subscribe self to systemEvents;\n"
        "}\n",
    ),
)


def _identity_for(source: str) -> list[list[object]]:
    """The ordered `[line, code, subject]` list for one source.

    `_collect` is what `python -m ownlang check` runs, so this is the same
    surface `diag_parity` freezes — read one field wider.
    """
    diags, _mod = _collect(source)
    return [[d.line, d.code, getattr(d, "subject", None)] for d in diags]


def _corpus_files() -> list[str]:
    found: list[str] = []
    for base in CORPUS_DIRS:
        for dirpath, _dirs, files in os.walk(os.path.join(REPO_ROOT, base)):
            for name in files:
                if name.endswith(".own"):
                    rel = os.path.relpath(os.path.join(dirpath, name), REPO_ROOT)
                    found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def build() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for rel in _corpus_files():
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            src = fh.read()
        cases.append({"name": rel, "source": src, "identity": _identity_for(src)})
    for name, src in _CURATED:
        cases.append({"name": name, "source": src, "identity": _identity_for(src)})
    return {
        "comment": (
            "GENERATED by tests/test_identity_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative; rust/crates/own-analysis must "
            "reproduce the ordered (line, code, subject) list exactly. This is "
            "ROUTING IDENTITY only — the prerequisite #259 cp4 needs to keep an "
            "analysis-selected primary anchor. Message/severity/resource_kind/"
            "Evidence parity remains cp5."
        ),
        "cases": cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def run(write: bool = False) -> int:
    fresh = build()
    if write:
        with open(FIXTURE, "w", encoding="utf-8") as fh:
            fh.write(_render(fresh))
        print(f"wrote {FIXTURE}")
        return 0

    failures = 0
    if not os.path.exists(FIXTURE):
        return _fail(f"{FIXTURE} missing; regenerate with --write")
    with open(FIXTURE, encoding="utf-8") as fh:
        frozen = json.load(fh)

    rows = [r for c in frozen.get("cases", []) for r in c["identity"]]
    named = [r for r in rows if r[2] is not None]
    anonymous = [r for r in rows if r[2] is None]

    # Observability, the same rule the verdict oracle enforces: an artifact
    # that froze only nulls would be satisfied by a port that stamps nothing.
    if not named:
        failures += _fail(
            "no frozen row carries a subject — this artifact would be "
            "satisfied by a port that never stamps one")
    # ...and the converse: `None` is a real state, not an absence to optimise
    # away. A port that stamped SOMETHING on every diagnostic must fail too.
    if not anonymous:
        failures += _fail(
            "no frozen row carries a null subject — the resolver diagnostics "
            "have no identity, and a port that invents one must be visible")

    # Both families, named. Ownership takes `sym.origin`; OWN014 takes
    # `source#line` through an entirely different construction. One proven
    # family must not imply the other.
    codes = {r[1] for r in named}
    if not any(c.startswith("OWN0") and c not in {"OWN014"} for c in codes):
        failures += _fail("no ownership-family diagnostic carries a subject")
    if "OWN014" not in codes:
        failures += _fail(
            "OWN014 carries no subject in the frozen set — the lifetime family "
            "builds its identity differently and needs its own witness")

    if _render(frozen) != _render(fresh):
        failures += _fail(
            "the frozen identities are stale (the reference decides "
            "differently now); regenerate with --write")

    if failures:
        return 1
    print(
        f"identity parity OK: {len(frozen['cases'])} cases, {len(rows)} rows "
        f"({len(named)} with a subject, {len(anonymous)} without); "
        f"subject-bearing codes {', '.join(sorted(codes))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(write="--write" in sys.argv))
