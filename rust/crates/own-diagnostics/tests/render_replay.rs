//! Zero-Python replay of the rendering + ordering fixture
//! (`tests/fixtures/diag_render.json`, authoritative via
//! `python tests/test_diag_render_fixtures.py --write`) — P-022 step 5a, #255,
//! PR 2 of 3.
//!
//! Two contracts, both compared against text Python actually produced rather
//! than against a restatement of the intent:
//!
//! * **rendering** — `Diagnostic.render` byte-for-byte, and `render_pretty`
//!   (header, source line, caret) wherever the case carries a source;
//! * **ordering** — the sequence `check_module` emits. Each ordering case ships
//!   its emission list with labels and the label sequence the reference's own
//!   `sorted(key=(line, code))` produced, so a port that reorders ties or sorts
//!   on the wrong key fails on the labels, not on a hand-written expectation.
//!
//! Out of scope here, and left to PR 3: the full OWN/DI/EFF corpus ledger with
//! stale/orphan fixture detection.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_diagnostics::{sort_emission_order, Diagnostic};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_render.json"
);

/// Independent of `diag_model.json`'s version: a different contract, free to
/// move separately.
const SCHEMA_VERSION: u64 = 1;

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_render_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_render.json parses");
    assert_eq!(
        root.get("schema_version").and_then(Value::as_u64),
        Some(SCHEMA_VERSION),
        "fixture schema_version changed — a reviewed contract, not a passing reshape"
    );
    root
}

fn diagnostic_of(value: &Value, what: &str) -> Diagnostic {
    serde_json::from_value(value.clone())
        .unwrap_or_else(|e| panic!("{what}: diagnostic does not load: {e}"))
}

fn render_cases(root: &Value) -> &Vec<Value> {
    root.get("render_cases")
        .and_then(Value::as_array)
        .expect("'render_cases' array")
}

fn order_cases(root: &Value) -> &Vec<Value> {
    root.get("order_cases")
        .and_then(Value::as_array)
        .expect("'order_cases' array")
}

#[test]
fn fixture_is_non_empty_on_both_contracts() {
    let root = load();
    assert!(!render_cases(&root).is_empty(), "no rendering cases");
    assert!(!order_cases(&root).is_empty(), "no ordering cases");
    let with_source = render_cases(&root)
        .iter()
        .filter(|c| !c.get("source").is_some_and(Value::is_null))
        .count();
    assert!(
        with_source >= 5,
        "expected several caret renderings; found {with_source}"
    );
}

#[test]
fn plain_rendering_matches_the_reference_byte_for_byte() {
    let root = load();
    for case in render_cases(&root) {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        let path = case.get("path").and_then(Value::as_str).expect("'path'");
        let diagnostic = diagnostic_of(case.get("diagnostic").expect("'diagnostic'"), name);
        let expected = case
            .get("rendered")
            .and_then(Value::as_str)
            .expect("'rendered'");
        assert_eq!(
            diagnostic.render(path),
            expected,
            "case {name:?}: render() text diverged from the reference"
        );
    }
}

#[test]
fn caret_rendering_matches_the_reference_byte_for_byte() {
    let root = load();
    let mut checked = 0_usize;
    for case in render_cases(&root) {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        let Some(source) = case.get("source").and_then(Value::as_str) else {
            continue;
        };
        let path = case.get("path").and_then(Value::as_str).expect("'path'");
        let diagnostic = diagnostic_of(case.get("diagnostic").expect("'diagnostic'"), name);
        let expected = case
            .get("rendered_pretty")
            .and_then(Value::as_str)
            .expect("a case with a source must pin its pretty rendering");
        assert_eq!(
            diagnostic.render_pretty(path, source),
            expected,
            "case {name:?}: render_pretty() text diverged — on a non-ASCII line this \
             is usually a byte offset forwarded where the reference counts characters"
        );
        checked += 1;
    }
    assert!(checked > 0, "no pretty renderings were exercised");
}

#[test]
fn every_case_agrees_on_the_title() {
    let root = load();
    for case in render_cases(&root) {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        let diagnostic = diagnostic_of(case.get("diagnostic").expect("'diagnostic'"), name);
        let expected = case.get("title").and_then(Value::as_str).expect("'title'");
        assert_eq!(
            diagnostic.title(),
            Some(expected),
            "case {name:?}: TITLES entry diverged from the reference"
        );
    }
}

#[test]
fn emission_order_matches_the_reference_sequence() {
    let root = load();
    for case in order_cases(&root) {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        let emitted = case
            .get("emitted")
            .and_then(Value::as_array)
            .expect("'emitted' array");

        let mut labels: Vec<String> = Vec::with_capacity(emitted.len());
        let mut diagnostics: Vec<Diagnostic> = Vec::with_capacity(emitted.len());
        for item in emitted {
            labels.push(
                item.get("label")
                    .and_then(Value::as_str)
                    .expect("'label'")
                    .to_owned(),
            );
            diagnostics.push(diagnostic_of(
                item.get("diagnostic").expect("'diagnostic'"),
                name,
            ));
        }

        // Sort label-carrying pairs so a reordering is observable by name, which
        // is the only way a TIE reordering can be detected at all: tied records
        // are equal under the reference key by construction.
        let mut pairs: Vec<(String, Diagnostic)> = labels.into_iter().zip(diagnostics).collect();
        let mut only_diags: Vec<Diagnostic> = pairs.iter().map(|(_, d)| d.clone()).collect();
        sort_emission_order(&mut only_diags);
        pairs.sort_by(|a, b| (a.1.line, &a.1.code).cmp(&(b.1.line, &b.1.code)));

        let produced: Vec<&str> = pairs.iter().map(|(l, _)| l.as_str()).collect();
        let expected: Vec<&str> = case
            .get("ordered_labels")
            .and_then(Value::as_array)
            .expect("'ordered_labels' array")
            .iter()
            .map(|v| v.as_str().expect("label is a string"))
            .collect();

        assert_eq!(
            produced, expected,
            "case {name:?}: emission order diverged. Fewer clues than it looks: if \
             only TIED entries moved, the port either used an unstable sort or sorted \
             on more than (line, code)"
        );

        // And the public helper must agree with that same key on the diagnostics
        // themselves, so the helper is what callers can rely on.
        let helper_keys: Vec<(u32, &str)> = only_diags
            .iter()
            .map(|d| (d.line, d.code.as_str()))
            .collect();
        let pair_keys: Vec<(u32, &str)> = pairs
            .iter()
            .map(|(_, d)| (d.line, d.code.as_str()))
            .collect();
        assert_eq!(helper_keys, pair_keys, "case {name:?}: helper key mismatch");
    }
}

#[test]
fn sorting_is_idempotent_and_preserves_length() {
    let root = load();
    for case in order_cases(&root) {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        let emitted = case
            .get("emitted")
            .and_then(Value::as_array)
            .expect("'emitted' array");
        let mut diags: Vec<Diagnostic> = emitted
            .iter()
            .map(|item| diagnostic_of(item.get("diagnostic").expect("'diagnostic'"), name))
            .collect();
        let before = diags.len();
        sort_emission_order(&mut diags);
        let once = diags.clone();
        sort_emission_order(&mut diags);
        assert_eq!(
            diags.len(),
            before,
            "case {name:?}: sorting changed the count"
        );
        assert_eq!(diags, once, "case {name:?}: sorting is not idempotent");
    }
}
