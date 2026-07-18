//! Negative model tests: the typed surface must reject impossible documents
//! and preserve presence semantics — `deny_unknown_fields` alone is strict
//! about surplus keys but says nothing about impossible VALUES, and the
//! Python emitter distinguishes a MISSING handle key from an explicit `null`
//! (`{k: rec[k] for k in _HANDLE_KEYS if k in rec}` — membership, not truth).
//!
//! Pinned here (#300 review):
//! * `lowered_version` is enforced on every parsed surface, accepted and
//!   rejected alike — not just on the manifest;
//! * a parameter's `type` is non-nullable (`Param.type: TypeRef` in the
//!   Python AST — the emitter always writes an object);
//! * the schema-nullable handle keys (`type`, `source`, `source_type`) keep
//!   explicit `null` through a parse→emit round trip;
//! * a non-nullable optional handle key with an explicit `null` is rejected,
//!   never silently deleted.

#![allow(clippy::panic, clippy::expect_used)]

use own_lowered::{parse_document, to_canonical_json};

/// A minimal full document; `handles` is spliced in so each test controls
/// exactly the entries under scrutiny.
fn doc(version: u32, handles: &str) -> String {
    format!(
        r#"{{
  "lowered_version": {version},
  "module": "m",
  "resources": [],
  "externs": [],
  "lifetimes": [],
  "functions": [],
  "handles": {handles}
}}"#
    )
}

#[test]
fn rejects_wrong_version_on_a_lowered_document() {
    let err = parse_document(&doc(99, "[]"))
        .expect_err("lowered_version 99 must not parse — the crate docs promise lockstep");
    assert!(
        err.to_string().contains("lowered_version"),
        "the rejection must name the version field, got: {err}"
    );
}

#[test]
fn rejects_wrong_version_on_a_rejection_document() {
    let err = parse_document(r#"{"lowered_version": 99, "error": "boom"}"#)
        .expect_err("a rejection surface with lowered_version 99 must not parse");
    assert!(
        err.to_string().contains("lowered_version"),
        "the rejection must name the version field, got: {err}"
    );
}

#[test]
fn accepts_the_current_version_on_a_rejection_document() {
    let text = "{\n  \"lowered_version\": 1,\n  \"error\": \"boom\"\n}\n";
    let surface = parse_document(text).expect("a current-version rejection parses");
    let emitted = to_canonical_json(&surface).expect("canonical emit");
    assert_eq!(
        emitted, text,
        "rejection surface must round-trip byte-exactly"
    );
}

#[test]
fn rejects_a_null_parameter_type() {
    // Python's `Param.type: TypeRef` is not `TypeRef | None`; the emitter can
    // never write `"type": null` on a parameter, so the typed model must not
    // accept it either.
    let text = r#"{
  "lowered_version": 1,
  "module": "m",
  "resources": [],
  "externs": [],
  "lifetimes": [],
  "functions": [
    {
      "name": "f",
      "lifetime": null,
      "params": [
        {
          "handle": "parg_0",
          "type": null,
          "line": 1,
          "lifetime": null
        }
      ],
      "ret": null,
      "body": []
    }
  ],
  "handles": []
}"#;
    parse_document(text)
        .expect_err("a parameter with \"type\": null is a shape Python cannot produce");
}

#[test]
fn rejects_explicit_null_on_a_non_nullable_handle_key() {
    // `released` is optional-but-boolean on the record; an explicit null must
    // fail the parse, not decay to "missing" and vanish on re-emit.
    let text = doc(1, r#"[{"handle": "sub_0", "released": null}]"#);
    parse_document(&text).expect_err("\"released\": null must be rejected, not deleted");
}

#[test]
fn preserves_explicit_null_metadata_through_a_round_trip() {
    // The strict OwnIR schema accepts (and the emitter preserves, by key
    // membership) explicit `null` for `type`, `source`, and `source_type` —
    // `{}` and `{"source_type": null}` are DIFFERENT Layer 2 documents.
    let text = doc(
        1,
        r#"[
    {
      "handle": "sub_0",
      "source": null,
      "source_type": null,
      "type": null
    },
    {
      "handle": "sub_1"
    }
  ]"#,
    );
    let surface = parse_document(&text).expect("explicit-null metadata parses");
    let emitted = to_canonical_json(&surface).expect("canonical emit");
    for key in ["source", "source_type", "type"] {
        assert_eq!(
            emitted.matches(&format!("\"{key}\": null")).count(),
            1,
            "explicit \"{key}\": null must survive the round trip exactly once \
             (present on sub_0, absent on sub_1); emitted:\n{emitted}"
        );
    }
}
