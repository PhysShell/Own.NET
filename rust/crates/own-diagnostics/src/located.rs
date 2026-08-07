//! The primary-location envelope and the canonical comparison identity
//! (P-022 step 5a, issue #255 — PR 1 of 3).
//!
//! [`DiagKey`](crate::DiagKey) — the step-4 parity key — is `(line, code)`. That
//! was the right surface for "which verdicts fire", but it **collapses** two
//! findings that share an anchor and differ in subject, resource kind, severity
//! or evidence. Step 5a's whole subject is that remainder, so it needs a key that
//! separates them: [`DiagIdentity`].
//!
//! ## Why a location envelope and not two more fields on `Diagnostic`
//!
//! The Python `Diagnostic` dataclass carries **no `path` and no `column`**:
//!
//! * `path` is the *input identity* — the core reports per-file and the caller
//!   already knows which file it handed in. That is why the oracle surface is
//!   written `(path, line, code)` while the frozen pair is `(line, code)`.
//! * `column` lives on `ownlang.ownir.Finding` (#317): optional, and **never
//!   substituted** — not 0, not 1, and never recovered by re-reading the source.
//!   (`Diagnostic._caret_col` re-reads the line to place a caret; that is a
//!   renderer heuristic and is *not* a source column.)
//!
//! Adding both to [`Diagnostic`] would make the Rust type stop mirroring the
//! reference dataclass in order to suit a fixture — precisely the "do not change
//! the reference to simplify the port" rule this migration runs on. So the
//! location rides *outside* the ported value, in [`LocatedDiagnostic`].
//!
//! ## What the identity does and does not normalise
//!
//! Nothing. Paths are compared **verbatim**: `src\A.cs` and `src/A.cs` are two
//! records. Python folds separators only at the SARIF seam
//! (`ownlang.evidence::_phys`), so folding them here would invent a behaviour the
//! reference does not have at this layer; the projection owns it (#256).
//!
//! Ordering is a **total order for determinism**, not a semantic ranking: field
//! declaration order below is the comparison precedence, and `None` sorts before
//! `Some` (Rust's `Option` order). The *contract* for how findings are ordered on
//! an output surface is PR 2's, pinned against Python; this type only guarantees
//! that sorting is total, antisymmetric and reproducible.

use std::num::NonZeroU32;

use serde::{Deserialize, Serialize};

use crate::diagnostic::{Diagnostic, Evidence, Severity};

/// A [`Diagnostic`] together with the primary-location identity the ported
/// dataclass does not carry.
///
/// **This type defines the READ contract for `tests/fixtures/diag_model.json`**
/// (regenerate: `python tests/test_diag_model_fixtures.py --write`) — every key
/// the Python writer emits loads into a field here, and
/// `tests/model_replay.rs::fixture_shape_is_pinned_key_for_key` asserts that
/// key-for-key so a Python-side shape change fails the replay.
///
/// Serialization is deliberately **not** byte-symmetric with that writer: the
/// ported [`Diagnostic`] carries `skip_serializing_if` from step 4, so a Rust
/// round-trip omits `subject`, `resource_kind` and an empty `evidence` where
/// Python writes `null` and `[]`. Reading is unaffected (`serde(default)` and
/// `null` both land on the same value), and a Rust→Rust round-trip therefore
/// proves nothing about the writer — which is exactly why the shape is pinned by
/// a separate assertion against the raw JSON rather than by round-tripping.
/// Making the *write* side canonical belongs to `.ownreport.json` (#256), which
/// owns output serialization; changing those attributes here would alter a
/// step-4 type for a step-5a fixture's convenience.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocatedDiagnostic {
    /// The file this verdict is reported against, **verbatim** — the input
    /// identity, not a normalised path.
    pub path: String,
    /// The 1-based source column (#317), when the producer reported one.
    /// `None` means *not reported*; it is never substituted with a placeholder.
    ///
    /// [`NonZeroU32`] is the type-level mirror of `ownlang.ownir::_check_column`,
    /// which rejects `0` rather than reading it as "unknown": SARIF columns start
    /// at 1, so a `0` is a producer bug, and silently absorbing it would hide the
    /// bug while looking correct. Serde rejects a `0` here for the same reason.
    #[serde(default)]
    pub column: Option<NonZeroU32>,
    /// The ported verdict value.
    pub diagnostic: Diagnostic,
}

impl LocatedDiagnostic {
    /// Wrap a diagnostic at `path` with no reported column.
    #[must_use]
    pub fn new(path: impl Into<String>, diagnostic: Diagnostic) -> Self {
        Self {
            path: path.into(),
            column: None,
            diagnostic,
        }
    }

    /// Attach a reported 1-based source column.
    ///
    /// Takes a [`NonZeroU32`] so column `0` is unrepresentable rather than
    /// rejected at runtime — the reference treats it as a producer bug, and an
    /// illegal state that cannot be constructed needs no check.
    #[must_use]
    pub const fn with_column(mut self, column: NonZeroU32) -> Self {
        self.column = Some(column);
        self
    }

    /// The 1-based anchor line (delegated — the line lives on the ported value).
    #[must_use]
    pub const fn line(&self) -> u32 {
        self.diagnostic.line
    }

    /// This record's canonical comparison identity.
    ///
    /// Spans **every** field of the step-5a contract, so two records compare
    /// equal only when they are the same finding. Cloning is deliberate: the
    /// identity is an owned, sortable key, not a borrow of the record.
    #[must_use]
    pub fn identity(&self) -> DiagIdentity {
        DiagIdentity {
            path: self.path.clone(),
            line: self.diagnostic.line,
            column: self.column,
            code: self.diagnostic.code.clone(),
            severity: self.diagnostic.severity,
            subject: self.diagnostic.subject.clone(),
            resource_kind: self.diagnostic.resource_kind.clone(),
            message: self.diagnostic.message.clone(),
            evidence: self
                .diagnostic
                .evidence
                .iter()
                .map(EvidenceIdentity::of)
                .collect(),
        }
    }
}

/// One evidence step's identity — every field participates, and the enclosing
/// [`Vec`] compares **positionally**, so a reordered slice is a different
/// reachability path rather than the same one.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct EvidenceIdentity {
    /// 1-based line of the step.
    pub line: u32,
    /// The step's file; `None` means "the anchor's own file" and is **not**
    /// resolved to the anchor path here — the two forms stay distinct, exactly
    /// as the reference leaves them until the SARIF seam resolves one.
    pub file: Option<String>,
    /// The protocol role (`acquired`/`released`/`escaped`/…, default `related`).
    pub role: String,
    /// The human label for the step.
    pub label: String,
}

impl EvidenceIdentity {
    /// The identity of one [`Evidence`] step.
    #[must_use]
    pub fn of(evidence: &Evidence) -> Self {
        Self {
            line: evidence.line,
            file: evidence.file.clone(),
            role: evidence.role.clone(),
            label: evidence.label.clone(),
        }
    }
}

/// The canonical comparison identity of a located diagnostic.
///
/// Equality is "these are the same finding". Field declaration order is the
/// comparison precedence for [`Ord`]; see the module docs for why that order is
/// a determinism guarantee and not a semantic ranking.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct DiagIdentity {
    /// Verbatim source path.
    pub path: String,
    /// 1-based anchor line.
    pub line: u32,
    /// Reported source column, if any (`None` sorts first).
    pub column: Option<NonZeroU32>,
    /// The diagnostic code.
    pub code: String,
    /// The severity tier.
    pub severity: Severity,
    /// The subject identity (`name#line`), if any.
    pub subject: Option<String>,
    /// The resource kind tag, if any.
    pub resource_kind: Option<String>,
    /// The message text.
    ///
    /// Carried so the identity spans the whole compared contract; this slice
    /// treats it as an **opaque string**. Producing this text from the analysis
    /// is PR 2's canonical-rendering contract.
    pub message: String,
    /// The ordered evidence slice, compared positionally.
    pub evidence: Vec<EvidenceIdentity>,
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::*;

    fn diag() -> Diagnostic {
        Diagnostic::new("OWN001", "not released", 42).expect("OWN001 is known")
    }

    #[test]
    fn subject_separates_records_that_diagkey_collapses() {
        let a = LocatedDiagnostic::new("src/A.cs", diag().with_subject("a#42"));
        let b = LocatedDiagnostic::new("src/A.cs", diag().with_subject("b#42"));
        // The step-4 key cannot tell them apart -- that is the gap 5a closes.
        assert_eq!(a.diagnostic.key(), b.diagnostic.key());
        assert_ne!(a.identity(), b.identity());
    }

    fn col(n: u32) -> NonZeroU32 {
        NonZeroU32::new(n).expect("test columns are 1-based")
    }

    #[test]
    fn absent_column_never_equals_a_reported_one() {
        let bare = LocatedDiagnostic::new("src/A.cs", diag());
        let at_one = LocatedDiagnostic::new("src/A.cs", diag()).with_column(col(1));
        assert_ne!(bare.identity(), at_one.identity());
        // and `None` sorts before any reported column, deterministically.
        assert!(bare.identity() < at_one.identity());
    }

    #[test]
    fn column_zero_is_rejected_like_the_reference_does() {
        // `ownlang.ownir::_check_column` fails loud on 0 rather than reading it
        // as "unknown" — a fabricated coordinate is the one thing that contract
        // refuses. NonZeroU32 makes serde do the same, at the type level.
        let err = serde_json::from_str::<LocatedDiagnostic>(
            r#"{"path":"src/A.cs","column":0,
                "diagnostic":{"code":"OWN001","message":"m","line":1,"severity":"error"}}"#,
        )
        .expect_err("column 0 must not deserialise");
        assert!(
            err.to_string().contains("nonzero"),
            "expected a nonzero-rejection, got {err}"
        );
    }

    #[test]
    fn path_separators_are_not_folded() {
        let unix = LocatedDiagnostic::new("src/A.cs", diag());
        let windows = LocatedDiagnostic::new("src\\A.cs", diag());
        assert_ne!(unix.identity(), windows.identity());
    }

    #[test]
    fn evidence_order_is_part_of_identity() {
        let acquired = Evidence::new(10, "acquired here").with_role("acquired");
        let escaped = Evidence::new(20, "escapes here").with_role("escaped");
        let forward = LocatedDiagnostic::new(
            "src/A.cs",
            diag().with_evidence(vec![acquired.clone(), escaped.clone()]),
        );
        let reversed =
            LocatedDiagnostic::new("src/A.cs", diag().with_evidence(vec![escaped, acquired]));
        assert_ne!(forward.identity(), reversed.identity());
    }

    #[test]
    fn evidence_file_none_is_not_the_anchor_path() {
        let implicit = LocatedDiagnostic::new(
            "src/A.cs",
            diag().with_evidence(vec![Evidence::new(3, "registered here")]),
        );
        let explicit = LocatedDiagnostic::new(
            "src/A.cs",
            diag().with_evidence(vec![
                Evidence::new(3, "registered here").with_file("src/A.cs")
            ]),
        );
        assert_ne!(implicit.identity(), explicit.identity());
    }

    #[test]
    fn identical_records_share_one_identity() {
        let a = LocatedDiagnostic::new("src/A.cs", diag().with_subject("s#42")).with_column(col(4));
        let b = LocatedDiagnostic::new("src/A.cs", diag().with_subject("s#42")).with_column(col(4));
        assert_eq!(a.identity(), b.identity());
    }

    #[test]
    fn severity_separates_and_orders_deterministically() {
        let err = LocatedDiagnostic::new("src/A.cs", diag().with_severity(Severity::Error));
        let warn = LocatedDiagnostic::new("src/A.cs", diag().with_severity(Severity::Warning));
        assert_ne!(err.identity(), warn.identity());
        // Declaration order (Error, Warning) is the key order -- documented as a
        // determinism guarantee, not a claim that Error "outranks" Warning.
        assert!(err.identity() < warn.identity());
    }
}
