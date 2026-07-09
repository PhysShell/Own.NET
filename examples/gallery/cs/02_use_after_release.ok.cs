using System.IO;

namespace GalleryCs;

// 02_use_after_release (fixed) — no touch after Dispose() -> silent.
public class UseAfterReleaseOk
{
    public void Run()
    {
        var galleryUseAfterReleaseOk = new MemoryStream();
        galleryUseAfterReleaseOk.WriteByte(1);
        galleryUseAfterReleaseOk.Dispose();
    }
}
