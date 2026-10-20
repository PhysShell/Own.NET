// P-014 reference-coverage instrument (research only). Same sources, parse and compilation options in every mode;
// only the reference list differs (00-preregistration.md §2).
//
// p014bind emit <asmName> <version> <src.cs> <out.dll> <refDir>
// p014bind measure --sources <list.txt> --refs-A <list> --refs-B <list> --refs-C <list> [--c-extra <file.cs>] --out <dir>
using System.Reflection;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

if (args[0] == "emit")
{
    var (name, ver, src, outDll, refDir) = (args[1], args[2], args[3], args[4], args[5]);
    var text = $"[assembly: System.Reflection.AssemblyVersion(\"{ver}\")]\n" + File.ReadAllText(src);
    var refs = Directory.EnumerateFiles(refDir, "*.dll").Select(p => (MetadataReference)MetadataReference.CreateFromFile(p));
    var c = CSharpCompilation.Create(name, [CSharpSyntaxTree.ParseText(text)], refs,
        new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, nullableContextOptions: NullableContextOptions.Enable));
    var r = c.Emit(outDll);
    if (!r.Success) { foreach (var d in r.Diagnostics.Where(d => d.Severity == DiagnosticSeverity.Error)) Console.Error.WriteLine(d); return 1; }
    return 0;
}

string? srcList = null, outDir = null, cExtra = null;
var refLists = new Dictionary<string, string>();
for (var i = 1; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--sources": srcList = args[++i]; break;
        case "--refs-A": refLists["A"] = args[++i]; break;
        case "--refs-B": refLists["B"] = args[++i]; break;
        case "--refs-C": refLists["C"] = args[++i]; break;
        case "--c-extra": cExtra = args[++i]; break;
        case "--out": outDir = args[++i]; break;
        default: throw new ArgumentException(args[i]);
    }
}
Directory.CreateDirectory(outDir!);
var files = File.ReadAllLines(srcList!).Where(l => l.Trim().Length > 0).ToList();
// identical parse: the extractor's ParseText(text, path) with default options
var trees = files.Select(f => CSharpSyntaxTree.ParseText(File.ReadAllText(f), path: f)).ToList();
var sites = new SortedDictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
var summary = new Dictionary<string, object>();
foreach (var (mode, listPath) in refLists.OrderBy(k => k.Key))
{
    var refPaths = File.ReadAllLines(listPath).Where(l => l.Trim().Length > 0).ToList();
    var refs = new List<MetadataReference>();
    var loadFail = 0;
    foreach (var p in refPaths)
        try { refs.Add(MetadataReference.CreateFromFile(p)); } catch { loadFail++; }
    var modeTrees = new List<SyntaxTree>(trees);
    if (mode == "C" && cExtra is not null) modeTrees.Add(CSharpSyntaxTree.ParseText(File.ReadAllText(cExtra), path: cExtra));
    var comp = CSharpCompilation.Create("own", modeTrees, refs, new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
    var errs = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error)
        .GroupBy(d => d.Id).ToDictionary(g => g.Key, g => g.Count());
    int inv = 0, invOk = 0, invAmb = 0, typ = 0, typOk = 0, ev = 0, evEvent = 0, evOther = 0;
    foreach (var t in trees)
    {
        var sm = comp.GetSemanticModel(t);
        var root = t.GetRoot();
        foreach (var n in root.DescendantNodes())
        {
            string? kind = null, status = null, detail = "";
            switch (n)
            {
                case InvocationExpressionSyntax ie:
                {
                    kind = "call"; inv++;
                    var si = sm.GetSymbolInfo(ie);
                    if (si.Symbol is { } s) { status = "resolved"; invOk++; detail = Describe(s); }
                    else if (si.CandidateSymbols.Length > 0) { status = $"ambiguous:{si.CandidateReason}"; invAmb++; detail = string.Join(" | ", si.CandidateSymbols.Take(3).Select(Describe)); }
                    else status = "unresolved";
                    break;
                }
                case AssignmentExpressionSyntax ae when ae.IsKind(SyntaxKind.AddAssignmentExpression) || ae.IsKind(SyntaxKind.SubtractAssignmentExpression):
                {
                    if (ae.Left is not (MemberAccessExpressionSyntax or IdentifierNameSyntax)) break;
                    kind = "plus_eq"; ev++;
                    var s = sm.GetSymbolInfo(ae.Left).Symbol;
                    if (s is IEventSymbol) { status = "event"; evEvent++; }
                    else if (s is not null) { status = $"other:{s.Kind}"; evOther++; }
                    else status = "unresolved";
                    detail = s is null ? "" : Describe(s);
                    break;
                }
                case TypeSyntax ts when IsTypePosition(ts) && !ts.IsVar:
                {
                    kind = "type"; typ++;
                    var tt = sm.GetTypeInfo(ts).Type ?? sm.GetSymbolInfo(ts).Symbol as ITypeSymbol;
                    if (tt is not null && tt.TypeKind != TypeKind.Error) { status = "resolved"; typOk++; detail = Describe(tt); }
                    else status = "unresolved";
                    break;
                }
            }
            if (kind is null) continue;
            var pos = n.GetLocation().GetLineSpan().StartLinePosition;
            var key = $"{t.FilePath}\t{pos.Line + 1}\t{pos.Character + 1}\t{kind}";
            if (!sites.TryGetValue(key, out var row))
                sites[key] = row = new Dictionary<string, string> { ["expr"] = Snip(n) };
            row[mode] = status!;
            row[mode + "_sym"] = detail;
        }
    }
    summary[mode] = new
    {
        references = refPaths.Count, load_failures = loadFail, errors = errs,
        calls = inv, calls_resolved = invOk, calls_ambiguous = invAmb,
        types = typ, types_resolved = typOk, plus_eq = ev, plus_eq_event = evEvent, plus_eq_other = evOther,
    };
}
File.WriteAllText(Path.Combine(outDir!, "summary.json"), JsonSerializer.Serialize(summary, new JsonSerializerOptions { WriteIndented = true }));
var modes = refLists.Keys.OrderBy(k => k).ToList();
using (var w = new StreamWriter(Path.Combine(outDir!, "sites.tsv")))
{
    w.WriteLine("file\tline\tcol\tkind\texpr\t" + string.Join('\t', modes.SelectMany(m => new[] { m, m + "_sym" })));
    foreach (var (k, row) in sites)
        w.WriteLine(k + "\t" + row["expr"] + "\t" + string.Join('\t', modes.SelectMany(m => new[] { row.GetValueOrDefault(m, "-"), row.GetValueOrDefault(m + "_sym", "") })));
}
Console.Error.WriteLine($"p014bind: {files.Count} files, {sites.Count} sites, modes {string.Join(",", modes)}");
return 0;

static bool IsTypePosition(TypeSyntax ts) => ts.Parent switch
{
    VariableDeclarationSyntax v => v.Type == ts,
    ObjectCreationExpressionSyntax o => o.Type == ts,
    SimpleBaseTypeSyntax => true,
    ParameterSyntax p => p.Type == ts,
    PropertyDeclarationSyntax pd => pd.Type == ts,
    MethodDeclarationSyntax md => md.ReturnType == ts,
    _ => false,
};

static string Describe(ISymbol s)
{
    var asm = s.ContainingAssembly is { } a ? $"{a.Identity.Name}/{a.Identity.Version}" : "?";
    var ct = s.ContainingType?.ToDisplayString() ?? s.ContainingNamespace?.ToDisplayString() ?? "";
    return $"{s.Kind}|{ct}|{s.ToDisplayString().Replace('\t', ' ')}|{asm}";
}

static string Snip(SyntaxNode n)
{
    var s = string.Join(' ', n.ToString().Split((char[])['\r', '\n', '\t'], StringSplitOptions.RemoveEmptyEntries).Select(x => x.Trim()));
    return s.Length > 100 ? s[..100] + "…" : s;
}
