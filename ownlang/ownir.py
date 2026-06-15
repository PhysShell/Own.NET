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

An unreleased entry is the core's OWN001 (owned-but-not-released) at the C#
`line`. The `resource`/`type` fields are additive and optional, so they do NOT
bump `ownir_version`: an older core just reads every entry as a subscription.
Region escape (OWN014) is later (see docs/proposals/P-004).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .diagnostics import Severity

# The OwnIR schema version this core understands. Bump it whenever the fact
# vocabulary changes incompatibly; the extractor stamps the same number so a
# mismatched extractor/core pair fails loudly (see load()) instead of silently
# mis-reading facts.
OWNIR_VERSION = 0


class OwnIRError(ValueError):
    """A malformed or unmappable OwnIR fact set. Carries a human message; the
    driver turns it into a clear one-line error rather than a traceback."""


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
)

# OwnIR resource kinds the bridge knows how to lower: (own resource type to
# acquire, human kind tag the finding carries). `event +=` is a Subscription; a
# `Tick`/`Elapsed` handler on a started timer is a Timer (the running timer
# strong-refs the handler's owner); an `IDisposable` field the class `new`s is a
# Disposable it owns. Unknown values fall back to Subscription.
_RESOURCES = {
    "subscription": ("Subscription", "subscription token"),
    "timer": ("Timer", "timer"),
    "disposable": ("Disposable", "disposable field"),
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

    def render(self) -> str:
        return (f"{self.file}:{self.line}: error: [{self.code}] "
                f"{self.message} [resource: {self.kind}]")


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


def _handle_of(diag: object) -> str | None:
    """The synthetic handle (`sub_N`) a diagnostic is about, recovered from its
    structured `subject` (`name#line`) — NOT by scraping the human message. Each
    acquire stamps `subject` in cfg.lower_let; None means the diagnostic carries
    no subject identity at all."""
    subject = getattr(diag, "subject", None)
    if not subject:
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
    # imported here to avoid a module-level cycle (ownir is a leaf consumer).
    # v0 lowers to `.own` text and goes through _collect (parse + the one
    # checker). The next pattern (timers / region facts with no surface syntax)
    # builds a Module and calls __main__.check_module directly instead — the
    # seam is already split so that switch is additive, not a rewrite.
    from .__main__ import _collect

    src, handles = to_own(facts)
    diags, mod = _collect(src)
    if mod is None:
        # the only source here is our own generator, so a parse failure is an
        # internal bug in to_own, not bad user input — surface it loudly.
        msg = diags[0].message if diags else "unknown parse error"
        raise OwnIRError(
            f"internal: the lowered OwnIR module did not parse ({msg}). "
            f"This is a bug in the fact lowering, not in the facts.")

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
        else:
            message = (f"event '{event}' is subscribed (handler '{handler}') "
                       f"but never unsubscribed — the source keeps "
                       f"'{component}' alive (leak)")
        findings.append(Finding(
            file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
            component=component, event=event, handler=handler,
            message=message, kind=kind))
    findings.sort(key=lambda f: (f.file, f.line, f.code))
    return findings
