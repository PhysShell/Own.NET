using System;
using System.IO;

namespace GalleryCs;

// 07_use_after_handoff (bad) — C#-native mirror of
// examples/gallery/07_use_after_handoff.own: OWN002, use after ownership was
// consumed by a callee. Real C#: a method takes ownership (it will Dispose),
// then the caller touches the value again. Reduced from the same pattern as
// corpus/real-world/ownership-handoff-use/.
public static class UseAfterHandoff
{
    // Consumer: takes ownership of `sink` and closes it.
    public static void Consume(Stream sink)
    {
        sink.CopyTo(Stream.Null);
        sink.Dispose(); // Consume owns and closes it
    }

    public static long Run(string path)
    {
        var galleryHandoff = File.OpenRead(path);
        Consume(galleryHandoff);       // ownership moves to Consume
        return galleryHandoff.Length;  // ...but we used it afterwards -> OWN002
    }
}
