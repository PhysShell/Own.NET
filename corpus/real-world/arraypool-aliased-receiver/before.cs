// BEFORE (buggy). The same double-return bug as arraypool-double-return, but the pool
// is reached through an ALIASED receiver: `ArrayPool<int> p = ArrayPool<int>.Shared;`
// then `p.Rent(...)` / `p.Return(...)`. Caching the pool in a local (or a field) rather
// than repeating `ArrayPool<int>.Shared` at every call site is common real C#.
//
// This case is the proof for semantic-model pool recognition. A purely TEXTUAL detector
// keyed on the receiver spelling ("Pool"/"pool") cannot see `p.Rent` — the receiver `p`
// carries no "Pool" — so the buffer was invisible and this double-return was MISSED.
// Binding the call to System.Buffers.ArrayPool<T> via the Roslyn SemanticModel resolves
// the pool no matter how the receiver is spelled; the path-sensitive flow engine then
// flags the double release (OWN003).
//
// Wrapped in a class so the extractor's per-class flow pass visits it; Work stubbed.
using System.Buffers;

static class PoolAliasedReceiver
{
    static void Use(int n)
    {
        ArrayPool<int> p = ArrayPool<int>.Shared;   // the pool, via an aliased receiver
        int[] rented = p.Rent(n);
        try
        {
            Work(rented);
            p.Return(rented);   // returned here ...
        }
        finally
        {
            p.Return(rented);   // <-- ... and again here (double) -> OWN003
        }
    }

    static void Work(int[] buffer) { }
}
