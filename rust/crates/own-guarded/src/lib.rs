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

    /// The legacy MOS value; an overloaded name has no per-coordinate key here.
    fn legacy(&self, (fi, i): (usize, usize)) -> Option<Transfer> {
        let f = self.fns.get(fi)?;
        let unique = self.fns.iter().filter(|g| g.name == f.name).count() == 1;
        self.legacy
            .get(&(f.name.to_owned(), i))
            .copied()
            .filter(|_| unique)
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
            "method": f.name, "file": f.file, "index": i, "param": f.params.get(i),
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
