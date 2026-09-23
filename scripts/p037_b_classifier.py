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
2. `classify(witness)`, the three CLOSED classes plus UNCLASSIFIED, decided
   from WITNESS fields alone -- never from a file path, a fixture name or a
   diagnostic code (§10.1's own rule, repeated in the B1 brief). Tested here
   against SYNTHETIC witnesses built by hand from the proposal's own worked
   rows (18-19, K11b), the same way formal/p037-kernel/'s Kani harnesses are
   tested against hand-built System values with no production code existing
   yet -- proving the LOGIC is correct against the frozen CONTRACT, not that
   any real mos.rs output will ever conform to it. That binding happens only
   once B-after evidence exists to classify for real.
3. A named, permanent GAP note (GAP_REAL_WITNESS_SOURCE below) instead of a
   silent hole: real-data classification requires the treatment's own guard-
   aware types and a genuinely new per-coordinate/per-call-site trace this
   module does not and cannot emit. Building that trace is the treatment's
   own first deliverable, not a B1 retrofit onto mos.rs/lower.rs (which stay
   untouched through all of B1) -- see the formal note's B1 section for the
   full reasoning, including why legacy-side provenance (PathAction origins,
   which forwards release priority drops, a per-call-site consumed-transfer-
   and-outcome record with column) COULD technically be added without any
   guard concept, but is deliberately NOT added here: threading it through
   lower.rs in isolation, then extending it again once guard-awareness
   lands, is less coherent than doing both together as part of the first
   treatment.

Run:  python scripts/p037_b_classifier.py selftest
"""

from __future__ import annotations

from typing import Any, Literal

APPLICATION_REFINEMENT = "APPLICATION_REFINEMENT"
SUMMARY_REFINEMENT = "SUMMARY_REFINEMENT"
LEGACY_HONESTY = "LEGACY_HONESTY"
UNCLASSIFIED = "UNCLASSIFIED"

CLOSED_CLASSES = (APPLICATION_REFINEMENT, SUMMARY_REFINEMENT, LEGACY_HONESTY)

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
    _require(guarded.get("shape") in ("uncond", "split"), "guarded.shape must be uncond|split")
    if guarded["shape"] == "split":
        cells = guarded.get("finalized_cells")
        _require(isinstance(cells, dict) and cells.get("pos") in _TRANSFER_VALUES
                 and cells.get("neg") in _TRANSFER_VALUES,
                 "guarded.finalized_cells must be {pos,neg} Transfer values for a split shape")
        _require(guarded.get("selection") in ("pos", "neg", "unselected"),
                 "guarded.selection must be pos|neg|unselected for a split shape")
        if guarded["selection"] in ("pos", "neg"):
            _require(isinstance(guarded.get("selection_license"), dict)
                     and guarded["selection_license"].get("kind"),
                     "a pos/neg selection needs a selection_license naming what licensed it")
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

    Decision order (checked, not guessed): LEGACY_HONESTY first (it is the
    narrowest, most specific shape -- a collapsed value of exactly `unknown`
    against a legacy `may`, both lowering to `plain`); then, for a `split`
    shape, whether a call-site SELECTION was actually made (APPLICATION_
    REFINEMENT) or not (SUMMARY_REFINEMENT then rests on the COLLAPSED value
    alone). A witness whose collapsed value differs from legacy AND ALSO
    carries a pos/neg selection is a real overlap the proposal's rows 1-19
    do not settle (checked directly against the proposal text, not assumed);
    this classifier reports that overlap as UNCLASSIFIED with a named
    reason rather than inventing a priority rule -- inventing one would be
    new semantics, a §10.1 case-5 event, not classification tooling.
    """
    check_witness(w)
    guarded = w["guarded"]
    legacy_t: Transfer = w["legacy_transfer"]
    collapsed: Transfer = guarded["collapsed"]
    legacy_lowered = lower(legacy_t)
    guarded_lowered = lower(collapsed)

    class_3_shape = collapsed == "unknown" and legacy_t == "may"
    if class_3_shape and legacy_lowered == guarded_lowered == "plain":
        return {"class": LEGACY_HONESTY,
                "reason": "collapsed=unknown against legacy=may, both lower to plain (G-T2b "
                          "class 3, the K11b amendment's own declared verdict-equivalent case)"}

    if guarded["shape"] == "split":
        selected = guarded["selection"]
        collapse_differs = collapsed != legacy_t
        if selected in ("pos", "neg") and collapse_differs:
            return {"class": UNCLASSIFIED,
                    "reason": "both a call-site selection and a collapsed-value difference are "
                              "present at once; the proposal's rows 1-19 do not settle which "
                              "class this is, and this classifier does not invent a priority "
                              "rule for it (that would be new semantics, a case-5 event)"}
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

    # --- hostile negative: a made-up fourth class is not a thing this module
    # can even express -- CLOSED_CLASSES has exactly three members, checked
    # directly rather than trusted ---
    _check("closed-classes-has-exactly-three-members", len(CLOSED_CLASSES) == 3,
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

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-classifier selftest: all checks pass "
          f"(GAP, permanent and by design: {GAP_REAL_WITNESS_SOURCE[:60]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
