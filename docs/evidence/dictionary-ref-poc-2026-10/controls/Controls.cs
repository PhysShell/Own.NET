using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace Controls;

public static class Positive
{
    // P1 Meziantou shape: the caller's dictionary, the caller's factory
    public static TValue GetOrAdd<TKey, TValue>(Dictionary<TKey, TValue> dict, TKey key, Func<TKey, TValue> factory)
        where TKey : notnull
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(dict, key, out var exists);
        if (exists) return v!;
        v = factory(key);                 // EXPECT: write after delegate
        return v;
    }

    // P3 direct mutation of the same dictionary, then a read
    public static int Direct(Dictionary<int, int> d)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrNullRef(d, 1);
        d.Add(2, 2);
        return v;                         // EXPECT: read after direct
    }

    // P4 indexer write on the same dictionary, then a write through the ref
    public static void IndexerWrite(Dictionary<int, int> d)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        d[2] = 2;
        v = 5;                            // EXPECT: write after direct
    }
}

public sealed class Bindable
{
    private readonly Dictionary<int, object?> _props = new();
    private readonly Func<Bindable, object>? _creator;
    public Bindable(Func<Bindable, object>? creator) => _creator = creator;

    // P2 MAUI shape: a first-party callee runs the user creator
    public object? GetOrCreate(int id)
    {
        ref var ctx = ref CollectionsMarshal.GetValueRefOrAddDefault(_props, id, out var exists);
        if (!exists)
            ctx = Create();               // EXPECT: write after callee -> delegate
        return ctx;
    }
    private object Create() => _creator?.Invoke(this) ?? new object();

    // N3b safe first-party factory on the same field dictionary
    public object? GetOrCreateSafe(int id)
    {
        ref var ctx = ref CollectionsMarshal.GetValueRefOrAddDefault(_props, id, out var exists);
        if (!exists)
            ctx = MakePure(id);           // silent
        return ctx;
    }
    private static object MakePure(int id) => id.ToString();
}

public static class Negative
{
    // N1 no mutation at all
    public static void NoMutation(Dictionary<string, int> d)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, "k", out _);
        v = Math.Max(v, 3);               // silent: BCL pure call, no mutation of d
    }

    // N2 mutation of a DIFFERENT dictionary
    public static int OtherDictionary(Dictionary<int, int> a, Dictionary<int, int> b)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrNullRef(a, 1);
        b.Add(3, 3);
        return v;                         // silent
    }

    // N3 safe factory (BCL / constructor)
    public static void SafeFactory(Dictionary<int, List<int>> d)
    {
        ref var list = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out var exists);
        if (!exists) list = new List<int>(4);
        list!.Add(1);                     // silent: the Add is on the list value, not on d
    }

    // N4 ref used only BEFORE the potential mutation
    public static void UsedBefore(Dictionary<int, int> d, Func<int> f)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        v++;
        d.Add(9, f());                    // silent: v not used afterwards
    }

    // N5 delegate invoked, but the dictionary is a local nothing else can see
    public static int LocalDictionary(Func<int> f)
    {
        var d = new Dictionary<int, int>();
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        v = f();                          // silent: f cannot reach d
        return v;
    }

    // N6 event and use on exclusive branches
    public static int Exclusive(Dictionary<int, int> d, bool c, Func<int> f)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        if (c) { d.Add(2, f()); return 0; }
        else { return v; }                // silent
    }

    // N7 fresh ref after the mutation
    public static int Refreshed(Dictionary<int, int> d)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        d.Add(2, 2);
        v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out _);
        return v;                         // silent
    }

    // N8 the mutation is followed by return / throw in its own block (round-1 FP shape)
    public static int LeavesAfterMutation(Dictionary<int, int> d, bool bad)
    {
        ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(d, 1, out var exists);
        if (!exists)
        {
            if (bad) { d.Remove(1); return -1; }
            try { v = 1; } catch (Exception) { d.Remove(1); throw; }
        }
        return v;                         // silent
    }

    // N9 a method-local dictionary that escapes only after the delegate ran (round-1 FP shape)
    public static Dictionary<int, int> LocalEscapesLater(IEnumerable<int> xs, Func<int, int, int> f)
    {
        var dict = new Dictionary<int, int>();
        foreach (var x in xs)
        {
            ref var acc = ref CollectionsMarshal.GetValueRefOrAddDefault(dict, x % 3, out _);
            acc = f(acc, x);              // silent: f cannot see dict yet
        }
        return dict;
    }
}
