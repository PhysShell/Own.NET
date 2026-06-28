# local-dispose-via-using-statement

A disposable acquired into a **local** and released through the **statement** form of
`using` whose resource is an **already-acquired local** — `var r = new ...; using (r)
{ ... }` — rather than the declaration form (`using var r = ...` / `using (var r =
...)`). The real-world shape is protobuf-net's `assorted/` Silverlight `Page.xaml.cs`,
where a timer is constructed and then wrapped in `using (timer) { ... }`.

- **before.cs** — the local is acquired and used but never wrapped in a `using` and
  never `.Dispose()`d → `OWN001` (the bug is caught).
- **after.cs** — the local is wrapped in `using (r) { ... }` → **clean**. The dispose
  happens at scope exit, on a local the flow detector was already tracking.

## Recognition rule

The `--flow-locals` lowering already handles two `using` shapes: the declaration form
`using (var x = ...)` (where `x` is auto-disposed and never tracked as a leak), and the
`using (IMemoryOwner o = MemoryPool.Rent(...))` statement form (acquire + scope-exit
release, threaded onto the body's returns/throws). The gap was the **expression** form
`using (existingLocal)` over a local that was **already acquired** earlier (`var r =
new ...`): the block disposes `r` at scope exit, but the lowering previously just
emitted the body, leaving the tracked `r` looking live at method exit — a spurious
`OWN001`.

The fix threads a `release` for the using's identifier onto the body's normal
completion **and** its return/throw exits, exactly like the `MemoryPool` owner branch —
but with **no `acquire`** (the local was already acquired at its `new`; only the missing
release is added).

## Honesty caveat — what this does and does not reach

Scoped to a `using (identifier)` whose identifier is a **tracked local**. A
`using (SomeExpr())` whose resource is a method call or member access is not an
identifier and is not threaded — that resource is the callee's to dispose and is not a
tracked local here. The declaration forms are unchanged.

An explicit `throw` in the body is now handled soundly. The lowering threads an
`onThrowDefinite` flag alongside `onThrow`: for a `using` (no catch) a throw runs the
release then propagates, so the `ThrowStatementSyntax` case routes it through the release
continuation instead of bailing the method. A `try` with a `catch` keeps `onThrowDefinite`
false and still bails (the catch-vs-thrown-type match is not modelled). See the companion
fixture [`using-statement-throw-releases`](../using-statement-throw-releases/notes.md) and
the `onThrowDefinite` contract on `LowerFlowStmt`.
