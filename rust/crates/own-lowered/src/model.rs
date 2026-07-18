//! Typed model of the Layer 2 document and its manifest ledger.
//!
//! Field ORDER in every struct is normative: serde serializes declaration
//! order, and the canonical emitter must reproduce `ownlang/lowered.py`'s
//! construction order byte-for-byte. Optional keys exist in exactly two
//! flavours, mirroring the Python emitter: fields Python always writes
//! (possibly `null`) are `Option<T>` WITHOUT skip; the handle-entry allowlist
//! keys Python writes only-when-present are `Option<T>` with
//! `skip_serializing_if`.

use serde::{Deserialize, Serialize};

/// The Layer 2 surface version — must equal `ownlang/lowered.py`'s
/// `LOWERED_VERSION` and `manifest.json`'s `lowered_version`.
pub const LOWERED_VERSION: u32 = 1;

/// One parsed golden: either a full lowered document or a fail-loud rejection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Surface {
    /// A lowered Module + handle map.
    Lowered(LoweredDocument),
    /// An `OwnIRError` rejection whose message text is part of the surface.
    Rejected(Rejected),
}

/// `{"lowered_version": ..., "error": ...}` — a vocabulary-skew rejection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rejected {
    pub lowered_version: u32,
    pub error: String,
}

/// The full Layer 2 document (field order is the canonical JSON order).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoweredDocument {
    pub lowered_version: u32,
    pub module: String,
    pub resources: Vec<Resource>,
    pub externs: Vec<Extern>,
    pub lifetimes: Vec<Lifetime>,
    pub functions: Vec<Function>,
    pub handles: Vec<HandleEntry>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Resource {
    pub name: String,
    /// Always present, possibly `null` (the human `[resource: ...]` tag).
    pub kind: Option<String>,
    pub members: Vec<ResourceMember>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceMember {
    pub role: String,
    pub name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Extern {
    pub name: String,
    pub params: Vec<ExternParam>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExternParam {
    pub effect: String,
    #[serde(rename = "type")]
    pub type_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lifetime {
    pub name: String,
    /// The strictly-longer region, or `null` for a root region.
    pub longer: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Function {
    pub name: String,
    /// The subscriber region, or `null` when no capture was minted.
    pub lifetime: Option<String>,
    pub params: Vec<Param>,
    /// The synthesized owned return type, or `null` for a void body.
    pub ret: Option<TypeShape>,
    pub body: Vec<Stmt>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Param {
    pub handle: String,
    #[serde(rename = "type")]
    pub type_shape: Option<TypeShape>,
    pub line: i64,
    pub lifetime: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TypeShape {
    pub name: String,
    pub borrowed: bool,
    pub mutable: bool,
}

/// The closed statement vocabulary under the `stmt` discriminator. Adding a
/// variant is a Layer 2 contract change (version bump on both sides).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "stmt", rename_all = "snake_case", deny_unknown_fields)]
pub enum Stmt {
    Acquire {
        handle: String,
        resource: String,
        line: i64,
    },
    Release {
        handle: String,
        line: i64,
    },
    Use {
        handle: String,
        line: i64,
    },
    Overspan {
        handle: String,
        line: i64,
    },
    Return {
        /// `null` = a bare return (no owned value).
        handle: Option<String>,
        line: i64,
    },
    AliasJoin {
        handle: String,
        src: String,
        line: i64,
    },
    Call {
        callee: String,
        args: Vec<String>,
        line: i64,
    },
    Subscribe {
        source: String,
        line: i64,
    },
    If {
        cond: String,
        then: Vec<Self>,
        #[serde(rename = "else")]
        r#else: Vec<Self>,
        line: i64,
    },
    While {
        cond: String,
        body: Vec<Self>,
        line: i64,
    },
}

/// One normalized handle-map entry: `handle` first, then the allowlist keys in
/// fixed order, each present only when the underlying record carried it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HandleEntry {
    pub handle: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub component: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub handler: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resource: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub released: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub di_source_life: Option<String>,
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub type_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ever_released: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pool: Option<bool>,
}

/// `tests/fixtures/lowered/manifest.json` — the frozen case ledger.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub comment: String,
    pub lowered_version: u32,
    pub cases: Vec<ManifestCase>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManifestCase {
    pub name: String,
    pub rules: Vec<String>,
    pub rust_replay: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decision: Option<String>,
}

/// Parse one golden document, strictly typed.
///
/// A JSON object carrying `error` is a [`Rejected`], anything else must be a
/// full [`LoweredDocument`] — unknown fields fail in both shapes, so a
/// Python-side surface change cannot slip past the typed replay.
///
/// # Errors
/// Returns the underlying `serde_json` error when the text is not valid JSON
/// or does not match the closed Layer 2 shapes.
pub fn parse_document(text: &str) -> Result<Surface, serde_json::Error> {
    let value: serde_json::Value = serde_json::from_str(text)?;
    if value.get("error").is_some() {
        return serde_json::from_value::<Rejected>(value).map(Surface::Rejected);
    }
    serde_json::from_value::<LoweredDocument>(value).map(Surface::Lowered)
}

/// The canonical serialized form — byte-identical to the Python emitter's
/// `render_lowered`: 2-space pretty JSON, declaration field order, raw UTF-8,
/// one trailing newline.
///
/// # Errors
/// Returns the underlying `serde_json` error if serialization fails (it
/// cannot for these closed types, but the emitter refuses to panic).
pub fn to_canonical_json(surface: &Surface) -> Result<String, serde_json::Error> {
    let mut out = match surface {
        Surface::Lowered(doc) => serde_json::to_string_pretty(doc)?,
        Surface::Rejected(rej) => serde_json::to_string_pretty(rej)?,
    };
    out.push('\n');
    Ok(out)
}
