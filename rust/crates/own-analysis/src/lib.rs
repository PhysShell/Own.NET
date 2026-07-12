//! `own-analysis` — the analysis heart (P-022 step 4, issue #214).
//!
//! Two layers, matching the Python `ownlang.analysis` split:
//!
//! * [`solver`] — a generic monotone-lattice forward worklist solver (the
//!   `_Analyzer.fixpoint` shape), domain-agnostic and dependency-free.
//! * the domain analyses (ownership first, then lifetime/effect/DI) built on the
//!   solver, consuming an [`own_cfg`] CFG and constructing [`own_diagnostics`]
//!   verdicts.
//!
//! Python stays authoritative; the diagnostics differential oracle
//! (`tests/parity.rs`, replaying `tests/fixtures/diag_parity.json`) pins the
//! Rust output to it on `(path, line, code)`.

pub mod solver;

pub use solver::{solve, solve_with, Analysis, ControlFlowGraph, Lattice, Schedule, Solution};
