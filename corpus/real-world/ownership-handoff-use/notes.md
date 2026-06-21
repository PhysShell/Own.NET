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
vanished and the later `s.Length` was invisible — a **miss**. Now a call to a first-party
**consumer** — a method whose own body disposes a by-value `IDisposable` parameter — is
modelled as a **release of the argument at the call site**, the same shape as pool
`Return(buf)` (the resource leaves the caller's hands right there). The use *after* that
release then trips **OWN002**. The signal is the callee's own body, so it is inter-procedural
without a cross-call signature table (and so without a dangling-callee crash). This fixture is
a *miss* before and a *catch* after; `ownership-handoff-consume` is caught for its leak arm
either way, so this is the row that makes the use-after-handoff capability a measurable ratchet.

**Honesty / scope.** `case.own` is a faithful hand reduction of the C# pattern, not C# the
`.own` checker ingested. `before.cs` / `after.cs` are representative of the bug and its fix,
not a verbatim copy of one PR.
