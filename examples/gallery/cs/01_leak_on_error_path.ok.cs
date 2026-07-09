using System.IO;

namespace GalleryCs;

// 01_leak_on_error_path (fixed) — disposed on every path -> silent.
public class LeakOnErrorPathOk
{
    public void Handle(bool flag)
    {
        var galleryLeakOnErrorOk = new MemoryStream();
        if (flag)
        {
            galleryLeakOnErrorOk.WriteByte(1);
        }
        galleryLeakOnErrorOk.Dispose();
    }
}
