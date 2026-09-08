//! The three frozen text surfaces the binary prints, and the one rule about
//! how they are written down.
//!
//! Each is a `concat!` of one string literal PER SOURCE LINE, every literal
//! ending in `\n`. That is not a style choice: a checkout with
//! `core.autocrlf` on rewrites line *endings*, and no literal here contains
//! one, so the bytes this binary prints cannot depend on how the tree was
//! checked out. A single multi-line raw string would carry `\r\n` on such a
//! checkout and silently fail the byte contract on Windows only. (#343.)
//!
//! * [`OWNLANG_DOCSTRING`] is the REFERENCE's module docstring, reproduced
//!   byte for byte. `python -m ownlang ownir` prints it to stdout with exit 2
//!   for a positional-count error or an unknown argument, and C-1 draws the
//!   oracle boundary at the surface rather than at that internal print branch
//!   — so these bytes are the contract as measured. The fixture marks that
//!   class `oracle: "python-docstring"` so the owner can see what was frozen.
//! * [`SHELL_USAGE`] and [`OWNIR_USAGE`] have NO Python oracle. They are the
//!   `owen`-convention parity surface C-1 creates, authored once and shared
//!   with `tests/fixtures/cli_ownir/manifest.json`; `tests/replay.rs` asserts
//!   the two copies are equal, so they cannot drift apart.

/// The reference's module docstring, byte for byte (`ownlang/__main__.py`).
pub(crate) const OWNLANG_DOCSTRING: &str = concat!(
    "\n",
    "Command-line driver for the OwnLang PoC.\n",
    "\n",
    "    python -m ownlang check  file.own      # report ownership diagnostics\n",
    "    python -m ownlang check  file.own --format sarif   # SARIF 2.1.0 log (code scanning)\n",
    "    python -m ownlang emit   file.own      # check, then print generated C#\n",
    "    python -m ownlang cfg    file.own      # dump the control-flow graph (human debug view)\n",
    "    python -m ownlang cfg    file.own --format json   # canonical CFG JSON (oracle seam)\n",
    "    python -m ownlang report file.own      # buffer storage report + .ownreport.json\n",
    "    python -m ownlang ownir  facts.json    # check OwnIR facts extracted from C# (P-001)\n",
    "    python -m ownlang ownir  facts.json --format github|msbuild|human|sarif\n",
    "    python -m ownlang summaries facts.json # dump solved method-ownership summaries\n",
    "                                           # (MOS) + extern log — deterministic JSON\n",
    "    python -m ownlang explain OWN001 [DI002 ...]     # explain diagnostic code(s): what/why/fix\n",
    "    python -m ownlang explain --json findings.json   # explain every code in a findings/SARIF file\n",
    "\n",
    "`explain` is the diagnostic catalogue side of the CLI (the `ownsharp explain` the\n",
    "roslyn-tools-shaped surface advertises): it prints what a code means, why it fires,\n",
    "and how to fix it. It lives in the core, next to the catalogue, because there is one\n",
    "checker — the C# extractor emits facts, it does not own the diagnostics.\n",
    "\n",
    "`--format` selects the finding surface. On `ownir`: `human` (default CLI line),\n",
    "`github` (CI annotations on the PR diff), `msbuild` (VS Error List), or `sarif`\n",
    "(a SARIF 2.1.0 log — GitHub code scanning, and the cross-tool oracle reads it too).\n",
    "On `check` it is `human` (default) or `sarif` — the `.own` flow diagnostics as a\n",
    "SARIF log carrying each finding's evidence slice (relatedLocations / codeFlows);\n",
    "`github`/`msbuild` are ownir-only (they render a Finding, not a Diagnostic).\n",
    "`--severity` (ownir only) picks how the host shows a finding — `error` (default,\n",
    "fails a build / red check) or `warning` (advisory). It is a presentation choice;\n",
    "the finding is still the core's verdict.\n",
    "`--verbosity` (ownir only) is `quiet` (errors only — hide the advisory notes:\n",
    "OWN050 \"leakage analysis skipped\", OWN051 \"ownership transfer unverified\",\n",
    "OWN052 \"summaries skipped\"), `normal` (default), or `verbose` (also print a\n",
    "per-code breakdown).\n",
    "\n",
    "Exit code is non-zero if any error-level diagnostic was produced.\n",
);

/// The top-level shell's help. Shared with the fixture manifest.
pub(crate) const SHELL_USAGE: &str = concat!(
    "own-cli — the Own.NET core as a native executable.\n",
    "\n",
    "Usage:\n",
    "  own-cli ownir <facts.json> [options]   check OwnIR facts extracted from C#\n",
    "\n",
    "Options (ownir):\n",
    "  --format {human|github|msbuild|sarif}  finding surface (default: human)\n",
    "  --severity {error|warning}             how a finding is shown (default: error)\n",
    "  --verbosity {quiet|normal|verbose}     quiet hides the advisory notes;\n",
    "                                         verbose adds a per-code breakdown\n",
    "                                         (default: normal)\n",
    "  --help, -h                             print this help\n",
    "  --version                              print the version\n",
    "\n",
    "Both `--flag value` and `--flag=value` are accepted. `ownir` takes exactly one\n",
    "positional argument, the facts file; there is no `--` separator and there are\n",
    "no short flags.\n",
    "\n",
    "Exit codes:\n",
    "  0  clean\n",
    "  1  findings — any non-advisory, unsuppressed finding, independent of\n",
    "     --severity\n",
    "  2  usage error, or a facts document the strict door refuses\n",
    "  70 internal error — a bug in the analyzer, never silence\n",
);

/// The `ownir` subcommand's usage. C-1 declares the reference's reaction to
/// `--help` a defect and does not port it: this is printed to stdout with exit
/// 0 instead, the shell convention extended to the subcommand.
pub(crate) const OWNIR_USAGE: &str = concat!(
    "own-cli ownir — check OwnIR facts extracted from C# by the Roslyn frontend.\n",
    "\n",
    "Usage:\n",
    "  own-cli ownir <facts.json> [--format F] [--severity S] [--verbosity V]\n",
    "\n",
    "Options:\n",
    "  --format {human|github|msbuild|sarif}  human is the default CLI line, github\n",
    "                                         a CI annotation, msbuild the VS Error\n",
    "                                         List line, sarif a SARIF 2.1.0 log\n",
    "  --severity {error|warning}             how the host shows a finding; it never\n",
    "                                         changes the exit code\n",
    "  --verbosity {quiet|normal|verbose}     quiet hides the advisory notes\n",
    "                                         (OWN050/051/052, OBL005); verbose adds\n",
    "                                         a per-code breakdown over every\n",
    "                                         finding, suppressed ones included\n",
    "\n",
    "Both `--flag value` and `--flag=value` are accepted. Exactly one positional\n",
    "argument; there is no `--` separator and there are no short flags.\n",
    "\n",
    "Exit codes:\n",
    "  0  no leaks\n",
    "  1  at least one non-advisory, unsuppressed finding\n",
    "  2  usage error, or a facts document the strict door refuses\n",
    "  70 internal error — a bug in the analyzer, never silence\n",
);
