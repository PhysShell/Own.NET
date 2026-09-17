//! Property twins.
//!
//! Every property is a Kani harness (`#[cfg(kani)]`, symbolic inputs,
//! bounded model checking) AND a plain test (`#[cfg(test)]`, exhaustive
//! where the domain allows, seeded-random otherwise). Both call the kernel
//! functions of `crate` — never a copy.
//!
//! Numbering follows the owner's A0 list: K1 transfer join laws, K2 election
//! join laws, K3 transform monotonicity, K4 election import monotonicity,
//! K5 collapse monotonicity (and join-morphism), K6 the G-A2 floor,
//! K7 no fabricated consume, K8 id/neg involutions, K9 the residual-⊥ lemma,
//! K10 solver order-independence; added: K11 the G-T2 lax simulation,
//! K12 `Uncond` coordinates stay diagonal, K13 the worked rows of P-037 §8.

pub mod application;
pub mod election;
pub mod lattice;
pub mod refinement;
pub mod solver;
pub mod transforms;

use crate::{
    elect, solve, Cells, Coord, Edge, Election, ElectionCoord, ElectionEdge, ElectionSystem, Guard,
    GuardBinding, Mask, Shape, System, Transfer, Transform, MAX_COORDS, MAX_EDGES,
};

/// The guarded lfp.
///
/// # Panics
/// If the solver does not stabilize within the height bound (K10 says it
/// always does).
#[must_use]
pub fn lfp(sys: &System) -> [Cells; MAX_COORDS] {
    let x = solve(sys);
    assert!(x.is_some(), "terminates within the height bound: {sys:?}");
    x.unwrap_or([Cells::BOT; MAX_COORDS])
}

/// The election lfp.
///
/// # Panics
/// If the pre-solver does not stabilize within the height bound.
#[must_use]
pub fn lfp_election(sys: &ElectionSystem) -> [Election; MAX_COORDS] {
    let x = elect(sys);
    assert!(x.is_some(), "terminates within the height bound: {sys:?}");
    x.unwrap_or([Election::None; MAX_COORDS])
}

/// The first coordinate of a solved system.
#[must_use]
pub const fn first<T: Copy>(x: [T; MAX_COORDS]) -> T {
    let [a, _, _] = x;
    a
}

/// Deterministic xorshift64 for the randomized twins (no dependencies).
#[derive(Debug)]
pub struct Rng(u64);

impl Rng {
    /// A seeded generator; the seed is part of the test's identity.
    #[must_use]
    pub const fn new(seed: u64) -> Self {
        Self(seed | 1)
    }

    /// Next 64 random bits.
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x.wrapping_shl(13);
        x ^= x.wrapping_shr(7);
        x ^= x.wrapping_shl(17);
        self.0 = x;
        x
    }

    /// A uniform-ish index below `n` (`0` when `n == 0`).
    pub fn below(&mut self, n: usize) -> usize {
        let r = self.next_u64();
        let m = u64::try_from(n).unwrap_or(u64::MAX);
        r.checked_rem(m)
            .and_then(|v| usize::try_from(v).ok())
            .unwrap_or(0)
    }

    /// A random element of a non-empty slice (`dflt` for an empty one).
    pub fn pick<T: Copy>(&mut self, xs: &[T], dflt: T) -> T {
        xs.get(self.below(xs.len())).copied().unwrap_or(dflt)
    }
}

/// The three guard indices the twins range over.
pub const GUARDS: [Guard; 3] = [0, 1, 2];

/// Every pair of cells.
pub fn all_cells() -> impl Iterator<Item = Cells> {
    Transfer::ALL
        .iter()
        .flat_map(|&pos| Transfer::ALL.iter().map(move |&neg| Cells { pos, neg }))
}

/// Every election over [`GUARDS`].
#[must_use]
pub const fn all_elections() -> [Election; 5] {
    [
        Election::None,
        Election::One(0),
        Election::One(1),
        Election::One(2),
        Election::Conflict,
    ]
}

/// Every binding over [`GUARDS`].
#[must_use]
pub fn all_bindings() -> Vec<GuardBinding> {
    let mut out = vec![GuardBinding::Const, GuardBinding::Opaque];
    for &callee in &GUARDS {
        for &caller in &GUARDS {
            out.push(GuardBinding::Id { callee, caller });
            out.push(GuardBinding::Neg { callee, caller });
        }
    }
    out
}

/// The two shapes (the guard index of a split is irrelevant to the algebra).
pub const SHAPES: [Shape; 2] = [Shape::Uncond, Shape::Split(0)];

/// Every edge into a system of `n` coordinates.
#[must_use]
pub fn all_edges(n: usize) -> Vec<Edge> {
    let mut out = Vec::new();
    for callee in 0..n {
        for &transform in &Transform::ALL {
            for &mask in &Mask::ALL {
                out.push(Edge {
                    callee,
                    transform,
                    mask,
                });
            }
        }
    }
    out
}

/// Every coordinate with at most one edge into `n` coordinates.
#[must_use]
pub fn all_coords_one_edge(n: usize) -> Vec<Coord> {
    let mut out = Vec::new();
    let edges = all_edges(n);
    for &shape in &SHAPES {
        for seed in all_cells() {
            out.push(Coord {
                shape,
                seed,
                edges: [None; MAX_EDGES],
            });
            for &e in &edges {
                let mut es = [None; MAX_EDGES];
                if let Some(slot) = es.first_mut() {
                    *slot = Some(e);
                }
                out.push(Coord {
                    shape,
                    seed,
                    edges: es,
                });
            }
        }
    }
    out
}

/// A dead coordinate (index ≥ `n`).
pub const DEAD: Coord = Coord {
    shape: Shape::Uncond,
    seed: Cells::BOT,
    edges: [None; MAX_EDGES],
};

/// Every well-formed system of `n ∈ {1, 2}` coordinates with at most one
/// edge each.
pub fn systems_exhaustive(n: usize) -> impl Iterator<Item = System> {
    let coords = all_coords_one_edge(n);
    let m = coords.len();
    let total = if n == 1 { m } else { m.saturating_mul(m) };
    (0..total).filter_map(move |k| {
        let a = coords
            .get(k.checked_rem(m).unwrap_or(0))
            .copied()
            .unwrap_or(DEAD);
        let b = coords
            .get(k.checked_div(m).unwrap_or(0))
            .copied()
            .unwrap_or(DEAD);
        let sys = System {
            n,
            coords: [a, if n > 1 { b } else { DEAD }, DEAD],
        };
        sys.well_formed().then_some(sys)
    })
}

/// A random well-formed system of `n` coordinates with up to `MAX_EDGES`
/// edges each.
pub fn random_system(rng: &mut Rng, n: usize) -> System {
    let edges = all_edges(n);
    loop {
        let mut coords = [DEAD; MAX_COORDS];
        for c in coords.iter_mut().take(n) {
            let shape = rng.pick(&SHAPES, Shape::Uncond);
            let pos = rng.pick(&Transfer::ALL, Transfer::Bot);
            let neg = rng.pick(&Transfer::ALL, Transfer::Bot);
            let seed = if matches!(shape, Shape::Uncond) {
                Cells::diag(pos)
            } else {
                Cells { pos, neg }
            };
            let mut es = [None; MAX_EDGES];
            for slot in &mut es {
                if rng.below(3) > 0 {
                    let mut e = rng.pick(
                        &edges,
                        Edge {
                            callee: 0,
                            transform: Transform::Opaque,
                            mask: Mask::Both,
                        },
                    );
                    if matches!(shape, Shape::Uncond) {
                        e.mask = Mask::Both;
                        if matches!(e.transform, Transform::Id | Transform::Neg) {
                            e.transform = Transform::Opaque;
                        }
                    }
                    *slot = Some(e);
                }
            }
            *c = Coord {
                shape,
                seed,
                edges: es,
            };
        }
        let sys = System { n, coords };
        if sys.well_formed() {
            return sys;
        }
    }
}

/// A random well-formed election system of `n` coordinates.
pub fn random_election_system(rng: &mut Rng, n: usize) -> ElectionSystem {
    let elections = all_elections();
    let bindings = all_bindings();
    let dead = ElectionCoord {
        seed: Election::None,
        edges: [None; MAX_EDGES],
    };
    let mut coords = [dead; MAX_COORDS];
    for c in coords.iter_mut().take(n) {
        let seed = rng.pick(&elections, Election::None);
        let mut es = [None; MAX_EDGES];
        for slot in &mut es {
            if rng.below(3) > 0 {
                *slot = Some(ElectionEdge {
                    callee: rng.below(n),
                    binding: rng.pick(&bindings, GuardBinding::Opaque),
                });
            }
        }
        *c = ElectionCoord { seed, edges: es };
    }
    ElectionSystem { n, coords }
}

/// Small-width symbolic inputs for the Kani harnesses.
///
/// CBMC bit-blasts every field, so a symbolic `usize` index costs 64 bits
/// where two would do. The harnesses draw `u8` symbols, convert, and assume
/// well-formedness — the kernel types are untouched. The live-coordinate
/// count is concrete (3, or 2 for the "small" systems the whole-solver
/// harnesses use): a smaller SCC is the same thing with unreferenced
/// coordinates, and a symbolic `n` only widens every loop bound.
#[cfg(kani)]
pub mod symbolic {
    use super::DEAD;
    use crate::{
        Cells, Coord, Edge, Election, ElectionCoord, ElectionEdge, ElectionSystem, Guard,
        GuardBinding, Shape, System, MAX_COORDS, MAX_EDGES,
    };

    /// A symbolic index below `n`.
    pub fn any_index(n: usize) -> usize {
        let v: u8 = kani::any();
        kani::assume(usize::from(v) < n);
        usize::from(v)
    }

    /// A guard index below 3.
    fn any_guard() -> Guard {
        let g: Guard = kani::any();
        kani::assume(g < 3);
        g
    }

    fn any_edge(n: usize) -> Option<Edge> {
        let present: bool = kani::any();
        present.then(|| Edge {
            callee: any_index(n),
            transform: kani::any(),
            mask: kani::any(),
        })
    }

    fn any_coord(n: usize, edges: usize) -> Coord {
        let split: bool = kani::any();
        Coord {
            shape: if split {
                Shape::Split(0)
            } else {
                Shape::Uncond
            },
            seed: kani::any(),
            edges: [any_edge(n), if edges > 1 { any_edge(n) } else { None }],
        }
    }

    /// A well-formed system of exactly 3 live coordinates, ≤ 2 edges each.
    pub fn any_system() -> System {
        let n = MAX_COORDS;
        let coords = [any_coord(n, 2), any_coord(n, 2), any_coord(n, 2)];
        let sys = System { n, coords };
        kani::assume(sys.well_formed());
        sys
    }

    /// A well-formed system of 2 live coordinates, ≤ 1 edge each — the
    /// bound at which the whole-solver harnesses stay tractable.
    pub fn any_small_system() -> System {
        let n = 2;
        let coords = [any_coord(n, 1), any_coord(n, 1), DEAD];
        let sys = System { n, coords };
        kani::assume(sys.well_formed());
        sys
    }

    /// A symbolic state whose `Uncond` coordinates are diagonal (K12's
    /// inductive hypothesis).
    pub fn any_state_diagonal_where_uncond(sys: &System) -> [Cells; MAX_COORDS] {
        let x: [Cells; MAX_COORDS] = kani::any();
        for (c, v) in sys.coords.iter().zip(x.iter()) {
            if matches!(c.shape, Shape::Uncond) {
                kani::assume(v.is_diag());
            }
        }
        x
    }

    /// A fair per-pass schedule over `0..n`.
    pub fn any_schedule(n: usize) -> [usize; MAX_COORDS] {
        let s = [any_index(n), any_index(n), any_index(n)];
        kani::assume((0..n).all(|i| s.contains(&i)));
        s
    }

    fn any_election() -> Election {
        match any_index(3) {
            0 => Election::None,
            1 => Election::One(any_guard()),
            _ => Election::Conflict,
        }
    }

    fn any_binding() -> GuardBinding {
        match any_index(4) {
            0 => GuardBinding::Const,
            1 => GuardBinding::Opaque,
            2 => GuardBinding::Id {
                callee: any_guard(),
                caller: any_guard(),
            },
            _ => GuardBinding::Neg {
                callee: any_guard(),
                caller: any_guard(),
            },
        }
    }

    fn any_election_edge(n: usize) -> Option<ElectionEdge> {
        let present: bool = kani::any();
        present.then(|| ElectionEdge {
            callee: any_index(n),
            binding: any_binding(),
        })
    }

    fn any_election_coord(n: usize, edges: usize) -> ElectionCoord {
        ElectionCoord {
            seed: any_election(),
            edges: [
                any_election_edge(n),
                if edges > 1 {
                    any_election_edge(n)
                } else {
                    None
                },
            ],
        }
    }

    /// A well-formed election system of exactly 3 live coordinates.
    pub fn any_election_system() -> ElectionSystem {
        let n = MAX_COORDS;
        let coords = [
            any_election_coord(n, 2),
            any_election_coord(n, 2),
            any_election_coord(n, 2),
        ];
        let sys = ElectionSystem { n, coords };
        kani::assume(sys.well_formed());
        sys
    }

    /// A well-formed election system of 2 live coordinates, ≤ 1 edge each.
    pub fn any_small_election_system() -> ElectionSystem {
        let n = 2;
        let dead = ElectionCoord {
            seed: Election::None,
            edges: [None; MAX_EDGES],
        };
        let coords = [any_election_coord(n, 1), any_election_coord(n, 1), dead];
        let sys = ElectionSystem { n, coords };
        kani::assume(sys.well_formed());
        sys
    }
}

/// All permutations of `0..n` for `n ≤ 3`.
#[must_use]
pub fn permutations(n: usize) -> Vec<Vec<usize>> {
    match n {
        0 => vec![vec![]],
        1 => vec![vec![0]],
        2 => vec![vec![0, 1], vec![1, 0]],
        _ => vec![
            vec![0, 1, 2],
            vec![0, 2, 1],
            vec![1, 0, 2],
            vec![1, 2, 0],
            vec![2, 0, 1],
            vec![2, 1, 0],
        ],
    }
}
