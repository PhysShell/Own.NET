# The Rust core workspace (P-022)

The strangler-fig port of the Python core (`ownlang/`) to Rust, one crate at a
time. Full plan, crate DAG, and rationale:
[`docs/proposals/P-022-rust-core-migration.md`](../docs/proposals/P-022-rust-core-migration.md)
(revised per
[`docs/notes/p022-review-notes.md`](../docs/notes/p022-review-notes.md)).

**Python stays authoritative.** Nothing here replaces `python -m ownlang` yet.
Each crate lands *behind a differential ratchet*: it must reproduce the
Python core byte-for-byte (error text, AST shape, OwnIR round-trip) on the
existing fixture corpus before the next crate is added. If Rust and Python
ever disagree, Python wins until the divergence is a deliberate, justified
change.

## Status

Seven of the planned crates exist (`own-lowered`, the typed Layer 2 surface,
joined the DAG with #259). The checkpoint-level truth lives in P-022's
implementation-status block; this table is the one-line orientation:

| Crate | Status | What it is |
|---|---|---|
| `own-ir` | **done** (step 1; strict door #259 cp1) | The OwnIR fact contract (`serde` types + the strict validator over the raw document) and the span/location leaf. Port of `ownlang/ownir.py`'s `load()`, not its bridge logic (that's `own-bridge`). |
| `own-syntax` | **done** (step 2) | Lexer + recursive-descent parser + AST. Port of `ownlang/{lexer,parser,ast_nodes}.py`, with a **byte-identical error-text** contract against Python. |
| `own-cfg` | **done** (step 3) | AST → CFG lowering, replaying the canonical CFG-JSON seam. |
| `own-analysis` | **done** (step 4) | The worklist/lattice solver plus ownership, lifetime, buffer-policy, effect and DI, with `(line, code)` parity on the `.own` corpus and the verdict `subject` the bridge maps through. |
| `own-diagnostics` | **done** (steps 5a/5b) | `Diagnostic`/`Evidence` model, canonical render text, the SARIF 2.1.0 projection. |
| `own-lowered` | **done** (#259) | The typed Layer 2 document + canonical emitter the bridge lowers into. |
| `own-bridge` | **in progress** (#259: cp1–cp4 done, cp5 open) | The OwnIR bridge: facts → Layer 2 → core AST → analyses → verdicts (`lower`, `dump_summaries`, `check_facts`). |
| `own-codegen` | not started (#257) | C# emission (`emit_*` templates), verdict-independent. |
| `own-cli` | not started (#261) | The binary; `own-oracle` is the dev-only differential harness alongside it. |

## Build & test

```bash
cd rust
cargo fmt --check
cargo clippy --all-targets   # workspace lints are the gate — see Cargo.toml
cargo test
```

Same three commands the CI job `rust (fmt + clippy + tests)` runs
(`.github/workflows/ci.yml`) on every push. Every crate's parity suites
replay Python-authored fixtures under `tests/fixtures/` with zero Python
present (the counts live in each suite's assertions, not here — a number
in prose rots).

`unsafe_code = "forbid"` workspace-wide, `clippy::pedantic`/`nursery` warn,
`unwrap_used`/`indexing_slicing`/`arithmetic_side_effects`/`panic` deny — see
the workspace `[lints]` in [`Cargo.toml`](Cargo.toml) and the "ratchet"
section of P-022 for why (and where it's allowed to be loosened, with a
justification comment, never by reflex).

## Test cases: what "parity" actually checks

Both crates are pinned by fixtures the **Python side generates and owns** —
Rust only replays them (`tests/test_syntax_fixtures.py --write` regenerates
`tests/fixtures/syntax_parity.json`; a stale fixture fails Python's own test
first). This is deliberate: Python is the oracle, Rust proves it agrees.

### `own-syntax` — byte-identical error text, or a matching AST digest

`tests/parity.rs` replays every case in `tests/fixtures/syntax_parity.json`
(24 today) through the Rust parser and asserts either the exact Python error
string or an equivalent structural digest. A sample of what's actually in
there:

| Case | Input (abridged) | Expected |
|---|---|---|
| `unexpected_char` | `@...` | `1:1: unexpected character '@'` |
| `unterminated_string` | `"...` (no closing quote) | `1:33: unterminated string literal` |
| `rejected_keyword_top_level` | `for ...` | `'for' is out of scope for the MVP — for/loop-style iteration and async are deliberately unsupported ('while' is supported; see README, 'Where it cheats')` |
| `subscribe_not_self` | `subscribe foo to bus;` | `expected 'self' after 'subscribe' (got IDENT 'foo')` |
| `subscribe_not_to` | `subscribe self from bus;` | `expected 'to' in 'subscribe self to <source>' (got IDENT 'from')` |
| `buffer_positional_after_named` | `Buffer.stack(1, max = 2, 3)` | `only the leading size may be positional in a buffer intent; later arguments must be named` |
| `unicode_idents` | `module м { fn f(х: int) {} }` | accepted; digest matches Python's |
| `full_module` | a resource + 2 externs + 2 fns, one with a `while` | digest `m=Demo r=2 e=4 f=2 p=1 l=2 fns=[setup/2/16,empty/0/1] conds=[n < 10\|n]` |

The point of the digest cases isn't the string itself — it's that Rust and
Python parsed the **same shape** (resource/extern/fn counts, statement
counts including into nested `if`/`while` bodies, and every condition's raw
token text) out of the same source.

### `own-ir` — every OwnIR fixture round-trips value-for-value

`tests/roundtrip.rs` reads every `*.json` under `tests/fixtures/ownir/` (21
files — the same fixtures `tests/test_ownir.py` uses on the Python side:
`subscribe`, `di`, `pool`, `flow_while`, `protocol_isloaded_violation`, …),
parses it with `OwnIr::from_json`, re-serializes it, and asserts the output
equals the input **exactly** — typed fields and unrecognized `extra` fields
alike, so a newer frontend's additive field survives a Rust round-trip
untouched. Plus schema-gate unit tests: `version_gate_rejects_future_schema`,
`absent_version_means_v0`, `bool_is_not_an_integer` (JSON `true` isn't an
`int` here, unlike Python), `additive_unknown_fields_are_preserved`.

## Why a `rust/` subtree and not a sibling repo

Monorepo, for this phase: the oracle and the fixture corpus are one `git`
away, no submodule/pinned-SHA ceremony. Revisit once Rust is authoritative
and Python is reference-only — see P-022 "Open questions".
