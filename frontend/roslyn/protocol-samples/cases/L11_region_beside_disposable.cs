using System;
using System.IO;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// A method that opens a region AND owns an IDisposable. The two lowerings are independent
// readings of one method (they track disjoint resources), so each gets its own record.
// The stream here is disposed, so both are clean.
public static class L11RegionBesideDisposable
{
    public static void Run(Order order)
    {
        var log = new MemoryStream();
        log.WriteByte(1);
        Protocol.WithApproved(order, approved =>
        {
            approved.Ship();
        });
        log.Dispose();
    }
}
