//! The BR-D1 strict door, as a sequential validator over the **raw** document.
//!
//! # Why this is not `serde`
//!
//! The obvious Rust design is to let `Deserialize` be the gate: declare the
//! model precisely and let a failed deserialization mean "rejected". That was
//! the previous design here, and it is wrong for this door in two ways that
//! only a differential census makes visible.
//!
//! **It cannot answer *why*.** A `lifetime` enum rejects `"eternal"` perfectly
//! well — and reports it as [`OwnIrErrorKind::Shape`], when the contract
//! violated is a closed vocabulary. A `NonZeroU32` column rejects `0` and calls
//! that a type error, when it is the 1-based coordinate rule. #259 asks for a
//! matching error *class*, so the implementation mechanism must not be what
//! picks the semantic category.
//!
//! **It cannot answer *which first*.** BR-D1 fixes the order of checks, and the
//! spec notes the order "is observable through which error fires first". serde
//! visits fields in the order the *struct* declares and containers depth-first;
//! the reference visits sections in document-declaration order and, within a
//! section, interleaves shape and semantic checks per record. A document that
//! breaks a `components` shape rule and a `services` vocabulary rule has one
//! correct answer, and it is the components one.
//!
//! An earlier attempt kept serde and hoisted the semantic checks in front of it
//! — version gate, then every vocabulary/identity/location rule, then
//! deserialize. That passes section-local controls and fails every cross-section
//! ordering control, because "all semantics, then all shapes" is a third order
//! that matches neither implementation. There is no arrangement of two passes
//! that reproduces one interleaved pass; the interleaving has to be the code.
//!
//! # What serde is for now
//!
//! Construction. By the time [`crate::OwnIr::from_json`] deserializes, this
//! module has already accepted the document, so a `serde` failure afterwards is
//! not a rejection — it is a **hole in this validator**, reported as such and
//! asserted against by the replay test.
//!
//! # Shape of the port
//!
//! Not 47 transcribed `if`s: a handful of primitives that each encode one of
//! Python's access idioms, and one function per section that applies them in
//! the reference's order.
//!
//! | primitive | Python idiom |
//! |---|---|
//! | [`objects`] | `x = d.get(k, []); isinstance(x, list) and all(isinstance(i, dict))` |
//! | [`name_slot`] | `isinstance(v, str) and v` — a value other facts join on |
//! | [`optional_string`] | `v is not None and not isinstance(v, str)` — null tolerated |
//! | [`defaulted_string`] | `isinstance(d.get(k, "?"), str)` — null rejected |
//! | [`defaulted_int`] | `isinstance(x, int) and not isinstance(x, bool)` |
//! | [`string_array`] | `isinstance(x, list) and all(isinstance(i, str))` |
//! | [`column`] | `_check_column` — the 1-based contract (#317) |
//! | [`sites`] | the `{type, file, line}` call-site record |
//!
//! The distinction between the two string primitives is the one place a single
//! "policy for optional fields" would silently be wrong: `resource` rejects an
//! explicit `null` and `source_provenance` accepts it, because the reference
//! writes one as `isinstance(...)` on a defaulted read and the other as `is not
//! None and ...`. They shared a bug once; they do not share a contract.

// `unreachable_pub` (denied workspace-wide) and `redundant_pub_crate`
// disagree about a private module's cross-module helpers: the first
// rejects `pub`, the second flags `pub(crate)`. `pub(crate)` is the one
// that states the real visibility, so the other lint is silenced here
// rather than the module being made public to satisfy it.
#![allow(clippy::redundant_pub_crate)]

use serde_json::{Map, Value};

use crate::{OwnIrError, OwnIrErrorKind, KNOWN_RESOURCE_KINDS};

type Checked = Result<(), OwnIrError>;

const LIFETIMES: [&str; 3] = ["scoped", "singleton", "transient"];
const PARAM_EFFECTS: [&str; 4] = ["borrow", "borrow_mut", "consume", "plain"];

fn shape(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Shape, message)
}

fn identity(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Identity, message)
}

fn vocabulary(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Vocabulary, message)
}

/// Is this an integer in Python's sense — `int` and not `bool`?
///
/// `true` is called out rather than folded in with other non-numbers: it is the
/// trap the reference guards explicitly, because a Python `bool` *is* an `int`
/// and `True` would otherwise read as `1`.
fn is_integer(v: &Value) -> bool {
    match v {
        Value::Number(n) => n.is_i64() || n.is_u64(),
        _ => false,
    }
}

/// `d.get(key, [])` read as a list of objects. Absent is empty; a present
/// `null` is **not** absent and is rejected, exactly as `isinstance(None, list)`
/// fails in the reference.
fn objects<'a>(
    obj: &'a Map<String, Value>,
    key: &str,
    message: &str,
) -> Result<Vec<&'a Map<String, Value>>, OwnIrError> {
    let Some(v) = obj.get(key) else {
        return Ok(Vec::new());
    };
    let Some(items) = v.as_array() else {
        return Err(shape(message.to_owned()));
    };
    items
        .iter()
        .map(|i| i.as_object().ok_or_else(|| shape(message.to_owned())))
        .collect()
}

/// `d.get(key, [])` read as a bare list — the element type is somebody else's
/// contract. `protocols` and `protocol_functions` are checked this way, because
/// the reference delegates each record to the shared obligation parser.
fn list<'a>(
    obj: &'a Map<String, Value>,
    key: &str,
    message: &str,
) -> Result<&'a [Value], OwnIrError> {
    match obj.get(key) {
        None => Ok(&[]),
        Some(Value::Array(items)) => Ok(items),
        Some(_) => Err(shape(message.to_owned())),
    }
}

/// A **name slot**: a value some other fact joins on. Absent, `null`, empty or
/// non-string are one defect — the name cannot be used to join — and all report
/// [`OwnIrErrorKind::Identity`].
pub(crate) fn name_slot<'a>(
    obj: &'a Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<&'a str, OwnIrError> {
    match obj.get(key) {
        Some(Value::String(s)) if !s.is_empty() => Ok(s),
        _ => Err(identity(format!(
            "{what}: '{key}' must be a non-empty string"
        ))),
    }
}

/// `v = d.get(key); if v is not None and not isinstance(v, str)` — absent *and*
/// an explicit `null` both pass.
pub(crate) fn optional_string(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    match obj.get(key) {
        None | Some(Value::Null | Value::String(_)) => Ok(()),
        Some(other) => Err(shape(format!(
            "{what} '{key}' must be a string, got {other}"
        ))),
    }
}

/// `isinstance(d.get(key, "?"), str)` — absent passes on the default, a present
/// `null` does not.
fn defaulted_string(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    match obj.get(key) {
        None | Some(Value::String(_)) => Ok(()),
        Some(other) => Err(shape(format!(
            "{what} '{key}' must be a string, got {other}"
        ))),
    }
}

/// `x = d.get(key, 0); isinstance(x, int) and not isinstance(x, bool)`.
pub(crate) fn defaulted_int(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    match obj.get(key) {
        None => Ok(()),
        Some(v) if is_integer(v) => Ok(()),
        Some(other) => Err(shape(format!(
            "{what} '{key}' must be an integer, got {other}"
        ))),
    }
}

/// `isinstance(x, list) and all(isinstance(i, str) for i in x)`.
fn string_array(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    let Some(v) = obj.get(key) else {
        return Ok(());
    };
    let ok = v
        .as_array()
        .is_some_and(|items| items.iter().all(Value::is_string));
    if ok {
        Ok(())
    } else {
        Err(shape(format!("{what} '{key}' must be an array of strings")))
    }
}

/// The 1-based source-column contract (#317).
///
/// A column is a positive integer or it is absent — and, unlike a `line`, an
/// explicit `null` **is** accepted, because the reference returns early on
/// `None`. `0` is rejected rather than read as "unknown": SARIF columns start at
/// 1, so a `0` is a producer bug, and silently treating it as absent would hide
/// the bug while looking correct.
fn column(value: Option<&Value>, what: &str) -> Checked {
    let Some(v) = value else { return Ok(()) };
    if v.is_null() {
        return Ok(());
    }
    let ok = is_integer(v) && v.as_i64().is_some_and(|i| i >= 1);
    if ok {
        return Ok(());
    }
    Err(OwnIrError::new(
        OwnIrErrorKind::Location,
        format!("{what} 'column' must be a 1-based integer or absent, got {v}"),
    ))
}

/// `column` on every flow op, recursing through `then` / `else` / `body`.
///
/// A non-list body is **skipped**, not rejected, and so is a non-object op: the
/// reference returns early in both cases. Tightening that would be a
/// Rust-only rejection of facts that analyse today.
///
/// Recursion is bounded by `serde_json`'s own 128-level parse limit — a document
/// deep enough to exhaust the stack here never becomes a [`Value`] in the first
/// place.
fn flow_columns(nodes: Option<&Value>, what: &str) -> Checked {
    let Some(Value::Array(items)) = nodes else {
        return Ok(());
    };
    for node in items {
        let Some(op) = node.as_object() else { continue };
        let label = op
            .get("op")
            .map_or_else(|| format!("{what} op"), |name| format!("{what} op {name}"));
        column(op.get("column"), &label)?;
        for key in ["then", "else", "body"] {
            flow_columns(op.get(key), what)?;
        }
    }
    Ok(())
}

/// An array of `{type, file, line}` call-site records (DI004 / DI005). Every
/// field is defaulted, so `{}` is a legal site; the reference folds the whole
/// check into one `all(...)`, so any violation is one shape failure.
fn sites(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    let Some(v) = obj.get(key) else {
        return Ok(());
    };
    let ok = v.as_array().is_some_and(|items| {
        items.iter().all(|s| {
            s.as_object().is_some_and(|site| {
                matches!(site.get("type"), None | Some(Value::String(_)))
                    && matches!(site.get("file"), None | Some(Value::String(_)))
                    && site.get("line").map_or(true, is_integer)
            })
        })
    });
    if ok {
        Ok(())
    } else {
        Err(shape(format!(
            "{what} '{key}' must be an array of {{type:str, file:str, line:int}} objects"
        )))
    }
}

/// Run the whole strict door, in the reference's order.
///
/// Sections are visited in declaration order and each is finished before the
/// next begins — that is the property the cross-section ordering controls pin.
pub(crate) fn validate_document(obj: &Map<String, Value>) -> Checked {
    version(obj)?;
    components(obj)?;
    services(obj)?;
    effects(obj)?;
    functions(obj)?;
    protocols(obj)?;
    protocol_functions(obj)
}

/// The version gate, first: a vocabulary mismatch makes every later shape check
/// meaningless. An absent field means the current version — the only producers
/// that omit it predate versioning.
fn version(obj: &Map<String, Value>) -> Checked {
    let Some(v) = obj.get("ownir_version") else {
        return Ok(());
    };
    let ver = if is_integer(v) { v.as_i64() } else { None };
    let Some(ver) = ver else {
        return Err(OwnIrError::new(
            OwnIrErrorKind::Version,
            format!("OwnIR 'ownir_version' must be an integer, got {v}"),
        ));
    };
    if ver != crate::OWNIR_VERSION {
        return Err(OwnIrError::new(
            OwnIrErrorKind::Version,
            format!(
                "OwnIR facts are schema v{ver}, but this core understands \
                 v{}. Build the extractor and the core from the same commit — \
                 the OwnIR fact vocabulary changed between the version that \
                 produced this file and the one reading it.",
                crate::OWNIR_VERSION
            ),
        ));
    }
    Ok(())
}

fn components(obj: &Map<String, Value>) -> Checked {
    let comps = objects(
        obj,
        "components",
        "OwnIR 'components' must be a JSON array of objects",
    )?;
    for component in comps {
        let subs = objects(
            component,
            "subscriptions",
            "each component's 'subscriptions' must be objects",
        )?;
        for sub in subs {
            // Shape before vocabulary: `resource` must BE a string before its
            // value can be tested against the closed set. An absent field
            // defaults to "subscription", which is known; a present `null` is
            // not a string and fails here.
            match sub.get("resource") {
                None | Some(Value::String(_)) => {}
                Some(other) => {
                    return Err(shape(format!(
                        "subscription 'resource' must be a string, got {other}"
                    )))
                }
            }
            // IR4: a present-but-unknown kind changes routing, so the strict
            // door rejects it rather than let it mis-route. The lowering door
            // keeps its own copy of this rule (#294 OD-2) for callers that
            // bypass this loader entirely — two doors, not one duplicated check.
            if let Some(kind) = sub.get("resource").and_then(Value::as_str) {
                if !KNOWN_RESOURCE_KINDS.contains(&kind) {
                    return Err(vocabulary(format!(
                        "unknown resource kind {kind:?} — a new kind is a \
                         vocabulary change that must bump OWNIR_VERSION"
                    )));
                }
            }
            column(sub.get("column"), "subscription")?;
            optional_string(sub, "type", "subscription")?;
            optional_string(sub, "source_type", "subscription")?;
            optional_string(sub, "source_provenance", "subscription")?;
            optional_string(sub, "ignore_reason", "subscription")?;
        }
    }
    Ok(())
}

fn services(obj: &Map<String, Value>) -> Checked {
    let svcs = objects(
        obj,
        "services",
        "OwnIR 'services' must be a JSON array of objects",
    )?;
    for svc in svcs {
        // Lifetime BEFORE name — the reference's order, and observable: a
        // record breaking both is a vocabulary failure, not an identity one.
        // There is no default, so an absent lifetime is `None`, which is
        // outside the closed set exactly like a misspelt one.
        let known = svc
            .get("lifetime")
            .and_then(Value::as_str)
            .is_some_and(|l| LIFETIMES.contains(&l));
        if !known {
            let got = svc.get("lifetime").unwrap_or(&Value::Null);
            return Err(vocabulary(format!(
                "service 'lifetime' must be one of {LIFETIMES:?}, got {got}"
            )));
        }
        name_slot(svc, "name", "service")?;
        string_array(svc, "deps", "service")?;
        string_array(svc, "weak_deps", "service")?;
        string_array(svc, "root_resolves", "service")?;
        defaulted_string(svc, "file", "service")?;
        defaulted_int(svc, "line", "service")?;
        defaulted_string(svc, "ctor_file", "service")?;
        defaulted_int(svc, "ctor_line", "service")?;
        defaulted_string(svc, "ctor_type", "service")?;
        sites(svc, "root_resolve_sites", "service")?;
        string_array(svc, "scope_cached", "service")?;
        sites(svc, "scope_cache_sites", "service")?;
    }
    Ok(())
}

fn effects(obj: &Map<String, Value>) -> Checked {
    let effs = objects(
        obj,
        "effects",
        "OwnIR 'effects' must be a JSON array of objects",
    )?;
    for eff in effs {
        string_array(eff, "deps", "effect")?;
        match eff.get("io") {
            None | Some(Value::Bool(_)) => {}
            Some(other) => {
                return Err(shape(format!("effect 'io' must be a boolean, got {other}")))
            }
        }
        defaulted_int(eff, "line", "effect")?;
        let binds = objects(
            eff,
            "bindings",
            "effect 'bindings' must be a JSON array of objects",
        )?;
        for binding in binds {
            defaulted_string(binding, "name", "binding")?;
            defaulted_string(binding, "init", "binding")?;
            string_array(binding, "refs", "binding")?;
            defaulted_int(binding, "line", "binding")?;
        }
    }
    Ok(())
}

fn functions(obj: &Map<String, Value>) -> Checked {
    let fns = objects(
        obj,
        "functions",
        "OwnIR 'functions' must be a JSON array of objects",
    )?;
    for function in fns {
        optional_string(function, "sig", "function")?;
        // The BODY's columns precede `params` — the least obvious edge in the
        // door, because params read like the more primitive thing.
        flow_columns(function.get("body"), "function body")?;
        let params = objects(
            function,
            "params",
            "a function's 'params' must be a JSON array of objects",
        )?;
        for param in params {
            name_slot(param, "name", "parameter")?;
            defaulted_int(param, "line", "parameter")?;
            column(param.get("column"), "parameter")?;
            match param.get("effect") {
                None | Some(Value::Null) => {}
                Some(v) if v.as_str().is_some_and(|e| PARAM_EFFECTS.contains(&e)) => {}
                Some(other) => {
                    return Err(vocabulary(format!(
                        "parameter 'effect' must be one of {PARAM_EFFECTS:?}, got {other}"
                    )))
                }
            }
        }
    }
    Ok(())
}

/// `protocols[]` — record grammar from the shared parser, then the identity
/// invariant two individually valid records can only violate together.
fn protocols(obj: &Map<String, Value>) -> Checked {
    let protos = list(
        obj,
        "protocols",
        "OwnIR 'protocols' must be a JSON array of objects",
    )?;
    let mut seen: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
    for raw in protos {
        let name = crate::protocol::validate_protocol(raw)?;
        // The name is the identity the bridge maps verdicts back by (IR5); two
        // protocols sharing one would make that mapping ambiguous and can
        // collapse distinct findings in the dedup.
        if !seen.insert(name) {
            return Err(identity(format!(
                "duplicate protocol name '{name}' — protocol names are the \
                 identity findings map back by and must be unique"
            )));
        }
    }
    Ok(())
}

fn protocol_functions(obj: &Map<String, Value>) -> Checked {
    let pfns = list(
        obj,
        "protocol_functions",
        "OwnIR 'protocol_functions' must be a JSON array of objects",
    )?;
    for raw in pfns {
        crate::protocol::validate_method(raw)?;
    }
    Ok(())
}
