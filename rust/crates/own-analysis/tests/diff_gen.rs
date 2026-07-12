//! Generated differential battery — the Rust side of the seeded mini-program
//! oracle (#214). Replays `tests/fixtures/diag_diff_gen.json` (authoritative:
//! `python tests/test_diff_gen_fixtures.py --write`) through the ported `check`
//! surface with **zero Python**. On any divergence it prints the failing seed +
//! source so the case can be lifted into a permanent regression fixture.
//!
//! Same sound covered/deferred partition as `parity.rs`: a case is asserted only
//! when none of its Python codes come from a not-yet-ported pass (the generator
//! is tuned to emit only ownership faults, so in practice every case is covered).

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_diff_gen.json"
);

fn is_fact_only(code: &str) -> bool {
    code.starts_with("DI") || code.starts_with("EFF") || code.starts_with("OBL")
}

/// The full Rust `check` surface (parse → `check_module`; parse error → OWN020).
fn rust_check(source: &str) -> Vec<(u32, String)> {
    match own_syntax::parse(source) {
        Err(e) => {
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

fn golden(case: &Value) -> Vec<(u32, String)> {
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
fn generated_ownership_programs_match_python() {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diff_gen_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_diff_gen.json parses");
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array");
    assert!(cases.len() >= 100, "generated corpus must be substantial");

    let mut covered = 0usize;
    let mut deferred = 0usize;
    let mut failures: Vec<String> = Vec::new();

    for case in cases {
        let seed = case.get("seed").and_then(Value::as_u64).expect("seed");
        let source = case.get("source").and_then(Value::as_str).expect("source");
        let py = golden(case);

        if py.iter().any(|(_, c)| is_fact_only(c)) {
            deferred += 1;
            continue;
        }
        covered += 1;

        let got = rust_check(source);
        if got != py {
            // Print the seed + source so this becomes a permanent regression.
            failures.push(format!(
                "SEED {seed} diverged:\n--- source ---\n{source}--- python {py:?}\n--- rust   {got:?}"
            ));
        }
    }

    eprintln!("generated differential: {covered} covered asserted, {deferred} deferred");
    assert!(
        failures.is_empty(),
        "{} generated-program divergence(s):\n{}",
        failures.len(),
        failures.join("\n\n")
    );
    assert!(
        covered >= 100,
        "expected >= 100 covered generated cases, got {covered}"
    );
}
