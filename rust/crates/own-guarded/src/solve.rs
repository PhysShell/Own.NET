//! The shadow driver: taint, election, SCCs, cells. Every lattice operation is
//! the kernel's (`read`, `contribute`, `Cells::join`, `import`, `shape_of`);
//! this file only decides which coordinates exist, which edge carries which
//! transform, and in which order the SCCs are swept.
//!
//! No schedule parameter: each SCC is iterated by full sweeps over its members
//! until a pass changes nothing, within `n·HEIGHT+1` passes (A7, A12). Only
//! `fin()` values cross an SCC boundary (A13).

use std::collections::HashMap;

use crate::facts::{local, Act, Arg, Call, Func, Local, Nge};
use p037_kernel::{
    contribute, import, read, shape_of, Cells, Election, GuardBinding, Lattice, Mask, Shape,
    Transfer, Transform,
};

/// One coordinate's result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum Solved {
    /// The raw least fixpoint of the guarded system and its shape.
    Guarded {
        /// The elected shape.
        shape: Shape,
        /// The raw (unfinalized) lfp cells; `apply` finalizes them.
        cells: Cells,
    },
    /// `NO_GUARDED_EVIDENCE(reason)`.
    NoEvidence(String),
}

pub(crate) fn via(r: &str) -> Nge {
    format!("via:{}", r.trim_start_matches("via:"))
}

/// A coordinate's local facts with its forwards resolved to coordinate ids.
struct Node<'n> {
    func: usize,
    local: &'n Local,
    fwds: Vec<(usize, usize)>,
}

/// G-S1 stage 2's binding of the callee's elected guard at one call.
fn binding(call: Option<&Call<'_>>, callee: Election) -> GuardBinding {
    let Election::One(h) = callee else {
        return GuardBinding::Opaque;
    };
    match call.and_then(|c| c.arg(u64::from(h))) {
        Some(Arg::Param { ordinal, negated }) => match u8::try_from(ordinal) {
            Ok(k) if negated => GuardBinding::Neg {
                callee: h,
                caller: k,
            },
            Ok(k) => GuardBinding::Id {
                callee: h,
                caller: k,
            },
            Err(_) => GuardBinding::Opaque,
        },
        Some(Arg::Bool(_) | Arg::Null | Arg::New) => GuardBinding::Const,
        _ => GuardBinding::Opaque,
    }
}

/// G-S5, in the canonical orientation (pos = truthy / non-null).
fn transform(call: Option<&Call<'_>>, callee: Election, caller: Election) -> Transform {
    let Election::One(h) = callee else {
        return Transform::Opaque;
    };
    match call.and_then(|c| c.arg(u64::from(h))) {
        Some(Arg::Bool(true) | Arg::New) => Transform::ConstPos,
        Some(Arg::Bool(false) | Arg::Null) => Transform::ConstNeg,
        Some(Arg::Param { ordinal, negated })
            if u8::try_from(ordinal).ok().map(Election::One) == Some(caller) =>
        {
            if negated {
                Transform::Neg
            } else {
                Transform::Id
            }
        }
        _ => Transform::Opaque,
    }
}

/// Stage 1: the joined guard, when an action sits on a path through it.
fn own_seed(l: &Local) -> Election {
    let governed = l
        .paths
        .iter()
        .any(|p| p.pos.is_some() && p.act != Act::Kept);
    l.guard
        .filter(|_| governed)
        .map_or(Election::None, Election::One)
}

/// Strongly connected components, callees first (Kosaraju, iterative).
fn sccs(adj: &[Vec<usize>]) -> Vec<Vec<usize>> {
    let mut radj: Vec<Vec<usize>> = vec![Vec::new(); adj.len()];
    for (u, vs) in adj.iter().enumerate() {
        for v in vs {
            radj.get_mut(*v).into_iter().for_each(|r| r.push(u));
        }
    }
    let mut seen = vec![false; adj.len()];
    let mut order = Vec::new();
    for s in 0..adj.len() {
        let mut stack = vec![(s, 0_usize)];
        while let Some((u, k)) = stack.pop() {
            if k == 0 && std::mem::replace(seen.get_mut(u).unwrap_or(&mut true), true) {
                continue;
            }
            match adj.get(u).and_then(|a| a.get(k)) {
                Some(&v) => stack.extend([(u, k.saturating_add(1)), (v, 0)]),
                None => order.push(u),
            }
        }
    }
    let mut comp = vec![false; adj.len()];
    let mut out = Vec::new();
    for &s in order.iter().rev() {
        let mut members = Vec::new();
        let mut stack = vec![s];
        while let Some(u) = stack.pop() {
            if !std::mem::replace(comp.get_mut(u).unwrap_or(&mut true), true) {
                members.push(u);
                stack.extend(radj.get(u).into_iter().flatten());
            }
        }
        if !members.is_empty() {
            out.push(members);
        }
    }
    out.reverse();
    out
}

/// Solve every coordinate of the document. `height` is the per-member pass
/// allowance (`Cells::HEIGHT` in production; a smaller value is the A12 fault
/// injection).
pub(crate) fn solve(fns: &[Func<'_>], height: usize) -> (Vec<(usize, usize)>, Vec<Solved>) {
    let all: Vec<(usize, usize)> = fns
        .iter()
        .enumerate()
        .flat_map(|(fi, f)| (0..f.params.len()).map(move |i| (fi, i)))
        .collect();
    let ids: HashMap<(usize, usize), usize> =
        all.iter().enumerate().map(|(c, x)| (*x, c)).collect();
    let locals: Vec<Result<Local, Nge>> = all.iter().map(|&(fi, i)| local(fns, fi, i)).collect();

    // A9–A11: a local failure or an unresolvable forward is no evidence; a
    // forward into a coordinate without evidence taints its caller below,
    // callee-first. Absence never reads as a value.
    let mut st: Vec<Option<Nge>> = Vec::new();
    let mut nodes: Vec<Option<Node<'_>>> = Vec::new();
    for (&(func, _), l) in all.iter().zip(&locals) {
        let id = |t: &Result<(usize, usize), Nge>| -> Result<usize, Nge> {
            Ok(*ids
                .get(t.as_ref().map_err(Clone::clone)?)
                .ok_or("malformed")?)
        };
        let fwds = l.as_ref().map_err(Clone::clone).and_then(|l| {
            l.fwds
                .iter()
                .map(|(n, t)| Ok((*n, id(t)?)))
                .collect::<Result<Vec<_>, Nge>>()
        });
        st.push(fwds.as_ref().err().cloned());
        nodes.push(
            l.as_ref()
                .ok()
                .zip(fwds.ok())
                .map(|(local, fwds)| Node { func, local, fwds }),
        );
    }
    let call = |n: &Node<'_>, k: usize| fns.get(n.func)?.sidecar.as_ref().ok()?.calls.get(k);
    let live = || {
        nodes
            .iter()
            .enumerate()
            .filter_map(|(c, n)| Some((c, n.as_ref()?)))
    };

    // G-S1: the election fixpoint over the clean coordinates, full sweeps.
    let mut e = vec![Election::None; all.len()];
    let n_clean = nodes.iter().flatten().count();
    let mut elected = false;
    for _ in 0..n_clean
        .saturating_mul(<Election as Lattice>::HEIGHT)
        .saturating_add(1)
    {
        let mut changed = false;
        for (c, n) in live() {
            let v = n.fwds.iter().fold(own_seed(n.local), |acc, &(k, t)| {
                let callee = e.get(t).copied().unwrap_or(Election::Conflict);
                acc.join(import(callee, binding(call(n, k), callee)))
            });
            if let Some(x) = e.get_mut(c).filter(|x| **x != v) {
                *x = v;
                changed = true;
            }
        }
        if !changed {
            elected = true;
            break;
        }
    }
    if !elected {
        let out = st
            .iter()
            .map(|r| Solved::NoEvidence(r.clone().unwrap_or_else(|| "bound".to_owned())));
        return (all, out.collect());
    }
    let el = |c: usize| e.get(c).copied().unwrap_or(Election::Conflict);

    // G-S2..G-S5: seeds and edges per clean coordinate.
    let mut seeds = vec![Cells::BOT; all.len()];
    let mut edges: Vec<Vec<(usize, Transform, Mask)>> = vec![Vec::new(); all.len()];
    for (c, n) in live() {
        let split = matches!(el(c), Election::One(g) if n.local.guard == Some(g));
        for p in &n.local.paths {
            let mask = match p.pos {
                Some(true) if split => Mask::PosOnly,
                Some(false) if split => Mask::NegOnly,
                _ => Mask::Both,
            };
            let seed = match p.act {
                Act::Kept => Transfer::No,
                Act::Release => Transfer::Must,
                Act::Forward(k) => {
                    let t = n.fwds.iter().find(|f| f.0 == k).map_or(usize::MAX, |f| f.1);
                    let tr = transform(call(n, k), el(t), el(c));
                    edges
                        .get_mut(c)
                        .into_iter()
                        .for_each(|es| es.push((t, tr, mask)));
                    Transfer::Bot
                }
            };
            let s = seeds.get_mut(c);
            s.into_iter()
                .for_each(|s| *s = s.join(contribute(mask, Cells::diag(seed))));
        }
    }

    // G-F1 per SCC, callees first; only finalized values cross (A13).
    let adj: Vec<Vec<usize>> = edges
        .iter()
        .map(|es| es.iter().map(|x| x.0).collect())
        .collect();
    let comps = sccs(&adj);
    let mut comp = vec![usize::MAX; all.len()];
    for (id, members) in comps.iter().enumerate() {
        for &m in members {
            comp.get_mut(m).into_iter().for_each(|x| *x = id);
        }
    }
    let mut raw = vec![Cells::BOT; all.len()];
    for (id, members) in comps.iter().enumerate() {
        let members: Vec<usize> = members
            .iter()
            .copied()
            .filter(|&m| nodes.get(m).is_some_and(Option::is_some))
            .collect();
        let out_edges = || {
            members
                .iter()
                .flat_map(|&m| edges.get(m).into_iter().flatten())
        };
        let mut verdict = out_edges()
            .find_map(|x| st.get(x.0).cloned().flatten())
            .map(|r| via(&r));
        if verdict.is_none() {
            verdict = Some("bound".to_owned());
            for _ in 0..members.len().saturating_mul(height).saturating_add(1) {
                let mut changed = false;
                for &m in &members {
                    let seed = seeds.get(m).copied().unwrap_or(Cells::BOT);
                    let v = edges
                        .get(m)
                        .into_iter()
                        .flatten()
                        .fold(seed, |acc, &(t, tr, mask)| {
                            let callee = raw
                                .get(t)
                                .copied()
                                .unwrap_or(Cells::diag(Transfer::Unknown));
                            let callee = if comp.get(t) == Some(&id) {
                                callee
                            } else {
                                callee.fin()
                            };
                            acc.join(contribute(mask, read(tr, callee)))
                        });
                    if let Some(x) = raw.get_mut(m).filter(|x| **x != v) {
                        *x = v;
                        changed = true;
                    }
                }
                if !changed {
                    verdict = None;
                    break;
                }
            }
        }
        if let Some(r) = verdict {
            for &m in &members {
                st.get_mut(m).into_iter().for_each(|x| *x = Some(r.clone()));
            }
        }
    }
    let out = (0..all.len())
        .map(|c| match st.get(c).cloned().flatten() {
            Some(r) => Solved::NoEvidence(r),
            None => Solved::Guarded {
                shape: shape_of(el(c)),
                cells: raw.get(c).copied().unwrap_or(Cells::BOT),
            },
        })
        .collect();
    (all, out)
}
