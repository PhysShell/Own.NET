# using-statement-throw-releases

The sound handling of an **explicit `throw` inside a `using (existingLocal)` body** — the
follow-up to [`local-dispose-via-using-statement`](../local-dispose-via-using-statement/notes.md),
which first deferred this case (Codex P2 on PR #159).

When the `using`-local release was threaded as a non-null `bodyOnThrow`, the
`ThrowStatementSyntax` lowering bailed the **whole method** (it refuses a non-null `onThrow`
because a throw inside a `try` might be caught). That lost detection of UNRELATED leaks in
any method with such a body. This fixture pins the fixed behaviour.

- **before.cs** — an unrelated local `conn` is never disposed → `OWN001`. Crucially, the
  `using (guard)` body contains `if (bad) throw …;`. The bug is only caught if the throw
  does **not** bail the method — so this fixture is a direct regression test for the
  no-bail fix. `guard` is released on every path (normal, throw, return) and stays silent.
- **after.cs** — `conn` is `using`-declared (auto-disposed); the body still throws, and the
  method stays analysed and **clean**.

## Recognition rule

`LowerFlowStmt`/`LowerFlowStatements`/`LowerSwitchSection` thread an `onThrowDefinite` flag
beside `onThrow`. It is true when a throw that runs `onThrow` **definitely** leaves the
method uncaught — a `using` or a finally-only `try` (neither has a catch) — and false for a
`try` with any `catch` (the throw may be caught). The `ThrowStatementSyntax` case:

- `onThrow is null` (method level) → bare exit, as before;
- `onThrow` non-null **and** `onThrowDefinite` → route the throw through `onThrow` (the
  release continuation, ending in exit), so the cleanup's resource is released on the throw
  path and the method stays analysed;
- `onThrow` non-null and **not** definite (try-with-catch) → still bail.

## Honesty caveat

The definite routing covers `using` statements and finally-only `try`s. A `try` with a
`catch` still bails an explicit throw in its body — modelling that soundly needs matching
the thrown type against each catch clause, which the lowering does not do. That is the same
conservative posture as before; this change only *adds* the provably-uncaught cases.
