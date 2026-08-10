//! #259 cp4's acceptance: replay every frozen verdict case with zero Python.
//!
//! ```text
//! case document → own_ir::OwnIr → own_verdicts::check_facts
//!               → {di, effects}  ==  tests/fixtures/ownir/verdicts.json
//! ```
//!
//! TWO channels, not three. `core` is blocked on `Diagnostic.subject`, which
//! `own-analysis` does not stamp, and on the handle → C# line mapping the
//! reference anchors flow-local findings with — both cp5 by name. The measured
//! divergence (40 of 51 agreeing, 11 differing in the LINE) is written out in
//! `facts.rs`. cp4 is NOT closed by this file.
//!
//! The golden is EXPECTED OUTPUT only, never an input to construction. Each
//! channel is compared as an ORDERED LIST at the granularity the oracle froze —
//! `core` is `(line, code)`, the fact-driven channels are `(path, line, code)`.
//! Comparing as sets would drop the BR-V8 final ordering, which one case exists
//! specifically to pin.
//!
//! `protocols` and `advisories` are frozen OBSERVATIONS for cp5. They are read
//! here only to assert that this crate does NOT claim them: a green replay of
//! three channels must not be readable as evidence about five.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_verdicts::{check_facts, VerdictChannels};
use serde_json::Value;

const FIXDIR: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures/ownir");

fn golden() -> Value {
    let path = format!("{FIXDIR}/verdicts.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!("cannot read {path}: {e} — regenerate: python tests/test_ownir_verdict_fixtures.py --write")
    });
    serde_json::from_str(&text).expect("verdicts.json parses")
}

/// The document a case replays. A `fixture` case names a `.facts.json` on disk;
/// a `witness` carries its document inline. Both are the reference's input,
/// never something this test composes.
fn document(case: &Value) -> Value {
    match case.get("origin").and_then(Value::as_str) {
        Some("fixture") => {
            let source = case["source"].as_str().expect("a fixture names its source");
            let path = format!("{FIXDIR}/{source}");
            serde_json::from_str(
                &std::fs::read_to_string(&path)
                    .unwrap_or_else(|e| panic!("cannot read {path}: {e}")),
            )
            .unwrap_or_else(|e| panic!("{source} does not parse: {e}"))
        }
        _ => case["document"].clone(),
    }
}

/// `[[file, line, code], …]` — the frozen fact-driven shape.
fn frozen_triples(case: &Value, channel: &str) -> Vec<(String, i64, String)> {
    case[channel]
        .as_array()
        .unwrap_or_else(|| panic!("{channel} is a list"))
        .iter()
        .map(|row| {
            (
                row[0].as_str().expect("file is a string").to_owned(),
                row[1].as_i64().expect("line is an integer"),
                row[2].as_str().expect("code is a string").to_owned(),
            )
        })
        .collect()
}

fn got_triples(rows: &[(String, own_ir::span::SourceLine, String)]) -> Vec<(String, i64, String)> {
    rows.iter()
        .map(|(f, l, c)| (f.clone(), l.get(), c.clone()))
        .collect()
}

#[test]
fn replays_every_frozen_case_on_the_fact_driven_channels() {
    let doc = golden();
    assert_eq!(
        doc["verdicts_version"].as_i64(),
        Some(1),
        "this replay is keyed to verdicts_version 1"
    );
    let cases = doc["cases"].as_array().expect("cases is a list");

    let mut replayed = 0_usize;
    for case in cases {
        let name = case["name"].as_str().expect("every case is named");
        // Deserialized WITHOUT the strict door, like own-bridge's own replay:
        // `check_facts` is the TOLERANT entry an embedder reaches directly, and
        // routing through `load()` would test a different door.
        let facts: own_ir::OwnIr = serde_json::from_value(document(case))
            .unwrap_or_else(|e| panic!("{name}: the case document does not deserialize: {e}"));

        let got = check_facts(&facts)
            .unwrap_or_else(|e| panic!("{name}: the composition rejected a frozen case: {e}"));

        assert_eq!(
            got_triples(&got.di),
            frozen_triples(case, "di"),
            "{name}: di channel"
        );
        assert_eq!(
            got_triples(&got.effects),
            frozen_triples(case, "effects"),
            "{name}: effects channel"
        );
        replayed = replayed.saturating_add(1);
    }

    assert_eq!(
        replayed,
        cases.len(),
        "every frozen case must be replayed, none skipped"
    );
    assert!(
        replayed >= 51,
        "the oracle should still carry the whole frozen set, replayed {replayed}"
    );
}

/// The channels cp4 does NOT own must stay unclaimed.
///
/// `VerdictChannels` has three fields and the oracle freezes five. This asserts
/// the gap is real rather than accidental: the frozen `protocols`/`advisories`
/// rows exist, and nothing in this crate produces them — so a green replay
/// above cannot be read as "cp4 covers five channels".
#[test]
fn protocols_and_advisories_are_observations_this_crate_does_not_claim() {
    let doc = golden();
    let cases = doc["cases"].as_array().expect("cases is a list");

    let frozen_rows: usize = cases
        .iter()
        .map(|c| {
            c["protocols"].as_array().map_or(0, Vec::len)
                + c["advisories"].as_array().map_or(0, Vec::len)
        })
        .sum();
    assert!(
        frozen_rows > 0,
        "the oracle should still freeze protocols/advisories rows — with none, \
         this test would pass by observing nothing"
    );

    // The type is the assertion: a field added here without a channel to
    // compare it against would be an unproven claim, and adding one would not
    // compile against this destructuring.
    let VerdictChannels { di: _, effects: _ } = VerdictChannels::default();
}
