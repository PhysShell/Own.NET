"""
OwnIR fact bridge (P-001 v0): C# leak facts -> the existing OwnLang core.

A Roslyn extractor (frontend/roslyn/, CI-only) scans real C# and emits *facts* in
the spec's vocabulary; this module ingests them, routes them through the proven
checker, and maps the verdict back to the original C# location. The core stays a
single checker — we do not reimplement it in C# (a second checker would drift).

OwnIR v0 schema (JSON)::

    {
      "module": "WpfApp",
      "components": [
        {
          "name": "CustomerViewModel",
          "file": "CustomerViewModel.cs",
          "subscriptions": [
            {"event": "bus.CustomerChanged", "handler": "OnCustomerChanged",
             "line": 12, "released": false}
          ]
        }
      ]
    }

A subscription is modelled as an owned `Subscription` resource: `event +=` is an
`acquire`, a matching `-=` / Dispose is a `release`. An unreleased subscription
is therefore the core's OWN001 (owned-but-not-released), carrying the
`[resource: subscription token]` kind tag — surfaced at the C# `line`.

v0 covers exactly the `event += without -=` pattern (released == false -> leak).
Timers, IDisposable fields and region escape are later (see docs/proposals/P-001).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .diagnostics import _SUBJECT_RE, Severity

_PRELUDE = (
    'resource Subscription {\n'
    '    acquire Subscribe\n'
    '    release Dispose\n'
    '    kind "subscription token"\n'
    '}\n'
)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    code: str
    component: str
    event: str
    handler: str
    message: str

    def render(self) -> str:
        return (f"{self.file}:{self.line}: error: [{self.code}] "
                f"{self.message} [resource: subscription token]")


def load(path: str) -> dict[str, Any]:
    """Load an OwnIR facts file."""
    with open(path, encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
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
    for comp in facts.get("components", []):
        cname = comp.get("name", f"Component{gid}")
        lines.append(f"fn {cname}() {{")
        for sub in comp.get("subscriptions", []):
            handle = f"sub_{gid}"
            gid += 1
            handles[handle] = {**sub, "component": cname,
                               "file": comp.get("file", "?")}
            lines.append(f"    let {handle} = acquire Subscription();")
            if sub.get("released"):
                lines.append(f"    release {handle};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines), handles


def check_facts(facts: dict[str, Any]) -> list[Finding]:
    """Run the core checker over the lowered facts and return findings mapped
    back to their original C# locations (v0: the `event += without -=` leak)."""
    # imported here to avoid a module-level cycle (ownir is a leaf consumer)
    from .__main__ import _collect

    src, handles = to_own(facts)
    diags, _ = _collect(src)
    findings: list[Finding] = []
    for d in diags:
        if d.severity != Severity.ERROR:
            continue
        m = _SUBJECT_RE.search(d.message)
        sub = handles.get(m.group(1)) if m else None
        if sub is None:
            continue
        findings.append(Finding(
            file=sub["file"], line=int(sub.get("line", 0)), code=d.code,
            component=sub["component"], event=sub.get("event", "?"),
            handler=sub.get("handler", "?"),
            message=(f"event '{sub.get('event', '?')}' is subscribed "
                     f"(handler '{sub.get('handler', '?')}') but never "
                     f"unsubscribed — the source keeps "
                     f"'{sub['component']}' alive (leak)")))
    findings.sort(key=lambda f: (f.file, f.line, f.code))
    return findings
