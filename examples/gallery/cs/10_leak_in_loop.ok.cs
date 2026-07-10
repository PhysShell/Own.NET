using System.IO;

namespace GalleryCs;

// 10_leak_in_loop (fixed) — disposed within the same iteration it was
// acquired in -> balanced on every pass -> silent.
public class LeakInLoopOk
{
    public void Drain(int n)
    {
        while (n > 0)
        {
            var galleryLoopLeakOk = new MemoryStream();
            galleryLoopLeakOk.WriteByte(1);
            galleryLoopLeakOk.Dispose();
            n = n - 1;
        }
    }
}
