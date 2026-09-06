//! The `AnalysisTrace` acceptance contract (P-022 step 7a checkpoint 3, #269):
//!
//! ```text
//! <case>.repro.json → own_shadow::project_traces  ≡  <case>.trace.json
//! ```
//!
//! byte-for-byte, with **zero Python**. The reference authors the goldens
//! (`python tests/test_repro_fixtures.py --write`); this side projects the
//! same artifacts through its own independent implementation of the same
//! frozen schema. Both sides project **both** engines' captures — projecting a
//! capture is not authoring it — so the *normalization itself* is
//! cross-checked, and a disagreement between the two implementations is a
//! finding about the projection rather than about either engine.
//!
//! **Nothing here compares the two engines.** The trace is the shape a
//! comparison would need; producing it is not performing one. Reading one
//! engine's steps against the other's is the reduction checkpoint's job.
//!
//! The properties asserted beyond the goldens are the ones the normalization
//! exists for:
//! * **totality** — no counter-shaped handle survives the rewrite anywhere;
//! * **a mint-order shift does not move a stable id** — the whole point;
//! * **order is not normalized away** — the same shift still changes the
//!   lowered layer's step order, because that difference is real.

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use std::collections::{BTreeMap, BTreeSet};

use own_shadow::{parse, project_traces, Json, ORDER_CANONICAL, ORDER_SIGNIFICANT, TRACE_VERSION};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures");

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| panic!("cannot read {path}: {e}"))
}

fn artifact_names() -> BTreeSet<String> {
    let manifest =
        parse(&read(&format!("{FIXTURES}/repro/manifest.json"))).expect("repro manifest parses");
    manifest
        .get("artifacts")
        .and_then(Json::as_array)
        .expect("manifest carries an 'artifacts' ledger")
        .iter()
        .filter_map(|e| e.get("name").and_then(Json::as_str))
        .map(str::to_owned)
        .collect()
}

/// The first differing line, both sides. A failure that only says "they
/// differ" makes the reader do the diff by hand, which for a 2 000-line trace
/// is how a real disagreement gets waved through as "probably formatting".
fn first_difference(committed: &str, ours: &str) -> String {
    for (i, (a, b)) in committed.lines().zip(ours.lines()).enumerate() {
        if a != b {
            let line = i.saturating_add(1);
            return format!("    first difference at line {line}:\n      committed = {a}\n      ours      = {b}");
        }
    }
    format!(
        "    the shorter side ends first: committed has {} line(s), ours {}",
        committed.lines().count(),
        ours.lines().count()
    )
}

#[test]
fn every_trace_golden_is_reproduced_byte_for_byte() {
    let names = artifact_names();
    assert!(!names.is_empty(), "no artifacts to trace");
    let mut divergences: Vec<String> = Vec::new();
    for name in &names {
        let artifact =
            parse(&read(&format!("{FIXTURES}/repro/{name}.repro.json"))).expect("artifact parses");
        let ours = project_traces(&artifact, name)
            .unwrap_or_else(|e| panic!("{name}: this side cannot project the trace: {e}"));
        // Determinism: the same artifact, twice.
        assert_eq!(
            ours,
            project_traces(&artifact, name).expect("second projection"),
            "{name}: the trace projection is not deterministic"
        );
        let mut rendered = ours.to_pretty();
        rendered.push('\n');
        let committed = read(&format!("{FIXTURES}/repro/{name}.trace.json"));
        if rendered != committed {
            divergences.push(format!(
                "{name}: this side's trace differs from the committed one — the two \
                 implementations of the normalization disagree, which is a finding about the \
                 PROJECTION, not about either engine.\n{}",
                first_difference(&committed, &rendered)
            ));
        }
    }
    assert!(
        divergences.is_empty(),
        "{} trace(s) differ:\n{}",
        divergences.len(),
        divergences.join("\n")
    );
}

#[test]
fn the_declared_order_semantics_are_the_frozen_ones() {
    for name in artifact_names() {
        let traces = parse(&read(&format!("{FIXTURES}/repro/{name}.trace.json")))
            .expect("trace golden parses");
        assert_eq!(
            traces.get("trace_version").and_then(Json::as_i64),
            Some(TRACE_VERSION),
            "{name}: trace golden is keyed to a different surface version"
        );
        for trace in traces
            .get("traces")
            .and_then(Json::as_array)
            .expect("traces")
        {
            for layer in trace
                .get("layers")
                .and_then(Json::as_array)
                .expect("layers")
            {
                let layer_name = layer.get("layer").and_then(Json::as_str).expect("layer");
                let order = layer.get("order").and_then(Json::as_str).expect("order");
                let want = if layer_name == "summaries" {
                    ORDER_CANONICAL
                } else {
                    ORDER_SIGNIFICANT
                };
                assert_eq!(
                    order, want,
                    "{name}/{layer_name}: order semantics drifted — a comparison reads this to \
                     CLASSIFY an ordering difference, and it must never license sorting"
                );
            }
        }
    }
}

#[test]
fn no_counter_shaped_handle_survives_anywhere_in_a_trace() {
    // Totality, checked from the OUTSIDE: the projection asserts it internally,
    // and this walks the committed result so the assertion cannot be the only
    // thing standing between a leaked counter and a comparison.
    fn walk(value: &Json, out: &mut Vec<String>) {
        match value {
            Json::Str(s) => {
                if let Some((prefix, digits)) = s.split_once('_') {
                    if matches!(prefix, "sub" | "cap" | "parg" | "loc")
                        && !digits.is_empty()
                        && digits.bytes().all(|b| b.is_ascii_digit())
                    {
                        out.push(s.clone());
                    }
                }
            }
            Json::Array(items) => items.iter().for_each(|v| walk(v, out)),
            Json::Object(entries) => entries.iter().for_each(|(_, v)| walk(v, out)),
            _ => {}
        }
    }
    for name in artifact_names() {
        let traces = parse(&read(&format!("{FIXTURES}/repro/{name}.trace.json")))
            .expect("trace golden parses");
        let mut leaked = Vec::new();
        walk(&traces, &mut leaked);
        assert!(
            leaked.is_empty(),
            "{name}: minted handles survived into the trace: {leaked:?}"
        );
    }
}

/// The property the whole checkpoint exists for, driven through the port's own
/// pipeline: shifting the mint counters must not move a stable id, and must
/// still move the step ORDER.
#[test]
fn a_mint_order_shift_moves_the_order_but_not_the_stable_ids() {
    // A document with several components: reversing them reshuffles the global
    // handle counters (BR-L2) without changing any record's identity.
    let facts_path = format!("{FIXTURES}/lowered/handles_global_counters.facts.json");
    let facts = parse(&read(&facts_path)).expect("facts parse");
    let Json::Object(fields) = &facts else {
        panic!("facts is not an object")
    };
    let permuted = Json::Object(
        fields
            .iter()
            .map(|(k, v)| {
                if k != "components" {
                    return (k.clone(), v.clone());
                }
                let mut items = v.as_array().expect("components").to_vec();
                items.reverse();
                (k.clone(), Json::Array(items))
            })
            .collect(),
    );

    let steps = |document: &Json| -> (Vec<String>, Vec<String>) {
        let text = document.to_canonical();
        let capture = own_shadow::capture(&text).expect("capture");
        let artifact = Json::Object(vec![
            ("engines".to_owned(), Json::Array(vec![capture])),
            (
                "input".to_owned(),
                Json::Object(vec![("canonical".to_owned(), Json::Null)]),
            ),
        ]);
        let traces = project_traces(&artifact, "probe").expect("trace");
        let layer = traces
            .get("traces")
            .and_then(Json::as_array)
            .and_then(<[Json]>::first)
            .and_then(|t| t.get("layers"))
            .and_then(Json::as_array)
            .and_then(<[Json]>::first)
            .expect("the lowered layer");
        let ids: Vec<String> = layer
            .get("steps")
            .and_then(Json::as_array)
            .expect("steps")
            .iter()
            .filter_map(|s| s.get("id").and_then(Json::as_str))
            .map(str::to_owned)
            .collect();
        let handles: Vec<String> = ids
            .iter()
            .filter(|id| id.starts_with("handles["))
            .cloned()
            .collect();
        (ids, handles)
    };

    let (order_a, handles_a) = steps(&facts);
    let (order_b, handles_b) = steps(&permuted);

    assert!(
        !handles_a.is_empty(),
        "the probe document mints no handles, so it proves nothing"
    );
    let mut sorted_a = handles_a;
    let mut sorted_b = handles_b;
    sorted_a.sort();
    sorted_b.sort();
    assert_eq!(
        sorted_a, sorted_b,
        "a mint-order shift moved a stable id — the normalization does not survive the \
         reordering it exists for, and one permuted input would report every handle as a \
         difference between engines"
    );
    assert_ne!(
        order_a, order_b,
        "the permutation did not change the lowered layer's step order, so this case cannot \
         show that order is DECLARED rather than normalized away — pick a document where it does"
    );
}

#[test]
fn a_refused_layer_carries_no_steps() {
    // An empty step list that compared equal to another engine's empty one
    // would score a refusal as agreement, so refusals must be visibly refusals.
    let mut refused = 0_usize;
    let mut by_case: BTreeMap<String, usize> = BTreeMap::new();
    for name in artifact_names() {
        let traces = parse(&read(&format!("{FIXTURES}/repro/{name}.trace.json")))
            .expect("trace golden parses");
        for trace in traces
            .get("traces")
            .and_then(Json::as_array)
            .expect("traces")
        {
            for layer in trace
                .get("layers")
                .and_then(Json::as_array)
                .expect("layers")
            {
                let status = layer.get("status").and_then(Json::as_str).expect("status");
                let steps = layer.get("steps").and_then(Json::as_array).expect("steps");
                if status == "refused" {
                    refused = refused.saturating_add(1);
                    *by_case.entry(name.clone()).or_default() += 1;
                    assert!(
                        steps.is_empty(),
                        "{name}: a refused layer carries {} step(s)",
                        steps.len()
                    );
                    assert!(
                        layer.get("error").and_then(Json::as_str).is_some(),
                        "{name}: a refused layer carries no error text"
                    );
                } else {
                    assert!(
                        !steps.is_empty(),
                        "{name}: a produced layer carries no steps"
                    );
                }
            }
        }
    }
    assert!(
        refused > 0,
        "no committed trace carries a refused layer, so this control proves nothing"
    );
}
