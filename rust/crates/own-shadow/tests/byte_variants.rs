//! Byte-level input variants, the port's column (P-022 step 7a, #260
//! acceptance F.0).
//!
//! The reference's half is `tests/test_byte_variants.py`. It writes the
//! `python` column of `tests/fixtures/repro/variants/byte_variants.json` and
//! carries this one through untouched; this target writes the `rust` column
//! and touches nothing else — the same rule the reproduction artifact follows,
//! for the same reason: a ledger where one engine authored the other's
//! measurement would record one reader twice and call it agreement.
//!
//! ## What is measured, and why it is measured rather than assumed
//!
//! Owner decision B-1 says #260's same-input invariant is **byte-level**, and
//! B-2 says the artifact must attest the bytes each engine actually consumed.
//! Both need one prior fact: which byte-level rewritings of a document do both
//! readers still accept? A rewriting both accept is a **raw variant** — one
//! canonical identity, a different byte sequence, which is precisely the pair
//! B-1 says `canonical-equivalent input != byte-identical input`. A rewriting
//! both refuse is **invalid**, and belongs to the compare driver's negative
//! controls rather than to any artifact.
//!
//! **A disagreement is neither.** If this reader accepts a sequence the
//! reference refuses, or the reverse, that is a domain decision for the owner
//! (the shape D-2 records for `-0`) and this target fails rather than filing
//! it. The class is derived from the two `accepted` flags on both sides; there
//! is nowhere to write a disagreement down and stay green.
//!
//! Two readers are measured here, because they are two different gates and the
//! difference is load-bearing:
//!
//! * [`own_shadow::parse`]'s value reader over the bytes — the **canonical
//!   identity** gate, the one the reference's `load_document` is the twin of;
//! * `serde_json::from_slice::<own_ir::OwnIr>` — this engine's **typed door**,
//!   which is upstream of every layer and refuses more than the value reader
//!   does (#294 OD-1). A document the value reader names and the door refuses
//!   is a *layer* refusal with a declared boundary, never an unnameable input,
//!   and conflating the two is how a declared boundary would come to read as a
//!   parse failure.
//!
//! Regenerate this column with:
//! `OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test byte_variants`

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use own_shadow::{canonical_hash, parse, Json};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures");

fn variants_dir() -> String {
    format!("{FIXTURES}/repro/variants")
}

fn ledger_path() -> String {
    format!("{}/byte_variants.json", variants_dir())
}

/// `OWN_SHADOW_WRITE=1` rewrites this engine's column. Opt-in for the reason
/// every `--write` in this family is: a suite that rewrites its own
/// expectations on every run has measured nothing.
fn writing() -> bool {
    std::env::var("OWN_SHADOW_WRITE").is_ok_and(|v| v == "1")
}

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

/// This engine's answer for one byte sequence.
///
/// Hash-free and allocation-light on purpose: the only thing recorded is what
/// each reader did, plus the canonical identity when the value reader named the
/// document. `stage` is `parse` for every refusal here — unlike the reference,
/// this side has no separate decode step, because `serde_json` reads bytes and
/// reports a bad code point as a syntax error of its own. That asymmetry is
/// data, not noise: it is why the ledger records a stage per side rather than
/// one shared one.
fn measure(raw: &[u8]) -> Json {
    let typed_door = serde_json::from_slice::<own_ir::OwnIr>(raw).is_ok();
    match serde_json::from_slice::<Json>(raw) {
        Ok(value) => {
            let hash = canonical_hash(&value);
            object(vec![
                ("accepted", Json::Bool(true)),
                ("stage", Json::Null),
                ("error", Json::Null),
                ("typed_door_accepted", Json::Bool(typed_door)),
                (
                    "canonical",
                    object(vec![
                        ("algorithm", Json::Str(hash.algorithm.to_owned())),
                        ("digest", Json::Str(hash.digest)),
                        (
                            "bytes",
                            Json::Int(i64::try_from(hash.bytes).unwrap_or(i64::MAX)),
                        ),
                    ]),
                ),
            ])
        }
        Err(e) => object(vec![
            ("accepted", Json::Bool(false)),
            ("stage", Json::Str("parse".to_owned())),
            ("error", Json::Str(e.to_string())),
            ("typed_door_accepted", Json::Bool(typed_door)),
            ("canonical", Json::Null),
        ]),
    }
}

fn read_ledger() -> Json {
    let text = std::fs::read_to_string(ledger_path())
        .unwrap_or_else(|e| panic!("cannot read the byte-variant ledger: {e}"));
    parse(&text).expect("the byte-variant ledger parses")
}

/// The ledger with this engine's column replaced, every other member kept in
/// place — including the reference's, which this side never authors.
fn with_our_column(ledger: &Json) -> Json {
    let Json::Object(entries) = ledger else {
        panic!("the ledger is not an object")
    };
    Json::Object(
        entries
            .iter()
            .map(|(k, v)| {
                if k != "variants" {
                    return (k.clone(), v.clone());
                }
                let rebuilt = v
                    .as_array()
                    .expect("variants array")
                    .iter()
                    .map(|record| {
                        let name = record.get("name").and_then(Json::as_str).expect("name");
                        let raw = std::fs::read(format!("{}/{name}.bin", variants_dir()))
                            .unwrap_or_else(|e| panic!("{name}: cannot read the variant: {e}"));
                        let Json::Object(fields) = record else {
                            panic!("{name}: a variant record is not an object")
                        };
                        Json::Object(
                            fields
                                .iter()
                                .map(|(fk, fv)| {
                                    if fk == "rust" {
                                        (fk.clone(), measure(&raw))
                                    } else {
                                        (fk.clone(), fv.clone())
                                    }
                                })
                                .collect(),
                        )
                    })
                    .collect();
                (k.clone(), Json::Array(rebuilt))
            })
            .collect(),
    )
}

#[test]
fn this_reader_reproduces_its_committed_column() {
    let ledger = read_ledger();
    if writing() {
        let mut out = with_our_column(&ledger).to_pretty();
        out.push('\n');
        std::fs::write(ledger_path(), out).expect("write the byte-variant ledger");
        eprintln!("OWN_SHADOW_WRITE=1: rewrote the 'rust' column of the byte-variant ledger");
        return;
    }
    let mut divergences: Vec<String> = Vec::new();
    for record in ledger
        .get("variants")
        .and_then(Json::as_array)
        .expect("the ledger carries a 'variants' array")
    {
        let name = record.get("name").and_then(Json::as_str).expect("name");
        let raw = std::fs::read(format!("{}/{name}.bin", variants_dir()))
            .unwrap_or_else(|e| panic!("{name}: cannot read the variant: {e}"));

        // The committed variant IS the bytes the ledger claims. Without this
        // the digest beside it describes nothing.
        let claimed = record.get("raw").expect("a variant record carries its raw identity");
        let actual = sha256_hex(&raw);
        assert_eq!(
            claimed.get("digest").and_then(Json::as_str),
            Some(actual.as_str()),
            "{name}: the committed bytes are not the ones the ledger names"
        );
        assert_eq!(
            claimed.get("bytes").and_then(Json::as_i64),
            i64::try_from(raw.len()).ok(),
            "{name}: the committed byte length is not the one the ledger names"
        );

        let ours = measure(&raw);
        match record.get("rust") {
            None | Some(Json::Null) => divergences.push(format!(
                "{name}: the ledger carries no 'rust' column — regenerate: \
                 OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test byte_variants"
            )),
            Some(committed) if committed != &ours => divergences.push(format!(
                "{name}: this reader's answer differs from the committed one\n\
                 committed = {committed:#?}\n     now = {ours:#?}"
            )),
            Some(_) => {}
        }

        // The class is DERIVED, and a disagreement is not a class.
        let python_accepted = record
            .get("python")
            .and_then(|p| p.get("accepted"))
            .map(|v| matches!(v, Json::Bool(true)));
        let ours_accepted = matches!(ours.get("accepted"), Some(Json::Bool(true)));
        assert_eq!(
            python_accepted,
            Some(ours_accepted),
            "{name}: the two readers DISAGREE about this byte sequence. That is a \
             domain decision for the repository owner (the shape D-2 records for '-0'), \
             not something this measurement may file under either class — stop and report."
        );
    }
    assert!(
        divergences.is_empty(),
        "{} variant(s) disagree with this reader:\n{}",
        divergences.len(),
        divergences.join("\n")
    );
}

/// Every accepted variant is the SAME document written as DIFFERENT bytes.
///
/// Both halves matter and each would pass alone: a variant whose canonical
/// identity drifted would not be a rewriting of the base at all, and one whose
/// bytes matched another's would prove nothing about an attestation taken over
/// them. Together they are the executable form of B-1's sentence.
#[test]
fn every_accepted_variant_is_one_document_in_distinct_bytes() {
    if writing() {
        eprintln!("OWN_SHADOW_WRITE=1: regeneration pass, this check stands down");
        return;
    }
    let ledger = read_ledger();
    let mut canonical: Option<String> = None;
    let mut seen: Vec<(String, String)> = Vec::new();
    for record in ledger
        .get("variants")
        .and_then(Json::as_array)
        .expect("variants")
    {
        let name = record.get("name").and_then(Json::as_str).expect("name");
        let raw = std::fs::read(format!("{}/{name}.bin", variants_dir()))
            .unwrap_or_else(|e| panic!("{name}: cannot read the variant: {e}"));
        let Ok(value) = serde_json::from_slice::<Json>(&raw) else {
            continue; // the invalid class: nothing to name
        };
        let digest = canonical_hash(&value).digest;
        match &canonical {
            None => canonical = Some(digest),
            Some(first) => assert_eq!(
                first, &digest,
                "{name}: an accepted variant has a different canonical identity — a raw \
                 variant is the same document, so the canonical form must not see it"
            ),
        }
        let raw_digest = sha256_hex(&raw);
        if let Some((other, _)) = seen.iter().find(|(_, d)| *d == raw_digest) {
            panic!("{name}: the same bytes as {other} — a variant that does not change the byte sequence proves nothing about an attestation over it");
        }
        seen.push((name.to_owned(), raw_digest));
    }
    assert!(
        seen.len() > 1,
        "fewer than two accepted variants: the raw-variant class is not exercised"
    );
}

/// SHA-256, hex. `own_shadow::canonical_hash` hashes the *canonical* form of a
/// parsed value; this hashes the bytes on disk, which is a different question
/// and the one the attestation asks.
fn sha256_hex(raw: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(raw);
    hasher
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
