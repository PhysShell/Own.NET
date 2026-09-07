//! The reproduction artifact: its frozen vocabulary, and the verification
//! that makes an artifact describe itself.
//!
//! The format is frozen in `ownlang/repro.py`'s docstring — that module is the
//! authoritative emitter, this is the replaying half. Verification is written
//! against the **parsed document**, not against a typed projection, for the
//! same reason the reference verifies the loaded dict: a typed view would
//! silently accept an artifact whose extra members it dropped, and "unknown
//! member" is one of the things this gate exists to report.

use std::collections::BTreeSet;

use crate::base64;
use crate::canonical::{canonical_hash, hash_bytes, CanonicalHash, CANONICAL_ALGORITHM};
use crate::json::Json;

/// The artifact format version. Both engines are keyed to it.
///
/// 2 added the layer envelope's `projection` (checkpoint 2, the engine
/// protocol); **3 added the raw input and the per-engine consumption
/// attestation** (owner decision B-2) and the derived SARIF surface (D-6).
pub const REPRO_VERSION: i64 = 3;

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

/// The projection vocabulary (the engine protocol, checkpoint 2): a layer
/// declares whether its engine emitted the whole frozen surface, or names the
/// members it did emit and why the rest are absent.
pub const PROJECTION_FULL: &str = "full";
pub const PROJECTION_PARTIAL: &str = "partial";

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

    let raw_identity = if let Some(input @ Json::Object(_)) = artifact.get("input") {
        verify_input(input, &mut problems)
    } else {
        problems.push("input is missing or not an object".to_owned());
        None
    };

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
            &["id", "consumed", "layers"],
            &format!("engines[{i}]"),
            &mut problems,
        );
        verify_consumed(
            engine,
            &format!("engines[{i}]"),
            raw_identity.as_ref(),
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

/// Verify the input envelope; returns `input.raw`'s recomputed identity, or
/// `None` when the raw chain broke before one could be established — no engine
/// is then judged against a claim that is itself unverified.
fn verify_input(input: &Json, problems: &mut Vec<String>) -> Option<CanonicalHash> {
    unknown_members(
        input,
        &["ownir_version", "raw", "canonical", "document"],
        "input",
        problems,
    );
    match input.get("document") {
        None => problems.push("input.document is missing".to_owned()),
        Some(document) => match input.get("canonical") {
            Some(claimed @ Json::Object(_)) => {
                let actual = canonical_hash(document);
                if !identity_matches(claimed, &actual) {
                    problems.push(format!(
                        "input.canonical does not describe input.document: claimed \
                         {{algorithm: {:?}, digest: {:?}, bytes: {:?}}}, recomputed \
                         {{algorithm: {:?}, digest: {:?}, bytes: {}}}",
                        claimed.get("algorithm").and_then(Json::as_str),
                        claimed.get("digest").and_then(Json::as_str),
                        claimed.get("bytes").and_then(Json::as_i64),
                        actual.algorithm,
                        actual.digest,
                        actual.bytes
                    ));
                }
            }
            _ => problems.push("input.canonical is missing or not an object".to_owned()),
        },
    }
    verify_raw(input, problems)
}

/// One identity block (`{algorithm, digest, bytes}`) against a recomputed one.
fn identity_matches(claimed: &Json, actual: &CanonicalHash) -> bool {
    claimed.get("algorithm").and_then(Json::as_str) == Some(actual.algorithm)
        && claimed.get("digest").and_then(Json::as_str) == Some(actual.digest.as_str())
        && claimed.get("bytes").and_then(Json::as_i64) == i64::try_from(actual.bytes).ok()
}

/// The raw-input chain (owner decision B-2), link by link.
///
/// Each link is a **separate named problem**, and that is the design rather
/// than verbosity: "the artifact does not verify" is not actionable, and the
/// links fail for different reasons — a mis-copied digest, a truncated blob, a
/// re-serialized document, a document swapped under a kept digest. One message
/// covering all of them would let a mutation move the failure between links
/// with the suite still red for the same string, and a control could not say
/// which rule it protects.
///
/// Deliberately an independent reading of the reference's
/// `ownlang.repro._verify_raw`, like the rest of this module: a divergence
/// between the two verifiers is itself a finding.
fn verify_raw(input: &Json, problems: &mut Vec<String>) -> Option<CanonicalHash> {
    let Some(raw @ Json::Object(_)) = input.get("raw") else {
        problems.push(
            "input.raw is missing or not an object — a v3 artifact carries the byte-exact \
             input it was taken over"
                .to_owned(),
        );
        return None;
    };
    unknown_members(
        raw,
        &["algorithm", "digest", "bytes", "base64"],
        "input.raw",
        problems,
    );
    let algorithm = raw.get("algorithm").and_then(Json::as_str);
    if algorithm != Some(CANONICAL_ALGORITHM) {
        problems.push(format!(
            "input.raw.algorithm {algorithm:?} is not {CANONICAL_ALGORITHM:?}"
        ));
    }
    let Some(encoded) = raw.get("base64").and_then(Json::as_str) else {
        problems.push("input.raw.base64 is missing or not a string".to_owned());
        return None;
    };
    let decoded = match base64::decode(encoded) {
        Ok(bytes) => bytes,
        Err(e) => {
            problems.push(e);
            return None;
        }
    };
    let actual = hash_bytes(&decoded);
    if raw.get("bytes").and_then(Json::as_i64) != i64::try_from(decoded.len()).ok() {
        problems.push(format!(
            "input.raw.bytes {:?} does not describe input.raw.base64, which decodes to {} byte(s)",
            raw.get("bytes").and_then(Json::as_i64),
            decoded.len()
        ));
    }
    if raw.get("digest").and_then(Json::as_str) != Some(actual.digest.as_str()) {
        problems.push(format!(
            "input.raw.digest does not describe input.raw.base64: claimed {:?}, recomputed {:?}",
            raw.get("digest").and_then(Json::as_str),
            actual.digest
        ));
    }
    // `from_slice`, never `from_str`: the bytes are the subject, and routing
    // them through a `str` on the way to the parser would be a decode this
    // chain is supposed to be measuring.
    let reparsed = match serde_json::from_slice::<Json>(&decoded) {
        Ok(value) => value,
        Err(e) => {
            problems.push(format!("input.raw does not parse: {e}"));
            return Some(actual);
        }
    };
    let reparsed_identity = canonical_hash(&reparsed);
    match input.get("canonical") {
        Some(claimed) if identity_matches(claimed, &reparsed_identity) => {}
        claimed => problems.push(format!(
            "input.raw does not reproduce input.canonical: parsing the raw bytes yields \
             {{digest: {:?}, bytes: {}}}, the artifact claims {:?}",
            reparsed_identity.digest,
            reparsed_identity.bytes,
            claimed.map(|c| (
                c.get("digest").and_then(Json::as_str),
                c.get("bytes").and_then(Json::as_i64)
            ))
        )),
    }
    Some(actual)
}

/// Every engine attests the bytes it consumed, and they are the artifact's.
///
/// An entry without `consumed` is refused rather than defaulted (owner decision
/// B-3): defaulting is exactly how a version-2 capture would be promoted into a
/// version-3 artifact carrying a claim no execution ever made.
fn verify_consumed(
    engine: &Json,
    at: &str,
    raw_identity: Option<&CanonicalHash>,
    problems: &mut Vec<String>,
) {
    let Some(consumed @ Json::Object(_)) = engine.get("consumed") else {
        problems.push(format!(
            "{at}: consumed is missing or not an object — every v3 engine entry attests the \
             bytes it read, and an entry that does not is a capture from an older format \
             rather than a run"
        ));
        return;
    };
    unknown_members(
        consumed,
        &["algorithm", "digest", "bytes"],
        &format!("{at}.consumed"),
        problems,
    );
    // The raw chain already failed; judging against it would say nothing.
    let Some(identity) = raw_identity else { return };
    if !identity_matches(consumed, identity) {
        problems.push(format!(
            "{at}: consumed {{digest: {:?}, bytes: {:?}}} is not input.raw's identity \
             {{digest: {:?}, bytes: {}}} — this engine did not read the bytes the artifact \
             carries, so the two captures are not of one input",
            consumed.get("digest").and_then(Json::as_str),
            consumed.get("bytes").and_then(Json::as_i64),
            identity.digest,
            identity.bytes
        ));
    }
}

/// The engine protocol's one rule: a layer says what its engine could produce,
/// and a **partial** projection must NAME the members it carries and say why
/// the rest are absent. An unexplained partial is how a comparison would
/// quietly score an unported member as agreement.
fn verify_projection(projection: Option<&Json>, at: &str, problems: &mut Vec<String>) {
    let Some(projection) = projection else {
        problems.push(format!(
            "{at}: projection is missing or not an object — every layer declares what its \
             engine could produce"
        ));
        return;
    };
    if !matches!(projection, Json::Object(_)) {
        problems.push(format!(
            "{at}: projection is missing or not an object — every layer declares what its \
             engine could produce"
        ));
        return;
    }
    unknown_members(
        projection,
        &["kind", "members", "reason"],
        &format!("{at}.projection"),
        problems,
    );
    match projection.get("kind").and_then(Json::as_str) {
        Some(kind) if kind == PROJECTION_FULL => {
            for name in ["members", "reason"] {
                if projection.has(name) {
                    problems.push(format!(
                        "{at}.projection: a 'full' projection carries no {name:?} — it emits \
                         the whole surface"
                    ));
                }
            }
        }
        Some(kind) if kind == PROJECTION_PARTIAL => {
            match projection.get("members").and_then(Json::as_array) {
                Some(members)
                    if !members.is_empty()
                        && members
                            .iter()
                            .all(|m| m.as_str().is_some_and(|s| !s.is_empty())) =>
                {
                    let names: Vec<&str> = members.iter().filter_map(Json::as_str).collect();
                    let unique: BTreeSet<&str> = names.iter().copied().collect();
                    if unique.len() != names.len() {
                        problems.push(format!("{at}.projection: duplicate member names"));
                    }
                }
                _ => problems.push(format!(
                    "{at}.projection: a 'partial' projection must NAME the members it carries"
                )),
            }
            if !projection
                .get("reason")
                .and_then(Json::as_str)
                .is_some_and(|r| !r.is_empty())
            {
                problems.push(format!(
                    "{at}.projection: a 'partial' projection must say WHY the remaining \
                     members are absent"
                ));
            }
        }
        other => problems.push(format!(
            "{at}.projection: kind {other:?} is not one of \
             [{PROJECTION_FULL:?}, {PROJECTION_PARTIAL:?}]"
        )),
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
            &[
                "layer",
                "surface_version",
                "projection",
                "status",
                "document",
                "error",
            ],
            &at,
            problems,
        );
        if !layer.has("surface_version") {
            problems.push(format!(
                "{at}: surface_version is missing (null when the surface has none)"
            ));
        }
        verify_projection(layer.get("projection"), &at, problems);
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
