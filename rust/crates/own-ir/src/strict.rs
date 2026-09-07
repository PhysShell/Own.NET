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
//! | [`defaulted_line`] | `isinstance(x, int) and not isinstance(x, bool)`, plus the §4.2 form and domain |
//! | [`string_array`] | `isinstance(x, list) and all(isinstance(i, str))` |
//! | [`column`] | `_check_column` — representability, the 1-based rule (#317), the domain |
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

fn location(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Location, message)
}

/// The source-coordinate DOMAIN (`spec/OwnIR.md` §4.2) — the inner of the two
/// axes, and a different rule from [`is_representable_int`] above.
///
/// `int32` is the line type of every consumer this project feeds (Roslyn's
/// `LinePosition.Line`, LSP's `uinteger`, .NET diagnostics), so a line wider
/// than this cannot reach the place it points at whatever it can be stored in.
/// `0` is legal and means "unknown / file-level" — the reference's own default
/// for an absent line. A column starts one higher because it is 1-based (§4.1).
pub(crate) const LINE_MIN: i64 = 0;
pub(crate) const LINE_MAX: i64 = 2_147_483_647;
pub(crate) const COLUMN_MIN: i64 = 1;
pub(crate) const COLUMN_MAX: i64 = 2_147_483_647;

/// Is this line inside the domain? Shared with the protocol grammar, which
/// answers the same question under whichever door it was called from.
pub(crate) const fn in_line_domain(value: i64) -> bool {
    LINE_MIN <= value && value <= LINE_MAX
}

/// The domain rule for a line that already HAS a representable form.
///
/// It answers [`OwnIrErrorKind::Location`], never `Shape`, and that is the
/// whole point of the two axes being two functions: `i64::MAX` is a
/// representable coordinate violating the rule about what a coordinate may
/// mean, while `i64::MAX + 1` is not a coordinate at all. The cp1 ledger
/// classifies by mechanism, so a single predicate over both would report one
/// of them under the other's category — the defect #326's census found in
/// `column` and this change would otherwise have re-introduced in `line`.
pub(crate) fn line_domain(value: i64, what: &str, key: &str) -> Checked {
    if in_line_domain(value) {
        return Ok(());
    }
    Err(location(format!(
        "{what} '{key}' must be a source line in [{LINE_MIN}, {LINE_MAX}], \
         got {value} (spec/OwnIR.md §4.2)"
    )))
}

/// Is this a **representable** `OwnIR` integer — `int`, not `bool`, and inside
/// the signed-64 range the contract declares (`spec/OwnIR.md` §4.2)?
///
/// `true` is called out rather than folded in with other non-numbers: it is the
/// trap the reference guards explicitly, because a Python `bool` *is* an `int`
/// and `True` would otherwise read as `1`.
///
/// The range belongs here rather than in each caller because representability
/// is one contract rule, and a predicate that answered the weaker question
/// "is this an integer *at all*" is what let `i64::MAX + 1` through the door
/// and into serde. Measured before the fix: eight `line` paths reported the
/// validator-hole sentinel, because the raw layer said yes and the typed model
/// then said no.
///
/// `is_i64()` is exactly the contract's range, so this is not an extra check
/// bolted beside the type check — it *is* the type check, stated at the width
/// `OwnIR` actually has. Note the two routes it has to cover: `i64::MAX + 1`
/// arrives as a `u64` and is still integer-shaped, while anything outside
/// `i64::MIN ..= u64::MAX` has already been flattened to `f64` by the parser.
/// Both answer `false` here, which is why the category cannot depend on which
/// route a value took.
fn is_representable_int(v: &Value) -> bool {
    match v {
        Value::Number(n) => n.is_i64(),
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

/// A validated source LINE: `x = d.get(key, 0)`, an integer and not a `bool`,
/// within the representable range — see [`is_representable_int`], which carries
/// both halves so no call site can get one without the other — and then within
/// the coordinate domain ([`line_domain`]).
///
/// Named for the field rather than for the type since #259's final acceptance:
/// every call site reads a `line` or a `ctor_line`, and the domain rule it now
/// applies is a rule about coordinates, not about integers.
pub(crate) fn defaulted_line(obj: &Map<String, Value>, key: &str, what: &str) -> Checked {
    let value = defaulted_int_value(obj, key, what)?;
    line_domain(value, what, key)
}

/// [`defaulted_int`], keeping the value it validated.
///
/// The protocol grammar needs the number it just checked (an event's `line`
/// travels to a finding's anchor), and everything else needs only the verdict.
/// One implementation with two returns, rather than a second reader of the same
/// slot that could disagree about the default or the domain.
pub(crate) fn defaulted_int_value(
    obj: &Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<i64, OwnIrError> {
    match obj.get(key) {
        None => Ok(0),
        Some(v) if is_representable_int(v) => Ok(v.as_i64().unwrap_or(0)),
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

/// The 1-based source-column contract (#317), in **two** rules on two axes.
///
/// A column is a positive integer or it is absent — and, unlike a `line`, an
/// explicit `null` **is** accepted, because the reference returns early on
/// `None`. `0` is rejected rather than read as "unknown": SARIF columns start at
/// 1, so a `0` is a producer bug, and silently treating it as absent would hide
/// the bug while looking correct.
///
/// The two rules are deliberately not one predicate. `column` is the only field
/// carrying both axes, which makes it the place they were conflated: a single
/// `is_integer(v) && v >= 1` reported a bool, a string, a float and an
/// out-of-range integer as [`OwnIrErrorKind::Location`] — a "1-based contract
/// violation" for values that have no integer form for the 1-based rule to be
/// about.
///
/// The conflation was inherited rather than invented. The reference raises one
/// message for all of them, so the ledger read the category off the diagnostic
/// instead of off the mechanism, and recorded a float column as `Location` next
/// to a float line as `Shape`. Representability is checked first and answers
/// [`OwnIrErrorKind::Shape`]; only a value that HAS a representable form can go
/// on to violate a rule about what that form means.
fn column(value: Option<&Value>, what: &str) -> Checked {
    let Some(v) = value else { return Ok(()) };
    if v.is_null() {
        return Ok(());
    }
    if !is_representable_int(v) {
        return Err(shape(format!(
            "{what} 'column' must be an integer within the representable \
             range, got {v}"
        )));
    }
    let n = v.as_i64().unwrap_or(0);
    if n < COLUMN_MIN {
        return Err(location(format!(
            "{what} 'column' must be a 1-based integer or absent, got {v}"
        )));
    }
    // …and the same domain a line carries (§4.2). Both bounds answer
    // `Location`, because both are rules about what a representable
    // coordinate may MEAN — the 1-based rule at the bottom and the int32
    // consumer domain at the top are one axis, not two.
    if n > COLUMN_MAX {
        return Err(location(format!(
            "{what} 'column' must be a source column in \
             [{COLUMN_MIN}, {COLUMN_MAX}], got {v} (spec/OwnIR.md §4.2)"
        )));
    }
    Ok(())
}

/// `line` and `column` on every flow op, recursing through `then`/`else`/`body`.
///
/// The line joined the column here in #259's final acceptance: §4.2 used to
/// record a flow op's `line` as validated NOWHERE — not for range, not even
/// for type — on both sides, and answered the contract question it left open
/// with "yes, a coordinate no rule reads must still be well-formed", because
/// the TOLERANT door reads it and anchors findings on it. Line before column,
/// the record's own order and §4.1's: they are the same node's coordinate.
///
/// A non-list body is **skipped**, not rejected, and so is a non-object op: the
/// reference returns early in both cases. Tightening that would be a
/// Rust-only rejection of facts that analyse today.
///
/// Recursion here is bounded for a **parsed** document: `serde_json` caps
/// nesting at 128 levels, so a body deep enough to exhaust the stack never
/// becomes a [`Value`]. A value built **in memory** has no such bound, which is
/// why [`crate::OwnIr::to_value`] depth-checks before serializing — and why
/// that check is iterative.
fn flow_coordinates(nodes: Option<&Value>, what: &str, depth: usize) -> Checked {
    // The early return comes FIRST, and that order is measured rather than
    // reasoned. Every op is probed for `then`/`else`/`body` whether or not it
    // has them, so a depth check placed before this one counts the absent
    // bodies and rejects a body at exactly the limit. The reference had the
    // same off-by-one, and only the at-limit case caught it. Only a list that
    // actually exists is a level.
    let Some(Value::Array(items)) = nodes else {
        return Ok(());
    };
    if depth > MAX_NESTING_DEPTH {
        return Err(shape(format!(
            "{what} nested deeper than {MAX_NESTING_DEPTH} levels"
        )));
    }
    for node in items {
        let Some(op) = node.as_object() else { continue };
        let label = op
            .get("op")
            .map_or_else(|| format!("{what} op"), |name| format!("{what} op {name}"));
        defaulted_line(op, "line", &label)?;
        column(op.get("column"), &label)?;
        for key in ["then", "else", "body"] {
            flow_coordinates(op.get(key), what, depth.saturating_add(1))?;
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
                    && site.get("line").map_or(true, is_representable_int)
            })
        })
    });
    if !ok {
        return Err(shape(format!(
            "{what} '{key}' must be an array of {{type:str, file:str, line:int}} objects"
        )));
    }
    // …then the DOMAIN, in a second pass over the same array, because that is
    // where the reference puts it: the shape check is one folded `all(...)`
    // whose violation is a single shape failure, and the coordinate rule is a
    // separate loop right after it. One pass answering both would report a
    // domain violation as the record's shape.
    let singular = format!("{what} {}", key.trim_end_matches('s'));
    for site in v.as_array().map_or(&[][..], Vec::as_slice) {
        if let Some(obj) = site.as_object() {
            defaulted_line(obj, "line", &singular)?;
        }
    }
    Ok(())
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
    let ver = if is_representable_int(v) {
        v.as_i64()
    } else {
        None
    };
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
            // The record's own coordinate — line, then the column of the same
            // node (§4.1). The line was validated NOWHERE on either side until
            // #259's final acceptance, which is why it sits between the
            // vocabulary check and the column rather than at the top: this is
            // the reference's order, and BR-D1 makes order observable.
            defaulted_line(sub, "line", "subscription")?;
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
        defaulted_line(svc, "line", "service")?;
        defaulted_string(svc, "ctor_file", "service")?;
        defaulted_line(svc, "ctor_line", "service")?;
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
        defaulted_line(eff, "line", "effect")?;
        let binds = objects(
            eff,
            "bindings",
            "effect 'bindings' must be a JSON array of objects",
        )?;
        for binding in binds {
            defaulted_string(binding, "name", "binding")?;
            defaulted_string(binding, "init", "binding")?;
            string_array(binding, "refs", "binding")?;
            defaulted_line(binding, "line", "binding")?;
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
        flow_coordinates(function.get("body"), "function body", 0)?;
        let params = objects(
            function,
            "params",
            "a function's 'params' must be a JSON array of objects",
        )?;
        for param in params {
            name_slot(param, "name", "parameter")?;
            defaulted_line(param, "line", "parameter")?;
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
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for raw in protos {
        let name = crate::protocol::parse_protocol(raw)?.name;
        // The name is the identity the bridge maps verdicts back by (IR5); two
        // protocols sharing one would make that mapping ambiguous and can
        // collapse distinct findings in the dedup.
        if !seen.insert(name.clone()) {
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
        crate::protocol::parse_method(raw, crate::protocol::Door::Strict)?;
    }
    Ok(())
}

/// The nesting depth beyond which a raw [`Value`] is refused — the one
/// normative depth number in this crate.
///
/// Deliberately `serde_json`'s own parse limit: a document that could be
/// *parsed* never exceeds it, so this bound rejects nothing
/// [`crate::OwnIr::from_json`] would accept. It exists for values built **in
/// memory**, which never passed a parser and therefore carry no bound at all.
///
/// It matches the parser rather than sitting just under some observed overflow
/// point. Where an unguarded serialization happens to abort depends on stack
/// size, build profile and platform — pinning a contract to that would be
/// pinning it to one machine.
/// How deeply flow bodies and event trees may nest (`spec/OwnIR.md` §4.2).
///
/// A **domain** limit, counted in enclosing bodies rather than JSON levels,
/// because nested bodies are the thing a frontend can reason about — the ratio
/// between the two is an encoding detail (each `if` costs two JSON levels).
/// Distinct in kind from [`MAX_VALUE_DEPTH`], which is a defence against
/// exhausting the stack on an in-memory value and carries no contract meaning.
///
/// Set by the reference, and mirrored rather than chosen here: the number is a
/// contract, so the two implementations cannot each pick their own.
pub(crate) const MAX_NESTING_DEPTH: usize = 32;

pub(crate) const MAX_VALUE_DEPTH: usize = 128;

/// Depth of a raw value, measured with an explicit stack.
///
/// Iterative on purpose: a recursive depth check would be the failure it is
/// meant to prevent, and would abort the process rather than return an error —
/// a stack overflow is not catchable.
pub(crate) fn check_depth(value: &Value, what: &str) -> Checked {
    let mut stack: Vec<(&Value, usize)> = vec![(value, 1)];
    while let Some((v, depth)) = stack.pop() {
        if depth > MAX_VALUE_DEPTH {
            return Err(shape(format!(
                "{what}: nested more than {MAX_VALUE_DEPTH} levels deep"
            )));
        }
        let Some(next) = depth.checked_add(1) else {
            return Err(shape(format!("{what}: nesting depth overflowed")));
        };
        match v {
            Value::Array(items) => stack.extend(items.iter().map(|i| (i, next))),
            Value::Object(map) => stack.extend(map.values().map(|i| (i, next))),
            _ => {}
        }
    }
    Ok(())
}

/// [`check_depth`] over every value in a `serde(flatten)` `extra` map, which is
/// itself one level of nesting.
pub(crate) fn check_map_depth(map: &Map<String, Value>, what: &str) -> Checked {
    for value in map.values() {
        check_depth(value, what)?;
    }
    Ok(())
}
