//! The MOS parity dump — `ownlang/ownir.py::dump_summaries`, serialized as
//! the `python -m ownlang summaries` CLI prints it (spec/Inference.md §8).
//!
//! The output contract is BYTE-EXACT stdout parity with the reference:
//! `json.dumps(doc, indent=2, sort_keys=True)` plus the newline `print`
//! appends. That serialization keeps Python's `ensure_ascii` default (unlike
//! the Layer 2 surface, which pins `ensure_ascii=False`), so this module
//! carries its own emitter: sorted keys at every level, 2-space indent, and
//! `\uXXXX` escapes (surrogate pairs above the BMP) for everything outside
//! printable ASCII — `serde_json` cannot produce that shape.
//!
//! Determinism is the point (INF-R1): summaries sorted by method key, the
//! unresolved log sorted, fixed field vocabulary — the same facts yield
//! byte-identical output regardless of `functions[]` input order, which is
//! what makes the dump a parity artifact rather than a debug log. A failed
//! solve degrades exactly like the reference: empty `summaries`/`unresolved`
//! with the reason under `degraded` (INF-F6), never a crash.

// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules; pub(crate) is the honest
// visibility here (same stance as `mos.rs`).
#![allow(clippy::redundant_pub_crate)]

use crate::lower::{as_list, build_skeletons, py_str};
use crate::mos;
use crate::BridgeError;
use own_ir::{OwnIr, OWNIR_VERSION};
use serde_json::{json, Value};

/// Render the summaries document for one `OwnIR` facts document —
/// byte-identical to `python -m ownlang summaries` on the same facts.
///
/// Scope note (the `py_str` caveat, same as the Layer 2 surface): the
/// reference `str()`-ifies raw metadata scalars (`module`, and the
/// per-record `name`/`file` the skeleton builder reads), and neither door
/// validates their TYPE — a container placed where a scalar belongs would
/// render as Python `repr` there and as JSON text here. That shape has no
/// producer, cannot be reproduced faithfully for dicts at all
/// (`serde_json`'s map re-sorts keys; Python `str()` keeps insertion
/// order), and is kept OUT of the parity contract rather than
/// half-emulated: the harness pins only scalar-metadata corpora, and any
/// future fixture that smuggles a container in goes red on the byte diff
/// instead of diverging silently.
///
/// # Errors
/// [`BridgeError`] only if the typed facts cannot be re-serialized to JSON
/// (not reachable for a document `OwnIr::from_json` accepted); a SOLVER
/// failure is not an error here — it is the `degraded` branch of the
/// document, same as the reference.
pub(crate) fn dump_summaries(facts: &OwnIr) -> Result<String, BridgeError> {
    let root = facts.to_value().map_err(|e| BridgeError(e.to_string()))?;
    let root = root.as_object().cloned().unwrap_or_default();
    // Python: `str(facts.get("module", "?"))` / `facts.get("functions", [])`
    // (a present non-list reads as empty).
    let module = root.get("module").map_or_else(|| "?".to_owned(), py_str);
    let raw_fns = as_list(root.get("functions"));

    let mut summaries: Vec<Value> = Vec::new();
    let mut unresolved: Vec<String> = Vec::new();
    let mut degraded = Value::Null;
    match mos::solve_with_log(build_skeletons(raw_fns)) {
        Ok((mos, log)) => {
            unresolved = log;
            // `sorted(summaries)` — the map key IS `MethodSummary.key` in the
            // reference, so sorting keys sorts the dump.
            let mut keys: Vec<&String> = mos.keys().collect();
            keys.sort();
            for key in keys {
                let Some(s) = mos.get(key) else {
                    continue; // unreachable: `keys` was collected from `mos`
                };
                let params: Vec<Value> = s
                    .params
                    .iter()
                    .map(|p| {
                        json!({
                            "index": p.index,
                            "name": p.name,
                            "disposable": p.disposable,
                            "transfer": p.transfer.as_str(),
                        })
                    })
                    .collect();
                // `escapes` is deliberately NOT serialized (INF-R2): no
                // producer sets the axis, so emitting it would freeze an
                // always-`false` lie into the parity artifact.
                summaries.push(json!({
                    "method": key,
                    "file": s.file,
                    "line": s.line,
                    "source": s.source,
                    "params": params,
                    "returns": {"owned": s.returns},
                }));
            }
        }
        Err(e) => {
            // Python: `except Exception as exc: f"{type(exc).__name__}: {exc}"`.
            // The only failure a facts document can reach is the duplicate-key
            // guard, a `ValueError` in the reference — mirror its type name.
            degraded = Value::String(format!("ValueError: {e}"));
        }
    }

    let doc = json!({
        "module": module,
        "ownir_version": OWNIR_VERSION,
        "summaries": summaries,
        "unresolved": unresolved,
        "degraded": degraded,
    });
    let mut out = String::new();
    emit(&doc, 0, &mut out);
    out.push('\n'); // the newline `print` appends
    Ok(out)
}

/// One string, escaped exactly as Python's `json.dumps` default
/// (`ensure_ascii=True`) escapes it: printable ASCII (0x20–0x7E) literal
/// except `"` and `\`, the five short escapes, `\uXXXX` (lowercase hex) for
/// everything else, surrogate PAIRS for code points above the BMP.
fn escape_py(s: &str, out: &mut String) {
    use std::fmt::Write as _;
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut units = [0_u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    // Writing into a String cannot fail; the lint-honest
                    // form still avoids unwrap.
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
        }
    }
    out.push('"');
}

/// `json.dumps(value, indent=2, sort_keys=True)`: 2-space indent, `": "` /
/// `","` separators, keys sorted at every level, empty containers inline.
fn emit(v: &Value, indent: usize, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        // The document carries only i64s (lines, the version); a non-integer
        // number cannot be constructed by `dump_summaries`.
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => escape_py(s, out),
        Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                pad(indent.saturating_add(2), out);
                emit(item, indent.saturating_add(2), out);
            }
            out.push('\n');
            pad(indent, out);
            out.push(']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                pad(indent.saturating_add(2), out);
                escape_py(key, out);
                out.push_str(": ");
                emit(
                    map.get(key.as_str()).unwrap_or(&Value::Null),
                    indent.saturating_add(2),
                    out,
                );
            }
            out.push('\n');
            pad(indent, out);
            out.push('}');
        }
    }
}

fn pad(n: usize, out: &mut String) {
    for _ in 0..n {
        out.push(' ');
    }
}
