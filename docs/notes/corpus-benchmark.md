# Corpus benchmark — recall + specificity on real C# (P-012 slice 1)

The labeled corpus (`corpus/<area>/<case>/`) was already half a benchmark: every
case carries `before.cs` (buggy), `after.cs` (fixed), `expected-diagnostics.txt`
and a `case.own` reduction. But the only thing scoring it — `tests/test_corpus.py`
— checks the **`.own` reduction**, and its own note conceded *"not that the tool
scanned real C#."* That note is now stale: the P-001 extractor exists.

`scripts/benchmark.py` closes the gap. It runs the **actual C#** through the
extractor + core (`own-check.sh --format sarif`) and measures the two things the
`.own` check cannot:

- **recall** — the bug is *caught* in the real `before.cs` (≥ 1 verdict);
- **specificity** — the real `after.cs` (the fix) is *silent* (0 verdicts — no
  false alarm on correct code).

The aggregate is one defensible line. The **first measurement** (9 cases):

```text
benchmark: 3/9 bugs caught in real C# · 9/9 fixes clean · 0 false positive(s) on fixes
```

That is the honest day-one number, and it is *sharp*: **specificity is perfect**
(every real fix is silent, zero false positives — the checker does not cry wolf on
correct code), and **recall was 3/9** — the three caught are exactly the
subscription/region class the extractor is strongest at (`zombie-viewmodel` →
OWN001, two static-event escapes → OWN014).

## Ratchet → 9/11 (five ratchets)

### → 4/9: a fixture was understating us

The first thing the number bought was a *diagnosis*. `screentogif-loaded-subscription`
is a **subscription** leak — our strongest class — yet it scored a miss. The cause
was not the extractor: the reduction's `before.cs` subscribed to
`_viewModel.ShowErrorRequested` but **never declared `VideoSourceViewModel`**, so
the type-aware extractor could not bind the `+=` to an event and honestly emitted
`OWN050` (unresolved) — a `note`, not a verdict. The fixture was understating our own
detection. Making the reduction self-contained (a minimal `VideoSourceViewModel` with
the three events, mirrored in `after.cs`) lets the extractor resolve it and flag the
leak (warning-tier — an injected `DataContext` source) exactly as it does on the full
ScreenToGif repo. **Recall is now 4/9** and the floor is raised to match. (Lesson: a
benchmark fixture that references an undeclared type silently degrades to `OWN050`;
self-contained fixtures, like the samples, measure honestly.)

### → 6/9: pooled buffers join the flow engine

The next two misses were a real **capability** gap, not a fixture: `arraypool-double-return`
(`OWN003`) and `arraypool-use-after-return` (`OWN002`). The extractor's pool pass was
purely syntactic — *"was this buffer `Return`ed anywhere?"* — so it only ever produced
`POOL001` (rent-without-return); a second `Return` or a read after `Return` was invisible.
Counting `Return`s would be unsound (it false-positives on `if (x) Return(b); else Return(b);`),
and **precision is sacred** here. So instead pooled buffers are now **routed through the
path-sensitive flow engine** that already proves `OWN002`/`OWN003` for IDisposable locals:
a `*Pool.Rent(...)` local is an *acquire*, `*Pool.Return(buf)` is a *release* (the buffer is
the argument, not the receiver), and a read of the buffer — including in a `return` value — is
a *use*. The core's CFG analysis then flags the double-release and the use-after-release
*soundly*, path-sensitive. Pooled buffers deliberately do **not** escape on arg-passing (the
ArrayPool convention is the renter returns), and the syntactic `POOL001` is suppressed under
`--flow-locals` so there is no double-report. **Recall is now 6/9.**

### → 7/10: pool recognition goes semantic

The pool pass recognised a `Rent`/`Return` by the **text** of the receiver — `Contains("Pool")` —
which is structurally blind to an *aliased* receiver: `ArrayPool<int> p = ArrayPool<int>.Shared;
p.Rent(...); p.Return(buf);` spells the receiver `p`, with no "Pool" in it, so the buffer was
invisible and a double-return through it was a **miss** (the symmetric hazard is a false match on
an unrelated `_connectionPool.Rent()`). Both are gone now that `IsPoolRent` / `PoolReturnBuffer`
bind the call through the **Roslyn SemanticModel** to `System.Buffers.ArrayPool<T>` — the receiver
may be spelled any way. That one definition is shared by the syntactic `POOL001` pass and the flow
engine (no divergence between the two), and it is ArrayPool-specific on purpose: `MemoryPool<T>.Rent`
hands back an `IMemoryOwner<T>` released by `Dispose`, so there is no `Return` to model. A new
fixture — `arraypool-aliased-receiver`, a double-return reached through `var p = ArrayPool<int>.Shared`
— is a *miss* under the old text heuristic and a *catch* (`OWN003`) under the semantic one. The
heuristic's failure mode was recall-leaning (a missed alias is a missed catch, never a false alarm),
so the upgrade only adds — precision stays absolute. **Recall is now 7/10.**

### → 8/10: factory acquires, not just `new`

The extractor only ever treated `new X()` as *acquiring* an owned disposable — so a stream
opened by a **factory**, `var s = File.OpenRead(path)`, was invisible, and the leak arm of
`ownership-handoff-consume` (a stream neither disposed nor handed off → a real `OWN001`)
scored a miss. `File.Open*` / `Create*` hand back a fresh `FileStream` the caller owns
exactly as if it had `new`'d one, so a local bound to one is an acquire. `IsOwningFactory`
recognises them off the resolved **symbol** against a curated `System.IO.File` set (precision
over recall — the set grows only where ownership is certain, so a borrowed/cached disposable
handed back by some other API is never mistaken for an acquire). With it the leak arm fires
`OWN001` (the fix's `using var` stays silent), so the case flips to caught — **recall is now
8/10**. The blast radius is exactly one file: nothing else in the corpus or the samples opens
a `File.*` stream, so no `after.cs` and no dog-food scan can newly cry wolf.

### → 9/11: the inter-procedural consume contract

The last handoff gap was the *use-after-handoff* arm — a stream handed to a consumer that
disposes it, then touched again (`OWN002`). The extractor treated every argument-pass as an
*escape* (untracked), so the handed-off stream vanished and the later read was invisible. Now
a call to a first-party **consumer** — a method whose own body disposes a by-value
`IDisposable` parameter — is modelled as a **release of the argument at the call site**, the
same shape as pool `Return(buf)` (the resource leaves the caller's hands right there). A use of
the argument *after* that call is then a use-after-release, `OWN002`; the matching argument is
exempted from the escape set so it stays tracked through the handoff. It is inter-procedural —
the signal is the *callee's own body* — but there is **no cross-call signature table**, so a
callee with no body to inspect (interface / abstract / extern) or that doesn't dispose the
parameter yields nothing and the argument stays an ordinary escape. Crucially there is no
dangling `call` op to a method the flow pass never lowered (the early call-op design crashed
the bridge on exactly that — `UnitOfWorkFlowSample`'s consumer, whose body the pass skips), and
the escape exemption is gated on the *same* body-inspection as the release, so an argument is
exempted **iff** it is also released — never a tracked-but-unreleased local that would read as a
false leak. A new fixture `ownership-handoff-use` (a *pure* use-after-handoff, no leak arm) is a
miss before and a catch after, so **recall is now 9/11**; `ownership-handoff-consume` now fires
both its arms (`OWN001`+`OWN002`). The verdicts were pinned locally (hand-built facts →
`check_facts` → the exact `OWN001`/`OWN002` and silence on the fixes).

The remaining gaps are genuine **frontend extraction** islands: a field/cross-method
use-after-dispose needs cross-method field-state, and the injected-source region-escape
(`viewmodel-escapes-to-app`) needs the source's lifetime *proven* — its DI registration —
which the fixture does not even carry. The `.own` reductions catch both; the C# extractor does
not yet. Each is a real capability the floor will ratchet up to as it lands.

## Why catch/clean, not exact-code match

The metric is deliberately **code-agnostic**: a leak reported as `OWN001` (token
leak) vs `OWN014` (region escape) both count as "caught". `test_corpus.py` pins the
exact code on the `.own` reduction; the real-C# benchmark answers the blunter, more
honest product question — *did we catch the real bug, and did we stay silent on the
real fix?* — which survives a sound reclassification of the leak that an exact-code
assertion would spuriously fail. (`expected-diagnostics.txt` is still reported as a
secondary `expected_hit` signal, just not part of the gate.)

A **verdict** is any SARIF result at error/warning level. The advisory `note` level
(`OWN050` "resolution skipped") is coverage honesty, not a verdict, so it is
neither a catch nor a false positive — a `before.cs` whose framework type didn't
resolve reads as a *miss*, not a fake catch.

## Validated two ways (the harness pattern)

- **`--selftest` (no SDK)** — the SARIF-parsing and scoring/aggregation logic is
  pinned on embedded fixtures (verdict levels counted, `note` excluded, malformed
  input safe, the catch/clean/FP arithmetic), wired into the lint job alongside the
  miner/oracle/metamorphic selftests. Keeps the harness honest on every push.
- **`corpus-benchmark` CI job (dotnet)** — runs the real benchmark. Some cases
  subscribe to framework events (WPF `Window`, `Microsoft.Win32.SystemEvents`), so
  it materializes the WindowsDesktop ref pack and exports `OWN_EXTRA_REF_DIRS` (the
  same mechanism as the oracle/mine jobs) — else a `+=` to an unresolved event is an
  `OWN050` note, not a leak. The gate is **asymmetric and honest**: precision is
  absolute (**every** `after.cs` silent, **zero** false positives — a regression
  there means crying wolf on correct code), while recall is pinned at a **floor**
  (`--min-recall`, currently 3) that ratchets up as the frontend's extraction
  coverage grows. We do *not* hard-assert 9/9 the tool cannot yet deliver — the
  benchmark *reports* the recall number and forbids it regressing, which is exactly
  what a measurement spine should do.

## Why it matters

This is the **measurement spine**. Until now "does Own.NET work?" was answered by
the `.own` logic check and anecdotal oracle overlaps; now there is a reproducible
recall/specificity number over real C#, pinned against regression. It is also the
**verifiable reward** for any future learning loop (RLVR): a deterministic verifier
over labeled real-C# data is exactly the clean reward signal — built *before* any
proposer/LLM layer, never trusting a source.

## Next

- Grow the corpus (P-012 stage 1 mining) — every new mined `before`/`after` pair is
  a new benchmark row for free; the number gets more defensible as N grows.
- Stage 2 prevalence scan (hits per 1k LOC across 50–100 repos) feeding the
  `docs/ROADMAP.md` priority matrix — replacing the proxy estimates with counts.
- Per-code recall and a precision breakdown once the corpus is large enough for the
  rates to mean something.
