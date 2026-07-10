using System.IO;

namespace GalleryCs;

// 02_use_after_release (bad) — C#-native mirror of
// examples/gallery/02_use_after_release.own: OWN002, use after release (definite).
// Real C#: touching a stream after Dispose() -> ObjectDisposedException at runtime.
public class UseAfterRelease
{
    public void Run()
    {
        var galleryUseAfterRelease = new MemoryStream();
        galleryUseAfterRelease.WriteByte(1);
        galleryUseAfterRelease.Dispose();
        galleryUseAfterRelease.WriteByte(2); // used after Dispose() -> OWN002
    }
}
