//! The obligation-protocol **acceptance grammar** (P-025), ported from the
//! shared parser in `ownlang/obligations.py`.
//!
//! # Why this lives in `own-ir` at all
//!
//! `load()` delegates every `protocols[]` and `protocol_functions[]` record to
//! that parser, and wraps its errors as `OwnIRError`. So the parser is part of
//! the strict-door contract even though it lives in another module: a document
//! the parser refuses is a document `load()` refuses. Leaving it out would not
//! be a smaller checkpoint, it would be a strict door with a hole in it — which
//! is what the second census measured, at 46 of 58 permissive cases.
//!
//! # What is ported, and what deliberately is not
//!
//! Ported: **acceptance only** — `parse_protocol`, `parse_matcher`,
//! `parse_events`, `parse_method`. These answer "is this a well-formed protocol
//! declaration / event tree?".
//!
//! Not ported: everything that *uses* the answer — the obligation lattice, the
//! walker, matching, `check_protocols`, verdicts. Those are analysis, they are
//! not part of what the door accepts, and they belong to a later checkpoint.
//!
//! Consequently these functions build no `Protocol` value for a caller to use.
//! They validate and return the record's identity, and `own-ir` keeps
//! `protocols` / `protocol_functions` as raw [`Value`]s. Parsing them into typed
//! Rust structures now would be inventing a representation before anything
//! consumes it.
//!
//! # Two rules that are not about types
//!
//! `parse_protocol` refuses a protocol that can never fire (no barriers with
//! `exit_barriers: false`) and one whose barrier equals its `opens` matcher (the
//! walk checks opens first, so the barrier is dead). Both are well-formedness,
//! not shape: every value in such a record has the right type. They are reported
//! as [`OwnIrErrorKind::Shape`] because the six-category taxonomy has no better
//! home, and that imprecision is written down in the ledger rather than
//! smoothed over.

// `unreachable_pub` (denied workspace-wide) and `redundant_pub_crate`
// disagree about a private module's cross-module helpers: the first
// rejects `pub`, the second flags `pub(crate)`. `pub(crate)` is the one
// that states the real visibility, so the other lint is silenced here
// rather than the module being made public to satisfy it.
#![allow(clippy::redundant_pub_crate)]

use std::collections::BTreeSet;

use serde_json::{Map, Value};

use crate::strict::{defaulted_int, name_slot, optional_string};
use crate::{OwnIrError, OwnIrErrorKind};

/// The closed event vocabulary of `protocol_functions[].events` — the `ev`
/// discriminator. Mirrors the flow-op rule (`OwnIR` §5): a present-but-unknown
/// value is rejected, never skipped.
const EVENT_KINDS: [&str; 6] = ["assign", "call", "if", "return", "throw", "while"];

/// Matcher vocabulary for `opens` / `closes` / `barriers` / `allow`.
const MATCHER_KINDS: [&str; 2] = ["assign", "call"];

fn shape(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Shape, message)
}

fn vocabulary(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Vocabulary, message)
}

/// One event pattern, in the only form this checkpoint needs: something that can
/// be compared. The `opens in barriers` rule is a value comparison in the
/// reference (a frozen dataclass), so equality here has to mean the same thing —
/// `args` is a set, not a list, because the reference stores a `frozenset`.
#[derive(Debug, PartialEq, Eq)]
struct MatcherSpec {
    kind: &'static str,
    /// assign: the member name; call: the callee name.
    target: String,
    /// assign only — `None` means "any written value".
    value: Option<bool>,
    /// call only — empty means "any argument".
    args: BTreeSet<String>,
}

/// Validate one `protocols[]` record and return the name it declares.
///
/// # Errors
/// [`OwnIrError`] on any shape, vocabulary or identity violation, in the
/// reference parser's order.
pub(crate) fn validate_protocol(raw: &Value) -> Result<&str, OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!("a protocol must be an object, got {raw}")));
    };
    let name = name_slot(obj, "name", "protocol")?;
    let what = format!("protocol '{name}'");

    // Presence is checked for BOTH before either is parsed, so a record missing
    // one reports the requirement rather than a matcher error for the other.
    if !obj.contains_key("opens") || !obj.contains_key("closes") {
        return Err(shape(format!(
            "{what}: 'opens' and 'closes' are both required"
        )));
    }
    // `require_value`: an opens/closes assign matcher must name the written
    // boolean — "any write opens" is not a checkable protocol.
    let opens = matcher(&obj["opens"], &format!("{what} 'opens'"), true)?;
    matcher(&obj["closes"], &format!("{what} 'closes'"), true)?;

    let barriers = matchers(obj, "barriers", &what)?;
    matchers(obj, "allow", &what)?;

    let exit_barriers = match obj.get("exit_barriers") {
        None => true,
        Some(Value::Bool(b)) => *b,
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'exit_barriers' must be a boolean, got {other}"
            )))
        }
    };
    if barriers.is_empty() && !exit_barriers {
        return Err(shape(format!(
            "{what}: no barriers and exit_barriers is false — the protocol can \
             never fire (a rule that structurally never fires is decoration)"
        )));
    }
    if barriers.contains(&opens) {
        return Err(shape(format!(
            "{what}: a barrier equals the 'opens' matcher — the open wins and \
             the barrier can never fire (re-entrancy checks are not supported yet)"
        )));
    }

    let scope: Option<&Map<String, Value>> = match obj.get("scope") {
        None => None,
        Some(Value::Object(m)) => Some(m),
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'scope' must be an object, got {other}"
            )))
        }
    };
    match scope.and_then(|s| s.get("methods")) {
        None => {}
        Some(Value::Array(methods)) => {
            for method in methods {
                // A scope entry is a method NAME the protocol is filtered by, so
                // an empty or mistyped one is an identity failure. The reference
                // raises one message for this and for a non-array `methods`; the
                // ledger separates them because a missing container and an
                // unusable name are different defects.
                if !method.as_str().is_some_and(|m| !m.is_empty()) {
                    return Err(OwnIrError::new(
                        OwnIrErrorKind::Identity,
                        format!("{what}: 'scope.methods' entries must be non-empty strings"),
                    ));
                }
            }
        }
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'scope.methods' must be an array of non-empty strings, got {other}"
            )))
        }
    }
    match obj.get("description") {
        None | Some(Value::String(_)) => {}
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'description' must be a string, got {other}"
            )))
        }
    }
    Ok(name)
}

/// `barriers` / `allow`: an array of matchers, each parsed without the
/// `require_value` rule that only `opens`/`closes` carry.
fn matchers(
    obj: &Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<Vec<MatcherSpec>, OwnIrError> {
    let Some(v) = obj.get(key) else {
        return Ok(Vec::new());
    };
    let Some(items) = v.as_array() else {
        return Err(shape(format!("{what}: '{key}' must be an array, got {v}")));
    };
    items
        .iter()
        .map(|m| matcher(m, &format!("{what} {key}"), false))
        .collect()
}

/// One matcher object.
fn matcher(raw: &Value, what: &str, require_value: bool) -> Result<MatcherSpec, OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!("{what} must be an object, got {raw}")));
    };
    let kind = obj.get("kind").and_then(Value::as_str);
    let Some(kind) = kind.filter(|k| MATCHER_KINDS.contains(k)) else {
        let got = obj.get("kind").unwrap_or(&Value::Null);
        return Err(vocabulary(format!(
            "{what}: unknown matcher kind {got} — the vocabulary is {MATCHER_KINDS:?}"
        )));
    };
    if kind == "assign" {
        let target = name_slot(obj, "target", what)?.to_owned();
        let value = match obj.get("value") {
            None | Some(Value::Null) => None,
            Some(Value::Bool(b)) => Some(*b),
            Some(other) => {
                return Err(shape(format!(
                    "{what}: assign 'value' must be a boolean, got {other}"
                )))
            }
        };
        if require_value && value.is_none() {
            return Err(shape(format!(
                "{what}: an opens/closes assign matcher must state the written \
                 boolean 'value' — 'any write' cannot open or close an obligation"
            )));
        }
        return Ok(MatcherSpec {
            kind: "assign",
            target,
            value,
            args: BTreeSet::new(),
        });
    }
    let callee = name_slot(obj, "callee", what)?.to_owned();
    let args = match obj.get("args") {
        None => BTreeSet::new(),
        Some(Value::Array(items)) if items.iter().all(Value::is_string) => items
            .iter()
            .filter_map(Value::as_str)
            .map(ToOwned::to_owned)
            .collect(),
        Some(_) => {
            return Err(shape(format!(
                "{what}: call 'args' must be an array of strings"
            )))
        }
    };
    Ok(MatcherSpec {
        kind: "call",
        target: callee,
        value: None,
        args,
    })
}

/// Validate one `protocol_functions[]` record.
///
/// # Errors
/// [`OwnIrError`] on any violation in the record or its event tree.
pub(crate) fn validate_method(raw: &Value) -> Result<(), OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!(
            "a protocol function must be an object, got {raw}"
        )));
    };
    let name = name_slot(obj, "name", "protocol function")?;
    let what = format!("protocol function '{name}'");
    match obj.get("file") {
        None | Some(Value::String(_)) => {}
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'file' must be a string, got {other}"
            )))
        }
    }
    events(obj.get("events"), &what)
}

/// An ordered event list, recursive over `if` / `while`.
///
/// Absent means empty; a present `null` is not a list and is rejected. Recursion
/// is bounded by `serde_json`'s 128-level parse limit.
fn events(raw: Option<&Value>, what: &str) -> Result<(), OwnIrError> {
    let items: &[Value] = match raw {
        None => &[],
        Some(Value::Array(items)) => items,
        Some(other) => {
            return Err(shape(format!(
                "{what}: events must be an array, got {other}"
            )))
        }
    };
    for event in items {
        let Some(obj) = event.as_object() else {
            return Err(shape(format!(
                "{what}: each event must be an object, got {event}"
            )));
        };
        let kind = obj.get("ev").and_then(Value::as_str);
        let Some(kind) = kind.filter(|k| EVENT_KINDS.contains(k)) else {
            let got = obj.get("ev").unwrap_or(&Value::Null);
            return Err(vocabulary(format!(
                "{what}: unknown protocol event {got} — the vocabulary is {EVENT_KINDS:?}"
            )));
        };
        // The line is checked for every kind, before the per-kind fields.
        defaulted_int(obj, "line", what)?;
        match kind {
            "assign" => {
                name_slot(obj, "target", &format!("{what} assign"))?;
                match obj.get("value") {
                    None | Some(Value::Null | Value::Bool(_)) => {}
                    Some(other) => {
                        return Err(shape(format!(
                            "{what}: assign 'value' must be a boolean or absent \
                             (absent = opaque write), got {other}"
                        )))
                    }
                }
            }
            "call" => {
                name_slot(obj, "callee", &format!("{what} call"))?;
                optional_string(obj, "arg", what)?;
            }
            "if" => {
                events(obj.get("then"), what)?;
                events(obj.get("else"), what)?;
            }
            "while" => events(obj.get("body"), what)?,
            // "return" / "throw" carry only the line, already checked.
            _ => {}
        }
    }
    Ok(())
}
