//! Zero-Python replay of the BR-D1 strict-door acceptance language
//! (`tests/fixtures/ownir_validation.json`, authoritative via
//! `python tests/test_ownir_validation_fixtures.py --write`) — P-022 step 6b,
//! #259 checkpoint 1.
//!
//! The checkpoint is not "port 47 `if`s". It is: **prove the two loaders accept
//! the same language and classify rejections the same way**. So the test is a
//! matrix, not a pass/fail:
//!
//! | | meaning |
//! |---|---|
//! | Python accept / Rust accept | agreed |
//! | Python reject / Rust reject, same kind | agreed |
//! | Python reject / **Rust accept** | *critical permissiveness* — the strict door is the gate over untrusted extractor output |
//! | Python accept / **Rust reject** | *over-strictness* — not a hole, but a post-cutover outage: facts that analyse today would stop |
//! | kind mismatch | both reject, but disagree about **why** |
//!
//! All three failure rows must be zero. The asymmetry in *severity* is real and
//! reported, but it is not an asymmetry in *acceptability*.
//!
//! What is compared is the **kind**, never the message. The reference funnels
//! every rejection into one `OwnIRError` whose strings are a human-facing
//! presentation aid; freezing them would make this a byte-comparison of two
//! languages' English.
//!
//! Equally: the expected kind is declared by the ledger and confirmed by the
//! oracle only as accept/reject. It is **not** derived from the reference's
//! message text — that would abandon message parity at the front door and
//! rebuild it as regex parity at the back.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_ir::{OwnIr, OwnIrErrorKind};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/ownir_validation.json"
);

const SCHEMA_VERSION: u64 = 1;

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE).expect(
        "fixture missing — regenerate: python tests/test_ownir_validation_fixtures.py --write",
    );
    let root: Value = serde_json::from_str(&raw).expect("ownir_validation.json parses");
    assert_eq!(
        root.get("schema_version").and_then(Value::as_u64),
        Some(SCHEMA_VERSION),
        "fixture schema_version changed — a reviewed contract, not a passing reshape"
    );
    root
}

fn cases(root: &Value) -> &Vec<Value> {
    root.get("cases")
        .and_then(Value::as_array)
        .expect("'cases' array")
}

/// The document text to feed the loader.
///
/// A control carrying `raw: true` supplies the file's literal TEXT (the only
/// way to reach the JSON-parse branch); anything else is a value to serialize.
/// The flag is explicit rather than inferred from the document being a string —
/// that heuristic mis-encoded the JSON document `"hello"` as the unparseable
/// bytes `hello`, and the resulting category mismatch looked like a port bug.
fn document_text(case: &Value) -> String {
    let doc = case.get("document").expect("case 'document'");
    if case.get("raw").and_then(Value::as_bool) == Some(true) {
        return doc
            .as_str()
            .expect("a raw control's document is text")
            .to_owned();
    }
    serde_json::to_string(doc).expect("document serializes")
}

#[derive(Default, Debug)]
struct Matrix {
    agreed_accept: usize,
    agreed_reject: usize,
    rust_only_accept: usize,
    rust_only_reject: usize,
    kind_mismatch: usize,
}

#[test]
fn the_two_loaders_accept_the_same_language() {
    let root = load();
    let mut m = Matrix::default();
    let mut permissive: Vec<String> = Vec::new();
    let mut over_strict: Vec<String> = Vec::new();
    let mut mismatched: Vec<String> = Vec::new();

    for case in cases(&root) {
        let name = case
            .get("name")
            .and_then(Value::as_str)
            .expect("case 'name'");
        let python_rejects = case.get("verdict").and_then(Value::as_str) == Some("reject");
        let expected_kind = case.get("category").and_then(Value::as_str);

        match (python_rejects, OwnIr::from_json(&document_text(case))) {
            (false, Ok(_)) => m.agreed_accept = m.agreed_accept.saturating_add(1),
            (true, Err(e)) => {
                let expected = expected_kind.expect("a rejected control declares its kind");
                if e.kind.as_str() == expected {
                    m.agreed_reject = m.agreed_reject.saturating_add(1);
                } else {
                    m.kind_mismatch = m.kind_mismatch.saturating_add(1);
                    mismatched.push(format!(
                        "{name}: reference says {expected}, port says {} ({})",
                        e.kind.as_str(),
                        e.message
                    ));
                }
            }
            (true, Ok(_)) => {
                m.rust_only_accept = m.rust_only_accept.saturating_add(1);
                permissive.push(name.to_owned());
            }
            (false, Err(e)) => {
                m.rust_only_reject = m.rust_only_reject.saturating_add(1);
                over_strict.push(format!("{name}: {}", e.message));
            }
        }
    }

    // One assertion covering all three failure rows, not three sequential ones.
    // Sequential asserts report only the first non-empty row, so a census that
    // opens 58 permissive cases and 9 category mismatches at once looks like a
    // permissiveness problem alone — and the second round only becomes visible
    // after the first is fixed. Measuring the whole matrix in one pass is the
    // difference between one RED reading and a series of them.
    let rows = [
        (
            m.rust_only_accept,
            "CRITICAL permissiveness — the strict door is the gate over \
             untrusted extractor output, and these documents are refused by the \
             reference but analysed by the port",
            &permissive,
        ),
        (
            m.rust_only_reject,
            "over-strictness — not a hole, but facts the reference analyses \
             today would stop being analysable after cutover",
            &over_strict,
        ),
        (
            m.kind_mismatch,
            "category mismatch — both loaders reject, but disagree about WHY. \
             Accept/reject parity can be green while the taxonomy is \
             decorative; this is what stops that",
            &mismatched,
        ),
    ];
    let report = rows
        .iter()
        .filter(|(count, _, _)| *count > 0)
        .map(|(count, heading, names)| {
            format!("\n\n{heading} ({count}):\n  {}", names.join("\n  "))
        })
        .collect::<Vec<_>>()
        .concat();
    assert!(
        report.is_empty(),
        "the two loaders do not accept the same language.\nmatrix: {m:?}{report}"
    );
    assert_eq!(
        m.agreed_accept.saturating_add(m.agreed_reject),
        cases(&root).len(),
        "every control must land in an agreed row: {m:?}"
    );
}

#[test]
fn no_control_escapes_into_serde() {
    // The architecture's central claim is that `strict` decides accept/reject
    // and serde only CONSTRUCTS. That claim is falsifiable: if a document
    // survives validation and serde still refuses it, some rule lives in the
    // model instead of the validator — the category would be whatever serde
    // felt like, and the ordering contract would be bypassed entirely.
    //
    // `from_json` marks exactly that case, and this asserts no control reaches
    // it. Without this the design would degrade silently back into "serde is
    // the gate" one undeclared field at a time.
    let root = load();
    let mut escaped: Vec<String> = Vec::new();
    for case in cases(&root) {
        if let Err(e) = OwnIr::from_json(&document_text(case)) {
            if e.message.contains(own_ir::VALIDATOR_HOLE) {
                let name = case.get("name").and_then(Value::as_str).unwrap_or("?");
                escaped.push(format!("{name}: {}", e.message));
            }
        }
    }
    assert!(
        escaped.is_empty(),
        "the strict validator accepted documents serde then refused, so these \
         rules live in the MODEL rather than the validator — their category and \
         their ordering are both accidental:\n  {}",
        escaped.join("\n  ")
    );
}

#[test]
fn the_acceptance_controls_make_the_rejections_discriminating() {
    // A ledger of rejections alone would pass against a loader that refuses
    // everything. The valid twins are what give the rejections meaning, so the
    // count is asserted rather than assumed.
    let root = load();
    let accepted = cases(&root)
        .iter()
        .filter(|c| c.get("verdict").and_then(Value::as_str) == Some("accept"))
        .count();
    assert!(
        accepted >= 5,
        "only {accepted} acceptance control(s); the rejections are not \
         discriminating without valid twins"
    );
}

#[test]
fn every_declared_category_is_exercised_by_a_control() {
    // The taxonomy must not outgrow its evidence. A variant no control reaches
    // is a claim about the contract that nothing backs — which is exactly why
    // there is no `Reference` variant.
    let root = load();
    let declared = root
        .get("categories")
        .and_then(Value::as_object)
        .expect("'categories'");
    for name in declared.keys() {
        let used = cases(&root)
            .iter()
            .any(|c| c.get("category").and_then(Value::as_str) == Some(name.as_str()));
        assert!(
            used,
            "category {name:?} is declared but no control exercises it"
        );
    }
    // …and the port must be able to name every one of them.
    for kind in [
        OwnIrErrorKind::Json,
        OwnIrErrorKind::Version,
        OwnIrErrorKind::Shape,
        OwnIrErrorKind::Vocabulary,
        OwnIrErrorKind::Identity,
        OwnIrErrorKind::Location,
    ] {
        assert!(
            declared.contains_key(kind.as_str()),
            "the port has a kind {:?} the ledger does not declare",
            kind.as_str()
        );
    }
}

#[test]
fn malformed_input_never_panics() {
    // Facts are external input. #259 cp1 requires "no panic on malformed
    // JSON/OwnIR", so this feeds shapes no control covers — deep nesting, wrong
    // types at every level, and the empty document — and asserts only that the
    // loader RETURNS rather than unwinds.
    let hostile = [
        "",
        "   ",
        "null",
        "0",
        "[]",
        "{}",
        "{\"ownir_version\":}",
        "{\"components\":[{\"subscriptions\":[{\"column\":1e400}]}]}",
        "{\"services\":[[[[[]]]]]}",
        "{\"functions\":[{\"params\":[{\"name\":null}]}]}",
        "{\"protocols\":[null,null]}",
        "{\"ownir_version\":-9223372036854775808}",
    ];
    for text in hostile {
        // Panicking here fails the test by unwinding; the assertion is that we
        // reach this line at all for every input.
        let _ = OwnIr::from_json(text);
    }
}

#[test]
fn a_deep_in_memory_value_is_refused_rather_than_aborting() {
    // `serde_json::to_value` recurses over a `Value`. On a deep enough one it
    // does not return an error — it overflows the stack, which aborts the
    // process and cannot be caught. `from_json` was never exposed (the parser
    // caps nesting at 128); `validate()` is, because it serializes a value the
    // caller built in memory.
    //
    // Depth 200 is chosen deliberately: past the 128 guard, and well inside the
    // band where the value can still be built and dropped. See the honesty note
    // below for why it is not larger.
    let mut node = serde_json::json!({"ev": "return", "line": 1});
    for _ in 0..200 {
        node = serde_json::json!({"ev": "if", "line": 1, "then": [node]});
    }
    let doc = OwnIr {
        protocol_functions: Some(vec![serde_json::json!({"name": "M", "events": [node]})]),
        ..OwnIr::default()
    };

    let err = doc.validate().expect_err("a 200-deep tree must be refused");
    assert_eq!(err.kind, OwnIrErrorKind::Shape, "{}", err.message);
    assert!(
        err.message.contains("nested more than"),
        "expected the depth guard, got: {}",
        err.message
    );
    // …and `to_value` refuses it directly, since that is where the hazard is.
    // The guard lives there, NOT in the validator's own recursion: measured,
    // `to_value` and `validate` abort at the SAME depth, so a counter threaded
    // through `events`/`flow_columns` would never be the check that fires.
    assert!(doc.to_value().is_err(), "to_value must refuse it too");

    // HONESTY NOTE, measured rather than assumed: this guard covers depths 129
    // to roughly 800. Above ~804 merely DROPPING the value aborts, because
    // `serde_json::Value` has a recursive `Drop` — nothing this crate does can
    // prevent that, and a test asserting otherwise would abort before it could
    // report. The bound stops the serializer, not the type.
}

#[test]
fn the_depth_guard_never_fires_on_a_document_from_json_accepts() {
    // The guard is set to serde_json's own parse limit, so it must be
    // unreachable for anything that survived parsing — otherwise it is not a
    // stack-overflow bound, it is a new rejection rule with no counterpart in
    // the reference.
    //
    // The ledger alone cannot check this: every control is a handful of levels
    // deep, so a guard set to 16 would pass against all 191 of them. Measured —
    // that mutation SURVIVED until this document was added. So the test builds
    // the deepest document `from_json` still accepts and pins the guard above
    // it.
    let mut node = serde_json::json!({"ev": "return", "line": 1});
    for _ in 0..50 {
        node = serde_json::json!({"ev": "if", "line": 1, "then": [node]});
    }
    let deep = serde_json::json!({
        "ownir_version": 0,
        "protocol_functions": [{"name": "M", "events": [node]}]
    });
    let text = serde_json::to_string(&deep).expect("serializes");
    let doc = OwnIr::from_json(&text).expect(
        "a 50-level protocol tree is within serde_json's parse limit and the \
         reference accepts it",
    );
    assert!(
        doc.to_value().is_ok(),
        "the depth guard refused a document the strict door accepted — it is \
         tighter than the parser, which makes it a rejection rule rather than \
         an overflow bound"
    );

    // …and every ledger control, for the same reason at ordinary depths.
    let root = load();
    for case in cases(&root) {
        if let Ok(doc) = OwnIr::from_json(&document_text(case)) {
            let name = case.get("name").and_then(Value::as_str).unwrap_or("?");
            assert!(doc.to_value().is_ok(), "{name}: refused by the depth guard");
        }
    }
}
