// An owned parameter that fails the whole-body stability check (G-V4: it is
// reassigned somewhere in the method) is still an OWNED parameter — stability
// decides `param` vs `opaque` representation, per spec/OwnIR.md §5.2, it does
// not decide whether the call is relevant. The call record must exist with
// an opaque slot for `p`, not vanish because `p` happened to be unstable.
using System.IO;

static class ShapeUnstableOwnedParam
{
    static void Sink(Stream s)
    {
    }

    static void Caller(Stream p, bool replace)
    {
        if (replace)
        {
            p = null;
        }
        Sink(p);
    }
}
