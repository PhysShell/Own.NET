//! The first parity check of the migration (P-022 step 1): `own-ir` must
//! round-trip every `OwnIR` fixture the Python core's test suite uses,
//! value-for-value — typed fields and additive `extra` fields alike.

// Tests fail by panicking — that IS their reporting mechanism, so the
// production bans on `panic!`/`expect` don't apply in this file (justified,
// file-scoped allow per the strictness doctrine in P-022).
#![allow(clippy::panic, clippy::expect_used)]

use own_ir::{OwnIr, OWNIR_VERSION};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn fixtures_dir() -> PathBuf {
    // rust/crates/own-ir -> repo root is three levels up.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/ownir")
}

#[test]
fn round_trips_every_python_fixture() {
    let dir = fixtures_dir();
    let mut seen = 0u32;
    let entries = fs::read_dir(&dir).expect("OwnIR fixture dir must exist (run from the repo)");
    for entry in entries {
        let path = entry.expect("readable dir entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let text = fs::read_to_string(&path).expect("fixture must be readable");
        let original: Value = serde_json::from_str(&text).expect("fixture must be valid JSON");
        let doc = OwnIr::from_json(&text)
            .unwrap_or_else(|e| panic!("{} must parse like Python load(): {e}", path.display()));
        let back = doc.to_value().expect("round-trip serialization");
        assert_eq!(
            back,
            original,
            "{} must round-trip value-for-value",
            path.display()
        );
        seen = seen.saturating_add(1);
    }
    assert!(seen >= 15, "expected the fixture corpus, found only {seen}");
}

#[test]
fn version_gate_rejects_future_schema() {
    let err = OwnIr::from_json(r#"{"ownir_version": 1}"#).expect_err("v1 must be rejected");
    assert!(
        err.0.contains("schema v1") && err.0.contains(&format!("v{OWNIR_VERSION}")),
        "gate message must name both versions: {err}"
    );
}

#[test]
fn absent_version_means_v0() {
    let doc = OwnIr::from_json(r#"{"components": []}"#).expect("pre-versioning producers are v0");
    assert_eq!(doc.ownir_version, None);
}

#[test]
fn bool_is_not_an_integer() {
    // Python needs an explicit `isinstance(x, bool)` check because bool is an
    // int subclass; Rust must reject it too for acceptance parity.
    let res =
        OwnIr::from_json(r#"{"services": [{"lifetime": "singleton", "name": "A", "line": true}]}"#);
    assert!(res.is_err(), "a boolean 'line' must be rejected");
}

#[test]
fn lifetime_vocabulary_is_closed() {
    let res = OwnIr::from_json(r#"{"services": [{"lifetime": "static", "name": "A"}]}"#);
    assert!(res.is_err(), "an unknown lifetime must be rejected");
}

#[test]
fn empty_identity_fields_are_rejected() {
    let res = OwnIr::from_json(r#"{"services": [{"lifetime": "scoped", "name": ""}]}"#);
    assert!(res.is_err(), "an empty service name must be rejected");
    let res = OwnIr::from_json(r#"{"functions": [{"params": [{"name": ""}]}]}"#);
    assert!(res.is_err(), "an empty parameter name must be rejected");
}

#[test]
fn param_effect_vocabulary_is_closed() {
    let res = OwnIr::from_json(r#"{"functions": [{"params": [{"name": "s", "effect": "own"}]}]}"#);
    assert!(res.is_err(), "an unknown param effect must be rejected");
    let ok =
        OwnIr::from_json(r#"{"functions": [{"params": [{"name": "s", "effect": "borrow_mut"}]}]}"#);
    assert!(ok.is_ok(), "borrow_mut is in the vocabulary");
}

#[test]
fn additive_unknown_fields_are_preserved() {
    let text = r#"{
        "module": "M",
        "future_top_level": {"x": 1},
        "components": [{"name": "C", "future_field": [1, 2],
                        "subscriptions": [{"event": "e", "released": false}]}]
    }"#;
    let original: Value = serde_json::from_str(text).expect("valid JSON");
    let doc = OwnIr::from_json(text).expect("additive fields are tolerated");
    assert_eq!(doc.to_value().expect("serialize"), original);
}
