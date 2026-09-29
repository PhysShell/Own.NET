//! P-037-X Stage 2b acceptance (research/p037-max-v1, EXPLORATORY): the four driver-fidelity
//! rules frozen in Own.NET-paperwork `paper-eval/p037-max/stage2b-prereg-v1.json` — R1 the
//! empty-sidecar leaf, R2 sig-keyed coordinate identity, R3 the declared ordinal as a fact,
//! R4 the per-coordinate election seed (G-S1 verbatim) — each pinned by its hostile control.
//! The fixtures are the extractor's own output over `corpus/p037x-controls/*.cs` (Stage 2b
//! extractor, `--flow-locals`), committed byte for byte; X2B-C6 is hand-written on purpose.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_guarded::{report, Coordinate, GuardedDoc};
use own_ir::OwnIr;
use p037_kernel::{Lowered, Shape, Transfer};
use serde_json::{json, Value};

fn fixture(name: &str) -> String {
    let path = format!(
        "{}/tests/fixtures/{name}.facts.json",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::read_to_string(path).unwrap()
}

fn doc(name: &str) -> GuardedDoc {
    GuardedDoc::solve(&OwnIr::from_json(&fixture(name)).unwrap())
}

/// The statement line of the first sidecar call of `caller` in the fixture's facts.
fn call_line(name: &str, caller: &str) -> i64 {
    let v: Value = serde_json::from_str(&fixture(name)).unwrap();
    v["functions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"] == caller)
        .and_then(|f| f["guarded_facts"]["calls"][0]["statement_line"].as_i64())
        .unwrap_or_else(|| panic!("{caller}: no sidecar call in {name}"))
}

fn no_evidence(c: Option<&Coordinate>) -> Option<&str> {
    match c? {
        Coordinate::NoEvidence(r) => Some(r.as_str()),
        Coordinate::Guarded { .. } => None,
    }
}

fn guarded(c: Option<&Coordinate>) -> (Shape, Transfer, Transfer) {
    match c.expect("coordinate") {
        Coordinate::Guarded { shape, cells } => {
            let f = cells.fin();
            (*shape, f.pos, f.neg)
        }
        Coordinate::NoEvidence(r) => panic!("expected guarded evidence, got NO_GUARDED_EVIDENCE({r})"),
    }
}

const STREAM: &str = "System.IO.Stream";

#[test]
fn x2b_c1_sidecar_less_leaf_with_an_if_stays_no_evidence() {
    // R1's boundary: the body carries an `if` (on `n > 0`, no eligible guard), so the missing
    // sidecar is NOT read as empty; the caller falls back to the legacy `may`.
    let g = doc("x2b-c1");
    assert_eq!(no_evidence(g.coordinate("X2bC1.Leaf", 0)), Some("missing_sidecar"));
    let line = call_line("x2b-c1", "X2bC1.Caller");
    assert_eq!(
        g.apply_at("X2bC1.Caller", line, "X2bC1.Leaf", Some("System.IO.Stream,System.Int32"), 0),
        None
    );
}

#[test]
fn x2b_c2_sidecar_less_leaf_with_a_while_stays_no_evidence() {
    let g = doc("x2b-c2");
    assert_eq!(no_evidence(g.coordinate("X2bC2.Loop", 0)), Some("missing_sidecar"));
}

#[test]
fn x2b_c3_overloads_are_distinct_coordinates_and_no_name_fallback() {
    let g = doc("x2b-c3");
    let guarded_key = format!("X2bC3.Take({STREAM},System.Boolean)");
    let leaf_key = format!("X2bC3.Take({STREAM})");
    // the guarded overload: Split over `keep` (ordinal 1); `keep == true` keeps, `false` disposes
    let (shape, pos, neg) = guarded(g.coordinate(&guarded_key, 0));
    assert_eq!(shape, Shape::Split(1));
    assert_eq!((pos, neg), (Transfer::No, Transfer::Must));
    // the straight-line consumer: R1's empty sidecar -> Uncond(must)
    let (shape, pos, neg) = guarded(g.coordinate(&leaf_key, 0));
    assert_eq!(shape, Shape::Uncond);
    assert_eq!((pos, neg), (Transfer::Must, Transfer::Must));
    // the bare name is not a coordinate: overloads have no name-only identity
    assert!(g.coordinate("X2bC3.Take", 0).is_none());
    // callers
    let l = call_line("x2b-c3", "X2bC3.GuardedCaller");
    assert_eq!(
        g.apply_at("X2bC3.GuardedCaller", l, "X2bC3.Take", Some("System.IO.Stream,System.Boolean"), 0),
        Some(Lowered::Consume),
        "Take(r, false): the negative cell is `must`"
    );
    let l = call_line("x2b-c3", "X2bC3.ConsumerCaller");
    assert_eq!(
        g.apply_at("X2bC3.ConsumerCaller", l, "X2bC3.Take", Some(STREAM), 0),
        Some(Lowered::Consume)
    );
    // the record-less overload: a sig that matches no record of that name resolves to nothing
    let l = call_line("x2b-c3", "X2bC3.NoRecordCaller");
    assert_eq!(
        g.apply_at("X2bC3.NoRecordCaller", l, "X2bC3.Take", Some("System.IO.Stream,System.Int32"), 0),
        None
    );
    let r = report(&OwnIr::from_json(&fixture("x2b-c3")).unwrap(), &json!({"summaries": []}));
    let row = r["application"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["caller"] == "X2bC3.NoRecordCaller")
        .unwrap();
    assert_eq!(row["class"], "NO_GUARDED_EVIDENCE");
    assert_eq!(row["reason"], "callee_sig");
}

#[test]
fn x2b_c4_two_governing_literals_seed_conflict_never_consume() {
    let g = doc("x2b-c4");
    let (shape, pos, neg) = guarded(g.coordinate("X2bC4.Two", 0));
    assert_eq!(shape, Shape::Uncond, "Conflict elects Uncond (the honest join)");
    assert_eq!((pos, neg), (Transfer::May, Transfer::May));
    let l = call_line("x2b-c4", "X2bC4.Caller");
    let lowered = g.apply_at(
        "X2bC4.Caller",
        l,
        "X2bC4.Two",
        Some("System.IO.Stream,System.Boolean,System.Boolean"),
        0,
    );
    assert_eq!(lowered, Some(Lowered::Plain));
    assert_ne!(lowered, Some(Lowered::Consume));
}

#[test]
fn x2b_c5_only_the_governing_guard_is_elected() {
    let g = doc("x2b-c5");
    let (shape, pos, neg) = guarded(g.coordinate("X2bC5.Mixed", 0));
    assert_eq!(shape, Shape::Split(2), "`dispose` is declared ordinal 2; `log` governs nothing on `s`");
    assert_eq!((pos, neg), (Transfer::Must, Transfer::No));
    let sig = Some("System.IO.Stream,System.Boolean,System.Boolean");
    let l = call_line("x2b-c5", "X2bC5.KeepsIt");
    assert_eq!(g.apply_at("X2bC5.KeepsIt", l, "X2bC5.Mixed", sig, 0), Some(Lowered::Borrow));
    let l = call_line("x2b-c5", "X2bC5.HandsItOff");
    assert_eq!(g.apply_at("X2bC5.HandsItOff", l, "X2bC5.Mixed", sig, 0), Some(Lowered::Consume));
}

#[test]
fn x2b_c6_an_ordinal_fact_that_disagrees_is_refused() {
    // hand-written: (a) ordinals not strictly increasing; (b) ordinals disagreeing with A17's
    // derivation from the sig. Neither side is trusted: NO_GUARDED_EVIDENCE(ordinal_map).
    let ir = OwnIr::from_json(&fixture("x2b-c6")).unwrap();
    let g = GuardedDoc::solve(&ir);
    assert_eq!(no_evidence(g.coordinate("X2bC6.Decreasing", 0)), Some("ordinal_map"));
    assert_eq!(no_evidence(g.coordinate("X2bC6.Decreasing", 1)), Some("ordinal_map"));
    assert_eq!(no_evidence(g.coordinate("X2bC6.Disagrees", 0)), Some("ordinal_map"));
    // and the well-formed sibling in the same document solves
    let (shape, pos, neg) = guarded(g.coordinate("X2bC6.Fine", 0));
    assert_eq!(shape, Shape::Uncond);
    assert_eq!((pos, neg), (Transfer::Must, Transfer::Must));
}

#[test]
fn x2b_c7_a_merging_guard_governs_nothing() {
    // Added after the first R4 implementation was seen to over-elect (a walker-based
    // "governs" counted any action AFTER a passed literal); G-S1 names exactly two shapes.
    let g = doc("x2b-c7");
    let (shape, pos, neg) = guarded(g.coordinate("X2bC7.Merged", 0));
    assert_eq!(shape, Shape::Split(2), "`log` merges before the release and elects nothing");
    assert_eq!((pos, neg), (Transfer::Must, Transfer::No));
    let l = call_line("x2b-c7", "X2bC7.Caller");
    let sig = Some("System.IO.Stream,System.Boolean,System.Boolean");
    assert_eq!(g.apply_at("X2bC7.Caller", l, "X2bC7.Merged", sig, 0), Some(Lowered::Borrow));
}
