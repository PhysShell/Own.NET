#!/usr/bin/env python3
"""Own.NET#401 - a deep `if / else if` chain must not take the whole run down.

THE DEFECT

The flow pass lowers every `if` to `{op:"if", then:[...], else:[...]}`, so each `else if`
nests two JSON levels (an object and an array). The facts document was serialised with
System.Text.Json's default MaxDepth of 64, so ONE method with a tracked disposable local and
31 conditions threw `JsonException` at the final serialise: no facts, no SARIF, every other
method in the repository unanalysed (couchbase-net-client, dnSpy).

WHAT THIS TEST PINS (each a separate PASS/KILL criterion of the fix)

  P1  n <= 32 conditions (flow nesting <= 32, the spec/OwnIR.md §4.2 limit): the extractor
      exits 0, the method IS flow-analysed, its body nests exactly n levels, and the core
      accepts the document. A fix that dodges the crash by skipping these methods fails here
      (it would lose coverage the spec allows).
  P2  n >= 33 (deeper than the spec admits): the extractor exits 0, the method is honestly
      skipped and counted in `methods_skipped_unmodelled`, and the core still accepts the
      document - so the crash is not merely moved from the extractor to the core.
  P3  In every case a sibling method with a real undisposed local is still reported, i.e.
      one deep method never costs the rest of the file its analysis.
  P4  n = 1000: the lowering recursion itself used to overflow the stack (an uncatchable
      crash, the whole run lost) somewhere between 300 and 600 conditions; it must bail the
      method as unmodelled instead (P2 and P3 apply).

The boundary n = 32 / 33 is the spec's, not a tuning knob: `then`/`else` bodies are levels,
the top-level body is level 0, so the k-th condition's `then` sits at level k+1 and a chain
of n conditions nests exactly n.

REQUIRED VS SKIPPED: as tests/test_extractor_columns.py - required when OWN_TIERB_REQUIRED=1
(the wpf-extractor CI job), a clean, explained skip when dotnet is absent.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_extractor_deep_flow.py
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
_LIMIT = 32  # spec/OwnIR.md §4.2: a body nesting exactly 32 is accepted, 33 rejected
_CASES = (31, 32, 33, 200, 1000)


def _source(n: int) -> str:
    lines = [
        "using System.IO;",
        "",
        "namespace Repro;",
        "",
        "public static class Chain",
        "{",
        "    public static int Classify(int x)",
        "    {",
        "        var ms = new MemoryStream();",
        "        int r;",
    ]
    for i in range(n):
        kw = "if" if i == 0 else "else if"
        lines.append(f"        {kw} (x == {i}) {{ r = {i}; }}")
    lines += [
        "        else { r = -1; }",
        "        ms.Dispose();",
        "        return r;",
        "    }",
        "",
        "    public static void Leaky()",
        "    {",
        "        var leaked = new MemoryStream();",
        "        leaked.WriteByte(1);",
        "    }",
        "}",
        "",
    ]
    return "\n".join(lines)


def _depth(nodes: object, level: int = 0) -> int:
    """Deepest body level, counted like spec §4.2 / ownir._check_flow_coordinates."""
    if not isinstance(nodes, list):
        return -1
    deepest = level
    for n in nodes:
        if isinstance(n, dict):
            for key in ("then", "else", "body"):
                deepest = max(deepest, _depth(n.get(key), level + 1))
    return deepest


def _run_case(n: int, work: str, fails: list[str]) -> None:
    src = os.path.join(work, f"n{n}")
    os.makedirs(src)
    with open(os.path.join(src, "Chain.cs"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_source(n))
    facts_path = os.path.join(work, f"n{n}.facts.json")
    ext = subprocess.run(
        ["dotnet", "run", "--project", _EXT, "--",
         src, "-o", facts_path, "--flow-locals", "--stats"],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tag = f"n={n}"
    if ext.returncode != 0 or not os.path.exists(facts_path):
        tail = (ext.stderr or ext.stdout).strip().splitlines()[-3:]
        joined = " | ".join(tail)
        fails.append(f"{tag}: extractor rc={ext.returncode}, no facts ({joined})")
        return
    with open(facts_path, encoding="utf-8") as f:
        facts = json.load(f)
    fns = {fn.get("name"): fn for fn in facts.get("functions", [])}
    chain = fns.get("Repro.Chain.Classify")
    skipped = (facts.get("stats") or {}).get("methods_skipped_unmodelled")
    if n <= _LIMIT:
        if chain is None:
            fails.append(f"{tag}: P1 Classify was not flow-analysed "
                         "(coverage the spec allows was lost)")
        elif _depth(chain.get("body")) != n:
            got = _depth(chain.get("body"))
            fails.append(f"{tag}: P1 Classify nests {got} levels, expected {n}")
    else:
        if chain is not None:
            got = _depth(chain.get("body"))
            fails.append(f"{tag}: P2 Classify nests {got} > {_LIMIT} but was emitted")
        if not isinstance(skipped, int) or skipped < 1:
            fails.append(f"{tag}: P2 the skip is not counted "
                         f"(methods_skipped_unmodelled={skipped!r})")
    env = dict(os.environ, PYTHONPATH=_REPO)
    core = subprocess.run(
        [sys.executable, "-m", "ownlang", "ownir", facts_path,
         "--format", "sarif", "--severity", "warning"],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    try:
        results = json.loads(core.stdout)["runs"][0]["results"]
    except (ValueError, KeyError, IndexError):
        fails.append(f"{tag}: core rejected the document (rc={core.returncode}): "
                     f"{(core.stderr or core.stdout).strip()[-200:]}")
        return
    if not any("leaked" in r.get("message", {}).get("text", "") for r in results):
        fails.append(f"{tag}: P3 the sibling leak in Leaky() is not reported")


def run() -> int:
    # Failure text can carry U+FFFD from a crashed extractor; never let printing it fail the run.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if not shutil.which("dotnet"):
        if os.environ.get("OWN_TIERB_REQUIRED") == "1":
            print("extractor deep flow: FAIL - dotnet is REQUIRED here "
                  "(OWN_TIERB_REQUIRED=1) and is not on PATH")
            return 1
        print("extractor deep flow: SKIP - dotnet not on PATH")
        return 0
    fails: list[str] = []
    work = tempfile.mkdtemp(prefix="own401-")
    try:
        for n in _CASES:
            _run_case(n, work, fails)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        print("extractor deep flow: FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print(f"extractor deep flow: OK ({len(_CASES)} chain lengths, limit {_LIMIT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
