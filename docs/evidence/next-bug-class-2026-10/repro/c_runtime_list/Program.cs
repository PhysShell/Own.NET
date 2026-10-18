using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

static class P
{
    static void Main()
    {
        // BAD: view, structural mutation with forced reallocation, use of the old view
        var list = new List<int>(capacity: 1) { 10 };
        Span<int> view = CollectionsMarshal.AsSpan(list);
        list.Add(20);                         // capacity 1 -> reallocation
        view[0] = 99;
        Console.WriteLine($"bad: list[0]={list[0]} (stale write lost: {list[0] != 99})");

        // BAD without reallocation: contract violation, no observable effect
        var list2 = new List<int>(capacity: 8) { 10 };
        Span<int> v2 = CollectionsMarshal.AsSpan(list2);
        list2.Add(20);
        v2[0] = 99;
        Console.WriteLine($"bad-spare-capacity: list2[0]={list2[0]} (observable: {list2[0] != 99}), v2.Length={v2.Length} list2.Count={list2.Count}");

        // BAD RemoveAt: view still reads shifted storage
        var list3 = new List<int> { 1, 2, 3 };
        Span<int> v3 = CollectionsMarshal.AsSpan(list3);
        list3.RemoveAt(0);
        Console.WriteLine($"bad-removeat: v3=[{string.Join(",", v3.ToArray())}] list3=[{string.Join(",", list3)}]");

        // OK: no mutation
        var ok1 = new List<int>(1) { 10 };
        Span<int> o1 = CollectionsMarshal.AsSpan(ok1); o1[0] = 99;
        Console.WriteLine($"ok-no-mutation: {ok1[0] == 99}");
        // OK: mutation of a different list
        var a = new List<int>(1) { 10 }; var b = new List<int>(1) { 1 };
        Span<int> va = CollectionsMarshal.AsSpan(a); b.Add(2); va[0] = 99;
        Console.WriteLine($"ok-other-list: {a[0] == 99}");
        // OK: no use after mutation
        var ok3 = new List<int>(1) { 10 };
        Span<int> o3 = CollectionsMarshal.AsSpan(ok3); o3[0] = 5; ok3.Add(20);
        Console.WriteLine($"ok-no-use-after: {ok3[0] == 5}");
        // OK: refreshed view after mutation
        var ok4 = new List<int>(1) { 10 };
        Span<int> o4 = CollectionsMarshal.AsSpan(ok4); ok4.Add(20); o4 = CollectionsMarshal.AsSpan(ok4); o4[0] = 99;
        Console.WriteLine($"ok-refreshed: {ok4[0] == 99}");
    }
}
