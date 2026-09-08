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

**Not measured: the Windows reference's non-ASCII output (§4).** The reference
`print`s through the console/pipe encoding, so a Windows run may emit different
bytes or fail with `UnicodeEncodeError`. This environment is Linux-only. The
fixture is therefore generated on Linux, its `oracle: "python"` cases are
re-verified against the reference by the `tests` matrix on `ubuntu-latest`, and
the Windows leg replays the **frozen bytes** against the Rust binary — which is
what #261's acceptance asks for. A platform-dependent *reference* would be a
Python-first question and a stop; this task did not have the platform to ask it
on, and says so rather than normalizing it away.

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

**Not pinned, and the reason:** the reference's stderr is a traceback whose text
**changes between trials** (it names whichever line the interrupt landed on).
The fixture writer refuses a non-deterministic case by construction, and pinning
only half of a case would be pinning less than was measured. Windows was not
measurable in this environment (§4). `130` is not invented anywhere.

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
  the campaign registration.

**No existing fixture moves, and nothing under `ownlang/` is touched.**
