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
//! ## The scope is every layer, and it IS the layer order
//!
//! [`REDUCTION_SCOPE`] is [`LAYER_ORDER`] — the same constant, not a second
//! list that happens to agree with it (owner decision D-4). It used to be
//! narrower, and the narrowing was right at the time: the verdict layer was
//! *refused* rather than skipped, because comparing final diagnostics is
//! #260's acceptance and infrastructure that would quietly do it on request
//! becomes an unearned shadow-mode claim the first time somebody widens a
//! constant. #259's final acceptance removed that reason and the owner took
//! the decision. `out_of_scope` stays in the output and is **empty**: the
//! member is the slot a future exclusion would occupy, and dropping it would
//! make "nothing is excluded" indistinguishable from "the field went away".
//!
//! ## Kind and acceptance are different questions
//!
//! Every observation carries both (owner decision D-5), and neither is
//! recoverable from the other:
//!
//! * the **kind** says what was seen — `left-only` / `right-only` / `changed` /
//!   `ordering-only` are the four content classes; `status` is a layer-level
//!   disagreement about whether the layer produced at all; `projection` means
//!   the engines declared different views of one surface; `missing-layer`
//!   means an engine did not report the layer.
//! * the **acceptance** says whether it is explained: `unexplained`, or
//!   `declared-boundary`.
//!
//! They used to be one field, with `unexplained` sitting in the kind
//! vocabulary beside `changed`. That made the two unable to disagree, which is
//! the wrong shape for an acceptance surface: it must be possible to observe a
//! `status` difference and *judge* it, and to observe a `changed` and have no
//! judgement available at all.
//!
//! ## What may be explained, and by whom
//!
//! Every **content** observation — on every layer, `summaries` and `verdicts`
//! included — is `unexplained`. The policy is not consulted for one, so a known
//! class attached to a `changed` cannot explain it even in principle.
//!
//! A `status` or `projection` observation is a `declared-boundary` only when
//! its structured class and its `(layer, kind)` match an exact entry of
//! [`BOUNDARY_POLICY`]. The class is declared by the **refusing engine**, in
//! its own capture, and this reducer only copies it: a comparison tool that
//! inferred a boundary from an error TEXT would read one engine's prose and
//! call the result a contract, and one carrying its own table of known cases
//! would be a second place the boundary is defined. `detail` never
//! participates — it is prose for a human.
//!
//! ## The verdict layer, and why it needs no special case
//!
//! The BR-V8 address `file:line:column:code` is a **pairing address**, not
//! object identity (owner decision D-7). Two findings that share it are the
//! same *place*, and every other member is compared as a value there — so a
//! difference is `changed` with a minimal path rather than a pair of one-sided
//! observations. The duplicate-address `~<n>` suffix is part of the address,
//! which is why permuting two findings that share one address reports
//! `changed` on both and never `ordering-only`.
//!
//! ## When both engines refused
//!
//! The reducer compares *that* they refused and never *how they phrased it*: a
//! refusal's text is each engine's own, and diffing the wordings would
//! manufacture a divergence out of a known difference in message vocabulary.

use crate::artifact::{LAYER_ORDER, STATUS_REFUSED};
use crate::json::Json;
use crate::trace::ORDER_SIGNIFICANT;

/// The reduction surface version. 2 widened the scope to every layer (owner
/// decision D-4) and made the ACCEPTANCE judgement a field of its own beside
/// the observation kind (D-5).
pub const REDUCTION_VERSION: i64 = 2;

/// The layers this reducer walks: **the layer order itself**.
///
/// Owner decision D-4, aliased rather than copied. The tree already held the
/// layer vocabulary three times — the order, the ordering semantics, and this
/// scope — and only the third could drift silently, because nothing compared
/// it to the first.
pub const REDUCTION_SCOPE: [&str; 3] = LAYER_ORDER;

pub const KIND_LEFT_ONLY: &str = "left-only";
pub const KIND_RIGHT_ONLY: &str = "right-only";
pub const KIND_CHANGED: &str = "changed";
pub const KIND_ORDERING_ONLY: &str = "ordering-only";
pub const KIND_STATUS: &str = "status";
pub const KIND_PROJECTION: &str = "projection";
/// Replaces the old `unexplained` KIND (owner decision D-5). An engine that did
/// not report a layer at all is a *shape*, and naming it after the judgement
/// meant the two could never disagree.
pub const KIND_MISSING_LAYER: &str = "missing-layer";

const KINDS: [&str; 7] = [
    KIND_LEFT_ONLY,
    KIND_RIGHT_ONLY,
    KIND_CHANGED,
    KIND_ORDERING_ONLY,
    KIND_STATUS,
    KIND_PROJECTION,
    KIND_MISSING_LAYER,
];

/// The ACCEPTANCE judgement (owner decision D-5), orthogonal to the kind.
pub const ACCEPTANCE_UNEXPLAINED: &str = "unexplained";
pub const ACCEPTANCE_DECLARED: &str = "declared-boundary";

const ACCEPTANCES: [&str; 2] = [ACCEPTANCE_UNEXPLAINED, ACCEPTANCE_DECLARED];

/// The one boundary class any engine declares today: the #294 OD-1 typed door.
pub const BOUNDARY_OD1: &str = "OD-1";

/// The FROZEN boundary policy (owner decision D-5): the exact
/// `(layer, kind, class)` triples an observation may be judged a declared
/// boundary on. A test asserts EXACT equality to these three.
///
/// Three entries for one door, and that is the point rather than repetition:
/// the typed `OwnIr` constructor sits upstream of every layer, so one refusal
/// produces three refused layer records, and a policy keyed by class alone
/// could not tell "the door refused this document" from "somebody attached a
/// known class to an unrelated layer".
///
/// `projection` has **no** entry, deliberately. A projection difference means
/// the two engines declared different views of one surface, so their values are
/// not comparable member-for-member; that is a reason to stop comparing, never
/// a reason to call the difference explained.
pub const BOUNDARY_POLICY: [(&str, &str, &str); 3] = [
    ("lowered", KIND_STATUS, BOUNDARY_OD1),
    ("summaries", KIND_STATUS, BOUNDARY_OD1),
    ("verdicts", KIND_STATUS, BOUNDARY_OD1),
];

/// The reduction outcomes.
///
/// `declared-boundary` is not a softer `diverged`: it says every observation
/// was matched by the frozen policy, a stronger statement about a surface with
/// known boundaries than "nothing was found".
pub const OUTCOME_IDENTICAL: &str = "identical";
pub const OUTCOME_DECLARED: &str = "declared-boundary";
pub const OUTCOME_DIVERGED: &str = "diverged";
pub const OUTCOME_SINGLE_ENGINE: &str = "single-engine";

/// The ACCEPTANCE judgement for one observation, and the boundary it keeps.
///
/// The rule, in the order it is written, because the order is the contract:
/// anything that is not a `status` or a `projection` is **unexplained** and
/// keeps no boundary — the policy is not consulted at all, which is stronger
/// than consulting it and refusing; then the `(layer, kind, class)` triple must
/// match the frozen policy exactly; and `detail` never participates.
///
/// No case-name matching and no error-text matching, anywhere.
#[must_use]
pub fn judge(layer: &str, kind: &str, boundary: Option<&Json>) -> (&'static str, Json) {
    if kind != KIND_STATUS && kind != KIND_PROJECTION {
        return (ACCEPTANCE_UNEXPLAINED, Json::Null);
    }
    let kept = match boundary {
        Some(b @ Json::Object(_)) => b.clone(),
        _ => Json::Null,
    };
    if let Some(class) = kept.get("class").and_then(Json::as_str) {
        if BOUNDARY_POLICY
            .iter()
            .any(|(l, k, c)| *l == layer && *k == kind && *c == class)
        {
            return (ACCEPTANCE_DECLARED, kept);
        }
    }
    (ACCEPTANCE_UNEXPLAINED, kept)
}

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

/// One observation, with its kind and its acceptance as separate fields.
fn observation(
    layer: &str,
    kind: &str,
    step: Option<&str>,
    path: Option<&str>,
    left: Json,
    right: Json,
    detail: &str,
) -> Json {
    observation_with_boundary(layer, kind, step, path, left, right, detail, None)
}

// Eight fields of ONE record, not eight decisions: the observation schema is
// what it is, and bundling half of them into a struct would put the schema in
// two places for the sake of an argument count.
#[allow(clippy::too_many_arguments)]
fn observation_with_boundary(
    layer: &str,
    kind: &str,
    step: Option<&str>,
    path: Option<&str>,
    left: Json,
    right: Json,
    detail: &str,
    boundary: Option<&Json>,
) -> Json {
    let (acceptance, kept) = judge(layer, kind, boundary);
    object(vec![
        ("layer", Json::Str(layer.to_owned())),
        ("kind", Json::Str(kind.to_owned())),
        ("acceptance", Json::Str(acceptance.to_owned())),
        ("boundary", kept),
        ("step", step.map_or(Json::Null, |s| Json::Str(s.to_owned()))),
        ("path", path.map_or(Json::Null, |p| Json::Str(p.to_owned()))),
        ("left", left),
        ("right", right),
        ("detail", Json::Str(detail.to_owned())),
    ])
}

/// The structured boundary class a REFUSING engine declared on its own layer
/// record, or `None`.
///
/// The refusing side declares it; this reducer only copies it.
fn boundary_of(layer: &Json) -> Option<&Json> {
    if layer.get("status").and_then(Json::as_str) != Some(STATUS_REFUSED) {
        return None;
    }
    match layer.get("boundary") {
        Some(b @ Json::Object(_)) => Some(b),
        _ => None,
    }
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
        // Exactly one side refused, so exactly one side can have declared a
        // class. Whichever it is, the class travels with the observation.
        let declared = boundary_of(left).or_else(|| boundary_of(right));
        return vec![observation_with_boundary(
            name,
            KIND_STATUS,
            None,
            None,
            left.get("status").cloned().unwrap_or(Json::Null),
            right.get("status").cloned().unwrap_or(Json::Null),
            "the two engines disagree about whether this layer produced at all; the refusing \
             engine declares its boundary class in its own capture and this reducer copies it, \
             judging the result against the frozen policy by (layer, kind, class) — never by \
             its text",
            declared,
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
    // Empty, and kept (owner decision D-4). Every layer is in scope; the member
    // is the slot a future exclusion would occupy, and dropping it would make
    // "nothing is excluded" indistinguishable from "the field went away".
    let out_of_scope = Json::Array(
        LAYER_ORDER
            .iter()
            .filter(|l| !REDUCTION_SCOPE.contains(*l))
            .map(|l| {
                object(vec![
                    ("layer", Json::Str((*l).to_owned())),
                    ("reason", Json::Str("not in scope".to_owned())),
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
            ("outcome", Json::Str(OUTCOME_SINGLE_ENGINE.to_owned())),
            (
                "detail",
                Json::Str(
                    "only one engine captured this input, so there is nothing to reduce".to_owned(),
                ),
            ),
            (
                "classification",
                object(vec![
                    ("by_kind", Json::Object(Vec::new())),
                    ("by_acceptance", Json::Object(Vec::new())),
                ]),
            ),
            ("first", Json::Null),
            ("observations", Json::Array(Vec::new())),
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
                KIND_MISSING_LAYER,
                None,
                None,
                Json::Bool(a.is_some()),
                Json::Bool(b.is_some()),
                "an engine did not report this layer at all",
            )),
        }
    }
    let tally = |field: &str, values: &[&str]| -> Json {
        Json::Object(
            values
                .iter()
                .map(|want| {
                    let n = observations
                        .iter()
                        .filter(|o| o.get(field).and_then(Json::as_str) == Some(*want))
                        .count();
                    (
                        (*want).to_owned(),
                        Json::Int(i64::try_from(n).unwrap_or(i64::MAX)),
                    )
                })
                .collect(),
        )
    };
    let classification = object(vec![
        ("by_kind", tally("kind", &KINDS)),
        ("by_acceptance", tally("acceptance", &ACCEPTANCES)),
    ]);
    let unexplained = observations
        .iter()
        .filter(|o| o.get("acceptance").and_then(Json::as_str) == Some(ACCEPTANCE_UNEXPLAINED))
        .count();
    let first = observations.first().cloned().unwrap_or(Json::Null);
    let outcome = if observations.is_empty() {
        OUTCOME_IDENTICAL
    } else if unexplained > 0 {
        OUTCOME_DIVERGED
    } else {
        OUTCOME_DECLARED
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
        // The whole walk, in step order, beside the headline. The verdict layer
        // entering scope is exactly when one document can differ at several
        // findings at once, and a reduction that showed one at a time would
        // make a reviewer re-run the reducer to see the second. `first` is
        // still what a first-divergence reduction is FOR; this is what a
        // divergence report needs.
        ("observations", Json::Array(observations)),
        ("out_of_scope", out_of_scope),
    ])
}
