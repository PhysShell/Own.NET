//! The checkpoint-5.3 acceptance contract (#259): for every case of the
//! rendered-surface fixture family,
//!
//! ```text
//! facts.json → OwnIr → own_bridge::check_facts → render_finding / build_sarif
//!            ≡  <case>.renders.json   BYTE FOR BYTE
//! ```
//!
//! The golden is what the reference's own renderers returned
//! (`ownlang/renders.py`, regenerate: `python
//! tests/test_verdict_render_fixtures.py --write`). This replay reconstructs
//! the whole document — every format at both host severities, the SARIF log at
//! both — serializes it with the same conventions the emitter fixes (2-space
//! indent, non-ASCII preserved, a trailing newline) and compares the BYTES.
//! Not a value comparison: SARIF key order is part of the surface here, and a
//! value comparison would score a reordered log as agreement.
//!
//! Independently enforced, not outsourced to Python:
//! * the ledger is the tree — every manifest case has facts and a golden, and
//!   every facts/golden file on disk is a manifest case;
//! * every case pins at least one BR-V9 ledger row, and the rows the manifest
//!   claims are the rows the inventory reads;
//! * no rendered surface carries a diagnostic `subject` (the checkpoint-4
//!   subject tail, re-checked over the bytes on this side too);
//! * every case is deterministic.

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use own_bridge::{build_sarif, check_facts, render_finding, Finding, SarifLog};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/verdict_renders"
);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    #[allow(dead_code)]
    comment: String,
    renders_version: u32,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    rules: Vec<String>,
    pins: Vec<String>,
}

/// One surface at both host severities. A struct rather than a map because the
/// emitter's KEY ORDER is part of the golden and `serde_json`'s map type sorts.
#[derive(Serialize)]
struct PerSeverity<T> {
    error: T,
    warning: T,
}

/// The whole rendered document, in the emitter's key order
/// (`ownlang/renders.py`). `skip_serializing_if` reproduces the two shapes it
/// emits: a refusal carries `error` and nothing else; a success carries the
/// four rendered formats and the SARIF pair.
#[derive(Serialize)]
struct RenderedDocument {
    renders_version: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    human: Option<PerSeverity<Vec<String>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    github: Option<PerSeverity<Vec<String>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    msbuild: Option<PerSeverity<Vec<String>>>,
    #[serde(rename = "unknown-format", skip_serializing_if = "Option::is_none")]
    unknown_format: Option<PerSeverity<Vec<String>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    sarif: Option<PerSeverity<SarifLog>>,
}

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: \
             python tests/test_verdict_render_fixtures.py --write"
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

/// The emitter's serialization: `json.dumps(indent=2, ensure_ascii=False)` plus
/// a trailing newline. `serde_json`'s pretty printer uses the same two-space
/// indent and leaves non-ASCII unescaped, so the two agree on the bytes.
fn serialize(doc: &RenderedDocument) -> String {
    let mut out = serde_json::to_string_pretty(doc).expect("the projection serializes");
    out.push('\n');
    out
}

fn lines_of(findings: &[Finding], fmt: &str) -> PerSeverity<Vec<String>> {
    let render = |severity: &str| {
        findings
            .iter()
            .map(|f| render_finding(f, fmt, severity))
            .collect()
    };
    PerSeverity {
        error: render("error"),
        warning: render("warning"),
    }
}

/// Rebuild one case's whole rendered document.
fn project(facts_text: &str) -> RenderedDocument {
    let empty = RenderedDocument {
        renders_version: 1,
        error: None,
        human: None,
        github: None,
        msbuild: None,
        unknown_format: None,
        sarif: None,
    };
    let facts: own_ir::OwnIr = serde_json::from_str(facts_text)
        .unwrap_or_else(|door| panic!("the typed door refused a rendered-surface case: {door}"));
    match check_facts(&facts) {
        Err(refusal) => RenderedDocument {
            error: Some(refusal.to_string()),
            ..empty
        },
        Ok(findings) => RenderedDocument {
            human: Some(lines_of(&findings, "human")),
            github: Some(lines_of(&findings, "github")),
            msbuild: Some(lines_of(&findings, "msbuild")),
            unknown_format: Some(lines_of(&findings, "unknown-format")),
            sarif: Some(PerSeverity {
                error: build_sarif(&findings, "error"),
                warning: build_sarif(&findings, "warning"),
            }),
            ..empty
        },
    }
}

#[test]
fn replays_every_rendered_surface_byte_for_byte() {
    let manifest: Manifest = serde_json::from_str(&read(&format!("{FIXDIR}/manifest.json")))
        .expect("manifest.json parses (typed, strict)");
    assert_eq!(
        manifest.renders_version, 1,
        "manifest renders_version must match this replay's surface version"
    );

    let mut planned: BTreeSet<String> = BTreeSet::new();
    let mut pinned: BTreeSet<String> = BTreeSet::new();
    for case in &manifest.cases {
        assert!(
            !case.rules.is_empty(),
            "case '{}' must name the BR rules it pins",
            case.name
        );
        assert!(
            !case.pins.is_empty(),
            "case '{}' pins no BR-V9 ledger row — a rendered golden nobody can read a \
             claim off is not evidence",
            case.name
        );
        assert!(
            planned.insert(case.name.clone()),
            "duplicate manifest case name: {}",
            case.name
        );
        pinned.extend(case.pins.iter().cloned());
    }
    assert_eq!(
        planned,
        stems(".facts.json"),
        "manifest case names != *.facts.json under fixtures/verdict_renders"
    );
    assert_eq!(
        planned,
        stems(".renders.json"),
        "planned cases != *.renders.json goldens on disk (missing or orphaned golden)"
    );

    let mut divergences: Vec<String> = Vec::new();
    for name in &planned {
        let facts_text = read(&format!("{FIXDIR}/{name}.facts.json"));
        let ours = serialize(&project(&facts_text));
        assert_eq!(
            ours,
            serialize(&project(&facts_text)),
            "{name}: the rendered projection is not deterministic"
        );
        for marker in ["\"subject\"", "'subject'"] {
            assert!(
                !ours.contains(marker),
                "{name}: a rendered surface carries {marker} — the bridge's Finding has no \
                 diagnostic subject and no output may invent one"
            );
        }
        let golden = read(&format!("{FIXDIR}/{name}.renders.json"));
        if ours != golden {
            let first = golden
                .lines()
                .zip(ours.lines())
                .enumerate()
                .find(|(_, (a, b))| a != b);
            let where_ = first.map_or_else(
                || "the end — one document is longer".to_owned(),
                |(i, (python, rust))| {
                    format!(
                        "line {}\n    python = {python:?}\n    rust   = {rust:?}",
                        i + 1
                    )
                },
            );
            divergences.push(format!("{name}: rendered bytes differ, first at {where_}"));
        }
    }
    assert!(
        divergences.is_empty(),
        "{} rendered-surface divergence(s):\n{}",
        divergences.len(),
        divergences.join("\n")
    );
    eprintln!(
        "cp5.3 rendered surfaces: {} cases replayed byte-for-byte, {} BR-V9 rows pinned",
        planned.len(),
        pinned.len()
    );
}
