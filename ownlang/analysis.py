"""
Flow-sensitive ownership analysis on an explicit loans + permissions model.

This revision formalises what the previous version did implicitly. The reviewer
was right that "owner becomes SharedBorrowed" is the wrong mental model — but
note the *code* already kept the owner's variable-state separate from its borrow
counts. Here that separation is made explicit and given names:

* **VariableState** (per owned symbol): a *set* drawn from
  {OWNED, MOVED, RELEASED, ESCAPED}. The set is "what could be true here across
  all paths"; merges take the union. The owner stays OWNED for the whole time it
  is borrowed — a borrow never overwrites the owner's state.

* **ActiveLoans**: a borrow is a first-class Loan(owner, binding, kind) that is
  *added* when the borrow opens and *removed* when it closes. Loans live beside
  the variable-states, not inside them.

* **Permissions** are derived on demand from (variable-state + active loans):

      Owned, no loans      -> Own + Read + Write + Drop
      Owned, shared loan   -> Read                  (Own/Write/Drop suspended)
      Owned, mutable loan  -> (nothing)             (exclusive: owner unusable)
      Moved/Released/Escaped -> (nothing)

  Each operation checks the permission it needs and reports the specific code:
  a move needs Own (suspended by *any* loan -> OWN007), a release needs Drop
  (-> OWN008), `use` needs Read (suspended by a mutable loan -> OWN013), and so on.

The traversal is a forward worklist to a fixpoint, so it handles loops (`while`):
a block is re-evaluated until its in-state stops growing. The per-symbol lattice
is the finite set {OWNED,MOVED,RELEASED,ESCAPED} merged by union, and the transfer
is monotone, so the iteration converges (no widening needed). On a loop-free CFG
this reduces to one pass per block — identical to the previous topological walk.
Because every borrow is block-scoped, the active loans are identical on all
predecessors of a merge (back-edges included), so joining loans is trivial; this
invariant is asserted, not assumed.

Diagnostics are emitted in a second pass, once, on the converged in-states — never
during the fixpoint iteration (a looped block is transferred many times).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import assert_never

from .ast_nodes import Effect
from .cfg import (
    CFG,
    Acquire,
    AcquireBuffer,
    Block,
    BorrowEnd,
    BorrowStart,
    Instr,
    Invoke,
    Kind,
    MoveInto,
    Overspan,
    Release,
    Return,
    Symbol,
    Use,
)
from .diagnostics import Diagnostic


class VarState(Enum):
    OWNED = auto()
    MOVED = auto()
    RELEASED = auto()
    ESCAPED = auto()   # ownership left the function: returned, or consumed by a call


class LoanKind(Enum):
    SHARED = auto()
    MUT = auto()


@dataclass(frozen=True)
class Loan:
    loan_id: int      # we use id(binding_symbol): unique per borrow scope
    owner: int        # id(owner_symbol)
    binding: int      # id(binding_symbol)
    kind: LoanKind


@dataclass
class State:
    # `var` is keyed by **RID** (resource id), not by handle identity. A RID is the
    # obligation that carries the {OWNED,MOVED,RELEASED,ESCAPED} state; a handle
    # (local/param symbol) denotes a RID through `handle_rid`. See the class note in
    # `rid_of`. (D5.4 step 0 — the no-op identity refactor that lets step 1 add
    # `alias_join`: two handles → one RID. Until an alias is minted the map is 1:1
    # and the analysis is byte-for-byte the pre-RID behaviour.)
    var: dict[int, set[VarState]] = field(default_factory=dict)
    loans: dict[int, Loan] = field(default_factory=dict)
    handle_rid: dict[int, int] = field(default_factory=dict)

    def copy(self) -> State:
        return State(
            var={k: set(v) for k, v in self.var.items()},
            loans=dict(self.loans),
            handle_rid=dict(self.handle_rid),
        )

    def rid_of(self, sym: Symbol) -> int:
        """Resolve a handle to its resource id (RID).

        Default is **1:1**: a handle that has not been explicitly aliased denotes
        its own resource, keyed by the originating symbol's identity. Choosing
        ``RID == id(sym)`` for an un-aliased handle is what makes step 0 a no-op —
        every ``var`` key is the same int it was before the indirection, so
        ``_sym_by_id`` still resolves a RID straight back to its symbol. D5.4
        step 1's ``alias_join`` is the only operation that points a *second* handle
        at an existing RID; until then this is the identity map."""
        return self.handle_rid.get(id(sym), id(sym))

    def mint(self, sym: Symbol) -> int:
        """Bind `sym` to a fresh resource (its own RID) — the 1:1 acquire. Records
        the mapping explicitly so the handle is a known owning alias of the RID."""
        rid = id(sym)
        self.handle_rid[id(sym)] = rid
        return rid


def _join_handle_rid(a: dict[int, int], b: dict[int, int]) -> dict[int, int]:
    """Join the handle→RID maps of two merging paths. Under the step-0 1:1 invariant
    a handle resolves to the same RID on every path that knows it (RIDs are minted
    deterministically as ``id(sym)``), so the union cannot conflict. Assert that —
    locking the invariant the way `join` already locks the block-scoped-loan one —
    rather than silently picking a side. Step 1 (aliasing) will revisit this join."""
    out = dict(a)
    for handle, rid in b.items():
        if handle in out:
            assert out[handle] == rid, (
                "a handle maps to two different RIDs at a control-flow merge; the "
                "D5.4 step-0 invariant is a single 1:1 handle->RID mapping"
            )
        else:
            out[handle] = rid
    return out


def join(a: State, b: State) -> State:
    out = State()
    for k in set(a.var) | set(b.var):
        out.var[k] = set(a.var.get(k, set())) | set(b.var.get(k, set()))
    # Block-scoped borrows => identical active loans on both predecessors. This
    # holds across loop back-edges too: a borrow opened inside a loop body closes
    # within the same iteration, so the loan set at the body exit equals the one on
    # the entry edge. Assert the invariant rather than paper over a builder bug.
    assert set(a.loans) == set(b.loans), (
        "active loans differ at a control-flow merge; this should be impossible "
        "for block-scoped borrows (they close within the scope that opened them)"
    )
    out.loans = dict(a.loans)
    out.handle_rid = _join_handle_rid(a.handle_rid, b.handle_rid)
    return out


class _Analyzer:
    def __init__(self, cfg: CFG):
        self.cfg = cfg
        self.diags: list[Diagnostic] = []
        self.blocks = {b.id: b for b in cfg.blocks}
        # During the fixpoint pass (phase 1) the transfer runs repeatedly to
        # converge the per-block in-states; diagnostics must NOT be emitted then
        # (a block in a loop is visited many times). `silent` gates `err`; phase 2
        # re-runs the transfer once per block, emitting on the converged state.
        self.silent = False

    def initial_state(self) -> State:
        s = State()
        for p in self.cfg.params:
            if p.kind == Kind.OWNED:
                s.var[s.mint(p)] = {VarState.OWNED}
        return s

    def err(self, code: str, msg: str, line: int,
            subject: str | None = None,
            resource_kind: str | None = None) -> None:
        if self.silent:
            return
        self.diags.append(Diagnostic(code, msg, line, subject=subject,
                                     resource_kind=resource_kind))

    # -- loan / permission helpers -----------------------------------------

    def loans_on(self, st: State, owner: Symbol) -> tuple[int, bool]:
        shared = 0
        mut = False
        for ln in st.loans.values():
            if ln.owner == id(owner):
                if ln.kind == LoanKind.SHARED:
                    shared += 1
                else:
                    mut = True
        return shared, mut

    def binding_live(self, st: State, sym: Symbol) -> bool:
        if sym.is_param_borrow:
            return True
        return any(ln.binding == id(sym) for ln in st.loans.values())

    # Common state classification, returning a code to emit (or None) when an
    # operation `verb` is attempted on owned symbol `sym`. Handles the
    # gone / maybe-gone cases shared by use/move/release/borrow/consume.
    def _state_problem(self, st: State, sym: Symbol, verb: str, line: int) -> bool:
        S = st.var.get(st.rid_of(sym), {VarState.OWNED})
        subj = sym.origin
        kind = sym.resource_kind
        if VarState.OWNED not in S:
            if VarState.MOVED in S:
                self.err("OWN005", f"{verb} '{sym.name}' after it was moved",
                         line, subject=subj, resource_kind=kind)
            elif VarState.ESCAPED in S and VarState.RELEASED not in S:
                self.err("OWN002",
                         f"{verb} '{sym.name}' after it was consumed", line,
                         subject=subj, resource_kind=kind)
            else:
                self.err("OWN002", f"{verb} '{sym.name}' after it was released",
                         line, subject=subj, resource_kind=kind)
            return True
        if S & {VarState.RELEASED, VarState.ESCAPED}:
            self.err("OWN009",
                     f"{verb} '{sym.name}', which may have been released on some "
                     f"path", line, subject=subj, resource_kind=kind)
            return True
        if VarState.MOVED in S:
            self.err("OWN010",
                     f"{verb} '{sym.name}', which may have been moved on some "
                     f"path", line, subject=subj, resource_kind=kind)
            return True
        return False

    # -- reachability + dataflow fixpoint ----------------------------------

    def reachable(self) -> set[int]:
        seen: set[int] = set()
        stack = [self.cfg.entry]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(self.blocks[x].succ)
        return seen

    def in_state_of(self, bid: int, preds: dict[int, list[int]],
                    reachable: set[int], out_states: dict[int, State]) -> State:
        """The in-state of a block = the join (union) of its already-computed
        predecessors' out-states; the entry block starts from `initial_state`."""
        if bid == self.cfg.entry:
            return self.initial_state()
        ps = [p for p in preds[bid] if p in reachable and p in out_states]
        if not ps:
            return State()
        st = out_states[ps[0]].copy()
        for p in ps[1:]:
            st = join(st, out_states[p])
        return st

    def fixpoint(self, reachable: set[int]) -> dict[int, State]:
        """Forward worklist to a fixpoint over a (possibly cyclic) CFG. The
        per-symbol lattice is the finite set {OWNED,MOVED,RELEASED,ESCAPED}, merged
        by union at joins; the transfer is monotone, so iterating until no out-state
        changes converges (a block's out can only grow up the finite lattice). A
        block is re-queued only when one of its predecessors' out-state changed.
        Runs silently — phase 2 emits the diagnostics on the converged in-states."""
        preds = self.cfg.preds()
        in_states: dict[int, State] = {}
        out_states: dict[int, State] = {}
        work: deque[int] = deque(sorted(reachable))
        queued: set[int] = set(reachable)
        while work:
            bid = work.popleft()
            queued.discard(bid)
            in_states[bid] = self.in_state_of(bid, preds, reachable, out_states)
            new_out = self.transfer(self.blocks[bid], in_states[bid])
            if bid not in out_states or new_out != out_states[bid]:
                out_states[bid] = new_out
                for s in self.blocks[bid].succ:
                    if s in reachable and s not in queued:
                        work.append(s)
                        queued.add(s)
        return in_states

    # -- main --------------------------------------------------------------

    def run(self) -> list[Diagnostic]:
        reachable = self.reachable()
        # Phase 1: converge the in-states silently (no diagnostics — a looped block
        # is transferred many times before it stabilises).
        self.silent = True
        in_states = self.fixpoint(reachable)
        self.silent = False
        # Phase 2: one emitting transfer per block, on its converged in-state, so
        # every diagnostic is reported exactly once at the fixpoint. Block order is
        # irrelevant — __main__ sorts the diagnostics by (line, code).
        out_states: dict[int, State] = {}
        for bid in sorted(reachable):
            out_states[bid] = self.transfer(self.blocks[bid], in_states[bid])

        for bid in sorted(reachable):
            blk = self.blocks[bid]
            if blk.succ:
                continue
            if blk.instrs and isinstance(blk.instrs[-1], Return):
                continue
            self.leak_check(out_states[bid], at_line=self.last_line(blk),
                            context="at end of function")
        return self.diags

    def last_line(self, blk: Block) -> int:
        if blk.instrs:
            return getattr(blk.instrs[-1], "line", self.first_line())
        return self.first_line()

    def first_line(self) -> int:
        for b in self.cfg.blocks:
            if b.instrs:
                return getattr(b.instrs[0], "line", 0)
        return 0

    def leak_check(self, st: State, at_line: int, context: str,
                   exclude: Symbol | None = None) -> None:
        excl = st.rid_of(exclude) if exclude is not None else None
        for rid, states in st.var.items():
            if rid == excl:
                continue
            if VarState.OWNED in states:
                sym = self._sym_by_id(rid)
                name = sym.name if sym else f"#{rid}"
                self.err("OWN001",
                         f"'{name}' is owned but not released {context} "
                         f"(leaks on at least one path)", at_line,
                         subject=(sym.origin if sym else None),
                         resource_kind=(sym.resource_kind if sym else None))

    def _sym_by_id(self, symid: int) -> Symbol | None:
        if not hasattr(self, "_symindex"):
            idx: dict[int, Symbol] = {}
            for p in self.cfg.params:
                idx[id(p)] = p
            for b in self.cfg.blocks:
                for ins in b.instrs:
                    for attr in ("sym", "dst", "src", "owner", "binding"):
                        s = getattr(ins, attr, None)
                        if isinstance(s, Symbol):
                            idx[id(s)] = s
                    if isinstance(ins, Invoke):
                        for s, _ in ins.args:
                            if isinstance(s, Symbol):
                                idx[id(s)] = s
            self._symindex = idx
        return self._symindex.get(symid)

    # -- transfer -----------------------------------------------------------

    def transfer(self, blk: Block, st: State) -> State:
        st = st.copy()
        for ins in blk.instrs:
            self.step(ins, st)
        return st

    def step(self, ins: Instr, st: State) -> None:
        if isinstance(ins, Acquire):
            st.var[st.mint(ins.sym)] = {VarState.OWNED}
            return

        if isinstance(ins, AcquireBuffer):
            st.var[st.mint(ins.sym)] = {VarState.OWNED}
            return

        if isinstance(ins, MoveInto):
            self._consume_like(st, ins.src, "move", ins.line, code_borrowed="OWN007")
            st.var[st.rid_of(ins.src)] = {VarState.MOVED}
            st.var[st.mint(ins.dst)] = {VarState.OWNED}
            return

        if isinstance(ins, Release):
            subj = ins.sym.origin
            rkind = ins.sym.resource_kind
            S = st.var.get(st.rid_of(ins.sym), {VarState.OWNED})
            if {VarState.RELEASED} == S:
                self.err("OWN003", f"'{ins.sym.name}' is released twice",
                         ins.line, subject=subj, resource_kind=rkind)
            elif VarState.RELEASED in S:
                self.err("OWN003",
                         f"'{ins.sym.name}' may already be released on some path "
                         f"before this release", ins.line, subject=subj,
                         resource_kind=rkind)
            elif not self._state_problem(st, ins.sym, "release", ins.line):
                shared, mut = self.loans_on(st, ins.sym)
                if shared or mut:
                    self.err("OWN008",
                             f"cannot release '{ins.sym.name}' while it is borrowed",
                             ins.line, subject=subj, resource_kind=rkind)
            st.var[st.rid_of(ins.sym)] = {VarState.RELEASED}
            return

        if isinstance(ins, Use):
            if ins.sym.kind == Kind.OWNED:
                if not self._state_problem(st, ins.sym, "use", ins.line):
                    _, mut = self.loans_on(st, ins.sym)
                    if mut:
                        self.err("OWN013",
                                 f"cannot use '{ins.sym.name}' directly while it "
                                 f"is mutably borrowed", ins.line)
            elif ins.sym.kind == Kind.BORROW:
                if not self.binding_live(st, ins.sym):
                    self.err("OWN004",
                             f"borrow '{ins.sym.name}' used outside its live "
                             f"region", ins.line)
            return

        if isinstance(ins, Overspan):
            # POOL005: a full-length view over the whole pooled array reaches past
            # the logical length it was rented for (the oversized [n, Length) tail).
            # A property of the view-creation site, not of the owner's flow state —
            # so it raises regardless of OWNED/RELEASED and changes no state.
            self.err("OWN025",
                     f"'{ins.sym.name}' is viewed at its full backing length, past "
                     f"the logical length it was rented for (over-read / "
                     f"over-clear)", ins.line, subject=ins.sym.origin,
                     resource_kind=ins.sym.resource_kind)
            return

        if isinstance(ins, Invoke):
            for sym, eff in ins.args:
                if sym is not None:
                    self._apply_effect(st, sym, eff, ins.callee, ins.line)
            return

        if isinstance(ins, BorrowStart):
            if ins.mut:
                self._check_mut_borrowable(st, ins.owner, ins.line)
                kind = LoanKind.MUT
            else:
                self._check_shared_borrowable(st, ins.owner, ins.line)
                kind = LoanKind.SHARED
            st.loans[id(ins.binding)] = Loan(
                loan_id=id(ins.binding), owner=id(ins.owner),
                binding=id(ins.binding), kind=kind)
            return

        if isinstance(ins, BorrowEnd):
            st.loans.pop(id(ins.binding), None)
            return

        if isinstance(ins, Return):
            self.leak_check(st, at_line=ins.line, context="before return",
                            exclude=ins.sym)
            if ins.sym is not None:
                subj = ins.sym.origin
                rkind = ins.sym.resource_kind
                S = st.var.get(st.rid_of(ins.sym), {VarState.OWNED})
                if VarState.OWNED not in S:
                    if VarState.MOVED in S:
                        self.err("OWN005",
                                 f"'{ins.sym.name}' returned after it was moved",
                                 ins.line, subject=subj, resource_kind=rkind)
                    else:
                        self.err("OWN002",
                                 f"'{ins.sym.name}' returned after it was released",
                                 ins.line, subject=subj, resource_kind=rkind)
                else:
                    # returning an owner is an escape (consume): it needs Own
                    # permission, so a live loan on it is OWN007, just like move.
                    shared, mut = self.loans_on(st, ins.sym)
                    if shared or mut:
                        self.err("OWN007",
                                 f"cannot return '{ins.sym.name}' while it is "
                                 f"borrowed", ins.line, subject=subj,
                                 resource_kind=rkind)
                    elif ins.sym.buffer is not None and ins.sym.buffer.stack_backed:
                        self.err("OWN015",
                                 f"'{ins.sym.name}' is a {ins.sym.buffer.mode.value} "
                                 f"buffer and may be stack-backed; it cannot escape "
                                 f"the current function", ins.line, subject=subj)
                    elif ins.sym.buffer is not None:
                        self.err("OWN017",
                                 f"'{ins.sym.name}' is a {ins.sym.buffer.mode.value} "
                                 f"buffer; the PoC code generator cannot lower an "
                                 f"escaping buffer to faithful .NET (the caller gets "
                                 f"no handle to Return/Free), so returning it is "
                                 f"rejected", ins.line, subject=subj)
                st.var[st.rid_of(ins.sym)] = {VarState.ESCAPED}
            return

        assert_never(ins)

    # -- permission checks --------------------------------------------------

    def _consume_like(self, st: State, sym: Symbol, verb: str, line: int,
                      code_borrowed: str) -> None:
        """move / consume: needs Own permission (no loans)."""
        if self._state_problem(st, sym, verb, line):
            return
        shared, mut = self.loans_on(st, sym)
        if shared or mut:
            self.err(code_borrowed,
                     f"cannot {verb} '{sym.name}' while it is borrowed", line)

    def _check_mut_borrowable(self, st: State, owner: Symbol, line: int) -> None:
        if self._state_problem(st, owner, "mutably borrow", line):
            return
        shared, mut = self.loans_on(st, owner)
        if shared:
            self.err("OWN006",
                     f"cannot mutably borrow '{owner.name}': a shared borrow is "
                     f"live", line)
        elif mut:
            self.err("OWN011",
                     f"cannot mutably borrow '{owner.name}': it is already "
                     f"mutably borrowed", line)

    def _check_shared_borrowable(self, st: State, owner: Symbol, line: int) -> None:
        if self._state_problem(st, owner, "borrow", line):
            return
        _, mut = self.loans_on(st, owner)
        if mut:
            self.err("OWN012",
                     f"cannot share-borrow '{owner.name}': it is mutably "
                     f"borrowed", line)

    def _apply_effect(self, st: State, sym: Symbol, eff: Effect,
                      callee: str, line: int) -> None:
        if sym.kind == Kind.OWNED:
            if eff == Effect.CONSUME:
                self._consume_like(st, sym, "consume", line, code_borrowed="OWN007")
                if sym.buffer is not None and sym.buffer.stack_backed:
                    self.err("OWN016",
                             f"'{sym.name}' is a {sym.buffer.mode.value} buffer "
                             f"and may be stack-backed; it cannot be moved to a "
                             f"longer-lived owner by consuming it in '{callee}'",
                             line, subject=sym.origin)
                elif sym.buffer is not None:
                    self.err("OWN017",
                             f"'{sym.name}' is a {sym.buffer.mode.value} buffer; "
                             f"the PoC code generator cannot lower an escaping "
                             f"buffer, so consuming it in '{callee}' is rejected",
                             line, subject=sym.origin)
                st.var[st.rid_of(sym)] = {VarState.ESCAPED}
            elif eff == Effect.BORROW_MUT:
                self._check_mut_borrowable(st, sym, line)
            elif eff == Effect.BORROW:
                self._check_shared_borrowable(st, sym, line)
            else:  # PLAIN
                self.err("OWN041",
                         f"argument '{sym.name}' to '{callee}' is an owned "
                         f"resource but the parameter is a plain value", line)
        elif sym.kind == Kind.BORROW:
            if eff == Effect.BORROW:
                if not self.binding_live(st, sym):
                    self.err("OWN004",
                             f"borrow '{sym.name}' used outside its live region",
                             line)
            elif eff == Effect.BORROW_MUT:
                if sym.borrow_is_mut is False:
                    self.err("OWN041",
                             f"cannot pass shared borrow '{sym.name}' to '{callee}'"
                             f": a mutable borrow is required", line)
            elif eff == Effect.CONSUME:
                self.err("OWN034",
                         f"cannot consume '{sym.name}': it is a borrow, not an "
                         f"owned resource", line)
            else:  # PLAIN
                self.err("OWN041",
                         f"argument '{sym.name}' to '{callee}': a borrow cannot "
                         f"be passed as a plain value", line)
        elif sym.kind == Kind.PLAIN:
            if eff in (Effect.BORROW, Effect.BORROW_MUT, Effect.CONSUME):
                self.err("OWN041",
                         f"argument '{sym.name}' to '{callee}': a plain value "
                         f"cannot satisfy a resource parameter", line)


def analyze(cfg: CFG) -> list[Diagnostic]:
    return _Analyzer(cfg).run()
