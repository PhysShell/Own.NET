//! `own-ir` — the `OwnIR` **fact** contract, re-typed with serde (P-022 step 1).
//!
//! `OwnIR` is the frozen seam between the frontends (the Roslyn C# extractor,
//! `OwnTS`) and the core: a versioned JSON fact vocabulary. This crate is the
//! Rust side of that seam. Its acceptance rule mirrors the Python reference
//! (`ownlang/ownir.py::load`) — a claim that is **measured**, not asserted:
//! `tests/validation_replay.rs` replays a 193-control Python-authored ledger
//! and requires zero Rust-only accepts, zero Rust-only rejects and zero
//! error-category mismatches.
//!
//! The measurement had to be taken twice, and the second time is the one worth
//! reading. A first sweep of 77 controls found twelve permissive documents,
//! fixed them, and read 0/0/0 — but the same author had written the ledger and
//! the port, so a gap in reading BR-D1 produced a matching gap in each. A
//! re-census built from the reference line by line opened **58** more
//! permissive documents and **9** category mismatches. Both numbers are in the
//! commit history on purpose: a differential oracle written by the author of
//! the implementation measures the author's understanding until something
//! external disagrees with it.
//!
//! * **the strict door is the `strict` module, not serde.** Validation runs over
//!   the raw document and is complete before deserialization begins, because
//!   BR-D1 interleaves shape and semantic checks per section in
//!   document-declaration order — an order neither serde's field traversal nor
//!   a "semantics first, shapes second" gate reproduces. serde afterwards is a
//!   *constructor*; if it still rejects, that is a hole in the validator, and
//!   it says so ([`VALIDATOR_HOLE`]);
//! * **typed fields are not what makes a rule enforced** — everything
//!   undeclared rides in a flattened `extra` map, so additive optional fields a
//!   newer frontend emits are tolerated *and preserved on round-trip*
//!   (`tests/roundtrip.rs`). Six fields Python validated were once absent from
//!   this model and fell into `extra`, escaping checking entirely; that class
//!   of bug is now caught by the validator rather than prevented by remembering
//!   to declare things;
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

mod protocol;
pub mod span;
mod strict;

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
/// The set is closed by measurement, in both directions:
///
/// * it cannot outgrow its evidence — `tests/fixtures/ownir_validation.json`
///   fails if a declared category has no control exercising it. There is
///   deliberately no `Reference` variant, because the strict-door sweep found
///   no load-time referential constraint and adding one on the strength of an
///   issue's prose would invent a category nothing can reach;
/// * and it is not frozen against new evidence. [`Self::WellFormedness`] was
///   added when the second census found a mechanism the first had not reached.
///   A taxonomy settled by one census is a claim about that census, not about
///   the contract, and reporting the new mechanism under the nearest existing
///   variant would be exactly the substitution this enum exists to prevent.
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
    /// Every value has the right type and the right vocabulary, and the record
    /// still cannot mean anything — a rule that structurally never fires, a
    /// barrier the walk can never reach.
    ///
    /// This variant exists because the second census found the mechanism, and
    /// a taxonomy frozen by the *first* census is not evidence about the
    /// second. Reporting these as `Shape` was the exact failure the taxonomy
    /// was built to prevent: letting the nearest available category stand in
    /// for the real one.
    WellFormedness,
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
            Self::WellFormedness => "well_formedness",
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

/// Sentinel prefix on the one error [`OwnIr::from_json`] can raise that is not
/// a rejection.
///
/// Once the `strict` module has accepted a document, `serde` is only building the
/// typed value; if it still refuses, the validator is missing a rule the model
/// happens to encode. That is a defect in this crate, not in the document, and
/// it must not hide inside a plausible-looking `Shape` error — so it is marked,
/// and `validation_replay` asserts no control in the ledger reaches it.
pub const VALIDATOR_HOLE: &str = "strict validator hole";

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
    /// check lives in the `strict` module — reached from [`OwnIr::from_json`]
    /// and [`OwnIr::validate`] alike — where it can answer `Location`.
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
    /// Obligation-protocol declarations. Held as raw values because nothing
    /// consumes a typed representation yet — not because the records go
    /// unchecked.
    ///
    /// The reference checks only list-ness *here* and delegates each record to
    /// the shared obligation parser. That parser is called by `load()` and its
    /// errors are wrapped as `OwnIRError`, so it is part of the strict-door
    /// contract, and its **acceptance grammar** is ported in `protocol.rs`. An
    /// earlier revision of this comment called record validity a delegated
    /// boundary "not yet mirrored"; the second census measured that as a hole
    /// in the door worth 47 of its 58 permissive documents. Protocol
    /// *analysis* — the lattice, the walker, verdicts — is still absent, and
    /// that one is a real boundary.
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub protocols: Option<Vec<Value>>,
    /// Per-method protocol facts. Same arrangement as `protocols`: list shape
    /// here, the event-tree grammar in `protocol.rs`, no analysis anywhere.
    #[serde(
        default,
        deserialize_with = "reject_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub protocol_functions: Option<Vec<Value>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl OwnIr {
    /// Parse + shape-check an `OwnIR` JSON document — the **strict door**
    /// (BR-D1). Accepts the same language as Python `ownlang.ownir.load`,
    /// including the observable order in which it rejects.
    ///
    /// Validation runs over the **raw** document (the `strict` module) and is
    /// finished before `serde` sees anything. That is not an optimisation of
    /// the previous design, it is the only arrangement that can reproduce the
    /// contract: BR-D1 interleaves shape and semantic checks per section, in
    /// document-declaration order, and neither serde's field order nor a
    /// "semantics first, shapes second" two-pass gate is that order.
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
        let raw: Value = serde_json::from_str(text)
            .map_err(|e| OwnIrError::new(OwnIrErrorKind::Json, format!("not valid JSON: {e}")))?;
        let Some(obj) = raw.as_object() else {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Shape,
                "OwnIR root must be a JSON object",
            ));
        };
        strict::validate_document(obj)?;
        // serde is the CONSTRUCTOR, not the arbiter: the document has already
        // been accepted, so a failure here is a hole in the validator rather
        // than a rejection. Marked with a sentinel the replay test asserts no
        // control ever reaches — see `no_control_escapes_into_serde`.
        serde_json::from_value(raw).map_err(|e| {
            OwnIrError::new(
                OwnIrErrorKind::Shape,
                format!(
                    "{VALIDATOR_HOLE}: the strict validator accepted a document serde \
                         then refused, so a rule is missing from it — {e}"
                ),
            )
        })
    }

    /// The strict door applied to a value built in memory rather than parsed.
    ///
    /// Serializing and re-validating costs a round-trip, and buys the property
    /// that broke this crate once already: there is exactly **one** copy of the
    /// acceptance law. The previous design kept a second, smaller copy here, and
    /// a mutation planted in one was caught by the other — a false "survived"
    /// that cost real time to explain.
    ///
    /// # Errors
    /// [`OwnIrError`] if the value would not survive [`OwnIr::from_json`].
    pub fn validate(&self) -> Result<(), OwnIrError> {
        let value = self.to_value()?;
        let Some(obj) = value.as_object() else {
            return Err(OwnIrError::new(
                OwnIrErrorKind::Shape,
                "OwnIR root must be a JSON object",
            ));
        };
        strict::validate_document(obj)
    }

    /// Serialize back to a JSON value. Together with `from_json` this is the
    /// round-trip the oracle's first parity check rides on.
    ///
    /// Refuses a document whose raw values nest deeper than
    /// `strict::MAX_VALUE_DEPTH` (128). `serde_json::to_value` recurses over a
    /// `Value`, and on a deep enough one it does not fail — it **aborts the
    /// process**. A stack overflow cannot be caught, so the only place to stop
    /// it is before serialization starts.
    ///
    /// **128 is the contract**, and the only depth number that is. It is
    /// `serde_json`'s own parser bound, so nothing [`OwnIr::from_json`] can
    /// accept is refused here. The depth at which an unguarded serialization
    /// would actually abort is a property of one stack size, build profile and
    /// platform; useful forensics, not a specification, so it is not written as
    /// one.
    ///
    /// # Errors
    /// [`OwnIrError`] if a raw value is nested too deeply, or if serialization
    /// fails (it cannot for these types, but the contract stays honest rather
    /// than panicking).
    pub fn to_value(&self) -> Result<Value, OwnIrError> {
        self.check_raw_depth()?;
        serde_json::to_value(self)
            .map_err(|e| OwnIrError::new(OwnIrErrorKind::Shape, format!("serialize failed: {e}")))
    }

    /// Depth-check every raw [`Value`] the model carries.
    ///
    /// The *typed* nesting is fixed — root → components → subscriptions and so
    /// on — so these are plain loops, not recursion. Only the `extra` maps, the
    /// two protocol sections and `Subscription::column` hold values of
    /// caller-chosen shape, and each is measured iteratively.
    fn check_raw_depth(&self) -> Result<(), OwnIrError> {
        strict::check_map_depth(&self.extra, "OwnIR root")?;
        for value in self.protocols.iter().flatten() {
            strict::check_depth(value, "protocol")?;
        }
        for value in self.protocol_functions.iter().flatten() {
            strict::check_depth(value, "protocol function")?;
        }
        for component in self.components.iter().flatten() {
            strict::check_map_depth(&component.extra, "component")?;
            for sub in component.subscriptions.iter().flatten() {
                strict::check_map_depth(&sub.extra, "subscription")?;
                if let Some(column) = sub.column.as_ref() {
                    strict::check_depth(column, "subscription 'column'")?;
                }
            }
        }
        for service in self.services.iter().flatten() {
            strict::check_map_depth(&service.extra, "service")?;
            for site in service
                .root_resolve_sites
                .iter()
                .flatten()
                .chain(service.scope_cache_sites.iter().flatten())
            {
                strict::check_map_depth(&site.extra, "service call site")?;
            }
        }
        for effect in self.effects.iter().flatten() {
            strict::check_map_depth(&effect.extra, "effect")?;
            for binding in effect.bindings.iter().flatten() {
                strict::check_map_depth(&binding.extra, "binding")?;
            }
        }
        for function in self.functions.iter().flatten() {
            strict::check_map_depth(&function.extra, "function")?;
            for param in function.params.iter().flatten() {
                strict::check_map_depth(&param.extra, "parameter")?;
            }
        }
        Ok(())
    }
}
