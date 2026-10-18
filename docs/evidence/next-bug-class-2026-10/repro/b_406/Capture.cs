using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Repro;

public static class Capture
{
    public static void LeakSyncLambda()
    {
        var stream = new MemoryStream();
        Action use = () => stream.WriteByte(1);
        use();
    }

    public static void LeakNoLambda()
    {
        var plain = new MemoryStream();
        plain.WriteByte(1);
    }

    public static void LeakLocalFunction()
    {
        var lf = new MemoryStream();
        void Use() => lf.WriteByte(1);
        Use();
    }

    public static Task ForEachAsync<T>(IEnumerable<T> items, Func<T, Task> body, int max)
    {
        SemaphoreSlim throttler = new SemaphoreSlim(max, max);
        IEnumerable<Task> tasks = items.Select(async input =>
        {
            await throttler.WaitAsync();
            try { await body(input); } finally { throttler.Release(); }
        });
        return Task.WhenAll(tasks);
    }
}
