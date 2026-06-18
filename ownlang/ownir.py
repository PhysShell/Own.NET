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
  - "capture": a *tokenless* strong subscription (`event += handler` with no
    token to release) whose event SOURCE provably outlives the subscriber. This
    is NOT an acquire/release owned resource — it lowers to the lifetime engine's
    `subscribe self to <source>` (ownlang/lifetimes.py) with the source's region,
    so a source that strictly outlives the captured component yields OWN014 (the
    region escape — the captured object is promoted to the longer lifetime and
    leaks). The source's lifetime class is the entry's `source`: a `static`
    (process-lived) event is the longest region. A source of unknown/shorter
    lifetime is left conservative (no finding) — the region model is precise where
    the token model (`resource: "subscription"`) only warns. A `capture` with a
    matching `-=` (`released: true`) is mitigated and stays silent (the source no
    longer holds self on close), just as a released token subscription nets to a
    balanced acquire/release. Tag `[resource: subscription token]`.
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
A `capture` entry instead routes through the lifetime/region engine and surfaces
as OWN014 (region escape) when its source provably outlives — see docs/proposals/
P-004 and docs/lifetimes.md (the C# facts now reach the region core, not only the
`.own` DSL).

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
    If,
    Let,
    LifetimeDecl,
    Module,
    Param,
    Release,
    ResourceDecl,
    ResourceMember,
    Return,
    Stmt,
    Subscribe,
    TypeRef,
    Use,
    While,
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

# --- P-004 region escape (the `capture` resource kind) ----------------------
# A `capture` is a tokenless strong subscription routed NOT through the
# acquire/release ownership model but through the lifetime/region engine
# (ownlang/lifetimes.py): the captured component lives in a short region, its
# event source in a longer one, and `subscribe self to <source>` promotes the
# component to the longer lifetime -> OWN014. The map below turns the extractor's
# `source` kind into the source's region; only *provably longer* sources are
# mapped, so an unknown/shorter source produces no node and no finding (the region
# model is conservative — no false positive). `_SUBSCRIBER_REGION` is the shorter
# region every captured component lives in, declared strictly inside every mapped
# source region by `_CAPTURE_LIFETIMES` (added to the module once when any capture
# is present). Slice #1 models the one provable case — a process-lived `static`
# event; further source classes (singletons, parent scopes) are a later slice.
_SUBSCRIBER_REGION = "Subscriber"
_CAPTURE_SOURCE_REGIONS = {
    "static": "Process",   # a static event (e.g. SystemEvents.*) lives for the
                           # whole process -> strictly longer than any subscriber.
}
_CAPTURE_LIFETIMES = [
    LifetimeDecl("Process", None, 0),
    LifetimeDecl(_SUBSCRIBER_REGION, "Process", 0),   # Subscriber strictly < Process
]


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
    # P-004 tiering: the intrinsic level when the source's lifetime cannot be
    # proven — "warning" for a subscription whose event SOURCE is an injected
    # dependency of unknown lifetime, None for a provable leak (shown at the host's
    # --severity, default error). Still a leak verdict (counts in the exit code);
    # only the displayed level differs.
    severity: str | None = None

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
    # Optional per-method flow bodies (P-016 B0b/B2 — local IDisposable
    # acquire/use/release over a CFG). Additive/optional; an older core ignores it.
    fns = result.get("functions", [])
    if not isinstance(fns, list) or not all(isinstance(f, dict) for f in fns):
        raise OwnIRError("OwnIR 'functions' must be a JSON array of objects")
    return result


def to_own(facts: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Lower OwnIR facts to a synthetic `.own` module (a readable ownership
    sketch of the C#) plus a map from each synthetic handle to its source fact.

    Each subscription becomes `let <handle> = acquire Subscription();`, with a
    `release` iff the extractor found a matching unsubscribe. Handles are globally
    unique so a diagnostic naming one maps straight back to its C# location."""
    handles: dict[str, dict[str, Any]] = {}
    gid = 0
    any_capture = False
    comp_lines: list[str] = []
    components = facts.get("components", [])
    if not isinstance(components, list):
        raise OwnIRError("OwnIR 'components' must be a JSON array")
    for comp in components:
        if not isinstance(comp, dict):
            raise OwnIRError("each OwnIR component must be a JSON object")
        cname = comp.get("name", f"Component{gid}")
        subscriptions = comp.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise OwnIRError("component 'subscriptions' must be a JSON array")
        cap_params: list[str] = []     # `<handle>: EventSource lifetime <region>`
        cap_handles: list[str] = []    # sources for `subscribe self to <handle>;`
        owned_lines: list[str] = []    # `let <handle> = acquire <R>();` (+ release)
        for sub in subscriptions:
            if not isinstance(sub, dict):
                raise OwnIRError("each subscription must be a JSON object")
            rkind = sub.get("resource", "subscription")
            # An "unresolved-subscription" marker is not an owned resource (the
            # extractor could not bind the LHS to an event). Do not lower it to an
            # acquire — that would become a phantom OWN001 leak. It is surfaced as
            # an advisory OWN050 note by _unresolved_findings instead.
            if rkind == "unresolved-subscription":
                continue
            # A `capture` is the tokenless region-escape shape: it does NOT acquire
            # a token (no OWN001); it lowers to `subscribe self to <source>` with
            # the source's region, so the lifetime engine reports OWN014 when the
            # source provably outlives. An unmapped (unknown/shorter) source stays
            # conservative — no node, no finding. Mirrors to_module exactly.
            if rkind == "capture":
                # a released capture (matching `-=`) is mitigated -> silent; skip
                # it, mirroring to_module (and a released token subscription).
                src = sub.get("source")
                region = _CAPTURE_SOURCE_REGIONS.get(src) \
                    if isinstance(src, str) else None
                if region is None or sub.get("released"):
                    continue
                handle = f"cap_{gid}"
                gid += 1
                handles[handle] = {**sub, "component": cname,
                                   "file": comp.get("file", "?")}
                cap_params.append(f"{handle}: EventSource lifetime {region}")
                cap_handles.append(handle)
                any_capture = True
                continue
            handle = f"sub_{gid}"
            gid += 1
            handles[handle] = {**sub, "component": cname,
                               "file": comp.get("file", "?")}
            rtype, _ = _RESOURCES.get(rkind, _RESOURCES["subscription"])
            owned_lines.append(f"    let {handle} = acquire {rtype}();")
            if sub.get("released"):
                owned_lines.append(f"    release {handle};")
        sig = ", ".join(cap_params)
        lt = f" lifetime {_SUBSCRIBER_REGION}" if cap_handles else ""
        comp_lines.append(f"fn {cname}({sig}){lt} {{")
        comp_lines.extend(owned_lines)
        for handle in cap_handles:
            comp_lines.append(f"    subscribe self to {handle};")
        comp_lines.append("}")
        comp_lines.append("")
    # The region order the captures reference — emitted once, only when needed, so
    # a capture-free fact set lowers to byte-identical output as before.
    lifetime_lines: list[str] = []
    if any_capture:
        for d in _CAPTURE_LIFETIMES:
            lifetime_lines.append(f"lifetime {d.name};" if d.longer is None
                                  else f"lifetime {d.name} < {d.longer};")
        lifetime_lines.append("")
    lines = [f"module {facts.get('module', 'Extracted')}", "", _PRELUDE,
             *lifetime_lines, *comp_lines]
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
    any_capture = False
    components = facts.get("components", [])
    if not isinstance(components, list):
        raise OwnIRError("OwnIR 'components' must be a JSON array")
    for comp in components:
        if not isinstance(comp, dict):
            raise OwnIRError("each OwnIR component must be a JSON object")
        cname = comp.get("name", f"Component{gid}")
        body: list[Stmt] = []
        params: list[Param] = []      # capture sources, carrying their region
        fn_lt: str | None = None      # the subscriber region, set iff a capture
        subscriptions = comp.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise OwnIRError("component 'subscriptions' must be a JSON array")
        for sub in subscriptions:
            if not isinstance(sub, dict):
                raise OwnIRError("each subscription must be a JSON object")
            rkind = sub.get("resource", "subscription")
            # an unresolved-subscription marker is not an owned resource — it is
            # surfaced as an advisory OWN050 note, never lowered (see to_own).
            if rkind == "unresolved-subscription":
                continue
            # P-004 region escape: a `capture` is a tokenless strong subscription
            # whose source provably outlives the subscriber. Lower it to the
            # lifetime engine (`subscribe self to <source>` + the source's region)
            # -> OWN014, NOT to an acquire/release token. The source becomes a
            # param carrying its (longer) region; the function carries the shorter
            # subscriber region. A source of unknown/shorter lifetime stays
            # conservative (no node emitted, hence no finding). cfg.lower_stmt
            # treats Subscribe as a no-op and a non-resource param as PLAIN, so
            # this is inert for the OWN001 ownership pass — only check_lifetimes
            # reads it.
            if rkind == "capture":
                # A `capture` whose subscription IS torn down (a matching `-=`,
                # `released: true`) is mitigated: the source no longer holds self
                # on close, so there is no escape — skip it (silent), exactly as a
                # released token subscription nets to a balanced acquire/release.
                src = sub.get("source")
                region = _CAPTURE_SOURCE_REGIONS.get(src) \
                    if isinstance(src, str) else None
                if region is None or sub.get("released"):
                    continue
                handle = f"cap_{gid}"
                gid += 1
                handles[handle] = {**sub, "component": cname,
                                   "file": comp.get("file", "?")}
                line = _as_int(sub.get("line", 0))
                params.append(Param(handle, TypeRef("EventSource", False, False, 0),
                                    0, lifetime=region))
                body.append(Subscribe(handle, line))
                fn_lt = _SUBSCRIBER_REGION
                any_capture = True
                continue
            handle = f"sub_{gid}"
            gid += 1
            handles[handle] = {**sub, "component": cname,
                               "file": comp.get("file", "?")}
            rtype, _ = _RESOURCES.get(rkind, _RESOURCES["subscription"])
            line = _as_int(sub.get("line", 0))
            body.append(Let(handle, Acquire(rtype, [], line), line))
            if sub.get("released"):
                body.append(Release(handle, line))
        functions.append(FnDecl(cname, params, None, body, 0, lifetime=fn_lt))
    # P-016 B0b/B2: per-method flow bodies for local IDisposables (acquire / use /
    # release / if / return over a CFG). The core checks them path-sensitively
    # (OWN001 not-released-on-all-paths, OWN002 use-after-release, OWN003 double-
    # release) — beyond the flat detectors. Experimental/additive at v0; graduation
    # bumps OWNIR_VERSION.
    loc = [0]
    raw_fns = facts.get("functions", [])
    if isinstance(raw_fns, list):
        for fn in raw_fns:
            if not isinstance(fn, dict):
                continue
            fname = str(fn.get("name", f"Fn{loc[0]}"))
            ffile = str(fn.get("file", "?"))
            nodes = fn.get("body", [])
            nodes = nodes if isinstance(nodes, list) else []
            # which locals have ANY release in the body (any branch) — lets the OWN001
            # wording distinguish "never disposed" (no release at all) from "not
            # disposed on every path" (released on some branch, leaked on another).
            released = _released_vars(nodes)
            fbody = _lower_flow(nodes, ffile, fname, handles, loc, {}, released)
            functions.append(FnDecl(fname, [], None, fbody, 0))
    return (Module(str(facts.get("module", "Extracted")),
                   resources=_prelude_resources(), functions=functions,
                   lifetimes=list(_CAPTURE_LIFETIMES) if any_capture else []),
            handles)


def _released_vars(nodes: list[Any]) -> set[str]:
    """The set of local names with at least one `release` op anywhere in a flow body
    (recursing into `if` branches and `while` bodies). Used to word an OWN001 as
    "never disposed" (the name is absent here, so it was released on no path) vs "not
    on every path" (the name is present, but the core still found a leaking path)."""
    out: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        if op == "release":
            v = n.get("var")
            if isinstance(v, str):
                out.add(v)
        elif op == "if":
            for branch in ("then", "else"):
                b = n.get(branch, [])
                if isinstance(b, list):
                    out |= _released_vars(b)
        elif op == "while":
            b = n.get("body", [])
            if isinstance(b, list):
                out |= _released_vars(b)
    return out


def _lower_flow(nodes: list[Any], ffile: str, fname: str,
                handles: dict[str, dict[str, Any]], loc: list[int],
                localmap: dict[str, str],
                released_vars: set[str]) -> list[Stmt]:
    """Lower one OwnIR flow body (B0b/B2) into core statements. acquire/use/release/
    return reference a C# local by name (`var`); `if` carries `then`/`else`
    sub-bodies; `while` carries a `body` (a back-edge — the core's worklist fixpoint
    checks it, P-016 A1). Each acquire gets a globally-unique handle `loc_<n>` (so a
    finding maps back to the C# local); `localmap` resolves later references within
    the same function and its branches/loops."""
    body: list[Stmt] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        line = _as_int(n.get("line", 0))
        if op == "acquire":
            handle = f"loc_{loc[0]}"
            loc[0] += 1
            name = str(n.get("var", "?"))
            localmap[name] = handle
            handles[handle] = {"file": ffile, "line": line, "event": name,
                               "component": fname, "resource": "flow-local",
                               "ever_released": name in released_vars}
            body.append(Let(handle, Acquire("Disposable", [], line), line))
        elif op == "use":
            h = localmap.get(str(n.get("var")))
            if h is not None:
                body.append(Use(h, line))
        elif op == "release":
            h = localmap.get(str(n.get("var")))
            if h is not None:
                body.append(Release(h, line))
        elif op == "return":
            v = n.get("var")
            h = localmap.get(str(v)) if v is not None else None
            body.append(Return(h, line))
        elif op == "if":
            tn = n.get("then", [])
            en = n.get("else", [])
            then_b = _lower_flow(tn if isinstance(tn, list) else [],
                                 ffile, fname, handles, loc, localmap, released_vars)
            else_b = _lower_flow(en if isinstance(en, list) else [],
                                 ffile, fname, handles, loc, localmap, released_vars)
            body.append(If("?", then_b, else_b, line))
        elif op == "while":
            bn = n.get("body", [])
            body_b = _lower_flow(bn if isinstance(bn, list) else [],
                                 ffile, fname, handles, loc, localmap, released_vars)
            body.append(While("?", body_b, line))
    return body


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
        if rkind == "flow-local":
            # P-016 B0b/B2: path-sensitive local-IDisposable verdicts. The code is
            # the core's (OWN001/002/003/009); phrase it for the C# local.
            name = event
            if d.code == "OWN001":
                # OWN001 spans "released on 0 paths" and "released on some but not all"
                # — the core's "not on every path". Word it from whether the flow body
                # released this local anywhere (ever_released): no release at all reads
                # as "never disposed"; a partial release as "not on every path". Same
                # leak verdict either way.
                msg = (f"IDisposable local '{name}' may not be disposed on every path (leak)"
                       if sub.get("ever_released")
                       else f"IDisposable local '{name}' is never disposed (leak)")
            else:
                msg = {
                    "OWN002": f"IDisposable local '{name}' is used after it is disposed",
                    "OWN003": f"IDisposable local '{name}' is disposed more than once",
                    "OWN009": f"IDisposable local '{name}' may be used after disposal on some path",
                }.get(d.code, f"IDisposable local '{name}': {d.message}")
            findings.append(Finding(
                file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
                component=component, event=name, handler="", message=msg,
                kind="disposable"))
            continue
        if rkind == "capture":
            # OWN014 region escape (P-004): the lifetime engine proved the event
            # SOURCE outlives the subscriber, so the strong (tokenless) subscription
            # promotes '{component}' to the source's longer lifetime and it can
            # never be collected. This is the `event += handler` fire-and-forget;
            # the mitigation — a disposable token released on close — would be a
            # `resource: "subscription"` (OWN001), not this. A provable leak, so it
            # stays error-tier (severity None).
            src = sub.get("source", "?")
            origin = ("a static (process-lived) event source" if src == "static"
                      else f"a longer-lived source ('{src}')")
            message = (f"event '{event}' is subscribed (handler '{handler}') to "
                       f"{origin} that outlives '{component}'; the strong "
                       f"subscription promotes '{component}' to the source's "
                       f"lifetime, so it can never be collected — a region escape "
                       f"(leak, no release path)")
            findings.append(Finding(
                file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
                component=component, event=event, handler=handler,
                message=message, kind="subscription token"))
            continue
        _, kind = _RESOURCES.get(rkind, _RESOURCES["subscription"])
        # P-004 tiering: only the plain `event += handler` leak (the else branch
        # below) grades its severity from the source's proven lifetime; every other
        # resource is a provable leak and stays at the host's --severity (error).
        fsev: str | None = None
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
            # The source's lifetime decides the severity (the extractor stamps
            # `source`): a static event is process-lived -> a provable leak (error);
            # an injected dependency (ctor param / field / property) has UNKNOWN
            # lifetime -> a warning ("may outlive this", honest until ownership
            # modelling can prove it). A lambda handler has no `-=` handle, so it
            # could never be detached even on purpose — worth spelling out.
            lam = (" — and being an inline lambda it has no '-=' handle, so it "
                   "could never be detached") if sub.get("lambda") else ""
            if sub.get("source") == "injected":
                fsev = "warning"
                message = (f"event '{event}' is subscribed (handler '{handler}') "
                           f"but never unsubscribed; its source is an injected "
                           f"dependency whose lifetime is unknown, so it may "
                           f"outlive and keep '{component}' alive (possible "
                           f"leak{lam})")
            else:
                message = (f"event '{event}' is subscribed (handler '{handler}') "
                           f"but never unsubscribed — the source keeps "
                           f"'{component}' alive (leak{lam})")
        findings.append(Finding(
            file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
            component=component, event=event, handler=handler,
            message=message, kind=kind, severity=fsev))

    # DI001 (captive dependency): a separate core analysis over the registration
    # graph, not the acquire/release model — the bridge just routes the facts to
    # it (see ownlang/di.py). Findings carry the registration site as file/line.
    findings.extend(_di_findings(facts))

    # OWN050 (P-014 Tier A): a `+=` whose declaring type could not be resolved —
    # an advisory "leakage analysis skipped" note, never a leak. Routed through
    # this side path so it bypasses the ERROR-only diagnostic mapping above.
    findings.extend(_unresolved_findings(facts))

    # A resource that leaks on more than one exit yields one core OWN001 per exit:
    # e.g. the try-lowering injects an exceptional exit before each may-throw
    # statement, so a local never disposed leaks on BOTH that exit and the normal
    # fall-through. For a flow-local every such diagnostic remaps to the same acquire
    # line (sub["line"]) above, collapsing to byte-identical findings — keep one.
    # The key includes `line`, so genuinely distinct leak sites stay distinct.
    seen: set[tuple[Any, ...]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.file, f.line, f.code, f.component, f.event, f.handler,
               f.message, f.kind, f.advisory, f.severity)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    findings = deduped

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
