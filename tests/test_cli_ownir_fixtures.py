#!/usr/bin/env python3
"""The frozen `own-cli ownir` CLI contract (P-022 step 7b, #261 261.B).

Python is the oracle for everything **after `ownir` is selected**; the
top-level shell is a cross-implementation parity surface with no Python byte
oracle at all. C-1 of #261's ratified decision packet draws that line at the
*surface*, never at the reference's internal print branch, so a case is tagged
with the oracle that authored it and a reader can tell the classes apart:

    python            an executed `python -m ownlang ownir ...` run
    python-docstring  the same, and the bytes are the whole module docstring on
                      stdout (a positional-count error or an unknown argument).
                      Frozen as measured AND flagged, so the owner can declare
                      that exact class a defect without having to find it.
    owen-convention   no Python oracle exists: authored once from the help text
                      carried in the manifest, following the public `owen`
                      convention (frontend/roslyn/OwnSharp.Cli/Program.cs).

What this module is *for* is the Rust replay
(`rust/crates/own-cli/tests/replay.rs`), which runs the built binary against
these bytes with **zero Python**. This side proves the bytes are still the
reference's.

Run:  python tests/test_cli_ownir_fixtures.py            (verify)
      python tests/test_cli_ownir_fixtures.py --write    (regenerate)
      python tests/run_tests.py                          (in the suite)

Two things this writer refuses to do, both on purpose:

* it never writes a case whose two runs disagree — a fixture that is not
  byte-deterministic is not a contract, it is a coin flip with a filename;
* it never writes a raw `.txt` expectation. Streams live inside JSON strings
  so a checkout with `core.autocrlf` on cannot corrupt an expectation (#343).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

FIXTURE_DIR = os.path.join(_HERE, "fixtures", "cli_ownir")
MANIFEST = os.path.join(FIXTURE_DIR, "manifest.json")
CLI_OWNIR_VERSION = 1

# The one placeholder the format admits. It consumes the rest of the line it
# appears on, and the replay requires it to consume something non-empty. It may
# appear ONLY on a line carrying an OS error text: `cannot read <path>: <tail>`
# is platform-native (`[Errno 2] No such file or directory: '...'` on Linux,
# `[Errno 13] Permission denied` where Windows refuses a directory), so the
# contract is the line up to and including `cannot read <path>: ` and the tail
# is recorded per platform rather than asserted. The same choice
# tests/test_cli_contract.py already made with its "cannot read" substring.
OS_ERROR = "<OS_ERROR>"
_READ_MARK = "cannot read "


class NonDeterministic(RuntimeError):
    """Two runs of the reference disagreed. A case like that is not a contract,
    so `--write` refuses to write it and `run()` reports it as a failure —
    never as a `SystemExit`, which would end the aggregate runner at import
    time (`tests/_preflight.py` forbids exactly that)."""

# --------------------------------------------------------------------------
# The `owen-convention` surface: authored ONCE, here, and carried in the
# manifest. The binary holds the same two strings as consts and
# rust/crates/own-cli/tests/replay.rs asserts they are equal, so the text
# cannot drift between the two halves of the contract.
# --------------------------------------------------------------------------

OWN_CLI_VERSION = "0.1.0"  # asserted against CARGO_PKG_VERSION by the replay

SHELL_USAGE = """\
own-cli — the Own.NET core as a native executable.

Usage:
  own-cli ownir <facts.json> [options]   check OwnIR facts extracted from C#

Options (ownir):
  --format {human|github|msbuild|sarif}  finding surface (default: human)
  --severity {error|warning}             how a finding is shown (default: error)
  --verbosity {quiet|normal|verbose}     quiet hides the advisory notes;
                                         verbose adds a per-code breakdown
                                         (default: normal)
  --help, -h                             print this help
  --version                              print the version

Both `--flag value` and `--flag=value` are accepted. `ownir` takes exactly one
positional argument, the facts file; there is no `--` separator and there are
no short flags.

Exit codes:
  0  clean
  1  findings — any non-advisory, unsuppressed finding, independent of
     --severity
  2  usage error, or a facts document the strict door refuses
  70 internal error — a bug in the analyzer, never silence
"""

OWNIR_USAGE = """\
own-cli ownir — check OwnIR facts extracted from C# by the Roslyn frontend.

Usage:
  own-cli ownir <facts.json> [--format F] [--severity S] [--verbosity V]

Options:
  --format {human|github|msbuild|sarif}  human is the default CLI line, github
                                         a CI annotation, msbuild the VS Error
                                         List line, sarif a SARIF 2.1.0 log
  --severity {error|warning}             how the host shows a finding; it never
                                         changes the exit code
  --verbosity {quiet|normal|verbose}     quiet hides the advisory notes
                                         (OWN050/051/052, OBL005); verbose adds
                                         a per-code breakdown over every
                                         finding, suppressed ones included

Both `--flag value` and `--flag=value` are accepted. Exactly one positional
argument; there is no `--` separator and there are no short flags.

Exit codes:
  0  no leaks
  1  at least one non-advisory, unsuppressed finding
  2  usage error, or a facts document the strict door refuses
  70 internal error — a bug in the analyzer, never silence
"""

_UNKNOWN_COMMAND = "own-cli: unknown command {name!r}\n"


def _shell(stdout: str = "", stderr: str = "", exit_code: int = 0) -> dict:
    return {"exit": exit_code, "stdout": stdout, "stderr": stderr,
            "os_error_tail": None}


# --------------------------------------------------------------------------
# The case list. Declared, never swept: every case names what it is a control
# for, and the census fragment is rendered from these rules.
# --------------------------------------------------------------------------

# Paths are relative to the fixture directory, which is also the default cwd,
# so the bytes a case freezes carry a relative path that means the same thing
# on both platforms and in a fresh clone.
_CLEAN = "../verdict_renders/render_empty.facts.json"
_LEAKY = "../verdict_renders/render_columns.facts.json"
_ADVISORY = "../verdict_renders/render_anchorless.facts.json"
_BANDS = "../verdict_renders/render_tiers_and_levels.facts.json"
_ESCAPING = "../verdict_renders/render_escaping.facts.json"
_REFUSAL = "../verdict_renders/render_refusal.facts.json"
_SUPPRESSED = "inputs/suppressed_only.facts.json"
_NONASCII = "inputs/nonascii_file.facts.json"
_EMPTY_REASON = "inputs/empty_ignore_reason.facts.json"
_SPACED = "inputs/pa th ünïcødé/facts.json"
_NOT_OBJECT = "inputs/not_an_object.facts.json"


class Case:
    """One frozen invocation.

    `oracle` decides who authors the bytes; `rules` is what the case is the
    control for (the census groups by them); `expected` is filled in by
    `--write` for a python oracle and stated here for an owen-convention one.
    """

    def __init__(self, name: str, argv: list[str], *, oracle: str,
                 rules: list[str], pins: list[str], cwd: str = ".",
                 env: dict[str, str] | None = None,
                 expected: dict | None = None) -> None:
        self.name = name
        self.argv = argv
        self.oracle = oracle
        self.rules = rules
        self.pins = pins
        self.cwd = cwd
        self.env = env or {}
        self.expected = expected


def _display_cases() -> list[Case]:
    """The display policy: which findings are shown, the summary and `ok`
    lines, the stream split, and the four formats through the process
    boundary."""
    out: list[Case] = []

    # A clean document in every format: the machine formats must write ZERO
    # bytes to stdout, and `human` must write the ok line and the summary there.
    for fmt in ("human", "github", "msbuild", "sarif"):
        out.append(Case(
            f"clean-{fmt}", ["ownir", _CLEAN, "--format", fmt],
            oracle="python",
            rules=(["ok-line", "stream-split"]
                   + (["machine-stdout-empty-when-clean"]
                      if fmt in ("github", "msbuild") else [])),
            pins=[f"a clean document rendered as {fmt}"]))

    # The failing tier in every format, at both host severities: --severity
    # changes the rendered level and NEVER the exit code.
    for fmt in ("human", "github", "msbuild", "sarif"):
        for sev in ("error", "warning"):
            out.append(Case(
                f"leaky-{fmt}-{sev}", ["ownir", _LEAKY, "--format", fmt,
                                       "--severity", sev],
                oracle="python",
                rules=["exit-independent-of-severity", "stream-split"],
                pins=[f"two OWN001 leaks as {fmt} at --severity {sev}"]))

    # All four bands in one document (leak + intrinsic-warning leak + advisory
    # + suppressed) across the whole verbosity axis and both severities. This is
    # where quiet/normal/verbose, the summary tails and the SARIF list are
    # proved together.
    for fmt in ("human", "github", "msbuild", "sarif"):
        for sev in ("error", "warning"):
            for verb in ("quiet", "normal", "verbose"):
                rules = ["exit-independent-of-severity", "stream-split",
                         "summary-suppressed-tail"]
                if verb == "quiet":
                    rules.append("quiet-hides-advisory")
                if verb == "verbose":
                    rules.append("verbose-counts-every-finding")
                if fmt == "sarif":
                    rules.append("sarif-carries-shown-plus-suppressed")
                out.append(Case(
                    f"bands-{fmt}-{sev}-{verb}",
                    ["ownir", _BANDS, "--format", fmt, "--severity", sev,
                     "--verbosity", verb],
                    oracle="python", rules=rules,
                    pins=[f"all four bands as {fmt}, --severity {sev}, "
                          f"--verbosity {verb}"]))

    # Advisory-only: exit 0 even though something is printed, and `quiet` hides
    # it without touching the exit.
    for verb in ("quiet", "normal", "verbose"):
        out.append(Case(
            f"advisory-only-{verb}", ["ownir", _ADVISORY, "--verbosity", verb],
            oracle="python",
            rules=["advisory-never-fails-the-run", "quiet-hides-advisory",
                   "verbose-counts-every-finding"],
            pins=["an OWN052 advisory and no leak: exit 0"]))

    # Suppressed-only: the `ok` line AND a suppressed tally in one run, and a
    # verbose breakdown that counts a finding nothing showed.
    for verb in ("normal", "verbose"):
        out.append(Case(
            f"suppressed-only-{verb}", ["ownir", _SUPPRESSED,
                                        "--verbosity", verb],
            oracle="python",
            rules=["ok-line-with-suppressed", "summary-suppressed-tail",
                   "verbose-counts-every-finding"],
            pins=["every finding [OwnIgnore]-suppressed: ok, a tally, exit 0"]))
    out.append(Case(
        "suppressed-only-sarif", ["ownir", _SUPPRESSED, "--format", "sarif"],
        oracle="python",
        rules=["sarif-carries-shown-plus-suppressed", "ok-line-with-suppressed"],
        pins=["a suppressed finding still rides in the SARIF results"]))

    # BR-V6: an empty-string reason never suppresses.
    out.append(Case(
        "empty-ignore-reason-does-not-suppress", ["ownir", _EMPTY_REASON],
        oracle="python", rules=["empty-reason-never-suppresses"],
        pins=["ignore_reason='' leaves the finding shown and the exit at 1"]))

    # Paths and encodings, through the formats that render them differently.
    out.append(Case(
        "path-nonascii-file-human", ["ownir", _NONASCII],
        oracle="python", rules=["nonascii-in-file-field"],
        pins=["a non-ASCII (and astral) `file` on the human line"]))
    out.append(Case(
        "path-nonascii-file-github", ["ownir", _NONASCII, "--format", "github"],
        oracle="python", rules=["nonascii-in-file-field"],
        pins=["the same, as a GitHub annotation"]))
    out.append(Case(
        "path-nonascii-file-sarif", ["ownir", _NONASCII, "--format", "sarif"],
        oracle="python", rules=["sarif-ascii-escape", "nonascii-in-file-field"],
        pins=["json.dumps' ASCII escaping, surrogate pair above the BMP"]))
    out.append(Case(
        "sarif-ascii-escape-em-dash", ["ownir", _LEAKY, "--format", "sarif"],
        oracle="python", rules=["sarif-ascii-escape"],
        pins=["the message's U+2014 leaves as the six ASCII characters "
              "\\u2014, NOT the literal bytes the BR-V9 goldens carry"]))
    out.append(Case(
        "path-backslash-file-github", ["ownir", _ESCAPING, "--format", "github"],
        oracle="python", rules=["windows-path-form"],
        pins=["a backslash `file` and the %3A/%2C property escaping"]))
    out.append(Case(
        "path-backslash-file-sarif", ["ownir", _ESCAPING, "--format", "sarif"],
        oracle="python", rules=["windows-path-form"],
        pins=["SARIF folds the backslash to a forward slash in the uri"]))
    out.append(Case(
        "path-with-space-and-nonascii", ["ownir", _SPACED],
        oracle="python", rules=["nonascii-in-path"],
        pins=["the facts PATH carries a space and non-ASCII"]))

    # OWNLANG_DEBUG is scrubbed from the inherited environment unless a case
    # sets it; this case sets it and proves it changes nothing for a run that
    # does not crash.
    out.append(Case(
        "debug-env-does-not-change-ordinary-output", ["ownir", _LEAKY],
        oracle="python", rules=["debug-env-is-inert-when-nothing-crashes"],
        env={"OWNLANG_DEBUG": "1"},
        pins=["OWNLANG_DEBUG only ever changes the internal-error path"]))

    # cwd is part of the case: the same document reached from a subdirectory
    # echoes the path it was given, not a resolved one.
    out.append(Case(
        "cwd-relative-path-is-echoed-as-given", ["ownir", "facts.json"],
        cwd="inputs/pa th ünïcødé",
        oracle="python", rules=["path-echoed-as-given", "nonascii-in-path"],
        pins=["the summary echoes argv, never a resolved path"]))
    return out


def _usage_cases() -> list[Case]:
    """Everything after `ownir` that answers with a usage error."""
    doc = ["docstring-on-stdout"]
    return [
        # The docstring-on-stdout class, frozen AND flagged (C-1).
        Case("usage-no-positional", ["ownir"], oracle="python-docstring",
             rules=doc, pins=["zero positionals prints the whole module "
                              "docstring to stdout, exit 2"]),
        Case("usage-two-positionals", ["ownir", _CLEAN, _CLEAN],
             oracle="python-docstring", rules=doc,
             pins=["two positionals: the same docstring"]),
        Case("usage-unknown-flag-with-path", ["ownir", "--bogus", _CLEAN],
             oracle="python-docstring", rules=[*doc, "unknown-flag-is-positional"],
             pins=["an unknown flag is a POSITIONAL to the reference's parser, "
                   "so with a real path it is two positionals"]),
        Case("usage-double-dash-not-a-separator", ["ownir", "--", _CLEAN],
             oracle="python-docstring", rules=[*doc, "no-double-dash-separator"],
             pins=["`--` is an ordinary positional; there is no separator"]),

        # The other half of the unknown-flag behaviour: alone it is ONE
        # positional, so it reaches the ordinary path and fails to open.
        Case("usage-unknown-flag-alone", ["ownir", "--bogus"], oracle="python",
             rules=["unknown-flag-is-positional", "os-error-placeholder"],
             pins=["one positional named --bogus: the read fails, exit 2"]),

        # A flag with no value.
        *[Case(f"usage-{flag[2:]}-missing-value", ["ownir", _CLEAN, flag],
               oracle="python", rules=["missing-flag-value"],
               pins=[f"`{flag}` with nothing after it"])
          for flag in ("--format", "--severity", "--verbosity")],

        # An invalid value for each flag. --format names `json` among the
        # choices because it passes the GLOBAL value gate.
        Case("usage-format-invalid", ["ownir", _CLEAN, "--format", "x"],
             oracle="python", rules=["invalid-flag-value"],
             pins=["the global _FORMATS gate, which still lists json"]),
        Case("usage-format-empty-value", ["ownir", _CLEAN, "--format="],
             oracle="python", rules=["invalid-flag-value", "equals-spelling"],
             pins=["`--format=` is an empty value, not a missing one"]),
        Case("usage-format-value-is-a-flag",
             ["ownir", _CLEAN, "--format", "--severity"],
             oracle="python", rules=["invalid-flag-value"],
             pins=["a following flag is consumed as the value"]),
        Case("usage-severity-invalid", ["ownir", _CLEAN, "--severity", "x"],
             oracle="python", rules=["invalid-flag-value"], pins=["error|warning"]),
        Case("usage-verbosity-invalid", ["ownir", _CLEAN, "--verbosity", "x"],
             oracle="python", rules=["invalid-flag-value"],
             pins=["quiet|normal|verbose"]),

        # `json` passes the global gate and is refused on the ownir branch with
        # its own message, naming the four surfaces in ITS order.
        Case("usage-format-json-rejected-by-ownir",
             ["ownir", _CLEAN, "--format", "json"], oracle="python",
             rules=["invalid-flag-value", "ownir-format-scope"],
             pins=["the cfg seam's format is not an ownir surface"]),

        # The `=` spelling is accepted, and a duplicate is not an error.
        Case("usage-equals-spelling-accepted",
             ["ownir", _CLEAN, "--format=sarif"], oracle="python",
             rules=["equals-spelling"],
             pins=["--flag=value is identical to --flag value"]),
        Case("usage-duplicate-flag-last-wins",
             ["ownir", _CLEAN, "--format=human", "--format=sarif"],
             oracle="python", rules=["equals-spelling", "duplicate-flag"],
             pins=["a repeated flag is not an error; the last one wins"]),
    ]


def _refusal_cases() -> list[Case]:
    """The strict door, and the OS-error class."""
    return [
        Case("refuse-missing-file", ["ownir", "inputs/no_such_facts.json"],
             oracle="python", rules=["os-error-placeholder", "strict-door"],
             pins=["a missing facts file is a polite exit 2, never a crash"]),
        Case("refuse-directory", ["ownir", "inputs"], oracle="python",
             rules=["os-error-placeholder", "strict-door"],
             pins=["a directory is an OS error, and its text is platform-native"]),
        Case("refuse-root-not-an-object", ["ownir", _NOT_OBJECT],
             oracle="python", rules=["strict-door"],
             pins=["the shape refusal, byte-identical in both implementations"]),
        Case("refuse-unknown-flow-op", ["ownir", _REFUSAL], oracle="python",
             rules=["strict-door"],
             pins=["the vocabulary refusal, already byte-pinned by BR-V9"]),
        # The stdin ruling, recorded EXPLICITLY rather than silently: `-` is not
        # a stdin marker to the reference, it is a file name.
        Case("stdin-dash-is-out-of-contract", ["ownir", "-"], oracle="python",
             rules=["stdin-out-of-contract", "os-error-placeholder"],
             pins=["the ruling: stdin is not part of the contract. The "
                   "reference opens the literal path '-' and fails; recorded "
                   "here so 'out of contract' is a fixture, not a silence"]),
    ]


def _shell_cases() -> list[Case]:
    """The top-level shell — a parity surface of its own (C-1). No Python
    oracle exists for any of these, and `ownir --help` is the one case after
    `ownir` the owner declared a defect and did NOT port."""
    conv = "owen-convention"
    return [
        Case("shell-empty-invocation", [], oracle=conv,
             rules=["usage-owen-shape"],
             pins=["the empty invocation prints help to stdout and exits 2"],
             expected=_shell(stdout=SHELL_USAGE, exit_code=2)),
        Case("shell-help-long", ["--help"], oracle=conv,
             rules=["usage-owen-shape"], pins=["--help is a success"],
             expected=_shell(stdout=SHELL_USAGE, exit_code=0)),
        Case("shell-help-short", ["-h"], oracle=conv,
             rules=["usage-owen-shape"], pins=["-h is the same as --help"],
             expected=_shell(stdout=SHELL_USAGE, exit_code=0)),
        Case("shell-version", ["--version"], oracle=conv,
             rules=["usage-owen-shape"], pins=["own-cli <version> on stdout"],
             expected=_shell(stdout=f"own-cli {OWN_CLI_VERSION}\n", exit_code=0)),
        Case("shell-unknown-command", ["bogus"], oracle=conv,
             rules=["usage-owen-shape"],
             pins=["distinct from the empty invocation: one error line and the "
                   "help, both on STDERR, exit 2"],
             expected=_shell(
                 stderr=_UNKNOWN_COMMAND.format(name="bogus") + SHELL_USAGE,
                 exit_code=2)),
        Case("shell-unknown-command-that-looks-like-a-flag", ["--nope"],
             oracle=conv, rules=["usage-owen-shape"],
             pins=["an unrecognised flag at the SHELL is an unknown command; "
                   "the reference's positional-swallowing parser is a branch "
                   "after `ownir`, not the surface"],
             expected=_shell(
                 stderr=_UNKNOWN_COMMAND.format(name="--nope") + SHELL_USAGE,
                 exit_code=2)),
        Case("ownir-help-is-the-declared-defect", ["ownir", "--help"],
             oracle=conv, rules=["usage-owen-shape", "declared-defect"],
             pins=["C-1: the reference answers `cannot read --help` with exit "
                   "2. That is declared a defect and NOT ported: the shell "
                   "convention extends to the subcommand"],
             expected=_shell(stdout=OWNIR_USAGE, exit_code=0)),
    ]


def cases() -> list[Case]:
    return (_shell_cases() + _usage_cases() + _refusal_cases()
            + _display_cases())


# --------------------------------------------------------------------------
# Running the reference
# --------------------------------------------------------------------------

def _reference(case: Case) -> tuple[int, str, str]:
    """One `python -m ownlang ownir ...` run, from the case's cwd, with
    OWNLANG_DEBUG scrubbed from the inherited environment unless the case sets
    it. `-m ownlang` needs the repo on the path, and the cwd is the fixture
    directory, so PYTHONPATH carries the root explicitly."""
    env = {k: v for k, v in os.environ.items() if k != "OWNLANG_DEBUG"}
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.update(case.env)
    proc = subprocess.run(
        [sys.executable, "-m", "ownlang", *case.argv],
        capture_output=True, check=False, env=env,
        cwd=os.path.join(FIXTURE_DIR, case.cwd))
    return (proc.returncode,
            proc.stdout.decode("utf-8", "surrogateescape"),
            proc.stderr.decode("utf-8", "surrogateescape"))


def _placeholder(stderr: str) -> tuple[str, str | None]:
    """Replace the platform-native OS error tail with `<OS_ERROR>` and hand back
    the tail that was replaced. Only the text after `cannot read <path>: ` on
    that one line is replaced — the rest of the line is contract."""
    idx = stderr.find(_READ_MARK)
    if idx < 0:
        return stderr, None
    # The tail starts after the ": " that follows the echoed path.
    colon = stderr.find(": ", idx + len(_READ_MARK))
    if colon < 0:
        return stderr, None
    start = colon + 2
    end = stderr.find("\n", start)
    if end < 0:
        end = len(stderr)
    tail = stderr[start:end]
    if not tail:
        return stderr, None
    return stderr[:start] + OS_ERROR + stderr[end:], tail


def _expectation(case: Case) -> dict:
    """The expectation for one python-oracle case, taken twice: a case whose
    two runs disagree is not written at all."""
    first = _reference(case)
    second = _reference(case)
    if first != second:
        raise NonDeterministic(
            f"case {case.name!r} is NOT deterministic — two runs of the "
            f"reference disagreed, so it cannot be a contract.\n"
            f"  first : {first!r}\n  second: {second!r}")
    code, out, err = first
    err, tail = _placeholder(err)
    return {"exit": code, "stdout": out, "stderr": err,
            "os_error_tail": {"linux": tail} if tail else None}


def _case_path(name: str) -> str:
    return os.path.join(FIXTURE_DIR, f"{name}.case.json")


def _dump(path: str, payload: dict) -> None:
    """Write UTF-8 with `\\n` endings, deterministically. Streams are JSON
    strings, so a `core.autocrlf` checkout cannot corrupt an expectation."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False,
                  sort_keys=False)
        handle.write("\n")


def write() -> int:
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    entries = []
    for case in cases():
        try:
            expected = (case.expected if case.oracle == "owen-convention"
                        else _expectation(case))
        except NonDeterministic as exc:
            print(f"cli_ownir: refusing to write — {exc}")
            return 1
        _dump(_case_path(case.name), {
            "cli_ownir_version": CLI_OWNIR_VERSION,
            "argv": case.argv,
            "cwd": case.cwd,
            "env": case.env,
            "expected": expected,
        })
        entries.append({"name": case.name, "oracle": case.oracle,
                        "rules": case.rules, "pins": case.pins})
    _dump(MANIFEST, {
        "comment": (
            "The frozen `own-cli ownir` CLI contract (#261 261.B). Authoritative "
            "via `python tests/test_cli_ownir_fixtures.py --write` on LINUX; "
            "replayed against the built binary with zero Python by "
            "rust/crates/own-cli/tests/replay.rs on Linux and Windows. `oracle` "
            "says who authored a case's bytes: `python` an executed reference "
            "run, `python-docstring` the same where the bytes are the whole "
            "module docstring on stdout (frozen as measured AND flagged so the "
            "owner can declare that class a defect), `owen-convention` the "
            "top-level shell, which has no Python byte oracle at all."),
        "cli_ownir_version": CLI_OWNIR_VERSION,
        "own_cli_version": OWN_CLI_VERSION,
        "shell_usage": SHELL_USAGE,
        "ownir_usage": OWNIR_USAGE,
        "unknown_command_line": _UNKNOWN_COMMAND,
        "os_error_placeholder": OS_ERROR,
        "cases": entries,
    })
    print(f"cli_ownir fixtures written: {len(entries)} cases -> {FIXTURE_DIR}")
    return 0


def run() -> int:
    fails: list[str] = []
    checks = 0
    hint = "'python tests/test_cli_ownir_fixtures.py --write'"

    if not os.path.exists(MANIFEST):
        print(f"FAIL: cli_ownir manifest missing — run {hint}")
        return 1
    with open(MANIFEST, encoding="utf-8") as handle:
        manifest = json.load(handle)

    checks += 1
    if manifest.get("cli_ownir_version") != CLI_OWNIR_VERSION:
        fails.append(f"manifest cli_ownir_version is "
                     f"{manifest.get('cli_ownir_version')!r}, expected "
                     f"{CLI_OWNIR_VERSION}")

    # The owen-convention surface has one source of truth, and it is here.
    for key, want in (("shell_usage", SHELL_USAGE),
                      ("ownir_usage", OWNIR_USAGE),
                      ("own_cli_version", OWN_CLI_VERSION)):
        checks += 1
        if manifest.get(key) != want:
            fails.append(f"manifest {key} has drifted from this module — "
                         f"the binary shares it, so run {hint}")

    declared = cases()
    by_name = {c.name: c for c in declared}
    listed = [e["name"] for e in manifest.get("cases", [])]

    checks += 1
    if listed != [c.name for c in declared]:
        fails.append("manifest case list differs from the declared cases "
                     f"(stale or reordered) — run {hint}")

    # No orphan case files: a file nobody lists is a fixture nobody replays.
    on_disk = {f[:-len(".case.json")] for f in os.listdir(FIXTURE_DIR)
               if f.endswith(".case.json")}
    checks += 1
    for orphan in sorted(on_disk - set(by_name)):
        fails.append(f"orphan case file {orphan}.case.json — run {hint}")

    for case in declared:
        path = _case_path(case.name)
        checks += 1
        if not os.path.exists(path):
            fails.append(f"missing case file for {case.name!r} — run {hint}")
            continue
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        if stored.get("cli_ownir_version") != CLI_OWNIR_VERSION:
            fails.append(f"{case.name}: cli_ownir_version drift")
            continue
        if stored.get("argv") != case.argv or stored.get("cwd") != case.cwd:
            fails.append(f"{case.name}: argv/cwd differ from the declaration "
                         f"— run {hint}")
            continue
        if case.oracle == "owen-convention":
            # No Python to consult: the stored bytes must still be the ones
            # this module authors.
            if stored.get("expected") != case.expected:
                fails.append(f"{case.name}: the owen-convention expectation "
                             f"has drifted — run {hint}")
            continue
        try:
            fresh = _expectation(case)
        except NonDeterministic as exc:
            fails.append(str(exc))
            continue
        if stored.get("expected") != fresh:
            fails.append(
                f"{case.name}: the frozen bytes are no longer what the "
                f"reference produces.\n    stored: "
                f"{json.dumps(stored.get('expected'), ensure_ascii=False)}\n"
                f"    fresh : {json.dumps(fresh, ensure_ascii=False)}\n"
                f"  If Python moved deliberately, run {hint}; if it did not, "
                f"this is a regression.")

    if fails:
        for failure in fails:
            print(f"FAIL: cli_ownir {failure}")
        return 1
    print(f"cli_ownir CLI contract OK: {checks} checks over {len(declared)} "
          f"cases (Python oracle; the Rust replay runs the binary)")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
