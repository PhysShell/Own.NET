//! `check_facts` — the composition itself.
//!
//! ```text
//!                    ┌─→ project → Module → check_module ──→ core
//! OwnIr → lower ─────┤
//!   ├──────────────────→ services → DI analysis ───────────→ di
//!   └──────────────────→ effects  → effect analysis ───────→ effects
//! ```
//!
//! The two sidecar arrows start at `OwnIr`, never at the lowered document.
//!
//! # The `core` channel is NOT here, and that is a measured blocker
//!
//! It was implemented, replayed, and taken back out. The frozen `core` channel
//! is `(line, code)` — and that LINE is not the diagnostic's. The reference
//! anchors a flow-local finding at `_as_int(sub.get("line", 0))`: the HANDLE's
//! C# line from the handle map, not `d.line` (only `OWN025`, the pooled-view
//! case, uses the diagnostic's own line, and for a written reason).
//!
//! Reaching that handle needs `Diagnostic.subject` (`name#line`), and
//! `own-analysis` never stamps one: its declared parity contract at #214 was
//! `(line, code)`, so no consumer needed it until now. `ownlang/lifetimes.py`
//! and `ownlang/analysis.py` both set it.
//!
//! So the core channel needs two things this checkpoint does not own —
//! `subject` parity and the handle -> C# location mapping — and the crate docs
//! assign both to cp5 by name. Measured against the 51 frozen cases with core
//! wired from `check_module` directly: 40 agree, 11 do not, and every one of
//! the 11 differs in the LINE, never in the ordering:
//!
//! ```text
//! contract_inference   got 26,32     want 24,31
//! flow_column_anchors  got 21,21,31,48,48,48   want 30,40,40,44,12,21
//! flow_finally_switch  got 21        want 20
//! flow_leak_two_exits  got 106,106   want 105
//! flow_nested_throw    got 202,218   want 201,217
//! flow_pool_partial    got 11,21,31  want 10,20,30
//! flow_while           got 22        want 20    (OWN003)
//! handoff_contract     got 19,26     want 18,24
//! local_disposable     got 18        want 12
//! pool                 got 16        want 9
//! unitofwork_flow      got 48        want 26
//! ```
//!
//! The 40 agree only because their handle line happens to equal their
//! diagnostic line. Shipping that would be a checkpoint passing on a
//! coincidence, which is the exact failure the composition witnesses exist to
//! stop.
//!
//! # Why the sidecars still lower and project
//!
//! `check_module` reports `(code, line)`; the frozen `core` channel is
//! `(line, code)` — but its ORDER is the reference's final sort over every
//! finding, keyed `(file, line, column, code)`. One fixture
//! (`flow_column_anchors`) spans two C# files, so its core rows come back
//! grouped by file rather than by line, and reproducing that needs a file per
//! diagnostic.
//!
//! That file is read from the Layer 2 handle map: `own-cfg` stamps each
//! diagnostic with a `subject` of the form `name#line`, whose `name` half is
//! the synthetic handle, and `HandleEntry.file` is the C# file it came from.
//! This is the sort key and nothing else — no message, no severity mapping, no
//! subject/resource-kind parity, no Evidence. Those are cp5, and none of them
//! is constructed here.
//!
//! # Deliberately NOT implemented, because nothing observes it
//!
//! The reference dedups before sorting, keyed on twelve fields including
//! `message`, `component` and `ignore_reason`. Measured over all 51 frozen
//! cases: **no two findings share even `(file, line, column, code)`**, so the
//! dedup never fires and a port that omits it agrees everywhere. It is omitted,
//! and recorded here rather than left for someone to discover as a silence —
//! the same mistake the `effects` channel taught. It belongs to cp5, where the
//! message half of its key becomes real.
//!
//! `column` is likewise absent from the sort key: Layer 2's handle allowlist
//! does not carry it (it is verdict-presentation metadata, excluded on
//! purpose), and re-deriving it would mean re-deriving the bridge's handle
//! minting — a second source of truth. Measured: re-sorting every frozen case
//! without `column` reproduces the frozen surface exactly, because two rows
//! that tie on `(file, line, code)` are indistinguishable once projected to it.
//!
//! Both are holes in the same sense the `effects` channel was one. They are
//! written down, not warned about.

use own_analysis::{di_verdicts, effect_verdicts};
use own_ir::span::SourceLine;
use own_ir::OwnIr;

use crate::adapt::{effects as adapt_effects, services as adapt_services};
use crate::{project, VerdictError};

/// The verdict channels this crate can prove today, at the granularity the
/// frozen oracle compares.
///
/// cp4 gates on THREE — `core`, `di`, `effects`. `core` is absent until the
/// routing-identity prerequisite lands (see above); the field is missing rather
/// than empty so nothing can read a green replay as covering it.
///
/// Separate lists rather than one envelope: `core` is `(line, code)` and the
/// fact-driven channels are `(path, line, code)`, and unifying them is exactly
/// cp5's mapping work — started early and proven late is how a checkpoint
/// widens by accident. `protocols` and `advisories` are frozen OBSERVATIONS in
/// the oracle and deliberately have no field here, so a green replay of this
/// type cannot be read as evidence about them.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct VerdictChannels {
    /// DI lifetime verdicts, fact-driven and multi-file by nature.
    pub di: Vec<(String, SourceLine, String)>,
    /// Reactive-effect verdicts, same reason.
    pub effects: Vec<(String, SourceLine, String)>,
}

/// Compose one `OwnIR` document into the fact-driven gating channels.
///
/// # Errors
/// [`VerdictError`] when the bridge rejects the document (vocabulary skew),
/// when the projection cannot represent it. A document that analyses
/// cleanly returns empty channels, never an error.
pub fn check_facts(facts: &OwnIr) -> Result<VerdictChannels, VerdictError> {
    // The bridge and the projection still run: a document the composition
    // cannot lower or project is a rejection, not an empty verdict, and the
    // sidecars must not answer for a document the core path would refuse.
    let doc = own_bridge::lower(facts)?;
    project(&doc)?;

    // Sorting each channel separately is equivalent to the reference's single
    // global sort followed by the oracle's split: the split is order-preserving,
    // so a row's position within its channel depends only on the other rows of
    // that channel.
    let mut di = di_verdicts(&adapt_services(facts));
    di.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then_with(|| a.1.cmp(&b.1))
            .then_with(|| a.2.cmp(b.2))
    });
    let mut effects = effect_verdicts(&adapt_effects(facts));
    effects.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then_with(|| a.1.cmp(&b.1))
            .then_with(|| a.2.cmp(b.2))
    });

    Ok(VerdictChannels {
        di: di
            .into_iter()
            .map(|(f, l, c)| (f, l, c.to_owned()))
            .collect(),
        effects: effects
            .into_iter()
            .map(|(f, l, c)| (f, l, c.to_owned()))
            .collect(),
    })
}
