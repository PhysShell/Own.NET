// The caller names its arguments OUT of declaration order. Today the extractor
// drops every named argument from a call's `args` (`a.NameColon is null`),
// which is defensible for a positional model and fatal for P-037: all four F3
// fixtures pass their guard by name. a2 must RESOLVE a named argument to its
// declared parameter slot, never keep source order and hope.
using System.IO;

static class ShapeNamedArgs
{
    static void Inner(Stream resource, bool flag)
    {
        if (!flag)
        {
            resource.Dispose();
        }
    }

    static void Caller(string path)
    {
        var s = File.OpenRead(path);
        Inner(flag: true, resource: s);
    }
}
