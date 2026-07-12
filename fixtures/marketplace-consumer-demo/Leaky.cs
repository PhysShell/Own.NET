using System.IO;

namespace ConsumerDemo;

public class Leaky
{
    public void Run()
    {
        var buffer = new MemoryStream();
        buffer.WriteByte(1);
        // no Dispose()/using -> OWN001
    }
}
