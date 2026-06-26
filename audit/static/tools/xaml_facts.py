#!/usr/bin/env python3
"""
Own.NET Audit — XAML facts extractor (Phase-2 seam).

The Phase-1 runner (``xaml_check.py``) turns markup into *rule findings* (SARIF).
This module turns the **same parsed tree** into structured *facts* — the seam the
Phase-2 binding-path join needs (``docs/notes/xaml-analyzer-design.md`` →
"Phase 2 mechanics"). It does **not** evaluate rules and emits **no** findings; it
emits a fact document per ``.xaml`` so the existing Roslyn extractor
(``frontend/roslyn/OwnSharp.Extractor`` → OwnIR) has something to join against.

Two fact families, exactly the design note's split:

* **XamlResourceGraph** — ``resources`` (keyed type + scope + line) and
  ``merged_dictionaries`` (include sources). Self-contained in markup.
* **XamlBindingFacts** — ``bindings`` (element, property, parsed binding path /
  mode / UpdateSourceTrigger / converter / Delay / RelativeSource), ``event_handlers``
  (``Click=``/``EventSetter``) and ``converters_used``. These are *pointers into C#*:
  on their own they are inert; the value is the join (binding ``path`` resolved
  against the ``x:Class`` / DataContext type by Roslyn → getter/converter/setter /
  PropertyChanged cascade). That resolution is the Roslyn step, not this one.

The envelope mirrors OwnIR's ``*.facts.json`` (``{ownir_version, module,
components}``) so the two fact sources read alike:

    {"xaml_facts_version": 0, "module": "...", "documents": [ {file, x_class,
     framework, resources[], merged_dictionaries[], bindings[], event_handlers[],
     converters_used[]} ], "totals": {...}}

Pure stdlib, build-free — it rides the same no-toolchain tier as ``xaml_check``.

Usage:
  xaml_facts.py --target /path/to/legacy/src --out artifacts/own-audit
  xaml_facts.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from xaml_check import Node, _is_avalonia, _keyed_resources, _resource_dictionaries, parse_xaml

# Common WPF/XAML routed events: an attribute with one of these names whose value is
# a bare identifier (not a markup extension) is a code-behind handler. Not exhaustive
# by design — facts are honest about what they captured; the join can be refined.
COMMON_EVENTS = {
    "Click", "Loaded", "Unloaded", "Initialized", "SelectionChanged", "TextChanged",
    "Checked", "Unchecked", "Closing", "Closed", "MouseDown", "MouseUp",
    "MouseDoubleClick", "PreviewMouseDown", "KeyDown", "KeyUp", "PreviewKeyDown",
    "GotFocus", "LostFocus", "DataContextChanged", "SizeChanged", "Drop", "DragEnter",
    "Expanded", "Collapsed", "ValueChanged", "Scroll",
}

_RESOURCE_REF_RE = re.compile(r"\{\s*(?:Static|Dynamic)Resource\s+([^}]+)\}", re.IGNORECASE)
_RELSOURCE_RE = re.compile(r"\{\s*RelativeSource\s+([^},]+)", re.IGNORECASE)


def _split_top_level(s: str) -> list[str]:
    """Split on commas at brace-depth 0, so a nested ``Converter={StaticResource c}``
    is not chopped at its inner comma."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _resource_key(val: str) -> str:
    """``{StaticResource boolToVis}`` -> ``boolToVis``; otherwise the raw value."""
    m = _RESOURCE_REF_RE.search(val)
    return m.group(1).strip() if m else val.strip()


def parse_binding(value: str) -> dict[str, Any] | None:
    """Parse a ``{Binding ...}`` / ``{TemplateBinding ...}`` markup extension into the
    fields the join cares about, or ``None`` if ``value`` is not a binding. The first
    positional token of a ``Binding`` is its ``Path`` (the ``{Binding Qty}`` form);
    ``{TemplateBinding Prop}`` is a binding to the templated parent."""
    v = value.strip()
    if not (v.startswith("{") and v.endswith("}")):
        return None
    inner = v[1:-1].strip()
    head, _, rest = inner.partition(" ")
    kind = head.lower()
    if kind not in ("binding", "templatebinding"):
        return None
    fact: dict[str, Any] = {
        "kind": "TemplateBinding" if kind == "templatebinding" else "Binding",
        "path": None, "mode": None, "update_source_trigger": None, "converter": None,
        "delay": None, "relative_source": None, "element_name": None, "source": None,
    }
    if kind == "templatebinding":
        fact["path"] = rest.strip() or None
        fact["relative_source"] = "TemplatedParent"
        return fact
    for i, raw in enumerate(_split_top_level(rest)):
        part = raw.strip()
        if not part:
            continue
        if "=" not in part:
            if i == 0:
                fact["path"] = part  # positional Path
            continue
        key, _, val = part.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key == "path":
            fact["path"] = val
        elif key == "mode":
            fact["mode"] = val
        elif key == "updatesourcetrigger":
            fact["update_source_trigger"] = val
        elif key == "converter":
            fact["converter"] = _resource_key(val)
        elif key == "delay":
            fact["delay"] = val
        elif key == "relativesource":
            m = _RELSOURCE_RE.search(val)
            fact["relative_source"] = m.group(1).strip() if m else val
        elif key == "elementname":
            fact["element_name"] = val
        elif key == "source":
            fact["source"] = val
    return fact


def document_facts(root: Node, rel_path: str) -> dict[str, Any]:
    """The fact document for one parsed ``.xaml`` tree: its resource graph, binding
    facts, event handlers and the converter keys it references."""
    resources: list[dict[str, Any]] = []
    for rd in _resource_dictionaries(root):
        scope = rd.type_name() if rd.is_property_element() else "root"
        for key, c in _keyed_resources(rd):
            resources.append({"key": key, "type": c.type_name(),
                              "scope": scope, "line": c.line})

    merged: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    handlers: list[dict[str, Any]] = []
    converters: set[str] = set()

    for n in root.walk():
        if n.local() == "MergedDictionaries" and n.is_property_element():
            for c in n.children:
                src = c.attr("Source")
                if src:
                    merged.append({"source": src.strip(), "line": c.line})
        if n.type_name() == "EventSetter":
            ev, h = n.attr("Event"), n.attr("Handler")
            if ev and h:
                handlers.append({"element": "EventSetter", "event": ev.strip(),
                                 "handler": h.strip(), "line": n.line})
        for k, v in n.attrib.items():
            b = parse_binding(v)
            if b is not None:
                prop = k.split(":", 1)[-1].rsplit(".", 1)[-1]
                bindings.append({"element": n.type_name(), "property": prop,
                                 "line": n.line, **b})
                if b["converter"]:
                    converters.add(b["converter"])
                continue
            ev = k.split(":", 1)[-1].rsplit(".", 1)[-1]
            if ev in COMMON_EVENTS and v.strip() and not v.strip().startswith("{"):
                handlers.append({"element": n.type_name(), "event": ev,
                                 "handler": v.strip(), "line": n.line})

    return {
        "file": rel_path,
        "x_class": root.attr("Class"),               # x:Class on the root, or None
        "framework": "avalonia" if _is_avalonia(root) else "wpf",
        "resources": resources,
        "merged_dictionaries": merged,
        "bindings": bindings,
        "event_handlers": handlers,
        "converters_used": sorted(converters),
    }


def module_facts(documents: list[dict[str, Any]], module: str = "target") -> dict[str, Any]:
    """Wrap per-document facts in the OwnIR-parallel envelope, with roll-up totals."""
    def total(field: str) -> int:
        return sum(len(d[field]) for d in documents)

    return {
        "xaml_facts_version": 0,
        "module": module,
        "documents": documents,
        "totals": {
            "documents": len(documents),
            "resources": total("resources"),
            "merged_dictionaries": total("merged_dictionaries"),
            "bindings": total("bindings"),
            "event_handlers": total("event_handlers"),
        },
    }


def build_facts(target: str) -> dict[str, Any]:
    """Parse every ``.xaml`` / ``.axaml`` under ``target`` into the module fact doc."""
    root = Path(target)
    documents: list[dict[str, Any]] = []
    if root.exists():
        for fp in sorted(p for p in root.rglob("*")
                         if p.suffix.lower() in (".xaml", ".axaml") and p.is_file()):
            try:
                data = fp.read_bytes()
            except OSError:
                continue
            tree = parse_xaml(data)
            if tree is None:
                continue
            documents.append(document_facts(tree, fp.relative_to(root).as_posix()))
    return module_facts(documents, module=root.name or "target")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract XAML facts (Phase-2 seam) -> JSON.")
    ap.add_argument("--target", help="path to the target source tree")
    ap.add_argument("--out", default="artifacts/own-audit", help="output directory")
    ap.add_argument("--selftest", action="store_true", help="run built-in checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.target:
        ap.error("--target is required (or use --selftest)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = build_facts(args.target)
    (out_dir / "xaml-facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(json.dumps(facts["totals"], indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Selftest — embedded fixtures; gates on Linux CI like the other build-free      #
# modules (no .NET, nothing on disk).                                            #
# --------------------------------------------------------------------------- #

_WPF_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
           'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')


def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    # --- binding markup parser ---
    b = parse_binding("{Binding Qty, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}")
    check(b is not None and b["path"] == "Qty" and b["mode"] == "TwoWay"
          and b["update_source_trigger"] == "PropertyChanged",
          f"positional path + mode + UST parse wrong: {b}")
    b = parse_binding("{Binding Path=Total, Converter={StaticResource money}}")
    check(b is not None and b["path"] == "Total" and b["converter"] == "money",
          f"Path= + nested Converter resource key parse wrong: {b}")
    b = parse_binding("{Binding Background, RelativeSource={RelativeSource TemplatedParent}}")
    check(b is not None and b["relative_source"] == "TemplatedParent",
          f"RelativeSource parse wrong: {b}")
    b = parse_binding("{TemplateBinding Padding}")
    check(b is not None and b["kind"] == "TemplateBinding" and b["path"] == "Padding"
          and b["relative_source"] == "TemplatedParent", f"TemplateBinding parse wrong: {b}")
    check(parse_binding("Hello") is None and parse_binding("{StaticResource x}") is None,
          "non-binding values must not parse as bindings")
    # the nested-comma split must not chop the Converter argument
    check(len(_split_top_level("Qty, Converter={StaticResource a,b}, Mode=OneWay")) == 3,
          "top-level comma split must respect nested braces")

    # --- document facts on a representative view ---
    doc_xaml = (f'<UserControl {_WPF_NS} x:Class="App.Views.CustomerView">\n'
                '  <UserControl.Resources>\n'
                '    <SolidColorBrush x:Key="PanelBrush" Color="Gray" />\n'
                '    <ResourceDictionary.MergedDictionaries>\n'
                '      <ResourceDictionary Source="Themes/Colors.xaml" />\n'
                '    </ResourceDictionary.MergedDictionaries>\n'
                '  </UserControl.Resources>\n'
                '  <StackPanel>\n'
                '    <TextBox Text="{Binding Name, Mode=TwoWay, '
                'UpdateSourceTrigger=PropertyChanged}" />\n'
                '    <TextBlock Text="{Binding Total, Converter={StaticResource money}}" />\n'
                '    <Button Click="OnSave" Content="Save" />\n'
                '  </StackPanel>\n'
                '</UserControl>\n')
    root = parse_xaml(doc_xaml)
    d = document_facts(root, "Views/CustomerView.xaml")

    check(d["x_class"] == "App.Views.CustomerView", f"x:Class not captured: {d['x_class']}")
    check(d["framework"] == "wpf", "framework should be wpf")
    check(any(r["key"] == "PanelBrush" and r["type"] == "SolidColorBrush"
              and r["scope"] == "UserControl" for r in d["resources"]),
          f"resource graph wrong: {d['resources']}")
    check(any(m["source"] == "Themes/Colors.xaml" for m in d["merged_dictionaries"]),
          "merged dictionary source not captured")
    names = {(x["element"], x["property"]): x for x in d["bindings"]}
    tb = names.get(("TextBox", "Text"))
    check(tb is not None and tb["path"] == "Name" and tb["update_source_trigger"]
          == "PropertyChanged" and tb["line"] == 9,
          f"TextBox binding fact wrong: {tb}")
    check(d["converters_used"] == ["money"], f"converters_used wrong: {d['converters_used']}")
    check(any(h["event"] == "Click" and h["handler"] == "OnSave"
              and h["element"] == "Button" for h in d["event_handlers"]),
          f"event handler not captured: {d['event_handlers']}")

    # EventSetter handlers, and "a binding value is not an event handler".
    es = parse_xaml(f'<Style {_WPF_NS}><EventSetter Event="Click" Handler="OnClick" /></Style>\n')
    esd = document_facts(es, "s.xaml")
    check(any(h["element"] == "EventSetter" and h["handler"] == "OnClick"
              for h in esd["event_handlers"]), "EventSetter handler not captured")

    # --- module envelope mirrors OwnIR's shape ---
    mod = module_facts([d], module="App")
    check(mod["xaml_facts_version"] == 0 and mod["module"] == "App"
          and mod["totals"]["bindings"] == 2 and mod["totals"]["documents"] == 1,
          f"module envelope/totals wrong: {mod['totals']}")
    # the whole doc must be JSON-serializable (it is written to disk)
    check(isinstance(json.dumps(mod), str), "module facts must be JSON-serializable")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"XAML_FACTS SELFTEST FAIL: {f}")
    print(f"xaml_facts selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
