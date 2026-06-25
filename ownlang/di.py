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


def _consumed_suffix(ctor_type: str, file: str, line: int) -> str:
    """The ` [consumed by the '<impl>' constructor at <file>:<line>]` tail a captive finding
    appends so it names **both** the registration site (its primary anchor) and the *consuming
    constructor* where the capture is introduced (P-006 open question #1). The owner named is
    the **implementation** type whose ctor it is — for an interface registration that is the
    impl, never the (ctor-less) service interface (Codex). Empty when the ctor location is
    unknown (older extractor / hand-authored facts); the type name is dropped (not guessed)
    when only the location is known, so the message always degrades cleanly."""
    if line < 1:
        return ""
    owner = (f"the '{ctor_type}' constructor"
             if ctor_type and ctor_type != "?" else "the constructor")
    return f" [consumed by {owner} at {file}:{line}]"


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
    # service types this class resolves BY HAND from an injected `IServiceProvider`
    # (`GetService<T>()` / `GetRequiredService<T>()`) — the service-locator pattern. For a
    # SINGLETON the injected provider is the root container, so a transient `IDisposable`
    # resolved this way is tracked to app shutdown: DI004. Off the registration graph (it is
    # a call site, not a ctor edge); declared LAST, after `weak_deps`, for the same reason.
    root_resolves: tuple[str, ...] = ()
    # the **consuming constructor** of this service's implementation — the ctor that injects
    # the captive dependency (P-006 open question #1). `file`/`line` above point at the
    # *registration* site; these point at the *code* where the capture is introduced, so a
    # captive finding can name both. Declared LAST (positional-contract safe), default unknown.
    ctor_file: str = "?"
    ctor_line: int = 0
    # the IMPLEMENTATION type that owns that constructor. For an interface registration
    # (`AddSingleton<IFoo, Foo>`) `name` is the service `IFoo` (no ctor), but the consuming
    # ctor is `Foo`'s — so the finding must name `Foo`, not the interface (Codex). Empty when
    # unknown, in which case the suffix names "the constructor" without a (wrong) type.
    ctor_type: str = ""
    # for DI004 (service-location): where each `root_resolves` type was resolved by hand —
    # `(type, file, line)` triples for the `GetService<T>()` / `GetRequiredService<T>()` call
    # site. The consumer of a DI004 leak is this call site (not a ctor), so the finding anchors
    # at it; optional presentation metadata, declared LAST (positional-contract safe).
    root_resolve_sites: tuple[tuple[str, str, int], ...] = ()
    # service types this class resolves from a scope it CREATES (`IServiceScopeFactory.
    # CreateScope()` / an injected provider's `.CreateScope()`) and then CACHES into a FIELD —
    # the "scope-per-operation fix" done wrong (DI005). The scope is disposed at the end of the
    # operation, so a cached scoped service both dangles (use-after-dispose) and is promoted to
    # the singleton's application lifetime. Off the registration graph (a call site + a field
    # store), gated on SINGLETON + cached type SCOPED in the core. Declared LAST (positional
    # contract safe), with its cache-site metadata after it.
    scope_cached: tuple[str, ...] = ()
    # for DI005: where each `scope_cached` type was cached — `(type, file, line)` of the field
    # assignment, the finding's anchor (the leak is that store). Optional, declared LAST.
    scope_cache_sites: tuple[tuple[str, str, int], ...] = ()


@dataclass(frozen=True)
class CaptiveDependency:
    """A singleton capturing a scoped service, with the dependency path that
    reaches it (singleton -> ... -> captured)."""

    singleton: str
    captured: str
    path: tuple[str, ...]
    file: str
    line: int
    consumed_file: str = "?"
    consumed_line: int = 0
    consumed_type: str = ""

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' captures scoped service "
                f"'{self.captured}' (captive dependency: {chain})"
                + _consumed_suffix(self.consumed_type, self.consumed_file, self.consumed_line))


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
                            file=s.file, line=s.line,
                            consumed_file=s.ctor_file, consumed_line=s.ctor_line,
                            consumed_type=s.ctor_type))
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
    consumed_file: str = "?"
    consumed_line: int = 0
    consumed_type: str = ""

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' weakly captures scoped service "
                f"'{self.captured}' (WeakReference): '{self.captured}' is still resolved "
                f"from the root provider and promoted to application lifetime — the weak "
                f"reference avoids pinning it for the GC but does not fix the "
                f"captive-dependency lifetime violation ({chain})"
                + _consumed_suffix(self.consumed_type, self.consumed_file, self.consumed_line))


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
                        file=s.file, line=s.line,
                        consumed_file=s.ctor_file, consumed_line=s.ctor_line,
                        consumed_type=s.ctor_type))
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
    consumed_file: str = "?"
    consumed_line: int = 0
    consumed_type: str = ""

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        return (f"singleton '{self.singleton}' captures transient IDisposable "
                f"'{self.captured}': it is promoted to application lifetime and "
                f"disposed only when the root provider is disposed ({chain})"
                + _consumed_suffix(self.consumed_type, self.consumed_file, self.consumed_line))


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
                        file=s.file, line=s.line,
                        consumed_file=s.ctor_file, consumed_line=s.ctor_line,
                        consumed_type=s.ctor_type))
                if dep not in visited:
                    visited.add(dep)
                    stack.append((dep, npath))
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.captured))
    return findings


@dataclass(frozen=True)
class ExplicitRootResolution:
    """A singleton that resolves a transient `IDisposable` BY HAND from its injected
    **root** `IServiceProvider` — `GetService<T>()` / `GetRequiredService<T>()` (DI004, the
    service-locator-from-root anti-pattern). For a singleton the injected provider *is* the
    root container; the root tracks every `IDisposable` it resolves and disposes them only at
    application shutdown, so each such call accumulates a transient that its `transient`
    registration says should be short-lived — an unbounded leak the registration graph cannot
    see (it is a call site, not a constructor edge). The disposable may be the resolved type
    itself or a transient it drags in (the root builds the whole transient subtree); `path`
    is the service-location chain (singleton -> resolved -> ... -> disposable)."""

    singleton: str
    resolved: str
    path: tuple[str, ...]
    file: str
    line: int
    # the GetService/GetRequiredService call site that hand-resolved the entry type — DI004's
    # actual consumer (the leak *is* this call), so the bridge makes it the finding's PRIMARY
    # anchor; `file`/`line` (the registration site) become the secondary. Unknown -> 0.
    resolved_file: str = "?"
    resolved_line: int = 0

    @property
    def message(self) -> str:
        chain = " -> ".join(self.path)
        # the call site is the primary anchor (set by the bridge); name the registration site
        # (the secondary) in the tail when both it and the call site are known.
        reg = (f" [singleton registered at {self.file}:{self.line}]"
               if self.resolved_line >= 1 and self.line >= 1 else "")
        return (f"singleton '{self.singleton}' resolves transient IDisposable "
                f"'{self.resolved}' by hand from its injected root IServiceProvider "
                f"(GetService/GetRequiredService — the service-locator anti-pattern): the "
                f"root provider tracks every IDisposable it resolves and frees them only at "
                f"application shutdown, so each call leaks a transient that should be "
                f"scope-lived — resolve it from an IServiceScope instead ({chain}){reg}")


def find_explicit_root_resolutions(
        services: list[Service]) -> list[ExplicitRootResolution]:
    """Return every transient `IDisposable` a singleton resolves by hand from its injected
    root `IServiceProvider` (DI004). Only **singletons** are considered: a singleton's
    injected provider is the root container, whereas a scoped/transient service's injected
    provider is its request scope (which disposes what it resolves — no leak, so it is left
    silent). The extractor records only resolutions whose receiver is the injected provider
    itself, never a scope's `.ServiceProvider`, so the service-locator-from-root pattern is
    isolated from the correct scope-resolution pattern.

    From each resolved type, walk the STRONG transient graph exactly as DI003 does, but rooted
    at the service-location call site instead of a constructor edge: the root provider builds
    the resolved type's whole transient subtree, so a transient `IDisposable` reached directly
    (`GetRequiredService<Disposable>()`) or through a non-disposable transient wrapper
    (`GetRequiredService<Mid>()` where `Mid` depends on a transient `IDisposable`) is tracked
    to app shutdown and reported. A scoped edge is not followed (resolving scoped from the root
    is DI001's concern / a runtime scope-validation error); a singleton edge is its own pass.
    Cycles are guarded."""
    by_name = {s.name: s for s in services}
    findings: list[ExplicitRootResolution] = []
    for s in services:
        if s.lifetime != SINGLETON:
            continue
        # the hand-resolution call site for each entry type (path[1]) — the DI004 consumer.
        sites = {t: (f, ln) for (t, f, ln) in s.root_resolve_sites}
        reported: set[str] = set()
        visited: set[str] = set()
        # DFS rooted at each explicitly resolved type, following the transient deps the root
        # provider builds and tracks (DI003's DFS, entered at the resolution call site).
        stack: list[tuple[str, tuple[str, ...]]] = [
            (t, (s.name, t)) for t in s.root_resolves]
        while stack:
            cur, path = stack.pop()
            node = by_name.get(cur)
            if node is None or node.lifetime != TRANSIENT:
                continue  # only transients are root-built/tracked (scoped is DI001's)
            if node.disposable and cur not in reported:
                reported.add(cur)
                # the call site is where the ENTRY type (path[1]) was hand-resolved, even when
                # the leaked disposable is dragged in transitively below it.
                rf, rl = sites.get(path[1], ("?", 0)) if len(path) >= 2 else ("?", 0)
                findings.append(ExplicitRootResolution(
                    singleton=s.name, resolved=cur, path=path,
                    file=s.file, line=s.line, resolved_file=rf, resolved_line=rl))
            if cur not in visited:
                visited.add(cur)
                for dep in node.deps:   # the root builds the transient's deps too
                    stack.append((dep, (*path, dep)))
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.resolved))
    return findings


@dataclass(frozen=True)
class ScopeCachedCaptive:
    """A singleton that resolves a **scoped** service from a scope it CREATES
    (`IServiceScopeFactory.CreateScope()`) and then **caches it into a field** (DI005).
    The scope-per-operation pattern is the *correct* fix for a DI001 captive — but only
    when the resolved service is used within the scope and discarded. Caching it into a
    field defeats that twice over: the field outlives the `using` scope, so the cached
    instance is used after the scope (and the service) is disposed (use-after-dispose),
    and it lives for the singleton's application lifetime — the captive is back, hidden
    behind the API that was supposed to fix it. The static surface "sees the fix"
    (`CreateScope`) and would otherwise stay silent, which is exactly what makes this
    worth a dedicated check."""

    singleton: str
    captured: str
    file: str
    line: int
    # the field-assignment call site where the scope-resolved service was cached — DI005's
    # consumer (the leak is that store), so the bridge anchors the finding here; the
    # registration `file`/`line` become the secondary. Unknown -> 0.
    cached_file: str = "?"
    cached_line: int = 0

    @property
    def message(self) -> str:
        reg = (f" [singleton registered at {self.file}:{self.line}]"
               if self.cached_line >= 1 and self.line >= 1 else "")
        return (f"singleton '{self.singleton}' caches scoped service '{self.captured}', "
                f"resolved from a scope it creates, into a field: the scope is disposed when "
                f"the operation ends, so the cached instance dangles (use-after-dispose) and "
                f"is promoted to application lifetime — the captive the scope was meant to "
                f"avoid. Resolve it inside the scope per use and do not cache it{reg}")


def find_scope_cached_captives(
        services: list[Service]) -> list[ScopeCachedCaptive]:
    """Return every scoped service a singleton resolves from a scope it creates and caches
    into a field (DI005). Only **singletons** are considered (a scoped/transient consumer's
    cached value lives no longer than its own short scope — no promotion). A cached type that
    is `scoped` in the registration graph is the captive; a cached `singleton`/`transient`
    type is not this violation (a singleton is shareable; a transient cached in a field is the
    DI003/DI004 promotion family, surfaced there). The extractor records only values cached
    into a FIELD off a self-created scope — a value used within the scope and discarded (the
    correct pattern) produces no `scope_cached` entry, so it stays silent."""
    by_name = {s.name: s for s in services}
    findings: list[ScopeCachedCaptive] = []
    for s in services:
        if s.lifetime != SINGLETON:
            continue
        sites = {t: (f, ln) for (t, f, ln) in s.scope_cache_sites}
        reported: set[str] = set()
        for dep in s.scope_cached:
            node = by_name.get(dep)
            if node is None or node.lifetime != SCOPED or dep in reported:
                continue
            reported.add(dep)
            cf, cl = sites.get(dep, ("?", 0))
            findings.append(ScopeCachedCaptive(
                singleton=s.name, captured=dep, file=s.file, line=s.line,
                cached_file=cf, cached_line=cl))
    findings.sort(key=lambda f: (f.file, f.line, f.singleton, f.captured))
    return findings
