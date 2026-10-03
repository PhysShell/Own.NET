#!/usr/bin/env python3
"""H0 heap-effect summaries — the parity fixtures and the kill-fixture semantics.

`tests/fixtures/heap_effects/` holds heap-effect SOURCE FACTS (`<case>.sidecar.json`)
and what the reference makes of them:

* `<case>.summaries.json` — the EXACT bytes `python -m ownlang.heap_effects` prints
  (`json.dumps(indent=2, sort_keys=True)` + newline);
* `<case>.rejected.txt` — the exact message of a sidecar the reader refuses.

`samples.sidecar.json` is what the real extractor writes for
`frontend/roslyn/heap-effects-samples/HeapEffects.cs` (scripts/heap_effects_gate.py
re-extracts it and requires it back); every other case is synthetic, aimed at a
solver corner C# does not reach directly.

Python is authoritative: `--write` regenerates the goldens. The Rust port holds up
its half in `rust/crates/own-bridge/tests/heap_effects.rs` — every golden, byte for
byte, every rejection text, with zero Python.

Beyond the bytes this pins the MEANING of the kill fixtures (a golden alone would
happily freeze a wrong answer), the order-independence of the solve, and that H0 is
inert except through one door: only the OwnIR v2 `proven_call` admission (ownir.py)
reads the summary domain, and only through the names it needs.

Run:  python tests/test_heap_effects_fixtures.py            (verify)
      python tests/test_heap_effects_fixtures.py --write    (regenerate)
"""

from __future__ import annotations

import ast
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.heap_effects import HEAP_EFFECTS_VERSION, HeapEffectsError, render

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
FIXDIR = os.path.join(ROOT, "tests", "fixtures", "heap_effects")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
NS = "Own.HeapEffects.Samples."


def _read(name: str) -> str:
    with open(os.path.join(FIXDIR, name), encoding="utf-8") as f:
        return f.read()


def _manifest() -> tuple[list[str], list[str], list[str]]:
    data = json.loads(_read("manifest.json"))
    problems = []
    if data.get("heap_effects_version") != HEAP_EFFECTS_VERSION:
        problems.append("manifest heap_effects_version does not match the reader")
    return ([c["name"] for c in data["cases"]], [r["name"] for r in data["rejections"]],
            problems)


def _reversed(text: str) -> str | None:
    """The same sidecar with its methods in reverse order (None if it is not one)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("methods"), list):
        return None
    doc = dict(doc, methods=list(reversed(doc["methods"])))
    return json.dumps(doc)


def _ledger(cases: list[str], rejections: list[str]) -> list[str]:
    fails: list[str] = []
    on_disk = sorted(n[: -len(".sidecar.json")] for n in os.listdir(FIXDIR)
                     if n.endswith(".sidecar.json"))
    planned = sorted(cases + rejections)
    if len(set(planned)) != len(planned):
        fails.append("manifest names a case twice")
    if on_disk != planned:
        fails.append(f"sidecars on disk {on_disk} != manifest {planned}")
    goldens = sorted(n[: -len(".summaries.json")] for n in os.listdir(FIXDIR)
                     if n.endswith(".summaries.json"))
    if goldens != sorted(cases):
        fails.append(f"summaries goldens {goldens} != cases {sorted(cases)}")
    texts = sorted(n[: -len(".rejected.txt")] for n in os.listdir(FIXDIR)
                   if n.endswith(".rejected.txt"))
    if texts != sorted(rejections):
        fails.append(f"rejection texts {texts} != rejections {sorted(rejections)}")
    return fails


def _replay(cases: list[str], rejections: list[str], write: bool) -> list[str]:
    fails: list[str] = []
    for case in cases:
        text = _read(f"{case}.sidecar.json")
        out = render(text)
        golden = os.path.join(FIXDIR, f"{case}.summaries.json")
        if write:
            with open(golden, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
        elif _read(f"{case}.summaries.json") != out:
            fails.append(f"{case}: the dump is not the golden")
        flipped = _reversed(text)
        if flipped is not None and render(flipped) != out:
            fails.append(f"{case}: the dump depends on the order of methods[]")
    for case in rejections:
        text = _read(f"{case}.sidecar.json")
        try:
            render(text)
        except HeapEffectsError as e:
            message = str(e)
        else:
            fails.append(f"{case}: accepted, but it is a rejection case")
            continue
        path = os.path.join(FIXDIR, f"{case}.rejected.txt")
        if write:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(message + "\n")
        elif _read(f"{case}.rejected.txt") != message + "\n":
            fails.append(f"{case}: rejected with {message!r}, not the pinned text")
    return fails


def _summary(doc: dict[str, object], method: str) -> dict[str, object]:
    for s in doc["summaries"]:  # type: ignore[attr-defined]
        if s["method"] == NS + method:
            return s  # type: ignore[no-any-return]
    raise KeyError(method)


def _shape(s: dict[str, object]) -> tuple[object, ...]:
    return ([p["effect"] for p in s["params"]], s["receiver"],  # type: ignore[attr-defined]
            s["writes"], s["returns"])


NONE_W = {"instance": "none", "static": "none", "indirect": "none"}
STATIC_W = dict(NONE_W, static="may")
ALL_UNKNOWN = {"instance": "unknown", "static": "unknown", "indirect": "unknown"}
ORDER = "Own.HeapEffects.Samples.Order"

# The meaning the slice exists for: (params, receiver, writes, returns).
EXPECT: dict[str, tuple[object, ...]] = {
    # the five kill fixtures
    "Kill.Twice(int)": (["plain"], None, NONE_W, []),
    f"Kill.Mutates({ORDER})": (["borrow_mut"], None, NONE_W, []),
    f"Kill.Escapes({ORDER})": (["may_escape"], None, STATIC_W, []),
    "Kill.TouchesGlobalState()": ([], None, STATIC_W, []),
    "Kill.Logs()": ([], None, ALL_UNKNOWN, []),
    # transitive: only B's summary says what A does
    f"Transitive.A({ORDER})": (["borrow_mut"], None, NONE_W, []),
    f"Transitive.EscapeOuter({ORDER})": (["may_escape"], None, STATIC_W, []),
    "Transitive.CallsLogs()": ([], None, ALL_UNKNOWN, []),
    f"Transitive.CallsTouch({ORDER})": (["borrow_mut"], None, NONE_W, []),
    f"Transitive.CallsPeek({ORDER})": (["borrow"], None, NONE_W, []),
    f"Transitive.AliasMutates({ORDER})": (["borrow_mut"], None, NONE_W, []),
    f"Transitive.Reassigned({ORDER})": (["borrow_mut"], None, dict(NONE_W, instance="may"), []),
    f"Transitive.SetFirst({ORDER}[], {ORDER})": (["borrow_mut", "may_escape"], None, NONE_W, []),
    f"Transitive.ReadsDeep({ORDER})": (["borrow"], None, NONE_W, []),
    # SCCs
    "Recursive.Even(int)": (["plain"], None, NONE_W, []),
    "Recursive.Odd(int)": (["plain"], None, NONE_W, []),
    f"Recursive.Ping({ORDER}, int)": (["borrow_mut", "plain"], None, NONE_W, []),
    f"Recursive.Pong({ORDER}, int)": (["borrow_mut", "plain"], None, NONE_W, []),
    f"Recursive.Tick({ORDER}, int)": (["unknown", "plain"], None, ALL_UNKNOWN, []),
    f"Recursive.Tock({ORDER}, int)": (["unknown", "plain"], None, ALL_UNKNOWN, []),
    # return aliases
    f"Returns.Id({ORDER})": (["plain"], None, NONE_W, ["param:0"]),
    f"Returns.ViaCall({ORDER})": (["plain"], None, NONE_W, ["param:0"]),
    "Returns.FromHeap()": ([], None, NONE_W, ["heap"]),
    f"Returns.MutatesResult({ORDER})": (["borrow_mut"], None, NONE_W, []),
    # opaque
    "Opaque.Virtual(Own.HeapEffects.Samples.IShape)": (["unknown"], None, ALL_UNKNOWN, []),
    f"Opaque.Lambda({ORDER})": (["unknown"], None, ALL_UNKNOWN, ["unknown"]),
    "Opaque.CallsLazy()": ([], None, ALL_UNKNOWN, []),
    "Order.Touch()": ([], "borrow_mut", NONE_W, []),
    "Order.Peek()": ([], "borrow", NONE_W, []),
    # a captured primary-constructor parameter is hidden state: Unknown
    "Holder.Touch()": ([], "unknown", ALL_UNKNOWN, []),
}


def _semantics() -> list[str]:
    fails: list[str] = []
    doc = json.loads(render(_read("samples.sidecar.json")))
    for method, want in EXPECT.items():
        try:
            got = _shape(_summary(doc, method))
        except KeyError:
            fails.append(f"samples: no summary for {method}")
            continue
        if got != want:
            fails.append(f"samples: {method} is {got}, expected {want}")
    logs = _summary(doc, "Kill.Logs()")
    if not any("System.Console.WriteLine" in r for r in logs["unresolved"]):  # type: ignore[attr-defined]
        fails.append("samples: Kill.Logs() does not name Console.WriteLine as unresolved")
    return fails


# H1 (OwnIR v2 `proven_call`) is the ONE consumer allowed to read the summary domain,
# and only through these names: the admission in ownir.py. Any other checker module
# reaching into it would be a second, unreviewed way for summaries to move a verdict.
_CONSUMER = "ownir.py"
_CONSUMED = {"HeapEffectsError", "load", "site_verdict", "solve"}


def _inert() -> list[str]:
    """The summary domain moves a verdict through exactly one door: ownir.py's
    `proven_call` admission, importing exactly `_CONSUMED`. Nothing else imports it."""
    fails: list[str] = []
    pkg = os.path.join(ROOT, "ownlang")
    seen: set[str] = set()
    for name in sorted(os.listdir(pkg)):
        if not name.endswith(".py") or name == "heap_effects.py":
            continue
        with open(os.path.join(pkg, name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                    a.name.endswith("heap_effects") for a in node.names):
                fails.append(f"ownlang/{name} imports heap_effects as a module")
            elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "heap_effects"):
                names = {a.name for a in node.names}
                if name != _CONSUMER:
                    fails.append(f"ownlang/{name} imports heap_effects: only the "
                                 f"proven_call admission ({_CONSUMER}) may")
                elif not names <= _CONSUMED:
                    fails.append(f"ownlang/{name} imports {sorted(names - _CONSUMED)} from "
                                 f"heap_effects: the admission reads only {sorted(_CONSUMED)}")
                seen |= names
            elif isinstance(node, ast.ImportFrom) and node.module is None and any(
                    a.name == "heap_effects" for a in node.names):
                fails.append(f"ownlang/{name} imports heap_effects as a module")
    if seen != _CONSUMED:
        fails.append(f"the proven_call admission imports {sorted(seen)} from heap_effects, "
                     f"expected {sorted(_CONSUMED)}")
    return fails


def run(write: bool = False) -> int:
    cases, rejections, fails = _manifest()
    fails += _replay(cases, rejections, write)
    fails += _ledger(cases, rejections)
    fails += _semantics()
    fails += _inert()
    for f in fails:
        print(f"FAIL heap_effects: {f}")
    print(f"heap_effects: {len(cases)} cases, {len(rejections)} rejections, "
          f"{len(EXPECT)} pinned summaries — {'FAIL' if fails else 'PASS'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run(write="--write" in sys.argv[1:]))
