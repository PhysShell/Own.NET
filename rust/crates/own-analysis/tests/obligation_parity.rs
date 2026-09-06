//! Fact-level differential parity for the obligation-protocol analysis
//! (OBL001–005) — the Rust side of the Python-authored oracle
//! (`tests/fixtures/obligation_fact_parity.json`, regenerate:
//! `python tests/test_obligation_fact_parity.py --write`), #259 checkpoint 4b.
//!
//! ```text
//! raw protocols[] / protocol_functions[] documents
//!   → own_ir::protocol::{parse_protocol, parse_method}
//!   → own_analysis::{check_protocols, unmatched_scopes}
//!   ≡  the frozen violation list and dead-rule list, member for member
//! ```
//!
//! The family has no `.own` surface and Python is the reference, exactly as for
//! DI and effects (`fact_parity.rs`). Two things make it a real differential
//! rather than a re-assertion:
//!
//! * the cases carry the **raw documents**, so this side builds the typed
//!   values with its own half of the shared grammar. A grammar that accepted
//!   the same records and built a different value would show up here as a
//!   verdict divergence rather than passing unnoticed;
//! * every member of a violation is compared — `line`, `definite`, `open_line`,
//!   `barrier_desc` and `close_line` included — in the reference's order, so a
//!   port that got the anchor right and the provenance wrong is red.
//!
//! Codes, messages and evidence slices are deliberately absent: those are the
//! bridge's (BR-P3) and the Layer 3 verdict family compares them.
//!
//! Divergences are collected without fail-fast (P-022 discipline rule 3) and
//! reported together, each naming its case.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_analysis::{check_protocols, unmatched_scopes};
use own_ir::protocol::{parse_method, parse_protocol, MethodEvents, Protocol};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/obligation_fact_parity.json"
);

/// The surface version the fixture and this replay agree on. A bump is a
/// reviewed contract change, not a passing reshape.
const PARITY_VERSION: u64 = 1;

/// One violation as the fixture spells it — the comparison key, in the
/// reference dataclass's member order.
#[derive(Debug, PartialEq, Eq)]
struct Row {
    protocol: String,
    method: String,
    file: String,
    line: i64,
    kind: String,
    definite: bool,
    open_line: i64,
    barrier_desc: String,
    close_line: Option<i64>,
}

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE).expect(
        "fixture missing — regenerate: python tests/test_obligation_fact_parity.py --write",
    );
    let root: Value = serde_json::from_str(&raw).expect("obligation_fact_parity.json parses");
    assert_eq!(
        root.get("obligation_parity_version")
            .and_then(Value::as_u64),
        Some(PARITY_VERSION),
        "the fixture's surface version changed — teach this replay the new version"
    );
    root
}

/// The golden rows of one case, read strictly: a missing or mistyped member is
/// a fixture the replay does not understand, not a member to skip.
fn golden_rows(case: &Value) -> Vec<Row> {
    case.get("expected")
        .and_then(Value::as_array)
        .expect("'expected'")
        .iter()
        .map(|v| Row {
            protocol: v
                .get("protocol")
                .and_then(Value::as_str)
                .expect("protocol")
                .to_owned(),
            method: v
                .get("method")
                .and_then(Value::as_str)
                .expect("method")
                .to_owned(),
            file: v
                .get("file")
                .and_then(Value::as_str)
                .expect("file")
                .to_owned(),
            line: v.get("line").and_then(Value::as_i64).expect("line"),
            kind: v
                .get("kind")
                .and_then(Value::as_str)
                .expect("kind")
                .to_owned(),
            definite: v
                .get("definite")
                .and_then(Value::as_bool)
                .expect("definite"),
            open_line: v
                .get("open_line")
                .and_then(Value::as_i64)
                .expect("open_line"),
            barrier_desc: v
                .get("barrier_desc")
                .and_then(Value::as_str)
                .expect("barrier_desc")
                .to_owned(),
            // `null` is the reference's "no late close"; a missing key is a
            // malformed golden and is not read as one.
            close_line: match v.get("close_line") {
                Some(Value::Null) => None,
                Some(other) => Some(other.as_i64().expect("close_line is an integer")),
                None => panic!("golden row carries no 'close_line'"),
            },
        })
        .collect()
}

fn documents(case: &Value, key: &str) -> Vec<Value> {
    case.get(key)
        .and_then(Value::as_array)
        .unwrap_or_else(|| panic!("case carries '{key}'"))
        .clone()
}

fn strings(case: &Value, key: &str) -> Vec<String> {
    case.get(key)
        .and_then(Value::as_array)
        .unwrap_or_else(|| panic!("case carries '{key}'"))
        .iter()
        .map(|v| v.as_str().expect("a name").to_owned())
        .collect()
}

#[test]
fn obligation_fact_parity() {
    let root = load();
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases'");
    let mut failures: Vec<String> = Vec::new();
    let mut violations = 0_usize;
    let mut dead_rules = 0_usize;

    for case in cases {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        // The grammar is the port's, not the fixture's: a record the reference
        // accepted must construct here too, or the two doors disagree.
        let protocols: Vec<Protocol> = documents(case, "protocols")
            .iter()
            .map(|p| {
                parse_protocol(p).unwrap_or_else(|e| {
                    panic!("{name}: the port refuses a protocol Python accepted: {e}")
                })
            })
            .collect();
        let methods: Vec<MethodEvents> = documents(case, "methods")
            .iter()
            .map(|m| {
                parse_method(m).unwrap_or_else(|e| {
                    panic!("{name}: the port refuses a method Python accepted: {e}")
                })
            })
            .collect();

        let got: Vec<Row> = check_protocols(&protocols, &methods)
            .into_iter()
            .map(|v| Row {
                protocol: v.protocol,
                method: v.method,
                file: v.file,
                line: v.line,
                kind: v.kind.as_str().to_owned(),
                definite: v.definite,
                open_line: v.open_line,
                barrier_desc: v.barrier_desc,
                close_line: v.close_line,
            })
            .collect();
        let want = golden_rows(case);
        if got == want {
            violations = violations.checked_add(want.len()).expect("count fits");
        } else {
            failures.push(format!(
                "obligation case {name}:\n    python={want:#?}\n    rust  ={got:#?}"
            ));
        }

        let got_dead: Vec<String> = unmatched_scopes(&protocols, &methods)
            .into_iter()
            .map(|p| p.name.clone())
            .collect();
        let want_dead = strings(case, "dead");
        if got_dead == want_dead {
            dead_rules = dead_rules.checked_add(want_dead.len()).expect("count fits");
        } else {
            failures.push(format!(
                "obligation case {name} dead rules:\n    python={want_dead:?}\n    \
                 rust  ={got_dead:?}"
            ));
        }
    }

    assert!(
        failures.is_empty(),
        "{} obligation divergence(s):\n{}",
        failures.len(),
        failures.join("\n")
    );
    eprintln!(
        "obligation fact parity: {} cases replayed ({violations} violations, \
         {dead_rules} dead rules)",
        cases.len()
    );
    assert!(
        cases.len() >= 45,
        "expected the full obligation corpus, got {}",
        cases.len()
    );
}

/// The walk must be a pure function of its inputs: the same documents twice
/// give the same ordered list. A `HashMap` iteration order leaking into the
/// sort would pass a single run and fail this one.
#[test]
fn the_walk_is_deterministic() {
    let root = load();
    for case in root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases'")
    {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        let protocols: Vec<Protocol> = documents(case, "protocols")
            .iter()
            .map(|p| parse_protocol(p).expect("a protocol the reference accepted"))
            .collect();
        let methods: Vec<MethodEvents> = documents(case, "methods")
            .iter()
            .map(|m| parse_method(m).expect("a method the reference accepted"))
            .collect();
        assert_eq!(
            check_protocols(&protocols, &methods),
            check_protocols(&protocols, &methods),
            "{name}: check_protocols is not deterministic"
        );
    }
}
