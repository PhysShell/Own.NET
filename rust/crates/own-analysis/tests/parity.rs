//! Ownership diagnostics parity — the Rust side of the #214 oracle at
//! **checkpoint 2**. Replays the frozen `tests/fixtures/diag_parity.json`
//! (authoritative: `python tests/test_diag_fixtures.py --write`) through the
//! ported `check` surface and asserts `(line, code)` equality, in emission order.
//!
//! Scope partition (sound, not a weakening): this checkpoint ports the generic
//! solver + the **ownership** analysis (`analyze`, d2) on top of the already-
//! parity-verified `own-cfg` resolver (d1) and the OWN020 parse-error path. It
//! does **not** yet port `check_lifetimes` (OWN014/OWN036) or `validate_policies`
//! (OWN019/OWN021/OWN023/OWN024) — those are checkpoint 3. A fixture case is
//! **covered** iff none of its Python codes belong to an unported pass; every
//! covered case is asserted to match EXACTLY (full ordered `(line, code)` list —
//! no field is weakened). Uncovered cases are listed by name and deferred.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_parity.json"
);

/// Codes emitted only by passes not yet ported at checkpoint 2 (lifetime +
/// buffer-policy), plus the resolver-name codes those passes can *also* emit
/// (OWN030/OWN031) — excluded so a case is deferred rather than half-asserted.
/// DI*/EFF*/OBL* are OwnIR-fact sidecar families (own-bridge, step 6).
fn is_unported(code: &str) -> bool {
    const UNPORTED: &[&str] = &[
        "OWN014", "OWN019", "OWN021", "OWN023", "OWN024", "OWN036", "OWN030", "OWN031",
    ];
    UNPORTED.contains(&code)
        || code.starts_with("DI")
        || code.starts_with("EFF")
        || code.starts_with("OBL")
}

/// The Rust `check` surface at checkpoint 2: parse (own-syntax) → on error a
/// synthetic OWN020 at the error line (the preserved Python quirk) → else the
/// resolver diagnostics (own-cfg, d1) followed by the ownership diagnostics
/// (own-analysis, d2), stable-sorted by `(line, code)` — exactly `_collect`
/// composed with `check_module`'s ownership-relevant passes.
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
        Ok(module) => {
            let (cfgs, d1) = own_cfg::build_module(&module);
            let mut all: Vec<(u32, String)> =
                d1.iter().map(|d| (d.line, d.code.to_owned())).collect();
            for cfg in &cfgs {
                for d in own_analysis::analyze(cfg) {
                    all.push((d.line, d.code));
                }
            }
            // Stable sort by (line, code): ties keep emission order (d1 before
            // d2; within, instruction order) — matching check_module's sort.
            all.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
            all
        }
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
fn ownership_parity_on_the_frozen_corpus() {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_parity.json parses");
    let cases = root
        .get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array");

    let mut covered = 0usize;
    let mut deferred: Vec<String> = Vec::new();
    let mut failures: Vec<String> = Vec::new();

    for case in cases {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        let source = case.get("source").and_then(Value::as_str).expect("source");
        let py = python_diags(case);

        if py.iter().any(|(_, c)| is_unported(c)) {
            deferred.push(name.to_owned());
            continue;
        }
        covered += 1;

        let got = rust_check(source);
        if got != py {
            failures.push(format!(
                "case {name}:\n    python = {py:?}\n    rust   = {got:?}"
            ));
        }
    }

    eprintln!(
        "ownership parity: {covered} covered cases asserted, {} deferred to checkpoint 3 ({:?})",
        deferred.len(),
        deferred
    );

    assert!(
        failures.is_empty(),
        "{} ownership parity divergence(s):\n{}",
        failures.len(),
        failures.join("\n")
    );
    // Guard against a silently-shrunk corpus: the .own suite must exercise most
    // of the fixture through the ownership surface.
    assert!(
        covered >= 60,
        "expected >= 60 covered cases, got {covered} (corpus shrank or partition drifted)"
    );
}
