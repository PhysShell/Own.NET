//! P-037-X Stage 4 acceptance (research/p037-max-v1, EXPLORATORY): the relational
//! (resource, ownsResource) abstraction as frozen in Own.NET-paperwork
//! `paper-eval/p037-max/stage4-relational-prereg-v1.json` — the producer's result relation
//! (R4-4), the witness bindings and the site match (R4-5) — over the extractor's opt-in facts of
//! `corpus/p037x-controls/x4-*.cs` (`OWEN_P037X_RELATIONAL=1`), committed byte for byte. The
//! verdict-level outcomes of the same controls are pinned by tests/test_p037x_controls.py.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_guarded::{report, Coordinate, GuardedDoc};
use own_ir::OwnIr;
use p037_kernel::{Shape, Transfer};
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

/// The statement line of the sidecar call of `caller` whose callee ends in `callee`, `nth` of
/// its kind in sidecar order.
fn site_line(name: &str, caller: &str, callee: &str, nth: usize) -> i64 {
    let v: Value = serde_json::from_str(&fixture(name)).unwrap();
    v["functions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"] == caller)
        .and_then(|f| {
            f["guarded_facts"]["calls"]
                .as_array()?
                .iter()
                .filter(|c| c["callee"].as_str().is_some_and(|c| c.ends_with(callee)))
                .nth(nth)
                .and_then(|c| c["statement_line"].as_i64())
        })
        .unwrap_or_else(|| panic!("{caller}: no sidecar call to {callee} in {name}"))
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

/// The shadow report over an EMPTY legacy dump: the relation rows and the witness columns do
/// not read the legacy side (the Stage 4 classes are pinned here; the legacy-dependent
/// classes are the report binary's business and are measured, not unit-tested).
fn shadow(name: &str) -> Value {
    let ir = OwnIr::from_json(&fixture(name)).unwrap();
    report(&ir, &json!({ "summaries": [] }))
}

fn application_rows(name: &str) -> Vec<Value> {
    shadow(name)["application"].as_array().unwrap().clone()
}

fn relations(name: &str) -> Vec<(String, u64, String)> {
    shadow(name)["relations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            (
                r["method"].as_str().unwrap().to_owned(),
                r["slot"].as_u64().unwrap(),
                r["relation"].as_str().unwrap().to_owned(),
            )
        })
        .collect()
}

/// `(class, witness, selection)` of one application row.
fn class_at(name: &str, caller: &str, line: i64, handle: &str) -> (String, Option<String>) {
    let row = application_rows(name)
        .into_iter()
        .find(|a| {
            a["caller"] == caller && a["statement_line"].as_i64() == Some(line) && a["handle"] == handle
        })
        .unwrap_or_else(|| panic!("{caller}:{line} {handle}: no application row in {name}"));
    (
        row["class"].as_str().unwrap().to_owned(),
        row["witness"].as_str().map(str::to_owned),
    )
}

/// A witnessed row that is NOT a discharge: the witness is known, the site did not match.
fn not_discharged(name: &str, caller: &str, line: i64, handle: &str, witness: &str) {
    let (class, w) = class_at(name, caller, line, handle);
    assert_ne!(class, "RELATIONAL_DISCHARGE", "{caller}:{line}");
    assert_eq!(w.as_deref(), Some(witness), "{caller}:{line}");
}

const RB: &str = "R,System.Boolean";

// R4-4: the producer's result relation — slot 0 is fresh iff flag slot 1; the always-shared
// slot 2 has no relation; the consumer's coordinate is the frozen Split(owns) [must, no].
#[test]
fn x4_p1_relation_and_coordinates() {
    let g = doc("x4-p1");
    assert_eq!(g.result_relation("X4P1.Produce", Some(""), 0), Some(1));
    assert_eq!(g.result_relation("X4P1.Produce", Some(""), 2), None);
    assert_eq!(g.result_relation("X4P1.Produce", Some(""), 1), None);
    let (shape, pos, neg) = guarded(g.coordinate("X4P1.Consume", 0));
    assert_eq!((shape, pos, neg), (Shape::Split(1), Transfer::Must, Transfer::No));
    assert_eq!(
        relations("x4-p1"),
        vec![
            ("X4P1.Produce".to_owned(), 0, "fresh_iff(1)".to_owned()),
            ("X4P1.Produce".to_owned(), 2, "none".to_owned()),
        ]
    );
}

// R4-5: the deconstruction binds r to its witness `owns`; the guarded call with that witness at
// the elected ordinal discharges (try/finally and plain forms alike); a must consumer and a
// borrowing consumer are not witness matches (the frozen readings stand).
#[test]
fn x4_p1_witness_bindings_and_matches() {
    let g = doc("x4-p1");
    for caller in ["X4P1.Matched", "X4P1.MatchedPlain", "X4P1.AlwaysCaller", "X4P1.NeverCaller"] {
        assert_eq!(g.witness_of(caller, "r"), Some("owns"), "{caller}");
        assert_eq!(g.witness_of(caller, "owns"), None, "{caller}: a flag is no handle");
    }
    let l = site_line("x4-p1", "X4P1.Matched", "Consume", 0);
    assert!(g.witness_match("X4P1.Matched", l, "X4P1.Consume", Some(RB), 0, "owns"));
    assert!(!g.witness_match("X4P1.Matched", l, "X4P1.Consume", Some(RB), 0, "other"));
    let l2 = site_line("x4-p1", "X4P1.MatchedPlain", "Consume", 0);
    assert!(g.witness_match("X4P1.MatchedPlain", l2, "X4P1.Consume", Some(RB), 0, "owns"));
    let la = site_line("x4-p1", "X4P1.AlwaysCaller", "Always", 0);
    assert!(!g.witness_match("X4P1.AlwaysCaller", la, "X4P1.Always", Some("R"), 0, "owns"));
    let ln = site_line("x4-p1", "X4P1.NeverCaller", "Never", 0);
    assert!(!g.witness_match("X4P1.NeverCaller", ln, "X4P1.Never", Some("R"), 0, "owns"));
    assert_eq!(
        class_at("x4-p1", "X4P1.Matched", l, "var:r"),
        ("RELATIONAL_DISCHARGE".to_owned(), Some("owns".to_owned()))
    );
    assert_eq!(
        class_at("x4-p1", "X4P1.MatchedPlain", l2, "var:r"),
        ("RELATIONAL_DISCHARGE".to_owned(), Some("owns".to_owned()))
    );
    not_discharged("x4-p1", "X4P1.AlwaysCaller", la, "var:r", "owns");
    not_discharged("x4-p1", "X4P1.NeverCaller", ln, "var:r", "owns");
}

// X4-P2, the SHAPE TWIN of the frozen case 2 (never counted as its recovery): the producer's
// relation forms and every FinishSend site of the four callers discharges by `disposeCts`; the
// catch-side HandleFailure sites are not witness matches.
#[test]
fn x4_p2_finishsend_shape_twin_discharges_at_every_site() {
    let g = doc("x4-p2");
    let producer = "Client.PrepareCancellationTokenSource";
    assert_eq!(g.result_relation(producer, Some("System.Threading.CancellationToken"), 0), Some(1));
    assert_eq!(g.result_relation(producer, Some("System.Threading.CancellationToken"), 2), None);
    let (shape, pos, neg) = guarded(g.coordinate("Client.FinishSend", 1));
    assert_eq!((shape, pos, neg), (Shape::Split(2), Transfer::Must, Transfer::No));
    let sig = "Response,System.Threading.CancellationTokenSource,System.Boolean,System.Boolean,System.Boolean";
    for caller in [
        "Client.GetStringAsyncCore",
        "Client.GetByteArrayAsyncCore",
        "Client.GetStreamAsyncCore",
        "Client.Send",
    ] {
        assert_eq!(g.witness_of(caller, "cts"), Some("disposeCts"), "{caller}");
        assert_eq!(g.witness_of(caller, "pendingRequestsCts"), None, "{caller}: no relation at slot 2");
        let l = site_line("x4-p2", caller, "FinishSend", 0);
        assert!(g.witness_match(caller, l, "Client.FinishSend", Some(sig), 1, "disposeCts"), "{caller}");
        assert_eq!(
            class_at("x4-p2", caller, l, "var:cts"),
            ("RELATIONAL_DISCHARGE".to_owned(), Some("disposeCts".to_owned())),
            "{caller}"
        );
        let h = site_line("x4-p2", caller, "HandleFailure", 0);
        assert!(!g.witness_match(caller, h, "Client.HandleFailure", None, 3, "disposeCts"), "{caller}");
    }
}

// X4-C1: an unrelated boolean at the guard ordinal is not the handle's witness.
#[test]
fn x4_c1_unrelated_flag_is_no_witness() {
    let g = doc("x4-c1");
    assert_eq!(g.witness_of("X4C1.Unrelated", "r"), Some("owns"));
    let l = site_line("x4-c1", "X4C1.Unrelated", "Consume", 0);
    assert!(!g.witness_match("X4C1.Unrelated", l, "X4C1.Consume", Some(RB), 0, "owns"));
    not_discharged("x4-c1", "X4C1.Unrelated", l, "var:r", "owns");
}

// X4-C2: a reassigned flag is not stable, so the site carries no witness identity.
#[test]
fn x4_c2_reassigned_flag_degrades() {
    let g = doc("x4-c2");
    assert_eq!(g.witness_of("X4C2.Reassigned", "r"), Some("owns"));
    let l = site_line("x4-c2", "X4C2.Reassigned", "Consume", 0);
    assert!(!g.witness_match("X4C2.Reassigned", l, "X4C2.Consume", Some(RB), 0, "owns"));
    not_discharged("x4-c2", "X4C2.Reassigned", l, "var:r", "owns");
}

// X4-C3: two resources and one flag never cross-associate; each with its own flag discharges.
#[test]
fn x4_c3_no_cross_association() {
    let g = doc("x4-c3");
    assert_eq!(g.witness_of("X4C3.Crossed", "a"), Some("fa"));
    assert_eq!(g.witness_of("X4C3.Crossed", "b"), Some("fb"));
    let c0 = site_line("x4-c3", "X4C3.Crossed", "Consume", 0);
    let c1 = site_line("x4-c3", "X4C3.Crossed", "Consume", 1);
    assert!(!g.witness_match("X4C3.Crossed", c0, "X4C3.Consume", Some(RB), 0, "fa"));
    assert!(!g.witness_match("X4C3.Crossed", c1, "X4C3.Consume", Some(RB), 0, "fb"));
    not_discharged("x4-c3", "X4C3.Crossed", c0, "var:a", "fa");
    not_discharged("x4-c3", "X4C3.Crossed", c1, "var:b", "fb");
    let s0 = site_line("x4-c3", "X4C3.Straight", "Consume", 0);
    let s1 = site_line("x4-c3", "X4C3.Straight", "Consume", 1);
    assert!(g.witness_match("X4C3.Straight", s0, "X4C3.Consume", Some(RB), 0, "fa"));
    assert!(g.witness_match("X4C3.Straight", s1, "X4C3.Consume", Some(RB), 0, "fb"));
    assert_eq!(class_at("x4-c3", "X4C3.Straight", s0, "var:a").0, "RELATIONAL_DISCHARGE");
    assert_eq!(class_at("x4-c3", "X4C3.Straight", s1, "var:b").0, "RELATIONAL_DISCHARGE");
}

// X4-C4: a (no, must) coordinate is the wrong polarity for an owned-iff handle.
#[test]
fn x4_c4_polarity_is_respected() {
    let g = doc("x4-c4");
    let (shape, pos, neg) = guarded(g.coordinate("X4C4.ConsumeUnless", 0));
    assert_eq!((shape, pos, neg), (Shape::Split(1), Transfer::No, Transfer::Must));
    let l = site_line("x4-c4", "X4C4.Inverted", "ConsumeUnless", 0);
    assert!(!g.witness_match("X4C4.Inverted", l, "X4C4.ConsumeUnless", Some(RB), 0, "owns"));
    not_discharged("x4-c4", "X4C4.Inverted", l, "var:r", "owns");
}

// X4-C5: the owned-slot filler carries the handle in the later slot; the filler is no handle.
#[test]
fn x4_c5_filler_carries_the_later_slot() {
    let g = doc("x4-c5");
    let sig = "R,R,System.Boolean";
    let (shape, pos, neg) = guarded(g.coordinate("X4C5.ConsumeSecond", 1));
    assert_eq!((shape, pos, neg), (Shape::Split(2), Transfer::Must, Transfer::No));
    let l = site_line("x4-c5", "X4C5.Filled", "ConsumeSecond", 0);
    assert!(g.witness_match("X4C5.Filled", l, "X4C5.ConsumeSecond", Some(sig), 1, "owns"));
    assert_eq!(class_at("x4-c5", "X4C5.Filled", l, "var:r").0, "RELATIONAL_DISCHARGE");
    assert_eq!(g.witness_of("X4C5.Filled", "first"), None);
    let v: Value = serde_json::from_str(&fixture("x4-c5")).unwrap();
    let filled = v["functions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"] == "X4C5.Filled")
        .unwrap();
    let call = filled["body"]
        .as_array()
        .unwrap()
        .iter()
        .find(|o| o["op"] == "call" && o["callee"] == "X4C5.ConsumeSecond")
        .expect("the canonical call with the filler");
    assert_eq!(call["args"], serde_json::json!(["first", "r"]));
}
