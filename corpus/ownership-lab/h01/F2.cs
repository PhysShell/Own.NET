using System;
using System.IO;
public static class F2
{
    // H-19 positives (must be clean under the flag)
    public static void NotEquals() { var x = new MemoryStream(); x.WriteByte(1); if (x != null) x.Dispose(); }
    public static void NullFirst() { var x = new MemoryStream(); x.WriteByte(1); if (null != x) x.Dispose(); }
    public static void IsNotNull() { var x = new MemoryStream(); x.WriteByte(1); if (x is not null) x.Dispose(); }
    public static void IsEmptyPattern() { var x = new MemoryStream(); x.WriteByte(1); if (x is { }) x.Dispose(); }
    public static void BlockBranch() { var x = new MemoryStream(); x.WriteByte(1); if (x != null) { x.Dispose(); } }
    public static void Parenthesised() { var x = new MemoryStream(); x.WriteByte(1); if ((x != null)) x.Dispose(); }
    // H-19 hostile twins (the guard must stay conditional: OWN001 'may not' expected for x)
    public static void GuardOnOtherLocal() { var x = new MemoryStream(); var y = new MemoryStream(); if (y != null) x.Dispose(); y.Dispose(); }
    public static void Conjunction(bool flag) { var x = new MemoryStream(); x.WriteByte(1); if (x != null && flag) x.Dispose(); }
    public static void BranchTouchesAnother() { var x = new MemoryStream(); var y = new MemoryStream(); if (x != null) { x.Dispose(); y.Dispose(); } }
    public static void WithElse() { var x = new MemoryStream(); x.WriteByte(1); if (x != null) x.Dispose(); else Console.WriteLine(); }
    public static void EqualsNullEarlyReturn() { var x = new MemoryStream(); x.WriteByte(1); if (x == null) return; x.Dispose(); }
    public static void GuardedUseOnly() { var x = new MemoryStream(); if (x != null) x.WriteByte(1); }   // never released: OWN001 'never' expected either way
}
