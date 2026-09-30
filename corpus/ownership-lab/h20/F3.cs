using System;
using System.IO;
public static class F3
{
    // H-20 positive: an argument guard that THROWS before a fresh return -> fresh
    public static MemoryStream GuardedFactory(byte[] data)
    {
        if (data == null) throw new ArgumentNullException(nameof(data));
        return new MemoryStream(data);
    }
    // positive: the guard throws via a helper call that itself throws (ThrowIfNull-style is a call: no edge at body level)
    public static MemoryStream GuardedFactory2(byte[] data)
    {
        if (data.Length == 0) { throw new ArgumentException("empty"); }
        var ms = new MemoryStream(data);
        return ms;
    }
    // twin: a null VALUE return on one path -> stays none
    public static MemoryStream NullOnOnePath(byte[] data)
    {
        if (data == null) return null;
        return new MemoryStream(data);
    }
    // twin: conditional null value -> stays none
    public static MemoryStream ConditionalNull(bool c) => c ? new MemoryStream() : null;
    // twin: a field returned on one path -> stays not fresh
    static MemoryStream s_shared = new MemoryStream();
    public static MemoryStream FieldOnOnePath(bool c)
    {
        if (c) throw new InvalidOperationException();
        if (s_shared.CanRead) return s_shared;
        return new MemoryStream();
    }
    // consumer: the guarded factory's result dropped -> OWN001 expected under the flag (fresh proved), silent off
    public static void Consumer()
    {
        var m = GuardedFactory(new byte[] { 1 });
        m.WriteByte(2);
    }
    public static void ConsumerTwin()
    {
        var m = NullOnOnePath(new byte[] { 1 });
        m?.WriteByte(2);
    }
}
