#!/usr/bin/env python3
"""
Own.NET Audit — XAML ↔ C# Phase-2 join (build-free, convention-based).

Phase 1 emits two fact sources independently: ``xaml-facts.json`` (this repo's XAML
extractor) and OwnIR ``*.facts.json`` (the ``OwnSharp.Extractor`` → core pipeline,
which already computes the acquire/release verdict per subscription). Phase 2 is the
*join*: link a XAML pointer to its C# symbol and let the interprocedural engine's
existing facts speak — markup and code stitched into one finding instead of two
disconnected alerts (``docs/notes/xaml-analyzer-design.md`` → "Phase 2 mechanics").

**The link is the deterministic XAML naming convention, not the build artifact.** A
``.g.cs`` (InitializeComponent / IComponentConnector glue) would only exist after a
successful markup-compile, which would drag the join into the build-required tier;
but the wiring it encodes is a fixed contract we can synthesize without building:

  * ``x:Class="App.Views.CustomerView"``  → the code-behind partial type
    ``CustomerView`` (OwnIR ``components[].name``, matched on the unqualified name).
  * ``Loaded="OnLoaded"`` / ``Click="OnSave"`` → a method on that type.
  * ``x:Name="btn"``  → a generated field of that type.
  * ``{Binding Qty}``  → a property on the DataContext type.

So this stays build-free (Linux CI, broken solutions) like the rest of the static
layer. A ``.g.cs`` ground-truth cross-check is a documented build-tier follow-up,
not the mechanism.

Rule implemented (first slice):

  **XAML203 ViewSubscribesWithoutRelease** (cat 2 — subscription leak / region
  escape, P1). A view whose ``x:Class`` component has a subscription the engine
  flagged ``released: false`` AND which wires a *load-lifecycle* handler
  (``Loaded`` / ``Initialized`` / ``DataContextChanged``) in markup: the view is the
  lifetime owner that subscribed but never releases, so a closed view is retained.
  ``released: false`` is authoritative — the engine already checked for a matching
  ``-=`` anywhere in the class (code-behind included) — so no XAML ``Unloaded``
  heuristic is needed. The finding is anchored at the **code-behind subscription
  site** (where the matching ``-=`` goes), with the XAML view + the lifecycle handler
  that wired it named in the message. It is mapped to category 2 (subscription leak),
  so it lands at the same file+line as own-check's ``OWN001`` and **clusters with it
  into one high-confidence finding** — two independent sources agreeing on the leak
  (the static→static agreement of Plan.md §3.5) — instead of double-reporting it on a
  separate ``.xaml`` line. The join's value is exactly this: it upgrades the
  own-check subscription finding to high-confidence and tags it as a view-lifecycle
  (closed-view-retained) leak, not a second copy of it. Phase 3 promotes it to a
  measured retention path via the heap walker.

Binding-path-hotness rules (XAML200/204) need the DataContext type, which markup
rarely declares statically; they are a later increment, deliberately not guessed
here.

Usage:
  xaml_join.py --xaml-facts xaml-facts.json --ownir own-check.facts.json --out DIR
  xaml_join.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Lifecycle events whose handler runs as the view comes up: a subscription wired from
# here is owned by the view's lifetime, so an unreleased one leaks the closed view.
LOAD_LIFECYCLE_EVENTS = {"Loaded", "Initialized", "DataContextChanged"}

# OwnIR's components[].subscriptions is an UMBRELLA list: an untagged entry is a plain
# event `+=` subscription, but the same list also carries timer / IDisposable / pool
# leaks tagged via `resource`. XAML203 is specifically the category-2 *event
# subscription leak / region escape* lane, so it fires on subscription-family records
# — including `capture` (a static/process-lived event subscription that retains the
# subscriber, the OWN014 region-escape case, which is exactly a closed-view-retained
# leak) — but NOT timer/disposable/pool, which are other categories (3 / 1) already
# covered by own-check on the .cs.
SUBSCRIPTION_RESOURCES = {None, "", "subscribe", "subscription", "subscription token",
                          "event", "capture"}


def _component_index(ownir: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Index OwnIR components by their unqualified type name (``CustomerView``), so a
    fully-qualified ``x:Class`` (``App.Views.CustomerView``) links by its last
    segment — the same basename-keyed robustness the rest of the audit uses for
    cross-tool matching. Same-name collisions are disambiguated by code-behind path
    in ``_linked_components`` (a name index can hold several entries)."""
    idx: dict[str, list[dict[str, Any]]] = {}
    for c in ownir.get("components") or []:
        name = str(c.get("name", ""))
        if name:
            idx.setdefault(name.rsplit(".", 1)[-1], []).append(c)
    return idx


def _stem(path: str, suffixes: tuple[str, ...]) -> str:
    """``path`` with the first matching suffix stripped, forward-slashed."""
    p = str(path).replace("\\", "/")
    for suf in suffixes:
        if p.endswith(suf):
            return p[: -len(suf)]
    return p


def _path_corresponds(xaml_file: str, component_file: str) -> bool:
    """True if an OwnIR component's source file is the code-behind of this XAML — its
    path stem (``Views/Admin/CustomerView`` after stripping ``.xaml.cs``/``.cs``)
    matches the XAML's stem on a path-segment boundary. Suffix match tolerates the
    prefix differences between how the two tools report paths."""
    xs = _stem(xaml_file, (".axaml", ".xaml"))
    cs = _stem(component_file, (".xaml.cs", ".axaml.cs", ".g.cs", ".g.i.cs", ".cs"))
    if not xs or not cs:
        return False
    longer, shorter = (xs, cs) if len(xs) >= len(cs) else (cs, xs)
    return longer == shorter or longer.endswith("/" + shorter)


def _linked_components(doc: dict[str, Any],
                       by_name: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The OwnIR component(s) that are this view's code-behind, matched by
    code-behind-path correspondence. The simple-name index drops the namespace, so a
    *unique* basename hit can still be the wrong type (``App.Views.CustomerView`` vs an
    unrelated ``Legacy.CustomerView``); every candidate — single or not — is therefore
    path-checked against the XAML's file, and a non-corresponding match links nothing
    rather than cross-link. The only fallback is a lone candidate with no file metadata
    to check against (best effort)."""
    x_class = doc.get("x_class")
    if not x_class:
        return []
    cands = by_name.get(str(x_class).rsplit(".", 1)[-1], [])
    matches = [c for c in cands
               if _path_corresponds(str(doc.get("file", "")), str(c.get("file", "")))]
    if matches:
        return matches
    return cands if len(cands) == 1 and not cands[0].get("file") else []


def _unreleased(component: dict[str, Any]) -> list[dict[str, Any]]:
    """Event subscriptions the engine flagged as never released (the authoritative
    leak verdict — it already looked for a matching ``-=`` across the whole class),
    excluding the non-subscription resource leaks (timer / disposable / pool) that
    share the OwnIR subscriptions list."""
    return [s for s in (component.get("subscriptions") or [])
            if s.get("released") is False and s.get("resource") in SUBSCRIPTION_RESOURCES]


def join(xaml_facts: dict[str, Any], ownir: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce XAML203 link findings from the two fact sources. Each finding is a
    plain dict ``{rule, path, line, message, resource}`` ready for SARIF.

    One finding **per unreleased subscription**, anchored at the **code-behind
    subscription site** (``component.file : subscription.line``) — the same spot
    own-check reports OWN001, and where the matching ``-=`` actually goes. That makes
    the join cluster with own-check into one **high-confidence** finding (two sources
    agree) instead of double-reporting the same leak on a separate ``.xaml`` line; the
    XAML view + the lifecycle handler that wired it ride in the message. (Only a
    component with no file metadata falls back to anchoring on the XAML itself.)"""
    by_name = _component_index(ownir)
    out: list[dict[str, Any]] = []

    for doc in xaml_facts.get("documents") or []:
        x_class = doc.get("x_class")
        if not x_class:
            continue  # no code-behind type to link against
        components = _linked_components(doc, by_name)
        if not components:
            continue  # x:Class resolves to no (unambiguous) OwnIR component

        load_handlers = [h for h in (doc.get("event_handlers") or [])
                         if h.get("event") in LOAD_LIFECYCLE_EVENTS]
        if not load_handlers:
            continue  # the leak exists but is not wired from a view-lifecycle handler

        anchor = min(load_handlers, key=lambda h: h.get("line") or 0)
        view = str(x_class).rsplit(".", 1)[-1]
        xaml_file = doc.get("file", "?")
        wired = f"{anchor['event']}={anchor.get('handler', '?')}"
        for c in components:
            cb = c.get("file")
            for s in _unreleased(c):
                ev = s.get("event", "?")
                if cb:                                  # anchor on the code-behind
                    path, line = cb, (s.get("line") or 0)
                else:                                   # no file -> fall back to markup
                    path, line = xaml_file, (anchor.get("line") or 0)
                out.append({
                    "rule": "XAML203",
                    "path": path,
                    "line": line,
                    "message": (
                        f"view {view} ({xaml_file}, {wired}) subscribes to {ev} "
                        "without releasing — a closed view is retained; add the "
                        "matching unsubscribe [resource: subscription token]"),
                    "resource": "subscription token",
                })
    return out


def to_sarif(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Canonical SARIF 2.1.0 (the shape parse_sarif reads), tool ``xaml-join``."""
    results: list[dict[str, Any]] = []
    for f in findings:
        phys: dict[str, Any] = {"artifactLocation": {"uri": f["path"]}}
        if f.get("line", 0) >= 1:
            phys["region"] = {"startLine": f["line"]}
        results.append({
            "ruleId": f["rule"], "level": "warning",
            "message": {"text": f["message"]},
            "locations": [{"physicalLocation": phys}],
        })
    return {"version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "xaml-join",
                                          "informationUri": "https://github.com/physshell/own.net",
                                          "rules": []}},
                      "results": results}]}


def run_join(xaml_facts_path: Path, ownir_path: Path, out_dir: Path) -> dict[str, Any]:
    """Join ``xaml-facts.json`` with an OwnIR facts file, writing
    ``out_dir/xaml-join.sarif``. Best-effort: a missing/garbled input yields
    ``available=False`` with a reason, never a crash."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sarif_path = out_dir / "xaml-join.sarif"
    status: dict[str, Any] = {"tool": "xaml-join", "tier": "build-free",
                              "available": False, "sarif": None, "reason": ""}
    try:
        xaml_facts = json.loads(xaml_facts_path.read_text(encoding="utf-8"))
        ownir = json.loads(ownir_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        status["reason"] = f"could not read join inputs: {exc}"
        return status

    findings = join(xaml_facts, ownir)
    try:
        sarif_path.write_text(json.dumps(to_sarif(findings), indent=2), encoding="utf-8")
    except OSError as exc:
        status["reason"] = f"failed to write xaml-join.sarif: {exc}"
        return status
    status.update(available=True, sarif=str(sarif_path), findings=len(findings))
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Join XAML facts with OwnIR -> XAML2xx SARIF.")
    ap.add_argument("--xaml-facts", help="path to xaml-facts.json")
    ap.add_argument("--ownir", help="path to an OwnIR *.facts.json")
    ap.add_argument("--out", default="artifacts/own-audit", help="SARIF output directory")
    ap.add_argument("--selftest", action="store_true", help="run built-in checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not (args.xaml_facts and args.ownir):
        ap.error("--xaml-facts and --ownir are required (or use --selftest)")

    status = run_join(Path(args.xaml_facts), Path(args.ownir), Path(args.out))
    print(json.dumps(status, indent=2))
    return 0 if status["available"] else 1


# --------------------------------------------------------------------------- #
# Selftest — embedded fact fixtures; gates on Linux CI, no .NET / no files.      #
# --------------------------------------------------------------------------- #

def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    # A view that wires Loaded and whose component has an unreleased subscription.
    xaml_facts = {"documents": [
        {"file": "Views/CustomerView.xaml", "x_class": "App.Views.CustomerView",
         "event_handlers": [{"element": "UserControl", "event": "Loaded",
                             "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
        # a view with a load handler but NO matching unreleased subscription -> clean
        {"file": "Views/CleanView.xaml", "x_class": "App.Views.CleanView",
         "event_handlers": [{"element": "UserControl", "event": "Loaded",
                             "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
        # a leaking component but the view wires no lifecycle handler -> not XAML203
        {"file": "Views/NoLifecycle.xaml", "x_class": "App.Views.NoLifecycle",
         "event_handlers": [{"element": "Button", "event": "Click",
                             "handler": "OnClick", "line": 7}],
         "bindings": [], "named_elements": []},
        # a view whose component's unreleased record is a TIMER, not an event
        # subscription -> NOT XAML203 (own-check covers timer leaks at cat 3).
        {"file": "Views/TimerView.xaml", "x_class": "App.Views.TimerView",
         "event_handlers": [{"element": "UserControl", "event": "Loaded",
                             "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
        # two views share the simple name OrderView in different namespaces/folders;
        # the leak is in Sales, so it must land on Sales's XAML, never Admin's.
        {"file": "Views/Admin/OrderView.xaml", "x_class": "Admin.OrderView",
         "event_handlers": [{"event": "Loaded", "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
        {"file": "Views/Sales/OrderView.xaml", "x_class": "Sales.OrderView",
         "event_handlers": [{"event": "Loaded", "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
        # a view that subscribes to a static/process-lived event (resource: capture,
        # the OWN014 region-escape case) without release -> IS a XAML203.
        {"file": "Views/CaptureView.xaml", "x_class": "App.Views.CaptureView",
         "event_handlers": [{"event": "Loaded", "handler": "OnLoaded", "line": 4}],
         "bindings": [], "named_elements": []},
    ]}
    ownir = {"ownir_version": 0, "module": "App", "components": [
        {"name": "CustomerView", "file": "Views/CustomerView.xaml.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 21, "released": False}]},
        {"name": "CleanView", "file": "Views/CleanView.xaml.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 21, "released": True}]},
        {"name": "NoLifecycle", "file": "Views/NoLifecycle.xaml.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 30, "released": False}]},
        {"name": "TimerView", "file": "Views/TimerView.xaml.cs", "subscriptions": [
            {"event": "_timer.Tick", "handler": "OnTick", "line": 18,
             "released": False, "resource": "timer"}]},
        {"name": "OrderView", "file": "Views/Admin/OrderView.xaml.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 21, "released": True}]},
        {"name": "OrderView", "file": "Views/Sales/OrderView.xaml.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 21, "released": False}]},
        {"name": "CaptureView", "file": "Views/CaptureView.xaml.cs", "subscriptions": [
            {"event": "AppDomain.UnhandledException", "handler": "OnErr", "line": 14,
             "released": False, "resource": "capture"}]},
    ]}

    findings = join(xaml_facts, ownir)
    # One finding per leaking subscription, ANCHORED ON THE CODE-BEHIND (.xaml.cs) so it
    # clusters with own-check's OWN001 — keyed here by that path.
    by_path = {f["path"]: f for f in findings}

    check(len(findings) == 3, f"expected exactly 3 XAML203, got {len(findings)}: {findings}")
    check("Views/CaptureView.xaml.cs" in by_path,
          "a 'capture' (region-escape) subscription must be a XAML203")
    f = by_path.get("Views/CustomerView.xaml.cs")
    check(f is not None and f["rule"] == "XAML203" and f["line"] == 21,
          f"XAML203 must anchor at the code-behind subscription line (21): {f}")
    check(f is not None and "_bus.Changed" in f["message"]
          and "CustomerView" in f["message"] and "Views/CustomerView.xaml" in f["message"]
          and "Loaded=OnLoaded" in f["message"],
          f"XAML203 message must name the view, its XAML, the handler and the event: {f}")
    check(f is not None and f["resource"] == "subscription token",
          "XAML203 must carry the subscription-token resource tag (cat-2 mapping)")
    check("Views/CleanView.xaml.cs" not in by_path,
          "a released subscription must NOT produce a finding")
    check("Views/NoLifecycle.xaml.cs" not in by_path,
          "a leak with no view-lifecycle handler must NOT be XAML203 (own-check covers it)")
    check("Views/TimerView.xaml.cs" not in by_path,
          "an unreleased TIMER (not an event subscription) must NOT be a cat-2 XAML203")
    # same-name disambiguation: the Sales leak lands on Sales's code-behind, not Admin's.
    check("Views/Admin/OrderView.xaml.cs" not in by_path,
          "a leak in Sales.OrderView must NOT cross-link to Admin.OrderView")
    so = by_path.get("Views/Sales/OrderView.xaml.cs")
    check(so is not None and "Views/Sales/OrderView.xaml" in so["message"],
          f"XAML203 must anchor on Sales's code-behind and name Sales's view: {so}")

    # x:Class that resolves to no component -> nothing (not analysed / no leak).
    unknown_doc = {"documents": [{"file": "x.xaml", "x_class": "App.Unknown",
                   "event_handlers": [{"event": "Loaded", "handler": "H", "line": 1}]}]}
    check(join(unknown_doc, ownir) == [],
          "an x:Class with no matching OwnIR component must yield nothing")

    # a UNIQUE basename match whose code-behind path does not correspond is the wrong
    # namespace's class -> must NOT cross-link (path-checked even when unique).
    wrong_ns = {"documents": [{"file": "Features/Billing/CustomerView.xaml",
                "x_class": "Billing.CustomerView",
                "event_handlers": [{"event": "Loaded", "handler": "OnLoaded", "line": 4}]}]}
    other = {"ownir_version": 0, "components": [
        {"name": "CustomerView", "file": "Legacy/CustomerView.cs", "subscriptions": [
            {"event": "_bus.Changed", "handler": "OnChanged", "line": 9, "released": False}]}]}
    check(join(wrong_ns, other) == [],
          "a unique basename match with a non-corresponding code-behind path must not cross-link")

    # SARIF round-trips through the shared parse_sarif with the anchor line intact.
    sarif = to_sarif(findings)
    here = Path(__file__).resolve()
    sys.path.insert(0, str(here.parents[3] / "scripts"))
    try:
        from oracle_compare import parse_sarif
        parsed = parse_sarif(json.dumps(sarif), "xaml-join", [])
        cust = next((p for p in parsed if p.path.endswith("CustomerView.xaml.cs")), None)
        check(len(parsed) == len(findings) and cust is not None
              and cust.rule == "XAML203" and cust.line == 21,
              "SARIF round-trip must preserve every XAML203 at its code-behind line (21)")
    except ImportError:
        check(False, "could not import scripts/oracle_compare.parse_sarif for round-trip")

    fails = [c for c in checks if c]
    for c in fails:
        print(f"XAML_JOIN SELFTEST FAIL: {c}")
    print(f"xaml_join selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
