using System.IO;

namespace GalleryCs;

// 03_double_release (bad) — C#-native mirror of
// examples/gallery/03_double_release.own: OWN003, double release.
// Real C#: Dispose() called twice (and the type isn't idempotent about it).
public class DoubleRelease
{
    public void Run()
    {
        var galleryDoubleRelease = new MemoryStream();
        galleryDoubleRelease.Dispose();
        galleryDoubleRelease.Dispose();
    }
}
