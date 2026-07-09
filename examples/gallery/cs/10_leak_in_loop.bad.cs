using System.IO;

namespace GalleryCs;

// 10_leak_in_loop (bad) — C#-native mirror of examples/gallery/10_leak_in_loop.own:
// OWN001, a resource acquired every iteration but never released — leaks each pass.
public class LeakInLoop
{
    public void Drain(int n)
    {
        while (n > 0)
        {
            var galleryLoopLeak = new MemoryStream(); // opened every iteration ...
            galleryLoopLeak.WriteByte(1);
            n = n - 1;
        } // ...never closed -> leak
    }
}
