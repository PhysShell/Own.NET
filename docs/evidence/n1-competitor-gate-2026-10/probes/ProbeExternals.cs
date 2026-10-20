// Compiled into the stub assembly for the ablation run only (external to the analysed compilation).
using System.IO;
using System.Threading.Tasks;

namespace Stubs;

public static class ExternalFactories
{
    public static StreamReader OpenSync(string p) => new StreamReader(p);
    public static Task<StreamReader> OpenAsync(string p) => Task.FromResult(new StreamReader(p));
    public static ServiceBusClient CreateClient(string cs) => new ServiceBusClient(cs);
}

public interface IReaderFactory { StreamReader Open(string p); }
