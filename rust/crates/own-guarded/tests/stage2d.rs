//! P-037-X Stage 2d acceptance (research/p037-max-v1, EXPLORATORY): R6 as frozen in
//! Own.NET-paperwork `paper-eval/p037-max/stage2d-prereg-v1.json` — a body op at a sidecar call
//! line whose callee has NO coordinate for reasons of absence contributes by its own kind (the
//! legacy borrow / release), never a forward; identity conflicts and forwards to coordinates keep
//! B1's fail-closed reading. Fixtures: the extractor's output over `corpus/p037x-controls/x2d-*.cs`
//! (and `x2b-c3` for X2D-C5), committed byte for byte.

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

const SB: &str = "System.IO.Stream,System.Boolean";

#[test]
fn x2d_c1_external_forward_on_the_else_branch_is_the_borrow() {
    let g = doc("x2d-c1");
    let (shape, pos, neg) = guarded(g.coordinate("X2dC1.M", 0));
    assert_eq!(shape, Shape::Split(1));
    assert_eq!((pos, neg), (Transfer::Must, Transfer::No), "XD-4's stated value (must, no)");
    let l = call_line("x2d-c1", "X2dC1.HandsOff");
    assert_eq!(g.apply_at("X2dC1.HandsOff", l, "X2dC1.M", Some(SB), 0), Some(Lowered::Consume));
    let l = call_line("x2d-c1", "X2dC1.Keeps");
    assert_eq!(g.apply_at("X2dC1.Keeps", l, "X2dC1.M", Some(SB), 0), Some(Lowered::Borrow));
    let l = call_line("x2d-c1", "X2dC1.Opaque");
    assert_eq!(g.apply_at("X2dC1.Opaque", l, "X2dC1.M", Some(SB), 0), Some(Lowered::Plain));
}

#[test]
fn x2d_c2_external_initializer_use_then_guarded_release() {
    let g = doc("x2d-c2");
    let (shape, pos, neg) = guarded(g.coordinate("X2dC2.N", 0));
    assert_eq!(shape, Shape::Split(2), "`dispose` is declared ordinal 2");
    assert_eq!((pos, neg), (Transfer::Must, Transfer::No));
    let sig = Some("System.IO.Stream,System.Func`2,System.Boolean");
    let l = call_line("x2d-c2", "X2dC2.Keeps");
    assert_eq!(g.apply_at("X2dC2.Keeps", l, "X2dC2.N", sig, 0), Some(Lowered::Borrow));
    let l = call_line("x2d-c2", "X2dC2.Hands");
    assert_eq!(g.apply_at("X2dC2.Hands", l, "X2dC2.N", sig, 0), Some(Lowered::Consume));
}

#[test]
fn x2d_c3_two_forwards_to_coordinates_stay_multi_action() {
    let g = doc("x2d-c3");
    assert_eq!(no_evidence(g.coordinate("X2dC3.Two", 0)), Some("multi_action"));
}

#[test]
fn x2d_c4_release_then_external_use_is_uncond_must() {
    let g = doc("x2d-c4");
    let (shape, pos, neg) = guarded(g.coordinate("X2dC4.RelThenUse", 0));
    assert_eq!(shape, Shape::Uncond);
    assert_eq!((pos, neg), (Transfer::Must, Transfer::Must));
    let l = call_line("x2d-c4", "X2dC4.Caller");
    assert_eq!(
        g.apply_at("X2dC4.Caller", l, "X2dC4.RelThenUse", Some("System.IO.Stream"), 0),
        Some(Lowered::Consume)
    );
}

#[test]
fn x2d_c5_an_identity_conflict_is_not_absence() {
    // A parameter forwarded to a same-name callee whose sig matches no record: the forward
    // stays a forward and the coordinate is NO_GUARDED_EVIDENCE(callee_sig); reading
    // `callee_sig` like absence would turn the legacy op at that line into a value.
    let g = doc("x2d-c5");
    assert_eq!(no_evidence(g.coordinate("X2dC5.Fwd", 0)), Some("callee_sig"));
    let r = report(&OwnIr::from_json(&fixture("x2d-c5")).unwrap(), &json!({"summaries": []}));
    let row = r["application"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["caller"] == "X2dC5.Fwd")
        .unwrap();
    assert_eq!(row["class"], "NO_GUARDED_EVIDENCE");
    assert_eq!(row["reason"], "callee_sig");
    // and X2B-C3's caller-side site keeps answering nothing (no name-only fallback)
    let g3 = doc("x2b-c3");
    let l = call_line("x2b-c3", "X2bC3.NoRecordCaller");
    assert_eq!(
        g3.apply_at("X2bC3.NoRecordCaller", l, "X2bC3.Take", Some("System.IO.Stream,System.Int32"), 0),
        None
    );
}
