using System.IO;

namespace GalleryCs;

// 00_ok_clean — C#-native mirror of examples/gallery/00_ok_clean.own:
// acquire, use, release on every path. No finding expected.
public class OkClean
{
    public void Process()
    {
        var galleryClean = new MemoryStream();
        galleryClean.WriteByte(1);
        galleryClean.Dispose();
    }
}
