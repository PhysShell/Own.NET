//! Zero-Python replay of the SARIF 2.1.0 projection
//! (`tests/fixtures/sarif_parity.json`, authoritative via
//! `python tests/test_sarif_parity_fixtures.py --write`) — P-022 step 5b, #256.
//!
//! ## The canonical comparison
//!
//! #256 forbids demanding raw byte identity where two correct serializers
//! legitimately differ, and equally forbids a wildcard "ignore metadata" rule.
//! What is actually done here:
//!
//! 1. parse both documents;
//! 2. remove **nothing** — the volatile-field list is empty, and the fixture's
//!    own generator proves it by census (no timestamp, GUID or absolute path)
//!    plus a determinism check (same input twice, byte-identical). The empty
//!    list is a measurement, not a shortcut;
//! 3. normalize only **object key order**, the one axis JSON declares
//!    unordered;
//! 4. leave every array in place — `results`, `relatedLocations` and
//!    `threadFlows[].locations` are ordered contracts and sorting them would
//!    erase exactly what this step pins;
//! 5. serialize the canonical form and compare bytes.
//!
//! Arrays being left alone is what makes the comparison strict rather than
//! convenient: a port that emitted the right *set* of results in the wrong
//! order fails here.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_diagnostics::{build_sarif, Diagnostic, SarifLog};
use serde_json::{Map, Value};

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/sarif_parity.json"
);

const SCHEMA_VERSION: u64 = 1;

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_sarif_parity_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("sarif_parity.json parses");
    assert_eq!(
        root.get("schema_version").and_then(Value::as_u64),
        Some(SCHEMA_VERSION),
        "fixture schema_version changed — a reviewed contract, not a passing reshape"
    );
    root
}

fn cases(root: &Value) -> &Vec<Value> {
    root.get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array")
}

fn name_of(case: &Value) -> &str {
    case.get("name")
        .and_then(Value::as_str)
        .expect("case 'name'")
}

/// Sort object keys recursively; leave arrays exactly as they are.
fn canonical(node: &Value) -> Value {
    match node {
        Value::Object(map) => {
            // BTreeMap ordering via serde_json::Map requires the
            // `preserve_order` feature to be OFF, which is the default — its
            // Map is already a BTreeMap, so collecting sorts for us. Build it
            // explicitly anyway so the guarantee does not ride on a feature
            // flag chosen elsewhere in the workspace.
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let mut out = Map::new();
            for k in keys {
                out.insert(k.clone(), canonical(&map[k]));
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical).collect()),
        other => other.clone(),
    }
}

fn diagnostics_of(case: &Value) -> Vec<Diagnostic> {
    let raw = case
        .get("diagnostics")
        .and_then(Value::as_array)
        .expect("case 'diagnostics'");
    raw.iter()
        .map(|d| {
            serde_json::from_value(d.clone()).unwrap_or_else(|e| {
                panic!("case {:?}: diagnostic does not load: {e}", name_of(case))
            })
        })
        .collect()
}

/// The migration packet's counters, computed rather than asserted by hand.
#[derive(Default, Debug)]
struct Counters {
    cases: usize,
    results: usize,
    changed: usize,
    unexplained: usize,
}

#[test]
fn sarif_projection_matches_the_reference_for_every_case() {
    let root = load();
    let mut counters = Counters::default();
    let mut first_divergence: Option<String> = None;

    for case in cases(&root) {
        counters.cases = counters.cases.saturating_add(1);
        let name = name_of(case);
        let filename = case
            .get("filename")
            .and_then(Value::as_str)
            .expect("case 'filename'");
        let severity = case
            .get("severity")
            .and_then(Value::as_str)
            .expect("case 'severity'");
        let expected = case.get("sarif").expect("case 'sarif'");
        counters.results = counters.results.saturating_add(
            expected
                .get("runs")
                .and_then(Value::as_array)
                .and_then(|r| r.first())
                .and_then(|r| r.get("results"))
                .and_then(Value::as_array)
                .map_or(0, Vec::len),
        );

        let produced = build_sarif(&diagnostics_of(case), filename, severity);
        let produced = serde_json::to_value(&produced).expect("SarifLog serializes");

        let (want, got) = (canonical(expected), canonical(&produced));
        if want != got {
            counters.changed = counters.changed.saturating_add(1);
            counters.unexplained = counters.unexplained.saturating_add(1);
            if first_divergence.is_none() {
                first_divergence = Some(format!(
                    "case {name:?}\n  expected: {}\n  produced: {}",
                    serde_json::to_string_pretty(&want).unwrap_or_default(),
                    serde_json::to_string_pretty(&got).unwrap_or_default(),
                ));
            }
        }
    }

    // Equal by construction: this replay has no mechanism for marking a
    // difference as explained, so both counters move on the same branch. The
    // assertion forces that to be revisited deliberately if one is ever added.
    // On a green tree it is 0 == 0 and proves nothing — it arms only once
    // something diverges, which is when a silently over-reporting `unexplained`
    // would mislead.
    assert_eq!(
        counters.changed, counters.unexplained,
        "changed and unexplained are equal by construction; they diverged: {counters:?}"
    );
    assert_eq!(
        counters.unexplained,
        0,
        "#256 requires zero unexplained diff. Counters: {counters:?}\n\
         first divergence:\n{}",
        first_divergence.as_deref().unwrap_or("<none>")
    );
}

#[test]
fn the_volatile_field_list_is_empty_and_stays_that_way() {
    // #256 requires every removed/normalized field to be enumerated and
    // justified. The list is empty, so the contract to defend is that it stays
    // empty: if a future log gains a timestamp or run id, this fails and forces
    // the field to be justified rather than quietly stripped.
    let root = load();
    let declared = root
        .get("volatile_fields")
        .and_then(Value::as_array)
        .expect("'volatile_fields'");
    assert!(
        declared.is_empty(),
        "volatile_fields is no longer empty ({declared:?}); the canonical \
         comparison must enumerate and justify each entry, never wildcard them"
    );
}

#[test]
fn canonicalization_sorts_object_keys_but_never_reorders_arrays() {
    // The canonicalizer is load-bearing: if it sorted arrays, the ordering
    // contracts above would silently stop being tested. Pin both halves.
    let reordered_keys: Value =
        serde_json::from_str(r#"{"b": 1, "a": {"d": 2, "c": 3}}"#).expect("parses");
    let sorted_keys: Value =
        serde_json::from_str(r#"{"a": {"c": 3, "d": 2}, "b": 1}"#).expect("parses");
    assert_eq!(
        canonical(&reordered_keys),
        canonical(&sorted_keys),
        "object key order must be normalized away"
    );

    let forward: Value = serde_json::from_str("[1, 2, 3]").expect("parses");
    let backward: Value = serde_json::from_str("[3, 2, 1]").expect("parses");
    assert_ne!(
        canonical(&forward),
        canonical(&backward),
        "array order must SURVIVE canonicalization — results, relatedLocations \
         and threadFlow locations are ordered contracts"
    );
}

#[test]
fn every_artifact_location_uri_is_non_empty_and_slash_normalized() {
    // The invariant `ownlang/evidence.py` calls out by name: an empty
    // `artifactLocation.uri` makes the whole log unprocessable for GitHub code
    // scanning, and a backslash is not a URI separator. Checked over the
    // RUST-produced logs, not the fixture, so it constrains the port.
    let root = load();
    let mut uris: Vec<String> = Vec::new();
    for case in cases(&root) {
        let filename = case
            .get("filename")
            .and_then(Value::as_str)
            .expect("case 'filename'");
        let severity = case
            .get("severity")
            .and_then(Value::as_str)
            .expect("case 'severity'");
        let log = build_sarif(&diagnostics_of(case), filename, severity);
        collect_uris(
            &serde_json::to_value(&log).expect("SarifLog serializes"),
            &mut uris,
        );
    }
    assert!(
        !uris.is_empty(),
        "no uris collected — the walk is broken, not the invariant"
    );
    let empty = uris.iter().filter(|u| u.is_empty()).count();
    assert_eq!(empty, 0, "{empty} empty artifactLocation.uri value(s)");
    let backslashed: Vec<&String> = uris.iter().filter(|u| u.contains('\\')).collect();
    assert!(
        backslashed.is_empty(),
        "uri(s) still carry a backslash: {backslashed:?}"
    );
}

fn collect_uris(node: &Value, out: &mut Vec<String>) {
    match node {
        Value::Object(map) => {
            for (k, v) in map {
                if k == "artifactLocation" {
                    out.push(
                        v.get("uri")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_owned(),
                    );
                } else {
                    collect_uris(v, out);
                }
            }
        }
        Value::Array(items) => {
            for v in items {
                collect_uris(v, out);
            }
        }
        _ => {}
    }
}

#[test]
fn the_log_round_trips_through_the_typed_model() {
    // The port models SARIF as typed structs rather than free-form JSON. That
    // only holds if the typed model can also READ what it writes — otherwise a
    // field could be write-only and silently absent from the contract.
    let root = load();
    for case in cases(&root) {
        let name = name_of(case);
        let expected = case.get("sarif").expect("case 'sarif'");
        let parsed: SarifLog = serde_json::from_value(expected.clone())
            .unwrap_or_else(|e| panic!("case {name:?}: reference log does not load: {e}"));
        let reserialized = serde_json::to_value(&parsed).expect("SarifLog serializes");
        assert_eq!(
            canonical(expected),
            canonical(&reserialized),
            "case {name:?}: the typed model lost or invented a field on round-trip"
        );
    }
}

#[test]
fn code_scanning_acceptance_invariants_hold_for_every_case() {
    // #256 lists "GitHub upload of Rust-generated SARIF" as a control. That is
    // not reachable at this step and not fudged here: the Rust workspace has no
    // binary target, so nothing can WRITE a log, and #256's own guardrail says
    // "no CLI migration". Adding a throwaway binary to tick the box would cross
    // the line the step exists to respect.
    //
    // What is verifiable — and what the upload would actually be testing — is
    // that the produced log satisfies the structural rules a code-scanning
    // ingest enforces. Combined with byte-identity against the Python log that
    // CI already uploads successfully (the dog-food job), acceptance follows
    // from identity rather than from an untested claim.
    let root = load();
    for case in cases(&root) {
        let name = name_of(case);
        let filename = case
            .get("filename")
            .and_then(Value::as_str)
            .expect("case 'filename'");
        let severity = case
            .get("severity")
            .and_then(Value::as_str)
            .expect("case 'severity'");
        let log = build_sarif(&diagnostics_of(case), filename, severity);
        let run = log.runs.first().expect("a log always carries one run");

        let catalogue: std::collections::BTreeSet<&str> = run
            .tool
            .driver
            .rules
            .iter()
            .map(|r| r.id.as_str())
            .collect();
        for result in &run.results {
            // An ingest resolves every result's ruleId against the driver's
            // rules; a dangling id loses the rule metadata on the finding.
            assert!(
                catalogue.contains(result.rule_id.as_str()),
                "case {name:?}: result ruleId {:?} is absent from the rules \
                 catalogue {catalogue:?}",
                result.rule_id
            );
            // SARIF 2.1.0 §3.27.10 constrains `level` to a fixed enum.
            assert!(
                matches!(result.level.as_str(), "error" | "warning" | "note" | "none"),
                "case {name:?}: level {:?} is not a SARIF level",
                result.level
            );
            for location in &result.locations {
                if let Some(region) = &location.physical_location.region {
                    assert!(
                        region.start_line >= 1,
                        "case {name:?}: startLine must be 1-based, got {}",
                        region.start_line
                    );
                }
            }
        }
    }
}

#[test]
fn tool_identity_stays_owen() {
    // #256 acceptance: "Tool identity remains `Owen`". Asserted over the
    // RUST-produced log so a rename in the port is caught here rather than by a
    // downstream consumer.
    let log = build_sarif(&[], "x.own", "error");
    let run = log.runs.first().expect("a log always carries one run");
    assert_eq!(run.tool.driver.name, "Owen");
    assert_eq!(log.version, "2.1.0");
    assert!(log.schema.ends_with("sarif-schema-2.1.0.json"));
}
