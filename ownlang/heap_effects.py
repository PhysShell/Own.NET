"""Heap-effect summaries — H0 (docs/notes/heap-effect-summaries.md). INERT.

What a source-visible method may do to memory its caller can see, solved from the
extractor's heap-effect SOURCE FACTS (`ownsharp-extract --heap-effects FILE`) by a
least fixpoint over the call graph's SCC condensation. It is a second summary
domain beside the Method Ownership Summary (`ownership.py`), in its own document:
nothing here reads OwnIR facts, and nothing in the checker reads this. No verdict,
refusal or diagnostic depends on it, with ONE exception: OwnIR v2's `proven_call`
(H1) admits a call inside an exclusive region only when `site_verdict` below proves
it harmless — the predicate lives here, in the summary layer, not in the typestate
code that asks.

THE DOMAIN, per method:

  params[i].effect, receiver   plain < borrow < borrow_mut < may_escape < unknown
      plain       the argument's object graph is not touched (every inert value is plain);
      borrow      it is read through;
      borrow_mut  it may be written through (a field, an element, a ref/out location);
      may_escape  it may be stored where it outlives the call — after which anybody may
                  write it, so may_escape subsumes borrow_mut on this chain;
      unknown     nothing proves less.
  writes.{instance,static,indirect}   none < may < unknown — writes to memory reached
      from NEITHER the parameters NOR the receiver: an object's field (instance), a
      static field (static), an array element or other indirect storage (indirect).
      A write through a parameter is that parameter's borrow_mut, not a `writes` entry.
  returns   [] (nothing the caller can reach through, or an inert value) | some of
      param:<i>, receiver, heap | ["unknown"].
  unresolved   the method's OWN reasons for an Unknown (an unmodelled construct, a call
      that is extern / virtual / through a delegate / to a method with no record).
      Local, for evidence; what is transitively unknown shows in the effects.

UNKNOWN ABSORBS wherever silence would read as clean: a method with an unmodelled
construct is Unknown on every non-inert parameter, its receiver, every write kind and
its return; a call nothing summarizes makes every argument and the receiver Unknown
and every write kind Unknown; a value that came back from such a call is an Unknown
root, and a write through it is an Unknown write.

Determinism (the parity contract with `own-bridge/src/heap_effects.rs`): the solution
is the least fixpoint of a monotone system over finite lattices, so it is independent
of iteration order; the dump sorts summaries by key and serializes
`json.dumps(indent=2, sort_keys=True)` plus a newline. The Rust port reproduces the
dump byte-for-byte (tests/test_heap_effects_fixtures.py, own-bridge/tests/heap_effects.rs).

Run:  python -m ownlang.heap_effects sidecar.json      (print the solved summaries)
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

HEAP_EFFECTS_VERSION = 1

EFFECTS = ("plain", "borrow", "borrow_mut", "may_escape", "unknown")
PLAIN, BORROW, BORROW_MUT, MAY_ESCAPE, UNKNOWN = range(5)
WRITES = ("none", "may", "unknown")
W_NONE, W_MAY, W_UNKNOWN = range(3)
WRITE_KINDS = ("instance", "static", "indirect")
DISPATCHES = ("direct", "virtual", "extern", "delegate")

_TOKEN = re.compile(r"(param|local|call):(0|[1-9][0-9]*)")
_MAX_LINE = 2147483647


class HeapEffectsError(Exception):
    """The sidecar does not satisfy its own vocabulary. The message is the parity text."""


# --- the source facts -------------------------------------------------------


@dataclass(frozen=True)
class Call:
    callee: str
    dispatch: str
    receiver: tuple[str, ...] | None
    args: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Method:
    key: str
    file: str
    line: int
    receiver: bool
    return_inert: bool
    params: tuple[tuple[str, bool], ...]  # (name, inert), by index
    locals: tuple[tuple[str, ...], ...]  # sources, by id
    derefs: tuple[str, ...]
    writes: tuple[tuple[str, tuple[str, ...]], ...]
    stores: tuple[str, ...]
    returns: tuple[str, ...]
    calls: tuple[Call, ...]
    unknown: tuple[str, ...]


def _fail(where: str, what: str) -> HeapEffectsError:
    return HeapEffectsError(f"heap-effect facts: {where}: {what}")


def _is_int(v: object) -> bool:
    """An integer both JSON readers hold exactly (the Rust port reads 64-bit integers;
    anything wider it reads as a float, so it is a wrong type on both sides)."""
    return type(v) is int and -(2 ** 63) <= v <= 2 ** 64 - 1


def _strings(v: object) -> tuple[str, ...] | None:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        return None
    return tuple(v)


def load(doc: object) -> list[Method]:
    """Validate a sidecar document and return its methods (in document order).

    Validation order IS the parity contract: the first violation in this order is the
    one reported, by both engines, with the same text."""
    if not isinstance(doc, dict):
        raise HeapEffectsError("heap-effect facts: the document is not an object")
    version = doc.get("heap_effects_version")
    if not _is_int(version) or version != HEAP_EFFECTS_VERSION:
        raise HeapEffectsError(
            f"heap-effect facts: heap_effects_version must be {HEAP_EFFECTS_VERSION}")
    raw = doc.get("methods")
    if not isinstance(raw, list) or not all(isinstance(m, dict) for m in raw):
        raise HeapEffectsError("heap-effect facts: methods must be an array of objects")

    methods: list[Method] = []
    seen: set[str] = set()
    for i, m in enumerate(raw):
        where = f"method #{i}"

        def bad(field: str, where: str = where) -> HeapEffectsError:
            return _fail(where, f"field '{field}' is missing or has the wrong type")

        key = m.get("key")
        if not isinstance(key, str) or not key:
            raise bad("key")
        if key in seen:
            raise _fail(where, "duplicate key")
        seen.add(key)
        file = m.get("file")
        if not isinstance(file, str):
            raise bad("file")
        line = m.get("line")
        if not _is_int(line) or not 0 <= line <= _MAX_LINE:
            raise bad("line")
        receiver = m.get("receiver")
        if not isinstance(receiver, bool):
            raise bad("receiver")
        return_inert = m.get("return_inert")
        if not isinstance(return_inert, bool):
            raise bad("return_inert")

        raw_params = m.get("params")
        if not isinstance(raw_params, list):
            raise bad("params")
        params: list[tuple[str, bool]] = []
        for j, p in enumerate(raw_params):
            if (not isinstance(p, dict) or not _is_int(p.get("index"))
                    or not isinstance(p.get("name"), str) or not isinstance(p.get("inert"), bool)):
                raise bad("params")
            if p["index"] != j:
                raise _fail(where, f"params[{j}] is out of sequence")
            params.append((p["name"], p["inert"]))

        raw_locals = m.get("locals")
        if not isinstance(raw_locals, list):
            raise bad("locals")
        local_sources: list[tuple[str, ...]] = []
        for j, loc in enumerate(raw_locals):
            sources = _strings(loc.get("sources")) if isinstance(loc, dict) else None
            if (not isinstance(loc, dict) or not _is_int(loc.get("id"))
                    or not isinstance(loc.get("name"), str) or sources is None):
                raise bad("locals")
            if loc["id"] != j:
                raise _fail(where, f"locals[{j}] is out of sequence")
            local_sources.append(sources)

        raw_calls = m.get("calls")
        if not isinstance(raw_calls, list):
            raise bad("calls")
        calls: list[Call] = []
        for j, c in enumerate(raw_calls):
            if not isinstance(c, dict):
                raise bad("calls")
            args_raw = c.get("args")
            args = (tuple(_strings(a) for a in args_raw)
                    if isinstance(args_raw, list) else None)
            recv_raw = c.get("receiver")
            recv = None if recv_raw is None else _strings(recv_raw)
            if (not _is_int(c.get("id")) or not isinstance(c.get("callee"), str)
                    or not isinstance(c.get("dispatch"), str)
                    or not _is_int(c.get("line")) or not 0 <= c["line"] <= _MAX_LINE
                    or (recv_raw is not None and recv is None)
                    or args is None or any(a is None for a in args)):
                raise bad("calls")
            if c["id"] != j:
                raise _fail(where, f"calls[{j}] is out of sequence")
            if c["dispatch"] not in DISPATCHES:
                raise _fail(where, f"calls[{j}] has an unknown dispatch")
            calls.append(Call(c["callee"], c["dispatch"], recv,
                              tuple(a for a in args if a is not None)))

        raw_writes = m.get("writes")
        if not isinstance(raw_writes, list):
            raise bad("writes")
        writes: list[tuple[str, tuple[str, ...]]] = []
        for j, w in enumerate(raw_writes):
            target = _strings(w.get("target")) if isinstance(w, dict) else None
            if not isinstance(w, dict) or not isinstance(w.get("kind"), str) or target is None:
                raise bad("writes")
            if w["kind"] not in WRITE_KINDS:
                raise _fail(where, f"writes[{j}] has an unknown kind")
            writes.append((w["kind"], target))

        lists: dict[str, tuple[str, ...]] = {}
        for field in ("derefs", "stores", "returns", "unknown"):
            value = _strings(m.get(field))
            if value is None:
                raise bad(field)
            lists[field] = value

        method = Method(
            key=key, file=file, line=line, receiver=receiver, return_inert=return_inert,
            params=tuple(params), locals=tuple(local_sources), derefs=lists["derefs"],
            writes=tuple(writes), stores=lists["stores"], returns=lists["returns"],
            calls=tuple(calls), unknown=lists["unknown"])
        _check_tokens(method, where)
        methods.append(method)

    by_key = {m.key: m for m in methods}
    for i, m in enumerate(methods):
        for j, c in enumerate(m.calls):
            callee = by_key.get(c.callee)
            if c.dispatch == "direct" and callee is not None and len(c.args) != len(callee.params):
                raise _fail(f"method #{i}",
                            f"calls[{j}] has {len(c.args)} argument slots, "
                            f"its callee takes {len(callee.params)}")
    return methods


def _check_tokens(m: Method, where: str) -> None:
    def check(tokens: Iterable[str], field: str) -> None:
        for t in tokens:
            if t == "heap" or (t == "receiver" and m.receiver):
                continue
            match = _TOKEN.fullmatch(t)
            limit = {"param": len(m.params), "local": len(m.locals),
                     "call": len(m.calls)}.get(match.group(1), 0) if match else 0
            if match is None or int(match.group(2)) >= limit:
                raise _fail(where, f"{field} holds a token outside the vocabulary")

    for j, sources in enumerate(m.locals):
        check(sources, f"locals[{j}]")
    check(m.derefs, "derefs")
    for j, (_, target) in enumerate(m.writes):
        check(target, f"writes[{j}]")
    check(m.stores, "stores")
    check(m.returns, "returns")
    for j, c in enumerate(m.calls):
        if c.receiver is not None:
            check(c.receiver, f"calls[{j}].receiver")
        for k, arg in enumerate(c.args):
            check(arg, f"calls[{j}].args[{k}]")


# --- the solved summary ------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    params: tuple[int, ...]
    receiver: int | None
    writes: tuple[int, int, int]  # instance, static, indirect
    returns: tuple[str, ...]


def _bottom(m: Method) -> Summary:
    return Summary(tuple(PLAIN for _ in m.params), PLAIN if m.receiver else None,
                   (W_NONE, W_NONE, W_NONE), ())


def _callee_unknown(c: Call, methods: dict[str, Method]) -> bool:
    return c.dispatch != "direct" or c.callee not in methods


def _evaluate(m: Method, methods: dict[str, Method], solved: dict[str, Summary]) -> Summary:
    """One application of the method's transfer function to its callees' current
    summaries. Monotone in them; recomputed from scratch each time."""
    if m.unknown:
        return Summary(
            tuple(PLAIN if inert else UNKNOWN for _, inert in m.params),
            UNKNOWN if m.receiver else None,
            (W_UNKNOWN, W_UNKNOWN, W_UNKNOWN),
            () if m.return_inert else ("unknown",))

    params = [PLAIN for _ in m.params]
    receiver = [PLAIN] if m.receiver else []
    writes = [W_NONE, W_NONE, W_NONE]
    returns: set[str] = set()

    def roots(tokens: Iterable[str]) -> set[str]:
        """The roots a value may be: param:<i>, receiver, heap, unknown."""
        out: set[str] = set()
        stack = list(tokens)
        seen: set[str] = set()
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t)
            if t in ("receiver", "heap", "unknown") or t.startswith("param:"):
                out.add(t)
            elif t.startswith("local:"):
                stack.extend(m.locals[int(t[6:])])
            else:  # call:<k>
                c = m.calls[int(t[5:])]
                if _callee_unknown(c, methods):
                    out.add("unknown")
                    continue
                for r in solved[c.callee].returns:
                    if r.startswith("param:"):
                        stack.extend(c.args[int(r[6:])])
                    elif r == "receiver":
                        # a constructor's receiver is the new object: heap to the caller
                        stack.extend(c.receiver if c.receiver is not None else ("heap",))
                    else:
                        out.add(r)
        return out

    def apply(tokens: Iterable[str], effect: int, kind: int) -> None:
        for r in roots(tokens):
            if r.startswith("param:"):
                i = int(r[6:])
                if not m.params[i][1]:
                    params[i] = max(params[i], effect)
            elif r == "receiver":
                receiver[0] = max(receiver[0], effect)
            elif effect >= BORROW_MUT:
                # an object reached from neither a parameter nor the receiver
                level = W_UNKNOWN if (r == "unknown" or effect == UNKNOWN) else W_MAY
                writes[kind] = max(writes[kind], level)

    apply(m.derefs, BORROW, 0)
    for kind, target in m.writes:
        if kind == "static":
            writes[1] = max(writes[1], W_MAY)
        else:
            apply(target, BORROW_MUT, WRITE_KINDS.index(kind))
    apply(m.stores, MAY_ESCAPE, 0)
    for c in m.calls:
        if _callee_unknown(c, methods):
            for arg in c.args:
                apply(arg, UNKNOWN, 0)
            if c.receiver is not None:
                apply(c.receiver, UNKNOWN, 0)
            writes = [W_UNKNOWN, W_UNKNOWN, W_UNKNOWN]
            continue
        s = solved[c.callee]
        for j, effect in enumerate(s.params):
            apply(c.args[j], effect, 0)
        if s.receiver is not None and c.receiver is not None:
            apply(c.receiver, s.receiver, 0)
        writes = [max(a, b) for a, b in zip(writes, s.writes, strict=True)]
    if not m.return_inert:
        for r in roots(m.returns):
            if r.startswith("param:") and m.params[int(r[6:])][1]:
                continue
            returns.add(r)

    return Summary(
        tuple(params), receiver[0] if m.receiver else None,
        (writes[0], writes[1], writes[2]),
        ("unknown",) if "unknown" in returns else tuple(sorted(returns)))


def _sccs(keys: list[str], edges: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan, iterative, bottom-up (every component before its callers)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in keys:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, pos = work.pop()
            if pos == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            succ = edges[v]
            if pos < len(succ):
                work.append((v, pos + 1))
                w = succ[pos]
                if w not in index:
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            if low[v] == index[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return out


def solve(methods: list[Method]) -> dict[str, Summary]:
    by_key = {m.key: m for m in methods}
    keys = sorted(by_key)
    edges = {k: sorted({c.callee for c in by_key[k].calls
                        if not _callee_unknown(c, by_key)}) for k in keys}
    solved = {k: _bottom(by_key[k]) for k in keys}
    for comp in _sccs(keys, edges):
        changed = True
        while changed:
            changed = False
            for k in comp:
                new = _evaluate(by_key[k], by_key, solved)
                if new != solved[k]:
                    solved[k] = new
                    changed = True
    return solved


# --- H1: the harmless predicate (docs/notes/h1-proven-call.md) ----------------
#
# The ONE consumer of the solved summaries that decides anything: OwnIR v2's
# `proven_call` (ownir.py `_admit_proven_calls`, own-bridge `proven.rs`) admits a
# call inside an exclusive region only when these two functions say so. Strict on
# purpose — a reference returned without an alias is still refused (`returns` must
# be empty), and Unknown fails every clause it touches.


def harmless(s: Summary) -> str | None:
    """None when the summary proves the method harmless; otherwise the FIRST failing
    clause, in a fixed order (parameters, receiver, writes, returns)."""
    for i, effect in enumerate(s.params):
        if effect > BORROW:
            return f"parameter {i} is {EFFECTS[effect]}"
    if s.receiver is not None and s.receiver > BORROW:
        return f"receiver is {EFFECTS[s.receiver]}"
    for i, kind in enumerate(WRITE_KINDS):
        if s.writes[i] != W_NONE:
            return f"writes.{kind} is {WRITES[s.writes[i]]}"
    if s.returns:
        return f"returns alias {', '.join(s.returns)}"
    return None


def site_verdict(methods: dict[str, Method], solved: dict[str, Summary],
                 site: str, callee: str) -> str | None:
    """None when the call site `site` (a record the frontend wrote for one call
    expression) is proven harmless; otherwise why not. Every call in the site must be
    a `direct` call to a summarized, harmless method, the site must contain a direct
    call to `callee`, and the site's own solved summary must be harmless too."""
    m = methods[site]
    if not any(c.callee == callee and c.dispatch == "direct" for c in m.calls):
        return f"the site does not call '{callee}' directly"
    for c in m.calls:
        if c.dispatch != "direct":
            return f"'{c.callee}' is {c.dispatch}"
        if c.callee not in methods:
            return f"'{c.callee}' has no summary"
        reason = harmless(solved[c.callee])
        if reason is not None:
            return f"'{c.callee}': {reason}"
    reason = harmless(solved[site])
    if reason is not None:
        return f"the call site: {reason}"
    return None


def _unresolved(m: Method, methods: dict[str, Method]) -> list[str]:
    reasons = set(m.unknown)
    for c in m.calls:
        if c.dispatch != "direct":
            reasons.add(f"{c.callee} ({c.dispatch})")
        elif c.callee not in methods:
            reasons.add(f"{c.callee} (no summary)")
    return sorted(reasons)


def dump(doc: object) -> dict[str, Any]:
    """The solved document (raises HeapEffectsError on a sidecar that fails `load`)."""
    methods = load(doc)
    by_key = {m.key: m for m in methods}
    solved = solve(methods)
    summaries = []
    for key in sorted(by_key):
        m, s = by_key[key], solved[key]
        summaries.append({
            "method": key,
            "file": m.file,
            "line": m.line,
            "params": [{"index": i, "name": name, "effect": EFFECTS[s.params[i]]}
                       for i, (name, _) in enumerate(m.params)],
            "receiver": None if s.receiver is None else EFFECTS[s.receiver],
            "writes": {kind: WRITES[s.writes[i]] for i, kind in enumerate(WRITE_KINDS)},
            "returns": list(s.returns),
            "unresolved": _unresolved(m, by_key),
        })
    return {"heap_effects_version": HEAP_EFFECTS_VERSION, "summaries": summaries}


def _reject_constant(_: str) -> object:
    raise ValueError("not RFC 8259")


def _strict_float(text: str) -> float:
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError("out of range")
    return value


def render(text: str) -> str:
    """Sidecar JSON text -> the dump bytes (`json.dumps(indent=2, sort_keys=True)` + newline).

    The JSON reader is held to RFC 8259 — no NaN/Infinity, no overflowing number, no lone
    surrogate — the input both engines accept identically."""
    try:
        doc = json.loads(text, parse_constant=_reject_constant, parse_float=_strict_float)
        json.dumps(doc, ensure_ascii=False).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        raise HeapEffectsError("heap-effect facts: not valid JSON") from None
    return json.dumps(dump(doc), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m ownlang.heap_effects <heap-effects.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HeapEffectsError("heap-effect facts: not valid JSON") from None
        sys.stdout.write(render(text))
    except (OSError, HeapEffectsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
