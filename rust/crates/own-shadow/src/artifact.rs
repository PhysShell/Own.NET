//! The reproduction artifact: its frozen vocabulary, and the verification
//! that makes an artifact describe itself.
//!
//! The format is frozen in `ownlang/repro.py`'s docstring — that module is the
//! authoritative emitter, this is the replaying half. Verification is written
//! against the **parsed document**, not against a typed projection, for the
//! same reason the reference verifies the loaded dict: a typed view would
//! silently accept an artifact whose extra members it dropped, and "unknown
//! member" is one of the things this gate exists to report.

use crate::canonical::{canonical_hash, CANONICAL_ALGORITHM};
use crate::json::Json;

/// The artifact format version. Both engines are keyed to it.
pub const REPRO_VERSION: i64 = 1;

/// The reference engine: `ownlang`, which stays authoritative until #262.
///
/// `ENGINE_ORDER` is the closed vocabulary, in the order `engines` carries
/// them. `rust-own-bridge` is declared from the start — the format has a slot
/// for it — and filled by the engine protocol (a later checkpoint), so an
/// artifact carrying one engine is a capture, never a comparison.
pub const ENGINE_PYTHON: &str = "python-ownlang";
pub const ENGINE_RUST: &str = "rust-own-bridge";
pub const ENGINE_ORDER: [&str; 2] = [ENGINE_PYTHON, ENGINE_RUST];

/// The closed layer vocabulary, in pipeline order — the order a
/// first-divergence reduction walks.
pub const LAYER_ORDER: [&str; 3] = ["lowered", "summaries", "verdicts"];

pub const STATUS_PRODUCED: &str = "produced";
pub const STATUS_REFUSED: &str = "refused";

/// Verify an artifact against itself; an empty result means verified.
///
/// The gate a tampered artifact fails: the digest and the byte length are
/// **recomputed** from the embedded document, so a single changed byte in the
/// input is a refusal rather than a silently different reproduction. The
/// structural rules, in order: the format version and member set; the input
/// envelope; the recomputed canonical hash; the engine array against the
/// frozen vocabulary and order; each engine's layer array against the frozen
/// layer order; each layer envelope's status/payload agreement.
///
/// Deliberately mirrors `ownlang.repro.verify_repro` message-for-message in
/// substance — the two are independent implementations of one rule, so a
/// divergence between them is itself a finding.
#[must_use]
pub fn verify(artifact: &Json) -> Vec<String> {
    let mut problems = Vec::new();
    if !matches!(artifact, Json::Object(_)) {
        return vec![format!(
            "artifact is {}, not an object",
            artifact.type_name()
        )];
    }
    if artifact.get("repro_version").and_then(Json::as_i64) != Some(REPRO_VERSION) {
        problems.push(format!(
            "repro_version {:?} != REPRO_VERSION {REPRO_VERSION}",
            artifact.get("repro_version")
        ));
    }
    unknown_members(
        artifact,
        &["repro_version", "input", "engines"],
        "artifact",
        &mut problems,
    );

    match artifact.get("input") {
        Some(input @ Json::Object(_)) => verify_input(input, &mut problems),
        _ => problems.push("input is missing or not an object".to_owned()),
    }

    let Some(engines) = artifact.get("engines").and_then(Json::as_array) else {
        problems.push("engines is missing or not an array".to_owned());
        return problems;
    };
    if engines.is_empty() {
        problems.push("engines is empty — an artifact captures at least one engine".to_owned());
    }
    let mut seen: Vec<&str> = Vec::new();
    for (i, engine) in engines.iter().enumerate() {
        if !matches!(engine, Json::Object(_)) {
            problems.push(format!("engines[{i}] is not an object"));
            continue;
        }
        unknown_members(
            engine,
            &["id", "layers"],
            &format!("engines[{i}]"),
            &mut problems,
        );
        match engine.get("id").and_then(Json::as_str) {
            Some(id) if ENGINE_ORDER.contains(&id) => {
                if seen.contains(&id) {
                    problems.push(format!("engines[{i}]: engine {id:?} appears twice"));
                } else if let Some(previous) = seen.last() {
                    if rank(id) < rank(previous) {
                        problems.push(format!(
                            "engines[{i}]: engine {id:?} is out of the frozen order {ENGINE_ORDER:?}"
                        ));
                    }
                }
                seen.push(id);
            }
            other => problems.push(format!(
                "engines[{i}]: id {other:?} is not in the frozen engine vocabulary {ENGINE_ORDER:?}"
            )),
        }
        verify_layers(
            engine.get("layers"),
            &format!("engines[{i}]"),
            &mut problems,
        );
    }
    problems
}

fn rank(id: &str) -> usize {
    ENGINE_ORDER
        .iter()
        .position(|e| *e == id)
        .unwrap_or(usize::MAX)
}

fn unknown_members(value: &Json, allowed: &[&str], where_: &str, problems: &mut Vec<String>) {
    let mut extra: Vec<&str> = value
        .keys()
        .into_iter()
        .filter(|k| !allowed.contains(k))
        .collect();
    if !extra.is_empty() {
        extra.sort_unstable();
        problems.push(format!("{where_}: unknown member(s): {extra:?}"));
    }
}

fn verify_input(input: &Json, problems: &mut Vec<String>) {
    unknown_members(
        input,
        &["ownir_version", "canonical", "document"],
        "input",
        problems,
    );
    let Some(document) = input.get("document") else {
        problems.push("input.document is missing".to_owned());
        return;
    };
    let Some(claimed) = input.get("canonical") else {
        problems.push("input.canonical is missing or not an object".to_owned());
        return;
    };
    if !matches!(claimed, Json::Object(_)) {
        problems.push("input.canonical is missing or not an object".to_owned());
        return;
    }
    let actual = canonical_hash(document);
    let algorithm = claimed.get("algorithm").and_then(Json::as_str);
    let digest = claimed.get("digest").and_then(Json::as_str);
    let bytes = claimed.get("bytes").and_then(Json::as_i64);
    let matches = algorithm == Some(CANONICAL_ALGORITHM)
        && digest == Some(actual.digest.as_str())
        && bytes == i64::try_from(actual.bytes).ok();
    if !matches {
        problems.push(format!(
            "input.canonical does not describe input.document: claimed \
             {{algorithm: {algorithm:?}, digest: {digest:?}, bytes: {bytes:?}}}, recomputed \
             {{algorithm: {:?}, digest: {:?}, bytes: {}}}",
            actual.algorithm, actual.digest, actual.bytes
        ));
    }
}

fn verify_layers(layers: Option<&Json>, where_: &str, problems: &mut Vec<String>) {
    let Some(layers) = layers.and_then(Json::as_array) else {
        problems.push(format!("{where_}.layers is missing or not an array"));
        return;
    };
    let names: Vec<Option<&str>> = layers
        .iter()
        .map(|l| l.get("layer").and_then(Json::as_str))
        .collect();
    let expected: Vec<Option<&str>> = LAYER_ORDER.iter().copied().map(Some).collect();
    if names != expected {
        problems.push(format!(
            "{where_}.layers carries {names:?} — every engine reports exactly the frozen \
             layers {LAYER_ORDER:?}, in that order"
        ));
    }
    for (i, layer) in layers.iter().enumerate() {
        let at = format!("{where_}.layers[{i}]");
        if !matches!(layer, Json::Object(_)) {
            problems.push(format!("{at} is not an object"));
            continue;
        }
        unknown_members(
            layer,
            &["layer", "surface_version", "status", "document", "error"],
            &at,
            problems,
        );
        if !layer.has("surface_version") {
            problems.push(format!(
                "{at}: surface_version is missing (null when the surface has none)"
            ));
        }
        match layer.get("status").and_then(Json::as_str) {
            Some(s) if s == STATUS_PRODUCED => {
                if !layer.has("document") {
                    problems.push(format!("{at}: status 'produced' without a document"));
                }
                if layer.has("error") {
                    problems.push(format!("{at}: status 'produced' carries an error"));
                }
            }
            Some(s) if s == STATUS_REFUSED => {
                if !layer
                    .get("error")
                    .and_then(Json::as_str)
                    .is_some_and(|e| !e.is_empty())
                {
                    problems.push(format!(
                        "{at}: status 'refused' needs a non-empty error text"
                    ));
                }
                if layer.has("document") {
                    problems.push(format!("{at}: status 'refused' carries a document"));
                }
            }
            other => problems.push(format!(
                "{at}: status {other:?} is neither {STATUS_PRODUCED:?} nor {STATUS_REFUSED:?}"
            )),
        }
    }
}

/// Render an artifact the way the reference writes it: document order,
/// 2-space indent, non-ASCII preserved, trailing newline.
#[must_use]
pub fn render(artifact: &Json) -> String {
    let mut out = artifact.to_pretty();
    out.push('\n');
    out
}
