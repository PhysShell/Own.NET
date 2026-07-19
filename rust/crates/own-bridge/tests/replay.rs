//! The slice-3 acceptance contract (#259): for every `rust_replay: true`
//! manifest case,
//!
//! ```text
//! facts.json → own_ir::OwnIr::from_json → own_bridge::lower
//!            → own_lowered::to_canonical_json  ==  golden.json (byte-exact)
//! ```
//!
//! The golden is EXPECTED OUTPUT only — it is never parsed as an input to
//! construction (contrast `own-lowered/tests/replay.rs`, which round-trips the
//! golden through the typed model; here the document is BUILT from facts).
//!
//! Independently enforced here (not outsourced to Python or to own-lowered):
//! * `manifest.lowered_version == LOWERED_VERSION == 1`;
//! * exact ledger/tree equality — `unique(manifest names) == *.facts.json ==
//!   *.golden.json`;
//! * `tolerant_unknown_kind` stays the ONLY `rust_replay: false` case (#294 —
//!   this crate takes no side on the tolerant door);
//! * every shared case's facts actually pass through the Rust lowering (a
//!   lowering rejection must BE the golden — the `Rejected` form — never a
//!   skip);
//! * lowering the same facts twice is byte-deterministic.

#![allow(clippy::panic, clippy::expect_used)]

use own_lowered::{to_canonical_json, Manifest, Rejected, Surface, LOWERED_VERSION};
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

/// facts text → the canonical Layer 2 bytes, through the Rust pipeline only.
fn lower_bytes(facts_text: &str, case: &str) -> String {
    let facts = own_ir::OwnIr::from_json(facts_text)
        .unwrap_or_else(|e| panic!("{case}: own-ir rejected the shared facts: {e}"));
    let surface = match own_bridge::lower(&facts) {
        Ok(doc) => Surface::Lowered(doc),
        Err(e) => Surface::Rejected(Rejected {
            lowered_version: LOWERED_VERSION,
            error: e.to_string(),
        }),
    };
    to_canonical_json(&surface).unwrap_or_else(|e| panic!("{case}: canonical emit failed: {e}"))
}

#[test]
fn lowers_every_shared_facts_to_its_golden() {
    let manifest: Manifest =
        serde_json::from_str(&read("manifest.json")).expect("manifest.json parses (typed, strict)");
    assert_eq!(
        manifest.lowered_version, LOWERED_VERSION,
        "manifest lowered_version must match LOWERED_VERSION"
    );

    // Ledger/tree equality, independently of Python and of own-lowered.
    let mut listed = BTreeSet::new();
    for case in &manifest.cases {
        assert!(
            listed.insert(case.name.clone()),
            "duplicate manifest case name: {}",
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
        "manifest names != *.facts.json on disk"
    );
    assert_eq!(
        listed, golden_files,
        "manifest names != *.golden.json on disk"
    );

    let mut lowered = 0_u32;
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
        let facts_text = read(&format!("{}.facts.json", case.name));
        let emitted = lower_bytes(&facts_text, &case.name);
        assert!(
            emitted == golden,
            "{}: Rust lowering is not byte-identical to the Python golden.\n\
             --- emitted ---\n{emitted}\n--- golden ---\n{golden}",
            case.name
        );
        // determinism: the same facts must lower byte-identically on re-run.
        assert_eq!(
            lower_bytes(&facts_text, &case.name),
            emitted,
            "{}: lowering is not deterministic",
            case.name
        );
        lowered = lowered.checked_add(1).expect("case count fits u32");
    }
    assert!(
        lowered >= 26,
        "expected at least 26 shared cases lowered from facts, got {lowered}"
    );
    assert_eq!(
        skipped,
        vec!["tolerant_unknown_kind".to_owned()],
        "exactly the OD-2 (#294) snapshot is Python-only; changing this set is \
         a deliberate contract decision"
    );
}
