#!/usr/bin/env python3
"""#262 Stage 3 — every CI launcher invocation can actually reach an engine.

The cutover's quietest failure mode is not a red job. It is a GREEN one.

A step that injects a broken Python and then invokes a launcher surface BARE
tested something real for the whole of Stages 1 and 2, because the bare surface
resolved Python. After Stage 3 the bare surface resolves Rust, never consults
`OWEN_PYTHON` at all, and that same step passes while proving nothing. Five such
steps existed in this repository when the default moved. Two more jobs would
have gone RED instead, because their bare invocation had no candidate to
resolve and would have exited 2 before doing any work.

Both directions are the same question — *which engine does this step actually
reach, and can it?* — so both are asked here, over the workflows themselves
rather than over a list someone maintains by hand.

## The rule

Every step that invokes a launcher surface is either:

* **EXPLICIT** — it names `--engine` / `-Engine`, so the cutover cannot have
  changed what it measures; or
* **BARE** — it runs the public default, and its job must then be able to
  RESOLVE that default. A bare invocation in a job with no candidate is not a
  test of the public default, it is an exit 2.

A job supplies a candidate in one of three ways, and this is the whole list:

    OWEN_RUST_CORE=      the ratified locator (D3), set by the job
    OwenRustCoreDir      the job packs the candidate INTO the package it then
                         installs (D6)
    uses: ./             the Action, which builds its own production own-cli

plus one cross-job case: a job that installs `Owen.Cli` from an artifact built
by another job in the same workflow is served by that job's pack.

## What this is not

It is not a claim that every bare step SHOULD be bare, and it does not know
which engine a step ought to measure — that is the Stage-2 census's job, by
role. This only refuses the two states in which a step cannot mean what it
says: a bare invocation that cannot reach an engine, and a step that names an
engine-specific environment variable while invoking bare.

Run:  python tests/test_stage3_surfaces.py
      python tests/run_tests.py            (in the suite)
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")

# An invocation of one of the four launcher surfaces. `uses: ./` is the Action,
# which is a launcher surface too and carries its engine as an input.
INVOCATION = re.compile(
    r"(?:\bbash\s+)?(?:\./)?(?:scripts[/\\])own-check\.(?:sh|ps1)\b"
    r"|(?<![\w-])owen\s+check\b"
    r"|ownsharp\.dll[\"']?\s+check\b")

# The spellings that make a step explicit about its engine.
EXPLICIT = re.compile(r"--engine\b|-Engine\b")

# Engine-specific environment variables. Setting one of these and then invoking
# BARE is not wrong by itself -- it is wrong when the step EXPECTS the injection
# to take effect, because since the cutover a bare invocation never consults
# them. So the step's own assertion is what decides:
PYTHON_SPECIFIC = re.compile(r"\bOWE?N_PYTHON=")

# ...it expects the injection to BITE (so it must name the engine): it asserts
# the Python-resolution tier, or reads a Python-specific message back out.
EXPECTS_PYTHON_TO_BITE = re.compile(
    r"-eq\s+3\b|expected exit 3|grep -q[i]?\s+\"?OWE?N_PYTHON"
    r"|ownlang: internal error|OWN_PYTHON is deprecated")

# ...or it expects the injection to be IGNORED, which is exactly what a Stage-3
# cutover assertion looks like: break Python, run bare, demand a verdict anyway.
EXPECTS_PYTHON_IGNORED = re.compile(r"-eq\s+[01]\b|expected 1 \(findings\)")

# How a job can supply the public default's candidate.
SUPPLIES_CANDIDATE = re.compile(
    r"OWEN_RUST_CORE\s*=|OWEN_RUST_CORE:|OwenRustCoreDir|uses:\s*\./")

# A job that installs the tool rather than building it is served by whichever
# job in the same workflow packed it.
INSTALLS_PACKAGE = re.compile(r"dotnet tool install.*Owen\.Cli", re.I)


def _fail(msg: str, *, check: str) -> int:
    print(f"FAIL[{check}]: {msg}")
    return 1


def _jobs(text: str) -> list[tuple[int, str]]:
    """(line index, job id) for every job in a workflow, in order."""
    return [(i, m.group(1))
            for i, line in enumerate(text.splitlines())
            if (m := re.match(r"^  ([a-z0-9_-]+):\s*$", line))]


def _owner(jobs: list[tuple[int, str]], line: int) -> str:
    owned = [j for j in jobs if j[0] <= line]
    return owned[-1][1] if owned else "<top-level>"


def _step_text(lines: list[str], line: int) -> str:
    """The body of the step containing `line`: from its own `- name:` to the
    next one at the same indent. The step's ASSERTION is what says whether an
    injection was meant to take effect, so the question cannot be answered from
    the invocation line alone."""
    start = 0
    indent = ""
    for i in range(line, -1, -1):
        m = re.match(r"^(\s*)- name:", lines[i])
        if m:
            start, indent = i, m.group(1)
            break
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(rf"^{indent}- (name|uses):", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def _job_text(text: str, jobs: list[tuple[int, str]], job: str) -> str:
    lines = text.splitlines()
    starts = [i for i, name in jobs if name == job]
    if not starts:
        return ""
    start = starts[0]
    after = [i for i, _ in jobs if i > start]
    return "\n".join(lines[start:after[0] if after else len(lines)])


def run() -> int:
    failures = 0
    bare = explicit = ignored_ok = 0
    checked_files = 0

    for name in sorted(os.listdir(WORKFLOWS)):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(WORKFLOWS, name)
        text = open(path, encoding="utf-8").read()
        checked_files += 1
        jobs = _jobs(text)
        workflow_packs = bool(re.search(r"OwenRustCoreDir", text))

        for i, line in enumerate(text.splitlines()):
            stripped = line.strip()
            # Comments and the `on:` path filters are not invocations.
            if stripped.startswith("#") or stripped.startswith("- \""):
                continue
            if not INVOCATION.search(line):
                continue
            # A line that merely NAMES the script (a step title, an echo, a
            # path variable) is not an invocation of it.
            if stripped.startswith("- name:") or stripped.startswith("name:"):
                continue
            if re.match(r'^(echo|Write-Host|\$script\s*=|if \(\$LASTEXITCODE)', stripped):
                continue

            job = _owner(jobs, i)
            where = f"{name}:{i + 1} [{job}]"
            if EXPLICIT.search(line):
                explicit += 1
                continue
            bare += 1

            body = _job_text(text, jobs, job)
            served = bool(SUPPLIES_CANDIDATE.search(body))
            if not served and INSTALLS_PACKAGE.search(body) and workflow_packs:
                served = True
            if not served:
                failures += _fail(
                    f"{where}: a BARE launcher invocation in a job that supplies no candidate. "
                    f"The public default is Rust (#262 Stage 3), so this step cannot reach an "
                    f"engine: it will exit 2 before doing any work. Either name the engine it "
                    f"is actually about (--engine/-Engine) or give the job a candidate "
                    f"(OWEN_RUST_CORE, OwenRustCoreDir, or the Action).\n      {stripped[:150]}",
                    check="bare-invocation-can-reach-an-engine")

            if PYTHON_SPECIFIC.search(line):
                step = _step_text(text.splitlines(), i)
                if EXPECTS_PYTHON_TO_BITE.search(step):
                    failures += _fail(
                        f"{where}: this step injects a broken Python and then invokes the "
                        f"launcher BARE, while ASSERTING that the injection took effect. Since "
                        f"the cutover a bare invocation never consults OWEN_PYTHON, so the "
                        f"injection cannot happen -- this step can only pass by proving nothing. "
                        f"Name the engine it is about.\n      {stripped[:150]}",
                        check="python-injection-needs-an-explicit-engine")
                elif not EXPECTS_PYTHON_IGNORED.search(step):
                    failures += _fail(
                        f"{where}: this step injects a broken Python into a BARE invocation and "
                        f"asserts neither that the injection bit nor that it was ignored, so "
                        f"nobody can tell which it meant.\n      {stripped[:150]}",
                        check="python-injection-needs-an-explicit-engine")
                else:
                    ignored_ok += 1

    if not bare and not explicit:
        return _fail(
            "no launcher invocation was found in any workflow — the matcher stopped matching, "
            "so this control was asserting over an empty set",
            check="stage3-surfaces-non-vacuous")

    if failures:
        return 1
    print(
        f"stage-3 CI surfaces OK: {explicit + bare} launcher invocations over {checked_files} "
        f"workflows — {explicit} name their engine explicitly, {bare} run the public default and "
        f"every one of them is in a job that can resolve it. {ignored_ok} step(s) inject a broken "
        f"Python into a bare invocation and assert it is IGNORED, which is the cutover "
        f"assertion; none assert an injection that can no longer happen")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
