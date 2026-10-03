//! The H0 heap-effect parity harness: for every case of the heap-effect
//! fixture family,
//!
//! ```text
//! <case>.sidecar.json → own_bridge::dump_heap_effects
//!                     == <case>.summaries.json   (byte-exact)
//!                     or the text of <case>.rejected.txt
//! ```
//!
//! The goldens are the EXACT stdout bytes of `python -m ownlang.heap_effects`
//! and the exact rejection messages (`tests/test_heap_effects_fixtures.py
//! --write` regenerates them). The ledger is re-derived here, independently
//! of Python: every sidecar is a listed case or rejection, every case has a
//! golden, every rejection has its text — none missing, none orphaned.

#![allow(clippy::panic, clippy::expect_used)]

use serde::Deserialize;
use std::collections::BTreeSet;

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/heap_effects"
);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    heap_effects_version: i64,
    cases: Vec<Case>,
    rejections: Vec<Rejection>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    #[allow(dead_code)]
    #[serde(default)]
    source: Option<String>,
    pins: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Rejection {
    name: String,
}

fn read(name: &str) -> String {
    let path = format!("{FIXDIR}/{name}");
    std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: python tests/test_heap_effects_fixtures.py --write"
        )
    })
}

fn stems(suffix: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for entry in std::fs::read_dir(FIXDIR).expect("fixture directory is readable") {
        let file = entry.expect("directory entry").file_name();
        let file = file.to_str().expect("fixture filenames are UTF-8");
        if let Some(stem) = file.strip_suffix(suffix) {
            out.insert(stem.to_owned());
        }
    }
    out
}

/// The same sidecar with `methods[]` reversed (the solve must not care).
fn reversed(text: &str) -> Option<String> {
    let mut doc: serde_json::Value = serde_json::from_str(text).ok()?;
    doc.get_mut("methods")?.as_array_mut()?.reverse();
    Some(doc.to_string())
}

#[test]
fn replays_every_case_and_rejection() {
    let manifest: Manifest =
        serde_json::from_str(&read("manifest.json")).expect("manifest.json parses (typed, strict)");
    assert_eq!(manifest.heap_effects_version, 1, "manifest version");

    let cases: BTreeSet<String> = manifest.cases.iter().map(|c| c.name.clone()).collect();
    let rejections: BTreeSet<String> = manifest.rejections.iter().map(|r| r.name.clone()).collect();
    assert_eq!(cases.len(), manifest.cases.len(), "a case is listed twice");
    assert_eq!(
        rejections.len(),
        manifest.rejections.len(),
        "a rejection is listed twice"
    );
    assert!(
        cases.is_disjoint(&rejections),
        "a name is both a case and a rejection"
    );
    for c in &manifest.cases {
        assert!(
            !c.pins.is_empty(),
            "case '{}' must say what it pins",
            c.name
        );
    }
    let all: BTreeSet<String> = cases.union(&rejections).cloned().collect();
    assert_eq!(all, stems(".sidecar.json"), "manifest != sidecars on disk");
    assert_eq!(
        cases,
        stems(".summaries.json"),
        "cases != summaries goldens"
    );
    assert_eq!(
        rejections,
        stems(".rejected.txt"),
        "rejections != rejection texts"
    );

    for case in &cases {
        let text = read(&format!("{case}.sidecar.json"));
        let golden = read(&format!("{case}.summaries.json"));
        let emitted = own_bridge::dump_heap_effects(&text)
            .unwrap_or_else(|e| panic!("{case}: rejected: {e}"));
        assert!(
            emitted == golden,
            "{case}: Rust dump is not byte-identical to the Python golden.\n\
             --- emitted ---\n{emitted}\n--- golden ---\n{golden}"
        );
        assert_eq!(
            own_bridge::dump_heap_effects(&text).ok().as_deref(),
            Some(emitted.as_str()),
            "{case}: dump is not deterministic"
        );
        if let Some(flipped) = reversed(&text) {
            assert_eq!(
                own_bridge::dump_heap_effects(&flipped).ok().as_deref(),
                Some(emitted.as_str()),
                "{case}: dump depends on the order of methods[]"
            );
        }
    }
    for case in &rejections {
        let text = read(&format!("{case}.sidecar.json"));
        let want = read(&format!("{case}.rejected.txt"));
        match own_bridge::dump_heap_effects(&text) {
            Ok(_) => panic!("{case}: accepted, but it is a rejection case"),
            Err(e) => assert_eq!(
                format!("{e}\n"),
                want,
                "{case}: rejection text differs from the reference"
            ),
        }
    }
    assert!(
        cases.len() >= 10,
        "expected at least 10 cases, got {}",
        cases.len()
    );
    assert!(
        rejections.len() >= 16,
        "expected at least 16 rejections, got {}",
        rejections.len()
    );
}
