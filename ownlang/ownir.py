"""
OwnIR fact bridge (P-001 v0): C# leak facts -> the existing OwnLang core.

A Roslyn extractor (frontend/roslyn/, CI-only) scans real C# and emits *facts* in
the spec's vocabulary; this module ingests them, routes them through the proven
checker, and maps the verdict back to the original C# location. The core stays a
single checker — we do not reimplement it in C# (a second checker would drift).

OwnIR schema (JSON)::

    {
      "ownir_version": 0,
      "module": "WpfApp",
      "components": [
        {
          "name": "CustomerViewModel",
          "file": "CustomerViewModel.cs",
          "subscriptions": [
            {"event": "bus.CustomerChanged", "handler": "OnCustomerChanged",
             "line": 12, "released": false},
            {"event": "_timer.Tick", "handler": "OnTick", "line": 18,
             "released": false, "resource": "timer"}
          ]
        }
      ]
    }

Each entry in `subscriptions` (historically named — it is really the list of
owned-resource records) is an owned resource, discriminated by an optional
`resource` field:

  - "subscription" (default): `event +=` acquires, a matching `-=` releases;
    tag `[resource: subscription token]`.
  - "timer": a started `DispatcherTimer`/`Timer` whose `Tick`/`Elapsed` handler
    is never `-=`'d or `Stop()`ped; tag `[resource: timer]`.
  - "disposable": an `IDisposable` field the class `new`s and never `Dispose()`s
    (optional `type` names the field's declared type); tag
    `[resource: disposable field]`.
  - "subscribe": a `X.Subscribe(...)` whose `IDisposable` result is ignored (a
    bare statement, not captured/disposed) — always a leak; tag
    `[resource: subscription token]`.
  - "local-disposable": a local the method `new`s of an `IDisposable` type,
    never disposed and not guarded by `using` (and not returned/passed out);
    tag `[resource: disposable]`.
  - "pool": an `ArrayPool`/`MemoryPool` buffer `Rent`ed but never `Return`ed;
    tag `[resource: pooled buffer]`.
  - "unresolved-subscription": a `+=` whose left side could not be bound to an
    event (its declaring type is an unreferenced external assembly). NOT an owned
    resource — it is skipped by the lowering and surfaced separately as an
    advisory OWN050 "leakage analysis skipped" note, never a leak (P-014 Tier A).

An unreleased entry is the core's OWN001 (owned-but-not-released) at the C#
`line`. The `resource`/`type` fields are additive and optional, so they do NOT
bump `ownir_version`: an older core just reads every entry as a subscription.
Region escape (OWN014) is later (see docs/proposals/P-004).

An optional top-level `services` array carries the DI registration graph for the
DI001 captive-dependency check (P-006) — a separate core analysis (ownlang/di.py)
over who is registered with which lifetime and who they depend on::

    "services": [
      {"name": "EmailSender", "lifetime": "singleton", "deps": ["AppDbContext"],
       "file": "Startup.cs", "line": 12},
      {"name": "AppDbContext", "lifetime": "scoped", "deps": []}
    ]

A singleton that reaches a scoped service (directly, or through a transient) is a
DI001 finding at its registration site. The block is additive/optional too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .ast_nodes import (
    Acquire,
    FnDecl,
    Let,
    Module,
    Release,
    ResourceDecl,
    ResourceMember,
    Stmt,
)
from .di import LIFETIMES as DI_LIFETIMES
from .di import Service, find_captive_dependencies
from .diagnostics import Severity

# The OwnIR schema version this core understands. Bump it whenever the fact
# vocabulary changes incompatibly; the extractor stamps the same number so a
# mismatched extractor/core pair fails loudly (see load()) instead of silently
# mis-reading facts.
OWNIR_VERSION = 0


class OwnIRError(ValueError):
    """A malformed or unmappable OwnIR fact set. Carries a human message; the
    driver turns it into a clear one-line error rather than a traceback."""


def _esc_data(s: str) -> str:
    """Escape a GitHub workflow-command message (the text after `::`). Per the
    Actions command spec, only `%`, CR and LF are special there."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(s: str) -> str:
    """Escape a GitHub workflow-command property value (`file=`, `title=`).
    Property values additionally treat `:` and `,` as separators."""
    return _esc_data(s).replace(":", "%3A").replace(",", "%2C")


_PRELUDE = (
    'resource Subscription {\n'
    '    acquire Subscribe\n'
    '    release Dispose\n'
    '    kind "subscription token"\n'
    '}\n'
    'resource Timer {\n'
    '    acquire Start\n'
    '    release Stop\n'
    '    kind "timer"\n'
    '}\n'
    'resource Disposable {\n'
    '    acquire New\n'
    '    release Dispose\n'
    '    kind "disposable field"\n'
    '}\n'
    'resource PooledBuffer {\n'
    '    acquire Rent\n'
    '    release Return\n'
    '    kind "pooled buffer"\n'
    '}\n'
)

# OwnIR resource kinds the bridge knows how to lower: (own resource type to
# acquire, human kind tag the finding carries). `event +=` is a Subscription; a
# `Tick`/`Elapsed` handler on a started timer is a Timer (the running timer
# strong-refs the handler's owner); an `IDisposable` field the class `new`s is a
# Disposable it owns; an `ArrayPool`/`MemoryPool` `Rent` is a PooledBuffer that
# must be `Return`ed. Unknown values fall back to Subscription.
_RESOURCES = {
    "subscription": ("Subscription", "subscription token"),
    "subscribe": ("Subscription", "subscription token"),
    "timer": ("Timer", "timer"),
    "disposable": ("Disposable", "disposable field"),
    "local-disposable": ("Disposable", "disposable"),
    "pool": ("PooledBuffer", "pooled buffer"),
}


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    code: str
    component: str
    event: str
    handler: str
    message: str
    kind: str = "subscription token"
    # an advisory note (e.g. OWN050 "leakage analysis skipped") rather than a leak
    # verdict: rendered as a warning and excluded from the exit code.
    advisory: bool = False

    def render(self, severity: str = "error") -> str:
        return (f"{self.file}:{self.line}: {severity}: [{self.code}] "
                f"{self.message} [resource: {self.kind}]")

    def render_github(self, severity: str = "error") -> str:
        """A GitHub Actions workflow annotation. Printed on a CI step's stdout,
        GitHub renders it inline on the PR diff at the C# location. `severity`
        is the annotation level (`error`/`warning`); `title` carries the OWN
        code; the message keeps the [resource:] tag."""
        msg = f"[{self.code}] {self.message} [resource: {self.kind}]"
        return (f"::{severity} file={_esc_prop(self.file)},line={self.line},"
                f"title={_esc_prop(self.code)}::{_esc_data(msg)}")

    def render_msbuild(self, severity: str = "error") -> str:
        """The canonical MSBuild diagnostic format `file(line): error CODE: msg`.
        `dotnet build` and the Visual Studio Error List parse exactly this, so
        the findings surface in-IDE without a Roslyn analyzer — one checker, not
        a second one reimplemented in C#. `severity` picks `error`/`warning` so a
        build can show them advisory instead of failing."""
        return (f"{self.file}({self.line}): {severity} {self.code}: "
                f"{self.message} [resource: {self.kind}]")


def render_finding(f: Finding, fmt: str, severity: str = "error") -> str:
    """Render a finding in one of the supported surfaces: `human` (the default
    CLI line), `github` (CI annotation), or `msbuild` (VS Error List). `severity`
    is a presentation choice — the finding is still the core's verdict; it only
    controls whether the host shows it as an error (default) or a warning."""
    if fmt == "github":
        return f.render_github(severity)
    if fmt == "msbuild":
        return f.render_msbuild(severity)
    return f.render(severity)


def load(path: str) -> dict[str, Any]:
    """Load and shape-check an OwnIR facts file (it is external input — a
    malformed file should fail with a clear error, not a deep traceback)."""
    with open(path, encoding="utf-8") as f:
        try:
            result: Any = json.load(f)
        except json.JSONDecodeError as e:
            raise OwnIRError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(result, dict):
        raise OwnIRError("OwnIR root must be a JSON object")
    # version gate first: a vocabulary mismatch makes every later shape-check
    # meaningless, so reject it up front with an actionable message. An absent
    # field is treated as the current version (the only producers that omit it
    # predate versioning, i.e. are v0 by definition).
    ver = result.get("ownir_version", OWNIR_VERSION)
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise OwnIRError(f"OwnIR 'ownir_version' must be an integer, got {ver!r}")
    if ver != OWNIR_VERSION:
        raise OwnIRError(
            f"OwnIR facts are schema v{ver}, but this core understands "
            f"v{OWNIR_VERSION}. Build the Roslyn extractor and the Python core "
            f"from the same commit — the OwnIR fact vocabulary changed between "
            f"the version that produced this file and the one reading it.")
    comps = result.get("components", [])
    if not isinstance(comps, list) or not all(isinstance(c, dict) for c in comps):
        raise OwnIRError("OwnIR 'components' must be a JSON array of objects")
    for c in comps:
        subs = c.get("subscriptions", [])
        if not isinstance(subs, list) or not all(isinstance(s, dict) for s in subs):
            raise OwnIRError("each component's 'subscriptions' must be objects")
        for s in subs:
            r = s.get("resource", "subscription")
            if not isinstance(r, str):
                raise OwnIRError(
                    f"subscription 'resource' must be a string, got {r!r}")
            t = s.get("type")
            if t is not None and not isinstance(t, str):
                raise OwnIRError(
                    f"subscription 'type' must be a string, got {t!r}")
    # Optional DI registration graph (DI001 — captive dependency, P-006). Additive
    # and optional: an older core simply ignores it.
    svcs = result.get("services", [])
    if not isinstance(svcs, list) or not all(isinstance(s, dict) for s in svcs):
        raise OwnIRError("OwnIR 'services' must be a JSON array of objects")
    for s in svcs:
        lt = s.get("lifetime")
        if lt not in DI_LIFETIMES:
            raise OwnIRError(
                f"service 'lifetime' must be one of {sorted(DI_LIFETIMES)}, "
                f"got {lt!r}")
        name = s.get("name")
        if not isinstance(name, str) or not name:
            raise OwnIRError("service 'name' must be a non-empty string")
        deps = s.get("deps", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise OwnIRError("service 'deps' must be an array of strings")
        if not isinstance(s.get("file", "?"), str):
            raise OwnIRError("service 'file' must be a string")
        ln = s.get("line", 0)
        if not isinstance(ln, int) or isinstance(ln, bool):
            raise OwnIRError("service 'line' must be an integer")
    return result


def to_own(facts: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Lower OwnIR facts to a synthetic `.own` module (a readable ownership
    sketch of the C#) plus a map from each synthetic handle to its source fact.

    Each subscription becomes `let <handle> = acquire Subscription();`, with a
    `release` iff the extractor found a matching unsubscribe. Handles are globally
    unique so a diagnostic naming one maps straight back to its C# location."""
    handles: dict[str, dict[str, Any]] = {}
    lines = [f"module {facts.get('module', 'Extracted')}", "", _PRELUDE]
    gid = 0
    components = facts.get("components", [])
    if not isinstance(components, list):
        raise OwnIRError("OwnIR 'components' must be a JSON array")
    for comp in components:
        if not isinstance(comp, dict):
            raise OwnIRError("each OwnIR component must be a JSON object")
        cname = comp.get("name", f"Component{gid}")
        lines.append(f"fn {cname}() {{")
        subscriptions = comp.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise OwnIRError("component 'subscriptions' must be a JSON array")
        for sub in subscriptions:
            if not isinstance(sub, dict):
                raise OwnIRError("each subscription must be a JSON object")
            # An "unresolved-subscription" marker is not an owned resource (the
            # extractor could not bind the LHS to an event). Do not lower it to an
            # acquire — that would become a phantom OWN001 leak. It is surfaced as
            # an advisory OWN050 note by _unresolved_findings instead.
            if sub.get("resource") == "unresolved-subscription":
                continue
            handle = f"sub_{gid}"
            gid += 1
            handles[handle] = {**sub, "component": cname,
                               "file": comp.get("file", "?")}
            rtype, _ = _RESOURCES.get(sub.get("resource", "subscription"),
                                      _RESOURCES["subscription"])
            lines.append(f"    let {handle} = acquire {rtype}();")
            if sub.get("released"):
                lines.append(f"    release {handle};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines), handles


def _prelude_resources() -> list[ResourceDecl]:
    """The owned-resource declarations the lowered functions acquire — the AST twin
    of `_PRELUDE`. Members mirror the text prelude; `kind` carries the
    `[resource: <kind>]` tag a finding surfaces."""
    return [
        ResourceDecl("Subscription",
                     [ResourceMember("acquire", "Subscribe", 0),
                      ResourceMember("release", "Dispose", 0)], 0,
                     kind="subscription token"),
        ResourceDecl("Timer",
                     [ResourceMember("acquire", "Start", 0),
                      ResourceMember("release", "Stop", 0)], 0, kind="timer"),
        ResourceDecl("Disposable",
                     [ResourceMember("acquire", "New", 0),
                      ResourceMember("release", "Dispose", 0)], 0,
                     kind="disposable field"),
        ResourceDecl("PooledBuffer",
                     [ResourceMember("acquire", "Rent", 0),
                      ResourceMember("release", "Return", 0)], 0,
                     kind="pooled buffer"),
    ]


def to_module(facts: dict[str, Any]) -> tuple[Module, dict[str, dict[str, Any]]]:
    """Build the core `Module` AST **directly** from OwnIR facts — no `.own` source
    text and no re-parse (P-016 B0a; the round-trip `to_own` + `parse` has existed
    since P-001). Mirrors `to_own`'s lowering exactly: each owned-resource fact
    becomes `let <handle> = acquire <Resource>();`, with a `release` iff the
    extractor found a matching teardown. Returns the Module plus the handle->fact
    map; a diagnostic names a handle via its symbol `origin` (`<name>#<line>`,
    cfg.py), which maps straight back to the C# location."""
    handles: dict[str, dict[str, Any]] = {}
    functions: list[FnDecl] = []
    gid = 0
    components = facts.get("components", [])
    if not isinstance(components, list):
        raise OwnIRError("OwnIR 'components' must be a JSON array")
    for comp in components:
        if not isinstance(comp, dict):
            raise OwnIRError("each OwnIR component must be a JSON object")
        cname = comp.get("name", f"Component{gid}")
        body: list[Stmt] = []
        subscriptions = comp.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise OwnIRError("component 'subscriptions' must be a JSON array")
        for sub in subscriptions:
            if not isinstance(sub, dict):
                raise OwnIRError("each subscription must be a JSON object")
            # an unresolved-subscription marker is not an owned resource — it is
            # surfaced as an advisory OWN050 note, never lowered (see to_own).
            if sub.get("resource") == "unresolved-subscription":
                continue
            handle = f"sub_{gid}"
            gid += 1
            handles[handle] = {**sub, "component": cname,
                               "file": comp.get("file", "?")}
            rtype, _ = _RESOURCES.get(sub.get("resource", "subscription"),
                                      _RESOURCES["subscription"])
            line = _as_int(sub.get("line", 0))
            body.append(Let(handle, Acquire(rtype, [], line), line))
            if sub.get("released"):
                body.append(Release(handle, line))
        functions.append(FnDecl(cname, [], None, body, 0))
    return (Module(str(facts.get("module", "Extracted")),
                   resources=_prelude_resources(), functions=functions),
            handles)


def _handle_of(diag: object) -> str | None:
    """The synthetic handle (`sub_N`) a diagnostic is about, recovered from its
    structured `subject` (`name#line`) — NOT by scraping the human message. Each
    acquire stamps `subject` in cfg.lower_let; None means the diagnostic carries
    no subject identity at all."""
    subject = getattr(diag, "subject", None)
    if not isinstance(subject, str) or not subject:
        return None
    return subject.split("#", 1)[0]


def check_facts(facts: dict[str, Any]) -> list[Finding]:
    """Run the core checker over the lowered facts and return findings mapped
    back to their original C# locations (v0: the `event += without -=` leak).

    The fact->handle->diagnostic round-trip is fully ours: every error the core
    reports on the lowered module MUST attribute to a known subscription handle.
    If one does not, the lowering has drifted from the core (or the core grew a
    diagnostic the bridge has not been taught to map) — we raise rather than
    silently dropping a real finding, since a swallowed leak is the worst
    outcome for a leak checker."""
    # P-016 B0a: build the core Module AST DIRECTLY from facts and check it — no
    # `.own` source text and no re-parse (the round-trip that existed since P-001).
    # `to_own` is kept as a human-readable sketch / test aid. Imported here to avoid
    # a module-level cycle (ownir is a leaf consumer).
    from .__main__ import check_module

    mod, handles = to_module(facts)
    diags = check_module(mod)

    findings: list[Finding] = []
    for d in diags:
        if d.severity != Severity.ERROR:
            continue
        sub = handles.get(_handle_of(d) or "")
        if sub is None:
            raise OwnIRError(
                f"internal: the core reported [{d.code}] on the lowered facts "
                f"that the bridge cannot map back to a C# subscription "
                f"(subject={getattr(d, 'subject', None)!r}, "
                f"message={d.message!r}). The OwnIR lowering has drifted from "
                f"the core; teach the bridge this diagnostic rather than "
                f"dropping the finding.")
        event = sub.get("event", "?")
        handler = sub.get("handler", "?")
        component = sub["component"]
        rkind = sub.get("resource", "subscription")
        _, kind = _RESOURCES.get(rkind, _RESOURCES["subscription"])
        if rkind == "timer":
            message = (f"timer '{event}' (handler '{handler}') is started but "
                       f"never stopped or detached — the running timer keeps "
                       f"'{component}' alive (leak)")
        elif rkind == "disposable":
            typ = sub.get("type")
            of_type = f" (type '{typ}')" if typ else ""
            message = (f"IDisposable field '{event}'{of_type} is never "
                       f"disposed — its owner '{component}' leaks it (leak)")
        elif rkind == "local-disposable":
            typ = sub.get("type")
            of_type = f" (type '{typ}')" if typ else ""
            message = (f"local IDisposable '{event}'{of_type} is created but "
                       f"never disposed (leak)")
        elif rkind == "subscribe":
            message = (f"the result of '{event}' is ignored — the IDisposable "
                       f"subscription is never disposed, leaking "
                       f"'{component}' (leak)")
        elif rkind == "pool":
            message = (f"pooled buffer '{event}' is rented but never returned "
                       f"to the pool (leak)")
        else:
            message = (f"event '{event}' is subscribed (handler '{handler}') "
                       f"but never unsubscribed — the source keeps "
                       f"'{component}' alive (leak)")
        findings.append(Finding(
            file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
            component=component, event=event, handler=handler,
            message=message, kind=kind))

    # DI001 (captive dependency): a separate core analysis over the registration
    # graph, not the acquire/release model — the bridge just routes the facts to
    # it (see ownlang/di.py). Findings carry the registration site as file/line.
    findings.extend(_di_findings(facts))

    # OWN050 (P-014 Tier A): a `+=` whose declaring type could not be resolved —
    # an advisory "leakage analysis skipped" note, never a leak. Routed through
    # this side path so it bypasses the ERROR-only diagnostic mapping above.
    findings.extend(_unresolved_findings(facts))

    findings.sort(key=lambda f: (f.file, f.line, f.code))
    return findings


def _as_int(v: Any) -> int:
    """A non-throwing int coercion: load() already validates `line`, but
    check_facts may be called directly (tests, embedders) on un-validated facts,
    so a bad `line` degrades to 0 rather than raising a bare ValueError."""
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _di_findings(facts: dict[str, Any]) -> list[Finding]:
    """Run the DI captive-dependency check over the facts' `services` graph and
    map each result to a DI001 Finding at its registration site."""
    raw = facts.get("services", [])
    if not isinstance(raw, list):
        return []
    services = [
        Service(
            name=str(s.get("name", "?")),
            lifetime=str(s.get("lifetime", "")),
            deps=tuple(s.get("deps", [])),
            file=str(s.get("file", "?")),
            line=_as_int(s.get("line", 0)),
        )
        for s in raw if isinstance(s, dict)
    ]
    return [
        Finding(
            file=c.file, line=c.line, code="DI001",
            component=c.singleton, event=c.captured, handler="",
            message=c.message, kind="DI lifetime")
        for c in find_captive_dependencies(services)
    ]


def _unresolved_findings(facts: dict[str, Any]) -> list[Finding]:
    """Surface every "unresolved-subscription" marker as an advisory OWN050
    finding (P-014 Tier A): the extractor saw a `+=` that looks like an event
    subscription but could not bind the left side to an event — its declaring
    type is an unreferenced external assembly. We do not guess a leak; we say,
    honestly, that it was not checked. Advisory: rendered as a warning and
    excluded from the exit code (see __main__.cmd_ownir)."""
    out: list[Finding] = []
    comps = facts.get("components", [])
    if not isinstance(comps, list):
        return out
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        cfile = comp.get("file", "?")
        cname = comp.get("name", "?")
        subs = comp.get("subscriptions", [])
        if not isinstance(subs, list):
            continue
        for sub in subs:
            if not isinstance(sub, dict) or \
                    sub.get("resource") != "unresolved-subscription":
                continue
            event = sub.get("event", "?")
            handler = sub.get("handler", "?")
            message = (f"cannot verify '{event}' — its declaring type is an "
                       f"unresolved reference (build the project or pass "
                       f"references); leakage analysis skipped")
            out.append(Finding(
                file=cfile, line=_as_int(sub.get("line", 0)), code="OWN050",
                component=cname, event=event, handler=handler, message=message,
                kind="unresolved reference", advisory=True))
    return out
