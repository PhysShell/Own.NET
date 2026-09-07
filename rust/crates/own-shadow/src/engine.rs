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

use crate::artifact::{
    ENGINE_RUST, LAYER_ORDER, SARIF_CONFIGURATION, SARIF_SEVERITY, STATUS_PRODUCED, STATUS_REFUSED,
};
use crate::canonical::{canonical_hash, hash_bytes};
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

/// A refusal that DECLARES its boundary class (owner decision D-5).
///
/// Structured, not inferred: `class` is the token the frozen policy matches on
/// and `detail` is the prose beside it. The declaration belongs here — to the
/// engine that refused — because the alternative is a comparison tool reading
/// this engine's error text and calling the result a contract. `detail`
/// repeats the door's own words on purpose: `error` is this engine's free-form
/// wording and may be rephrased, while `detail` is the human half of a
/// structured record, and a reader of the reduction alone should not have to
/// go back to the capture to learn what was refused.
fn refused_at_boundary(
    layer: &str,
    surface_version: Json,
    projection: Json,
    error: &str,
    class: &str,
) -> Json {
    let Json::Object(mut fields) = refused(layer, surface_version, projection, error) else {
        return Json::Null;
    };
    fields.push((
        "boundary".to_owned(),
        object(vec![
            ("class", Json::Str(class.to_owned())),
            ("detail", Json::Str(error.to_owned())),
        ]),
    ));
    Json::Object(fields)
}

/// A layer whose own surface stamps a version; the version is read back out of
/// the produced document so the envelope cannot claim one the document does
/// not carry.
fn surface_version_of(document: &Json, key: &str) -> Json {
    document.get(key).cloned().unwrap_or(Json::Null)
}

/// This engine's capture of one **byte sequence**: the `engines[]` entry.
///
/// `raw` is the document's byte-exact source, not a re-serialization of a
/// parsed value and not a `&str`: the typed `OwnIr` constructor is the port's
/// real entry point and must see what a producer actually wrote, and owner
/// decision B-2 makes that a *byte-level* requirement rather than a textual
/// one. The identity is taken on the first line — before `serde_json` looks at
/// a single byte — so `consumed` names what this engine actually read and
/// cannot name anything else. There is no code path here that derives a
/// `consumed` from an artifact's `input.raw`, which is exactly what promoting
/// a version-2 entry would have needed (B-3).
///
/// `from_slice`, never `read_to_string` then `from_str`: a decode on the way in
/// is a place a difference gets normalized away before anyone can see it, and
/// the whole point of v3 is that nothing on this path may do that.
///
/// # Errors
/// A layer's own serialization failing is not modelled as a layer refusal —
/// that would report an internal defect as though the reference had been
/// disagreed with. It is an error out of the whole capture.
pub fn capture(raw: &[u8]) -> Result<Json, String> {
    capture_detailed(raw).map(|c| c.engine)
}

/// One engine capture, plus the derived documents behind its `derived` block.
///
/// The artifact carries identities, never documents (owner decision D-6), so
/// [`capture`] returns only the entry. A **compare driver** needs the documents
/// too — it retains them on mismatch — and asking for them by re-invoking this
/// engine would be a second execution of the thing whose single execution is
/// the point. So they come back beside the entry and the caller decides what to
/// keep.
#[derive(Debug, Clone)]
pub struct Capture {
    /// The `engines[]` entry, exactly as it appears in an artifact.
    pub engine: Json,
    /// The rendered SARIF this engine's `derived.sarif.canonical` names, or
    /// `None` when the verdict layer was refused.
    pub sarif: Option<Json>,
}

/// See [`capture`]; this is the same work, with the derived documents kept.
///
/// # Errors
/// As [`capture`].
pub fn capture_detailed(raw: &[u8]) -> Result<Capture, String> {
    let consumed = hash_bytes(raw).to_json();
    let layers = match serde_json::from_slice::<OwnIr>(raw) {
        // The typed door is upstream of every layer: when it refuses, no layer
        // ran, so all three report the door's refusal.
        Err(door) => {
            let text = format!("typed door: {door}");
            // #294 OD-1, declared structurally rather than left to be inferred
            // from the text. One refusal, three refused layer records — which
            // is why the frozen policy carries one entry per layer rather than
            // one per class.
            LAYER_ORDER
                .iter()
                .map(|layer| {
                    refused_at_boundary(
                        layer,
                        Json::Null,
                        full_projection(),
                        &text,
                        crate::reduce::BOUNDARY_OD1,
                    )
                })
                .collect()
        }
        Ok(facts) => vec![
            lowered_layer(&facts)?,
            summaries_layer(&facts)?,
            verdicts_layer(&facts)?,
        ],
    };
    let derived = derived_block(
        layers
            .iter()
            .find(|l| l.get("layer").and_then(Json::as_str) == Some("verdicts")),
    );
    let sarif = layers
        .iter()
        .find(|l| l.get("layer").and_then(Json::as_str) == Some("verdicts"))
        .and_then(sarif_of);
    let layers: Vec<Json> = layers.into_iter().map(strip_sarif).collect();
    Ok(Capture {
        engine: object(vec![
            ("id", Json::Str(ENGINE_RUST.to_owned())),
            ("consumed", consumed),
            ("layers", Json::Array(layers)),
            // Beside `layers`, never inside them: a derived surface is not a
            // layer (owner decision D-6). Nothing in LAYER_ORDER, the trace or
            // the reduction knows it exists.
            ("derived", derived),
        ]),
        sarif,
    })
}

/// This engine's `derived` block: the IDENTITY of each surface derived from
/// its own layers, never the surface itself (owner decision D-6).
///
/// Only the digest and the length are carried, for the same reason the artifact
/// carries an input digest rather than a second copy of the input. The
/// documents are retained by the compare driver, on mismatch only.
///
/// The closed-domain check on the rendered log happens in [`verdicts_layer`],
/// where the findings are: `Json` enforces the domain at parse, so a float or
/// a non-finite in the SARIF surfaces there as an error out of the whole
/// capture — because a surface the two engines cannot name identically is not
/// a surface either of them may claim to have compared. By the time a document
/// reaches here it is already in the domain, so this cannot fail.
fn derived_block(verdicts: Option<&Json>) -> Json {
    let document = verdicts.and_then(sarif_of);
    let (status, canonical) = document
        .as_ref()
        .map_or((STATUS_REFUSED, Json::Null), |value| {
            (STATUS_PRODUCED, canonical_hash(value).to_json())
        });
    object(vec![(
        "sarif",
        object(vec![
            ("configuration", Json::Str(SARIF_CONFIGURATION.to_owned())),
            ("status", Json::Str(status.to_owned())),
            // The SAME canonical form the artifact already uses to name an
            // input. A second serialization rule for a second surface is a
            // second thing to keep two engines agreeing about.
            ("canonical", canonical),
        ]),
    )])
}

/// The canonical SARIF this engine renders from its OWN verdict layer, or
/// `None` when that layer was refused.
///
/// The rendered log is carried on the layer record (`sarif`, a private member
/// this module puts there and strips before the envelope is built), because it
/// is produced from the very `Vec<Finding>` the verdict layer document was
/// built from — one `check_facts` run, two projections of it. That is what
/// makes a *renderer-only divergence* an unambiguous finding: when the two
/// engines' verdict layers are equal in the artifact and their SARIF is not,
/// the renderer is the only thing left.
///
/// The rendering itself, and the domain check on it, happen in
/// [`verdicts_layer`] where the findings are; this only reads the slot back.
fn sarif_of(layer: &Json) -> Option<Json> {
    match layer.get(SARIF_SLOT) {
        None | Some(Json::Null) => None,
        Some(value) => Some(value.clone()),
    }
}

/// The private slot a verdict layer carries its rendered SARIF in, between
/// `verdicts_layer` and `derived_block`. Stripped before the layer reaches the
/// envelope — the artifact's layer records are the frozen envelope and nothing
/// else — so it never appears in a committed artifact.
const SARIF_SLOT: &str = "$sarif";

fn strip_sarif(layer: Json) -> Json {
    let Json::Object(fields) = layer else {
        return layer;
    };
    Json::Object(
        fields
            .into_iter()
            .filter(|(k, _)| k != SARIF_SLOT)
            .collect(),
    )
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

fn verdicts_layer(facts: &OwnIr) -> Result<Json, String> {
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
            // The derived SARIF, rendered from the SAME `Vec<Finding>` this
            // layer document was built from: one `check_facts` run, two
            // projections of it (owner decision D-6). It rides on a private
            // slot to `derived_block` and is stripped before the envelope — a
            // layer record is the frozen envelope and nothing else.
            let log = own_bridge::build_sarif(&findings, SARIF_SEVERITY);
            let text = serde_json::to_string(&log)
                .map_err(|e| format!("the derived SARIF does not serialize: {e}"))?;
            let value = parse(&text).map_err(|e| {
                format!(
                    "the derived SARIF is outside the closed canonical value domain, so the two \
                     engines cannot name it identically: {e}"
                )
            })?;
            let Json::Object(mut fields) = produced("verdicts", version, projection, document)
            else {
                return Err("a produced layer is not an object".to_owned());
            };
            fields.push((SARIF_SLOT.to_owned(), value));
            Ok(Json::Object(fields))
        }
        Err(e) => Ok(refused("verdicts", version, projection, &e.to_string())),
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
