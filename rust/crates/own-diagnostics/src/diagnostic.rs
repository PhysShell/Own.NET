//! The verdict data model — an exact, data-only port of the `ownlang`
//! `Severity` / `Evidence` / `Diagnostic` dataclasses. No rendering, no solver
//! state: these are the values `own-analysis` will construct and the oracle will
//! compare on `(path, line, code)`.

use serde::{Deserialize, Serialize};

/// A diagnostic's severity. Serialises to the same `"error"`/`"warning"`
/// strings the Python `Severity` enum uses, so a future JSON/SARIF seam matches.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    /// A verdict that fails a build / red check.
    #[default]
    Error,
    /// Advisory — reported, but does not by itself fail the check.
    Warning,
}

/// One secondary, structured location explaining a diagnostic.
///
/// A single step in its reachability slice (where a resource was acquired, where
/// a borrow escapes, where a missing release should go). The primary
/// [`Diagnostic::line`] stays the anchor; evidence rides alongside it.
///
/// A data-only mirror of the Python `Evidence` dataclass; the `note:` / SARIF
/// projection is a later step and is deliberately not implemented here.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Evidence {
    /// 1-based source line of this step.
    pub line: u32,
    /// Human label for the step ("acquired here", "escapes here", …).
    pub label: String,
    /// The file of this step; `None` means "same file as the diagnostic's anchor".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
    /// What this step is, for consumers that group/colour evidence: a plain
    /// `"related"` by default, or a resource-protocol role
    /// (`acquired`/`released`/`escaped`/`consumed`/`step`).
    #[serde(default = "default_role")]
    pub role: String,
}

fn default_role() -> String {
    "related".to_owned()
}

impl Evidence {
    /// A `"related"` step in the same file as its diagnostic's anchor.
    #[must_use]
    pub fn new(line: u32, label: impl Into<String>) -> Self {
        Self {
            line,
            label: label.into(),
            file: None,
            role: default_role(),
        }
    }

    /// Set an explicit protocol role (`acquired`/`released`/`escaped`/…).
    #[must_use]
    pub fn with_role(mut self, role: impl Into<String>) -> Self {
        self.role = role.into();
        self
    }

    /// Set an explicit file (a cross-file evidence step).
    #[must_use]
    pub fn with_file(mut self, file: impl Into<String>) -> Self {
        self.file = Some(file.into());
        self
    }
}

/// A single ownership/lifetime/effect/DI verdict. A data-only mirror of the
/// Python `Diagnostic` dataclass, preserving its field order
/// (`code, message, line, severity, subject, resource_kind, evidence`).
///
/// Construct with [`Diagnostic::new`]: a code absent from [`TITLES`] is a bug,
/// not a blank finding, so construction fails loudly — the same guard as the
/// Python `__post_init__`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diagnostic {
    /// The diagnostic code (e.g. `"OWN001"`); must be present in [`TITLES`].
    pub code: String,
    /// The human message. Not part of the `(path, line, code)` parity key at
    /// this step (message-text parity is a later, fixture-backed contract).
    pub message: String,
    /// 1-based anchor line.
    pub line: u32,
    /// Severity; defaults to [`Severity::Error`].
    #[serde(default)]
    pub severity: Severity,
    /// A stable identity (`name#line`) of the subject, for report attribution.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subject: Option<String>,
    /// The resource's human "kind" (e.g. `"subscription token"`), when tagged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resource_kind: Option<String>,
    /// Ordered reachability slice; empty for a single-point finding.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence: Vec<Evidence>,
}

/// Returned by [`Diagnostic::new`] when handed a code with no [`TITLES`] entry —
/// the port of the Python "unknown diagnostic code" `ValueError`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownCode(pub String);

impl std::fmt::Display for UnknownCode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unknown diagnostic code {:?} (not in own_diagnostics::TITLES); \
             a code and its title must be added together",
            self.0
        )
    }
}

impl std::error::Error for UnknownCode {}

impl Diagnostic {
    /// A single-point verdict at `line` with the default severity (`Error`) and
    /// no subject/kind/evidence. Fails with [`UnknownCode`] if `code` is not a
    /// known [`TITLES`] entry — mirroring the Python construction guard.
    ///
    /// # Errors
    /// Returns [`UnknownCode`] when `code` has no [`TITLES`] entry.
    pub fn new(
        code: impl Into<String>,
        message: impl Into<String>,
        line: u32,
    ) -> Result<Self, UnknownCode> {
        let code = code.into();
        if title(&code).is_none() {
            return Err(UnknownCode(code));
        }
        Ok(Self {
            code,
            message: message.into(),
            line,
            severity: Severity::Error,
            subject: None,
            resource_kind: None,
            evidence: Vec::new(),
        })
    }

    /// Override the severity (builder style).
    #[must_use]
    pub const fn with_severity(mut self, severity: Severity) -> Self {
        self.severity = severity;
        self
    }

    /// Attach a subject identity (`name#line`).
    #[must_use]
    pub fn with_subject(mut self, subject: impl Into<String>) -> Self {
        self.subject = Some(subject.into());
        self
    }

    /// Attach a resource kind (e.g. `"subscription token"`).
    #[must_use]
    pub fn with_resource_kind(mut self, kind: impl Into<String>) -> Self {
        self.resource_kind = Some(kind.into());
        self
    }

    /// Attach an ordered evidence slice.
    #[must_use]
    pub fn with_evidence(mut self, evidence: Vec<Evidence>) -> Self {
        self.evidence = evidence;
        self
    }

    /// The human title for this diagnostic's code (always `Some` for a value
    /// built through [`Diagnostic::new`]).
    #[must_use]
    pub fn title(&self) -> Option<&'static str> {
        title(&self.code)
    }

    /// This diagnostic's `(line, code)` parity key — the per-file half of the
    /// `(path, line, code)` oracle comparison surface.
    #[must_use]
    pub fn key(&self) -> DiagKey {
        DiagKey {
            line: self.line,
            code: self.code.clone(),
        }
    }
}

/// The per-diagnostic parity key: a `(line, code)` pair.
///
/// The full oracle surface is `(path, line, code)` — the `path` is the input
/// identity, and a file's diagnostics are compared as the ordered `Vec<DiagKey>`
/// in emission order, so list position pins the deterministic intra-location
/// (same line + code) order.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct DiagKey {
    /// 1-based anchor line.
    pub line: u32,
    /// The diagnostic code.
    pub code: String,
}

impl DiagKey {
    /// Construct a key directly (used by the fixture replay).
    #[must_use]
    pub fn new(line: u32, code: impl Into<String>) -> Self {
        Self {
            line,
            code: code.into(),
        }
    }
}

/// The human title for a diagnostic `code`, or `None` if the code is unknown.
///
/// A panic-free binary search over the sorted [`TITLES`] table (its ordering is
/// asserted by a unit test), so it never indexes out of bounds.
#[must_use]
pub fn title(code: &str) -> Option<&'static str> {
    TITLES
        .binary_search_by(|(c, _)| (*c).cmp(code))
        .ok()
        .and_then(|i| TITLES.get(i))
        .map(|(_, t)| *t)
}

/// Every diagnostic code and its human title — the complete verdict vocabulary.
///
/// A verbatim port of `ownlang.diagnostics.TITLES`, kept **sorted by code** so
/// [`title`] can binary-search it; a unit test asserts the ordering and the
/// count so a hand edit that breaks either fails loudly.
pub static TITLES: &[(&str, &str)] = &[
    (
        "DI001",
        "captive dependency: a shorter-lived service is captured by a longer-lived one",
    ),
    (
        "DI002",
        "singleton captures a scoped service (captive dependency)",
    ),
    (
        "DI003",
        "singleton captures a transient service (captive dependency)",
    ),
    (
        "DI004",
        "scoped service resolved from the root provider (captured for the app lifetime)",
    ),
    (
        "DI005",
        "disposable transient resolved from a long-lived scope (delayed disposal)",
    ),
    (
        "EFF001",
        "reactive effect re-runs on an unstable dependency identity (render-time IO storm)",
    ),
    (
        "OBL001",
        "obligation still open when a barrier fires (open on every path)",
    ),
    (
        "OBL002",
        "obligation may still be open when a barrier fires (open on some path)",
    ),
    (
        "OBL003",
        "obligation not closed before the method exits (on every path)",
    ),
    (
        "OBL004",
        "obligation may not be closed before the method exits (on some path)",
    ),
    (
        "OBL005",
        "protocol scope matched no reported method -- rule is dead (advisory)",
    ),
    (
        "OWN001",
        "owned resource not released on all paths (possible leak)",
    ),
    ("OWN002", "use after release"),
    ("OWN003", "double release"),
    ("OWN004", "borrow escapes its scope"),
    ("OWN005", "use after move"),
    ("OWN006", "mutable borrow while a shared borrow is live"),
    ("OWN007", "move while borrowed"),
    ("OWN008", "release while borrowed"),
    (
        "OWN009",
        "use after possible release (released on some path)",
    ),
    ("OWN010", "use after possible move (moved on some path)"),
    (
        "OWN011",
        "mutable borrow while another mutable borrow is live",
    ),
    ("OWN012", "shared borrow while a mutable borrow is live"),
    ("OWN013", "owner accessed while it is mutably borrowed"),
    (
        "OWN014",
        "value escapes to a longer-lived region (lifetime promotion)",
    ),
    (
        "OWN015",
        "stack-backed buffer cannot escape the current function",
    ),
    (
        "OWN016",
        "stack-backed buffer moved to a longer-lived owner",
    ),
    (
        "OWN017",
        "movable buffer escape is not supported by code generation (PoC limitation)",
    ),
    ("OWN018", "buffer size must be an integer"),
    (
        "OWN019",
        "inline capacity too large for a stack-backed policy",
    ),
    ("OWN020", "unsupported construct (out of scope for the MVP)"),
    (
        "OWN021",
        "stack allocation requires a statically known bound",
    ),
    (
        "OWN023",
        "scratch fallback forbidden but the size may exceed the inline limit",
    ),
    ("OWN024", "sensitive buffer is not cleared on release"),
    (
        "OWN025",
        "full-length view of a pooled buffer reaches past its logical length",
    ),
    ("OWN030", "undefined name"),
    ("OWN031", "name already defined in this scope"),
    ("OWN032", "owned resource copied without 'move'"),
    ("OWN033", "function must return a value on all paths"),
    ("OWN034", "operation requires an owned resource"),
    ("OWN035", "return type mismatch"),
    ("OWN036", "cyclic lifetime ordering"),
    (
        "OWN040",
        "call to an undeclared function (unknown calls are forbidden)",
    ),
    ("OWN041", "call argument mismatch"),
    (
        "OWN050",
        "declaring type unresolved -- leakage analysis skipped",
    ),
    (
        "OWN051",
        "ownership transfer unverified -- local not checked past this call",
    ),
    (
        "OWN052",
        "interprocedural summary inference failed -- method summaries skipped",
    ),
];

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::*;

    #[test]
    fn titles_are_sorted_and_unique() {
        let codes: Vec<&str> = TITLES.iter().map(|(c, _)| *c).collect();
        let mut sorted = codes.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(
            codes, sorted,
            "TITLES must be strictly sorted by code and unique (title() binary-searches it)"
        );
    }

    #[test]
    fn titles_count_matches_python_reference() {
        // Locked to `len(ownlang.diagnostics.TITLES)` — a drift on either side is
        // a real vocabulary change and must be made on both, together.
        assert_eq!(TITLES.len(), 47);
    }

    #[test]
    fn title_lookup_is_panic_free_and_correct() {
        assert_eq!(
            title("OWN001"),
            Some("owned resource not released on all paths (possible leak)")
        );
        assert_eq!(
            title("OWN020"),
            Some("unsupported construct (out of scope for the MVP)")
        );
        assert_eq!(
            title("EFF001"),
            Some(
                "reactive effect re-runs on an unstable dependency identity (render-time IO storm)"
            )
        );
        assert_eq!(title("NOPE999"), None);
        assert_eq!(title(""), None);
    }

    #[test]
    fn new_rejects_unknown_code() {
        let err = Diagnostic::new("OWN999", "nope", 1).unwrap_err();
        assert_eq!(err.0, "OWN999");
        assert!(err.to_string().contains("unknown diagnostic code"));
    }

    #[test]
    fn new_accepts_known_code_with_defaults() {
        let d = Diagnostic::new("OWN001", "leak", 12).expect("OWN001 is known");
        assert_eq!(d.severity, Severity::Error);
        assert_eq!(d.subject, None);
        assert!(d.evidence.is_empty());
        assert_eq!(d.key(), DiagKey::new(12, "OWN001"));
        assert!(d.title().is_some());
    }

    #[test]
    fn severity_serialises_like_python() {
        assert_eq!(
            serde_json::to_string(&Severity::Error).unwrap(),
            "\"error\""
        );
        assert_eq!(
            serde_json::to_string(&Severity::Warning).unwrap(),
            "\"warning\""
        );
    }
}
