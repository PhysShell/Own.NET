#!/usr/bin/env python3
"""#382 gates A1-A3: what the frontend loses, and what the core does with a hand-made `call`.

Research probe, not an implementation. Everything is written to a temporary directory; the
checkout is not modified. The `call` ops are edited into the extracted facts by hand.

Usage (from the repository root):
    python docs/evidence/next-bug-class-2026-10/repro/a_382_probe.py [--rust path/to/own-cli]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 4))
EXT = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")
SAMPLE = os.path.join(ROOT, "frontend", "roslyn", "samples", "GuardedConsumeSample.cs")

CALLERS = """
    public static void CallerUsesAfterForward()
    {
        var x = new MemoryStream();
        ForwardDynamic(x, true);
        x.WriteByte(1);
    }
    public static void CallerLeaksAfterBorrow()
    {
        var y = new MemoryStream();
        ForwardDynamic(y, false);
        y.WriteByte(1);
    }
}
"""

CHAIN = """using System.IO;

namespace Repro;

public static class Chain
{
    public static void Close1(Stream s) { s.Dispose(); }
    public static void Close2(Stream s) { Close1(s); }
    public static void UseAfterTwoLevels()
        { var b = new MemoryStream(); Close2(b); b.WriteByte(1); }
    public static void Borrow(Stream s) { s.WriteByte(0); }
    public static void Borrow2(Stream s) { Borrow(s); }
    public static void LeakThroughBorrow2() { var d = new MemoryStream(); Borrow2(d); }
}
"""


def sh(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=ROOT)
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, **kw)  # type: ignore[call-overload]


def extract(src: str, out: str) -> dict:
    r = sh(["dotnet", "run", "--project", EXT, "--", src, "-o", out, "--flow-locals"])
    if r.returncode != 0:
        sys.exit(f"extractor failed: {r.stderr[-400:]}")
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def cores(path: str, rust: str | None) -> None:
    py = sh([sys.executable, "-m", "ownlang", "ownir", path, "--severity", "warning"])
    lines = [ln.split(": ", 1)[-1] for ln in py.stdout.splitlines() if "warning:" in ln]
    print("  python:", *lines, sep="\n    ")
    if rust:
        rs = sh([rust, "ownir", path, "--severity", "warning"])
        print("  rust:  ", *[ln.split(": ", 1)[-1] for ln in rs.stdout.splitlines()
                             if "warning:" in ln], sep="\n    ")


def summaries(path: str, names: tuple[str, ...]) -> None:
    out = json.loads(sh([sys.executable, "-m", "ownlang", "summaries", path]).stdout)
    for s in out["summaries"]:
        if s["method"].endswith(names):
            print("  summary", s["method"].split(".")[-1],
                  [(p["name"], p["transfer"]) for p in s["params"]])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rust", help="own-cli binary for the Rust door (optional)")
    rust = ap.parse_args().rust
    work = tempfile.mkdtemp(prefix="nbc-a-")

    a = os.path.join(work, "a")
    os.makedirs(a)
    with open(SAMPLE, encoding="utf-8") as f:
        text = f.read().rstrip().rstrip("}")
    with open(os.path.join(a, "GuardedConsumeSample.cs"), "w", encoding="utf-8") as f:
        f.write(text + CALLERS)
    facts = extract(a, os.path.join(work, "a.json"))
    fd = next(f for f in facts["functions"] if f["name"].endswith("ForwardDynamic"))
    print("A1 ForwardDynamic body on main:", json.dumps(fd["body"]))
    callers = [f["name"] for f in facts["functions"] if "Caller" in f["name"]]
    print("A1 caller records emitted:", callers)
    summaries(os.path.join(work, "a.json"), ("ForwardDynamic", "MaybeClose", "BorrowingWrapper"))

    fd["body"] = [{"op": "call", "callee": "GuardedConsumeSample.MaybeClose",
                   "sig": "System.IO.Stream,System.Boolean", "args": ["forwarded"],
                   "line": fd["body"][0]["line"]}]
    for name, var in (("CallerUsesAfterForward", "x"), ("CallerLeaksAfterBorrow", "y")):
        facts["functions"].append({
            "name": "GuardedConsumeSample." + name, "file": fd["file"], "sig": "", "params": [],
            "body": [{"op": "acquire", "var": var, "line": 1, "column": 1, "kind": "disposable"},
                     {"op": "call", "callee": "GuardedConsumeSample.ForwardDynamic",
                      "sig": "System.IO.Stream,System.Boolean", "args": [var], "line": 2},
                     {"op": "use", "var": var, "line": 3}]})
    edited = os.path.join(work, "a.call.json")
    with open(edited, "w", encoding="utf-8") as f:
        json.dump(facts, f)
    print("A2 with a hand-made call:")
    summaries(edited, ("ForwardDynamic", "MaybeClose", "BorrowingWrapper"))
    print("A3 caller diagnostics with the call (both callers):")
    cores(edited, rust)

    b = os.path.join(work, "b")
    os.makedirs(b)
    with open(os.path.join(b, "Chain.cs"), "w", encoding="utf-8") as f:
        f.write(CHAIN)
    chain = extract(b, os.path.join(work, "b.json"))
    print("A3 multi-level definite forward and borrow leak on main:")
    cores(os.path.join(work, "b.json"), rust)
    for f in chain["functions"]:
        if f["name"].endswith("Borrow2"):
            f["body"] = [{"op": "call", "callee": "Repro.Chain.Borrow", "sig": "System.IO.Stream",
                          "args": ["s"], "line": f["body"][0]["line"]}]
    chain["functions"].append({
        "name": "Repro.Chain.LeakThroughBorrow2", "file": chain["functions"][0]["file"], "sig": "",
        "params": [],
        "body": [{"op": "acquire", "var": "d", "line": 12, "column": 1, "kind": "disposable"},
                 {"op": "call", "callee": "Repro.Chain.Borrow2", "sig": "System.IO.Stream",
                  "args": ["d"], "line": 12}]})
    edited_b = os.path.join(work, "b.call.json")
    with open(edited_b, "w", encoding="utf-8") as f:
        json.dump(chain, f)
    print("A3 borrow leak with a hand-made call:")
    cores(edited_b, rust)
    print(f"(work dir: {work})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
