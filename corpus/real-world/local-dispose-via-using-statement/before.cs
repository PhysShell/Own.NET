using System;

// A disposable acquired into a LOCAL and used, but (in the fix) released through the
// STATEMENT form `using (existingLocal) { ... }` rather than `using var` /
// `using (var x = ...)`. Mirrors protobuf-net's assorted/ Silverlight Page.xaml.cs,
// where a timer is created and then wrapped in `using (timer) { ... }`.
sealed class Res : IDisposable
{
    public void Work() { }
    public void Dispose() { }
}

static class Demo
{
    // BUG: the local is acquired and used but never disposed on any path — neither a
    // `using` nor a `.Dispose()`. A genuine OWN001 local leak.
    public static void Run()
    {
        var r = new Res();
        r.Work();
    }
}
