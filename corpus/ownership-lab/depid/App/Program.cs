using System.Reflection;
using System.Runtime.Loader;
using Lib;
// The APP was compiled against Lib A (Make() returns a fresh owned Res each call) and disposes each result: correct
// under A. If the runtime substitutes a same-version patch (B) or a major bump (C) whose Make() returns a shared
// cached Res, the second Make() hands back an already-disposed object: the effective semantics differ.
static string Facets(Assembly a)
{
    var n = a.GetName();
    var info = a.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
    return $"name={n.Name} version={n.Version} pkt={Convert.ToHexString(n.GetPublicKeyToken() ?? Array.Empty<byte>()).ToLowerInvariant()} mvid={a.ManifestModule.ModuleVersionId} info={info} path={a.Location}";
}
var mode = args.Length > 0 ? args[0] : "direct";
if (mode == "direct")
{
    var a = Factory.Make(); a.Dispose();
    var b = Factory.Make();
    Console.WriteLine($"[direct] loaded: {Facets(typeof(Factory).Assembly)}");
    Console.WriteLine($"[direct] flavor={Factory.Flavor} second_make_already_disposed={b.Disposed} same_instance={ReferenceEquals(a, b)} live={Res.Live}");
    b.Dispose();
}
else
{
    // plugin-style load through a custom AssemblyLoadContext + AssemblyDependencyResolver rooted at a plugin dir
    var dir = Path.GetFullPath(args[1]);
    var alc = new PluginContext(Path.Combine(dir, "Lib.dll"));
    var asm = alc.LoadFromAssemblyName(new AssemblyName("Lib"));
    var factory = asm.GetType("Lib.Factory")!;
    var make = factory.GetMethod("Make")!;
    var r1 = (IDisposable)make.Invoke(null, null)!; r1.Dispose();
    var r2 = make.Invoke(null, null)!;
    var disposed = (bool)r2.GetType().GetProperty("Disposed")!.GetValue(r2)!;
    Console.WriteLine($"[plugin] loaded: {Facets(asm)}");
    Console.WriteLine($"[plugin] flavor={factory.GetProperty("Flavor")!.GetValue(null)} second_make_already_disposed={disposed} same_instance={ReferenceEquals(r1, r2)} default_alc_lib={Facets(typeof(Factory).Assembly)}");
}
sealed class PluginContext : AssemblyLoadContext
{
    readonly AssemblyDependencyResolver _resolver;
    public PluginContext(string mainAssembly) : base(isCollectible: true) => _resolver = new AssemblyDependencyResolver(mainAssembly);
    protected override Assembly? Load(AssemblyName name)
    {
        var p = _resolver.ResolveAssemblyToPath(name);
        return p is null ? null : LoadFromAssemblyPath(p);
    }
}
