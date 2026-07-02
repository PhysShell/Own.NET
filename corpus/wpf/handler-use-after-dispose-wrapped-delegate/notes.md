# Handler-use-after-dispose through an explicit-delegate `+=` (OWN002 recognition)

**Pattern.** A view owns its event source (`_source = new Publisher()`), subscribes with an
explicit delegate creation `_source.Changed += new EventHandler(OnSourceChanged)`, and a late
`Changed` event — fired after `Dispose()` — reads the disposed `_conn` in the handler. Because the
source is self-owned, the subscription is **not** an OWN001 leak; the defect is the **OWN002**
use-after-dispose in the still-live handler.

**The bug (Own.NET extractor).** The handler-use-after-dispose pass keys live subscription targets
by `IsHandler(a.Right)` / `FieldName(a.Right)` on the **raw** RHS. A wrapped
`+= new EventHandler(OnSourceChanged)` fails `IsHandler`, so `OnSourceChanged` never enters the
subscribed-handler set and its disposed-field read escapes OWN002 (Codex P2 on #163) — the same
`NormalizeHandler` gap the release-matching fix closed, in a second pass. The fix applies
`NormalizeHandler` to the live-subscription keying too, so the wrapped and target-typed spellings
register consistently.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught** (OWN002) and
`after.cs` must be **silent**. Before the fix, `before.cs` is missed (the wrapped handler is never
tracked); after it, the OWN002 fires. `after.cs` guards the read (`if (_disposed) return;`) and is
clean either way — the source is self-owned, so there is no OWN001 to entangle the specificity check.
