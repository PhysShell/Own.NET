//! P-037 guarded-transfer kernel — the pure algebra of
//! `docs/proposals/P-037-guarded-effect-summaries.md`, and nothing else.
//!
//! What is here: the base transfer lattice (INF-L1/L2), the product cells
//! (G-L2), the flat election lattice and its import map (G-S1), the five edge
//! transforms with the G-S4 branch mask (G-S5/G-F2), collapse and finalization
//! (G-T2/G-L4), a bounded Jacobi/chaotic least-fixpoint solver (G-F1),
//! call-site application (G-A1/G-A2), and the two "today" models P-037 §7
//! argues against: the collapsed system of §7.2 and today's derivation
//! conservatisms exactly as `ownlang/ownir.py::_build_skeletons` states them.
//!
//! What is NOT here, by design — the trusted-input boundary of the A0 spike:
//! Roslyn, CFGs, guard eligibility (G-V4), cell-local definite-release facts
//! (G-S2/G-S3), diagnostics, SARIF. The kernel assumes honest primitive facts
//! and is checked to never turn them into a fabricated `must`.
//!
//! Every function is total, allocation-free and finite-domain, so a Kani
//! harness explores it symbolically and a plain test enumerates it
//! exhaustively. Both live under `properties/` and call THESE functions — a
//! production kernel (A1) reuses them; it never re-implements them.
//!
//! This crate is not a member of the `rust/` core workspace and is wired to
//! nothing: it changes no verdict and is not a P-037 implementation (§10 of
//! the proposal keeps that post-cutover).
#![forbid(unsafe_code)]

#[cfg(any(test, kani))]
pub mod properties;

/// Coordinates (method, disposable parameter) in one bounded SCC.
pub const MAX_COORDS: usize = 3;
/// Forward edges per coordinate.
pub const MAX_EDGES: usize = 2;

// ---------------------------------------------------------------------------
// INF-L1/L2 — the base transfer lattice
// ---------------------------------------------------------------------------

/// `⊥ < no | must < may < unknown`; `no` and `must` are incomparable (G-L3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Transfer {
    /// Seed-only (INF-L2); never escapes a finalized summary.
    Bot,
    /// Kept on every path.
    No,
    /// Transferred on every normal-return path.
    Must,
    /// Transferred on some paths, kept on others.
    May,
    /// Insufficient evidence — absorbing under join.
    Unknown,
}

impl Transfer {
    /// Every element, for exhaustive twins.
    pub const ALL: [Self; 5] = [Self::Bot, Self::No, Self::Must, Self::May, Self::Unknown];

    /// INF-L1/L2: `⊥` is the identity, `unknown` absorbs, equal stays, any
    /// other mix of distinct values is `may`.
    #[must_use]
    pub const fn join(self, other: Self) -> Self {
        match (self, other) {
            (Self::Bot, x) | (x, Self::Bot) => x,
            (Self::Unknown, _) | (_, Self::Unknown) => Self::Unknown,
            (Self::No, Self::No) => Self::No,
            (Self::Must, Self::Must) => Self::Must,
            _ => Self::May,
        }
    }

    /// The lattice order induced by the join.
    #[must_use]
    pub fn leq(self, other: Self) -> bool {
        self.join(other) == other
    }

    /// G-L4 / INF-L2: a residual `⊥` finalizes as `no`.
    #[must_use]
    pub const fn fin(self) -> Self {
        match self {
            Self::Bot => Self::No,
            t => t,
        }
    }
}

/// What the bounded solver needs from a domain.
pub trait Lattice: Copy + Eq + core::fmt::Debug {
    /// The seed.
    const BOT: Self;
    /// Length of the longest strictly ascending chain, minus one (G-L3).
    const HEIGHT: usize;
    /// Least upper bound.
    #[must_use]
    fn join(self, other: Self) -> Self;
    /// The induced order.
    fn leq(self, other: Self) -> bool {
        self.join(other) == other
    }
}

impl Lattice for Transfer {
    const BOT: Self = Self::Bot;
    const HEIGHT: usize = 3;
    fn join(self, other: Self) -> Self {
        Self::join(self, other)
    }
}

// ---------------------------------------------------------------------------
// G-L2 — the product cells of an elected coordinate
// ---------------------------------------------------------------------------

/// `Split(g, pos, neg)` as its two cells; an `Uncond(t)` coordinate is the
/// diagonal `(t, t)` (the read-only embedding of §3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct Cells {
    /// The transfer when the guard's positive side holds.
    pub pos: Transfer,
    /// The transfer when the guard's negative side holds.
    pub neg: Transfer,
}

impl Cells {
    /// Both cells `⊥`.
    pub const BOT: Self = Self {
        pos: Transfer::Bot,
        neg: Transfer::Bot,
    };

    /// `Uncond(t)` embedded as `(t, t)`.
    #[must_use]
    pub const fn diag(t: Transfer) -> Self {
        Self { pos: t, neg: t }
    }

    /// Cellwise INF-L1 join (G-L2).
    #[must_use]
    pub const fn join(self, other: Self) -> Self {
        Self {
            pos: self.pos.join(other.pos),
            neg: self.neg.join(other.neg),
        }
    }

    /// The product order.
    #[must_use]
    pub fn leq(self, other: Self) -> bool {
        self.pos.leq(other.pos) && self.neg.leq(other.neg)
    }

    /// Cellwise finalization (G-L4).
    #[must_use]
    pub const fn fin(self) -> Self {
        Self {
            pos: self.pos.fin(),
            neg: self.neg.fin(),
        }
    }

    /// G-T2 collapse: `C(Split(g, a, b)) = join(a, b)`; on a diagonal,
    /// `C(Uncond(t)) = t`.
    #[must_use]
    pub const fn collapse(self) -> Transfer {
        self.pos.join(self.neg)
    }

    /// The `neg` transform's cell swap.
    #[must_use]
    pub const fn swap(self) -> Self {
        Self {
            pos: self.neg,
            neg: self.pos,
        }
    }

    /// Whether this is an `Uncond` embedding.
    #[must_use]
    pub fn is_diag(self) -> bool {
        self.pos == self.neg
    }
}

impl Lattice for Cells {
    const BOT: Self = Self::BOT;
    const HEIGHT: usize = 6;
    fn join(self, other: Self) -> Self {
        Self::join(self, other)
    }
}

// ---------------------------------------------------------------------------
// G-S1 — the flat election lattice and the import map
// ---------------------------------------------------------------------------

/// A guard variable of the method being summarized (G-V1), by index.
pub type Guard = u8;

/// `None ⊑ One(g) ⊑ Conflict`; distinct `One(g)` / `One(h)` incomparable.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Election {
    /// No guard literal elected.
    None,
    /// Exactly one guard variable elected.
    One(Guard),
    /// Two distinct variables met: the coordinate stays `Uncond`.
    Conflict,
}

impl Election {
    /// The G-S1 election join.
    #[must_use]
    pub const fn join(self, other: Self) -> Self {
        match (self, other) {
            (Self::None, x) | (x, Self::None) => x,
            (Self::Conflict, _) | (_, Self::Conflict) => Self::Conflict,
            (Self::One(g), Self::One(h)) => {
                if g == h {
                    Self::One(g)
                } else {
                    Self::Conflict
                }
            }
        }
    }

    /// The induced order.
    #[must_use]
    pub fn leq(self, other: Self) -> bool {
        self.join(other) == other
    }
}

impl Lattice for Election {
    const BOT: Self = Self::None;
    const HEIGHT: usize = 2;
    fn join(self, other: Self) -> Self {
        Self::join(self, other)
    }
}

/// How a call binds the callee's guard parameter (G-S1 stage 2, G-S5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum GuardBinding {
    /// The callee's guard `callee` receives the caller's stable guard `caller`.
    Id {
        /// The callee's guard parameter.
        callee: Guard,
        /// The caller's own guard variable.
        caller: Guard,
    },
    /// The callee's guard `callee` receives `!caller`.
    Neg {
        /// The callee's guard parameter.
        callee: Guard,
        /// The caller's own guard variable.
        caller: Guard,
    },
    /// A literal argument.
    Const,
    /// Anything else, including a mutated or by-ref-exposed guard (G-V4).
    Opaque,
}

/// G-S1 stage 2: the import of a callee's election into the caller through
/// one call.
///
/// `None → None`; `One(h) → One(g)` when `h` is exactly the guard parameter
/// bound from the caller's `g` by an `id`/`neg` binding, else `None`;
/// `Conflict → Conflict`.
#[must_use]
pub const fn import(callee: Election, binding: GuardBinding) -> Election {
    match callee {
        Election::None => Election::None,
        Election::Conflict => Election::Conflict,
        Election::One(h) => match binding {
            GuardBinding::Id { callee: c, caller } | GuardBinding::Neg { callee: c, caller }
                if c == h =>
            {
                Election::One(caller)
            }
            _ => Election::None,
        },
    }
}

/// The domain election types for a coordinate (§3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Shape {
    /// Plain `Transfer`, kept as a diagonal pair.
    Uncond,
    /// `Transfer × Transfer` over the elected guard.
    Split(Guard),
}

/// `One(g)` → `Split(g)`; `None` / `Conflict` → `Uncond`.
#[must_use]
pub const fn shape_of(e: Election) -> Shape {
    match e {
        Election::One(g) => Shape::Split(g),
        Election::None | Election::Conflict => Shape::Uncond,
    }
}

// ---------------------------------------------------------------------------
// G-S5 / G-F2 / G-S4 — edge transforms and the branch mask
// ---------------------------------------------------------------------------

/// The five edge transforms (G-S5) — the entire guard-propagation story.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Transform {
    /// A literal `true` / non-null argument: read the callee's positive cell.
    ConstPos,
    /// A literal `false` / `null` argument: read the negative cell.
    ConstNeg,
    /// The caller's own stable guard passed through.
    Id,
    /// Passed through negated.
    Neg,
    /// Anything else: read the join of the callee's cells (today's read).
    Opaque,
}

impl Transform {
    /// Every transform, for exhaustive twins.
    pub const ALL: [Self; 5] = [
        Self::ConstPos,
        Self::ConstNeg,
        Self::Id,
        Self::Neg,
        Self::Opaque,
    ];
}

/// G-F2: read a callee's cells through an edge transform, as the pair
/// delivered to the caller's (positive, negative) cells.
#[must_use]
pub const fn read(t: Transform, callee: Cells) -> Cells {
    match t {
        Transform::ConstPos => Cells::diag(callee.pos),
        Transform::ConstNeg => Cells::diag(callee.neg),
        Transform::Id => callee,
        Transform::Neg => callee.swap(),
        Transform::Opaque => Cells::diag(callee.collapse()),
    }
}

/// G-S4: which of the caller's cells a forward contributes to — the cell
/// whose literal governs the forward, or both when it is unguarded.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Mask {
    /// An unguarded forward contributes to both cells.
    Both,
    /// A forward under the positive literal.
    PosOnly,
    /// A forward under the negative literal.
    NegOnly,
}

impl Mask {
    /// Every mask, for exhaustive twins.
    pub const ALL: [Self; 3] = [Self::Both, Self::PosOnly, Self::NegOnly];
}

/// G-S4 applied to a G-F2 read.
#[must_use]
pub const fn contribute(m: Mask, r: Cells) -> Cells {
    match m {
        Mask::Both => r,
        Mask::PosOnly => Cells {
            pos: r.pos,
            neg: Transfer::Bot,
        },
        Mask::NegOnly => Cells {
            pos: Transfer::Bot,
            neg: r.neg,
        },
    }
}

// ---------------------------------------------------------------------------
// G-F1 — one bounded SCC as a system of coordinates
// ---------------------------------------------------------------------------

/// A forward edge of a coordinate.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct Edge {
    /// The callee coordinate (index into the system).
    pub callee: usize,
    /// The G-S5 transform on the edge.
    pub transform: Transform,
    /// The G-S4 branch mask of the forward.
    pub mask: Mask,
}

/// One `(method, parameter)` coordinate after election.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct Coord {
    /// The domain election typed.
    pub shape: Shape,
    /// The cell-local facts (G-S2/G-S3): `must` a definite release in the
    /// cell, `no` a kept path, `may` a release behind a second condition,
    /// `⊥` nothing local (edges only). TRUSTED INPUT.
    pub seed: Cells,
    /// Forward edges.
    pub edges: [Option<Edge>; MAX_EDGES],
}

/// A bounded SCC.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct System {
    /// Live coordinates: indices `0..n`.
    pub n: usize,
    /// The coordinates.
    pub coords: [Coord; MAX_COORDS],
}

impl System {
    /// The frontend's guarantees (G-L1, G-S5, G-V4 boundary): every edge
    /// targets a live coordinate; an `Uncond` coordinate has a diagonal seed,
    /// `Both` masks and no `id`/`neg` edge; an `id`/`neg` edge joins two
    /// `Split` coordinates.
    // plain loops for the model checker (this runs under every `assume`)
    #[allow(clippy::manual_flatten)]
    #[must_use]
    pub fn well_formed(&self) -> bool {
        if self.n > MAX_COORDS {
            return false;
        }
        for (i, c) in self.coords.iter().enumerate() {
            if i >= self.n {
                break;
            }
            let uncond = matches!(c.shape, Shape::Uncond);
            if uncond && !c.seed.is_diag() {
                return false;
            }
            for slot in &c.edges {
                if let Some(e) = slot {
                    let through_guard = matches!(e.transform, Transform::Id | Transform::Neg);
                    let callee_split = self
                        .coords
                        .get(e.callee)
                        .copied()
                        .is_some_and(|k| matches!(k.shape, Shape::Split(_)));
                    if e.callee >= self.n
                        || (uncond && (!matches!(e.mask, Mask::Both) || through_guard))
                        || (through_guard && !callee_split)
                    {
                        return false;
                    }
                }
            }
        }
        true
    }

    /// `F_G` at one coordinate: seed joined with every masked, transformed
    /// edge read (G-F1/G-F2/G-S4). Dead coordinates stay `⊥`.
    // plain loops, no iterator adapters: the model checker unrolls these and
    // `flatten` costs it an order of magnitude
    #[allow(clippy::manual_flatten)]
    #[must_use]
    pub fn step(&self, i: usize, x: &[Cells; MAX_COORDS]) -> Cells {
        if i >= self.n {
            return Cells::BOT;
        }
        // by value: a reference at a symbolic index is a symbolic-offset
        // pointer for the model checker, and every field read through it
        // costs a case split; a copy of a small Copy struct is one array read
        let Some(c) = self.coords.get(i).copied() else {
            return Cells::BOT;
        };
        let mut acc = c.seed;
        for slot in &c.edges {
            if let Some(e) = slot {
                let callee = x.get(e.callee).copied().unwrap_or(Cells::BOT);
                acc = acc.join(contribute(e.mask, read(e.transform, callee)));
            }
        }
        acc
    }

    /// `F_0` of G-T2 §7.2: the same SCC with every coordinate `Uncond`, its
    /// seed collapsed and every edge read as the join of the callee's cells
    /// with no branch mask — the pure-lattice "today".
    #[must_use]
    pub fn collapsed(&self) -> Self {
        // by-value maps, no mutable references: the model checker sees pure
        // functions of the coordinate instead of pointer updates
        let coords = self.coords.map(|c| Coord {
            shape: Shape::Uncond,
            seed: Cells::diag(c.seed.collapse()),
            edges: c.edges.map(|slot| {
                slot.map(|e| Edge {
                    callee: e.callee,
                    transform: Transform::Opaque,
                    mask: Mask::Both,
                })
            }),
        });
        Self { n: self.n, coords }
    }

    /// Today's `_build_skeletons` read of the same bodies, as P-037 §7.1
    /// states it and `ownlang/ownir.py` implements it (REPOSITORY FACT,
    /// the `if rel:` / `elif passed:` ladder): a local release has priority —
    /// definite on every path ⇒ `dispose`, partial ⇒ `[dispose, borrow]` —
    /// and its forwards are never processed; without a local release the
    /// forwards are read (join of cells), and a conditional / multi-target
    /// handoff adds a synthetic `borrow`. Cell seeds: `must`/`may` = a local
    /// release in that cell, `no` = a kept path, `⊥` = nothing local.
    #[must_use]
    pub fn today(&self) -> Self {
        let collapsed = self.collapsed();
        let [g0, g1, g2] = self.coords;
        let [t0, t1, t2] = collapsed.coords;
        Self {
            n: self.n,
            coords: [
                Self::today_coord(g0, t0),
                Self::today_coord(g1, t1),
                Self::today_coord(g2, t2),
            ],
        }
    }

    /// One coordinate of [`Self::today`]: `g` is the guarded coordinate, `t`
    /// its collapsed form.
    #[allow(clippy::manual_flatten)]
    fn today_coord(g: Coord, t: Coord) -> Coord {
        let released = |x: Transfer| matches!(x, Transfer::Must | Transfer::May);
        if released(g.seed.pos) || released(g.seed.neg) {
            let definite = g.seed.pos == Transfer::Must && g.seed.neg == Transfer::Must;
            let seed = Cells::diag(if definite {
                Transfer::Must
            } else {
                Transfer::May
            });
            return Coord {
                shape: t.shape,
                seed,
                edges: [None; MAX_EDGES],
            };
        }
        let mut count = 0_usize;
        let mut conditional = false;
        for slot in &g.edges {
            if let Some(e) = slot {
                count = count.saturating_add(1);
                conditional |= !matches!(e.mask, Mask::Both);
            }
        }
        let seed = if count > 0 && (count > 1 || conditional) {
            t.seed.join(Cells::diag(Transfer::No))
        } else {
            t.seed
        };
        Coord {
            shape: t.shape,
            seed,
            edges: t.edges,
        }
    }
}

// ---------------------------------------------------------------------------
// The bounded least-fixpoint solver (G-F1, INF-F3)
// ---------------------------------------------------------------------------

/// Passes after which a strictly ascending chaotic iteration must have
/// stabilized: every pass that changes anything raises at least one
/// coordinate, and a coordinate can rise `HEIGHT` times.
#[must_use]
pub const fn max_passes(height: usize) -> usize {
    MAX_COORDS.saturating_mul(height).saturating_add(1)
}

/// Synchronous (Jacobi) iteration from `⊥`; `None` if the bound is exceeded
/// (impossible for a monotone step — asserted by the harnesses).
// index loops keep the model checker's unrolling simple; the pedantic hint
// to use iterator adapters would cost CBMC an order of magnitude
#[allow(clippy::needless_range_loop)]
pub fn lfp_jacobi<L: Lattice>(
    n: usize,
    step: impl Fn(usize, &[L; MAX_COORDS]) -> L,
) -> Option<[L; MAX_COORDS]> {
    let mut x = [L::BOT; MAX_COORDS];
    for _ in 0..max_passes(L::HEIGHT) {
        let mut next = [L::BOT; MAX_COORDS];
        for i in 0..MAX_COORDS {
            let Some(slot) = next.get_mut(i) else {
                continue;
            };
            if i < n {
                *slot = step(i, &x);
            }
        }
        if next == x {
            return Some(x);
        }
        x = next;
    }
    None
}

/// Chaotic (Gauss–Seidel) iteration from `⊥` in the given per-pass order,
/// each update reading the latest values; repeated until a pass changes
/// nothing. Order-independence of the result is property K10.
pub fn lfp_chaotic<L: Lattice>(
    n: usize,
    step: impl Fn(usize, &[L; MAX_COORDS]) -> L,
    schedule: &[usize],
) -> Option<[L; MAX_COORDS]> {
    let mut x = [L::BOT; MAX_COORDS];
    for _ in 0..max_passes(L::HEIGHT) {
        let mut changed = false;
        for &i in schedule {
            if i >= n {
                continue;
            }
            let v = step(i, &x);
            if let Some(slot) = x.get_mut(i) {
                if *slot != v {
                    *slot = v;
                    changed = true;
                }
            }
        }
        if !changed {
            return Some(x);
        }
    }
    None
}

/// The guarded lfp of a system (Jacobi).
#[must_use]
pub fn solve(sys: &System) -> Option<[Cells; MAX_COORDS]> {
    lfp_jacobi(sys.n, |i, x| sys.step(i, x))
}

/// The guarded lfp of a system under a chaotic schedule.
#[must_use]
pub fn solve_with(sys: &System, schedule: &[usize]) -> Option<[Cells; MAX_COORDS]> {
    lfp_chaotic(sys.n, |i, x| sys.step(i, x), schedule)
}

// ---------------------------------------------------------------------------
// G-S1 — the election pre-solver as its own system
// ---------------------------------------------------------------------------

/// An import edge of the election fixpoint.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct ElectionEdge {
    /// The callee coordinate.
    pub callee: usize,
    /// The guard binding at that call.
    pub binding: GuardBinding,
}

/// One coordinate of the election fixpoint.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct ElectionCoord {
    /// Stage 1: the own-body seed (join of the governing literals).
    pub seed: Election,
    /// Stage 2: the import edges.
    pub edges: [Option<ElectionEdge>; MAX_EDGES],
}

/// The election pre-solver's SCC.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub struct ElectionSystem {
    /// Live coordinates.
    pub n: usize,
    /// The coordinates.
    pub coords: [ElectionCoord; MAX_COORDS],
}

impl ElectionSystem {
    /// Every edge targets a live coordinate.
    #[allow(clippy::manual_flatten)]
    #[must_use]
    pub fn well_formed(&self) -> bool {
        if self.n > MAX_COORDS {
            return false;
        }
        for (i, c) in self.coords.iter().enumerate() {
            if i >= self.n {
                break;
            }
            for slot in &c.edges {
                if let Some(e) = slot {
                    if e.callee >= self.n {
                        return false;
                    }
                }
            }
        }
        true
    }

    /// Seed joined with every import (G-S1).
    // plain loops for the model checker, as in `System::step`
    #[allow(clippy::manual_flatten)]
    #[must_use]
    pub fn step(&self, i: usize, x: &[Election; MAX_COORDS]) -> Election {
        if i >= self.n {
            return Election::None;
        }
        let Some(c) = self.coords.get(i).copied() else {
            return Election::None;
        };
        let mut acc = c.seed;
        for slot in &c.edges {
            if let Some(e) = slot {
                let callee = x.get(e.callee).copied().unwrap_or(Election::None);
                acc = acc.join(import(callee, e.binding));
            }
        }
        acc
    }
}

/// The election lfp (Jacobi).
#[must_use]
pub fn elect(sys: &ElectionSystem) -> Option<[Election; MAX_COORDS]> {
    lfp_jacobi(sys.n, |i, x| sys.step(i, x))
}

/// The election lfp under a chaotic schedule.
#[must_use]
pub fn elect_with(sys: &ElectionSystem, schedule: &[usize]) -> Option<[Election; MAX_COORDS]> {
    lfp_chaotic(sys.n, |i, x| sys.step(i, x), schedule)
}

// ---------------------------------------------------------------------------
// G-A1 / G-A2 — application at the call site
// ---------------------------------------------------------------------------

/// G-A1's static test at one call site.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Selection {
    /// The argument bound to `g` is `true` / provably non-null.
    Pos,
    /// The argument is `false` / `null`.
    Neg,
    /// Anything else: lower the collapse.
    Unselected,
}

impl Selection {
    /// Every selection, for exhaustive twins.
    pub const ALL: [Self; 3] = [Self::Pos, Self::Neg, Self::Unselected];
}

/// INF-A1's lowered effect. `Plain` carries the OWN051 advisory exactly when
/// lowering degraded (G-A5) — the value `may`/`unknown` is the degradation.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Lowered {
    /// `must → consume`.
    Consume,
    /// `no → borrow`: the obligation stays with the caller (G-A3).
    Borrow,
    /// `may` / `unknown → plain` (+ OWN051).
    Plain,
}

/// INF-A1 on a finalized value. A raw `⊥` is finalized first (G-L4) — the
/// lowering never trusts an unfinalized cell.
#[must_use]
pub const fn lower(t: Transfer) -> Lowered {
    match t.fin() {
        Transfer::Must => Lowered::Consume,
        Transfer::No => Lowered::Borrow,
        Transfer::May | Transfer::Unknown | Transfer::Bot => Lowered::Plain,
    }
}

/// G-A1/G-A2: select a cell when the static test allows it, otherwise lower
/// the collapse; an `Uncond` coordinate has nothing to select on.
#[must_use]
pub const fn apply(shape: Shape, solved: Cells, sel: Selection) -> Lowered {
    let c = solved.fin();
    match (shape, sel) {
        (Shape::Split(_), Selection::Pos) => lower(c.pos),
        (Shape::Split(_), Selection::Neg) => lower(c.neg),
        (Shape::Split(_), Selection::Unselected) | (Shape::Uncond, _) => lower(c.collapse()),
    }
}

// ---------------------------------------------------------------------------
// G-T2 §7.3 — the residual-⊥ lemma's three groundings, as stated
// ---------------------------------------------------------------------------

/// When one cell is `⊥` at the lfp (every contribution an ungrounded
/// same-SCC forward), what grounds the OTHER cell.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(kani, derive(kani::Arbitrary))]
pub enum Grounding {
    /// A local release on the other side (`must`, or `may` behind a second
    /// condition); today: release priority ⇒ `[dispose, borrow]`.
    PartialLocalRelease(Transfer),
    /// A grounded forward on the other side reading this value; today:
    /// `[forward, forward(ungrounded), borrow]`.
    GroundedForward(Transfer),
    /// No grounding anywhere; today's solve is residual-`⊥` too.
    Ungrounded,
}

/// The guarded lfp cells of the lemma's shapes: `(other, ⊥)`.
#[must_use]
pub const fn lemma_guarded(g: Grounding) -> Cells {
    match g {
        Grounding::PartialLocalRelease(t) | Grounding::GroundedForward(t) => Cells {
            pos: t,
            neg: Transfer::Bot,
        },
        Grounding::Ungrounded => Cells::BOT,
    }
}

/// Today's solved value for the same shapes, as P-037 §7.3 states it.
#[must_use]
pub const fn lemma_today(g: Grounding) -> Transfer {
    match g {
        Grounding::PartialLocalRelease(_) => Transfer::May,
        Grounding::GroundedForward(t) => t.join(Transfer::No),
        Grounding::Ungrounded => Transfer::Bot,
    }
}
