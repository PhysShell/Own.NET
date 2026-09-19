// A tracked handle local passed by `ref` is unrepresentable precisely (the
// slot must be opaque), but it still flowed: the call record must exist, not
// vanish. Same relevance/representability separation as the `params` shape,
// via a different route Roslyn treats specially (RefKindKeyword, not a
// resolved `params` parameter). `keep` is a second, non-escaping local
// purely so the method still gets flow-analysed at all.
using System.IO;

static class ShapeRefOutHandle
{
    static void Touch(ref Stream s)
    {
    }

    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        Touch(ref s);
        keep.Dispose();
        s.Dispose();
    }
}
