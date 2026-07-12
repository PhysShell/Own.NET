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

pub mod check;
pub mod di;
pub mod effect;
pub mod lifetime;
pub mod ownership;
pub mod solver;

pub use check::check_module;
pub use di::{check_di, di_verdicts};
pub use effect::{effect_diagnostics, effect_verdicts, find_effect_storms};
pub use lifetime::check_lifetimes;
pub use ownership::analyze;
pub use solver::{solve, solve_with, Analysis, ControlFlowGraph, Lattice, Schedule, Solution};
