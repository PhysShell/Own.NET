using System;
using System.IO;

// P-005 D5.4 step 2 (T4 wrap/adopt): the Roslyn extractor recognises a first-party wrapper
// that ADOPTS a disposable argument into an owning field (its Dispose disposes that field, its
// ctor stores the arg into it) and emits an `alias_join` — so the wrapper and the inner share
// ONE obligation. Disposing either discharges it; disposing both is a double-dispose; dropping
// both leaks the one resource ONCE. A non-adopting wrapper makes NO claim (precision-first).
namespace OwnSharp.Samples
{
    // VERIFIED ADOPTER: Dispose disposes the field unconditionally; the ctor assigns the field
    // directly from its parameter. -> `new StreamAdopter(s)` adopts `s`.
    internal sealed class StreamAdopter : IDisposable
    {
        private readonly MemoryStream _inner;
        public StreamAdopter(MemoryStream inner) { _inner = inner; }
        public void Dispose() { _inner.Dispose(); }
        public void Poke() { }
    }

    // NON-ADOPTER: holds the disposable but its Dispose does NOT dispose it. The extractor must
    // make no alias claim, so disposing both the holder and the inner is NOT a double-dispose.
    internal sealed class StreamHolder : IDisposable
    {
        private readonly MemoryStream _held;
        public StreamHolder(MemoryStream held) { _held = held; }
        public void Dispose() { }
    }

    internal static class AdoptConsumers
    {
        // Disposing the wrapper alone discharges the shared obligation -> CLEAN (silent).
        public static void AdoptClean()
        {
            var adoptInnerClean = new MemoryStream();
            var adoptWrapClean = new StreamAdopter(adoptInnerClean);
            adoptWrapClean.Dispose();
        }

        // Dropping BOTH leaks the one underlying resource ONCE (OWN001 on the inner).
        public static void AdoptLeak()
        {
            var adoptInnerLeak = new MemoryStream();
            var adoptWrapLeak = new StreamAdopter(adoptInnerLeak);
            adoptWrapLeak.Poke();
        }

        // Disposing BOTH aliases is a double-dispose (OWN003).
        public static void AdoptDouble()
        {
            var adoptInnerDbl = new MemoryStream();
            var adoptWrapDbl = new StreamAdopter(adoptInnerDbl);
            adoptInnerDbl.Dispose();
            adoptWrapDbl.Dispose();
        }

        // Disposing the inner directly (the Dapper "dispose-the-inner" path) also discharges
        // the shared obligation -> CLEAN (silent).
        public static void AdoptInnerOnly()
        {
            var adoptInnerDirect = new MemoryStream();
            var adoptWrapDirect = new StreamAdopter(adoptInnerDirect);
            adoptInnerDirect.Dispose();
        }

        // TARGET-TYPED `new(...)`: the adopt must be recognised for an implicit object creation
        // too (Codex P2). Disposing the inner directly discharges the shared obligation -> CLEAN.
        public static void AdoptTargetTyped()
        {
            var adoptInnerTt = new MemoryStream();
            StreamAdopter adoptWrapTt = new(adoptInnerTt);
            adoptInnerTt.Dispose();
        }

        // PRECISION CONTROL: a NON-adopting holder. No alias is claimed, so the inner escapes as
        // an argument (silent) and disposing both must NOT be a false double-dispose.
        public static void NonAdoptDoubleOk()
        {
            var holdInner = new MemoryStream();
            var holdWrap = new StreamHolder(holdInner);
            holdInner.Dispose();
            holdWrap.Dispose();
        }
    }
}
