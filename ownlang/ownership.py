"""Interprocedural ownership summaries — P-005 D5, infra slice **D5.0**.

See [`docs/notes/d5-ownership-transfer.md`](../docs/notes/d5-ownership-transfer.md).

This module is pure **data + algorithm**: it computes a Method Ownership Summary
(MOS) for each first-party method from per-method *local evidence* (a "skeleton"
of what a body directly does with each disposable parameter and what it returns),
resolving the parts that depend on other methods' summaries via a **depth-capped
bottom-up resolution** over the call graph.

D5.0 deliberately does **nothing** to findings — no extractor wiring, no
behaviour change. It defines the summary vocabulary and the solver so the lattice
can be unit-tested in pure Python (the synthetic-flow discipline, lifted to the
effect level). Lowering a summary into the core's `consume`/`borrow`/`acquire`
vocabulary is D5.1+; the wrapper/alias (`aliasOf`) obligation-identity model is
D5.4 (see the note's §11).

The skeleton is the extractor-facing input; here it is hand-authored in tests.

Precision note: a parameter is reported `must`-transfer only when ownership leaves
the caller on **every** normal-return path the skeleton lists. A recursive forward
edge contributes *no* transfer evidence (the cycle is broken at `no`), and a chain
deeper than the cap, or a forward to an unsummarized (extern) callee, degrades to
`unknown` — never to a guessed `must`. That keeps the project's precision-first
stance: we only ever *claim* transfer when we can prove it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

# Default interprocedural forward-chain depth, matching CA2000's
# `max_interprocedural_method_call_chain` default. Beyond it, a forward degrades
# to `unknown` (and is logged) rather than spending unbounded work.
DEFAULT_CAP = 3


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


def _resolve_param(key: str, i: int, depth: int, stack: frozenset[str],
                   cap: int, sk: dict[str, MethodSkeleton],
                   capped: list[str]) -> Transfer:
    skel = sk.get(key)
    if skel is None:
        return Transfer.UNKNOWN
    # `i` is the callee's *logical* parameter index (`ParamSkeleton.index`), which
    # need not equal the tuple offset — a skeleton may list only the disposable /
    # interesting params, so a wrapper `Create(cmd, reader)` can carry just index 1.
    # Resolve by `.index`, never by position.
    p = next((q for q in skel.params if q.index == i), None)
    if p is None:
        return Transfer.UNKNOWN
    if not p.disposable:
        return Transfer.NO
    if not p.paths:
        return Transfer.NO  # nothing happens to it -> kept (borrowed)
    verdict: Transfer | None = None
    for a in p.paths:
        verdict = _path_verdict(a, depth, stack, cap, sk, capped) if verdict is None \
            else join(verdict, _path_verdict(a, depth, stack, cap, sk, capped))
    return verdict if verdict is not None else Transfer.NO


def _path_verdict(a: PathAction, depth: int, stack: frozenset[str], cap: int,
                  sk: dict[str, MethodSkeleton], capped: list[str]) -> Transfer:
    if a.kind in ("dispose", "adopt", "return"):
        return Transfer.MUST  # ownership left the caller on this path
    if a.kind == "borrow":
        return Transfer.NO
    if a.kind == "forward":
        if a.callee not in sk:
            return Transfer.UNKNOWN  # extern / unsummarized callee
        if depth + 1 >= cap:
            capped.append(f"{a.callee}#{a.arg} (depth {depth + 1} >= cap {cap})")
            return Transfer.UNKNOWN
        if a.callee in stack:
            return Transfer.NO  # recursion: this edge carries no transfer evidence
        return _resolve_param(a.callee, a.arg, depth + 1, stack | {a.callee},
                              cap, sk, capped)
    return Transfer.UNKNOWN


def _resolve_return(key: str, depth: int, stack: frozenset[str], cap: int,
                    sk: dict[str, MethodSkeleton], capped: list[str]) -> str:
    skel = sk.get(key)
    if skel is None:
        return "unknown"
    r = skel.ret
    if r.kind == "fresh":
        return "fresh"
    if r.kind == "aliasOf":
        return f"aliasOf:{r.arg}"
    if r.kind == "aliased":
        return "aliased"
    if r.kind == "forward":
        if r.callee not in sk:
            return "unknown"
        if depth + 1 >= cap:
            capped.append(f"return {r.callee} (depth {depth + 1} >= cap {cap})")
            return "unknown"
        if r.callee in stack:
            return "unknown"
        inner = _resolve_return(r.callee, depth + 1, stack | {r.callee}, cap, sk, capped)
        if inner.startswith("aliasOf:"):
            # `inner` aliases one of the *callee's* params; remapping it to one of
            # OUR args needs the call's argument mapping, which the skeleton does not
            # carry yet (it arrives with the obligation-identity model in D5.4). Until
            # then, never propagate a wrong index — degrade to unknown (precision-safe:
            # nothing is acquired/aliased at lowering).
            return "unknown"
        return inner  # fresh / aliased / none / unknown propagate as-is
    if r.kind == "none":
        return "none"  # explicit no-owned-return
    return "unknown"  # an unrecognised kind fails closed, never silently "none"


def solve_with_log(skeletons: Iterable[MethodSkeleton], *,
                   cap: int = DEFAULT_CAP) -> tuple[dict[str, MethodSummary], list[str]]:
    """Resolve every method's MOS from its skeleton plus its callees' skeletons.

    Returns (summaries-by-key, capped-log). The log names every forward that hit
    the depth cap, so a run can surface what it gave up on (no silent
    truncation)."""
    sk: dict[str, MethodSkeleton] = {}
    for s in skeletons:
        if s.key in sk:
            # Key collision-freedom is an open design question (note's §10 q2). Silently
            # keeping the last duplicate would corrupt the call graph and make summaries
            # depend on input order — fail fast instead.
            raise ValueError(f"duplicate MethodSkeleton key: {s.key}")
        sk[s.key] = s
    capped: list[str] = []
    out: dict[str, MethodSummary] = {}
    for key, skel in sk.items():
        params = tuple(
            ParamSummary(
                p.index, p.name, p.disposable,
                _resolve_param(key, p.index, 0, frozenset({key}), cap, sk, capped)
                if p.disposable else Transfer.NO,
                p.escapes,
            )
            for p in skel.params
        )
        returns = _resolve_return(key, 0, frozenset({key}), cap, sk, capped)
        out[key] = MethodSummary(key, params, returns, skel.file, skel.line)
    return out, capped


def solve(skeletons: Iterable[MethodSkeleton], *,
          cap: int = DEFAULT_CAP) -> dict[str, MethodSummary]:
    """Convenience wrapper around :func:`solve_with_log` dropping the cap log."""
    return solve_with_log(skeletons, cap=cap)[0]
