//! **First-divergence reduction** (P-022 step 7a checkpoint 4, #260): walk two
//! engines' traces in pipeline order and name the *first* place they part
//! company — the layer, the step address, and the **minimal** difference inside
//! that step.
//!
//! The reference's half is `ownlang/repro.py::reduce_traces`; this is the
//! port's independent reading of the same rules, for the same reason the trace
//! is implemented twice: a comparison is the last thing you want to have only
//! one implementation of.
//!
//! ## The scope is a contract, and `verdicts` is refused rather than skipped
//!
//! [`REDUCTION_SCOPE`] is `lowered` and `summaries`. Comparing final
//! diagnostics is #260's **acceptance**, which is blocked by #259 (cp5 and 4b).
//! Infrastructure that would quietly do it on request is infrastructure that
//! becomes an unearned shadow-mode claim the first time somebody widens a
//! constant — so the verdict layer is *refused*, and the refusal is carried in
//! the output. "Not compared" must never be readable as "compared and agreed".
//!
//! ## What is and is not a content difference
//!
//! * `left-only` / `right-only` / `changed` / `ordering-only` are the four
//!   content classes.
//! * `status` is a layer-level disagreement about whether the layer produced at
//!   all. The reducer reports it; the artifacts are where each such case is
//!   recorded as a *declared* boundary, and judging that is not this tool's job.
//! * `projection` means the engines declared different projections of the
//!   surface, so their values are not comparable member-for-member. Comparing
//!   them anyway would score an unported member as a difference.
//! * When both engines **refused** a layer, the reducer compares *that* they
//!   refused and never *how they phrased it*: a refusal's text is each engine's
//!   own, and diffing the wordings would manufacture a divergence out of a
//!   known difference in message vocabulary.

use crate::artifact::{LAYER_ORDER, STATUS_REFUSED};
use crate::json::Json;
use crate::trace::ORDER_SIGNIFICANT;

pub const REDUCTION_VERSION: i64 = 1;

/// The layers this reducer walks, in pipeline order. Widening it is a contract
/// decision, not a parameter — see the module docs.
pub const REDUCTION_SCOPE: [&str; 2] = ["lowered", "summaries"];

pub const KIND_LEFT_ONLY: &str = "left-only";
pub const KIND_RIGHT_ONLY: &str = "right-only";
pub const KIND_CHANGED: &str = "changed";
pub const KIND_ORDERING_ONLY: &str = "ordering-only";
pub const KIND_STATUS: &str = "status";
pub const KIND_PROJECTION: &str = "projection";
pub const KIND_UNEXPLAINED: &str = "unexplained";

const KINDS: [&str; 7] = [
    KIND_LEFT_ONLY,
    KIND_RIGHT_ONLY,
    KIND_CHANGED,
    KIND_ORDERING_ONLY,
    KIND_STATUS,
    KIND_PROJECTION,
    KIND_UNEXPLAINED,
];

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

fn observation(
    layer: &str,
    kind: &str,
    step: Option<&str>,
    path: Option<&str>,
    left: Json,
    right: Json,
    detail: &str,
) -> Json {
    object(vec![
        ("layer", Json::Str(layer.to_owned())),
        ("kind", Json::Str(kind.to_owned())),
        ("step", step.map_or(Json::Null, |s| Json::Str(s.to_owned()))),
        ("path", path.map_or(Json::Null, |p| Json::Str(p.to_owned()))),
        ("left", left),
        ("right", right),
        ("detail", Json::Str(detail.to_owned())),
    ])
}

/// The smallest path at which two values differ, and the values there.
///
/// "Minimal" is the point: reporting a whole statement as "changed" makes the
/// reader diff it by hand, which is how a real difference gets waved through as
/// formatting.
fn minimal_difference(left: &Json, right: &Json, path: &str) -> (String, Json, Json) {
    match (left, right) {
        (Json::Object(a), Json::Object(b)) => {
            let mut keys: Vec<&String> = a.iter().map(|(k, _)| k).collect();
            for (k, _) in b {
                if !a.iter().any(|(ak, _)| ak == k) {
                    keys.push(k);
                }
            }
            for key in keys {
                let av = a.iter().find(|(k, _)| k == key).map(|(_, v)| v);
                let bv = b.iter().find(|(k, _)| k == key).map(|(_, v)| v);
                match (av, bv) {
                    (Some(x), Some(y)) if x == y => {}
                    (Some(x), Some(y)) => {
                        return minimal_difference(x, y, &format!("{path}.{key}"))
                    }
                    _ => {
                        return (
                            format!("{path}.{key}"),
                            av.cloned().unwrap_or(Json::Null),
                            bv.cloned().unwrap_or(Json::Null),
                        )
                    }
                }
            }
            let (ka, kb): (Vec<&String>, Vec<&String>) = (
                a.iter().map(|(k, _)| k).collect(),
                b.iter().map(|(k, _)| k).collect(),
            );
            if ka == kb {
                (path.to_owned(), left.clone(), right.clone())
            } else {
                // Every value matches and only the key ORDER differs: name
                // that, rather than dumping two identical-looking objects on
                // the reader.
                let names = |keys: Vec<&String>| {
                    Json::Array(keys.into_iter().map(|k| Json::Str(k.clone())).collect())
                };
                (format!("{path}[keys]"), names(ka), names(kb))
            }
        }
        (Json::Array(a), Json::Array(b)) => {
            for (i, (x, y)) in a.iter().zip(b.iter()).enumerate() {
                if x != y {
                    return minimal_difference(x, y, &format!("{path}[{i}]"));
                }
            }
            if a.len() == b.len() {
                (path.to_owned(), left.clone(), right.clone())
            } else {
                (
                    format!("{path}[len]"),
                    Json::Int(i64::try_from(a.len()).unwrap_or(i64::MAX)),
                    Json::Int(i64::try_from(b.len()).unwrap_or(i64::MAX)),
                )
            }
        }
        _ => (path.to_owned(), left.clone(), right.clone()),
    }
}

fn layer_of<'a>(trace: &'a Json, name: &str) -> Option<&'a Json> {
    trace
        .get("layers")?
        .as_array()?
        .iter()
        .find(|l| l.get("layer").and_then(Json::as_str) == Some(name))
}

fn steps(layer: &Json) -> &[Json] {
    layer.get("steps").and_then(Json::as_array).unwrap_or(&[])
}

fn step_id(step: &Json) -> &str {
    step.get("id").and_then(Json::as_str).unwrap_or("")
}

fn step_value(step: &Json) -> Json {
    step.get("value").cloned().unwrap_or(Json::Null)
}

// Six branches, each a distinct classification with its own reasoning; splitting
// them would scatter one decision procedure across six names.
#[allow(clippy::too_many_lines)]
fn reduce_layer(name: &str, left: &Json, right: &Json) -> Vec<Json> {
    let (ls, rs) = (
        left.get("status").and_then(Json::as_str),
        right.get("status").and_then(Json::as_str),
    );
    if ls != rs {
        return vec![observation(
            name,
            KIND_STATUS,
            None,
            None,
            left.get("status").cloned().unwrap_or(Json::Null),
            right.get("status").cloned().unwrap_or(Json::Null),
            "the two engines disagree about whether this layer produced at all; the artifacts \
             record every such case as a DECLARED boundary, and this reducer reports it rather \
             than judging it",
        )];
    }
    if ls == Some(STATUS_REFUSED) {
        return Vec::new();
    }
    if left.get("projection") != right.get("projection") {
        return vec![observation(
            name,
            KIND_PROJECTION,
            None,
            None,
            left.get("projection").cloned().unwrap_or(Json::Null),
            right.get("projection").cloned().unwrap_or(Json::Null),
            "the engines declare different projections of this surface, so their step values \
             are not comparable member-for-member; a value comparison here would score an \
             unported member as a difference",
        )];
    }

    let mut out = Vec::new();
    for step in steps(left) {
        let id = step_id(step);
        match steps(right).iter().find(|s| step_id(s) == id) {
            None => out.push(observation(
                name,
                KIND_LEFT_ONLY,
                Some(id),
                None,
                step_value(step),
                Json::Null,
                "addressed by the left engine only",
            )),
            Some(other) => {
                let (a, b) = (step_value(step), step_value(other));
                if a != b {
                    let (path, x, y) = minimal_difference(&a, &b, "");
                    out.push(observation(
                        name,
                        KIND_CHANGED,
                        Some(id),
                        Some(if path.is_empty() { "." } else { &path }),
                        x,
                        y,
                        "the same address carries different values",
                    ));
                }
            }
        }
    }
    for step in steps(right) {
        let id = step_id(step);
        if !steps(left).iter().any(|s| step_id(s) == id) {
            out.push(observation(
                name,
                KIND_RIGHT_ONLY,
                Some(id),
                None,
                Json::Null,
                step_value(step),
                "addressed by the right engine only",
            ));
        }
    }
    if !out.is_empty() {
        return out;
    }
    let order = |layer: &Json| -> Vec<Json> {
        steps(layer)
            .iter()
            .map(|s| Json::Str(step_id(s).to_owned()))
            .collect()
    };
    let (lo, ro) = (order(left), order(right));
    if lo != ro {
        let significant = left.get("order").and_then(Json::as_str) == Some(ORDER_SIGNIFICANT);
        out.push(observation(
            name,
            KIND_ORDERING_ONLY,
            None,
            None,
            Json::Array(lo),
            Json::Array(ro),
            if significant {
                "the same steps in a different sequence; this layer declares its order \
                 SIGNIFICANT, so the sequence is the difference"
            } else {
                "the same steps in a different sequence on a layer whose order is CANONICAL — \
                 one engine did not canonicalize"
            },
        ));
    }
    out
}

/// Walk two engines' traces and name the first divergence, with a
/// classification over the whole scope.
///
/// Silent by construction on identical data: `outcome` is `identical` and
/// `first` is `null`.
// One output document, assembled field by field; the length is the schema's,
// not a missing abstraction.
#[allow(clippy::too_many_lines)]
#[must_use]
pub fn reduce_traces(traces: &Json) -> Json {
    let entries = traces.get("traces").and_then(Json::as_array).unwrap_or(&[]);
    let scope = Json::Array(
        REDUCTION_SCOPE
            .iter()
            .map(|s| Json::Str((*s).to_owned()))
            .collect(),
    );
    let out_of_scope = Json::Array(
        LAYER_ORDER
            .iter()
            .filter(|l| !REDUCTION_SCOPE.contains(*l))
            .map(|l| {
                object(vec![
                    ("layer", Json::Str((*l).to_owned())),
                    (
                        "reason",
                        Json::Str(
                            "comparing final diagnostics is #260's ACCEPTANCE and is blocked by \
                             #259 (cp5 and 4b); this reducer refuses the layer rather than \
                             skipping it, so 'not compared' can never be read as 'compared and \
                             agreed'"
                                .to_owned(),
                        ),
                    ),
                ])
            })
            .collect(),
    );
    let engines = |list: &[Json]| -> Json {
        Json::Array(
            list.iter()
                .map(|t| t.get("engine").cloned().unwrap_or(Json::Null))
                .collect(),
        )
    };
    if entries.len() < 2 {
        return object(vec![
            ("reduction_version", Json::Int(REDUCTION_VERSION)),
            ("case", traces.get("case").cloned().unwrap_or(Json::Null)),
            ("engines", engines(entries)),
            ("scope", scope),
            ("outcome", Json::Str("single-engine".to_owned())),
            (
                "detail",
                Json::Str(
                    "only one engine captured this input, so there is nothing to reduce".to_owned(),
                ),
            ),
            ("classification", Json::Object(Vec::new())),
            ("first", Json::Null),
            ("out_of_scope", out_of_scope),
        ]);
    }
    let mut pair = entries.iter();
    let (Some(left), Some(right)) = (pair.next(), pair.next()) else {
        // Unreachable: the length was just checked. Written without indexing
        // because the workspace denies a panicking `[i]`, and a reducer is the
        // last place to introduce one.
        return Json::Null;
    };
    let mut observations: Vec<Json> = Vec::new();
    for name in LAYER_ORDER {
        if !REDUCTION_SCOPE.contains(&name) {
            continue;
        }
        match (layer_of(left, name), layer_of(right, name)) {
            (Some(a), Some(b)) => observations.extend(reduce_layer(name, a, b)),
            (a, b) => observations.push(observation(
                name,
                KIND_UNEXPLAINED,
                None,
                None,
                Json::Bool(a.is_some()),
                Json::Bool(b.is_some()),
                "an engine did not report this layer at all",
            )),
        }
    }
    let classification = Json::Object(
        KINDS
            .iter()
            .map(|kind| {
                let n = observations
                    .iter()
                    .filter(|o| o.get("kind").and_then(Json::as_str) == Some(*kind))
                    .count();
                (
                    (*kind).to_owned(),
                    Json::Int(i64::try_from(n).unwrap_or(i64::MAX)),
                )
            })
            .collect(),
    );
    let first = observations.first().cloned().unwrap_or(Json::Null);
    let outcome = if observations.is_empty() {
        "identical"
    } else {
        "diverged"
    };
    object(vec![
        ("reduction_version", Json::Int(REDUCTION_VERSION)),
        ("case", traces.get("case").cloned().unwrap_or(Json::Null)),
        (
            "engines",
            Json::Array(vec![
                left.get("engine").cloned().unwrap_or(Json::Null),
                right.get("engine").cloned().unwrap_or(Json::Null),
            ]),
        ),
        ("scope", scope),
        ("outcome", Json::Str(outcome.to_owned())),
        ("detail", Json::Null),
        ("classification", classification),
        ("first", first),
        ("out_of_scope", out_of_scope),
    ])
}
