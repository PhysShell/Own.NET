# Inter-procedural use-after-handoff — the TRANSITIVE (forwarded) consumer

**Pattern:** the same use-after-handoff as `ownership-handoff-use`, but the consumer does **not**
dispose the stream itself — it **forwards** it to another method that owns and closes it
(`Consume(sink) -> Inner(sink) -> sink.Dispose()`). The caller hands ownership to `Consume`, then
touches the stream again. The bug is the use **after** ownership moved; the handoff itself is
correct (the stream is closed, just one hop further down).

**What the checker says:** using a resource after it was consumed (here, *transitively*) by a
callee is the generic **OWN002** (use after release) — the same code as use-after-dispose.

**Why this case exists (the transitive consume-contract).** The consume contract was already
modelled for a callee that disposes a by-value `IDisposable` parameter *directly*
(`ownership-handoff-use`). But the inference deliberately **stopped at one hop**: a parameter
merely *handed to another call* was "genuinely ambiguous without that callee's contract, so we do
not infer it" (`ownlang/ownir.py`, the `passed` branch) — and the extractor's
`ConsumeReleaseArgs` only recognised a *direct* disposer. So `Consume` (which forwards rather than
disposes) was **not** seen as a consumer, the handoff was not a release, and the later `s.Length`
was invisible — a **miss**.

Now the extractor's consumer detection (`ConsumesParam`) is **transitive**: a parameter is
consumed if the body either disposes it directly **or** forwards it to another first-party
consumer that consumes it — following `Consume -> Inner -> Dispose` through the chain, guarded
against cycles. Inspecting each callee's own body keeps it inter-procedural without a cross-call
signature table (and without a dangling-callee crash). Conservative: a parameter handed to an
unknown or merely-borrowing callee is **not** treated as consumed (no false release, no false
OWN002). This fixture is a **miss** before and a **catch** after — the ratchet row that lifts the
use-after-handoff capability across a forwarding hop. The `.own` reduction already checks the
transitive shape (the front-end's signature inference recurses); this brings it to real C#.

**Honesty / scope.** `case.own` is a faithful hand reduction of the C# pattern, not C# the `.own`
checker ingested. `before.cs` / `after.cs` are representative of the bug and its fix, not a
verbatim copy of one PR.
