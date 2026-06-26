"""Reachability-slice evidence -> SARIF (P-015).

A finding is only as useful as the *path* it shows. A bare "OWN014: lifetime
promotion" or "DI001: captive dependency" tells a developer *that* something is
wrong; it does not answer the question they actually ask -- *why is this value
held, and through what?* (the data-flow reachability question ReachHover's study
found developers ask many times a day). This module turns an ordered chain of
program points into the two SARIF constructs that answer it:

  * ``relatedLocations`` -- unordered secondary anchors ("acquired here",
    "missing release here", "consuming constructor") that a consumer (GitHub
    code scanning, an IDE hover) renders as clickable, labelled links beside
    the primary location.
  * ``codeFlows`` -- an *ordered* slice: step 1 -> step 2 -> ... -> the finding.
    This is the reachability slice: e.g. a DI captive's
    ``singleton -> transient -> scoped`` retention path, each hop a real source
    location.

It is deliberately a pure, dependency-free transform over ``(file, line, label)``
triples so every producer in the core -- the OwnIR DI checker, the flow-sensitive
ownership checker, a future XAML->.g.cs join -- emits the same shape and any
consumer reads one vocabulary. Frontends produce facts; this is how the core
*explains* its verdicts.

The builders return plain SARIF fragments (no Own.NET types), so they compose
into either ``ownlang.ownir.build_sarif`` (the C# extractor path) or the audit
aggregator without a dependency either way.
"""

from __future__ import annotations

from typing import Iterable

# one evidence step: a source location plus the human label for what happens there.
Step = tuple[str, int, str]   # (file, line, label)


def _phys(file: str, line: int) -> dict:
    """A SARIF ``physicalLocation`` for a 1-based line. ``region`` is omitted for a
    file-level step (line < 1) so the location stays schema-valid rather than
    carrying a bogus ``startLine``."""
    loc: dict = {"artifactLocation": {"uri": file.replace("\\", "/")}}
    if line >= 1:
        loc["region"] = {"startLine": line}
    return loc


def related_locations(steps: Iterable[Step]) -> list[dict]:
    """SARIF ``relatedLocations`` from evidence steps -- the unordered secondary
    anchors. Steps without a resolvable line are dropped (a related location with
    nowhere to point is noise)."""
    return [
        {"physicalLocation": _phys(f, ln), "message": {"text": label}}
        for (f, ln, label) in steps if ln >= 1
    ]


def code_flow(steps: Iterable[Step]) -> list[dict]:
    """A SARIF ``codeFlows`` value (a one-element list) from an *ordered* slice of
    evidence steps -- the reachability path that leads to the finding. Returns
    ``[]`` when no step has a resolvable line, so a caller can splice the result
    conditionally (``if flow: result["codeFlows"] = flow``)."""
    locations = [
        {"location": {"physicalLocation": _phys(f, ln), "message": {"text": label}}}
        for (f, ln, label) in steps if ln >= 1
    ]
    if not locations:
        return []
    return [{"threadFlows": [{"locations": locations}]}]


def di_path_steps(path: tuple[str, ...],
                  loc_by_name: dict[str, tuple[str, int]],
                  end_label: str) -> tuple[Step, ...]:
    """Turn a DI dependency *path* (service names, captor first, captured last)
    into ordered evidence steps anchored at each service's registration site.

    ``loc_by_name`` maps a service name to its ``(file, line)`` registration
    location; a hop whose location is unknown is skipped (the slice stays ordered
    and truthful -- a partial registration graph yields a partial, not a wrong,
    path). The first hop is labelled the captor singleton, the last with
    ``end_label`` (which differs per family: "captures scoped service", "leaked
    transient IDisposable", ...), the middle hops as pass-through links.

    This is the concrete reachability slice the DI checker already computes (the
    ``path`` tuple on every captive finding) but today only renders into the
    message text -- here it becomes a structured ``codeFlows``.
    """
    n = len(path)
    steps: list[Step] = []
    for i, name in enumerate(path):
        loc = loc_by_name.get(name)
        if loc is None:
            continue
        f, ln = loc
        if i == 0:
            label = f"singleton '{name}' (captor)"
        elif i == n - 1:
            label = f"{end_label} '{name}'"
        else:
            label = f"via '{name}'"
        steps.append((f, ln, label))
    return tuple(steps)
