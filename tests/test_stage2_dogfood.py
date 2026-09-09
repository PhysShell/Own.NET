#!/usr/bin/env python3
"""#262 Stage 2 — Own.NET's own CI and dogfood select Rust, and the public
contract does not move.

Stage 1 proved the Rust core works behind the launcher. Stage 2 proves only
that this repository can RUN on it internally, and that doing so moved nothing
a user can see. That is a claim about the CI configuration, so most of the
evidence here is a claim about the CI configuration, read from the workflows
themselves rather than asserted in prose.

Why a census and not a demonstration. "Own.NET CI is Rust-default" is
unfalsifiable without a denominator: one Rust job proves one Rust job. So
`docs/evidence/p022-stage2-census.json` names EVERY call site in every workflow
that executes the analysis core or a production launcher surface, and the role
each one plays (A public-contract verifier / B explicit reference / C compare
gate / D operational dogfood). This harness enumerates the workflows itself and
fails when the two disagree in EITHER direction — an unclassified call site, or
a ledger entry for a job that no longer invokes anything. A census that can be
satisfied by editing prose is not a census.

The controls, and the direction each one guards:

    stage2-census                every core/launcher call site is classified
    internal-default-not-rust    every Class-D call site selects Rust explicitly
    public-default-moved         all four public surfaces still resolve Python
    rust-job-falls-back          a forced Rust failure is never rescued by Python
    wrong-rust-candidate         Class-D runs the production own-cli, and says which
    locator-contract-bypassed    no discovery: OWEN_RUST_CORE or nothing
    python-reference-lost        the explicit reference path still exists and runs
    compare-gate-dropped         no compare gate was traded for Rust exposure
    platform-leg-lost            the Rust-default claim covers Linux AND Windows

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one, so a
mutation campaign sees every catcher it trips rather than the first.

Run:  python tests/test_stage2_dogfood.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs/evidence/p022-stage2-census.json"
WORKFLOWS = ROOT / ".github/workflows"

SAMPLE_CS = """using System;
using System.IO;

public class Leaky
{
    public void Run()
    {
        var s = new FileStream("x.txt", FileMode.OpenOrCreate);
        Console.WriteLine(s.Length);
    }
}
"""

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []
_SKIPS: list[tuple[str, str]] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def skip(check: str, why: str) -> None:
    """Unrunnable here. Required in CI: OWEN_STAGE2_REQUIRE=1 turns every skip
    into a failure, so a gate cannot go green by quietly measuring nothing."""
    if os.environ.get("OWEN_STAGE2_REQUIRE"):
        fail(check, f"required but unrunnable: {why}")
    else:
        _SKIPS.append((check, why))
        print(f"skip[{check}]: {why}")


def tail(r: subprocess.CompletedProcess[bytes], limit: int = 300) -> str:
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip().replace("\n", " | ")
    return out[-limit:] if len(out) > limit else out


# --- the workflow reader ---------------------------------------------------


def ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _strip_comment(line: str) -> str:
    """A `#` comment is not a call site.

    Only whole-line comments are dropped. A `#` inside a shell line can be a
    real comment too, but it can equally be a fragment of a command, and
    guessing wrong in the direction of DROPPING text would let a call site hide
    behind a hash. Whole-line only, deliberately conservative.
    """
    return "" if line.strip().startswith("#") else line


def _is_path_filter(line: str) -> bool:
    """`- "scripts/own-check.sh"` under `paths:` names a file to WATCH, not a
    command to run."""
    s = line.strip()
    return bool(re.match(r'^-\s*["\']?[\w./*-]+["\']?$', s))


def job_spans(path: Path) -> list[tuple[str, int, int]]:
    """(job id, first line, last line) for every job in a workflow, 1-based.

    Job ids are the two-space keys AFTER `jobs:` — the same shape as `push:`
    under `on:`, which is why the `jobs:` boundary is required rather than
    assumed.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "jobs:"), None)
    if start is None:
        return []
    heads: list[tuple[str, int]] = []
    for i in range(start + 1, len(lines)):
        m = re.match(r"^  ([A-Za-z0-9][A-Za-z0-9_-]*):\s*$", lines[i])
        if m:
            heads.append((m.group(1), i + 1))
    spans = []
    for n, (job, first) in enumerate(heads):
        last = heads[n + 1][1] - 1 if n + 1 < len(heads) else len(lines)
        spans.append((job, first, last))
    return spans


def job_text(path: Path, first: int, last: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[first - 1:last])


def job_code(path: Path, first: int, last: int) -> str:
    """The job with its whole-line comments removed.

    Every control below that asks "does this job do X" must ask it of the code
    and not of the prose beside it, or a mutation that comments X out leaves
    the words in place and the control green.
    """
    return "\n".join(_strip_comment(ln) for ln in job_text(path, first, last).splitlines())


def runner_oses(path: Path, first: int, last: int) -> set[str]:
    """The runner images this job ACTUALLY runs on.

    Not "does the string windows-latest appear somewhere in it". That was the
    first version, and a mutation that deleted windows-latest from the matrix
    SURVIVED it: the `if: matrix.os == 'windows-latest'` guards left behind
    still contained the word, so a job that could no longer run on Windows
    still looked like one that did. The lesson is the same one this repository
    keeps paying for — a validator must read the thing it means.

    Two shapes are read, because two are used here: a literal `runs-on`, and a
    `runs-on: ${{ matrix.os }}` resolved through `strategy.matrix.os` in either
    its flow or its block form. Anything else returns empty, which fails the
    caller rather than passing it.
    """
    lines = job_code(path, first, last).splitlines()
    runs_on: str | None = None
    matrix: list[str] = []
    in_os_block = False
    for ln in lines:
        m = re.match(r"^    runs-on:\s*(\S.*?)\s*$", ln)
        if m:
            runs_on = m.group(1)
        m = re.match(r"^\s{6,}os:\s*\[(.+)\]\s*$", ln)
        if m:
            matrix = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
            in_os_block = False
            continue
        if re.match(r"^\s{6,}os:\s*$", ln):
            in_os_block = True
            continue
        if in_os_block:
            m = re.match(r"^\s+-\s*['\"]?([A-Za-z0-9._-]+)['\"]?\s*$", ln)
            if m:
                matrix.append(m.group(1))
            elif ln.strip():
                in_os_block = False
    if runs_on is None:
        return set()
    return set(matrix) if "matrix." in runs_on else {runs_on}


def platform_of(image: str) -> str | None:
    low = image.lower()
    if "windows" in low:
        return "windows"
    if "ubuntu" in low or "linux" in low:
        return "linux"
    if "macos" in low:
        return "macos"
    return None


def enumerate_call_sites() -> tuple[dict[tuple[str, str], list[str]], list[str]]:
    """Every (workflow, job) that executes the core or a launcher surface.

    Returns the map and the entry-point patterns used, so the report can say
    what was searched for rather than only what was found.
    """
    patterns = [re.compile(p) for p in ledger()["entry_points"]]  # type: ignore[index]
    found: dict[tuple[str, str], list[str]] = {}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        # as_posix(), not str(). On Windows str() yields `.github\\workflows\\ci.yml`
        # while the ledger stores forward slashes, so every key missed: every
        # call site read as unclassified and every ledger entry as stale, and
        # the census failed on Windows while passing on Linux. This repository
        # has paid for a host path separator once already — #260's mutation
        # harness took the separator into a catcher NAME and reported five
        # protected rules as unprotected. The ledger is a committed artefact
        # shared by both platforms, so its keys are POSIX by definition.
        rel = wf.relative_to(ROOT).as_posix()
        lines = wf.read_text(encoding="utf-8").splitlines()
        for job, first, last in job_spans(wf):
            hits = []
            for n in range(first - 1, min(last, len(lines))):
                line = _strip_comment(lines[n])
                if not line or _is_path_filter(line):
                    continue
                for p in patterns:
                    if p.search(line):
                        hits.append(f"{rel}:{n + 1}: {line.strip()[:90]}")
                        break
            if hits:
                found[(rel, job)] = hits
    return found, [str(p.pattern) for p in patterns]


def classified() -> dict[tuple[str, str], dict[str, str]]:
    return {(c["workflow"], c["job"]): c for c in ledger()["call_sites"]}  # type: ignore[index,union-attr]


def sites_of_class(cls: str) -> dict[tuple[str, str], dict[str, str]]:
    return {k: v for k, v in classified().items() if v["class"] == cls}


# --- toolchain -------------------------------------------------------------


def rust_core() -> str | None:
    p = os.environ.get("OWEN_RUST_CORE")
    return p if p and Path(p).is_file() else None


def launcher_dll() -> str | None:
    p = os.environ.get("OWEN_STAGE1_LAUNCHER_DLL")
    return p if p and Path(p).is_file() else None


def have_dotnet() -> bool:
    return shutil.which("dotnet") is not None


def bash_exe() -> str:
    """The bash that can run own-check.sh — never WSL's System32 stub."""
    if os.name != "nt":
        return "bash"
    for c in (os.environ.get("SHELL"),
              r"C:\Program Files\Git\bin\bash.exe",
              r"C:\Program Files\Git\usr\bin\bash.exe"):
        if c and Path(c).is_file():
            return c
    return "bash"


# --- controls: the census ---------------------------------------------------


def control_census() -> None:
    """Every call site is classified, and every classification is still live.

    Both directions matter. A new bare invocation that nobody classified is the
    hole this whole ledger exists to close; a stale entry is how a census keeps
    claiming coverage of a job that no longer analyses anything.
    """
    check = "stage2-census"
    found, patterns = enumerate_call_sites()
    known = classified()
    problems = []

    for key, hits in sorted(found.items()):
        if key not in known:
            problems.append(f"UNCLASSIFIED call site {key[0]}::{key[1]} — {hits[0]}")
    for key in sorted(known):
        if key not in found:
            problems.append(f"STALE ledger entry {key[0]}::{key[1]}: no call site found there "
                            "any more; re-classify or remove it")
    for key, entry in sorted(known.items()):
        if entry["class"] not in ledger()["classes"]:  # type: ignore[operator]
            problems.append(f"{key[1]}: unknown class {entry['class']!r}")
        if len(entry.get("why", "")) < 40:
            problems.append(f"{key[1]}: classified without a justification")

    # The relabel escape, closed. Every rule above is satisfied by moving a job
    # OUT of Class D: the Rust-default population shrinks, every remaining
    # member still selects Rust, and the census still balances. So a job that
    # calls itself dog-food in its own display name is Class D by declaration,
    # and the ledger does not get to disagree with the workflow about what the
    # job is for.
    for wf_rel, job in sorted(found):
        path = ROOT / wf_rel
        span = next((sp for sp in job_spans(path) if sp[0] == job), None)
        if span is None:
            continue
        m = re.search(r"^    name: (.+)$", job_code(path, span[1], span[2]), re.M)
        label = (m.group(1) if m else "").lower()
        if re.search(r"dog[- ]?food", label) and known.get((wf_rel, job), {}).get("class") != "D":
            problems.append(f"{wf_rel}::{job} calls itself dog-food but is classified "
                            f"{known.get((wf_rel, job), {}).get('class')!r} — a job cannot "
                            "leave the Rust-default population by being relabelled")

    if problems:
        fail(check, "; ".join(problems))
    else:
        counts = {c: len(sites_of_class(c)) for c in ("A", "B", "C", "D")}
        ok(check, f"{len(found)} core/launcher call sites across "
                  f"{len({k[0] for k in found})} workflows, all classified "
                  f"(A={counts['A']} public-contract, B={counts['B']} reference, "
                  f"C={counts['C']} compare, D={counts['D']} dogfood), "
                  f"{len(patterns)} entry-point patterns")


# --- controls: the Rust-default population ---------------------------------


_RUST_SELECTORS = (r"--engine rust", r"-Engine rust", r"engine: rust")


def control_internal_default_not_rust() -> None:
    """Every Class-D call site selects Rust EXPLICITLY.

    Explicitly, because Stage 2 is not allowed to work by moving a default: the
    product default stays Python, so an internal job that says nothing gets
    Python. "The dogfood is Rust-default" therefore has to be written down at
    every dogfood call site, and this is what reads it back.
    """
    check = "internal-default-not-rust"
    problems = []
    d_sites = sites_of_class("D")
    if not d_sites:
        problems.append("no Class-D call site exists at all — the Rust-default population is "
                        "empty, so the Stage-2 claim has nothing to stand on")
    for (wf, job) in sorted(d_sites):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            problems.append(f"{job}: not found in {wf}")
            continue
        text = job_code(path, span[1], span[2])
        if not any(re.search(p, text) for p in _RUST_SELECTORS):
            problems.append(f"{wf}::{job} is Class D but selects no engine explicitly — it "
                            "would run the PUBLIC default, which is Python")
        if "OWEN_RUST_CORE" not in text:
            problems.append(f"{wf}::{job} selects Rust without supplying a candidate through "
                            "OWEN_RUST_CORE")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"all {len(d_sites)} Class-D call sites select Rust explicitly and supply "
                  "the candidate through OWEN_RUST_CORE")


def control_wrong_rust_candidate() -> None:
    """Class-D runs the PRODUCTION own-cli, and the job says which binary ran.

    The three wrong candidates are all things this repository actually builds:
    `own-shadow-engine` (the #260 dev adapter), the Stage-1 test stub, and the
    `fault-injection` build. A dogfood job that quietly ran any of them would be
    green and meaningless.
    """
    check = "wrong-rust-candidate"
    banned = {
        "own-shadow-engine": "the #260 dev-only compare adapter",
        "stage1-stub": "the Stage-1 test instrument",
        "OWEN_STAGE1_STUB": "the Stage-1 test instrument",
        "target-fault": "the fault-injection build",
    }
    problems = []
    for (wf, job) in sorted(sites_of_class("D")):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            continue
        text = job_code(path, span[1], span[2])
        for token, what in banned.items():
            if re.search(rf"OWEN_RUST_CORE[^\n]*{re.escape(token)}", text):
                problems.append(f"{wf}::{job} points OWEN_RUST_CORE at {what} ({token})")
        if not re.search(r"cargo build[^\n]*-p own-cli[^\n]*--release", text):
            problems.append(f"{wf}::{job} does not build the production own-cli deterministically")
        if not re.search(r"sha256sum|Get-FileHash|shasum", text):
            problems.append(f"{wf}::{job} never records the candidate's identity — 'a Rust "
                            "binary ran' is not the same claim as 'THIS binary ran'")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "every Class-D job builds the production own-cli and records its identity")


def control_locator_contract_bypassed() -> None:
    """D3 has one locator and no discovery. A dogfood job is not an exception.

    Discovery is how a stale binary silently stands in for the one under test —
    the failure this repository has already paid for once. `which own-cli` in a
    CI job is the same defect as PATH lookup in the launcher.
    """
    check = "locator-contract-bypassed"
    discovery = [
        (r"which own-cli", "PATH lookup"),
        (r"command -v own-cli", "PATH lookup"),
        (r"Get-Command own-cli", "PATH lookup"),
        (r"find [^\n]*-name ['\"]?own-cli", "filesystem probing"),
        (r"ls [^\n]*target[^\n]*own-cli\*", "target-dir globbing"),
    ]
    problems = []
    for (wf, job) in sorted(sites_of_class("D")):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            continue
        text = job_code(path, span[1], span[2])
        for pat, what in discovery:
            if re.search(pat, text):
                problems.append(f"{wf}::{job} does {what} for its candidate instead of naming "
                                "it through OWEN_RUST_CORE")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "no Class-D job discovers its candidate; the locator is OWEN_RUST_CORE alone")


def control_platform_leg_lost() -> None:
    """The Rust-default claim covers Linux AND Windows.

    The two launcher surfaces differ in exactly the mechanics that broke during
    Stage 1 — process launch, executable bits, path forms, stream capture — so
    a Linux-only dogfood claim is a claim about half the product.

    It reads each Class-D job's actual runner images (see `runner_oses`), which
    is the whole point: the `windows-latest` that appears in a step guard is
    not a Windows leg.
    """
    check = "platform-leg-lost"
    seen: dict[str, list[str]] = {"linux": [], "windows": []}
    problems = []
    for (wf, job) in sorted(sites_of_class("D")):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            continue
        images = runner_oses(path, span[1], span[2])
        if not images:
            problems.append(f"{wf}::{job}: could not read which runner it uses at all")
        for image in images:
            fam = platform_of(image)
            if fam in seen:
                seen[fam].append(f"{job} ({image})")
    missing = [p for p, jobs in seen.items() if not jobs]
    if missing:
        problems.append(f"the Rust-default dogfood has no {', '.join(missing)} leg — "
                        f"present: { {k: v for k, v in seen.items() if v} }")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"Class-D dogfood runs on both platforms (linux: {', '.join(seen['linux'])}; "
                  f"windows: {', '.join(seen['windows'])})")


def control_compare_gate_dropped() -> None:
    """Rust exposure is never bought with differential evidence.

    The cheapest way to make a Rust-default dogfood green is to delete the job
    that would have disagreed with it.
    """
    check = "compare-gate-dropped"
    c_sites = sites_of_class("C")
    problems = []
    if len(c_sites) < 5:
        problems.append(f"only {len(c_sites)} compare gates remain; the ratified #260 set is "
                        "five (two in CI, three in the sweep)")
    found, _ = enumerate_call_sites()
    for key in sorted(c_sites):
        if key not in found:
            problems.append(f"compare gate {key[0]}::{key[1]} no longer invokes anything")
    for (wf, job) in sorted(c_sites):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            problems.append(f"compare gate {job} is gone from {wf}")
            continue
        text = job_code(path, span[1], span[2])
        if "if: false" in text.replace(" ", " "):
            problems.append(f"{wf}::{job} is disabled")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"all {len(c_sites)} compare gates are present and enabled")


def control_python_reference_lost() -> None:
    """The explicit reference path still exists, and still runs.

    Compare needs a reference. If the Python path decays into something nobody
    executes, the differential evidence decays with it and Rust-default dogfood
    starts passing because nothing is left to disagree with it.
    """
    check = "python-reference-lost"
    problems = []
    b_sites = sites_of_class("B")
    if not b_sites:
        problems.append("no Class-B explicit-reference call site remains")
    found, _ = enumerate_call_sites()
    for key in sorted(b_sites):
        if key not in found:
            problems.append(f"reference call site {key[0]}::{key[1]} no longer invokes anything")

    # And the runtime half: `--engine python` is not merely spelled somewhere,
    # it produces a verdict.
    if not have_dotnet():
        skip(check, "no dotnet, so the reference path could not be executed")
        return
    with tempfile.TemporaryDirectory(prefix="owen-stage2-ref-") as td:
        sample = Path(td) / "sample"
        sample.mkdir()
        (sample / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")
        r = subprocess.run(
            [bash_exe(), str(ROOT / "scripts/own-check.sh"),
             "--engine", "python", "--format", "human", "--", str(sample)],
            capture_output=True, cwd=str(ROOT), check=False)
        if b"OWN001" not in r.stdout:
            problems.append(f"--engine python produced no verdict (exit {r.returncode}) "
                            f"[{tail(r)}]")
    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, f"{len(b_sites)} reference call sites remain and --engine python still "
                  "produces a verdict")


# --- controls: the public contract -----------------------------------------


def control_public_default_moved() -> None:
    """All four public surfaces still resolve PYTHON when asked for nothing.

    The positive direction, which no amount of grepping for the word "rust"
    can give: a bare invocation is RUN, with OWEN_RUST_CORE set to something
    that CANNOT work, and it must still produce a verdict. If the public
    default had moved to Rust, that run would die on the locator (exit 2)
    instead. An unusable candidate is the falsifier here precisely because a
    usable one proves nothing — a Rust-default launcher and a Python-default
    launcher both succeed when the candidate is fine.

    The `owen` surface additionally gets the other direction: with the
    interpreter broken it must fail ON PYTHON (exit 3, no usable runtime),
    which is a positive statement about which engine it resolved rather than
    an inference from a missing error. own-check.sh cannot be asked that
    question the same way — it invokes a bare `python` and has no OWEN_PYTHON
    override, which is a real asymmetry between the surfaces and is recorded
    here rather than papered over; the unusable-candidate falsifier above does
    not depend on it.
    """
    check = "public-default-moved"
    problems = []

    # The two written-down defaults.
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    m = re.search(r"^  engine:\n(?:.*\n)*?    default: \"([a-z]+)\"", action, re.M)
    if not m:
        problems.append("action.yml: could not read the engine input's default at all")
    elif m.group(1) != "python":
        problems.append(f"action.yml: the PUBLIC engine default is {m.group(1)!r}, not python")

    sel = (ROOT / "frontend/roslyn/OwnSharp.Cli/EngineSelection.cs").read_text(encoding="utf-8")
    if not re.search(r"public const Engine Default = Engine\.Python;", sel):
        problems.append("EngineSelection.Default is no longer Engine.Python — the product "
                        "default moved, which is Stage 3 and is not authorized here")

    # The Action forwards its input to own-check.sh, so a default changed in
    # the forwarding would not show in the input's declared default.
    if not re.search(r'--engine "\$OWN_ENGINE"', action):
        problems.append("action.yml no longer forwards its engine input verbatim to "
                        "own-check.sh — the public default could be overridden in transit")

    if not have_dotnet():
        skip(check, "no dotnet, so the bare surfaces could not be run")
        return
    with tempfile.TemporaryDirectory(prefix="owen-stage2-pub-") as td:
        sample = Path(td) / "sample"
        sample.mkdir()
        (sample / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")

        # A candidate that exists and cannot possibly run. If a bare surface
        # selected Rust, this is fatal to it; if it selects Python, it is
        # irrelevant to it.
        unusable = Path(td) / "not-a-core"
        unusable.write_text("this is not an executable image\n", encoding="utf-8")
        env = dict(os.environ)
        env["OWEN_RUST_CORE"] = str(unusable)

        surfaces: list[tuple[str, list[str]]] = [
            ("own-check.sh", [bash_exe(), str(ROOT / "scripts/own-check.sh"),
                              "--format", "human", "--", str(sample)]),
        ]
        dll = launcher_dll()
        if dll is not None:
            surfaces.append(("owen", ["dotnet", dll, "check", str(sample)]))
        for name, argv in surfaces:
            r = subprocess.run(argv, capture_output=True, env=env, cwd=str(ROOT), check=False)
            merged = (r.stdout + r.stderr).decode("utf-8", "replace")
            if b"OWN001" not in r.stdout:
                problems.append(
                    f"{name}: a BARE invocation produced no verdict with an unusable "
                    f"OWEN_RUST_CORE present (exit {r.returncode}) — it tried to use the Rust "
                    f"candidate, so the public default has moved [{tail(r)}]")
            if "OWEN_RUST_CORE" in merged:
                problems.append(f"{name}: a bare invocation complained about OWEN_RUST_CORE — "
                                "it consulted the Rust locator, which the Python path must not")

        # The other direction, on the one surface that can be asked: with the
        # interpreter unusable the default must fail ON PYTHON.
        dll = launcher_dll()
        if dll is not None:
            env2 = dict(os.environ)
            env2["OWEN_RUST_CORE"] = str(rust_core() or unusable)
            env2["OWEN_PYTHON"] = str(Path(td) / "no-such-python")
            r = subprocess.run(["dotnet", dll, "check", str(sample)],
                               capture_output=True, env=env2, cwd=str(ROOT), check=False)
            merged = (r.stdout + r.stderr).decode("utf-8", "replace").lower()
            if b"OWN001" in r.stdout:
                problems.append("owen: a bare invocation produced a verdict while the "
                                "interpreter was unusable and a GOOD Rust candidate was "
                                "present — the default resolved Rust")
            elif "python" not in merged:
                problems.append(f"owen: a bare invocation failed without naming Python "
                                f"(exit {r.returncode}) [{tail(r)}]")

    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "action.yml and EngineSelection still default to python, the Action still "
                  "forwards its input verbatim, and a bare invocation ignores an unusable "
                  "Rust candidate entirely")


def control_rust_job_falls_back() -> None:
    """A forced Rust failure fails visibly; Python never rescues it.

    Two halves. Statically, a Class-D step must not swallow the launcher's exit
    code — `|| true` on the dogfood run turns every Stage-2 control into
    decoration. At run time, an explicitly Rust-selected run whose candidate
    cannot work must not produce a verdict.
    """
    check = "rust-job-falls-back"
    problems = []
    for (wf, job) in sorted(sites_of_class("D")):
        path = ROOT / wf
        span = next((s for s in job_spans(path) if s[0] == job), None)
        if span is None:
            continue
        for n, line in enumerate(job_code(path, span[1], span[2]).splitlines(), span[1]):
            if _strip_comment(line) and re.search(r"own-check\.(sh|ps1)[^\n]*\|\|\s*true", line):
                problems.append(f"{wf}:{n}: the dogfood run swallows its own exit code")
            if _strip_comment(line) and re.search(r"continue-on-error:\s*true", line):
                problems.append(f"{wf}:{n}: a Class-D step is allowed to fail silently")

    if not have_dotnet():
        skip(check, "no dotnet, so the forced-failure run could not be made")
        return
    with tempfile.TemporaryDirectory(prefix="owen-stage2-nofb-") as td:
        sample = Path(td) / "sample"
        sample.mkdir()
        (sample / "Leak.cs").write_text(SAMPLE_CS, encoding="utf-8")
        broken = Path(td) / "not-a-core"
        broken.write_text("this is not an executable image\n", encoding="utf-8")
        env = dict(os.environ)
        env["OWEN_RUST_CORE"] = str(broken)
        r = subprocess.run(
            [bash_exe(), str(ROOT / "scripts/own-check.sh"),
             "--engine", "rust", "--format", "human", "--", str(sample)],
            capture_output=True, env=env, cwd=str(ROOT), check=False)
        if b"OWN001" in r.stdout:
            problems.append("an explicitly Rust-selected run produced a verdict with an "
                            "unusable candidate — Python answered for Rust")
        elif r.returncode == 0:
            problems.append(f"an unusable Rust candidate exited 0 [{tail(r)}]")

    if problems:
        fail(check, "; ".join(problems))
    else:
        ok(check, "no Class-D step swallows its exit code, and a forced Rust failure produces "
                  "no verdict")


def run() -> int:
    control_census()
    control_internal_default_not_rust()
    control_public_default_moved()
    control_rust_job_falls_back()
    control_wrong_rust_candidate()
    control_locator_contract_bypassed()
    control_python_reference_lost()
    control_compare_gate_dropped()
    control_platform_leg_lost()

    print()
    print(f"stage-2 dogfood controls: {len(_PASSES)} passed, {len(_FAILURES)} failed, "
          f"{len(_SKIPS)} skipped")
    if _SKIPS:
        print("  skipped (set OWEN_STAGE2_REQUIRE=1 to make these failures):")
        for name, why in _SKIPS:
            print(f"    {name}: {why}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
