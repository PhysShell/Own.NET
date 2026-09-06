//! The checkpoint-5 acceptance contract (#259): for every case of the Layer 3
//! verdict fixture family,
//!
//! ```text
//! facts.json → OwnIr (typed constructor, the tolerant entry) → own_bridge::check_facts
//!            ≡  <case>.verdicts.json  on EVERY `Finding` member
//! ```
//!
//! The golden is the reference's COMPLETE `Finding` list (`ownlang/verdicts.py`,
//! regenerate: `python tests/test_verdict_fixtures.py --write`) and this replay
//! now compares all of it: cp4's identity, anchor, kind and tiering, plus the
//! synthesized `message` (BR-V4) and the ordered `related` / `flow` evidence
//! triples (BR-V5). **Not one golden was regenerated to get here** — they have
//! carried these three members since cp4, which is the whole reason the family
//! was built that way.
//!
//! Refusals compare on the reference's error text **in full** — including the
//! `message=` member of the map-or-raise class (BR-V3), which interpolates the
//! core diagnostic's own message. cp4 had to cut the comparison there because
//! this core carried each code's title; cp5.2 gave `own_cfg::Diag` the
//! reference's message and removed the cut. No comparison boundary is left on
//! a refusal.
//!
//! That also makes the unported remainder of the core message layer a
//! tripwire rather than a blind spot: a code whose message `own-cfg` does not
//! carry still renders as its title, so the first golden that refuses on one
//! goes red here demanding the message, instead of agreeing with a title.
//!
//! Independently enforced here (not outsourced to Python):
//! * ledger/tree equality — the swept corpora + the synthetic manifest cases
//!   == the goldens on disk, with unique names across all sources;
//! * the exclusion ledger is EXECUTABLE: every `rust_replay_excluded` case is
//!   run and must be refused exactly as declared (at the typed door, or by
//!   `check_facts` with the declared error text) — an exclusion that stops
//!   holding is a red build demanding promotion, never a silent coverage hole;
//! * the exclusion set is pinned by name — a new declared boundary is a
//!   deliberate contract decision, not a drive-by;
//! * every replayed case is deterministic (same facts, same list, twice).

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use own_bridge::{Finding, Step};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/verdicts"
);
const CORPORA: [(&str, &str); 3] = [
    (
        "ownir",
        concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures/ownir"),
    ),
    (
        "lowered",
        concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../tests/fixtures/lowered"
        ),
    ),
    (
        "summaries",
        concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../tests/fixtures/summaries"
        ),
    ),
];

/// The verdict-family ledger (strict: an unknown field is a contract change
/// this suite must be taught, not skip).
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    #[allow(dead_code)]
    comment: String,
    verdicts_version: u32,
    rust_replay_excluded: Vec<Exclusion>,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Exclusion {
    name: String,
    reason: String,
    rust_refusal: Refusal,
    #[serde(default)]
    rust_error_contains: Option<String>,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "lowercase")]
enum Refusal {
    /// The typed `OwnIr` constructor refuses the document (#294 OD-1).
    Door,
    /// `check_facts` returns an error (a declared bridge boundary).
    Bridge,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    rules: Vec<String>,
}

/// One golden: the reference's complete finding list, or its refusal text.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Golden {
    verdicts_version: u32,
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    findings: Option<Vec<GoldenFinding>>,
}

/// Every `ownir.Finding` member, strictly — a member added on the Python side
/// goes red here until this replay is taught it (and decides whether to
/// compare it). The evidence arrives as a fixed `(file, line, label)` TUPLE,
/// so a golden triple of the wrong arity fails to parse rather than comparing
/// as some shorter shape.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GoldenFinding {
    file: String,
    line: i64,
    code: String,
    component: String,
    event: String,
    handler: String,
    message: String,
    kind: String,
    advisory: bool,
    severity: Option<String>,
    related: Vec<Step>,
    flow: Vec<Step>,
    ignore_reason: Option<String>,
    column: Option<i64>,
}

/// The checkpoint-5 comparison key: every member, in the reference's
/// declaration order. A named struct rather than a tuple — fourteen members is
/// past what the standard library derives for tuples, and a mislabelled field
/// in a divergence report is worse than a long type.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Key {
    file: String,
    line: i64,
    column: Option<i64>,
    code: String,
    component: String,
    event: String,
    handler: String,
    message: String,
    kind: String,
    advisory: bool,
    severity: Option<String>,
    related: Vec<Step>,
    flow: Vec<Step>,
    ignore_reason: Option<String>,
}

fn key_of_golden(f: &GoldenFinding) -> Key {
    Key {
        file: f.file.clone(),
        line: f.line,
        column: f.column,
        code: f.code.clone(),
        component: f.component.clone(),
        event: f.event.clone(),
        handler: f.handler.clone(),
        message: f.message.clone(),
        kind: f.kind.clone(),
        advisory: f.advisory,
        severity: f.severity.clone(),
        related: f.related.clone(),
        flow: f.flow.clone(),
        ignore_reason: f.ignore_reason.clone(),
    }
}

fn key_of_rust(f: &Finding) -> Key {
    Key {
        file: f.file.clone(),
        line: f.line,
        column: f.column,
        code: f.code.clone(),
        component: f.component.clone(),
        event: f.event.clone(),
        handler: f.handler.clone(),
        message: f.message.clone(),
        kind: f.kind.clone(),
        advisory: f.advisory,
        severity: f.severity.clone(),
        related: f.related.clone(),
        flow: f.flow.clone(),
        ignore_reason: f.ignore_reason.clone(),
    }
}

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: python tests/test_verdict_fixtures.py --write"
        )
    })
}

fn stems(dir: &str, suffix: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for entry in std::fs::read_dir(dir).expect("fixture directory is readable") {
        let file = entry.expect("directory entry").file_name();
        let file = file.to_str().expect("fixture filenames are UTF-8");
        if let Some(stem) = file.strip_suffix(suffix) {
            out.insert(stem.to_owned());
        }
    }
    out
}

/// The full plan: case name → facts path (the swept corpora + the synthetic
/// cases), with unique names enforced across every source.
fn plan(manifest: &Manifest) -> BTreeMap<String, String> {
    let mut plan: BTreeMap<String, String> = BTreeMap::new();
    let mut origin: BTreeMap<String, &str> = BTreeMap::new();
    for (label, dir) in CORPORA {
        for name in stems(dir, ".facts.json") {
            assert!(
                !plan.contains_key(&name),
                "case name '{name}' exists in BOTH the {} and {label} corpora",
                origin.get(&name).copied().unwrap_or("?")
            );
            plan.insert(name.clone(), format!("{dir}/{name}.facts.json"));
            origin.insert(name, label);
        }
    }
    let mut synthetic = BTreeSet::new();
    for c in &manifest.cases {
        assert!(
            !c.rules.is_empty(),
            "case '{}' must name the BR rules it pins",
            c.name
        );
        assert!(
            synthetic.insert(c.name.clone()),
            "duplicate manifest case name: {}",
            c.name
        );
        assert!(
            !plan.contains_key(&c.name),
            "synthetic case '{}' shadows a swept corpus case name",
            c.name
        );
    }
    assert_eq!(
        synthetic,
        stems(FIXDIR, ".facts.json"),
        "manifest case names != *.facts.json under fixtures/verdicts"
    );
    for name in synthetic {
        plan.insert(name.clone(), format!("{FIXDIR}/{name}.facts.json"));
    }
    plan
}

/// The tolerant entry: the typed constructor, WITHOUT the strict door
/// (`OwnIr::from_json`) — the same choice `tests/replay.rs` makes, for the
/// same reason: `check_facts` is the tolerant door in the reference, and the
/// map-or-raise and unknown-kind cases must reach the bridge to be measured.
fn construct(facts_text: &str) -> Result<own_ir::OwnIr, serde_json::Error> {
    serde_json::from_str(facts_text)
}

/// The exclusion ledger: pinned by name, and EXECUTABLE — every entry is run
/// and must be refused exactly as declared. Returns the excluded entries.
fn assert_exclusions_hold<'m>(
    manifest: &'m Manifest,
    plan: &BTreeMap<String, String>,
) -> BTreeMap<String, &'m Exclusion> {
    let mut excluded: BTreeMap<String, &Exclusion> = BTreeMap::new();
    for e in &manifest.rust_replay_excluded {
        assert!(
            !e.reason.is_empty(),
            "exclusion '{}' must carry its reason",
            e.name
        );
        assert!(
            plan.contains_key(&e.name),
            "rust_replay_excluded names '{}', which is not a planned case",
            e.name
        );
        assert!(
            excluded.insert(e.name.clone(), e).is_none(),
            "rust_replay_excluded lists '{}' twice",
            e.name
        );
    }
    let expected_exclusions: BTreeSet<&str> = [
        "protocol_isloaded_clean",
        "protocol_isloaded_violation",
        "verdict_boundary_line_negative",
        "verdict_boundary_line_above_u32",
        "verdict_boundary_service_line_negative",
        "verdict_boundary_effect_line_negative",
        "verdict_door_effect_deps_not_strings",
        "verdict_door_service_unknown_lifetime",
    ]
    .into_iter()
    .collect();
    assert_eq!(
        excluded.keys().map(String::as_str).collect::<BTreeSet<_>>(),
        expected_exclusions,
        "the exclusion ledger changed — a new declared boundary (or a promotion) is a \
         deliberate contract decision recorded in the checkpoint note, not a drive-by"
    );
    for (name, e) in &excluded {
        let facts_text = read(plan.get(name).expect("an exclusion names a planned case"));
        match e.rust_refusal {
            Refusal::Door => {
                assert!(
                    construct(&facts_text).is_err(),
                    "{name}: declared a typed-door refusal, but the constructor now ACCEPTS \
                     the document — the exclusion has rotted; promote the case (remove it \
                     from rust_replay_excluded)"
                );
            }
            Refusal::Bridge => {
                let facts = construct(&facts_text).unwrap_or_else(|err| {
                    panic!("{name}: a bridge-refused case must construct: {err}")
                });
                let err = own_bridge::check_facts(&facts).err().unwrap_or_else(|| {
                    panic!(
                        "{name}: declared a bridge refusal, but check_facts now SUCCEEDS — the \
                         exclusion has rotted; promote the case"
                    )
                });
                if let Some(needle) = &e.rust_error_contains {
                    assert!(
                        err.to_string().contains(needle),
                        "{name}: refused, but not for the declared reason: expected {needle:?} \
                         in {err}"
                    );
                }
            }
        }
    }
    excluded
}

/// Replay one case against its golden: `Ok((refused, finding count))`, or the
/// divergence description.
fn replay_case(name: &str, facts_path: &str) -> Result<(bool, usize), String> {
    let golden: Golden = serde_json::from_str(&read(&format!("{FIXDIR}/{name}.verdicts.json")))
        .unwrap_or_else(|e| panic!("{name}: golden does not parse (typed, strict): {e}"));
    assert_eq!(golden.verdicts_version, 1, "{name}: golden surface version");
    let facts = construct(&read(facts_path)).unwrap_or_else(|e| {
        panic!("{name}: the typed door refused a case that is not in the exclusion ledger: {e}")
    });
    let first = own_bridge::check_facts(&facts);
    let second = own_bridge::check_facts(&facts);
    assert_eq!(
        first
            .as_ref()
            .map(|v| v.iter().map(key_of_rust).collect::<Vec<_>>()),
        second
            .as_ref()
            .map(|v| v.iter().map(key_of_rust).collect::<Vec<_>>()),
        "{name}: check_facts is not deterministic"
    );
    match (first, golden.error, golden.findings) {
        (Err(err), Some(text), _) => {
            // Byte-exact on both sides, with no normalization (cp5.2).
            let (got, want) = (err.to_string(), text);
            if got == want {
                Ok((true, 0))
            } else {
                Err(format!(
                    "{name}: refusal text differs\n    python = {want}\n    rust   = {got}"
                ))
            }
        }
        (Ok(list), None, Some(want)) => {
            let got: Vec<Key> = list.iter().map(key_of_rust).collect();
            let want: Vec<Key> = want.iter().map(key_of_golden).collect();
            if got == want {
                Ok((false, want.len()))
            } else {
                Err(format!(
                    "{name}: verdict list differs\n    python = {want:#?}\n    rust   = {got:#?}"
                ))
            }
        }
        (Ok(list), Some(text), _) => Err(format!(
            "{name}: the reference REFUSES ({text}) but Rust returned {} finding(s)",
            list.len()
        )),
        (Err(err), None, _) => Err(format!(
            "{name}: the reference returns findings but Rust REFUSED: {err}"
        )),
        (Ok(_), None, None) => panic!("{name}: a golden must carry findings or an error"),
    }
}

#[test]
fn replays_every_case_to_its_golden() {
    let manifest: Manifest = serde_json::from_str(&read(&format!("{FIXDIR}/manifest.json")))
        .expect("manifest.json parses (typed, strict)");
    assert_eq!(
        manifest.verdicts_version, 1,
        "manifest verdicts_version must match this replay's surface version"
    );
    let plan = plan(&manifest);
    let planned: BTreeSet<String> = plan.keys().cloned().collect();
    assert_eq!(
        planned,
        stems(FIXDIR, ".verdicts.json"),
        "planned cases != *.verdicts.json goldens on disk (missing or orphaned golden)"
    );
    let excluded = assert_exclusions_hold(&manifest, &plan);

    let mut replayed = 0_u32;
    let mut refusals = 0_u32;
    let mut findings = 0_usize;
    let mut failures: Vec<String> = Vec::new();
    for (name, facts_path) in &plan {
        if excluded.contains_key(name) {
            continue;
        }
        match replay_case(name, facts_path) {
            Ok((true, _)) => refusals = refusals.checked_add(1).expect("count fits u32"),
            Ok((false, n)) => findings = findings.checked_add(n).expect("count fits usize"),
            Err(divergence) => failures.push(divergence),
        }
        replayed = replayed.checked_add(1).expect("count fits u32");
    }
    assert!(
        failures.is_empty(),
        "{} verdict divergence(s):\n{}",
        failures.len(),
        failures.join("\n")
    );
    eprintln!(
        "cp5 verdict surface (every Finding member): {replayed} cases replayed \
         ({refusals} refusals, {findings} findings), \
         {} declared exclusions held",
        excluded.len()
    );
    assert!(
        replayed >= 66,
        "expected at least 66 replayed cases, got {replayed}"
    );
    assert!(
        refusals >= 5,
        "the refusal classes (vocabulary skew, unknown kind, map-or-raise) must stay pinned, \
         got {refusals}"
    );
}
