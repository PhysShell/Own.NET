"""OX-02 P2: the extractor run as a library writes what the command line writes.

`InProcessExtractor.Run` (frontend/roslyn/OwnSharp.Extractor/InProcess.cs) is how the IDE
service runs the ONE extractor program inside a long-lived process. This check holds it to
the command line:

  E1  every job, run in-process, writes facts byte-identical to `ownsharp-extract` run as a
      process with the same arguments in the same directory, and exits with the same code;
  E2  the same, with the jobs run in the reverse order inside one process: no run leaks
      state into the next;
  E3  an overlay equal to the file on disk changes nothing;
  E4  an overlay that differs from the disk is read INSTEAD of the disk: the facts equal a
      command-line run over a copy of the tree with that file changed on disk, and differ
      from the facts of the unchanged tree (an implementation that kept reading the disk
      would fail here: mutation M6).

Run: python tests/check_extractor_in_process.py  (needs the .NET 8 SDK)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACTOR = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")
DRIVER = os.path.join(ROOT, "tests", "owen-live", "InProcessDriver")
SAMPLES = "frontend/roslyn/samples"
PROTO = "frontend/roslyn/protocol-samples"

FLAG_SETS: list[list[str]] = [
    [],
    ["--flow-locals"],
    ["--flow-locals", "--stats"],
    ["--fix-candidates"],
    ["--flow-locals", "--body-throw-edges"],
    ["--no-event-leaks", "--flow-locals"],
]


def _run(cmd: list[str], cwd: str = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _build(project: str) -> None:
    done = _run(["dotnet", "build", project, "-c", "Release", "-nologo", "-v", "q"])
    if done.returncode != 0:
        print(done.stdout[-3000:])
        raise SystemExit(f"FAIL: {project} does not build")


def _jobs() -> list[tuple[str, list[str]]]:
    """(label, arguments without -o); every job runs with the repository root as cwd."""
    jobs: list[tuple[str, list[str]]] = []
    for flags in FLAG_SETS:
        jobs.append((f"samples {' '.join(flags)}", [SAMPLES, *flags]))
    for name in sorted(os.listdir(os.path.join(ROOT, SAMPLES))):
        if name.endswith(".cs"):
            jobs.append((f"samples/{name}", [f"{SAMPLES}/{name}", "--flow-locals"]))
    for name in sorted(os.listdir(os.path.join(ROOT, PROTO, "cases"))):
        if name.endswith(".cs"):
            jobs.append(
                (f"cases/{name}", [f"{PROTO}/Api", f"{PROTO}/cases/{name}", "--flow-locals"])
            )
    for sub in ("same-assembly", "unrelated"):
        jobs.append((sub, [f"{PROTO}/{sub}", "--flow-locals"]))
    jobs.append(("heap-effects-samples", ["frontend/roslyn/heap-effects-samples", "--flow-locals"]))
    jobs.append(
        (
            "project-input-sample",
            ["frontend/roslyn/project-input-sample/ProjectInputSample.csproj", "--flow-locals"],
        )
    )
    jobs.append(
        ("OrderBackend", ["samples/OrderBackend/OrderBackend/OrderBackend.csproj", "--flow-locals"])
    )
    return jobs


def _cli(dll: str, args: list[str], out: str, cwd: str = ROOT) -> int:
    return _run(["dotnet", "exec", dll, *args, "-o", out], cwd=cwd).returncode


def _in_process(driver: str, jobs: list[dict[str, object]], tmp: str) -> list[int]:
    path = os.path.join(tmp, "jobs.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")
    done = _run(["dotnet", "exec", driver, path])
    if done.returncode != 0:
        raise SystemExit(
            f"FAIL: the in-process driver exited {done.returncode}: {done.stderr[-2000:]}"
        )
    lines = [ln for ln in done.stdout.splitlines() if ln.strip()]
    return [int(json.loads(ln)["rc"]) for ln in lines]


def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def main() -> int:
    _build(EXTRACTOR)
    _build(DRIVER)
    dll = os.path.join(EXTRACTOR, "bin", "Release", "net8.0", "ownsharp-extract.dll")
    driver = os.path.join(DRIVER, "bin", "Release", "net8.0", "InProcessDriver.dll")
    fails: list[str] = []
    checks = 0
    jobs = _jobs()
    with tempfile.TemporaryDirectory() as tmp:
        cli_out = [os.path.join(tmp, f"cli-{i}.json") for i in range(len(jobs))]
        cli_rc = [_cli(dll, args, out) for (_, args), out in zip(jobs, cli_out, strict=True)]

        for order, label in (
            (list(range(len(jobs))), "E1"),
            (list(reversed(range(len(jobs)))), "E2"),
        ):
            outs = {i: os.path.join(tmp, f"{label}-{i}.json") for i in order}
            rcs = _in_process(
                driver, [{"cwd": ROOT, "args": [*jobs[i][1], "-o", outs[i]]} for i in order], tmp
            )
            for i, rc in zip(order, rcs, strict=True):
                checks += 1
                name = jobs[i][0]
                if rc != cli_rc[i]:
                    fails.append(f"{label} {name}: exit {rc}, the command line exited {cli_rc[i]}")
                elif _read(outs[i]) != _read(cli_out[i]):
                    fails.append(f"{label} {name}: facts differ from the command line's")

        # E3/E4: the samples directory, one file overlaid. Self-contained on purpose: a run
        # whose facts depend on a built bin/ (OrderBackend's EF types) would refuse on a
        # clean checkout and compare no facts with no facts.
        project = SAMPLES
        target = os.path.join(ROOT, project, "FlowLocalsSample.cs")
        with open(target, encoding="utf-8") as f:
            original = f.read()
        same = os.path.join(tmp, "same.cs")
        with open(same, "w", encoding="utf-8", newline="") as f:
            f.write(original)
        # a non-escaping disposable local: the flow pass emits a function for it
        changed_text = original + (
            "\nstatic class OverlayProbe { static void M() "
            "{ var s = new System.IO.MemoryStream(); s.WriteByte(1); } }\n"
        )
        changed = os.path.join(tmp, "changed.cs")
        with open(changed, "w", encoding="utf-8", newline="") as f:
            f.write(changed_text)
        args = [project, "--flow-locals"]
        base_out = os.path.join(tmp, "e3-base.json")
        _cli(dll, args, base_out)
        e3 = os.path.join(tmp, "e3.json")
        e4 = os.path.join(tmp, "e4.json")
        _in_process(
            driver,
            [
                {"cwd": ROOT, "args": [*args, "-o", e3], "overlay": {target: same}},
                {"cwd": ROOT, "args": [*args, "-o", e4], "overlay": {target: changed}},
            ],
            tmp,
        )
        checks += 1
        if _read(e3) != _read(base_out):
            fails.append("E3: an overlay equal to the disk changed the facts")
        # the same change made on disk, in a copy of the tree, run by the command line
        copy = os.path.join(tmp, "tree")
        shutil.copytree(os.path.join(ROOT, project), os.path.join(copy, project))
        with open(
            os.path.join(copy, project, "FlowLocalsSample.cs"), "w", encoding="utf-8", newline=""
        ) as f:
            f.write(changed_text)
        disk_out = os.path.join(tmp, "e4-disk.json")
        _cli(dll, args, disk_out, cwd=copy)
        checks += 1
        e4_bytes = _read(e4)
        if _read(base_out) is None:
            fails.append("E4: the unchanged samples produced no facts; nothing was compared")
        elif e4_bytes is None or e4_bytes == _read(base_out):
            fails.append(
                "E4: an overlay that differs from the disk did not change the facts "
                "(the disk was read instead of the buffer)"
            )
        elif e4_bytes != _read(disk_out):
            fails.append(
                "E4: overlay facts differ from the command line's over the same contents on disk"
            )

    for failure in fails:
        print(f"FAIL: {failure}")
    print(
        f"extractor in-process: {checks - len(fails)}/{checks} passed, {len(fails)} failed "
        f"({len(jobs)} jobs)"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
