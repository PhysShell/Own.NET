"""OX-02 mutation controls M1-M6 (docs/notes/owen-visual-studio-preregistration.md §12).

Each mutation edits ONE product source the way the bug it stands for would, runs the check
that is registered to catch it, and requires that check to go red; the source is restored
whatever happens. A mutation that leaves its check green is a FAIL of this script.

  M1  the client publishes every answer, current or not       -> LiveClientTests K4-stale-dropped
  M2  a service that cannot start is swallowed silently       -> LiveClientTests M2-cannot-start
  M3  the coordinate contract is off by one                   -> LiveClientTests coord-*
  M4  the host routes only Typed Builder's generated sources  -> owen_live_gate K8-two-extensions
  M5  live forms its own severity instead of the core's       -> owen_live_gate P10-parity-*
  M6  the unsaved document is read from disk                  -> owen_live_gate K2 + extractor E4

Run: python scripts/owen_live_mutations.py [--rust-core <own-cli>] [--only M1,M3]
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VS = os.path.join(ROOT, "frontend", "roslyn", "Owen.VisualStudio", "Live")
CLI = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Cli")
EXTRACTOR = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")
TESTS = os.path.join(ROOT, "tests", "owen-live", "LiveClientTests")

MUTATIONS: list[tuple[str, str, str, str, str, list[str]]] = [
    (
        "M1",
        os.path.join(VS, "LiveEngine.cs"),
        "if (!IgnoreVersions && !_gate.IsCurrent(snapshot.Key, response.Version))",
        "if (false && !_gate.IsCurrent(snapshot.Key, response.Version))",
        "client",
        ["K4-stale-dropped"],
    ),
    (
        "M2",
        os.path.join(VS, "LiveEngine.cs"),
        "                if (IgnoreVersions || _gate.IsCurrent(snapshot.Key, version))\n"
        "                    Publish(",
        "                if (false)\n                    Publish(",
        "client",
        ["M2-cannot-start"],
    ),
    (
        "M3",
        os.path.join(VS, "LiveScheduler.cs"),
        "return (start, end, start + 1);",
        "return (start + 1, end, start + 2);",
        "client",
        ["coord-no-column", "coord-column"],
    ),
    (
        "M4",
        os.path.join(CLI, "OwenHost.cs"),
        "descriptors.SelectMany(d => d.Generators)",
        'descriptors.Where(d => d.Id == "Owen.TypedBuilder").SelectMany(d => d.Generators)',
        "gate",
        ["K8-two-extensions"],
    ),
    (
        "M5",
        os.path.join(CLI, "LiveAnalysis.cs"),
        'level == "error" ? "error" : "warning",',
        '"error",',
        "gate",
        ["P10-parity-stale", "P10-parity-copy", "P10-parity-raw"],
    ),
    (
        "M6",
        os.path.join(EXTRACTOR, "InProcess.cs"),
        "if (SourceOverlay is null || !SourceOverlay.TryGetValue(",
        "if (true || !SourceOverlay!.TryGetValue(",
        "gate",
        ["K2-unsaved-own002"],
    ),
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def red(output: str, names: list[str]) -> list[str]:
    return [n for n in names if f"FAIL[{n}]" in output]


def main() -> int:
    argv = sys.argv[1:]
    core = argv[argv.index("--rust-core") + 1] if "--rust-core" in argv else None
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    failures = []
    # the client tests' service half needs a real `owen serve` and a live request; a request
    # with no extension is enough (the service answers OWENB001), so build the host locally
    built = run(["dotnet", "build", CLI, "-nologo", "-v", "q"])
    if built.returncode != 0:
        raise SystemExit(f"FAIL: OwnSharp.Cli does not build: {built.stdout[-800:]}")
    host = os.path.join(CLI, "bin", "Debug", "net8.0", "ownsharp.dll")
    scratch = tempfile.mkdtemp(prefix="owen-live-mutations-")
    request = os.path.join(scratch, "live.txt")
    with open(request, "w", encoding="utf-8") as f:
        f.write(f"project\t{os.path.join(scratch, 'Empty.csproj')}\nhost\t{host}\n")
    for name, path, before, after, where, expect in MUTATIONS:
        if only is not None and name not in only:
            continue
        with open(path, encoding="utf-8") as f:
            original = f.read()
        if original.count(before) != 1:
            failures.append(
                f"{name}: its anchor is not exactly once in {os.path.relpath(path, ROOT)}"
            )
            continue
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(original.replace(before, after))
            if where == "client":
                built = run(["dotnet", "build", TESTS, "-c", "Release", "-nologo", "-v", "q"])
                if built.returncode != 0:
                    failures.append(
                        f"{name}: LiveClientTests no longer builds: {built.stdout[-500:]}"
                    )
                    continue
                done = run(
                    [
                        "dotnet",
                        os.path.join(TESTS, "bin", "Release", "net8.0", "LiveClientTests.dll"),
                        host,
                        request,
                    ]
                )
            else:
                cmd = [sys.executable, os.path.join(ROOT, "scripts", "owen_live_gate.py")]
                if core:
                    cmd += ["--rust-core", core]
                done = run(cmd)
            caught = red(done.stdout, expect)
            if caught:
                print(f"ok[{name}]: caught by {caught} (exit {done.returncode})")
            else:
                failures.append(f"{name}: none of {expect} went red (exit {done.returncode})")
                print(done.stdout[-3000:])
        finally:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(original)
    for failure in failures:
        print(f"FAIL[{failure.split(':')[0]}]: {failure}")
    print(f"owen live mutations: {len(failures)} not caught")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
