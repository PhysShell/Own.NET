//! The **`AnalysisTrace`** (P-022 step 7a checkpoint 3, #269): the
//! normalization that turns a *pair* of captures into something a comparison
//! can walk.
//!
//! The schema is frozen in `ownlang/repro.py`'s docstring; this is the port's
//! independent reading of it. Two things stand between an artifact and a
//! comparison, and the trace removes exactly one of them and **declares** the
//! other:
//!
//! * **Internal identifiers are normalized away.** The Layer 2 handles
//!   (`sub_0`, `cap_1`, `parg_0`, `loc_3`) are minted from global counters in
//!   document order (BR-L2) — positions wearing the costume of names. Each is
//!   rebuilt from the record's own identity (`component | file | line | event
//!   | handler`), and every occurrence anywhere in the document is rewritten.
//!   The mint *kind* is not discarded: it moves onto the handle record as
//!   `mint`, so a routing difference stays a comparable **value** on one step
//!   instead of splitting into a pair of "only in one engine" addresses.
//! * **Order is declared, never normalized away.** `order` is `significant`
//!   for `lowered` (BR-D4/BR-L5) and `verdicts` (BR-V8 leaves ties in
//!   construction order), `canonical` for `summaries` (INF-R1). Sorting a
//!   significant layer to make a comparison pass would delete the defect the
//!   layer exists to expose.
//!
//! This crate still **compares nothing**. The trace is the shape a comparison
//! would need; producing it is not performing one.

use crate::artifact::{LAYER_ORDER, STATUS_REFUSED};
use crate::json::Json;

/// The trace surface version, keyed to the reference's `TRACE_VERSION`.
pub const TRACE_VERSION: i64 = 1;

pub const ORDER_SIGNIFICANT: &str = "significant";
pub const ORDER_CANONICAL: &str = "canonical";

/// Per-layer ordering semantics, frozen. A comparison reads this to CLASSIFY
/// an ordering difference; it never licenses sorting a layer.
#[must_use]
pub fn order_semantics(layer: &str) -> &'static str {
    match layer {
        "summaries" => ORDER_CANONICAL,
        _ => ORDER_SIGNIFICANT,
    }
}

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

/// `Some(prefix)` when the string is a minted handle (`prefix_<digits>`).
fn minted_prefix(value: &str) -> Option<&str> {
    let (prefix, digits) = value.split_once('_')?;
    if !matches!(prefix, "sub" | "cap" | "parg" | "loc") {
        return None;
    }
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(prefix)
}

fn text(value: Option<&Json>) -> String {
    match value {
        Some(Json::Str(s)) => s.clone(),
        Some(Json::Int(i)) => i.to_string(),
        Some(Json::Bool(b)) => b.to_string(),
        Some(Json::Null) | None => String::new(),
        Some(other) => other.to_canonical(),
    }
}

/// A handle's identity, from the record the bridge attached to it — never from
/// the counter. An absent field renders empty, so "no handler" and "the empty
/// handler" stay one address: they are the same fact.
fn identity(record: &Json) -> String {
    ["component", "file", "line", "event", "handler"]
        .iter()
        .map(|k| text(record.get(k)))
        .collect::<Vec<_>>()
        .join("|")
}

/// `minted name -> stable id`. A bijection by construction: a repeated
/// identity takes a `~<n>` suffix in encounter order, the one place position
/// leaks back into an address.
fn stable_handle_ids(handles: &[Json]) -> Vec<(String, String)> {
    let mut seen: Vec<(String, usize)> = Vec::new();
    let mut out = Vec::new();
    for record in handles {
        let Some(minted) = record.get("handle").and_then(Json::as_str) else {
            continue;
        };
        let id = identity(record);
        let n = if let Some(slot) = seen.iter_mut().find(|(k, _)| *k == id) {
            slot.1 = slot.1.saturating_add(1);
            slot.1.saturating_sub(1)
        } else {
            seen.push((id.clone(), 1));
            0
        };
        let stable = if n == 0 { id } else { format!("{id}~{n}") };
        out.push((minted.to_owned(), stable));
    }
    out
}

fn rewrite(value: &Json, rename: &[(String, String)]) -> Json {
    match value {
        Json::Str(s) => rename
            .iter()
            .find(|(from, _)| from == s)
            .map_or_else(|| value.clone(), |(_, to)| Json::Str(to.clone())),
        Json::Array(items) => Json::Array(items.iter().map(|v| rewrite(v, rename)).collect()),
        Json::Object(entries) => Json::Object(
            entries
                .iter()
                .map(|(k, v)| (k.clone(), rewrite(v, rename)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn minted_leftovers(value: &Json, out: &mut Vec<String>) {
    match value {
        Json::Str(s) => {
            if minted_prefix(s).is_some() {
                out.push(s.clone());
            }
        }
        Json::Array(items) => {
            for item in items {
                minted_leftovers(item, out);
            }
        }
        Json::Object(entries) => {
            for (_, v) in entries {
                minted_leftovers(v, out);
            }
        }
        _ => {}
    }
}

/// A Layer 2 document with every minted handle replaced by its stable id, and
/// the mint kind preserved as each handle record's `mint`.
///
/// # Errors
/// When a counter-shaped name survives the rewrite: the rename claims to be
/// total, and a claim nothing can falsify is not a contract.
fn normalize_handles(document: &Json) -> Result<Json, String> {
    let Some(handles) = document.get("handles").and_then(Json::as_array) else {
        return Ok(document.clone());
    };
    let rename = stable_handle_ids(handles);
    let rewritten = rewrite(document, &rename);
    // Stamp `mint` onto each handle record, positionally against the original
    // list (the rewrite preserves order and arity).
    let stamped = match (&rewritten, handles) {
        (Json::Object(entries), originals) => Json::Object(
            entries
                .iter()
                .map(|(k, v)| {
                    if k != "handles" {
                        return (k.clone(), v.clone());
                    }
                    let records = v.as_array().unwrap_or(&[]);
                    let stamped: Vec<Json> = records
                        .iter()
                        .zip(originals.iter())
                        .map(|(record, original)| {
                            let mint = original
                                .get("handle")
                                .and_then(Json::as_str)
                                .and_then(minted_prefix)
                                .map_or_else(|| text(original.get("handle")), str::to_owned);
                            let Json::Object(fields) = record else {
                                return record.clone();
                            };
                            let mut fields = fields.clone();
                            fields.push(("mint".to_owned(), Json::Str(mint)));
                            Json::Object(fields)
                        })
                        .collect();
                    (k.clone(), Json::Array(stamped))
                })
                .collect(),
        ),
        _ => rewritten,
    };
    let mut leftovers = Vec::new();
    minted_leftovers(&stamped, &mut leftovers);
    if leftovers.is_empty() {
        Ok(stamped)
    } else {
        leftovers.sort_unstable();
        leftovers.dedup();
        leftovers.truncate(5);
        Err(format!(
            "stable-ID normalization is not total: {leftovers:?} survived the rewrite — a \
             handle is referenced somewhere the rename did not reach, and a comparison would \
             report it as a difference between engines rather than as a counter"
        ))
    }
}

/// Joins a prefix and an address into a seen-key. `U+0001` cannot appear in a
/// Layer 2 name, a file path or a code, so `a[b]` and `a` + `[b]` cannot
/// collide into one counter.
const SEEN_KEY_SEP: char = '\u{1}';

/// Address a list of `(address, value)` pairs under one prefix, disambiguating
/// repeats with `~<n>` in encounter order.
struct Addresser {
    seen: Vec<(String, usize)>,
    steps: Vec<Json>,
}

impl Addresser {
    const fn new() -> Self {
        Self {
            seen: Vec::new(),
            steps: Vec::new(),
        }
    }

    fn plain(&mut self, id: &str, value: Json) {
        self.steps.push(object(vec![
            ("id", Json::Str(id.to_owned())),
            ("value", value),
        ]));
    }

    /// Returns the disambiguated address, so a caller can reuse it as a prefix
    /// (a function's body hangs off its own, already-disambiguated, address).
    ///
    /// The `~<n>` suffix goes **inside the bracket** — `functions[Take~1]`,
    /// never `functions[Take]~1` — uniformly for every addressed list: it
    /// disambiguates *which of the repeated items*, which is a property of the
    /// item rather than of the path, and that is what lets a nested prefix
    /// compose. The rule is spelled out because the two implementations of this
    /// schema first read it two different ways, and the disagreement surfaced
    /// as a trace-golden mismatch rather than as prose.
    fn addressed(&mut self, prefix: &str, address: &str, value: Json) -> String {
        // The seen-key joins prefix and address on a separator no address can
        // contain, so `a[b]` and `a` + `[b]` cannot collide.
        let key = format!("{prefix}{SEEN_KEY_SEP}{address}");
        let n = if let Some(slot) = self.seen.iter_mut().find(|(k, _)| *k == key) {
            slot.1 = slot.1.saturating_add(1);
            slot.1.saturating_sub(1)
        } else {
            self.seen.push((key, 1));
            0
        };
        let inner = if n == 0 {
            address.to_owned()
        } else {
            format!("{address}~{n}")
        };
        let id = format!("{prefix}[{inner}]");
        self.plain(&id, value);
        id
    }
}

fn lowered_steps(document: &Json) -> Result<Vec<Json>, String> {
    let doc = normalize_handles(document)?;
    let mut a = Addresser::new();
    a.plain(
        "lowered_version",
        doc.get("lowered_version").cloned().unwrap_or(Json::Null),
    );
    a.plain("module", doc.get("module").cloned().unwrap_or(Json::Null));
    for key in ["resources", "externs", "lifetimes"] {
        for entry in doc.get(key).and_then(Json::as_array).unwrap_or(&[]) {
            a.addressed(key, &text(entry.get("name")), entry.clone());
        }
    }
    // One disambiguator across ALL functions, and the body prefix inherits it:
    // a repeated C# name puts two functions under one address, and a
    // per-function counter would reset and collide.
    for function in doc.get("functions").and_then(Json::as_array).unwrap_or(&[]) {
        let head = match function {
            Json::Object(fields) => Json::Object(
                fields
                    .iter()
                    .filter(|(k, _)| k != "body")
                    .cloned()
                    .collect(),
            ),
            other => other.clone(),
        };
        let address = a.addressed("functions", &text(function.get("name")), head);
        let body_prefix = format!("{address}.body");
        for (i, stmt) in function
            .get("body")
            .and_then(Json::as_array)
            .unwrap_or(&[])
            .iter()
            .enumerate()
        {
            a.addressed(&body_prefix, &i.to_string(), stmt.clone());
        }
    }
    for record in doc.get("handles").and_then(Json::as_array).unwrap_or(&[]) {
        a.addressed("handles", &text(record.get("handle")), record.clone());
    }
    Ok(a.steps)
}

fn summaries_steps(document: &Json) -> Vec<Json> {
    let mut a = Addresser::new();
    for key in ["module", "ownir_version", "degraded"] {
        a.plain(key, document.get(key).cloned().unwrap_or(Json::Null));
    }
    for entry in document
        .get("summaries")
        .and_then(Json::as_array)
        .unwrap_or(&[])
    {
        a.addressed("summaries", &text(entry.get("method")), entry.clone());
    }
    for entry in document
        .get("unresolved")
        .and_then(Json::as_array)
        .unwrap_or(&[])
    {
        a.addressed("unresolved", &text(Some(entry)), entry.clone());
    }
    a.steps
}

fn verdicts_steps(document: &Json) -> Vec<Json> {
    let mut a = Addresser::new();
    a.plain(
        "verdicts_version",
        document
            .get("verdicts_version")
            .cloned()
            .unwrap_or(Json::Null),
    );
    for finding in document
        .get("findings")
        .and_then(Json::as_array)
        .unwrap_or(&[])
    {
        let anchor = format!(
            "{}:{}:{}:{}",
            text(finding.get("file")),
            text(finding.get("line")),
            anchor_column(finding),
            text(finding.get("code")),
        );
        a.addressed("findings", &anchor, finding.clone());
    }
    a.steps
}

/// `column` renders as the reference's `None`, not as an empty string: the
/// address has to read the same on both sides, and absence is data here.
fn anchor_column(finding: &Json) -> String {
    match finding.get("column") {
        Some(Json::Int(i)) => i.to_string(),
        _ => "None".to_owned(),
    }
}

/// One capture layer as a trace layer.
///
/// # Errors
/// A layer this projection has not been taught to address, or a lowered
/// document whose handle rename is not total.
fn trace_layer(layer: &Json) -> Result<Json, String> {
    let name = text(layer.get("layer"));
    let status = text(layer.get("status"));
    let mut fields = vec![
        ("layer", Json::Str(name.clone())),
        ("status", Json::Str(status.clone())),
        (
            "projection",
            layer.get("projection").cloned().unwrap_or(Json::Null),
        ),
        ("order", Json::Str(order_semantics(&name).to_owned())),
    ];
    if status == STATUS_REFUSED {
        // No steps: there is nothing to address, and an empty step list that
        // compared equal to another engine's would score a refusal as
        // agreement.
        fields.push(("error", layer.get("error").cloned().unwrap_or(Json::Null)));
        fields.push(("steps", Json::Array(Vec::new())));
        return Ok(object(fields));
    }
    let document = layer.get("document").cloned().unwrap_or(Json::Null);
    let steps = match name.as_str() {
        "lowered" => lowered_steps(&document)?,
        "summaries" => summaries_steps(&document),
        "verdicts" => verdicts_steps(&document),
        other => {
            return Err(format!(
                "no trace projection for layer {other:?} — a layer added to {LAYER_ORDER:?} \
                 must be taught how to address its steps, or a comparison would silently \
                 skip it"
            ))
        }
    };
    fields.push(("steps", Json::Array(steps)));
    Ok(object(fields))
}

/// Project one engine's capture, out of a reproduction artifact, into the
/// comparable trace.
///
/// # Errors
/// The artifact carries no capture for that engine, or a layer cannot be
/// addressed.
pub fn project_trace(artifact: &Json, engine_id: &str) -> Result<Json, String> {
    let engines = artifact
        .get("engines")
        .and_then(Json::as_array)
        .unwrap_or(&[]);
    let engine = engines
        .iter()
        .find(|e| e.get("id").and_then(Json::as_str) == Some(engine_id))
        .ok_or_else(|| {
            let present: Vec<&str> = engines
                .iter()
                .filter_map(|e| e.get("id").and_then(Json::as_str))
                .collect();
            format!(
                "the artifact carries no capture for engine {engine_id:?} (present: {present:?})"
            )
        })?;
    let layers = engine
        .get("layers")
        .and_then(Json::as_array)
        .unwrap_or(&[])
        .iter()
        .map(trace_layer)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(object(vec![
        ("trace_version", Json::Int(TRACE_VERSION)),
        ("engine", Json::Str(engine_id.to_owned())),
        (
            "input",
            artifact
                .get("input")
                .and_then(|i| i.get("canonical"))
                .cloned()
                .unwrap_or(Json::Null),
        ),
        ("layers", Json::Array(layers)),
    ]))
}

/// Every engine's capture in one artifact, projected into traces, in the
/// artifact's engine order.
///
/// Projecting an engine's capture is not authoring it: the trace is a pure
/// normalization of a capture somebody else produced, and **both** sides
/// project **both** engines so the normalization itself is cross-checked. If
/// the two implementations of it ever disagree, that is a finding about the
/// projection, not about either engine.
///
/// # Errors
/// Propagated from [`project_trace`].
pub fn project_traces(artifact: &Json, case: &str) -> Result<Json, String> {
    let ids: Vec<String> = artifact
        .get("engines")
        .and_then(Json::as_array)
        .unwrap_or(&[])
        .iter()
        .filter_map(|e| e.get("id").and_then(Json::as_str))
        .map(str::to_owned)
        .collect();
    let traces = ids
        .iter()
        .map(|id| project_trace(artifact, id))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(object(vec![
        ("trace_version", Json::Int(TRACE_VERSION)),
        ("case", Json::Str(case.to_owned())),
        ("traces", Json::Array(traces)),
    ]))
}

#[cfg(test)]
// A test module asserts; `expect`/`expect_err` ARE the assertion here, and the
// workspace denies them for production code, not for the place a panic is the
// reporting mechanism (same stance as every integration test in this crate).
#[allow(clippy::expect_used)]
mod tests {
    use super::{normalize_handles, Json};

    /// The totality assertion guards a state the corpus cannot reach: every
    /// statement references a handle the `handles[]` array lists, because the
    /// bridge mints both. So the rule is driven synthetically HERE, at the only
    /// level that can reach it — the same resting place #259 cp4 chose for
    /// BR-V1's ERROR-only rule, and for the same reason: leaving a normative
    /// rule permanently unprovable is worse than proving it off the production
    /// path and saying so.
    #[test]
    fn a_handle_reference_the_rename_cannot_reach_is_refused() {
        // `loc_1` is referenced by a statement but absent from `handles[]`, so
        // the rewrite has no entry for it and a counter survives.
        let document = Json::Object(vec![
            (
                "functions".to_owned(),
                Json::Array(vec![Json::Object(vec![(
                    "body".to_owned(),
                    Json::Array(vec![Json::Object(vec![(
                        "handle".to_owned(),
                        Json::Str("loc_1".to_owned()),
                    )])]),
                )])]),
            ),
            (
                "handles".to_owned(),
                Json::Array(vec![Json::Object(vec![
                    ("handle".to_owned(), Json::Str("loc_0".to_owned())),
                    ("component".to_owned(), Json::Str("M".to_owned())),
                ])]),
            ),
        ]);
        let err = normalize_handles(&document)
            .expect_err("a surviving counter must be refused, not carried into a comparison");
        assert!(
            err.contains("not total") && err.contains("loc_1"),
            "refused, but not for the declared reason: {err}"
        );
    }

    /// …and the same document with the reference listed normalizes cleanly, so
    /// the control above is testing the leak and not merely the shape.
    #[test]
    fn a_fully_listed_document_normalizes() {
        let document = Json::Object(vec![
            (
                "functions".to_owned(),
                Json::Array(vec![Json::Object(vec![(
                    "body".to_owned(),
                    Json::Array(vec![Json::Object(vec![(
                        "handle".to_owned(),
                        Json::Str("loc_0".to_owned()),
                    )])]),
                )])]),
            ),
            (
                "handles".to_owned(),
                Json::Array(vec![Json::Object(vec![
                    ("handle".to_owned(), Json::Str("loc_0".to_owned())),
                    ("component".to_owned(), Json::Str("M".to_owned())),
                ])]),
            ),
        ]);
        let out = normalize_handles(&document).expect("normalizes");
        assert_eq!(
            out.get("handles")
                .and_then(Json::as_array)
                .and_then(<[Json]>::first)
                .and_then(|h| h.get("mint"))
                .and_then(Json::as_str),
            Some("loc"),
            "the mint kind must survive as a comparable value"
        );
    }
}
