# P-034 — Runtime lifetime guard & disposal quarantine

- **Status:** draft.
- **Depends on:** `spec/OwnCore.md` (OWN001–003), [P-005](P-005-idisposable-ownership.md) (`D1`–`D5` `IDisposable` ownership), [P-004](P-004-wpf-lifetime-profile.md) (WPF profile); complements OwnAudit's runtime correlation (`OwnAudit/docs/runtime-contract.md`, phase 5).
- **Related, not overlapping:** [P-025](P-025-obligation-protocols.md) (obligation protocols) and [P-027](P-027-resource-state-machine.md) (resource state machines) are both **static, analysis-time** checks over source — P-027 explicitly ships no runtime type ("Own.NET does not ship a `ResourceState<T>` NuGet package as the mandated fix"). This proposal is the complementary **dynamic/runtime** half: something that actually executes and throws. No redundancy either way.

## Motivation

Trigger: a design discussion asked whether the "harden malloc/free with paranoid
enterprise checks" idea (common in C/C++ shops — wrap the allocator to catch
use-after-free / OOB / double-free) has a .NET analog. Conclusion, worth pinning
down before anyone re-derives it:

- As a **malloc shim**, the idea is nearly void under the CLR: bounds-checked
  arrays, a tracing GC, and the absence of manual `free()` already remove the
  C-style failure modes (use-after-free, OOB write, double-free) the
  enterprise-malloc pattern exists to catch.
- The *idea itself* — make lifetime misuse loud instead of silent — has a real
  .NET target, and Own.NET already built most of it as a **static** discipline:
  `OWN001` (leak), `OWN002` (use-after-dispose), `OWN003` (double-dispose),
  `OWN014` (region-escape / event retention) are exactly "managed
  use-after-free" and "managed double-free" for `IDisposable` and event
  subscriptions, proven end-to-end by P-005 (D1–D4 built) and
  P-004/WPF-region-escape. OwnAudit's phase 5 (`runtime-contract.md`) then
  confirms the WPF-specific case (event retention) against a real heap.

So the static half of "enterprise lifetime checking" is not a gap — it's shipped.
What's actually missing is the **dynamic/runtime half**: a lightweight guard
that fails loudly *at run time* for exactly the two cases static analysis
structurally cannot close — D5 (ownership transferred through an unmodeled
callee) and cross-thread disposal races (both explicit non-goals of P-005) —
plus a cheap, cross-platform substitute for OwnAudit's ClrMD heap walk that
runs in an ordinary unit test, no Windows stand required.

## What already exists (do not re-derive)

| Idea from the discussion | Already covered by |
|---|---|
| use-after-`Dispose` as managed use-after-free | `OWN002`, built (P-005 D4, flow-sensitive intraprocedural) |
| double `Dispose` as managed double-free | `OWN003`, built (P-005 D3) |
| `IDisposable` field/local never released | `OWN001`, built (P-005 D1/D2) |
| event `+=` without `-=` (leak) | `OWN001` subscription-leak category (P-004 WPF001–005) |
| static-event / long-lived source retaining a short-lived subscriber | `OWN014` region-escape (`docs/lifetimes.md` §4, slice #2/#3) |
| `DispatcherTimer`/`Timer` not stopped | `WPF002` |
| singleton captures scoped dependency (captive dependency) | `DI001`–`DI005` (P-006) |
| `ArrayPool<T>.Rent` without `Return`, use-after-`Return` | `POOL001`–`003` (P-007) |
| "boolean/nullable soup" standing in for a resource's lifecycle state | `ASYNC050` (P-027), static |
| runtime confirmation of a static leak against a real heap (WPF specifically) | OwnAudit phase 5 — `runtime.json` / ClrMD heap walk, confirmed / static-only / runtime-only buckets (`OwnAudit/docs/runtime-contract.md`) |

If a future task proposes any of the above as new work, point back here first.

## Deliberately out of scope already — don't re-open without new evidence

- **Raw `IntPtr` / `Marshal.Alloc*`/`Free*` balance proof.** Tagged *impossible
  statically* in the corpus-mining detectability matrix (P-012 §Non-goals:
  "unmanaged cyclic refs / `Marshal.AllocHGlobal` freed on all paths"). A
  flow-sensitive proof over arbitrary P/Invoke code is exactly the swamp
  OwnLang's `native` buffer policy avoids by only covering *code compiled
  through OwnSharp* (where `Free`/`NativeMemory.Free` is enforced by
  construction, `spec/BufferPolicies.md`), not arbitrary legacy C#.
- **`SafeHandle` internals / finalizer ceremony.** Explicit non-goal in P-005:
  "we care about the leak, not the ceremony." Requiring `SafeHandle` over a raw
  `IntPtr` is a one-line syntactic lint if anyone wants it (no dataflow needed
  — flag a field/param typed `IntPtr` that crosses a P/Invoke boundary and is
  never wrapped) but nobody has asked for it yet; noted here as a cheap future
  D-rule under P-005 if a corpus case ever needs it, not a commitment.

## Scope — the new piece: a runtime lifetime guard + disposal quarantine

Two small, independent, opt-in runtime helpers (a "diagnostic mode", not a
shipped allocator):

**1. `LifetimeGuard` base / wrapper — loud instead of silent.**
A `DEBUG`/`TEST`-only `IDisposable` base that turns the two silent failure
modes static analysis cannot close (D5 unknown transfer, cross-thread race)
into an immediate `ObjectDisposedException`/`InvalidOperationException` instead
of corrupting state quietly:

```csharp
public abstract class LifetimeGuard : IDisposable
{
    private int _disposed; // Interlocked — catches the cross-thread double-dispose race by construction
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
            throw new ObjectDisposedException(GetType().Name, "double Dispose");
        DisposeCore();
        GC.SuppressFinalize(this);
    }
    protected void ThrowIfDisposed() { if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(GetType().Name); }
    protected abstract void DisposeCore();
}
```

This does not replace `OWN002`/`OWN003` — those catch the mistake at compile
time, for free, when the pattern is intraprocedural. `LifetimeGuard` catches
what's left: ownership handed through a callee own-check doesn't model
(P-005 D5), and the cross-thread race P-005 explicitly declines to touch.

**2. Disposal quarantine for tests — a ClrMD-free complement to phase 5.**
An opt-in `ITrackedDisposable` + an ambient registry that records the
allocation-site stack trace on construction and asserts, at test teardown,
that nothing tracked is still undisposed:

```csharp
public interface ITrackedDisposable : IDisposable
{
    bool IsDisposed { get; }
}
// test base: DisposalQuarantine.AssertClean() at [TearDown] — throws with the
// recorded allocation-site stack trace for anything still live.
```

This is *not* a substitute for OwnAudit's phase 5 (`runtime-contract.md`) —
that walks the real CLR heap of the real app and is the only thing that proves
an object is *actually rooted* (via `roots[]`, e.g. a `static-event` delegate)
after realistic UI scenarios, on Windows, against STS. The quarantine only
proves "this object's own `Dispose()` was/wasn't called during this test" —
recall bounded by test coverage, exactly like any other dynamic check, and
blind to *why* something is still reachable. Its value is that it needs no CLR
heap walk, no Windows stand, and no compiled STS: it runs in an ordinary
`dotnet test`, in CI, for any class the team chooses to opt in — closer to a
debug assertion than an auditor.

## Non-goals

- Not a general-purpose allocator shim; nothing here wraps `malloc`/GC
  allocation.
- Not a production-safe pattern as-is: throwing from `Dispose()` is a real
  behavior change (already-suppressed `Dispose` exceptions in `finally`/`using`
  chains can mask the original exception) — `LifetimeGuard` must ship
  `DEBUG`/`TEST`-gated (e.g. `[Conditional]` on the throw, or a config flag),
  never silently opt production code into new exceptions.
- Not a replacement for `OWN002`/`OWN003` (compile-time, zero runtime cost,
  works before the code ever ships) or for OwnAudit phase 5 (ground-truth heap
  retention) — it fills the gap between them: cases neither can see, at the
  cost of only firing when a test actually exercises the path.
- Not a replacement for P-027's static state-machine lint (`ASYNC050`) — that
  flags the *shape* of ad-hoc lifecycle state in source; this catches *misuse*
  of an actual `Dispose()` contract at run time. Different signal, same theme.
- Not proposing to relitigate the `Marshal.Alloc*`/`SafeHandle` non-goals
  above.

## Open questions

1. Home for this: a new tiny package (`Own.Diagnostics`?) versus living inside
   OwnAudit's `runtime/` as a test-time collector alongside the ClrMD one?
   Leans OwnAudit, since it's audit tooling for *consumers'* code, not part of
   the OwnLang core checker.
2. Does the quarantine registry need to be thread-safe / async-local scoped
   per test, or is a single ambient static acceptable given tests already run
   isolated per fixture?
3. Should `LifetimeGuard`'s double-dispose check be `Interlocked`-based by
   default (cross-thread-safe) or opt-in, given most `IDisposable` usage in the
   STS corpus is single-threaded and the extra `Interlocked.Exchange` has a
   (tiny) cost?
4. Worth a corpus entry (P-012) once a real cross-thread
   `ObjectDisposedException` or D5-transfer bug is mined, to validate
   `LifetimeGuard` actually would have caught it?
