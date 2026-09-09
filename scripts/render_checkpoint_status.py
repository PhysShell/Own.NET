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
* `docs/generated/p022-cp1-census.md` — the checkpoint-1 strict-door ledger,
  counted from the ledger itself by `tests/validation_census.py`: controls by
  section, by verdict and by category, plus the coordinate family on its own.
  Three numbers about that ledger used to be typed on the P-022 table.
* `docs/generated/p022-coord-census.md` — every source coordinate the fixture
  tree carries, classified against the §4.2 domain, from
  `tests/coordinate_census.compute_coordinate_census()`. It is the measurement
  the coordinate-domain decision was taken against and the one the churn budget
  is checked with; it deliberately counts the GOLDENS too, because `0` staying
  a legal line is a property of the outputs, not of the door.
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
* `docs/generated/p022-coord-mutations.md` — final acceptance's two campaigns,
  split by door (strict / tolerant) rather than by sub-checkpoint.
* `docs/generated/p022-shadow-census.md` — the step-7a (#260/#269)
  shadow-mode INFRASTRUCTURE census, from
  `tests/shadow_census.compute_shadow_census()` over the committed
  reproduction artifacts, traces and reductions.
* `docs/generated/p022-shadow-mutations.md` — that slice's recorded
  campaigns, through the same `summarize()` as cp4's. One interpreter for
  every campaign in the tree: two readings of one run is how two documents
  come to disagree about it.
* `docs/generated/p022-shadow-sweep.md` — #260's FINAL-ACCEPTANCE sweep: the
  five pinned OSS repositories of #243, the large-solution controls and the
  examples tree, from `tests/shadow_sweep.compute_sweep_summary()` over the
  committed definition and one recorded run. The per-target denominators are
  the point of the document: a repository is not covered because its
  extraction succeeded.

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
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("tests", "scripts"):
    _p = os.path.join(ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coordinate_census import (  # noqa: E402
    CoordinateCensus,
    CoordinateCensusError,
    compute_coordinate_census,
)
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
from shadow_sweep import DEFINITION as DEFINITION_PATH  # noqa: E402
from shadow_sweep import (  # noqa: E402
    TARGET_FIELDS,
    SweepError,
    SweepSummary,
    compute_sweep_summary,
    load_pair,
)
from validation_census import (  # noqa: E402
    ValidationCensus,
    ValidationCensusError,
    compute_validation_census,
)
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
COORD_CENSUS_MD = "p022-coord-census.md"
CP1_CENSUS_MD = "p022-cp1-census.md"
INVENTORY_MD = "p022-cp5-inventory.md"
CP5_MUTATIONS_MD = "p022-cp5-mutations.md"
CP4B_MUTATIONS_MD = "p022-cp4b-mutations.md"
COORD_MUTATIONS_MD = "p022-coord-mutations.md"
MUTATIONS_MD = "p022-cp4-mutations.md"
CLI_CENSUS_MD = "p022-cli-census.md"
CLI_MUTATIONS_MD = "p022-cli-mutations.md"
STAGE1_MUTATIONS_MD = "p022-stage1-mutations.md"
SHADOW_CENSUS_MD = "p022-shadow-census.md"
SHADOW_MUTATIONS_MD = "p022-shadow-mutations.md"
SHADOW_SWEEP_MD = "p022-shadow-sweep.md"
CAMPAIGN = os.path.join(EVIDENCE, "p022-cp4-mutations.json")
RESULT = os.path.join(EVIDENCE, "p022-cp4-mutations.result.json")
# One campaign per shadow checkpoint: each stays frozen at what it measured, so
# a later checkpoint cannot quietly restate an earlier one's numbers.
SHADOW_CAMPAIGNS = (
    ("checkpoint 1 — same-input capture and the reproduction artifact", "p022-shadow-cp1"),
    ("checkpoint 2 — the engine protocol", "p022-shadow-cp2"),
    ("checkpoint 3 — the AnalysisTrace and stable-ID normalization", "p022-shadow-cp3"),
    ("checkpoint 4 — first-divergence reduction", "p022-shadow-cp4"),
    ("acceptance 1 — the artifact format and the byte-level attestation (B-2, B-3)",
     "p022-shadow-acc-1"),
    ("acceptance 2 — the scope, the boundary policy, the derived surface and the "
     "driver (D-4..D-7, R-1, R-2)", "p022-shadow-acc-2"),
    ("final acceptance — the driver's v2 surfaces and the sweep interpreter",
     "p022-shadow-sweep-1"),
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
# Final acceptance, split by DOOR rather than by sub-checkpoint: the strict
# door refuses and the tolerant one degrades, they fail differently, and a
# campaign that measured them together could not say which half a survivor
# belonged to.
COORD_CAMPAIGNS = (
    ("the strict door — the coordinate domain, both implementations", "p022-coord-1"),
    ("the tolerant door — the degrade, both implementations", "p022-coord-2"),
)
# P-022 step 7b (#261): the production OwnIR executable. One campaign, because
# the surface is one process contract — the display policy, the serialization
# and the exit codes fail together and are read together.
CLI_CAMPAIGNS = (
    ("261.B — `own-cli ownir`: the display policy, the CLI's SARIF bytes, the "
     "usage exit codes and the process contract", "p022-cli-1"),
)
# P-022 step 8 (#262) STAGE 1: the launcher's engine-selection contract. One
# campaign, because the surface is one seam — the selector, the candidate
# locator, the child-status mapping and the compare contract are read together
# and fail together.
STAGE1_CAMPAIGNS = (
    ("Stage 1 — the launcher's `--engine` contract: the default, the candidate "
     "locator, the Rust child status and the compare result contract",
     "p022-stage1-1"),
    ("Stage 1 — the surfaces only Windows can be asked about: `own-check.ps1`, "
     "and the drive-rooted arm of the shell's locator classifier. Measured on "
     "a WINDOWS runner, because a mutant of either is invisible to a Linux "
     "catcher",
     "p022-stage1-windows"),
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


# --- checkpoint 1: the strict-door ledger census ---------------------------


def render_validation_census(c: ValidationCensus) -> str:
    """The cp1 ledger, counted from the ledger itself.

    Three numbers about this ledger used to be typed on the P-022 table. They
    were true when written and are the kind that stops being true quietly, so
    the row links here instead."""
    lines = [
        _header("tests/fixtures/ownir_validation.json through tests/validation_census.py"),
        "# P-022 #259 checkpoint 1 — the strict-door ledger, counted",
        "",
        "`tests/fixtures/ownir_validation.json` is the frozen BR-D1 acceptance language, "
        "regenerated from the reference by "
        "`python tests/test_ownir_validation_fixtures.py --write` and replayed with zero "
        "Python by `own-ir/tests/validation_replay.rs`.",
        "",
        "**What the replay compares is accept/reject and, on a rejection, the CATEGORY — "
        "never the message text.** The reference funnels every rejection through one "
        "`OwnIRError` whose strings are a human-facing presentation aid, so byte-comparing "
        "them across two languages would freeze a debug surface as a contract. The "
        "`message` each record carries is Python's own, kept for the record rather than "
        "for the comparison. The matrix the replay asserts — agreed accepts, agreed "
        "rejects, Rust-only accepts, Rust-only rejects, kind mismatches — is a property "
        "of a green `cargo test -p own-ir`, not a number reproduced here: all three "
        "failure rows are zero or the build is red.",
        "",
        f"| {'measure'.ljust(30)} | value |",
        f"|{'-' * 32}|------:|",
        f"| {'controls'.ljust(30)} | {c.controls} |",
        f"| {'… accepted'.ljust(30)} | {c.accepted} |",
        f"| {'… rejected'.ljust(30)} | {c.rejected} |",
        "",
        "## By category",
        "",
        "Seven categories on two axes (`shape` is \"no representable primitive or "
        "container form\"; `location` is \"a representable coordinate violating its "
        "domain rule\"). The split is the one #326's census had to discover, and #259's "
        "final acceptance moved a family across it — an `i64::MAX` line was an accept, is "
        "now `location`, and `i64::MAX + 1` was and stays `shape`.",
        "",
        "| category | controls | what it means |",
        "|---|---:|---|",
    ]
    counts = dict(c.by_category)
    lines.append(f"| `accepted` | {counts.get('accepted', 0)} | the document is accepted |")
    for name, meaning in c.categories:
        lines.append(f"| `{name}` | {counts.get(name, 0)} | {meaning} |")
    lines += [
        "",
        "## By section",
        "",
        "The ledger's own grouping, which is BR-D1's check order. A section with "
        "acceptances and no rejections is a door nobody probed; one with rejections and "
        "no acceptance twin is a rejection nothing discriminates.",
        "",
        "| section | accepted | rejected | by category |",
        "|---|---:|---:|---|",
    ]
    for row in c.sections:
        detail = ", ".join(f"`{k}` {n}" for k, n in row.by_category) or "—"
        lines.append(f"| `{row.section}` | {row.accepted} | {row.rejected} | {detail} |")
    lines += [
        "",
        "## The coordinate family",
        "",
        "Every control whose document carries a `line`, `ctor_line` or `column` at any "
        "depth — the family #259's final acceptance moved, pulled out so a reviewer can "
        "find it without reading every record. Each line-bearing field is pinned at four "
        "points (`0` and `2147483647` accepted, `-1` and `2147483648` rejected), the two "
        "fields §4.2 used to record as validated nowhere carry type controls as well, and "
        "the flow-op line is pinned at every nesting shape because `then`/`else`/`body` "
        "are three separate recursion sites.",
        "",
        f"| {'measure'.ljust(34)} | value |",
        f"|{'-' * 36}|------:|",
        f"| {'coordinate-bearing controls'.ljust(34)} | {c.coordinate_controls} |",
        f"| {'… accepted'.ljust(34)} | {c.coordinate_accepted} |",
    ]
    for name, n in c.coordinate_by_category:
        if name == "accepted":
            continue
        lines.append(f"| {('… rejected `' + name + '`').ljust(34)} | {n} |")
    lines.append("")
    return "\n".join(lines)

# --- the CLI contract census ----------------------------------------------


class CliCensusError(Exception):
    """The CLI fixture cannot be read as evidence."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def compute_cli_census() -> tuple[list[tuple[str, int]], list[tuple[str, int]], int]:
    """`(by rule, by oracle, total)` over `tests/fixtures/cli_ownir/manifest.json`.

    Read from the manifest rather than counted by hand, for the reason every
    other census here exists: a number typed beside a fixture stops being true
    the first time somebody adds a case and does not stop LOOKING true.
    """
    path = os.path.join(ROOT, "tests", "fixtures", "cli_ownir", "manifest.json")
    if not os.path.isfile(path):
        raise CliCensusError([f"{_rel(path)} is missing"])
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CliCensusError([f"{_rel(path)} lists no cases"])
    by_rule: dict[str, int] = {}
    by_oracle: dict[str, int] = {}
    problems: list[str] = []
    for case in cases:
        name = case.get("name", "?")
        oracle = case.get("oracle")
        if oracle not in ("python", "python-docstring", "owen-convention"):
            problems.append(f"case {name!r} has an unknown oracle {oracle!r}")
            continue
        by_oracle[oracle] = by_oracle.get(oracle, 0) + 1
        rules = case.get("rules")
        if not isinstance(rules, list) or not rules:
            problems.append(f"case {name!r} names no rule it is the control for")
            continue
        for rule in rules:
            by_rule[str(rule)] = by_rule.get(str(rule), 0) + 1
    if problems:
        raise CliCensusError(problems)
    return sorted(by_rule.items()), sorted(by_oracle.items()), len(cases)


_ORACLE_MEANING = {
    "python": "an executed `python -m ownlang ownir` run",
    "python-docstring": "the same, where the bytes are the WHOLE module docstring on "
                        "stdout — frozen as measured and flagged, so the owner can "
                        "declare that class a defect knowing what was frozen",
    "owen-convention": "no Python byte oracle exists: the top-level shell, authored "
                       "once from the `owen` convention and shared with the binary",
}


def render_cli_census(census: tuple[list[tuple[str, int]], list[tuple[str, int]], int]) -> str:
    """The frozen CLI contract, counted from the fixture that is the contract."""
    by_rule, by_oracle, total = census
    lines = [
        _header("tests/fixtures/cli_ownir/manifest.json"),
        "# P-022 step 7b (#261) — the `own-cli ownir` contract, counted",
        "",
        "`tests/fixtures/cli_ownir/` is the frozen CLI contract, authoritative via "
        "`python tests/test_cli_ownir_fixtures.py --write` on Linux and replayed against "
        "the built binary with **zero Python** by `own-cli/tests/replay.rs` on Linux and "
        "Windows CI. Every case names the rule it is the control for and the oracle that "
        "authored its bytes; both tables below are read from the manifest.",
        "",
        f"| {'measure'.ljust(34)} | value |",
        f"|{'-' * 36}|------:|",
        f"| {'frozen cases'.ljust(34)} | {total} |",
        "",
        "## By oracle",
        "",
        "The oracle boundary is #261's C-1, and it is the SURFACE rather than the "
        "reference's internal print branch.",
        "",
        "| oracle | cases | what authored the bytes |",
        "|---|------:|---|",
    ]
    for oracle, count in by_oracle:
        lines.append(f"| `{oracle}` | {count} | {_ORACLE_MEANING[oracle]} |")
    lines += [
        "",
        "## By rule",
        "",
        "A case may be the control for more than one rule, so these do not sum to the "
        "case count — they say how much evidence each rule has, which is the question.",
        "",
        "| rule | cases |",
        "|---|------:|",
    ]
    for rule, count in by_rule:
        lines.append(f"| `{rule}` | {count} |")
    lines.append("")
    return "\n".join(lines)


# --- the coordinate census ------------------------------------------------


def render_coordinate_census(c: CoordinateCensus) -> str:
    """Every `line` / `column` slot in the fixture tree, by family, slot and
    value class. Computed by `tests/coordinate_census.py`; nothing here is
    typed, including the sentence about what did not move."""
    lines = [
        _header("tests/fixtures/**/*.json through tests/coordinate_census.py"),
        "# P-022 #259 final acceptance — the source-coordinate census",
        "",
        "The measurement the coordinate-domain decision (`spec/OwnIR.md` §4.2) was "
        "taken against: every `line`, `ctor_line` and `column` slot in every JSON file "
        "under `tests/fixtures/`, at any depth and under any key.",
        "",
        "It is wider than the door on purpose. A **door slot** sits on an OwnIR "
        "*document* and `load()` rules on it; every other row is an **observation** — "
        "a golden, a ledger, a captured trace — which the door never sees and which "
        "this change must therefore leave alone. `0` stays a legal line (the "
        "reference's own default for an absent one), so the observation rows anchored "
        "at zero are the records the decision must go on accepting, and a census that "
        "read only the inputs could not see them at all.",
        "",
        "Value classes follow the cp1 taxonomy's axis rather than blurring it: "
        "`outside-int64` has no representable integer form (`Shape`), while `negative` "
        "and `above-int32` are representable coordinates violating the domain rule "
        "(`Location`). `below-1` is the column's own 1-based rule.",
        "",
        f"| {'measure'.ljust(34)} | value |",
        f"|{'-' * 36}|------:|",
        f"| {'JSON files scanned'.ljust(34)} | {c.files} |",
        f"| {'coordinate slots found'.ljust(34)} | {c.coordinates} |",
        "",
        "## By value class",
        "",
        "| value class | all slots | door slots |",
        "|---|---:|---:|",
    ]
    door = dict(c.door_by_class)
    for value_class, n in c.by_class:
        lines.append(f"| `{value_class}` | {n} | {door.get(value_class, 0)} |")
    lines += [
        "",
        "## By family and slot",
        "",
        "`door` marks a slot the strict door rules on. Examples are shown for every "
        "class outside `in-domain` / `null` / `zero`, because those are the values a "
        "reader needs to see rather than count.",
        "",
        "| family | slot | class | door | count | files | values |",
        "|---|---|---|:--:|---:|---:|---|",
    ]
    for row in c.rows:
        shown = ", ".join(f"`{e}`" for e in row.examples) or "—"
        lines.append(
            f"| `{row.family}` | `{row.path}` | `{row.value_class}` | "
            f"{'yes' if row.door else '—'} | {row.count} | {row.files} | {shown} |")
    lines += [
        "",
        "## Slot inventory reachability",
        "",
        "`tests/coordinate_census.SLOTS` is the door inventory, and it is asserted as "
        "a set rather than spot-checked: a declared slot no fixture reaches is a "
        "phantom claiming coverage it does not have.",
        "",
    ]
    if c.unreachable_slots:
        lines += [f"- **unreachable**: `{slot}`" for slot in c.unreachable_slots]
        lines.append("")
    else:
        lines += ["Every declared slot is reached by at least one fixture.", ""]
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




# --- step 7a: #260's final-acceptance sweep --------------------------------


def render_sweep(summary: SweepSummary) -> str:
    """The sweep, as the one document every count in the packet links to.

    The per-target block is not decoration: #250's fifth failure mode is a
    green gate over an empty set, so the DENOMINATOR is rendered beside the
    outcome for every target, and a target with nothing compared is visible
    rather than absent."""
    document_rows = "\n".join(
        f"| `{d.id}` | `{d.target}` | {d.extraction_mode} | `{d.target_commit[:12]}` | "
        f"{d.raw_bytes} | `{d.raw_digest[:12]}` | `{d.canonical_digest[:12]}` | "
        f"{d.reduction_outcome} | {d.derived_outcome} | {d.declared_boundary} | "
        f"{d.unexplained} | {d.wall_clock_seconds:.2f} | {d.timeout_seconds:.0f} |"
        for d in summary.documents)
    target_rows = "\n".join("| `" + row[0] + "` | " + " | ".join(row[1:]) + " |"
                             for row in summary.targets)
    totals_row = ("| **total** | "
                  + " | ".join(str(summary.totals[name]) for name in TARGET_FIELDS)
                  + " |")
    adapter_rows = "\n".join(f"| `{digest}` | {size} |"
                             for digest, size in summary.adapters)
    doc_head = " | ".join((
        "document", "target", "mode", "pin", "raw bytes", "raw sha256",
        "canonical sha256", "reduction", "derived SARIF", "declared-boundary",
        "unexplained", "wall clock (s)", "timeout (s)"))
    doc_align = "|---|---|---|---|---:|---|---|---|---|---:|---:|---:|---:|"
    target_head = " | ".join((
        "target", "extracted", "compared", "agreed", "diverged",
        "execution failures", "input refusals", "input disagreements",
        "declared-boundary", "unexplained"))
    target_align = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    where = (f"[the workflow run]({summary.workflow_run_url})"
             if summary.workflow_run_url
             else "a local run (no workflow run URL)")
    unexplained = summary.totals.get("acceptance_unexplained_observations", 0)
    verdict = (
        "Every document agreed and no observation is acceptance-unexplained."
        if unexplained == 0 and all(d.outcome == "agreed" for d in summary.documents)
        else "**This run is NOT clean.** A document did not agree, or an "
             "observation is acceptance-unexplained: that is a finding, it "
             "stays on the record until it is resolved, and #260 stays open.")
    return f"""{_header(_rel(DEFINITION_PATH) + " and its .result.json")}
# P-022 step 7a (#260) — the final-acceptance sweep

The measurement the acceptance surfaces over the committed corpus deliberately
did not take: the five pinned OSS repositories of #243 at their pinned commits,
the large/multi-project solution controls, and the `examples/` tree. Every
document is one OwnIR byte sequence fed to BOTH engines and judged by compare
mode; the record is [`{_rel(DEFINITION_PATH)}`](../evidence/p022-shadow-sweep.json)
(what should be measured) and its `.result.json` (one actual run), read by
`tests/shadow_sweep.py`. {verdict}

**What "covered" means here.** A repository is not covered because extraction
succeeded, and a solution is not covered because some project inside it emitted
OwnIR. Coverage is a recorded, non-empty set of documents fed byte-identically
to both engines and judged — per target, with the denominator on the record.
A run that compared zero documents is a failure, and so is a declared target
nothing reached.

## The run

| what | value |
|---|---|
| Own.NET commit | `{summary.source_commit}` |
| recorded at | {summary.recorded_at} |
| host | {summary.host} |
| where | {where} |
| driver | `shadow_compare_version` {summary.driver_version} |

The adapter each leg executed, by digest — a path is not an identity, so a
stale build cannot stand in for the engine that was meant:

| `own-shadow-engine` sha256 | bytes |
|---|---:|
{adapter_rows}

## The documents

| {doc_head} |
{doc_align}
{document_rows}

## The denominators, per target

| {target_head} |
{target_align}
{target_rows}
{totals_row}
"""


def render_shadow_census(c: ShadowCensus) -> str:
    corpus_rows = "\n".join(f"| `tests/fixtures/{corpus}` | {n} |" for corpus, n in c.by_corpus)
    engine_rows = "\n".join(f"| `{eid}` | {produced} | {refused} | {full} | {partial} |"
                            for eid, produced, refused, full, partial in c.engines)
    differ_rows = ("\n".join(f"| `{case}` | `{layer}` | {shown} |"
                             for case, layer, shown in c.status_differs)
                   or "| — | — | the two engines' statuses agree everywhere |")
    gate_rows = "\n".join(f"- `own-shadow/tests/{target}::{name}`" for target, name in c.gates)
    boundary_rows = ("\n".join(f"| `{case}` | `{layer}` | {acceptance} | `{cls}` |"
                                for case, layer, acceptance, cls in c.boundaries)
                     or "| — | — | — | the reducer made no observation at all |")
    derived_rows = "\n".join(f"| `{case}` | {outcome} |"
                              for case, outcome in c.derived_outcomes)
    scope = list(c.scope)
    return f"""{_header("tests/fixtures/repro/ (artifacts, traces, reductions)")}
# P-022 step 7a — shadow-mode infrastructure: census

**Compare mode over the committed corpus — one leg of #260's test matrix.**
What is measured here is every document this repository commits, at all three
layers and on the derived SARIF surface, on byte-attested same input. The five
pinned OSS repositories, the large-solution controls and the examples tree are
the OTHER legs and have their own record
([`{SHADOW_SWEEP_MD}`]({SHADOW_SWEEP_MD})); nothing below may be read as shadow
mode having been achieved, as P-022 being done, or as Rust being the default.

This document is the **live view** of the slice as it stands; the recorded
mutation campaigns are their own fragment
([`{SHADOW_MUTATIONS_MD}`]({SHADOW_MUTATIONS_MD})), each frozen at what it
measured. Every place the work departed from the brief it was given, and every
decision it was blocked on, is on the record in
[the owner-decision ledger](../notes/p022-shadow-infra-owner-decisions.md):
the checkpoint grouping, the `-0` domain narrowing and the `sha2` dependency
from the infrastructure slice, and D-4..D-7 / B-2 / B-3 / R-1 / R-2 for the
acceptance work.

## The measured set — same-input capture (checkpoint 1)

| corpus | documents |
|---|---|
{corpus_rows}
| **total** | **{c.documents}** |

Every one of those documents is canonicalized and hashed by the reference
(`ownlang/repro.py`) and re-hashed from the same file by the port
(`own-shadow`). Since artifact **v3** that claim is byte-level rather than
canonical-level (owner decision B-2): the artifact carries `input.raw` — the
byte-exact input — and every engine entry carries `consumed`, the identity of
what THAT engine read, taken before any decode or parse. Verification walks the
chain end to end, and every `consumed` comes from an execution of the engine
that claims it (B-3): nothing computes one from `input.raw`, and the reference
refuses to carry a foreign entry that has none rather than filling one in.

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

**Layer envelopes where the two engines' status differs** — structural
accounting, not a content comparison. Every one of them is a boundary the port
DECLARES, structurally, in its own capture (`boundary: {{"class", "detail"}}`
on the refused layer record), rather than a disagreement it stumbled into:

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

## First-divergence reduction, and the two-axis classification

The reducer walks the pair in pipeline order over **{scope}** — every layer,
the verdict layer included (owner decision D-4) — and names the first place
they part company: the layer, the step address and the *minimal* difference
inside it. `REDUCTION_SCOPE` **is** `LAYER_ORDER`, aliased rather than copied,
and `out_of_scope` stays in the schema and is empty: the member is the slot a
future exclusion would occupy, so "nothing is excluded" stays distinguishable
from "the field went away".

Over the {c.reductions} committed reductions, {c.identical} are `identical` and
{c.declared} are `declared-boundary`. The counters below are **computed** by
the reducer, not implied by a green build.

**By kind** — what was seen:

| kind | count |
|---|---|
| Python-only (`left-only`) | **{c.by_class["left-only"]}** |
| Rust-only (`right-only`) | **{c.by_class["right-only"]}** |
| Changed | **{c.by_class["changed"]}** |
| Ordering-only | **{c.by_class["ordering-only"]}** |
| *status* (a layer-level disagreement about whether it produced) | {c.by_class["status"]} |
| *projection* (surfaces not comparable member-for-member) | {c.by_class["projection"]} |
| *missing-layer* (an engine did not report the layer) | {c.by_class["missing-layer"]} |

**By acceptance** — whether it is explained (owner decision D-5):

| acceptance | count |
|---|---|
| `unexplained` | **{c.by_acceptance["unexplained"]}** |
| `declared-boundary` | {c.by_acceptance["declared-boundary"]} |

The two axes are separate fields because they are different questions, and
neither is recoverable from the other. Every **content** observation — on every
layer, `summaries` and `verdicts` included — is `unexplained` by construction:
the frozen boundary policy is not consulted for one, so a known class attached
to a `changed` cannot explain it even in principle. A `status` or `projection`
observation is a `declared-boundary` only when its structured class and its
`(layer, kind)` match an exact entry of the frozen policy, whose three entries
are the OD-1 typed door on each of the three layers. `detail` never
participates: matching on it would make the judgement depend on wording.

**Every observation, with its judgement and the class the refusing engine
declared:**

| case | layer | acceptance | declared class |
|---|---|---|---|
{boundary_rows}

## The derived SARIF surface (owner decision D-6)

Canonical SARIF is a #260 zero-diff acceptance surface and **not** an
`AnalysisTrace` layer: it is not in `LAYER_ORDER`, it has no step addressing,
and no reduction walks it. Each engine renders it from its **own** verdict
layer, under one frozen, named configuration — `{c.derived_configuration}` —
recorded in the artifact rather than assumed, because two engines rendering the
same findings under different severities would differ for a reason that is not
a divergence. The artifact carries the **identity**; the full documents are
retained by the compare driver on mismatch only.

Three outcomes, and they are three rather than two because "the renderers
disagree" and "there was nothing to compare" are different findings:

| case | derived outcome |
|---|---|
{derived_rows}

Every case where **both** engines produce a verdict layer is `equal`. Every
`not-comparable` case is one where at least one engine refused that layer, so
nothing was rendered to compare — and they come in **two** shapes, which is
worth stating because the acceptance work was written expecting one:

* the two **OD-1 door** documents, where the port's typed door refuses and the
  reference does not (an asymmetric refusal, a `status` observation, a declared
  boundary);
* two documents where **both** engines refuse the verdict layer for the same
  reason — `vocab_unknown_op` (an unknown flow op: extractor/core vocabulary
  skew) and `hoist_neg_while_body` (the BR-V3 map-or-raise class). These are
  `identical` at the layer and still `not-comparable` on the derived surface,
  because "the two engines agree that they refused" is not "the two engines
  rendered the same document".

That second shape is a measurement rather than a prediction, and folding it
into the first would have been a claim the corpus does not support.

`renderer-only divergence` is therefore a real classification rather than a
spare word: it can only be reported when the verdict layers agree and the
rendered bytes do not, and the renderer is then the only thing left.

The same-input layer carries its own counters, and those remain gate-enforced
rather than computed: the port asserts per-document equality of the canonical
identity and byte-exact equality of every committed artifact and trace, so a
non-zero counter there is not representable as a passing build. The gates:

{gate_rows}

## The unmeasured set, named

- **The five-repository sweep and the large-solution controls.** #260's test
  matrix names them, and nothing here runs them. What is measured is the
  **committed corpus**; the sweep is separate work with its own commands and
  its own recorded artifacts, and until it is taken this slice is not #260's
  acceptance.
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
        out[CP1_CENSUS_MD] = render_validation_census(compute_validation_census())
    except ValidationCensusError as e:
        problems.extend(f"cp1 ledger census: {p}" for p in e.problems)
    try:
        out[COORD_CENSUS_MD] = render_coordinate_census(compute_coordinate_census())
    except CoordinateCensusError as e:
        problems.extend(f"coordinate census: {p}" for p in e.problems)
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
    try:
        sweep_summary = compute_sweep_summary(*load_pair())
        out[SHADOW_SWEEP_MD] = render_sweep(sweep_summary)
        problems.extend(f"shadow sweep: {p}" for p in sweep_summary.problems)
    except SweepError as e:
        problems.extend(f"shadow sweep: {p}" for p in e.problems)
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
    coord, coord_problems = render_campaign_set(
        "# P-022 #259 final acceptance — mutation campaigns",
        "The coordinate-domain contract, measured in two halves because the two doors "
        "fail differently: the STRICT door refuses an out-of-domain coordinate and the "
        "TOLERANT one degrades it to absent. Every rule is mutated on BOTH sides — the "
        "reference and its Rust mirror — since a domain only one implementation enforces "
        "is a divergence, not a rule. Every mutation edits a **production** surface "
        "(P-022 discipline 2) and every declared layer runs for every mutation "
        "(discipline 3: no fail-fast); the counts are derived from the recorded runs by "
        "`scripts/mutate_campaign.summarize()`, never typed.",
        COORD_CAMPAIGNS)
    out[COORD_MUTATIONS_MD] = coord
    problems.extend(f"mutation campaign {p}" for p in coord_problems)
    try:
        out[CLI_CENSUS_MD] = render_cli_census(compute_cli_census())
    except CliCensusError as e:
        problems.extend(f"cli contract census: {p}" for p in e.problems)
    cli, cli_problems = render_campaign_set(
        "# P-022 step 7b (#261) — mutation campaigns",
        "The production OwnIR executable's contract: the display policy the reference's "
        "`cmd_ownir` defines, the CLI's own SARIF serialization conventions (which are "
        "NOT the BR-V9 fixture emitter's), the usage-error exit codes, and the process "
        "contract — a catchable panic is one actionable diagnostic and exit 70, never "
        "101. Every mutation is a plausible MISREADING of the reference rather than a "
        "syntactic accident: each one would pass a reviewer who had read the module "
        "docstring instead of the code. Every mutation edits a **production** surface "
        "(P-022 discipline 2) and every declared layer runs for every mutation "
        "(discipline 3: no fail-fast) — including the layer that enables the "
        "off-by-default `fault-injection` feature, without which the two failure-mode "
        "controls could not be seen to catch anything. The counts are derived from the "
        "recorded run by `scripts/mutate_campaign.summarize()`, never typed.",
        CLI_CAMPAIGNS)
    out[CLI_MUTATIONS_MD] = cli
    problems.extend(f"mutation campaign {p}" for p in cli_problems)
    stage1, stage1_problems = render_campaign_set(
        "# P-022 step 8 (#262) Stage 1 — mutation campaigns",
        "Stage 1 makes the Rust core SELECTABLE by the launcher while Python stays the "
        "default and the reference. Every mutation below is a plausible MISREADING of "
        "that contract rather than a syntactic accident: the default moved because the "
        "cutover was read as already decided; Python resolved for every engine because "
        "the old unconditional resolution looked harmless; 70 admitted to the verdict "
        "set because both engines document it; an unexpected child status propagated "
        "as itself because that looked like faithfulness; the shell falling back to "
        "Python because answering the user looked helpful. Each would pass a reviewer "
        "who had read the stage's summary instead of its rulings. Every mutation edits "
        "a **production** launcher surface (P-022 discipline 2), and the single layer "
        "REBUILDS the launcher before testing it — a mutated `.cs` file is otherwise "
        "invisible to controls that drive a compiled binary — and runs every control "
        "for every mutation with no fail-fast (discipline 3), under "
        "`OWEN_STAGE1_REQUIRE=1` so a control that could not run is a failure rather "
        "than a silently shrinking denominator. The counts are derived from the "
        "recorded run by `scripts/mutate_campaign.summarize()`, never typed.",
        STAGE1_CAMPAIGNS)
    out[STAGE1_MUTATIONS_MD] = stage1
    problems.extend(f"mutation campaign {p}" for p in stage1_problems)
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
        print(f"checkpoint status fragments OK: {CENSUS_MD}, {CP1_CENSUS_MD}, "
              f"{COORD_CENSUS_MD}, {INVENTORY_MD}, {MUTATIONS_MD}, {CP5_MUTATIONS_MD}, "
              f"{SHADOW_CENSUS_MD}, {SHADOW_MUTATIONS_MD}, {SHADOW_SWEEP_MD}, "
              f"{STAGE1_MUTATIONS_MD} in sync with the evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
