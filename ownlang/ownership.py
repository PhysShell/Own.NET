"""Interprocedural ownership summaries — P-005 D5, infra slice **D5.0**.

See [`docs/notes/d5-ownership-transfer.md`](../docs/notes/d5-ownership-transfer.md).

This module is pure **data + algorithm**: it computes a Method Ownership Summary
(MOS) for each first-party method from per-method *local evidence* (a "skeleton"
of what a body directly does with each disposable parameter and what it returns),
resolving the parts that depend on other methods' summaries by a **summary
fixpoint over the strongly-connected-component condensation** of the call graph.

The summary is *context-insensitive*: each method has exactly one MOS, independent
of who calls it or how deep the call sits. That is what makes the computation both
linear (each method resolved once and reused — no per-call re-descent) and exact
on recursion: cycles are solved to their least fixpoint on the four-point lattice
rather than truncated. There is **no depth cap** — the SCC condensation bounds the
work without one (an earlier slice capped the recursive descent at depth 3 purely
to dodge the exponential a memo-less re-descent would otherwise hit on diamond call
graphs; the condensation removes both the blowup and the cap-induced false
`unknown`s on deep chains).

Lowering a summary into the core's `consume`/`borrow`/`acquire` vocabulary lives in
the bridge (`ownir.py`, D5.1+: `must`→consume, `no`→borrow, `may`/`unknown`→plain);
the wrapper/alias (`aliasOf`) obligation-identity model is D5.4. The skeleton is the
extractor-facing input; here it is hand-authored in tests.

Precision note: a parameter is reported `must`-transfer only when ownership leaves
the caller on **every** normal-return path. The fixpoint seeds each recursive edge
at the lattice bottom (⊥, "no evidence yet") rather than at a spurious `no`, so a
method that disposes on its base case and recurses otherwise resolves to `must`
(every *terminating* path disposes), and mutual recursion that never disposes
settles at `no`. A forward to an unsummarized (extern) callee is the only residual
`unknown`, and `solve_with_log` surfaces every such boundary — never a guessed
`must`. That keeps the project's precision-first stance: we only ever *claim*
transfer when we can prove it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum


class Transfer(StrEnum):
    """Did ownership of a disposable parameter leave the caller?

    `no`      — borrowed; the caller keeps ownership (a leak if never disposed).
    `must`    — transferred on **every** normal-return path.
    `may`     — transferred on **some** paths but not all (partial consume).
    `unknown` — insufficient evidence (extern callee, or a chain past the cap).
    """

    NO = "no"
    MUST = "must"
    MAY = "may"
    UNKNOWN = "unknown"


def join(a: Transfer, b: Transfer) -> Transfer:
    """Combine two paths' transfer verdicts for one parameter.

    `unknown` is absorbing (one un-characterizable path leaves the whole
    un-characterizable); otherwise a path that transfers joined with one that
    keeps is `may` (it is path-dependent, and we know it)."""
    if a == b:
        return a
    if Transfer.UNKNOWN in (a, b):
        return Transfer.UNKNOWN
    return Transfer.MAY  # any mix of {no, must, may} without unknown


# --- the extractor-facing input (a per-method "skeleton") -------------------

@dataclass(frozen=True)
class PathAction:
    """One thing a method body does with a parameter on one normal-return path.

    kind: `dispose` (releases it) | `adopt` (stores it into an owning field) |
    `return` (returns it — escapes to the caller of *this* method) | `borrow`
    (only reads/uses) | `forward` (passes it to `callee` at position `arg`).
    The first three are ownership *leaving the caller* on that path (`must`)."""

    kind: str
    callee: str = ""
    arg: int = -1


@dataclass(frozen=True)
class ParamSkeleton:
    index: int
    name: str = ""
    disposable: bool = True
    paths: tuple[PathAction, ...] = ()
    escapes: bool = False  # the reference outlives the call (field/collection/return)


@dataclass(frozen=True)
class ReturnSkeleton:
    """What a method returns. kind: `fresh` (a newly-owned disposable) |
    `aliasOf` (shares the obligation of parameter `arg` — the wrapper case) |
    `aliased` (a borrowed/shared reference the caller does not own) | `forward`
    (returns the result of `callee`) | `none` (no owned return)."""

    kind: str = "none"
    arg: int = -1
    callee: str = ""


@dataclass(frozen=True)
class MethodSkeleton:
    key: str  # canonical signature key (stable, collision-free — open question 2)
    params: tuple[ParamSkeleton, ...] = ()
    ret: ReturnSkeleton = field(default_factory=ReturnSkeleton)
    file: str = "?"
    line: int = 0


# --- the solved summary (the MOS artifact) ----------------------------------

@dataclass(frozen=True)
class ParamSummary:
    index: int
    name: str
    disposable: bool
    transfer: Transfer
    escapes: bool


@dataclass(frozen=True)
class MethodSummary:
    key: str
    params: tuple[ParamSummary, ...]
    returns: str  # "fresh" | "aliasOf:<i>" | "aliased" | "none" | "unknown"
    file: str = "?"
    line: int = 0
    source: str = "inferred"  # inferred | bcl | annotation | heuristic

    def to_dict(self) -> dict[str, object]:
        """The detached `summaries[]` serialization (see the note's §6)."""
        return {
            "method": self.key,
            "file": self.file,
            "line": self.line,
            "source": self.source,
            "params": [
                {"index": p.index, "name": p.name, "disposable": p.disposable,
                 "transfer": p.transfer.value, "escapes": p.escapes}
                for p in self.params
            ],
            "returns": {"owned": self.returns},
        }


# A parameter is resolved by `.index` (its logical `ParamSkeleton.index`), never by
# tuple offset: a skeleton may list only the disposable/interesting params, so a
# wrapper `Create(cmd, reader)` can carry just index 1.
ParamKey = tuple[str, int]  # (method key, logical parameter index)

# `None` is the lattice bottom ⊥ ("no evidence yet") used only as the fixpoint seed
# on a recursive edge. It never escapes a solved summary — it is mapped to `no` at
# finalization (a parameter nothing demonstrably consumes is kept = borrowed).
def _join_opt(a: Transfer | None, b: Transfer | None) -> Transfer | None:
    """`join` lifted to the bottom-extended lattice: ⊥ (None) is the identity."""
    if a is None:
        return b
    if b is None:
        return a
    return join(a, b)


def _sccs(adj: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's SCCs, returned bottom-up (every component precedes its callers).

    Iterative (no Python recursion limit on deep call graphs). Tarjan emits each
    component only after all components it depends on, so the natural output order
    is exactly the reverse-topological order the summary fixpoint wants: a callee's
    summary is final before any caller reads it; only same-SCC callees are still
    mid-iteration. Adjacency is sorted so the result (and the cap-free log) is
    deterministic regardless of input ordering."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in adj:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work: list[tuple[str, Iterator[str]]] = [(root, iter(sorted(adj[root])))]
        while work:
            node, it = work[-1]
            descended = False
            for w in it:  # the iterator is stored in `work`, so it resumes here
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj[w]))))
                    descended = True
                    break
                if w in on_stack:
                    low[node] = min(low[node], index[w])
            if descended:
                continue
            if low[node] == index[node]:  # component root
                comp: list[str] = []
                while True:
                    x = stack.pop()
                    on_stack.discard(x)
                    comp.append(x)
                    if x == node:
                        break
                out.append(comp)
            work.pop()
            if work:  # propagate this node's low-link up to its DFS parent
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out


def _call_graph(sk: dict[str, MethodSkeleton]) -> dict[str, set[str]]:
    """Dependency edges M -> callees whose summaries M's summary reads: every
    first-party callee a param forwards to, plus a forwarded return target."""
    adj: dict[str, set[str]] = {k: set() for k in sk}
    for k, skel in sk.items():
        deps = adj[k]
        for p in skel.params:
            for a in p.paths:
                if a.kind == "forward" and a.callee in sk:
                    deps.add(a.callee)
        if skel.ret.kind == "forward" and skel.ret.callee in sk:
            deps.add(skel.ret.callee)
    return adj


def solve_with_log(skeletons: Iterable[MethodSkeleton]) -> tuple[
        dict[str, MethodSummary], list[str]]:
    """Resolve every method's MOS by a summary fixpoint over the call graph's SCC
    condensation.

    Returns (summaries-by-key, unresolved-log). The log names every forward that
    crosses an extern (unsummarized) boundary — the only place a transfer or return
    degrades to `unknown`. There is no depth cap and so no silent truncation: the
    condensation makes the work linear, and recursion is solved, not cut off."""
    sk: dict[str, MethodSkeleton] = {}
    for s in skeletons:
        if s.key in sk:
            # Key collision-freedom is an open design question (note's §10 q2). Silently
            # keeping the last duplicate would corrupt the call graph and make summaries
            # depend on input order — fail fast instead.
            raise ValueError(f"duplicate MethodSkeleton key: {s.key}")
        sk[s.key] = s

    unresolved: set[str] = set()
    param_val: dict[ParamKey, Transfer] = {}  # finalized disposable-param transfers

    def lookup(callee: str, arg: int, cur: dict[ParamKey, Transfer | None]) -> Transfer | None:
        """The current transfer of callee param `arg` (resolve by `.index`): a final
        value for a callee in a lower SCC, the live iterate for one in the current
        SCC (possibly ⊥), `no` for a non-disposable, `unknown` past an extern edge."""
        skel = sk.get(callee)
        if skel is None:
            unresolved.add(f"{callee}#{arg} (extern, no summary)")
            return Transfer.UNKNOWN
        p = next((q for q in skel.params if q.index == arg), None)
        if p is None:
            return Transfer.UNKNOWN  # callee has no such logical param
        if not p.disposable:
            return Transfer.NO
        keyp = (callee, arg)
        if keyp in param_val:
            return param_val[keyp]
        if keyp in cur:
            return cur[keyp]  # same-SCC member, mid-fixpoint (may be ⊥)
        return Transfer.UNKNOWN  # unreachable under a correct topo order; fail closed

    def contrib(a: PathAction, cur: dict[ParamKey, Transfer | None]) -> Transfer | None:
        if a.kind in ("dispose", "adopt", "return"):
            return Transfer.MUST  # ownership left the caller on this path
        if a.kind == "borrow":
            return Transfer.NO
        if a.kind == "forward":
            return lookup(a.callee, a.arg, cur)
        return Transfer.UNKNOWN

    def transfer_of(key: str, index: int,
                    cur: dict[ParamKey, Transfer | None]) -> Transfer | None:
        p = next(q for q in sk[key].params if q.index == index)
        if not p.paths:
            return Transfer.NO  # nothing happens to it -> kept (borrowed)
        acc: Transfer | None = None
        for a in p.paths:
            acc = _join_opt(acc, contrib(a, cur))
        return acc

    # --- param transfers: bottom-up, per-SCC least fixpoint on the lattice -------
    for comp in _sccs(_call_graph(sk)):
        members: list[ParamKey] = [
            (k, p.index) for k in comp for p in sk[k].params if p.disposable
        ]
        if not members:
            continue
        cur: dict[ParamKey, Transfer | None] = dict.fromkeys(members)  # seed ⊥ (None)
        changed = True
        while changed:  # monotone ascent on a height-3 lattice: converges fast
            changed = False
            for m in members:
                new = transfer_of(m[0], m[1], cur)
                if new != cur[m]:
                    cur[m] = new
                    changed = True
        for m in members:  # ⊥ (no evidence) finalizes as `no` (kept/borrowed)
            v = cur[m]
            param_val[m] = v if v is not None else Transfer.NO

    # --- returns: a memoized, cycle-safe chase along forward-return edges --------
    ret_val: dict[str, str] = {}

    def resolve_return(key: str, visiting: frozenset[str]) -> str:
        if key in ret_val:
            return ret_val[key]  # context-insensitive: a return has one forward target
        r = sk[key].ret
        if r.kind == "fresh":
            v = "fresh"
        elif r.kind == "aliasOf":
            v = f"aliasOf:{r.arg}"
        elif r.kind == "aliased":
            v = "aliased"
        elif r.kind == "none":
            v = "none"  # explicit no-owned-return
        elif r.kind == "forward":
            if r.callee not in sk:
                unresolved.add(f"return {r.callee} (extern, no summary)")
                v = "unknown"
            elif r.callee in visiting:
                v = "unknown"  # return-forward cycle: no ground to stand on
            else:
                inner = resolve_return(r.callee, visiting | {key})
                # `inner` aliasOf:<i> aliases one of the *callee's* params; remapping it
                # to OUR args needs the call's argument mapping, which the skeleton does
                # not carry yet (the obligation-identity model, D5.4). Never propagate a
                # wrong index — degrade to unknown (precision-safe: nothing aliased at
                # lowering). fresh / aliased / none / unknown propagate as-is.
                v = "unknown" if inner.startswith("aliasOf:") else inner
        else:
            v = "unknown"  # an unrecognised kind fails closed, never silently "none"
        ret_val[key] = v
        return v

    out: dict[str, MethodSummary] = {}
    for key, skel in sk.items():
        params = tuple(
            ParamSummary(
                p.index, p.name, p.disposable,
                param_val.get((key, p.index), Transfer.NO) if p.disposable else Transfer.NO,
                p.escapes,
            )
            for p in skel.params
        )
        returns = resolve_return(key, frozenset())
        out[key] = MethodSummary(key, params, returns, skel.file, skel.line)
    return out, sorted(unresolved)


def solve(skeletons: Iterable[MethodSkeleton]) -> dict[str, MethodSummary]:
    """Convenience wrapper around :func:`solve_with_log` dropping the unresolved log."""
    return solve_with_log(skeletons)[0]
