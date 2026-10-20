// External-factory probes (not scored): acquire from an external method, opaque await, then dispose.
using System.Threading.Tasks;
using Stubs;

namespace Ablation;

public sealed class ExternalProbes
{
    private readonly IStep2 _step;
    private readonly IReaderFactory _factory;
    public ExternalProbes(IStep2 step, IReaderFactory factory) { _step = step; _factory = factory; }

    public async Task P10ExternalSync(string p)
    {
        var r = ExternalFactories.OpenSync(p); // ACQ:P10
        await _step.RunAsync();
        r.Dispose();
    }

    public async Task P11ExternalAsync(string p)
    {
        var r = await ExternalFactories.OpenAsync(p); // ACQ:P11
        await _step.RunAsync();
        r.Dispose();
    }

    public async Task P12ExternalStubType(string cs)
    {
        var c = ExternalFactories.CreateClient(cs); // ACQ:P12
        await _step.RunAsync();
        await c.DisposeAsync();
    }

    public async Task P13InterfaceMethod(string p)
    {
        var r = _factory.Open(p); // ACQ:P13
        await _step.RunAsync();
        r.Dispose();
    }
}
