//! The Layer 2 parity surface, typed (P-022 #259, spec/Bridge.md §6).
//!
//! `ownlang/lowered.py` is the authoritative Python emitter of the normalized
//! lowered representation; `tests/fixtures/lowered/` holds its frozen
//! facts/golden pairs under `manifest.json`. This crate is the **typed Rust
//! half of that contract**: a strict (`deny_unknown_fields`) data model of the
//! surface plus the canonical emitter that re-serializes it **byte-for-byte**
//! (2-space indent, fixed field order, raw UTF-8, trailing newline).
//!
//! Deliberately NOT here (next slices, gated separately): deriving these
//! documents from `OwnIR` facts (the lowering itself), `OwnIR` validation,
//! MOS inference, and any analysis wiring. A `rust_replay: false` manifest
//! case is a Python-only behavior snapshot pinning an open decision (#294)
//! and is not replayed by this crate's parity suite.
//!
//! Every shape here mirrors the frozen normalization decisions in the Python
//! emitter's docstring; a field added there without a matching change here (or
//! vice-versa) fails the replay suite, and `LOWERED_VERSION` must move in
//! lockstep on both sides.

mod model;

pub use model::{
    parse_document, to_canonical_json, Extern, ExternParam, Function, HandleEntry, Lifetime,
    LoweredDocument, Manifest, ManifestCase, Param, Rejected, Resource, ResourceMember, Stmt,
    Surface, TypeShape, LOWERED_VERSION,
};
