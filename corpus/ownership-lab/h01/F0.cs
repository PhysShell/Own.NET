using System;
using System.IO;
public static class F0
{
    public static void NullGuardRelease()
    {
        var x = new MemoryStream();
        x.WriteByte(1);
        if (x != null) x.Dispose();       // control: a null guard on a tracked local must not read as 'may not release'
    }
    public static void NullConditionalRelease()
    {
        var x = new MemoryStream();
        x.WriteByte(1);
        x?.Dispose();
    }
    public static void TryFinallyNullGuard()
    {
        var x = new MemoryStream();
        try { x.WriteByte(1); }
        finally { if (x != null) x.Dispose(); }
    }
}
