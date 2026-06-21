"""DI lifetime analysis — DI001, captive dependency (P-006).

A **singleton** that depends — directly, or through **transient** services — on a
**scoped** service captures that scoped instance for the whole application
lifetime. The scoped service then outlives the scope it was meant to live in (a
"captive dependency"); in ASP.NET Core this is the classic *"Cannot consume
scoped service from singleton"* bug, and a `DbContext` held by a singleton is the
canonical example.

This is a deterministic, static-friendly property of the **registration graph**
(who is registered with which lifetime, and who they depend on) — not of the
acquire/release lifetime model the rest of the core checks. So it lives in its
own small analyzer that the OwnIR bridge feeds registration facts to: one
checker, several analyses (the frontend still only *produces facts*).

The rule (matching the .NET DI guidance):

  - singleton -> scoped                : captive (the edge itself is the bug)
  - singleton -> transient -> scoped   : captive (the transient is resolved by
                                          the singleton, so it is singleton-lived
                                          and drags the scoped along)
  - singleton -> singleton -> scoped   : NOT reported here — the *inner* singleton
                                          is the captor and is flagged on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

SINGLETON = "singleton"
SCOPED = "scoped"
TRANSIENT = "transient"
LIFETIMES = frozenset({SINGLETON, SCOPED, TRANSIENT})


@dataclass(frozen=True)
class Service:
    """One DI registration: a service `name`, its `lifetime`, and the service
    names it depends on (constructor injection). `disposable` is whether the
    implementation type is `IDisposable`/`IAsyncDisposable` (so its disposal is the
    container's concern). `file`/`line` point at the registration site so a finding
    lands there."""

    name: str
    lifetime: str
    deps: tuple[str, ...] = ()
    disposable: bool = False
    file: str = "?"
    line: int = 0
    # services injected via `WeakReference<T>` — held WEAKLY, so they are NOT strong
    # captive edges (DI001 must not see them), but a weakly-held scoped service is still
    # a lifetime-contract violation: DI002. Declared LAST so the positional constructor
    # contract (name, lifetime, deps, disposable, file, line) is preserved — callers pass
    # `disposable`/etc. positionally, so a new field before them would shift their meaning.
    weak_deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptiveDependency:
    """A singleton capturing a scoped service, with the dependency path that
    reaches it (singleton -> ... -> captured)."""

    singleton: str
    captured: str
    path: tuple[str, ...]
    file: str
    line: int

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' captures scoped service "
                f"'{self.captured}' (captive dependency: {chain})")


def find_captive_dependencies(services: list[Service]) -> list[CaptiveDependency]:
    """Return every captive dependency in the registration graph. For each
    singleton, walk its dependencies: an edge into a scoped service is a
    violation (reported on the singleton); transients are followed (a transient
    held by a singleton is itself singleton-lived); singletons are not followed
    (the inner singleton is reported on its own pass). Cycles are guarded."""
    by_name = {s.name: s for s in services}
    findings: list[CaptiveDependency] = []
    for s in services:
        if s.lifetime != SINGLETON:
            continue
        reported: set[str] = set()
        visited: set[str] = set()
        # DFS over the dependency chain rooted at this singleton.
        stack: list[tuple[str, tuple[str, ...]]] = [(s.name, (s.name,))]
        while stack:
            cur, path = stack.pop()
            node = by_name.get(cur)
            if node is None:
                continue
            for dep in node.deps:
                dnode = by_name.get(dep)
                if dnode is None:
                    continue
                npath = (*path, dep)
                if dnode.lifetime == SCOPED:
                    if dep not in reported:
                        reported.add(dep)
                        findings.append(CaptiveDependency(
                            singleton=s.name, captured=dep, path=npath,
                            file=s.file, line=s.line))
                    continue  # the violating edge is found; don't recurse past it
                if dnode.lifetime == TRANSIENT and dep not in visited:
                    visited.add(dep)
                    stack.append((dep, npath))
                # a singleton dependency is safe here (captor reported on its own)
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.captured))
    return findings


@dataclass(frozen=True)
class WeakCaptiveDependency:
    """A singleton that holds a **scoped** service via `WeakReference<T>` (DI002). A
    weak reference is the usual "fix" for the DI001 captive leak — it stops the
    singleton from pinning the scoped instance for the GC. But it does not fix the
    *lifetime contract*: the scoped service is still resolved from the root provider
    and lives for the application lifetime; the weak reference only hides the
    GC-retention symptom, not the captive cause (and may go dead under the consumer)."""

    singleton: str
    captured: str
    path: tuple[str, ...]
    file: str
    line: int

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' weakly captures scoped service "
                f"'{self.captured}' (WeakReference): '{self.captured}' is still resolved "
                f"from the root provider and promoted to application lifetime — the weak "
                f"reference avoids pinning it for the GC but does not fix the "
                f"captive-dependency lifetime violation ({chain})")


def find_weak_captive_dependencies(
        services: list[Service]) -> list[WeakCaptiveDependency]:
    """Return every scoped service a singleton reaches via `WeakReference<T>` (DI002).
    From each weak dependency, walk the STRONG dependency chain exactly as DI001 does: the
    weak edge enters a service the singleton holds weakly, and a scoped service it reaches —
    directly (`WeakReference<Scoped>`) or transitively through a weakly-held transient that
    strongly depends on it — is still root-resolved and app-lived, a lifetime-contract
    violation surfaced as a warning. Transients are followed (a transient resolved through
    the singleton drags its scoped dep along); a singleton edge is another singleton's own
    pass. Cycles are guarded. The weak entry edge keeps it off the DI001 strong graph."""
    by_name = {s.name: s for s in services}
    findings: list[WeakCaptiveDependency] = []
    for s in services:
        if s.lifetime != SINGLETON:
            continue
        reported: set[str] = set()
        visited: set[str] = set()
        # DFS rooted at the WEAK deps, then following STRONG transient edges (DI001-style).
        stack: list[tuple[str, tuple[str, ...]]] = [
            (dep, (s.name, dep)) for dep in s.weak_deps]
        while stack:
            cur, path = stack.pop()
            cnode = by_name.get(cur)
            if cnode is None:
                continue
            if cnode.lifetime == SCOPED:
                if cur not in reported:
                    reported.add(cur)
                    findings.append(WeakCaptiveDependency(
                        singleton=s.name, captured=cur, path=path,
                        file=s.file, line=s.line))
                continue  # the violating scoped edge is found; don't recurse past it
            if cnode.lifetime == TRANSIENT and cur not in visited:
                visited.add(cur)
                for d in cnode.deps:   # follow the transient's STRONG deps
                    stack.append((d, (*path, d)))
            # a singleton edge is safe here (the inner singleton is reported on its own pass)
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.captured))
    return findings


@dataclass(frozen=True)
class CapturedTransientDisposable:
    """A singleton that captures a transient `IDisposable` service (DI003): the
    transient is resolved from the root (via the singleton), promoted to the
    application lifetime, and disposed only when the root provider is disposed — held
    until the app exits, far longer than its `transient` registration implies."""

    singleton: str
    captured: str
    path: tuple[str, ...]
    file: str
    line: int

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' captures transient IDisposable "
                f"'{self.captured}': it is promoted to application lifetime and "
                f"disposed only when the root provider is disposed ({chain})")


def find_captured_transient_disposables(
        services: list[Service]) -> list[CapturedTransientDisposable]:
    """Return every transient `IDisposable` captured by a singleton (DI003). For each
    singleton, walk its dependency chain through transients (a transient held by a
    singleton is itself singleton-lived, resolved from the root); a transient that is
    `IDisposable` is reported — it is disposed only at root disposal (app exit). A
    scoped edge belongs to DI001 (not followed here); a singleton edge is another
    singleton's own pass. Cycles are guarded."""
    by_name = {s.name: s for s in services}
    findings: list[CapturedTransientDisposable] = []
    for s in services:
        if s.lifetime != SINGLETON:
            continue
        reported: set[str] = set()
        visited: set[str] = set()
        stack: list[tuple[str, tuple[str, ...]]] = [(s.name, (s.name,))]
        while stack:
            cur, path = stack.pop()
            node = by_name.get(cur)
            if node is None:
                continue
            for dep in node.deps:
                dnode = by_name.get(dep)
                if dnode is None or dnode.lifetime != TRANSIENT:
                    continue  # scoped -> DI001; singleton -> its own pass
                npath = (*path, dep)
                if dnode.disposable and dep not in reported:
                    reported.add(dep)
                    findings.append(CapturedTransientDisposable(
                        singleton=s.name, captured=dep, path=npath,
                        file=s.file, line=s.line))
                if dep not in visited:
                    visited.add(dep)
                    stack.append((dep, npath))
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.captured))
    return findings
