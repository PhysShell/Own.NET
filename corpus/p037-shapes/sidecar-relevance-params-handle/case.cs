// A tracked handle flowing into a `params` slot is unrepresentable precisely
// (the slot must be opaque, per spec/OwnIR.md §5.2), but it still flowed: the
// call record must exist, not vanish. Relevance and representability are
// orthogonal. `keep` is a second, non-escaping local purely so the method
// still gets flow-analysed at all (a method whose only tracked local fully
// escapes into a non-consuming callee is legitimately skipped upstream of
// the guarded-fact sidecar; that is unrelated to what this shape tests).
using System.IO;

static class ShapeParamsHandle
{
    static void Sink(params Stream[] xs)
    {
    }

    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        Sink(s);
        keep.Dispose();
        s.Dispose();
    }
}
