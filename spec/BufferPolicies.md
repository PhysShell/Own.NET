# Buffer Storage Policies

> **Status: normative, descriptive.** Source of truth: `ownlang/buffers.py`,
> `ownlang/codegen.py`. Buffers are owned resources (OwnCore §1–7 apply) with an
> additional *storage policy* that constrains escape and codegen.

A buffer is introduced by a buffer-intent let, e.g. `let b = Buffer.scratch(n,
inline = 256)`. The namespace is `Buffer`; the method selects the mode.

## Modes

| Mode | Backing | Escape | Release |
|------|---------|--------|---------|
| `stack` | `stackalloc` | **local-only**, cannot escape | none (stack unwinds) |
| `scratch` | stack branch *or* pool branch | local-only | pool branch returns; clear if sensitive |
| `pooled` | `ArrayPool<byte>` rented array | owns the array | returns to the pool |
| `native` | `NativeMemory` unmanaged pointer | owns the pointer | frees the pointer |
| `inline` | fixed stack buffer | local-only | none |

## Rules (normative)

- **B1 — stack cannot escape.** A stack-backed buffer (`stack`, `inline`, or a
  `scratch` whose pool fallback is forbidden) MUST NOT be returned, consumed,
  stored in a longer-lived owner, or captured → **OWN015** (return),
  **OWN016** (move to longer-lived owner).
- **B2 — movable escape unsupported.** Returning a `pooled`/`native` buffer is
  rejected in the MVP because codegen has no handle representation for the caller
  to Return/Free → **OWN017**. (Checker-accepts / codegen-rejects, see
  [CodegenContract.md](CodegenContract.md).)
- **B3 — static bound for dynamic stack.** A dynamically-sized stack allocation
  requires a statically-known bound (`max = N`) → **OWN021** if absent;
  → **OWN019** if the inline capacity is too large for the stack.
- **B4 — size is integer.** A non-integer size → **OWN018**.
- **B5 — scratch fallback honesty.** A `scratch` that forbids the pool fallback
  but whose size may exceed the inline limit → **OWN023**. Its compile-time
  report MUST NOT advertise an ArrayPool branch that cannot occur at runtime.
- **B6 — sensitive must clear.** A `sensitive` buffer that is not cleared on
  release → **OWN024** (zeroing before return/free is mandatory).
- **B7 — requested length preserved.** `scratch` lowering preserves the
  *requested* logical length, independent of whether the stack or pool branch is
  taken.
- **B9 — full view stays within the logical length.** A pooled buffer is
  *oversized*: `ArrayPool<T>.Rent(n)` returns an array of `Length >= n`, not
  exactly `n`. A FULL-length view of it — `buf.AsSpan()` / `buf.AsMemory()` /
  `new Span<T>(buf)` with **no length bound** — reaches past the requested length
  `n` into the stale `[n, Length)` tail (a previous renter's bytes); reading or
  copying through it is an over-read / over-copy → **OWN025**. The fix is a bounded
  view, `buf.AsSpan(0, n)`. (P-007 POOL005; the OwnLang model op is `overspan b`.
  Distinct from B6/OWN024, which is clearing *too little* of a sensitive buffer —
  this is reading *too much*.)

## Buffer options and `policy` blocks

A buffer-intent takes a positional `size` plus named options; a `policy P { ... }`
block is a **reusable bundle of the same defaults**, applied by `policy = P`.
Inline options win over the policy. Recognised keys: `inline`/`inline_bytes`,
`max`/`max_bytes`, `fallback` (`pool`/`forbidden`), `trace`, `counters`,
`clear`/`clear_on_release`, `sensitive`, `mode`, `policy`.

- **B8 — keys are validated.** An unknown key in a `policy` block, or a malformed
  value (e.g. `clear = ture`, `fallback = bogus`), is **OWN030** — never a silent
  default. A duplicate key is reported too.

## Logging surfaces

Under `[Conditional]` compilation symbols, codegen may emit `OwnTrace` (which
branch was selected) and `OwnCounters` (stack hits, requested/returned bytes,
forced clears). These are off by default and never change semantics — see
`README.md` for the symbols.

## Compile-time report

`ownlang report` emits a per-buffer summary (mode, policy, runtime branches,
checks) to stdout and `*.ownreport.json`, attributed by resource identity
(name#line#col), not by variable name.
