//! Comparison-harness plumbing against the frozen diagnostics-parity fixture
//! (`tests/fixtures/diag_parity.json`, authoritative via
//! `python tests/test_diag_fixtures.py --write`).
//!
//! This is the Rust side of the #214 oracle at **checkpoint 1**: the semantic
//! port (parse → lower → analyse → construct diagnostics) does not exist yet, so
//! this test does not *produce* diagnostics. What it locks now is the
//! comparison contract itself — the exact shape the replay will diff against:
//!
//! * the fixture parses into the `(name, source, diags)` case model;
//! * every `code` in every case is a **known** [`own_diagnostics::TITLES`] entry
//!   (so the golden set can never freeze a titleless code — the same guard the
//!   Python side enforces at construction);
//! * each case's diagnostics load into an ordered `Vec<DiagKey>` preserving
//!   emission order, which is the deterministic intra-location ordering the
//!   oracle pins;
//! * the golden set round-trips through the parity types unchanged.
//!
//! When `own-analysis` lands, its `tests/parity.rs` replays each `source`
//! through the `check` surface and asserts `produced == case.expected` using
//! exactly this `expected` vector. The TODO below marks that seam.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_diagnostics::{title, DiagKey};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_parity.json"
);

/// One frozen case: the input identity, its source, and the golden ordered
/// `(line, code)` verdict list the Rust `check` surface must reproduce.
struct Case {
    name: String,
    #[allow(dead_code)] // consumed by own-analysis's replay at the next checkpoint
    source: String,
    expected: Vec<DiagKey>,
}

fn load_cases() -> Vec<Case> {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_parity.json parses");
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array");
    cases
        .iter()
        .map(|case| {
            let name = case
                .get("name")
                .and_then(Value::as_str)
                .expect("case 'name'")
                .to_owned();
            let source = case
                .get("source")
                .and_then(Value::as_str)
                .expect("case 'source'")
                .to_owned();
            let expected = case
                .get("diags")
                .and_then(Value::as_array)
                .expect("case 'diags' array")
                .iter()
                .map(|pair| {
                    let pair = pair.as_array().expect("each diag is a [line, code] pair");
                    let line = pair
                        .first()
                        .and_then(Value::as_u64)
                        .expect("diag line is a number");
                    let code = pair
                        .get(1)
                        .and_then(Value::as_str)
                        .expect("diag code is a string");
                    DiagKey::new(u32::try_from(line).expect("line fits u32"), code)
                })
                .collect();
            Case {
                name,
                source,
                expected,
            }
        })
        .collect()
}

#[test]
fn fixture_loads_and_is_non_empty() {
    let cases = load_cases();
    assert!(!cases.is_empty(), "diag parity corpus must not be empty");
    // The corpus + curated set is 60+ cases; guard against a truncated fixture.
    assert!(
        cases.len() >= 60,
        "expected the full corpus (60+ cases), found {}",
        cases.len()
    );
}

#[test]
fn every_frozen_code_is_a_known_title() {
    for case in load_cases() {
        for key in &case.expected {
            assert!(
                title(&key.code).is_some(),
                "case {:?} froze unknown code {:?} — the golden set must never \
                 carry a titleless code (regenerate the fixture / add the title)",
                case.name,
                key.code
            );
        }
    }
}

#[test]
fn diagnostics_load_in_emission_order() {
    // Within a case the list order IS the contract (intra-location ordering).
    // A round-trip through DiagKey must preserve it verbatim — no sorting, no
    // dedup (the parity policy forbids sorting away meaningful duplicates).
    for case in load_cases() {
        let reloaded: Vec<DiagKey> = case.expected.clone();
        assert_eq!(
            reloaded, case.expected,
            "DiagKey load must preserve emission order for case {:?}",
            case.name
        );
    }
}

// TODO(#214, checkpoint 2 — own-analysis): replay each `case.source` through the
// ported `check` surface and assert the produced `Vec<DiagKey>` equals
// `case.expected` exactly. That step needs the worklist solver + ownership /
// lifetime analyses, which land after this checkpoint's fixture + comparison
// design are reviewed. `Case.source` is carried now so the replay is a pure
// addition here, not a fixture reshape.
