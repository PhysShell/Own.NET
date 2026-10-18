using System.Runtime.InteropServices;
using BuggyNs;

static class P
{
    static void Main()
    {
        // Meziantou 7addb26c GetOrAdd(dict, key, factory): reentrant factory
        var d = new Dictionary<int, string>();
        var r = d.GetOrAdd(0, _ => { for (var i = 1; i <= 64; i++) d[i] = "filler"; return "computed"; });
        Console.WriteLine($"meziantou reentrant: returned={r} stored={d[0] ?? "<null>"}  (bug: {d[0] != "computed"})");
        // Meziantou: throwing factory poisons the entry
        var e = new Dictionary<string, string>();
        try { e.GetOrAdd("k", _ => throw new InvalidOperationException()); } catch (InvalidOperationException) { }
        Console.WriteLine($"meziantou throwing: ContainsKey={e.ContainsKey("k")} value={(e.TryGetValue("k", out var v) ? v ?? "<null>" : "-")}");
        // control: non-reentrant factory
        var c = new Dictionary<int, string>();
        c.GetOrAdd(0, _ => "ok");
        Console.WriteLine($"control non-reentrant: stored={c[0]} (ok: {c[0] == "ok"})");

        // MAUI 7b051d1b GetOrCreateContext shape: ref held across a creator that mutates the same dictionary
        var props = new Dictionary<int, object>();
        object Create() { for (var i = 1; i <= 15; i++) props[i] = i; return "context"; }
        ref var ctx = ref CollectionsMarshal.GetValueRefOrAddDefault(props, 0, out var exists);
        if (!exists) ctx = Create();
        Console.WriteLine($"maui shape: stored={props[0] ?? "<null>"} (bug: {props[0] is null})");
    }
}
