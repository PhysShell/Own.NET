# P-005 — `IDisposable` ownership profile

- **Status:** draft (P0 — the most down-to-earth resource module)
- **Depends on:** `spec/OwnCore.md` (OWN001 leak, OWN002 use-after-release,
  OWN003 double-release), [P-001](P-001-csharp-extractor.md) (the C# seam).
  Shares the resource core with [P-004](P-004-wpf-lifetime-profile.md).
  See [`docs/ROADMAP.md`](../ROADMAP.md) (Milestone 2).

## Motivation

`IDisposable` is the single most common resource discipline in .NET, and the one
C# expresses worst: to the compiler, `.Dispose()` is just a method and the object
is still "valid" afterwards. So the bugs are everywhere and the language shrugs:
a stream not disposed on an exception path, a disposable field the owner forgets,
a write after `Dispose()`. These are exactly OwnLang's `acquire → must release on
all paths`, `use-after-release`, `double-release` — already proven on `.own`.
This profile points that core at real C#.

## Scope

The five concrete findings, all intraprocedural (or single-class) to start:

| Finding | Pattern | Core verdict |
|---------|---------|--------------|
| **D1** local not disposed | `new FileStream(...)` (or any `IDisposable`) not disposed on every path | `OWN001` |
| **D2** owned field not disposed | an `IDisposable` field whose owner's `Dispose()` does not cascade to it | `OWN001` |
| **D3** double dispose | `Dispose()` reachable twice | `OWN003` |
| **D4** use after dispose | `x.Dispose(); x.Write(...)` (same method/CFG) | `OWN002` |
| **D5** transfer unknown | a disposable handed to a callee whose ownership effect is unknown | (heuristic) |

Resource mapping (the vocabulary is already the core's):

```text
new IDisposable() / Open(...)  -> acquire(Disposable, loc)
Dispose() / using-scope end    -> release(Disposable, loc)
using (x) { ... }              -> acquire + guaranteed release
an IDisposable field           -> owned by the containing object
the owner's Dispose() body     -> the release region for owned fields
```

`using` declarations are the easy, sound case (guaranteed release); the value is
in the paths *without* `using`. D4 (use-after-dispose) is the part the reality
matrix marks **deterministic** — `x.Dispose(); x.Use();` in one CFG is plainly
visible, contrary to the myth that "`ObjectDisposedException` can't be caught
statically" (the *cross-thread race* can't; the local sequence can).

## Non-goals

- **Cross-thread / async disposal races** (thread A disposes while thread B
  reads) — a happens-before problem, not a structural one; out of scope (P3).
- Full interprocedural ownership transfer (D5) in v0 — model it as a *heuristic
  warning* plus an explicit transfer contract (`[OwnTransfers]` / an extern
  signature), rather than tracing every callee. Bug-driven later.
- Finalizers / `SafeHandle` internals / the full Dispose-pattern boilerplate
  audit (CA1063 territory) — we care about the leak, not the ceremony.

## Sketch

This *is* the resource core; WPF subscriptions (P-004) are a profile of it where
the resource is named `Subscription`. The extractor emits `acquire`/`release`
facts for `new`/`Dispose`/`using`/fields; the core runs its existing flow-
sensitive lattice (the same one that already produces OWN001/002/003 on `.own`).

```text
*.cs --[extractor: new / using / Dispose / field-cascade]--> facts.json
     --[core: flow lattice]--> OWN001 / OWN002 / OWN003 @ C# line
```

D2 (owned field) needs an object-level "owner releases its fields in `Dispose`"
fact — the same `owner(this, R)` + release-region machinery P-004 needs for
WPF003, so build it once. D5 stays a warning until a real bug forces a transfer
model.

## Open questions

1. Field ownership: does *every* `IDisposable` field imply the class must
   implement `IDisposable` and cascade, or only fields the class itself created
   (vs injected/borrowed)? (Injected ≈ borrowed, not owned — start there to cut
   false positives.)
2. What counts as a release region for D2 — `Dispose()` only, or also
   `DisposeAsync()` / `Close()`? (Conservative set first; async is P2.)
3. How to express ownership transfer at the call boundary (D5) without
   interprocedural analysis — extern signatures / `[OwnTransfers("arg0")]`?
4. Should `using`-covered locals be reported at all (they are sound) or stay
   silent to keep noise down? (Silent.)
