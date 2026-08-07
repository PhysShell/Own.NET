//! `own-ir` — the `OwnIR` **fact** contract, re-typed with serde (P-022 step 1).
//!
//! `OwnIR` is the frozen seam between the frontends (the Roslyn C# extractor,
//! `OwnTS`) and the core: a versioned JSON fact vocabulary. This crate is the
//! Rust side of that seam. Its acceptance rule mirrors the Python reference
//! (`ownlang/ownir.py::load`) exactly — a claim that is now **measured**, not
//! asserted: `tests/validation_replay.rs` replays a 77-control Python-authored
//! ledger and requires zero Rust-only accepts, zero Rust-only rejects and zero
//! error-category mismatches.
//!
//! That measurement was worth having. The same sentence used to sit here
//! unbacked, and a differential sweep found **twelve** documents the reference
//! refused and this crate accepted (#259 cp1) — mostly because a field the
//! model never declared cannot be checked by serde, however strict serde is
//! about the fields it *has* been told about.
//!
//! * **typed fields are the ones the strict door validates** — everything else
//!   rides in a flattened `extra` map, so additive optional fields a newer
//!   frontend emits are tolerated *and preserved on round-trip* (the parity
//!   property `tests/roundtrip.rs` pins against the repo's `OwnIR` fixtures).
//!   A field that Python *does* validate must be declared here, or it silently
//!   falls into `extra` and escapes checking entirely;
//! * the **schema version gates first** (`ownir_version`, absent ⇒ v0), and a
//!   vocabulary mismatch fails loudly with an actionable message;
//! * JSON `true` is **not** an integer here (unlike Python, where `bool` is an
//!   `int` subclass and needs an explicit check — Rust gets that for free).
//!
//! Verdict types deliberately do **not** live here: `own-ir` is facts + the
//! span/location leaf; diagnostics/evidence belong to `own-diagnostics`.
//!
//! Error *message* parity with Python is not claimed yet — that lands with the
//! shared error-text fixtures (P-022 oracle section), not by copy-paste.

pub mod span;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// The schema version this crate understands. Bump only on an incompatible
/// vocabulary change — additive optional fields are NOT a version bump.
pub const OWNIR_VERSION: i64 = 0;

/// Why a document was rejected.
///
/// This is the cross-language comparison surface. The reference funnels every rejection into one `OwnIRError` whose message is
/// a human-facing presentation aid. #259 asks for a matching error
/// *class/category*, so parity is pinned on this enum instead: byte-comparing
/// two languages' English would freeze a debug surface as a contract.
///
/// One variant per **mechanism** a loader can reject on, not one per message.
/// The set is closed by measurement — `tests/fixtures/ownir_validation.json`
/// fails if a declared category has no control exercising it, so the taxonomy
/// cannot outgrow its evidence. There is deliberately no `Reference` variant:
/// the strict-door sweep found no load-time referential constraint, and adding
/// one on the strength of an issue's prose would invent a category nothing can
/// reach.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OwnIrErrorKind {
    /// The document is not JSON at all.
    Json,
    /// The `ownir_version` gate — wrong type, or a version this core cannot read.
    Version,
    /// Right place, wrong JSON type or container shape.
    Shape,
    /// Right JSON type, value outside a closed set (resource kind, lifetime,
    /// parameter effect).
    Vocabulary,
    /// An identity field that is empty, non-string, or duplicated.
    Identity,
    /// A source coordinate violating the 1-based contract (#317).
    Location,
}

impl OwnIrErrorKind {
    /// The stable wire name the parity ledger compares on.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Version => "version",
            Self::Shape => "shape",
            Self::Vocabulary => "vocabulary",
            Self::Identity => "identity",
            Self::Location => "location",
        }
    }
}

/// A rejection from the strict door. Facts are external input, so a malformed
/// file must fail with a clear error, not a panic.
///
/// `kind` is the contract; `message` stays actionable for a human but is never
/// compared across languages.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnIrError {
    pub kind: OwnIrErrorKind,
    pub message: String,
}

impl OwnIrError {
    fn new(kind: OwnIrErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for OwnIrError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OwnIrError {}

/// The closed set of resource discriminators (IR4).
///
/// A present-but-unknown kind changes routing, so the strict door rejects it
/// rather than let it fall through to the owned/subscription path; a new kind
/// is a vocabulary change that must bump [`OWNIR_VERSION`].
pub const KNOWN_RESOURCE_KINDS: [&str; 8] = [
    "capture",
    "disposable",
    "local-disposable",
    "pool",
    "subscribe",
    "subscription",
    "timer",
    "unresolved-subscription",
];

/// Deserializer for load()-validated optional fields: **absent** means default
/// (Python's `d.get("f", default)`), but a **present `null` is rejected** —
/// exactly like Python's `isinstance` check failing on `None`. `serde(default)`
/// handles absence before this runs; here a null hits `T::deserialize` and
/// errors.
fn reject_null<'de, D, T>(de: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(de).map(Some)
}

/// Deserializer for the three fields Python checks with `if x is not None and
/// not isinstance(...)` — a present `null` is **accepted** there, and the value
/// stays `null` in the document, so round-trip must preserve it. Outer `None` =
/// absent (skipped on serialize); `Some(None)` = explicit null (serialized as
/// `null`); `Some(Some(v))` = a value.
#[allow(clippy::option_option)] // the 3 states ARE the contract: absent / explicit null / value
fn nullable<'de, D, T>(de: D) -> Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(de).map(Some)
}

/// DI registration lifetime — the only closed vocabulary inside the facts
/// (`ownlang/di.py::LIFETIMES`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lifetime {
    Singleton,
    Scoped,
    Transient,
}

/// Ownership effect a function parameter applies to its argument — the same
/// closed set `load()` enforces on `functions[].params[].effect`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParamEffect {
    Consume,
    Borrow,
    BorrowMut,
    Plain,
}

/// One `{type, file, line}` call-site record (DI004 / DI005 metadata).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Site {
    #[serde(
        rename = "type",
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub type_name: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub file: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub line: Option<i64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One event subscription inside a component.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Subscription {
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub resource: Option<String>,
    #[serde(
        rename = "type",
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub type_name: Option<Option<String>>,
    #[serde(
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub source_type: Option<Option<String>>,
    /// Interprocedural publisher provenance (P-004, #146). Nullable-optional:
    /// the reference tests `is not None and not isinstance(str)`, so an
    /// explicit `null` is accepted and read as absent.
    #[serde(
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub source_provenance: Option<Option<String>>,
    /// The mandatory justification on an inline suppression (#209). Same
    /// nullable-optional rule as `source_provenance` — and deliberately *not*
    /// the same as `resource`, which rejects `null`. These fields shared one
    /// bug (absent from the Rust model, so serde never checked them); they do
    /// not share one policy.
    #[serde(
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub ignore_reason: Option<Option<String>>,
    /// The source **column** of the node `line` anchors on (#317).
    ///
    /// Held as a raw [`Value`] on purpose. A typed `Option<NonZeroU32>` would
    /// make `0`, `-1`, `true` and `"3"` all die inside serde — correct
    /// rejections, but every one of them reported as [`OwnIrErrorKind::Shape`],
    /// when the contract being violated is the 1-based coordinate rule. The
    /// implementation mechanism must not pick the semantic category, so the
    /// check lives in [`OwnIr::validate`] where it can answer `Location`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub column: Option<Value>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One component (a view model / window / control the extractor saw).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Component {
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub subscriptions: Option<Vec<Subscription>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One DI service registration (P-006).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Service {
    pub lifetime: Lifetime,
    pub name: String,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub deps: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub weak_deps: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub root_resolves: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub file: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub line: Option<i64>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub ctor_file: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub ctor_line: Option<i64>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub ctor_type: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub root_resolve_sites: Option<Vec<Site>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub scope_cached: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub scope_cache_sites: Option<Vec<Site>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One reactive-effect binding row (P-020).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Binding {
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub name: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub init: Option<String>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub refs: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub line: Option<i64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One reactive effect (P-020, EFF001).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Effect {
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub deps: Option<Vec<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub io: Option<bool>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub line: Option<i64>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub bindings: Option<Vec<Binding>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One function parameter (ownership contract, P-006/2b).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Param {
    pub name: String,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub line: Option<i64>,
    #[serde(
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub effect: Option<Option<ParamEffect>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One per-method flow body (P-016). The body's `nodes` are deliberately
/// untyped here — their vocabulary is the bridge's concern, not the schema's.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Function {
    /// The overload key MOS resolution joins on. Nullable-optional: the
    /// reference rejects a non-string but reads `null` as absent. A malformed
    /// `sig` on a FLOW OP is treated differently (read as absent, degrading to
    /// the merged summary) — that is a different door, not this one.
    #[serde(
        default,
        deserialize_with = "nullable",
        skip_serializing_if = "Option::is_none"
    )]
    pub sig: Option<Option<String>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub params: Option<Vec<Param>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// The `OwnIR` document root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct OwnIr {
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub ownir_version: Option<i64>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub components: Option<Vec<Component>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub services: Option<Vec<Service>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub effects: Option<Vec<Effect>>,
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub functions: Option<Vec<Function>>,
    /// Obligation-protocol declarations. Held as raw values: the reference
    /// checks only that this is a LIST here and delegates each record to the
    /// shared obligation parser, which is a separate surface with its own
    /// vocabulary. What this crate owns from it is the identity invariant —
    /// see [`OwnIr::validate`]. Record-level validity beyond that is NOT yet
    /// mirrored; documented in the ledger rather than silently assumed.
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub protocols: Option<Vec<Value>>,
    /// Per-method protocol facts. Same delegation as `protocols`: list shape
    /// here, record parsing elsewhere.
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub protocol_functions: Option<Vec<Value>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// The checks whose **category** must not be decided by serde.
///
/// Run against the raw document, before typed deserialization. A serde enum
/// would reject `lifetime: "eternal"` perfectly well — and report it as
/// [`OwnIrErrorKind::Shape`], when the contract violated is a closed
/// vocabulary. Likewise a `name: 7` is an identity failure in the reference,
/// not a type failure. Deserializing first and classifying after would make
/// accept/reject parity green while the taxonomy quietly lied.
///
/// Ordered to follow BR-D1: `components` → `services` → `functions` →
/// `protocols`.
fn gate_semantics(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
    gate_components(obj)?;
    gate_services(obj)?;
    gate_params(obj)?;
    gate_protocols(obj)
}

/// `components[]` — resource shape, then its closed vocabulary, then columns.
fn gate_components(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
    for sub in obj
        .get("components")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
        .filter_map(|c| c.get("subscriptions"))
        .filter_map(Value::as_array)
        .flatten()
        .filter_map(Value::as_object)
    {
        // IR4. A present-but-unknown kind changes routing, so the strict door
        // rejects it rather than let it mis-route. The lowering door keeps its
        // OWN copy of this rule (#294 OD-2) — that one guards the tolerant path
        // which bypasses this loader entirely. Two doors, not one duplicated
        // check: removing either reopens a different hole.
        // Shape before vocabulary, in that order: `resource` must BE a string
        // before its value can be tested against the closed set. Checking the
        // set first (and skipping a non-string) would let `{"resource": 7,
        // "column": 0}` be reported as a column problem, which is the wrong
        // contract and the wrong category.
        match sub.get("resource") {
            Some(Value::String(_)) | None => {}
            Some(other) => {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Shape,
                    format!("subscription 'resource' must be a string, got {other}"),
                ))
            }
        }
        if let Some(kind) = sub.get("resource").and_then(Value::as_str) {
            if !KNOWN_RESOURCE_KINDS.contains(&kind) {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Vocabulary,
                    format!(
                        "unknown resource kind {kind:?} — a new kind is a \
                         vocabulary change that must bump OWNIR_VERSION"
                    ),
                ));
            }
        }
        check_column(sub.get("column"), "subscription")?;
    }
    Ok(())
}

/// `services[]` — name identity, then the DI lifetime vocabulary.
fn gate_services(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
    for svc in obj
        .get("services")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
    {
        // The service name is the identity the DI graph joins on: empty and
        // non-string are the same defect class, and the reference reports both
        // with one message.
        match svc.get("name") {
            Some(Value::String(n)) if !n.is_empty() => {}
            None => {}
            _ => {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Identity,
                    "service 'name' must be a non-empty string",
                ))
            }
        }
        if let Some(v) = svc.get("lifetime") {
            let known = v
                .as_str()
                .is_some_and(|l| ["scoped", "singleton", "transient"].contains(&l));
            if !known {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Vocabulary,
                    format!(
                        "service 'lifetime' must be one of \
                         [\"scoped\", \"singleton\", \"transient\"], got {v}"
                    ),
                ));
            }
        }
    }

    Ok(())
}

/// `functions[].params[]` — name identity, then the effect vocabulary.
fn gate_params(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
    for param in obj
        .get("functions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
        .filter_map(|f| f.get("params"))
        .filter_map(Value::as_array)
        .flatten()
        .filter_map(Value::as_object)
    {
        match param.get("name") {
            Some(Value::String(n)) if !n.is_empty() => {}
            None => {}
            _ => {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Identity,
                    "parameter 'name' must be a non-empty string",
                ))
            }
        }
        if let Some(v) = param.get("effect") {
            let known = v.is_null()
                || v.as_str()
                    .is_some_and(|e| ["borrow", "borrow_mut", "consume", "plain"].contains(&e));
            if !known {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Vocabulary,
                    format!(
                        "parameter 'effect' must be one of \
                         [\"borrow\", \"borrow_mut\", \"consume\", \"plain\"], got {v}"
                    ),
                ));
            }
        }
    }

    Ok(())
}

/// `protocols[]` — the identity invariant two individually valid records can
/// only violate together.
fn gate_protocols(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
    let mut seen: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
    for proto in obj
        .get("protocols")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
    {
        if let Some(name) = proto.get("name").and_then(Value::as_str) {
            if !seen.insert(name) {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Identity,
                    format!(
                        "duplicate protocol name '{name}' — protocol names are \
                         the identity findings map back by and must be unique"
                    ),
                ));
            }
        }
    }
    Ok(())
}

/// The 1-based source-column contract (#317).
///
/// A column is a positive integer or it is absent. `0` is rejected rather than
/// read as "unknown": SARIF columns start at 1, so a `0` is a producer bug, and
/// silently treating it as absent would hide the bug while looking correct.
/// `true` is rejected explicitly — the reference guards the same trap because a
/// Python `bool` is an `int`, and accepting it would fabricate column 1.
fn check_column(value: Option<&Value>, where_: &str) -> Result<(), OwnIrError> {
    let Some(v) = value else { return Ok(()) };
    if v.is_null() {
        return Ok(());
    }
    // `Bool` is called out rather than folded into the wildcard: it is the
    // trap the reference guards explicitly (a Python `bool` is an `int`, so
    // `True` would otherwise be read as column 1 — a fabricated coordinate).
    let ok = match v {
        Value::Number(n) => n.as_i64().is_some_and(|i| i >= 1),
        _ => false,
    };
    if ok {
        return Ok(());
    }
    Err(OwnIrError::new(
        OwnIrErrorKind::Location,
        format!("{where_} 'column' must be a 1-based integer or absent, got {v}"),
    ))
}

impl OwnIr {
    /// Parse + shape-check an `OwnIR` JSON document — the **strict door**
    /// (BR-D1). Mirrors the acceptance of Python `ownlang.ownir.load`,
    /// including the observable order: JSON → root-is-object → version gate →
    /// semantic gate → typed shapes.
    ///
    /// The tolerant door (`check_facts`/`to_module`, which take a document
    /// directly and never call `load`) is a *different* entry surface with its
    /// own fail-loud rules in `own-bridge`. Neither subsumes the other: the
    /// lowerer's unknown-resource check (#294 OD-2) guards callers who bypass
    /// this function entirely.
    ///
    /// # Errors
    /// [`OwnIrError`] on invalid JSON, a schema-version mismatch, or any field
    /// that the reference implementation would reject.
    pub fn from_json(text: &str) -> Result<Self, OwnIrError> {
        // BR-D1 fixes the ORDER, and the spec notes it "is observable through
        // which error fires first". A single `from_str::<Self>` would collapse
        // that: serde would reject a malformed `components` before anything
        // could look at `ownir_version`, reporting Shape where the reference
        // reports Version. So the gate runs on an untyped value first.
        let raw: Value = serde_json::from_str(text)
            .map_err(|e| OwnIrError::new(OwnIrErrorKind::Json, format!("not valid JSON: {e}")))?;
        let Some(obj) = raw.as_object() else {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Shape,
                "OwnIR root must be a JSON object",
            ));
        };
        Self::gate_version(obj)?;
        gate_semantics(obj)?;
        let doc: Self = serde_json::from_value(raw).map_err(|e| {
            OwnIrError::new(
                OwnIrErrorKind::Shape,
                format!("OwnIR facts are not valid: {e}"),
            )
        })?;
        doc.validate()?;
        Ok(doc)
    }

    /// The version gate, run against the untyped document so it precedes every
    /// shape check exactly as BR-D1 requires.
    ///
    /// An absent field means the current version (the only producers that omit
    /// it predate versioning). A present `bool` is rejected explicitly: JSON
    /// has a real boolean type, but the reference guards the same trap because
    /// `True` is an `int` in Python, and accepting `true` as v1 here would let
    /// a document through that the reference refuses.
    fn gate_version(obj: &Map<String, Value>) -> Result<(), OwnIrError> {
        let Some(v) = obj.get("ownir_version") else {
            return Ok(());
        };
        // A `Bool` deliberately falls through to `None` with everything else:
        // the reference guards it because a Python `bool` is an `int`, and
        // accepting `true` here would read as schema v1.
        let ver = match v {
            Value::Number(n) if n.is_i64() => n.as_i64(),
            _ => None,
        };
        let Some(ver) = ver else {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Version,
                format!("OwnIR 'ownir_version' must be an integer, got {v}"),
            ));
        };
        if ver != OWNIR_VERSION {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Version,
                format!(
                    "OwnIR facts are schema v{ver}, but this core understands \
                     v{OWNIR_VERSION}. Build the extractor and the core from the \
                     same commit — the OwnIR fact vocabulary changed between the \
                     version that produced this file and the one reading it."
                ),
            ));
        }
        Ok(())
    }

    /// The checks serde's typing cannot express, for a value built directly
    /// rather than loaded.
    ///
    /// The full semantic gate (closed vocabularies, the 1-based column rule,
    /// protocol identity) runs inside [`OwnIr::from_json`] against the **raw**
    /// document, because getting the error *category* right requires checking
    /// before serde deserializes — see [`gate_semantics`]. `from_json` is the
    /// strict door; this is the residue a typed value can still violate.
    ///
    /// # Errors
    /// [`OwnIrError`] on a schema-version mismatch or an empty identity field.
    pub fn validate(&self) -> Result<(), OwnIrError> {
        let ver = self.ownir_version.unwrap_or(OWNIR_VERSION);
        if ver != OWNIR_VERSION {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Version,
                format!(
                    "OwnIR facts are schema v{ver}, but this core understands \
                     v{OWNIR_VERSION}. Build the extractor and the core from the \
                     same commit — the OwnIR fact vocabulary changed between the \
                     version that produced this file and the one reading it."
                ),
            ));
        }
        for s in self.services.iter().flatten() {
            if s.name.is_empty() {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Identity,
                    "service 'name' must be a non-empty string",
                ));
            }
        }
        for p in self
            .functions
            .iter()
            .flatten()
            .flat_map(|f| f.params.iter().flatten())
        {
            if p.name.is_empty() {
                return Err(OwnIrError::new(
                    OwnIrErrorKind::Identity,
                    "parameter 'name' must be a non-empty string",
                ));
            }
        }
        Ok(())
    }

    /// Serialize back to a JSON value. Together with `from_json` this is the
    /// round-trip the oracle's first parity check rides on.
    ///
    /// # Errors
    /// [`OwnIrError`] if serialization fails (it cannot for these types, but
    /// the contract stays honest rather than panicking).
    pub fn to_value(&self) -> Result<Value, OwnIrError> {
        serde_json::to_value(self)
            .map_err(|e| OwnIrError::new(OwnIrErrorKind::Shape, format!("serialize failed: {e}")))
    }
}
