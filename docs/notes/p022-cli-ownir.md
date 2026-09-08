# P-022 step 7b (#261, 261.B) — `own-cli ownir`: the measured reference, the frozen CLI contract

> **Scope of this note.** It is the record of the **production Rust OwnIR
> executable** — the binary `own-cli` with its single subcommand `ownir` — and
> of the measurement that produced its fixture. The contract it runs under is
> #261's ratified decision packet (261.A: C-1..C-5 and the stdin / panic /
> death / SIGINT rulings), reproduced in that issue's body. **This note may not
> reopen any of it.** What #345 adds to the same binary later (`cfg`,
> `summaries`, `explain`, `.own check`, `emit`) is deliberately absent here, and
> `report` is struck (C-2), not deferred.
>
> Python is the oracle and does not move: nothing under `ownlang/` changed in
> this work, and no existing fixture under `tests/fixtures/` was regenerated or
> relocated.

**Where the numbers are.** Every count this work produced — fixture cases by
rule and by oracle class, the mutation campaign's outcome — lives in
[`docs/generated/p022-cli-census.md`](../generated/p022-cli-census.md) and
[`docs/generated/p022-cli-mutations.md`](../generated/p022-cli-mutations.md),
rendered by `scripts/render_checkpoint_status.py`, and is reached from here by
link. No count is typed into this prose.

---

## §1 — What the reference actually does, measured

Everything below was **executed** against `python -m ownlang ownir` on this
tree, not read off the module docstring. Where the docstring and the code
disagree, the code is the contract and the fixture proves it.

**Host of record.** Linux (`ubuntu`-class container), CPython 3.11.15, repo
root as the working directory. The CI `tests` job re-verifies every
`oracle: "python"` case against 3.11/3.12/3.13 on `ubuntu-latest`.

### 1.1 The usage surface after `ownir`

Every one of these is *after* `ownir` is selected, so by C-1 every one of them
is contract **as measured** — the reference's stream, text and exit — with the
single declared-defect exception noted below.

| invocation | stream | exit | what comes out |
|---|---|---|---|
| `ownir` (no positional) | **stdout** | 2 | the whole module docstring |
| `ownir <facts> <facts>` (two positionals) | **stdout** | 2 | the whole module docstring |
| `ownir --bogus <facts>` (unknown flag **with** a path) | **stdout** | 2 | the whole module docstring |
| `ownir -- <facts>` (`--` is not a separator) | **stdout** | 2 | the whole module docstring |
| `ownir --bogus` (unknown flag **without** a path) | stderr | 2 | `--bogus: error: cannot read --bogus: <OS_ERROR>` |
| `ownir <facts> --format` (missing value) | stderr | 2 | `--format requires a value` |
| `ownir <facts> --severity` / `--verbosity` | stderr | 2 | `--severity requires a value` / `--verbosity requires a value` |
| `ownir <facts> --format x` | stderr | 2 | `unknown --format 'x' (choose: github, human, json, msbuild, sarif)` |
| `ownir <facts> --format=` (empty value) | stderr | 2 | `unknown --format '' (choose: …)` |
| `ownir <facts> --format --severity` (flag as value) | stderr | 2 | `unknown --format '--severity' (choose: …)` |
| `ownir <facts> --severity x` | stderr | 2 | `unknown --severity 'x' (choose: error, warning)` |
| `ownir <facts> --verbosity x` | stderr | 2 | `unknown --verbosity 'x' (choose: normal, quiet, verbose)` |
| `ownir <facts> --format json` | stderr | 2 | `ownir --format must be one of github/human/msbuild/sarif (got 'json')` |
| `ownir <facts> --format=sarif` (the `=` spelling) | — | 0/1 | accepted, identical to the space spelling |
| `ownir <facts> --format=human --format=sarif` | — | 0/1 | **last flag wins**; a duplicate is not an error |
| `ownir --help` | stderr | 2 | `--help: error: cannot read --help: <OS_ERROR>` — **declared a defect (C-1)** |
| `ownir -` | stderr | 2 | `-: error: cannot read -: <OS_ERROR>` — **out of contract (stdin ruling)** |

Two consequences are made visible rather than hidden, exactly as C-1 requires:

1. **The docstring-on-stdout class.** A positional-count error or an unknown
   argument prints the *entire* module docstring — the usage text of the whole
   PoC CLI, `report` and `emit` included — to **stdout**, with exit 2. Under
   C-1's boundary those bytes are the contract as measured. They are frozen and
   marked `oracle: "python-docstring"` in the manifest. The four cases in that
   class are, by fixture name:
   `usage-no-positional`, `usage-two-positionals`,
   `usage-unknown-flag-with-path`, `usage-double-dash-not-a-separator`.
   **The owner may declare that exact class a defect; this task does not make
   that call.**
2. **An unknown flag is not an error to the reference's parser.** It becomes a
   positional. With a real path present that is *two* positionals (the
   docstring); alone it is *one* positional and goes down the ordinary
   `cmd_ownir` path, where opening a file named `--bogus` fails. The two halves
   of that behaviour are separate fixture cases on purpose.

`--format x` lists **`json`** among the choices (it passes the global
`_FORMATS` gate) and is then rejected on the `ownir` branch by its own message,
which names the four surfaces in the order `github/human/msbuild/sarif`. Both
messages are frozen.

### 1.2 The display policy — four documents × four formats × two severities × three verbosities

Measured over the full 96-cell matrix. The documents are existing fixtures
wherever one had the shape; three inputs were added under
`tests/fixtures/cli_ownir/inputs/` because no existing document had the shape at
all (named below).

| shape | document | exit |
|---|---|---|
| clean | `tests/fixtures/verdict_renders/render_empty.facts.json` | 0 |
| leaky | `tests/fixtures/verdict_renders/render_columns.facts.json` | 1 |
| advisory-only (OWN052, no leak) | `tests/fixtures/verdict_renders/render_anchorless.facts.json` | 0 |
| all four bands (leak + intrinsic-warning leak + advisory + suppressed) | `tests/fixtures/verdict_renders/render_tiers_and_levels.facts.json` | 1 |
| **suppressed-only** (new) | `cli_ownir/inputs/suppressed_only.facts.json` | 0 |
| **non-ASCII `file`** (new) | `cli_ownir/inputs/nonascii_file.facts.json` | 1 |
| **empty-string `ignore_reason`** (new) | `cli_ownir/inputs/empty_ignore_reason.facts.json` | 1 |
| **spaced + non-ASCII *path*** (new) | `cli_ownir/inputs/pa th ünïcødé/facts.json` | 1 |

What the matrix proves, each one a named fixture control:

- **The exit code is independent of `--severity`.** Across all 24 cells per
  document the observed exit set is a *singleton*: clean `{0}`, leaky `{1}`,
  advisory-only `{0}`, all-bands `{1}`. The docstring's "non-zero if any
  error-level diagnostic" is **not** the contract; `return 1 if leaks else 0`
  is, where `leaks` are the non-advisory, non-suppressed findings. `--verbosity`
  does not move it either.
- **`quiet` hides advisories and leaves the exit alone.** The stream loses the
  advisory lines and the summary reads `(N advisory hidden)` instead of
  `, N advisory (CODES)`. Nothing else changes.
- **The `ok` line fires on `not shown`, suppressions included.** The
  suppressed-only document prints
  `<path>: ok — no subscription leaks found` *and*
  `0 findings, 1 suppressed ([OwnIgnore]).` — both, in one run, at exit 0. The
  em dash is U+2014 and is not ASCII.
- **The verbose `by code:` breakdown counts every finding.** On the all-bands
  document it reports `OWN001=3` while only two OWN001 lines are shown; on the
  suppressed-only document it reports `OWN001=1` while *nothing* is shown. It
  iterates `findings`, never `shown`.
- **The stream split is per format.** `human` writes findings *and* the summary
  to stdout (stderr is empty); `github`, `msbuild` and `sarif` write the
  machine payload to stdout and the summary to **stderr**.
- **A clean `github`/`msbuild` run writes zero bytes to stdout.** Verified for
  every severity/verbosity cell of the clean document.
- **SARIF carries `shown + suppressed`.** On the all-bands document `quiet`
  yields three results (2 leaks + 1 suppressed) and `normal` four (3 active + 1
  suppressed).
- **An empty-string `ignore_reason` does not suppress** (BR-V6): the document
  exits 1 with the finding shown. Measured, not assumed.

### 1.3 The SARIF byte shape on stdout is **not** the BR-V9 golden's

This is the one place where two byte shapes come out of one builder, and the
difference is load-bearing:

| surface | emitter | non-ASCII |
|---|---|---|
| the CLI's `--format sarif` stdout | `json.dumps(…, indent=2)` — `ensure_ascii` **defaults to True** | escaped `\uXXXX` |
| `tests/fixtures/verdict_renders/*.renders.json` (BR-V9) | the fixture writer, `ensure_ascii=False` | literal UTF-8 bytes |

Measured on the all-bands document: the CLI's SARIF stdout is **pure ASCII**,
carries the six ASCII characters `\u2014` where the message has an em dash, and ends in exactly one
`\n`. The BR-V9 golden for the same document carries the literal `e2 80 94`
bytes and no escape. **The builder is not touched.** The CLI path gets its own
ASCII-escaping serializer; `own_bridge::build_sarif` stays the single source of
the document's *shape*.

The astral case is measured too: with `U+1F600` in a `file` field the CLI's
SARIF emits the **surrogate pair** `\ud83d\ude00`, while the `human`/`github`/
`msbuild` lines carry the character itself.

### 1.4 Byte-level inputs, and the one that is not pinnable

| input | exit | stderr |
|---|---|---|
| missing file | 2 | `<path>: error: cannot read <path>: <OS_ERROR>` |
| a directory | 2 | `<path>: error: cannot read <path>: <OS_ERROR>` |
| empty file | 2 | `<path>: error: <path> is not valid JSON: Expecting value: line 1 column 1 (char 0)` |
| truncated JSON | 2 | `… is not valid JSON: Expecting value: line 1 column 37 (char 36)` |
| UTF-8 BOM | 2 | `… is not valid JSON: Unexpected UTF-8 BOM (decode using utf-8-sig): …` |
| root is not an object | 2 | `<path>: error: OwnIR root must be a JSON object` |
| `ownir_version` mismatch | 2 | `<path>: error: OwnIR facts are schema v99, but this core understands v0. Build the Roslyn extractor and the Python core from the same commit — …` |
| **invalid UTF-8** | **70** | `ownlang: internal error: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 45: invalid start byte` + the second line |

**Stop condition — invalid UTF-8 exits 70 (§5.1).** `load()` converts `OSError`
and `JSONDecodeError` and nothing else; a `UnicodeDecodeError` is neither, so it
escapes to `run()`'s catch-all. Per the brief this is reported, **not pinned**:
whether a crash on malformed input is a contract or a Python-first refusal to
add is the owner's decision. No fixture case freezes it and no refusal was
invented for it.

**Stop condition — strict-door message drift (§5.2).** Two of the refusal
classes above cannot be reproduced by the Rust door as it stands today. Details,
with the exact bytes, in §5.

### 1.5 OS error text — the one placeholder

The `cannot read <path>: ` tail is platform-native: Linux produces
`[Errno 2] No such file or directory: '<path>'` and `[Errno 21] Is a directory:
'<path>'`; Windows refuses a directory with `[Errno 13] Permission denied`.

**The decision, written down:** the contract is the line **up to and including**
`cannot read <path>: `, byte-exact; the tail is recorded per platform in the
case file and matched through the single placeholder `<OS_ERROR>`, which
consumes the rest of that line and must consume something non-empty. This is
the same choice `tests/test_cli_contract.py` already made with its
`"cannot read"` substring, made explicit and narrower. `<OS_ERROR>` is the
**only** placeholder the fixture format admits, and it may appear only on a line
that carries an OS error text.

### 1.6 Paths

Measured through all four formats:

- a `file` field carrying a **backslash** (`render_escaping.facts.json`): the
  `github` render escapes `:` and `,` as `%3A`/`%2C` and leaves the backslash;
  SARIF folds `\` to `/` in the `uri`.
- a `file` field carrying **non-ASCII** including an astral character: §1.3.
- a facts **path** through a directory carrying both a space and non-ASCII
  (`inputs/pa th ünïcødé/facts.json`): accepted, and the path is echoed
  verbatim in the `ok`/summary lines.

**The Windows reference was measured, and it diverges (§5.3).** This
environment is Linux-only, so the measurement was taken on `windows-latest`
through a temporary CI workflow and is recorded in §1.9. It is a **stop
condition**: the reference is not byte-portable, and the divergence is far
wider than the non-ASCII cases alone. The fixture stays Linux-generated, as the
brief requires, and nothing about the Windows reference is normalized away.

### 1.7 SIGINT — measured, **not pinned**

A synthesized 1.7 MB facts document (400 components × 40 subscriptions, ~1.3 s
of work; not committed) interrupted mid-run on Linux, five trials:

| subject | exit status | stdout | stderr |
|---|---|---|---|
| `python -m ownlang ownir … --format sarif` | killed by **SIGINT** (signal 2) every trial | 0 bytes | a full `KeyboardInterrupt` traceback |
| a throwaway Rust binary with no signal handler | killed by **SIGINT** (signal 2) every trial | 0 bytes | empty |

`KeyboardInterrupt` is a `BaseException`, so `run()`'s `except Exception`
catch-all never sees it: the reference dies by the signal rather than exiting
70. A plain Rust binary installs no handler and dies the same way, so the two
agree on the **exit disposition** on Linux without anything being written down.

The Windows measurement is in §1.9, and it is a *different* answer.

**Not pinned, and the reason:** the reference's stderr on Linux is a traceback
whose text **changes between trials** (it names whichever line the interrupt
landed on), and the two platforms do not agree on the exit status either. The
fixture writer refuses a non-deterministic case by construction, and pinning
only half of a case would be pinning less than was measured. `130` is not
invented anywhere, and neither is a cross-platform interruption contract.

### 1.8 Closed stdout — measured, deterministic, **not expressible as a case**

`… --format sarif | head -c 1`, three trials, identical every time:

```text
exit 70
ownlang: internal error: BrokenPipeError: [Errno 32] Broken pipe
  This is a bug in the analyzer, not in your code. Re-run with OWNLANG_DEBUG=1 for the full traceback and please report it.
```

So a write failure on stdout is the **internal-error path**, not a usage error
and not a silent success. The binary matches that *shape* — exit 70 with its own
two-line internal-error diagnostic — and is unit-covered for it. It is not a
fixture case because the case format (`argv`/`cwd`/`env` → captured streams) has
no way to close the consumer's pipe; recording it here is the alternative to
pretending it was frozen.

### 1.9 The Windows reference, measured

Taken on `windows-latest` (Windows 10.0.26100, CPython 3.11.9) through a
temporary CI workflow, because this implementing environment is Linux-only and
#261 rules that interruption is measured on both platforms **before** anything
is written down. The run:
[actions/runs/34198702579](https://github.com/PhysShell/Own.NET/actions/runs/34198702579).
The workflow and its script were deleted once these numbers landed here; the
commit that added them is the record that the measurement was taken.

`sys.stdout.encoding` on a piped Windows stdout is **`cp1252`**, and that one
fact drives most of what follows.

| case | Linux reference | Windows reference |
|---|---|---|
| non-ASCII `file`, `human` | exit 1, UTF-8 bytes | **exit 70** — `UnicodeEncodeError: 'charmap' codec can't encode characters in position 12-14: character maps to <undefined>` |
| non-ASCII `file`, `github` | exit 1, UTF-8 bytes | **exit 70**, the same encoder failure |
| non-ASCII `file`, `sarif` | exit 1, pure ASCII | exit 1, pure ASCII — the ASCII escaping saves this one |
| the em dash in the `ok` line | `e2 80 94` (UTF-8) | **`97`** (cp1252) |
| every line ending | `\n` | **`\r\n`** (text-mode `print` translates) |
| a missing file | `[Errno 2] No such file or directory` | the same |
| a directory | `[Errno 21] Is a directory` | `[Errno 13] Permission denied` |
| closed stdout | exit 70, `BrokenPipeError`, 3/3 trials | **the same**, 3/3 trials |
| interruption | killed by **SIGINT** (signal 2); stderr a `KeyboardInterrupt` traceback whose text varies per trial | **`0xC000013A`** (`STATUS_CONTROL_C_EXIT`, 3221225786); stdout 0 bytes; **stderr empty**, 3/3 trials |

Two of these are worth naming out loud:

* **the em dash is in almost every case.** It is in the `ok` line and in most
  finding messages, so the CRLF/cp1252 pair means the Windows reference
  produces different bytes for nearly every case in the fixture, not only the
  ones with non-ASCII inputs;
* **interruption is deterministic on Windows and not on Linux.** Windows gives
  a fixed status and an empty stderr; Linux gives a fixed *disposition* and a
  varying traceback. Neither is pinned, because a contract that held on one
  platform and not the other would not be a contract.

---

## §2 — The fixture format, the boundary as applied, and the churn budget

### 2.1 The format

`tests/fixtures/cli_ownir/` holds `manifest.json` plus one `<name>.case.json`
per case.

```jsonc
// manifest.json
{"comment": "...", "cli_ownir_version": 1,
 "shell_usage": "<the C-1 help text, authored once, shared with the binary>",
 "ownir_usage": "<the ownir help text, authored once, shared with the binary>",
 "cases": [{"name": "...", "oracle": "python|python-docstring|owen-convention",
            "rules": ["exit-independent-of-severity", ...],
            "pins": ["..."]}]}
```

```jsonc
// <name>.case.json
{"cli_ownir_version": 1,
 "argv": ["ownir", "inputs/…"],          // relative to the fixture dir
 "cwd": ".",                              // relative to the fixture dir
 "env": {"OWNLANG_DEBUG": "1"} | {},
 "expected": {"exit": 2, "stdout": "…", "stderr": "…",
              "os_error_tail": {"linux": "…", "windows": "…"} | null}}
```

Streams are **JSON strings** (`\n` escaped), never raw text files: a checkout
with `core.autocrlf` on must not be able to corrupt an expectation. That is the
#343 lesson applied to this family, and it is why no `.txt` expectation exists
anywhere under it.

### 2.2 The oracle classes, so a reader can tell them apart

| class | what authored the bytes | cases |
|---|---|---|
| `python` | an executed `python -m ownlang ownir` run | everything after `ownir` except the four below and the declared defect |
| `python-docstring` | the same, and the bytes happen to be the **whole module docstring on stdout** — flagged so the owner can declare the class a defect | §1.1 |
| `owen-convention` | **no Python oracle exists**: authored once from the checked-in help text in the manifest, following the public `owen` convention (`Program.cs` 14–43) | the shell's empty invocation, `--help`, `-h`, `--version`, unknown command; and `ownir --help`, the one declared defect |

### 2.3 The C-1 boundary as applied

The boundary is the **surface**, never the reference's internal print branch:

```text
own-cli                  -> the shell help on stdout, exit 2      (owen convention)
own-cli --help | -h      -> the shell help on stdout, exit 0      (owen convention)
own-cli --version        -> "own-cli <version>" on stdout, exit 0 (owen convention)
own-cli <garbage>        -> one error line + help on stderr, exit 2 (owen convention)
own-cli ownir --help     -> the ownir usage on stdout, exit 0     (declared defect, not ported)
own-cli ownir <anything else> -> exactly what the reference does  (measured)
```

The shell help text has no Python byte oracle. It is written **once**, lives in
the manifest, and the binary and the fixture share that one source — a test
fails if they drift.

### 2.4 The churn budget, written before anything moved

New files only:

- `rust/crates/own-cli/**` — the crate, its binary, its tests;
- `tests/fixtures/cli_ownir/**` — the manifest, the cases, the four new inputs;
- `tests/test_cli_ownir_fixtures.py` — the writer/verifier;
- `docs/evidence/p022-cli-1.json` — the mutation campaign;
- `docs/generated/p022-cli-census.md`, `docs/generated/p022-cli-mutations.md`;
- this note.

Named existing surfaces, edited and nothing else:

- `rust/Cargo.toml` — the workspace member list, and the **stale `panic`
  design note** (§6);
- `rust/crates/own-diagnostics/tests/dag.rs` — `own-cli`'s edges;
- `rust/README.md` — the `own-cli` row;
- `docs/proposals/P-022-rust-core-migration.md` — row 7b and the `panic` mirror;
- `docs/proposals/README.md` — the index row;
- `.github/workflows/ci.yml` — one new job;
- `scripts/render_checkpoint_status.py`, `tests/test_checkpoint_status.py` —
  the campaign registration;
- `scripts/mutate_campaign.py` — one line and its docstring: the catcher
  validator special-cased `src/lib.rs` and not `src/main.rs`, and `own-cli` is
  the first binary crate whose unit tests a campaign names (§6);
- `docs/generated/p022-coord-census.md` — **regenerated, not edited**: it sweeps
  `tests/fixtures/**` for OwnIR documents and the four new inputs are four more
  of them.

**No existing fixture moves, and nothing under `ownlang/` is touched.**

---

## §3 — What landed

`rust/crates/own-cli/` — a binary crate with one subcommand, and the shape
#345's commands can join rather than a special case they would have to rewrite:
one dispatch table, one help surface.

* **the shell** answers the C-1 convention: an empty invocation is help on
  stdout at exit 2, `--help`/`-h` the same help at exit 0, `--version` is
  `own-cli <CARGO_PKG_VERSION>`, and an unknown command is one error line plus
  the help on **stderr** at exit 2. The empty invocation and the unknown command
  are distinct cases because `owen` makes them distinct;
* **`ownir`** takes the reference's argv — one positional, `--format`,
  `--severity`, `--verbosity`, both the `--flag V` and `--flag=V` spellings, no
  `--` separator, no short flags — and answers every usage error exactly as the
  reference does, the docstring on stdout included;
* **the display policy** is a pure function of `&[Finding]` and the three
  options, so every trap is a unit test rather than a process invocation. It
  lives in the CLI crate because it is CLI logic: which findings are shown,
  the `ok` and summary lines, the verbosity variants, the stream split, and
  `1 if leaks else 0`;
* **the renders are reused, never re-derived.** `own_bridge::check_facts` is the
  analysis; `own_bridge::render_finding` and `own_bridge::build_sarif` are the
  only renderers called. What the CLI adds is the *serialization*, because
  `cmd_ownir` writes the SARIF document `json.dumps(indent=2)` does — ASCII
  escaped — and the BR-V9 goldens are `ensure_ascii=False`. The builder is not
  touched;
* **the process contract** under `panic = "unwind"`: a hook installed first
  thing in `main` suppresses the default panic output and records the payload,
  and a top-level `catch_unwind` turns the unwind into one actionable stderr
  diagnostic and exit 70. The hook alone would only *observe* the panic and the
  process would still exit 101. Under `OWNLANG_DEBUG` the payload and a captured
  backtrace print and the exit is still 70;
* **an off-by-default `fault-injection` feature** gates two dev-only hooks that
  force each failure mode, so both rulings are measured rather than asserted.
  No production build carries them.

The DAG gains exactly two edges — `own-cli -> own-ir` and `own-cli ->
own-bridge` — registered in `own-diagnostics/tests/dag.rs`, where an
unregistered member fails the whole `cargo test`. No `own-codegen`, no
`own-shadow`, no `sha2`.

**Nothing is wired.** `owen`, `own-check.sh`, `own-check.ps1`, `action.yml`,
`own-shadow-engine` and `scripts/shadow_compare.py` are untouched; the binary
knows nothing of Python and offers no engine selection, no compare mode and no
fallback. Python remains the public engine.

## §4 — The ledger, and where the numbers are

* the fixture cases by rule and by oracle class:
  [`docs/generated/p022-cli-census.md`](../generated/p022-cli-census.md);
* the mutation campaign:
  [`docs/generated/p022-cli-mutations.md`](../generated/p022-cli-mutations.md),
  from [`docs/evidence/p022-cli-1.json`](../evidence/p022-cli-1.json) and its
  recorded run.

The campaign runs **three layers** rather than a workspace sweep, because the
two failure-mode controls live behind the off-by-default feature and a campaign
that cannot run the layer holding a catcher cannot see it catch. The third
layer runs every *other* workspace member and is expected to catch nothing: a
catcher appearing there would mean a mutation reached past its target.

Two of the campaign's mutations exist as a pair because the first run said so.
`usage_error` and the docstring answer are two different paths to exit 2, and a
catcher named on one cannot see a mutation in the other. The wrong expectation
was corrected **and** the path it had named became its own mutation, rather than
the expectation being quietly dropped.

## §5 — Measured, not pinned; and the stop conditions

### 5.1 Invalid UTF-8 exits 70 on the reference — reported, not pinned

`load()` converts `OSError` and `JSONDecodeError` and nothing else, so a
`UnicodeDecodeError` escapes to `run()`'s catch-all:

```text
exit 70
ownlang: internal error: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 45: invalid start byte
  This is a bug in the analyzer, not in your code. Re-run with OWNLANG_DEBUG=1 for the full traceback and please report it.
```

**No fixture case freezes it and no refusal was invented for it.** Whether a
crash on malformed input is a contract or a Python-first refusal to add is the
owner's decision. The binary reproduces the *code and the shape* — exit 70 with
its own two-line internal-error diagnostic — and claims no byte parity, because
there is no oracle for a Python exception's `repr`.

### 5.2 The strict door's message drifts between the implementations

Two refusal classes cannot be reproduced by the Rust door as it stands. Exact
bytes, both sides:

**JSON syntax** (an empty file, a truncated document, a BOM):

```text
Python: <path>: error: <path> is not valid JSON: Expecting value: line 1 column 1 (char 0)
Rust  : <path>: error: not valid JSON: EOF while parsing a value at line 1 column 0
```

**The version gate** — the same sentence, two words apart:

```text
Python: ... Build the Roslyn extractor and the Python core from the same commit ...
Rust  : ... Build the extractor and the core from the same commit ...
```

The **shape and vocabulary** refusals agree byte for byte and are pinned:
`OwnIR root must be a JSON object`, and the BR-V9-pinned
`unknown OwnIR flow op 'try' (F.cs:2) — extractor/core vocabulary skew; ...`.

This is not a new defect so much as a boundary #259 drew on purpose:
`own-ir/tests/validation_replay.rs` says in its own docstring that what is
compared is "the **kind**, never the message", because "the reference funnels
every rejection into one `OwnIRError` whose strings are a human-facing
presentation aid; freezing them would make this a byte-comparison of two
languages' English." C-1 asks the CLI for the reference's message. The two
cannot both be satisfied without deciding whether the strict door's *message*
joins the byte-pinned surface — **which is the owner's call, on a #259
surface**. Nothing here patched Python and nothing here patched `own-ir`; the
affected classes are simply not in the fixture.

### 5.3 The Windows reference is not byte-portable — the platform stop

§1.9 has the table. The short form: on a piped Windows stdout the reference
encodes with `cp1252` and translates line endings, so it emits `\r\n` where
Linux emits `\n` and `97` where Linux emits `e2 80 94` — for the em dash that
appears in the `ok` line and in most finding messages. On the two non-ASCII
`file` cases it does not emit anything at all: it exits **70** with a
`UnicodeEncodeError`, where the Linux reference exits 1 with a finding.

The brief's instruction for this case is exact, and was followed: **a
platform-dependent reference is a Python-first question, and the fixture is
generated on Linux only until it is answered.** It was not normalized away, and
no fixture case was weakened to accommodate it.

What that leaves is worth stating plainly, because it is the useful half of the
finding: **the Rust binary is byte-identical on both platforms where the
reference is not.** It writes bytes through a locked handle with no encoding
layer and no line-ending translation, so the Linux-authored fixture replays
byte-for-byte on `windows-latest` — all cases, including the non-ASCII `file`
ones the Windows reference cannot produce. The unicode-and-space directory name
round-trips through a fresh Windows clone too.

### 5.4 Recorded, deterministic, and not expressible as a case

* **closed stdout** — exit 70 with the internal-error shape, 3/3 trials on both
  platforms. Not a fixture case because the case format (`argv`/`cwd`/`env` →
  captured streams) has no way to close the consumer's pipe; the binary matches
  the shape and is unit-covered for it.
* **interruption** — §1.7 and §1.9. Measured on both platforms, pinned on
  neither, for the reasons given there.
* **the uncatchable death** — `std::process::abort()` on Linux produced shell
  status **134** (SIGABRT), zero stdout, zero stderr. The number is recorded
  here and deliberately **not** asserted: #261 contracts no OS exit number for
  this case. What the test asserts is that the outcome is non-zero, outside
  `{0, 1, 2, 70}` and silent on stdout.
* **a non-UTF-8 argv** — `std::env::args_os` is converted lossily rather than
  with `std::env::args`, which panics on such an argument. A path that is not
  valid Unicode is outside the measured contract (the reference round-trips it
  through Python's `surrogateescape`, which has no fixture here) and fails with
  an ordinary "cannot read" rather than a crash. Recorded as a known deferred
  case.

## §6 — Tails

* **the `panic`-per-package design note** is corrected in `rust/Cargo.toml` and
  its P-022 mirror: Cargo cannot set `panic` per package — a profile applies to
  every target of a build — so "abort for `own-cli`, unwind for the LSP" was
  never a plan Cargo could execute. Corrected as a design note; nothing about
  the built artifacts moves.
* **`py_repr` is carried twice.** The identical helper is `pub(crate)` in
  `own-syntax`, and exporting it would need an `own-cli -> own-syntax` edge the
  architecture does not admit. A shared `own-pyparity` leaf is the eventual
  home, and #345 — which adds the commands whose errors interpolate far more
  `repr()`s — is where it starts to pay.
* **the campaign's catcher validator** special-cased `src/lib.rs` and not
  `src/main.rs`. `own-cli` is the first binary crate whose unit tests a campaign
  names, and without the fix every one of them read as "names a test that does
  not exist" while pointing at a test that plainly did.
* **for the owner to decide:** the docstring-on-stdout class (§1.1, four cases,
  frozen and flagged); whether a crash on malformed input is a contract (§5.1);
  whether the strict door's message joins the byte-pinned surface (§5.2); and
  what a non-byte-portable reference means for the Windows half of parity
  (§5.3).
* **for #345 to inherit:** the dispatch table and the single help surface are
  built to be joined rather than rewritten; the fixture family's format, its
  writer and its oracle classes generalize to any subcommand; and the
  `<OS_ERROR>` placeholder rule is already written down.

## §7 — Reproducing this

```bash
# regenerate the fixture from the reference (Linux; the authoring platform)
python tests/test_cli_ownir_fixtures.py --write

# verify the frozen bytes are still the reference's
python tests/test_cli_ownir_fixtures.py

# the steady-state gate: build the binary and replay, zero Python
cd rust && cargo test -p own-cli

# the two failure-mode controls (off in every production build)
cd rust && cargo test -p own-cli --features fault-injection --test faults

# the mutation campaign, on a clean tree
python scripts/mutate_campaign.py --campaign docs/evidence/p022-cli-1.json --run

# the generated fragments
python scripts/render_checkpoint_status.py --check
```
