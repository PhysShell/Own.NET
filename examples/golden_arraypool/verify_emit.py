#!/usr/bin/env python3
"""
CI guard for the runnable golden.

`Program.cs` pastes the `process` method verbatim from `ownlang emit
buffer.own` and wraps it in host code (Main + Fill/Hash stubs). This checks the
pasted method is still exactly what the generator produces, so the runnable
example can't drift from the checker's output before the .NET job compiles it.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from ownlang.parser import parse        # noqa: E402
from ownlang.codegen import generate     # noqa: E402


def _method_lines(text: str) -> list[str]:
    """The `process(...)` method, as a list of whitespace-stripped lines."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if "static void process(" in l)
    out: list[str] = []
    depth = 0
    seen_brace = False
    for l in lines[start:]:
        out.append(l.strip())
        depth += l.count("{") - l.count("}")
        if "{" in l:
            seen_brace = True
        if seen_brace and depth == 0:
            break
    return [x for x in out if x]


def main() -> int:
    emitted = generate(parse(open(os.path.join(_HERE, "buffer.own"),
                                   encoding="utf-8").read()))
    program = open(os.path.join(_HERE, "Program.cs"), encoding="utf-8").read()
    want = _method_lines(emitted)
    have = [l.strip() for l in program.splitlines() if l.strip()]
    # `want` must appear as a contiguous run inside Program.cs.
    n = len(want)
    ok = any(have[i:i + n] == want for i in range(len(have) - n + 1))
    if not ok:
        print("Program.cs is out of sync with `ownlang emit buffer.own`.")
        print("--- emitted process method ---")
        print("\n".join(want))
        return 1
    print(f"golden in sync: process() ({n} lines) matches `ownlang emit`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
