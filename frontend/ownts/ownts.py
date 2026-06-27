#!/usr/bin/env python3
"""OwnTS frontend spike — React `useEffect` acquire/release facts -> OwnIR.

This is the TS/TSX sibling of the Roslyn C# extractor (frontend/roslyn/): it scans
real `.tsx` and emits *facts* in the OwnIR vocabulary, which the existing Python
core (`python -m ownlang ownir`) routes through the same OWN001 acquire->release
checker. The core stays the one checker — we do not reimplement leak analysis in
JS-land (that would drift), exactly as the C# side does not.

Scope is a deliberate **spike**, per docs/proposals/P-020 ("Not a TypeScript
analyzer"). It implements the honest, end-to-end-today slice of the `Own.React`
EFF catalog — the rules that *are* the existing acquire->release model:

    EFF003  effect subscribes (`X.subscribe(...)`) with no cleanup return  -> OWN001
    EFF004  setInterval/setTimeout in an effect with no cleanup            -> OWN001
    (addEventListener with no removeEventListener cleanup)                  -> OWN001

It does NOT implement EFF001/002 (the unstable-dependency "effect storm"): that is
a genuinely new core analysis (dependency-identity stability), not an
acquire->release leak, and P-020 is explicit that EFF001 must not masquerade as
OWN001. As a courtesy the scanner emits a clearly-labelled, *frontend-only*
heuristic note for EFF001 candidates on stderr — never as a core-verified finding.

The extraction is heuristic (brace matching + verb detection), not a real TS parse.
That is fine for a spike whose job is to prove the seam, not to ship a frontend.

Usage::

    python frontend/ownts/ownts.py App.tsx                 # print OwnIR JSON
    python frontend/ownts/ownts.py App.tsx -o app.facts.json
    python frontend/ownts/ownts.py App.tsx --check         # run through the core
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field


# --- acquire catalog: how each React acquire maps onto a core resource kind -----
#
# Each acquire has (a) a regex that spots the acquire call, (b) the OwnIR `resource`
# discriminator the core understands, (c) the cleanup verb that releases it, and
# (d) the EFF id + tag for provenance. The `resource` value is the *only* field the
# core acts on; `eff`/`profile` ride along as additive provenance the core ignores.
@dataclass(frozen=True)
class Acquire:
    name: str            # human label, e.g. "setInterval"
    pattern: re.Pattern  # spots the acquire call
    resource: str        # OwnIR resource kind: timer / subscribe / subscription
    release: re.Pattern  # the cleanup verb that releases it
    eff: str             # Own.React catalog id

ACQUIRES: list[Acquire] = [
    Acquire("setInterval", re.compile(r"\bsetInterval\s*\("),
            "timer", re.compile(r"\bclearInterval\s*\("), "EFF004"),
    Acquire("setTimeout", re.compile(r"\bsetTimeout\s*\("),
            "timer", re.compile(r"\bclearTimeout\s*\("), "EFF004"),
    Acquire(".subscribe", re.compile(r"\.subscribe\s*\("),
            "subscribe", re.compile(r"\.unsubscribe\s*\(|\.remove\s*\("), "EFF003"),
    Acquire("addEventListener", re.compile(r"\.addEventListener\s*\("),
            "subscription", re.compile(r"\.removeEventListener\s*\("), "EFF003"),
]

# A React component is a function whose name is Capitalized (the JSX convention).
_COMPONENT = re.compile(
    r"(?:function\s+([A-Z]\w*)\s*\(|"
    r"(?:const|let|var)\s+([A-Z]\w*)\s*=\s*(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>)"
)
_USE_EFFECT = re.compile(r"\buseEffect\s*\(")


@dataclass
class Resource:
    event: str
    line: int
    released: bool
    resource: str
    eff: str


@dataclass
class Component:
    name: str
    file: str
    resources: list[Resource] = field(default_factory=list)


def _strip_comments(text: str) -> str:
    """Blank out `//` and `/* */` comments (preserving newlines so line numbers
    survive) without touching string/template contents. Stops the scanner from
    mistaking a `// no return () => clearInterval(id)` note for real cleanup."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            out.append(c)
            i += 1
            while i < len(text) and text[i] != c:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < len(text):
                    out.append(text[i + 1])
                    i += 2
                    continue
                i += 1
            if i < len(text):
                out.append(text[i])
                i += 1
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                out.append(" ")
                i += 1
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            while i < len(text):
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    break
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _match_block(text: str, open_idx: int) -> int:
    """Index just past the `}` that closes the `{` at/after `open_idx`. Skips over
    string/template/comment content so a brace inside a string does not fool us."""
    i = text.index("{", open_idx)
    depth = 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            quote = c
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            i = text.find("\n", i)
            if i == -1:
                return len(text)
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i)
            i = len(text) if end == -1 else end + 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _component_at(text: str, idx: int) -> str:
    """Name of the React component enclosing position `idx` — the nearest preceding
    Capitalized function declaration. Falls back to a synthetic name."""
    name = None
    for m in _COMPONENT.finditer(text, 0, idx):
        name = m.group(1) or m.group(2)
    return name or "AnonymousComponent"


def _split_cleanup(body: str) -> tuple[str, str]:
    """Split an effect body into (setup, cleanup). Cleanup is the block of the
    `return () => { ... }` the effect hands back to React; setup is the rest."""
    m = re.search(r"return\s*(?:\(\s*\)|\w+)\s*=>", body)
    if not m:
        return body, ""
    brace = body.find("{", m.end())
    if brace == -1:
        # `return () => clearInterval(id)` — single-expression cleanup, no block.
        nl = body.find("\n", m.end())
        tail = body[m.end(): nl if nl != -1 else len(body)]
        return body[: m.start()], tail
    end = _match_block(body, brace)
    return body[: m.start()] + body[end:], body[brace:end]


def extract(path: str) -> list[Component]:
    text = _strip_comments(open(path, encoding="utf-8").read())
    comps: dict[str, Component] = {}
    for eff in _USE_EFFECT.finditer(text):
        end = _match_block(text, eff.end())
        body = text[eff.end():end]
        setup, cleanup = _split_cleanup(body)
        cname = _component_at(text, eff.start())
        comp = comps.setdefault(cname, Component(cname, path))
        for acq in ACQUIRES:
            for hit in acq.pattern.finditer(setup):
                line = text.count("\n", 0, eff.end() + hit.start()) + 1
                released = bool(acq.release.search(cleanup))
                # the acquire expression, trimmed to the call head for a readable tag
                snippet = setup[hit.start():].splitlines()[0].strip().rstrip("{").strip()
                comp.resources.append(
                    Resource(snippet or acq.name, line, released, acq.resource, acq.eff))
    return [c for c in comps.values() if c.resources]


def to_ownir(comps: list[Component], module: str) -> dict:
    return {
        "ownir_version": 0,
        "module": module,
        "components": [
            {
                "name": c.name,
                "file": c.file,
                # historically named "subscriptions"; it is the owned-resource list.
                "subscriptions": [
                    {"event": r.event, "line": r.line, "released": r.released,
                     "resource": r.resource,
                     # additive provenance the core ignores:
                     "profile": "react", "eff": r.eff}
                    for r in c.resources
                ],
            }
            for c in comps
        ],
    }


def _eff001_notes(path: str) -> list[str]:
    """Frontend-only heuristic for EFF001 (unstable dependency -> effect storm).
    NOT a core finding — the core has no stability model (P-020 open question 1).
    Flags `useEffect(..., [dep])` where `dep` is a local object/array literal that
    does IO, i.e. a fresh identity every render."""
    text = _strip_comments(open(path, encoding="utf-8").read())
    notes = []
    for eff in _USE_EFFECT.finditer(text):
        end = _match_block(text, eff.end())
        block = text[eff.end():end]
        # deps array sits just past the effect body block: `}, [a, b])`
        deps = re.search(r",\s*\[([^\]]*)\]\s*\)", text[end - 1:end + 120])
        if not deps:
            continue
        does_io = re.search(r"\bfetch\s*\(|\baxios\b|\.get\s*\(|\.post\s*\(", block)
        for dep in (d.strip() for d in deps.group(1).split(",") if d.strip()):
            decl = re.search(
                rf"(?:const|let|var)\s+{re.escape(dep)}\s*=\s*(\{{|\[)", text)
            if decl and does_io:
                line = text.count("\n", 0, eff.start()) + 1
                notes.append(
                    f"{path}:{line}: EFF001 (frontend heuristic, NOT core-verified): "
                    f"dependency '{dep}' is a fresh object/array identity every render; "
                    f"the effect does IO — possible request storm. Stabilise with useMemo.")
    return notes


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}
    out = None
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
    if not args:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: ownts.py FILE.tsx [--check] [-o facts.json]", file=sys.stderr)
        return 2
    path = args[0]
    module = re.sub(r"\.[jt]sx?$", "", path.rsplit("/", 1)[-1])
    comps = extract(path)
    facts = to_ownir(comps, module)

    for note in _eff001_notes(path):
        print(note, file=sys.stderr)

    if "--check" in flags:
        # Run the extracted facts straight through the existing core.
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from ownlang.ownir import check_facts, render_finding
        findings = check_facts(facts)
        for f in findings:
            print(render_finding(f, "human"))
        n = len(findings)
        print(f"\n{n} finding{'s' if n != 1 else ''} (via OwnTS -> OwnIR -> core).")
        return 1 if findings else 0

    payload = json.dumps(facts, indent=2)
    if out:
        open(out, "w", encoding="utf-8").write(payload + "\n")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
