//! Canonical rendering and the emission ordering contract
//! (P-022 step 5a, issue #255 — PR 2 of 3).
//!
//! PR 1 modelled a diagnostic's *identity* and treated `message` as opaque. This
//! module is the text: the exact strings `ownlang.diagnostics.Diagnostic.render`
//! and `render_pretty` produce, plus the sequence
//! `ownlang.__main__.check_module` emits them in.
//!
//! ## The ordering contract is a STABLE two-key sort, not a total order
//!
//! The reference ends its pipeline with:
//!
//! ```text
//! diags.sort(key=lambda d: (d.line, d.code))
//! ```
//!
//! Python's `list.sort` is stable, so equal `(line, code)` pairs keep their
//! **emission** order. Two ways to get this wrong produce the right *set* in the
//! wrong *sequence*:
//!
//! * sorting by [`DiagIdentity`](crate::DiagIdentity) — that key is total by
//!   design (PR 1 needed it for set operations) and would reorder ties by
//!   subject, message or evidence, none of which the reference consults;
//! * using an unstable sort — `sort_unstable_by` may permute ties freely.
//!
//! [`sort_emission_order`] is therefore a stable sort on exactly `(line, code)`.
//! Note what the key omits: the **path**. Within one module every diagnostic
//! shares a file, so the core never orders by it; cross-file ordering belongs to
//! the finding layers (`ownlang.di`, `ownlang.effects`), and inventing it here
//! would be a behaviour the reference does not have.
//!
//! ## The caret column counts CHARACTERS
//!
//! `render_pretty` places a caret via the reference's `_caret_col`, a renderer
//! heuristic — explicitly *not* the #317 source column PR 1 modelled. It is
//! reproduced here in full, and the load-bearing detail is that Python's
//! `str.find` and `re.Match.start()` return **character** offsets while Rust's
//! `str::find` returns a **byte** offset. Forwarding a byte index would put the
//! caret mid-glyph on any non-ASCII line, silently and plausibly. Every offset
//! below is a `char` count.
//!
//! No regex crate is pulled in for this: the two patterns involved are a
//! first-single-quoted-group scan and a word-boundary search, both small enough
//! to write directly, and a new production dependency would need its own review
//! against the crate DAG.

use crate::diagnostic::{Diagnostic, Evidence, Severity};

impl Severity {
    /// The severity word the reference renders (`Severity.value`).
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Error => "error",
            Self::Warning => "warning",
        }
    }
}

impl Evidence {
    /// The one-line `note:` rendering of this step.
    ///
    /// `anchor_file` is the diagnostic's own file, used when the step shares it
    /// (`file` is `None`) — the port of `Evidence.render`.
    #[must_use]
    pub fn render(&self, anchor_file: &str) -> String {
        let where_ = self.file.as_deref().unwrap_or(anchor_file);
        format!("  note: {} at {}:{}", self.label, where_, self.line)
    }
}

/// True for a character Python's `\w` matches on a `str` pattern: ASCII
/// alphanumerics and `_`, widened to Unicode alphanumerics.
fn is_word_char(ch: char) -> bool {
    ch.is_alphanumeric() || ch == '_'
}

/// The first single-quoted, non-empty group in `message` — the port of
/// `_SUBJECT_RE = re.compile(r"'([^']+)'")`.
///
/// Returns `None` for an unpaired quote or an empty `''`, matching the regex:
/// `[^']+` requires at least one character.
fn first_quoted(message: &str) -> Option<&str> {
    let open = message.find('\'')?;
    let rest = message.get(open.checked_add(1)?..)?;
    let close = rest.find('\'')?;
    let inner = rest.get(..close)?;
    if inner.is_empty() {
        None
    } else {
        Some(inner)
    }
}

/// The CHARACTER index at which `needle` occurs in `haystack` as a whole word —
/// the port of `re.search(rf"\b{escape(name)}\b", line)`.
///
/// A `\b` holds where a word character abuts a non-word character or a string
/// edge; the check is applied to both ends of the candidate match.
fn find_word_boundary(haystack: &str, needle: &str) -> Option<usize> {
    let need: Vec<char> = needle.chars().collect();
    // `first`/`last` double as the non-empty guard `windows` needs: a zero-length
    // window panics, and an empty needle has no boundary to speak of anyway.
    let (&first, &last) = (need.first()?, need.last()?);
    let hay: Vec<char> = haystack.chars().collect();
    // A `\b` holds where a word character abuts a non-word one (or a string
    // edge), checked at both ends of the candidate.
    hay.windows(need.len())
        .enumerate()
        .find(|(start, window)| {
            if *window != need.as_slice() {
                return false;
            }
            let left_ok = match start.checked_sub(1).and_then(|i| hay.get(i)) {
                Some(&prev) => is_word_char(prev) != is_word_char(first),
                None => true,
            };
            let right_ok = match start.checked_add(need.len()).and_then(|i| hay.get(i)) {
                Some(&next) => is_word_char(next) != is_word_char(last),
                None => true,
            };
            left_ok && right_ok
        })
        .map(|(start, _)| start)
}

/// The CHARACTER index of `needle` in `haystack`, or `None` — the port of
/// `str.find`, which returns a character offset in Python.
fn find_char_index(haystack: &str, needle: &str) -> Option<usize> {
    haystack
        .find(needle)
        .and_then(|byte_idx| haystack.get(..byte_idx))
        .map(|prefix| prefix.chars().count())
}

impl Diagnostic {
    /// The ` [resource: <kind>]` tail, or empty when the finding carries no kind.
    ///
    /// A verbatim passthrough, not a lookup: a profile's new tag needs no change
    /// here.
    #[must_use]
    pub fn kind_suffix(&self) -> String {
        self.resource_kind
            .as_ref()
            .map_or_else(String::new, |kind| format!(" [resource: {kind}]"))
    }

    /// The 1-based **character** column this diagnostic points at within
    /// `src_line`, or `None` when it cannot be located.
    ///
    /// The port of `_caret_col`: prefer the first single-quoted name matched at a
    /// word boundary, fall back to a plain substring occurrence, and finally to
    /// the line's indent — `None` only for a blank line. A renderer heuristic,
    /// never a source column (see the module docs).
    #[must_use]
    pub fn caret_col(&self, src_line: &str) -> Option<usize> {
        if let Some(name) = first_quoted(&self.message) {
            // Whole-word first, so 'a' lands on the argument in `Hash(a)` rather
            // than the 'a' inside `Hash`.
            if let Some(idx) = find_word_boundary(src_line, name) {
                return idx.checked_add(1);
            }
            if let Some(idx) = find_char_index(src_line, name) {
                return idx.checked_add(1);
            }
        }
        if src_line.trim().is_empty() {
            return None;
        }
        src_line
            .chars()
            .count()
            .checked_sub(src_line.trim_start().chars().count())
            .and_then(|indent| indent.checked_add(1))
    }

    /// The `note:` lines for this diagnostic's reachability slice, in order.
    #[must_use]
    pub fn evidence_lines(&self, filename: &str) -> Vec<String> {
        self.evidence.iter().map(|e| e.render(filename)).collect()
    }

    /// Plain rendering: `file:line: severity: [code] message`, then one `note:`
    /// line per evidence step.
    #[must_use]
    pub fn render(&self, filename: &str) -> String {
        let head = format!(
            "{}:{}: {}: [{}] {}{}",
            filename,
            self.line,
            self.severity.as_str(),
            self.code,
            self.message,
            self.kind_suffix()
        );
        let mut out = vec![head];
        out.extend(self.evidence_lines(filename));
        out.join("\n")
    }

    /// A rustc-style rendering: a `file:line:col` header, the offending source
    /// line, a caret under the named identifier, then the `note:` lines.
    ///
    /// Degrades to the plain header when the line or column cannot be resolved,
    /// exactly as the reference does.
    #[must_use]
    pub fn render_pretty(&self, filename: &str, source: &str) -> String {
        let lines: Vec<&str> = source.split('\n').collect();
        // Python's `str.splitlines()` drops a single trailing newline's empty
        // tail; `split('\n')` keeps it, so trim that one element back off.
        let lines = match lines.split_last() {
            Some((last, head)) if last.is_empty() && !head.is_empty() => head,
            _ => lines.as_slice(),
        };
        let src_line = usize::try_from(self.line)
            .ok()
            .and_then(|n| n.checked_sub(1))
            .and_then(|idx| lines.get(idx))
            .copied()
            .unwrap_or("");
        let col = self.caret_col(src_line);
        let loc = col.map_or_else(
            || format!("{}:{}", filename, self.line),
            |c| format!("{}:{}:{}", filename, self.line, c),
        );
        let mut out = vec![format!(
            "{}: {}: [{}] {}{}",
            loc,
            self.severity.as_str(),
            self.code,
            self.message,
            self.kind_suffix()
        )];
        if !src_line.trim().is_empty() {
            let gutter = format!("  {} | ", self.line);
            out.push(format!("{gutter}{src_line}"));
            if let Some(pad) = col.and_then(|c| {
                gutter
                    .chars()
                    .count()
                    .checked_add(c)
                    .and_then(|n| n.checked_sub(1))
            }) {
                out.push(format!("{}^", " ".repeat(pad)));
            }
        }
        out.extend(self.evidence_lines(filename));
        out.join("\n")
    }
}

/// Order diagnostics the way the core emits them: a **stable** sort on
/// `(line, code)`.
///
/// Stability is the contract, not an implementation detail — ties keep their
/// emission order (policies → lifetimes → per function: CFG, then analysis). Do
/// not "improve" this into a total order or an unstable sort; see the module
/// docs for why either reproduces the right set in the wrong sequence.
pub fn sort_emission_order(diagnostics: &mut [Diagnostic]) {
    diagnostics.sort_by(|a, b| (a.line, &a.code).cmp(&(b.line, &b.code)));
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::*;

    fn diag(code: &str, message: &str, line: u32) -> Diagnostic {
        Diagnostic::new(code, message, line).expect("known code")
    }

    #[test]
    fn first_quoted_needs_a_matched_non_empty_pair() {
        assert_eq!(first_quoted("use 'b' after release"), Some("b"));
        assert_eq!(first_quoted("move 'a' while 'b' is borrowed"), Some("a"));
        assert_eq!(first_quoted("it's complicated"), None);
        assert_eq!(first_quoted("empty '' group"), None);
        assert_eq!(first_quoted("no quotes at all"), None);
    }

    #[test]
    fn word_boundary_beats_a_substring_hit() {
        // 'a' occurs inside `Hash` first, but the boundary match is the argument.
        assert_eq!(find_word_boundary("    Hash(a);", "a"), Some(9));
        assert_eq!(find_char_index("    Hash(a);", "a"), Some(5));
    }

    #[test]
    fn caret_column_is_counted_in_characters() {
        // Cyrillic is 2 bytes per char: a byte offset would overshoot badly.
        let line = "    освободить поток;";
        let d = diag("OWN003", "'поток' освобождён дважды", 1);
        assert_eq!(d.caret_col(line), Some(16));
        assert!(
            line.find("поток").expect("present") > 16,
            "byte index differs"
        );
    }

    #[test]
    fn caret_falls_back_to_indent_then_to_nothing() {
        let d = diag("OWN020", "unsupported construct", 1);
        assert_eq!(d.caret_col("        deeply(indented);"), Some(9));
        assert_eq!(d.caret_col("   "), None);
        assert_eq!(d.caret_col(""), None);
    }

    #[test]
    fn stable_sort_keeps_emission_order_on_ties() {
        let mut diags = vec![
            diag("OWN001", "zulu", 5),
            diag("OWN001", "alpha", 5),
            diag("OWN001", "mike", 5),
        ];
        sort_emission_order(&mut diags);
        let messages: Vec<&str> = diags.iter().map(|d| d.message.as_str()).collect();
        assert_eq!(
            messages,
            ["zulu", "alpha", "mike"],
            "ties must NOT be reordered — the reference sort is stable and does \
             not consult the message"
        );
    }

    #[test]
    fn codes_compare_as_strings() {
        let mut diags = vec![diag("OWN010", "ten", 4), diag("OWN009", "nine", 4)];
        sort_emission_order(&mut diags);
        let codes: Vec<&str> = diags.iter().map(|d| d.code.as_str()).collect();
        assert_eq!(codes, ["OWN009", "OWN010"]);
    }
}
