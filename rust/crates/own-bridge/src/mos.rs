//! Method Ownership Summaries — the `ownlang/ownership.py` solver, ported in
//! the shape `ownir.py::_build_skeletons` actually produces (P-005 D5.0).
//!
//! The solver resolves each method's per-parameter ownership transfer by a
//! least fixpoint over the call graph's SCC condensation, and each method's
//! owned-return kind by a memoized, cycle-safe chase along forward edges.
//!
//! Deliberately NOT carried from the reference: the `adopt`/`return` path
//! kinds and the `aliasOf`/`aliased` return kinds (reserved in Python — the
//! production skeleton builder never emits them; they would contribute
//! `Transfer::Must` / terminal strings exactly like Python's), the `escapes`
//! axis (no producer sets it), and the unresolved-edge log (`solve_with_log`)
//! — none of them can influence a lowered document today. The summary also
//! drops the dump-only fields (`name`, `file`, `line`, `source`): the merged
//! name/location tie-breaks in `_merge_skeletons` affect only the detached
//! summaries artifact, never the lowering.

// Solver internals index maps by invariant-backed keys (every key read was
// inserted by the same pass); expect()/indexing over those invariants is the
// faithful shape of the reference and never input-reachable. `solve` mirrors
// the Python function boundaries rather than splitting for a line count.
// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules; pub(crate) is the honest
// visibility here.
#![allow(
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::too_many_lines,
    clippy::redundant_pub_crate
)]

use std::collections::{BTreeMap, BTreeSet, HashMap};

/// Did ownership of a disposable parameter leave the caller?
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Transfer {
    /// Borrowed; the caller keeps ownership.
    No,
    /// Transferred on every normal-return path.
    Must,
    /// Transferred on some paths but not all.
    May,
    /// Insufficient evidence (extern callee).
    Unknown,
}

/// Combine two paths' transfer verdicts: `unknown` is absorbing; any other
/// disagreement is `may` (path-dependent, and we know it).
pub(crate) const fn join(a: Transfer, b: Transfer) -> Transfer {
    match (a, b) {
        (Transfer::No, Transfer::No) => Transfer::No,
        (Transfer::Must, Transfer::Must) => Transfer::Must,
        (Transfer::Unknown, _) | (_, Transfer::Unknown) => Transfer::Unknown,
        _ => Transfer::May,
    }
}

/// One thing a method body does with a parameter on one normal-return path.
/// The production builder emits exactly these three kinds.
#[derive(Debug, Clone)]
pub(crate) enum PathAction {
    /// Releases it — ownership left the caller on this path (`must`).
    Dispose,
    /// Only reads/uses it — kept (`no`).
    Borrow,
    /// Hands it to `callee` at parameter position `arg` — resolved against
    /// that callee's summary by the fixpoint.
    Forward { callee: String, arg: i64 },
}

/// What a method returns, in the kinds the production builder emits
/// (`aliasOf`/`aliased` are reserved in Python and never produced).
#[derive(Debug, Clone)]
pub(crate) enum ReturnSkeleton {
    /// No owned return (void / no claim).
    None,
    /// A newly-owned disposable the caller must release.
    Fresh,
    /// Returns the result of `callee` — chased through that summary.
    Forward { callee: String },
    /// The conservative overload-merge result — fails closed.
    Unknown,
}

#[derive(Debug, Clone)]
pub(crate) struct ParamSkeleton {
    /// The logical parameter index calls resolve by (never tuple offset).
    pub index: i64,
    /// Empty = nothing happens to it -> kept (`no`).
    pub paths: Vec<PathAction>,
}

#[derive(Debug, Clone)]
pub(crate) struct MethodSkeleton {
    /// The call-graph identity: `{Type}.{Method}` or `{Type}.{Method}(sig)`.
    pub key: String,
    pub params: Vec<ParamSkeleton>,
    pub ret: ReturnSkeleton,
}

#[derive(Debug, Clone)]
pub(crate) struct ParamSummary {
    pub index: i64,
    pub transfer: Transfer,
}

#[derive(Debug, Clone)]
pub(crate) struct MethodSummary {
    pub params: Vec<ParamSummary>,
    /// `"fresh" | "none" | "unknown"` — the terminal forms the production
    /// skeletons can reach. Only `== "fresh"` is read by the lowering.
    pub returns: String,
}

/// The lowering consumes summaries through this map (`mos` in Python).
pub(crate) type Mos = HashMap<String, MethodSummary>;

/// Dependency edges `M -> callees whose summaries M's summary reads`.
fn call_graph(sk: &BTreeMap<String, MethodSkeleton>) -> BTreeMap<String, BTreeSet<String>> {
    let mut adj: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for (k, skel) in sk {
        let deps = adj.entry(k.clone()).or_default();
        for p in &skel.params {
            for a in &p.paths {
                if let PathAction::Forward { callee, .. } = a {
                    if sk.contains_key(callee) {
                        deps.insert(callee.clone());
                    }
                }
            }
        }
        if let ReturnSkeleton::Forward { callee } = &skel.ret {
            if sk.contains_key(callee) {
                deps.insert(callee.clone());
            }
        }
    }
    adj
}

/// Tarjan's SCCs, iterative, emitted bottom-up (every component precedes its
/// callers). Adjacency is ordered, so the walk is deterministic; the fixpoint
/// result is order-independent regardless (a least fixpoint on a lattice).
fn sccs(adj: &BTreeMap<String, BTreeSet<String>>) -> Vec<Vec<String>> {
    let mut index: HashMap<&str, usize> = HashMap::new();
    let mut low: HashMap<&str, usize> = HashMap::new();
    let mut on_stack: BTreeSet<&str> = BTreeSet::new();
    let mut stack: Vec<&str> = Vec::new();
    let mut out: Vec<Vec<String>> = Vec::new();
    let mut counter = 0_usize;
    for root in adj.keys() {
        let root = root.as_str();
        if index.contains_key(root) {
            continue;
        }
        index.insert(root, counter);
        low.insert(root, counter);
        counter = counter.wrapping_add(1);
        stack.push(root);
        on_stack.insert(root);
        let mut work: Vec<(&str, Vec<&str>)> =
            vec![(root, adj[root].iter().map(String::as_str).rev().collect())];
        while let Some((node, pending)) = work.last_mut() {
            let node = *node;
            let mut descended = false;
            while let Some(w) = pending.pop() {
                if !index.contains_key(w) {
                    index.insert(w, counter);
                    low.insert(w, counter);
                    counter = counter.wrapping_add(1);
                    stack.push(w);
                    on_stack.insert(w);
                    work.push((w, adj[w].iter().map(String::as_str).rev().collect()));
                    descended = true;
                    break;
                }
                if on_stack.contains(w) {
                    let lw = index[w];
                    let ln = low.get_mut(node).expect("visited node has a low-link");
                    *ln = (*ln).min(lw);
                }
            }
            if descended {
                continue;
            }
            if low[node] == index[node] {
                let mut comp: Vec<String> = Vec::new();
                loop {
                    let x = stack.pop().expect("component member on the stack");
                    on_stack.remove(x);
                    comp.push(x.to_owned());
                    if x == node {
                        break;
                    }
                }
                out.push(comp);
            }
            work.pop();
            if let Some((parent, _)) = work.last() {
                let parent = *parent;
                let child_low = low[node];
                let lp = low.get_mut(parent).expect("parent has a low-link");
                *lp = (*lp).min(child_low);
            }
        }
    }
    out
}

type ParamKey = (String, i64);

/// Resolve every method's MOS. A duplicate skeleton key is an error the
/// caller degrades on (Python: `ValueError` → the bridge drops to an empty
/// MOS rather than corrupting the call graph).
pub(crate) fn solve(skeletons: Vec<MethodSkeleton>) -> Result<Mos, String> {
    let mut sk: BTreeMap<String, MethodSkeleton> = BTreeMap::new();
    for s in skeletons {
        if sk.contains_key(&s.key) {
            return Err(format!("duplicate MethodSkeleton key: {}", s.key));
        }
        sk.insert(s.key.clone(), s);
    }

    let mut param_val: HashMap<ParamKey, Transfer> = HashMap::new();

    // --- param transfers: bottom-up, per-SCC least fixpoint on the lattice --
    let adj = call_graph(&sk);
    for comp in sccs(&adj) {
        let mut members: Vec<ParamKey> = Vec::new();
        for k in &comp {
            for p in &sk[k].params {
                members.push((k.clone(), p.index));
            }
        }
        if members.is_empty() {
            continue;
        }
        // ⊥ ("no evidence yet") is the fixpoint seed on recursive edges only.
        let mut cur: HashMap<ParamKey, Option<Transfer>> =
            members.iter().cloned().map(|m| (m, None)).collect();

        let lookup = |callee: &str,
                      arg: i64,
                      param_val: &HashMap<ParamKey, Transfer>,
                      cur: &HashMap<ParamKey, Option<Transfer>>|
         -> Option<Transfer> {
            let Some(skel) = sk.get(callee) else {
                return Some(Transfer::Unknown); // extern, no summary
            };
            if !skel.params.iter().any(|q| q.index == arg) {
                return Some(Transfer::Unknown); // no such logical param
            }
            let keyp = (callee.to_owned(), arg);
            if let Some(v) = param_val.get(&keyp) {
                return Some(*v);
            }
            if let Some(v) = cur.get(&keyp) {
                return *v; // same-SCC member, mid-fixpoint (may be ⊥)
            }
            Some(Transfer::Unknown) // unreachable under a correct topo order
        };

        let mut changed = true;
        while changed {
            changed = false;
            for m in &members {
                let p = sk[&m.0]
                    .params
                    .iter()
                    .find(|q| q.index == m.1)
                    .expect("member param exists");
                let new = if p.paths.is_empty() {
                    Some(Transfer::No) // nothing happens to it -> kept
                } else {
                    let mut acc: Option<Transfer> = None;
                    for a in &p.paths {
                        let contrib = match a {
                            PathAction::Dispose => Some(Transfer::Must),
                            PathAction::Borrow => Some(Transfer::No),
                            PathAction::Forward { callee, arg } => {
                                lookup(callee, *arg, &param_val, &cur)
                            }
                        };
                        acc = match (acc, contrib) {
                            (None, b) => b,
                            (a, None) => a,
                            (Some(a), Some(b)) => Some(join(a, b)),
                        };
                    }
                    acc
                };
                if new != cur[m] {
                    cur.insert(m.clone(), new);
                    changed = true;
                }
            }
        }
        for m in members {
            // ⊥ (no evidence) finalizes as `no` (kept/borrowed).
            let v = cur[&m].unwrap_or(Transfer::No);
            param_val.insert(m, v);
        }
    }

    // --- returns: iterative, memoized, cycle-safe chase along forward edges --
    let mut ret_val: HashMap<String, String> = HashMap::new();
    let resolve_return = |start: &str, ret_val: &mut HashMap<String, String>| -> String {
        if let Some(v) = ret_val.get(start) {
            return v.clone();
        }
        let mut path: Vec<String> = Vec::new();
        let mut on_path: BTreeSet<String> = BTreeSet::new();
        let mut key = start.to_owned();
        let val: String;
        loop {
            if let Some(v) = ret_val.get(&key) {
                val = v.clone();
                break;
            }
            match &sk[&key].ret {
                ReturnSkeleton::None => {
                    val = "none".to_owned();
                    ret_val.insert(key.clone(), val.clone());
                    break;
                }
                ReturnSkeleton::Fresh => {
                    val = "fresh".to_owned();
                    ret_val.insert(key.clone(), val.clone());
                    break;
                }
                ReturnSkeleton::Unknown => {
                    val = "unknown".to_owned();
                    ret_val.insert(key.clone(), val.clone());
                    break;
                }
                ReturnSkeleton::Forward { callee } => {
                    if !sk.contains_key(callee) {
                        val = "unknown".to_owned(); // extern, no summary
                        ret_val.insert(key.clone(), val.clone());
                        break;
                    }
                    if *callee == key || on_path.contains(callee) {
                        // forward-return cycle: no ground
                        val = "unknown".to_owned();
                        ret_val.insert(key.clone(), val.clone());
                        break;
                    }
                    path.push(key.clone());
                    on_path.insert(key.clone());
                    key = callee.clone();
                }
            }
        }
        // Propagate up the chain (`aliasOf:` remap degradation cannot occur —
        // the production skeletons never produce it).
        for k in path.into_iter().rev() {
            ret_val.insert(k, val.clone());
        }
        ret_val[start].clone()
    };

    let mut out: Mos = HashMap::new();
    let keys: Vec<String> = sk.keys().cloned().collect();
    for key in keys {
        let params = sk[&key]
            .params
            .iter()
            .map(|p| ParamSummary {
                index: p.index,
                transfer: param_val
                    .get(&(key.clone(), p.index))
                    .copied()
                    .unwrap_or(Transfer::No),
            })
            .collect();
        let returns = resolve_return(&key, &mut ret_val);
        out.insert(key.clone(), MethodSummary { params, returns });
    }
    Ok(out)
}
