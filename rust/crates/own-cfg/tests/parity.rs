//! Replays the shared CFG parity fixtures — the Rust side of
//! `tests/test_cfg_fixtures.py` (authoritative: it regenerates
//! `tests/fixtures/cfg_parity.json` from the real Python lowering over the whole
//! corpus and fails when the file is stale).
//!
//! For every case: a rejected source must produce the **byte-identical** parser
//! error string (riding on `own-syntax`'s error parity); an accepted source must
//! lower to the **byte-identical** canonical CFG JSON and the identical
//! `(line, code)` resolver diagnostics.

#![allow(clippy::panic, clippy::expect_used)]

use own_syntax::parse;
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/cfg_parity.json"
);

fn expected_diags(case: &Value) -> Vec<(u64, String)> {
    case.get("diags")
        .and_then(Value::as_array)
        .expect("accepted case carries a 'diags' array")
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
            (line, code.to_owned())
        })
        .collect()
}

#[test]
fn replays_python_authored_fixtures() {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture file missing — regenerate: python tests/test_cfg_fixtures.py --write");
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
                    "parser error text diverged from Python on case '{name}'"
                );
            }
            (Some(expected), Ok(_)) => {
                panic!("case '{name}': Rust accepted a source Python rejects with: {expected}");
            }
            (None, Ok(module)) => {
                let expected_cfg = case
                    .get("cfg")
                    .and_then(Value::as_str)
                    .expect("accepted case carries a 'cfg' string");
                let (cfgs, diags) = own_cfg::build_module(&module);

                let got_cfg = own_cfg::canonical_json(&cfgs);
                assert_eq!(
                    got_cfg, expected_cfg,
                    "canonical CFG JSON diverged from Python on case '{name}'"
                );

                let got_diags: Vec<(u64, String)> = diags
                    .iter()
                    .map(|d| (u64::from(d.line), d.code.to_owned()))
                    .collect();
                assert_eq!(
                    got_diags,
                    expected_diags(case),
                    "resolver diagnostics diverged from Python on case '{name}'"
                );
            }
            (None, Err(e)) => {
                panic!("case '{name}': Rust rejected a source Python accepts: {e}");
            }
        }
    }
}
