//! `own-diagnostics` — the Diagnostic / Evidence **verdict** data model
//! (P-022 step 4, issue #214), a data-only port of `ownlang/diagnostics.py`.
//!
//! This crate owns the verdict *types* the solver constructs. Per the P-022
//! crate DAG it sits **upstream** of `own-analysis`: the solver depends on this
//! crate to build `Diagnostic`/`Evidence` values, so the arrow is
//! `own-analysis → own-diagnostics`, never the reverse. This crate depends only
//! on the span/location leaf (`own-ir`) — and today not even that, since a
//! verdict's `line` is a plain source line exactly as in the Python reference.
//! The presentation surface (human render, SARIF `relatedLocations`/`codeFlows`)
//! is a **later** step (5) and deliberately lives elsewhere: these are data, not
//! `Err`, and not rendering.
//!
//! What is faithful to the Python reference here:
//!
//! * `Severity` serialises to the same `"error"`/`"warning"` strings.
//! * `Evidence` carries `line`, `label`, an optional `file` (`None` ⇒ the
//!   diagnostic's own file) and a `role` defaulting to `"related"`.
//! * `Diagnostic` carries `code`, `message`, `line`, `severity`, optional
//!   `subject` and `resource_kind`, and an ordered `evidence` slice — the same
//!   positional contract as the frozen Python dataclass.
//! * A `Diagnostic` **must** carry a code present in [`TITLES`]; constructing one
//!   with an unknown code fails loudly ([`Diagnostic::new`] returns `Err`),
//!   mirroring the Python `__post_init__` guard ("a code and its title must be
//!   added together") — the one stringly-typed contract, checked at the seam.
//!
//! The parity **comparison surface** (issue #214) is `(path, line, code)` in
//! emission order; [`DiagKey`] is that per-diagnostic key. The frozen golden set
//! lives in `tests/fixtures/diag_parity.json` (regenerate:
//! `python tests/test_diag_fixtures.py --write`); `tests/fixture.rs` validates
//! the harness plumbing against it. The full replay (parse → lower → analyse →
//! compare) lands with `own-analysis` at the next checkpoint.

mod diagnostic;

pub use diagnostic::{title, DiagKey, Diagnostic, Evidence, Severity, UnknownCode, TITLES};
