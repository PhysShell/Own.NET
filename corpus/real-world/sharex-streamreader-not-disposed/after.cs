// AFTER (fixed): scope the reader with `using` too, so the StreamReader is disposed (not
// just the underlying stream). Disposed on every path -> silent.
using System.IO;

static class XmlFormatter
{
    static string ToText(byte[] payload)
    {
        using MemoryStream ms = new MemoryStream(payload);
        ms.Position = 0;
        using StreamReader sReader = new StreamReader(ms);
        return sReader.ReadToEnd();
    }
}
