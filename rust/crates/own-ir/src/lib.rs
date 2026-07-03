//! `own-ir` — the `OwnIR` **fact** contract, re-typed with serde (P-022 step 1).
//!
//! `OwnIR` is the frozen seam between the frontends (the Roslyn C# extractor,
//! `OwnTS`) and the core: a versioned JSON fact vocabulary. This crate is the
//! Rust side of that seam. Its acceptance rule mirrors the Python reference
//! (`ownlang/ownir.py::load`) exactly:
//!
//! * **typed fields are only the ones Python validates** — everything else
//!   rides in a flattened `extra` map, so additive optional fields a newer
//!   frontend emits are tolerated *and preserved on round-trip* (the parity
//!   property `tests/roundtrip.rs` pins against the repo's `OwnIR` fixtures);
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

/// A shape/vocabulary violation in an `OwnIR` document. Facts are external
/// input, so a malformed file must fail with a clear error, not a panic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnIrError(pub String);

impl std::fmt::Display for OwnIrError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for OwnIrError {}

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
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub type_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One event subscription inside a component.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Subscription {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resource: Option<String>,
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub type_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_type: Option<String>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One component (a view model / window / control the extractor saw).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Component {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subscriptions: Option<Vec<Subscription>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One DI service registration (P-006).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Service {
    pub lifetime: Lifetime,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deps: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub weak_deps: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub root_resolves: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctor_file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctor_line: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctor_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub root_resolve_sites: Option<Vec<Site>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope_cached: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scope_cache_sites: Option<Vec<Site>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One reactive-effect binding row (P-020).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Binding {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub init: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refs: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One reactive effect (P-020, EFF001).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Effect {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deps: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub io: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bindings: Option<Vec<Binding>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One function parameter (ownership contract, P-006/2b).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Param {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub effect: Option<ParamEffect>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One per-method flow body (P-016). The body's `nodes` are deliberately
/// untyped here — their vocabulary is the bridge's concern, not the schema's.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Function {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub params: Option<Vec<Param>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// The `OwnIR` document root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct OwnIr {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ownir_version: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub components: Option<Vec<Component>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub services: Option<Vec<Service>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub effects: Option<Vec<Effect>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub functions: Option<Vec<Function>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl OwnIr {
    /// Parse + shape-check an `OwnIR` JSON document. Mirrors the acceptance of
    /// Python `ownlang.ownir.load` (version gate first, then field shapes).
    ///
    /// # Errors
    /// [`OwnIrError`] on invalid JSON, a schema-version mismatch, or any field
    /// that the reference implementation would reject.
    pub fn from_json(text: &str) -> Result<Self, OwnIrError> {
        let doc: Self = serde_json::from_str(text)
            .map_err(|e| OwnIrError(format!("OwnIR facts are not valid: {e}")))?;
        doc.validate()?;
        Ok(doc)
    }

    /// The checks serde's typing cannot express: the version gate and the
    /// non-empty-identity rules.
    ///
    /// # Errors
    /// [`OwnIrError`] on a schema-version mismatch or an empty identity field.
    pub fn validate(&self) -> Result<(), OwnIrError> {
        let ver = self.ownir_version.unwrap_or(OWNIR_VERSION);
        if ver != OWNIR_VERSION {
            return Err(OwnIrError(format!(
                "OwnIR facts are schema v{ver}, but this core understands \
                 v{OWNIR_VERSION}. Build the extractor and the core from the \
                 same commit — the OwnIR fact vocabulary changed between the \
                 version that produced this file and the one reading it."
            )));
        }
        for s in self.services.iter().flatten() {
            if s.name.is_empty() {
                return Err(OwnIrError(
                    "service 'name' must be a non-empty string".to_owned(),
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
                return Err(OwnIrError(
                    "parameter 'name' must be a non-empty string".to_owned(),
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
        serde_json::to_value(self).map_err(|e| OwnIrError(format!("serialize failed: {e}")))
    }
}
