//! `own-bridge` — the `OwnIR` bridge (P-022 step 6b, #259): facts → the core
//! → verdicts, the port of `ownlang/ownir.py` beyond its schema.
//!
//! Three surfaces, one per landed checkpoint family:
//!
//! * [`lower`] — `to_module` as the normalized **Layer 2** document (cp2):
//!   routing R1–R6, global `sub_`/`cap_` and `parg_`/`loc_` handle minting,
//!   capture/DI lifetime regions, flow lowering with the local map and
//!   kill-on-rebind, branch-local hoisting with its negative gates,
//!   `alias_join`, unmapped references, call lowering, the `$consume`/
//!   `$borrow`/`$borrow_mut` channels, the precise-overload channel vs the
//!   merged-may kill site, in-branch untrack vs top-level kill site,
//!   fresh-result minting, and the fail-loud flow-op vocabulary;
//! * [`dump_summaries`] — the MOS summaries document (cp3), byte-identical to
//!   `python -m ownlang summaries` over the shared scalar-metadata parity
//!   domain (spec/Inference.md §8; see the function's contract for the
//!   domain boundary);
//! * [`check_facts`] — the **analysis wiring** (cp4): the lowered module
//!   through `own_analysis::check_module` (ownership, lifetime, buffer
//!   policy), the `services[]`/`effects[]` blocks through the DI and effect
//!   analyses, plus the OWN050/051/052 advisory side paths, mapped back to
//!   their C# anchors per spec/Bridge.md §5 — at the checkpoint-4 surface
//!   (identity, anchor, kind and tiering; messages and evidence are cp5).
//!
//! **Pure transformation**, still: a typed [`own_ir::OwnIr`] document in,
//! values out (or a [`BridgeError`] whose message text is part of the parity
//! surface — Python projects it as the `Rejected` form). No filesystem, no
//! CLI. The bridge prepares analysis inputs and maps analysis outputs; it
//! owns no solver, no dataflow and no graph algorithm (BR-B1) — every verdict
//! comes from `own-analysis`, every anchor is the analysis's own selection,
//! and a verdict the bridge cannot attribute to a fact handle is a refusal,
//! never a dropped finding (BR-V3).
//!
//! The oracles are Python-authored and replayed with zero Python: the Layer 2
//! goldens (`tests/replay.rs`), the summaries goldens (`tests/summaries.rs`)
//! and the verdict goldens (`tests/verdicts.rs`). Goldens are expected output
//! ONLY — never an input to construction.

mod ast;
mod dump;
mod lower;
mod mos;
mod verdict;

use own_ir::OwnIr;
use own_lowered::LoweredDocument;

pub use verdict::{Finding, Step};

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
/// Byte-identical to `python -m ownlang summaries` (`json.dumps(doc,
/// indent=2, sort_keys=True)` + the trailing newline) **for the shared
/// parity domain**: facts whose metadata fields consumed through Python
/// `str()` — `module`, `functions[].name`/`file`, call `callee`/`sig` — are
/// JSON scalars. Every real producer emits scalars there, and the fixture
/// corpus pins only such documents. Container-valued metadata is OUTSIDE
/// this stage-1 contract: both doors accept it, but the reference renders
/// it as Python `repr` while this port renders JSON text, so the outputs
/// diverge without a runtime error. Door-wide type validation (or exact
/// container-repr parity) is a separate #294-class door decision — see the
/// scope note on the implementation for why neither is folded in here.
///
/// A solver failure is not an error: it is the document's `degraded`
/// branch, exactly like the reference (INF-F6).
///
/// # Errors
/// [`BridgeError`] only if the typed facts cannot be re-serialized to JSON
/// (not reachable for a document [`OwnIr::from_json`] accepted).
pub fn dump_summaries(facts: &OwnIr) -> Result<String, BridgeError> {
    dump::dump_summaries(facts)
}

/// Run the core over one `OwnIR` facts document and return its findings.
///
/// The port of `ownlang/ownir.py::check_facts` at the #259 checkpoint-4
/// surface — every finding mapped back to its C# anchor (see [`Finding`] for
/// the members carried). Deterministic: the list is deduplicated on the
/// reference's key (BR-V7) and stably sorted by `(file, line, column, code)`
/// (BR-V8).
///
/// # Errors
/// [`BridgeError`] when the lowering fails loud (vocabulary skew, an unknown
/// resource kind), when a core verdict cannot be attributed to a fact handle
/// (BR-V3 — the reference's `OwnIRError`), when a coordinate falls outside
/// the core's `u32` line domain, or when the document declares an obligation
/// protocol (the protocol analysis is not wired yet; refused rather than
/// silently incomplete).
pub fn check_facts(facts: &OwnIr) -> Result<Vec<Finding>, BridgeError> {
    verdict::check_facts(facts)
}
