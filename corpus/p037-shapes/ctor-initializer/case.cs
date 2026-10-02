// A2.2 G-B: `: base(s, keep)` hands the owned parameter to the base
// constructor before the body runs. It is a call; A2.1 does not record it.
// (The constructor has a body so that its record exists at all: an empty-body
// constructor is the record-absence boundary, see record-absence-boundary.)
using System.IO;

class GuardedBase
{
    protected GuardedBase(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }
}

class ForwardingDerived : GuardedBase
{
    public ForwardingDerived(Stream s, bool keep) : base(s, keep)
    {
        s.Flush();
    }
}
