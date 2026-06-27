"""Reactive-effect stability analysis — EFF001, the effect storm (P-020).

Not every lifecycle bug leaks memory; some leak *requests*. A React `useEffect`
re-runs whenever one of its declared dependencies changes **identity**. A
dependency that is an object/array literal created in render scope gets a brand
new identity on every render, so the effect re-fires every render — and if the
effect does IO (a `fetch`), that is a render-rate request storm (the Cloudflare
12-Sep-2025 shape).

This is NOT the acquire/release leak model the rest of the core checks
(EFF003/004/005 -> OWN001 are that). It is a deterministic property of the
**render-scope binding graph**: which names are bound to fresh-identity
expressions, how those names derive from one another, and which effect depends on
which name. So — exactly like `di.py` over the DI registration graph — it lives in
its own small analyzer the OwnIR bridge feeds facts to. One checker, several
analyses; the frontend still only *produces facts* (what each binding's initialiser
syntactically is, the dep list, whether the body does IO) and the **core decides**
stability. The frontend must NOT pre-judge "unstable" — that gating call is here.

The stability lattice (join = worst case), computed to a fixpoint over the binding
references so a chain `a = {..}; b = a; c = b` carries instability to `c`:

  STABLE   < UNKNOWN < UNSTABLE

  - object / array / new literal in render scope        -> UNSTABLE (fresh identity)
  - useMemo / useCallback / useRef result               -> STABLE   (memoised)
  - prop / state / primitive / import / fn / param       -> STABLE   (referential)
  - identifier / spread / ternary (a derivation)         -> join of what it references
  - call (an opaque return value)                        -> UNKNOWN  (conservative)

An effect is an **EFF001 storm** iff it performs IO AND at least one of its
dependencies is provably UNSTABLE. UNKNOWN never fires (low false positives is the
whole point — P-020); a `useMemo`/primitive dep clears it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# stability lattice
STABLE = "stable"
UNKNOWN = "unknown"
UNSTABLE = "unstable"
_RANK = {STABLE: 0, UNKNOWN: 1, UNSTABLE: 2}

# a plain identifier or member chain (`tenantId`, `props.id`) — referentially stable
# when it has no render-scope binding; anything else (a literal/ctor/call) is not.
_IDENT = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")

# initialiser kinds the frontend can observe syntactically
_FRESH = frozenset({"object", "array", "new"})         # fresh identity every render
_MEMOISED = frozenset({"memo", "callback", "ref"})     # useMemo/useCallback/useRef
_REFERENTIAL = frozenset({"prop", "state", "primitive", "import", "fn", "param"})
_DERIVED = frozenset({"ident", "spread", "ternary", "derive"})  # join over refs
# "call" and any unknown kind fall through to UNKNOWN (opaque return identity).


def _join(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass(frozen=True)
class Binding:
    """One render-scope binding: a `name` bound to an initialiser of kind `init`,
    which may reference other binding names (`refs`) for derivations. `line` is the
    declaration site (the finding's evidence hop)."""

    name: str
    init: str
    refs: tuple[str, ...] = ()
    line: int = 0


@dataclass(frozen=True)
class Effect:
    """One `useEffect`: the `component` it lives in, the `deps` it declares, whether
    its body does `io`, the render-scope `bindings` visible to it, and the call
    `line` (the finding's anchor — where the effect re-fires)."""

    component: str
    deps: tuple[str, ...]
    io: bool
    bindings: tuple[Binding, ...]
    file: str = "?"
    line: int = 0


@dataclass(frozen=True)
class EffectStorm:
    """An EFF001 finding: `dep` (the unstable dependency) makes the effect re-run;
    `origin`/`origin_kind` name the binding whose fresh identity is the root cause
    (the same as `dep` for a direct literal, or an upstream one for a derivation)."""

    component: str
    dep: str
    origin: str
    origin_kind: str
    file: str
    line: int
    decl_line: int
    path: tuple[str, ...] = ()

    @property
    def _kind_phrase(self) -> str:
        return {
            "object": "an object literal",
            "array": "an array literal",
            "new": "a freshly constructed object",
        }.get(self.origin_kind, "a value with an unstable identity")

    @property
    def message(self) -> str:
        via = ""
        if len(self.path) > 1:
            via = f" (via {' -> '.join(self.path)})"
        root = (f"dependency '{self.dep}' is {self._kind_phrase} created in render "
                f"scope, so its identity changes on every render"
                if self.origin == self.dep else
                f"dependency '{self.dep}' derives from '{self.origin}', "
                f"{self._kind_phrase} created in render scope{via}, so its identity "
                f"changes on every render")
        return (f"effect re-runs on every render: {root}; the effect performs IO, "
                f"which can become a request storm — stabilise '{self.origin}' with "
                f"useMemo/useCallback (or move it out of render)")


class _Lattice:
    """Stability of each binding name, computed to a fixpoint over references with a
    cycle guard. Also records, for an UNSTABLE name, the upstream `origin` binding
    and the reference `path` that carried the instability (for the evidence slice)."""

    def __init__(self, bindings: list[Binding]) -> None:
        self._by_name = {b.name: b for b in bindings}
        self._stab: dict[str, str] = {}
        self._origin: dict[str, str] = {}
        self._path: dict[str, tuple[str, ...]] = {}

    def stability(self, name: str) -> str:
        return self._resolve(name, frozenset())[0]

    def origin(self, name: str) -> str:
        return self._origin.get(name, name)

    def path(self, name: str) -> tuple[str, ...]:
        return self._path.get(name, (name,))

    def _resolve(self, name: str, on_stack: frozenset[str]) -> tuple[str, str, tuple[str, ...]]:
        if name in self._stab:
            return self._stab[name], self._origin.get(name, name), self._path.get(name, (name,))
        b = self._by_name.get(name)
        if b is None:
            # A dep with no render-scope binding: a plain identifier or member chain
            # (`tenantId`, `props.id`) is a prop/state/global — referentially stable.
            # A non-identifier dep the frontend forwarded verbatim (`{}`, `new URL(x)`,
            # `f()`) is NOT provably stable — stay conservative (UNKNOWN, no finding)
            # rather than assert STABLE and silence a real fresh-identity storm.
            stab = STABLE if _IDENT.match(name) else UNKNOWN
            return stab, name, (name,)
        if name in on_stack:
            # an identity cycle (a = b; b = a): cannot prove unstable — stay safe.
            return UNKNOWN, name, (name,)
        stab, origin, path = self._classify(b, on_stack | {name})
        self._stab[name] = stab
        self._origin[name] = origin
        self._path[name] = path
        return stab, origin, path

    def _classify(self, b: Binding, on_stack: frozenset[str]) -> tuple[str, str, tuple[str, ...]]:
        if b.init in _FRESH:
            return UNSTABLE, b.name, (b.name,)
        if b.init in _MEMOISED or b.init in _REFERENTIAL:
            return STABLE, b.name, (b.name,)
        if b.init in _DERIVED:
            if not b.refs:
                return UNKNOWN, b.name, (b.name,)
            worst: str = STABLE
            worst_origin: str = b.name
            worst_path: tuple[str, ...] = (b.name,)
            for r in b.refs:
                s, o, p = self._resolve(r, on_stack)
                if _RANK[s] > _RANK[worst]:
                    worst, worst_origin, worst_path = s, o, (b.name, *p)
            return worst, worst_origin, worst_path
        # "call" or any unrecognised kind: opaque identity -> conservative.
        return UNKNOWN, b.name, (b.name,)


def find_effect_storms(effects: list[Effect]) -> list[EffectStorm]:
    """Return every EFF001 effect storm: an IO effect with a provably UNSTABLE
    dependency. Deterministic; sorted by location. One storm per effect (the first
    unstable dep) — re-running once is the bug, the count of culprits is noise."""
    out: list[EffectStorm] = []
    for e in effects:
        if not e.io:
            continue
        lat = _Lattice(list(e.bindings))
        decl = {b.name: b.line for b in e.bindings}
        for dep in e.deps:
            if lat.stability(dep) != UNSTABLE:
                continue
            origin = lat.origin(dep)
            b = next((x for x in e.bindings if x.name == origin), None)
            out.append(EffectStorm(
                component=e.component, dep=dep, origin=origin,
                origin_kind=b.init if b else "object",
                file=e.file, line=e.line,
                decl_line=decl.get(origin, e.line), path=lat.path(dep)))
            break  # one finding per effect
    out.sort(key=lambda f: (f.file, f.line, f.dep))
    return out
