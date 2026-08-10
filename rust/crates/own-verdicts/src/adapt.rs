//! The sidecar adapters: `OwnIr` → the fact-native analysis inputs.
//!
//! These start at [`own_ir::OwnIr`] and **never** at the lowered document.
//! Layer 2 carries `module`/`resources`/`externs`/`lifetimes`/`functions`/
//! `handles` and no DI or effect facts at all, so reconstructing them from
//! handles would be inventing a second source of truth that is convincing
//! right up until it disagrees with the reference.
//!
//! # Transport, not repair
//!
//! Every function here moves data and decides nothing. In particular it does
//! **no** dedup, no filtering, no re-keying and no last-wins: the resolution
//! rules live in `own_analysis` (`primary_from_site` takes the LAST site
//! matching an entry type and only then applies the `>= 1` anchor test), and an
//! adapter that helped would change a verdict the analysis is supposed to own.
//!
//! Order is data. `root_resolve_sites` and `scope_cache_sites` arrive as
//! sequences and leave as sequences, duplicates and all — reversing them,
//! deduplicating them or dropping entries whose line cannot serve as an anchor
//! each move the reported site, which the composition witnesses in
//! `tests/fixtures/ownir/verdicts.json` are built to catch.

use own_analysis::di::{Lifetime, Service, SiteTriple};
use own_analysis::effect::{Binding, Effect};
use own_ir::span::SourceLine;
use own_ir::OwnIr;

/// `str(x.get(key, default))` for a flattened key the typed model does not name.
///
/// A JSON string arrives as itself; anything else takes the default, matching
/// the reference's `str(...)` over a value its schema does not constrain.
fn text(extra: &serde_json::Map<String, serde_json::Value>, key: &str, default: &str) -> String {
    extra
        .get(key)
        .and_then(serde_json::Value::as_str)
        .unwrap_or(default)
        .to_owned()
}

/// `services[].disposable`, read the way the reference reads it.
///
/// There is deliberately **no typed `disposable` on [`own_ir::Service`]**, and
/// this is not an oversight to be fixed here: adding `Option<bool>` would make
/// `"disposable": "false"` pass the strict door — which has no rule for this
/// field, its job being finished before serde constructs anything — and then
/// fail in deserialization. That is a `VALIDATOR_HOLE`, which cp1 defines as a
/// bug in the validator rather than a rejected document. So the field arrives
/// through the flattened `extra` map and is read here.
///
/// The reference is `s.get("disposable") is True`: the JSON boolean `true` and
/// nothing else. Not truthiness, not a parsed string, not "they probably
/// meant". A string `"false"` is `false`, and so is `1`.
fn disposable(extra: &serde_json::Map<String, serde_json::Value>) -> bool {
    extra.get("disposable") == Some(&serde_json::Value::Bool(true))
}

/// `Option<i64>` → [`SourceLine`], absent reading as `0`.
///
/// Mirrors `_as_int`, which degrades rather than raising because `check_facts`
/// may be handed facts that never went through the strict door. `0` is a real
/// coordinate here, not a sentinel — what it MEANS is decided downstream by the
/// `>= 1` anchor test, which is not this layer's business.
const fn line_of(raw: Option<i64>) -> SourceLine {
    match raw {
        Some(v) => SourceLine(v),
        None => SourceLine(0),
    }
}

/// `services[].root_resolve_sites` / `scope_cache_sites` → `SiteTriple`s.
///
/// Lossless and order-preserving, one entry in, one entry out. Every entry is
/// carried, including duplicated types and lines that cannot serve as an
/// anchor, because both of those change the analysis's answer:
/// `primary_from_site` takes the last matching entry and *then* tests the line,
/// so a trailing non-anchor line falls back to the registration even when an
/// earlier usable site exists.
fn sites(raw: Option<&Vec<own_ir::Site>>) -> Vec<SiteTriple> {
    raw.map(|v| {
        v.iter()
            .map(|s| {
                (
                    s.type_name.clone().unwrap_or_default(),
                    s.file.clone().unwrap_or_else(|| "?".to_owned()),
                    line_of(s.line),
                )
            })
            .collect()
    })
    .unwrap_or_default()
}

/// `OwnIr.services` → the DI analysis input, in document order.
// `redundant_pub_crate`: the module is private, but a sibling module cannot
// see a private item, so `pub(crate)` is what makes this reachable from
// `facts.rs` and nothing wider. The lint reads the module's privacy and not
// the sibling's need.
#[allow(clippy::redundant_pub_crate)]
pub(crate) fn services(facts: &OwnIr) -> Vec<Service> {
    facts
        .services
        .iter()
        .flatten()
        .map(|s| Service {
            name: s.name.clone(),
            lifetime: Lifetime::parse(match s.lifetime {
                own_ir::Lifetime::Singleton => "singleton",
                own_ir::Lifetime::Scoped => "scoped",
                own_ir::Lifetime::Transient => "transient",
            }),
            deps: s.deps.clone().unwrap_or_default(),
            disposable: disposable(&s.extra),
            file: s.file.clone().unwrap_or_else(|| "?".to_owned()),
            line: line_of(s.line),
            weak_deps: s.weak_deps.clone().unwrap_or_default(),
            root_resolves: s.root_resolves.clone().unwrap_or_default(),
            root_resolve_sites: sites(s.root_resolve_sites.as_ref()),
            scope_cached: s.scope_cached.clone().unwrap_or_default(),
            scope_cache_sites: sites(s.scope_cache_sites.as_ref()),
        })
        .collect()
}

/// `OwnIr.effects` → the effect analysis input, in document order.
///
/// `component` and `file` are flattened keys, like `disposable`; `deps`,
/// `io` and `bindings` are typed. An absent `io` reads as `false` and an absent
/// `deps`/`bindings` as empty, exactly as the reference's `.get(k, default)`
/// does — the shape rejection the reference performs alongside those defaults
/// is serde's job here, and a document that fails it never reaches this
/// function.
// `redundant_pub_crate`: the module is private, but a sibling module cannot
// see a private item, so `pub(crate)` is what makes this reachable from
// `facts.rs` and nothing wider. The lint reads the module's privacy and not
// the sibling's need.
#[allow(clippy::redundant_pub_crate)]
pub(crate) fn effects(facts: &OwnIr) -> Vec<Effect> {
    facts
        .effects
        .iter()
        .flatten()
        .map(|e| Effect {
            component: text(&e.extra, "component", "?"),
            deps: e.deps.clone().unwrap_or_default(),
            io: e.io.unwrap_or(false),
            bindings: e
                .bindings
                .iter()
                .flatten()
                .map(|b| Binding {
                    name: b.name.clone().unwrap_or_else(|| "?".to_owned()),
                    init: b.init.clone().unwrap_or_else(|| "unknown".to_owned()),
                    refs: b.refs.clone().unwrap_or_default(),
                    line: line_of(b.line),
                })
                .collect(),
            file: text(&e.extra, "file", "?"),
            line: line_of(e.line),
        })
        .collect()
}
