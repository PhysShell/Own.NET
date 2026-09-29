//! P-037 B1 acceptance: the executable controls of the 16 B0 obligations
//! (docs/notes/p037-phase-b1-shadow.md §B N3/N4, §C). Test names are the
//! filters `scripts/p037_proof_boundary.py --mutants` runs each falsifier
//! against, so a renamed test is a falsifier that stopped firing.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_guarded::{classify_application, classify_summary, report, report_with_height, SCHEMA};
use own_ir::OwnIr;
use p037_kernel::{Lowered, Transfer};
use serde_json::{json, Value};

fn facts(name: &str) -> Value {
    let path = format!(
        "{}/tests/fixtures/{name}.facts.json",
        env!("CARGO_MANIFEST_DIR")
    );
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn run(doc: &Value, legacy: &Value) -> Value {
    report(&OwnIr::from_json(&doc.to_string()).unwrap(), legacy)
}

fn row<'r>(r: &'r Value, method: &str) -> &'r Value {
    r["summary"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["method"] == method)
        .unwrap()
}

fn app<'r>(r: &'r Value, caller: &str) -> &'r Value {
    r["application"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["caller"] == caller)
        .unwrap()
}

/// The legacy MOS dump shape, one `(method, transfer)` per coordinate 0.
fn legacy(rows: &[(&str, &str)]) -> Value {
    let summaries: Vec<Value> = rows
        .iter()
        .map(|(m, t)| json!({"method": m, "params": [{"index": 0, "transfer": t}]}))
        .collect();
    json!({ "summaries": summaries })
}

/// Edit the one sidecar call of `method` in place.
fn edit_call(doc: &mut Value, method: &str, f: impl FnOnce(&mut Value)) {
    let fns = doc["functions"].as_array_mut().unwrap();
    let func = fns.iter_mut().find(|x| x["name"] == method).unwrap();
    f(&mut func["guarded_facts"]["calls"][0]);
}

/// A4/A15 (G6): every B0 probe shape, with its pre-registered B0 §E.6
/// outcome. `None` = placeable: the join places every op, so any
/// degradation comes from the callee (`via:`, `callee_`) or the absent legacy
/// row, never from the join itself.
#[test]
fn a15_b0_probe_outcomes() {
    let r = run(&facts("B0"), &json!({}));
    let expected = [
        ("Probe.Branchy", None),
        // P-037-X Stage 2b R4 (research/p037-max-v1): the election is seeded per coordinate,
        // so each guard record is located by its own `if`; TwoIfs' two eligible ifs on one
        // line answer `join_guard` (the guard join is ambiguous) where B1's per-function rule
        // answered `multi_guard`. NO_GUARDED_EVIDENCE either way — B0 §E.6's outcome holds.
        ("Probe.TwoIfs", Some("join_guard")),
        ("Probe.Early", None),
        ("Probe2.InBranch", None),
        ("Probe2.AfterIf", None),
        ("Probe2.Behind", None),
        ("Probe3.ShortCircuit", Some("expression_form")),
        ("Probe3.Switch", None),
        ("Probe3.TryCatch", Some("no_body_op")),
        ("Probe3.Loop", Some("join_structural")),
        ("ForwardingDerived..ctor", Some("no_body_op")),
    ];
    for (method, want) in expected {
        let s = row(&r, method);
        let reason = s["reason"].as_str().unwrap_or("");
        match want {
            Some(w) => assert_eq!(reason, w, "{method}: {s}"),
            None => assert!(
                ["", "legacy_missing"].contains(&reason)
                    || reason.starts_with("via:")
                    || reason.starts_with("callee_"),
                "{method} must be placeable: {s}"
            ),
        }
    }
    // Probe3.Ternary has no functions[] record at all (R): no coordinate.
    assert!(r["summary"]
        .as_array()
        .unwrap()
        .iter()
        .all(|s| s["method"] != "Probe3.Ternary"));
    // Behind: the kept path under the ineligible `if (ready)` joins `no`.
    assert_eq!(row(&r, "Probe2.Behind")["cells"], json!(["no", "may"]));
}

/// A8 (G8): the K7 witness ported onto the adapter. `K7.Rec` is
/// `(pos, neg) = (⊥, must)` from real facts; the unselected site in
/// `K7.Caller` must lower through `apply`'s `fin` to plain, never consume.
#[test]
fn k7_witness_on_the_adapter() {
    let r = run(
        &facts("B1"),
        &legacy(&[("K7.Rec", "may"), ("K7.Caller", "may")]),
    );
    assert_eq!(row(&r, "K7.Rec")["shape"], "split(1)");
    let site = app(&r, "K7.Caller");
    assert_eq!(site["selection"], "unselected");
    assert_eq!(site["guarded"], "plain", "{site}");
    assert_eq!(site["class"], "EQUAL");
}

/// A13 (G9): only `fin()` cells cross an SCC boundary. Read raw, the
/// opaque edge would collapse `(⊥, must)` to `must` at the caller.
#[test]
fn a13_only_finalized_cells_cross_sccs() {
    let r = run(&facts("B1"), &legacy(&[("K7.Caller", "may")]));
    let caller = row(&r, "K7.Caller");
    assert_eq!(caller["shape"], "uncond");
    assert_eq!(caller["cells"], json!(["may", "may"]), "{caller}");
    assert_eq!(caller["class"], "EQUAL");
}

/// A9–A11 (G7) and `record-absence-boundary`: a missing record, a missing
/// sidecar or an unresolved callee is no evidence, and so is everything that
/// forwards into it. Absence never reads as ⊥ / no / must.
#[test]
fn record_absence_boundary() {
    let r = run(&facts("B1"), &json!({}));
    assert_eq!(row(&r, "Absence.ToBodied")["reason"], "callee_no_record");
    // P-037-X Stage 2b R1 (research/p037-max-v1): a straight-line leaf carries a record but
    // no sidecar because A2.1 emits one only for a relevant call or an eligible guard; its
    // absence encodes the EMPTY sidecar, so `Absence.Leaf` is solved from its body ops and
    // `Absence.ToLeaf` through the edge. B1 pinned both as `missing_sidecar`; the record
    // absence of `ToBodied` (a callee with no record at all) stays the fail-closed answer.
    assert_eq!(row(&r, "Absence.Leaf")["reason"], "legacy_missing");
    assert_eq!(row(&r, "Absence.Leaf")["guarded"], "must");
    // ToLeaf forwards under an early-return guard on `keep`: Split(keep, no, must) through
    // the id edge into Leaf's Uncond(must); its collapse is the honest `may`.
    assert_eq!(row(&r, "Absence.ToLeaf")["reason"], "legacy_missing");
    assert_eq!(row(&r, "Absence.ToLeaf")["shape"], "split(1)");
    assert_eq!(row(&r, "Absence.ToLeaf")["cells"], json!(["no", "must"]));
    assert_eq!(row(&r, "Absence.ToLeaf")["guarded"], "may");
    assert_eq!(app(&r, "Absence.ToBodied")["reason"], "callee_no_record");
    let mut doc = facts("B1");
    edit_call(&mut doc, "Pass.KeepIt", |c| c["callee"] = Value::Null);
    assert_eq!(
        row(&run(&doc, &json!({})), "Pass.KeepIt")["reason"],
        "callee_unresolved"
    );
}

/// WF/EWF: an edge into a slot that is no coordinate is never solved.
#[test]
fn wf_edge_without_a_coordinate() {
    let mut doc = facts("B1");
    edit_call(&mut doc, "Pass.KeepIt", |c| {
        c["args"][0]["param"] = json!(7)
    });
    assert_eq!(
        row(&run(&doc, &json!({})), "Pass.KeepIt")["reason"],
        "callee_no_coord"
    );
}

/// A12: a bound failure (fault-injected) is no evidence for the SCC and its
/// callers, never a partial value or a panic.
#[test]
fn a12_bound_failure_is_no_evidence() {
    let doc = facts("B1");
    let r = report_with_height(&OwnIr::from_json(&doc.to_string()).unwrap(), &json!({}), 0);
    assert_eq!(row(&r, "K7.Rec")["reason"], "bound");
    assert_eq!(row(&r, "K7.Caller")["reason"], "via:bound");
}

/// A2/A5: an `id` edge imports the callee's election; literals select a cell
/// in the canonical orientation (`true`/`new` pos, `false`/`null` neg).
#[test]
fn a2_a5_edges_and_selection() {
    let lg = legacy(&[
        ("Pass.Inner", "may"),
        ("Pass.Outer", "may"),
        ("Pass.KeepIt", "may"),
    ]);
    let r = run(&facts("B1"), &lg);
    assert_eq!(row(&r, "Pass.Outer")["shape"], "split(1)");
    assert_eq!(row(&r, "Pass.Outer")["cells"], json!(["no", "must"]));
    assert_eq!(row(&r, "Pass.KeepIt")["guarded"], "no");
    assert_eq!(row(&r, "Pass.KeepIt")["class"], "SUMMARY_REFINEMENT");
    assert_eq!(row(&r, "Pass.DropIt")["guarded"], "must");
    let keep = app(&r, "Pass.KeepIt");
    assert_eq!(
        (&keep["selection"], &keep["guarded"]),
        (&json!("pos"), &json!("borrow"))
    );
    assert_eq!(keep["class"], "APPLICATION_REFINEMENT");
    assert_eq!(app(&r, "Pass.Outer")["class"], "EQUAL");
    for (kind, want) in [("null_literal", "must"), ("object_creation", "no")] {
        let mut doc = facts("B1");
        edit_call(&mut doc, "Pass.KeepIt", |c| {
            c["args"][1] = json!({"param": 1, "kind": kind})
        });
        assert_eq!(
            row(&run(&doc, &json!({})), "Pass.KeepIt")["guarded"],
            want,
            "{kind}"
        );
    }
}

/// The A2 inertness control's lie (scripts/p037_sidecar_inertness.py).
fn contradictory(mut doc: Value) -> Value {
    for f in doc["functions"].as_array_mut().unwrap() {
        if f.get("guarded_facts").is_none() {
            f["guarded_facts"] = json!({"version": 1, "calls": [], "guards": []});
        }
        let gf = &mut f["guarded_facts"];
        for c in gf["calls"].as_array_mut().unwrap() {
            for a in c["args"].as_array_mut().unwrap() {
                match a["kind"].as_str().unwrap() {
                    "bool_const" => a["value"] = json!(!a["value"].as_bool().unwrap()),
                    "param" => a["negated"] = json!(!a["negated"].as_bool().unwrap_or(false)),
                    _ => {}
                }
            }
        }
        for g in gf["guards"].as_array_mut().unwrap() {
            g["negated"] = json!(!g["negated"].as_bool().unwrap());
        }
        let fake = json!({"site": {"line": 1, "column": 1}, "param": 0, "predicate": "truth", "negated": false});
        gf["guards"].as_array_mut().unwrap().push(fake);
    }
    doc
}

/// N4 (G10): the contradictory sidecar that A2 had to ignore must CHANGE
/// the guarded shadow, which proves the sidecar is read.
#[test]
fn n4_required_read_contradictory_sidecar() {
    let doc = facts("B1");
    let honest = run(&doc, &json!({}));
    let lie = run(&contradictory(doc), &json!({}));
    assert_ne!(honest["summary"], lie["summary"]);
}

/// A14 (G11): every report is conditional on static dispatch.
#[test]
fn a14_report_is_static_dispatch_conditional() {
    let r = run(&facts("B1"), &json!({}));
    assert_eq!(r["schema"], SCHEMA);
    assert_eq!(r["static_dispatch_conditional"], json!(true));
}

/// N5 (G13): a pair outside its level's classes is UNEXPLAINED, never
/// bucketed; a pair only G-T2a would justify (raw ⊥ ≤ must, finalized `no`
/// against legacy `must`) is UNEXPLAINED too.
#[test]
fn g13_classifiers_never_bucket() {
    use Transfer::{May, Must, No, Unknown};
    assert_eq!(classify_summary(Must, Must), "EQUAL");
    assert_eq!(classify_summary(Must, May), "SUMMARY_REFINEMENT");
    assert_eq!(classify_summary(No, Unknown), "SUMMARY_REFINEMENT");
    assert_eq!(classify_summary(Unknown, May), "LEGACY_HONESTY");
    for (g, t) in [
        (No, Must),
        (Must, No),
        (May, Must),
        (Unknown, Must),
        (May, No),
    ] {
        assert_eq!(classify_summary(g, t), "UNEXPLAINED", "{g:?} vs {t:?}");
    }
    use Lowered::{Borrow, Consume, Plain};
    assert_eq!(classify_application(Consume, Plain, Consume), "EQUAL");
    assert_eq!(
        classify_application(Borrow, Plain, Plain),
        "APPLICATION_REFINEMENT"
    );
    assert_eq!(classify_application(Consume, Consume, Plain), "UNEXPLAINED");
}
