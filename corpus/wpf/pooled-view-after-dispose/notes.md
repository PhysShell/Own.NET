# Pooled-buffer view-in-a-field, read after the owner is returned

**Pattern:** a type rents a pooled buffer (`IMemoryOwner<byte>` from `MemoryPool<byte>`), keeps a
`Memory<byte>` **view of it in a field**, and subscribes a handler to an event source. On teardown
`Dispose()` returns the buffer to the pool (disposing the owner), but a callback already queued on the
dispatcher still runs after `Dispose()` and reads the field-held view — a `Memory` backed by a buffer
already handed back to the pool: a dangling borrow / use-after-free (an `ObjectDisposedException`, or
stale/torn bytes once the buffer is re-rented). It is the pooled-buffer, field-stored cousin of the
local returned-view dangle (`memorypool-view-after-dispose`) and of the disposed-field UAF
(`field-use-after-dispose`).

**What's new — the extractor follows the view-field to its owner.** The field-mediated
use-after-dispose pass (#75/#76) is generalised to **pooled owners** and their **Memory views**: an
`IMemoryOwner<T>` field released in `Dispose()` is a released owner, and a `Memory`/`ReadOnlyMemory`
field assigned `_owner.Memory` (or `_buf.AsMemory(...)`) is recorded as a **view of that owner**. A
read of the view field (or of the owner directly) in a live subscription-target handler — directly or
one hop through a private helper — with no `if (_disposed) return;` guard before it, is lowered to a
synthetic `acquire`/`release`/`use` flow on the owner → **OWN002**, via the existing OwnIR bridge (no
new diagnostic). On the real C# the `corpus-benchmark` job scores `before.cs` as caught and the
guarded `after.cs` as silent.

**Precision (why it stays low-FP).** The same reachability that makes the disposed-field UAF sound: a
live (not unsubscribed) handler can fire *after* `Dispose()`, so reading the owner's buffer (through
its view field) then is a use-after-release. The guard exclusion is the canonical fix; an unsubscribed
or guarded handler never fires; the owner must be released in the dispose lifecycle; and the view→owner
alias is recognised by the resolved `IMemoryOwner<T>.Memory` / `MemoryExtensions.AsMemory` symbols, not
by name. Exposing such a view via a public getter is **not** flagged — `IMemoryOwner.Memory` is itself
a legitimate "valid until Dispose" pattern, so the exposure is sound; only a provably-post-release read
(the handler reachability) is a bug.

**Honesty / scope.** This slice covers an **`IMemoryOwner<T>`** owner field and its `Memory` view read
via member access (`_view.Span`, `_view.Length`, …) in a handler/helper. Honest follow-ups: an
**ArrayPool `byte[]` buffer field** returned in `Dispose()` (it interacts with the existing per-member
pool-leak pass), the view passed as a **bare argument** (`Consume(_view)`) rather than through a member
access, and **element-access** reads (`_buf[i]`). `case.own` is a faithful hand reduction of the
ownership logic; `before.cs` / `after.cs` are representative of the bug and its fix.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the local twin is
`memorypool-view-after-dispose`; the disposed-field twins are `field-use-after-dispose` /
`handler-use-after-dispose`.
