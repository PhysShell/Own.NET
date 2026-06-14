#!/usr/bin/env python3
"""
The "what it catches" gallery, as an executable, self-checking demo.

Each file in examples/gallery/ is a tiny, real-shaped program that trips exactly
one ownership/borrow diagnostic, with a comment giving the real C# analog. This
module pins every example to the code it is supposed to produce, so the demo can
never quietly drift from what the checker actually does.

Run:  python tests/test_gallery.py     (prints the gallery table)
      python tests/run_tests.py        (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import analyze
from ownlang.buffers import validate_policies
from ownlang.cfg import build_cfg, collect_policies, collect_signatures
from ownlang.diagnostics import TITLES, Severity
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

_GALLERY = os.path.join(os.path.dirname(__file__), "..", "examples", "gallery")

# file -> the diagnostic it is meant to demonstrate (None == must check clean),
# plus a one-line real-world analog for the printed table.
MANIFEST = [
    ("00_ok_clean.own",              None,     "clean: rent -> view -> return, exception-safe"),
    ("01_leak_on_error_path.own",    "OWN001", "forgot Dispose() on the early-out path"),
    ("02_use_after_release.own",     "OWN002", "touched a stream after Dispose()"),
    ("03_double_release.own",        "OWN003", "Dispose() called twice"),
    ("04_use_after_move.own",        "OWN005", "used a value after moving ownership away"),
    ("05_dispose_while_view_live.own","OWN008","ArrayPool.Return while a Span over it is live"),
    ("06_exclusive_while_shared.own","OWN006", "wrote through a Span aliased by a ReadOnlySpan"),
    ("07_use_after_handoff.own",     "OWN002", "used a buffer after a callee took ownership"),
    ("08_stack_buffer_escapes.own",  "OWN015", "returned a Span over a stackalloc (dangling)"),
    ("09_untracked_call.own",        "OWN040", "ownership laundered through an opaque call"),
]


def _codes(src: str) -> list[str]:
    """The error codes the checker produces for one `.own` source string."""
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["OWN020"]
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    out = [d.code for d in validate_policies(collect_policies(mod))
           if d.severity == Severity.ERROR]
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        out += [d.code for d in (d1 + d2) if d.severity == Severity.ERROR]
    return out


def _render_smoke() -> list[str]:
    """The pretty CLI rendering must carry a line:col header, the source line,
    and a caret on the named identifier."""
    fails: list[str] = []
    with open(os.path.join(_GALLERY, "02_use_after_release.own"),
              encoding="utf-8") as f:
        src = f.read()
    mod = parse(src)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    diags = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        diags += d1 + analyze(cfg)
    pretty = "\n".join(d.render_pretty("f.own", src) for d in diags)
    if ":9:" not in pretty:
        fails.append("render_pretty: missing line:col header")
    if "\n" not in pretty or "^" not in pretty:
        fails.append("render_pretty: missing source line / caret")
    return fails


def run() -> int:
    """Check every gallery example against its documented code; return 0/1."""
    fails: list[str] = _render_smoke()
    rows: list[tuple[str, str, str]] = []
    matched = 0
    for name, want, analog in MANIFEST:
        path = os.path.join(_GALLERY, name)
        try:
            with open(path, encoding="utf-8") as f:
                got = sorted(set(_codes(f.read())))
        except FileNotFoundError:
            fails.append(f"{name}: missing")
            continue
        if want is None:
            ok = not got
            if not ok:
                fails.append(f"{name}: expected clean, got {got}")
            shown = "clean"
        else:
            ok = got == [want]
            if not ok:
                fails.append(f"{name}: expected [{want}], got {got}")
            shown = want
        if ok:
            matched += 1
        rows.append((name, shown, analog))

    width = max((len(n) for n, _, _ in rows), default=0)
    print("what it catches — gallery (examples/gallery/):")
    for name, code, analog in rows:
        title = TITLES.get(code, "")
        print(f"  {name:<{width}}  {code:<7}  {analog}")
        if code != "clean":
            print(f"  {'':<{width}}  {'':<7}  ({title})")
    for f in fails:
        print(f"GALLERY FAIL: {f}")
    print(f"gallery: {matched}/{len(MANIFEST)} "
          f"examples match their documented diagnostic")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
