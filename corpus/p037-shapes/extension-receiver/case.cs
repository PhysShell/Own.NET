// A reduced EXTENSION method. Roslyn's reduced symbol drops the `this`
// parameter from `Parameters`, but the summary lives on the UNREDUCED
// declaration where the receiver is parameter 0. a2 must synthesise
//   receiver -> declared parameter 0
//   timeout  -> declared parameter 1
// or `CallReleasesReceiver` can never be honestly retired: the guarded
// summaries would be complete except for one old tunnel under the fence.
using System.IO;

static class ShapeExtensionReceiver
{
    static void WaitForDispose(this Stream self, int timeout)
    {
        if (timeout >= 0)
        {
            self.Dispose();
        }
    }

    static void Caller(string path)
    {
        var s = File.OpenRead(path);
        s.WaitForDispose(5);
    }
}
