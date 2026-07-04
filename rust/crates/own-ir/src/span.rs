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
