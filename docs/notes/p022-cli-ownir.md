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

**Invalid UTF-8 exits 70 — a declared reference defect (§5.1).** `load()`
converts `OSError` and `JSONDecodeError` and nothing else; a
`UnicodeDecodeError` is neither, so it escapes to `run()`'s catch-all. Ruling 1
records it as a defect of the reference, excluded from #261's byte contract
pending a Python-first normalization before public cutover. No fixture case
freezes it.

**The other two refusal families are settled, differently (§5.2).** The
**Version** family was a Rust bug in our own text and is now byte-exact (ruling
2a). The **JSON-syntax** family keeps its CLI-owned wrapper byte-exact and
declares only the parser library's own detail, under the named boundary
**CLI-B1** (ruling 2b). Every other family — shape, vocabulary, identity,
location — is pinned byte-exact.

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
through a temporary CI workflow and is recorded in §1.9. The divergence is far
wider than the non-ASCII cases alone. The fixture stays Linux-generated and
nothing about the Windows reference is normalized away; §5.3 states the result
as three separate claims, of which **native-Windows Python parity is claim C and
is NOT claimed**.

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

## §5 — What was fixed, what is declared, and what is not claimed

### 5.1 Invalid UTF-8 — a declared **reference defect** (#261 ruling 1)

`load()` converts `OSError` and `JSONDecodeError` and nothing else, so a
`UnicodeDecodeError` escapes to `run()`'s catch-all:

```text
exit 70
ownlang: internal error: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 45: invalid start byte
  This is a bug in the analyzer, not in your code. Re-run with OWNLANG_DEBUG=1 for the full traceback and please report it.
```

**Status: a declared defect of the Python reference, excluded from #261's byte
contract pending a Python-first normalization before public cutover.** A debt
with a name and an owner, not a permanent constitutional exclusion.

The binary's `rc 70` + internal-error shape is sufficient for #261, and there is
no byte fixture. The reason is worth stating precisely, because an earlier draft
of this note got it wrong: it is **not** that no oracle exists — Python printed
one, and it is quoted above. It is that we **decline to make a CPython
exception's wording a cross-language contract**. Freezing that line would bind
the Rust implementation to the spelling of a `UnicodeDecodeError`, which is a
CPython implementation detail that no part of this project has decided to own.

**Python-first hygiene tail.** `UnicodeDecodeError` → `OwnIRError` → `rc 2`, so
a file that is not UTF-8 is refused by the strict door like every other
malformed input instead of crashing the run. To close **before public cutover**;
#261 does not block on it.

**Tracker state, as it actually stands.** #262 is the tracker of record: the
reviewer recorded this ruling there under *Known differences recorded ahead of
the packet* (2026-09-08). The #250 roadmap mirror is **pending reconciliation**
— queued, not yet written — so this note claims #262 and nothing more. An
earlier draft said the tail was "opened under #250/#262", which asserted a
tracker state this note is not the authority on and had not verified.

### 5.2 The strict door: one family **fixed**, one narrow boundary **declared**

The 1a32185 draft of this note lumped these together as "strict-door messages
differ". They are not one thing, and the review was right to split them.

#### 5.2a The Version family — FIXED to byte parity (#261 ruling 2a)

The `ownir_version` rejection text is **ours on both sides**, so a divergence
there was a Rust bug rather than a boundary. It is fixed.

**The taxonomy first**, because the corrected one has two rejection rows and not
three — an absent `ownir_version` is *accepted as v0* and carries no message, so
it is no control to reproduce:

```text
absent                  -> accepted as v0        (no message)
present, valid v0       -> accepted              (no message)
present, wrong type     -> Version rejection, repr-sensitive message
present, integer != v0  -> Version rejection, schema-mismatch message
```

**The census**, over both rejection rows and their value variants, measured on
this tree before anything was edited:

| control | Python | Rust *before* | Rust *after* |
|---|---|---|---|
| `ownir_version` absent | accept | accept | accept — same, no message |
| `= 0` | accept | accept | accept — same, no message |
| `= "0"` | `got '0'` | `got "0"` ✗ | `got '0'` ✓ |
| `= "x"` | `got 'x'` | `got "x"` ✗ | `got 'x'` ✓ |
| `= true` | `got True` | `got true` ✗ | `got True` ✓ |
| `= false` | `got False` | `got false` ✗ | `got False` ✓ |
| `= 0.0` | `got 0.0` | `got 0.0` ✓ | `got 0.0` ✓ |
| `= null` | `got None` | `got null` ✗ | `got None` ✓ |
| `= [1]` | `got [1]` | `got [1]` ✓ | `got [1]` ✓ |
| `= 99` / `1` / `-3` | `… Roslyn extractor … Python core …` | `… extractor … core …` ✗ | matches ✓ |

Two things the ruling's own list did not enumerate, found by taking the census
rather than trusting it: **`null` → `None`** is a third wrong-type divergence,
and **containers** diverge as well (`["a"]` is `['a']` to Python), because
`json` decodes them to `list`/`dict` and `repr` reprs their members.

**The layer, and why.** A pre-change consumer/churn census decided it, not
preference. `own-ir` states that its cross-language contract on this surface is
`OwnIrErrorKind` with the message a human-facing aid, so editing the text is a
deeper layer than #261 needs — unless nothing frozen depends on it:

| consumer of the old Version text | class | churn expected |
|---|---|---|
| `own-ir/src/strict.rs` (both messages) | production implementation | **the edit itself** |
| `own-ir/tests/roundtrip.rs` | unit test — asserts `contains("schema v1")` and `contains("v0")` | none: both substrings survive |
| `own-ir/tests/validation_replay.rs` | unit test — `contains(needle)` over a hardcoded list carrying **no** Version needle | none |
| `tests/fixtures/ownir_validation.json` | frozen ledger — **Python-authored**, carries **Python's** messages; the Rust replay compares KIND, never message | none: Rust never writes it |
| #260 repro/shadow evidence (`docs/evidence/`) | — | **none: no artifact carries any door refusal text** |
| generated docs | — | none |
| `own-cli` | production output | the point of the repair |

So the old text reached only `own-ir`'s implementation, two `own-ir` tests whose
assertions survive, and #261's own new CLI fixtures. Under R2's own rule that
sanctions the `own-ir` edit — and **measured after the change, zero `own-ir`
tests needed to move and no golden was regenerated.** Had the census found a
repro/shadow surface, the alignment would have gone into an `own-cli`
presentation adapter instead, so #260's evidence did not ride along behind #261.

Kind parity is untouched: #259 compares the kind, so cp1/validation stays green.
Every Version control is now a **pinned** CLI fixture case, `oracle: "python"`.

`py_repr_value` is a **third** copy of a helper `own-syntax` and `own-cli`
already carry — `own-ir` is the DAG leaf and may import neither. That is the
`own-pyparity` tail getting more expensive, recorded in §6.

##### The census above was too narrow, and here is what it missed (#261 R2b)

Everything in it is still true. It is also the wrong shape of measurement, and
the second review was right to say so. Each row picked a *value*; the oracle is
about a *value class*, and the four scalars chosen happen to be the classes
where a `serde_json::Value` and CPython's `json` agree. A `Value` is a **lossy**
rendering of the document for `repr` purposes, and three defects were hiding in
the loss:

| what `Value` loses | `Value` says | CPython says | why the first census could not see it |
|---|---|---|---|
| object key **order** (`Map` is a `BTreeMap`; `dict` is insertion-ordered) | `{'a': 2, 'b': 1}` | `{'b': 1, 'a': 2}` | its only object control had **one key**, and one key is order-invariant |
| float **spelling** (`Display` writes ryū's shortest form; `repr` pads the exponent) | `1e-6` | `1e-06` | its only float was `0.0`, which needs no exponent |
| integer **precision** (no `arbitrary_precision`, so an oversized literal arrives as `f64`) | `1e+31`, wrong-type arm | `100000…000`, **mismatch** arm | its integers all fit `i64` |

The third is not a spelling difference at all: a Python `int` has no width, so
an oversized *integral* version clears the reference's type check and takes its
**mismatch** branch (#261 ruling V3). Same document, different arm.

**The fix is a raw re-read, not a feature flag.** `own-ir` now reads
`json.loads(raw)["ownir_version"]` back out of the document text into a
`PyValue` — insertion-ordered dicts with CPython's rebind-in-place semantics for
a repeated key, arbitrary-precision integers kept as digits, and `int`/`float`
decided by the literal. `serde_json/preserve_order` and `arbitrary_precision`
would each fix a row by changing `Value` for **every crate in the workspace**
— map iteration order, number equality, `to_value` output — and #260's
canonical-domain evidence is measured against the current `Value`. So the
re-read is scoped to the one value whose spelling is contractual and runs on the
rejection path only. `serde_json` stays the only parser whose verdict decides
accept/reject; the re-read decides only how an already-certain rejection is
spelled.

**Then the sweep found a fourth.** 200 000 doubles through the production path
against CPython's `repr`: 7 mismatches, all the same shape. Where a double's
exact value sits **exactly midway** between two candidates of the shortest
round-trip length, CPython (David Gay's `dtoa`) rounds half to **even** and
Rust's shortest formatter does not — `-1128910513108089.25` is
`-1128910513108089.2` there and `...3` here, about one double in 3 000. The
digits now come from Rust's *exact* formatter asked for the shortest formatter's
length, which rounds half to even. Re-swept: **200 000 / 0**.

**The re-measurement, in two groups.** The groups are separate so the declared
divergences can never drift back into the byte denominator:

*Group 1 — the byte denominator.* 24 value classes, **24/24 byte-identical**:
the five float classes either side of both presentation boundaries, the
round-half-to-even tie, out-of-order and repeated-key and nested and empty
objects, quote-heavy and astral and plain strings, both bools, `null`, arrays,
oversized integers of both signs, the `i64` boundary, and an ordinary mismatch.
Then **20 000 randomized documents** — nested containers, repeated keys, the
whole string surface, oversized integers — **0 mismatches**.

*Group 2 — declared, and NOT in that denominator.*

| ruling | class | reference | this core | why it is declared |
|---|---|---|---|---|
| V1 | `NaN`, `Infinity`, `-Infinity` | `got nan` / `inf` / `-inf` | `not valid JSON` | CPython `json` extensions, not JSON. Teaching the Rust parser non-standard JSON to match an error message would widen what the product accepts |
| V2 | literal `-0` at the gate | **accepts** (an `int`) | `got -0.0` | the cross-parser encoding split #260 already froze. Emulating the acceptance is out of #261's scope, and reporting `0` would name a type we did not read and imply an acceptance we do not grant |
| V4 | Unicode table skew (see below) | escaped | printed | **new**, below |

`-0` *inside a container* is not V2 and is not declared: nothing there is being
type-checked, so the reference's own spelling is free to be reproduced, and is
(`[-0]` → `[0]` on both sides). That is why the stand-down is written as "the
value the type check is about" rather than "any `-0` anywhere".

**V4, found by this pass: the Unicode tables are independently versioned.**
`str.isprintable()` is a general-category question, and each side answers it
from the Unicode table it was **built** with. CPython 3.11.15 links Unicode
14.0.0; `unicode-properties` 0.1.4 ships 17.0.0. A whole-plane sweep — all
1 114 112 scalar values, both sides — puts the disagreement at exactly **15 097
code points**, every one of them `Cn` (unassigned) in 14.0.0 and assigned since.
No single static Unicode-property table can be byte-identical to every supported
CPython reference version on the code points whose classification differs
between them, so a pin is a reference-contract choice rather than a fix: the
reference's table is a property of the *interpreter build*, and a pin would buy
parity with one Python and silently lose it against another. Declared, measured, and out of
the denominator. It predates this pass — `is_printable` shipped in R2 — and it
has the same root cause as the other three: a control set chosen by hand.
`own-syntax` carries the same helper and therefore the same boundary; that is a
tail (§6), not a change #261 makes.

Its practical reach here is **nil, and measured rather than assumed**: no file in
the frozen CLI fixture family contains one of those code points, which is
why the `oracle: "python"` cases stay green on 3.11, 3.12 and 3.13 even though
those interpreters link three different Unicode tables. The boundary is real; it
is simply not something any case in this contract can reach.

**The census is now a test, not a table.** `own-ir/tests/version_repr_census.rs`
carries every group-1 row with the byte CPython produced for it, and group 2
pinned to what this core does with the reference's own answer written beside
each. Python authored those bytes once; the suite defends them with **zero
Python** from here on, and a new value class has to be added to the table rather
than merely not thought of. Campaign mutations M20–M23 attack the four defects
directly.

#### 5.2b CLI-B1 — the JSON parser detail, a named typed boundary (#261 ruling 2b)

```text
CLI-B1  JSON_PARSER_DETAIL   (applies iff OwnIrErrorKind == Json)
  pinned:   exit = 2 · stream = stderr · rejection kind = Json ·
            the FULL CLI-owned wrapper, byte-exact:
              "{path}: error: {path} is not valid JSON: "
  declared: only the bytes AFTER that exact prefix — the parser library's own
            text (CPython  "Expecting value: line 1 column 1 (char 0)"
                   serde_json "EOF while parsing a value at line 1 column 0")
```

It has a **name and a kind guard** on purpose: "the JSON parser's detail" cannot
quietly grow into "strict-door wording may differ". No `JSONDecodeError`
emulator was built.

**The wrapper was drifting, and that is fixed first.** The reference bakes the
path into the message inside `load()` and prints it again in `cmd_ownir`, so the
line carries the path **twice**; `own-ir` emitted it once, because
`from_json(&str)` has no path to bake. Relaxing everything after
`{path}: error: ` would have silently declared that missing half
implementation-defined too — far too much. An `own-cli` presentation adapter
guarded by `kind == Json` supplies the CLI-owned half, touching neither #259 nor
#260.

**The guard has a lock in it.** A `Json` rejection whose message does not start
with `own-ir`'s own `not valid JSON: ` prefix is a **broken internal invariant
of the Rust implementation**, not a JSON rejection to pass through: it takes the
internal-error path — `rc 70`, one actionable diagnostic — and **CLI-B1 does not
apply**. Never `rc 2`, never the whole message swallowed as the tail. A guard on
the kind that then let the adapter eat its own structural drift would be a door
built with the lock left out.

**It is an executable guard, not a substring convention.** There is no second
placeholder: one strictly-bounded `<OS_ERROR>` is the entire budget, and a
second would turn the fixture format into a little language of excuses. The case
carries structured metadata — `"boundary": {"id": "CLI-B1", "expected_kind":
"json"}` — and `replay.rs` proves eligibility *before* relaxing anything:

```text
1. take the facts bytes the CLI case ran with
2. decode with str::from_utf8, NO normalization
3. the decode must SUCCEED   — invalid UTF-8 is §5.1's defect alone, never CLI-B1
4. OwnIr::from_json(that &str) must REJECT
5. the rejection kind must be Json
6. only then: exit == 2, stdout == "", stderr starts with the pinned prefix,
   and only the bytes after it are relaxed (and must be non-empty)
```

**The negative control, and the hole it had (#261 R3b).** The first version of
it read a *different case at a different path* from the positives it was
contrasted against, and its own comment had quietly relaxed "same path" to "same
path **shape**". That is the one thing a negative control exists to rule out: a
guard keyed on the path, the extension or the case name would have passed it
without ever consulting a rejection kind. The relaxation in the comment is the
tell — a control whose own prose has to widen to stay true is not measuring what
it says.

The decision now takes the facts bytes as a **parameter**, so the control runs
**one case** — one argv, one exact path string, one decode route, one fixture —
twice, against two byte sequences:

| run | bytes | strict door | eligible |
|---|---|---|---|
| positive | the case's own facts, on disk | `Json` | yes |
| negative | a valid document with a version mismatch | `Version` | **no** |

Everything a guard could accidentally be keyed on is held literally identical
across the two runs, and the test asserts that both runs resolve the same path
from the same case, so eligibility can only turn on the content. The bytes are
still frozen fixture bytes rather than bytes invented in the replay — inventing
them would move the oracle into the test. It is still deliberately **not** a
malformed mutation: malformed bytes could be refused by some other parser or
decoder fork and "prove" the guard by accident. The case those negative bytes
come from is itself pinned byte-exact as a Version rejection per §5.2a, and the
control asserts it carries no boundary metadata.

A sweep test additionally asserts that *every* case carrying CLI-B1 metadata
really does reject with `Json`, so a future case cannot acquire the relaxed
matcher by accident.

One honest limit: **a control's non-vacuity is a property of its construction,
not something a mutation can prove.** No source mutation distinguishes "this
control compares two documents" from "this control compares one document with
itself" — running the suite cannot tell you a test asserted nothing. What M24
does show is that the construction is load-bearing: make the guard reach for a
file instead of judging the bytes it was handed, and the control fires.

### 5.3 Windows — three separate claims (#261 ruling 3)

The 1a32185 draft ran these together and reached for "the useful half", which
read as a parity flavour over a result that is not parity. They are three
claims, and the third is **not claimed**.

**A. Canonical reference parity — CLAIMED.** The Rust binary reproduces the
Linux/UTF-8 Python reference byte for byte over every pinned fixture case.

**B. Rust portability — CLAIMED.** Rust on Linux and Rust on Windows emit the
same bytes: the Linux-authored fixture replays byte-for-byte on
`windows-latest`, including the cases the Windows *reference* cannot produce.
The binary writes through a locked handle with no encoding layer and no
line-ending translation. The unicode-and-space directory name round-trips
through a fresh Windows clone.

**C. Native-Windows Python parity — NOT CLAIMED.** It is a measured defect of
the reference, and no wording in this note or on any status surface should
suggest otherwise:

| | Linux reference | Windows reference |
|---|---|---|
| piped `sys.stdout.encoding` | `utf-8` | **`cp1252`** |
| line endings | `\n` | **`\r\n`** |
| the em dash in the `ok` line and most messages | `e2 80 94` | **`97`** |
| non-ASCII `file`, `human` / `github` | exit 1, a finding | **exit 70**, `UnicodeEncodeError` |

Because the em dash appears in the `ok` line and in most finding messages, the
Windows reference produces different bytes for nearly every case in the fixture,
not only the ones with non-ASCII inputs. §1.9 has the full measurement.

**A behavior change, not parity — recorded in #262.** Windows Python today
emits cp1252 / CRLF and can fail outright with `UnicodeEncodeError`; Rust
tomorrow emits UTF-8 canonical bytes on both platforms. That is very likely an
improvement — and it is still a **behavior change** for a Windows user whose
tooling consumes those bytes, so it belongs in *Known differences* rather than
being folded into a parity claim.

#262 is the tracker of record and carries it: the reviewer recorded it there
under *Known differences recorded ahead of the packet* (2026-09-08). The #250
roadmap mirror is **pending reconciliation**.

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
* **`py_repr` is carried THREE times now** — `own-syntax`, `own-cli`, and
  (with the repair pass) `own-ir`, whose Version message interpolates one.
  Each import is a forbidden edge: `own-cli -> own-syntax` is not in the DAG,
  and `own-ir` is the leaf that may depend on no workspace crate at all. A
  shared `own-pyparity` leaf is the home; the repair pass raised its price from
  "tidy" to "three copies of a Unicode-category table", and #345 — which adds
  the commands whose errors interpolate far more `repr()`s — is where it starts
  to pay.
* **the `line`-family message still uses `Value`'s Display.** `own-ir`'s
  `defaulted_int_value` builds `{what} '{key}' must be an integer, got {other}`
  the way the Version message used to, so it carries the same quote/bool/None
  divergence. It is a #259 surface and outside #261's scope; the repair pass
  deliberately touched only the Version call site. Worth closing with the same
  helper when the `own-pyparity` leaf lands.
* **the Unicode table skew is a boundary, not a bug (§5.2a, ruling V4).**
  `str.isprintable()` is answered from the table each side was built with, and
  the two are independently versioned — the gap is a specific two-version
  measurement (CPython 3.11.15 / UCD 14.0.0 vs unicode-properties 0.1.4 /
  UCD 17.0.0; see §5.2a), not a fixed size of V4.
  `own-syntax` carries the same helper and inherits the same boundary. When the
  `own-pyparity` leaf lands it should carry the measurement with it, so the
  answer lives in one place rather than being re-derived per crate.
* **the campaign's catcher validator** special-cased `src/lib.rs` and not
  `src/main.rs`. `own-cli` is the first binary crate whose unit tests a campaign
  names, and without the fix every one of them read as "names a test that does
  not exist" while pointing at a test that plainly did.
* **Python-first hygiene** — `UnicodeDecodeError` → `OwnIRError` → `rc 2` in
  `ownlang/ownir.py`'s `load()`, so a file that is not UTF-8 is refused by the
  strict door like any other malformed input rather than crashing the run. To
  close **before public cutover**; #261 does not block on it (§5.1).
  **Recorded in #262**, the tracker of record, under *Known differences recorded
  ahead of the packet* (2026-09-08); the #250 roadmap mirror is **pending
  reconciliation**.
* **Windows byte differences** — Windows Python emits cp1252 / CRLF and can fail
  with `UnicodeEncodeError` where Rust emits UTF-8 canonical bytes: an
  improvement, and a behavior change (§5.3 claim C). **Recorded in #262** in the
  same place; the #250 mirror is **pending reconciliation**.
* **for the owner to decide:** the docstring-on-stdout class (§1.1, four cases,
  frozen and flagged) is the one class still awaiting a ruling.
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
