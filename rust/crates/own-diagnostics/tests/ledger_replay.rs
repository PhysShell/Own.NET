//! Zero-Python replay of the complete diagnostic-family ledger
//! (`tests/fixtures/diag_ledger.json`, authoritative via
//! `python tests/test_diag_ledger_fixtures.py --write`) — P-022 step 5a, #255,
//! PR 3 of 3.
//!
//! PR 1 pinned identity and PR 2 pinned rendering, both on curated shapes. This
//! makes the coverage total and self-policing: **every** code in
//! [`own_diagnostics::TITLES`] must have a case, so a family cannot be added
//! without a fixture.
//!
//! The three failure modes, each with its own test so a red build names the
//! actual problem:
//!
//! * **missing** — a `TITLES` code with no ledger case;
//! * **orphan** — a ledger case naming a code absent from `TITLES`;
//! * **divergence** — the rendered text disagrees with the reference.
//!
//! What this does NOT claim: that the analyzer emits a given code. That is step
//! 4's contract, pinned over the real `.own` corpus by `diag_parity.json`. The
//! ledger carries `analyzer_corpus` per code so the two claims stay separable —
//! rendering coverage is 47/47, analyzer-corpus coverage is not, and conflating
//! them would overstate the evidence.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::collections::BTreeSet;

use own_diagnostics::{title, Diagnostic, TITLES};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/diag_ledger.json"
);

const SCHEMA_VERSION: u64 = 1;

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_diag_ledger_fixtures.py --write");
    let root: Value = serde_json::from_str(&raw).expect("diag_ledger.json parses");
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

fn code_of(case: &Value) -> &str {
    case.get("code")
        .and_then(Value::as_str)
        .expect("case 'code'")
}

#[test]
fn every_title_code_has_a_ledger_case() {
    let root = load();
    let covered: BTreeSet<&str> = cases(&root).iter().map(code_of).collect();
    let missing: Vec<&str> = TITLES
        .iter()
        .map(|(code, _)| *code)
        .filter(|code| !covered.contains(code))
        .collect();
    assert!(
        missing.is_empty(),
        "{} diagnostic code(s) have no ledger case: {missing:?}. A new family must \
         ship with a fixture — regenerate: python tests/test_diag_ledger_fixtures.py --write",
        missing.len()
    );
}

#[test]
fn no_ledger_case_names_an_unknown_code() {
    let root = load();
    let orphans: Vec<&str> = cases(&root)
        .iter()
        .map(code_of)
        .filter(|code| title(code).is_none())
        .collect();
    assert!(
        orphans.is_empty(),
        "{} ledger case(s) name a code absent from TITLES: {orphans:?}. A removed or \
         renamed code must not leave its fixture behind",
        orphans.len()
    );
}

#[test]
fn ledger_case_count_matches_the_vocabulary() {
    let root = load();
    let declared = root
        .get("totals")
        .and_then(|t| t.get("codes"))
        .and_then(Value::as_u64)
        .expect("'totals.codes'");
    assert_eq!(
        usize::try_from(declared).expect("fits usize"),
        cases(&root).len(),
        "the ledger's own total disagrees with the number of cases it carries"
    );
    assert_eq!(
        cases(&root).len(),
        TITLES.len(),
        "the ledger and TITLES disagree on the size of the vocabulary"
    );
}

#[test]
fn every_case_title_matches_the_ported_vocabulary() {
    let root = load();
    for case in cases(&root) {
        let code = code_of(case);
        let expected = case
            .get("title")
            .and_then(Value::as_str)
            .expect("case 'title'");
        assert_eq!(
            title(code),
            Some(expected),
            "code {code:?}: the ported TITLES entry diverged from the reference"
        );
    }
}

/// The migration packet's counters, computed rather than asserted by hand.
///
/// `Unexplained` is the one that must be zero; the others are reported so a
/// reviewer sees the shape of any difference instead of a bare boolean.
#[derive(Default, Debug)]
struct Counters {
    python_only: usize,
    rust_only: usize,
    changed: usize,
    unexplained: usize,
}

#[test]
fn rendered_text_matches_the_reference_for_every_family() {
    let root = load();
    let mut counters = Counters::default();
    let mut first_divergence: Option<String> = None;

    let covered: BTreeSet<&str> = cases(&root).iter().map(code_of).collect();
    counters.python_only = TITLES
        .iter()
        .filter(|(code, _)| !covered.contains(code))
        .count();
    counters.rust_only = cases(&root)
        .iter()
        .map(code_of)
        .filter(|code| title(code).is_none())
        .count();

    for case in cases(&root) {
        let code = code_of(case);
        let path = case
            .get("path")
            .and_then(Value::as_str)
            .expect("case 'path'");
        let diagnostic: Diagnostic =
            serde_json::from_value(case.get("diagnostic").expect("'diagnostic'").clone())
                .unwrap_or_else(|e| panic!("code {code:?}: diagnostic does not load: {e}"));
        let expected = case
            .get("rendered")
            .and_then(Value::as_str)
            .expect("case 'rendered'");
        let produced = diagnostic.render(path);
        if produced != expected {
            counters.changed = counters.changed.saturating_add(1);
            counters.unexplained = counters.unexplained.saturating_add(1);
            if first_divergence.is_none() {
                first_divergence = Some(format!(
                    "code {code:?}\n  expected: {expected:?}\n  produced: {produced:?}"
                ));
            }
        }
    }

    assert_eq!(
        counters.unexplained,
        0,
        "the migration packet requires Unexplained == 0. Counters: {counters:?}\n\
         first divergence:\n{}",
        first_divergence.as_deref().unwrap_or("<none>")
    );
    assert_eq!(counters.python_only, 0, "counters: {counters:?}");
    assert_eq!(counters.rust_only, 0, "counters: {counters:?}");
    assert_eq!(counters.changed, 0, "counters: {counters:?}");
}

#[test]
fn analyzer_corpus_coverage_is_recorded_not_assumed() {
    // Rendering coverage is total; analyzer-corpus coverage is not, and the
    // ledger must keep saying so. If this ever reaches 47 it means the `.own`
    // corpus genuinely grew — a real event worth a deliberate fixture update,
    // not something to discover silently.
    let root = load();
    let declared = root
        .get("totals")
        .and_then(|t| t.get("analyzer_corpus"))
        .and_then(Value::as_u64)
        .expect("'totals.analyzer_corpus'");
    let counted = cases(&root)
        .iter()
        .filter(|c| {
            c.get("analyzer_corpus")
                .and_then(Value::as_bool)
                .unwrap_or(false)
        })
        .count();
    assert_eq!(
        usize::try_from(declared).expect("fits usize"),
        counted,
        "the ledger's analyzer_corpus total disagrees with its own per-code flags"
    );
    assert!(
        counted < cases(&root).len(),
        "every code now claims analyzer-corpus coverage — verify that against \
         diag_parity.json before believing it"
    );
}
