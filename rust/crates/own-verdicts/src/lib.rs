//! `own-verdicts` — the composition of `OwnIR` facts into verdict channels
//! (P-022 #259 checkpoint 4).
//!
//! # What this crate is
//!
//! The Rust twin of `ownlang.ownir::check_facts`: it reads an [`own_ir::OwnIr`]
//! document, lowers it through the pure bridge, projects the result into the
//! analysis AST, feeds the fact-native sidecar analyses from the ORIGINAL
//! facts, and returns the verdicts as separate channels.
//!
//! ```text
//!                    ┌─→ project → Module → check_module ──→ core
//! OwnIr → lower ─────┤
//!   │                └─ (Layer 2 carries no services/effects)
//!   ├──────────────────→ services → DI analysis ───────────→ di
//!   └──────────────────→ effects  → effect analysis ───────→ effects
//! ```
//!
//! The two sidecar arrows start at `OwnIr`, not at the lowered document, and
//! that is a contract rather than a shortcut: `own_lowered::LoweredDocument`
//! carries `module`/`resources`/`externs`/`lifetimes`/`functions`/`handles`
//! and no DI or effect facts at all. Reconstructing them from handles would be
//! inventing a second source of truth that is only convincing until it
//! disagrees with the reference.
//!
//! # Why it is a separate crate
//!
//! `own-bridge` cannot host this. Its contract is a pure
//! `OwnIr -> LoweredDocument` function and the DAG test pins it to
//! `{own-ir, own-lowered}` with the reason written out: "no analysis/
//! diagnostics edge". Composition needs six edges at once, so it belongs above
//! the bridge — which keeps that promise instead of widening it.
//!
//! Python has the same problem and solves it with a lazy import inside
//! `check_facts` ("ownir is a leaf consumer"). That is a runtime dodge; in a
//! typed workspace the edge is in the graph whether or not it is taken late,
//! so the shape has to differ.
//!
//! # Scope of checkpoint 4
//!
//! Three channels gate this checkpoint — `core`, `di`, `effects` — matching
//! `tests/fixtures/ownir/verdicts.json`. The oracle also freezes `protocols`
//! and `advisories`; those are **observations for cp5** and deliberately have
//! no field here, so a green replay of what this crate returns cannot be read
//! as evidence about them.
//!
//! Also not here, and also cp5: the `Finding` shape, the handle → C# location
//! mapping, message/severity/subject/resource-kind parity, evidence ordering,
//! dedup and the BR-V8 final sort. The three channels keep the granularity the
//! oracle compares at — `core` is `(line, code)`, the fact-driven ones are
//! `(path, line, code)` — rather than being unified behind one envelope now.
//! An envelope is exactly cp5's mapping work, started early and proven late.

/// A rejection from the composition.
///
/// Distinct from a *verdict*: this means the document could not be turned into
/// something analysable at all, the way `lower` rejects vocabulary skew. A
/// document that analyses cleanly returns empty channels, never an error.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerdictError(pub String);

impl std::fmt::Display for VerdictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for VerdictError {}

impl From<own_bridge::BridgeError> for VerdictError {
    fn from(e: own_bridge::BridgeError) -> Self {
        Self(e.0)
    }
}
