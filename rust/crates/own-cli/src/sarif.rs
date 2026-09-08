//! The CLI's SARIF serialization — and why it is not the fixture emitter's.
//!
//! `own_bridge::build_sarif` is the single source of the log's *shape*, and it
//! is byte-pinned by the BR-V9 family
//! (`rust/crates/own-bridge/tests/renders.rs` against
//! `tests/fixtures/verdict_renders/`). This module does not re-derive one byte
//! of it. What it owns is the **serialization**, because the reference writes
//! the same document twice, differently:
//!
//! | surface | emitter | non-ASCII |
//! |---|---|---|
//! | `cmd_ownir`'s `--format sarif` stdout | `json.dumps(..., indent=2)` — `ensure_ascii` left at its **default, True** | escaped `\uXXXX` |
//! | `tests/fixtures/verdict_renders/*.renders.json` | the fixture writer, `ensure_ascii=False` | literal UTF-8 |
//!
//! Measured on `render_tiers_and_levels`: the CLI's stdout is pure ASCII and
//! carries the six ASCII characters `\u2014` where the message has an em
//! dash; the golden for the same document carries the `e2 80 94` bytes. So the goldens' emitter is **not**
//! wrong and is not to be "fixed" — the two byte shapes are both correct, for
//! different consumers, and this is the CLI's.
//!
//! The escaping is applied to the finished pretty-printed text rather than
//! through a custom `serde_json::ser::Formatter`, and that is a correctness
//! argument rather than a convenience: every character of JSON *syntax* is
//! ASCII, so any non-ASCII scalar in the serialized document is necessarily
//! inside a string literal, where `\uXXXX` is exactly the right escape. A
//! hand-rolled formatter would have to re-implement every pretty-printing hook
//! correctly to earn the same guarantee.

use std::fmt::Write as _;

use own_bridge::SarifLog;

/// Escape every non-ASCII scalar as CPython's `json.dumps` does: lowercase
/// `\uXXXX`, and a **surrogate pair** for anything above the BMP (measured:
/// `U+1F600` in a `file` field leaves as `\ud83d\ude00`). `char::encode_utf16`
/// produces exactly that pair, so the rule is one branch rather than a manual
/// surrogate computation the denied `arithmetic_side_effects` lint would
/// rightly object to.
fn escape_non_ascii(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut units = [0_u16; 2];
    for ch in text.chars() {
        if ch.is_ascii() {
            out.push(ch);
            continue;
        }
        for unit in ch.encode_utf16(&mut units) {
            // `write!` into a String is infallible; the Result is discarded
            // rather than unwrapped (the workspace denies `unwrap_used`).
            let _ = write!(out, "\\u{unit:04x}");
        }
    }
    out
}

/// The document as `cmd_ownir` writes it to stdout: two-space indent, the
/// `": "` / `", "` separators `json.dumps` uses when `indent` is given, ASCII
/// escaping, and exactly one trailing newline (the reference's `print`).
///
/// # Errors
///
/// Returns the `serde_json` error if the typed log fails to serialize. That
/// cannot happen for `SarifLog` — every field is a plain owned scalar or a
/// `Vec` of them — but it is reported rather than unwrapped: the workspace
/// denies `unwrap_used`, and a CLI that panicked on its own output would be
/// answering an internal-error question nobody asked.
pub(crate) fn render(log: &SarifLog) -> Result<String, serde_json::Error> {
    let pretty = serde_json::to_string_pretty(log)?;
    let mut out = escape_non_ascii(&pretty);
    out.push('\n');
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::escape_non_ascii;

    /// The three characters that matter, against CPython's `json.dumps`
    /// output as measured on this tree (H.0): ASCII untouched, a BMP scalar as
    /// one lowercase `\uXXXX`, an astral scalar as a surrogate PAIR.
    #[test]
    fn escapes_exactly_as_json_dumps_does() {
        assert_eq!(escape_non_ascii("plain ASCII"), "plain ASCII");
        assert_eq!(escape_non_ascii("a \u{2014} b"), r"a \u2014 b");
        assert_eq!(escape_non_ascii("\u{1f600}"), r"\ud83d\ude00");
        assert_eq!(
            escape_non_ascii("\u{dc}n\u{ef}c\u{f8}d\u{e9}"),
            r"\u00dcn\u00efc\u00f8d\u00e9"
        );
    }

    /// Lowercase hex, and zero-padded to four digits — `json.dumps` writes
    /// `\u00dc`, never `\u00DC` and never `\uDC`.
    #[test]
    fn hex_is_lowercase_and_padded() {
        assert_eq!(escape_non_ascii("\u{e9}"), r"\u00e9");
        assert_eq!(escape_non_ascii("\u{412}"), r"\u0412");
    }

    /// A JSON structural character is always ASCII, so escaping the finished
    /// text can only ever touch the inside of a string literal. This is the
    /// module's correctness argument, asserted rather than asserted-in-prose.
    #[test]
    fn json_syntax_is_entirely_ascii() {
        for ch in ['{', '}', '[', ']', ':', ',', '"', '\\', '\n', ' '] {
            assert!(ch.is_ascii(), "{ch:?} is JSON syntax and must be ASCII");
        }
    }
}
