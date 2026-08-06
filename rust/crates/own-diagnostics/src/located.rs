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

use serde::{Deserialize, Serialize};

use crate::diagnostic::{Diagnostic, Evidence, Severity};

/// A [`Diagnostic`] together with the primary-location identity the ported
/// dataclass does not carry.
///
/// Serde shape matches `tests/fixtures/diag_model.json` exactly (regenerate:
/// `python tests/test_diag_model_fixtures.py --write`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocatedDiagnostic {
    /// The file this verdict is reported against, **verbatim** — the input
    /// identity, not a normalised path.
    pub path: String,
    /// The 1-based source column (#317), when the producer reported one.
    /// `None` means *not reported*; it is never substituted with a placeholder.
    #[serde(default)]
    pub column: Option<u32>,
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
    #[must_use]
    pub const fn with_column(mut self, column: u32) -> Self {
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
    pub column: Option<u32>,
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

    #[test]
    fn absent_column_never_equals_a_reported_one() {
        let bare = LocatedDiagnostic::new("src/A.cs", diag());
        let at_one = LocatedDiagnostic::new("src/A.cs", diag()).with_column(1);
        assert_ne!(bare.identity(), at_one.identity());
        // and `None` sorts before any reported column, deterministically.
        assert!(bare.identity() < at_one.identity());
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
        let a = LocatedDiagnostic::new("src/A.cs", diag().with_subject("s#42")).with_column(4);
        let b = LocatedDiagnostic::new("src/A.cs", diag().with_subject("s#42")).with_column(4);
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
