using System;
using System.IO;
public static class Complementary
{
    public static void Comp(int count)
    {
        var x = new MemoryStream();
        x.WriteByte(1);
        if (count > 10) x.Dispose();
        if (count <= 10) x.Dispose();     // complementary: exactly one release on every path
    }
    public static void Gap(int count)
    {
        var x = new MemoryStream();
        x.WriteByte(1);
        if (count > 10) x.Dispose();
        if (count < 10) x.Dispose();      // count == 10 leaks
    }
    public static void Twin(int count)
    {
        var x = new MemoryStream();
        x.WriteByte(1);
        if (count > 10) x.Dispose(); else x.Dispose();   // the if/else form the syntax pipeline handles
    }
}
