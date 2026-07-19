//! Replays the shared Layer 2 goldens — the Rust side of
//! `tests/test_lowered_fixtures.py` (authoritative: Python regenerates the
//! goldens with `--write`; this suite must reproduce every shared one
//! byte-for-byte from the typed model).
//!
//! Contract (spec/Bridge.md §6 + the manifest ledger):
//! * every `rust_replay: true` case's golden must PARSE into the strict typed
//!   model (`deny_unknown_fields` — a Python-side surface change cannot slip
//!   past) and RE-EMIT byte-identically through the canonical emitter;
//! * a `rust_replay: false` case is a Python-only behavior snapshot pinning an
//!   open decision (#294) — it is deliberately NOT replayed, and the manifest
//!   must name the decision it waits on;
//! * the manifest's `lowered_version` must equal this crate's
//!   `LOWERED_VERSION`, and the ledger must equal the tree EXACTLY —
//!   `unique(manifest names) == facts files == golden files`. The zero-Python
//!   steady state means this suite cannot outsource ledger integrity to the
//!   Python harness: a duplicate manifest name, an unlisted facts file, or an
//!   orphaned golden is a red build here too.

#![allow(clippy::panic, clippy::expect_used)]

use own_lowered::{parse_document, to_canonical_json, Manifest, LOWERED_VERSION};
use std::collections::BTreeSet;

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/lowered"
);

fn read(name: &str) -> String {
    let path = format!("{FIXDIR}/{name}");
    std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: python tests/test_lowered_fixtures.py --write"
        )
    })
}

#[test]
fn replays_python_authored_goldens() {
    let manifest: Manifest =
        serde_json::from_str(&read("manifest.json")).expect("manifest.json parses (typed, strict)");
    assert_eq!(
        manifest.lowered_version, LOWERED_VERSION,
        "manifest lowered_version must match own-lowered::LOWERED_VERSION"
    );
    assert!(!manifest.cases.is_empty(), "manifest must not be empty");

    // Ledger/tree equality, independently of Python: the manifest names must
    // be unique and equal BOTH on-disk filename sets exactly.
    let mut listed = BTreeSet::new();
    for case in &manifest.cases {
        assert!(
            listed.insert(case.name.clone()),
            "duplicate manifest case name: {}",
            case.name
        );
        assert!(
            !case.rules.is_empty() && case.rules.iter().all(|r| !r.is_empty()),
            "{}: 'rules' must be a non-empty array of non-empty strings",
            case.name
        );
    }
    let mut facts_files = BTreeSet::new();
    let mut golden_files = BTreeSet::new();
    for entry in std::fs::read_dir(FIXDIR).expect("fixture directory is readable") {
        let file = entry.expect("directory entry").file_name();
        let file = file.to_str().expect("fixture filenames are UTF-8");
        if let Some(stem) = file.strip_suffix(".facts.json") {
            facts_files.insert(stem.to_owned());
        } else if let Some(stem) = file.strip_suffix(".golden.json") {
            golden_files.insert(stem.to_owned());
        }
    }
    assert_eq!(
        listed, facts_files,
        "manifest case names != *.facts.json on disk — the ledger and the \
         tree may not drift (unlisted facts file, or a listed case whose \
         facts are gone)"
    );
    assert_eq!(
        listed, golden_files,
        "manifest case names != *.golden.json on disk — regenerate with \
         python tests/test_lowered_fixtures.py --write or fix the ledger"
    );

    let mut replayed = 0_u32;
    let mut skipped = Vec::new();
    for case in &manifest.cases {
        let golden = read(&format!("{}.golden.json", case.name));

        if !case.rust_replay {
            assert!(
                case.decision.is_some(),
                "{}: a Python-only case must name the open decision it pins",
                case.name
            );
            skipped.push(case.name.clone());
            continue;
        }
        let surface = parse_document(&golden).unwrap_or_else(|e| {
            panic!(
                "{}: golden does not match the typed surface: {e}",
                case.name
            )
        });
        let emitted = to_canonical_json(&surface)
            .unwrap_or_else(|e| panic!("{}: canonical emit failed: {e}", case.name));
        assert!(
            emitted == golden,
            "{}: canonical re-emit is not byte-identical to the Python golden",
            case.name
        );
        replayed = replayed.checked_add(1).expect("case count fits u32");
    }
    assert!(
        replayed >= 26,
        "expected at least 26 shared cases, replayed {replayed}"
    );
    assert_eq!(
        skipped,
        vec!["tolerant_unknown_kind".to_owned()],
        "exactly the OD-2 (#294) snapshot is Python-only today; changing this \
         set is a deliberate contract decision"
    );
}
