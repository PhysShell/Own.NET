#!/usr/bin/env python3
"""Own.NET#408 - two locals with one name in sibling scopes must not be conflated.

THE DEFECT

The `--flow-locals` pass tracks locals by NAME. C# lets two DIFFERENT locals share a name when their
scopes are disjoint (two branches, two blocks, a branch and a loop). When only one of them is a
tracked disposable/pooled local, every reference to the other one was still emitted as an op on
the tracked name:
  * in a sibling branch: a `use` with no `acquire` on that path - the core aborted the WHOLE
    document (internal OWN030 "undefined name", exit 2; mined on MessagePack-CSharp
    ToLZ4BinaryCore);
  * in a later block: a `use` after the first local's `release` - a false OWN002 use-after-return.

WHAT THIS TEST PINS (each a separate PASS/KILL criterion of the fix)

  C1  sibling branches (the MessagePack shape): the core accepts the document, and a leak in another
      method of the same file is still reported - one method never costs the file its analysis.
  C2  sequential blocks: no OWN002 for the second, unpooled local.
  C3  a foreach iteration variable and an `out var` sharing the tracked name: no crash, no OWN002.
  C4  both same-named locals tracked: the never-disposed one still leaks (OWN001 at its line).
  C5  control: a real use-after-return of ONE local in ONE scope still reports OWN002.
  C6  the untracked local declared directly in a `try` block (lowered as a statement list).

REQUIRED VS SKIPPED: as tests/test_extractor_columns.py - required when OWN_TIERB_REQUIRED=1,
a clean, explained skip when dotnet is absent.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_extractor_sibling_locals.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")

_SOURCE = """using System;
using System.Buffers;
using System.Collections.Generic;
using System.IO;

namespace Repro;

public static class SiblingLocals
{
    // C1: MessagePack-CSharp ToLZ4BinaryCore shape
    public static void Branches(bool pooled, int n)
    {
        if (pooled)
        {
            var buf = ArrayPool<byte>.Shared.Rent(n);
            try { buf[0] = 1; }
            finally { ArrayPool<byte>.Shared.Return(buf); }
        }
        else
        {
            foreach (var i in new[] { 1, 2 })
            {
                var buf = new byte[n];
                buf.AsSpan(0, 1).Clear();
            }
        }
    }

    // C2
    public static void Sequential(int n)
    {
        {
            var seq = ArrayPool<byte>.Shared.Rent(n);
            try { seq[0] = 1; }
            finally { ArrayPool<byte>.Shared.Return(seq); }
        }
        {
            var seq = new byte[n];
            seq[0] = 2;
        }
    }

    // C3
    public static void LoopAndOut(bool a, int n, List<byte[]> items, string text)
    {
        if (a)
        {
            var it = ArrayPool<byte>.Shared.Rent(n);
            try { it[0] = 1; }
            finally { ArrayPool<byte>.Shared.Return(it); }
        }
        else if (n > 0)
        {
            foreach (var it in items)
                it[0] = 3;
        }
        else
        {
            if (int.TryParse(text, out var it))
                Console.WriteLine(it);
        }
    }

    // C4
    public static void BothTracked(bool a)
    {
        if (a)
        {
            var both = new MemoryStream();
            both.WriteByte(1);
            both.Dispose();
        }
        else
        {
            var both = new MemoryStream();
            both.WriteByte(2);
        }
    }

    // C5
    public static void RealUseAfterReturn(int n)
    {
        var real = ArrayPool<byte>.Shared.Rent(n);
        ArrayPool<byte>.Shared.Return(real);
        real[0] = 1;
    }

    // C6: the untracked local is declared directly in a `try` block (lowered as a statement list)
    public static void TryBlock(bool pooled, int n)
    {
        if (pooled)
        {
            var tb = ArrayPool<byte>.Shared.Rent(n);
            try { tb[0] = 1; }
            finally { ArrayPool<byte>.Shared.Return(tb); }
        }
        else
        {
            try
            {
                var tb = new byte[n];
                tb[0] = 2;
            }
            finally { Console.WriteLine(); }
        }
    }

    // C1: a sibling method with a plain leak
    public static void Leaky()
    {
        var leaked = new MemoryStream();
        leaked.WriteByte(1);
    }
}
"""


def _line_of(marker: str) -> int:
    for i, line in enumerate(_SOURCE.splitlines(), 1):
        if marker in line:
            return i
    raise AssertionError(marker)


def run() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if not shutil.which("dotnet"):
        if os.environ.get("OWN_TIERB_REQUIRED") == "1":
            print("extractor sibling locals: FAIL - dotnet is REQUIRED here "
                  "(OWN_TIERB_REQUIRED=1) and is not on PATH")
            return 1
        print("extractor sibling locals: SKIP - dotnet not on PATH")
        return 0
    fails: list[str] = []
    work = tempfile.mkdtemp(prefix="own408-")
    try:
        src = os.path.join(work, "src")
        os.makedirs(src)
        with open(os.path.join(src, "Repro.cs"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_SOURCE)
        facts = os.path.join(work, "facts.json")
        ext = subprocess.run(
            ["dotnet", "run", "--project", _EXT, "--", src, "-o", facts, "--flow-locals"],
            cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if ext.returncode != 0 or not os.path.exists(facts):
            tail = " | ".join((ext.stderr or ext.stdout).strip().splitlines()[-3:])
            print(f"extractor sibling locals: FAIL - extractor rc={ext.returncode} ({tail})")
            return 1
        env = dict(os.environ, PYTHONPATH=_REPO)
        core = subprocess.run(
            [sys.executable, "-m", "ownlang", "ownir", facts,
             "--format", "sarif", "--severity", "warning"],
            cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            results = json.loads(core.stdout)["runs"][0]["results"]
        except (ValueError, KeyError, IndexError):
            tail = (core.stderr or core.stdout).strip()[-240:]
            print(f"extractor sibling locals: FAIL - C1 the core rejected the document "
                  f"(rc={core.returncode}): {tail}")
            return 1
        found = [(r.get("ruleId"), r["locations"][0]["physicalLocation"]["region"]["startLine"],
                  r["message"]["text"]) for r in results]

        def has(rule: str, line: int, local: str) -> bool:
            return any(r == rule and ln == line and f"'{local}'" in t for r, ln, t in found)

        def any_on(local: str, rule: str) -> bool:
            return any(r == rule and f"'{local}'" in t for r, _, t in found)

        if not has("OWN001", _line_of("var leaked ="), "leaked"):
            fails.append("C1 the sibling leak in Leaky() is not reported")
        if any_on("buf", "OWN002") or any_on("buf", "OWN001"):
            fails.append("C1 a finding on 'buf' in Branches(): " + repr(
                [x for x in found if "'buf'" in x[2]]))
        if any_on("seq", "OWN002"):
            fails.append("C2 false OWN002 on 'seq': the unpooled second local was conflated")
        if any("'it'" in t for _, _, t in found):
            fails.append("C3 a finding on 'it': " + repr([x for x in found if "'it'" in x[2]]))
        if not has("OWN001", _second_line("var both = new MemoryStream();"), "both"):
            fails.append("C4 the never-disposed second 'both' no longer leaks: " + repr(
                [x for x in found if "'both'" in x[2]]))
        if any("'tb'" in t for _, _, t in found):
            fails.append("C6 a finding on 'tb': " + repr([x for x in found if "'tb'" in x[2]]))
        if not any_on("real", "OWN002"):
            fails.append("C5 the real use-after-return on 'real' is no longer reported")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        print("extractor sibling locals: FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("extractor sibling locals: OK (6 criteria)")
    return 0


def _second_line(marker: str) -> int:
    hits = [i for i, line in enumerate(_SOURCE.splitlines(), 1) if marker in line]
    return hits[1]


if __name__ == "__main__":
    raise SystemExit(run())
