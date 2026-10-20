// Explanatory probes for the MISSED verdicts (not scored). Same leak each time: acquire, a call that
// can throw, then hand over or dispose. Only the acquisition form or the enclosing construct changes.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;

namespace Probes;

public sealed class Probes
{
    private readonly Dictionary<string, StreamReader> _store = new();

    private static StreamReader Open(string p) => new StreamReader(p);
    private static Task<StreamReader> OpenAsync(string p) => Task.FromResult(new StreamReader(p));
    // the throwing step is opaque (an interface call), as in the reproductions; an empty local
    // method would let CA2000's interprocedural analysis prove it cannot throw
    private readonly IStep _step;
    public Probes(IStep step) { _step = step; }
    private Task MayThrowAsync() => _step.RunAsync();
    private void MayThrow() => _step.Run();

    // P1 `new`, sync throw, dispose after: the harness control shape
    public void P1New(string p) { var r = new StreamReader(p); MayThrow(); r.Dispose(); } // ACQ:P1

    // P2 synchronous factory method instead of `new`
    public void P2Factory(string p) { var r = Open(p); MayThrow(); r.Dispose(); } // ACQ:P2

    // P3 BCL factory (File.OpenText)
    public void P3BclFactory(string p) { var r = File.OpenText(p); MayThrow(); r.Dispose(); } // ACQ:P3

    // P4 awaited async factory
    public async Task P4AsyncFactory(string p) { var r = await OpenAsync(p); await MayThrowAsync(); r.Dispose(); } // ACQ:P4

    // P5 `new`, awaited throw, then stored into a dictionary field (R/B hand-over, with `new`)
    public async Task P5NewThenStore(string p) { var r = new StreamReader(p); await MayThrowAsync(); _store["k"] = r; } // ACQ:P5

    // P6 `new`, awaited throw, then wrapped and returned (X hand-over, with `new`)
    public async Task<Wrapper> P6NewThenWrap(string p) { var r = new StreamReader(p); await MayThrowAsync(); return new Wrapper(r); } // ACQ:P6

    // P7 `new` inside an async iterator, awaited throw, then dispose (B construct, with `new`)
    public async IAsyncEnumerable<int> P7Iterator(string p, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var r = new StreamReader(p); // ACQ:P7
        await MayThrowAsync();
        r.Dispose();
        yield return 1;
    }

    // P8 `new`, awaited throw, return (W hand-over without the loop)
    public async Task<StreamReader> P8NewThenReturn(string p) { var r = new StreamReader(p); await MayThrowAsync(); return r; } // ACQ:P8
}

public interface IStep { void Run(); Task RunAsync(); }

public sealed class Wrapper : IDisposable
{
    private readonly StreamReader _r;
    public Wrapper(StreamReader r) { _r = r; }
    public void Dispose() => _r.Dispose();
}
