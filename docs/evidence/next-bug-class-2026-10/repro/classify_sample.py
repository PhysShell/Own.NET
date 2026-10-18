#!/usr/bin/env python3
"""Crude classification of `ref x = ref CollectionsMarshal.GetValueRefOrAddDefault(D, ...)` sites.

Usage: python classify_sample.py <sample-dir>   (sample-dir holds index.tsv and N.cs from sample.sh)

What runs between taking the ref and the last textual use of the ref local in the same block?
  NONE      no invocation in between
  DELEGATE  a delegate/factory-looking call (Invoke, *Factory/*Creator/*Callback/...)
  SELF      a call on the same dictionary, on `this`, or an unqualified PascalCase call
            (this bucket also catches constructors: it is deliberately over-inclusive)
  CALL      other invocations only
Textual and single-method; the suspicious sites were then reviewed by hand (see REPORT.md).
"""

from __future__ import annotations

import collections
import os
import re
import sys

SITE = re.compile(
    r"ref\s+(?:var|[\w<>?,\s\[\]]+?)\s+(\w+)\s*=\s*ref\s+"
    r"CollectionsMarshal\.GetValueRefOrAddDefault\s*\(\s*([\w.]+)")
CALL = re.compile(r"([\w.]+)\s*(?:<[^<>()]*>)?\s*\(")
KEYWORDS = {"if", "while", "for", "foreach", "switch", "return", "nameof", "typeof", "sizeof",
            "default", "new", "using", "lock", "catch", "when", "out", "ref", "Unsafe.IsNullRef"}
DELEGATE_NAME = re.compile(r"(?i)factory|creator|callback|func|action|selector|create$")


def block_after(text: str, idx: int) -> str:
    depth = 0
    for i in range(idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            if depth == 0:
                return text[idx:i]
            depth -= 1
    return text[idx:]


def classify(calls: list[str], dic: str) -> str:
    if not calls:
        return "NONE"
    if any(c.endswith("Invoke") or DELEGATE_NAME.search(c.split(".")[-1]) for c in calls):
        return "DELEGATE"
    if any(c.startswith((dic + ".", "this.")) or ("." not in c and c[0].isupper()) for c in calls):
        return "SELF"
    return "CALL"


def main() -> int:
    sample = sys.argv[1] if len(sys.argv) > 1 else "sample"
    with open(os.path.join(sample, "index.tsv"), encoding="utf-8") as f:
        index = [line.rstrip("\n").split("\t") for line in f]
    rows = []
    for n, (repo, path, _sha) in enumerate(index, 1):
        src = os.path.join(sample, f"{n}.cs")
        if not os.path.exists(src):
            continue
        with open(src, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for m in SITE.finditer(text):
            var, dic = m.group(1), m.group(2)
            rest = block_after(text, m.end())
            uses = [u.start() for u in re.finditer(r"\b" + re.escape(var) + r"\b", rest)]
            span = rest[: uses[-1]] if uses else ""
            span = span[span.find(";") + 1:] if ";" in span else span
            calls = [c for c in CALL.findall(span)
                     if c not in KEYWORDS and c.split(".")[-1] not in KEYWORDS]
            line = text[: m.start()].count("\n") + 1
            rows.append((repo, path, line, var, classify(calls, dic), sorted(set(calls))[:6]))
    kinds = collections.Counter(r[4] for r in rows)
    print("sites", len(rows), "repos", len({r[0] for r in rows}), dict(kinds))
    for r in rows:
        if r[4] != "NONE":
            print("\t".join(map(str, r)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
