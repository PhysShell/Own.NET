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
