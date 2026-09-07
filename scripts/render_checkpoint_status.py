#!/usr/bin/env python3
"""Render the P-022 checkpoint status fragments from the evidence in the tree.

The status surfaces (the P-022 table, the proposals index, a checkpoint note)
say WHAT a checkpoint proves and link here; the measured numbers live only in
these generated fragments, computed from the evidence — never typed:

* `docs/generated/p022-cp4-census.md` — the Layer 3 census: the verdict ledger
  from `tests/verdict_census.compute_verdict_census()` and the rendered-surface
  family from `tests/verdict_render_census.compute_render_census()` (in both
  cases the same interpretation the fixture harnesses use). The filename is
  checkpoint 4's, because that is where the fragment was introduced and two
  notes link it; what it DESCRIBES is the current comparison surface, which the
  document says in its own first paragraph.
* `docs/generated/p022-cp5-inventory.md` — the checkpoint-5 SURFACE inventory,
  from `tests/verdict_surface_inventory.compute_surface_inventory()`: which
  BR-V4 wording branch, BR-V5 evidence family and BR-V9 rendered-surface rule
  the frozen goldens already reach, and which are not reached at all. The
  census counts the ledger; this one says what the ledger covers.
* `docs/generated/p022-cp4-mutations.md` — the recorded mutation campaign,
  from `docs/evidence/p022-cp4-mutations.json` and its `.result.json`, through
  `scripts/mutate_campaign.summarize()` (the same interpretation the runner
  prints).
* `docs/generated/p022-cp5-mutations.md` — checkpoint 5's recorded mutation
  campaigns, one section per sub-checkpoint, through the same
  `summarize()` as every other campaign in the tree.
* `docs/generated/p022-cp4b-mutations.md` — checkpoint 4b's two campaigns (the
  obligation ANALYSIS and its BRIDGE half), rendered the same way.
* `docs/generated/p022-shadow-census.md` — the step-7a (#260/#269)
  shadow-mode INFRASTRUCTURE census, from
  `tests/shadow_census.compute_shadow_census()` over the committed
  reproduction artifacts, traces and reductions.
* `docs/generated/p022-shadow-mutations.md` — that slice's four recorded
  campaigns, through the same `summarize()` as cp4's. One interpreter for
  every campaign in the tree: two readings of one run is how two documents
  come to disagree about it.

Determinism: nothing in a fragment depends on HEAD, the clock or the
environment, so an unrelated commit never changes one. The campaign fragment
carries the campaign's own provenance (the commit the run was taken on)
because that is data from the recorded run, not a property of the tree.

Usage:
  python scripts/render_checkpoint_status.py            # (re)write the fragments
  python scripts/render_checkpoint_status.py --check    # exit 1 when a committed fragment
                                                        # differs from the projection
`tests/test_checkpoint_status.py` runs `--check` in-process inside
`tests/run_tests.py`, so a change to the evidence without regenerating the
fragments turns the existing Python gate red.
"""

from __future__ import annotations

import difflib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("tests", "scripts"):
    _p = os.path.join(ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mutate_campaign import (  # noqa: E402  (sys.path set above)
    CampaignError,
    Definition,
    Result,
    Summary,
    load_definition,
    load_result,
    provenance_problems,
    summarize,
)
from shadow_census import ShadowCensus, ShadowCensusError, compute_shadow_census  # noqa: E402
from verdict_census import Census, CensusError, compute_verdict_census  # noqa: E402
from verdict_render_census import (  # noqa: E402
    RenderCensus,
    RenderCensusError,
    compute_render_census,
)
from verdict_surface_inventory import (  # noqa: E402
    Coverage,
    InventoryError,
    SurfaceInventory,
    compute_surface_inventory,
)

GENERATED = os.path.join(ROOT, "docs", "generated")
EVIDENCE = os.path.join(ROOT, "docs", "evidence")
CENSUS_MD = "p022-cp4-census.md"
INVENTORY_MD = "p022-cp5-inventory.md"
CP5_MUTATIONS_MD = "p022-cp5-mutations.md"
CP4B_MUTATIONS_MD = "p022-cp4b-mutations.md"
MUTATIONS_MD = "p022-cp4-mutations.md"
SHADOW_CENSUS_MD = "p022-shadow-census.md"
SHADOW_MUTATIONS_MD = "p022-shadow-mutations.md"
CAMPAIGN = os.path.join(EVIDENCE, "p022-cp4-mutations.json")
RESULT = os.path.join(EVIDENCE, "p022-cp4-mutations.result.json")
# One campaign per shadow checkpoint: each stays frozen at what it measured, so
# a later checkpoint cannot quietly restate an earlier one's numbers.
SHADOW_CAMPAIGNS = (
    ("checkpoint 1 — same-input capture and the reproduction artifact", "p022-shadow-cp1"),
    ("checkpoint 2 — the engine protocol", "p022-shadow-cp2"),
    ("checkpoint 3 — the AnalysisTrace and stable-ID normalization", "p022-shadow-cp3"),
    ("checkpoint 4 — first-divergence reduction", "p022-shadow-cp4"),
)
# One campaign per cp5 sub-checkpoint, for the same reason the shadow slice has
# one per checkpoint: a campaign stays frozen at what it measured, so a later
# sub-checkpoint cannot quietly restate an earlier one's numbers.
CP5_CAMPAIGNS = (
    ("checkpoint 5.1 — the message matrix and the evidence slices", "p022-cp5-1"),
    ("checkpoint 5.2 — the refusal text and the core message it quotes", "p022-cp5-2"),
    ("checkpoint 5.3 — the rendered surfaces", "p022-cp5-3"),
)
# Checkpoint 4b, on the same one-campaign-per-sub-checkpoint rule: the analysis
# and the bridge are measured separately because they fail separately — a walk
# that decides wrongly and a wording that phrases wrongly are different defects
# with different catchers.
CP4B_CAMPAIGNS = (
    ("checkpoint 4b.1 — the obligation analysis", "p022-cp4b-1"),
    ("checkpoint 4b.2 — the bridge mapping (BR-P3)", "p022-cp4b-2"),
)
SELF = "scripts/render_checkpoint_status.py"


def _header(sources: str) -> str:
    return (f"<!-- GENERATED by {SELF} from {sources}. Do not edit: regenerate with "
            f"`python {SELF}`; tests/run_tests.py fails while this file is stale. -->\n")


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


# --- census ---------------------------------------------------------------


def render_census(c: Census, r: RenderCensus | None) -> str:
    rows: list[tuple[str, str]] = [
        ("goldens — Python's complete truth, one per planned case", str(c.goldens))]
    for origin, n in c.by_origin:
        label = ("synthetic controls (`manifest.json` cases)" if origin == "synthetic"
                 else f"swept from `tests/fixtures/{origin}`")
        rows.append((f"… {label}", str(n)))
    rows += [
        ("reference refusals over all goldens", str(c.python_refusals)),
        ("reference findings over all goldens", str(c.python_findings)),
        ("declared Rust exclusions — the executable ledger `rust_replay_excluded`",
         str(c.excluded)),
    ]
    for refusal, contains, n in c.excluded_by_expectation:
        if refusal == "door":
            what = "… refused at the typed `OwnIr` door (#294 OD-1)"
        else:
            what = f"… refused by `check_facts` with an error containing `{contains}`"
        rows.append((what, str(n)))
    rows += [
        ("replayed by Rust (goldens minus exclusions)", str(c.replayed)),
        ("… reference refusals among them (compared in full)", str(c.replayed_refusals)),
        ("… findings among them (compared on every `Finding` member)",
         str(c.replayed_findings)),
    ]
    width = max(len(k) for k, _ in rows)
    lines = [
        _header("tests/fixtures/verdicts/ and tests/fixtures/verdict_renders/ "
                "(manifests + goldens)"),
        "# P-022 #259 — the Layer 3 measured census",
        "",
        "Computed by `tests/verdict_census.py` and `tests/verdict_render_census.py` (the "
        "interpretations the two fixture harnesses verify against the Python projections) "
        "over the frozen ledgers; the Rust halves are "
        "`rust/crates/own-bridge/tests/verdicts.rs` and `.../tests/renders.rs`.",
        "",
        "**The surface this describes is checkpoint 5's**: the verdict replay compares "
        "EVERY `Finding` member (`message`, `related` and `flow` included) and every "
        "refusal in full, and the rendered-surface replay compares bytes. At checkpoint 4 "
        "the same ledger was compared on identity, anchor, kind and tiering only, and "
        "refusals up to their `message=` member; the counts below are the ledger's either "
        "way, which is why one fragment serves both and says which surface it means.",
        "",
        f"| {'measure'.ljust(width)} | value |",
        f"|{'-' * (width + 2)}|------:|",
    ]
    lines += [f"| {k.ljust(width)} | {v} |" for k, v in rows]
    lines += [
        "",
        "The differential counts over the replayed set — Python-only, Rust-only, changed, "
        "ordering-only, unexplained — are asserted, not measured here: the Rust replay "
        "compares every replayed case's full ordered verdict list (or its refusal text) "
        "against the golden on every member, collects every divergence without fail-fast, "
        "and fails if one exists. A green `cargo test -p own-bridge --test verdicts` is "
        "0 / 0 / 0 / 0 / 0 by construction; a non-zero count is a red build.",
        "",
        "## The rendered surfaces (BR-V9)",
        "",
        "A second family, and a different kind of comparison: its replay compares the "
        "**bytes**, because SARIF key order is part of this surface. Cases are listed, "
        "never swept — one exists to exercise a BR-V9 rule, and which rows each pins is "
        "the join the [surface inventory](" + INVENTORY_MD + ") reports on.",
        "",
    ]
    if r is None:
        lines += ["The family could not be counted (see the gate's problems).", ""]
        return "\n".join(lines)
    render_rows = [
        ("cases — one per BR-V9 rule group, listed exhaustively in the manifest",
         str(r.cases)),
        ("… whose golden is a bridge refusal (nothing to render)", str(r.refusals)),
        ("rendered lines compared byte-for-byte (4 formats, 2 host severities)",
         str(r.rendered_lines)),
        ("SARIF results compared byte-for-byte (both host severities)",
         str(r.sarif_results)),
        ("BR-V9 ledger rows pinned by at least one case", str(r.pinned_rows)),
    ]
    width = max(len(k) for k, _ in render_rows)
    lines += [f"| {'measure'.ljust(width)} | value |", f"|{'-' * (width + 2)}|------:|"]
    lines += [f"| {k.ljust(width)} | {v} |" for k, v in render_rows]
    lines.append("")
    return "\n".join(lines)


# --- checkpoint 5: the surface inventory ----------------------------------


def _coverage_table(rows: tuple[Coverage, ...]) -> list[str]:
    """One ledger as a table: id, what it is, and the two measured counts. A row
    at zero over the replayed set is a gap, marked so a reader does not have to
    compare two numbers to find it."""
    out = ["| ledger row | surface | what it is | all goldens | replayed |",
           "|---|---|---|---:|---:|"]
    for c in rows:
        what = c.what
        if c.replayed == 0:
            what += f" — **not replayed**: {c.note}" if c.note else " — **GAP: no control**"
        out.append(f"| `{c.id}` | {c.detail} | {what} | {c.total} | {c.replayed} |")
    out.append("")
    return out


def render_inventory(inv: SurfaceInventory) -> str:
    """The cp5 surface ledger. Every count is matched out of the committed
    goldens by `tests/verdict_surface_inventory.py`; a finding or slice the
    ledger cannot place fails the gate rather than being rounded away."""
    lines = [
        _header("tests/fixtures/verdicts/*.verdicts.json through "
                "tests/verdict_surface_inventory.py"),
        "# P-022 checkpoint 5 — surface inventory (what the frozen goldens reach)",
        "",
        "Checkpoint 4 proved identity, anchor, kind and tiering over the replayed set "
        "([census](" + CENSUS_MD + ")). Checkpoint 5 proves the three surfaces cp4 "
        "carried without comparing: the **messages** (BR-V4), the **evidence slices** "
        "(BR-V5) and the **rendered surfaces** (BR-V9). This fragment is the "
        "completeness ledger for those three: every branch read off `ownlang/ownir.py`, "
        "matched against the committed goldens.",
        "",
        "`all goldens` counts Python's complete truth; `replayed` counts only the cases "
        "the Rust replay runs (the ledger's `rust_replay_excluded` entries removed). A "
        "row whose **replayed** count is zero is a branch the golden corpus does not "
        "prove; each such row carries its **disposition** — what pins the branch instead, "
        "and why no facts document can reach it. A zero row with no disposition reads "
        "`GAP: no control`, which is a missing control, not a passing one.",
        "",
        "## BR-V4 — message synthesis, by who owns the string",
        "",
        "`bridge` — synthesized by `check_facts` from the handle record; `core-analysis` "
        "— the `message` property of `ownlang/di.py` / `ownlang/effects.py`'s own "
        "finding; `core-diagnostic` — the core `Diagnostic.message`, interpolated "
        "verbatim; `bridge-protocol` — the OBL family (BR-P3), synthesized by the "
        "bridge from a violation the obligation analysis owns.",
        "",
    ]
    lines += _coverage_table(inv.messages)
    lines += ["### Wording tails", "",
              "Each is its own degradation rule inside an analysis message — the tail is "
              "dropped, not blanked, when its location is unknown.", ""]
    lines += _coverage_table(inv.tails)
    lines += ["## BR-V5 — evidence slices", "",
              "One row per `related`/`flow` family; a slice matching no family (or two) "
              "fails the gate.", ""]
    lines += _coverage_table(inv.slices)
    lines += ["### Degradations", "",
              "The rules that produce an EMPTY slice: a step whose line is unknown is "
              "omitted, and a slice left shorter than two steps is dropped. Counted "
              "separately, because a rule only ever seen firing positively has no "
              "negative control.", ""]
    lines += _coverage_table(inv.degradations)
    lines += ["## BR-V9 — rendered surfaces", ""]
    if inv.render_family_exists:
        lines += ["Coverage is matched out of the `tests/fixtures/verdict_renders/` "
                  "family's `pins` ledger.", ""]
    else:
        lines += ["**No fixture family exists yet.** `render_finding` and `build_sarif` "
                  "on the bridge path have no golden of their own: checkpoint 5.3 builds "
                  "`tests/fixtures/verdict_renders/`, and every row below reads zero "
                  "until it does. The rows are declared here so the gap is a ledger "
                  "entry rather than an omission.", ""]
    lines += _coverage_table(inv.renders)
    return "\n".join(lines)


# --- mutation campaign ----------------------------------------------------


def _load_campaign(campaign: str = CAMPAIGN,
                   result_path: str = RESULT) -> tuple[Definition | None, Result | None,
                                                       list[str]]:
    problems: list[str] = []
    definition: Definition | None = None
    result: Result | None = None
    if os.path.exists(campaign):
        try:
            definition = load_definition(campaign)
        except (CampaignError, OSError, ValueError) as e:
            problems.append(f"campaign definition unreadable: {e}")
    if definition is not None and os.path.exists(result_path):
        try:
            result = load_result(result_path)
        except (CampaignError, OSError, ValueError) as e:
            problems.append(f"campaign result unreadable: {e}")
    return definition, result, problems


def render_mutations(definition: Definition | None, result: Result | None,
                     summary: Summary | None) -> str:
    return _header(f"{_rel(CAMPAIGN)} and {_rel(RESULT)}") + "\n" + _mutation_section(
        "# P-022 checkpoint 4 — mutation campaign", definition, result, summary,
        CAMPAIGN, RESULT)


def _mutation_section(heading: str, definition: Definition | None, result: Result | None,
                      summary: Summary | None, campaign_path: str, result_path: str) -> str:
    CAMPAIGN, RESULT = campaign_path, result_path
    lines = [heading, ""]
    if definition is None:
        lines += ["No campaign definition is committed (expected at "
                  f"`{_rel(CAMPAIGN)}`).", ""]
        return "\n".join(lines)
    lines += [
        f"Campaign `{definition.campaign}` — {definition.description}",
        "",
        f"Definition: `{_rel(CAMPAIGN)}` (sha256 `{definition.sha256[:16]}…`, "
        f"{len(definition.mutations)} mutations). Replay on a clean tree with "
        f"`python scripts/mutate_campaign.py --campaign {_rel(CAMPAIGN)} --run`; the "
        "recorded run is raw outcomes and provenance, the counts below are derived from it.",
        "",
    ]
    if result is None or summary is None:
        lines += [f"**No recorded run** is committed (expected at `{_rel(RESULT)}`): the "
                  "campaign has a definition but no evidence. Nothing below is a number.", ""]
        return "\n".join(lines)
    ran = ("layers run (every one, for every mutation)" if result.layers
           else "packages tested (every workspace member, `--no-fail-fast`)")
    rows: list[tuple[str, str]] = [
        ("recorded at commit", f"`{summary.source_commit}`"),
        (ran, ", ".join(f"`{p}`" for p in result.ran)),
        ("mutations", str(summary.total)),
        ("caught", str(summary.caught)),
        ("survived", str(summary.survived)),
        ("compile-error (no evidence either way)", str(summary.compile_error)),
        ("invalid-mutation", str(summary.invalid)),
        ("runner-error", str(summary.runner_error)),
        ("caught without every expected catcher",
         ", ".join(summary.expected_catchers_missed) or "none"),
        (f"honesty control `{definition.control_id}` (unmutated tree must pass)",
         f"{result.control.outcome}" + (" — as required" if summary.control_ok else " — VOID")),
    ]
    width = max(len(k) for k, _ in rows)
    lines += [f"| {'measure'.ljust(width)} | value |", f"|{'-' * (width + 2)}|---|"]
    lines += [f"| {k.ljust(width)} | {v} |" for k, v in rows]
    if summary.problems:
        lines += ["", "**This run is not evidence:**", ""]
        lines += [f"- {p}" for p in summary.problems]
    lines += ["", "| id | rule | mutation | outcome | caught by |", "|---|---|---|---|---|"]
    recorded = {o.id: o for o in result.mutations}
    missed = set(summary.expected_catchers_missed)
    for m in definition.mutations:
        o = recorded.get(m.id)
        if o is None:
            outcome, by = "**not recorded**", "—"
        else:
            outcome = o.outcome
            if m.id in missed:
                outcome += " (a required catcher did not fail)"
            by = "<br>".join(f"`{c}`" for c in o.catchers) or (o.detail or "—")
        lines.append(f"| {m.id} | {m.rule or '—'} | {m.description} | {outcome} | {by} |")
    lines.append("")
    return "\n".join(lines)


# --- step 7a: the shadow-mode infrastructure slice ------------------------


def render_shadow_mutations() -> tuple[str, list[str]]:
    """The slice's four campaigns, one document, the same interpreter as cp4's."""
    return render_campaign_set(
        "# P-022 step 7a — shadow-mode infrastructure: mutation campaigns",
        "Every mutation edits a **production** surface (P-022 discipline 2) and every "
        "declared layer runs for every mutation (discipline 3: no fail-fast). Each "
        "campaign stays frozen at what it measured; the counts below are derived from "
        "the recorded runs by `scripts/mutate_campaign.summarize()`, never typed.",
        SHADOW_CAMPAIGNS)


def _campaign_paths(campaign: str) -> tuple[str, str]:
    return (os.path.join(EVIDENCE, f"{campaign}.json"),
            os.path.join(EVIDENCE, f"{campaign}.result.json"))


def render_campaign_set(heading: str, blurb: str, campaigns: tuple[tuple[str, str], ...],
                        ) -> tuple[str, list[str]]:
    """A set of campaigns as one document, through the single interpreter every
    campaign in the tree shares. Two readings of one run is how two documents
    come to disagree about it."""
    sources = ", ".join(_rel(_campaign_paths(c)[0]) for _, c in campaigns)
    parts = [_header(f"{sources} and their .result.json"), heading, "", blurb, ""]
    problems: list[str] = []
    for title, campaign in campaigns:
        definition_path, result_path = _campaign_paths(campaign)
        definition, result, load_problems = _load_campaign(definition_path, result_path)
        problems.extend(f"{campaign}: {p}" for p in load_problems)
        summary = summarize(definition, result) if definition and result else None
        if summary is not None and result is not None:
            problems.extend(f"{campaign}: {p}" for p in summary.problems)
            problems.extend(f"{campaign}: {p}" for p in provenance_problems(result))
        parts.append(_mutation_section(f"## {title}", definition, result, summary,
                                       definition_path, result_path))
    return "\n".join(parts), problems


def render_shadow_census(c: ShadowCensus) -> str:
    corpus_rows = "\n".join(f"| `tests/fixtures/{corpus}` | {n} |" for corpus, n in c.by_corpus)
    engine_rows = "\n".join(f"| `{eid}` | {produced} | {refused} | {full} | {partial} |"
                            for eid, produced, refused, full, partial in c.engines)
    differ_rows = ("\n".join(f"| `{case}` | `{layer}` | {shown} |"
                             for case, layer, shown in c.status_differs)
                   or "| — | — | the two engines' statuses agree everywhere |")
    gate_rows = "\n".join(f"- `own-shadow/tests/{target}::{name}`" for target, name in c.gates)
    scope = list(c.scope)
    return f"""{_header("tests/fixtures/repro/ (artifacts, traces, reductions)")}
# P-022 step 7a — shadow-mode infrastructure: census

**Infrastructure for shadow mode, not shadow mode.** Nothing measured here
compares two engines' end diagnostics — or any of their layer *contents*. That
comparison is #260's acceptance and is blocked on #259 (cp5 and 4b). Nothing
here is a parity claim either.

This document is the **live view** of the slice as it stands; the recorded
mutation campaigns are their own fragment
([`{SHADOW_MUTATIONS_MD}`]({SHADOW_MUTATIONS_MD})), each frozen at what it
measured. Where the slice departed from the brief it was given — the checkpoint
grouping, the `-0` domain decision, the `sha2` dependency — the departures are
decisions on the record in
[the owner-decision ledger](../notes/p022-shadow-infra-owner-decisions.md),
which also states the byte-level boundary repeated in the unmeasured set below.

## The measured set — same-input capture (checkpoint 1)

| corpus | documents |
|---|---|
{corpus_rows}
| **total** | **{c.documents}** |

Every one of those documents is canonicalized and hashed by the reference
(`ownlang/repro.py`) and re-hashed from the same file by the port
(`own-shadow`), which is what makes "both engines saw the same input" a
checked fact rather than an assumption — **at the level of canonical document
identity**. That is a weaker statement than #260's acceptance invariant, and
the difference is named in the unmeasured set below.

| surface | count |
|---|---|
| documents captured and digest-pinned | {c.documents} |
| tamper controls (one changed character per document, refusal required) | {c.documents} |
| documents both engines must REFUSE to name (`domain_refusals`) | {c.domain_refusals} |
| reproduction artifacts committed and replayed byte-for-byte | {c.artifacts} |
| structural negative controls on `verify` (each side) | {c.structural_controls} |
| value-level domain backstop controls | {c.domain_backstop_controls} |

## The engine protocol (checkpoint 2)

Each engine authors only its own `engines[]` entry, and declares per layer what
it could **produce**. Over the committed artifacts:

| engine | layers produced | layers refused | projection `full` | projection `partial` |
|---|---|---|---|---|
{engine_rows}

The port's `partial` column read non-zero until #259 cp5.1/5.2: its verdict
surface sat at the checkpoint-4 projection, carrying every `Finding` member
except `message`, `related` and `flow`, and said so in the artifact rather than
emitting a short document a later comparison would score as agreement. Those
members are ported, so the layer is `full` and no partial projection remains —
a fact about this port's progress, not a reason to drop the field. The check
moved with it: it now asserts a `full` claim against the complete Layer 3
record too, because a `full` declared over a short document is the over-claim
that became reachable the moment nothing was partial.

**Still not shadow mode, and still not the verdict layer entering it.** The
reducer REFUSES the verdict layer and records the refusal in every reduction;
what changed above is one engine's declaration of what it puts in the
envelope.

**Layer envelopes where the two engines' status differs** — structural
accounting, not a content comparison, and every one of them a boundary the port
declares rather than a disagreement it stumbled into:

| case | layer | statuses |
|---|---|---|
{differ_rows}

## The AnalysisTrace (checkpoint 3)

Each capture is normalized into a walkable shape: internal identifiers are
replaced by addresses derived from what they identify, and each layer's
ordering semantics are **declared** rather than normalized away.

| surface | count |
|---|---|
| trace layers projected (both engines, every artifact) | {c.trace_layers} |
| addressed steps | {c.trace_steps} |
| of those, handle addresses standing in for a mint counter | {c.stable_id_steps} |

The normalization is proven on the property it exists for, over the whole
captured corpus: permuting a document's components reshuffles the global mint
counters (BR-L2) so the raw handle names change wholesale, and the **stable
ids must not move** — while the lowered layer's step **order** must still
change, because that difference is real. Both halves are asserted; a trace that
hid the second would delete the defect the layer exists to expose.

## First-divergence reduction (checkpoint 4), and the classification

The reducer walks the pair in pipeline order over **{scope}** and names the
first place they part company: the layer, the step address and the *minimal*
difference inside it. The `verdicts` layer is **refused, not skipped** —
comparing final diagnostics is #260's acceptance, blocked by #259 — and the
refusal is carried in every reduction, so "not compared" can never be read as
"compared and agreed".

Over the {c.reductions} committed reductions, {c.identical} are
`identical`. The counters below are **computed** by the reducer, not implied by
a green build:

| class | count |
|---|---|
| Python-only (`left-only`) | **{c.by_class["left-only"]}** |
| Rust-only (`right-only`) | **{c.by_class["right-only"]}** |
| Changed | **{c.by_class["changed"]}** |
| Ordering-only | **{c.by_class["ordering-only"]}** |
| Unexplained | **{c.by_class["unexplained"]}** |
| *status* (a layer-level disagreement, each a declared boundary) | {c.by_class["status"]} |
| *projection* (surfaces not comparable member-for-member) | {c.by_class["projection"]} |

`status` and `projection` are counted apart from the four content classes on
purpose: neither is a difference in what an engine *computed*. Every `status`
row in the table above is a boundary the port declares in its own error text —
the unported obligation-protocol analysis, and the typed door.

The same-input layer carries its own counters, and those remain gate-enforced
rather than computed: the port asserts per-document equality of the canonical
identity and byte-exact equality of every committed artifact and trace, so a
non-zero counter there is not representable as a passing build. The gates:

{gate_rows}

## The unmeasured set, named

- **#260's raw-byte same-input invariant.** #260 asks that the `OwnIR`
  document be produced or loaded exactly once, that the **raw bytes** be
  hashed, and that *those exact bytes* reach both engines. What this slice
  proves is shared **canonical document identity**: each engine parses the
  file and agrees on the canonical form's digest. Canonical-equivalent input
  is not byte-identical input — two files differing in whitespace, in object
  key order, or in duplicate-key resolution share one canonical identity,
  because ignoring exactly those differences is the canonical form's job.
  Acceptance must therefore prove the byte-level invariant separately; until
  it does, "same input" here means canonical identity and nothing stronger
  ([owner decision B-1](../notes/p022-shadow-infra-owner-decisions.md)).
- **End diagnostics compared as an acceptance surface** — #260's acceptance,
  blocked by #259 (cp5 and 4b). Not attempted, not approximated.
- **The verdict layer.** Refused by the reducer, and recorded as refused in
  every reduction. This is the same blocker as the row above, stated where a
  tool could otherwise have quietly crossed it.
- **Nested statement bodies as individual steps.** A `then`/`else`/`while` body
  is part of its enclosing statement's step, so a difference inside a branch is
  reported on that statement rather than on the branch's own address.
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
"""


# --- fragments ------------------------------------------------------------


def fragments() -> tuple[dict[str, str], list[str]]:
    """name -> rendered content, plus the problems that make a fragment
    non-evidence (a broken ledger; a campaign result that does not match its
    definition, was taken on a dirty tree, missed a required catcher, or names
    a commit this tree does not descend from). The provenance check is the
    gate's, not the fragment's: it never changes the rendered text."""
    out: dict[str, str] = {}
    problems: list[str] = []
    renders: RenderCensus | None = None
    try:
        renders = compute_render_census()
    except RenderCensusError as e:
        problems.extend(f"rendered-surface census: {p}" for p in e.problems)
    try:
        out[CENSUS_MD] = render_census(compute_verdict_census(), renders)
    except CensusError as e:
        problems.extend(f"verdict census: {p}" for p in e.problems)
    try:
        out[INVENTORY_MD] = render_inventory(compute_surface_inventory())
    except InventoryError as e:
        problems.extend(f"cp5 surface inventory: {p}" for p in e.problems)
    definition, result, campaign_problems = _load_campaign()
    problems.extend(campaign_problems)
    summary = summarize(definition, result) if definition and result else None
    if summary is not None and result is not None:
        problems.extend(f"mutation campaign: {p}" for p in summary.problems)
        problems.extend(f"mutation campaign: {p}" for p in provenance_problems(result))
    out[MUTATIONS_MD] = render_mutations(definition, result, summary)
    try:
        out[SHADOW_CENSUS_MD] = render_shadow_census(compute_shadow_census())
    except ShadowCensusError as e:
        problems.extend(f"shadow census: {p}" for p in e.problems)
    shadow, shadow_problems = render_shadow_mutations()
    out[SHADOW_MUTATIONS_MD] = shadow
    problems.extend(f"mutation campaign {p}" for p in shadow_problems)
    cp5, cp5_problems = render_campaign_set(
        "# P-022 checkpoint 5 — mutation campaigns",
        "One campaign per sub-checkpoint, each frozen at what it measured. Every "
        "mutation edits a **production** surface (P-022 discipline 2) and every "
        "workspace member runs for every mutation (discipline 3: no fail-fast); the "
        "counts are derived from the recorded runs by "
        "`scripts/mutate_campaign.summarize()`, never typed.",
        CP5_CAMPAIGNS)
    out[CP5_MUTATIONS_MD] = cp5
    problems.extend(f"mutation campaign {p}" for p in cp5_problems)
    cp4b, cp4b_problems = render_campaign_set(
        "# P-022 checkpoint 4b — mutation campaigns",
        "The obligation-protocol family, measured in two halves: the ANALYSIS "
        "(`own-analysis/src/obligation.rs` plus the half of the shared grammar it "
        "reads) and the BRIDGE mapping (BR-P3 — codes, wordings, identity "
        "derivations, the evidence slice and the tolerant-door rules). Every "
        "mutation edits a **production** surface (P-022 discipline 2) and every "
        "workspace member runs for every mutation (discipline 3: no fail-fast); the "
        "counts are derived from the recorded runs by "
        "`scripts/mutate_campaign.summarize()`, never typed.",
        CP4B_CAMPAIGNS)
    out[CP4B_MUTATIONS_MD] = cp4b
    problems.extend(f"mutation campaign {p}" for p in cp4b_problems)
    return out, problems


def check() -> list[str]:
    """Every committed fragment must equal its projection, byte for byte."""
    rendered, problems = fragments()
    for name, want in rendered.items():
        path = os.path.join(GENERATED, name)
        if not os.path.exists(path):
            problems.append(f"{_rel(path)}: missing — run `python {SELF}`")
            continue
        with open(path, encoding="utf-8") as f:
            have = f.read()
        if have != want:
            diff = "".join(difflib.unified_diff(
                have.splitlines(keepends=True), want.splitlines(keepends=True),
                fromfile=f"{_rel(path)} (committed)", tofile=f"{_rel(path)} (projection)", n=1))
            problems.append(f"{_rel(path)}: stale — the evidence changed without "
                            f"regenerating it (run `python {SELF}`):\n{diff}")
    return problems


def write() -> list[str]:
    rendered, problems = fragments()
    os.makedirs(GENERATED, exist_ok=True)
    for name, content in rendered.items():
        path = os.path.join(GENERATED, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"wrote {_rel(path)}")
    return problems


def main(argv: list[str]) -> int:
    if argv and argv != ["--check"]:
        print(__doc__)
        return 2
    problems = check() if argv else write()
    for p in problems:
        print(f"FAIL: checkpoint status {p}")
    if problems:
        return 1
    if argv:
        print(f"checkpoint status fragments OK: {CENSUS_MD}, {INVENTORY_MD}, "
              f"{MUTATIONS_MD}, {CP5_MUTATIONS_MD}, {SHADOW_CENSUS_MD}, "
              f"{SHADOW_MUTATIONS_MD} in sync with the evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
