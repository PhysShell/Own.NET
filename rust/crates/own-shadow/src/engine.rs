//! The **engine protocol** (P-022 step 7a, checkpoint 2): how this engine
//! reports its per-layer outputs in the artifact's one format.
//!
//! The reference's half is `ownlang/repro.py::project_layers`. This is the
//! port's half, and the two are deliberately *independent* readings of one
//! frozen format rather than one being a translation of the other.
//!
//! ## What a capture is, and is not
//!
//! It is this engine's answer for one input, per layer, in the shared
//! envelope. It is **not** a comparison: an artifact carrying two captures
//! still compares nothing, and this crate builds no verdict about either. That
//! comparison is #260's acceptance, blocked on #259.
//!
//! ## The projection, and why the format needs one
//!
//! All three of this engine's layers now emit the whole frozen surface. The
//! Layer 2 lowered document and the MOS summaries dump have been byte-exact
//! against the reference's own goldens since #259 cp2 and cp3; the verdict
//! layer was the one **partial** projection — `own_bridge::check_facts` sat at
//! the #259 checkpoint-4 surface and carried every `Finding` member except
//! `message`, `related` and `flow` — and #259 cp5.1/5.2 ported those, so it is
//! `full` too.
//!
//! The field stays, and stays load-bearing. A format without it would leave a
//! mid-migration port two bad options: emit a short document and let a later
//! comparison score the absent members as agreement, or refuse a layer it can
//! in fact mostly produce. `{"kind": "partial", "members": [...], "reason":
//! "..."}` is how a port says exactly what it produced — the cp4 discipline
//! generalized, *a replay declares what it compares, and the golden always
//! carries everything*. That no layer needs it today is a fact about this
//! engine's progress, not a reason to drop the field; the census fragment is
//! where that fact is counted.
//!
//! **This is not the verdict layer entering shadow mode.** The reducer still
//! REFUSES it and records the refusal in every reduction; that stays until
//! #260's acceptance, after row 4b. What changed is only this engine's honest
//! declaration of what it puts in the envelope.
//!
//! ## The typed door is upstream of every layer
//!
//! This engine reaches its layers through the typed [`own_ir::OwnIr`]
//! constructor. When that refuses a document (the #294 OD-1 shapes), no layer
//! runs — so **all three** layers report `refused` with the door's text, and
//! their projections stay `full`: a refusal is complete information about what
//! this engine did, not a partial answer. The alternative — one envelope-level
//! error — would break the format's rule that every engine reports exactly the
//! frozen layers, and would make a door refusal indistinguishable from a
//! missing implementation.

use own_ir::OwnIr;

use crate::artifact::{ENGINE_RUST, LAYER_ORDER, STATUS_PRODUCED, STATUS_REFUSED};
use crate::json::{parse, Json};

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

fn full_projection() -> Json {
    object(vec![("kind", Json::Str("full".to_owned()))])
}

/// The format's partial branch. No layer of THIS engine needs it today (the
/// verdict layer was the last one, and #259 cp5.1/5.2 completed it), and it is
/// kept because the field is the format's, not this engine's progress report:
/// the reference emits partials, and the next port to land mid-surface will.
/// Pinned by a unit test so an unused-but-contractual shape cannot rot.
#[cfg_attr(not(test), allow(dead_code))]
fn partial_projection(members: &[&str], reason: &str) -> Json {
    object(vec![
        ("kind", Json::Str("partial".to_owned())),
        (
            "members",
            Json::Array(members.iter().map(|m| Json::Str((*m).to_owned())).collect()),
        ),
        ("reason", Json::Str(reason.to_owned())),
    ])
}

fn produced(layer: &str, surface_version: Json, projection: Json, document: Json) -> Json {
    object(vec![
        ("layer", Json::Str(layer.to_owned())),
        ("surface_version", surface_version),
        ("projection", projection),
        ("status", Json::Str(STATUS_PRODUCED.to_owned())),
        ("document", document),
    ])
}

fn refused(layer: &str, surface_version: Json, projection: Json, error: &str) -> Json {
    object(vec![
        ("layer", Json::Str(layer.to_owned())),
        ("surface_version", surface_version),
        ("projection", projection),
        ("status", Json::Str(STATUS_REFUSED.to_owned())),
        ("error", Json::Str(error.to_owned())),
    ])
}

/// A layer whose own surface stamps a version; the version is read back out of
/// the produced document so the envelope cannot claim one the document does
/// not carry.
fn surface_version_of(document: &Json, key: &str) -> Json {
    document.get(key).cloned().unwrap_or(Json::Null)
}

/// This engine's capture of one facts document: the `engines[]` entry.
///
/// `facts_text` is the document's **source text**, not a re-serialization of a
/// parsed value: the typed `OwnIr` constructor is the port's real entry point
/// and must see what a producer actually wrote.
///
/// # Errors
/// A layer's own serialization failing is not modelled as a layer refusal —
/// that would report an internal defect as though the reference had been
/// disagreed with. It is an error out of the whole capture.
pub fn capture(facts_text: &str) -> Result<Json, String> {
    let layers = match serde_json::from_str::<OwnIr>(facts_text) {
        // The typed door is upstream of every layer: when it refuses, no layer
        // ran, so all three report the door's refusal.
        Err(door) => {
            let text = format!("typed door: {door}");
            LAYER_ORDER
                .iter()
                .map(|layer| refused(layer, Json::Null, full_projection(), &text))
                .collect()
        }
        Ok(facts) => vec![
            lowered_layer(&facts)?,
            summaries_layer(&facts)?,
            verdicts_layer(&facts),
        ],
    };
    Ok(object(vec![
        ("id", Json::Str(ENGINE_RUST.to_owned())),
        ("layers", Json::Array(layers)),
    ]))
}

fn lowered_layer(facts: &OwnIr) -> Result<Json, String> {
    match own_bridge::lower(facts) {
        Ok(document) => {
            let text = own_lowered::to_canonical_json(&own_lowered::Surface::Lowered(document))
                .map_err(|e| format!("lowered layer does not serialize: {e}"))?;
            let value =
                parse(&text).map_err(|e| format!("lowered layer does not re-parse: {e}"))?;
            let version = surface_version_of(&value, "lowered_version");
            Ok(produced("lowered", version, full_projection(), value))
        }
        // The reference lifts a `{"lowered_version": N, "error": ...}` surface
        // refusal into the envelope; this side reaches the same envelope from a
        // typed error, and carries the surface version the emitter stamps.
        Err(e) => Ok(refused(
            "lowered",
            Json::Int(i64::from(own_lowered::LOWERED_VERSION)),
            full_projection(),
            &e.to_string(),
        )),
    }
}

fn summaries_layer(facts: &OwnIr) -> Result<Json, String> {
    let text = own_bridge::dump_summaries(facts)
        .map_err(|e| format!("summaries layer does not serialize: {e}"))?;
    let value = parse(&text).map_err(|e| format!("summaries layer does not re-parse: {e}"))?;
    // The MOS dump has no surface version of its own (its document carries
    // `ownir_version`), and a failed solve is its `degraded` branch rather than
    // a refusal (INF-F6) — so this layer never reports `refused` today.
    Ok(produced("summaries", Json::Null, full_projection(), value))
}

/// Unlike the other two, this layer cannot fail as a whole: `check_facts`
/// either returns findings or a refusal, and both are envelopes. (`lowered`
/// and `summaries` can fail on *serialization*, which is an internal defect
/// rather than a disagreement with the reference, so only they return a
/// `Result`.)
/// One `[file, line, label]` evidence triple, the shape the Layer 3 surface
/// serializes (`ownlang/verdicts.py`).
fn steps(slice_: &[own_bridge::Step]) -> Json {
    Json::Array(
        slice_
            .iter()
            .map(|(file, line, label)| {
                Json::Array(vec![
                    Json::Str(file.clone()),
                    Json::Int(*line),
                    Json::Str(label.clone()),
                ])
            })
            .collect(),
    )
}

fn verdicts_layer(facts: &OwnIr) -> Json {
    // Every `Finding` member since #259 cp5.1/5.2 — no projection to declare.
    let projection = full_projection();
    let version = Json::Int(1);
    match own_bridge::check_facts(facts) {
        Ok(findings) => {
            let records = findings
                .iter()
                .map(|f| {
                    object(vec![
                        ("file", Json::Str(f.file.clone())),
                        ("line", Json::Int(f.line)),
                        ("code", Json::Str(f.code.clone())),
                        ("component", Json::Str(f.component.clone())),
                        ("event", Json::Str(f.event.clone())),
                        ("handler", Json::Str(f.handler.clone())),
                        ("message", Json::Str(f.message.clone())),
                        ("kind", Json::Str(f.kind.clone())),
                        ("advisory", Json::Bool(f.advisory)),
                        ("severity", opt_str(f.severity.as_deref())),
                        ("related", steps(&f.related)),
                        ("flow", steps(&f.flow)),
                        ("ignore_reason", opt_str(f.ignore_reason.as_deref())),
                        ("column", f.column.map_or(Json::Null, Json::Int)),
                    ])
                })
                .collect();
            let document = object(vec![
                ("verdicts_version", Json::Int(1)),
                ("findings", Json::Array(records)),
            ]);
            produced("verdicts", version, projection, document)
        }
        Err(e) => refused("verdicts", version, projection, &e.to_string()),
    }
}

fn opt_str(value: Option<&str>) -> Json {
    value.map_or(Json::Null, |s| Json::Str(s.to_owned()))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::{full_projection, partial_projection, Json};

    /// The two projection shapes the artifact format declares. `partial` has no
    /// caller in this engine any more — every layer emits its whole surface —
    /// so without this its shape would be unchecked the day someone needs it.
    #[test]
    fn the_two_projection_shapes_are_pinned() {
        assert_eq!(
            full_projection(),
            Json::Object(vec![("kind".to_owned(), Json::Str("full".to_owned()))])
        );
        assert_eq!(
            partial_projection(&["line", "code"], "why"),
            Json::Object(vec![
                ("kind".to_owned(), Json::Str("partial".to_owned())),
                (
                    "members".to_owned(),
                    Json::Array(vec![
                        Json::Str("line".to_owned()),
                        Json::Str("code".to_owned())
                    ])
                ),
                ("reason".to_owned(), Json::Str("why".to_owned())),
            ])
        );
    }
}
