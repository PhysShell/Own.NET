// A statement-level call. The C# lowering emits a `call` op in exactly ONE
// place and only for `var x = Foo(...)` — a call whose RESULT binds to a local.
// `Inner(s, true);` as a statement produces no `call` node at all, so there is
// nothing for a summary layer to specialise. Without this, F3 cannot be carried
// through the existing summary layer at all.
//
// This is also where a2's zero-semantic-cut risk lives: a real `call` op is
// already semantically active and MOS reads it, so emitting one here can move
// an existing summary before the guarded kernel is anywhere near. The MOS
// collapsed-view diff is what catches that.
using System.IO;

static class ShapeStatementCall
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Inner(r, true);
    }
}
