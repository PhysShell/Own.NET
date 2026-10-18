#!/usr/bin/env python3
"""Triage bug-fix pairs for the three candidate mechanisms (source level, no build).

Usage: python triage_pairs.py <pairs-dir>   (one directory per pair: pair.meta.json, base/, fix/)

For every changed .cs file of every pair: locals that GAIN a release in the fix revision
(`using var x`, `using (x`, `using (var x`, `x.Dispose()`, `x?.Dispose()`), then the same local in
the BASE revision's enclosing method is classified:
  B  referenced lexically inside a lambda / local function / anonymous method
  A  passed as an argument to a method declared in the pair's own source (first-party)
  O  passed to some other call
  -  none of these
Any changed file mentioning CollectionsMarshal is flagged C.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

REL = re.compile(
    r"using\s*\(\s*(?:var\s+)?(\w+)\b|using\s+var\s+(\w+)\b|\b(\w+)\s*\??\.\s*Dispose(?:Async)?\s*\(")
METHOD_DECL = re.compile(
    r"\b(?:public|private|protected|internal|static)[\w\s<>\[\],?]*\s(\w+)\s*\([^;{]*\)"
    r"\s*(?:where[^{]*)?\{")
LAMBDA = re.compile(
    r"=>\s*\{(?:[^{}]|\{[^{}]*\})*\}|=>[^;\n]*;"
    r"|delegate\s*\([^)]*\)\s*\{(?:[^{}]|\{[^{}]*\})*\}")


def released(text: str) -> set[str]:
    return {next(g for g in m.groups() if g) for m in REL.finditer(text)}


def first_party_methods(root: str) -> set[str]:
    names: set[str] = set()
    for f in glob.glob(os.path.join(root, "**", "*.cs"), recursive=True):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                names |= set(METHOD_DECL.findall(fh.read()))
        except OSError:  # e.g. a path past the Windows MAX_PATH limit: skipped, as originally
            pass
    return names


def enclosing_method(text: str, idx: int) -> str:
    start = max((m.start() for m in METHOD_DECL.finditer(text) if m.start() < idx), default=0)
    depth, opened = 0, False
    i = text.find("{", start)
    while 0 <= i < len(text):
        if text[i] == "{":
            depth += 1
            opened = True
        elif text[i] == "}":
            depth -= 1
            if opened and depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def classify(base_text: str, name: str, fp: set[str]) -> str | None:
    decl = re.search(r"(?:var|[\w<>\[\]?.]+)\s+" + re.escape(name) + r"\s*=\s*(new\b|[\w.]+\s*\()",
                     base_text)
    if not decl:
        return None
    body = enclosing_method(base_text, decl.start())
    word = re.compile(r"\b" + re.escape(name) + r"\b")
    kinds = {"B"} if any(word.search(m.group(0)) for m in LAMBDA.finditer(body)) else set()
    arg = re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w.(])")
    for call in re.finditer(r"\b(\w+)\s*\(([^()]*\b" + re.escape(name) + r"\b[^()]*)\)", body):
        callee, args = call.group(1), call.group(2)
        if callee in ("using", "if", "while", "Dispose", "nameof") or not arg.search(args):
            continue
        kinds.add("A" if callee in fp else "O")
    return "".join(sorted(kinds)) or "-"


def main() -> int:
    pairs = sys.argv[1] if len(sys.argv) > 1 else "pairs"
    rows = []
    for meta_f in sorted(glob.glob(os.path.join(pairs, "*", "pair.meta.json"))):
        pair = os.path.dirname(meta_f)
        with open(meta_f, encoding="utf-8") as f:
            meta = json.load(f)
        fp: set[str] | None = None
        for rel in meta.get("changed_files", []):
            if not rel.endswith(".cs"):
                continue
            texts = []
            for side in ("base", "fix"):
                p = os.path.join(pair, side, rel)
                if os.path.exists(p):
                    with open(p, encoding="utf-8", errors="replace") as f:
                        texts.append(f.read())
                else:
                    texts.append("")
            bt, ft = texts
            if "CollectionsMarshal" in bt + ft:
                rows.append((os.path.basename(pair), rel, "CollectionsMarshal", "C"))
            for name in sorted(released(ft) - released(bt)):
                if fp is None:
                    fp = first_party_methods(os.path.join(pair, "base"))
                k = classify(bt, name, fp)
                if k is not None:
                    rows.append((os.path.basename(pair), rel, name, k))
    for r in rows:
        print("\t".join(r))
    print(f"# {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
