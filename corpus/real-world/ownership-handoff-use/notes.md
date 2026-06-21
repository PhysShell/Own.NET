# Inter-procedural use-after-handoff (pure)

**Pattern:** a stream is handed to a consumer that takes **ownership** (reads it, then
`Dispose()`s it), and the caller then touches the stream again. Unlike
`ownership-handoff-consume` there is **no leak arm** — the handoff itself is correct, so the
*only* bug is the use **after** ownership moved. Common shape: serialize/compress into a
stream, hand it to a sink that owns it, then accidentally read it once more (an
`ObjectDisposedException` at runtime).

**What the checker says:** using a resource after it was consumed by a callee is the generic
**OWN002** (use after release) — the same code `.own` produces for use-after-dispose.

**Why this case exists (the consume-contract proof).** The extractor used to treat any
argument-passing as an *escape* (untracked), so a stream handed to `Consume(s)` simply
vanished and the later `s.Length` was invisible — a **miss**. With the inter-procedural
**consume contract**, a first-party method owning a by-value `IDisposable` parameter is
recognised, the handoff `Consume(s)` lowers to a `call` op, and the bridge **moves
ownership** across it — the cut is the *signature*, not whole-program points-to, exactly like
Rust's move. The use after the move then trips **OWN002**. This fixture is a *miss* before the
contract and a *catch* after; `ownership-handoff-consume` is caught for its leak arm either
way, so this is the row that makes the use-after-handoff capability a measurable ratchet.

**Honesty / scope.** `case.own` is a faithful hand reduction of the C# pattern, not C# the
`.own` checker ingested. `before.cs` / `after.cs` are representative of the bug and its fix,
not a verbatim copy of one PR.
