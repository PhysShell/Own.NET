# WPF field-mediated use-after-dispose (a disposed field touched in a handler)

**Pattern:** a ViewModel owns an `IDisposable` field (here a `SqlConnection`) and
subscribes a handler to an event source. On teardown `Dispose()` disposes the field
(and the subscription token), but a callback that was **already queued on the
dispatcher** still runs after `Dispose()` and **directly reads the disposed field**
(`_conn.ChangeDatabase(...)`). In real code this is an `ObjectDisposedException` or a
read of torn state — the field-mediated cousin of the zombie-ViewModel leak. The
defensive fix (the canonical one) is a disposed-flag guard at the top of the handler;
relying on unsubscribe-ordering alone does not close the already-queued-callback race.

**What's new — the extractor catches this end-to-end.** The Roslyn extractor's
field-mediated cross-method use-after-dispose pass (under `--flow-locals`) recognises
an `IDisposable` field that is

  1. disposed in this class's `Dispose()` / `DisposeAsync()` (the lifecycle release),
  2. directly read (`_field.Member`) inside a **live subscription target** — a method
     that is the RHS of a `+=` or the argument of a `.Subscribe(...)`, and whose
     subscription is **not** torn down by a matching `-=` (an unsubscribed callback
     cannot fire post-dispose, so it is exempt), and
  3. read in a handler with **no** `if (_disposed) return;` guard,

and lowers it to a synthetic `acquire`/`release`/`use` flow. That rides the existing
OwnIR bridge — the same machinery the local-disposable and MemoryPool slices use — so
the core raises **OWN002** ("use after release") with no new diagnostic and no second
checker. `case.own` is the hand reduction of exactly that flow; on the real C# the
`corpus-benchmark` job scores `before.cs` as caught (OWN002) and `after.cs` (the
guarded fix) as silent.

**Precision (why it stays low-FP).** The check fires only on a field disposed in the
dispose *lifecycle*, used in a *live* subscription target, with no guard, via a
**direct** field member access. The guard exclusion is the canonical fix, so a fixed
handler is silent; an unsubscribed (`-=`) or empty handler never fires; and an
*indirect* use through a helper is deliberately **not** chased.

**Honesty / scope.** This catches the **direct** `_field.Member` read. Its sibling
`handler-use-after-dispose` reaches the disposed state **indirectly** (`Refresh()`
touches subscription-backed state) — the extractor does not follow that hop, so that
case remains an honest extractor miss (a tracked recall gap, not a logic gap: its
`case.own` reduction still fires OWN002). `case.own` here is a faithful hand reduction
of the ownership logic; `before.cs` / `after.cs` are representative of the bug and its
fix, not a verbatim copy of one PR.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the indirect twin
is `handler-use-after-dispose`; the late-callback framing matches `zombie-viewmodel`.
