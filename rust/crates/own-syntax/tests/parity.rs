//! Replays the shared syntax parity fixtures — the Rust side of
//! `tests/test_syntax_fixtures.py` (which is authoritative: it regenerates
//! `tests/fixtures/syntax_parity.json` by running the real Python parser and
//! fails when the file is stale).
//!
//! For every case: a rejected source must produce the **byte-identical**
//! error string; an accepted source must produce the same structural digest
//! (the digest function here mirrors the Python `_digest` line for line).

#![allow(clippy::panic, clippy::expect_used)]

use own_syntax::ast::{Module, Stmt};
use own_syntax::parse;
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/syntax_parity.json"
);

fn stmt_count(stmts: &[Stmt]) -> usize {
    let mut n = 0usize;
    for s in stmts {
        n = n.saturating_add(1);
        match s {
            Stmt::BorrowBlock(b) => n = n.saturating_add(stmt_count(&b.body)),
            Stmt::If(i) => {
                n = n
                    .saturating_add(stmt_count(&i.then_body))
                    .saturating_add(stmt_count(&i.else_body));
            }
            Stmt::While(w) => n = n.saturating_add(stmt_count(&w.body)),
            _ => {}
        }
    }
    n
}

fn collect_conds(stmts: &[Stmt], out: &mut Vec<String>) {
    for s in stmts {
        match s {
            Stmt::BorrowBlock(b) => collect_conds(&b.body, out),
            Stmt::If(i) => {
                out.push(i.cond_text.clone());
                collect_conds(&i.then_body, out);
                collect_conds(&i.else_body, out);
            }
            Stmt::While(w) => {
                out.push(w.cond_text.clone());
                collect_conds(&w.body, out);
            }
            _ => {}
        }
    }
}

fn digest(m: &Module) -> String {
    let fns: Vec<String> = m
        .functions
        .iter()
        .map(|f| format!("{}/{}/{}", f.name, f.params.len(), stmt_count(&f.body)))
        .collect();
    let mut conds: Vec<String> = Vec::new();
    for f in &m.functions {
        collect_conds(&f.body, &mut conds);
    }
    format!(
        "m={} r={} e={} f={} p={} l={} fns=[{}] conds=[{}]",
        m.name,
        m.resources.len(),
        m.externs.len(),
        m.functions.len(),
        m.policies.len(),
        m.lifetimes.len(),
        fns.join(","),
        conds.join("|")
    )
}

#[test]
fn replays_python_authored_fixtures() {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture file missing — regenerate: python tests/test_syntax_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("fixture JSON parses");
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array");
    assert!(!cases.is_empty(), "fixture corpus must not be empty");

    for case in cases {
        let name = case
            .get("name")
            .and_then(Value::as_str)
            .expect("case 'name'");
        let source = case
            .get("source")
            .and_then(Value::as_str)
            .expect("case 'source'");
        let expected_error = case.get("error").and_then(Value::as_str);
        match (expected_error, parse(source)) {
            (Some(expected), Err(e)) => {
                assert_eq!(
                    e.to_string(),
                    expected,
                    "error text diverged from Python on case '{name}'"
                );
            }
            (Some(expected), Ok(_)) => {
                panic!("case '{name}': Rust accepted a source Python rejects with: {expected}");
            }
            (None, Ok(module)) => {
                let expected = case
                    .get("digest")
                    .and_then(Value::as_str)
                    .expect("accepted case carries a 'digest'");
                assert_eq!(
                    digest(&module),
                    expected,
                    "AST digest diverged from Python on case '{name}'"
                );
            }
            (None, Err(e)) => {
                panic!("case '{name}': Rust rejected a source Python accepts: {e}");
            }
        }
    }
}
