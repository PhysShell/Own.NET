//! `own-guarded` — the P-037 B1 guarded **shadow** read (#304).
//!
//! It computes a guarded summary for every `(method, parameter)` coordinate of
//! an `OwnIR` document from A2's sidecar, the legacy `body` and the
//! `functions[]` records, and classifies it against the legacy MOS it is
//! handed. Contract: `docs/notes/p037-phase-b1-shadow.md`.
//!
//! * **Reuse, not re-implementation.** Every lattice operation, the election
//!   import, the edge read, the branch mask and the call-site application are
//!   `p037_kernel`'s. This crate defines none of them (B0 A6/A8, the reuse
//!   guard in `scripts/p037_proof_boundary.py`).
//! * **Fail closed.** An ambiguous join, a missing record or sidecar, an
//!   unresolved callee, a bound failure or an unsupported placement is
//!   `NO_GUARDED_EVIDENCE(reason)`, never a value (§0.9).
//! * **Static dispatch is a condition, not a fact.** Every report carries
//!   `static_dispatch_conditional: true` (A14); nothing here reads dispatch.
//! * **Shadow only.** No verdict, MOS or diagnostic reads this crate; its one
//!   consumer is the `own-shadow` oracle.

mod facts;
mod solve;

use std::collections::HashMap;

use own_ir::OwnIr;
use p037_kernel::{apply, Cells, Lattice, Lowered, Selection, Shape, Transfer};
use serde_json::{json, Value};

use solve::Solved;

pub use p037_kernel;

/// The report's schema identifier.
pub const SCHEMA: &str = "p037-guarded-shadow/1";

/// The summary-level class (N5, G-T2b only): `guarded` is the finalized
/// guarded collapse, `legacy` the legacy MOS value.
#[must_use]
pub fn classify_summary(guarded: Transfer, legacy: Transfer) -> &'static str {
    if guarded == legacy {
        "EQUAL"
    } else if guarded.leq(legacy) {
        "SUMMARY_REFINEMENT"
    } else if guarded == Transfer::Unknown && legacy == Transfer::May {
        "LEGACY_HONESTY"
    } else {
        "UNEXPLAINED"
    }
}

/// The application-level class (N5): `selected` is `apply` with the site's
/// selection, `collapsed` is `apply` unselected (the collapse lowered), and
/// `legacy` the legacy lowering of the same site.
#[must_use]
pub fn classify_application(
    selected: Lowered,
    collapsed: Lowered,
    legacy: Lowered,
) -> &'static str {
    if selected == legacy {
        "EQUAL"
    } else if selected != collapsed {
        "APPLICATION_REFINEMENT"
    } else {
        "UNEXPLAINED"
    }
}

/// A kernel value's lowercase name (`must`, `borrow`, ...).
fn name(x: impl std::fmt::Debug) -> String {
    format!("{x:?}").to_lowercase()
}

/// The members of JSON array `k` of `v` (none when absent).
fn list<'v>(v: &'v Value, k: &str) -> impl Iterator<Item = &'v Value> {
    v.get(k).and_then(Value::as_array).into_iter().flatten()
}

/// `own-bridge`'s MOS dump, as `(method key, params index) -> transfer`.
fn legacy_map(dump: &Value) -> HashMap<(String, usize), Transfer> {
    let mut m = HashMap::new();
    for s in list(dump, "summaries") {
        let Some(method) = s.get("method").and_then(Value::as_str) else {
            continue;
        };
        for p in list(s, "params") {
            let wire = p.get("transfer").and_then(Value::as_str);
            let t = Transfer::ALL
                .into_iter()
                .find(|t| Some(name(t).as_str()) == wire);
            let i = p
                .get("index")
                .and_then(Value::as_u64)
                .and_then(|i| usize::try_from(i).ok());
            if let (Some(t), Some(i)) = (t.filter(|t| *t != Transfer::Bot), i) {
                m.insert((method.to_owned(), i), t);
            }
        }
    }
    m
}

/// Everything one report reads.
struct Doc<'a> {
    fns: Vec<facts::Func<'a>>,
    ids: HashMap<(usize, usize), usize>,
    solved: Vec<Solved>,
    legacy: HashMap<(String, usize), Transfer>,
}

impl Doc<'_> {
    fn solved(&self, coord: (usize, usize)) -> Option<&Solved> {
        self.solved.get(*self.ids.get(&coord)?)
    }

    /// The legacy MOS value at the coordinate's identity (P-037-X Stage 2b R2: `name`, or
    /// the bridge's per-overload key `name(sig)`); no identity, no legacy value.
    fn legacy(&self, (fi, i): (usize, usize)) -> Option<Transfer> {
        let key = facts::identity(&self.fns, fi)?;
        self.legacy.get(&(key, i)).copied()
    }

    /// The summary row's class and its guarded columns.
    fn summary(&self, coord: (usize, usize)) -> (&'static str, Value) {
        let nge = |r: &str| ("NO_GUARDED_EVIDENCE", json!({ "reason": r }));
        let (shape, cells) = match self.solved(coord) {
            Some(Solved::Guarded { shape, cells }) => (*shape, *cells),
            Some(Solved::NoEvidence(r)) => return nge(r),
            None => return nge("malformed"),
        };
        let (fc, g) = (cells.fin(), cells.fin().collapse());
        let t = self.legacy(coord);
        let (class, reason) = t.map_or(("NO_GUARDED_EVIDENCE", Some("legacy_missing")), |t| {
            (classify_summary(g, t), None)
        });
        let cols = json!({
            "shape": name(shape), "cells": [name(fc.pos), name(fc.neg)], "guarded": name(g),
            "legacy": t.map(name), "reason": reason,
        });
        (class, cols)
    }

    /// The application columns of one handle slot of one call.
    fn application(&self, c: &facts::Call<'_>, slot: u64) -> Result<Value, String> {
        let callee = facts::callee_coord(&self.fns, c, slot)?;
        let (shape, cells) = match self.solved(callee) {
            Some(Solved::Guarded { shape, cells }) => (*shape, *cells),
            Some(Solved::NoEvidence(r)) => return Err(solve::via(r)),
            None => return Err("callee_no_coord".to_owned()),
        };
        let t = self.legacy(callee).ok_or("legacy_missing")?;
        let sel = match shape {
            Shape::Split(h) => match c.arg(u64::from(h)) {
                Some(facts::Arg::Bool(true) | facts::Arg::New) => Selection::Pos,
                Some(facts::Arg::Bool(false) | facts::Arg::Null) => Selection::Neg,
                _ => Selection::Unselected,
            },
            Shape::Uncond => Selection::Unselected,
        };
        let selected = apply(shape, cells, sel);
        let collapsed = apply(shape, cells, Selection::Unselected);
        let legacy = apply(Shape::Uncond, Cells::diag(t), Selection::Unselected);
        let class = classify_application(selected, collapsed, legacy);
        Ok(json!({
            "selection": format!("{sel:?}").to_lowercase(), "guarded": name(selected),
            "collapsed": name(collapsed), "legacy": name(legacy),
            "class": class,
        }))
    }
}

fn merge(mut row: Value, cols: Value) -> Value {
    if let (Some(r), Value::Object(c)) = (row.as_object_mut(), cols) {
        r.extend(c);
    }
    row
}

/// The guarded-vs-legacy shadow report for one facts document, given
/// `own-bridge`'s MOS dump of the same document.
#[must_use]
pub fn report(ir: &OwnIr, legacy_dump: &Value) -> Value {
    report_with_height(ir, legacy_dump, <Cells as Lattice>::HEIGHT)
}

/// [`report`] with the per-member pass allowance given explicitly: the A12
/// fault injection. Production uses `Cells::HEIGHT`.
#[must_use]
pub fn report_with_height(ir: &OwnIr, legacy_dump: &Value, height: usize) -> Value {
    let fns = facts::functions(ir);
    let (all, solved) = solve::solve(&fns, height);
    let ids = all.iter().enumerate().map(|(c, x)| (*x, c)).collect();
    let doc = Doc {
        fns,
        ids,
        solved,
        legacy: legacy_map(legacy_dump),
    };
    let mut summary = Vec::new();
    for &(fi, i) in &all {
        let Some(f) = doc.fns.get(fi) else { continue };
        let (class, cols) = doc.summary((fi, i));
        let row = json!({
            "method": f.name, "identity": facts::identity(&doc.fns, fi), "file": f.file,
            "index": i, "param": f.params.get(i),
            "ordinal": f.ordinals.as_ref().and_then(|o| o.get(i)), "class": class,
        });
        summary.push(merge(row, cols));
    }
    let mut application = Vec::new();
    for (fi, f) in doc.fns.iter().enumerate() {
        let Ok(sc) = &f.sidecar else { continue };
        for (c, &(slot, arg)) in sc
            .calls
            .iter()
            .flat_map(|c| c.args.iter().map(move |a| (c, a)))
        {
            let handle = match arg {
                facts::Arg::Var(name) => Ok((format!("var:{name}"), None)),
                facts::Arg::Param { .. } if f.ordinals.is_none() => {
                    Err("caller_ordinal_map".to_owned())
                }
                facts::Arg::Param { ordinal, .. } => {
                    match f.ordinals.iter().flatten().position(|&o| o == ordinal) {
                        Some(k) => Ok((format!("param:{k}"), Some(k))),
                        None => continue,
                    }
                }
                _ => continue,
            };
            let in_chain = matches!(&handle, Ok((_, Some(k))) if matches!(doc.solved((fi, *k)), Some(Solved::Guarded { .. })));
            let row = json!({
                "caller": f.name, "file": f.file, "site": {"line": c.site.0, "column": c.site.1},
                "statement_line": c.statement_line, "form": c.form, "callee": c.callee,
                "first_party": c.first_party, "slot": slot, "in_chain": in_chain,
                "handle": handle.as_ref().ok().map(|h| h.0.clone()),
            });
            let cols = handle.and_then(|_| doc.application(c, slot));
            let cols =
                cols.unwrap_or_else(|r| json!({"class": "NO_GUARDED_EVIDENCE", "reason": r}));
            application.push(merge(row, cols));
        }
    }
    json!({
        "schema": SCHEMA,
        "static_dispatch_conditional": true,
        "summary": summary,
        "application": application,
    })
}

// ---- P-037-X Stage 2 (research/p037-max-v1): the application seam ----------------------------
//
// The B1 shadow read above classifies guarded summaries against the legacy MOS and reaches no
// verdict. Stage 2 replays the FROZEN P-037 semantics on the Stage-1 canonical carrier and lets
// the bridge APPLY them at call sites, behind an explicit opt-in (the bridge's
// `OWEN_P037X_GUARDED` switch). Everything semantic is still the kernel's: election, cells,
// transforms, finalization and `apply`. This type only answers two questions the bridge asks:
// "what is this coordinate's finalized collapse?" (INF-A1 on the collapsed value, the
// SUMMARY_REFINEMENT / LEGACY_HONESTY classes) and "what does G-A1 select at this site?"
// (APPLICATION_REFINEMENT). A coordinate without guarded evidence answers `None`, and the bridge
// keeps its legacy value there: absence is never read as a value.

/// One solved coordinate, for the bridge.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Coordinate {
    /// The elected shape and the RAW least-fixpoint cells (finalize before reading).
    Guarded {
        /// The elected shape.
        shape: Shape,
        /// The raw lfp cells.
        cells: Cells,
    },
    /// `NO_GUARDED_EVIDENCE(reason)`.
    NoEvidence(String),
}

/// A sidecar call of one function, as the site-selection lookup needs it.
#[derive(Debug, Clone)]
struct Site {
    statement_line: i64,
    callee: Option<String>,
    args: Vec<(u64, SiteArg)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SiteArg {
    Bool(bool),
    Null,
    New,
    Other,
}

/// The guarded solution of one facts document.
#[derive(Debug, Clone)]
pub struct GuardedDoc {
    coords: HashMap<(String, usize), Coordinate>,
    sites: HashMap<String, Vec<Site>>,
}

impl GuardedDoc {
    /// Solve every `(functions[] key, params index)` coordinate of `ir` with the kernel, exactly
    /// as the shadow report does, and keep each function's sidecar calls for site selection.
    #[must_use]
    pub fn solve(ir: &OwnIr) -> Self {
        let fns = facts::functions(ir);
        let (all, solved) = solve::solve(&fns, <Cells as Lattice>::HEIGHT);
        let mut coords = HashMap::new();
        for (&(fi, i), s) in all.iter().zip(&solved) {
            // P-037-X Stage 2b R2: coordinates are keyed by the record's identity — its name,
            // or the bridge's per-overload key `name(sig)`; an overload without a `sig` has
            // no identity and no coordinate (the solver answers `overloaded` for it).
            let Some(key) = facts::identity(&fns, fi) else { continue };
            let coord = match s {
                Solved::Guarded { shape, cells } => Coordinate::Guarded {
                    shape: *shape,
                    cells: *cells,
                },
                Solved::NoEvidence(r) => Coordinate::NoEvidence(r.clone()),
            };
            coords.insert((key, i), coord);
        }
        let mut sites: HashMap<String, Vec<Site>> = HashMap::new();
        for f in &fns {
            let Ok(sc) = &f.sidecar else { continue };
            let list = sites.entry(f.name.to_owned()).or_default();
            for c in &sc.calls {
                list.push(Site {
                    statement_line: c.statement_line,
                    callee: c.callee.map(str::to_owned),
                    args: c
                        .args
                        .iter()
                        .map(|(o, a)| {
                            let a = match a {
                                facts::Arg::Bool(b) => SiteArg::Bool(*b),
                                facts::Arg::Null => SiteArg::Null,
                                facts::Arg::New => SiteArg::New,
                                _ => SiteArg::Other,
                            };
                            (*o, a)
                        })
                        .collect(),
                });
            }
        }
        Self { coords, sites }
    }

    /// The coordinate of `(identity, params index)`, if the document has one. The identity
    /// is the bridge's MOS key: the method name, or `name(sig)` for an overload.
    #[must_use]
    pub fn coordinate(&self, method: &str, index: usize) -> Option<&Coordinate> {
        self.coords.get(&(method.to_owned(), index))
    }

    /// The callee identity a call site names: `callee(sig)` when that overload key has a
    /// coordinate, else the bare name (a unique record), else nothing.
    #[must_use]
    pub fn callee_key(&self, callee: &str, sig: Option<&str>) -> Option<String> {
        if let Some(sig) = sig {
            let key = format!("{callee}({sig})");
            if self.coords.keys().any(|(k, _)| *k == key) {
                return Some(key);
            }
        }
        self.coords
            .keys()
            .any(|(k, _)| k == callee)
            .then(|| callee.to_owned())
    }

    /// The finalized collapse `C(fin(cells))` of a guarded coordinate: the value INF-A1 lowers
    /// where no site selects (G-A1's join branch). `None` without guarded evidence.
    #[must_use]
    pub fn collapsed(&self, method: &str, index: usize) -> Option<Transfer> {
        match self.coordinate(method, index)? {
            Coordinate::Guarded { cells, .. } => Some(cells.fin().collapse()),
            Coordinate::NoEvidence(_) => None,
        }
    }

    /// G-A1 at one call site: `caller` hands its argument at statement `line` to `callee`'s
    /// coordinate `index`. The site's sidecar call (unique by `statement_line` and callee; an
    /// ambiguous line selects nothing) supplies the argument at the callee's elected guard
    /// ordinal: `true`/object creation select the positive cell, `false`/`null` the negative,
    /// anything else applies the collapse. The kernel's `apply` finalizes first (K7).
    // `caller`/`callee` name the two ends of the G-A1 edge; the lint's suggested rename
    // would obscure exactly the distinction this method exists for.
    #[allow(clippy::similar_names)]
    #[must_use]
    pub fn apply_at(
        &self,
        caller: &str,
        line: i64,
        callee: &str,
        sig: Option<&str>,
        index: usize,
    ) -> Option<Lowered> {
        let key = self.callee_key(callee, sig)?;
        let Coordinate::Guarded { shape, cells } = self.coordinate(&key, index)? else {
            return None;
        };
        let sel = match shape {
            Shape::Uncond => Selection::Unselected,
            Shape::Split(h) => {
                let mut hits = self
                    .sites
                    .get(caller)
                    .into_iter()
                    .flatten()
                    .filter(|s| s.statement_line == line && s.callee.as_deref() == Some(callee));
                match (hits.next(), hits.next()) {
                    (Some(site), None) => match site
                        .args
                        .iter()
                        .find(|(o, _)| *o == u64::from(*h))
                        .map(|(_, a)| *a)
                    {
                        Some(SiteArg::Bool(true) | SiteArg::New) => Selection::Pos,
                        Some(SiteArg::Bool(false) | SiteArg::Null) => Selection::Neg,
                        _ => Selection::Unselected,
                    },
                    _ => Selection::Unselected,
                }
            }
        };
        Some(apply(*shape, *cells, sel))
    }
}
