#!/usr/bin/env python3
"""
Own.NET Audit — XAML analyzer runner (build-free tier).

Phase 1 of the XAML analyzer described in ``docs/notes/xaml-analyzer-design.md``:
a *markup-only* static pass over ``.xaml`` / ``.axaml`` that needs **no .NET build
and no stand**. It is a second fact source feeding the existing ``audit/`` pipeline
— it emits the same SARIF record the own-check / CodeQL runners do, so a XAML
finding rides the existing normalize → score → SARIF → baseline → ratchet path for
free (the one architectural decision in the design note: *XAML is another fact
source, not a parallel linter*).

Because it is pure stdlib XML (no ``dotnet``, no ``lxml``), it runs on Linux in CI
like the other build-free runners here, and — unlike own-check — it has **no
toolchain prerequisite**, so it is never NO-TOOL for lack of an SDK.

Line preservation is a hard requirement, not a detail (design note): a naive
``ElementTree.parse`` drops source positions and ``report/sarif.py`` maps a
missing/0 line to SARIF ``startLine=1``, which would point *every* XAML alert at
the top of the file. We therefore build the tree through ``expat`` directly,
stamping each element with ``CurrentLineNumber`` — stdlib, no third-party dep. A
rule that can only locate a *file-level* issue emits line 0 on purpose (parse_sarif
records 0; report/sarif.py then omits the region rather than fabricating line 1),
so it stays honestly file-level instead of mis-pinning.

Phase-1 rules implemented here (see the catalogue in the design note). Each is the
perf/lifetime axis that WpfAnalyzers / PropertyChangedAnalyzers do **not** cover —
we deliberately do not re-implement their correctness rules:

  XAML101  DuplicateStatelessConverterResource  (cat 9)  per-instance resource churn
  XAML102  DynamicResourceLikelyStatic          (cat 9)  WPF-only, deferred-lookup cost
  XAML103  SuspiciousSharedFalse                (cat 9)  WPF-only, x:Shared opt-out
  XAML104  DuplicateMergedDictionaryInclude     (cat 9)  wasted load + order ambiguity
  XAML106  FreezableResourceShouldFreeze        (cat 9)  WPF-only, change-notify overhead
  XAML107  VirtualizationExplicitlyDisabled     (cat 8)  virtualization accidentally killed
  XAML108  PerKeystrokeBindingWithoutDelay      (cat 6)  per-keystroke source flooding
  XAML109  TemplateComplexityHigh               (cat 8)  visual-tree / layout inflation
  XAML110  ImageDecodedAtFullSize               (cat 9)  WPF-only, thumbnail full-size decode
  XAML111  LayoutTransformSuspicious            (cat 8)  WPF-only, layout-pass cost
  XAML112  TemplateBindingOpportunity           (cat 9)  cheaper compiled binding available
  XAML113  InlineFreezableDuplication           (cat 9)  identical inline brush/geometry

Deferred to a later Phase-1 slice (documented so nothing on the wishlist quietly
falls through — the design note's stated goal): XAML100 ResourceShouldBeHoisted
(needs the cross-sibling scope model) and XAML105 MergedDictionaryKeyShadowing
across *external* dictionaries (needs cross-file resolution). Phase 2 (Roslyn-linked
XAML2xx) and Phase 3 (runtime correlation) live elsewhere per the design note.

WPF-only rules (XAML102/103/106) are skipped on Avalonia ``.axaml`` because the
``DynamicResource`` / ``x:Shared`` / ``Freezable`` semantics differ or do not exist
(the today/never line from the coverage matrix).

Usage:
  xaml_check.py --target /path/to/legacy/src --out artifacts/own-audit
  xaml_check.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.parsers.expat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ItemsControl-family types whose virtualization we care about (XAML107/109 anchors).
ITEMS_CONTROLS = {
    "ListBox", "ListView", "DataGrid", "TreeView", "ComboBox", "ItemsControl",
    "GridView", "DataGridControl", "Selector", "HeaderedItemsControl",
}
# Panels that DO virtualize — an ItemsPanel of any other panel disables it.
VIRTUALIZING_PANELS = {"VirtualizingStackPanel", "VirtualizingPanel", "ItemsRepeater"}
NON_VIRTUALIZING_PANELS = {"StackPanel", "WrapPanel", "UniformGrid", "DockPanel", "Canvas"}

# Freezable resource types that benefit from PresentationOptions:Freeze (XAML106).
FREEZABLE_TYPES = {
    "SolidColorBrush", "LinearGradientBrush", "RadialGradientBrush", "ImageBrush",
    "DrawingBrush", "GeometryDrawing", "ImageDrawing", "DrawingImage", "DrawingGroup",
    "PathGeometry", "StreamGeometry", "RectangleGeometry", "EllipseGeometry",
    "LineGeometry", "CombinedGeometry", "GeometryGroup", "MatrixTransform",
    "RotateTransform", "ScaleTransform", "SkewTransform", "TranslateTransform",
    "TransformGroup", "BitmapImage",
}
# Resource keys that are legitimately dynamic (theme/system) — XAML102 must skip.
DYNAMIC_KEY_PREFIXES = ("System", "Theme", "{x:Static")
DYNAMIC_KEY_TYPES = ("SystemColors", "SystemParameters", "SystemFonts")

# Binding markers for XAML108 (per-keystroke source updates).
_TWOWAY_RE = re.compile(r"Mode\s*=\s*TwoWay", re.IGNORECASE)
_PROPCHANGED_RE = re.compile(r"UpdateSourceTrigger\s*=\s*PropertyChanged", re.IGNORECASE)
_DELAY_RE = re.compile(r"\bDelay\s*=", re.IGNORECASE)
_BINDING_RE = re.compile(r"\{\s*Binding\b", re.IGNORECASE)
# Properties whose source update genuinely floods per keystroke when un-delayed.
EDITABLE_PROPS = {"Text", "Value", "SelectedText", "SearchText", "FilterText", "Password"}

# Markers that make a Freezable un-freezable (XAML106 exception list).
_DYNAMIC_REF_RE = re.compile(r"\{\s*(DynamicResource|Binding|TemplateBinding|x:Reference)\b",
                             re.IGNORECASE)

# XAML112 — a TemplatedParent binding that could be the cheaper {TemplateBinding}.
_TPARENT_RE = re.compile(r"TemplatedParent", re.IGNORECASE)
_CONVERTER_RE = re.compile(r"\bConverter\s*=", re.IGNORECASE)
# XAML110 — an Image whose explicit display size is at or below this is a thumbnail,
# so a full-size decode (string Source, no DecodePixelWidth) is wasteful.
THUMBNAIL_MAX_DIP = 96.0

TEMPLATE_TYPES = {"ControlTemplate", "DataTemplate", "HierarchicalDataTemplate",
                  "ItemsPanelTemplate"}
TRIGGER_TYPES = {"Trigger", "DataTrigger", "MultiTrigger", "MultiDataTrigger",
                 "EventTrigger"}


@dataclass
class Node:
    """A line-stamped XML element. ``tag`` keeps the source prefix (e.g. ``x:Key``,
    ``ListBox.ItemsPanel``); helpers below strip it when matching."""

    tag: str
    attrib: dict[str, str]
    line: int
    children: list[Node] = field(default_factory=list)
    parent: Node | None = None

    def local(self) -> str:
        """The unqualified element name: ``controls:DataGrid`` -> ``DataGrid``;
        a property element ``ListBox.ItemsPanel`` -> ``ItemsPanel`` (the last dotted
        part), so callers test ``is_property_element`` first when they need either."""
        bare = self.tag.split(":", 1)[-1]
        return bare.rsplit(".", 1)[-1]

    def type_name(self) -> str:
        """The owning type name, ignoring any property-element suffix:
        ``ListBox.ItemsPanel`` -> ``ListBox``; ``controls:DataGrid`` -> ``DataGrid``."""
        bare = self.tag.split(":", 1)[-1]
        return bare.split(".", 1)[0]

    def is_property_element(self) -> bool:
        return "." in self.tag.split(":", 1)[-1]

    def attr(self, name: str) -> str | None:
        """Attribute by local name, prefix-insensitive (``x:Key`` matches ``Key``)."""
        for k, v in self.attrib.items():
            if k.split(":", 1)[-1] == name:
                return v
        return None

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def parse_xaml(text: str) -> Node | None:
    """Build a line-stamped ``Node`` tree from XAML markup via expat, or ``None`` if
    the markup is not well-formed (a broken file is skipped, never a crash — the
    continue-on-error discipline of the static layer). expat tracks
    ``CurrentLineNumber`` so every element carries its real source line; names are
    kept *as written* (prefixes intact), which is exactly what XAML tree patterns
    match on."""
    parser = xml.parsers.expat.ParserCreate()
    root: list[Node | None] = [None]
    stack: list[Node] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        node = Node(tag=name, attrib=dict(attrs), line=parser.CurrentLineNumber,
                    parent=stack[-1] if stack else None)
        if stack:
            stack[-1].children.append(node)
        else:
            root[0] = node
        stack.append(node)

    def end(_name: str) -> None:
        if stack:
            stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(text, True)
    except xml.parsers.expat.ExpatError:
        return None
    return root[0]


@dataclass
class XamlFinding:
    rule: str
    line: int
    message: str


def _is_avalonia(root: Node) -> bool:
    """Avalonia ``.axaml`` declares the avaloniaui default namespace; the WPF-only
    rules key off this to stay on the right side of the today/never line."""
    for k, v in root.attrib.items():
        if k == "xmlns" or k.startswith("xmlns"):
            if "avaloniaui" in v or "avalonia" in v.lower():
                return True
    return False


# --------------------------------------------------------------------------- #
# Rules. Each takes the parsed root and yields XamlFindings stamped to the      #
# offending element's real line.                                               #
# --------------------------------------------------------------------------- #

def _rule_virtualization(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML107 — virtualization explicitly disabled on a list-family control."""
    out: list[XamlFinding] = []
    for n in root.walk():
        if n.is_property_element():
            # An <X.ItemsPanel> whose template panel is non-virtualizing kills it.
            if n.local() == "ItemsPanel" and n.type_name() in ITEMS_CONTROLS:
                tmpl = next((c for c in n.children if c.local() == "ItemsPanelTemplate"),
                            None)
                panels = (tmpl.children if tmpl else n.children)
                for p in panels:
                    if p.type_name() in NON_VIRTUALIZING_PANELS:
                        out.append(XamlFinding(
                            "XAML107", p.line,
                            f"{n.type_name()} uses a non-virtualizing ItemsPanel "
                            f"({p.type_name()}); large item counts realize every "
                            "container [resource: virtualization]"))
            continue
        if n.type_name() not in ITEMS_CONTROLS:
            continue
        # Attached/attribute opt-outs that switch virtualization off.
        for k, v in n.attrib.items():
            local = k.split(":", 1)[-1].rsplit(".", 1)[-1]
            if local == "IsVirtualizing" and v.strip().lower() == "false":
                out.append(XamlFinding(
                    "XAML107", n.line,
                    f"{n.type_name()} sets {k}=False, disabling UI virtualization "
                    "[resource: virtualization]"))
            elif local == "CanContentScroll" and v.strip().lower() == "false":
                out.append(XamlFinding(
                    "XAML107", n.line,
                    f"{n.type_name()} sets {k}=False; pixel-scrolling defeats "
                    "container virtualization [resource: virtualization]"))
    return out


def _template_score(tmpl: Node) -> tuple[int, dict[str, int]]:
    """Weighted complexity of a template subtree: element count + panel-nesting depth
    + trigger count + nested ItemsControl depth (design note's XAML109 factors)."""
    nodes = 0
    triggers = 0
    items_depth = 0

    def depth_of(node: Node, panel_depth: int, items: int) -> tuple[int, int]:
        nonlocal nodes, triggers, items_depth
        max_panel = panel_depth
        for c in node.children:
            if c.is_property_element():
                pmax, _ = depth_of(c, panel_depth, items)
                max_panel = max(max_panel, pmax)
                continue
            nodes += 1
            tn = c.type_name()
            if tn in TRIGGER_TYPES:
                triggers += 1
            pd = panel_depth + (1 if tn in NON_VIRTUALIZING_PANELS
                                or tn in VIRTUALIZING_PANELS or tn == "Grid" else 0)
            it = items + (1 if tn in ITEMS_CONTROLS else 0)
            items_depth = max(items_depth, it)
            cmax, _ = depth_of(c, pd, it)
            max_panel = max(max_panel, cmax)
        return max_panel, items

    max_panel, _ = depth_of(tmpl, 0, 0)
    factors = {"nodes": nodes, "panel_depth": max_panel,
               "triggers": triggers, "items_depth": items_depth}
    score = nodes + 2 * max_panel + 3 * triggers + 4 * items_depth
    return score, factors


def _rule_template_complexity(root: Node, avalonia: bool,
                              threshold: int = 40) -> list[XamlFinding]:
    """XAML109 — a template whose weighted complexity exceeds ``threshold``. Each
    realized item re-expands the whole subtree, so this is a per-item multiplier."""
    out: list[XamlFinding] = []
    for n in root.walk():
        if n.type_name() not in TEMPLATE_TYPES or n.is_property_element():
            continue
        score, f = _template_score(n)
        if score > threshold:
            out.append(XamlFinding(
                "XAML109", n.line,
                f"{n.type_name()} complexity {score} > {threshold} "
                f"(nodes={f['nodes']}, panel-depth={f['panel_depth']}, "
                f"triggers={f['triggers']}, items-depth={f['items_depth']}); "
                "every realized item re-expands this subtree "
                "[resource: visual tree]"))
    return out


def _rule_per_keystroke_binding(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML108 — TwoWay + UpdateSourceTrigger=PropertyChanged with no Delay on an
    editable property: the source is hit on every keystroke. ``Text`` defaults to
    ``LostFocus`` for a reason; ``Delay`` exists to throttle this."""
    out: list[XamlFinding] = []
    for n in root.walk():
        for k, v in n.attrib.items():
            if not _BINDING_RE.search(v) or not _PROPCHANGED_RE.search(v):
                continue
            prop = k.split(":", 1)[-1].rsplit(".", 1)[-1]
            # Text/Value are TwoWay-by-default; otherwise require an explicit TwoWay.
            two_way = _TWOWAY_RE.search(v) or prop in EDITABLE_PROPS
            if prop in EDITABLE_PROPS and two_way and not _DELAY_RE.search(v):
                out.append(XamlFinding(
                    "XAML108", n.line,
                    f"{n.type_name()}.{prop} binds TwoWay with "
                    "UpdateSourceTrigger=PropertyChanged and no Delay; the source "
                    "updates on every keystroke [resource: binding update]"))
    return out


def _resource_dictionaries(root: Node):
    """Yield every ResourceDictionary element (inline or the implicit *.Resources)."""
    for n in root.walk():
        if n.type_name() == "ResourceDictionary" and not n.is_property_element():
            yield n


def _rule_duplicate_merged_dict(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML104 — the same dictionary Source merged more than once in one
    MergedDictionaries block (wasted load + include-order ambiguity)."""
    out: list[XamlFinding] = []
    for n in root.walk():
        if n.local() != "MergedDictionaries" or not n.is_property_element():
            continue
        seen: dict[str, int] = {}
        for c in n.children:
            src = c.attr("Source")
            if not src:
                continue
            key = src.strip().lower().replace("\\", "/")
            if key in seen:
                out.append(XamlFinding(
                    "XAML104", c.line,
                    f"merged dictionary '{src}' is included again (first at line "
                    f"{seen[key]}); wasted load and include-order ambiguity "
                    "[resource: merged dictionary]"))
            else:
                seen[key] = c.line
    return out


def _keyed_resources(rd: Node):
    """Direct keyed children of a ResourceDictionary (its declared resources)."""
    for c in rd.children:
        if c.is_property_element():
            continue
        key = c.attr("Key")
        if key:
            yield key, c


def _rule_duplicate_converter(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML101 — an identical stateless converter declared in several dictionaries.
    Stateless = a keyed element with no child content and no configuring attributes
    beyond x:Key. Converters are normally one shared instance; duplication is churn.
    Started with exact type match (design note: structural equivalence is later)."""
    out: list[XamlFinding] = []
    first: dict[str, int] = {}
    for rd in _resource_dictionaries(root):
        for _key, c in _keyed_resources(rd):
            tn = c.type_name()
            if "Converter" not in tn:
                continue
            stateless = not c.children and all(
                a.split(":", 1)[-1] in ("Key",) for a in c.attrib)
            if not stateless:
                continue
            if tn in first:
                out.append(XamlFinding(
                    "XAML101", c.line,
                    f"stateless converter {tn} re-declared (first at line "
                    f"{first[tn]}); converters are normally a single shared instance "
                    "[resource: converter]"))
            else:
                first[tn] = c.line
    return out


def _rule_shared_false(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML103 (WPF-only) — x:Shared="False" outside the documented exceptions.
    Resources are shared by default; x:Shared=False is the deliberate per-lookup-
    instance opt-out, so it is worth a second look on converters/styles/brushes."""
    if avalonia:
        return []
    out: list[XamlFinding] = []
    for n in root.walk():
        shared = n.attr("Shared")
        if shared is not None and shared.strip().lower() == "false":
            tn = n.type_name()
            # The FrameworkElement/FrameworkContentElement template-insertion case is
            # the legitimate reason to opt out — don't flag those.
            if tn in ("FrameworkElement", "FrameworkContentElement"):
                continue
            out.append(XamlFinding(
                "XAML103", n.line,
                f"{tn} sets x:Shared=False; a fresh instance is built per lookup "
                "instead of sharing one [resource: x:Shared]"))
    return out


def _rule_freezable_freeze(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML106 (WPF-only) — a keyed Freezable with no bindings/dynamic-resource/
    animation and no PresentationOptions:Freeze="True". Freezing drops change-
    notification overhead and working set. The exception list is load-bearing: a
    Freezable that is animated, data-bound, or references a DynamicResource *cannot*
    be frozen, so those must be skipped."""
    if avalonia:
        return []
    out: list[XamlFinding] = []
    for rd in _resource_dictionaries(root):
        for _key, c in _keyed_resources(rd):
            if c.type_name() not in FREEZABLE_TYPES:
                continue
            # Already frozen?
            if any(a.split(":", 1)[-1] == "Freeze" and v.strip().lower() == "true"
                   for a, v in c.attrib.items()):
                continue
            # Un-freezable: any descendant binding/dynamic-resource/x:Reference, or an
            # animation/trigger child.
            blob = json.dumps([ch.tag for ch in c.walk()]) + json.dumps(
                [v for nn in c.walk() for v in nn.attrib.values()])
            if _DYNAMIC_REF_RE.search(blob):
                continue
            if any(ch.local().endswith("Animation") or ch.local() == "Storyboard"
                   for ch in c.walk()):
                continue
            out.append(XamlFinding(
                "XAML106", c.line,
                f"{c.type_name()} resource is not frozen; add "
                "PresentationOptions:Freeze=\"True\" to drop change-notification "
                "overhead [resource: freezable]"))
    return out


def _rule_dynamic_resource_static(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML102 (WPF-only) — DynamicResource for a key that is defined locally and is
    not a theme/system key. StaticResource is recommended unless the value is
    runtime-mutated; DynamicResource carries a deferred-lookup cost per use."""
    if avalonia:
        return []
    # Collect locally-declared resource keys (lexically stable, app-local).
    local_keys: set[str] = set()
    for rd in _resource_dictionaries(root):
        for key, _c in _keyed_resources(rd):
            local_keys.add(key)
    out: list[XamlFinding] = []
    pat = re.compile(r"\{\s*DynamicResource\s+([^}]+)\}", re.IGNORECASE)
    for n in root.walk():
        for _k, v in n.attrib.items():
            m = pat.search(v)
            if not m:
                continue
            key = m.group(1).strip()
            if key.startswith(DYNAMIC_KEY_PREFIXES) or any(
                    key.startswith(t) for t in DYNAMIC_KEY_TYPES):
                continue
            if key in local_keys:
                out.append(XamlFinding(
                    "XAML102", n.line,
                    f"DynamicResource '{key}' resolves a lexically-stable, app-local "
                    "resource; StaticResource avoids the deferred-lookup cost "
                    "[resource: dynamic resource]"))
    return out


def _rule_image_decode(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML110 (WPF-only) — a thumbnail-sized Image whose Source is a plain URI
    string: WPF decodes the bitmap at full native size, then scales down every
    layout. A BitmapImage with DecodePixelWidth/Height decodes straight to the
    display size (less working set, less GPU upload). The decode hint cannot be set
    on a string Source, so the fix is the explicit BitmapImage form."""
    if avalonia:
        return []
    out: list[XamlFinding] = []
    for n in root.walk():
        if n.type_name() != "Image" or n.is_property_element():
            continue
        src = n.attr("Source")
        if not src or src.strip().startswith("{"):  # binding / markup ext: can't tell
            continue
        dims = []
        for d in ("Width", "Height"):
            v = n.attr(d)
            if v is None:
                continue
            try:
                dims.append(float(v.strip()))
            except ValueError:
                continue  # Auto / *
        if dims and min(dims) <= THUMBNAIL_MAX_DIP:
            out.append(XamlFinding(
                "XAML110", n.line,
                f"Image is shown at <={int(min(dims))}px but Source '{src}' is a "
                "plain URI; WPF decodes it at full size. Use a BitmapImage with "
                "DecodePixelWidth to decode-to-size [resource: image decode]"))
    return out


def _in_control_template(node: Node) -> bool:
    """True if ``node`` is nested inside a ControlTemplate (where TemplatedParent —
    and therefore TemplateBinding — is meaningful)."""
    p = node.parent
    while p is not None:
        if p.type_name() == "ControlTemplate" and not p.is_property_element():
            return True
        p = p.parent
    return False


def _rule_template_binding_opportunity(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML112 — inside a ControlTemplate, a {Binding RelativeSource=TemplatedParent}
    that carries no Converter and is not TwoWay could be the cheaper {TemplateBinding}
    (compiled, no full Binding object). A candidate, not a guarantee: TemplateBinding
    cannot do converters / two-way, which is exactly why those are excluded here."""
    out: list[XamlFinding] = []
    for n in root.walk():
        if not _in_control_template(n):
            continue
        for k, v in n.attrib.items():
            if (_BINDING_RE.search(v) and _TPARENT_RE.search(v)
                    and not _CONVERTER_RE.search(v) and not _TWOWAY_RE.search(v)):
                prop = k.split(":", 1)[-1].rsplit(".", 1)[-1]
                out.append(XamlFinding(
                    "XAML112", n.line,
                    f"{n.type_name()}.{prop} binds to TemplatedParent with no "
                    "converter/two-way; {TemplateBinding} is the cheaper compiled "
                    "form here [resource: template binding]"))
    return out


def _inline_freezable_sig(node: Node) -> tuple[Any, ...]:
    """Structural signature of an inline Freezable: type + non-key attributes + child
    element types. Two inline values with the same signature are the same object
    re-built per use, so they should be hoisted to one shared keyed resource."""
    attrs = tuple(sorted((k.split(":", 1)[-1], v) for k, v in node.attrib.items()
                         if k.split(":", 1)[-1] != "Key"))
    kids = tuple(c.type_name() for c in node.children if not c.is_property_element())
    return (node.type_name(), attrs, kids)


def _rule_inline_freezable_duplication(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML113 — the same inline Freezable (brush/geometry/transform set directly as a
    property value, not as a keyed resource) declared identically more than once.
    Each occurrence is a separate object; hoisting to one keyed resource shares it.
    Extends XAML100's hoisting story to the inline case (framework-agnostic)."""
    out: list[XamlFinding] = []
    first: dict[tuple[Any, ...], int] = {}
    for n in root.walk():
        if n.type_name() not in FREEZABLE_TYPES or n.is_property_element():
            continue
        if n.attr("Key") is not None:
            continue  # already a shared keyed resource
        if not (n.parent and n.parent.is_property_element()):
            continue  # only inline property values, not free-standing
        sig = _inline_freezable_sig(n)
        if not sig[1] and not sig[2]:
            continue  # empty/defaulted element — nothing to share
        if sig in first:
            out.append(XamlFinding(
                "XAML113", n.line,
                f"inline {n.type_name()} duplicates an identical one (first at line "
                f"{first[sig]}); hoist it to a shared keyed resource instead of "
                "rebuilding it per use [resource: inline freezable]"))
        else:
            first[sig] = n.line
    return out


def _rule_layout_transform(root: Node, avalonia: bool) -> list[XamlFinding]:
    """XAML111 (WPF-only) — a LayoutTransform where a RenderTransform would do.
    LayoutTransform re-runs measure/arrange on every change; RenderTransform is a
    cheap render-time matrix. Legitimate only when layout must react to the transform
    (e.g. rotated text that reflows), so this is a candidate to review."""
    if avalonia:
        return []
    out: list[XamlFinding] = []
    seen: set[int] = set()
    for n in root.walk():
        # Property-element form: <X.LayoutTransform><RotateTransform .../></X.LayoutTransform>
        if n.local() == "LayoutTransform" and n.is_property_element():
            if n.line not in seen:
                seen.add(n.line)
                out.append(XamlFinding(
                    "XAML111", n.line,
                    f"{n.type_name()} uses LayoutTransform, which forces a "
                    "measure/arrange pass on change; prefer RenderTransform unless "
                    "layout must react [resource: layout transform]"))
            continue
        # Attribute form (rare): LayoutTransform="..."
        for k in n.attrib:
            if k.split(":", 1)[-1].rsplit(".", 1)[-1] == "LayoutTransform":
                if n.line not in seen:
                    seen.add(n.line)
                    out.append(XamlFinding(
                        "XAML111", n.line,
                        f"{n.type_name()} sets LayoutTransform, which forces a "
                        "measure/arrange pass on change; prefer RenderTransform "
                        "unless layout must react [resource: layout transform]"))
    return out


RULES: list[Callable[[Node, bool], list[XamlFinding]]] = [
    _rule_virtualization,
    _rule_template_complexity,
    _rule_per_keystroke_binding,
    _rule_duplicate_merged_dict,
    _rule_duplicate_converter,
    _rule_shared_false,
    _rule_freezable_freeze,
    _rule_dynamic_resource_static,
    _rule_image_decode,
    _rule_template_binding_opportunity,
    _rule_inline_freezable_duplication,
    _rule_layout_transform,
]


def analyze_text(text: str) -> list[XamlFinding]:
    """All Phase-1 rules over one markup string. Malformed markup -> no findings."""
    root = parse_xaml(text)
    if root is None:
        return []
    avalonia = _is_avalonia(root)
    out: list[XamlFinding] = []
    for rule in RULES:
        out.extend(rule(root, avalonia))
    return out


def _to_sarif(results: list[tuple[str, XamlFinding]]) -> dict[str, Any]:
    """Canonical SARIF 2.1.0 — the same shape own-check / CodeQL emit, so the
    existing parse_sarif reads it with no special-casing. A file-level finding
    (line <= 0) omits the region so report/sarif.py keeps it file-level."""
    sarif_results: list[dict[str, Any]] = []
    for path, f in results:
        phys: dict[str, Any] = {"artifactLocation": {"uri": path}}
        if f.line >= 1:
            phys["region"] = {"startLine": f.line}
        sarif_results.append({
            "ruleId": f.rule, "level": "warning",
            "message": {"text": f.message},
            "locations": [{"physicalLocation": phys}],
        })
    return {"version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "xaml-check",
                                          "informationUri": "https://github.com/physshell/own.net",
                                          "rules": []}},
                      "results": sarif_results}]}


def run_xaml_check(target: str, out_dir: Path) -> dict[str, Any]:
    """Scan every ``.xaml`` / ``.axaml`` under ``target`` and write SARIF to
    ``out_dir/xaml-check.sarif``. Always best-effort: a missing target or zero
    markup files yields ``available=False`` with a reason, never a crash."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sarif_path = out_dir / "xaml-check.sarif"
    status: dict[str, Any] = {"tool": "xaml", "tier": "build-free",
                              "available": False, "sarif": None, "reason": ""}

    root = Path(target)
    if not root.exists():
        status["reason"] = f"target path does not exist: {target}"
        return status
    files = sorted(p for p in root.rglob("*")
                   if p.suffix.lower() in (".xaml", ".axaml") and p.is_file())
    if not files:
        status["reason"] = "no .xaml/.axaml files under target"
        return status

    results: list[tuple[str, XamlFinding]] = []
    scanned = 0
    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        rel = fp.relative_to(root).as_posix()
        for f in analyze_text(text):
            results.append((rel, f))

    sarif_path.write_text(json.dumps(_to_sarif(results), indent=2), encoding="utf-8")
    status.update(available=True, sarif=str(sarif_path),
                  findings=len(results), files_scanned=scanned)
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the build-free XAML analyzer -> SARIF.")
    ap.add_argument("--target", help="path to the target source tree")
    ap.add_argument("--out", default="artifacts/own-audit", help="SARIF output directory")
    ap.add_argument("--selftest", action="store_true", help="run built-in checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.target:
        ap.error("--target is required (or use --selftest)")

    status = run_xaml_check(args.target, Path(args.out))
    print(json.dumps(status, indent=2))
    return 0 if status["available"] else 1


# --------------------------------------------------------------------------- #
# Selftest — embedded markup fixtures exercising every rule + the hard          #
# line-preservation requirement, so it gates on Linux CI like the other         #
# build-free runners (no .NET, no files on disk needed).                        #
# --------------------------------------------------------------------------- #

_WPF_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
           'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
           'xmlns:PresentationOptions="http://schemas.microsoft.com/winfx/2006/xaml/presentation/options"')


def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    def rules(text: str) -> dict[str, XamlFinding]:
        return {f.rule: f for f in analyze_text(text)}

    # Line preservation — the hard requirement. The flagged control sits on line 3,
    # and the finding MUST carry line 3, not 1.
    virt = (f'<UserControl {_WPF_NS}>\n'
            '  <Grid>\n'
            '    <ListBox VirtualizingStackPanel.IsVirtualizing="False" />\n'
            '  </Grid>\n'
            '</UserControl>\n')
    r = rules(virt)
    check("XAML107" in r, "XAML107 must flag IsVirtualizing=False")
    check(r.get("XAML107") and r["XAML107"].line == 3,
          f"XAML107 line must be preserved (expected 3, got "
          f"{r['XAML107'].line if 'XAML107' in r else None})")

    # XAML107 via a non-virtualizing ItemsPanel.
    panel = (f'<UserControl {_WPF_NS}>\n'
             '  <ListView>\n'
             '    <ListView.ItemsPanel>\n'
             '      <ItemsPanelTemplate>\n'
             '        <StackPanel />\n'
             '      </ItemsPanelTemplate>\n'
             '    </ListView.ItemsPanel>\n'
             '  </ListView>\n'
             '</UserControl>\n')
    check("XAML107" in rules(panel), "XAML107 must flag a non-virtualizing ItemsPanel")
    # A VirtualizingStackPanel ItemsPanel must NOT be flagged.
    ok_panel = panel.replace("StackPanel", "VirtualizingStackPanel")
    check("XAML107" not in rules(ok_panel),
          "XAML107 false positive: VirtualizingStackPanel ItemsPanel is fine")

    # XAML108 — per-keystroke binding; the bound property must be editable.
    keystroke = (f'<UserControl {_WPF_NS}>\n'
                 '  <TextBox Text="{Binding Name, Mode=TwoWay, '
                 'UpdateSourceTrigger=PropertyChanged}" />\n'
                 '</UserControl>\n')
    check("XAML108" in rules(keystroke), "XAML108 must flag un-delayed PropertyChanged TwoWay")
    delayed = keystroke.replace("UpdateSourceTrigger=PropertyChanged",
                                "UpdateSourceTrigger=PropertyChanged, Delay=300")
    check("XAML108" not in rules(delayed), "XAML108 false positive: Delay present")
    non_editable = (f'<UserControl {_WPF_NS}>\n'
                    '  <CheckBox IsChecked="{Binding On, Mode=TwoWay, '
                    'UpdateSourceTrigger=PropertyChanged}" />\n'
                    '</UserControl>\n')
    check("XAML108" not in rules(non_editable),
          "XAML108 false positive: IsChecked is not a per-keystroke editable property")

    # XAML104 — duplicate merged dictionary include.
    dup = (f'<ResourceDictionary {_WPF_NS}>\n'
           '  <ResourceDictionary.MergedDictionaries>\n'
           '    <ResourceDictionary Source="Themes/Colors.xaml" />\n'
           '    <ResourceDictionary Source="Themes/Brushes.xaml" />\n'
           '    <ResourceDictionary Source="Themes/Colors.xaml" />\n'
           '  </ResourceDictionary.MergedDictionaries>\n'
           '</ResourceDictionary>\n')
    r = rules(dup)
    check("XAML104" in r, "XAML104 must flag a re-included dictionary")
    check(r.get("XAML104") and r["XAML104"].line == 5,
          "XAML104 must point at the duplicate include (line 5)")

    # XAML101 — duplicate stateless converter across dictionaries.
    conv = (f'<ResourceDictionary {_WPF_NS} xmlns:c="clr-namespace:App.Converters">\n'
            '  <c:BoolToVisibilityConverter x:Key="b2v" />\n'
            '  <c:BoolToVisibilityConverter x:Key="b2v2" />\n'
            '</ResourceDictionary>\n')
    check("XAML101" in rules(conv), "XAML101 must flag a re-declared stateless converter")

    # XAML103 — x:Shared=False (WPF only).
    shared = (f'<ResourceDictionary {_WPF_NS}>\n'
              '  <SolidColorBrush x:Key="b" x:Shared="False" Color="Red" />\n'
              '</ResourceDictionary>\n')
    check("XAML103" in rules(shared), "XAML103 must flag x:Shared=False")

    # XAML106 — unfrozen Freezable, with the exception list honoured.
    freez = (f'<ResourceDictionary {_WPF_NS}>\n'
             '  <SolidColorBrush x:Key="b" Color="#FF112233" />\n'
             '</ResourceDictionary>\n')
    check("XAML106" in rules(freez), "XAML106 must flag an unfrozen brush")
    frozen = freez.replace('Color="#FF112233"',
                           'Color="#FF112233" PresentationOptions:Freeze="True"')
    check("XAML106" not in rules(frozen), "XAML106 false positive: already frozen")
    bound = (f'<ResourceDictionary {_WPF_NS}>\n'
             '  <SolidColorBrush x:Key="b" Color="{DynamicResource AccentColor}" />\n'
             '</ResourceDictionary>\n')
    check("XAML106" not in rules(bound),
          "XAML106 false positive: a DynamicResource-referencing brush cannot be frozen")

    # XAML102 — DynamicResource for a locally-defined, non-theme key.
    dynr = (f'<ResourceDictionary {_WPF_NS}>\n'
            '  <SolidColorBrush x:Key="PanelBrush" Color="Gray" />\n'
            '  <Style x:Key="s" TargetType="Border">\n'
            '    <Setter Property="Background" Value="{DynamicResource PanelBrush}" />\n'
            '  </Style>\n'
            '</ResourceDictionary>\n')
    check("XAML102" in rules(dynr), "XAML102 must flag DynamicResource on a local static key")
    sysr = dynr.replace("PanelBrush", "SystemColors.WindowBrushKey")
    check("XAML102" not in rules(sysr),
          "XAML102 false positive: system/theme keys are legitimately dynamic")

    # XAML109 — a heavy template trips the complexity threshold; a small one does not.
    cells = "".join(f'<TextBlock Text="c{i}" />' for i in range(45))
    heavy = (f'<ResourceDictionary {_WPF_NS}>\n'
             f'  <DataTemplate x:Key="t"><StackPanel>{cells}</StackPanel></DataTemplate>\n'
             '</ResourceDictionary>\n')
    check("XAML109" in rules(heavy), "XAML109 must flag an over-threshold template")
    light = (f'<ResourceDictionary {_WPF_NS}>\n'
             '  <DataTemplate x:Key="t"><TextBlock Text="hi" /></DataTemplate>\n'
             '</ResourceDictionary>\n')
    check("XAML109" not in rules(light), "XAML109 false positive: a tiny template is fine")

    # XAML110 — a thumbnail Image with a full-size string Source; big image is fine.
    img = (f'<UserControl {_WPF_NS}>\n'
           '  <Image Source="Assets/logo.png" Width="32" Height="32" />\n'
           '</UserControl>\n')
    check("XAML110" in rules(img), "XAML110 must flag a thumbnail with a full-size source")
    big = img.replace('Width="32" Height="32"', 'Width="512" Height="512"')
    check("XAML110" not in rules(big), "XAML110 false positive: a full-size image is fine")
    bound_src = img.replace('Source="Assets/logo.png"', 'Source="{Binding Icon}"')
    check("XAML110" not in rules(bound_src),
          "XAML110 false positive: a bound source size is unknowable from markup")

    # XAML112 — a TemplatedParent binding inside a ControlTemplate; converters exempt.
    tb = (f'<ResourceDictionary {_WPF_NS}>\n'
          '  <ControlTemplate x:Key="t" TargetType="Button">\n'
          '    <Border Background="{Binding Background, '
          'RelativeSource={RelativeSource TemplatedParent}}" />\n'
          '  </ControlTemplate>\n'
          '</ResourceDictionary>\n')
    check("XAML112" in rules(tb), "XAML112 must flag a TemplatedParent binding")
    tb_conv = tb.replace("RelativeSource={RelativeSource TemplatedParent}}",
                         "RelativeSource={RelativeSource TemplatedParent}, "
                         "Converter={StaticResource c}}")
    check("XAML112" not in rules(tb_conv),
          "XAML112 false positive: a converter binding cannot become a TemplateBinding")
    tb_outside = tb.replace("<ControlTemplate x:Key=\"t\" TargetType=\"Button\">",
                            "<DataTemplate x:Key=\"t\">").replace(
                            "</ControlTemplate>", "</DataTemplate>")
    check("XAML112" not in rules(tb_outside),
          "XAML112 false positive: TemplatedParent is only meaningful in a ControlTemplate")

    # XAML113 — the same inline brush declared twice; a unique one is fine.
    inline = (f'<StackPanel {_WPF_NS}>\n'
              '  <Border><Border.Background><SolidColorBrush Color="#FF0080FF" />'
              '</Border.Background></Border>\n'
              '  <Border><Border.Background><SolidColorBrush Color="#FF0080FF" />'
              '</Border.Background></Border>\n'
              '</StackPanel>\n')
    r = rules(inline)
    check("XAML113" in r, "XAML113 must flag a duplicated inline brush")
    uniq = (f'<StackPanel {_WPF_NS}>\n'
            '  <Border><Border.Background><SolidColorBrush Color="#FF0080FF" />'
            '</Border.Background></Border>\n'
            '  <Border><Border.Background><SolidColorBrush Color="#FF00FF80" />'
            '</Border.Background></Border>\n'
            '</StackPanel>\n')
    check("XAML113" not in rules(uniq), "XAML113 false positive: distinct inline brushes are fine")

    # XAML111 — LayoutTransform (property-element form); WPF-only.
    lt = (f'<StackPanel {_WPF_NS}>\n'
          '  <TextBlock Text="hi"><TextBlock.LayoutTransform>'
          '<RotateTransform Angle="90" /></TextBlock.LayoutTransform></TextBlock>\n'
          '</StackPanel>\n')
    check("XAML111" in rules(lt), "XAML111 must flag a LayoutTransform")

    # WPF-only rules must stay silent on Avalonia .axaml.
    ava = ('<ResourceDictionary xmlns="https://github.com/avaloniaui" '
           'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n'
           '  <SolidColorBrush x:Key="b" Color="Red" />\n'
           '  <Image Source="logo.png" Width="16" Height="16" />\n'
           '</ResourceDictionary>\n')
    ar = rules(ava)
    check(not ({"XAML106", "XAML103", "XAML102", "XAML110", "XAML111"} & set(ar)),
          "WPF-only rules (102/103/106/110/111) must not fire on Avalonia markup")

    # Malformed markup must be skipped, never crash.
    check(analyze_text("<Not><Closed>") == [], "malformed markup must yield no findings")

    # End-to-end SARIF: the emitted log must be readable by the shared parse_sarif,
    # with the real line surviving the round-trip (the contract with the pipeline).
    sarif = _to_sarif([
        ("Views/Main.xaml", XamlFinding("XAML107", 3, "x [resource: virtualization]")),
        ("Views/Main.xaml", XamlFinding("XAML104", 0, "file-level x"))])
    here = Path(__file__).resolve()
    sys.path.insert(0, str(here.parents[3] / "scripts"))
    try:
        from oracle_compare import parse_sarif
        parsed = parse_sarif(json.dumps(sarif), "xaml", [])
        by_rule = {f.rule: f for f in parsed}
        check(by_rule.get("XAML107") and by_rule["XAML107"].line == 3,
              "SARIF round-trip must preserve the element line (3)")
        check(by_rule.get("XAML104") and by_rule["XAML104"].line == 0,
              "a file-level finding must round-trip as line 0 (region omitted)")
    except ImportError:
        check(False, "could not import scripts/oracle_compare.parse_sarif for round-trip")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"XAML_CHECK SELFTEST FAIL: {f}")
    print(f"xaml_check selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
