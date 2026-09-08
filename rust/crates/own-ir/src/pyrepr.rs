//! CPython `repr()` of what CPython's `json` module read — the strict door's
//! Version message interpolates one, so byte parity needs both CPython's
//! spelling *and* CPython's reading.
//!
//! #261 ruling 2a: the `ownir_version` rejection text is **our own text on both
//! sides**, so a divergence there is a Rust bug rather than a boundary. The
//! reference writes
//!
//! ```text
//! OwnIR 'ownir_version' must be an integer, got {ver!r}
//! ```
//!
//! and the oracle for that interpolation is **semantic, not lexical**: it is
//! `repr(json.loads(raw)["ownir_version"])`, not the raw token echoed back. The
//! two differ — `1E-6` reprs as `1e-06` and `1.00` as `1.0` — so a module that
//! echoed the source text would fail parity exactly as surely as one that
//! ignored it.
//!
//! ## Why a `serde_json::Value` is not enough (#261 R2b)
//!
//! R2 built this module over [`Value`] and read byte-parity on the ledger's
//! four controls. That measurement was real and too narrow: `Value` is a
//! **lossy** rendering of the document for `repr` purposes, in two ways no
//! single-key, integer-valued control can see.
//!
//! | what is lost | `Value` says | CPython says |
//! |---|---|---|
//! | object key order (`serde_json::Map` is a `BTreeMap`; `dict` is insertion-ordered) | `{'a': 2, 'b': 1}` | `{'b': 1, 'a': 2}` |
//! | float spelling below `1e-4` (`Display` writes ryū's shortest form; `repr` pads the exponent) | `1e-6` | `1e-06` |
//! | integer precision past `i64` (no `arbitrary_precision`, so an oversized literal arrives as `f64`) | `1e+31` | `10000000000000000000000000000000` |
//!
//! The first two are why [`PyValue`] exists and why [`version_value`] re-reads
//! the **raw text** rather than the parsed tree. Enabling
//! `serde_json/preserve_order` or `arbitrary_precision` would fix them by
//! changing `Value` for the whole workspace — a global semantic change (map
//! iteration order, number equality, `to_value` output) bought to correct one
//! error message, and #260's canonical-domain evidence is measured against the
//! current `Value`. So the re-read is scoped to the one value whose spelling is
//! contractual, on the rejection path only.
//!
//! The third is a **branch** difference rather than a spelling one, and
//! `strict::version` owns it: a Python `int` is arbitrary-precision, so an
//! oversized integral version reaches the reference's *mismatch* arm, not its
//! wrong-type arm (#261 ruling V3).
//!
//! ## What the re-read deliberately does not do
//!
//! It is not a second acceptance gate and it never widens what this crate
//! accepts. `serde_json` remains the only parser whose verdict decides
//! accept/reject; [`PyValue`] only decides how an already-certain rejection is
//! *spelled*. Two consequences are declared rather than emulated:
//!
//! * the reference's non-finite constants (`NaN`, `Infinity`) are CPython
//!   `json` extensions this parser rejects as malformed — #261 ruling V1, a
//!   declared reference defect, not a parity target;
//! * the literal `-0` is an `int` to CPython and an `f64` to `serde_json` —
//!   #261 ruling V2, the same cross-parser encoding defect `tests/fixtures/repro`
//!   froze for #260. Where the two parsers disagree about a value's *type*, the
//!   re-read stands down and this crate reports what **its own** parser read,
//!   because a message naming a type we did not read would be a second defect
//!   dressed as a fix. That is the one `Int` case [`version_value`]'s caller
//!   discards.
//!
//! ## Why this lives here, and why it is a third copy
//!
//! The same string helper exists in `own-syntax` (for `ParseError`/`LexError`)
//! and in `own-cli` (for the `--format` usage errors). `own-ir` is the DAG leaf
//! — it may depend on no workspace crate at all — so it cannot import either. A
//! shared `own-pyparity` leaf is the standing tail (see
//! `docs/notes/p022-cli-ownir.md` §6); until it exists, the alternative to this
//! copy is a Version message that is knowingly wrong, which #261 ruling 2a
//! exists to forbid.
//!
//! `unicode-properties` is added to this crate for the same reason
//! `own-syntax` carries it: `str.isprintable()` is a Unicode general-category
//! question, and guessing it would reintroduce exactly the residual divergence
//! this module is here to remove.

// This module is prose about CPython, and `doc_markdown` reads the name as an
// un-backticked item on every mention. Backticking a proper noun mid-sentence
// twenty times reads worse than the warning it silences, so the allow is
// scoped to this file rather than the lint being weakened workspace-wide.
#![allow(clippy::doc_markdown)]

use std::fmt::Write as _;

use serde_json::Value;
use unicode_properties::{GeneralCategory, UnicodeGeneralCategory};

/// CPython `str.isprintable()` for one char: false exactly for the general
/// categories Cc, Cf, Cs, Co, Cn, Zl, Zp and Zs-other-than-space.
fn is_printable(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    !matches!(
        c.general_category(),
        GeneralCategory::Control
            | GeneralCategory::Format
            | GeneralCategory::Surrogate
            | GeneralCategory::PrivateUse
            | GeneralCategory::Unassigned
            | GeneralCategory::LineSeparator
            | GeneralCategory::ParagraphSeparator
            | GeneralCategory::SpaceSeparator
    )
}

/// `repr(s)` for a string: single quotes by default, double quotes when the
/// string contains a `'` and no `"`; the backslash, the chosen quote, `\n`,
/// `\r` and `\t` escaped; every other non-printable character as
/// `\xNN` / `\uNNNN` / `\UNNNNNNNN` by code-point width; printable characters,
/// non-ASCII included, left alone.
fn py_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len().saturating_add(2));
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if !is_printable(c) => {
                // CPython picks the escape by code-point width. `write!` into a
                // String cannot fail; the Ok(()) is discarded rather than
                // unwrapped (the workspace denies `unwrap_used`).
                let cp = c as u32;
                if cp < 0x100 {
                    let _ = write!(out, "\\x{cp:02x}");
                } else if cp < 0x1_0000 {
                    let _ = write!(out, "\\u{cp:04x}");
                } else {
                    let _ = write!(out, "\\U{cp:08x}");
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `repr(f)` for a finite Python float.
///
/// CPython's float repr is *shortest round-trip digits, then a presentation
/// rule* (`Python/pystrtod.c::format_float_short`, mode `'r'`), and both halves
/// have to be reproduced.
///
/// ## The digits, and the tie Rust breaks the other way
///
/// Rust's `{:e}` is also shortest-round-trip, so it agrees with CPython on the
/// *number* of digits — but not always on the last one. When a double's exact
/// value sits **exactly midway** between two candidates of that length, CPython
/// (David Gay's `dtoa`) rounds half to even and Rust's shortest formatter does
/// not: `-1128910513108089.25` is `-1128910513108089.2` to CPython and
/// `-1128910513108089.3` to `{:e}`. A 24 000-value differential sweep found 7
/// such doubles, all of the same shape, and none of them reachable by the four
/// hand-picked controls R2 measured — which is the whole argument for sweeping.
///
/// So the digits come from Rust's **exact** formatter asked for the shortest
/// formatter's length (`{:.*e}`), which rounds half to even. That is not a
/// second opinion about how many digits are needed: the shortest length is a
/// property of the value, and the nearest decimal of that length round-trips
/// whenever any decimal of that length does.
///
/// ## Then the presentation rule
///
/// * with the value written `0.d1d2…dn × 10^decpt`, exponential form is used
///   exactly when `decpt <= -4 || decpt > 16` — which is why `1e15` reprs
///   as `1000000000000000.0` and `1e16` as `1e+16`, and why `0.0001` reprs
///   in full but `1e-05` does not;
/// * the exponent is **always signed and at least two digits** (`1e+16`,
///   `1e-06`), where Rust's `{:e}` writes `1e16` and `1e-6`. That padding is
///   the whole of R2's number defect;
/// * fixed form always keeps a fractional part, so an integral float is
///   `1.0` rather than `1` (CPython's `Py_DTSF_ADD_DOT_0`).
///
/// Non-finite inputs cannot arise from a JSON literal — #261 ruling V1 — but
/// the function is total rather than partial, because a caller that has to
/// remember a precondition is a caller that will one day forget it.
fn py_repr_float(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_owned();
    }
    if x.is_infinite() {
        return if x.is_sign_negative() {
            "-inf".to_owned()
        } else {
            "inf".to_owned()
        };
    }

    // "-1.25e-7" — shortest round-trip mantissa, unpadded signed exponent.
    let shortest = format!("{x:e}");
    let significant = shortest
        .split_once('e')
        .map_or(shortest.as_str(), |(mantissa, _)| mantissa)
        .chars()
        .filter(char::is_ascii_digit)
        .count();
    // Re-ask at that length in EXACT mode, which rounds half to even as
    // CPython does. A carry out of the leading digit (9.99…9 rounding to
    // 1.0…0e+1) changes the exponent, so the exponent is read from THIS
    // string rather than from the shortest one.
    let rendered = format!("{x:.*e}", significant.saturating_sub(1));
    // `LowerExp` for f64 always writes an `e`; if that ever stops being true,
    // the rendered form is still a truthful rendering of the value.
    let Some((mantissa, exponent)) = rendered.split_once('e') else {
        return rendered;
    };
    let Ok(exp10) = exponent.parse::<i32>() else {
        return rendered;
    };
    let sign = if mantissa.starts_with('-') { "-" } else { "" };
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    // `0.d1d2…dn × 10^decpt`, CPython's `decpt`.
    let decpt = exp10.saturating_add(1);

    if decpt <= -4 || decpt > 16 {
        let mut chars = digits.chars();
        let lead = chars.next().unwrap_or('0');
        let rest: String = chars.collect();
        let point = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        let exp_sign = if exp10 < 0 { '-' } else { '+' };
        let magnitude = exp10.unsigned_abs();
        return format!("{sign}{lead}{point}e{exp_sign}{magnitude:02}");
    }
    if decpt <= 0 {
        let zeros = "0".repeat(usize::try_from(decpt.unsigned_abs()).unwrap_or(0));
        return format!("{sign}0.{zeros}{digits}");
    }
    let point = usize::try_from(decpt).unwrap_or(0);
    if point >= digits.len() {
        let zeros = "0".repeat(point.saturating_sub(digits.len()));
        return format!("{sign}{digits}{zeros}.0");
    }
    match (digits.get(..point), digits.get(point..)) {
        (Some(whole), Some(frac)) => format!("{sign}{whole}.{frac}"),
        // Unreachable: `digits` is ASCII, so every index is a boundary.
        _ => rendered,
    }
}

/// A value as CPython's `json` module decodes it.
///
/// The three things this holds that a [`Value`] cannot: a `dict` remembers
/// **insertion order**, an `int` is **arbitrary precision** (kept as its
/// canonical decimal digits rather than narrowed to `i64`), and `int` and
/// `float` are distinguished by the *literal's* shape — `1` is an int and
/// `1.0` a float — rather than by what a numeric type could hold.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum PyValue {
    None,
    Bool(bool),
    /// Canonical decimal digits, exactly as `str(int(token))` writes them.
    Int(String),
    Float(f64),
    Str(String),
    List(Vec<Self>),
    /// Insertion-ordered, like `dict`. A repeated key keeps its **first**
    /// position and takes its **last** value, which is what CPython's decoder
    /// does and what `{"b": 1, "a": 2, "b": 3}` → `{'b': 3, 'a': 2}` measures.
    Dict(Vec<(String, Self)>),
}

/// `repr(value)` as CPython writes it.
///
/// Containers recurse, because `json` decodes them to `list`/`dict` and `repr`
/// of those reprs their members: `["a"]` is `['a']`, not `["a"]`.
pub(crate) fn py_repr(value: &PyValue) -> String {
    match value {
        PyValue::None => "None".to_owned(),
        PyValue::Bool(true) => "True".to_owned(),
        PyValue::Bool(false) => "False".to_owned(),
        PyValue::Int(digits) => digits.clone(),
        PyValue::Float(f) => py_repr_float(*f),
        PyValue::Str(s) => py_repr_str(s),
        PyValue::List(items) => {
            let inner: Vec<String> = items.iter().map(py_repr).collect();
            format!("[{}]", inner.join(", "))
        }
        PyValue::Dict(pairs) => {
            let inner: Vec<String> = pairs
                .iter()
                .map(|(k, v)| format!("{}: {}", py_repr_str(k), py_repr(v)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
    }
}

/// The lossy reading: what a [`Value`] can still say about a Python value once
/// the document text is gone.
///
/// Used only where there is no raw text to re-read — the in-memory door
/// (`OwnIr::validate`), whose `ownir_version` is a typed `Option<i64>` and so
/// cannot reach the wrong-type message at all except through a hand-built
/// `extra` collision. Object order is `Map`'s (sorted) and an oversized integer
/// has already been flattened to `f64`; both are recorded here rather than in a
/// comment on the caller, because this is where a future reader will look.
fn from_json_value(value: &Value) -> PyValue {
    match value {
        Value::Null => PyValue::None,
        Value::Bool(b) => PyValue::Bool(*b),
        Value::Number(n) => n.as_i64().map_or_else(
            || {
                n.as_u64().map_or_else(
                    || PyValue::Float(n.as_f64().unwrap_or(f64::NAN)),
                    |u| PyValue::Int(u.to_string()),
                )
            },
            |i| PyValue::Int(i.to_string()),
        ),
        Value::String(s) => PyValue::Str(s.clone()),
        Value::Array(items) => PyValue::List(items.iter().map(from_json_value).collect()),
        Value::Object(entries) => PyValue::Dict(
            entries
                .iter()
                .map(|(k, v)| (k.clone(), from_json_value(v)))
                .collect(),
        ),
    }
}

/// `repr` of a value read from a [`Value`] — the fallback spelling.
pub(crate) fn py_repr_value(value: &Value) -> String {
    py_repr(&from_json_value(value))
}

/// The re-read's recursion bound. `serde_json`'s own parser refuses past 128
/// nested values, so nothing [`crate::OwnIr::from_json`] accepted can exceed
/// it; the guard exists so this reader's totality does not *depend* on that
/// remaining true.
const MAX_DEPTH: u32 = 128;

/// Read `json.loads(text)["ownir_version"]` out of the raw document, keeping
/// what `Value` drops.
///
/// `None` means "this reader could not answer" — a non-object root, no such
/// key, or any byte it did not expect — and the caller falls back to the
/// [`Value`] spelling. It is deliberately not an error type: this function
/// cannot make a document invalid, only better-spelled, and a reader that
/// could veto a rejection would be a second acceptance gate.
///
/// Only the matching member is retained; every other root value is read and
/// dropped, so peak cost is one member's tree rather than the document's.
pub(crate) fn version_value(text: &str) -> Option<PyValue> {
    let mut reader = Reader::new(text);
    reader.skip_ws();
    reader.eat(b'{')?;
    reader.skip_ws();
    if reader.eat(b'}').is_some() {
        return None;
    }
    let mut found = None;
    loop {
        reader.skip_ws();
        let key = reader.string()?;
        reader.skip_ws();
        reader.eat(b':')?;
        let value = reader.value(1)?;
        if key == "ownir_version" {
            // Last binding wins, as CPython's decoder does for a repeated key.
            found = Some(value);
        }
        reader.skip_ws();
        match reader.peek()? {
            b',' => reader.bump(),
            b'}' => return found,
            _ => return None,
        }
    }
}

/// A cursor over already-valid JSON text.
///
/// Hand-rolled rather than delegated because the two things it exists to
/// preserve — member order and the exact integer token — are precisely what
/// `serde_json::Value` discards, and the features that would keep them
/// (`preserve_order`, `arbitrary_precision`) change `Value` for every crate in
/// the workspace. Every method returns `Option`, so malformed input ends the
/// read rather than panicking.
#[derive(Debug)]
struct Reader<'a> {
    text: &'a str,
    pos: usize,
}

impl<'a> Reader<'a> {
    const fn new(text: &'a str) -> Self {
        Self { text, pos: 0 }
    }

    fn peek(&self) -> Option<u8> {
        self.text.as_bytes().get(self.pos).copied()
    }

    fn peek_char(&self) -> Option<char> {
        self.text
            .get(self.pos..)
            .and_then(|rest| rest.chars().next())
    }

    fn bump(&mut self) {
        self.pos = self.pos.saturating_add(1);
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.bump();
        }
    }

    fn eat(&mut self, byte: u8) -> Option<()> {
        if self.peek() == Some(byte) {
            self.bump();
            Some(())
        } else {
            None
        }
    }

    fn word(&mut self, literal: &str) -> Option<()> {
        let end = self.pos.saturating_add(literal.len());
        if self.text.get(self.pos..end) == Some(literal) {
            self.pos = end;
            Some(())
        } else {
            None
        }
    }

    fn value(&mut self, depth: u32) -> Option<PyValue> {
        if depth > MAX_DEPTH {
            return None;
        }
        self.skip_ws();
        match self.peek()? {
            b'n' => self.word("null").map(|()| PyValue::None),
            b't' => self.word("true").map(|()| PyValue::Bool(true)),
            b'f' => self.word("false").map(|()| PyValue::Bool(false)),
            b'"' => self.string().map(PyValue::Str),
            b'[' => self.list(depth),
            b'{' => self.dict(depth),
            b'-' | b'0'..=b'9' => self.number(),
            _ => None,
        }
    }

    /// A number token, split the way CPython's decoder splits it: a literal
    /// with a fraction or an exponent is a `float`, anything else an `int` of
    /// arbitrary precision. That split is the whole of ruling V3 — `1e+31` and
    /// `10000000000000000000000000000000` are the same `f64` and *different*
    /// Python values.
    fn number(&mut self) -> Option<PyValue> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.bump();
        }
        let digits_at = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.bump();
        }
        if self.pos == digits_at {
            return None;
        }
        let mut fractional = false;
        if self.peek() == Some(b'.') {
            fractional = true;
            self.bump();
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.bump();
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            fractional = true;
            self.bump();
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.bump();
            }
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.bump();
            }
        }
        let token = self.text.get(start..self.pos)?;
        if fractional {
            token.parse::<f64>().ok().map(PyValue::Float)
        } else {
            Some(PyValue::Int(canonical_int(token)))
        }
    }

    fn string(&mut self) -> Option<String> {
        self.eat(b'"')?;
        let mut out = String::new();
        loop {
            let c = self.peek_char()?;
            match c {
                '"' => {
                    self.bump();
                    return Some(out);
                }
                '\\' => {
                    self.bump();
                    out.push(self.escape()?);
                }
                _ => {
                    self.pos = self.pos.saturating_add(c.len_utf8());
                    out.push(c);
                }
            }
        }
    }

    fn escape(&mut self) -> Option<char> {
        let code = self.peek()?;
        self.bump();
        let c = match code {
            b'"' => '"',
            b'\\' => '\\',
            b'/' => '/',
            b'b' => '\u{8}',
            b'f' => '\u{c}',
            b'n' => '\n',
            b'r' => '\r',
            b't' => '\t',
            b'u' => return self.escaped_scalar(),
            _ => return None,
        };
        Some(c)
    }

    /// `\uXXXX`, and the surrogate **pair** an astral scalar is written as.
    fn escaped_scalar(&mut self) -> Option<char> {
        let unit = self.hex4()?;
        if !(0xd800..0xdc00).contains(&unit) {
            return char::from_u32(u32::from(unit));
        }
        self.eat(b'\\')?;
        self.eat(b'u')?;
        let low = self.hex4()?;
        let lead = u32::from(unit).checked_sub(0xd800)?;
        let trail = u32::from(low).checked_sub(0xdc00)?;
        if trail > 0x3ff {
            return None;
        }
        let scalar = lead
            .checked_mul(0x400)?
            .checked_add(trail)?
            .checked_add(0x1_0000)?;
        char::from_u32(scalar)
    }

    fn hex4(&mut self) -> Option<u16> {
        let end = self.pos.saturating_add(4);
        let digits = self.text.get(self.pos..end)?;
        let unit = u16::from_str_radix(digits, 16).ok()?;
        self.pos = end;
        Some(unit)
    }

    fn list(&mut self, depth: u32) -> Option<PyValue> {
        self.eat(b'[')?;
        let mut items = Vec::new();
        self.skip_ws();
        if self.eat(b']').is_some() {
            return Some(PyValue::List(items));
        }
        loop {
            items.push(self.value(depth.saturating_add(1))?);
            self.skip_ws();
            match self.peek()? {
                b',' => self.bump(),
                b']' => {
                    self.bump();
                    return Some(PyValue::List(items));
                }
                _ => return None,
            }
        }
    }

    fn dict(&mut self, depth: u32) -> Option<PyValue> {
        self.eat(b'{')?;
        let mut pairs: Vec<(String, PyValue)> = Vec::new();
        self.skip_ws();
        if self.eat(b'}').is_some() {
            return Some(PyValue::Dict(pairs));
        }
        loop {
            self.skip_ws();
            let key = self.string()?;
            self.skip_ws();
            self.eat(b':')?;
            let value = self.value(depth.saturating_add(1))?;
            bind(&mut pairs, key, value);
            self.skip_ws();
            match self.peek()? {
                b',' => self.bump(),
                b'}' => {
                    self.bump();
                    return Some(PyValue::Dict(pairs));
                }
                _ => return None,
            }
        }
    }
}

/// `d[key] = value` with `dict` semantics: a repeated key is **rebound in
/// place**, so it keeps the position of its first appearance and the value of
/// its last.
fn bind(pairs: &mut Vec<(String, PyValue)>, key: String, value: PyValue) {
    if let Some(slot) = pairs.iter_mut().find(|(k, _)| *k == key) {
        slot.1 = value;
    } else {
        pairs.push((key, value));
    }
}

/// `str(int(token))` for a JSON integer literal.
///
/// JSON forbids a leading zero and a leading `+`, so the literal is already
/// canonical for every value but one: `int("-0")` is `0`, and Python spells it
/// `0`.
fn canonical_int(token: &str) -> String {
    let magnitude = token.strip_prefix('-').unwrap_or(token);
    if !magnitude.is_empty() && magnitude.bytes().all(|b| b == b'0') {
        return "0".to_owned();
    }
    token.to_owned()
}

#[cfg(test)]
#[allow(clippy::expect_used)]
mod tests {
    use super::{py_repr, py_repr_float, py_repr_str, py_repr_value, version_value, PyValue};
    use serde_json::Value;

    /// `repr` of the version member, read from the RAW document — the oracle
    /// the reference actually evaluates.
    fn version_repr(document: &str) -> String {
        py_repr(&version_value(document).expect("the reader reads a valid document"))
    }

    /// The same value put through the lossy [`Value`] reading, so the tests
    /// below can state *which* spelling each path produces rather than
    /// asserting one and hoping the other agrees.
    fn value_repr(text: &str) -> String {
        let value: Value = serde_json::from_str(text).expect("valid JSON");
        py_repr_value(&value)
    }

    /// The exact `ownir_version` values the validation ledger carries, against
    /// CPython's `repr` as measured on this tree. These four are the reason
    /// this module exists.
    #[test]
    fn matches_cpython_for_every_version_control() {
        assert_eq!(value_repr(r#""0""#), "'0'");
        assert_eq!(value_repr("true"), "True");
        assert_eq!(value_repr("0.0"), "0.0");
        assert_eq!(value_repr("null"), "None");
    }

    /// The rest of the JSON scalar surface, and the containers `json` decodes
    /// to `list`/`dict` — whose members are repr'd, not JSON-rendered.
    #[test]
    fn matches_cpython_for_the_rest_of_the_json_surface() {
        assert_eq!(value_repr("false"), "False");
        assert_eq!(value_repr(r#""x""#), "'x'");
        assert_eq!(value_repr("5"), "5");
        assert_eq!(value_repr("-3"), "-3");
        assert_eq!(value_repr("[1]"), "[1]");
        assert_eq!(value_repr(r#"["a"]"#), "['a']");
        assert_eq!(value_repr(r#"{"a": 1}"#), "{'a': 1}");
        assert_eq!(value_repr("[true, null]"), "[True, None]");
    }

    /// CPython's quoting rules, including the quote switch.
    #[test]
    fn matches_cpython_quoting() {
        assert_eq!(py_repr_str(""), "''");
        assert_eq!(py_repr_str("it's"), "\"it's\"");
        assert_eq!(py_repr_str("say \"hi\""), "'say \"hi\"'");
        assert_eq!(py_repr_str("both ' and \""), "'both \\' and \"'");
        assert_eq!(py_repr_str("a\nb\tc\\d"), "'a\\nb\\tc\\\\d'");
    }

    /// Printability is a general-category question, which is why this crate
    /// carries `unicode-properties` rather than guessing at it.
    #[test]
    fn matches_cpython_printability() {
        assert_eq!(py_repr_str("\u{1}"), r"'\x01'");
        assert_eq!(py_repr_str("\u{a0}"), r"'\xa0'"); // Zs NBSP
        assert_eq!(py_repr_str("\u{200b}"), r"'\u200b'"); // Cf
        assert_eq!(py_repr_str("\u{2028}"), r"'\u2028'"); // Zl
        assert_eq!(py_repr_str("\u{10ffff}"), r"'\U0010ffff'"); // Cn astral
        assert_eq!(py_repr_str("\u{1f600}"), "'\u{1f600}'"); // So, printable
        assert_eq!(py_repr_str("\u{e9} \u{436}"), "'\u{e9} \u{436}'");
    }

    /// CPython's float presentation rule, measured against `repr()` on this
    /// tree. The two boundaries are the whole rule: `decpt > 16` at the top and
    /// `decpt <= -4` at the bottom, with the exponent always signed and padded
    /// to two digits.
    #[test]
    fn matches_cpython_float_repr() {
        assert_eq!(py_repr_float(0.0), "0.0");
        assert_eq!(py_repr_float(-0.0), "-0.0");
        assert_eq!(py_repr_float(1.0), "1.0");
        assert_eq!(py_repr_float(1.5), "1.5");
        assert_eq!(py_repr_float(-2.25), "-2.25");
        assert_eq!(py_repr_float(0.1), "0.1");
        // Bottom boundary: 1e-4 is written in full, 1e-5 is not.
        assert_eq!(py_repr_float(1e-4), "0.0001");
        assert_eq!(py_repr_float(1e-5), "1e-05");
        assert_eq!(py_repr_float(1e-6), "1e-06");
        assert_eq!(py_repr_float(1.5e-7), "1.5e-07");
        // Top boundary: 1e15 is written in full, 1e16 is not.
        assert_eq!(py_repr_float(1e15), "1000000000000000.0");
        assert_eq!(py_repr_float(1e16), "1e+16");
        assert_eq!(py_repr_float(1.25e17), "1.25e+17");
        assert_eq!(py_repr_float(1e100), "1e+100");
        assert_eq!(py_repr_float(-1e-300), "-1e-300");
        assert_eq!(py_repr_float(123_456_789.25), "123456789.25");
    }

    /// The number defect R2 left behind, stated as the difference it was:
    /// `serde_json`'s `Display` writes ryū's unpadded exponent, CPython pads it.
    #[test]
    fn the_exponent_padding_is_the_defect_r2_left() {
        let one_millionth: Value = serde_json::from_str("1e-6").expect("valid JSON");
        assert_eq!(one_millionth.to_string(), "1e-6");
        assert_eq!(py_repr_value(&one_millionth), "1e-06");
    }

    /// A `dict` is insertion-ordered and `serde_json::Map` is a `BTreeMap`. The
    /// raw re-read is the only one of the two readings that can say so — which
    /// is why a single-key control could never have caught this.
    #[test]
    fn a_dict_keeps_document_order_not_sorted_order() {
        let document = r#"{"ownir_version": {"b": 1, "a": 2}}"#;
        assert_eq!(version_repr(document), "{'b': 1, 'a': 2}");
        assert_eq!(value_repr(r#"{"b": 1, "a": 2}"#), "{'a': 2, 'b': 1}");
    }

    /// A repeated key keeps its FIRST position and its LAST value.
    #[test]
    fn a_repeated_key_is_rebound_in_place() {
        let document = r#"{"ownir_version": {"b": 1, "a": 2, "b": 3}}"#;
        assert_eq!(version_repr(document), "{'b': 3, 'a': 2}");
    }

    /// Order survives nesting, and the members are repr'd all the way down.
    #[test]
    fn order_survives_nesting() {
        let document = r#"{"ownir_version": {"z": [1, {"y": null}, true], "a": "s"}}"#;
        assert_eq!(
            version_repr(document),
            "{'z': [1, {'y': None}, True], 'a': 's'}"
        );
    }

    /// A Python `int` has no width. The reader keeps the digits; `Value` has
    /// already flattened them to an `f64` by the time it is asked.
    #[test]
    fn an_oversized_integer_keeps_its_digits() {
        let document = r#"{"ownir_version": 10000000000000000000000000000000}"#;
        assert_eq!(
            version_value(document),
            Some(PyValue::Int("10000000000000000000000000000000".to_owned()))
        );
        assert_eq!(value_repr("10000000000000000000000000000000"), "1e+31");
    }

    /// `int` versus `float` is decided by the LITERAL, not by what a number
    /// type could hold: `1` is an int, `1.0` and `1e0` are floats.
    #[test]
    fn the_literal_decides_int_or_float() {
        let int = version_value(r#"{"ownir_version": 1}"#);
        assert_eq!(int, Some(PyValue::Int("1".to_owned())));
        let dotted = version_value(r#"{"ownir_version": 1.0}"#);
        assert_eq!(dotted, Some(PyValue::Float(1.0)));
        let exponent = version_value(r#"{"ownir_version": 1e0}"#);
        assert_eq!(exponent, Some(PyValue::Float(1.0)));
        // …and `repr` tells the two apart, which is the point of keeping them.
        assert_eq!(version_repr(r#"{"ownir_version": 1}"#), "1");
        assert_eq!(version_repr(r#"{"ownir_version": 1.0}"#), "1.0");
        assert_eq!(version_repr(r#"{"ownir_version": 1.00}"#), "1.0");
        assert_eq!(version_repr(r#"{"ownir_version": 1E-6}"#), "1e-06");
    }

    /// `int("-0")` is `0`. This is the ONLY literal whose canonical decimal
    /// differs from its token, because JSON forbids leading zeros and `+`.
    #[test]
    fn negative_zero_is_the_only_integer_the_token_misspells() {
        assert_eq!(
            version_value(r#"{"ownir_version": -0}"#),
            Some(PyValue::Int("0".to_owned()))
        );
        assert_eq!(
            version_value(r#"{"ownir_version": -5}"#),
            Some(PyValue::Int("-5".to_owned()))
        );
        assert_eq!(
            version_value(r#"{"ownir_version": 0}"#),
            Some(PyValue::Int("0".to_owned()))
        );
    }

    /// The reader is a *reader*, not a parser: whitespace, escapes and
    /// surrogate pairs all have to survive it, because the value it is asked
    /// about is caller-shaped.
    #[test]
    fn the_reader_handles_the_whole_json_string_surface() {
        assert_eq!(
            version_repr("{ \"ownir_version\"\n:\t\"a\\\"b\\\\c\\n\\u0001\" }"),
            r#"'a"b\\c\n\x01'"#
        );
        assert_eq!(
            version_repr(r#"{"ownir_version": "\ud83d\ude00"}"#),
            "'\u{1f600}'"
        );
        assert_eq!(version_repr(r#"{"ownir_version": "\u00e9"}"#), "'\u{e9}'");
        assert_eq!(
            version_repr(r#"{"ownir_version": "\/\b\f\r\t"}"#),
            r"'/\x08\x0c\r\t'"
        );
        assert_eq!(version_repr(r#"{"ownir_version": []}"#), "[]");
        assert_eq!(version_repr(r#"{"ownir_version": {}}"#), "{}");
        assert_eq!(version_repr(r#"{"ownir_version": [ 1 , 2 ]}"#), "[1, 2]");
    }

    /// The member is found past other members, and a repeated ROOT key takes
    /// its last binding — `json.loads` does the same.
    #[test]
    fn the_root_member_is_found_wherever_it_sits() {
        assert_eq!(
            version_repr(r#"{"components": [], "ownir_version": "x"}"#),
            "'x'"
        );
        assert_eq!(
            version_repr(r#"{"ownir_version": 1, "ownir_version": "last"}"#),
            "'last'"
        );
    }

    /// "Could not answer" is a first-class result: the caller falls back to the
    /// `Value` spelling rather than losing the rejection.
    #[test]
    fn the_reader_declines_rather_than_guessing() {
        assert_eq!(version_value("[]"), None);
        assert_eq!(version_value("{}"), None);
        assert_eq!(version_value(r#"{"other": 1}"#), None);
        assert_eq!(version_value("not json at all"), None);
        assert_eq!(version_value(r#"{"ownir_version": tru"#), None);
    }

    /// Nesting past `serde_json`'s own parser bound cannot reach this reader
    /// through `from_json`, and if it ever did the reader would decline rather
    /// than recurse without limit.
    #[test]
    fn the_reader_declines_past_the_recursion_bound() {
        let deep = format!(
            "{{\"ownir_version\": {}{}}}",
            "[".repeat(200),
            "]".repeat(200)
        );
        assert_eq!(version_value(&deep), None);
        let shallow = format!("{{\"ownir_version\": {}{}}}", "[".repeat(8), "]".repeat(8));
        assert!(version_value(&shallow).is_some());
    }
}
