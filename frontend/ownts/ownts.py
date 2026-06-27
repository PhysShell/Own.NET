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

It ALSO feeds the new **EFF001** core analysis (the unstable-dependency "effect
storm"): a genuinely new dimension — dependency-identity *stability*, not an
acquire->release leak. The honest split is preserved end-to-end: this frontend
emits only *facts* (each render-scope binding's syntactic shape, the dep list, and
whether the effect body does IO) into the OwnIR `effects` block; the stability
VERDICT is the core's (ownlang/effects.py), exactly as the DI captive check decides
over the `services` graph. EFF001 does NOT masquerade as OWN001 — it is its own
core code, like DI001.

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


def to_ownir(comps: list[Component], module: str,
             effects: list[dict] | None = None) -> dict:
    facts = {
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
    if effects:
        # The EFF001 stability facts the core's effects analysis decides on. The
        # frontend states only what each binding syntactically IS — it does NOT
        # pre-judge stability (that gate lives in ownlang/effects.py).
        facts["effects"] = effects
    return facts


# Network-IO calls in an effect body — the "leaks requests, not memory" trigger.
_IO = re.compile(r"\bfetch\s*\(|\baxios\b|\.(?:get|post|put|patch|delete)\s*\(|XMLHttpRequest")
# `const/let/var NAME = RHS` (simple binding; destructures fall through to stable).
_BINDING = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^\n;]+)")


def _classify_rhs(rhs: str) -> tuple[str, list[str]]:
    """Map a binding's right-hand side to an OwnIR identity `init` kind (+ the names
    it references, for derivations). Purely syntactic — the stability VERDICT is the
    core's; this only reports the shape the core reasons over."""
    r = rhs.strip()
    if r.startswith("{"):
        return "object", []
    if r.startswith("["):
        return "array", []
    if r.startswith("new "):
        return "new", []
    if r.startswith("useMemo"):
        return "memo", []
    if r.startswith("useCallback"):
        return "callback", []
    if r.startswith("useRef"):
        return "ref", []
    if r.startswith("function") or re.match(r"^(?:async\s+)?\(?[\w$,\s]*\)?\s*=>", r):
        return "fn", []
    if re.match(r"^(?:['\"`]|-?\d|true\b|false\b|null\b|undefined\b)", r):
        return "primitive", []
    # a bare identifier or member chain (`a`, `a.b.c`) — an alias/derivation of one root
    m = re.match(r"^([A-Za-z_$][\w$]*)(?:\.[A-Za-z_$][\w$]*)*$", r)
    if m:
        return "ident", [m.group(1)]
    # a function call returns an opaque (possibly fresh) identity -> let the core stay
    # conservative (UNKNOWN, no finding) rather than guess.
    if re.match(r"^[A-Za-z_$][\w$.]*\s*\(", r):
        return "call", []
    return "unknown", []


def extract_effects(path: str) -> list[dict]:
    """Extract the EFF001 stability facts: for each `useEffect`, its dependency list,
    whether its body does network IO, and the render-scope binding table of the
    component it lives in. The core's effects analysis turns these into a verdict."""
    text = _strip_comments(open(path, encoding="utf-8").read())
    # render-scope bindings, attributed to their enclosing component.
    binds_by_comp: dict[str, list[dict]] = {}
    for m in _BINDING.finditer(text):
        kind, refs = _classify_rhs(m.group(2))
        binds_by_comp.setdefault(_component_at(text, m.start()), []).append({
            "name": m.group(1), "init": kind, "refs": refs,
            "line": text.count("\n", 0, m.start()) + 1,
        })
    effects: list[dict] = []
    for eff in _USE_EFFECT.finditer(text):
        end = _match_block(text, eff.end())
        body = text[eff.end():end]
        deps_m = re.search(r",\s*\[([^\]]*)\]\s*\)", text[end - 1:end + 200])
        if not deps_m:  # no dep array -> not an EFF001 candidate (by-design re-run cadence)
            continue
        deps = [d.strip() for d in deps_m.group(1).split(",") if d.strip()]
        cname = _component_at(text, eff.start())
        effects.append({
            "component": cname, "file": path,
            "line": text.count("\n", 0, eff.start()) + 1,
            "io": bool(_IO.search(body)),
            "deps": deps,
            "bindings": binds_by_comp.get(cname, []),
        })
    return effects


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
    effects = extract_effects(path)
    facts = to_ownir(comps, module, effects)

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
