//! Passthrough adapter — for tools that already emit SARIF (Roslyn, CodeQL).
//!
//! Not an identity function: it makes native-SARIF output take the *same*
//! sandboxed, validated, provenance-stamped path as everything else. Their
//! SARIF is still derived from untrusted target code, so parsing it inside a
//! zero-import component is defensible — a malformed `.sarif` traps here
//! instead of corrupting the run.
//!
//! Does: parse -> assert SARIF 2.1.x with runs[] -> normalize version quirks
//! (canonical "2.1.0", ensure $schema) -> re-emit. Pure, capability-free.

#[allow(warnings)]
mod bindings;

use bindings::Guest;
use bindings::ownaudit::adapter::types::RawInput;

use serde_json::Value;

struct Component;

impl Guest for Component {
    fn to_sarif(input: RawInput) -> Result<Vec<u8>, String> {
        // Prefer a .sarif artifact; fall back to stdout.
        let raw = input
            .artifacts
            .iter()
            .find(|b| b.name.ends_with(".sarif") || b.name.ends_with(".sarif.json"))
            .map(|b| b.bytes.as_slice())
            .filter(|b| !b.is_empty())
            .unwrap_or(input.stdout.as_slice());

        if raw.is_empty() {
            return Err("no .sarif artifact and empty stdout".into());
        }

        let mut v: Value =
            serde_json::from_slice(raw).map_err(|e| format!("input is not JSON: {e}"))?;

        // Some tools stamp "2.1.0-rtm.6" etc; accept any 2.1.x, canonicalize.
        let ver = v.get("version").and_then(|s| s.as_str()).unwrap_or("");
        if !ver.starts_with("2.1") {
            return Err(format!("not SARIF 2.1.x (version = {ver:?})"));
        }
        if !v.get("runs").map(Value::is_array).unwrap_or(false) {
            return Err("missing runs[]".into());
        }

        if let Some(obj) = v.as_object_mut() {
            obj.insert("version".into(), Value::String("2.1.0".into()));
            obj.entry("$schema").or_insert(Value::String(
                "https://json.schemastore.org/sarif-2.1.0.json".into(),
            ));
        }

        serde_json::to_vec(&v).map_err(|e| format!("serializing SARIF: {e}"))
    }
}

bindings::export!(Component with_types_in bindings);
