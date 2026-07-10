using System.IO;

namespace GalleryCs;

// 07_use_after_handoff (fixed) — read what's needed BEFORE handing ownership
// off, then never touch the stream again -> silent.
public static class UseAfterHandoffOk
{
    public static void Consume(Stream sink)
    {
        sink.CopyTo(Stream.Null);
        sink.Dispose();
    }

    public static long Run(string path)
    {
        var galleryHandoffOk = File.OpenRead(path);
        long len = galleryHandoffOk.Length; // read first ...
        Consume(galleryHandoffOk);          // ... then move ownership last
        return len;
    }
}
