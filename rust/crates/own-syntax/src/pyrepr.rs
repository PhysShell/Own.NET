//! Python `repr()` emulation for strings — the error-message parity tool.
//!
//! Both Python exception formats interpolate `repr()` of token text
//! (`ParseError`: `... (got {kind} {text!r})`; `LexError`:
//! `unexpected character {c!r}`), so byte-identical error messages require
//! reproducing `CPython`'s quoting rules:
//!
//! * single quotes by default; **double quotes** when the string contains a
//!   `'` and no `"`;
//! * escape the backslash, the chosen quote, `\n`, `\r`, `\t`;
//! * every other character `str.isprintable()` rejects — C0/C1 controls, DEL,
//!   format chars (a pasted U+200B/BOM), separators, private-use, unassigned —
//!   as `\xNN` / `\uNNNN` / `\UNNNNNNNN` by code-point width;
//! * printable characters (including non-ASCII) stay as-is (Python 3 `repr`).
//!
//! `is_printable` mirrors `CPython`'s `str.isprintable()`: false exactly for
//! general categories Cc, Cf, Cs, Co, Cn, Zl, Zp and Zs-other-than-space.

use std::fmt::Write as _;

use unicode_properties::{GeneralCategory, UnicodeGeneralCategory};

/// `CPython` `str.isprintable()` for one char. (Cs is unreachable — a Rust
/// `char` is never a surrogate — but harmless to name.)
fn is_printable(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    !matches!(
        c.general_category(),
        GeneralCategory::Control            // Cc
            | GeneralCategory::Format       // Cf
            | GeneralCategory::Surrogate    // Cs
            | GeneralCategory::PrivateUse   // Co
            | GeneralCategory::Unassigned   // Cn
            | GeneralCategory::LineSeparator      // Zl
            | GeneralCategory::ParagraphSeparator // Zp
            | GeneralCategory::SpaceSeparator // Zs (space itself handled above)
    )
}

// pub(crate) in a private module is technically redundant (nursery lint), but
// plain `pub` here trips the denied `unreachable_pub` — keep the honest scope.
#[allow(clippy::redundant_pub_crate)]
#[must_use]
pub(crate) fn py_repr(s: &str) -> String {
    let has_single = s.contains('\'');
    let has_double = s.contains('"');
    let quote = if has_single && !has_double { '"' } else { '\'' };
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
                // CPython picks the escape by code-point width. write! into a
                // String cannot fail; ignore the Ok(()).
                let cp = c as u32;
                if cp < 0x100 {
                    let _ = write!(out, "\\x{cp:02x}");
                } else if cp < 0x10000 {
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

#[cfg(test)]
mod tests {
    use super::py_repr;

    #[test]
    fn matches_cpython_quoting() {
        assert_eq!(py_repr("abc"), "'abc'");
        assert_eq!(py_repr(""), "''");
        assert_eq!(py_repr("it's"), "\"it's\"");
        assert_eq!(py_repr("say \"hi\""), "'say \"hi\"'");
        assert_eq!(py_repr("both ' and \""), "'both \\' and \"'");
        assert_eq!(py_repr("a\nb\tc\\d"), "'a\\nb\\tc\\\\d'");
        assert_eq!(py_repr("\u{1}"), "'\\x01'");
        assert_eq!(py_repr("@"), "'@'");
    }

    /// Expectations produced by running `CPython` `repr()` on each char
    /// (`str.isprintable()` categories: Cc, Cf, Co, Cn, Zl, Zp, Zs≠space).
    #[test]
    fn matches_cpython_nonprintable_escapes() {
        assert_eq!(py_repr("\u{200b}"), r"'\u200b'"); // Cf zero-width space
        assert_eq!(py_repr("\u{feff}"), r"'\ufeff'"); // Cf BOM
        assert_eq!(py_repr("\u{a0}"), r"'\xa0'"); // Zs NBSP — \xNN below U+0100
        assert_eq!(py_repr("\u{85}"), r"'\x85'"); // Cc C1 control
        assert_eq!(py_repr("\u{2028}"), r"'\u2028'"); // Zl line separator
        assert_eq!(py_repr("\u{2029}"), r"'\u2029'"); // Zp paragraph separator
        assert_eq!(py_repr("\u{3000}"), r"'\u3000'"); // Zs ideographic space
        assert_eq!(py_repr("\u{378}"), r"'\u0378'"); // Cn unassigned
        assert_eq!(py_repr("\u{e000}"), r"'\ue000'"); // Co private use
        assert_eq!(py_repr("\u{10ffff}"), r"'\U0010ffff'"); // Cn astral
        assert_eq!(py_repr("\u{1f600}"), "'\u{1f600}'"); // So printable emoji
        assert_eq!(py_repr("é ж"), "'é ж'"); // printable non-ASCII + space
    }
}
