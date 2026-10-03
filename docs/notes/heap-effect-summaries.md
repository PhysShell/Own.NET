# H0 — heap-effect summaries (inert)

Status: **landed inert**. A second summary domain beside the Method Ownership
Summary, produced and solved end to end, and read by nothing that decides a
verdict or a refusal. Follows
[`protocol-harmless-call-summary-gap.md`](protocol-harmless-call-summary-gap.md),
which found that the MOS / P-037 transfer lattice cannot prove a call harmless.
Base: `main` = `a27a8277b40309aa56b945e73dd305ddb90e72b4`.

## 1. The domain

Per source-visible method:

| field | lattice | meaning |
|---|---|---|
| `params[i].effect` | `plain < borrow < borrow_mut < may_escape < unknown` | what the method may do to the object graph of argument *i* |
| `receiver` | same, or `null` for a static method | the same for `this` |
| `writes.instance` / `.static` / `.indirect` | `none < may < unknown` | writes to memory reached from **neither** a parameter **nor** the receiver: an object field, a static field, an array element / indirect storage |
| `returns` | `[]` · some of `param:<i>`, `receiver`, `heap` · `["unknown"]` | what the returned value may alias (`[]` also for an inert return) |
| `unresolved` | list | the method's own reasons for an Unknown (evidence only) |

- `plain` means the argument's graph is not touched. Every inert value (an unmanaged type or `string`) is `plain`, even under Unknown.
- `borrow` means the argument is read through.
- `borrow_mut` means it may be written through: a field, an element, a `ref`/`out` location.
- `may_escape` means it may be stored where it outlives the call. After that anybody may write it, so on this chain `may_escape` subsumes `borrow_mut`. Both disqualify "harmless".
- A write through a parameter is that parameter's `borrow_mut`, never a `writes` entry. So a callee's effect maps exactly onto the caller's arguments.

**Unknown absorbs** wherever silence would read as clean:
- **Unmodelled construct in the body:** Unknown on every non-inert parameter, the receiver, every write kind and the return.
- **Call with no summary** (virtual, `extern`, delegate, or a direct call with no record): Unknown on every argument and the receiver, and every write kind Unknown.
- **Value returned by such a call:** an Unknown root. A write through it is an Unknown write.

## 2. Where the source facts are born

`ownsharp-extract … --heap-effects FILE`. The producer is `frontend/roslyn/OwnSharp.Extractor/HeapEffectFacts.cs`, wired at the very end of `Program.cs`, after the facts JSON is final. It writes a **separate file**. The facts document is never touched, and no OwnIR field, op or version moves.

It is fact extraction, not an analysis. One `IOperation` body at a time, the walk records the following, in tokens `param:<i>`, `receiver`, `heap`, `local:<n>`, `call:<k>`:
- each value's sources;
- derefs and writes (kind + target);
- stores (values put somewhere that outlives the call);
- returns;
- locals (flow-insensitive);
- calls: callee key, dispatch `direct|virtual|extern|delegate`, receiver, and per-parameter arguments;
- `unknown` reasons.

The walk is **default-deny**: any construct it does not model is an `unknown` reason. It never solves, never reads a callee body from a call site, never says "harmless".

The vocabulary is version 1 (`heap_effects_version`). The record schema is the one validated by `ownlang/heap_effects.py::load`.

Deliberate conservatisms, all in the fail-closed direction:
- **New objects:** `new T(...)` reads as `heap` (its contents are not tracked). A write to a fresh object is a heap write.
- **Unknown constructs:** lambdas, local functions, `foreach` over a non-array, `using`, `lock`, `await`, iterators, object/collection initializers, events, ref locals, patterns that run getters, `dynamic`, pointers.
- **Static initialization:** touching a type with an explicit static constructor or a non-constant static initializer is Unknown, inside the type too: a `beforefieldinit` initializer may run lazily at the first static-field access.
- **External statics:** a static field of a type with no source is Unknown.
- **Constructors:** one whose type has non-constant instance initializers is Unknown. An implicit constructor is accepted only for a value type or a direct `object` subclass with no instance initializers.
- **The one exemption:** `object()` is empty.

## 3. Where the fixpoint is solved

- **Python reference:** `ownlang/heap_effects.py`. Run it with `python -m ownlang.heap_effects FILE`. It is deliberately **not** a `python -m ownlang` subcommand, so the public CLI surface (and its Rust mirror) is unchanged.
- **Rust port:** `rust/crates/own-bridge/src/heap_effects.rs`, public as `own_bridge::dump_heap_effects(text)`. It sits beside `mos.rs` and shares `dump.rs`'s Python-exact JSON emitter.

The solve is a least fixpoint over the call graph's SCC condensation: Tarjan bottom-up, then iteration inside each component from ⊥. Every transfer function is monotone over finite lattices, so the result is independent of iteration and input order.

## 4. Parity

- **Byte-exact goldens:** `tests/fixtures/heap_effects/` holds 10 cases and 16 rejections. `<case>.summaries.json` is the exact stdout of the reference; `<case>.rejected.txt` is the exact rejection text, and the validation order is part of the contract.
- **Python side:** `tests/test_heap_effects_fixtures.py` checks the goldens, input-order independence (`methods[]` reversed), the ledger, the meaning of 30 pinned summaries, and that no `ownlang` module imports `heap_effects`.
- **Rust side:** `own-bridge/tests/heap_effects.rs` replays every golden and every rejection text, re-derives the ledger, and checks determinism and order independence, with zero Python.
- **Differential fuzz (development):** 4000 random sidecars, 1318 of them corrupted into rejections, gave identical bytes and messages from both engines. Three planted solver mutants were each caught by both the goldens and the fuzz.
- **Parity domain:** RFC 8259 JSON whose integers fit 64 bits. The reference reader refuses `NaN`/`Infinity`, overflowing numbers and lone surrogates, as serde does.

## 5. Kill fixtures (`frontend/roslyn/heap-effects-samples/HeapEffects.cs`)

| method | params | receiver | writes | returns |
|---|---|---|---|---|
| `Twice(int)` | plain | — | none | [] — a harmless candidate |
| `Mutates(Order)` | **borrow_mut** | — | none | [] |
| `Escapes(Order)` | **may_escape** | — | static: **may** | [] |
| `TouchesGlobalState()` | — | — | static: **may** | [] |
| `Logs()` (`Console.WriteLine`) | — | — | **unknown** ×3 | [] (unresolved: `System.Console.WriteLine(string?) (extern)`) |
| `A(x) => B(x)`, `B` writes `x.State` | **borrow_mut** (only via B's summary) | — | none | [] |
| `EscapeOuter → EscapeInner` | **may_escape** | — | static: may | [] |
| `Even ⇄ Odd` (pure SCC) | plain | — | none | [] |
| `Ping ⇄ Pong` (Pong writes) | borrow_mut, plain (both) | — | none | [] |
| `Tick ⇄ Tock` (Tock logs) | unknown, plain (both) | — | unknown ×3 | [] |
| `CallsLogs() => Logs()` | — | — | unknown ×3 | [] |

Receiver mapping, local aliases, a reassigned parameter, array elements, return aliases through calls, static initialization, lambdas, virtual dispatch and a captured primary-constructor parameter are pinned beside them.

## 6. Inertness

**Gate:** `scripts/heap_effects_gate.py`, which needs `dotnet` and runs in CI's `state-protocols` job.
1. It re-extracts the samples and requires the committed sidecar.
2. It runs the extractor with and without `--heap-effects` over every protocol case, every protocol refusal, the samples, and `examples/`: 38 runs. Exit code, stderr and facts bytes must be identical.

**Against `main` (measured once for this change):** the `main` extractor (`a27a827`) and this one, without the flag, were compared over 208 C# inputs (`corpus/`, `examples/`, the protocol samples, fixtures) plus four directory scans in three flag modes (`--flow-locals`, `--fix-candidates`, none). All 220 runs gave identical facts bytes, exit codes and stderr, including the 2 refusals.

**The core:** no verdict-path module changed. The only edit to existing Rust code is the visibility of `dump.rs::emit` (private → `pub(crate)`). The existing suites (`tests/run_tests.py`, `cargo test`) pass unchanged. The coordinate census (`docs/generated/p022-coord-census.md`) is regenerated only because it now also counts the new fixture family's `line` slots.

## 7. What H1 still needed (landed: [`h1-proven-call.md`](h1-proven-call.md), OwnIR v2)

1. **The decision point: an owner ruling.** `ProtocolLowering` refuses in the extractor, before any fact exists, while the summary is solved in the core. Moving the decision core-side needs a must-understand construct for "a call inside this region whose effect must be proven", which is an OwnIR v2 op (IR3/IR4), plus the sidecar travelling with the facts it describes. Solving in the extractor is not an option: frontends emit facts only (IR6).
2. **The predicate**, over a solved summary of a `direct` callee:
   - all parameters and the receiver at most `borrow`;
   - every `writes` kind `none`;
   - `returns` either `[]` or not aliasing a parameter, the receiver or the heap;
   - no Unknown anywhere;
   - entity-typed arguments still lowered as a `use` (a verdict), as today.

   "Region-resource" precision (allowing a write to state that provably is not the entity's type family) needs typed write targets, which H0 does not carry. Without them H1 is the strict predicate, which is sound.
3. **External calls.** `logger.LogInformation(...)` is `extern`, so it is Unknown, so the motivating example stays refused under H1. Admitting it needs curated or annotated summaries (P-036's `source: bcl | annotation`), a separate slice with its own trust argument.
4. **Precision where it matters**, only if H1's first consumer runs into it: fresh-object tracking, local functions and lambdas, `foreach` via a known enumerator, sealed-receiver devirtualization.
