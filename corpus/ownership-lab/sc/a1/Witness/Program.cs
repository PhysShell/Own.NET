using System.Text.Json;
using CallerLib; using HelperLib;
var probes = new (string name, Func<object> make)[] { ("MakeDirect", () => Caller.MakeDirect()), ("MakeOneHop", () => Caller.MakeOneHop()), ("MakeTwoHop", () => Caller.MakeTwoHop()), ("MakeVirtual", () => Caller.MakeVirtual()), ("MakeViaProperty", () => Caller.MakeViaProperty()), ("MakeGeneric", () => Caller.MakeGeneric()) };
var results = new List<object>();
foreach (var (name, make) in probes)
{
    object w1 = make(), w2 = make(), w3 = make();
    bool distinct = !ReferenceEquals(w1, w2) && !ReferenceEquals(w2, w3) && !ReferenceEquals(w1, w3);
    bool same = ReferenceEquals(w1, w2) && ReferenceEquals(w2, w3);
    results.Add(new { callable = "CallerLib.Caller." + name, verdict = same ? "cached" : distinct ? "fresh" : "inconclusive", helper_mvid = typeof(Helper).Assembly.ManifestModule.ModuleVersionId.ToString(), caller_mvid = typeof(Caller).Assembly.ManifestModule.ModuleVersionId.ToString() });
}
Console.WriteLine("WITNESS " + JsonSerializer.Serialize(results));
