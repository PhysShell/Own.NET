//! An order-preserving JSON value over the **closed canonical domain**, plus
//! the two writers the shadow-mode surfaces need.
//!
//! Two reasons this is not `serde_json::Value`:
//!
//! * **Order.** `serde_json::Value`'s object is a `BTreeMap`, so parsing and
//!   re-serializing sorts the keys. The reproduction artifact renders its
//!   embedded document in **document order** (BR-D4: input order is
//!   semantic), so a byte-exact round-trip needs a value type that remembers
//!   the order it was parsed in. Turning on `serde_json`'s `preserve_order`
//!   feature would have done it — and would also have changed every other
//!   crate in the workspace, because cargo unifies features across a build;
//!   `own-ir`, `own-lowered` and `own-bridge` all have byte-exact output
//!   contracts that must not move because a test harness wanted an `IndexMap`.
//! * **Domain.** The canonical domain (object, array, string, `i64` integer,
//!   bool, null) is enforced **by the type**: there is no float variant, so a
//!   float or an integer outside `i64` is a *parse* refusal and every value
//!   that exists is canonicalizable. The Python side checks the same domain at
//!   run time because `json` has no such type; one contract, two enforcement
//!   points.
//!
//! Duplicate keys follow the reference exactly: the **last** value wins and
//! the key keeps its **first** position, which is what `dict` does for
//! `json.load` — the canonical form is defined over the *parsed* document, so
//! the two parsers have to agree about what parsing means.

use std::fmt;
use std::fmt::Write as _;

use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};

/// A parsed JSON document over the closed canonical domain.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Json {
    Null,
    Bool(bool),
    /// The only numeric form. `spec/OwnIR.md` §4.2 bounds every validated
    /// coordinate to signed 64 bits, so the domain costs the contract nothing.
    Int(i64),
    Str(String),
    Array(Vec<Self>),
    /// Entries in **document order**, keys unique (last value wins).
    Object(Vec<(String, Self)>),
}

impl Json {
    /// The value under `key`, or `None` for a non-object / absent key.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&Self> {
        match self {
            Self::Object(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// True when this is an object carrying `key` — the "present, possibly
    /// null" question, which `get(..).is_some()` also answers but reads worse.
    #[must_use]
    pub fn has(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    #[must_use]
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Self::Str(s) => Some(s),
            _ => None,
        }
    }

    #[must_use]
    pub const fn as_i64(&self) -> Option<i64> {
        match self {
            Self::Int(i) => Some(*i),
            _ => None,
        }
    }

    #[must_use]
    pub fn as_array(&self) -> Option<&[Self]> {
        match self {
            Self::Array(items) => Some(items),
            _ => None,
        }
    }

    /// The object's keys in document order, for "unknown member" reporting.
    #[must_use]
    pub fn keys(&self) -> Vec<&str> {
        match self {
            Self::Object(entries) => entries.iter().map(|(k, _)| k.as_str()).collect(),
            _ => Vec::new(),
        }
    }

    /// A short type name, for messages that have to say what was found.
    #[must_use]
    pub const fn type_name(&self) -> &'static str {
        match self {
            Self::Null => "null",
            Self::Bool(_) => "bool",
            Self::Int(_) => "integer",
            Self::Str(_) => "string",
            Self::Array(_) => "array",
            Self::Object(_) => "object",
        }
    }

    /// The **canonical** form: keys sorted by code point, no insignificant
    /// whitespace, UTF-8. This names an input; it is not how an artifact is
    /// rendered (see [`Self::to_pretty`]).
    #[must_use]
    pub fn to_canonical(&self) -> String {
        let mut out = String::new();
        self.write_canonical(&mut out);
        out
    }

    fn write_canonical(&self, out: &mut String) {
        match self {
            Self::Null => out.push_str("null"),
            Self::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Self::Int(i) => out.push_str(&i.to_string()),
            Self::Str(s) => write_escaped(s, out),
            Self::Array(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i != 0 {
                        out.push(',');
                    }
                    item.write_canonical(out);
                }
                out.push(']');
            }
            Self::Object(entries) => {
                // Sorted by the key's code points, which for Rust `str` is the
                // byte-wise UTF-8 order — the same order CPython's
                // `sort_keys=True` produces.
                let mut sorted: Vec<&(String, Self)> = entries.iter().collect();
                sorted.sort_by(|a, b| a.0.cmp(&b.0));
                out.push('{');
                for (i, (key, value)) in sorted.iter().enumerate() {
                    if i != 0 {
                        out.push(',');
                    }
                    write_escaped(key, out);
                    out.push(':');
                    value.write_canonical(out);
                }
                out.push('}');
            }
        }
    }

    /// The **rendering** form: document order, 2-space indent, `": "` after a
    /// key — byte-for-byte `json.dumps(..., indent=2, ensure_ascii=False)`.
    /// The trailing newline is the caller's (an artifact file carries one).
    #[must_use]
    pub fn to_pretty(&self) -> String {
        let mut out = String::new();
        self.write_pretty(0, &mut out);
        out
    }

    fn write_pretty(&self, level: usize, out: &mut String) {
        let inner = level.saturating_add(1);
        match self {
            Self::Null | Self::Bool(_) | Self::Int(_) | Self::Str(_) => self.write_canonical(out),
            Self::Array(items) => {
                if items.is_empty() {
                    out.push_str("[]");
                    return;
                }
                out.push_str("[\n");
                for (i, item) in items.iter().enumerate() {
                    if i != 0 {
                        out.push_str(",\n");
                    }
                    indent(inner, out);
                    item.write_pretty(inner, out);
                }
                out.push('\n');
                indent(level, out);
                out.push(']');
            }
            Self::Object(entries) => {
                if entries.is_empty() {
                    out.push_str("{}");
                    return;
                }
                out.push_str("{\n");
                for (i, (key, value)) in entries.iter().enumerate() {
                    if i != 0 {
                        out.push_str(",\n");
                    }
                    indent(inner, out);
                    write_escaped(key, out);
                    out.push_str(": ");
                    value.write_pretty(inner, out);
                }
                out.push('\n');
                indent(level, out);
                out.push('}');
            }
        }
    }
}

fn indent(level: usize, out: &mut String) {
    for _ in 0..level.saturating_mul(2) {
        out.push(' ');
    }
}

/// The frozen string-escape rule, shared by both writers: `"` and `\` escaped;
/// the five two-character C0 escapes; every other code point below `U+0020` as
/// `\u00xx` with **lowercase** hex; **everything else raw** — no `\u` for
/// non-ASCII, and none for `U+007F`, `U+2028` or `U+2029`. This is
/// `json.dumps(..., ensure_ascii=False)`, written out rather than inherited,
/// so both engines state the same rule; `tests/fixtures/repro/
/// canonical_torture.facts.json` holds them to it.
fn write_escaped(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{c}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            c if u32::from(c) < 0x20 => {
                // Infallible for a String sink; the Result is discarded rather
                // than unwrapped so the crate keeps its no-panic surface.
                let _ = write!(out, "\\u{:04x}", u32::from(c));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

struct JsonVisitor;

impl<'de> Visitor<'de> for JsonVisitor {
    type Value = Json;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value over the canonical domain (object, array, string, i64 integer, bool, null)")
    }

    fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
        Ok(Json::Null)
    }

    fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
        Ok(Json::Null)
    }

    fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<Self::Value, D::Error> {
        d.deserialize_any(Self)
    }

    fn visit_bool<E: de::Error>(self, v: bool) -> Result<Self::Value, E> {
        Ok(Json::Bool(v))
    }

    fn visit_i64<E: de::Error>(self, v: i64) -> Result<Self::Value, E> {
        Ok(Json::Int(v))
    }

    fn visit_u64<E: de::Error>(self, v: u64) -> Result<Self::Value, E> {
        i64::try_from(v).map(Json::Int).map_err(|_| {
            de::Error::custom(format!(
                "integer {v} is outside the canonical domain [-2**63, 2**63-1]; \
                 spec/OwnIR.md §4.2 bounds every validated coordinate to signed 64 bits"
            ))
        })
    }

    fn visit_f64<E: de::Error>(self, v: f64) -> Result<Self::Value, E> {
        // serde_json reaches here for a genuine float AND for an integer
        // literal too large for u64/i64 — both are outside the domain, and
        // both must refuse rather than round.
        Err(de::Error::custom(format!(
            "the value {v} is outside the canonical domain: the OwnIR vocabulary has no \
             float, and an integer beyond signed 64 bits is not representable in both \
             engines — cross-language byte-agreement is not provable over either"
        )))
    }

    fn visit_str<E: de::Error>(self, v: &str) -> Result<Self::Value, E> {
        Ok(Json::Str(v.to_owned()))
    }

    fn visit_string<E: de::Error>(self, v: String) -> Result<Self::Value, E> {
        Ok(Json::Str(v))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = seq.next_element()? {
            items.push(item);
        }
        Ok(Json::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
        let mut entries: Vec<(String, Json)> = Vec::new();
        while let Some((key, value)) = map.next_entry::<String, Json>()? {
            // Last value wins, first position kept — CPython `dict` semantics
            // for a duplicate key, which is what defines the parsed document
            // the canonical form is taken over.
            if let Some(slot) = entries.iter_mut().find(|(k, _)| *k == key) {
                slot.1 = value;
            } else {
                entries.push((key, value));
            }
        }
        Ok(Json::Object(entries))
    }
}

impl<'de> Deserialize<'de> for Json {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(JsonVisitor)
    }
}

/// Parse one JSON document over the canonical domain.
///
/// # Errors
/// The parser's error for malformed JSON, or a domain refusal (a float, or an
/// integer outside `i64`) — never a rounded or truncated value.
pub fn parse(text: &str) -> Result<Json, serde_json::Error> {
    serde_json::from_str(text)
}
