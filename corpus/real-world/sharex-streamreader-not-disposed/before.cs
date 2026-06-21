// BEFORE (buggy). Reduced from ShareX @ ed2a864 —
// ShareX.HelpersLib/Helpers/Helpers.cs:854 (an XML-to-string formatter), found by mining
// (docs/notes/real-world-mining.md).
//
// A StreamReader is wrapped around a MemoryStream to read it back to a string, but the
// reader is never disposed. StreamReader is IDisposable and a SEPARATE resource from the
// (using-scoped) stream — the reader itself is left undisposed: the CA2000 / CodeQL
// cs/local-not-disposed class. Uses real System.IO types (BCL, no ref pack).
using System.IO;

static class XmlFormatter
{
    static string ToText(byte[] payload)
    {
        using MemoryStream ms = new MemoryStream(payload);
        ms.Position = 0;
        StreamReader sReader = new StreamReader(ms);   // <-- OWN001: never disposed
        return sReader.ReadToEnd();
    }
}
