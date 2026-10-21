// P-014 Tiny PoC instrument (research only). Modes:
//   project <root.csproj> --mode exact|legacy [--tfm T] [--root DIR] [--sidecar F] [--iters N] [--timing F]
//   lost <root.csproj> [--tfm T] [--root DIR] --out F        sites resolved in legacy-merged but not in exact-project
//   controls --out F                                          in-memory controls K1 K2 K4 K5 K6 K7 K11 K12, F2.3-F2.5, guard
// Facts and verdicts are never produced: this program reads sources, assets, packs and the package cache only.
using System.Diagnostics;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

var env = new Env();
string? Opt(string n) { var i = Array.IndexOf(args, n); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }
if (Opt("--dotnet-root") is { } dr) env.DotnetRoot = dr;
var jsonOpts = new JsonSerializerOptions { WriteIndented = true };
var rootDir = Path.GetFullPath(Opt("--root") ?? Directory.GetCurrentDirectory());
string Rel(string p)
{
    var f = Path.GetFullPath(p);
    if (f.StartsWith(env.NugetRoot, StringComparison.OrdinalIgnoreCase)) return "<nuget>" + f[env.NugetRoot.Length..].Replace('\\', '/');
    if (f.StartsWith(env.DotnetRoot, StringComparison.OrdinalIgnoreCase)) return "<dotnet>" + f[env.DotnetRoot.Length..].Replace('\\', '/');
    return Path.GetRelativePath(rootDir, f).Replace('\\', '/');
}

switch (args.FirstOrDefault())
{
    case "project": return RunProject();
    case "lost": return RunLost();
    case "controls": return Controls.Run(env, Opt("--out")!, jsonOpts);
    default: Console.Error.WriteLine("usage: p014poc project|lost|controls ..."); return 2;
}

Unit LoadGraph(string csproj, string? tfm) => Assets.Load(csproj, tfm, null, env, new Dictionary<string, Unit>());

// legacy-merged: today's extractor shape — one compilation over every unit's sources, process TPA first-name-wins
(CSharpCompilation comp, List<SyntaxTree> trees) Legacy(Unit root)
{
    var files = Assets.Closure(root).SelectMany(u => u.SourceFiles).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(f => f, StringComparer.Ordinal).ToList();
    var trees = new List<SyntaxTree>();
    foreach (var f in files) { try { trees.Add(CSharpSyntaxTree.ParseText(File.ReadAllText(f), path: f)); } catch (IOException) { } }
    var tpa = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "").Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
        .Where(p => p.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)).ToList();
    var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    var refs = new List<MetadataReference>();
    foreach (var p in tpa) if (names.Add(Path.GetFileName(p))) refs.Add(env.Meta(p));
    return (CSharpCompilation.Create("own", trees, refs, new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)), trees);
}

object UnitRecord(Unit u, UnitCoverage? c) => new SortedDictionary<string, object?>(StringComparer.Ordinal)
{
    ["project"] = Rel(u.ProjectPath),
    ["assembly_name"] = u.Name,
    ["tfm"] = u.Tfm,
    ["framework_moniker"] = u.FrameworkMoniker,
    ["tfm_status"] = u.TfmStatus,
    ["unit_status"] = u.UnitStatus,
    ["reference_status"] = u.ReferenceStatus,
    ["source_set_status"] = u.SourceSetStatus,
    ["reasons"] = new SortedDictionary<string, object>(StringComparer.Ordinal)
    {
        ["reference"] = u.RefReasons.ToList(), ["source_set"] = u.SrcReasons.ToList(), ["unsupported"] = u.Unsupported.ToList(),
    },
    ["project_references"] = u.Children.Select(ch => Rel(ch.ProjectPath)).OrderBy(x => x, StringComparer.Ordinal).ToList(),
    ["manifest"] = u.Manifest.OrderBy(m => m.FileName, StringComparer.OrdinalIgnoreCase).Select(m => new SortedDictionary<string, string?>(StringComparer.Ordinal)
    {
        ["kind"] = m.IsFramework ? "pack" : "package", ["id"] = m.PackageId, ["version"] = m.PackageVersion,
        ["file"] = m.FileName, ["path"] = Rel(m.Path), ["assembly_version"] = m.AV?.ToString(), ["file_version"] = m.FV?.ToString(),
    }).ToList(),
    ["conflicts"] = u.Conflicts.Select(d => new SortedDictionary<string, string>(d, StringComparer.Ordinal)).ToList(),
    ["tie_framework_assumed"] = u.TieAssumed,
    ["files"] = new SortedDictionary<string, int>(StringComparer.Ordinal)
    {
        ["in_source_set"] = u.SourceFiles.Count, ["parsed"] = u.Trees.Count, ["unreadable"] = u.Unreadable, ["generated_excluded"] = u.GeneratedExcluded,
    },
    ["sites"] = c?.Sites,
    ["compiler_errors"] = c?.Errors,
    ["methods"] = c is null ? null : new SortedDictionary<string, int>(StringComparer.Ordinal)
    {
        ["total"] = c.MethodsTotal, ["with_relevant_sites"] = c.MethodsWithRelevant, ["all_relevant_sites_resolved"] = c.MethodsAllRelevantResolved,
    },
    ["foreign_binding"] = c?.Foreign.Count,
    ["foreign_binding_sites"] = c?.Foreign.OrderBy(x => x, StringComparer.Ordinal).ToList(),
    ["invariants_failed"] = c is null ? null : Coverage.Invariants(c),
};

int RunProject()
{
    var csproj = args[1];
    var mode = Opt("--mode") ?? "exact";
    var iters = int.Parse(Opt("--iters") ?? "1");
    var timing = new List<object>();
    object? sidecar = null;
    for (int it = 0; it < iters; it++)
    {
        var sw = Stopwatch.StartNew();
        var root = LoadGraph(csproj, Opt("--tfm"));
        var units = Assets.Closure(root).OrderBy(u => u.ProjectPath, StringComparer.Ordinal).ToList();
        if (mode == "exact")
        {
            Assets.Compile(root, env, new HashSet<Unit>());
            var recs = new List<object>();
            foreach (var u in units)
            {
                UnitCoverage? c = u.Comp is null ? null : Coverage.Measure(u.Comp, u.Trees, Coverage.Allowed(u.Comp), Rel);
                recs.Add(UnitRecord(u, c));
            }
            sidecar = new SortedDictionary<string, object>(StringComparer.Ordinal) { ["binding_coverage_version"] = 1, ["mode"] = "exact-project", ["units"] = recs };
        }
        else
        {
            var (comp, trees) = Legacy(root);
            var c = Coverage.Measure(comp, trees, null, Rel);
            sidecar = new SortedDictionary<string, object?>(StringComparer.Ordinal)
            {
                ["binding_coverage_version"] = 1, ["mode"] = "legacy-merged",
                ["units"] = new List<object> { new SortedDictionary<string, object?>(StringComparer.Ordinal)
                {
                    ["project"] = Rel(root.ProjectPath), ["merged_projects"] = units.Select(u => Rel(u.ProjectPath)).ToList(),
                    ["files"] = trees.Count, ["sites"] = c.Sites, ["compiler_errors"] = c.Errors,
                    ["unit_status"] = "APPROXIMATE", ["invariants_failed"] = Coverage.Invariants(c),
                } },
            };
        }
        sw.Stop();
        var proc = Process.GetCurrentProcess(); proc.Refresh();
        timing.Add(new { iteration = it, kind = it == 0 ? "cold" : "warm", wall_ms = sw.ElapsedMilliseconds, peak_working_set_mb = proc.PeakWorkingSet64 / (1024.0 * 1024.0) });
    }
    var json = JsonSerializer.Serialize(sidecar, jsonOpts);
    if (Opt("--sidecar") is { } sp) File.WriteAllText(sp, json); else Console.WriteLine(json);
    if (Opt("--timing") is { } tp) File.WriteAllText(tp, JsonSerializer.Serialize(new { mode, project = Rel(csproj), timing }, jsonOpts));
    return 0;
}

int RunLost()
{
    var csproj = args[1];
    var root = LoadGraph(csproj, Opt("--tfm"));
    Assets.Compile(root, env, new HashSet<Unit>());
    var exact = new Dictionary<string, Site>();
    foreach (var u in Assets.Closure(root))
        if (u.Comp is not null)
            foreach (var s in Coverage.Measure(u.Comp, u.Trees, null, Rel).AllSites) exact[$"{s.File}|{s.Start}|{s.Length}|{s.Kind}"] = s;
    var (lc, lt) = Legacy(LoadGraph(csproj, Opt("--tfm")));
    var legacy = Coverage.Measure(lc, lt, null, Rel).AllSites;
    var lost = new List<object>(); int gained = 0, both = 0;
    foreach (var s in legacy.Where(s => s.Kind is "invocation" or "type"))
    {
        var k = $"{s.File}|{s.Start}|{s.Length}|{s.Kind}";
        var e = exact.GetValueOrDefault(k);
        if (s.Status == "resolved" && (e is null || e.Status != "resolved"))
            lost.Add(new { s.File, s.Line, s.Kind, legacy = $"{s.Symbol} @ {s.Assembly}", exact = e is null ? "NOT_IN_EXACT_SOURCE_SET" : $"{e.Status} {e.Symbol} @ {e.Assembly}" });
        else if (s.Status == "resolved") both++;
    }
    foreach (var e in exact.Values.Where(e => e.Status == "resolved" && e.Kind is "invocation" or "type"))
        if (!legacy.Any(s => s.File == e.File && s.Start == e.Start && s.Length == e.Length && s.Kind == e.Kind && s.Status == "resolved")) gained++;
    File.WriteAllText(Opt("--out")!, JsonSerializer.Serialize(new { project = Rel(csproj), resolved_in_both = both, gained_in_exact = gained, lost_count = lost.Count, lost }, jsonOpts));
    Console.WriteLine($"lost={lost.Count} gained={gained} both={both}");
    return 0;
}
