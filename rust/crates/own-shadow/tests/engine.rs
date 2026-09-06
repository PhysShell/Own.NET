//! The engine protocol's acceptance contract (P-022 step 7a, checkpoint 2):
//!
//! ```text
//! facts.json → own_shadow::capture   ≡  the committed artifact's
//!                                       `rust-own-bridge` engine entry
//! ```
//!
//! **An engine writes only its own entry.** The reference authors
//! `python-ownlang` (`python tests/test_repro_fixtures.py --write`) and carries
//! any foreign entry through untouched; this side authors `rust-own-bridge`
//! (`OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test engine`) and touches
//! nothing else. That is what lets the two halves be produced independently,
//! each with zero of the other's runtime — and it is why neither half can
//! quietly become a comparison of one implementation against itself.
//!
//! **This is still not a comparison.** An artifact carrying two captures
//! compares nothing: no test here reads one engine's layer and asserts
//! anything about the other's. Comparing them is #260's acceptance, blocked on
//! #259 (cp5 and 4b), and the reduction that would consume the pairing is a
//! later checkpoint in this same slice.
//!
//! What this suite does assert, beyond "the entry is what it was":
//! * the capture is **deterministic** — the same input twice, byte-identical;
//! * every capture **verifies inside a whole artifact**, so a malformed
//!   envelope is caught by the same gate the reference's half goes through;
//! * a layer whose projection is `partial` carries **exactly** the members its
//!   documents actually have — a projection that over-claims is the failure
//!   this field exists to prevent, and it would otherwise be prose;
//! * the two engines' captures are **structurally comparable**: same layers,
//!   in the same order. Structure only — no value is compared.

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use std::collections::{BTreeMap, BTreeSet};

use own_shadow::{capture, parse, render, verify, Json, ENGINE_PYTHON, ENGINE_RUST, LAYER_ORDER};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures");

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| panic!("cannot read {path}: {e}"))
}

/// The artifact ledger, and where each named case's facts document lives.
fn artifacts() -> BTreeMap<String, String> {
    let manifest =
        parse(&read(&format!("{FIXTURES}/repro/manifest.json"))).expect("repro manifest parses");
    let mut out = BTreeMap::new();
    for entry in manifest
        .get("artifacts")
        .and_then(Json::as_array)
        .expect("manifest carries an 'artifacts' ledger")
    {
        let name = entry.get("name").and_then(Json::as_str).expect("name");
        let corpus = entry
            .get("corpus")
            .and_then(Json::as_str)
            .expect("an artifact entry names the corpus its facts live in");
        out.insert(
            name.to_owned(),
            format!("{FIXTURES}/{corpus}/{name}.facts.json"),
        );
    }
    out
}

fn engine_entry<'a>(artifact: &'a Json, id: &str) -> Option<&'a Json> {
    artifact
        .get("engines")
        .and_then(Json::as_array)?
        .iter()
        .find(|e| e.get("id").and_then(Json::as_str) == Some(id))
}

/// Replace (or append) this engine's entry, keeping the frozen engine order
/// and every other entry untouched.
fn with_our_entry(artifact: &Json, ours: &Json) -> Json {
    let Json::Object(entries) = artifact else {
        panic!("artifact is not an object")
    };
    let rebuilt = entries
        .iter()
        .map(|(k, v)| {
            if k != "engines" {
                return (k.clone(), v.clone());
            }
            let mut engines: Vec<Json> = v
                .as_array()
                .expect("engines array")
                .iter()
                .filter(|e| e.get("id").and_then(Json::as_str) != Some(ENGINE_RUST))
                .cloned()
                .collect();
            engines.push(ours.clone());
            engines.sort_by_key(|e| {
                e.get("id")
                    .and_then(Json::as_str)
                    .and_then(|id| own_shadow::ENGINE_ORDER.iter().position(|o| *o == id))
                    .unwrap_or(usize::MAX)
            });
            (k.clone(), Json::Array(engines))
        })
        .collect();
    Json::Object(rebuilt)
}

/// `OWN_SHADOW_WRITE=1` regenerates this engine's entry in every committed
/// artifact. Deliberately opt-in: a suite that rewrites its own expectations
/// on every run proves nothing, and "implementation disagreed with the golden
/// → regenerate → agreement" is the move this whole family exists to make
/// impossible.
fn writing() -> bool {
    std::env::var("OWN_SHADOW_WRITE").is_ok_and(|v| v == "1")
}

/// Cargo runs a target's tests in parallel, so under `OWN_SHADOW_WRITE` the
/// reading tests would race the writer over half-written artifacts. They stand
/// down for that run: a regeneration pass proves nothing, and a flaky red from
/// a self-inflicted race is worse than no signal.
fn stand_down_while_writing() -> bool {
    if writing() {
        eprintln!("OWN_SHADOW_WRITE=1: regeneration pass, this check stands down");
        return true;
    }
    false
}

#[test]
fn this_engine_reproduces_its_committed_capture() {
    let mut divergences: Vec<String> = Vec::new();
    for (name, facts_path) in artifacts() {
        let artifact_path = format!("{FIXTURES}/repro/{name}.repro.json");
        let artifact = parse(&read(&artifact_path)).expect("artifact parses");
        let facts_text = read(&facts_path);

        let ours = capture(&facts_text)
            .unwrap_or_else(|e| panic!("{name}: this engine cannot capture the document: {e}"));
        // Determinism: the same input, twice.
        assert_eq!(
            ours,
            capture(&facts_text).expect("second capture"),
            "{name}: the capture is not deterministic"
        );

        let rebuilt = with_our_entry(&artifact, &ours);
        if writing() {
            std::fs::write(&artifact_path, render(&rebuilt)).expect("write artifact");
            continue;
        }
        match engine_entry(&artifact, ENGINE_RUST) {
            None => divergences.push(format!(
                "{name}: the committed artifact carries no '{ENGINE_RUST}' entry — regenerate: \
                 OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test engine"
            )),
            Some(committed) if committed != &ours => divergences.push(format!(
                "{name}: this engine's capture differs from the committed one\n\
                 committed = {committed:#?}\n     now = {ours:#?}"
            )),
            Some(_) => {}
        }
        // The whole artifact, both engines in it, goes through the same gate
        // the reference's half goes through.
        assert_eq!(
            verify(&rebuilt),
            Vec::<String>::new(),
            "{name}: an artifact carrying this engine's capture does not verify"
        );
    }
    assert!(
        divergences.is_empty(),
        "{} artifact(s) disagree with this engine's capture:\n{}",
        divergences.len(),
        divergences.join("\n")
    );
}

/// The complete Layer 3 record — `ownir.Finding`'s members in declaration
/// order. The authority is the reference (`ownlang/verdicts.py`) and the place
/// it is enforced against it is `own-bridge/tests/verdicts.rs`, whose golden
/// parses with `deny_unknown_fields`; this list exists so a `full` claim here
/// means the same thing that replay means by it.
const VERDICT_SURFACE_MEMBERS: [&str; 14] = [
    "file",
    "line",
    "code",
    "component",
    "event",
    "handler",
    "message",
    "kind",
    "advisory",
    "severity",
    "related",
    "flow",
    "ignore_reason",
    "column",
];

#[test]
fn a_projection_names_exactly_the_members_it_carries() {
    if stand_down_while_writing() {
        return;
    }
    // The two ways a projection can lie, and BOTH are live now. A `partial` can
    // claim members its documents do not have, or carry ones it did not claim.
    // A `full` can be declared over a SHORT document — which became the
    // reachable lie the day the verdict layer stopped being partial (#259
    // cp5.1/5.2), and which the partial-only version of this test could not
    // see.
    for (name, facts_path) in artifacts() {
        let ours = capture(&read(&facts_path)).expect("capture");
        for layer in ours.get("layers").and_then(Json::as_array).expect("layers") {
            let projection = layer.get("projection").expect("projection");
            let kind = projection.get("kind").and_then(Json::as_str);
            let Some(document) = layer.get("document") else {
                continue; // a refused layer carries no records to check
            };
            // The verdict list is the only layer whose records this test can
            // describe; the other two surfaces are documents of their own shape.
            let Some(records) = document.get("findings").and_then(Json::as_array) else {
                continue;
            };
            let claimed: BTreeSet<&str> = match kind {
                Some("partial") => {
                    let claimed: BTreeSet<&str> = projection
                        .get("members")
                        .and_then(Json::as_array)
                        .expect("members")
                        .iter()
                        .filter_map(Json::as_str)
                        .collect();
                    assert!(
                        !claimed.is_empty(),
                        "{name}: a partial projection names nothing"
                    );
                    claimed
                }
                Some("full") => VERDICT_SURFACE_MEMBERS.into_iter().collect(),
                other => panic!("{name}: unknown projection kind {other:?}"),
            };
            for record in records {
                let actual: BTreeSet<&str> = record.keys().into_iter().collect();
                assert_eq!(
                    actual, claimed,
                    "{name}: a record's members differ from the projection's claim — a \
                     projection that over- or under-claims is exactly what this field exists \
                     to prevent"
                );
            }
        }
    }
}

#[test]
fn both_engines_report_the_same_layers_in_the_same_order() {
    if stand_down_while_writing() {
        return;
    }
    // STRUCTURE only: this asserts nothing about either engine's values, and
    // is not a comparison. It is the precondition a later reduction needs —
    // two captures that do not line up layer-for-layer cannot be walked.
    for (name, _facts) in artifacts() {
        let artifact =
            parse(&read(&format!("{FIXTURES}/repro/{name}.repro.json"))).expect("artifact parses");
        for id in [ENGINE_PYTHON, ENGINE_RUST] {
            let entry =
                engine_entry(&artifact, id).unwrap_or_else(|| panic!("{name}: no '{id}' entry"));
            let layers: Vec<&str> = entry
                .get("layers")
                .and_then(Json::as_array)
                .expect("layers")
                .iter()
                .filter_map(|l| l.get("layer").and_then(Json::as_str))
                .collect();
            assert_eq!(
                layers,
                LAYER_ORDER.to_vec(),
                "{name}: engine '{id}' does not report the frozen layers in order"
            );
        }
    }
}
