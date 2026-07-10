using System.IO;

namespace GalleryCs;

// 03_double_release (fixed) — disposed exactly once -> silent.
public class DoubleReleaseOk
{
    public void Run()
    {
        var galleryDoubleReleaseOk = new MemoryStream();
        galleryDoubleReleaseOk.Dispose();
    }
}
