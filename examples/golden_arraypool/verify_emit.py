#!/usr/bin/env python3
"""
CI guard for the runnable golden.

`Program.cs` pastes the `process` method verbatim from `ownlang emit
buffer.own` and wraps it in host code (Main + Fill/Hash stubs). This checks the
pasted method is still **byte-for-byte** what the generator produces, so the
runnable example can't drift from the checker's output before the .NET job
compiles it.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from ownlang.parser import parse        # noqa: E402
from ownlang.codegen import generate     # noqa: E402


def _method_lines(text: str) -> list[str]:
    """The `process(...)` method, preserving each line's exact text."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if "static void process(" in line)
    out: list[str] = []
    depth = 0
    seen_brace = False
    for line in lines[start:]:
        out.append(line)
        depth += line.count("{") - line.count("}")
        if "{" in line:
            seen_brace = True
        if seen_brace and depth == 0:
            break
    return out


def main() -> int:
    """Fail (1) if Program.cs's process() no longer matches `ownlang emit`."""
    with open(os.path.join(_HERE, "buffer.own"), encoding="utf-8") as f:
        emitted = generate(parse(f.read()))
    with open(os.path.join(_HERE, "Program.cs"), encoding="utf-8") as f:
        program = f.read()
    want = _method_lines(emitted)
    have = program.splitlines()
    # `want` must appear as a contiguous, byte-for-byte run inside Program.cs.
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
