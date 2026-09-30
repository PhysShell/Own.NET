using K4os.Compression.LZ4.Streams;

// minimal repro of the K4os discovery class: LZ4Stream.Decode (BODY_PROVED fresh) makes the decoder a tracked acquire
public static class Repro
{
    // finding site: disposed twice -> Own.NET KEY OWN003 expected (OFF: the call is unknown, silent)
    public static void DoubleDispose(Stream inner)
    {
        var lz4 = LZ4Stream.Decode(inner);
        lz4.Dispose();
        lz4.Dispose();
    }

    // finding site: never disposed -> Own.NET KEY OWN001 expected; OFF silent
    public static int Leak(Stream inner)
    {
        var lz4 = LZ4Stream.Decode(inner);
        return lz4.ReadByte();
    }

    // control
    public static int Ok(Stream inner)
    {
        using var lz4 = LZ4Stream.Decode(inner);
        return lz4.ReadByte();
    }
}
