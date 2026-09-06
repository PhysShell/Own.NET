//! The bridge's OUTPUT surfaces — `ownlang/ownir.py`'s `render_finding` and
//! `build_sarif` (spec/Bridge.md BR-V9), at the #259 checkpoint-5.3 surface.
//!
//! This is the second SARIF builder in the tree, and the split is deliberate.
//! `own_diagnostics::sarif` is the `.own` flow-diagnostic path (#256): one file
//! per run, `Diagnostic` values, no `properties`, no `suppressions`, no
//! `startColumn`, no schema stamp. The bridge's is the C#/DI path over
//! `ownir.Finding`: a file per finding, the subscription triple in
//! `properties`, `[OwnIgnore]` in `suppressions`, the #317 column in the
//! region, and the `ownirSchemaVersion` stamp on the driver. Where the two
//! formats coincide the core's builder is REUSED rather than re-derived — the
//! `codeFlows` projection is `own_diagnostics::code_flow` verbatim.
//!
//! **Where they do not coincide, reuse would be a bug.** The core's
//! `related_locations` drops a step with an empty file (an empty
//! `artifactLocation.uri` makes a log unprocessable for GitHub code scanning —
//! the invariant `evidence.py` calls out by name); the bridge's `relatedLocations`
//! is an inline comprehension in `ownir.py` that filters on the LINE alone and
//! emits the empty uri. That difference is the reference's, not a defect this
//! port may tidy, so this module builds its own — and
//! `tests/fixtures/verdict_renders/render_evidence_slices` is the golden that
//! goes red if someone "simplifies" it into the shared builder.
//!
//! Serialization order is part of the surface: the reference builds Python
//! dicts and `json.dumps` writes them in insertion order, so every struct here
//! declares its fields in that order and `skip_serializing_if` reproduces the
//! keys the reference splices in conditionally.

use own_diagnostics::{code_flow, title, Step as CoreStep};
use serde::Serialize;

use crate::verdict::{Finding, Step};

/// `_SARIF_SCHEMA` / `_SARIF_INFO_URI` / the tool identity, from `ownir.py`.
const SARIF_SCHEMA: &str = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json";
const SARIF_INFO_URI: &str = "https://github.com/PhysShell/Own.NET";
const SARIF_VERSION: &str = "2.1.0";
const TOOL_NAME: &str = "Owen";
/// `OWNIR_VERSION` — the schema stamp the driver carries so a consumer can tell
/// which fact vocabulary produced the log.
const OWNIR_VERSION: u32 = 0;

/// `_esc_data`: a GitHub workflow-command MESSAGE escapes only `%`, CR and LF.
fn esc_data(s: &str) -> String {
    s.replace('%', "%25")
        .replace('\r', "%0D")
        .replace('\n', "%0A")
}

/// `_esc_prop`: a workflow-command PROPERTY value additionally treats `:` and
/// `,` as separators. Applied on top of the message escaping, in that order —
/// the `%` of a `%3A` must not be re-escaped, which is why `_esc_data` runs
/// first and the two extra replacements after it.
fn esc_prop(s: &str) -> String {
    esc_data(s).replace(':', "%3A").replace(',', "%2C")
}

/// `Finding.render` — the human CLI line.
fn render_human(f: &Finding, severity: &str) -> String {
    format!(
        "{}:{}: {severity}: [{}] {} [resource: {}]",
        f.file, f.line, f.code, f.message, f.kind
    )
}

/// `Finding.render_github` — a GitHub Actions workflow annotation.
fn render_github(f: &Finding, severity: &str) -> String {
    let message = format!("[{}] {} [resource: {}]", f.code, f.message, f.kind);
    format!(
        "::{severity} file={},line={},title={}::{}",
        esc_prop(&f.file),
        f.line,
        esc_prop(&f.code),
        esc_data(&message)
    )
}

/// `Finding.render_msbuild` — `file(line): severity CODE: message`, the format
/// `dotnet build` and the VS Error List parse.
fn render_msbuild(f: &Finding, severity: &str) -> String {
    format!(
        "{}({}): {severity} {}: {} [resource: {}]",
        f.file, f.line, f.code, f.message, f.kind
    )
}

/// `render_finding`: the human line is the fallback for any format this
/// surface does not know — a typo in `--format` must not silence a finding.
#[must_use]
pub fn render_finding(f: &Finding, fmt: &str, severity: &str) -> String {
    match fmt {
        "github" => render_github(f, severity),
        "msbuild" => render_msbuild(f, severity),
        _ => render_human(f, severity),
    }
}

#[derive(Debug, Serialize)]
struct ArtifactLocation {
    uri: String,
}

/// The bridge's region: the 1-based line, and the #317 column only when the
/// producer reported one AND a line is being emitted at all.
#[derive(Debug, Serialize)]
struct Region {
    #[serde(rename = "startLine")]
    start_line: i64,
    #[serde(rename = "startColumn", skip_serializing_if = "Option::is_none")]
    start_column: Option<i64>,
}

#[derive(Debug, Serialize)]
struct PhysicalLocation {
    #[serde(rename = "artifactLocation")]
    artifact_location: ArtifactLocation,
    #[serde(skip_serializing_if = "Option::is_none")]
    region: Option<Region>,
}

#[derive(Debug, Serialize)]
struct Message {
    text: String,
}

#[derive(Debug, Serialize)]
struct Location {
    #[serde(rename = "physicalLocation")]
    physical_location: PhysicalLocation,
}

#[derive(Debug, Serialize)]
struct RelatedLocation {
    #[serde(rename = "physicalLocation")]
    physical_location: PhysicalLocation,
    message: Message,
}

/// `[OwnIgnore("reason")]` (#209): a suppressed finding stays in `results` so a
/// consumer counts it, and carries why.
#[derive(Debug, Serialize)]
struct Suppression {
    kind: &'static str,
    justification: String,
}

#[derive(Debug, Serialize)]
struct Properties {
    #[serde(rename = "resourceKind")]
    resource_kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    component: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    event: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    handler: Option<String>,
}

#[derive(Debug, Serialize)]
struct SarifResult {
    #[serde(rename = "ruleId")]
    rule_id: String,
    level: String,
    message: Message,
    locations: Vec<Location>,
    properties: Properties,
    #[serde(rename = "relatedLocations", skip_serializing_if = "Vec::is_empty")]
    related_locations: Vec<RelatedLocation>,
    #[serde(rename = "codeFlows", skip_serializing_if = "Vec::is_empty")]
    code_flows: Vec<own_diagnostics::CodeFlow>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    suppressions: Vec<Suppression>,
}

#[derive(Debug, Serialize)]
struct Rule {
    id: String,
    #[serde(rename = "shortDescription")]
    short_description: Message,
}

#[derive(Debug, Serialize)]
struct DriverProperties {
    #[serde(rename = "ownirSchemaVersion")]
    ownir_schema_version: u32,
}

#[derive(Debug, Serialize)]
struct Driver {
    name: &'static str,
    #[serde(rename = "informationUri")]
    information_uri: &'static str,
    rules: Vec<Rule>,
    properties: DriverProperties,
}

#[derive(Debug, Serialize)]
struct Tool {
    driver: Driver,
}

#[derive(Debug, Serialize)]
struct Run {
    tool: Tool,
    results: Vec<SarifResult>,
}

/// A complete SARIF 2.1.0 log from the bridge path.
#[derive(Debug, Serialize)]
pub struct SarifLog {
    #[serde(rename = "$schema")]
    schema: &'static str,
    version: &'static str,
    runs: Vec<Run>,
}

/// `_sarif_level`: an advisory is SARIF's dedicated `note` — a consumer can
/// tell "could not check this" from a warning-tier leak, which the flat
/// error/warning surfaces cannot express. The host severity only ever lowers.
fn sarif_level(f: &Finding, severity: &str) -> String {
    if f.advisory {
        return "note".to_owned();
    }
    if severity == "warning" || f.severity.as_deref() == Some("warning") {
        return "warning".to_owned();
    }
    "error".to_owned()
}

/// The primary `physicalLocation`. Backslashes fold to forward slashes so a
/// Windows-produced log stays consumable; `region` is omitted entirely for a
/// file-level finding, and a column never appears without a line.
fn primary_location(f: &Finding) -> PhysicalLocation {
    PhysicalLocation {
        artifact_location: ArtifactLocation {
            uri: f.file.replace('\\', "/"),
        },
        region: (f.line >= 1).then_some(Region {
            start_line: f.line,
            start_column: f.column,
        }),
    }
}

/// The bridge's `relatedLocations`. See the module docs: this filters on the
/// LINE alone, so a step whose file is empty emits an empty uri — the
/// reference's behaviour, and NOT `own_diagnostics::related_locations`'.
fn related_locations(related: &[Step]) -> Vec<RelatedLocation> {
    related
        .iter()
        .filter(|(_, line, _)| *line >= 1)
        .map(|(file, line, label)| RelatedLocation {
            physical_location: PhysicalLocation {
                artifact_location: ArtifactLocation {
                    uri: file.replace('\\', "/"),
                },
                region: Some(Region {
                    start_line: *line,
                    start_column: None,
                }),
            },
            message: Message {
                text: label.clone(),
            },
        })
        .collect()
}

/// The ordered `codeFlows`, through the core's own builder — the one place the
/// two SARIF paths genuinely share a format (`evidence.code_flow`).
fn code_flows(flow: &[Step]) -> Vec<own_diagnostics::CodeFlow> {
    let steps: Vec<CoreStep<'_>> = flow
        .iter()
        .filter_map(|(file, line, label)| {
            u32::try_from(*line)
                .ok()
                .map(|line| CoreStep { file, line, label })
        })
        .collect();
    code_flow(&steps)
}

fn optional(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_owned())
}

fn sarif_result(f: &Finding, severity: &str) -> SarifResult {
    SarifResult {
        rule_id: f.code.clone(),
        level: sarif_level(f, severity),
        message: Message {
            text: format!("{} [resource: {}]", f.message, f.kind),
        },
        locations: vec![Location {
            physical_location: primary_location(f),
        }],
        properties: Properties {
            resource_kind: f.kind.clone(),
            component: optional(&f.component),
            event: optional(&f.event),
            handler: optional(&f.handler),
        },
        related_locations: related_locations(&f.related),
        code_flows: code_flows(&f.flow),
        suppressions: f
            .ignore_reason
            .as_ref()
            .map(|reason| Suppression {
                kind: "inSource",
                justification: reason.clone(),
            })
            .into_iter()
            .collect(),
    }
}

/// `build_sarif`: the whole run as one SARIF 2.1.0 log.
///
/// One `run` whose driver is Owen, with a rule catalogue of the codes PRESENT
/// (sorted and deduplicated, each with its `TITLES` text, an unknown code
/// falling back to itself) and one result per finding in the bridge's own
/// order. Two orderings in one log, on purpose: sorting `results` would
/// destroy the BR-V8 order the tie-breaking depends on.
#[must_use]
pub fn build_sarif(findings: &[Finding], severity: &str) -> SarifLog {
    let mut codes: Vec<&str> = findings.iter().map(|f| f.code.as_str()).collect();
    codes.sort_unstable();
    codes.dedup();
    SarifLog {
        schema: SARIF_SCHEMA,
        version: SARIF_VERSION,
        runs: vec![Run {
            tool: Tool {
                driver: Driver {
                    name: TOOL_NAME,
                    information_uri: SARIF_INFO_URI,
                    rules: codes
                        .into_iter()
                        .map(|code| Rule {
                            id: code.to_owned(),
                            short_description: Message {
                                text: title(code).unwrap_or(code).to_owned(),
                            },
                        })
                        .collect(),
                    properties: DriverProperties {
                        ownir_schema_version: OWNIR_VERSION,
                    },
                },
            },
            results: findings.iter().map(|f| sarif_result(f, severity)).collect(),
        }],
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]
mod tests {
    use super::{related_locations, Step};

    /// The bridge's `relatedLocations` drops a step whose line is unknown. No
    /// facts document can produce one — `_consumer_related` and the DI004/DI005
    /// builders each require their line to be `>= 1` before they emit a step at
    /// all — so the filter is defensive, and the rendered goldens cannot
    /// exercise it. It is the reference's rule either way, and a port that
    /// dropped it would emit `"startLine": 0`, which is not a SARIF coordinate.
    ///
    /// The empty-FILE half of this builder is the opposite case and needs no
    /// unit test: it is reachable, and `render_evidence_slices` is its golden.
    #[test]
    fn a_related_step_with_no_line_is_dropped() {
        let steps: Vec<Step> = vec![
            ("a.cs".to_owned(), 0, "no line".to_owned()),
            ("b.cs".to_owned(), -3, "negative line".to_owned()),
            ("c.cs".to_owned(), 4, "kept".to_owned()),
        ];
        let out = related_locations(&steps);
        assert_eq!(out.len(), 1, "only the resolvable step survives");
        assert_eq!(out[0].message.text, "kept");
        assert_eq!(
            out[0]
                .physical_location
                .region
                .as_ref()
                .expect("a kept step carries its region")
                .start_line,
            4
        );
    }
}
