# Codegen Contract

> **Status: normative, descriptive.** Source of truth: `ownlang/codegen.py`.
> This is the contract between the checker and the C# code generator. It exists
> to stop the class of bug that dominated early development: codegen quietly
> emitting unsafe C# (double-return, leak, use-before-decl).

## The contract

- **C1 — separation.** The *checker* decides whether a program is sound. The
  *codegen* decides whether it can lower a sound program to faithful C#.
- **C2 — codegen may reject, never lie.** Codegen MAY reject a checker-accepted
  program it cannot lower, raising `CodegenError` (the program is sound but the
  PoC has no faithful lowering). Codegen MUST NEVER emit semantically unsafe C#
  to "make it compile". Honest rejection beats a wrong `Return`.
  - Example: an escaping `pooled`/`native` buffer — the checker may model it, but
    codegen rejects it (the caller has no handle to Return/Free). See
    [BufferPolicies §B2](BufferPolicies.md) / OWN017.
- **C3 — resource identity, not name.** Codegen MUST track resources by identity
  (carried across `move`), not by variable name. Looking only for `release x`
  after `let y = move x` is forbidden ([OwnCore §1](OwnCore.md#1-resource-identity)).
- **C4 — release on all paths is real.** For a sound program, every owned
  resource is released exactly once on every path. Codegen MUST preserve this:
  the `finally` makes it hold across C# exceptions too.

## Two lowering modes

| Mode | When | Shape |
|------|------|-------|
| **try/finally hoist** | straight-line: no branch, no `move`, no owned `return`, laminar scopes with top-level releases | acquire → `try { ... } finally { release }`, nested for multiple resources |
| **faithful inline** | branches / ownership transfer / non-laminar scopes | releases emitted inline exactly where the source put them |

The hoist emits **no** runtime "released?" flag: because the release is hoisted
*out* of the `try` (not also in the body), it runs exactly once with no guard. A
flag would only make sense if we did not trust the static result — and if we do
not trust it, we should not ship it.

## What "faithful" means

- `resource` emit templates (`emit_type`/`emit_acquire`/`emit_release`/
  `emit_borrow`) produce **real** .NET (e.g. `ArrayPool<byte>.Shared.Rent/Return`,
  `byte[]`, `.AsSpan()`). Absent templates fall back to the schematic
  `Resource.method()` form.
- A borrow binding renders as its C# view (the span / ref); an owned argument as
  its variable.
- The generated C# is intentionally **boring**. Boring generated code is the
  compiler doing the work instead of pretending to be an artist.

## Verification

The golden example (`examples/golden_arraypool/`) is the one place the generated
C# is genuinely compiled and run by the real .NET compiler — the `dotnet-golden`
CI job: it checks the emitted method stays byte-identical to the host
(`verify_emit.py`), then `dotnet run`s it. Elsewhere the property fuzzer asserts
the release-accounting invariant on generated programs via an independent AST
oracle.
