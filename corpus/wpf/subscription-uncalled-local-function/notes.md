# Subscription whose only `-=` is in an uncalled local function / lambda inside Dispose (soundness FN)

**Pattern (#278 follow-up, blocker 4).** The matching `-=` sits inside a
callable declared lexically inside `Dispose` — a local function
(`UncalledLocalFunctionView`) or a lambda stored in a local
(`UncalledLambdaView`) — that Dispose never invokes. Declaration is not
execution: a nested callable does not run just because its enclosing method
does.

**The bug.** The first #278 slice treated both as lexical pass-throughs — a
local function "part of its declaring method's body", a non-handler lambda
inheriting its lexical context — so a `-=` inside dead nested teardown code was
silently credited as released.

**The fix.**
- A LOCAL FUNCTION is a teardown context only when the symbol-based intra-class
  closure proves a teardown context CALLS it (`Dispose() { Detach(); void
  Detach() { ... } }` — the `after.cs` shape). The closure walks each
  callable's own body only (never descending into nested function bodies), so
  an invocation inside an uncalled nested function cannot extend the set
  either.
- A LAMBDA is a teardown context only as the handler provably wired to the
  class's own lifecycle event (`this.Closing += (s, e) => ... -= ...`, pinned
  in `subscription-xaml-name-only-release/after.cs`). Everything else —
  including a lambda stored in a local, passed to a combinator
  (`ForEach(x => x.E -= H)`), or simply declared and dropped — keeps the
  honest warning: nothing intra-class proves the delegate is invoked.

`before.cs` pins both bad forms (expected OWN001); `after.cs` pins the
called-local-function good form (silent).

**What the checker says (`.own` reduction).** The scope acquires the token and
no executed path releases it => **OWN001** with the subscription-token resource
tag.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**.
