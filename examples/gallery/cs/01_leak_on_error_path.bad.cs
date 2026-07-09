using System.IO;

namespace GalleryCs;

// 01_leak_on_error_path (bad) — C#-native mirror of
// examples/gallery/01_leak_on_error_path.own: OWN001, a leak on one path.
// Real C#: Dispose() runs in the happy branch but is forgotten on the early-out.
public class LeakOnErrorPath
{
    public void Handle(bool flag)
    {
        var galleryLeakOnError = new MemoryStream();
        if (flag)
        {
            galleryLeakOnError.Dispose(); // released here ...
        }
        // ...but on the else path it's never closed -> leak
    }
}
