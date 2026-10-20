// Harness control (00-preregistration.md): CA2000 must report ControlLeakOnThrow under AllPaths (K2)
// and not under the default kind (K1); ControlUsing must stay silent everywhere.
using System.IO;

namespace Repro;

public static class Control
{
    public static string ControlLeakOnThrow(string path)
    {
        var reader = new StreamReader(path); // ACQ:control
        var text = MayThrow(reader.ReadLine());
        reader.Dispose();
        return text;
    }

    public static string ControlUsing(string path)
    {
        using var reader = new StreamReader(path); // ACQ:control-using
        return MayThrow(reader.ReadLine());
    }

    private static string MayThrow(string? s) => s ?? throw new InvalidDataException();
}
