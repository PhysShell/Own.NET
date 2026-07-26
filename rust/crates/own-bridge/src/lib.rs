//! `own-bridge` — the `OwnIR` facts → Layer 2 lowering (P-022 #259 slice 3).
//!
//! The Rust port of `ownlang/ownir.py::to_module` **restricted to the behavior
//! the shared Layer 2 fixtures exercise**: routing R1–R6, global `sub_`/`cap_`
//! and `parg_`/`loc_` handle minting, capture/DI lifetime regions, flow
//! lowering with the local map and kill-on-rebind, branch-local hoisting with
//! its negative gates, `alias_join`, unmapped references, call lowering, the
//! `$consume`/`$borrow`/`$borrow_mut` channels, the precise-overload channel
//! vs the merged-may kill site, in-branch untrack vs top-level kill site,
//! fresh-result minting, and the fail-loud flow-op vocabulary.
//!
//! **Pure transformation**: [`lower`] maps a typed [`own_ir::OwnIr`] document
//! to an [`own_lowered::LoweredDocument`] (or a [`BridgeError`] whose message
//! text is part of the parity surface — Python projects it as the `Rejected`
//! form), and [`dump_summaries`] renders the MOS summaries document
//! byte-identically to `python -m ownlang summaries` (the inference layer's
//! parity artifact, spec/Inference.md §8). No filesystem, no CLI, no
//! diagnostics, no analysis. `OwnIR` validation parity, MOS contract
//! *changes*, and analysis wiring stay out of scope (#294 OD-2 landed:
//! IR4-everywhere — `tolerant_unknown_kind` is a shared `rust_replay` case
//! whose `Rejected` golden pins the fail-loud text on both sides).
//!
//! The oracle is byte-exact: for every `rust_replay: true` manifest case,
//! `facts → OwnIr::from_json → lower → own_lowered::to_canonical_json` must
//! equal the committed Python golden (`tests/replay.rs`), and every
//! summaries-family case must reproduce its `*.summaries.json` golden
//! through [`dump_summaries`] (`tests/summaries.rs`). The goldens are
//! expected output ONLY — never an input to construction.

mod dump;
mod lower;
mod mos;

use own_ir::OwnIr;
use own_lowered::LoweredDocument;

/// A lowering rejection — the Rust twin of Python's `OwnIRError` from
/// `to_module`. The message TEXT is part of the Layer 2 parity surface
/// (a fail-loud golden pins it byte-for-byte).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BridgeError(pub String);

impl std::fmt::Display for BridgeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for BridgeError {}

/// Lower one `OwnIR` facts document into the normalized Layer 2 document.
///
/// # Errors
/// [`BridgeError`] on vocabulary skew the reference bridge fails loud on
/// (e.g. an unknown flow op); the message text matches Python's `OwnIRError`.
pub fn lower(facts: &OwnIr) -> Result<LoweredDocument, BridgeError> {
    lower::lower(facts)
}

/// Render the MOS summaries document for one `OwnIR` facts document.
///
/// Byte-identical to `python -m ownlang summaries` on the same facts
/// (`json.dumps(doc, indent=2, sort_keys=True)` + the trailing newline).
/// A solver failure is not an error: it is the document's `degraded` branch,
/// exactly like the reference (INF-F6).
///
/// # Errors
/// [`BridgeError`] only if the typed facts cannot be re-serialized to JSON
/// (not reachable for a document [`OwnIr::from_json`] accepted).
pub fn dump_summaries(facts: &OwnIr) -> Result<String, BridgeError> {
    dump::dump_summaries(facts)
}
