//! Isolated tests for the generic worklist solver — the mandated correctness
//! battery from #214, exercised on a simple concrete lattice *before* any domain
//! rule is ported:
//!
//! * CFG shapes: straight line, diamond, loop, nested loop, unreachable block,
//!   multiple predecessors, an abnormal (early) exit;
//! * lattice laws (idempotent / commutative / associative join, `x <= join`),
//!   **exhaustively** over a small state space;
//! * worklist-order independence across every [`Schedule`];
//! * the convergence guard fires on a deliberately non-monotone join.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_analysis::{solve, solve_with, Analysis, ControlFlowGraph, Lattice, Schedule};
use std::cell::RefCell;
use std::collections::BTreeSet;

// ---- a tiny concrete lattice: a set of u8 tokens under union ----------------

#[derive(Debug, Clone, PartialEq, Eq)]
struct TokenSet(BTreeSet<u8>);

impl TokenSet {
    fn of(items: &[u8]) -> Self {
        Self(items.iter().copied().collect())
    }
}

impl Lattice for TokenSet {
    fn bottom() -> Self {
        Self(BTreeSet::new())
    }
    fn join(&mut self, other: &Self) -> bool {
        let before = self.0.len();
        self.0.extend(other.0.iter().copied());
        self.0.len() != before
    }
}

fn leq(a: &TokenSet, b: &TokenSet) -> bool {
    a.0.is_subset(&b.0)
}

// ---- a concrete graph + a gen/kill analysis over it -------------------------

struct Graph {
    entry: usize,
    succ: Vec<Vec<usize>>,
}

impl ControlFlowGraph for Graph {
    fn num_blocks(&self) -> usize {
        self.succ.len()
    }
    fn entry(&self) -> usize {
        self.entry
    }
    fn successors(&self, block: usize) -> &[usize] {
        self.succ.get(block).map_or(&[], Vec::as_slice)
    }
}

/// Forward "reaching tokens": each block generates a token set; the transfer is
/// `out = in ∪ gen` (a monotone union). `in` at a block is the join of pred outs.
struct Reaching {
    gen: Vec<TokenSet>,
    entry: TokenSet,
}

impl Analysis for Reaching {
    type Fact = TokenSet;
    fn entry_fact(&self) -> TokenSet {
        self.entry.clone()
    }
    fn transfer(&self, block: usize, in_fact: &TokenSet) -> TokenSet {
        let mut out = in_fact.clone();
        if let Some(g) = self.gen.get(block) {
            out.join(g);
        }
        out
    }
}

fn gens(per_block: &[&[u8]]) -> Vec<TokenSet> {
    per_block.iter().map(|b| TokenSet::of(b)).collect()
}

// ---- CFG-shape tests --------------------------------------------------------

#[test]
fn straight_line() {
    // 0 -> 1 -> 2, gens {0},{1},{2}
    let g = Graph {
        entry: 0,
        succ: vec![vec![1], vec![2], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    assert_eq!(sol.in_fact(0), Some(&TokenSet::of(&[])));
    assert_eq!(sol.in_fact(1), Some(&TokenSet::of(&[0])));
    assert_eq!(sol.in_fact(2), Some(&TokenSet::of(&[0, 1])));
}

#[test]
fn diamond_merges_both_arms() {
    // 0 -> {1,2} -> 3. gens: 0:{0} 1:{1} 2:{2} 3:{3}
    let g = Graph {
        entry: 0,
        succ: vec![vec![1, 2], vec![3], vec![3], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    // block 3's in-fact is the union of both arms: {0,1} ∪ {0,2} = {0,1,2}
    assert_eq!(sol.in_fact(3), Some(&TokenSet::of(&[0, 1, 2])));
}

#[test]
fn self_loop_reaches_fixpoint() {
    // 0 -> 1, 1 -> 1 (self loop) and 1 -> 2
    let g = Graph {
        entry: 0,
        succ: vec![vec![1], vec![1, 2], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    // 1 sees its own gen through the back-edge; in[1] = {0} ∪ {0,1} = {0,1}
    assert_eq!(sol.in_fact(1), Some(&TokenSet::of(&[0, 1])));
    assert_eq!(sol.in_fact(2), Some(&TokenSet::of(&[0, 1])));
}

#[test]
fn nested_loop_reaches_fixpoint() {
    // outer: 1..3, inner: 2 self-loops; 0->1->2->3->1 (outer back), 2->2 (inner)
    let g = Graph {
        entry: 0,
        succ: vec![vec![1], vec![2], vec![2, 3], vec![1, 4], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3], &[4]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    // Everything before the exit accumulates; exit sees all of 0..3 plus its own.
    assert_eq!(sol.in_fact(4), Some(&TokenSet::of(&[0, 1, 2, 3])));
    assert_eq!(sol.in_fact(2), Some(&TokenSet::of(&[0, 1, 2, 3])));
}

#[test]
fn unreachable_block_is_none_and_ignored() {
    // 0 -> 1 ; block 2 is unreachable (nobody points at it) and gens a poison
    // token that must NOT appear anywhere.
    let g = Graph {
        entry: 0,
        succ: vec![vec![1], vec![], vec![1]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[99]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    assert!(!sol.is_reachable(2));
    assert_eq!(sol.in_fact(2), None);
    // block 1's in-fact must not include the unreachable block's gen (99),
    // even though 2 -> 1 is an edge: an unreachable pred contributes nothing.
    assert_eq!(sol.in_fact(1), Some(&TokenSet::of(&[0])));
}

#[test]
fn multiple_predecessors_join() {
    // 0 -> {1,2,3} ; 1,2,3 -> 4. Four-way merge at 4.
    let g = Graph {
        entry: 0,
        succ: vec![vec![1, 2, 3], vec![4], vec![4], vec![4], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3], &[4]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    assert_eq!(sol.in_fact(4), Some(&TokenSet::of(&[0, 1, 2, 3])));
}

#[test]
fn abnormal_early_exit() {
    // 0 -> {1(early exit), 2}; 2 -> 3. Block 1 is a sink (return). Two exits.
    let g = Graph {
        entry: 0,
        succ: vec![vec![1, 2], vec![], vec![3], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3]]),
        entry: TokenSet::bottom(),
    };
    let sol = solve(&g, &a);
    assert_eq!(sol.in_fact(1), Some(&TokenSet::of(&[0]))); // early-exit sink
    assert_eq!(sol.in_fact(3), Some(&TokenSet::of(&[0, 2])));
}

// ---- worklist-order independence -------------------------------------------

#[test]
fn worklist_order_independence() {
    // A CFG with a loop, a diamond and multiple predecessors — enough structure
    // that a bad schedule would diverge if the result depended on order.
    let g = Graph {
        entry: 0,
        succ: vec![
            vec![1],
            vec![2, 3],
            vec![4],
            vec![4],
            vec![1, 5], // back-edge 4->1 (loop) + exit
            vec![],
        ],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3], &[4], &[5]]),
        entry: TokenSet::of(&[100]),
    };

    let schedules = [
        Schedule::Rpo,
        Schedule::Postorder,
        Schedule::Fifo,
        Schedule::Lifo,
        Schedule::BlockOrder,
    ];
    let reference = solve_with(&g, &a, Schedule::Rpo);
    for sched in schedules {
        let sol = solve_with(&g, &a, sched);
        for b in 0..g.num_blocks() {
            assert_eq!(
                sol.in_fact(b),
                reference.in_fact(b),
                "schedule {sched:?} diverged at block {b}"
            );
        }
    }
}

// ---- the schedules are materially distinct orders ---------------------------

/// A `Reaching` clone that records the block-visit sequence (interior mutability)
/// so a test can prove two schedules visit in genuinely different orders — not
/// merely that they agree on the result.
struct Recording<'a> {
    gen: Vec<TokenSet>,
    entry: TokenSet,
    order: &'a RefCell<Vec<usize>>,
}

impl Analysis for Recording<'_> {
    type Fact = TokenSet;
    fn entry_fact(&self) -> TokenSet {
        self.entry.clone()
    }
    fn transfer(&self, block: usize, in_fact: &TokenSet) -> TokenSet {
        self.order.borrow_mut().push(block);
        let mut out = in_fact.clone();
        if let Some(g) = self.gen.get(block) {
            out.join(g);
        }
        out
    }
}

#[test]
fn schedules_are_materially_distinct_not_aliases() {
    // A loop + diamond, so the visitation order genuinely diverges by schedule.
    let g = Graph {
        entry: 0,
        succ: vec![
            vec![1],
            vec![2, 3],
            vec![4],
            vec![4],
            vec![1, 5], // 4 -> 1 back-edge (loop) + exit
            vec![],
        ],
    };
    let gen = gens(&[&[0], &[1], &[2], &[3], &[4], &[5]]);
    let entry = TokenSet::of(&[100]);

    let schedules = [
        Schedule::Rpo,
        Schedule::Postorder,
        Schedule::Fifo,
        Schedule::Lifo,
        Schedule::BlockOrder,
    ];
    let mut sequences: Vec<Vec<usize>> = Vec::new();
    let mut solutions = Vec::new();
    for sched in schedules {
        let order = RefCell::new(Vec::new());
        let rec = Recording {
            gen: gen.clone(),
            entry: entry.clone(),
            order: &order,
        };
        let sol = solve_with(&g, &rec, sched);
        let facts: Vec<Option<TokenSet>> = (0..g.num_blocks())
            .map(|b| sol.in_fact(b).cloned())
            .collect();
        solutions.push(facts);
        sequences.push(order.into_inner());
    }

    // Same fixpoint under every schedule.
    let reference = solutions.first().expect("at least one schedule ran");
    for s in &solutions {
        assert_eq!(s, reference, "schedules must agree on the solution");
    }
    // But the visit ORDERS must be genuinely different — the old bug was that
    // Fifo/Lifo/BlockOrder collapsed to the same order. Require at least three
    // distinct sequences among the five.
    let distinct: BTreeSet<Vec<usize>> = sequences.iter().cloned().collect();
    assert!(
        distinct.len() >= 3,
        "expected >= 3 distinct visitation orders, got {} (schedules are aliasing): {sequences:?}",
        distinct.len()
    );
    // Fifo pops the front (block 0 first); Lifo pops the back (highest-seeded
    // block first) — so their first visited block differs.
    assert_ne!(
        sequences.get(2).and_then(|s| s.first()),
        sequences.get(3).and_then(|s| s.first()),
        "true FIFO and true LIFO must start at opposite ends"
    );
}

// ---- structural permutations do not change the result -----------------------

#[test]
fn successor_order_permutation_is_invariant() {
    // Same graph, but every block's successor list reversed. The join is
    // commutative, so the converged solution must be identical.
    let forward = Graph {
        entry: 0,
        succ: vec![vec![1, 2], vec![3], vec![3], vec![1, 4], vec![]],
    };
    let reversed = Graph {
        entry: 0,
        succ: vec![vec![2, 1], vec![3], vec![3], vec![4, 1], vec![]],
    };
    let a = Reaching {
        gen: gens(&[&[0], &[1], &[2], &[3], &[4]]),
        entry: TokenSet::bottom(),
    };
    let sf = solve(&forward, &a);
    let sr = solve(&reversed, &a);
    for b in 0..forward.num_blocks() {
        assert_eq!(
            sf.in_fact(b),
            sr.in_fact(b),
            "successor-order permutation changed block {b}"
        );
    }
}

#[test]
fn block_id_permutation_is_invariant_when_mapped_back() {
    // Relabel blocks by a permutation π, solve the relabelled graph, then map
    // results back: in_fact(original b) must equal in_fact(π(b)) in the permuted
    // solution. This also exercises a different seed/enqueue order.
    let base = Graph {
        entry: 0,
        succ: vec![vec![1], vec![2, 3], vec![4], vec![4], vec![1, 5], vec![]],
    };
    let gen0 = gens(&[&[0], &[1], &[2], &[3], &[4], &[5]]);
    let a0 = Reaching {
        gen: gen0.clone(),
        entry: TokenSet::of(&[7]),
    };
    let base_sol = solve(&base, &a0);

    // π: 0->5, 1->4, 2->3, 3->2, 4->1, 5->0 (reverse relabelling).
    let n = base.num_blocks();
    let pi = |b: usize| n - 1 - b;
    let mut succ = vec![Vec::new(); n];
    let mut gen = vec![TokenSet::bottom(); n];
    for b in 0..n {
        let succ_b: Vec<usize> = base.successors(b).iter().map(|&s| pi(s)).collect();
        if let Some(slot) = succ.get_mut(pi(b)) {
            *slot = succ_b;
        }
        if let (Some(dst), Some(src)) = (gen.get_mut(pi(b)), gen0.get(b)) {
            *dst = src.clone();
        }
    }
    let permuted = Graph { entry: pi(0), succ };
    let a1 = Reaching {
        gen,
        entry: TokenSet::of(&[7]),
    };
    let perm_sol = solve(&permuted, &a1);

    for b in 0..n {
        assert_eq!(
            base_sol.in_fact(b),
            perm_sol.in_fact(pi(b)),
            "block-ID permutation changed the mapped-back fact of block {b}"
        );
    }
}

// ---- lattice laws (exhaustive over a small state space) ---------------------

fn all_subsets(universe: &[u8]) -> Vec<TokenSet> {
    let n = universe.len();
    let mut out = Vec::new();
    // 2^n subsets via bitmask (n small).
    for mask in 0u32..(1u32 << n) {
        let mut s = BTreeSet::new();
        for (i, &tok) in universe.iter().enumerate() {
            if mask & (1u32 << i) != 0 {
                s.insert(tok);
            }
        }
        out.push(TokenSet(s));
    }
    out
}

#[test]
fn lattice_laws_hold_exhaustively() {
    let universe = [1u8, 2, 3, 4]; // 16 subsets -> 16^3 triples, cheap
    let elems = all_subsets(&universe);

    for x in &elems {
        // idempotent: join(x, x) == x
        let mut xx = x.clone();
        assert!(!xx.join(x), "join(x,x) must not report a change");
        assert_eq!(&xx, x, "join(x, x) == x");

        // bottom identity + x <= join(x, y), and commutativity/associativity
        assert!(leq(&TokenSet::bottom(), x), "bottom <= x");
        for y in &elems {
            let mut xy = x.clone();
            xy.join(y);
            let mut yx = y.clone();
            yx.join(x);
            assert_eq!(xy, yx, "join commutative");
            assert!(leq(x, &xy), "x <= join(x, y)");
            assert!(leq(y, &xy), "y <= join(x, y)");

            for z in &elems {
                // associative: join(join(x,y),z) == join(x,join(y,z))
                let mut lhs = x.clone();
                lhs.join(y);
                lhs.join(z);
                let mut rhs_inner = y.clone();
                rhs_inner.join(z);
                let mut rhs = x.clone();
                rhs.join(&rhs_inner);
                assert_eq!(lhs, rhs, "join associative");
            }
        }
    }
}

// ---- convergence guard ------------------------------------------------------

/// A deliberately BROKEN lattice whose `join` never stops growing (adds a fresh
/// token every time), to prove the convergence guard fires instead of hanging.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Diverging(u64);

impl Lattice for Diverging {
    fn bottom() -> Self {
        Self(0)
    }
    fn join(&mut self, other: &Self) -> bool {
        // Non-idempotent: always grows, so a looped block never stabilises.
        self.0 = self.0.wrapping_add(other.0).wrapping_add(1);
        true
    }
}

struct AlwaysGrow;
impl Analysis for AlwaysGrow {
    type Fact = Diverging;
    fn entry_fact(&self) -> Diverging {
        Diverging(1)
    }
    fn transfer(&self, _block: usize, in_fact: &Diverging) -> Diverging {
        Diverging(in_fact.0.wrapping_add(1))
    }
}

#[test]
#[should_panic(expected = "did not converge")]
fn convergence_guard_fires_on_nonmonotone_join() {
    // A loop between blocks 1 and 2 that does NOT pass through the entry (whose
    // in-fact is pinned to the boundary), so the diverging join keeps growing on
    // the back-edge forever: the guard must abort instead of hanging.
    // 0 -> 1 -> 2 -> 1 (back-edge)
    let g = Graph {
        entry: 0,
        succ: vec![vec![1], vec![2], vec![1]],
    };
    let _ = solve(&g, &AlwaysGrow);
}
