//! The MOS parity harness (P-022, roadmap stage 1): for every case of the
//! summaries fixture family,
//!
//! ```text
//! facts.json → own_ir::OwnIr::from_json → own_bridge::dump_summaries
//!            ==  <case>.summaries.json (byte-exact)
//! ```
//!
//! The goldens are the EXACT stdout bytes of `python -m ownlang summaries`
//! (`tests/test_summaries_fixtures.py --write` regenerates them), so this
//! suite diffs the Rust inference port against the reference at the SUMMARY
//! level — finer than diffing final diagnostics, where an inference bug can
//! hide behind an unrelated silence (spec/Inference.md §8, INF-R1/R2).
//!
//! Two case sources, independently re-derived here (not outsourced to
//! Python): the frozen Layer 2 facts corpus (`tests/fixtures/lowered/`,
//! swept automatically minus the manifest's audited `excluded_lowered`
//! ledger) and the synthetic MOS cases beside the manifest. Ledger/tree
//! equality is enforced in every direction — a golden cannot be missing,
//! stale, orphaned, or silently skipped; an exclusion must name a real
//! lowered case. `tolerant_unknown_kind` is the ONLY exclusion today:
//! Python's `load()` door rejects its unknown resource kind before the dump
//! runs (exit 2 — no document to pin), while the Rust twin of that rejection
//! lives in `lower()` and is pinned by the lowered family's `Rejected`
//! golden (#294 OD-2 door placement).

#![allow(clippy::panic, clippy::expect_used)]

use serde::Deserialize;
use std::collections::BTreeSet;

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/summaries"
);
const LOWDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/lowered"
);

/// The summaries-family ledger (strict: an unknown field is a contract
/// change this suite must be taught, not skip).
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    ownir_version: i64,
    excluded_lowered: Vec<Exclusion>,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Exclusion {
    name: String,
    reason: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    rules: Vec<String>,
}

fn read(dir: &str, name: &str) -> String {
    let path = format!("{dir}/{name}");
    std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: python tests/test_summaries_fixtures.py --write"
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

/// facts text → the summaries document bytes, through the Rust pipeline only.
fn dump_bytes(facts_text: &str, case: &str) -> String {
    let facts = own_ir::OwnIr::from_json(facts_text)
        .unwrap_or_else(|e| panic!("{case}: own-ir rejected the shared facts: {e}"));
    own_bridge::dump_summaries(&facts)
        .unwrap_or_else(|e| panic!("{case}: dump_summaries failed: {e}"))
}

#[test]
fn dumps_every_case_to_its_golden() {
    let manifest: Manifest = serde_json::from_str(&read(FIXDIR, "manifest.json"))
        .expect("manifest.json parses (typed, strict)");
    assert_eq!(
        manifest.ownir_version,
        own_ir::OWNIR_VERSION,
        "manifest ownir_version must match OWNIR_VERSION"
    );

    // --- ledger/tree equality, independently of Python -----------------------
    let lowered_facts = stems(LOWDIR, ".facts.json");
    let mut excluded = BTreeSet::new();
    for e in &manifest.excluded_lowered {
        assert!(
            !e.reason.is_empty(),
            "exclusion '{}' must carry its audit reason",
            e.name
        );
        assert!(
            lowered_facts.contains(&e.name),
            "excluded_lowered names '{}', which has no facts file in the \
             lowered corpus",
            e.name
        );
        assert!(
            excluded.insert(e.name.clone()),
            "excluded_lowered lists '{}' twice",
            e.name
        );
    }
    assert_eq!(
        excluded,
        BTreeSet::from(["tolerant_unknown_kind".to_owned()]),
        "the exclusion ledger changed — a new Python-only door divergence is \
         a deliberate contract decision, not a drive-by"
    );

    let mut synthetic = BTreeSet::new();
    for c in &manifest.cases {
        assert!(
            !c.rules.is_empty(),
            "case '{}' must name the INF rules it pins",
            c.name
        );
        assert!(
            synthetic.insert(c.name.clone()),
            "duplicate manifest case name: {}",
            c.name
        );
        assert!(
            !lowered_facts.contains(&c.name),
            "synthetic case '{}' shadows a lowered corpus case name",
            c.name
        );
    }
    assert_eq!(
        synthetic,
        stems(FIXDIR, ".facts.json"),
        "manifest case names != *.facts.json under fixtures/summaries"
    );

    let mut planned: BTreeSet<String> = lowered_facts.difference(&excluded).cloned().collect();
    planned.extend(synthetic.iter().cloned());
    assert_eq!(
        planned,
        stems(FIXDIR, ".summaries.json"),
        "planned cases != *.summaries.json goldens on disk (missing or \
         orphaned golden)"
    );

    // --- the byte-exact replay ----------------------------------------------
    let mut dumped = 0_u32;
    let mut degraded = 0_u32;
    for case in &planned {
        let dir = if synthetic.contains(case) {
            FIXDIR
        } else {
            LOWDIR
        };
        let facts_text = read(dir, &format!("{case}.facts.json"));
        let golden = read(FIXDIR, &format!("{case}.summaries.json"));
        let emitted = dump_bytes(&facts_text, case);
        assert!(
            emitted == golden,
            "{case}: Rust dump is not byte-identical to the Python golden.\n\
             --- emitted ---\n{emitted}\n--- golden ---\n{golden}",
        );
        // determinism: the same facts must dump byte-identically on re-run.
        assert_eq!(
            dump_bytes(&facts_text, case),
            emitted,
            "{case}: dump is not deterministic"
        );
        if emitted.contains("\"degraded\": \"") {
            degraded = degraded.checked_add(1).expect("count fits u32");
        }
        dumped = dumped.checked_add(1).expect("case count fits u32");
    }
    assert!(
        dumped >= 35,
        "expected at least 35 summaries cases dumped from facts, got {dumped}"
    );
    assert!(
        degraded >= 1,
        "the degraded branch (INF-F6) must stay pinned by at least one case"
    );
}
