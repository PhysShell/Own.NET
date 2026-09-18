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

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")

# An invocation of one of the four launcher surfaces. `uses: ./` is the Action,
# which is a launcher surface too and carries its engine as an input.
INVOCATION = re.compile(
    r"(?:\bbash\s+)?(?:\./)?(?:scripts[/\\])own-check\.(?:sh|ps1)\b"
    r"|(?<![\w-])owen\s+check\b"
    r"|ownsharp\.dll[\"']?\s+check\b")

# Inside a script the path is routinely BUILT rather than written --
# benchmark.py says os.path.join(root, "scripts", "own-check.sh") -- so the
# pattern above, which wants a literal `scripts/own-check.sh`, could not see the
# one call site in this repository that actually broke CI. Scripts get a looser
# matcher and a stricter pre-pass: comments and docstrings are blanked first, so
# the prose ABOUT these call sites, of which there is a great deal, cannot be
# mistaken for one of them.
SCRIPT_INVOCATION = re.compile(r"own-check\.(?:sh|ps1)\b|(?<![\w-])owen\s+check\b")

# ...and naming a launcher is still not running one. These files discuss their
# own call sites in ordinary strings -- an error message about a missing
# own-check.sh, a status fragment listing the surfaces -- so a match only counts
# as an invocation when something in the statement actually LAUNCHES a process.
LAUNCHES_PY = re.compile(r"subprocess\.|Popen|check_output|os\.system|os\.exec")
LAUNCHES_SH = re.compile(r"^\s*(?:[\"'`]?\$?[\w{}/$.\\-]*own-check\.(?:sh|ps1)|"
                         r"owen\s+check|bash\s|pwsh\s|&\s)")

_TRIPLE = (chr(34) * 3, chr(39) * 3)


def _code_only(text: str) -> list[str]:
    """The file with comment lines and triple-quoted blocks blanked out, line
    numbering intact so a finding still points at the right line."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if fence is not None:
            out.append("")
            if fence in line:
                fence = None
            continue
        opened = next((q for q in _TRIPLE if q in line), None)
        if opened is not None:
            out.append("")
            if line.count(opened) == 1:
                fence = opened
            continue
        out.append("" if stripped.startswith("#") else line)
    return out

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

# A second, quieter shape of the same mistake, and the one that went RED in CI
# rather than green: a step that asserts something about the VENDORED PYTHON
# CORE'S CACHE and then invokes bare. Only the Python engine unpacks
# ~/.owen/core, so after the cutover those assertions are about a directory
# nothing wrote. This needs no injected variable to go wrong, which is why the
# environment alone was not enough to detect it.
ASSERTS_PYTHON_CACHE = re.compile(
    r"\[ -d \"\$HOME/\.owen\"|\$HOME/\.owen\"? \]|"
    r"expected a fresh ~/\.owen unpack|~/\.owen/core|\$HOME/\.owen/core")

# ...or it expects the injection to be IGNORED, which is exactly what a Stage-3
# cutover assertion looks like: break Python, run bare, demand a verdict anyway.
EXPECTS_PYTHON_IGNORED = re.compile(r"-eq\s+[01]\b|expected 1 \(findings\)")

# How a job can supply the public default's candidate.
SUPPLIES_CANDIDATE = re.compile(
    r"OWEN_RUST_CORE\s*=|OWEN_RUST_CORE:|OwenRustCoreDir|uses:\s*\./")

# A script has no job to supply a candidate, so a bare invocation in one is a
# CHOICE: it follows the public default and leaves the locator to its caller.
# That choice has to be stated at the call site, in these words.
DECLARES_DEFAULT = re.compile(r"no --engine here on purpose")

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

    # The workflows, and then the SCRIPTS the workflows call. Two of the three
    # call sites the cutover broke were not in any YAML at all: `benchmark.py`
    # shells out to own-check.sh from Python and `mine.sh` from bash, so a
    # control that only read the workflows declared victory over them.
    sources = [(n, os.path.join(WORKFLOWS, n))
               for n in sorted(os.listdir(WORKFLOWS))
               if n.endswith((".yml", ".yaml"))]
    scripts_dir = os.path.join(ROOT, "scripts")
    sources += [(f"scripts/{n}", os.path.join(scripts_dir, n))
                for n in sorted(os.listdir(scripts_dir))
                if n.endswith((".py", ".sh"))
                # The launcher surfaces themselves are not call sites of
                # themselves, and perf_baseline is #263's instrument, which
                # drives BOTH engines by parameter and names each one.
                and n not in ("own-check.sh", "own-check.ps1")]

    for name, path in sources:
        if False:
            continue
        text = open(path, encoding="utf-8").read()
        checked_files += 1
        jobs = _jobs(text)
        workflow_packs = bool(re.search(r"OwenRustCoreDir", text))
        # A script has no jobs: a bare invocation in one is served by whichever
        # caller sets the locator, so what this control can assert about it is
        # that the choice was MADE rather than inherited by accident. A script
        # that runs the default says so in a comment naming Stage 3; anything
        # else has to name its engine.
        is_script = name.startswith("scripts/")

        scan_lines = _code_only(text) if is_script else text.splitlines()
        for i, line in enumerate(scan_lines):
            stripped = line.strip()
            # Comments and the `on:` path filters are not invocations.
            if stripped.startswith("#") or stripped.startswith("- \""):
                continue
            matcher = SCRIPT_INVOCATION if is_script else INVOCATION
            if not matcher.search(line):
                continue
            if is_script:
                stmt = "\n".join(
                    ln for ln in scan_lines[max(0, i - 2):i + 30] if ln.strip())
                launcher = LAUNCHES_PY if name.endswith(".py") else LAUNCHES_SH
                if not launcher.search(stmt if name.endswith(".py") else line):
                    continue
            # A line that merely NAMES the script (a step title, an echo, a
            # path variable) is not an invocation of it.
            if stripped.startswith("- name:") or stripped.startswith("name:"):
                continue
            if re.match(r'^(echo|Write-Host|\$script\s*=|if \(\$LASTEXITCODE)', stripped):
                continue

            job = _owner(jobs, i)
            where = f"{name}:{i + 1}" + (f" [{job}]" if not name.startswith("scripts/") else "")
            # In a script the path and the flags are routinely on different
            # lines -- `sh = str(ROOT / "scripts/own-check.sh")` and the argv
            # built three lines later -- so the unit is the STATEMENT, not the
            # line. A window rather than a parser, because the question is only
            # "was an engine named here", and a wrong answer in either direction
            # is caught by the assertion, not hidden by it.
            context = line
            if is_script:
                # Counted in CODE lines, not raw ones. _code_only blanks
                # comments, and the comments explaining these call sites run to
                # eight lines apiece -- a raw-line window measured the prose and
                # stopped short of the argv it was looking for.
                window = [ln for ln in scan_lines[max(0, i - 2):] if ln.strip()][:10]
                # COMMENTS ARE STRIPPED, and that is not tidiness. The comments
                # explaining these very call sites say things like "--engine
                # python is EXPLICIT", so a matcher that read them would find
                # the flag in the prose after a mutation had removed it from the
                # argv -- which is exactly what happened, twice, while this
                # control was being written. Only code counts as a flag.
                context = "\n".join(
                    ln for ln in window if not ln.lstrip().startswith("#"))
            if EXPLICIT.search(context):
                explicit += 1
                continue
            bare += 1

            if is_script:
                # The declaration has to sit AT the call site, not somewhere in
                # the file. A first version accepted any Stage-3 comment
                # mentioning the word "default" anywhere in the module, and a
                # mutation that took benchmark.py's engine flag back off
                # survived it -- exempted by the very comment explaining why the
                # flag was there.
                declares_here = bool(
                    DECLARES_DEFAULT.search("\n".join(
                        text.splitlines()[max(0, i - 10):i + 2])))
                if not declares_here:
                    failures += _fail(
                        f"{where}: a BARE launcher invocation inside a script. A script has no "
                        f"job to supply a candidate, so after the cutover this either needs to "
                        f"name the engine it is about, or to say in a comment that it "
                        f"deliberately follows the public default (#262 Stage 3) and leave the "
                        f"locator to its caller.\n      {stripped[:150]}",
                        check="bare-invocation-can-reach-an-engine")
                continue

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

            step = _step_text(text.splitlines(), i)
            if ASSERTS_PYTHON_CACHE.search(step):
                failures += _fail(
                    f"{where}: this step ASSERTS something about the vendored Python core's "
                    f"cache (~/.owen/core) and then invokes the launcher BARE. Only the Python "
                    f"engine unpacks that cache, so since the cutover the assertion is about a "
                    f"directory nothing wrote. Name the engine it is about.\n      "
                    f"{stripped[:150]}",
                    check="python-cache-assertion-needs-an-explicit-engine")

            if PYTHON_SPECIFIC.search(line):
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
        f"workflows and scripts — {explicit} name their engine explicitly, {bare} run "
        f"the public default and "
        f"every one of them is in a job that can resolve it. {ignored_ok} step(s) inject a broken "
        f"Python into a bare invocation and assert it is IGNORED, which is the cutover "
        f"assertion; none assert an injection that can no longer happen")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
