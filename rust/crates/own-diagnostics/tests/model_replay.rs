//! Zero-Python replay of the structured diagnostic-model fixture
//! (`tests/fixtures/diag_model.json`, authoritative via
//! `python tests/test_diag_model_fixtures.py --write`) — P-022 step 5a, #255,
//! PR 1 of 3.
//!
//! The differential claim under test is narrow and concrete: **Python's
//! frozen-dataclass equality and Rust's [`DiagIdentity`] must partition the same
//! records the same way.** Each fixture case carries near-identical records and
//! the `distinct_records` count Python computed over them; a Rust key that
//! collapses any pair (or splits an identical pair) disagrees with that count and
//! fails here. That is why the fixture is not merely "some structs round-trip":
//! the count is a reference behaviour, not a hand-written expectation.
//!
//! Out of scope for this slice, and deliberately not asserted: canonical message
//! *text* and the Python-pinned ordering of findings on an output surface (PR 2),
//! and coverage of every emitted OWN/DI/EFF family (PR 3). Ordering is checked
//! here only as a *property* — total, antisymmetric, reproducible — because a
//! non-total key would make the identity itself unsound.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::collections::BTreeSet;

use own_diagnostics::{title, DiagIdentity, LocatedDiagnostic};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_model.json"
);

/// The schema this slice froze. A bump means the envelope changed and both sides
/// must be re-reviewed together — PR 2 and PR 3 add *cases*, never a reshape.
const SCHEMA_VERSION: u64 = 1;

/// One frozen case: near-identical records plus the number of DISTINCT findings
/// Python's own dataclass equality found among them.
struct Case {
    name: String,
    records: Vec<LocatedDiagnostic>,
    distinct_records: usize,
}

fn load_cases() -> Vec<Case> {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_model_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_model.json parses");

    let version = root
        .get("schema_version")
        .and_then(Value::as_u64)
        .expect("'schema_version'");
    assert_eq!(
        version, SCHEMA_VERSION,
        "fixture schema_version changed — the envelope is a reviewed contract, \
         not something a later slice reshapes in passing"
    );

    root.get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array")
        .iter()
        .map(|case| {
            let name = case
                .get("name")
                .and_then(Value::as_str)
                .expect("case 'name'")
                .to_owned();
            let records: Vec<LocatedDiagnostic> = case
                .get("records")
                .and_then(Value::as_array)
                .expect("case 'records' array")
                .iter()
                .map(|r| {
                    serde_json::from_value(r.clone()).unwrap_or_else(|e| {
                        panic!("case {name:?}: record does not load into LocatedDiagnostic: {e}")
                    })
                })
                .collect();
            let distinct_records = usize::try_from(
                case.get("distinct_records")
                    .and_then(Value::as_u64)
                    .expect("case 'distinct_records'"),
            )
            .expect("distinct_records fits usize");
            Case {
                name,
                records,
                distinct_records,
            }
        })
        .collect()
}

fn all_identities() -> Vec<DiagIdentity> {
    load_cases()
        .iter()
        .flat_map(|c| c.records.iter().map(LocatedDiagnostic::identity))
        .collect()
}

#[test]
fn fixture_loads_and_is_non_empty() {
    let cases = load_cases();
    assert!(!cases.is_empty(), "the model corpus must not be empty");
    for case in &cases {
        assert!(
            case.records.len() >= 2,
            "case {:?} has fewer than two records — an identity case must compare \
             at least one pair to prove anything",
            case.name
        );
    }
}

#[test]
fn identity_partitions_exactly_as_python_equality_does() {
    for case in load_cases() {
        let distinct: BTreeSet<DiagIdentity> = case
            .records
            .iter()
            .map(LocatedDiagnostic::identity)
            .collect();
        assert_eq!(
            distinct.len(),
            case.distinct_records,
            "case {:?}: Rust's DiagIdentity found {} distinct record(s) where Python's \
             dataclass equality found {}. Fewer means the key COLLAPSES findings the \
             reference keeps apart; more means it SPLITS records the reference calls equal",
            case.name,
            distinct.len(),
            case.distinct_records,
        );
    }
}

#[test]
fn every_frozen_code_is_a_known_title() {
    for case in load_cases() {
        for record in &case.records {
            assert!(
                title(&record.diagnostic.code).is_some(),
                "case {:?} froze unknown code {:?} — the golden set must never carry a \
                 titleless code (the same guard the Python side enforces at construction)",
                case.name,
                record.diagnostic.code,
            );
        }
    }
}

/// Every key the Python writer emits, per level of the record. Asserted as an
/// EXACT set, not a subset: a lost key means the fixture stopped carrying part
/// of the contract, and an added key means Python grew a field Rust is silently
/// discarding (serde ignores unknown fields by default, so nothing else would
/// notice). Pinned here rather than via `deny_unknown_fields` on the type: the
/// exactness belongs to this fixture, and the types may later be fed by
/// producers whose tolerance is a separate decision.
const RECORD_KEYS: [&str; 3] = ["path", "column", "diagnostic"];
const DIAGNOSTIC_KEYS: [&str; 7] = [
    "code",
    "message",
    "line",
    "severity",
    "subject",
    "resource_kind",
    "evidence",
];
const EVIDENCE_KEYS: [&str; 4] = ["line", "label", "file", "role"];

fn key_set(value: &Value, what: &str) -> BTreeSet<String> {
    value
        .as_object()
        .unwrap_or_else(|| panic!("{what} is a JSON object"))
        .keys()
        .cloned()
        .collect()
}

fn expected(keys: &[&str]) -> BTreeSet<String> {
    keys.iter().map(|k| (*k).to_owned()).collect()
}

#[test]
fn fixture_shape_is_pinned_key_for_key() {
    // The round-trip test below serialises a Rust value and reads Rust's own
    // output back, so it cannot see the PYTHON writer drifting — and the two
    // shapes are not identical: Rust omits `subject`/`resource_kind`/empty
    // `evidence` (step-4 `skip_serializing_if`) where Python writes `null`/`[]`.
    // Reading is unaffected, which is precisely what makes the drift invisible.
    // So the writer's shape is pinned here, against the raw JSON.
    let raw = std::fs::read_to_string(FIXTURE).expect("fixture readable");
    let root: Value = serde_json::from_str(&raw).expect("diag_model.json parses");

    for case in root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array")
    {
        let name = case.get("name").and_then(Value::as_str).unwrap_or("<?>");
        for record in case
            .get("records")
            .and_then(Value::as_array)
            .expect("'records' array")
        {
            assert_eq!(
                key_set(record, "record"),
                expected(&RECORD_KEYS),
                "case {name:?}: record key set drifted from the Python writer"
            );
            let diagnostic = record.get("diagnostic").expect("'diagnostic'");
            assert_eq!(
                key_set(diagnostic, "diagnostic"),
                expected(&DIAGNOSTIC_KEYS),
                "case {name:?}: diagnostic key set drifted from the Python writer"
            );

            let steps = diagnostic
                .get("evidence")
                .and_then(Value::as_array)
                .expect("'evidence' is always written, as [] when empty");
            for step in steps {
                assert_eq!(
                    key_set(step, "evidence step"),
                    expected(&EVIDENCE_KEYS),
                    "case {name:?}: evidence step key set drifted from the Python writer"
                );
            }

            // Arity must survive the load: a step dropped on read would leave the
            // identity comparing a shorter reachability path than Python wrote.
            let loaded: LocatedDiagnostic =
                serde_json::from_value(record.clone()).expect("record loads");
            assert_eq!(
                loaded.diagnostic.evidence.len(),
                steps.len(),
                "case {name:?}: evidence arity drifted between the fixture and the model"
            );
        }
    }
}

#[test]
fn records_round_trip_through_the_model_unchanged() {
    // Serde is the load-bearing seam for every later slice (report/SARIF read
    // these same types), so a lossy field would silently truncate the contract.
    // NOTE: this is Rust→JSON→Rust and proves only self-consistency; the Python
    // writer's shape is pinned by `fixture_shape_is_pinned_key_for_key`.
    for case in load_cases() {
        for record in &case.records {
            let json = serde_json::to_value(record).expect("record serialises");
            let back: LocatedDiagnostic =
                serde_json::from_value(json).expect("record deserialises");
            assert_eq!(
                &back, record,
                "case {:?}: record did not survive a model round-trip",
                case.name
            );
            assert_eq!(back.identity(), record.identity());
        }
    }
}

#[test]
fn line_is_delegated_to_the_ported_value() {
    // The envelope adds `path`/`column`; the anchor line stays on the ported
    // dataclass, and the accessor must not drift into a second source of truth.
    for case in load_cases() {
        for record in &case.records {
            assert_eq!(
                record.line(),
                record.diagnostic.line,
                "case {:?}",
                case.name
            );
        }
    }
}

#[test]
fn identity_ordering_is_a_total_order() {
    let ids = all_identities();
    for a in &ids {
        for b in &ids {
            // Antisymmetry + totality: exactly one of <, ==, > holds.
            let ord = a.cmp(b);
            assert_eq!(
                ord == std::cmp::Ordering::Equal,
                a == b,
                "Ord and Eq disagree for {a:?} vs {b:?}"
            );
            assert_eq!(
                ord.reverse(),
                b.cmp(a),
                "ordering is not antisymmetric for {a:?} vs {b:?}"
            );
            for c in &ids {
                if a <= b && b <= c {
                    assert!(
                        a <= c,
                        "ordering is not transitive: {a:?} <= {b:?} <= {c:?}"
                    );
                }
            }
        }
    }
}

#[test]
fn sorting_is_reproducible_from_any_input_permutation() {
    // Determinism is the property this slice actually owes the oracle: the same
    // set must sort to the same sequence regardless of how it arrived. (WHICH
    // sequence a report emits is PR 2's contract, pinned against Python.)
    let mut forward = all_identities();
    let mut reversed = forward.clone();
    reversed.reverse();
    forward.sort();
    reversed.sort();
    assert_eq!(
        forward, reversed,
        "sorting depends on input order — the identity is not a deterministic key"
    );
}
