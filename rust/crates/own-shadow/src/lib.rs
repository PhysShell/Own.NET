//! `own-shadow` — **infrastructure for shadow mode** (P-022 step 7a,
//! #260/#269), layer 0: the same-input capture and the reproduction artifact.
//!
//! Two things have to be settled before two engines can be compared at all,
//! and neither of them is a comparison:
//!
//! * **Did both engines see the same input?** [`canonical_hash`] names an
//!   `OwnIR` document by a canonical form taken over the *parsed* document, so
//!   "same input" is a checked fact rather than an assumption about which file
//!   was passed where. `tests/fixtures/repro/digests.json` carries the
//!   reference's digest for every shared corpus document; `tests/repro.rs`
//!   recomputes all of them here with **zero Python**.
//! * **What does a reproduction look like?** [`verify`] and [`render`] are
//!   this side of the reproduction-artifact format: one self-contained JSON
//!   document carrying the input, its schema version, its hash, the engine
//!   identifiers and each engine's outputs **per layer**, so a divergence can
//!   be re-run from the artifact alone.
//! * **How does an engine report those outputs?** [`capture`] is this engine's
//!   half of the engine protocol (checkpoint 2): it drives `own-bridge`'s
//!   three layer surfaces and reports each in the shared envelope, declaring
//!   per layer what it could **produce** — the verdict layer is at the #259
//!   checkpoint-4 projection and says so, rather than emitting a short
//!   document a later comparison would score as agreement.
//! * **What would a comparison have to walk?** [`project_traces`] is the
//!   `AnalysisTrace` (#269): each capture normalized so that the Layer 2
//!   handles — global counters wearing the costume of names — become addresses
//!   derived from what they identify, while each layer's ORDER semantics are
//!   *declared* rather than normalized away. Producing that shape is still not
//!   performing a comparison.
//!
//! **This is not shadow mode**, and nothing here may be read as shadow mode
//! having been achieved. Comparing two engines' end diagnostics is #260's
//! acceptance and is blocked on #259 (cp5 and 4b); this crate builds no
//! comparison and no verdict. It also asserts no *parity*: an artifact records
//! one engine's capture and takes no side on another's.
//!
//! `ownlang/repro.py` is the authoritative emitter — the same relationship
//! `own-lowered` has to `ownlang/lowered.py`. The two `verify`
//! implementations are deliberately independent readings of one frozen rule,
//! so a divergence between them is itself a finding.

mod artifact;
mod canonical;
mod engine;
mod json;
mod trace;

pub use artifact::{
    render, verify, ENGINE_ORDER, ENGINE_PYTHON, ENGINE_RUST, LAYER_ORDER, PROJECTION_FULL,
    PROJECTION_PARTIAL, REPRO_VERSION, STATUS_PRODUCED, STATUS_REFUSED,
};
pub use canonical::{canonical_bytes, canonical_hash, CanonicalHash, CANONICAL_ALGORITHM};
pub use engine::capture;
pub use json::{parse, Json};
pub use trace::{
    order_semantics, project_trace, project_traces, ORDER_CANONICAL, ORDER_SIGNIFICANT,
    TRACE_VERSION,
};
