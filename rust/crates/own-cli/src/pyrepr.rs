//! CPython `repr()` emulation for strings — the usage-message parity tool.
//!
//! The reference interpolates `repr()` of a rejected flag value:
//!
//! ```text
//! unknown --format {fmt!r} (choose: github, human, json, msbuild, sarif)
//! ```
//!
//! so a byte-identical usage error needs CPython's quoting rules, not Rust's
//! `{:?}` (which would render `it's` as `"it's"` where CPython also picks the
//! double quote, but renders `a\u{1}b` as `"a\u{1}b"` where CPython writes
//! `'a\x01b'`, and escapes printable non-ASCII where CPython does not).
//!
//! **Provenance, and why this is a copy.** The identical helper already exists
//! as `own_syntax::pyrepr::py_repr`, where it serves the parser's `ParseError`
//! / `LexError` text. It is `pub(crate)` there, and exporting it would need an
//! `own-cli -> own-syntax` edge that #261's architecture section does not admit
//! (`own-cli` depends on `own-ir` and `own-bridge`, and nothing else unless the
//! compiler proves otherwise). A forbidden edge is a worse trade than a
//! forty-line pure function carried twice, so the function is carried twice and
//! the duplication is recorded as a tail: a shared `own-pyparity` leaf is the
//! eventual home, and #345 — which adds the commands whose errors interpolate
//! far more `repr()`s — is where it starts to pay.
//!
//! `is_printable` mirrors CPython's `str.isprintable()`: false exactly for the
//! general categories Cc, Cf, Cs, Co, Cn, Zl, Zp and Zs-other-than-space.

use std::fmt::Write as _;

use unicode_properties::{GeneralCategory, UnicodeGeneralCategory};

/// CPython `str.isprintable()` for one char. (Cs is unreachable — a Rust
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

/// `repr(s)` as CPython writes it: single quotes by default, double quotes
/// when the string contains a `'` and no `"`; the backslash, the chosen quote,
/// `\n`, `\r` and `\t` escaped; every other non-printable character as
/// `\xNN` / `\uNNNN` / `\UNNNNNNNN` by code-point width; printable characters,
/// non-ASCII included, left alone.
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

#[cfg(test)]
mod tests {
    use super::py_repr;

    /// The values a `--format`/`--severity`/`--verbosity` error can actually
    /// carry, and the quoting rules behind them. The first three are frozen by
    /// fixture cases (`usage-format-invalid`, `usage-format-empty-value`,
    /// `usage-format-value-is-a-flag`); the rest keep the helper honest for
    /// the values a user could still type.
    #[test]
    fn matches_cpython_quoting() {
        assert_eq!(py_repr("x"), "'x'");
        assert_eq!(py_repr(""), "''");
        assert_eq!(py_repr("--severity"), "'--severity'");
        assert_eq!(py_repr("it's"), "\"it's\"");
        assert_eq!(py_repr("say \"hi\""), "'say \"hi\"'");
        assert_eq!(py_repr("both ' and \""), "'both \\' and \"'");
        assert_eq!(py_repr("a\nb\tc\\d"), "'a\\nb\\tc\\\\d'");
        assert_eq!(py_repr("\u{1}"), "'\\x01'");
    }

    /// Produced by running CPython `repr()` on each character.
    #[test]
    fn matches_cpython_nonprintable_escapes() {
        assert_eq!(py_repr("\u{200b}"), r"'\u200b'"); // Cf zero-width space
        assert_eq!(py_repr("\u{feff}"), r"'\ufeff'"); // Cf BOM
        assert_eq!(py_repr("\u{a0}"), r"'\xa0'"); // Zs NBSP, below U+0100
        assert_eq!(py_repr("\u{85}"), r"'\x85'"); // Cc C1 control
        assert_eq!(py_repr("\u{2028}"), r"'\u2028'"); // Zl line separator
        assert_eq!(py_repr("\u{10ffff}"), r"'\U0010ffff'"); // Cn astral
        assert_eq!(py_repr("\u{1f600}"), "'\u{1f600}'"); // So printable emoji
        assert_eq!(py_repr("\u{e9} \u{436}"), "'\u{e9} \u{436}'"); // printable non-ASCII
    }
}
