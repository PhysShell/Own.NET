"""
Lifetime-region analysis (the `lifetimes` module, slice #2).

This is the genuinely new analysis on top of the ownership/borrow core: it
reasons about *region escape* — the WPF "zombie ViewModel" theorem — rather than
about resource release within one scope.

Model
-----
`lifetime` declarations define regions with a strict partial order:

    lifetime App;
    lifetime Window < App;        // Window is strictly shorter-lived than App
    lifetime ViewModel < Window;

A function carries the lifetime of the object it sets up (`fn F(...) lifetime
ViewModel`), and its parameters carry the lifetime of the service they are
(`bus: EventBus lifetime App`). A `subscribe self to bus;` statement is a strong
capture: `bus` now holds a reference to the object.

Theorem (region escape)
-----------------------
If `self` has lifetime L_self and is strongly captured by a `source` of lifetime
L_source with **L_source strictly longer than L_self**, then `self` is promoted
to L_source: it stays reachable for the whole of the longer region and leaks.
That is OWN014. A capture by a source of equal-or-shorter lifetime is fine (no
promotion). The mitigation — a disposable subscription *token* released on close
— is the slice-#1 pattern (`acquire`/`release`, caught by OWN001 if dropped);
the tokenless `subscribe` here is exactly the fire-and-forget leak.

What this is NOT (yet)
----------------------
No cross-procedural points-to: `self`/`source` are the function's own scope and
its annotated parameters. Weak-reference policy as an explicit escape hatch, and
ingestion of real C#, are later slices (see docs/lifetimes.md).
"""

from __future__ import annotations

from collections.abc import Iterator

from . import ast_nodes as A
from .diagnostics import Diagnostic


def _iter_subscribes(stmts: list[A.Stmt]) -> Iterator[A.Subscribe]:
    """Yield every `subscribe` statement in a body, descending into branches."""
    for st in stmts:
        if isinstance(st, A.Subscribe):
            yield st
        elif isinstance(st, A.If):
            yield from _iter_subscribes(st.then_body)
            yield from _iter_subscribes(st.else_body)
        elif isinstance(st, A.BorrowBlock):
            yield from _iter_subscribes(st.body)


def _strictly_longer(decls: list[A.LifetimeDecl]) -> dict[str, set[str]]:
    """Map each region to the set of regions strictly longer-lived than it.

    `lifetime X < Y` means X is shorter than Y, i.e. Y is longer than X. We take
    the transitive closure so `ViewModel < Window < App` puts both Window and App
    in `longer['ViewModel']`."""
    direct: dict[str, set[str]] = {}
    for d in decls:
        direct.setdefault(d.name, set())
        if d.longer is not None:
            direct.setdefault(d.longer, set())
            direct[d.name].add(d.longer)
    longer: dict[str, set[str]] = {n: set() for n in direct}
    for start in direct:
        stack = list(direct[start])
        while stack:
            cur = stack.pop()
            if cur in longer[start]:
                continue
            longer[start].add(cur)
            stack.extend(direct.get(cur, ()))
    return longer


def check_lifetimes(mod: A.Module) -> list[Diagnostic]:
    """Region diagnostics for a module: structural validation of the lifetime
    order plus the per-function escape check. Empty when no lifetimes are used."""
    diags: list[Diagnostic] = []
    if not mod.lifetimes:
        return diags

    names: set[str] = set()
    for d in mod.lifetimes:
        if d.name in names:
            diags.append(Diagnostic(
                "OWN031", f"lifetime '{d.name}' is already defined", d.line))
        names.add(d.name)
    for d in mod.lifetimes:
        if d.longer is not None and d.longer not in names:
            diags.append(Diagnostic(
                "OWN030", f"undefined lifetime '{d.longer}'", d.line))

    longer = _strictly_longer(mod.lifetimes)
    # a cycle shows up as a region being strictly longer than itself.
    for d in mod.lifetimes:
        if d.name in longer.get(d.name, set()):
            diags.append(Diagnostic(
                "OWN036",
                f"lifetime '{d.name}' is part of a cyclic ordering "
                f"(it ends up strictly longer than itself)", d.line))

    for fn in mod.functions:
        diags.extend(_check_fn(fn, names, longer))
    return diags


def _check_fn(fn: A.FnDecl, names: set[str],
              longer: dict[str, set[str]]) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    # validate any annotations on this function, even if it has no subscribes.
    if fn.lifetime is not None and fn.lifetime not in names:
        out.append(Diagnostic(
            "OWN030", f"undefined lifetime '{fn.lifetime}'", fn.line))
    param_lt: dict[str, str] = {}
    for p in fn.params:
        if p.lifetime is None:
            continue
        if p.lifetime not in names:
            out.append(Diagnostic(
                "OWN030", f"undefined lifetime '{p.lifetime}'", p.line))
        else:
            param_lt[p.name] = p.lifetime

    self_lt = fn.lifetime if fn.lifetime in names else None
    for sub in _iter_subscribes(fn.body):
        src_lt = param_lt.get(sub.source)
        # skip when we cannot compare (no self lifetime, unknown/untagged source):
        # being conservative avoids false positives.
        if self_lt is None or src_lt is None:
            continue
        if src_lt in longer.get(self_lt, set()):
            out.append(Diagnostic(
                "OWN014",
                f"'{sub.source}' (lifetime '{src_lt}') outlives the captured "
                f"object '{fn.name}' (lifetime '{self_lt}'); the strong "
                f"subscription promotes '{fn.name}' to '{src_lt}' and it leaks "
                f"(no release path)", sub.line))
    return out
