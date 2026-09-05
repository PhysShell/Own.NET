#!/usr/bin/env python3
"""Generate the census for a P-022 checkpoint from its evidence, and check
that the committed copy still matches.

The rule this exists to enforce: **a number in a document is never typed by
hand.** The #259 status table drifted twice because its counts were prose, and
P-022's own status block now carries a rule about it. A count that a reader
cannot re-derive is a claim, not evidence — so every figure below is read out
of a committed artifact (`tests/fixtures/repro/*`, the campaign result) or out
of the code that asserts it, and a stale census is a red build
(`tests/test_generated_docs.py`).

What it deliberately does NOT do: invent a divergence counter. The
Python-only / Rust-only / Changed / Ordering-only / Unexplained classification
over a measured set is enforced by a **gate**, not counted by this script —
the Rust replay asserts per-document equality and the build is red otherwise,
so a non-zero counter is not representable as a passing build. The census says
exactly that, names the test that enforces it, and names the unmeasured set
beside it. Reporting a counter this script could not have computed would be
the same lie in a new place.

Run:  python scripts/render_checkpoint_status.py --write
      python scripts/render_checkpoint_status.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

GENERATED = os.path.join(ROOT, "docs", "generated")
FIXDIR = os.path.join(ROOT, "tests", "fixtures", "repro")
# The recorded campaigns, one per checkpoint. Each stays frozen at what it
# measured — a later checkpoint may not quietly restate an earlier one's
# numbers — while THIS document is the live view of the slice as it stands.
CAMPAIGNS = (
    ("checkpoint 1 — capture and artifact",
     os.path.join(ROOT, "docs", "notes",
                  "p022-shadow-infra-checkpoint1-data", "campaign.json")),
    ("checkpoint 2 — engine protocol",
     os.path.join(ROOT, "docs", "notes",
                  "p022-shadow-infra-checkpoint2-data", "campaign.json")),
)
RUST_TESTS = (
    os.path.join(ROOT, "rust", "crates", "own-shadow", "tests", "repro.rs"),
    os.path.join(ROOT, "rust", "crates", "own-shadow", "tests", "engine.rs"),
)

HEADER = (
    "<!-- GENERATED FILE — do not edit by hand.\n"
    "     Regenerate: python scripts/render_checkpoint_status.py --write\n"
    "     Checked by: tests/test_generated_docs.py (a stale copy is a red build).\n"
    "     Every figure below is read out of committed evidence; none is typed. -->\n"
)


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rust_test_names() -> list[tuple[str, str]]:
    """The gates' own test names, read from the source. A renamed or deleted
    test makes the census stale, so the document cannot go on naming a gate
    that no longer exists."""
    out: list[tuple[str, str]] = []
    for path in RUST_TESTS:
        with open(path, encoding="utf-8") as f:
            source = f.read()
        target = os.path.basename(path)
        out += [(target, name) for name in sorted(
            re.findall(r"#\[test\][^\n]*\n(?:#\[[^\n]*\]\n)*fn (\w+)\(", source))]
    return out


def render_shadow_slice() -> str:
    # Imported here, not at module scope: sys.path is extended above.
    import test_repro_fixtures as harness

    digests = _load(os.path.join(FIXDIR, "digests.json"))
    manifest = _load(os.path.join(FIXDIR, "manifest.json"))

    documents = digests["documents"]
    per_corpus: dict[str, int] = {}
    for record in documents:
        per_corpus[record["corpus"]] = per_corpus.get(record["corpus"], 0) + 1

    # Per-engine, per-status accounting over the committed artifacts, plus the
    # layer envelopes where the two engines' STATUS differs. That last number
    # is the closest thing this slice has to a cross-engine measurement, and it
    # is structural: no layer's content is compared anywhere yet.
    engines: dict[str, dict[str, int]] = {}
    projections: dict[str, dict[str, int]] = {}
    status_differs: list[str] = []
    for entry in manifest["artifacts"]:
        artifact = _load(os.path.join(FIXDIR, f"{entry['name']}.repro.json"))
        by_layer: dict[str, dict[str, str]] = {}
        for engine in artifact["engines"]:
            eid = engine["id"]
            tally = engines.setdefault(eid, {"produced": 0, "refused": 0})
            proj = projections.setdefault(eid, {"full": 0, "partial": 0})
            for layer in engine["layers"]:
                tally[layer["status"]] = tally.get(layer["status"], 0) + 1
                kind = layer["projection"]["kind"]
                proj[kind] = proj.get(kind, 0) + 1
                by_layer.setdefault(layer["layer"], {})[eid] = layer["status"]
        for layer_name, statuses in sorted(by_layer.items()):
            if len(set(statuses.values())) > 1:
                shown = ", ".join(f"{e}: {s}" for e, s in sorted(statuses.items()))
                status_differs.append(f"| `{entry['name']}` | `{layer_name}` | {shown} |")

    engine_rows = "\n".join(
        f"| `{eid}` | {t_['produced']} | {t_['refused']} | "
        f"{projections[eid]['full']} | {projections[eid]['partial']} |"
        for eid, t_ in sorted(engines.items()))
    corpus_rows = "\n".join(
        f"| `tests/fixtures/{corpus}` | {per_corpus[corpus]} |"
        for corpus in sorted(per_corpus))
    gate_rows = "\n".join(f"- `own-shadow/tests/{target}::{name}`"
                           for target, name in _rust_test_names())
    differ_rows = ("\n".join(status_differs) if status_differs
                   else "| — | — | the two engines' statuses agree everywhere |")

    n_refusals = len(manifest["domain_refusals"])
    n_artifacts = len(manifest["artifacts"])
    campaign_blocks = []
    for label, path in CAMPAIGNS:
        campaign = _load(path)
        totals = campaign["totals"]
        by_layer_counts: dict[str, int] = {}
        for mutation in campaign["mutations"]:
            for catcher in mutation["caught_by"]:
                layer = catcher.split("::", 1)[0]
                by_layer_counts[layer] = by_layer_counts.get(layer, 0) + 1
        single = [m["id"] for m in campaign["mutations"] if len(m["caught_by"]) == 1]
        rows = "\n".join(
            f"| {m['id']} | {m['what']} | "
            f"{', '.join(f'`{c}`' for c in m['caught_by']) or '—'} |"
            for m in campaign["mutations"] if not m["status"].startswith("control_"))
        attribution = ", ".join(f"`{k}` {v}" for k, v in sorted(by_layer_counts.items()))
        campaign_blocks.append(f"""### {label} (`{campaign["campaign"]}`)

| | |
|---|---|
| mutations | **{totals["mutations"]}** |
| caught | **{totals["caught"]}** |
| survived | **{totals["survived"]}** |
| compile errors (reported as such, never as "caught") | {totals["compile_errors"]} |
| harness-honesty controls reporting zero failures | {totals["control_clean"]} |
| catches by layer | {attribution} |
| mutations with exactly **one** catching layer | {len(single)} — {', '.join(single)} |

| id | mutation | caught by |
|---|---|---|
{rows}""")

    return f"""{HEADER}
# P-022 step 7a — shadow-mode infrastructure: census

**Infrastructure for shadow mode, not shadow mode.** Nothing measured here
compares two engines' end diagnostics — or any of their layer *contents*. That
comparison is #260's acceptance and is blocked on #259 (cp5 and 4b). Nothing
here is a parity claim either.

This document is the **live view** of the slice as it stands; each checkpoint's
recorded mutation campaign stays frozen at what it measured, under
`docs/notes/p022-shadow-infra-checkpoint*-data/`.

## The measured set — same-input capture (checkpoint 1)

| corpus | documents |
|---|---|
{corpus_rows}
| **total** | **{len(documents)}** |

Every one of those documents is canonicalized and hashed by the reference
(`ownlang/repro.py`) and re-hashed from the same file by the port
(`own-shadow`), which is what makes "both engines saw the same input" a
checked fact rather than an assumption.

| surface | count |
|---|---|
| documents captured and digest-pinned | {len(documents)} |
| tamper controls (one changed character per document, refusal required) | {len(documents)} |
| documents both engines must REFUSE to name (`domain_refusals`) | {n_refusals} |
| reproduction artifacts committed and replayed byte-for-byte | {n_artifacts} |
| structural negative controls on `verify` (each side) | {harness.STRUCTURAL_CONTROL_COUNT} |
| value-level domain backstop controls | {harness.DOMAIN_BACKSTOP_COUNT} |

## The engine protocol (checkpoint 2)

Each engine authors only its own `engines[]` entry, and declares per layer what
it could **produce**. Over the committed artifacts:

| engine | layers produced | layers refused | projection `full` | projection `partial` |
|---|---|---|---|---|
{engine_rows}

The port's `partial` layers are its verdict surface: `own_bridge::check_facts`
is at the #259 checkpoint-4 projection, which carries every `Finding` member
except `message`, `related` and `flow`. It says so in the artifact rather than
emitting a short document a later comparison would score as agreement, and a
test asserts the claim matches the records byte for byte.

**Layer envelopes where the two engines' status differs** — structural
accounting, not a content comparison, and every one of them a boundary the port
declares rather than a disagreement it stumbled into:

| case | layer | statuses |
|---|---|---|
{differ_rows}

## Divergence classification

**Python-only 0 / Rust-only 0 / Changed 0 / Ordering-only n/a / Unexplained 0**,
over the {len(documents)}-document same-input set — the only cross-engine
quantity this slice measures.

It is enforced by a gate, not counted by this generator: the port asserts
per-document equality of the canonical identity and byte-exact equality of
every committed artifact, so a non-zero counter is not representable as a
passing build. *Ordering-only* is **not applicable** and is named rather than
reported as a zero that would mean something else — the canonical form sorts by
construction, so there is no ordered output being compared yet.

A classification over *layer contents* does not exist yet, and this document
does not invent one: the two engines' captures sit side by side in the
artifacts and nothing reads one against the other. The gates:

{gate_rows}

## The unmeasured set, named

- **End diagnostics compared as an acceptance surface** — #260's acceptance,
  blocked by #259 (cp5 and 4b). Not attempted, not approximated.
- **Any comparison of the two engines' layer contents.** The artifacts pair
  them; nothing reads the pair. That is the reduction checkpoint's job.
- **The `AnalysisTrace` schema** (#269) and **stable-ID normalization**, and
  **first-divergence reduction** over the lowered/MOS layers — the remaining
  step-7a checkpoints.
- **Rendered-byte parity of the three layer surfaces.** The artifact carries
  layer outputs as JSON *values*, so a rendering difference (indent,
  `ensure_ascii`) is invisible here. That contract stays with each layer's own
  fixture family (`tests/test_lowered_fixtures.py`,
  `tests/test_summaries_fixtures.py`, `tests/test_verdict_fixtures.py`).
- **The strict door.** Every layer in an artifact is projected through the
  **tolerant** door, so that the three entries describe one capture. Strict-door
  behaviour is Layer 1's own family (`own-ir`'s validation controls).
- **Engine build identity.** The artifact names *which* engine, never which
  build of it — a version stamp would make an artifact non-reproducible from
  the same inputs.
- **Nesting-depth agreement.** CPython's recursion limit and `serde_json`'s
  128-level cap differ; `spec/OwnIR.md` §4.2 bounds a conforming document
  well inside both, so no conforming document reaches the difference.

## Mutation campaigns

Definitions and recorded results live under
`docs/notes/p022-shadow-infra-checkpoint*-data/`. Every layer runs for every
mutation (P-022 discipline 3: no fail-fast), and every mutation edits a
**production** surface (discipline 2). The runs are recorded, not reproduced in
CI; what CI gates is that each definition still **anchors** to this tree and
that each recorded result is internally consistent
(`tests/test_generated_docs.py`).

{chr(10).join(campaign_blocks)}
"""


SURFACES = {
    "p022-shadow-census.md": render_shadow_slice,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not (args.write or args.check):
        ap.error("choose --write or --check")

    os.makedirs(GENERATED, exist_ok=True)
    stale: list[str] = []
    for name, render in sorted(SURFACES.items()):
        path = os.path.join(GENERATED, name)
        expected = render()
        if args.write:
            with open(path, "w", encoding="utf-8") as f:
                f.write(expected)
            print(f"wrote {path}")
            continue
        if not os.path.exists(path):
            stale.append(f"{name}: missing")
            continue
        with open(path, encoding="utf-8") as f:
            if f.read() != expected:
                stale.append(f"{name}: stale")
    for s in stale:
        print(f"ERROR: docs/generated/{s} — regenerate with "
              f"'python scripts/render_checkpoint_status.py --write'")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
