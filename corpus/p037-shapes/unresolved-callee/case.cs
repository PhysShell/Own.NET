// Negative control: a call whose target does not resolve. There is no
// declaration to bind against, so the record says `callee: null` and binds by
// SOURCE position — it must still exist, and must not guess a callee.
using System.IO;

static class ShapeUnresolved
{
    static void Caller(Stream p, bool keep)
    {
        Missing.Close(p, keep);
    }
}
