//! CPython `repr()` for a `serde_json::Value` — the strict door's Version
//! message interpolates one, so byte parity needs CPython's spelling.
//!
//! #261 ruling 2a: the `ownir_version` rejection text is **our own text on both
//! sides**, so a divergence there is a Rust bug rather than a boundary. The
//! reference writes
//!
//! ```text
//! OwnIR 'ownir_version' must be an integer, got {ver!r}
//! ```
//!
//! and `{ver!r}` is a Python `repr`, not a JSON rendering. Measured on this
//! tree, `serde_json::Value`'s `Display` disagrees with it four ways:
//!
//! | value | CPython `repr` | `Value` `Display` |
//! |---|---|---|
//! | `"0"` | `'0'` | `"0"` |
//! | `true` / `false` | `True` / `False` | `true` / `false` |
//! | `null` | `None` | `null` |
//! | `["a"]` | `['a']` | `["a"]` |
//! | `0.0` | `0.0` | `0.0` (already agree) |
//!
//! ## Why this lives here, and why it is a third copy
//!
//! The same helper exists in `own-syntax` (for `ParseError`/`LexError`) and in
//! `own-cli` (for the `--format` usage errors). `own-ir` is the DAG leaf — it
//! may depend on no workspace crate at all — so it cannot import either. A
//! shared `own-pyparity` leaf is the standing tail (see
//! `docs/notes/p022-cli-ownir.md` §6); until it exists, the alternative to this
//! copy is a Version message that is knowingly wrong, which #261 ruling 2a
//! exists to forbid.
//!
//! `unicode-properties` is added to this crate for the same reason
//! `own-syntax` carries it: `str.isprintable()` is a Unicode general-category
//! question, and guessing it would reintroduce exactly the residual divergence
//! this module is here to remove.

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

/// `repr(value)` as CPython writes it for a value decoded by `json.load`.
///
/// Containers recurse, because `json` decodes them to `list`/`dict` and `repr`
/// of those reprs their members: `["a"]` is `['a']`, not `["a"]`.
pub(crate) fn py_repr_value(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        // A JSON number's spelling already matches Python's `repr` for the
        // forms `json` produces — an integer prints bare and a float keeps its
        // `.0`, which `serde_json` preserves because it distinguishes the two.
        Value::Number(n) => n.to_string(),
        Value::String(s) => py_repr_str(s),
        Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(py_repr_value).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Object(entries) => {
            let inner: Vec<String> = entries
                .iter()
                .map(|(k, v)| format!("{}: {}", py_repr_str(k), py_repr_value(v)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
    }
}

#[cfg(test)]
#[allow(clippy::expect_used)]
mod tests {
    use super::{py_repr_str, py_repr_value};
    use serde_json::Value;

    fn repr(text: &str) -> String {
        let value: Value = serde_json::from_str(text).expect("valid JSON");
        py_repr_value(&value)
    }

    /// The exact `ownir_version` values the validation ledger carries, against
    /// CPython's `repr` as measured on this tree. These four are the reason
    /// this module exists.
    #[test]
    fn matches_cpython_for_every_version_control() {
        assert_eq!(repr(r#""0""#), "'0'");
        assert_eq!(repr("true"), "True");
        assert_eq!(repr("0.0"), "0.0");
        assert_eq!(repr("null"), "None");
    }

    /// The rest of the JSON scalar surface, and the containers `json` decodes
    /// to `list`/`dict` — whose members are repr'd, not JSON-rendered.
    #[test]
    fn matches_cpython_for_the_rest_of_the_json_surface() {
        assert_eq!(repr("false"), "False");
        assert_eq!(repr(r#""x""#), "'x'");
        assert_eq!(repr("5"), "5");
        assert_eq!(repr("-3"), "-3");
        assert_eq!(repr("[1]"), "[1]");
        assert_eq!(repr(r#"["a"]"#), "['a']");
        assert_eq!(repr(r#"{"a": 1}"#), "{'a': 1}");
        assert_eq!(repr(r#"[true, null]"#), "[True, None]");
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
}
