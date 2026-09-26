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

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-classifier selftest: all checks pass "
          f"(GAP, permanent and by design: {GAP_REAL_WITNESS_SOURCE[:60]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
