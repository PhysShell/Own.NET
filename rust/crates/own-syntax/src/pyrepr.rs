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
//! * other C0 controls and DEL as `\xNN`;
//! * printable non-ASCII stays as-is (Python 3 `repr`).
//!
//! This is not a general `repr` (no `\u`/`\U` for unprintable non-ASCII —
//! `OwnLang` sources in the corpus don't contain them; the parity fixtures
//! would catch it loudly if one ever did).

use std::fmt::Write as _;

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
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                // write! into a String cannot fail; ignore the Ok(()).
                let _ = write!(out, "\\x{:02x}", c as u32);
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
}
