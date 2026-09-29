#!/usr/bin/env python3
"""P-037-X Stage 7 (research/p037-max-v1, EXPLORATORY; pre-registered in Own.NET-paperwork
paper-eval/p037-max/stage7-cross-language-prereg-v1.json): a TWIN-ONLY OwnIR `functions[]`
emitter for TypeScript — the frozen Group E twins (P-037 §8 rows 1, 7, 8) through the UNCHANGED
core. Heuristic like the OwnTS spike itself (no TypeScript parser); it claims nothing beyond the
shapes named in the pre-registration and is not TypeScript support.

The rules, as frozen (T7-1..T7-6): an interface with `close(): void` / `dispose(): void` is a
resource type; a `declare function` returning one is an ambient factory (`acquire`); `r.close()`
is a `release`; a statement-form call of an in-file function that carries a handle is one
canonical `call` op plus a sidecar call record with raw argument facts by declared ordinal
(var / param / param negated / bool_const / opaque); `if (p)` / `if (!p)` on an own boolean
parameter is a body `if` plus a sidecar guard; `return e;` is a bare return. Owned parameters
carry their declared `ordinal` (R3) — `--no-ordinal` omits it (the X7-C2 control).

Usage::

    python frontend/ownts/ownts_p037x.py e1.ts [-o facts.json] [--no-ordinal]
"""
from __future__ import annotations

import json
import re
import sys

_IFACE = re.compile(r"\binterface\s+(\w+)\s*\{([^}]*)\}")
_AMBIENT = re.compile(r"\bdeclare\s+function\s+(\w+)\s*\(([^)]*)\)\s*:\s*(\w+)\s*;")
_FUNC = re.compile(r"(?:\bexport\s+)?\bfunction\s+(\w+)\s*\(([^)]*)\)\s*:\s*[\w<>\[\]| ]+\s*\{")
_CALL_STMT = re.compile(r"^\s*(\w+)\s*\((.*)\)\s*;\s*$")
_ACQ_STMT = re.compile(r"^\s*(?:const|let)\s+(\w+)\s*=\s*(\w+)\s*\((.*)\)\s*;\s*$")
_REL_STMT = re.compile(r"^\s*(\w+)\s*\.\s*(close|dispose)\s*\(\s*\)\s*;\s*$")
_IF = re.compile(r"^\s*if\s*\((.*)\)\s*\{\s*$")
_RET = re.compile(r"^\s*return\b(.*);\s*$")
_ELSE = re.compile(r"^\s*\}?\s*else\s*\{\s*$")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _col_of(text: str, pos: int) -> int:
    return pos - (text.rfind("\n", 0, pos) + 1) + 1


def _params(sig: str) -> list[tuple[str, str]]:
    out = []
    for piece in [p.strip() for p in sig.split(",") if p.strip()]:
        name, _, ty = piece.partition(":")
        out.append((name.strip(), ty.strip()))
    return out


def _split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        depth += ch in "([{"
        depth -= ch in ")]}"
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _block_end(lines: list[str], start: int) -> int:
    """Index of the line closing the block opened on `lines[start]` (brace counting)."""
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            return i
    return len(lines) - 1


class Emitter:
    def __init__(self, text: str, module: str, file: str, ordinals: bool) -> None:
        self.text = text
        self.module = module
        self.file = file
        self.ordinals = ordinals
        self.resource_types = {m.group(1) for m in _IFACE.finditer(text)
                               if re.search(r"\b(close|dispose)\s*\(\s*\)\s*:\s*void", m.group(2))}
        self.ambient = {m.group(1): m.group(3) for m in _AMBIENT.finditer(text)}
        self.funcs: dict[str, dict] = {}
        for m in _FUNC.finditer(text):
            name, sig = m.group(1), m.group(2)
            self.funcs[name] = {"name": name, "params": _params(sig),
                                "start": m.end(), "line": _line_of(text, m.start())}

    # --- one function -----------------------------------------------------------------------
    def _sig(self, name: str) -> str:
        return ",".join(ty for _, ty in self.funcs[name]["params"])

    def _owned(self, name: str) -> list[int]:
        return [i for i, (_, ty) in enumerate(self.funcs[name]["params"])
                if ty in self.resource_types]

    def _arg_fact(self, arg: str, fn: dict, handles: set[str], ordinal: int) -> tuple[dict, bool]:
        pnames = [n for n, _ in fn["params"]]
        ptypes = dict(fn["params"])
        a = arg.strip()
        if a in ("true", "false"):
            return {"param": ordinal, "kind": "bool_const", "value": a == "true"}, False
        neg = False
        if a.startswith("!"):
            neg, a = True, a[1:].strip()
        if a in pnames:
            if neg and ptypes[a] != "boolean":
                return {"param": ordinal, "kind": "opaque"}, False
            fact = {"param": ordinal, "kind": "param", "source_param": pnames.index(a)}
            if neg:
                fact["negated"] = True
            return fact, ptypes[a] in self.resource_types
        if not neg and a in handles:
            return {"param": ordinal, "kind": "var", "name": a}, True
        return {"param": ordinal, "kind": "opaque"}, False

    def _lower(self, lines: list[str], base_line: int, fn: dict, tracked: set[str],
               nodes: list, calls: list, guards: list) -> None:
        pnames = [n for n, _ in fn["params"]]
        ptypes = dict(fn["params"])
        i = 0
        while i < len(lines):
            ln = lines[i]
            line_no = base_line + i
            if _IF.match(ln):
                cond = _IF.match(ln).group(1).strip()
                end = _block_end(lines, i)
                then_nodes: list = []
                self._lower(lines[i + 1:end], line_no + 1, fn, tracked, then_nodes, calls, guards)
                else_nodes: list = []
                j = end
                has_else = end + 1 < len(lines) and (_ELSE.match(lines[end])
                                                     or _ELSE.match(lines[end + 1]))
                if has_else:
                    else_start = end if _ELSE.match(lines[end]) else end + 1
                    else_end = _block_end(lines, else_start)
                    self._lower(lines[else_start + 1:else_end], base_line + else_start + 1,
                                fn, tracked, else_nodes, calls, guards)
                    j = else_end
                nodes.append({"op": "if", "line": line_no, "then": then_nodes, "else": else_nodes})
                neg = cond.startswith("!")
                name = cond[1:].strip() if neg else cond
                if name in pnames and ptypes[name] == "boolean":
                    col = ln.index("if") + 1
                    guards.append({"site": {"line": line_no, "column": col},
                                   "param": pnames.index(name), "predicate": "truth",
                                   "negated": neg})
                i = j + 1
                continue
            m = _ACQ_STMT.match(ln)
            if (m and m.group(2) in self.ambient
                    and self.ambient[m.group(2)] in self.resource_types):
                tracked.add(m.group(1))
                nodes.append({"op": "acquire", "var": m.group(1), "line": line_no,
                              "column": ln.index(m.group(1)) + 1, "kind": "disposable"})
                i += 1
                continue
            m = _REL_STMT.match(ln)
            if m and (m.group(1) in tracked or m.group(1) in pnames):
                nodes.append({"op": "release", "var": m.group(1), "line": line_no})
                i += 1
                continue
            m = _CALL_STMT.match(ln)
            if m and m.group(1) in self.funcs:
                callee = self.funcs[m.group(1)]
                args = _split_args(m.group(2))
                handles = tracked | {n for n in pnames if ptypes[n] in self.resource_types}
                facts, any_handle = [], False
                for k, a in enumerate(args):
                    fact, is_handle = self._arg_fact(a, fn, handles, k)
                    facts.append(fact)
                    any_handle = any_handle or is_handle
                owned = self._owned(callee["name"])
                slots = [args[k].strip() for k in owned
                         if k < len(args) and args[k].strip() in handles]
                if any_handle and len(slots) == len(owned):
                    key = f"{self.module}.{callee['name']}"
                    nodes.append({"op": "call", "callee": key, "sig": self._sig(callee["name"]),
                                  "args": slots, "line": line_no})
                    calls.append({"site": {"line": line_no, "column": ln.index(m.group(1)) + 1},
                                  "statement_line": line_no, "form": "statement",
                                  "callee": key, "sig": self._sig(callee["name"]),
                                  "first_party": True, "args": facts})
                else:
                    for a in args:
                        if a.strip() in handles:
                            nodes.append({"op": "use", "var": a.strip(), "line": line_no})
                i += 1
                continue
            m = _RET.match(ln)
            if m:
                expr = m.group(1).strip()
                nodes.append({"op": "return", "var": expr if expr in tracked else None,
                              "line": line_no})
                i += 1
                continue
            for name in sorted(tracked | set(pnames)):
                is_handle = name in tracked or ptypes.get(name) in self.resource_types
                if is_handle and re.search(rf"\b{re.escape(name)}\b", ln):
                    nodes.append({"op": "use", "var": name, "line": line_no})
            i += 1

    def function_record(self, name: str) -> dict | None:
        fn = self.funcs[name]
        all_lines = self.text.splitlines()
        start_line = _line_of(self.text, fn["start"])  # the line holding the opening brace
        # the body: from the line after the opening brace to the matching close
        body_lines = all_lines[start_line:]
        depth, end = 1, None
        for i, ln in enumerate(body_lines):
            depth += ln.count("{") - ln.count("}")
            if depth == 0:
                end = i
                break
        if end is None:
            return None
        body = body_lines[:end]
        tracked: set[str] = set()
        nodes: list = []
        calls: list = []
        guards: list = []
        self._lower(body, start_line + 1, fn, tracked, nodes, calls, guards)
        owned = self._owned(name)
        if not owned and not tracked:
            return None
        params = []
        for k in owned:
            p = {"name": fn["params"][k][0], "line": fn["line"]}
            if self.ordinals:
                p["ordinal"] = k
            params.append(p)
        rec: dict = {"name": f"{self.module}.{name}", "file": self.file, "sig": self._sig(name)}
        if params:
            rec["params"] = params
        rec["body"] = nodes
        if calls or guards:
            rec["guarded_facts"] = {"version": 1, "calls": calls, "guards": guards}
        return rec

    def facts(self) -> dict:
        functions = [r for r in (self.function_record(n) for n in self.funcs) if r]
        return {"ownir_version": 0, "module": self.module, "components": [], "functions": functions}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    out = argv[argv.index("-o") + 1] if "-o" in argv else None
    if out in args:
        args.remove(out)
    if not args:
        print("usage: ownts_p037x.py FILE.ts [-o facts.json] [--no-ordinal]", file=sys.stderr)
        return 2
    path = args[0]
    text = open(path, encoding="utf-8").read()
    stripped = re.sub(r"//[^\n]*", "", text)
    module = re.sub(r"\.[jt]sx?$", "", path.rsplit("/", 1)[-1]).replace("-", "_")
    facts = Emitter(stripped, module, path, ordinals="--no-ordinal" not in argv).facts()
    payload = json.dumps(facts, indent=2)
    if out:
        open(out, "w", encoding="utf-8").write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
