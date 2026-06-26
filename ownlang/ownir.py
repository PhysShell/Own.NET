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
    bare statement, not captured/disposed). Tiered by `source` like a `+=`: a
    self-rooted `this.WhenAnyValue(x => x.SelfProp)` chain (`source: "self"`) is a
    GC-collectible self-cycle, not a leak (silent); an `injected` source is a
    warning (unknown lifetime); a `static`/external/unknown source is a leak. Tag
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

The `services` graph also feeds the region engine (P-006 + P-004): a subscription
with `source: "injected"` may carry `source_type` (the source's declared type). If
that type is registered here, its DI lifetime IS a region — singleton (application)
> scoped > transient — so an injected subscription whose source provably outlives
the subscriber surfaces as OWN014 (the captive/zombie escape), and one proven
shorter-or-equal stays silent. An unresolved `source_type` keeps the honest OWN001
warning. This is how lifetimes the intra-procedural model cannot know locally reach
the region check — from the registration graph.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .ast_nodes import (
    Acquire,
    Call,
    Effect,
    EffectParam,
    Expr,
    ExternDecl,
    FnDecl,
    If,
    Let,
    LifetimeDecl,
    Module,
    Overspan,
    Param,
    Release,
    ResourceDecl,
    ResourceMember,
    Return,
    Stmt,
    Subscribe,
    TypeRef,
    Use,
    VarRef,
    While,
)
from .di import LIFETIMES as DI_LIFETIMES
from .di import (
    Service,
    find_captive_dependencies,
    find_captured_transient_disposables,
    find_explicit_root_resolutions,
    find_scope_cached_captives,
    find_weak_captive_dependencies,
)
from .diagnostics import TITLES, Severity
from .ownership import (
    MethodSkeleton,
    ParamSkeleton,
    PathAction,
    ReturnSkeleton,
    Transfer,
    solve,
)

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
# region an un-registered UI subscriber (a Window/VM the framework owns) lives in.
#
# P-006 + P-004 (DI-sourced escape): a DI-registered source's lifetime IS a region
# too. The .NET DI order — singleton (application) > scoped (request) > transient
# (per-resolution) — is the same kind of partial order, so an *injected*
# subscription whose source's REGISTERED lifetime strictly outlives the
# subscriber's is the same region escape (the captive/zombie case). A `singleton`
# shares the long `Process` region with a static event (both app/process-lived); a
# subscriber that is itself DI-registered carries its own region. The lifetimes the
# intra-procedural model could not know locally come from the registration graph —
# we only escalate when the source's lifetime is KNOWN there; an unregistered
# source keeps the honest OWN001 warning.
_SUBSCRIBER_REGION = "Subscriber"
_CAPTURE_SOURCE_REGIONS = {
    "static": "Process",   # a static event (e.g. SystemEvents.*) lives for the
                           # whole process -> strictly longer than any subscriber.
}
# .NET DI lifetime -> region. `singleton` is the long `Process` region (app-lived,
# shared with static events); `scoped`/`transient` are strictly shorter.
_DI_REGION = {"singleton": "Process", "scoped": "scoped", "transient": "transient"}
_CAPTURE_LIFETIMES = [
    LifetimeDecl("Process", None, 0),               # app/process/singleton lifetime
    LifetimeDecl("scoped", "Process", 0),           # scoped strictly < Process
    LifetimeDecl("transient", "scoped", 0),         # transient strictly < scoped
    LifetimeDecl(_SUBSCRIBER_REGION, "Process", 0),  # un-registered VM < Process
]


def _di_life_map(facts: dict[str, Any]) -> dict[str, str]:
    """Map each DI-registered service name -> its lifetime (singleton/scoped/
    transient) from the optional `services` graph. The bridge cross-references a
    subscription's `source_type` (and the subscriber's own name) against this to
    derive regions for the lifetime engine."""
    out: dict[str, str] = {}
    raw = facts.get("services", [])
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict) and isinstance(s.get("name"), str) \
                    and s.get("lifetime") in DI_LIFETIMES:
                out[s["name"]] = s["lifetime"]
    return out


def _subscriber_region(cname: str, di_life: dict[str, str]) -> str:
    """The region a subscriber component lives in: its own DI-registered lifetime's
    region if it is registered, else the short un-registered `Subscriber` region (a
    Window/VM the UI framework owns, never a heap root)."""
    return _DI_REGION.get(di_life.get(cname, ""), _SUBSCRIBER_REGION)


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
    # secondary, structured locations that explain the finding — each a
    # (file, line, label) triple. The primary `file`/`line` stays the anchor; these ride
    # along as SARIF `relatedLocations` (e.g. a DI captive's *consuming constructor*, distinct
    # from its registration-site anchor). Empty for findings with a single location.
    related: tuple[tuple[str, int, str], ...] = ()

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


# SARIF 2.1.0 — the OASIS-standard static-analysis interchange format. Unlike the
# line-per-finding surfaces above, a SARIF log is ONE document for the whole run,
# so it is built from the finding *list*, not rendered per finding.
_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
_SARIF_INFO_URI = "https://github.com/PhysShell/Own.NET"


def _sarif_level(f: Finding, severity: str) -> str:
    """The SARIF result level for a finding. Mirrors the CLI's per-finding severity
    (an advisory OWN050 and an intrinsic-warning finding both stay sub-error), but
    uses SARIF's dedicated `note` level for the advisory coverage notes — so a
    consumer can tell a *skip* ("could not check this") from a real warning-tier
    leak, which the flat error/warning surfaces cannot express."""
    if f.advisory:
        return "note"
    if severity == "warning" or f.severity == "warning":
        return "warning"
    return "error"


def _sarif_result(f: Finding, severity: str) -> dict[str, Any]:
    """One SARIF `result` for a finding: the OWN code is the `ruleId`, the C#
    location is a `physicalLocation`, and the resource kind / subscription triple
    ride along in `properties` for any consumer that wants them."""
    phys: dict[str, Any] = {
        "artifactLocation": {"uri": f.file.replace("\\", "/")},
    }
    if f.line >= 1:  # SARIF region.startLine is 1-based; omit it for a file-level finding
        phys["region"] = {"startLine": f.line}
    props: dict[str, Any] = {"resourceKind": f.kind}
    for key, val in (("component", f.component), ("event", f.event),
                     ("handler", f.handler)):
        if val:
            props[key] = val
    result: dict[str, Any] = {
        "ruleId": f.code,
        "level": _sarif_level(f, severity),
        "message": {"text": f"{f.message} [resource: {f.kind}]"},
        "locations": [{"physicalLocation": phys}],
        "properties": props,
    }
    # secondary locations (e.g. a DI captive's consuming constructor) — a SARIF consumer
    # (GitHub code scanning) renders these as clickable, labelled related locations.
    related = [
        {"physicalLocation": {"artifactLocation": {"uri": rf.replace("\\", "/")},
                              "region": {"startLine": rl}},
         "message": {"text": rmsg}}
        for (rf, rl, rmsg) in f.related if rl >= 1
    ]
    if related:
        result["relatedLocations"] = related
    return result


def build_sarif(findings: list[Finding], severity: str = "error") -> dict[str, Any]:
    """Render the findings as a single SARIF 2.1.0 log: one `run` whose
    `tool.driver` is Own.NET (with a `rules` catalogue of the OWN codes present and
    their titles) and whose `results` carry each finding's code, C# location,
    message and resource kind. `severity` is the same presentation choice as the
    other surfaces (it only sets each result's `level`).

    SARIF earns its place three ways: it is GitHub code-scanning native, it is a
    frozen/diffable run artifact (reproducibility), and it is the *same* shape
    `scripts/oracle_compare.py` already parses for Infer# and CodeQL — so own-check
    can join the cross-tool diff through one SARIF reader instead of the bespoke
    text parser (the parser-drift class of bug it documents)."""
    codes = sorted({f.code for f in findings})
    rules = [
        {"id": code, "shortDescription": {"text": TITLES.get(code, code)}}
        for code in codes
    ]
    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Own.NET",
                        "informationUri": _SARIF_INFO_URI,
                        "rules": rules,
                        "properties": {"ownirSchemaVersion": OWNIR_VERSION},
                    },
                },
                "results": [_sarif_result(f, severity) for f in findings],
            },
        ],
    }


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
            # `source_type` (P-006 + P-004): the declared type of an injected event
            # source, cross-referenced against the `services` graph to derive its
            # DI lifetime/region. Additive/optional; an older core ignores it.
            stp = s.get("source_type")
            if stp is not None and not isinstance(stp, str):
                raise OwnIRError(
                    f"subscription 'source_type' must be a string, got {stp!r}")
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
        weak_deps = s.get("weak_deps", [])
        if not isinstance(weak_deps, list) or not all(isinstance(d, str) for d in weak_deps):
            raise OwnIRError("service 'weak_deps' must be an array of strings")
        root_resolves = s.get("root_resolves", [])
        if not isinstance(root_resolves, list) or not all(
                isinstance(d, str) for d in root_resolves):
            raise OwnIRError("service 'root_resolves' must be an array of strings")
        if not isinstance(s.get("file", "?"), str):
            raise OwnIRError("service 'file' must be a string")
        ln = s.get("line", 0)
        if not isinstance(ln, int) or isinstance(ln, bool):
            raise OwnIRError("service 'line' must be an integer")
        # the consuming-constructor location (optional, P-006 Q#1) is validated like file/line.
        if not isinstance(s.get("ctor_file", "?"), str):
            raise OwnIRError("service 'ctor_file' must be a string")
        cln = s.get("ctor_line", 0)
        if not isinstance(cln, int) or isinstance(cln, bool):
            raise OwnIRError("service 'ctor_line' must be an integer")
        if not isinstance(s.get("ctor_type", ""), str):
            raise OwnIRError("service 'ctor_type' must be a string")
        # DI004 call-site metadata (optional): an array of {type, file, line} objects.
        sites = s.get("root_resolve_sites", [])
        if not isinstance(sites, list) or not all(
                isinstance(x, dict) and isinstance(x.get("type", ""), str)
                and isinstance(x.get("file", "?"), str)
                and isinstance(x.get("line", 0), int) and not isinstance(x.get("line", 0), bool)
                for x in sites):
            raise OwnIRError(
                "service 'root_resolve_sites' must be an array of "
                "{type:str, file:str, line:int} objects")
        # DI005 (scope-cached captive): types resolved from a self-created scope and cached
        # into a field, plus their field-store sites — validated like root_resolves / its sites.
        scope_cached = s.get("scope_cached", [])
        if not isinstance(scope_cached, list) or not all(
                isinstance(d, str) for d in scope_cached):
            raise OwnIRError("service 'scope_cached' must be an array of strings")
        csites = s.get("scope_cache_sites", [])
        if not isinstance(csites, list) or not all(
                isinstance(x, dict) and isinstance(x.get("type", ""), str)
                and isinstance(x.get("file", "?"), str)
                and isinstance(x.get("line", 0), int) and not isinstance(x.get("line", 0), bool)
                for x in csites):
            raise OwnIRError(
                "service 'scope_cache_sites' must be an array of "
                "{type:str, file:str, line:int} objects")
    # Optional per-method flow bodies (P-016 B0b/B2 — local IDisposable
    # acquire/use/release over a CFG). Additive/optional; an older core ignores it.
    fns = result.get("functions", [])
    if not isinstance(fns, list) or not all(isinstance(f, dict) for f in fns):
        raise OwnIRError("OwnIR 'functions' must be a JSON array of objects")
    for f in fns:
        # Optional ownership CONTRACT (P-006/2b): params + their effects. Additive
        # and optional — an older core just reads functions without contracts. An
        # omitted `effect` is INFERRED from the body (v1 contract inference), so the
        # field is a hint/override, not a requirement.
        ps = f.get("params", [])
        if not isinstance(ps, list) or not all(isinstance(p, dict) for p in ps):
            raise OwnIRError("a function's 'params' must be a JSON array of objects")
        for p in ps:
            # identity fields first: `name` is what inference and finding-mapping
            # key on, so a malformed one must fail fast, not be silently coerced.
            pn = p.get("name")
            if not isinstance(pn, str) or not pn:
                raise OwnIRError(
                    f"parameter 'name' must be a non-empty string, got {pn!r}")
            pl = p.get("line", 0)
            if not isinstance(pl, int) or isinstance(pl, bool):
                raise OwnIRError(
                    f"parameter 'line' must be an integer, got {pl!r}")
            peff = p.get("effect")
            if peff is not None and peff not in ("consume", "borrow", "borrow_mut",
                                                 "plain"):
                raise OwnIRError(
                    f"parameter 'effect' must be consume/borrow/borrow_mut/plain, "
                    f"got {peff!r}")
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
    di_life = _di_life_map(facts)   # DI registrations: service name -> lifetime
    components = facts.get("components", [])
    if not isinstance(components, list):
        raise OwnIRError("OwnIR 'components' must be a JSON array")
    for comp in components:
        if not isinstance(comp, dict):
            raise OwnIRError("each OwnIR component must be a JSON object")
        cname = comp.get("name", f"Component{gid}")
        self_region = _subscriber_region(cname, di_life)
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
            # A `subscribe` (ignored `.Subscribe()` result) whose SOURCE is `self`
            # is a self-rooted `this.WhenAnyValue(x => x.SelfProp)` cycle — the
            # observable, its handler and `this` form one cycle the GC collects
            # together, so it is NOT a leak. Skip it (silent); only an EXTERNAL
            # source holds the component from a longer-lived root. Mirrors to_module.
            if rkind == "subscribe" and sub.get("source") == "self":
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
            # DI-sourced escape (mirrors to_module): an injected source with a KNOWN
            # DI lifetime lowers to `subscribe self to <source>` under its DI region.
            # Only subscriptions reroute here — a non-subscription resource with an
            # incidental `source`/`source_type` keeps its own analysis path.
            if (rkind == "subscription" and sub.get("source") == "injected"
                    and not sub.get("released")):
                st = sub.get("source_type")
                src_life = di_life.get(st) if isinstance(st, str) else None
                if src_life is not None:
                    handle = f"cap_{gid}"
                    gid += 1
                    handles[handle] = {**sub, "component": cname,
                                       "file": comp.get("file", "?"),
                                       "di_source_life": src_life}
                    cap_params.append(
                        f"{handle}: EventSource lifetime {_DI_REGION[src_life]}")
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
        lt = f" lifetime {self_region}" if cap_handles else ""
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
    di_life = _di_life_map(facts)   # DI registrations: service name -> lifetime
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
        self_region = _subscriber_region(cname, di_life)
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
            # A self-rooted `subscribe` (ignored `.Subscribe()` on a
            # `this.WhenAnyValue(x => x.SelfProp)` chain) is a GC-collectible
            # self-cycle, not a leak — skip it (silent), like a released
            # subscription. Only an EXTERNAL source holds the component.
            if rkind == "subscribe" and sub.get("source") == "self":
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
                fn_lt = self_region
                any_capture = True
                continue
            # P-006 + P-004 DI-sourced escape: an injected subscription whose source
            # TYPE resolves (via the `services` graph) to a KNOWN DI lifetime routes
            # through the SAME region engine. singleton/scoped/transient become the
            # source's region; the engine reports OWN014 iff it strictly outlives the
            # subscriber's region, and stays silent when it cannot (proven SAFE by
            # the registration order — no honest-warning hedge once the lifetime is
            # known). An unregistered/unknown source (src_life None) falls through to
            # the token path below and keeps the OWN001 warning. A released `-=`
            # mitigates it (same as any capture). Only subscriptions reroute here —
            # a non-subscription resource with an incidental `source`/`source_type`
            # keeps its own (timer/disposable/...) analysis path.
            if (rkind == "subscription" and sub.get("source") == "injected"
                    and not sub.get("released")):
                st = sub.get("source_type")
                src_life = di_life.get(st) if isinstance(st, str) else None
                if src_life is not None:
                    handle = f"cap_{gid}"
                    gid += 1
                    handles[handle] = {**sub, "component": cname,
                                       "file": comp.get("file", "?"),
                                       "di_source_life": src_life}
                    line = _as_int(sub.get("line", 0))
                    params.append(Param(handle,
                                        TypeRef("EventSource", False, False, 0),
                                        0, lifetime=_DI_REGION[src_life]))
                    body.append(Subscribe(handle, line))
                    fn_lt = self_region
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
        # D5.1: resolve interprocedural ownership transfer once, up front, so a
        # forwarded `consume`/`borrow` param is checked compositionally (the give-up
        # case `_infer_param_effect` used to leave plain). Never let summary
        # computation crash the bridge — degrade to no-MOS (the old behaviour).
        try:
            mos: dict[str, Any] = solve(_build_skeletons(raw_fns))
        except Exception:
            mos = {}
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
            # ownership contract params first (they seed `localmap` so the body's
            # uses/releases and call arguments resolve to them), then the flow body.
            localmap: dict[str, str] = {}
            fparams = _lower_fn_params(fn, ffile, fname, handles, loc, localmap,
                                       released, mos)
            fbody = _lower_flow(nodes, ffile, fname, handles, loc, localmap,
                                released, mos)
            # A body that returns a value gets an owned return type, so the core
            # models `return s` as a valid ESCAPE (the value is discharged to the
            # caller) instead of a void-return mismatch that would leave `s` looking
            # leaked. The bridge does not know the real C# return type; an owned
            # resource type is what makes the escape check fire (any return-type
            # mismatch it then reports is skipped in check_facts).
            fret = (TypeRef("Disposable", False, False)
                    if _returns_value(nodes) else None)
            functions.append(FnDecl(fname, fparams, fret, fbody, 0))
    return (Module(str(facts.get("module", "Extracted")),
                   resources=_prelude_resources(),
                   externs=list(_OWNERSHIP_SINK_EXTERNS),
                   functions=functions,
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


def _returns_value(nodes: Any) -> bool:
    """True if a flow body returns a VALUE on some path (a `return` op carrying a
    `var`), recursing into if/while. The bridge then gives the function an owned
    return type so `return s` models a valid escape (discharge), not a void-return
    mismatch."""
    if not isinstance(nodes, list):
        return False
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        if op == "return" and n.get("var") is not None:
            return True
        if op == "if" and (_returns_value(n.get("then"))
                           or _returns_value(n.get("else"))):
            return True
        if op == "while" and _returns_value(n.get("body")):
            return True
    return False


def _collect_vars(nodes: Any, op_kind: str, field: str) -> set[str]:
    """Every string `field` of every `op_kind` op in a flow body (recursing into
    if/while). Used to gather the locals a body `acquire`s and the locals it
    `return`s, for P-005 D5.2 fresh-return inference."""
    out: set[str] = set()
    if not isinstance(nodes, list):
        return out
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        if op == op_kind:
            v = n.get(field)
            if isinstance(v, str):
                out.add(v)
        elif op == "if":
            out |= _collect_vars(n.get("then"), op_kind, field)
            out |= _collect_vars(n.get("else"), op_kind, field)
        elif op == "while":
            out |= _collect_vars(n.get("body"), op_kind, field)
    return out


def _call_result_callees(nodes: Any) -> dict[str, str | None]:
    """Map each `result` local of a `call` op to the callee that produced it (for
    forward-return inference, P-005 D5.2). A local bound by two *different* callees
    (e.g. on separate branches) maps to None — ambiguous, so never claimed as a
    forward-return (precision-first)."""
    out: dict[str, str | None] = {}
    if not isinstance(nodes, list):
        return out

    def visit(ns: Any) -> None:
        if not isinstance(ns, list):
            return
        for n in ns:
            if not isinstance(n, dict):
                continue
            op = n.get("op")
            if op == "call":
                res = n.get("result")
                callee = n.get("callee")
                if isinstance(res, str) and isinstance(callee, str) and callee:
                    out[res] = None if res in out and out[res] != callee else callee
            elif op == "if":
                visit(n.get("then"))
                visit(n.get("else"))
            elif op == "while":
                visit(n.get("body"))

    visit(nodes)
    return out


def _infer_return_skeleton(nodes: Any, param_names: set[str]) -> ReturnSkeleton:
    """Infer a method's owned-return kind for the D5.0 solver (P-005 D5.2, T1).

    `fresh` — every `return <var>` path returns a local the body itself `acquire`d
    (a factory: `acquire x; …; return x`). A returned **parameter** is NOT fresh
    (that is the wrap/alias case, T4 / D5.4) — claiming fresh there would make a
    caller acquire a value it does not own. `forward` — a single returned local that
    is the result of a first-party `call` (a factory-of-factory: `var t = Make();
    return t;`); the solver propagates `Make`'s own return kind. Anything else stays
    `none` (no claim) — precision-first: we only mark a call an acquire site when we
    can prove the result is freshly owned."""
    returned = _collect_vars(nodes, "return", "var")
    if not returned:
        return ReturnSkeleton()  # void / no value return
    acquired = _collect_vars(nodes, "acquire", "var")
    call_results = _call_result_callees(nodes)
    # `fresh` only when EVERY returned local is acquired here and *nowhere else*. A local
    # that is also a call result on another path is mixed-origin (`if c: x = acquire()
    # else: x = other()`) — claiming fresh would make a caller acquire a value it does not
    # own on the non-acquire path, fabricating OWN001/OWN002 there. Degrade (CodeRabbit).
    if all(v in acquired and v not in param_names and v not in call_results
           for v in returned):
        return ReturnSkeleton("fresh")
    if len(returned) == 1:
        (v,) = tuple(returned)
        callee = call_results.get(v)
        if callee and v not in param_names and v not in acquired:
            return ReturnSkeleton("forward", callee=callee)
    return ReturnSkeleton()  # not provably owned -> no claim


# P-006/2b: a method's ownership CONTRACT is its parameters' effects. Encoding
# each effect as the TypeRef `collect_signatures` reads (a resource-typed value =>
# CONSUME, a borrowed type => BORROW/BORROW_MUT, anything else => PLAIN) lets the
# SAME core signature table + `lower_call` resolve a call's per-argument effects —
# so cross-method ownership transfer is checked compositionally (the inter-
# procedural island) with NO new checker. The resource name is the prelude
# `Disposable` (any prelude resource would do; what matters is that it is owned).
_PARAM_EFFECT_TYPE = {
    "consume": TypeRef("Disposable", False, False),   # takes ownership
    "borrow": TypeRef("Disposable", True, False),     # shared loan, noescape
    "borrow_mut": TypeRef("Disposable", True, True),  # exclusive loan, noescape
}

# P-005 D5.1b — the per-call-site ownership-contract channel. The extractor cannot
# always pin a call's ownership effect from a first-party body: a BCL sink (e.g.
# `new StreamReader(s, leaveOpen: false)`) or a `[ConsumesOwnership]`-style
# annotation lives outside our summary set. Rather than grow a bespoke lowering for
# each such case, we pre-declare three fixed sink externs and let the extractor
# route any call's per-argument ownership through them: a `call $consume [x]` takes
# ownership of `x`, `$borrow`/`$borrow_mut` lend it for the call. They resolve via
# the SAME `collect_signatures` + `lower_call` path as any contracted call (so a
# later use of a consumed `x` is OWN002, an un-discharged borrow is still OWN001) —
# no new checker, no new flow lowering. Externs are declaration-only, never leak-
# checked themselves, and the `$` prefix cannot collide with a real C# member name.
_OWNERSHIP_SINK_EXTERNS = (
    ExternDecl("$consume", [EffectParam(Effect.CONSUME, "Disposable", 0)], None, 0),
    ExternDecl("$borrow", [EffectParam(Effect.BORROW, "Disposable", 0)], None, 0),
    ExternDecl("$borrow_mut",
               [EffectParam(Effect.BORROW_MUT, "Disposable", 0)], None, 0),
)

# A forward to a sink extern is a *known* transfer, so a skeleton can record the
# resolved path action directly — `$consume` is ownership leaving (a must-transfer),
# `$borrow` is a kept loan — rather than a `forward` edge to an unsummarized callee
# (which the solver would degrade to `unknown`, diluting a real `must` to plain).
# `$borrow_mut` is DELIBERATELY ABSENT (Codex P2): the transfer lattice carries no
# shared-vs-exclusive axis, so mapping it to `borrow` would silently downgrade an
# EXCLUSIVE loan to a shared one in the wrapper's contract — asserting something
# weaker than the truth. We decline the transitive claim instead (it falls through
# to a `forward` edge → `unknown` → the wrapper param stays plain, no false shared-
# borrow contract). The DIRECT `call $borrow_mut [x]` channel is unaffected and keeps
# full exclusivity through `lower_call`. Kept in sync with `_OWNERSHIP_SINK_EXTERNS`.
_SINK_PATH_ACTION = {"$consume": "dispose", "$borrow": "borrow"}


def _param_signals(pname: str, nodes: Any) -> tuple[bool, bool, bool]:
    """Scan a flow body for how parameter `pname` is treated, returning
    (released, handed-to-a-call, used). Recurses into if/while branches so a
    discharge on any path counts."""
    rel = passed = used = False
    if not isinstance(nodes, list):
        return rel, passed, used
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        if op == "release" and str(n.get("var")) == pname:
            rel = True
        elif op == "call":
            args = n.get("args", [])
            if isinstance(args, list) and any(str(a) == pname for a in args):
                passed = True
        elif op == "use" and str(n.get("var")) == pname:
            used = True
        elif op in ("if", "while"):
            subs = ([n.get("then"), n.get("else")] if op == "if"
                    else [n.get("body")])
            for sub in subs:
                sr, sp, su = _param_signals(pname, sub)
                rel, passed, used = rel or sr, passed or sp, used or su
    return rel, passed, used


def _forward_targets(pname: str, nodes: Any,
                     recurse: bool = True) -> list[tuple[str, int]]:
    """Every `(callee, arg_index)` a `call` op hands `pname` to. The argument
    *position* is the callee's parameter index — what `solve()` resolves against
    the callee's summary (P-005 D5.1). With `recurse=False`, only top-level
    (straight-line) calls are counted, so a conditional/looped forward can be told
    apart from an unconditional one."""
    out: list[tuple[str, int]] = []
    if not isinstance(nodes, list):
        return out
    for n in nodes:
        if not isinstance(n, dict):
            continue
        op = n.get("op")
        if op == "call":
            callee = str(n.get("callee", ""))
            args = n.get("args", [])
            if callee and isinstance(args, list):
                for j, a in enumerate(args):
                    if str(a) == pname:
                        out.append((callee, j))
        elif op in ("if", "while") and recurse:
            subs = ([n.get("then"), n.get("else")] if op == "if" else [n.get("body")])
            for sub in subs:
                out.extend(_forward_targets(pname, sub))
    return out


def _forward_path_action(callee: str, arg: int) -> PathAction:
    """The skeleton path action for one forward edge. A forward to a fixed
    ownership-sink extern (D5.1b) is a *resolved* transfer recorded directly
    (`$consume` → `dispose`, `$borrow*` → `borrow`); any other callee is a
    `forward` edge the solver resolves against that callee's summary."""
    kind = _SINK_PATH_ACTION.get(callee)
    if kind is not None:
        return PathAction(kind)
    return PathAction("forward", callee, arg)


def _build_skeletons(raw_fns: list[Any]) -> list[MethodSkeleton]:
    """Derive a Method Ownership Summary skeleton per first-party function from its
    flow body, for the D5.0 solver (P-005 D5.1). A parameter's path actions mirror
    the same priority `_infer_param_effect` uses — a release is a `dispose`, a
    forward to another call is a `forward` edge the solver resolves, an
    otherwise-used param is a `borrow` — so the solved transfer lines up with the
    bridge's local inference on the non-forward cases and only *resolves* the
    forwarded one.

    Two precision rules keep `solve()` from ever inferring a false `must` (which
    would upgrade a caller to `consume` and fabricate OWN002/OWN001):
      - an **explicit** `effect` seeds the skeleton (it is a documented override —
        `consume`→`dispose`, `borrow`/`borrow_mut`→`borrow`, anything else owns
        nothing), so a contract-only callee resolves correctly even with no body;
      - a forward is resolved only when it is a **single, unconditional,
        straight-line** handoff. A conditional / looped / multi-target forward also
        emits a non-transfer (`borrow`) path, so the lattice yields `may`/`no`
        (→ the caller stays plain), never a flattened `must`. Per-path structure is
        not modelled here — D5.1 deliberately under-claims rather than guess.

    The return kind is inferred too (P-005 D5.2, T1): a body that `acquire`s a local
    and returns it is `fresh` (a factory); `_infer_return_skeleton` keeps it
    precision-first (a returned parameter is never `fresh`).

    Functions whose name is not unique are dropped (overload keys are not yet
    distinguishable — note's open question 2 — so a forward to such a name stays
    `unknown` → silent, the precision-safe choice)."""
    counts = Counter(str(fn.get("name", "")) for fn in raw_fns if isinstance(fn, dict))
    skels: list[MethodSkeleton] = []
    for fn in raw_fns:
        if not isinstance(fn, dict):
            continue
        key = str(fn.get("name", ""))
        if not key or counts[key] != 1:
            continue
        body = fn.get("body", [])
        body = body if isinstance(body, list) else []
        raw_params = fn.get("params", [])
        raw_params = raw_params if isinstance(raw_params, list) else []
        params: list[ParamSkeleton] = []
        for i, p in enumerate(raw_params):
            if not isinstance(p, dict):
                continue
            cname = str(p.get("name", "?"))
            eff = p.get("effect")
            paths: tuple[PathAction, ...]
            if eff == "consume":
                paths = (PathAction("dispose"),)                 # explicit override
            elif eff in ("borrow", "borrow_mut"):
                paths = (PathAction("borrow"),)
            elif isinstance(eff, str):
                paths = ()                                       # explicit non-owning
            else:
                rel, passed, used = _param_signals(cname, body)
                if rel:
                    paths = (PathAction("dispose"),)
                elif passed:
                    allt = _forward_targets(cname, body)
                    top = _forward_targets(cname, body, recurse=False)
                    paths = tuple(_forward_path_action(c, j) for c, j in allt)
                    if not (len(allt) == 1 and len(top) == 1):
                        # not a single unconditional handoff: a no-transfer path
                        # exists (other branch / zero-trip loop / sibling call), so
                        # the join is `may`/`no`, never a false `must`.
                        paths = (*paths, PathAction("borrow"))
                elif used:
                    paths = (PathAction("borrow"),)
                else:
                    paths = ()
            params.append(ParamSkeleton(i, cname, True, paths))
        pnames = {str(p.get("name", "")) for p in raw_params if isinstance(p, dict)}
        ret = _infer_return_skeleton(body, pnames)
        skels.append(MethodSkeleton(key, tuple(params), ret))
    return skels


def _infer_param_effect(pname: str, nodes: Any,
                        forward_transfer: Transfer | None = None) -> str | None:
    """Infer a parameter's ownership CONTRACT from the callee's OWN body — the
    bounded inter-procedural step that lets first-party C# be checked without
    annotating every method. A param the body discharges (release) is CONSUME
    (ownership taken and discharged); one only read and retained is a BORROW (the
    caller keeps ownership, must still release). A param handed to another call
    used to be ambiguous and stay plain; **P-005 D5.1** resolves it through the
    call graph: `forward_transfer` is the solved transfer of that param (must →
    CONSUME, no → BORROW, may/unknown → stay plain, precision-first). We
    deliberately do NOT treat `return <param>` as a consume signal: the bridge
    does not yet model returned (owned) VALUES, so a returned param is
    consume-and-handed-back, not a plain consume. Inference never upgrades a
    borrow to a consume (or vice-versa) on a guess — an explicit `effect` in the
    fact always wins over inference."""
    rel, passed, used = _param_signals(pname, nodes)
    if rel:
        return "consume"
    if passed:
        if forward_transfer == Transfer.MUST:
            return "consume"
        if forward_transfer == Transfer.NO:
            return "borrow"
        return None  # may / unknown / unresolved -> plain (precision-first)
    if used:
        return "borrow"
    return None


def _lower_fn_params(fn: dict[str, Any], ffile: str, fname: str,
                     handles: dict[str, dict[str, Any]], loc: list[int],
                     localmap: dict[str, str],
                     released_vars: set[str],
                     mos: dict[str, Any] | None = None) -> list[Param]:
    """Lower a function's declared ownership parameters into core Params. Each
    gets a globally-unique synthetic symbol (`parg_<n>`) so a finding maps back to
    its C# location; `localmap` resolves later references (and call arguments) by
    the C# name. A `consume` parameter is an owned obligation in the callee — the
    same Param the `.own` front-end produces — so an undischarged one leaks (the
    obligation having moved in from the caller). A parameter with no explicit
    `effect` has its contract INFERRED from the body (`_infer_param_effect`)."""
    out: list[Param] = []
    raw = fn.get("params", [])
    if not isinstance(raw, list):
        return out
    summ = mos.get(fname) if mos is not None else None
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            continue
        cname = str(p.get("name", "?"))
        eff = p.get("effect")
        if not isinstance(eff, str):
            # D5.1: when the contract is inferred, resolve a *forwarded* param's
            # transfer through the call graph (the solved MOS for this method).
            ftrans = None
            if summ is not None:
                ps = next((q for q in summ.params if q.index == i), None)
                if ps is not None:
                    ftrans = ps.transfer
            eff = _infer_param_effect(cname, fn.get("body", []), ftrans)
        tref = _PARAM_EFFECT_TYPE.get(eff) if isinstance(eff, str) else None
        if tref is None:
            tref = TypeRef("int", False, False)   # a plain (non-owned) parameter
        sym = f"parg_{loc[0]}"
        loc[0] += 1
        line = _as_int(p.get("line", 0))
        localmap[cname] = sym
        handles[sym] = {"file": ffile, "line": line, "event": cname,
                        "component": fname, "resource": "flow-local",
                        "ever_released": cname in released_vars}
        out.append(Param(sym, tref, line))
    return out


def _lower_flow(nodes: list[Any], ffile: str, fname: str,
                handles: dict[str, dict[str, Any]], loc: list[int],
                localmap: dict[str, str],
                released_vars: set[str],
                mos: dict[str, Any] | None = None) -> list[Stmt]:
    """Lower one OwnIR flow body (B0b/B2) into core statements. acquire/use/release/
    return reference a C# local by name (`var`); `if` carries `then`/`else`
    sub-bodies; `while` carries a `body` (a back-edge — the core's worklist fixpoint
    checks it, P-016 A1). Each acquire gets a globally-unique handle `loc_<n>` (so a
    finding maps back to the C# local); `localmap` resolves later references within
    the same function and its branches/loops.

    P-005 D5.2 (T1): a `call` op that binds a `result` local, whose callee's solved
    summary (`mos`) returns `fresh`, is **also** lowered as an `acquire` of that
    local — the call site is a factory, so the result is a newly-owned obligation and
    the existing leak / double-release / use-after-release checks apply to it."""
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
                               "ever_released": name in released_vars,
                               # the extractor stamps an ArrayPool Rent's acquire kind so a
                               # partial-path leak reads as a "pooled buffer", not "disposable".
                               "pool": n.get("kind") == "pool"}
            body.append(Let(handle, Acquire("Disposable", [], line), line))
        elif op == "use":
            h = localmap.get(str(n.get("var")))
            if h is not None:
                body.append(Use(h, line))
        elif op == "overspan":
            # POOL005: a full-length Span/Memory view of a pooled buffer. The
            # extractor emits this only for a Rent'd local viewed with no length
            # bound; it routes to the same core op the `.own` `overspan` lowers to.
            h = localmap.get(str(n.get("var")))
            if h is not None:
                body.append(Overspan(h, line))
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
                                 ffile, fname, handles, loc, localmap, released_vars, mos)
            else_b = _lower_flow(en if isinstance(en, list) else [],
                                 ffile, fname, handles, loc, localmap, released_vars, mos)
            body.append(If("?", then_b, else_b, line))
        elif op == "while":
            bn = n.get("body", [])
            body_b = _lower_flow(bn if isinstance(bn, list) else [],
                                 ffile, fname, handles, loc, localmap, released_vars, mos)
            body.append(While("?", body_b, line))
        elif op == "call":
            # A call to a CONTRACTED callee (a function/extern whose signature the
            # bridge also lowered). `lower_call` resolves each argument's effect
            # from that signature: a `consume` parameter moves ownership across the
            # call (so a later use is OWN002), a `borrow` lends it. This is the
            # compositional island — the caller is checked against the callee's
            # contract, not its body. Arguments resolve C# locals/params via
            # `localmap`; an uncontracted call is simply not emitted by the
            # extractor (it is an escape, surfaced separately).
            callee = str(n.get("callee", ""))
            raw_args = n.get("args", [])
            if callee and isinstance(raw_args, list):
                arg_refs: list[Expr] = [VarRef(localmap.get(str(a), str(a)), line)
                                        for a in raw_args]
                body.append(Call(callee, arg_refs, line))
            # P-005 D5.2 (T1): if the call binds a result and the callee is a known
            # `fresh`-returning factory, the result is a newly-owned local — mint an
            # acquire for it (the args' effects, if any, were applied by the Call
            # above; this models the return). A non-fresh / unknown return makes no
            # claim, so the result is never falsely owned (precision-first).
            result = n.get("result")
            summ = mos.get(callee) if (mos is not None and callee) else None
            if (isinstance(result, str) and result
                    and summ is not None and getattr(summ, "returns", None) == "fresh"):
                handle = f"loc_{loc[0]}"
                loc[0] += 1
                localmap[result] = handle
                handles[handle] = {"file": ffile, "line": line, "event": result,
                                   "component": fname, "resource": "flow-local",
                                   "ever_released": result in released_vars,
                                   "pool": False}
                body.append(Let(handle, Acquire("Disposable", [], line), line))
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
        # The bridge SYNTHESISES return types and parameter effects (from inference
        # / extractor annotations); a handful of core diagnostics only report
        # INCONSISTENCIES in those synthesised shapes, which are artifacts of the
        # bridge's incomplete modeling, not real C# bugs (C# already type-checks).
        # They also carry no subject, so they cannot map to a handle. Skip them:
        #   - OWN033/OWN035: return-TYPE mismatches (the bridge gives a function an
        #     owned return type iff its body returns a value; the real leak/use
        #     checks still run, and `return s` discharges via escape-on-return).
        #   - OWN034/OWN041: effect-kind mismatches at a call, which surface when a
        #     parameter's contract could not be inferred (an ambiguous pass-through
        #     stays plain) -- a "needs annotation / transitive inference" gap, not a
        #     leak. Surfacing these properly (with a subject) is a later step.
        if d.code in ("OWN033", "OWN034", "OWN035", "OWN041"):
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
            if d.code == "OWN025":
                # POOL005: a full-length view of a pooled buffer reaches past its
                # logical length. Report at the VIEW site (d.line — where the
                # unbounded AsSpan/Memory is taken), not the Rent site, and tag it
                # a pooled buffer rather than the generic disposable.
                findings.append(Finding(
                    file=sub["file"], line=d.line, code=d.code,
                    component=component, event=name, handler="",
                    message=(f"pooled buffer '{name}' is viewed at its full "
                             f"length, past the logical length it was rented for "
                             f"(over-read / over-clear)"),
                    kind="pooled buffer"))
                continue
            # An ArrayPool Rent is released by Return (a "pooled buffer"), not Dispose (a
            # "disposable"); the extractor stamps the acquire's kind so the flow path words
            # and tags it correctly — previously a Rent leaked/misused on a flow path was
            # mislabelled the generic "disposable" (e.g. a partial-throw-path Return).
            pool = sub.get("pool")
            if d.code == "OWN001":
                # OWN001 spans "released on 0 paths" and "released on some but not all" —
                # the core's "not on every path". Word it from whether the flow body
                # released this local anywhere (ever_released): no release at all reads as
                # "never returned/disposed"; a partial release as "not on every path".
                if pool:
                    if sub.get("ever_released"):
                        msg = (f"pooled buffer '{name}' may not be returned to the "
                               f"pool on every path (leak)")
                    else:
                        msg = (f"pooled buffer '{name}' is rented but never "
                               f"returned to the pool (leak)")
                else:
                    msg = (f"IDisposable local '{name}' may not be disposed on every path (leak)"
                           if sub.get("ever_released")
                           else f"IDisposable local '{name}' is never disposed (leak)")
            elif pool:
                msg = {
                    "OWN002": f"pooled buffer '{name}' is used after it is returned to the pool",
                    "OWN003": f"pooled buffer '{name}' is returned to the pool more than once",
                    "OWN009": (f"pooled buffer '{name}' may be used after "
                               f"being returned on some path"),
                }.get(d.code, f"pooled buffer '{name}': {d.message}")
            else:
                msg = {
                    "OWN002": f"IDisposable local '{name}' is used after it is disposed",
                    "OWN003": f"IDisposable local '{name}' is disposed more than once",
                    "OWN009": f"IDisposable local '{name}' may be used after disposal on some path",
                }.get(d.code, f"IDisposable local '{name}': {d.message}")
            findings.append(Finding(
                file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
                component=component, event=name, handler="", message=msg,
                kind="pooled buffer" if pool else "disposable"))
            continue
        if sub.get("di_source_life"):
            # OWN014 region escape sourced from the DI graph (P-006 + P-004): the
            # injected event SOURCE is registered with a lifetime that the engine
            # proved strictly outlives the subscriber, so the strong subscription
            # promotes '{component}' to the source's lifetime and it can never be
            # collected — the captive/zombie case, now PROVEN (not the honest OWN001
            # warning an unresolved-lifetime source gets). Error-tier.
            life = sub["di_source_life"]
            st = sub.get("source_type", "?")
            nice = {
                "singleton": "a DI singleton (application-lifetime) service",
                "scoped": "a DI scoped service",
                "transient": "a DI transient service",
            }.get(life, f"a DI {life} service")
            message = (f"event '{event}' is subscribed (handler '{handler}') to "
                       f"'{st}' — {nice} that outlives '{component}'; the strong "
                       f"subscription promotes '{component}' to the source's "
                       f"lifetime, so it can never be collected — a captive/region "
                       f"escape (leak, no release path)")
            findings.append(Finding(
                file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
                component=component, event=event, handler=handler,
                message=message, kind="subscription token"))
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
            # source-lifetime tiering (P-004), mirroring the `+=` else branch: a
            # self-rooted subscribe is already dropped in to_module (silent); an
            # injected source has UNKNOWN lifetime -> warning ("may outlive"); a
            # static/external/unknown source stays a provable leak (error).
            if sub.get("source") == "injected":
                fsev = "warning"
                message = (f"the result of '{event}' is ignored — its IDisposable "
                           f"subscription is never disposed; the source is an "
                           f"injected dependency whose lifetime is unknown, so it "
                           f"may outlive and keep '{component}' alive (possible "
                           f"leak)")
            else:
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


def _consumer_related(c: Any) -> tuple[tuple[str, int, str], ...]:
    """The captive finding's **consuming constructor** as a structured related location
    (file, line, label), or empty when the extractor did not record a ctor location. The
    primary anchor stays the registration site; this is the second, code-side anchor. The
    label names the **implementation** type that owns the ctor (not the possibly-interface
    service name — Codex), falling back to a plain label when the impl type is unknown."""
    if getattr(c, "consumed_line", 0) >= 1:
        owner = getattr(c, "consumed_type", "") or ""
        label = (f"consuming constructor of '{owner}'" if owner and owner != "?"
                 else "consuming constructor")
        return ((c.consumed_file, c.consumed_line, label),)
    return ()


def _di004_primary(c: Any) -> tuple[str, int]:
    """DI004's primary anchor — the `GetRequiredService<T>()` **call site** (where the leak is
    and where it is fixed), falling back to the registration site when the extractor did not
    record the call. Unlike DI001/2/3 (a registration-graph property, anchored at the
    registration), DI004 is a call-site property, so the call site is the primary (Codex)."""
    if getattr(c, "resolved_line", 0) >= 1:
        return (c.resolved_file, c.resolved_line)
    return (c.file, c.line)


def _di004_related(c: Any) -> tuple[tuple[str, int, str], ...]:
    """The DI004 **registration** site as a structured related location — the secondary anchor,
    beside the call-site primary. Empty when the call site is unknown (then the registration is
    already the primary) or the registration line is unknown."""
    if getattr(c, "resolved_line", 0) >= 1 and getattr(c, "line", 0) >= 1:
        return ((c.file, c.line, f"registration of singleton '{c.singleton}'"),)
    return ()


def _di005_primary(c: Any) -> tuple[str, int]:
    """DI005's primary anchor — the field-assignment **cache site** (where the scope-resolved
    service is stored and where the leak is), falling back to the registration site when the
    extractor did not record it. Like DI004, DI005 is a call-/store-site property, not a
    registration-graph one, so the store site is the primary."""
    if getattr(c, "cached_line", 0) >= 1:
        return (c.cached_file, c.cached_line)
    return (c.file, c.line)


def _di005_related(c: Any) -> tuple[tuple[str, int, str], ...]:
    """The DI005 **registration** site as a structured related location — the secondary anchor
    beside the cache-site primary. Empty when the cache site is unknown (then the registration
    is already the primary) or the registration line is unknown."""
    if getattr(c, "cached_line", 0) >= 1 and getattr(c, "line", 0) >= 1:
        return ((c.file, c.line, f"registration of singleton '{c.singleton}'"),)
    return ()


def _resolve_sites(raw: Any) -> tuple[tuple[str, str, int], ...]:
    """Parse a service's optional `root_resolve_sites` (DI004 call-site metadata) into
    `(type, file, line)` triples. Tolerant for direct `check_facts` callers; `load()` does the
    strict shape check."""
    if not isinstance(raw, list):
        return ()
    return tuple(
        (str(x.get("type", "")), str(x.get("file", "?")), _as_int(x.get("line", 0)))
        for x in raw if isinstance(x, dict)
    )


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
            # services injected via WeakReference<T> — held weakly, off the DI001 strong
            # graph, but a weakly-held scoped service is still a captive (DI002).
            weak_deps=tuple(s.get("weak_deps", [])),
            # types resolved by hand from an injected IServiceProvider (GetService<T>) —
            # the service-locator call sites a singleton uses, checked for DI004.
            root_resolves=tuple(s.get("root_resolves", [])),
            # only the JSON boolean `true` counts — a stray string ("false") or other
            # type from a non-extractor producer must not coerce to a disposable=True.
            disposable=s.get("disposable") is True,
            file=str(s.get("file", "?")),
            line=_as_int(s.get("line", 0)),
            # the consuming constructor's location (where the capture is injected) — a
            # secondary anchor distinct from the registration site above (P-006 Q#1).
            ctor_file=str(s.get("ctor_file", "?")),
            ctor_line=_as_int(s.get("ctor_line", 0)),
            # the IMPLEMENTATION type owning that ctor — named in the finding instead of the
            # (possibly interface) service name, which would point at a ctor-less type (Codex).
            ctor_type=str(s.get("ctor_type", "")),
            # DI004 call-site metadata: where each root_resolves type was hand-resolved, so the
            # finding can anchor at the GetRequiredService call site (its real consumer).
            root_resolve_sites=_resolve_sites(s.get("root_resolve_sites", [])),
            # DI005: types resolved from a self-created scope and cached into a field, plus
            # where each was cached (the field-store site the finding anchors at).
            scope_cached=tuple(s.get("scope_cached", [])),
            scope_cache_sites=_resolve_sites(s.get("scope_cache_sites", [])),
        )
        for s in raw if isinstance(s, dict)
    ]
    out = [
        Finding(
            file=c.file, line=c.line, code="DI001",
            component=c.singleton, event=c.captured, handler="",
            message=c.message, kind="DI lifetime", related=_consumer_related(c))
        for c in find_captive_dependencies(services)
    ]
    # DI003: a transient IDisposable captured by a singleton is promoted to application
    # lifetime and disposed only at root disposal (P-006). A real verdict, but shown at
    # `warning` level — the framework allows it; the lifetime promotion is the smell.
    # Not `advisory` (that is for "not checked"): this IS checked and found.
    out += [
        Finding(
            file=c.file, line=c.line, code="DI003",
            component=c.singleton, event=c.captured, handler="",
            message=c.message, kind="DI lifetime", severity="warning",
            related=_consumer_related(c))
        for c in find_captured_transient_disposables(services)
    ]
    # DI002: a singleton holding a scoped service via WeakReference<T> (P-006). The weak
    # ref is the usual "fix" for a DI001 captive, but the scoped service is still
    # root-resolved and app-lived — the lifetime contract is still violated. A real
    # verdict shown at `warning` (the weak ref fixes the GC symptom, not the cause).
    out += [
        Finding(
            file=c.file, line=c.line, code="DI002",
            component=c.singleton, event=c.captured, handler="",
            message=c.message, kind="DI lifetime", severity="warning",
            related=_consumer_related(c))
        for c in find_weak_captive_dependencies(services)
    ]
    # DI004: a singleton that resolves a transient IDisposable BY HAND from its injected
    # root IServiceProvider (GetService<T>/GetRequiredService<T> — the service-locator
    # anti-pattern). The root tracks every disposable it resolves and frees them only at
    # app shutdown, so each call leaks a transient. A warning (the framework allows it; the
    # call-site lifetime promotion is the smell), and a CALL SITE the registration graph
    # (DI001/002/003) cannot see — only resolutions off the injected provider, never a
    # scope's, so the correct scope-resolution pattern stays silent.
    for c in find_explicit_root_resolutions(services):
        pf, pl = _di004_primary(c)   # the call site (its real consumer), or registration if unknown
        out.append(Finding(
            file=pf, line=pl, code="DI004",
            component=c.singleton, event=c.resolved, handler="",
            message=c.message, kind="DI lifetime", severity="warning",
            related=_di004_related(c)))
    # DI005: a singleton that resolves a scoped service from a scope it CREATES
    # (IServiceScopeFactory.CreateScope()) and CACHES it into a field — the scope-per-operation
    # fix done wrong. The cached instance dangles after the scope is disposed (use-after-dispose)
    # and is promoted to application lifetime (the captive returns, hidden behind the API that
    # was meant to fix it). A warning, anchored at the field-store site (its real consumer), with
    # the registration as the secondary — the store-site twin of DI004's call-site anchoring.
    for sc in find_scope_cached_captives(services):
        pf, pl = _di005_primary(sc)
        out.append(Finding(
            file=pf, line=pl, code="DI005",
            component=sc.singleton, event=sc.captured, handler="",
            message=sc.message, kind="DI lifetime", severity="warning",
            related=_di005_related(sc)))
    return out


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
