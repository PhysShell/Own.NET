using System;
using System.IO;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// The same shape with the stream LEAKED: the IDisposable reading still reports it, which
// is the proof that a region in the method does not switch the other analysis off.
public static class L12RegionBesideLeakedDisposable
{
    public static void Run(Order order)
    {
        var log = new MemoryStream();
        log.WriteByte(1);
        Protocol.WithApproved(order, approved =>
        {
            approved.Ship();
        });
    }
}
