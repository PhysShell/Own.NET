//! The Version family's differential census — one row per JSON value class,
//! each carrying the byte the **reference** produced for it.
//!
//! #261 ruling 2a makes the `ownir_version` rejection text our own on both
//! sides, so its oracle is `repr(json.loads(raw)["ownir_version"])` evaluated
//! by `CPython`. R2 measured four values by hand and read parity; H3.1 measured
//! the value *classes* and found three defects those four could not reach —
//! object key order, float spelling, and the branch an oversized integer takes.
//! This file is what stops that from happening a third time: the classes are
//! enumerated, and every expectation below is a `CPython` byte, not a Rust one.
//!
//! **Measured**, not asserted, on this tree with `CPython`
//! 3.11.15 (`unicodedata` 14.0.0):
//! `ownlang.ownir.load` over each document, `str(OwnIRError)` recorded
//! verbatim. It then replays with **zero Python**, which is the whole point —
//! Python authored these bytes once and the Rust suite defends them forever.
//!
//! The two groups are separate on purpose. Group 1 is the byte denominator:
//! every row must match, and a new value class belongs here unless a ruling
//! says otherwise. Group 2 holds the **declared** divergences — the reference's
//! non-standard JSON (V1), the `-0` encoding split (V2), and the Unicode
//! table skew (V4) — pinned to what THIS crate does, with the reference's own
//! answer written beside each so the difference can never quietly become a
//! match nobody re-examined, nor drift back into group 1's denominator.

use own_ir::OwnIr;

/// `(class, document, the reference's exact message)`.
const CENSUS: &[(&str, &str, &str)] = &[
    ("float 1e-6", "{\"ownir_version\": 1e-6}", "OwnIR 'ownir_version' must be an integer, got 1e-06"),
    ("float 1E-6", "{\"ownir_version\": 1E-6}", "OwnIR 'ownir_version' must be an integer, got 1e-06"),
    ("float 1e+00", "{\"ownir_version\": 1e+00}", "OwnIR 'ownir_version' must be an integer, got 1.0"),
    ("float 1.00", "{\"ownir_version\": 1.00}", "OwnIR 'ownir_version' must be an integer, got 1.0"),
    ("float -0.0", "{\"ownir_version\": -0.0}", "OwnIR 'ownir_version' must be an integer, got -0.0"),
    ("float 1e16", "{\"ownir_version\": 1e16}", "OwnIR 'ownir_version' must be an integer, got 1e+16"),
    ("float 1e15", "{\"ownir_version\": 1e15}", "OwnIR 'ownir_version' must be an integer, got 1000000000000000.0"),
    ("float 1e-5", "{\"ownir_version\": 1e-5}", "OwnIR 'ownir_version' must be an integer, got 1e-05"),
    ("float 1e-4", "{\"ownir_version\": 0.0001}", "OwnIR 'ownir_version' must be an integer, got 0.0001"),
    // Two doubles whose exact value sits midway between two candidates of the
    // shortest round-trip length. CPython rounds that tie to EVEN; Rust's
    // shortest formatter does not, which is why the digits come from Rust's
    // exact formatter. Found by a 24 000-value sweep, not by inspection.
    (
        "float shortest-round-trip tie",
        "{\"ownir_version\": -1128910513108089.2}",
        "OwnIR 'ownir_version' must be an integer, got -1128910513108089.2",
    ),
    (
        "float tie, positive",
        "{\"ownir_version\": 154463098647652.62}",
        "OwnIR 'ownir_version' must be an integer, got 154463098647652.62",
    ),
    ("object b,a", "{\"ownir_version\": {\"b\": 1, \"a\": 2}}", "OwnIR 'ownir_version' must be an integer, got {'b': 1, 'a': 2}"),
    ("object dup b", "{\"ownir_version\": {\"b\": 1, \"a\": 2, \"b\": 3}}", "OwnIR 'ownir_version' must be an integer, got {'b': 3, 'a': 2}"),
    ("object nested", "{\"ownir_version\": {\"z\": [1, {\"y\": null}, true], \"a\": \"s\"}}", "OwnIR 'ownir_version' must be an integer, got {'z': [1, {'y': None}, True], 'a': 's'}"),
    ("object empty", "{\"ownir_version\": {}}", "OwnIR 'ownir_version' must be an integer, got {}"),
    ("string quote-heavy", "{\"ownir_version\": \"it's \\\"x\\\"\\n\\u0001\"}", "OwnIR 'ownir_version' must be an integer, got 'it\\'s \"x\"\\n\\x01'"),
    ("string astral", "{\"ownir_version\": \"\\ud83d\\ude00\"}", "OwnIR 'ownir_version' must be an integer, got '😀'"),
    ("string plain", "{\"ownir_version\": \"0\"}", "OwnIR 'ownir_version' must be an integer, got '0'"),
    ("bool true", "{\"ownir_version\": true}", "OwnIR 'ownir_version' must be an integer, got True"),
    ("null", "{\"ownir_version\": null}", "OwnIR 'ownir_version' must be an integer, got None"),
    ("array of one", "{\"ownir_version\": [\"a\"]}", "OwnIR 'ownir_version' must be an integer, got ['a']"),
    ("array empty", "{\"ownir_version\": []}", "OwnIR 'ownir_version' must be an integer, got []"),
    ("int oversized +", "{\"ownir_version\": 10000000000000000000000000000000}", "OwnIR facts are schema v10000000000000000000000000000000, but this core understands v0. Build the Roslyn extractor and the Python core from the same commit — the OwnIR fact vocabulary changed between the version that produced this file and the one reading it."),
    ("int oversized -", "{\"ownir_version\": -10000000000000000000000000000000}", "OwnIR facts are schema v-10000000000000000000000000000000, but this core understands v0. Build the Roslyn extractor and the Python core from the same commit — the OwnIR fact vocabulary changed between the version that produced this file and the one reading it."),
    ("int i64 max + 1", "{\"ownir_version\": 9223372036854775808}", "OwnIR facts are schema v9223372036854775808, but this core understands v0. Build the Roslyn extractor and the Python core from the same commit — the OwnIR fact vocabulary changed between the version that produced this file and the one reading it."),
    ("int mismatch 7", "{\"ownir_version\": 7}", "OwnIR facts are schema v7, but this core understands v0. Build the Roslyn extractor and the Python core from the same commit — the OwnIR fact vocabulary changed between the version that produced this file and the one reading it."),
];

/// Every value class the reference rejects, spelled byte for byte as the
/// reference spells it.
#[test]
fn the_version_family_is_byte_exact_with_the_reference() {
    let mut divergent = Vec::new();
    for (class, document, expected) in CENSUS {
        match OwnIr::from_json(document) {
            Ok(_) => divergent.push(format!("{class}: accepted, reference rejected")),
            Err(e) if e.message == *expected => {}
            Err(e) => divergent.push(format!(
                "{class}:\n     reference: {expected}\n        this core: {}",
                e.message
            )),
        }
    }
    assert!(
        divergent.is_empty(),
        "{} of {} value classes diverge from the reference:\n  {}",
        divergent.len(),
        CENSUS.len(),
        divergent.join("\n  ")
    );
}

/// The census is only worth its name if it keeps covering the classes the
/// three H3.1 defects lived in. Each of these is a class a defect hid behind,
/// so deleting the row is the cheapest way to un-fix the bug.
#[test]
fn the_census_covers_the_classes_the_defects_hid_in() {
    let documents: Vec<&str> = CENSUS.iter().map(|(_, d, _)| *d).collect();
    let has = |needle: &str| documents.iter().any(|d| d.contains(needle));
    // A multi-key object whose document order is NOT sorted order — the one
    // shape a single-key control can never distinguish.
    assert!(has(r#"{"b": 1, "a": 2}"#), "no out-of-order object class");
    // A repeated key, whose position and value come from different bindings.
    assert!(has(r#""b": 1, "a": 2, "b": 3"#), "no repeated-key class");
    // A float whose exponent needs padding, on both sides of both boundaries.
    for float in ["1e-6", "1e-5", "0.0001", "1e15", "1e16"] {
        assert!(has(float), "no {float} class");
    }
    // A float whose shortest round-trip digits are a TIE, so the last digit is
    // decided by the rounding rule rather than by the value.
    assert!(
        has("-1128910513108089.2"),
        "no shortest-round-trip tie class"
    );
    // An integer past i64 in both directions, and at the exact boundary.
    assert!(
        has("10000000000000000000000000000000"),
        "no oversized + class"
    );
    assert!(
        has("-10000000000000000000000000000000"),
        "no oversized - class"
    );
    assert!(has("9223372036854775808"), "no i64-boundary class");
}

/// Group 2 — the declared divergences. `(class, document)`, with the
/// reference's own answer in the comment above each row.
const DECLARED: &[(&str, &str)] = &[
    // reference: REJECT OwnIR 'ownir_version' must be an integer, got nan
    ("V1 NaN", "{\"ownir_version\": NaN}"),
    // reference: REJECT OwnIR 'ownir_version' must be an integer, got inf
    ("V1 Infinity", "{\"ownir_version\": Infinity}"),
    // reference: REJECT OwnIR 'ownir_version' must be an integer, got -inf
    ("V1 -Infinity", "{\"ownir_version\": -Infinity}"),
    // reference: ACCEPT
    ("V2 literal -0", "{\"ownir_version\": -0}"),
    // reference: REJECT OwnIR 'ownir_version' must be an integer, got '\u088f'
    // (`CPython` 3.11.15 links Unicode 14.0.0, where U+088F is unassigned)
    ("V4 unicode table skew", "{\"ownir_version\": \"\u{88f}\"}"),
];

/// The declared divergences still diverge, and still diverge the way the
/// rulings say. A ruling that has quietly become true is a ruling to retire
/// deliberately, not one to discover by accident — and one that has quietly
/// become a DIFFERENT divergence is a new defect wearing an old label.
#[test]
fn the_declared_divergences_are_exactly_the_declared_ones() {
    let outcome = |document: &str| match OwnIr::from_json(document) {
        Ok(_) => "ACCEPT".to_owned(),
        Err(e) => e.message,
    };
    let mut unhandled = Vec::new();
    for (class, document) in DECLARED {
        let got = outcome(document);
        match *class {
            // V1: `NaN`/`Infinity` are `CPython` `json` extensions, not JSON.
            // The reference reads them as floats and reports `nan`/`inf`;
            // this parser refuses the document. A declared reference defect
            // (#261 ruling V1) — NOT something to teach the parser.
            "V1 NaN" | "V1 Infinity" | "V1 -Infinity" => assert!(
                got.starts_with("not valid JSON: "),
                "{class} should still be refused as malformed, got {got:?}"
            ),
            // V2: the reference reads the literal `-0` as the int 0 and
            // ACCEPTS; `serde_json` reads the float -0.0 and this crate
            // reports what its own parser read. #260 froze the same split.
            "V2 literal -0" => assert_eq!(
                got, "OwnIR 'ownir_version' must be an integer, got -0.0",
                "{class} must report OUR parser's reading, never an acceptance \
                 we do not grant"
            ),
            // V4: `str.isprintable()` is a question about the Unicode table
            // each side was BUILT with. `CPython` 3.11.15 links 14.0.0, where
            // U+088F is unassigned and so escapes; `unicode-properties` 0.1.4
            // ships 17.0.0, where it is assigned Arabic and prints. 15 097
            // code points differ across that gap (measured, whole plane sweep).
            // No single static Unicode table can match every supported CPython
            // reference version at once — the table is a property of the interpreter
            // BUILD (CPython 3.11 -> UCD 14.0.0, CPython 3.12 -> UCD 15.0.0,
            // CPython 3.13 -> UCD 15.1.0), so pinning this crate's table would buy
            // parity with one Python and silently lose it against another.
            "V4 unicode table skew" => assert_eq!(
                got, "OwnIR 'ownir_version' must be an integer, got '\u{88f}'",
                "{class} must follow THIS crate's Unicode table; if this row \
                 moved, a dependency changed its answer and the skew needs \
                 re-measuring, not re-asserting"
            ),
            other => unhandled.push(other),
        }
    }
    assert!(
        unhandled.is_empty(),
        "a class was added to the declared table without a ruling to justify \
         it, so nothing checked it: {unhandled:?}"
    );
}

/// `-0` INSIDE a container is not the V2 divergence and must not be treated as
/// one: nothing there is being type-checked, so the message is free to be the
/// reference's own spelling — and is. This row is why the V2 stand-down is
/// written as "the value the type check is about", not "any -0 anywhere".
#[test]
fn negative_zero_below_the_top_level_matches_the_reference() {
    let refused = OwnIr::from_json(r#"{"ownir_version": [-0]}"#)
        .err()
        .map(|e| e.message);
    assert_eq!(
        refused.as_deref(),
        Some("OwnIR 'ownir_version' must be an integer, got [0]")
    );
}
