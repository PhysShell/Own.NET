using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

// usage: ownsharp-apilist <target.dll> [<extra reference dir> ...]
if (args.Length == 0) { Console.Error.WriteLine("usage: ownsharp-apilist <target.dll> [refdir...]"); return 2; }
var target = Path.GetFullPath(args[0]);
var refs = new List<MetadataReference>();
var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
void Add(string path)
{
    var name = Path.GetFileNameWithoutExtension(path);
    if (!seen.Add(name)) return;
    try { refs.Add(MetadataReference.CreateFromFile(path)); } catch { seen.Remove(name); }
}
Add(target);
foreach (var d in args.Skip(1))
    foreach (var f in Directory.EnumerateFiles(d, "*.dll", SearchOption.AllDirectories).OrderBy(x => x, StringComparer.Ordinal))
        Add(f);
foreach (var f in Directory.EnumerateFiles(Path.GetDirectoryName(target)!, "*.dll")) Add(f);
var tpa = (AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string ?? "").Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries);
foreach (var f in tpa) Add(f);
var comp = CSharpCompilation.Create("apilist", references: refs);
var targetName = Path.GetFileNameWithoutExtension(target);
var asm = comp.SourceModule.ReferencedAssemblySymbols.FirstOrDefault(a => string.Equals(a.Name, targetName, StringComparison.OrdinalIgnoreCase));
if (asm is null) { Console.Error.WriteLine("target assembly symbol not found: " + targetName); return 3; }
var idisp = comp.GetTypeByMetadataName("System.IDisposable");
var iadisp = comp.GetTypeByMetadataName("System.IAsyncDisposable");
bool Disp(ITypeSymbol? t) => t is INamedTypeSymbol n && idisp is not null && (SymbolEqualityComparer.Default.Equals(n, idisp) || n.AllInterfaces.Any(i => SymbolEqualityComparer.Default.Equals(i, idisp)));
bool ADisp(ITypeSymbol? t) => t is INamedTypeSymbol n && iadisp is not null && (SymbolEqualityComparer.Default.Equals(n, iadisp) || n.AllInterfaces.Any(i => SymbolEqualityComparer.Default.Equals(i, iadisp)));
var releaseName = new Regex("^(Close|Delete|Release|Shutdown|Disconnect|Return|Free|Destroy|Unload|Stop|Abort|Complete|Dispose|Logout|Quit|Terminate|Detach|Unregister|Deallocate|Clear)", RegexOptions.CultureInvariant);
var types = new List<object>(); var factories = new List<object>(); var releases = new List<object>(); var adopters = new List<object>();
IEnumerable<INamedTypeSymbol> AllTypes(INamespaceSymbol ns)
{
    foreach (var m in ns.GetMembers())
        if (m is INamespaceSymbol sub) { foreach (var t in AllTypes(sub)) yield return t; }
        else if (m is INamedTypeSymbol t) { yield return t; foreach (var nt in Nested(t)) yield return nt; }
    static IEnumerable<INamedTypeSymbol> Nested(INamedTypeSymbol t) { foreach (var n in t.GetTypeMembers()) { yield return n; foreach (var nn in Nested(n)) yield return nn; } }
}
string Disp1(ITypeSymbol t) => t.ToDisplayString();
// Task / ValueTask are IDisposable themselves and would make every async method a factory: unwrap Task<T> /
// ValueTask<T> to T (an async factory), and drop bare Task / ValueTask; enumerators are dropped by name.
ITypeSymbol? Unwrap(ITypeSymbol t)
{
    if (t is INamedTypeSymbol n && n.ContainingNamespace?.ToDisplayString() == "System.Threading.Tasks" && n.Name is "Task" or "ValueTask")
        return n.IsGenericType ? n.TypeArguments[0] : null;
    return t;
}
foreach (var t in AllTypes(asm.GlobalNamespace).Where(t => t.DeclaredAccessibility == Accessibility.Public))
{
    var d = Disp(t); var ad = ADisp(t);
    if (d || ad)
        types.Add(new { type = Disp1(t), kind = t.TypeKind.ToString().ToLowerInvariant(), disposable = d, async_disposable = ad, is_abstract = t.IsAbstract });
    foreach (var m in t.GetMembers().Where(m => m.DeclaredAccessibility == Accessibility.Public))
    {
        if (m is IMethodSymbol me && me.MethodKind is MethodKind.Ordinary && !me.ReturnsVoid && me.Name is not ("GetEnumerator" or "GetAsyncEnumerator")
            && Unwrap(me.ReturnType) is { } rt && (Disp(rt) || ADisp(rt)))
            factories.Add(new { callable = $"{Disp1(t)}.{me.Name}", arity = me.Parameters.Length, is_static = me.IsStatic, returns = Disp1(rt), async_wrapped = !SymbolEqualityComparer.Default.Equals(rt, me.ReturnType), declaring_type_disposable = d, parameters = me.Parameters.Select(p => Disp1(p.Type)).ToArray() });
        else if (m is IPropertySymbol pr && (Disp(pr.Type) || ADisp(pr.Type)) && pr.GetMethod is not null)
            factories.Add(new { callable = $"{Disp1(t)}.get_{pr.Name}", arity = 0, is_static = pr.IsStatic, returns = Disp1(pr.Type), declaring_type_disposable = d, parameters = Array.Empty<string>(), property = true });
        if (m is IMethodSymbol mc && mc.MethodKind is MethodKind.Constructor && mc.Parameters.Any(p => Disp(p.Type) || ADisp(p.Type)) && (d || ad))
            adopters.Add(new { callable = $"{Disp1(t)}..ctor", arity = mc.Parameters.Length, parameters = mc.Parameters.Select(p => Disp1(p.Type)).ToArray(), disposable_params = mc.Parameters.Where(p => Disp(p.Type) || ADisp(p.Type)).Select(p => p.Ordinal).ToArray(), bool_params = mc.Parameters.Where(p => p.Type.SpecialType == SpecialType.System_Boolean).Select(p => p.Name).ToArray() });
        if ((d || ad) && m is IMethodSymbol mr && mr.MethodKind is MethodKind.Ordinary && !mr.IsStatic && releaseName.IsMatch(mr.Name) && mr.Name is not ("Dispose" or "DisposeAsync"))
            releases.Add(new { callable = $"{Disp1(t)}.{mr.Name}", arity = mr.Parameters.Length, returns = Disp1(mr.ReturnType) });
    }
}
var mvid = asm.Modules.First().GetMetadata()?.GetModuleVersionId().ToString() ?? "";
Console.WriteLine(JsonSerializer.Serialize(new { assembly = asm.Name, version = asm.Identity.Version.ToString(), mvid, disposable_types = types.Count, types, factories, adopting_ctors = adopters, release_name_candidates = releases }, new JsonSerializerOptions { WriteIndented = true }));
return 0;
