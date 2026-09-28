#!/usr/bin/env python3
"""P-037 Phase B: the frozen difference classifier (B1).

docs/notes/p037-formal-kernel.md's B1 section states the honest limit this
module works inside: today's rust/crates/own-bridge/src/mos.rs carries
exactly ONE flat Transfer per parameter (No/Must/May/Unknown) -- no Election,
no Shape::Split, no Cells pair, no per-edge Transform/Mask, no per-call-site
selection or its license. None of that is a missing DUMP; it is a missing
REPRESENTATION, and adding the representation is the semantic treatment
itself (explicitly out of scope for B1). So this module cannot be handed a
single REAL captured difference and prove it belongs to one of the three
classes -- there is no real difference to hand it yet, and no instrument
that could honestly produce the fields the rule needs before the guarded
types exist.

What CAN be built now, and IS built here, matching §10.4/§10.1's own
"measurement/classification tooling is in scope, semantics are not":

1. WITNESS, a frozen, versioned schema for what a future guarded-aware
   trace must record about one coordinate or call site -- named fields only,
   in the vocabulary docs/proposals/P-037-guarded-effect-summaries.md and
   formal/p037-kernel/ already use and have proved (Transfer, Cells, Shape,
   Election, Transform, Selection, collapse/finalize). This is the contract
   a real treatment's own trace output will be checked against later; it is
   frozen here so the treatment does not invent its own ad hoc shape.
2. `classify(witness)`, the (now four, see CLOSED_CLASSES' own comment)
   CLOSED classes plus UNCLASSIFIED, decided from WITNESS fields alone --
   never from a file path, a fixture name or a diagnostic code (§10.1's own
   rule, repeated in the B1 brief). Tested here
   against SYNTHETIC witnesses built by hand from the proposal's own worked
   rows (18-19, K11b), the same way formal/p037-kernel/'s Kani harnesses are
   tested against hand-built System values with no production code existing
   yet -- proving the LOGIC is correct against the frozen CONTRACT, not that
   any real mos.rs output will ever conform to it. That binding happens only
   once B-after evidence exists to classify for real.
3. (B1-F2-F4) `derive_document_witnesses(legacy_doc, new_doc)`, the real
   witness-derivation adapter GAP_REAL_WITNESS_SOURCE below used to name as
   permanently missing. It reads two `dump_summaries`-shaped documents
   (`{"summaries": [{"method", "params": [{"index","transfer",...}], ...}]}`
   -- the exact byte-parity shape both `ownlang/ownir.py::dump_summaries`
   and `rust/crates/own-bridge/src/dump.rs::dump_summaries` already emit)
   STRUCTURALLY: every (method, param) pair present in both, comparing
   `transfer` values. Forbidden inputs, enforced by construction (there is
   no parameter through which one could enter): a fixture filename, a
   directory name, a diagnostic code, a handwritten per-case allowlist, or
   "this difference is expected because P-037". Parameters are named
   generically (`legacy_doc`/`new_doc`), not `python_doc`/`rust_doc`,
   because B1-F2-F4-R1 reuses this same adapter for TWO distinct axes:
   `p037_mos_snapshot.py`'s `divergence_status()` calls it intra-document
   (Python plays `legacy_doc`, Rust plays `new_doc`) AND `compare()` calls
   it inter-snapshot, before-Rust-vs-after-Rust (before plays `legacy_doc`,
   after plays `new_doc`) -- the classifier does not know or care which
   engine or which snapshot produced either side, only that `legacy_doc` is
   the reference a divergence is measured AGAINST and `new_doc` is the
   value a `guarded` field must justify. A `guarded` field on the `new_doc`
   side's per-parameter object (the field this module's own
   `rust_param_witness_shape()` reads) is the forward-compatible contract a
   future B2.1b/c dump-surface extension must populate (docs/evidence/
   p037-b-epoch.json's b1_f2_f4_findings.summary_dump_surface_for_class_3)
   -- today NO production dump emits it, so every derived witness is
   `shape: "uncond"` with `collapsed` equal to whatever the new side's own
   `transfer` says. This is not a stub standing in for missing logic: run
   today, against the UNCHANGED (pre-treatment) population, Python and
   Rust always report the same `transfer` for every (method, param), so
   this adapter correctly derives ZERO divergent witnesses -- proven in
   `selftest()` against REAL summaries documents (`python -m ownlang
   summaries` over a real corpus file), not just literal witness dicts.
   The moment a real divergence exists with no `guarded` field to justify
   it, `classify()`'s OWN existing, already-tested branch ("an uncond shape
   differing from legacy has no guard-mediated explanation available at
   all") returns UNCLASSIFIED on its own -- this adapter adds no new
   class-decision logic of its own, only the plumbing from a captured
   document pair to a WITNESS.
4. A named, permanent GAP note (GAP_REAL_WITNESS_SOURCE below) for the part
   that STILL cannot be built: mos.rs's ParamSkeleton/ParamSummary/Transfer
   model (and its dump) has no Split shape, Cells pair, or per-edge
   Transform/Mask REPRESENTATION at all, so no real B2.1b/c-shaped `guarded`
   value can be POPULATED before that treatment's own types exist -- the gap
   is about the missing representation, never about missing plumbing to
   read one once it exists. Building that representation is the treatment's
   own first deliverable, not a B1/B1-F2-F4 retrofit onto mos.rs/lower.rs/
   dump.rs (which stay semantically untouched throughout) -- see the formal
   note's B1 and B1-F2-F4 sections for the full reasoning, including why
   legacy-side provenance (PathAction origins, which forwards release
   priority drops, a per-call-site consumed-transfer-and-outcome record
   with column) COULD technically be added without any guard concept, but
   is deliberately NOT added here: threading it through lower.rs in
   isolation, then extending it again once guard-awareness lands, is less
   coherent than doing both together as part of the first treatment.
5. (amendment, post-B1) `check_call_site_witness`/`classify_call_site`, a
   SECOND, separately-typed witness for a real, measured shape the
   (method,param) SUMMARY WITNESS above cannot represent at all: a call site
   whose CALLER has no disposable parameter of its own to carry a
   coordinate (U1's own shape -- `Use` acquires its resource as a LOCAL,
   never as a parameter, so no `dump_summaries` row exists for `Use` full
   stop, yet the call site's own lowering/verdict genuinely moves across the
   same three measured states as U2/U3's summary-level movement does). This
   is not a workaround bolted onto WITNESS; it is a distinct, honestly-named
   evidence kind for a distinct thing being observed (a call site's own
   applied behavior, not a method's own summary), classified into the SAME
   closed class vocabulary `classify()` uses. Frozen here, exactly like the
   summary WITNESS originally was in B1: no production code emits one yet
   (mos.rs/lower.rs/dump.rs stay untouched by this amendment), tested only
   against synthetic and real-measured-by-hand witnesses; wiring a real
   emitter is the eventual R1-replay's own deliverable, not this amendment's.

Run:  python scripts/p037_b_classifier.py selftest
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parent.parent

APPLICATION_REFINEMENT = "APPLICATION_REFINEMENT"
SUMMARY_REFINEMENT = "SUMMARY_REFINEMENT"
LEGACY_HONESTY = "LEGACY_HONESTY"
CONDITIONALITY_HONESTY = "CONDITIONALITY_HONESTY"
UNCLASSIFIED = "UNCLASSIFIED"

CLOSED_CLASSES = (APPLICATION_REFINEMENT, SUMMARY_REFINEMENT, LEGACY_HONESTY,
                  CONDITIONALITY_HONESTY)

# --- amendment (post-B1, pre-new-T_B; see docs/evidence/p037-b-epoch.json's
# appended supersession entry for the full record) ---------------------------
# U1/U2/U3 (a direct call, a bare-forward wrapper, and the same wrapper with a
# defensive dispose after it -- all built around a NON-static, non-literal
# `bool` guard argument) measured, against the real pipeline at three states
# (pre-B2.1a, post-B2.1a-pre-B2.1b/c, and the held B2.1b/c-R1 treatment), a
# real, user-visible verdict/advisory movement that none of the original three
# classes covers: legacy's OWN scalar engine collapses a genuinely
# conditional callee (`if (!keep) s.Dispose();`) to a single extreme --
# `must` when the pre-B2.1a extractor fabricates an unconditional release at
# the delegating call site, `no` once B2.1a degrades that fabrication to a
# bare `use` -- and the guarded solver now honestly reconstructs the real
# Split(no,must)/Split(must,no) shape, which an UNSELECTED call site collapses
# to `may` (INF-A1: Plain, OWN051). `may` is neither `<= no` nor `<= must` in
# this module's own `_LEQ` table, so this is provably never SUMMARY_
# REFINEMENT (which requires an order-preserving improvement); it is not
# APPLICATION_REFINEMENT (no static selection exists at either measured
# state); and it is not LEGACY_HONESTY (`collapsed` is `may`, not `unknown`
# -- class 3 is a narrower, different shape). The module docstring's original
# point 2 claim -- "the three CLOSED classes plus UNCLASSIFIED" cover every
# observable difference -- was therefore FALSE, discovered only once a real
# `guarded` representation existed to measure against (B2.1b/c-R1, not B1).
# CONDITIONALITY_HONESTY names this fourth, narrowly-scoped shape: a
# recovered, genuinely conditional callee, no static selection, collapsing to
# `may` because the branch outcome is honestly UNRESOLVED at this site --
# never a lattice regression, a precision LOSS that is a semantic HONESTY
# gain. The other three classes' own predicates are UNCHANGED by this
# amendment (see `classify()`'s own reasoning below for why the new check
# cannot overlap SUMMARY_REFINEMENT's shape by construction).

GAP_REAL_WITNESS_SOURCE = (
    "no pre-treatment mechanism in this repository can populate a WITNESS "
    "with real data: mos.rs's ParamSkeleton/ParamSummary/Transfer model has "
    "no guard, Split shape, Cells pair, or per-edge Transform/Mask, and "
    "lower_fn_params/unverified_transfer_calls/kill_sites_for_unverified "
    "resolve a bare Transfer, never a licensed selection over two cells. "
    "This classifier is contract-complete and tested against synthetic "
    "witnesses (see selftest()); wiring it to real B-after evidence is the "
    "first semantic treatment's own deliverable, not B1's."
)

Transfer = Literal["no", "must", "may", "unknown"]
_TRANSFER_VALUES = ("no", "must", "may", "unknown")
# INF-L1/L2, formal/p037-kernel/src/lib.rs's own Transfer::leq: no < may,
# must < may, may < unknown; no and must are INCOMPARABLE (neither refines
# the other); unknown is top. Bot is not representable in mos.rs today (see
# module docstring) so it is not a member of this closed set at all. Each
# key maps to the set of values it is <= (itself included).
_LEQ: dict[Transfer, frozenset[Transfer]] = {
    "no": frozenset({"no", "may", "unknown"}),
    "must": frozenset({"must", "may", "unknown"}),
    "may": frozenset({"may", "unknown"}),
    "unknown": frozenset({"unknown"}),
}


def leq(a: Transfer, b: Transfer) -> bool:
    return b in _LEQ[a]


def lower(t: Transfer) -> str:
    """INF-A1, the closed vocabulary the B1 epoch record's application_rule
    already states: must -> consume, no -> borrow, may/unknown -> plain."""
    return {"must": "consume", "no": "borrow", "may": "plain", "unknown": "plain"}[t]


# R1-review of 20b09c9 (independent pushed-byte review, held-T_B repair):
# a selection_license carrying a truthy `kind` was accepted as licensing
# WHATEVER selection the witness itself claimed, never checked against what
# that license actually licenses -- a fabricated `{"kind": "bool_const",
# "value": false}` claiming `selection: "pos"` (or any unknown `kind`
# string) passed validation. Fixed by grounding the license->selection
# relationship in the frozen R1 PRODUCTION definition (mechanically read
# from the held R1 worktree's rust/crates/own-bridge/src/lower.rs, never
# guessed from the raw own_ir::GuardedArgKind vocabulary alone):
# `classify_guard_call_arg()` maps BoolConst true/false to ConstPos/ConstNeg,
# NullLiteral unconditionally to ConstNeg (a literal `null` takes a `g !=
# null` guard's false branch), ObjectCreation unconditionally to ConstPos (a
# fresh `new T(...)` is provably non-null); `call_arg_selection()` then maps
# ConstPos/ConstNeg to Selection::Pos/Neg. Param/Var/CallResult/Opaque never
# produce a static selection at all (Selection::Unselected) -- they are
# outside this vocabulary's domain, not mapped to `None` by omission.
_STATIC_LICENSE_SELECTIONS: dict[str, str] = {
    "null_literal": "neg",
    "object_creation": "pos",
}

# Independently measured so far: ONLY bool_const, via AR1/AR2's own real
# captured witnesses (both `{"kind": "bool_const", "value": true}`).
# null_literal/object_creation's mapping above is read directly from frozen
# production source, not guessed -- but has never been exercised by a real
# captured witness end to end. classify_call_site() below limits
# APPLICATION_REFINEMENT to this measured set for now; a consistent but
# unmeasured license classifies UNCLASSIFIED, a case review at B_after, per
# the same review. classify()'s own, older SUMMARY witness path is
# unaffected by this narrower scope -- only licensed_selection()'s
# CORRECTNESS fix (below) applies there, not this measured-evidence limit.
_MEASURED_CALL_SITE_LICENSE_KINDS: frozenset[str] = frozenset({"bool_const"})


def licensed_selection(license_: Any) -> str | None:
    """What Selection this selection_license object actually licenses --
    `"pos"`, `"neg"`, or `None` if it licenses no fixed selection at all (an
    unknown/missing `kind`, or a `bool_const` with a missing or non-bool
    `value`). Shared by BOTH check_witness()/classify() (the summary
    witness) and check_call_site_witness()/classify_call_site() (the
    call-site witness): a witness's claimed `selection` is never trusted
    merely because a selection_license object with a truthy `kind` is
    present -- it must equal what THIS function says that license actually
    licenses, checked mechanically, never assumed.

    `value is True`/`value is False` (identity, not `==`) deliberately reject
    a non-bool truthy/falsy stand-in (`1`, `"true"`, `1.0`) -- the same
    bool-is-int trap this codebase's own OwnIR door work is elsewhere
    careful to avoid."""
    if not isinstance(license_, dict):
        return None
    kind = license_.get("kind")
    if kind == "bool_const":
        value = license_.get("value")
        if value is True:
            return "pos"
        if value is False:
            return "neg"
        return None
    if isinstance(kind, str) and kind in _STATIC_LICENSE_SELECTIONS:
        return _STATIC_LICENSE_SELECTIONS[kind]
    return None


class WitnessError(Exception):
    """A witness is malformed against the frozen schema -- refused, not
    guessed through, same discipline as every other P-037 audit script."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise WitnessError(msg)


def check_witness(w: dict[str, Any]) -> None:
    """Validates WITNESS shape. Does not classify -- classify() calls this
    first and refuses (raises) rather than guessing past a malformed shape."""
    _require(isinstance(w, dict), "witness must be an object")
    _require(isinstance(w.get("coordinate"), dict), "witness.coordinate must be an object")
    coord = w["coordinate"]
    _require(isinstance(coord.get("method"), str) and coord["method"],
             "coordinate.method must be a non-empty string")
    _require(isinstance(coord.get("param"), int), "coordinate.param must be an integer")
    _require(w.get("legacy_transfer") in _TRANSFER_VALUES,
             f"legacy_transfer must be one of {_TRANSFER_VALUES}")
    guarded = w.get("guarded")
    _require(isinstance(guarded, dict), "witness.guarded must be an object")
    assert isinstance(guarded, dict)  # narrows for mypy; _require already enforced it at runtime
    _require(guarded.get("shape") in ("uncond", "split"), "guarded.shape must be uncond|split")
    if guarded["shape"] == "split":
        cells = guarded.get("finalized_cells")
        _require(isinstance(cells, dict) and cells.get("pos") in _TRANSFER_VALUES
                 and cells.get("neg") in _TRANSFER_VALUES,
                 "guarded.finalized_cells must be {pos,neg} Transfer values for a split shape")
        _require(guarded.get("selection") in ("pos", "neg", "unselected"),
                 "guarded.selection must be pos|neg|unselected for a split shape")
        if guarded["selection"] in ("pos", "neg"):
            _require(licensed_selection(guarded.get("selection_license")) == guarded["selection"],
                     "a pos/neg selection needs a selection_license that actually licenses "
                     "that exact selection (checked mechanically against the frozen R1 "
                     "production mapping) -- never a merely-present license object with any "
                     "truthy kind")
        _require(guarded.get("collapsed") in _TRANSFER_VALUES,
                 "guarded.collapsed must be a Transfer value")
    else:
        _require(guarded.get("selection") is None,
                 "an uncond shape has no call-site selection")
        _require(guarded.get("collapsed") in _TRANSFER_VALUES,
                 "guarded.collapsed must be a Transfer value even for uncond (diagonal)")
    site = w.get("site")
    if site is not None:
        _require(isinstance(site, dict) and isinstance(site.get("file"), str)
                 and isinstance(site.get("line"), int) and isinstance(site.get("column"), int),
                 "site, when present, must carry file/line/column")


def classify(w: dict[str, Any]) -> dict[str, Any]:
    """Returns {"class": one of CLOSED_CLASSES or UNCLASSIFIED, "reason": str}.

    Decision order (checked, not guessed): the overlap check runs FIRST,
    ahead of every narrow-shape class including LEGACY_HONESTY -- a witness
    that happens to satisfy a narrow shape's own condition (e.g. collapsed=
    unknown against legacy=may) while ALSO carrying an independent pos/neg
    selection is exactly the overlap the proposal's rows 1-19 do not settle,
    regardless of which narrow shape it also matches; checking any narrow
    shape first would silently resolve that overlap in that shape's favor,
    which is itself an invented priority rule (a §10.1 case-5 event this
    classifier refuses to make). Only once overlap is excluded does
    LEGACY_HONESTY get to claim the witness (the narrowest, most specific
    shape -- a collapsed value of exactly `unknown` against a legacy `may`,
    both lowering to `plain`); then, for a `split` shape, whether a
    call-site SELECTION was actually made (APPLICATION_REFINEMENT) or not
    (SUMMARY_REFINEMENT then rests on the COLLAPSED value alone).

    An earlier version of this function checked LEGACY_HONESTY before the
    overlap test, so a witness satisfying BOTH conditions at once (legacy=
    may, collapsed=unknown, split shape, selection=pos) was misclassified
    as LEGACY_HONESTY -- caught by owner review, not by this module's own
    selftest, whose overlap case used collapsed=must (not unknown) and so
    never exercised the intersection. selftest() now has a dedicated
    hostile case for exactly that intersection.

    Amendment (post-B1): a split, unselected witness that is neither
    SUMMARY_REFINEMENT nor an ordering violation is checked once more,
    against CONDITIONALITY_HONESTY's own narrow shape, before falling
    through to the final "collapsed is not <= legacy" UNCLASSIFIED case --
    see CLOSED_CLASSES' own comment for why this new shape provably cannot
    overlap SUMMARY_REFINEMENT's.
    """
    check_witness(w)
    guarded = w["guarded"]
    legacy_t: Transfer = w["legacy_transfer"]
    collapsed: Transfer = guarded["collapsed"]
    legacy_lowered = lower(legacy_t)
    guarded_lowered = lower(collapsed)

    selected = guarded["selection"]
    collapse_differs = collapsed != legacy_t
    has_selection = guarded["shape"] == "split" and selected in ("pos", "neg")

    if has_selection and collapse_differs:
        return {"class": UNCLASSIFIED,
                "reason": "both a call-site selection and a collapsed-value difference are "
                          "present at once; the proposal's rows 1-19 do not settle which "
                          "class this is, and this classifier does not invent a priority "
                          "rule for it (that would be new semantics, a case-5 event)"}

    class_3_shape = collapsed == "unknown" and legacy_t == "may"
    if class_3_shape and legacy_lowered == guarded_lowered == "plain":
        return {"class": LEGACY_HONESTY,
                "reason": "collapsed=unknown against legacy=may, both lower to plain (G-T2b "
                          "class 3, the K11b amendment's own declared verdict-equivalent case)"}

    if guarded["shape"] == "split":
        if selected in ("pos", "neg"):
            license_ = guarded["selection_license"]
            return {"class": APPLICATION_REFINEMENT,
                    "reason": f"call site selected the {selected} cell via {license_['kind']}; "
                              "the split summary already existed, only the final selection is "
                              "new (G-A1/G-A2 route 1)"}
        if collapse_differs and leq(collapsed, legacy_t) and collapsed != legacy_t:
            return {"class": SUMMARY_REFINEMENT,
                    "reason": f"no call-site selection; the summary's own collapsed value "
                              f"({collapsed}) is strictly below legacy ({legacy_t}) before any "
                              "site decides anything"}
        # CONDITIONALITY_HONESTY (amendment, see CLOSED_CLASSES' own comment):
        # deliberately narrow, structural, no fixture/path/diagnostic-code
        # input -- exactly legacy collapsed to ONE extreme of a genuinely
        # conditional callee, unselected, recovered as Split(no,must) (either
        # orientation) collapsing to `may`. This can NEVER also satisfy the
        # SUMMARY_REFINEMENT branch above: that branch requires
        # `leq(collapsed, legacy_t)`, and `_LEQ` makes `leq("may", "no")` and
        # `leq("may", "must")` both False by construction (no/must are the
        # two INCOMPARABLE bottom-ish points; may sits strictly above both) --
        # so the two branches are mutually exclusive on this shape, not
        # ordered by a priority choice.
        cells = guarded["finalized_cells"]
        is_recovered_conditional = (
            collapsed == "may" and legacy_t in ("no", "must")
            and {cells["pos"], cells["neg"]} == {"no", "must"}
        )
        if collapse_differs and is_recovered_conditional:
            return {"class": CONDITIONALITY_HONESTY,
                    "reason": f"no call-site selection; legacy ({legacy_t}) is a scalar "
                              "collapse of a genuinely conditional callee that the guarded "
                              "solver now honestly represents as a real Split(no,must) (finalized "
                              "cells {no,must} in either orientation) -- collapse is `may` "
                              "because the branch outcome is unresolved at this unselected site, "
                              "never a lattice regression (`may` is neither <= `no` nor <= "
                              "`must`), a precision loss that is a conditionality-honesty gain"}
        if not collapse_differs:
            return {"class": UNCLASSIFIED,
                    "reason": "a split shape with no selection and no collapsed-value "
                              "difference from legacy is not a difference at all"}
        return {"class": UNCLASSIFIED,
                "reason": f"collapsed ({collapsed}) is not <= legacy ({legacy_t}); a guarded "
                          "value must refine (or equal) legacy, never regress past it "
                          "(G-T2/G-T2b's own ordering) -- this witness violates that ordering"}

    # uncond: no split, no call-site selection is even meaningful
    if collapsed != legacy_t:
        return {"class": UNCLASSIFIED,
                "reason": "an uncond (uncond-shaped) coordinate differing from legacy has no "
                          "guard-mediated explanation available at all -- none of the three "
                          "classes covers an unguarded coordinate's own value changing"}
    return {"class": UNCLASSIFIED,
            "reason": "uncond shape, collapsed equals legacy: not a difference"}


# ------------------------------------------------------------ real witness derivation (B1-F2-F4)


def rust_param_witness_shape(param: dict[str, Any]) -> dict[str, Any]:
    """The `guarded` sub-object of a WITNESS, from a Rust MOS dump's own
    per-parameter object. A `guarded` key is the forward-compatible field a
    future B2.1b/c dump-surface extension must populate (see this module's
    docstring, point 3); its absence -- every real dump today -- means no
    recorded justification exists, represented honestly as an unconditional
    shape whose collapsed value is exactly whatever `transfer` already
    says."""
    guarded = param.get("guarded")
    transfer = param.get("transfer")
    if not isinstance(guarded, dict):
        return {"shape": "uncond", "selection": None, "selection_license": None,
               "finalized_cells": None, "collapsed": transfer}
    return {
        "shape": guarded.get("shape", "uncond"),
        "selection": guarded.get("selection"),
        "selection_license": guarded.get("selection_license"),
        "finalized_cells": guarded.get("finalized_cells"),
        "collapsed": guarded.get("collapsed", transfer),
    }


def build_witness(method: str, param_index: int, legacy_transfer: Any,
                  rust_param: dict[str, Any]) -> dict[str, Any]:
    """One WITNESS from structured data alone: the method/param coordinate,
    the Python (legacy/reference) summary's own `transfer`, and the Rust
    summary's own per-parameter object. No site is attached here -- a
    `dump_summaries` per-method record carries a method-level `line`, not a
    per-parameter coordinate, and `site` is optional in the WITNESS schema
    precisely for callers with nothing better than that to offer."""
    return {
        "coordinate": {"method": method, "param": param_index},
        "site": None,
        "legacy_transfer": legacy_transfer,
        "guarded": rust_param_witness_shape(rust_param),
    }


def _summaries_by_method(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in doc.get("summaries", []) or []:
        if isinstance(s, dict) and isinstance(s.get("method"), str):
            out[s["method"]] = s
    return out


def _params_by_index(summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for p in summary.get("params", []) or []:
        if isinstance(p, dict) and isinstance(p.get("index"), int):
            out[p["index"]] = p
    return out


def derive_document_witnesses(legacy_doc: dict[str, Any],
                              new_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every (method, param) whose `transfer` differs between two
    `dump_summaries`-shaped documents, each as {coordinate, legacy_transfer,
    new_transfer, witness, classification}. STRUCTURED data only (method
    names, parameter ordinals, transfer values, and the new side's own
    optional `guarded` field) -- see this module's docstring, point 3, for
    the forbidden-input list this signature makes structurally impossible
    to violate (there is no fixture-path or diagnostic-code parameter to
    read one from), and for why the parameters are named generically
    (`legacy_doc`/`new_doc`) rather than after one specific pair of callers.
    Returns the empty list whenever the two documents agree everywhere,
    which is every real document pair measured before a B2.1b/c-shaped
    divergence exists."""
    legacy_by_method = _summaries_by_method(legacy_doc)
    new_by_method = _summaries_by_method(new_doc)
    out: list[dict[str, Any]] = []
    for method in sorted(set(legacy_by_method) & set(new_by_method)):
        legacy_params = _params_by_index(legacy_by_method[method])
        new_params = _params_by_index(new_by_method[method])
        for idx in sorted(set(legacy_params) & set(new_params)):
            legacy_t = legacy_params[idx].get("transfer")
            new_t = new_params[idx].get("transfer")
            if legacy_t == new_t:
                continue
            witness = build_witness(method, idx, legacy_t, new_params[idx])
            try:
                verdict = classify(witness)
            except WitnessError as exc:
                verdict = {"class": UNCLASSIFIED, "reason": f"malformed witness: {exc}"}
            out.append({"coordinate": dict(witness["coordinate"]), "legacy_transfer": legacy_t,
                       "new_transfer": new_t, "witness": witness, "classification": verdict})
    return out


def explain_divergence(legacy_doc: dict[str, Any], new_doc: dict[str, Any]) -> dict[str, Any]:
    """Whether `derive_document_witnesses`'s classified witnesses account for
    the ENTIRE difference between two `dump_summaries` documents, not merely
    for the `transfer` values they name.

    Generic over WHICH two documents are being compared -- see this module's
    docstring point 3 and `derive_document_witnesses`'s own docstring for why
    the parameters are `legacy_doc`/`new_doc`, not `python_doc`/`rust_doc`:
    `p037_mos_snapshot.py` calls this both intra-document (Python as
    `legacy_doc`, Rust as `new_doc`, deciding epoch-b `is_evidence`) and
    inter-snapshot (before-Rust as `legacy_doc`, after-Rust as `new_doc`,
    deciding whether a Phase-B before/after MOS movement is classifiable).
    Both call sites need the identical "does a classified transfer change
    explain the WHOLE document" discipline; only which two documents play
    the two roles differs.

    A `dump_summaries` document carries more than per-parameter `transfer`
    (returns, unresolved, degraded, module, per-summary file/line/source);
    the classifier's WITNESS vocabulary explains transfer divergences only.
    So this reconstructs `legacy_doc` with EVERY witness's classified
    `new_transfer` patched onto its own (method, param) and nothing else,
    then requires the result to equal `new_doc` EXACTLY, modulo the one
    field this comparison must not penalize: a `guarded` key on the new
    side's own per-parameter object (the forward-compatible evidence field
    `rust_param_witness_shape` reads) never appears on the legacy side by
    design in the Python-vs-Rust use (Python is discharged of ever learning
    P-037, docs/evidence/p037-b-epoch.json's
    prerequisite_discharged.engine_scope_consequence) -- and cannot appear
    on a BEFORE-Rust snapshot either, since no production dump emits it yet
    (see point 3). Either way, its presence on the new side alone is
    exactly what a WITNESS already justified, not a second, unexplained
    difference, so both documents are compared with that key stripped from
    every parameter. Any OTHER leftover difference (a
    `returns`/`unresolved`/`degraded` movement, a method appearing in one
    document and not the other, or simply an UNCLASSIFIED witness) still
    makes `explained` False.
    """
    witnesses = derive_document_witnesses(legacy_doc, new_doc)
    if any(w["classification"]["class"] == UNCLASSIFIED for w in witnesses):
        return {"explained": False, "witnesses": witnesses,
               "reason": "at least one witness is UNCLASSIFIED"}
    patched = copy.deepcopy(legacy_doc)
    by_method = _summaries_by_method(patched)
    for w in witnesses:
        method, idx = w["coordinate"]["method"], w["coordinate"]["param"]
        for p in by_method.get(method, {}).get("params", []) or []:
            if isinstance(p, dict) and p.get("index") == idx:
                p["transfer"] = w["new_transfer"]
    if _strip_guarded_fields(patched) != _strip_guarded_fields(new_doc):
        return {"explained": False, "witnesses": witnesses,
               "reason": "classified transfer changes do not account for the whole document "
                         "difference; something outside the witness vocabulary also moved"}
    return {"explained": True, "witnesses": witnesses}


def _strip_guarded_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """A deep copy of `doc` with every per-parameter `guarded` key removed --
    the one field `explain_divergence` must not treat as an unexplained
    residual (see its own docstring)."""
    out = copy.deepcopy(doc)
    for s in out.get("summaries", []) or []:
        if not isinstance(s, dict):
            continue
        for p in s.get("params", []) or []:
            if isinstance(p, dict):
                p.pop("guarded", None)
    return out


# --------------------------------------------------- call-site witness (amendment, post-B1)
#
# A SEPARATE schema from WITNESS above, not a variant of it. WITNESS names a
# (method, param) SUMMARY coordinate; a call-site witness names one CALL SITE
# inside some caller, whose own summary coordinate may not exist at all (U1's
# `Use`: the resource is a LOCAL, `Use` itself has no disposable parameter, so
# there is no (method,param) row anywhere for a `guarded` field to attach to
# -- yet the call site's own applied behavior still moves, measurably, across
# the same three states U2/U3's summary witness moves across). Contorting
# WITNESS to represent this by inventing a fake caller parameter would be
# describing something that is not there; this is a distinct, honestly-typed
# evidence kind for a distinct thing being observed instead.


def check_call_site_witness(w: dict[str, Any]) -> None:
    """Validates a CALL_SITE_WITNESS. Refuses (raises), never guesses past a
    malformed shape -- same discipline as check_witness().

    Fields: `site` (file/line/column of the call), `callee` (the first-party
    method named at that site) and `callee_param` (which of ITS parameters
    is guarded), `resource_name` (the CALLER's own local/parameter name for
    the resource passed at `callee_param` -- e.g. `"s"` -- carried so a
    consumer can independently CONFIRM a claimed correlation against a real
    diagnostic's own message text, never merely trust a claimed line/code;
    see p037_verdict_snapshot.py's own observation-binding design),
    `resource_acquire_site` (`{"line": int}` or `None` -- the line a REAL
    before-side diagnostic about this resource, if any, would be anchored
    at; `None` when no single acquire line applies), `guarded` (that callee
    parameter's OWN finalized shape/cells/collapsed -- the SAME
    representation WITNESS.guarded uses, read from the same solved object,
    never re-derived), `selection` (this call site's own Pos/Neg/Unselected,
    #175's own vocabulary), and `lowered` (what #175's apply() actually
    produced at this site: consume/borrow/plain).

    Deliberately NO `legacy` field (an earlier draft had one: a free-text
    `observation` plus a closed `action`, meant to name what the UNGUARDED
    engine concluded here). Dropped, not merely unused: a REAL Rust producer
    mints this witness from ITS OWN computed state alone and has no channel
    to what a SEPARATE, independently-run Python analysis concluded at mint
    time -- asking it to fill `legacy.action` would force either a guess
    (exactly the "not measured" shape this whole file refuses) or plumbing
    a second engine's output into the first, which is not this contract's
    job. The question `legacy.action` was for -- is there a REAL before-side
    diagnostic this call site's own recovery explains -- is answered more
    rigorously elsewhere, by `p037_verdict_snapshot.py`'s own independent
    `resource_acquire_site` correlation against the ACTUAL captured
    before-snapshot (observation binding, not a witness-side claim); a
    witness with no acquire site to check simply explains no before-side key
    at all, which is honest, not a gap.
    """
    _require(isinstance(w, dict), "call-site witness must be an object")
    _require(w.get("kind") == "call_site", 'call-site witness must carry kind: "call_site"')
    site = w.get("site")
    _require(isinstance(site, dict) and isinstance(site.get("file"), str) and site["file"]
             and isinstance(site.get("line"), int) and isinstance(site.get("column"), int),
             "call-site witness.site must carry a non-empty file and integer line/column")
    _require(isinstance(w.get("callee"), str) and w["callee"],
             "call-site witness.callee must be a non-empty string")
    _require(isinstance(w.get("callee_param"), int),
             "call-site witness.callee_param must be an integer ordinal")
    _require(isinstance(w.get("resource_name"), str) and w["resource_name"],
             "call-site witness.resource_name must be a non-empty string (the caller-side "
             "name a real diagnostic's own message can be checked against)")
    acquire = w.get("resource_acquire_site")
    _require(acquire is None
             or (isinstance(acquire, dict) and isinstance(acquire.get("line"), int)),
             "call-site witness.resource_acquire_site must be null or {line: int}")
    _require(w.get("selection") in ("pos", "neg", "unselected"),
             "call-site witness.selection must be pos|neg|unselected")
    guarded = w.get("guarded")
    _require(isinstance(guarded, dict), "call-site witness.guarded must be an object")
    assert isinstance(guarded, dict)  # narrows for mypy; _require already enforced it at runtime
    _require(guarded.get("shape") in ("uncond", "split"), "guarded.shape must be uncond|split")
    if guarded["shape"] == "split":
        cells = guarded.get("finalized_cells")
        _require(isinstance(cells, dict) and cells.get("pos") in _TRANSFER_VALUES
                 and cells.get("neg") in _TRANSFER_VALUES,
                 "guarded.finalized_cells must be {pos,neg} Transfer values for a split shape")
    else:
        # CH3-8: an uncond shape has no split to select between -- the same
        # constraint check_witness() already enforces for the summary-level
        # witness's own guarded.selection, ported here now that a call-site
        # selection is a real, checked field rather than always "unselected".
        _require(w.get("selection") == "unselected",
                 "an uncond call-site guarded shape has no call-site selection to make")
    _require(guarded.get("collapsed") in _TRANSFER_VALUES,
             "guarded.collapsed must be a Transfer value")
    # CH3-8: selection_license, added for APPLICATION_REFINEMENT -- the SAME
    # requirement check_witness() already enforces for the summary-level
    # witness's own guarded.selection_license (a pos/neg selection needs a
    # license naming what licensed it), at this witness kind's own top level
    # rather than nested in `guarded`, matching where `selection`/`lowered`
    # themselves already live here. Only `kind` truthiness is checked, not a
    # closed set of kind values: the legal vocabulary (own_ir::GuardedArgKind
    # -- var/param/bool_const/null_literal/object_creation/call_result/
    # opaque) is the PRODUCER's, not re-validated bit-for-bit here, the same
    # looseness check_witness() already accepts for its own selection_license.
    if w.get("selection") in ("pos", "neg"):
        _require(licensed_selection(w.get("selection_license")) == w.get("selection"),
                 "a pos/neg call-site selection needs a selection_license that actually "
                 "licenses that exact selection (checked mechanically against the frozen R1 "
                 "production mapping) -- never a merely-present license object with any "
                 "truthy kind")
    _require(w.get("lowered") in ("consume", "borrow", "plain"),
             "call-site witness.lowered must be consume|borrow|plain (#175's own Lowered)")


def classify_call_site(w: dict[str, Any]) -> dict[str, Any]:
    """Classifies a CALL_SITE_WITNESS into the SAME closed class vocabulary
    classify() uses. This is NOT a fifth class: CH3-8 ports classify()'s own,
    already-tested APPLICATION_REFINEMENT branch (a static pos/neg selection
    against an existing split summary) to this witness kind, now that it
    carries its own `selection_license` (check_call_site_witness's own
    validation). SUMMARY_REFINEMENT stays unreachable here, unchanged: it
    names a (method,param) SUMMARY's own collapsed value refining with NO
    call-site selection at all, and a call-site witness carries no such
    summary value to refine -- SUMMARY_REFINEMENT stays p037_mos_snapshot.py's
    document-level classification's job (see docs/evidence/p037-b-epoch.json's
    own supersession note: no new call-site machinery is built for it).
    LEGACY_HONESTY is a summary-level, verdict-equivalent shape (collapsed=
    unknown, legacy=may, both plain) that this witness kind cannot even
    express: it carries no `legacy` field at all (see
    check_call_site_witness's own docstring for why), so there is no scalar
    legacy Transfer value to compare against."""
    check_call_site_witness(w)
    guarded = w["guarded"]
    collapsed: Transfer = guarded["collapsed"]
    selection = w["selection"]
    lowered = w["lowered"]

    if selection in ("pos", "neg"):
        # check_call_site_witness() already required guarded.shape == "split"
        # for a pos/neg selection (the uncond branch there requires
        # selection == "unselected"), so this cannot be reached with an
        # uncond shape -- no invented priority needed for that combination.
        cells = guarded["finalized_cells"]
        selected_cell: Transfer = cells["pos"] if selection == "pos" else cells["neg"]
        expected_lowered = lower(selected_cell)
        if lowered != expected_lowered:
            return {"class": UNCLASSIFIED,
                    "reason": f"selected the {selection} cell ({selected_cell}), which #175's "
                              f"apply() lowers to {expected_lowered}, but this witness's own "
                              f"lowered field says {lowered} -- the witness's selection/lowered "
                              "fields disagree with each other, which is refused rather than "
                              "explained away"}
        # check_call_site_witness() already confirmed licensed_selection()
        # equals this exact selection -- never re-derived here, but a
        # SEPARATE question remains: has this license kind's mapping ever
        # been independently MEASURED end to end (a real captured witness),
        # or only mechanically read from frozen source? R1-review of
        # 20b09c9: only bool_const has (AR1/AR2's own real captures) --
        # null_literal/object_creation stay UNCLASSIFIED here until a real
        # witness measures them too, a case review at B_after rather than a
        # silent extrapolation from source reading alone.
        license_ = w["selection_license"]
        license_kind = license_["kind"]
        if license_kind not in _MEASURED_CALL_SITE_LICENSE_KINDS:
            return {"class": UNCLASSIFIED,
                    "reason": f"selection_license.kind={license_kind!r} correctly licenses the "
                              f"{selection} cell (check_call_site_witness's own "
                              "licensed_selection() already confirmed it), but no real captured "
                              "call-site witness has independently measured this license kind "
                              f"yet (measured so far: {sorted(_MEASURED_CALL_SITE_LICENSE_KINDS)}, "
                              "AR1/AR2's own real captures) -- a case review at B_after is "
                              "required before widening this set, never a silent extrapolation "
                              "from source reading alone"}
        return {"class": APPLICATION_REFINEMENT,
                "reason": f"call site selected the {selection} cell ({selected_cell}) via "
                          f"{license_kind}, lowering to {lowered} (#175's own apply()); the "
                          "guarded summary already existed at this callee/param, only the "
                          "call-site's own static selection is new (the same G-A1/G-A2 route "
                          "classify()'s own summary-level APPLICATION_REFINEMENT branch already "
                          "recognizes, ported to this witness kind)"}
    if guarded["shape"] != "split":
        return {"class": UNCLASSIFIED,
                "reason": "an uncond call-site guarded shape has no conditional structure to "
                          "recover honestly; a legacy/new movement here has no class-4 "
                          "explanation"}

    cells = guarded["finalized_cells"]
    is_recovered_conditional = (collapsed == "may"
                                and {cells["pos"], cells["neg"]} == {"no", "must"})
    if not is_recovered_conditional:
        return {"class": UNCLASSIFIED,
                "reason": f"finalized_cells {cells} collapsing to {collapsed} is not the "
                          "{no,must}-split-collapsing-to-may shape CONDITIONALITY_HONESTY is "
                          "narrowly defined over"}
    if lowered != "plain":
        return {"class": UNCLASSIFIED,
                "reason": f"lowered={lowered}, not plain -- a genuinely conditional, unselected "
                          "callee must apply() to Plain (collapse(Split(no,must))=may lowers to "
                          "plain); this witness's own lowered/guarded fields disagree with each "
                          "other, which is refused rather than explained away"}
    return {"class": CONDITIONALITY_HONESTY,
            "reason": "a genuinely conditional callee recovered as a real Split(no,must) (either "
                      "orientation) with no static selection at this site, collapsing to 'may' "
                      "(Plain, OWN051 once an owned obligation reaches the call) because the "
                      "branch outcome is honestly unresolved here, not because information was "
                      "lost; whether a real before-side diagnostic this recovery explains exists "
                      "is answered separately, by p037_verdict_snapshot.py's own "
                      "resource_acquire_site correlation against the actual captured "
                      "before-snapshot -- this classification does not depend on that answer"}


# --------------------------------------------------------------------------- selftest

_failures = 0


def _check(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def _w(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "coordinate": {"method": "M", "param": 0},
        "site": None,
        "legacy_transfer": "may",
        "guarded": {"shape": "uncond", "selection": None, "collapsed": "may",
                   "finalized_cells": None, "selection_license": None},
    }
    base.update(kwargs)
    return base


def selftest() -> int:
    # --- positive: APPLICATION_REFINEMENT (proposal row 18's own-body split,
    # applied at a site with a bool_const literal licensing the positive cell;
    # here modelled as the well-formed, NON-mutated twin of row 18 -- a real
    # Split(g, must, no) where the literal genuinely licenses the cell) ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "pos",
                  "selection_license": {"kind": "bool_const", "value": True},
                  "finalized_cells": {"pos": "must", "neg": "no"}, "collapsed": "may"})
    r = classify(w)
    _check("application-refinement-positive", r["class"] == APPLICATION_REFINEMENT, r)

    # --- positive: SUMMARY_REFINEMENT (row 12/13's own shape: Split(g,must,
    # must) collapses to must, strictly below legacy's may -- no site selects,
    # the summary itself is more precise) ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "must"}, "collapsed": "must"})
    r = classify(w)
    _check("summary-refinement-positive", r["class"] == SUMMARY_REFINEMENT, r)

    # --- positive: LEGACY_HONESTY (the pinned f1/K11b class-3 shape:
    # collapsed unknown, legacy may, both plain) ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "unknown"}, "collapsed": "unknown"})
    r = classify(w)
    _check("legacy-honesty-positive", r["class"] == LEGACY_HONESTY, r)

    # --- positive: CONDITIONALITY_HONESTY (amendment; U2/U3's own measured
    # shape -- a genuinely conditional callee recovered as Split(no,must),
    # unselected, collapsing to may, against a legacy that collapsed it to
    # `no` -- the B2.1a-degraded reading, current Python's own value today) ---
    w = _w(legacy_transfer="no",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "no", "neg": "must"}, "collapsed": "may"})
    r = classify(w)
    _check("conditionality-honesty-positive-legacy-no", r["class"] == CONDITIONALITY_HONESTY, r)

    # --- positive twin (item 9): the SAME real shape, but against the
    # pre-B2.1a legacy value (`must` -- the fabricated-consume reading a
    # scratch measurement against e4199ec actually produced for U2/U3's
    # wrapper), and the opposite cell orientation. One class must cover both
    # extremes legacy happened to collapse to -- it must not need a second
    # class solely because the old scalar chose the other extreme ---
    w = _w(legacy_transfer="must",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "no"}, "collapsed": "may"})
    r = classify(w)
    _check("conditionality-honesty-positive-legacy-must-twin",
          r["class"] == CONDITIONALITY_HONESTY, r)

    # --- hostile: uncond shape, legacy no -> may -- no split evidence exists
    # to recover, so there is no conditionality to be honest ABOUT here ---
    w = _w(legacy_transfer="no", guarded={"shape": "uncond", "selection": None,
                                         "selection_license": None, "finalized_cells": None,
                                         "collapsed": "may"})
    r = classify(w)
    _check("hostile-uncond-no-to-may-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile: split(no,may), legacy=no -- one cell is already `may`, not
    # the closed {no,must} pair CONDITIONALITY_HONESTY is narrowly defined
    # over; this is also not SUMMARY_REFINEMENT (leq(may,no) is False) ---
    w = _w(legacy_transfer="no",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "no", "neg": "may"}, "collapsed": "may"})
    r = classify(w)
    _check("hostile-split-no-may-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile: split(must,may), legacy=must -- same reasoning, the other
    # extreme ---
    w = _w(legacy_transfer="must",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "may"}, "collapsed": "may"})
    r = classify(w)
    _check("hostile-split-must-may-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile: split(no,must) but WITH a static selection -- must stay
    # APPLICATION_REFINEMENT, never be pulled into class 4 just because the
    # cells match its {no,must} shape. `legacy_transfer` is set equal to
    # `collapsed` ("may"), matching the EXISTING application-refinement-
    # positive test's own pattern above and classify()'s own, unamended
    # overlap rule: a selection present ALONGSIDE a collapsed-vs-legacy
    # difference is the pre-existing, unrelated UNCLASSIFIED-overlap case
    # (checked first, unconditionally, well before this amendment's own
    # code even runs) -- proving APPLICATION_REFINEMENT and this amendment
    # are also disjoint by construction, for a second, independent reason
    # from the SUMMARY_REFINEMENT one CLOSED_CLASSES' comment already gives ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "pos",
                  "selection_license": {"kind": "bool_const", "value": True},
                  "finalized_cells": {"pos": "no", "neg": "must"}, "collapsed": "may"})
    r = classify(w)
    _check("hostile-split-no-must-pos-selected-is-application-refinement",
          r["class"] == APPLICATION_REFINEMENT, r)
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "neg",
                  "selection_license": {"kind": "bool_const", "value": False},
                  "finalized_cells": {"pos": "no", "neg": "must"}, "collapsed": "may"})
    r = classify(w)
    _check("hostile-split-no-must-neg-selected-is-application-refinement",
          r["class"] == APPLICATION_REFINEMENT, r)

    # --- hostile: split(must,unknown), legacy=may -- LEGACY_HONESTY's own
    # existing shape must still win here, unamended (collapsed=unknown, not
    # may, so class 4's own predicate never even matches) ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "unknown"}, "collapsed": "unknown"})
    r = classify(w)
    _check("hostile-split-must-unknown-legacy-may-is-legacy-honesty",
          r["class"] == LEGACY_HONESTY, r)

    # --- hostile negative: same diagnostic-adjacent shape but no guarded
    # cell selection at all (uncond, no difference) must not classify ---
    w = _w(legacy_transfer="may", guarded={"shape": "uncond", "selection": None,
                                          "selection_license": None, "finalized_cells": None,
                                          "collapsed": "may"})
    r = classify(w)
    _check("hostile-uncond-no-difference-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile negative: changed call site but no summary provenance
    # (a split with a selection yet no license attached) is REFUSED by the
    # schema check, not silently classified ---
    try:
        classify(_w(guarded={"shape": "split", "selection": "pos", "selection_license": None,
                             "finalized_cells": {"pos": "must", "neg": "no"},
                             "collapsed": "may"}))
        _check("hostile-selection-without-license-is-refused", False, "did not raise")
    except WitnessError:
        _check("hostile-selection-without-license-is-refused", True)

    # --- hostile negative (R1-review of 20b09c9): a FABRICATED license --
    # present, truthy `kind`, but licensing the OPPOSITE cell from the one
    # claimed -- must be refused here too, not just in the newer call-site
    # witness path. Proves licensed_selection() is the one shared validator
    # for both witness kinds, not a call-site-only fix. ---
    try:
        classify(_w(guarded={"shape": "split", "selection": "pos",
                             "selection_license": {"kind": "bool_const", "value": False},
                             "finalized_cells": {"pos": "must", "neg": "no"},
                             "collapsed": "may"}))
        _check("hostile-summary-fabricated-license-is-refused", False, "did not raise")
    except WitnessError:
        _check("hostile-summary-fabricated-license-is-refused", True)

    # --- hostile negative: an unknown transform/shape value is refused by
    # the schema check ---
    try:
        classify(_w(guarded={"shape": "diagonal-ish", "selection": None,
                             "selection_license": None, "finalized_cells": None,
                             "collapsed": "may"}))
        _check("hostile-unknown-shape-is-refused", False, "did not raise")
    except WitnessError:
        _check("hostile-unknown-shape-is-refused", True)

    # --- hostile negative: a "fact outside the frontend slice" style input --
    # missing the coordinate entirely -- is refused, not classified ---
    try:
        classify({"legacy_transfer": "may", "guarded": {"shape": "uncond", "selection": None,
                                                        "collapsed": "may"}})
        _check("hostile-missing-coordinate-is-refused", False, "did not raise")
    except WitnessError:
        _check("hostile-missing-coordinate-is-refused", True)

    # --- a made-up fifth class is not a thing this module can even express --
    # CLOSED_CLASSES has exactly four members (the original three plus the
    # amendment's CONDITIONALITY_HONESTY), checked directly rather than
    # trusted ---
    _check("closed-classes-has-exactly-four-members", len(CLOSED_CLASSES) == 4,
          CLOSED_CLASSES)
    _check("unclassified-is-not-in-closed-classes", UNCLASSIFIED not in CLOSED_CLASSES)

    # --- hostile negative: LEGACY_HONESTY must not accept a verdict-changing
    # delta -- collapsed=unknown, legacy=may, but lowered values now DIFFER
    # (a hypothetical malformed witness) must not be filed as class 3 ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "must", "neg": "unknown"}, "collapsed": "unknown"})
    # sanity: lower(unknown) == lower(may) == "plain" always holds by
    # construction (both map to plain in this closed vocabulary), so the
    # "verdict-changing" mutation has to happen at the classify() input
    # itself -- there is no way to construct that case through this schema,
    # which is itself the point: the schema cannot represent a class-3
    # candidate whose verdict differs, because `lower` is a pure, total,
    # already-frozen function of Transfer alone.
    r = classify(w)
    _check("legacy-honesty-verdict-compatibility-is-structural",
          lower("unknown") == lower("may") == "plain" and r["class"] == LEGACY_HONESTY, r)

    # --- hostile negative: collapsed value regressing PAST legacy (not a
    # refinement at all) must not be classified as SUMMARY_REFINEMENT ---
    w = _w(legacy_transfer="must",
          guarded={"shape": "split", "selection": "unselected", "selection_license": None,
                  "finalized_cells": {"pos": "no", "neg": "no"}, "collapsed": "no"})
    r = classify(w)
    _check("regression-past-legacy-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile negative: both a selection AND a collapse difference at
    # once -- the named, honest ambiguity -- must be UNCLASSIFIED, not
    # silently resolved either way ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "pos",
                  "selection_license": {"kind": "bool_const", "value": True},
                  "finalized_cells": {"pos": "must", "neg": "must"}, "collapsed": "must"})
    r = classify(w)
    _check("both-application-and-summary-signal-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # --- hostile negative: the SAME overlap, but through the LEGACY_HONESTY
    # shape specifically (collapsed=unknown, legacy=may) rather than through
    # SUMMARY_REFINEMENT's shape (collapsed=must) -- the exact intersection
    # an earlier version of classify() missed, because it checked LEGACY_
    # HONESTY before the overlap test and this case satisfies both at once.
    # Caught by owner review, not by the check above, precisely because
    # that check never used collapsed="unknown" -- this one exists so the
    # intersection stays caught mechanically from here on ---
    w = _w(legacy_transfer="may",
          guarded={"shape": "split", "selection": "pos",
                  "selection_license": {"kind": "bool_const", "value": True},
                  "finalized_cells": {"pos": "unknown", "neg": "unknown"},
                  "collapsed": "unknown"})
    r = classify(w)
    _check("selection-overlapping-legacy-honesty-shape-is-unclassified",
          r["class"] == UNCLASSIFIED, r)

    # --- B1-F2-F4: derive_document_witnesses(), the real witness adapter,
    # against a REAL `dump_summaries` document (not a literal witness dict) --
    # `python -m ownlang summaries` over an actual extracted facts.json. ---
    real_doc: dict[str, Any] | None = None
    real_error = ""
    try:
        fixture = ROOT / "corpus" / "p036-bakeoff" / "guarded-consume-flag-branch" / "after.cs"
        with tempfile.TemporaryDirectory(prefix="p037-classifier-selftest-") as td:
            facts = Path(td) / "facts.json"
            proc = subprocess.run(
                ["bash", str(ROOT / "scripts" / "own-check.sh"), "--engine", "python",
                 "--format", "human", "--severity", "warning", "--emit-facts", str(facts),
                 "--", str(fixture)],
                cwd=ROOT, capture_output=True, text=True, check=False)
            if proc.returncode not in (0, 1):
                real_error = f"extractor exit {proc.returncode}: {proc.stderr[-500:]}"
            else:
                out = subprocess.run(
                    [sys.executable, "-m", "ownlang", "summaries", str(facts)],
                    cwd=ROOT, capture_output=True, text=True, check=False)
                if out.returncode != 0:
                    real_error = f"summaries exit {out.returncode}: {out.stderr[-500:]}"
                else:
                    real_doc = json.loads(out.stdout)
    except OSError as exc:
        real_error = str(exc)

    if real_doc is None:
        _check("real-summaries-document-obtained", False, real_error)
    else:
        _check("real-summaries-document-has-summaries",
              isinstance(real_doc.get("summaries"), list) and len(real_doc["summaries"]) >= 1,
              real_doc)

        # identical documents (even the SAME real one on both sides): zero
        # divergent witnesses, exactly today's actual pre-treatment truth.
        witnesses = derive_document_witnesses(real_doc, real_doc)
        _check("real-identical-documents-derive-zero-witnesses", witnesses == [], witnesses)

        # a divergence with NO guarded field: classify()'s own existing
        # uncond/differs-from-legacy branch must return UNCLASSIFIED, added
        # by NO new logic in this adapter.
        mutated = copy.deepcopy(real_doc)
        target = mutated["summaries"][0]
        if target.get("params"):
            original_transfer = target["params"][0].get("transfer")
            # "must" is picked deliberately, not "unknown": collapsed=unknown
            # against legacy=may is class_3_shape, classify()'s OWN
            # LEGACY_HONESTY case regardless of shape (checked before the
            # split/uncond branch) -- using it here would exercise that
            # pre-existing rule, not the "no guard evidence" path this test
            # means to isolate. "must" is incomparable-by-difference for an
            # uncond shape (any uncond difference is UNCLASSIFIED) yet a
            # legitimate SUMMARY_REFINEMENT under a split shape, so it
            # actually distinguishes the two adapter paths.
            flipped: Transfer = "must" if original_transfer != "must" else "no"
            target["params"][0]["transfer"] = flipped
            witnesses = derive_document_witnesses(real_doc, mutated)
            _check("real-divergence-without-guarded-field-is-unclassified",
                  len(witnesses) == 1 and witnesses[0]["classification"]["class"] == UNCLASSIFIED,
                  witnesses)

            # the SAME divergence, but with a `guarded` field justifying it as
            # a genuine split-summary refinement -- proves the adapter reads
            # the field when present rather than ignoring it.
            mutated2 = copy.deepcopy(real_doc)
            target2 = mutated2["summaries"][0]
            target2["params"][0]["transfer"] = flipped
            target2["params"][0]["guarded"] = {
                "shape": "split", "selection": "unselected", "selection_license": None,
                "finalized_cells": {"pos": flipped, "neg": flipped}, "collapsed": flipped,
            }
            witnesses = derive_document_witnesses(real_doc, mutated2)
            expect_class = (SUMMARY_REFINEMENT if leq(flipped, original_transfer)
                           and flipped != original_transfer else UNCLASSIFIED)
            _check("real-divergence-with-guarded-field-is-read",
                  len(witnesses) == 1 and witnesses[0]["classification"]["class"] == expect_class,
                  witnesses)
            # explain_divergence(): the split-shaped, classified divergence
            # (mutated2, already proven SUMMARY_REFINEMENT above) is FULLY
            # explained -- patching real_doc's (legacy_doc's) transfer to
            # match is the WHOLE difference between the two documents.
            result = explain_divergence(real_doc, mutated2)
            _check("explain-divergence-fully-explained-when-only-transfer-moved",
                  result["explained"] is True, result)

            # the UNCLASSIFIED case (mutated, no guarded field) is correctly
            # NOT explained.
            result = explain_divergence(real_doc, mutated)
            _check("explain-divergence-unexplained-when-witness-is-unclassified",
                  result["explained"] is False, result)

            # a classified transfer change PLUS an unrelated residual
            # difference (unresolved[] gains an entry) must still be
            # unexplained -- the witness accounts for the transfer, nothing
            # accounts for the rest, so the document as a whole is not
            # fully explained by what was classified.
            mutated3 = copy.deepcopy(mutated2)
            mutated3["unresolved"] = [*mutated3.get("unresolved", []), "SomeExtern"]
            result = explain_divergence(real_doc, mutated3)
            _check("explain-divergence-unexplained-when-residual-difference-remains",
                  result["explained"] is False
                  and "outside the witness vocabulary" in result["reason"], result)
        else:
            _check("real-divergence-without-guarded-field-is-unclassified", False,
                  "fixture's first summary has no params to mutate")
            _check("real-divergence-with-guarded-field-is-read", False,
                  "fixture's first summary has no params to mutate")

    # --- call-site witness (amendment): U1's own real, measured shape -----
    # `ShapeU1.Use` calls `ShapeU1.Inner(s, keep)` directly on a LOCAL `s`
    # (never a parameter of `Use`), so no (method,param) coordinate for `Use`
    # exists at all -- measured via a scratch e4199ec worktree + the held R1
    # treatment worktree (own-check.sh --emit-facts, own-shadow-engine, and
    # own-cli ownir over U1.cs), not invented: Inner's real finalized cells
    # are {pos: no, neg: must} (`if (!keep) s.Dispose();`), the call argument
    # for `keep` is `kind: "param", source_param: 1` in the real
    # `guarded_facts` (a syntactic forward, never a `bool_const`) so
    # `call_arg_selection` maps it Unselected by construction, R1's own
    # lowered layer folds the acquire/use pair away entirely at this site and
    # the real verdict shows `[OWN051] cannot verify whether
    # 'ShapeU1.Inner' takes ownership of 's' ... optimistically assuming it
    # does` -- i.e. lowered=plain.
    def _cs(**kwargs: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "kind": "call_site",
            "site": {"file": "U1.cs", "line": 16, "column": 9},
            "callee": "ShapeU1.Inner",
            "callee_param": 0,
            "resource_name": "s",
            "resource_acquire_site": {"line": 14},
            "guarded": {"shape": "split", "finalized_cells": {"pos": "no", "neg": "must"},
                       "collapsed": "may"},
            "selection": "unselected",
            "lowered": "plain",
        }
        base.update(kwargs)
        return base

    # positive: U1's own real, measured shape classifies regardless of what
    # either engine's SCALAR analysis separately concluded at this site --
    # there is no more `legacy` axis to hold fixed or vary here (dropped per
    # check_call_site_witness's own docstring: unpopulatable by a real Rust
    # producer, and redundant with p037_verdict_snapshot.py's own
    # resource_acquire_site correlation against the real captured
    # before-snapshot). The former state-A/state-B "twin" pair collapses to
    # one test since both anchorings produced the identical witness once
    # `legacy` is gone.
    r = classify_call_site(_cs())
    _check("call-site-u1-conditionality-honesty-positive",
          r["class"] == CONDITIONALITY_HONESTY, r)

    # positive (CH3-8): a static selection with a valid selection_license
    # against the SAME {no,must} split classifies as APPLICATION_REFINEMENT
    # -- the class-4 CONDITIONALITY_HONESTY shape above and this class-1
    # shape are the same guarded coordinate, differing only in whether the
    # call site made a static choice; not a fifth class, the same
    # (method,param)-summary-level branch classify() already recognizes,
    # ported here now that this witness kind carries its own license.
    r = classify_call_site(_cs(selection="pos",
                              selection_license={"kind": "bool_const", "value": True},
                              lowered="borrow"))
    _check("call-site-pos-no-selected-borrow-is-application-refinement",
          r["class"] == APPLICATION_REFINEMENT, r)
    r = classify_call_site(_cs(selection="neg",
                              selection_license={"kind": "bool_const", "value": False},
                              lowered="consume"))
    _check("call-site-neg-must-selected-consume-is-application-refinement",
          r["class"] == APPLICATION_REFINEMENT, r)

    # hostile: the two possible selected-cell/lowered mismatches -- selected
    # No (which #175 lowers to Borrow) claiming Consume, and selected Must
    # (which lowers to Consume) claiming Borrow. Neither is silently
    # accepted as APPLICATION_REFINEMENT or folded into any other class.
    r = classify_call_site(_cs(selection="pos",
                              selection_license={"kind": "bool_const", "value": True},
                              lowered="consume"))
    _check("call-site-hostile-selected-no-lowered-consume-is-unclassified",
          r["class"] == UNCLASSIFIED, r)
    r = classify_call_site(_cs(selection="neg",
                              selection_license={"kind": "bool_const", "value": False},
                              lowered="borrow"))
    _check("call-site-hostile-selected-must-lowered-borrow-is-unclassified",
          r["class"] == UNCLASSIFIED, r)

    # hostile: a pos/neg selection with no selection_license at all, or a
    # structurally invalid one (missing `kind`), is REFUSED (raises), never
    # silently classified either way -- the schema-level check, not the
    # classifier's own priority logic, catches this.
    try:
        classify_call_site(_cs(selection="pos", lowered="borrow"))
        _check("call-site-hostile-selection-without-license-is-refused", False, "did not raise")
    except WitnessError:
        _check("call-site-hostile-selection-without-license-is-refused", True)
    try:
        classify_call_site(_cs(selection="pos", selection_license={"value": True},
                              lowered="borrow"))
        _check("call-site-hostile-invalid-license-is-refused", False, "did not raise")
    except WitnessError:
        _check("call-site-hostile-invalid-license-is-refused", True)

    # R1-review of 20b09c9: a selection_license must actually LICENSE the
    # claimed selection, not merely be present with a truthy kind --
    # licensed_selection() is checked mechanically here, ported from the
    # frozen R1 production mapping (lower.rs's classify_guard_call_arg()/
    # call_arg_selection()), never guessed.
    for label, selection, license_ in (
        ("fabricated-bool-const-false-claiming-pos", "pos",
         {"kind": "bool_const", "value": False}),
        ("fabricated-bool-const-true-claiming-neg", "neg",
         {"kind": "bool_const", "value": True}),
        ("unknown-license-kind", "pos", {"kind": "potato"}),
        ("bool-const-missing-value", "pos", {"kind": "bool_const"}),
        ("bool-const-non-bool-value", "pos", {"kind": "bool_const", "value": 1}),
        ("null-literal-claiming-pos", "pos", {"kind": "null_literal"}),
        ("object-creation-claiming-neg", "neg", {"kind": "object_creation"}),
    ):
        try:
            classify_call_site(_cs(selection=selection, selection_license=license_,
                                  lowered="borrow"))
            _check(f"call-site-hostile-{label}-is-refused", False, "did not raise")
        except WitnessError:
            _check(f"call-site-hostile-{label}-is-refused", True)

    # positive (mechanically correct license, but not yet independently
    # MEASURED by any real captured witness -- AR1/AR2 only ever measured
    # bool_const): null_literal ALWAYS licenses neg, object_creation ALWAYS
    # licenses pos (read directly from the frozen R1 production mapping),
    # so these pass validation and the selected-cell/lowered consistency
    # check, but classify_call_site() itself stops short of
    # APPLICATION_REFINEMENT until a real witness measures the kind too.
    r = classify_call_site(_cs(selection="neg", selection_license={"kind": "null_literal"},
                              lowered="consume"))
    _check("call-site-null-literal-licenses-neg-but-unmeasured-is-unclassified",
          r["class"] == UNCLASSIFIED, r)
    r = classify_call_site(_cs(selection="pos", selection_license={"kind": "object_creation"},
                              lowered="borrow"))
    _check("call-site-object-creation-licenses-pos-but-unmeasured-is-unclassified",
          r["class"] == UNCLASSIFIED, r)

    # hostile: uncond guarded shape at the call site -- nothing conditional
    # to recover.
    r = classify_call_site(_cs(guarded={"shape": "uncond", "finalized_cells": None,
                                       "collapsed": "may"}))
    _check("call-site-hostile-uncond-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # hostile: split cells that are not the closed {no,must} pair.
    r = classify_call_site(_cs(guarded={"shape": "split",
                                       "finalized_cells": {"pos": "no", "neg": "may"},
                                       "collapsed": "may"}))
    _check("call-site-hostile-non-nomust-cells-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # hostile: lowered disagrees with the guarded/selection fields (a
    # malformed witness a real emitter should never produce) -- refused as
    # UNCLASSIFIED, not silently trusted.
    r = classify_call_site(_cs(lowered="consume"))
    _check("call-site-hostile-lowered-mismatch-is-unclassified", r["class"] == UNCLASSIFIED, r)

    # hostile: the schema itself refuses a witness missing `kind`.
    try:
        bad = _cs()
        del bad["kind"]
        classify_call_site(bad)
        _check("call-site-hostile-missing-kind-is-refused", False, "did not raise")
    except WitnessError:
        _check("call-site-hostile-missing-kind-is-refused", True)

    # hostile: a missing/empty resource_name is refused -- a claimed
    # correlation with nothing to check it against is not measurement.
    try:
        classify_call_site(_cs(resource_name=""))
        _check("call-site-hostile-empty-resource-name-is-refused", False, "did not raise")
    except WitnessError:
        _check("call-site-hostile-empty-resource-name-is-refused", True)

    # hostile: a malformed resource_acquire_site (not null, not {line:int})
    # is refused, not silently coerced.
    try:
        classify_call_site(_cs(resource_acquire_site={"line": "14"}))
        _check("call-site-hostile-malformed-acquire-site-is-refused", False, "did not raise")
    except WitnessError:
        _check("call-site-hostile-malformed-acquire-site-is-refused", True)

    # null resource_acquire_site is legal (no single acquire line applies)
    # and does not itself change the classification.
    r = classify_call_site(_cs(resource_acquire_site=None))
    _check("call-site-null-acquire-site-is-legal-and-still-classifies",
          r["class"] == CONDITIONALITY_HONESTY, r)

    # --- an unrelated residual document difference is not excused by one
    # classified CONDITIONALITY_HONESTY witness elsewhere in the same
    # document -- explain_divergence() must still call the whole document
    # unexplained, same discipline as its existing SUMMARY_REFINEMENT case ---
    if real_doc is not None and real_doc["summaries"][0].get("params"):
        base_doc = real_doc
        ch_doc = copy.deepcopy(base_doc)
        ch_target = ch_doc["summaries"][0]["params"][0]
        ch_target["transfer"] = "may"
        ch_target["guarded"] = {
            "shape": "split", "selection": "unselected", "selection_license": None,
            "finalized_cells": {"pos": "no", "neg": "must"}, "collapsed": "may",
        }
        legacy_for_ch = copy.deepcopy(base_doc)
        legacy_for_ch["summaries"][0]["params"][0]["transfer"] = "no"
        witnesses = derive_document_witnesses(legacy_for_ch, ch_doc)
        _check("conditionality-honesty-real-document-witness",
              len(witnesses) == 1
              and witnesses[0]["classification"]["class"] == CONDITIONALITY_HONESTY,
              witnesses)
        result = explain_divergence(legacy_for_ch, ch_doc)
        _check("explain-divergence-fully-explained-for-conditionality-honesty",
              result["explained"] is True, result)
        ch_doc_plus_residual = copy.deepcopy(ch_doc)
        ch_doc_plus_residual["unresolved"] = [
            *ch_doc_plus_residual.get("unresolved", []), "SomeOtherExtern",
        ]
        result = explain_divergence(legacy_for_ch, ch_doc_plus_residual)
        _check("explain-divergence-unexplained-when-residual-remains-alongside-class4",
              result["explained"] is False, result)

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-classifier selftest: all checks pass "
          f"(GAP, permanent and by design: {GAP_REAL_WITNESS_SOURCE[:60]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
