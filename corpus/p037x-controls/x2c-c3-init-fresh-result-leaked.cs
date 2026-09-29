// P-037-X Stage 2c hostile control X2C-C3: the initializer's object creation takes the handle
// and its result is a fresh disposable that is itself leaked. OWN001 for the fresh result as
// today; nothing new for the handle (a parameter, disposed by this method).
using System.IO;

static class X2cC3
{
    static void Wrap(Stream r)
    {
        var w = new StreamReader(r);
        r.Dispose();
    }
}
