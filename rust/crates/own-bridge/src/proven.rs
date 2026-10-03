//! `OwnIR` v2's `proven_call` (H1, docs/notes/h1-proven-call.md) — the port of
//! `ownlang/ownir.py::_admit_proven_calls`.
//!
//! A `proven_call` is a call inside an exclusive region that the frontend
//! could not lower (it touches no entity and no token) and did not refuse,
//! because a summary might prove it harmless. MUST-UNDERSTAND: every one in the
//! document is admitted or refused here, before anything is lowered — not where
//! `lower_flow` happens to meet it — and a refusal is the whole document's. The
//! proof belongs to the shared heap-effect summary layer
//! (`heap_effects::Proof`) over the document's `heap_effects` section; the
//! frontend contributes facts only.
//!
//! Every message is the reference's, byte for byte, in the reference's order.

// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules (same stance as `mos.rs`).
#![allow(clippy::redundant_pub_crate)]

use crate::heap_effects;
use crate::lower::{as_line, as_list, py_str};
use crate::BridgeError;
use serde_json::{Map, Value};

/// The reference's recursion bound for the walk (`_proven_calls`).
const MAX_DEPTH: usize = 256;

/// The compound keys a flow node nests bodies under, in the reference's order.
const COMPOUND_KEYS: [&str; 3] = ["then", "else", "body"];

struct Site<'v> {
    node: &'v Map<String, Value>,
    file: String,
    in_region: bool,
}

/// `_proven_calls`: every `proven_call` under `nodes`, in document order, with
/// whether it sits inside a `borrow_mut` body.
fn collect<'v>(
    nodes: Option<&'v Value>,
    file: &str,
    in_region: bool,
    out: &mut Vec<Site<'v>>,
    depth: usize,
) {
    let Some(Value::Array(items)) = nodes else {
        return;
    };
    if depth > MAX_DEPTH {
        return;
    }
    for item in items {
        let Some(n) = item.as_object() else { continue };
        let op = n.get("op").and_then(Value::as_str);
        if op == Some("proven_call") {
            out.push(Site {
                node: n,
                file: file.to_owned(),
                in_region,
            });
        }
        let inner = in_region || op == Some("borrow_mut");
        for key in COMPOUND_KEYS {
            collect(n.get(key), file, inner, out, depth.saturating_add(1));
        }
    }
}

fn non_empty_str<'v>(n: &'v Map<String, Value>, key: &str) -> Option<&'v str> {
    n.get(key).and_then(Value::as_str).filter(|s| !s.is_empty())
}

/// `_admit_proven_calls`.
pub(crate) fn admit(root: &Map<String, Value>) -> Result<(), BridgeError> {
    let mut sites = Vec::new();
    if let Some(Value::Array(_)) = root.get("functions") {
        for fn_v in as_list(root.get("functions")) {
            let Some(f) = fn_v.as_object() else { continue };
            let file = f.get("file").map_or_else(|| "?".to_owned(), py_str);
            collect(f.get("body"), &file, false, &mut sites, 0);
        }
    }
    let Some(first) = sites.first() else {
        return Ok(());
    };
    for s in &sites {
        let line = as_line(s.node.get("line"));
        if non_empty_str(s.node, "site").is_none() || non_empty_str(s.node, "callee").is_none() {
            return Err(BridgeError(format!(
                "OwnIR flow op 'proven_call' needs a non-empty string 'site' and a \
                 non-empty string 'callee' ({}:{line})",
                s.file
            )));
        }
        if !s.in_region {
            return Err(BridgeError(format!(
                "OwnIR 'proven_call' outside a borrow_mut region ({}:{line}) — \
                 refused: the op admits a call only inside an exclusive region",
                s.file
            )));
        }
    }
    let section = match root.get("heap_effects") {
        None | Some(Value::Null) => {
            return Err(BridgeError(format!(
                "OwnIR 'proven_call' ({}:{}) needs the 'heap_effects' section — \
                 refused: a call with no effect evidence is not harmless",
                first.file,
                as_line(first.node.get("line"))
            )))
        }
        Some(v) => v,
    };
    let proof = heap_effects::prove(section)
        .map_err(|e| BridgeError(format!("OwnIR 'heap_effects' section is malformed — {e}")))?;
    for s in &sites {
        let line = as_line(s.node.get("line"));
        let site = non_empty_str(s.node, "site").unwrap_or_default();
        let callee = non_empty_str(s.node, "callee").unwrap_or_default();
        if !proof.has(site) {
            return Err(BridgeError(format!(
                "OwnIR 'proven_call' site '{site}' has no record in 'heap_effects' \
                 ({}:{line}) — refused: no evidence is not harmless",
                s.file
            )));
        }
        if let Some(reason) = proof.site_verdict(site, callee) {
            return Err(BridgeError(format!(
                "OwnIR 'proven_call' to '{callee}' is not proven harmless: {reason} \
                 ({}:{line}) — refused: an exclusive region admits only calls the \
                 effect summaries prove harmless",
                s.file
            )));
        }
    }
    Ok(())
}
