//! Full diagnostics parity — the Rust side of the #214 oracle at **checkpoint
//! 3**. Replays the frozen `tests/fixtures/diag_parity.json` (authoritative:
//! `python tests/test_diag_fixtures.py --write`) through the complete ported
//! `check` surface (`own_analysis::check_module`: buffer policy + lifetime +
//! resolver + ownership) and asserts `(line, code)` equality, in emission order,
//! for **every** case — no partition, no deferral (the `.own` corpus contains no
//! OwnIR-fact-only families; DI*/EFF*/OBL* land with `own-bridge`, step 6).

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_parity.json"
);

/// OwnIR-fact sidecar families (own-bridge, step 6) that no `.own` input can
/// exercise. If one ever appears in the corpus, flag it loudly rather than
/// silently pass — it needs the fact surface, not this seam.
fn is_fact_only(code: &str) -> bool {
    code.starts_with("DI") || code.starts_with("EFF") || code.starts_with("OBL")
}

/// The full Rust `check` surface: parse (own-syntax) → on error a synthetic
/// OWN020 at the error line (the preserved Python quirk) → else the complete
/// `check_module` composition, already sorted by `(line, code)`.
fn rust_check(source: &str) -> Vec<(u32, String)> {
    match own_syntax::parse(source) {
        Err(e) => {
            // `_collect` wraps a lex/parse failure as one OWN020 at the error line.
            let line = match e {
                own_syntax::SyntaxError::Lex(le) => le.line,
                own_syntax::SyntaxError::Parse(pe) => pe.line,
            };
            vec![(line, "OWN020".to_owned())]
        }
        Ok(module) => own_analysis::check_module(&module)
            .into_iter()
            .map(|d| (d.line, d.code))
            .collect(),
    }
}

fn python_diags(case: &Value) -> Vec<(u32, String)> {
    case.get("diags")
        .and_then(Value::as_array)
        .expect("case 'diags' array")
        .iter()
        .map(|pair| {
            let pair = pair.as_array().expect("[line, code]");
            let line = u32::try_from(pair.first().and_then(Value::as_u64).expect("line"))
                .expect("line fits u32");
            let code = pair
                .get(1)
                .and_then(Value::as_str)
                .expect("code")
                .to_owned();
            (line, code)
        })
        .collect()
}

#[test]
fn full_parity_on_the_frozen_corpus() {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_parity.json parses");
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array");

    let mut asserted = 0usize;
    let mut fact_only: Vec<String> = Vec::new();
    let mut failures: Vec<String> = Vec::new();

    for case in cases {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        let source = case.get("source").and_then(Value::as_str).expect("source");
        let py = python_diags(case);

        // The whole `.own` surface is ported now; only OwnIR-fact families would
        // be out of scope, and the corpus has none — record any as a loud signal.
        if py.iter().any(|(_, c)| is_fact_only(c)) {
            fact_only.push(name.to_owned());
            continue;
        }
        asserted += 1;

        let got = rust_check(source);
        if got != py {
            failures.push(format!(
                "case {name}:\n    python = {py:?}\n    rust   = {got:?}"
            ));
        }
    }

    eprintln!(
        "full parity: {asserted} cases asserted, {} fact-only skipped",
        fact_only.len()
    );
    assert!(
        fact_only.is_empty(),
        "the .own corpus grew a fact-only case (needs own-bridge): {fact_only:?}"
    );
    assert!(
        failures.is_empty(),
        "{} full-parity divergence(s):\n{}",
        failures.len(),
        failures.join("\n")
    );
    // Guard against a silently-shrunk corpus.
    assert!(asserted >= 65, "expected the full corpus, got {asserted}");
}
