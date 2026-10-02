using System;
using System.IO;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// What a region MAY contain besides transitions: locals captured from outside, literals,
// built-in operators, token reads, `if`. Everything that needs a call is computed before.
public static class L13ValuesCapturedIntoRegion
{
    public static void Run(Order order, int limit)
    {
        var threshold = limit * 2;
        Protocol.WithApproved(order, approved =>
        {
            var over = approved.Id > threshold;
            if (over && limit != 0)
            {
                approved.Ship();
            }
            else
            {
                approved.Ship();
            }
        });
    }
}
