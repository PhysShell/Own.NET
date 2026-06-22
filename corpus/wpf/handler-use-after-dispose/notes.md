# WPF field-use-after-dispose reached INDIRECTLY (through a helper)

**Pattern:** a ViewModel owns an `IDisposable` (here a `SqlConnection`) and subscribes a handler to
an event source. On teardown `Dispose()` disposes the connection (and the subscription token), but a
callback already queued on the dispatcher still runs after `Dispose()` and reaches the disposed
connection **indirectly** — the handler calls a private `Refresh()` helper that reads `_conn`. In
real code this is an `ObjectDisposedException` or a read of torn state — the use-after-dispose cousin
of the zombie-ViewModel leak.

**What's new — the extractor catches the one hop.** The Roslyn extractor's field-mediated
use-after-dispose pass (under `--flow-locals`) already caught a **direct** `_field.Member` read in a
live handler (`field-use-after-dispose`). This slice chases a **single hop**: a subscribed handler
that calls a **private same-class helper** (`Refresh()` / `this.Refresh()`) which itself
*unguardedly* reads a disposed field — with no `if (_disposed) return;` guard before the call — is
lowered to a synthetic `acquire`/`release`/`use` flow → **OWN002**, via the existing OwnIR bridge
(no new diagnostic). On the real C# the `corpus-benchmark` job scores `before.cs` as caught and
`after.cs` (the guarded fix) as silent.

**Precision (why it stays low-FP).** One hop only — a deeper chain stays an honest miss. The helper
must be a **private instance** method (not a public/virtual member with a broader contract); both the
handler (before the call) and the helper must lack a disposed-guard; and the field read is a
**direct** `this`-owned `_field.Member`. The guard exclusion is the canonical fix, so the guarded
`after.cs` is silent.

**Honesty / scope.** This catches the **direct** read (`field-use-after-dispose`) and now the
**one-hop indirect** read (this case). A two-plus-hop chain, or a read through a field/property
indirection, remains an honest extractor miss — the `case.own` reduction still fires OWN002, showing
the ownership logic maps onto the real bug. `before.cs` / `after.cs` are representative of the bug
and its fix.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the direct twin is
`field-use-after-dispose`; the late-callback framing matches `zombie-viewmodel`.
