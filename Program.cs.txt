// Golden runnable example for the OwnLang PoC.
//
// The process(...) method below is EMITTED VERBATIM by:
//     python -m ownlang emit examples/golden_arraypool/buffer.own
// Everything else (Main and the Fill/Hash stubs) is hand-written host code:
// an `extern fn` is a promise the host keeps, so the host supplies the body.
//
// Build & run (requires a .NET SDK; there is none in the PoC sandbox, so this
// was verified by construction + by the OwnLang checker, not executed here):
//     cd examples/golden_arraypool && dotnet run
//
using System;
using System.Buffers;

public static class PoolDemo
{
    // ===== emitted verbatim by OwnLang (ownership-checked) =====
    public static void process(int size)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(size);
        try
        {
            { // mutable borrow of buf as bytes
                var bytes = buf.AsSpan();
                Fill(bytes);
            }
            { // shared borrow of buf as view
                var view = buf.AsSpan();
                Hash(view);
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buf);
        }
    }
    // ===== end emitted region =====

    // Host-provided externs. Borrow params are noescape: these must not retain
    // the span beyond the call. Span<byte> converts implicitly to ReadOnlySpan.
    static void Fill(Span<byte> b)
    {
        for (int i = 0; i < b.Length; i++) b[i] = (byte)(i & 0xFF);
    }

    static void Hash(ReadOnlySpan<byte> b)
    {
        int h = 17;
        foreach (var x in b) h = unchecked(h * 31 + x);
        Console.WriteLine($"hash={h} len={b.Length}");
    }

    public static void Main()
    {
        process(64);
        Console.WriteLine("ok");
    }
}
