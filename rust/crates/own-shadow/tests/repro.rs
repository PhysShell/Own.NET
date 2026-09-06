//! The layer-0 acceptance contract (P-022 step 7a, #260/#269), replayed with
//! **zero Python**:
//!
//! ```text
//! every shared facts document → canonical form → sha256
//!     ≡ tests/fixtures/repro/digests.json          (same-input capture)
//!
//! every committed artifact  → parse → render
//!     ≡ the committed bytes                        (the format round-trips)
//!                            → verify              (it describes itself)
//!                            → one changed byte in the embedded document
//!     ⇒ refused                                    (the digest is a gate)
//! ```
//!
//! The digest ledger and the artifacts are Python-authored (regenerate:
//! `python tests/test_repro_fixtures.py --write`) and used here as expected
//! output only, never as an input to construction.
//!
//! **Infrastructure for shadow mode, not shadow mode**: nothing here compares
//! two engines' outputs. The artifacts carry one engine's capture, and this
//! side takes no side on it.
//!
//! Independently enforced here, not outsourced to the Python harness:
//! * the ledger covers exactly the facts documents on disk across all five
//!   swept corpora — a corpus document with no digest record, or a record
//!   naming a document that is gone, is a red build;
//!   the corpus roots are listed here too, so a *new* corpus directory has to
//!   be added on both sides deliberately;
//! * every artifact named by the manifest exists, and every `*.repro.json` on
//!   disk is named by the manifest;
//! * the canonical form is order-, whitespace- and duplicate-key-independent,
//!   and it separates documents that differ in one character;
//! * the manifest's `domain_refusals` ledger is EXECUTABLE here too: every
//!   document it declares unnameable must be refused by this engine's parser,
//!   for the declared reason where the two engines share one. An entry that
//!   stops holding is a red build demanding a decision, never a silently
//!   widened domain.

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use std::collections::{BTreeMap, BTreeSet};

use own_shadow::{
    canonical_hash, parse, render, verify, Json, CANONICAL_ALGORITHM, ENGINE_ORDER, LAYER_ORDER,
    REPRO_VERSION,
};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures");

/// The swept corpora, mirroring `tests/test_repro_fixtures.py::CORPORA`. Held
/// here as data so that adding a corpus is a deliberate two-sided change.
const CORPORA: [&str; 5] = ["ownir", "lowered", "summaries", "verdicts", "repro"];

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| {
        panic!("cannot read {path}: {e} — regenerate: python tests/test_repro_fixtures.py --write")
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

/// case → (corpus label, facts path), swept from disk exactly as the reference
/// harness sweeps it.
fn facts_on_disk() -> BTreeMap<String, (String, String)> {
    let refusals = domain_refusals();
    let mut plan: BTreeMap<String, (String, String)> = BTreeMap::new();
    for corpus in CORPORA {
        let dir = format!("{FIXTURES}/{corpus}");
        for name in stems(&dir, ".facts.json") {
            // A refusal control is deliberately NOT a capturable case: it has
            // no digest, because the point is that neither engine can name it.
            if refusals.iter().any(|(n, _)| n == &name) {
                continue;
            }
            let previous = plan.insert(
                name.clone(),
                (corpus.to_owned(), format!("{dir}/{name}.facts.json")),
            );
            assert!(
                previous.is_none(),
                "case name '{name}' exists in more than one corpus — names must be unique \
                 across the sweep, because one digest ledger serves them all"
            );
        }
    }
    assert!(!plan.is_empty(), "no facts documents swept");
    plan
}

fn manifest() -> Json {
    parse(&read(&format!("{FIXTURES}/repro/manifest.json"))).expect("repro manifest parses")
}

/// The declared-unnameable documents: `(case, Option<required error substring>)`.
fn domain_refusals() -> Vec<(String, Option<String>)> {
    manifest()
        .get("domain_refusals")
        .and_then(Json::as_array)
        .expect("manifest carries a 'domain_refusals' ledger")
        .iter()
        .map(|e| {
            let name = e
                .get("name")
                .and_then(Json::as_str)
                .expect("a refusal entry names its case")
                .to_owned();
            assert!(
                e.get("reason")
                    .and_then(Json::as_str)
                    .is_some_and(|r| !r.is_empty()),
                "refusal '{name}' must say WHY the two engines cannot agree on it"
            );
            let needle = e
                .get("rust_error_contains")
                .and_then(Json::as_str)
                .map(str::to_owned);
            (name, needle)
        })
        .collect()
}

#[test]
fn every_declared_unnameable_document_is_refused() {
    let refusals = domain_refusals();
    assert!(!refusals.is_empty(), "the refusal ledger is empty");
    for (name, needle) in &refusals {
        let path = format!("{FIXTURES}/repro/{name}.facts.json");
        let text = read(&path);
        let err = parse(&text).err().unwrap_or_else(|| {
            panic!(
                "{name}: this engine ACCEPTS a document the ledger declares unnameable — \
                 the control has rotted; promote it or record the decision"
            )
        });
        if let Some(needle) = needle {
            assert!(
                err.to_string().contains(needle.as_str()),
                "{name}: refused, but not for the declared reason: expected {needle:?} in {err}"
            );
        }
    }
}

fn ledger() -> Json {
    parse(&read(&format!("{FIXTURES}/repro/digests.json")))
        .expect("digests.json parses over the canonical domain")
}

#[test]
fn every_shared_document_hashes_to_the_recorded_digest() {
    let ledger = ledger();
    assert_eq!(
        ledger.get("repro_version").and_then(Json::as_i64),
        Some(REPRO_VERSION),
        "digests.json is keyed to a different format version"
    );
    assert_eq!(
        ledger.get("algorithm").and_then(Json::as_str),
        Some(CANONICAL_ALGORITHM),
        "digests.json names a different digest algorithm"
    );

    let recorded: BTreeMap<String, (String, String, i64)> = ledger
        .get("documents")
        .and_then(Json::as_array)
        .expect("digests.json carries a 'documents' array")
        .iter()
        .map(|r| {
            let case = r
                .get("case")
                .and_then(Json::as_str)
                .expect("case")
                .to_owned();
            let corpus = r
                .get("corpus")
                .and_then(Json::as_str)
                .expect("corpus")
                .to_owned();
            let digest = r
                .get("digest")
                .and_then(Json::as_str)
                .expect("digest")
                .to_owned();
            let bytes = r.get("bytes").and_then(Json::as_i64).expect("bytes");
            (case, (corpus, digest, bytes))
        })
        .collect();

    let on_disk = facts_on_disk();
    assert_eq!(
        recorded.keys().collect::<Vec<_>>(),
        on_disk.keys().collect::<Vec<_>>(),
        "the digest ledger and the swept corpora disagree about which documents exist; \
         regenerate: python tests/test_repro_fixtures.py --write"
    );

    let mut divergences: Vec<String> = Vec::new();
    for (case, (corpus, path)) in &on_disk {
        let document = match parse(&read(path)) {
            Ok(d) => d,
            Err(e) => {
                divergences.push(format!(
                    "{case}: this engine cannot parse the document over the canonical \
                     domain, but the reference recorded a digest for it: {e}"
                ));
                continue;
            }
        };
        let got = canonical_hash(&document);
        // Determinism: the same document, twice.
        assert_eq!(
            got,
            canonical_hash(&document),
            "{case}: hash is not deterministic"
        );
        let (want_corpus, want_digest, want_bytes) = recorded.get(case).expect("checked above");
        if want_corpus != corpus {
            divergences.push(format!(
                "{case}: recorded under corpus {want_corpus}, found under {corpus}"
            ));
        }
        if &got.digest != want_digest || i64::try_from(got.bytes).ok() != Some(*want_bytes) {
            divergences.push(format!(
                "{case}: canonical identity differs\n    python = {want_digest} ({want_bytes} bytes)\
                 \n    rust   = {} ({} bytes)",
                got.digest, got.bytes
            ));
        }
    }
    assert!(
        divergences.is_empty(),
        "the two engines do not agree on the identity of {} document(s):\n{}",
        divergences.len(),
        divergences.join("\n")
    );
}

fn manifest_artifacts() -> BTreeSet<String> {
    let manifest = manifest();
    assert_eq!(
        manifest.get("repro_version").and_then(Json::as_i64),
        Some(REPRO_VERSION),
        "the repro manifest is keyed to a different format version"
    );
    let mut names = BTreeSet::new();
    for entry in manifest
        .get("artifacts")
        .and_then(Json::as_array)
        .expect("manifest carries an 'artifacts' ledger")
    {
        let name = entry
            .get("name")
            .and_then(Json::as_str)
            .expect("an artifact entry names its case");
        let pins = entry
            .get("pins")
            .and_then(Json::as_array)
            .expect("an artifact entry says what it pins");
        assert!(
            !pins.is_empty(),
            "artifact '{name}' must say what it is evidence FOR"
        );
        assert!(names.insert(name.to_owned()), "duplicate artifact '{name}'");
    }
    assert_eq!(
        names,
        stems(&format!("{FIXTURES}/repro"), ".repro.json"),
        "the manifest's artifact ledger and the *.repro.json files on disk disagree"
    );
    names
}

#[test]
fn every_committed_artifact_round_trips_and_verifies() {
    let names = manifest_artifacts();
    assert!(!names.is_empty(), "no artifacts committed");
    let mut carried_refusals = 0_usize;
    for name in &names {
        let path = format!("{FIXTURES}/repro/{name}.repro.json");
        let bytes = read(&path);
        let artifact =
            parse(&bytes).unwrap_or_else(|e| panic!("{name}: artifact does not parse: {e}"));

        // The format round-trips: parse then render reproduces the file.
        assert_eq!(
            render(&artifact),
            bytes,
            "{name}: the artifact does not round-trip byte-for-byte — this side renders it \
             differently from the reference"
        );
        // It describes itself.
        assert_eq!(
            verify(&artifact),
            Vec::<String>::new(),
            "{name}: the committed artifact does not verify"
        );
        // The frozen vocabularies are actually present, not merely permitted.
        let engines = artifact
            .get("engines")
            .and_then(Json::as_array)
            .expect("engines");
        for engine in engines {
            let id = engine.get("id").and_then(Json::as_str).expect("engine id");
            assert!(ENGINE_ORDER.contains(&id), "{name}: unknown engine {id}");
            let layers = engine
                .get("layers")
                .and_then(Json::as_array)
                .expect("layers");
            assert_eq!(layers.len(), LAYER_ORDER.len(), "{name}: layer count");
            carried_refusals += layers
                .iter()
                .filter(|l| l.get("status").and_then(Json::as_str) == Some("refused"))
                .count();
        }
    }
    assert!(
        carried_refusals > 0,
        "no committed artifact carries a REFUSED layer — the curated set must include the \
         shape a first-divergence reduction has to distinguish from a produced one"
    );
}

/// Replace the first string leaf (depth-first, document order) with a value
/// differing in exactly one character — the same deterministic mutation the
/// reference harness applies, so the refusal it provokes is reproducible.
fn tamper(value: &Json, done: &mut bool) -> Json {
    if *done {
        return value.clone();
    }
    match value {
        Json::Str(s) if !s.is_empty() => {
            *done = true;
            let mut chars = s.chars();
            let head = chars.next().expect("non-empty");
            let replacement = if head == 'a' { 'b' } else { 'a' };
            let mut out = String::with_capacity(s.len());
            out.push(replacement);
            out.extend(chars);
            Json::Str(out)
        }
        Json::Int(i) => {
            *done = true;
            Json::Int(if *i > 0 {
                i.saturating_sub(1)
            } else {
                i.saturating_add(1)
            })
        }
        Json::Array(items) => Json::Array(items.iter().map(|v| tamper(v, done)).collect()),
        Json::Object(entries) => Json::Object(
            entries
                .iter()
                .map(|(k, v)| (k.clone(), tamper(v, done)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn replace_document(artifact: &Json, document: &Json) -> Json {
    let Json::Object(entries) = artifact else {
        panic!("artifact is not an object")
    };
    Json::Object(
        entries
            .iter()
            .map(|(k, v)| {
                if k != "input" {
                    return (k.clone(), v.clone());
                }
                let Json::Object(input) = v else {
                    panic!("input is not an object")
                };
                let rebuilt = input
                    .iter()
                    .map(|(ik, iv)| {
                        if ik == "document" {
                            (ik.clone(), document.clone())
                        } else {
                            (ik.clone(), iv.clone())
                        }
                    })
                    .collect();
                (k.clone(), Json::Object(rebuilt))
            })
            .collect(),
    )
}

#[test]
fn a_changed_byte_in_the_embedded_document_is_refused() {
    for name in manifest_artifacts() {
        let path = format!("{FIXTURES}/repro/{name}.repro.json");
        let artifact = parse(&read(&path)).expect("artifact parses");
        let document = artifact
            .get("input")
            .and_then(|i| i.get("document"))
            .expect("input.document")
            .clone();

        let mut done = false;
        let forged_document = tamper(&document, &mut done);
        assert!(done, "{name}: the embedded document has no leaf to tamper");
        assert_ne!(
            canonical_hash(&forged_document).digest,
            canonical_hash(&document).digest,
            "{name}: a changed character did not change the digest"
        );

        let forged = replace_document(&artifact, &forged_document);
        let problems = verify(&forged);
        assert!(
            problems
                .iter()
                .any(|p| p.contains("input.canonical does not describe input.document")),
            "{name}: an artifact whose embedded document was changed still verifies — the \
             digest is not a gate. Problems reported: {problems:?}"
        );
    }
}

#[test]
fn the_canonical_form_ignores_only_insignificant_text_formatting() {
    // Key order, whitespace and a duplicate key are text formatting: the
    // canonical form is taken over the PARSED document, so all three hash the
    // same. `dict` semantics for a duplicate key are last-wins, and both
    // engines have to agree about that or "same input" means nothing.
    let ordered = parse(r#"{"a": 1, "b": [2, 3], "c": {"d": null}}"#).unwrap();
    let shuffled = parse("{\n  \"c\" : { \"d\" : null },\n  \"b\":[2,3],\n\n \"a\":\t1 }").unwrap();
    let duplicated = parse(r#"{"a": 99, "b": [2, 3], "a": 1, "c": {"d": null}}"#).unwrap();
    assert_eq!(canonical_hash(&ordered), canonical_hash(&shuffled));
    assert_eq!(canonical_hash(&ordered), canonical_hash(&duplicated));

    // …and one changed character is a different document.
    let changed = parse(r#"{"a": 2, "b": [2, 3], "c": {"d": null}}"#).unwrap();
    assert_ne!(canonical_hash(&ordered), canonical_hash(&changed));

    // The rendering, unlike the hash, keeps document order — the artifact
    // carries the input as written (BR-D4: input order is semantic).
    assert!(shuffled.to_pretty().starts_with("{\n  \"c\": {"));
    assert_eq!(ordered.to_canonical(), shuffled.to_canonical());
}

#[test]
fn values_outside_the_canonical_domain_are_refused_at_parse() {
    for text in [
        r#"{"x": 1.5}"#,
        r#"{"x": 1e3}"#,
        r#"{"x": 9223372036854775808}"#,
        r#"{"x": -9223372036854775809}"#,
    ] {
        let err = parse(text).expect_err(&format!("{text} must be refused, never rounded"));
        assert!(
            err.to_string().contains("canonical domain"),
            "{text}: refused for the wrong reason: {err}"
        );
    }
    // The edges themselves are IN the domain.
    assert!(parse(r#"{"x": 9223372036854775807}"#).is_ok());
    assert!(parse(r#"{"x": -9223372036854775808}"#).is_ok());
}

/// Replace (or insert) one member of an object, keeping document order.
fn with_member(value: &Json, key: &str, replacement: Option<Json>) -> Json {
    let Json::Object(entries) = value else {
        panic!("not an object")
    };
    let mut out: Vec<(String, Json)> = Vec::new();
    let mut replaced = false;
    for (k, v) in entries {
        if k == key {
            replaced = true;
            if let Some(r) = &replacement {
                out.push((k.clone(), r.clone()));
            }
        } else {
            out.push((k.clone(), v.clone()));
        }
    }
    if !replaced {
        if let Some(r) = replacement {
            out.push((key.to_owned(), r));
        }
    }
    Json::Object(out)
}

fn engine0(artifact: &Json) -> Json {
    artifact
        .get("engines")
        .and_then(Json::as_array)
        .and_then(<[Json]>::first)
        .expect("first engine")
        .clone()
}

fn with_engines(artifact: &Json, engines: Vec<Json>) -> Json {
    with_member(artifact, "engines", Some(Json::Array(engines)))
}

fn layers(engine: &Json) -> Vec<Json> {
    engine
        .get("layers")
        .and_then(Json::as_array)
        .expect("layers")
        .to_vec()
}

/// Rebuild the artifact with the FIRST layer replaced by `f(first)` — an
/// iterator form, because the workspace denies panicking indexing.
fn with_first_layer(artifact: &Json, f: impl Fn(&Json) -> Json) -> Json {
    let rebuilt = layers(&engine0(artifact))
        .iter()
        .enumerate()
        .map(|(i, l)| if i == 0 { f(l) } else { l.clone() })
        .collect();
    with_layers(artifact, rebuilt)
}

fn with_layers(artifact: &Json, new: Vec<Json>) -> Json {
    let engine = with_member(&engine0(artifact), "layers", Some(Json::Array(new)));
    with_engines(artifact, vec![engine])
}

/// Negative controls for [`own_shadow::verify`]: every structural rule it
/// states must have a document that breaks exactly that rule and is refused
/// for it. Without these, `verify` could degrade to "recompute the digest" and
/// every positive check would still pass — the shape P-022 discipline 2 is
/// about. Mirrors `tests/test_repro_fixtures.py::_structural_controls`, case
/// for case: the two are independent readings of one frozen rule.
#[test]
#[allow(clippy::too_many_lines)] // twelve controls, each three lines of data
fn verify_refuses_each_structural_violation() {
    let name = "canonical_minimal";
    let artifact =
        parse(&read(&format!("{FIXTURES}/repro/{name}.repro.json"))).expect("artifact parses");
    assert_eq!(
        verify(&artifact),
        Vec::<String>::new(),
        "the control base must verify"
    );

    let mut cases: Vec<(&str, &str, Json)> = Vec::new();

    cases.push((
        "a wrong format version",
        "repro_version",
        with_member(
            &artifact,
            "repro_version",
            Some(Json::Int(REPRO_VERSION + 1)),
        ),
    ));
    cases.push((
        "an unknown artifact member",
        "unknown member",
        with_member(&artifact, "extra_member", Some(Json::Int(1))),
    ));
    let mut short = layers(&engine0(&artifact));
    short.remove(1);
    cases.push(("a missing layer", "frozen", with_layers(&artifact, short)));
    let mut reversed = layers(&engine0(&artifact));
    reversed.reverse();
    cases.push((
        "layers out of the frozen order",
        "frozen",
        with_layers(&artifact, reversed),
    ));
    cases.push((
        "an unknown engine id",
        "frozen engine vocabulary",
        with_engines(
            &artifact,
            vec![with_member(
                &engine0(&artifact),
                "id",
                Some(Json::Str("some-other-engine".to_owned())),
            )],
        ),
    ));
    cases.push((
        "a repeated engine",
        "appears twice",
        with_engines(&artifact, vec![engine0(&artifact), engine0(&artifact)]),
    ));
    cases.push((
        "engines out of the frozen order",
        "out of the frozen order",
        with_engines(
            &artifact,
            vec![
                with_member(
                    &engine0(&artifact),
                    "id",
                    Some(Json::Str("rust-own-bridge".to_owned())),
                ),
                engine0(&artifact),
            ],
        ),
    ));
    cases.push((
        "a produced layer carrying an error",
        "carries an error",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "error",
                Some(Json::Str("an error beside a document".to_owned())),
            )
        }),
    ));
    cases.push((
        "a refused layer without an error",
        "non-empty error text",
        with_first_layer(&artifact, |l| {
            with_member(
                &with_member(l, "document", None),
                "status",
                Some(Json::Str("refused".to_owned())),
            )
        }),
    ));
    cases.push((
        "a layer without surface_version",
        "surface_version is missing",
        with_first_layer(&artifact, |l| with_member(l, "surface_version", None)),
    ));
    cases.push((
        "an unknown layer status",
        "is neither",
        with_first_layer(&artifact, |l| {
            with_member(l, "status", Some(Json::Str("maybe".to_owned())))
        }),
    ));
    cases.push((
        "a missing canonical block",
        "input.canonical is missing",
        with_member(
            &artifact,
            "input",
            Some(with_member(
                artifact.get("input").expect("input"),
                "canonical",
                None,
            )),
        ),
    ));

    cases.push((
        "a layer without a projection",
        "projection is missing",
        with_first_layer(&artifact, |l| with_member(l, "projection", None)),
    ));
    cases.push((
        "an unknown projection kind",
        "is not one of",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "projection",
                Some(Json::Object(vec![(
                    "kind".to_owned(),
                    Json::Str("mostly".to_owned()),
                )])),
            )
        }),
    ));
    cases.push((
        "a partial projection naming no members",
        "must NAME",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "projection",
                Some(Json::Object(vec![
                    ("kind".to_owned(), Json::Str("partial".to_owned())),
                    (
                        "reason".to_owned(),
                        Json::Str("some members are not ported".to_owned()),
                    ),
                ])),
            )
        }),
    ));
    cases.push((
        "a partial projection with no reason",
        "must say WHY",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "projection",
                Some(Json::Object(vec![
                    ("kind".to_owned(), Json::Str("partial".to_owned())),
                    (
                        "members".to_owned(),
                        Json::Array(vec![Json::Str("module".to_owned())]),
                    ),
                ])),
            )
        }),
    ));
    cases.push((
        "a partial projection whose reason is empty",
        "must say WHY",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "projection",
                Some(Json::Object(vec![
                    ("kind".to_owned(), Json::Str("partial".to_owned())),
                    (
                        "members".to_owned(),
                        Json::Array(vec![Json::Str("module".to_owned())]),
                    ),
                    ("reason".to_owned(), Json::Str(String::new())),
                ])),
            )
        }),
    ));
    cases.push((
        "a full projection carrying members",
        "carries no",
        with_first_layer(&artifact, |l| {
            with_member(
                l,
                "projection",
                Some(Json::Object(vec![
                    ("kind".to_owned(), Json::Str("full".to_owned())),
                    (
                        "members".to_owned(),
                        Json::Array(vec![Json::Str("module".to_owned())]),
                    ),
                ])),
            )
        }),
    ));

    assert_eq!(
        cases.len(),
        18,
        "the structural control set changed — keep it in step with the Python side"
    );
    for (label, needle, forged) in cases {
        let problems = verify(&forged);
        assert!(
            problems.iter().any(|p| p.contains(needle)),
            "verify accepts {label} (expected a problem naming {needle:?}, got {problems:?})"
        );
    }
}
