//! A generic monotone-lattice forward dataflow solver (P-022 §"Solver
//! scheduling"; the `rustc_mir_dataflow` shape the Python `_Analyzer.fixpoint`
//! ports to).
//!
//! The contract:
//!
//! * [`Lattice`] — a join-semilattice with a `bottom`. `join` is the least upper
//!   bound *into self*, returning whether `self` changed. Callers guarantee it is
//!   idempotent, commutative, associative and monotone; `tests/solver.rs` checks
//!   those laws exhaustively for the concrete lattices.
//! * [`ControlFlowGraph`] — blocks `0..num_blocks`, an entry, and forward
//!   successor edges. Predecessors and reachability are derived here.
//! * [`Analysis`] — the boundary `entry_fact` and a monotone `transfer`.
//!
//! [`solve`] returns the converged **in-fact** per reachable block. Because the
//! join is commutative/associative and the transfer monotone, the fixpoint is
//! **unique regardless of visitation order** — [`Schedule`] only changes how many
//! times blocks are re-visited, never the result (proven in
//! `tests/solver.rs::worklist_order_independence`). Reverse-postorder is the
//! default because it minimizes re-visits on reducible CFGs.
//!
//! A **convergence guard** counts block visits and fails loudly (`assert!`) if it
//! exceeds a generous bound — a non-monotone `join` or an ever-ascending lattice
//! would otherwise spin forever. Monotone analyses over a finite lattice never
//! approach it.

use std::collections::{BTreeSet, VecDeque};

/// A join-semilattice element with a least (`bottom`) value.
pub trait Lattice: Clone + PartialEq {
    /// The identity for [`join`](Lattice::join): `x.join(bottom) == x` and
    /// `bottom` is `<=` every element.
    fn bottom() -> Self;

    /// Join `other` into `self` (least upper bound), returning `true` iff `self`
    /// changed. Must be idempotent, commutative, associative and monotone.
    fn join(&mut self, other: &Self) -> bool;
}

/// A forward control-flow graph over blocks `0..num_blocks()`.
pub trait ControlFlowGraph {
    /// Number of blocks; ids are `0..num_blocks`.
    fn num_blocks(&self) -> usize;
    /// The entry block id.
    fn entry(&self) -> usize;
    /// Forward successor block ids of `block`.
    fn successors(&self, block: usize) -> &[usize];
}

/// A monotone forward dataflow analysis over a [`ControlFlowGraph`].
pub trait Analysis {
    /// The lattice of dataflow facts.
    type Fact: Lattice;
    /// The boundary fact flowing into the entry block.
    fn entry_fact(&self) -> Self::Fact;
    /// The block's out-fact given its in-fact. Must be monotone in `in_fact`.
    fn transfer(&self, block: usize, in_fact: &Self::Fact) -> Self::Fact;
}

/// Worklist visitation order.
///
/// The converged solution is identical for every variant (that is the point of
/// `worklist_order_independence`); only the visit count differs.
/// [`Schedule::Rpo`] is the efficient default.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Schedule {
    /// Reverse postorder — a block after its (non-back-edge) predecessors.
    Rpo,
    /// Postorder — the RPO reversed (a deliberately poor order, for the test).
    Postorder,
    /// FIFO queue.
    Fifo,
    /// LIFO stack.
    Lifo,
    /// Ascending block id.
    BlockOrder,
}

/// The converged analysis result: the in-fact of every reachable block
/// (`None` for unreachable blocks).
#[derive(Debug, Clone)]
pub struct Solution<F> {
    in_facts: Vec<Option<F>>,
}

impl<F: Clone> Solution<F> {
    /// The converged in-fact of `block`, or `None` if the block is unreachable.
    #[must_use]
    pub fn in_fact(&self, block: usize) -> Option<&F> {
        self.in_facts.get(block).and_then(Option::as_ref)
    }

    /// Whether `block` is reachable from the entry.
    #[must_use]
    pub fn is_reachable(&self, block: usize) -> bool {
        self.in_facts.get(block).is_some_and(Option::is_some)
    }
}

/// Solve `analysis` over `graph` with the default reverse-postorder schedule.
#[must_use]
pub fn solve<G, A>(graph: &G, analysis: &A) -> Solution<A::Fact>
where
    G: ControlFlowGraph,
    A: Analysis,
{
    solve_with(graph, analysis, Schedule::Rpo)
}

/// Solve with an explicit [`Schedule`]. The result is schedule-independent; this
/// entry point exists so the order-independence property can be exercised.
///
/// # Panics
/// The convergence guard `assert!`s (fails loudly) if block visits exceed a
/// generous bound — which only happens if `A::Fact`'s `join` is non-monotone or
/// non-idempotent, i.e. violates the [`Lattice`] contract. A conforming monotone
/// analysis over a finite lattice never approaches it.
#[must_use]
pub fn solve_with<G, A>(graph: &G, analysis: &A, schedule: Schedule) -> Solution<A::Fact>
where
    G: ControlFlowGraph,
    A: Analysis,
{
    let n = graph.num_blocks();
    let entry = graph.entry();

    let preds = predecessors(graph);
    let reachable = reachable_from(graph, entry);
    let rpo_index = rpo_indices(graph, entry, &reachable);

    // out[b] holds the last computed out-fact; None until first visited.
    let mut out: Vec<Option<A::Fact>> = vec![None; n];
    let mut in_facts: Vec<Option<A::Fact>> = vec![None; n];

    // Seed every reachable block so unreachable ones are never touched. The seed
    // order is ascending block id; the block-ID-permutation test proves the
    // converged result does not depend on it.
    let mut worklist = Worklist::new(schedule, n, &rpo_index);
    for &b in &reachable {
        worklist.push(b);
    }

    // Convergence guard: a monotone analysis over a finite lattice re-visits each
    // block a bounded number of times. This backstop catches a non-monotone join
    // (an infinite ascent) and fails loudly instead of hanging.
    let reachable_len = reachable.len();
    let visit_cap = reachable_len
        .saturating_mul(reachable_len)
        .saturating_mul(64)
        .saturating_add(1024);
    let mut visits: usize = 0;

    while let Some(b) = worklist.pop() {
        visits = visits.saturating_add(1);
        assert!(
            visits <= visit_cap,
            "dataflow did not converge after {visits} block visits (cap {visit_cap}); \
             a non-monotone or non-idempotent `join` is the usual cause"
        );

        // in[b] = entry boundary if b is the entry, else the join of predecessor
        // out-facts. The entry's boundary fact dominates even under a back-edge.
        //
        // The merge is **seeded from the first predecessor with an out-fact** and
        // joins the rest — never `bottom.join(pred)`. This matches Python's
        // `in_state_of` (`out[ps[0]].copy()` then join `ps[1:]`) and, crucially,
        // means `join` is only ever called between two *real* predecessor states,
        // so a domain whose `join` carries a merge invariant (e.g. ownership's
        // block-scoped-loan equality) is never handed the empty `bottom` on one
        // side. With no predecessor yet processed, the seed is `bottom` (used
        // alone, unjoined) — the transient first-visit value, exactly like
        // Python's `State()` fallback.
        let in_b = if b == entry {
            analysis.entry_fact()
        } else {
            let mut acc: Option<A::Fact> = None;
            if let Some(ps) = preds.get(b) {
                for &p in ps {
                    if let Some(Some(op)) = out.get(p) {
                        match acc.as_mut() {
                            None => acc = Some(op.clone()),
                            Some(a) => {
                                a.join(op);
                            }
                        }
                    }
                }
            }
            acc.unwrap_or_else(A::Fact::bottom)
        };

        let out_b = analysis.transfer(b, &in_b);
        if let Some(slot) = in_facts.get_mut(b) {
            *slot = Some(in_b);
        }

        let changed = match out.get(b) {
            Some(Some(prev)) => prev != &out_b,
            _ => true,
        };
        if changed {
            if let Some(slot) = out.get_mut(b) {
                *slot = Some(out_b);
            }
            for &s in graph.successors(b) {
                if reachable.contains(&s) {
                    worklist.push(s);
                }
            }
        }
    }

    Solution { in_facts }
}

/// The worklist backing store — a *materially distinct* container per schedule,
/// with a `queued` bitset so a block is never enqueued twice.
enum Queue {
    /// Rpo / Postorder / `BlockOrder` — pop the smallest precomputed key.
    Priority(BTreeSet<(usize, usize)>),
    /// True FIFO: `push_back` / `pop_front` (visit in first-enqueued order).
    Fifo(VecDeque<usize>),
    /// True LIFO: `push` / `pop` (visit the most-recently-enqueued first).
    Lifo(Vec<usize>),
}

struct Worklist<'r> {
    queue: Queue,
    queued: Vec<bool>,
    schedule: Schedule,
    rpo_index: &'r [usize],
    n: usize,
}

impl<'r> Worklist<'r> {
    fn new(schedule: Schedule, n: usize, rpo_index: &'r [usize]) -> Self {
        let queue = match schedule {
            Schedule::Fifo => Queue::Fifo(VecDeque::new()),
            Schedule::Lifo => Queue::Lifo(Vec::new()),
            Schedule::Rpo | Schedule::Postorder | Schedule::BlockOrder => {
                Queue::Priority(BTreeSet::new())
            }
        };
        Self {
            queue,
            queued: vec![false; n],
            schedule,
            rpo_index,
            n,
        }
    }

    /// The priority key for the `Priority` schedules (unused by Fifo/Lifo).
    fn key(&self, block: usize) -> usize {
        let rpo = self.rpo_index.get(block).copied().unwrap_or(self.n);
        match self.schedule {
            Schedule::Rpo => rpo,                              // smallest RPO first
            Schedule::Postorder => self.n.saturating_sub(rpo), // largest RPO first
            // BlockOrder pops smallest id; Fifo/Lifo don't consult the key.
            Schedule::BlockOrder | Schedule::Fifo | Schedule::Lifo => block,
        }
    }

    fn push(&mut self, block: usize) {
        if self.queued.get(block).copied() == Some(true) {
            return;
        }
        if let Some(q) = self.queued.get_mut(block) {
            *q = true;
        }
        let key = self.key(block);
        match &mut self.queue {
            Queue::Priority(s) => {
                s.insert((key, block));
            }
            Queue::Fifo(q) => q.push_back(block),
            Queue::Lifo(v) => v.push(block),
        }
    }

    fn pop(&mut self) -> Option<usize> {
        let block = match &mut self.queue {
            Queue::Priority(s) => s.pop_first().map(|(_, b)| b),
            Queue::Fifo(q) => q.pop_front(),
            Queue::Lifo(v) => v.pop(),
        }?;
        if let Some(q) = self.queued.get_mut(block) {
            *q = false;
        }
        Some(block)
    }
}

fn predecessors<G: ControlFlowGraph>(graph: &G) -> Vec<Vec<usize>> {
    let n = graph.num_blocks();
    let mut preds = vec![Vec::new(); n];
    for b in 0..n {
        for &s in graph.successors(b) {
            if let Some(p) = preds.get_mut(s) {
                p.push(b);
            }
        }
    }
    preds
}

fn reachable_from<G: ControlFlowGraph>(graph: &G, entry: usize) -> BTreeSet<usize> {
    let mut seen = BTreeSet::new();
    let mut stack = vec![entry];
    while let Some(b) = stack.pop() {
        if seen.insert(b) {
            for &s in graph.successors(b) {
                if !seen.contains(&s) {
                    stack.push(s);
                }
            }
        }
    }
    seen
}

/// Reverse-postorder index for each block (`rpo_index[b]` smaller ⇒ earlier).
/// Unreachable blocks get index `n` (sorted last, never actually processed).
fn rpo_indices<G: ControlFlowGraph>(
    graph: &G,
    entry: usize,
    reachable: &BTreeSet<usize>,
) -> Vec<usize> {
    let n = graph.num_blocks();
    // Iterative postorder DFS (explicit stack of (block, next-successor-index)).
    let mut postorder: Vec<usize> = Vec::new();
    let mut visited = vec![false; n];
    let mut stack: Vec<(usize, usize)> = vec![(entry, 0)];
    if let Some(v) = visited.get_mut(entry) {
        *v = true;
    }
    while let Some(&(b, i)) = stack.last() {
        let succ = graph.successors(b);
        if let Some(&s) = succ.get(i) {
            if let Some(top) = stack.last_mut() {
                top.1 = i.saturating_add(1);
            }
            if visited.get(s).copied() == Some(false) {
                if let Some(v) = visited.get_mut(s) {
                    *v = true;
                }
                stack.push((s, 0));
            }
        } else {
            postorder.push(b);
            stack.pop();
        }
    }
    // RPO = reverse of postorder; assign ascending indices.
    let mut index = vec![n; n];
    let mut next = 0usize;
    for &b in postorder.iter().rev() {
        if reachable.contains(&b) {
            if let Some(slot) = index.get_mut(b) {
                *slot = next;
            }
            next = next.saturating_add(1);
        }
    }
    index
}
