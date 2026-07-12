using System.IO;

namespace ConsumerDemo;

public class Tidy
{
    public void Run()
    {
        using var buffer = new MemoryStream();
        buffer.WriteByte(1);
    }
}
