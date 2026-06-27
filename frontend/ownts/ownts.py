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
# discriminator the core understands, and (c) the EFF id + tag for provenance. The
# `resource` value is the *only* field the core acts on; `eff`/`profile` ride along
# as additive provenance the core ignores. Whether a *specific* acquire is released
# is decided per-resource by `_is_released` (matched to its own token/handler — not
# a kind-level "is there any cleanup verb", which would mark every same-kind acquire
# released as soon as one is cleaned up).
@dataclass(frozen=True)
class Acquire:
    name: str            # human label, e.g. "setInterval"
    pattern: re.Pattern  # spots the acquire call
    resource: str        # OwnIR resource kind: timer / subscribe / subscription
    eff: str             # Own.React catalog id

ACQUIRES: list[Acquire] = [
    Acquire("setInterval", re.compile(r"\bsetInterval\s*\("), "timer", "EFF004"),
    Acquire("setTimeout", re.compile(r"\bsetTimeout\s*\("), "timer", "EFF004"),
    Acquire(".subscribe", re.compile(r"\.subscribe\s*\("), "subscribe", "EFF003"),
    Acquire("addEventListener", re.compile(r"\.addEventListener\s*\("),
            "subscription", "EFF003"),
]


def _lhs_token(setup: str, pos: int) -> str | None:
    """The handle an acquire's result is bound to, so a matching `clearTimeout(handle)`
    / `handle.unsubscribe()` in cleanup can be found. Covers a declaration
    (`const id = setInterval(...)`), a plain reassignment of a pre-declared variable
    (`let i; … i = setInterval(...)`), and a ref/member store
    (`timeoutRef.current = setTimeout(...)`). Scoped to the current statement; takes
    the LAST assignment target before the call."""
    head = re.split(r"[;\n{}]", setup[:pos])[-1]
    tok = None
    for m in re.finditer(
            r"(?:(?:const|let|var)\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*=(?!=)",
            head):
        tok = m.group(1)
    return tok


def _capture_flag(opts: str) -> str:
    """The capture flag an addEventListener/removeEventListener options arg implies —
    the only field that identifies a listener for removal. `'true'`/`'false'`, or
    `'unknown'` for a non-literal we cannot read. An omitted arg, or an options
    object without a `capture` key, defaults to capture **false** (the DOM default);
    `passive`/`once`/`signal` do not affect removal identity."""
    o = opts.strip()
    if o in ("", "false"):
        return "false"
    if o == "true":
        return "true"
    if o.startswith("{"):
        m = re.search(r"\bcapture\s*:\s*(true|false)\b", o)
        return m.group(1) if m else "false"
    return "unknown"  # a variable/call — compare verbatim (equal only to itself)


_LISTENER = re.compile(
    r"\.\s*(?:add|remove)EventListener\s*\(\s*([^,]+?)\s*,\s*([A-Za-z_$][\w$.]*)\s*"
    r"(?:,\s*([^)]+?))?\s*\)")


def _listener_call(s: str) -> tuple[str, str, str] | None:
    """Parse a `.addEventListener`/`.removeEventListener` head into the
    (event, handler, capture) triple that identifies the listener for removal, or
    None when it doesn't parse. `s` starts at the `.`."""
    m = _LISTENER.match(s.lstrip())
    if not m:
        return None
    return (m.group(1).strip(), m.group(2), _capture_flag(m.group(3) or ""))


def _receiver(text: str, end: int) -> str:
    """The receiver expression ending at `end` (just before `.addEventListener`),
    allowing a member/index chain like `this.ref` or `nodes[i]`."""
    m = re.search(r"([A-Za-z_$][\w$.\[\]]*)$", text[:end])
    return m.group(1) if m else ""


def _call_args(s: str) -> str | None:
    """The normalized (whitespace-stripped) argument text of the first call in `s`,
    e.g. `target,handler` for `.subscribe(target, handler)`. None if no `(`."""
    i = s.find("(")
    if i == -1:
        return None
    close = _match_pair(s, i, "(", ")")
    return re.sub(r"\s+", "", s[i + 1:close - 1])


def _signal_controller(setup: str, opts: str) -> str | None:
    """The AbortController whose `signal` an addEventListener options arg uses, so a
    cleanup is only credited when THAT controller is aborted. `{ signal: c.signal }`
    → `c`; the shorthand `{ signal }` is resolved back through `const signal =
    c.signal` / `const { signal } = c` in setup. None when it can't be tied."""
    m = re.search(r"\bsignal\s*:\s*([A-Za-z_$][\w$.]*)", opts)
    if m:
        return re.sub(r"\.signal$", "", m.group(1))
    if re.search(r"\bsignal\b", opts):  # shorthand `{ signal }`
        m = re.search(r"(?:const|let|var)\s+signal\s*=\s*([A-Za-z_$][\w$]*)\s*\.\s*signal\b",
                      setup)
        if m:
            return m.group(1)
        m = re.search(r"(?:const|let|var)\s*\{\s*signal\b[^}]*\}\s*=\s*([A-Za-z_$][\w$]*)",
                      setup)
        if m:
            return m.group(1)
    return None


def _is_released(acq: Acquire, setup: str, pos: int, cleanup: str) -> bool:
    """Whether THIS acquire (at `pos` in `setup`) is released by the effect's cleanup
    — matched to its own handle, so two `setInterval`s with one `clearInterval` leave
    the other a leak. A resource with no capturable handle (a bare `setInterval(...)`
    or an ignored `.subscribe(...)` result) can never be released → False."""
    if acq.resource == "timer":
        tok = _lhs_token(setup, pos)
        return bool(tok and re.search(
            rf"\bclear(?:Interval|Timeout)\s*\(\s*{re.escape(tok)}\b", cleanup))
    if acq.resource == "subscribe":
        tok = _lhs_token(setup, pos)
        if tok and re.search(
                rf"\b{re.escape(tok)}\s*\.\s*(?:unsubscribe|remove)\s*\(", cleanup):
            return True
        # a bare `recv.subscribe(args)` (no token) is released only by a cleanup
        # `recv.unsubscribe(args)` on the SAME receiver AND the same argument list
        # (a `disconnect()` with no args tears down everything). Iterating + comparing
        # in Python gives an exact receiver match (no `otherro` substring) and no
        # interpolated regex.
        recv = _receiver(setup, pos)
        if not recv:
            return False
        sub_args = _call_args(setup[pos:])
        for um in re.finditer(
                r"([A-Za-z_$][\w$.\[\]]*)\s*\.\s*(?:unsubscribe|disconnect)\s*\(", cleanup):
            if um.group(1) == recv and _call_args(cleanup[um.end() - 1:]) in ("", sub_args):
                return True
        return False
    if acq.resource == "subscription":  # target.addEventListener(event, handler[, opts])
        a = _listener_call(setup[pos:])
        if a is None:
            return False
        # AbortController: a signal-bound listener is released only when THE controller
        # backing that signal is aborted in cleanup — tie `{ signal }` back to its
        # controller and require `<that controller>.abort()`, not any `.abort()`.
        am = _LISTENER.match(setup[pos:].lstrip())
        opts = (am.group(3) or "") if am else ""
        ctrl = _signal_controller(setup, opts)
        if ctrl and any(
                ab.group(1) == ctrl for ab in
                re.finditer(r"([A-Za-z_$][\w$.\[\]]*)\s*\.\s*abort\s*\(", cleanup)):
            return True
        # Otherwise the full listener key is (receiver, event, handler, capture): a
        # listener is released ONLY by a removeEventListener whose whole key matches —
        # a different event name, target, or capture flag is a different listener that
        # still leaks. Fail closed if the target can't be identified.
        a_recv = _receiver(setup, pos)
        if not a_recv:
            return False
        for rm in re.finditer(r"([A-Za-z_$][\w$.\[\]]*)\s*\.\s*removeEventListener\s*\(",
                              cleanup):
            if rm.group(1) != a_recv:
                continue
            b = _listener_call(cleanup[rm.start() + len(rm.group(1)):])
            if b == a:
                return True
        return False
    return False

# A React component is a function whose name is Capitalized (the JSX convention).
_COMPONENT = re.compile(
    r"(?:function\s+([A-Z]\w*)\b|"
    r"(?:const|let|var)\s+([A-Z]\w*)\s*=\s*(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>)"
)


def _body_brace(text: str, start: int) -> int:
    """Index of a component's body `{`, scanning from `start` (just past the name or
    `=>`). Skips the parameter list by paren depth, so a destructured param
    `({ x }: { x: T })` is not mistaken for the body block."""
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "{" and depth == 0:
            return i
    return -1
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


def _mask_strings(text: str) -> str:
    """Blank the CONTENT of string/template literals — keeping the delimiters, the
    length, and every newline — so the structural scanners (brace/paren/bracket
    depth, top-level commas, the deps array) are never fooled by punctuation inside
    a literal: `fetch("/a,b")`, `const s = "{"`, a `;` inside a string. Comments are
    already gone (`_strip_comments`). Positions are preserved, so a match found on
    the masked copy slices identically out of the original text."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            i += 1
            while i < n and text[i] != c:
                if text[i] == "\\" and i + 1 < n:
                    for k in (i, i + 1):
                        if text[k] != "\n":
                            out[k] = " "
                    i += 2
                    continue
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            i += 1  # past the closing delimiter (kept)
        else:
            i += 1
    return "".join(out)


def _match_pair(text: str, i: int, open_c: str, close_c: str) -> int:
    """Index just past the `close_c` matching the `open_c` at/after `i`. Assumes
    string contents are already masked (so no quote-skipping is needed here)."""
    i = text.index(open_c, i)
    depth = 0
    while i < len(text):
        if text[i] == open_c:
            depth += 1
        elif text[i] == close_c:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _split_top_commas(s: str) -> list[str]:
    """Split on commas at bracket/paren/brace depth 0, so a dependency like
    `items[i]` or `f(a, b)` stays one entry instead of being torn at its inner comma."""
    parts: list[str] = []
    depth, start = 0, 0
    for j, c in enumerate(s):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(s[start:j])
            start = j + 1
    parts.append(s[start:])
    return [p.strip() for p in parts if p.strip()]


def _component_at(text: str, idx: int) -> str:
    """Name of the React component enclosing position `idx` — the nearest preceding
    Capitalized function declaration. Falls back to a synthetic name."""
    name = None
    for m in _COMPONENT.finditer(text, 0, idx):
        name = m.group(1) or m.group(2)
    return name or "AnonymousComponent"


def _expr_end(text: str, i: int) -> int:
    """End index of an expression body — the first top-level `,` or `)` from `i`
    (so the `, [deps])` tail and the `useEffect(` close are not swallowed)."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c == "," and depth == 0:
            return i
        i += 1
    return i


def _effect_callback(masked: str, after_open: int) -> tuple[str, int, list[str] | None, int]:
    """Parse `useEffect(<cb>, [deps])` from just past the `(`, over the STRING-MASKED
    source (so literals never truncate a body or split a dep). Returns
    (body, body_start, deps, end). Handles a block arrow `() => { ... }`, an
    expression arrow `() => fetch(url)`, AND a `function () { ... }` expression
    (transpiled ES5 output) — calling `_match_block` blindly, or keying on `=>`,
    would jump to an unrelated `{`/arrow or run off the end. `deps` is None when no
    dependency array is present; the array is matched by BALANCED brackets so a dep
    like `items[i]` survives. `body` includes the braces for a block callback."""
    j0 = after_open
    while j0 < len(masked) and masked[j0] in " \t\r\n":
        j0 += 1
    if re.match(r"(?:async\s+)?function\b", masked[j0:]):
        # function-expression callback: the body `{` follows the parameter list.
        i = _body_brace(masked, after_open)
        end = _match_block(masked, i) if i != -1 else len(masked)
        if i == -1:
            i = after_open
    else:
        arrow = masked.find("=>", after_open)
        i = (arrow + 2) if arrow != -1 else after_open
        while i < len(masked) and masked[i] in " \t\r\n":
            i += 1
        if i < len(masked) and masked[i] == "{":
            end = _match_block(masked, i)
        else:
            end = _expr_end(masked, i)
    body = masked[i:end]
    # the dependency array is the balanced `[ ... ]` after an optional `, `
    deps: list[str] | None = None
    j = end
    while j < len(masked) and masked[j] in " \t\r\n":
        j += 1
    if j < len(masked) and masked[j] == ",":
        j += 1
        while j < len(masked) and masked[j] in " \t\r\n":
            j += 1
        if j < len(masked) and masked[j] == "[":
            close = _match_pair(masked, j, "[", "]")
            deps = _split_top_commas(masked[j + 1:close - 1])
    return body, i, deps, end


def _cleanup_span(mbody: str) -> tuple[int, int, int] | None:
    """`(start, end, cov_start)` for the effect's OWN cleanup within `mbody` (masked),
    or None. The cleanup is the `return () => …` directly in the effect callback —
    possibly inside an `if`/`try`/`.then()` BLOCK, but NOT inside a nested CALLBACK. So
    the test is FUNCTION depth, not brace depth: a block `{` keeps us in the effect; an
    arrow/`function` body `{` is a new function. A return at function-depth 1 is the
    cleanup; deeper is some inner callback's return.

    `cov_start` bounds which acquires the cleanup may credit: only acquires at body
    position `cov_start < p < start` are co-guarded with the cleanup. For a top-level
    cleanup that is the whole effect body (`cov_start == 0`); for a cleanup inside a
    block it is that block's `{` (so an acquire OUTSIDE the branch is NOT released by a
    conditional cleanup); for a *braceless* guard (`if (x) return …`) it is `start`
    (empty), so a conditionally-returned cleanup releases nothing it does not dominate."""
    # function-body braces: the effect body's own `{` (index 0), plus every `=> {`
    # and `function (...) {`. Every other `{` is a plain block (if/try/for/object).
    fn_braces = {0}
    for fm in re.finditer(r"=>\s*\{", mbody):
        fn_braces.add(fm.end() - 1)
    for fm in re.finditer(r"\bfunction\b[^{;]*?\)\s*\{", mbody):
        fn_braces.add(fm.end() - 1)
    # a cleanup is `return <arrow>` or `return <function expression>` (ES5 output).
    ret_re = re.compile(r"return\s*(?:(?:\(\s*\)|\w+)\s*=>|(?:async\s+)?function\b)")
    stack: list[tuple[bool, int]] = []  # (is_function_body, open_index) per open brace
    fdepth = 0
    i, n = 0, len(mbody)
    while i < n:
        c = mbody[i]
        if c == "{":
            is_fn = i in fn_braces
            stack.append((is_fn, i))
            fdepth += 1 if is_fn else 0
            i += 1
            continue
        if c == "}":
            if stack and stack.pop()[0]:
                fdepth -= 1
            i += 1
            continue
        if c == "r" and fdepth == 1:
            m = ret_re.match(mbody, i)
            if m:
                cov_start = stack[-1][1] if stack else 0  # innermost enclosing block
                b = max(mbody.rfind(";", 0, i), mbody.rfind("{", 0, i),
                        mbody.rfind("}", 0, i))
                if re.search(r"\b(?:if|else|for|while)\b", mbody[b + 1:i]):
                    cov_start = m.start()  # braceless conditional guard -> covers nothing
                if "function" in m.group():  # `return function () { ... }` (ES5 cleanup)
                    brace = _body_brace(mbody, m.end())  # body brace after the params
                    if brace != -1:
                        return (m.start(), _match_block(mbody, brace), cov_start)
                    i += 1
                    continue
                rest = mbody[m.end():]
                stripped = rest.lstrip()
                if stripped.startswith("{"):  # block-bodied cleanup: `=> { ... }`
                    brace = m.end() + (len(rest) - len(stripped))
                    return (m.start(), _match_block(mbody, brace), cov_start)
                # single-expression cleanup — consume the WHOLE expression across line
                # breaks, stopping at a top-level `;` or the effect body's own close.
                j, depth = m.end(), 0
                while j < n:
                    cj = mbody[j]
                    if cj in "([{":
                        depth += 1
                    elif cj in ")]}":
                        if depth == 0:
                            break
                        depth -= 1
                    elif cj == ";" and depth == 0:
                        break
                    j += 1
                return (m.start(), j, cov_start)
        i += 1
    return None


def extract(path: str) -> list[Component]:
    text = _strip_comments(open(path, encoding="utf-8").read())
    masked = _mask_strings(text)  # scan structure on this; show snippets from `text`
    comps: dict[str, Component] = {}
    for eff in _USE_EFFECT.finditer(masked):
        body_m, body_start, _deps, end = _effect_callback(masked, eff.end())
        body_o = text[body_start:end]  # original (unmasked) body — same positions
        span = _cleanup_span(body_m)
        if span:
            cs, ce, cov_start = span
            setup_m = body_m[:cs] + body_m[ce:]
            setup_o = body_o[:cs] + body_o[ce:]
            cleanup_o = body_o[cs:ce]
        else:
            cs = ce = cov_start = -1
            setup_m, setup_o, cleanup_o = body_m, body_o, ""
        cname = _component_at(masked, eff.start())
        comp = comps.setdefault(cname, Component(cname, path))
        for acq in ACQUIRES:
            # find the acquire on the MASKED setup (a keyword inside a string is gone);
            # decide release on the ORIGINAL setup/cleanup (so event-name strings and
            # handles are intact for the full-key comparison).
            for hit in acq.pattern.finditer(setup_m):
                # map the setup position back to the body (the cleanup span was cut out)
                sp = hit.start()
                bp = sp if (cs < 0 or sp < cs) else sp + (ce - cs)
                abs_pos = body_start + bp
                line = masked.count("\n", 0, abs_pos) + 1
                # a conditional cleanup only releases acquires it dominates (co-guarded
                # in the same block); an acquire outside that block keeps its own cleanup
                # empty, so a `return` guarded by a branch cannot silence it.
                covered = cs < 0 or cov_start < bp < cs
                released = _is_released(acq, setup_o, sp, cleanup_o if covered else "")
                # the acquire expression for the tag — from the ORIGINAL text, so the
                # message shows the real call (string args intact), trimmed to one line.
                snippet = text[abs_pos:].splitlines()[0].strip().rstrip("{").strip()
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


def _render_bindings(text: str) -> dict[str, list[dict]]:
    """The render-scope binding table per component, scanned over STRING-MASKED
    source so a brace/quote inside a literal cannot shift the depth. Only bindings
    declared DIRECTLY in the component body (brace-depth 1) count. A `const filters
    = {...}` inside a
    `useEffect` callback, an event handler, or any nested block is NOT render scope —
    it must not shadow the real outer dependency of the same name and mint a false
    EFF001. Excluding a render-level `if`/`try` binding only costs a missed finding
    (the dep reads as stable), never a false one — the safe direction."""
    out: dict[str, list[dict]] = {}
    for cm in _COMPONENT.finditer(text):
        name = cm.group(1) or cm.group(2)
        brace = _body_brace(text, cm.end())  # skips a destructured param list
        if brace == -1:
            continue
        body_end = _match_block(text, brace)
        body = text[brace + 1:body_end]
        base = text.count("\n", 0, brace + 1)  # 0-based line index of the body start
        binds: list[dict] = []
        for m in _BINDING.finditer(body):
            prefix = body[:m.start()]
            if prefix.count("{") != prefix.count("}"):
                continue  # inside a nested block -> not the component's render scope
            kind, refs = _classify_rhs(m.group(2))
            binds.append({"name": m.group(1), "init": kind, "refs": refs,
                          "line": base + prefix.count("\n") + 1})
        out[name] = binds
    return out


def extract_effects(path: str) -> list[dict]:
    """Extract the EFF001 stability facts: for each `useEffect`, its dependency list,
    whether its body does network IO, and the render-scope binding table of the
    component it lives in. The core's effects analysis turns these into a verdict."""
    text = _strip_comments(open(path, encoding="utf-8").read())
    masked = _mask_strings(text)
    binds_by_comp = _render_bindings(masked)
    effects: list[dict] = []
    for eff in _USE_EFFECT.finditer(masked):
        body, _start, deps, _end = _effect_callback(masked, eff.end())
        if deps is None:  # no dep array -> not an EFF001 candidate (by-design re-run cadence)
            continue
        cname = _component_at(masked, eff.start())
        effects.append({
            "component": cname, "file": path,
            "line": masked.count("\n", 0, eff.start()) + 1,
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
