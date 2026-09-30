using System;
using System.IO;
public static class F1
{
    // H-01 positive: null-initialised, assigned once in try, released in finally (null-conditional) -> clean
    public static void TryFinallyNullConditional()
    {
        MemoryStream x = null;
        try { x = new MemoryStream(); x.WriteByte(1); }
        finally { x?.Dispose(); }
    }
    // H-01 positive twin with the null-guard idiom (see F0: the guard itself is a separate production observation)
    public static void TryFinallyNullGuard()
    {
        MemoryStream x = null;
        try { x = new MemoryStream(); x.WriteByte(1); }
        finally { if (x != null) x.Dispose(); }
    }
    // H-01 negative: assigned once, never released -> OWN001 expected at the assignment
    public static void AssignedNeverReleased()
    {
        MemoryStream x = null;
        x = new MemoryStream();
        x.WriteByte(1);
    }
    // hostile: conditional acquire, null-conditional release -> clean
    public static void ConditionalAcquire(bool c)
    {
        MemoryStream x = null;
        if (c) x = new MemoryStream();
        x?.Dispose();
    }
    // hostile: two assignments -> NOT a candidate (the s11 family, not H-01's); must stay silent under H-01
    public static void TwoAssignments()
    {
        MemoryStream x = null;
        x = new MemoryStream();
        x = new MemoryStream();
        x.Dispose();
    }
    // hostile: assigned from a non-acquire (a parameter) -> not a candidate
    public static void AssignedFromParameter(MemoryStream p)
    {
        MemoryStream x = null;
        x = p;
        x.WriteByte(1);
    }
    // first-party fresh factory through the assignment form -> a call op; the core decides fresh
    public static void AssignedFromFactory()
    {
        MemoryStream x = null;
        x = Make();
        x.WriteByte(1);
    }
    static MemoryStream Make() { var m = new MemoryStream(); return m; }
    // hostile: the local escapes by return after the assignment -> silent (return is the transfer out)
    public static MemoryStream AssignedAndReturned()
    {
        MemoryStream x = null;
        x = new MemoryStream();
        return x;
    }
    // hostile: ref rebinding -> not a candidate
    public static void RefRebound()
    {
        MemoryStream x = null;
        x = new MemoryStream();
        Rebind(ref x);
    }
    static void Rebind(ref MemoryStream m) { m = null; }
}
