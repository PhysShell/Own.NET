//! SARIF 2.1.0 projection — the port of `ownlang/diag_sarif.py` plus the two
//! evidence builders it uses from `ownlang/evidence.py` (P-022 step 5b, #256).
//!
//! This is the `.own` **flow-diagnostic** SARIF path, the one behind
//! `check --format sarif`. The repo has a second SARIF builder,
//! `ownlang.ownir.build_sarif` over `ownir.Finding` (the C#/DI path, the
//! `DI`/`EFF`/`OBL` codes). That one is deliberately **not** ported here: it needs `OwnIR`, and
//! `own-diagnostics` may depend only on the span leaf. It lands with the bridge
//! (#259), not with this step.
//!
//! Modelled as typed structs rather than a JSON value so the shape is checked at
//! compile time and the crate gains no runtime JSON dependency — the same idiom
//! [`crate::Diagnostic`] already uses. `serde_json` stays a dev-dependency, used
//! only by the replay test.
//!
//! ## The three semantics a naive port gets wrong
//!
//! Each is pinned by a case in `tests/fixtures/sarif_parity.json`
//! (regenerate: `python tests/test_sarif_parity_fixtures.py --write`):
//!
//! * **`Evidence.file` falls back on emptiness, not absence.** Python writes
//!   `e.file or filename`, which is truthiness: `Some("")` takes the fallback
//!   just as `None` does. Reading it as `Option`-presence would emit an empty
//!   `artifactLocation.uri`, which makes the whole log unprocessable for GitHub
//!   code scanning — the one invariant `evidence.py` calls out by name.
//! * **`resource_kind` appends on emptiness, not absence.** `if d.resource_kind`
//!   is truthiness too, so `Some("")` adds *no* suffix. An `Option`-presence
//!   port emits `" [resource: ]"` into user-visible message text.
//! * **`results` follow input order; `rules` are sorted.** Two orderings in one
//!   log. Sorting `results` to match the catalogue would destroy the emission
//!   order that ties (equal code *and* message at different lines) depend on.
//!
//! ## Which layer catches what (measured, `--no-fail-fast`)
//!
//! | mutation | caught by |
//! |---|---|
//! | `Evidence.file` read as `Option`-presence | parity replay **only** |
//! | `resource_kind` read as `Option`-presence | parity replay only |
//! | `results` sorted by code | parity replay only |
//! | backslash normalization removed | parity replay **and** the uri invariant |
//! | `region` emitted for a file-level line | parity replay only |
//! | canonicalizer also sorting arrays | the canonicalizer's own guard |
//!
//! The first row is worth stating plainly, because the obvious intuition is
//! wrong: the "no empty `artifactLocation.uri`" test does **not** catch the
//! `Evidence.file` truthiness bug. Under that mutation the resolved file is
//! `""`, so [`emittable`] *drops* the step instead of emitting an empty uri —
//! the symptom is a silently missing evidence step, not a malformed one. Only
//! the reference comparison sees it. A port that shipped the uri invariant and
//! called the truthiness case covered would be wrong about its own coverage.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

use crate::{title, Diagnostic, Severity};

/// Mirrors the constants in `ownlang.diag_sarif`; both SARIF paths in the
/// reference emit the same 2.1.0 shape from one tool identity.
const SARIF_SCHEMA: &str = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json";
const SARIF_INFO_URI: &str = "https://github.com/PhysShell/Own.NET";
const SARIF_VERSION: &str = "2.1.0";
/// The tool identity. #256 requires this stays `Owen`.
const TOOL_NAME: &str = "Owen";

/// One evidence step resolved to a concrete location: `(file, line, label)`.
///
/// The port of `ownlang.evidence.Step`. `file` is already resolved — the
/// "same file as the anchor" convention is applied by [`steps_for`] before a
/// step reaches the builders, exactly as the reference requires of its callers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Step<'a> {
    /// Concrete artifact path; never the empty string for an emitted step.
    pub file: &'a str,
    /// 1-based source line; `0` marks a file-level step, which is dropped.
    pub line: u32,
    /// Human label for what happens here.
    pub label: &'a str,
}

/// A SARIF `artifactLocation`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactLocation {
    pub uri: String,
}

/// A SARIF `region`. Only ever carries the 1-based `startLine` this path emits.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Region {
    #[serde(rename = "startLine")]
    pub start_line: u32,
}

/// A SARIF `physicalLocation`.
///
/// `region` is `None` for a file-level location (line < 1): the reference omits
/// it rather than emitting a bogus `startLine`, keeping the log schema-valid.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PhysicalLocation {
    #[serde(rename = "artifactLocation")]
    pub artifact_location: ArtifactLocation,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub region: Option<Region>,
}

/// A SARIF `message`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Message {
    pub text: String,
}

/// A bare location — the primary `locations[]` entry, which carries no message.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Location {
    #[serde(rename = "physicalLocation")]
    pub physical_location: PhysicalLocation,
}

/// A labelled location: a `relatedLocations[]` entry, and the inner `location`
/// of a thread-flow step. The reference builds both from one shape.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LabelledLocation {
    #[serde(rename = "physicalLocation")]
    pub physical_location: PhysicalLocation,
    pub message: Message,
}

/// One `threadFlows[].locations[]` entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ThreadFlowLocation {
    pub location: LabelledLocation,
}

/// One `threadFlows[]` entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ThreadFlow {
    pub locations: Vec<ThreadFlowLocation>,
}

/// One `codeFlows[]` entry — the ordered reachability slice.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CodeFlow {
    #[serde(rename = "threadFlows")]
    pub thread_flows: Vec<ThreadFlow>,
}

/// One SARIF `result`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SarifResult {
    #[serde(rename = "ruleId")]
    pub rule_id: String,
    pub level: String,
    pub message: Message,
    pub locations: Vec<Location>,
    /// Omitted entirely when no evidence step survives — not emitted empty.
    #[serde(
        rename = "relatedLocations",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub related_locations: Vec<LabelledLocation>,
    /// Omitted entirely when no evidence step survives — not emitted empty.
    #[serde(rename = "codeFlows", default, skip_serializing_if = "Vec::is_empty")]
    pub code_flows: Vec<CodeFlow>,
}

/// A `tool.driver.rules[]` entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rule {
    pub id: String,
    #[serde(rename = "shortDescription")]
    pub short_description: Message,
}

/// The `tool.driver`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Driver {
    pub name: String,
    #[serde(rename = "informationUri")]
    pub information_uri: String,
    pub rules: Vec<Rule>,
}

/// The `tool`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tool {
    pub driver: Driver,
}

/// One SARIF `run`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Run {
    pub tool: Tool,
    pub results: Vec<SarifResult>,
}

/// A complete SARIF 2.1.0 log.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SarifLog {
    #[serde(rename = "$schema")]
    pub schema: String,
    pub version: String,
    pub runs: Vec<Run>,
}

/// A SARIF `physicalLocation` for a 1-based line.
///
/// Backslashes become forward slashes so a Windows-produced log stays
/// consumable; `region` is omitted for a file-level location.
fn phys(file: &str, line: u32) -> PhysicalLocation {
    PhysicalLocation {
        artifact_location: ArtifactLocation {
            uri: file.replace('\\', "/"),
        },
        region: (line >= 1).then_some(Region { start_line: line }),
    }
}

/// Is this step emittable at all?
///
/// The port of the reference's `if ln >= 1 and f`: a step needs both a
/// resolvable line and a non-empty file. A related location with nowhere to
/// point is noise, and an empty `artifactLocation.uri` makes the whole log
/// unprocessable for GitHub code scanning.
const fn emittable(step: &Step<'_>) -> bool {
    step.line >= 1 && !step.file.is_empty()
}

/// Resolve a diagnostic's evidence into concrete steps.
///
/// The port of `diag_sarif._steps`. **`Evidence.file` falls back on emptiness,
/// not absence** — `e.file or filename` is Python truthiness, so `Some("")`
/// resolves to `filename` exactly as `None` does.
#[must_use]
pub fn steps_for<'a>(diagnostic: &'a Diagnostic, filename: &'a str) -> Vec<Step<'a>> {
    diagnostic
        .evidence
        .iter()
        .map(|e| Step {
            file: match e.file.as_deref() {
                Some(f) if !f.is_empty() => f,
                _ => filename,
            },
            line: e.line,
            label: &e.label,
        })
        .collect()
}

/// SARIF `relatedLocations` — the unordered secondary anchors.
#[must_use]
pub fn related_locations(steps: &[Step<'_>]) -> Vec<LabelledLocation> {
    steps
        .iter()
        .filter(|s| emittable(s))
        .map(|s| LabelledLocation {
            physical_location: phys(s.file, s.line),
            message: Message {
                text: s.label.to_owned(),
            },
        })
        .collect()
}

/// SARIF `codeFlows` — the *ordered* reachability slice.
///
/// Returns an empty vector when no step survives, so the caller omits the key
/// rather than emitting an empty one (the reference returns `[]` for the same
/// reason).
#[must_use]
pub fn code_flow(steps: &[Step<'_>]) -> Vec<CodeFlow> {
    let locations: Vec<ThreadFlowLocation> = steps
        .iter()
        .filter(|s| emittable(s))
        .map(|s| ThreadFlowLocation {
            location: LabelledLocation {
                physical_location: phys(s.file, s.line),
                message: Message {
                    text: s.label.to_owned(),
                },
            },
        })
        .collect();
    if locations.is_empty() {
        return Vec::new();
    }
    vec![CodeFlow {
        thread_flows: vec![ThreadFlow { locations }],
    }]
}

/// One SARIF `result` for a diagnostic.
///
/// `severity` is a presentation choice that only sets `level`, and it only ever
/// *raises*: a diagnostic that is intrinsically a warning stays a warning
/// whatever the caller asks for.
fn result_for(diagnostic: &Diagnostic, filename: &str, severity: &str) -> SarifResult {
    let level = if severity == "warning" || diagnostic.severity == Severity::Warning {
        "warning"
    } else {
        "error"
    };
    // Truthiness, not presence: an empty `resource_kind` adds no suffix.
    let kind = match diagnostic.resource_kind.as_deref() {
        Some(k) if !k.is_empty() => format!(" [resource: {k}]"),
        _ => String::new(),
    };
    let steps = steps_for(diagnostic, filename);
    SarifResult {
        rule_id: diagnostic.code.clone(),
        level: level.to_owned(),
        message: Message {
            text: format!("{}{kind}", diagnostic.message),
        },
        locations: vec![Location {
            physical_location: phys(filename, diagnostic.line),
        }],
        related_locations: related_locations(&steps),
        code_flows: code_flow(&steps),
    }
}

/// Render flow diagnostics as a single SARIF 2.1.0 log.
///
/// One `run` whose `tool.driver` is `Owen` with a `rules` catalogue of the codes
/// present, and one `result` per diagnostic **in input order**. `severity` only
/// sets each result's `level`.
///
/// Two independent orderings live here on purpose: `rules` is sorted and
/// deduplicated by code, while `results` preserves the order the caller emitted.
/// Sorting `results` to match the catalogue would collapse the tie ordering that
/// equal-code, equal-message diagnostics at different lines depend on.
#[must_use]
pub fn build_sarif(diagnostics: &[Diagnostic], filename: &str, severity: &str) -> SarifLog {
    let codes: BTreeSet<&str> = diagnostics.iter().map(|d| d.code.as_str()).collect();
    let rules = codes
        .into_iter()
        .map(|code| Rule {
            id: code.to_owned(),
            // The reference is `TITLES.get(code, code)`: an unknown code falls
            // back to itself rather than vanishing from the catalogue.
            short_description: Message {
                text: title(code).unwrap_or(code).to_owned(),
            },
        })
        .collect();
    SarifLog {
        schema: SARIF_SCHEMA.to_owned(),
        version: SARIF_VERSION.to_owned(),
        runs: vec![Run {
            tool: Tool {
                driver: Driver {
                    name: TOOL_NAME.to_owned(),
                    information_uri: SARIF_INFO_URI.to_owned(),
                    rules,
                },
            },
            results: diagnostics
                .iter()
                .map(|d| result_for(d, filename, severity))
                .collect(),
        }],
    }
}
