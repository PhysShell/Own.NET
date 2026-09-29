using System.IO;

// #380 (INF-S2): the call-site handoff models a first-party consumer's release as a `release`
// of the caller's argument — an unconditional `must`. It may only do so when the callee's
// release is DEFINITE. A release behind a guard is partial (INF-S2 -> `may`), and lowering its
// call as a handoff fabricated false OWN002/OWN003/OWN009 at callers that keep the resource, and
// a false `must` summary on wrappers that forward their own parameter that way.
//
// Checked by tests/test_guarded_consume.py (facts AND verdicts, on the real extractor).
public static class GuardedConsumeSample
{
    // Partial: releases only when the flag says so.
    private static void MaybeClose(Stream s, bool dispose)
    {
        if (dispose)
            s.Dispose();
    }

    // Partial: a guarded early return skips the release.
    private static void CloseUnlessKept(Stream s, bool keep)
    {
        if (keep)
            return;
        s.Dispose();
    }

    // Partial through the chain: forwards to a definite consumer only under a guard.
    private static void MaybeForward(Stream s, bool forward)
    {
        if (forward)
            Close(s);
    }

    // Definite: the handoff anchor.
    private static void Close(Stream s)
    {
        s.Dispose();
    }

    // Definite: every return runs through the finally.
    private static int CloseInFinally(Stream s)
    {
        try
        {
            return s.ReadByte();
        }
        finally
        {
            s.Dispose();
        }
    }

    // (a) the guard is false, so the callee keeps the stream; the caller uses it and disposes it.
    // Must NOT be lowered as a release (it was: a false OWN002 on the write, a false OWN003 on
    // the dispose).
    public static void GuardFalseThenUseAndDispose()
    {
        var keptStream = new MemoryStream();
        MaybeClose(keptStream, false);
        keptStream.WriteByte(1);
        keptStream.Dispose();
    }

    // (a) early-return spelling of the same partial release.
    public static void EarlyReturnKeptThenUseAndDispose()
    {
        var earlyKept = new MemoryStream();
        CloseUnlessKept(earlyKept, true);
        earlyKept.WriteByte(1);
        earlyKept.Dispose();
    }

    // (a) guarded transitive forward.
    public static void GuardedForwardFalseThenUseAndDispose()
    {
        var forwardKept = new MemoryStream();
        MaybeForward(forwardKept, false);
        forwardKept.WriteByte(1);
        forwardKept.Dispose();
    }

    // (b) the guard is true, so the callee releases and the caller relies on it. Nothing beyond
    // current sound inference may be claimed: no fabricated release, and no fabricated leak
    // either — the caller must stay silent.
    public static void GuardTrueRelyOnCallee()
    {
        var handedStream = new MemoryStream();
        MaybeClose(handedStream, true);
    }

    // (c) definite consumer: still a handoff, so a later use is a true use-after-handoff.
    public static void DefiniteHandoffThenUse()
    {
        var handoffStream = new MemoryStream();
        Close(handoffStream);
        handoffStream.WriteByte(1);
    }

    // (c) definite through a finally: still a handoff.
    public static void FinallyHandoffThenUse()
    {
        var finallyStream = new MemoryStream();
        CloseInFinally(finallyStream);
        finallyStream.WriteByte(1);
    }

    // Wrapper forwarding its OWN parameter with the guard false: the parameter is borrowed, so
    // its summary must be `no`, never a fabricated `must`.
    public static void BorrowingWrapper(Stream borrowed)
    {
        MaybeClose(borrowed, false);
    }

    // KNOWN LIMITATION, pinned rather than accepted: the guard is forwarded, so whether the
    // stream is consumed depends on the caller. INF-S3 would summarize this `may` (a forward to a
    // `may` callee); today the forward is folded into a `use` and the summary is `no`. Reaching
    // `may` needs a canonical first-party call fact, outside #380. When that representation
    // lands this pin moves, and #304's reopen condition 1 is due for a re-check.
    public static void ForwardDynamic(Stream forwarded, bool dispose)
    {
        MaybeClose(forwarded, dispose);
    }
}
