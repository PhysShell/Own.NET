//! Infer# (`report.json`) -> SARIF 2.1.0.
//!
//! Pure and capability-free: input bytes in, SARIF bytes out. No filesystem,
//! no clock, no network — enforced by the world having zero imports. A crafted
//! `report.json` from a hostile target can, at worst, make us return `Err`; it
//! cannot escape the sandbox.

#[allow(warnings)]
mod bindings;

// NOTE: cargo-component generates `bindings.rs`. The exact module path of
// `RawInput` and the `Guest` trait depends on the generated layout; the two
// `use` lines below match the conventional cargo-component output for this
// world — if `cargo component build` disagrees, nudge them (BUILD.md §bindings).
use bindings::Guest;
use bindings::ownaudit::adapter::types::RawInput;

use serde::Deserialize;
use serde_json::json;

/// One Infer# finding, as emitted in `report.json` (fields we use; unknowns
/// are ignored by serde).
#[derive(Deserialize)]
struct InferBug {
    bug_type: String,
    #[serde(default)]
    bug_type_hum: String,
    #[serde(default)]
    qualifier: String,
    #[serde(default)]
    severity: String,
    #[serde(default)]
    file: String,
    #[serde(default)]
    line: i64,
    #[serde(default)]
    column: i64,
    #[serde(default)]
    procedure: String,
    #[serde(default)]
    hash: String,
}

struct Component;

impl Guest for Component {
    fn to_sarif(input: RawInput) -> Result<Vec<u8>, String> {
        // Infer# writes report.json to a file; the host pre-reads it into
        // `artifacts`. Prefer the named artifact, fall back to stdout.
        let raw = input
            .artifacts
            .iter()
            .find(|b| b.name.ends_with("report.json") || b.name == "report.json")
            .map(|b| b.bytes.as_slice())
            .filter(|b| !b.is_empty())
            .unwrap_or(input.stdout.as_slice());

        if raw.is_empty() {
            return Err("no report.json artifact and empty stdout".into());
        }

        let bugs: Vec<InferBug> = serde_json::from_slice(raw)
            .map_err(|e| format!("parsing Infer# report.json: {e}"))?;

        // Distinct rules, in first-seen order.
        let mut rules: Vec<serde_json::Value> = Vec::new();
        let mut seen: Vec<String> = Vec::new();
        for b in &bugs {
            if !seen.iter().any(|r| r == &b.bug_type) {
                seen.push(b.bug_type.clone());
                let name = if b.bug_type_hum.is_empty() {
                    b.bug_type.clone()
                } else {
                    b.bug_type_hum.clone()
                };
                rules.push(json!({
                    "id": b.bug_type,
                    "name": name,
                }));
            }
        }

        let results: Vec<serde_json::Value> = bugs
            .iter()
            .map(|b| {
                json!({
                    "ruleId": b.bug_type,
                    "level": level_of(&b.severity),
                    "message": { "text": message_of(b) },
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": b.file,
                                "uriBaseId": "SRCROOT"
                            },
                            "region": region_of(b)
                        },
                        "logicalLocations": logical_of(b)
                    }],
                    "partialFingerprints": fingerprints_of(b)
                })
            })
            .collect();

        let base = if input.base_uri.is_empty() {
            json!({})
        } else {
            json!({ "SRCROOT": { "uri": input.base_uri } })
        };

        let sarif = json!({
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "tool": { "driver": {
                    "name": "Infer#",
                    "informationUri": "https://github.com/microsoft/infersharpaction",
                    "rules": rules
                }},
                "originalUriBaseIds": base,
                "results": results
            }]
        });

        serde_json::to_vec(&sarif).map_err(|e| format!("serializing SARIF: {e}"))
    }
}

fn level_of(severity: &str) -> &'static str {
    match severity.to_ascii_uppercase().as_str() {
        "ERROR" => "error",
        "WARNING" => "warning",
        "INFO" | "ADVICE" | "LIKE" => "note",
        _ => "warning",
    }
}

fn message_of(b: &InferBug) -> String {
    if b.qualifier.is_empty() {
        b.bug_type.clone()
    } else {
        b.qualifier.clone()
    }
}

fn region_of(b: &InferBug) -> serde_json::Value {
    let mut r = serde_json::Map::new();
    if b.line > 0 {
        r.insert("startLine".into(), json!(b.line));
    }
    if b.column > 0 {
        r.insert("startColumn".into(), json!(b.column));
    }
    serde_json::Value::Object(r)
}

fn logical_of(b: &InferBug) -> serde_json::Value {
    if b.procedure.is_empty() {
        json!([])
    } else {
        json!([{ "fullyQualifiedName": b.procedure, "kind": "function" }])
    }
}

fn fingerprints_of(b: &InferBug) -> serde_json::Value {
    if b.hash.is_empty() {
        json!({})
    } else {
        json!({ "inferHash/v1": b.hash })
    }
}

bindings::export!(Component with_types_in bindings);
