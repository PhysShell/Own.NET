//! Span / location primitives — the *leaf* the whole workspace shares.
//!
//! Per P-022, these live in `own-ir` (not `own-syntax`) so the presentation
//! layer (`own-diagnostics`) can name a source position without dragging in
//! the parser. Internal positions are **byte offsets** plus one line index per
//! file (the ruff / rust-analyzer convention); line/column pairs are computed
//! only at the output seam. The types here are deliberately minimal — they
//! grow with the first real consumer (`own-syntax`), not speculatively.

use serde::{Deserialize, Serialize};

/// A byte offset into a source file's UTF-8 text. `u32` suffices for any
/// source this tool will see and keeps `Span` at 8 bytes.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
)]
#[serde(transparent)]
pub struct ByteOffset(pub u32);

/// A half-open byte range `[start, end)` in one source file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
pub struct Span {
    pub start: ByteOffset,
    pub end: ByteOffset,
}

impl Span {
    #[must_use]
    pub const fn new(start: u32, end: u32) -> Self {
        Self {
            start: ByteOffset(start),
            end: ByteOffset(end),
        }
    }

    #[must_use]
    pub const fn len(self) -> u32 {
        self.end.0.saturating_sub(self.start.0)
    }

    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.len() == 0
    }
}

/// A source **line**, as a signed 64-bit value.
///
/// Signed and 64-bit because that is the language the strict door accepts:
/// `spec/OwnIR.md` §4.2 declares the signed-64 range legal for a validated
/// coordinate, and the reference carries whatever it accepted onto the verdict
/// surface verbatim — measured across `i64::MIN`, `-1`, `0`, `u32::MAX + 1`
/// and `i64::MAX`. A narrower carrier here would refuse verdicts the door
/// admits, which is a parity boundary rather than an implementation detail.
///
/// It is a **carrier and nothing else**. There is deliberately no `valid()`,
/// no clamp, no normalisation and no `TryFrom<i64>`: `SourceLine(-1)` is
/// entirely legal. The rules about which lines *mean* something live where
/// they already live and are not repeated here — the DI004/DI005 site sentinel
/// and the SARIF region gate are both `>= 1`, and both keep working unchanged
/// over a signed value. Folding either of them into this type would make the
/// carrier decide semantics, which is the substitution the error taxonomy
/// exists to prevent.
///
/// A newtype rather than a bare `i64` so a line cannot be crossed with a
/// [`ByteOffset`] or a column by accident. `column` is **not** this type: it
/// keeps `NonZeroU32`, because unlike a line it really does carry a 1-based
/// contract (#317).
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
)]
#[serde(transparent)]
pub struct SourceLine(pub i64);

impl SourceLine {
    /// The underlying value. No interpretation, no fallback.
    #[must_use]
    pub const fn get(self) -> i64 {
        self.0
    }
}

/// Lossless widening from the lexer's line counter.
///
/// The parser counts newlines in a file it has in memory, so its `u32` is an
/// honest domain and stays one. This conversion is the seam where a
/// producer-specific bound meets the shared type: `From`, never `TryFrom`,
/// because every `u32` is a `SourceLine` and nothing here can fail.
impl From<u32> for SourceLine {
    fn from(line: u32) -> Self {
        Self(i64::from(line))
    }
}

impl std::fmt::Display for SourceLine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}
