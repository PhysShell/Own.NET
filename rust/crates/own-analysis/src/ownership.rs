//! The ownership analysis — an exact port of `ownlang/analysis.py` (the flow-
//! sensitive loans + permissions model), built on the generic [`solver`].
//!
//! Parity contract (#214 checkpoint 2): `(line, code)` on the `check` surface.
//! Message text, the evidence slice, subject/`resource_kind` and SARIF are later
//! steps and are deliberately not reproduced here (the diagnostic still carries a
//! human-readable title as its message so it is never blank).
//!
//! RID semantics map directly: Python keys resource state on `id(sym)`; here a
//! RID is the resource's [`SymId`] (`u32`), minted deterministically by `own-cfg`
//! (whose symbol table is itself pinned byte-for-byte by the CFG-JSON oracle), so
//! the whole aliasing/loan structure is reproduced without object identity.
//!
//! [`solver`]: crate::solver

use std::collections::{BTreeMap, BTreeSet};

use own_cfg::{Cfg, Instr, Kind, SymId};
use own_diagnostics::{title, Diagnostic};
use own_syntax::ast::Effect;

use crate::solver::{solve, Analysis, ControlFlowGraph, Lattice};

// Per-resource variable-state, as a bitset over `{OWNED, MOVED, RELEASED,
// ESCAPED}` (the P-022 `u8`-bitflags lattice; Python's `set[VarState]`).
const OWNED: u8 = 1;
const MOVED: u8 = 2;
const RELEASED: u8 = 4;
const ESCAPED: u8 = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LoanKind {
    Shared,
    Mut,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Loan {
    /// The owner's RID — so the loan is seen through every owning alias.
    owner: u32,
    kind: LoanKind,
}

/// The dataflow fact: per-RID variable-states, active loans, the handle→RID
/// aliasing map, and move/acquire provenance. A faithful port of `analysis.State`.
#[derive(Debug, Clone, PartialEq, Eq)]
struct State {
    /// RID → variable-state bitset. **Absent key reads as `OWNED`** (Python
    /// `st.var.get(rid, {OWNED})`); at a **join**, an absent key contributes the
    /// empty set (Python `a.var.get(k, set())`).
    var: BTreeMap<u32, u8>,
    /// Binding-RID → loan (keyed by the borrow binding's id).
    loans: BTreeMap<u32, Loan>,
    /// Handle id → RID (aliasing; default 1:1, i.e. a handle denotes itself).
    handle_rid: BTreeMap<u32, u32>,
    /// RID → (line, exact) move-site provenance (OWN005 evidence only).
    moved_at: BTreeMap<u32, (u32, bool)>,
    /// RID → (line, exact) acquire-site provenance (OWN001 evidence only).
    acquired_at: BTreeMap<u32, (u32, bool)>,
}

impl State {
    fn rid_of(&self, sym: SymId) -> u32 {
        self.handle_rid.get(&sym.0).copied().unwrap_or(sym.0)
    }

    fn mint(&mut self, sym: SymId) -> u32 {
        self.handle_rid.insert(sym.0, sym.0);
        sym.0
    }

    /// The variable-state of `rid` on read — **defaults to `OWNED`** when absent.
    fn states(&self, rid: u32) -> u8 {
        self.var.get(&rid).copied().unwrap_or(OWNED)
    }
}

/// Merge two RID→(line, exact) provenance maps (`analysis._join_sites`): agree on
/// a line ⇒ keep it, `exact` AND-ed; disagree ⇒ keep the earliest line, inexact.
fn join_sites(out: &mut BTreeMap<u32, (u32, bool)>, other: &BTreeMap<u32, (u32, bool)>) {
    for (&rid, &(line_b, exact_b)) in other {
        match out.get(&rid).copied() {
            Some((line_a, exact_a)) => {
                let merged = if line_a == line_b {
                    (line_a, exact_a && exact_b)
                } else {
                    (line_a.min(line_b), false)
                };
                out.insert(rid, merged);
            }
            None => {
                out.insert(rid, (line_b, exact_b));
            }
        }
    }
}

impl Lattice for State {
    fn bottom() -> Self {
        Self {
            var: BTreeMap::new(),
            loans: BTreeMap::new(),
            handle_rid: BTreeMap::new(),
            moved_at: BTreeMap::new(),
            acquired_at: BTreeMap::new(),
        }
    }

    fn join(&mut self, other: &Self) -> bool {
        let before = self.clone();

        // var: union of the per-RID bitsets; absent key contributes ∅ (0).
        let keys: BTreeSet<u32> = self.var.keys().chain(other.var.keys()).copied().collect();
        for k in keys {
            let merged =
                self.var.get(&k).copied().unwrap_or(0) | other.var.get(&k).copied().unwrap_or(0);
            self.var.insert(k, merged);
        }

        // Block-scoped borrows ⇒ identical active loans on both predecessors
        // (holds across loop back-edges: a borrow closes within its own scope).
        // Locked as an invariant, exactly like the Python `join`.
        let self_keys: BTreeSet<u32> = self.loans.keys().copied().collect();
        let other_keys: BTreeSet<u32> = other.loans.keys().copied().collect();
        assert!(
            self_keys == other_keys,
            "active loans differ at a control-flow merge; impossible for \
             block-scoped borrows (they close within the scope that opened them)"
        );

        // handle_rid: union; a handle must map to the same RID on both paths
        // (the step-0 1:1 invariant), asserted rather than silently picking a side.
        for (&handle, &rid) in &other.handle_rid {
            match self.handle_rid.get(&handle).copied() {
                Some(existing) => assert!(
                    existing == rid,
                    "a handle maps to two different RIDs at a merge (1:1 invariant broken)"
                ),
                None => {
                    self.handle_rid.insert(handle, rid);
                }
            }
        }

        join_sites(&mut self.moved_at, &other.moved_at);
        join_sites(&mut self.acquired_at, &other.acquired_at);

        *self != before
    }
}

/// A collector that emits diagnostics in phase 2 and is a no-op during the silent
/// fixpoint (phase 1) — the port of `_Analyzer.silent`.
enum Emit<'a> {
    Silent,
    Collect(&'a mut Vec<Diagnostic>),
}

impl Emit<'_> {
    fn push(&mut self, code: &'static str, line: u32) {
        if let Self::Collect(sink) = self {
            // Every `code` is a compile-time TITLES constant, so `new` cannot
            // fail; the title doubles as a non-blank human message (message-text
            // parity is a later step and is not compared now).
            let msg = title(code).unwrap_or(code);
            match Diagnostic::new(code, msg, line) {
                Ok(d) => sink.push(d),
                Err(_) => debug_assert!(false, "own-analysis emitted an unknown code {code}"),
            }
        }
    }
}

// -- loan / permission helpers (port of the `self`-less `_Analyzer` methods) --

/// Loans on `owner`'s RID: `(shared_count, has_mut)`. A loan is keyed by the
/// owner's RID, so a borrow of one owning alias is seen through all aliases.
fn loans_on(st: &State, owner: SymId) -> (u32, bool) {
    let owner_rid = st.rid_of(owner);
    let mut shared: u32 = 0;
    let mut mutable = false;
    for ln in st.loans.values() {
        if ln.owner == owner_rid {
            match ln.kind {
                LoanKind::Shared => shared = shared.saturating_add(1),
                LoanKind::Mut => mutable = true,
            }
        }
    }
    (shared, mutable)
}

/// The shared gone / maybe-gone classification (`_state_problem`); returns
/// whether a problem was reported for an operation on owned symbol `sym`.
///
/// Note: the "consumed" and "released" cases both emit OWN002 (only the message
/// differs in Python, and message text is not part of the checkpoint-2 contract).
fn state_problem(st: &State, sym: SymId, emit: &mut Emit<'_>, line: u32) -> bool {
    let s = st.states(st.rid_of(sym));
    if s & OWNED == 0 {
        if s & MOVED != 0 {
            emit.push("OWN005", line);
        } else {
            emit.push("OWN002", line);
        }
        return true;
    }
    if s & (RELEASED | ESCAPED) != 0 {
        emit.push("OWN009", line);
        return true;
    }
    if s & MOVED != 0 {
        emit.push("OWN010", line);
        return true;
    }
    false
}

/// move / consume: needs Own permission (no loans).
fn consume_like(
    st: &State,
    sym: SymId,
    emit: &mut Emit<'_>,
    line: u32,
    code_borrowed: &'static str,
) {
    if state_problem(st, sym, emit, line) {
        return;
    }
    let (shared, mutable) = loans_on(st, sym);
    if shared > 0 || mutable {
        emit.push(code_borrowed, line);
    }
}

fn check_mut_borrowable(st: &State, owner: SymId, emit: &mut Emit<'_>, line: u32) {
    if state_problem(st, owner, emit, line) {
        return;
    }
    let (shared, mutable) = loans_on(st, owner);
    if shared > 0 {
        emit.push("OWN006", line);
    } else if mutable {
        emit.push("OWN011", line);
    }
}

fn check_shared_borrowable(st: &State, owner: SymId, emit: &mut Emit<'_>, line: u32) {
    if state_problem(st, owner, emit, line) {
        return;
    }
    let (_shared, mutable) = loans_on(st, owner);
    if mutable {
        emit.push("OWN012", line);
    }
}

/// Report every RID still `OWNED` in `st` as a leak (OWN001), excluding a
/// returned resource. Port of `_Analyzer.leak_check`.
fn leak_check(st: &State, at_line: u32, emit: &mut Emit<'_>, exclude: Option<u32>) {
    for (&rid, &states) in &st.var {
        if Some(rid) == exclude {
            continue;
        }
        if states & OWNED != 0 {
            emit.push("OWN001", at_line);
        }
    }
}

/// The ownership analyzer over one function's CFG. Implements both the solver's
/// [`ControlFlowGraph`] (from the CFG shape) and [`Analysis`] (the silent
/// transfer that converges the in-states).
struct Ownership<'a> {
    cfg: &'a Cfg,
    /// Per-block successor ids as `usize` (the solver's graph view).
    succ: Vec<Vec<usize>>,
}

impl<'a> Ownership<'a> {
    fn new(cfg: &'a Cfg) -> Self {
        let succ = cfg
            .blocks
            .iter()
            .map(|b| b.succ.iter().map(|s| s.0 as usize).collect())
            .collect();
        Self { cfg, succ }
    }

    fn initial_state(&self) -> State {
        let mut s = State::bottom();
        for &pid in &self.cfg.params {
            if self.cfg.symbol(pid).kind == Kind::Owned {
                let rid = s.mint(pid);
                s.var.insert(rid, OWNED);
            }
        }
        s
    }

    // -- loan / permission helpers (the `self`-less ones are free fns below) --

    fn binding_live(&self, st: &State, sym: SymId) -> bool {
        self.cfg.symbol(sym).is_param_borrow || st.loans.contains_key(&sym.0)
    }

    fn apply_effect(
        &self,
        st: &mut State,
        sym: SymId,
        eff: Effect,
        emit: &mut Emit<'_>,
        line: u32,
    ) {
        let s = self.cfg.symbol(sym);
        match s.kind {
            Kind::Owned => match eff {
                Effect::Consume => {
                    consume_like(st, sym, emit, line, "OWN007");
                    if let Some(buf) = &s.buffer {
                        if buf.stack_backed() {
                            emit.push("OWN016", line);
                        } else {
                            emit.push("OWN017", line);
                        }
                    }
                    let rid = st.rid_of(sym);
                    st.var.insert(rid, ESCAPED);
                }
                Effect::BorrowMut => check_mut_borrowable(st, sym, emit, line),
                Effect::Borrow => check_shared_borrowable(st, sym, emit, line),
                Effect::Plain => emit.push("OWN041", line),
            },
            Kind::Borrow => match eff {
                Effect::Borrow => {
                    if !self.binding_live(st, sym) {
                        emit.push("OWN004", line);
                    }
                }
                Effect::BorrowMut => {
                    if s.borrow_is_mut == Some(false) {
                        emit.push("OWN041", line);
                    }
                }
                Effect::Consume => emit.push("OWN034", line),
                Effect::Plain => emit.push("OWN041", line),
            },
            Kind::Plain => {
                if matches!(eff, Effect::Borrow | Effect::BorrowMut | Effect::Consume) {
                    emit.push("OWN041", line);
                }
            }
        }
    }

    // -- transfer (the step() dispatch) ------------------------------------

    // One large `match` faithfully dispatching every `Instr` variant, mirroring
    // the Python `step()`; splitting it would obscure the 1:1 port.
    #[allow(clippy::too_many_lines)]
    fn step(&self, ins: &Instr, st: &mut State, emit: &mut Emit<'_>) {
        match ins {
            Instr::Acquire { sym, line, .. } | Instr::AcquireBuffer { sym, line, .. } => {
                let rid = st.mint(*sym);
                st.var.insert(rid, OWNED);
                st.acquired_at.insert(rid, (*line, true));
            }
            Instr::MoveInto { dst, src, line } => {
                consume_like(st, *src, emit, *line, "OWN007");
                let src_rid = st.rid_of(*src);
                if st.states(src_rid) & OWNED != 0 {
                    st.moved_at.insert(src_rid, (*line, true));
                }
                st.var.insert(src_rid, MOVED);
                let dst_rid = st.mint(*dst);
                st.var.insert(dst_rid, OWNED);
                st.acquired_at.insert(dst_rid, (*line, true));
            }
            Instr::AliasJoin { handle, src, .. } => {
                let rid = st.rid_of(*src);
                st.handle_rid.insert(handle.0, rid);
            }
            Instr::Release { sym, line } => {
                let rid = st.rid_of(*sym);
                let s = st.states(rid);
                // Python splits the message (released "twice" vs "maybe already
                // released on some path") but both are OWN003; merged since only
                // (line, code) is compared, and `s == RELEASED` ⊆ `s & RELEASED`.
                if s & RELEASED != 0 {
                    emit.push("OWN003", *line);
                } else if !state_problem(st, *sym, emit, *line) {
                    let (shared, mutable) = loans_on(st, *sym);
                    if shared > 0 || mutable {
                        emit.push("OWN008", *line);
                    }
                }
                st.var.insert(rid, RELEASED);
            }
            Instr::Use { sym, line } => {
                let s = self.cfg.symbol(*sym);
                match s.kind {
                    Kind::Owned => {
                        if !state_problem(st, *sym, emit, *line) {
                            let (_shared, mutable) = loans_on(st, *sym);
                            if mutable {
                                emit.push("OWN013", *line);
                            }
                        }
                    }
                    Kind::Borrow => {
                        if !self.binding_live(st, *sym) {
                            emit.push("OWN004", *line);
                        }
                    }
                    Kind::Plain => {}
                }
            }
            Instr::Overspan { line, .. } => {
                emit.push("OWN025", *line);
            }
            Instr::Invoke { args, line, .. } => {
                for (opt_sym, eff) in args {
                    if let Some(sid) = opt_sym {
                        self.apply_effect(st, *sid, *eff, emit, *line);
                    }
                }
            }
            Instr::BorrowStart {
                owner,
                binding,
                is_mut,
                line,
            } => {
                let kind = if *is_mut {
                    check_mut_borrowable(st, *owner, emit, *line);
                    LoanKind::Mut
                } else {
                    check_shared_borrowable(st, *owner, emit, *line);
                    LoanKind::Shared
                };
                let owner_rid = st.rid_of(*owner);
                st.loans.insert(
                    binding.0,
                    Loan {
                        owner: owner_rid,
                        kind,
                    },
                );
            }
            Instr::BorrowEnd { binding, .. } => {
                st.loans.remove(&binding.0);
            }
            Instr::Return { sym, line } => {
                let exclude = sym.map(|s| st.rid_of(s));
                leak_check(st, *line, emit, exclude);
                if let Some(sid) = sym {
                    let rid = st.rid_of(*sid);
                    let s = st.states(rid);
                    if s & OWNED == 0 {
                        if s & MOVED != 0 {
                            emit.push("OWN005", *line);
                        } else {
                            emit.push("OWN002", *line);
                        }
                    } else {
                        let (shared, mutable) = loans_on(st, *sid);
                        let symbol = self.cfg.symbol(*sid);
                        if shared > 0 || mutable {
                            emit.push("OWN007", *line);
                        } else if let Some(buf) = &symbol.buffer {
                            if buf.stack_backed() {
                                emit.push("OWN015", *line);
                            } else {
                                emit.push("OWN017", *line);
                            }
                        }
                    }
                    st.var.insert(rid, ESCAPED);
                }
            }
        }
    }

    fn transfer_block(&self, block: usize, in_state: &State, emit: &mut Emit<'_>) -> State {
        let mut st = in_state.clone();
        if let Some(blk) = self.cfg.blocks.get(block) {
            for ins in &blk.instrs {
                self.step(ins, &mut st, emit);
            }
        }
        st
    }
}

impl ControlFlowGraph for Ownership<'_> {
    fn num_blocks(&self) -> usize {
        self.cfg.blocks.len()
    }
    fn entry(&self) -> usize {
        self.cfg.entry.0 as usize
    }
    fn successors(&self, block: usize) -> &[usize] {
        self.succ.get(block).map_or(&[], Vec::as_slice)
    }
}

impl Analysis for Ownership<'_> {
    type Fact = State;
    fn entry_fact(&self) -> State {
        self.initial_state()
    }
    fn transfer(&self, block: usize, in_fact: &State) -> State {
        // Phase-1 fixpoint transfer: state evolves, no diagnostics.
        self.transfer_block(block, in_fact, &mut Emit::Silent)
    }
}

const fn instr_line(ins: &Instr) -> u32 {
    match ins {
        Instr::Acquire { line, .. }
        | Instr::AcquireBuffer { line, .. }
        | Instr::MoveInto { line, .. }
        | Instr::AliasJoin { line, .. }
        | Instr::Release { line, .. }
        | Instr::Use { line, .. }
        | Instr::Overspan { line, .. }
        | Instr::Invoke { line, .. }
        | Instr::BorrowStart { line, .. }
        | Instr::BorrowEnd { line, .. }
        | Instr::Return { line, .. } => *line,
    }
}

/// Run the ownership analysis over one function's CFG.
///
/// Returns its diagnostics in Python emission order (phase-2 block transfers,
/// then end-of-function leak checks). Port of `analysis.analyze` /
/// `_Analyzer.run`.
#[must_use]
pub fn analyze(cfg: &Cfg) -> Vec<Diagnostic> {
    let own = Ownership::new(cfg);

    // Phase 1: converge the in-states silently.
    let solution = solve(&own, &own);

    // Reachable blocks in ascending id order (Python `sorted(reachable)`).
    let reachable: Vec<usize> = (0..cfg.blocks.len())
        .filter(|&b| solution.is_reachable(b))
        .collect();

    let mut diags: Vec<Diagnostic> = Vec::new();
    let mut out_states: BTreeMap<usize, State> = BTreeMap::new();

    // Phase 2a: one emitting transfer per block, on its converged in-state.
    for &bid in &reachable {
        let in_st = solution.in_fact(bid).cloned().unwrap_or_else(State::bottom);
        let mut emit = Emit::Collect(&mut diags);
        let out = own.transfer_block(bid, &in_st, &mut emit);
        out_states.insert(bid, out);
    }

    // Phase 2b: leak check at every non-return function exit.
    for &bid in &reachable {
        let Some(blk) = cfg.blocks.get(bid) else {
            continue;
        };
        if !blk.succ.is_empty() {
            continue;
        }
        if matches!(blk.instrs.last(), Some(Instr::Return { .. })) {
            continue;
        }
        let at_line = last_line(cfg, blk);
        if let Some(st) = out_states.get(&bid) {
            let mut emit = Emit::Collect(&mut diags);
            leak_check(st, at_line, &mut emit, None);
        }
    }

    diags
}

fn last_line(cfg: &Cfg, blk: &own_cfg::Block) -> u32 {
    blk.instrs
        .last()
        .map_or_else(|| first_line(cfg), instr_line)
}

fn first_line(cfg: &Cfg) -> u32 {
    for b in &cfg.blocks {
        if let Some(first) = b.instrs.first() {
            return instr_line(first);
        }
    }
    0
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::{State, OWNED};
    use crate::solver::Lattice;

    /// A single-RID state whose var-set is the bitmask `bits` — the finite
    /// per-RID lattice `{OWNED, MOVED, RELEASED, ESCAPED}` is exactly `0..16`.
    fn one(bits: u8) -> State {
        let mut s = State::bottom();
        s.var.insert(0, bits);
        s
    }

    fn joined(a: &State, b: &State) -> State {
        let mut out = a.clone();
        out.join(b);
        out
    }

    #[test]
    fn ownership_lattice_laws_exhaustive_per_rid() {
        // Exhaustive over the finite per-RID state space (16 values), matching
        // the #214 requirement: idempotent, commutative, associative join, and
        // x <= join(x, y). Loans/handle_rid are empty so `join`'s block-scoped-
        // loan invariant holds for every pair (the merge case the solver hits).
        for x in 0u8..16 {
            let sx = one(x);
            // idempotent: join(x, x) == x, and reports no change.
            let mut xx = sx.clone();
            assert!(!xx.join(&sx), "join(x,x) reports no change");
            assert_eq!(xx, sx, "join(x, x) == x");

            for y in 0u8..16 {
                let sy = one(y);
                let xy = joined(&sx, &sy);
                let yx = joined(&sy, &sx);
                assert_eq!(xy, yx, "join commutative for {x},{y}");

                // x <= join(x, y): joining x into (x∨y) does not change it.
                let mut re = xy.clone();
                assert!(!re.join(&sx), "x <= join(x,y): {x},{y}");
                assert_eq!(re, xy);

                for z in 0u8..16 {
                    let sz = one(z);
                    let lhs = joined(&joined(&sx, &sy), &sz);
                    let rhs = joined(&sx, &joined(&sy, &sz));
                    assert_eq!(lhs, rhs, "join associative for {x},{y},{z}");
                }
            }
        }
    }

    #[test]
    fn bottom_is_identity() {
        let s = one(OWNED | super::MOVED);
        assert_eq!(joined(&State::bottom(), &s), s, "bottom ∨ x == x");
        assert_eq!(joined(&s, &State::bottom()), s, "x ∨ bottom == x");
    }

    #[test]
    fn join_reports_growth_only_when_the_set_actually_grows() {
        let mut owned = one(OWNED);
        let released = one(super::RELEASED);
        // OWNED ∨ RELEASED = {OWNED, RELEASED} — a strict growth.
        assert!(owned.join(&released), "adding a new state bit is a change");
        assert_eq!(owned.var.get(&0).copied(), Some(OWNED | super::RELEASED));
        // Re-joining a subset changes nothing.
        assert!(!owned.join(&released), "re-join of a subset is no change");
    }

    #[test]
    fn absent_rid_reads_as_owned_but_joins_as_empty() {
        // Read default is OWNED (Python st.var.get(rid, {OWNED})).
        let empty = State::bottom();
        assert_eq!(empty.states(0), OWNED);
        // Join default is ∅: joining a state that has rid=RELEASED with one that
        // omits it yields exactly RELEASED (∅ ∪ RELEASED), NOT OWNED|RELEASED.
        let mut a = State::bottom();
        let mut b = State::bottom();
        b.var.insert(0, super::RELEASED);
        a.join(&b);
        assert_eq!(a.var.get(&0).copied(), Some(super::RELEASED));
    }

    #[test]
    fn state_serialization_is_not_required_but_var_map_is_deterministic() {
        // A BTreeMap iterates in key order, so two equal states compare equal and
        // hash-independent — the property the fixpoint's `!=` convergence relies on.
        let mut a = State::bottom();
        a.var.insert(2, OWNED);
        a.var.insert(1, super::RELEASED);
        let mut b = State::bottom();
        b.var.insert(1, super::RELEASED);
        b.var.insert(2, OWNED);
        assert_eq!(a, b, "insertion order must not affect State equality");
        let keys: Vec<u32> = a.var.keys().copied().collect();
        assert_eq!(keys, vec![1, 2], "BTreeMap keeps deterministic key order");
    }
}
