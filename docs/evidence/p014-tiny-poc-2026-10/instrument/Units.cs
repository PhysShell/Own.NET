// P-014 Tiny PoC — units: one SDK-style project at one target, its reference manifest from the existing
// obj/project.assets.json + local targeting packs + the global packages folder, and its source set (the extractor's
// text rules). No restore, no build, no MSBuild evaluation. Contract sources (dotnet/sdk): ResolveTargetingPackAssets,
// ResolvePackageFileConflicts, ConflictResolver, PackageOverrideResolver — see the pre-registration §1.
using System.Diagnostics;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

sealed record RefItem(string FileName, string Path, Version? AV, Version? FV, string PackageId, string PackageVersion, bool IsFramework);

sealed class Unit
{
    public string Name = "";
    public string ProjectPath = "";       // absolute
    public string? Tfm;
    public string? FrameworkMoniker;
    public string TfmStatus = "NOT_APPLICABLE";
    public readonly SortedSet<string> RefReasons = new(StringComparer.Ordinal);    // reference axis
    public readonly SortedSet<string> SrcReasons = new(StringComparer.Ordinal);    // source-set axis
    public readonly SortedSet<string> Unsupported = new(StringComparer.Ordinal);
    public readonly List<RefItem> Manifest = new();
    public readonly List<Dictionary<string, string>> Conflicts = new();
    public readonly List<string> SourceFiles = new();
    public int GeneratedExcluded;
    public readonly List<Unit> Children = new();
    public bool TieAssumed;
    public CSharpCompilation? Comp;
    public List<SyntaxTree> Trees = new();
    public int Unreadable;

    public string ReferenceStatus => Unsupported.Count > 0 ? "UNSUPPORTED"
        : RefReasons.Any(r => r.StartsWith("conflict-unresolved", StringComparison.Ordinal)) ? "CONFLICT_UNRESOLVED"
        : RefReasons.Count > 0 ? "REFERENCE_MISSING" : "COMPLETE";
    public string SourceSetStatus => SrcReasons.Count > 0 ? "SOURCE_SET_INCOMPLETE" : "COMPLETE_BY_TEXT";
    public string UnitStatus => Unsupported.Count > 0 ? "UNSUPPORTED"
        : ReferenceStatus != "COMPLETE" ? "REFERENCE_MISSING"
        : SrcReasons.Count > 0 ? "SOURCE_SET_INCOMPLETE" : "COMPLETE";
}

sealed class Env
{
    public string DotnetRoot = @"C:\Program Files\dotnet";
    public string NugetRoot = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".nuget", "packages");
    public readonly Dictionary<string, MetadataReference> MetaCache = new(StringComparer.OrdinalIgnoreCase);
    public MetadataReference Meta(string path)
    {
        if (!MetaCache.TryGetValue(path, out var r)) MetaCache[path] = r = MetadataReference.CreateFromFile(path);
        return r;
    }
}

static class Assets
{
    static readonly CSharpCompilationOptions Opts = new(OutputKind.DynamicallyLinkedLibrary);

    // ---------- version helpers ----------
    public static Version? V(string? s)
    {
        if (string.IsNullOrWhiteSpace(s)) return null;
        var core = s.Split('-', '+', ' ')[0];
        var parts = core.Split('.').Select(p => int.TryParse(p, out var n) ? n : 0).ToList();
        while (parts.Count < 4) parts.Add(0);
        return new Version(parts[0], parts[1], parts[2], parts[3]);
    }

    public static (Version? av, Version? fv) DllVersions(string path)
    {
        Version? av = null, fv = null;
        try
        {
            using var fs = File.OpenRead(path);
            using var pe = new PEReader(fs);
            var md = pe.GetMetadataReader();
            if (md.IsAssembly) av = md.GetAssemblyDefinition().Version;
        }
        catch { }
        try
        {
            var fvi = FileVersionInfo.GetVersionInfo(path);
            if (fvi.FileVersion is not null)
                fv = new Version(fvi.FileMajorPart, fvi.FileMinorPart, fvi.FileBuildPart, fvi.FilePrivatePart);
        }
        catch { }
        return (av, fv);
    }

    // "net10.0-windows10.0.22000.0" -> ".NETCoreApp,Version=v10.0"; netstandard/netcoreapp/net4x handled; else null
    public static string? Moniker(string tfm)
    {
        var m = Regex.Match(tfm, @"^net(\d+)\.(\d+)");
        if (m.Success && int.Parse(m.Groups[1].Value) >= 5) return $".NETCoreApp,Version=v{m.Groups[1].Value}.{m.Groups[2].Value}";
        m = Regex.Match(tfm, @"^netcoreapp(\d+\.\d+)$"); if (m.Success) return $".NETCoreApp,Version=v{m.Groups[1].Value}";
        m = Regex.Match(tfm, @"^netstandard(\d+\.\d+)$"); if (m.Success) return $".NETStandard,Version=v{m.Groups[1].Value}";
        m = Regex.Match(tfm, @"^net(\d)(\d)(\d?)$");
        if (m.Success) return $".NETFramework,Version=v{m.Groups[1].Value}.{m.Groups[2].Value}" + (m.Groups[3].Value.Length > 0 ? "." + m.Groups[3].Value : "");
        return null;
    }

    static string? MajorMinor(string tfm)
    {
        var m = Regex.Match(tfm, @"^net(\d+\.\d+)"); if (m.Success && !tfm.StartsWith("netstandard") && !tfm.StartsWith("netcoreapp")) return m.Groups[1].Value;
        m = Regex.Match(tfm, @"^netcoreapp(\d+\.\d+)"); if (m.Success) return m.Groups[1].Value;
        m = Regex.Match(tfm, @"^netstandard(\d+\.\d+)"); if (m.Success) return m.Groups[1].Value;
        return null;
    }

    // framework reference name -> (pack id, profile, location: "packs" | "nuget")
    static (string pack, string? profile, string where)? MapFrameworkReference(string name) => name switch
    {
        "Microsoft.NETCore.App" => ("Microsoft.NETCore.App.Ref", null, "packs"),
        "Microsoft.AspNetCore.App" => ("Microsoft.AspNetCore.App.Ref", null, "packs"),
        "Microsoft.WindowsDesktop.App" => ("Microsoft.WindowsDesktop.App.Ref", null, "packs"),
        "Microsoft.WindowsDesktop.App.WPF" => ("Microsoft.WindowsDesktop.App.Ref", "WPF", "packs"),
        "Microsoft.WindowsDesktop.App.WindowsForms" => ("Microsoft.WindowsDesktop.App.Ref", "WindowsForms", "packs"),
        "Microsoft.Windows.SDK.NET.Ref.Windows" => ("Microsoft.Windows.SDK.NET.Ref", "Windows", "nuget"),
        "NETStandard.Library" => ("NETStandard.Library.Ref", null, "packs"),
        _ => null,
    };

    // ---------- the unit graph ----------
    public static Unit Load(string csproj, string? tfm, string? wantMoniker, Env env, Dictionary<string, Unit> seen)
    {
        var full = System.IO.Path.GetFullPath(csproj);
        var key = full + "|" + (tfm ?? wantMoniker ?? "");
        if (seen.TryGetValue(key, out var done)) return done;
        var u = new Unit { ProjectPath = full };
        seen[key] = u;
        var dir = System.IO.Path.GetDirectoryName(full)!;
        var proj = ProjectText.Read(full);
        u.Name = proj.AssemblyName ?? System.IO.Path.GetFileNameWithoutExtension(full);
        SourceSet.Fill(u, full, proj);

        var assetsPath = System.IO.Path.Combine(dir, "obj", "project.assets.json");
        if (!File.Exists(assetsPath)) { u.Unsupported.Add("no-assets"); return u; }
        using var doc = JsonDocument.Parse(File.ReadAllText(assetsPath));
        var root = doc.RootElement;
        var restore = root.GetProperty("project").GetProperty("restore");
        if (!restore.TryGetProperty("projectStyle", out var style) || style.GetString() != "PackageReference")
        { u.Unsupported.Add("project-style"); return u; }

        // target selection: RID-less keys only
        var targets = root.GetProperty("targets");
        var keys = targets.EnumerateObject().Select(p => p.Name).Where(k => !k.Contains('/')).OrderBy(k => k, StringComparer.Ordinal).ToList();
        string? chosen = null;
        if (tfm is not null) chosen = keys.FirstOrDefault(k => k == tfm);
        else if (wantMoniker is not null)
        {
            var hits = keys.Where(k => Moniker(k) == wantMoniker).ToList();
            if (hits.Count == 1) chosen = hits[0];
            else { u.Unsupported.Add($"p2p-target:{wantMoniker}:{hits.Count}"); return u; }
        }
        else if (keys.Count == 1) chosen = keys[0];
        else { u.Unsupported.Add($"multi-tfm:{string.Join(",", keys)}"); return u; }
        if (chosen is null) { u.Unsupported.Add($"tfm-not-in-assets:{tfm}"); return u; }
        u.Tfm = chosen;
        u.FrameworkMoniker = Moniker(chosen);
        var target = targets.GetProperty(chosen);

        // project.frameworks entry for this target (by key or targetAlias)
        JsonElement fwEntry = default;
        foreach (var f in root.GetProperty("project").GetProperty("frameworks").EnumerateObject())
            if (f.Name == chosen || (f.Value.TryGetProperty("targetAlias", out var ta) && ta.GetString() == chosen)) { fwEntry = f.Value; break; }

        // packages folder candidates
        var pkgRoots = new List<string>();
        if (restore.TryGetProperty("packagesPath", out var pp) && pp.GetString() is { } pps && Directory.Exists(pps)) pkgRoots.Add(pps);
        pkgRoots.Add(env.NugetRoot);
        string? PkgDir(string id, string ver) => pkgRoots.Select(r => System.IO.Path.Combine(r, id.ToLowerInvariant(), ver.ToLowerInvariant())).FirstOrDefault(Directory.Exists);

        // ---- framework references (project + transitive from packages) ----
        var fwRefs = new SortedSet<string>(StringComparer.Ordinal);
        if (fwEntry.ValueKind == JsonValueKind.Object && fwEntry.TryGetProperty("frameworkReferences", out var frs))
            foreach (var fr in frs.EnumerateObject()) fwRefs.Add(fr.Name);
        foreach (var e in target.EnumerateObject())
            if (e.Value.TryGetProperty("frameworkReferences", out var tfr) && tfr.ValueKind == JsonValueKind.Array)
                foreach (var x in tfr.EnumerateArray()) if (x.GetString() is { } s) fwRefs.Add(s);
        var download = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (fwEntry.ValueKind == JsonValueKind.Object && fwEntry.TryGetProperty("downloadDependencies", out var dd))
            foreach (var d in dd.EnumerateArray())
                download[d.GetProperty("name").GetString()!] = d.GetProperty("version").GetString()!.Trim('[', ']', ' ').Split(',')[0].Trim();

        var items = new List<RefItem>();
        var overrides = new Dictionary<string, Dictionary<string, Version>>(StringComparer.OrdinalIgnoreCase);
        var mm = MajorMinor(chosen);
        var packStatuses = new SortedSet<string>(StringComparer.Ordinal);
        // a WindowsDesktop.App reference with a profile and the same pack without one collapse to the union of profiles
        var packProfiles = new Dictionary<string, (string where, SortedSet<string?> profiles)>(StringComparer.Ordinal);
        foreach (var fr in fwRefs)
        {
            var map = MapFrameworkReference(fr);
            if (map is null) { u.Unsupported.Add($"framework-reference:{fr}"); continue; }
            if (!packProfiles.TryGetValue(map.Value.pack, out var e)) packProfiles[map.Value.pack] = e = (map.Value.where, new SortedSet<string?>(Comparer<string?>.Create((a, b) => string.CompareOrdinal(a, b))));
            e.profiles.Add(map.Value.profile);
        }
        foreach (var (pack, (where, profiles)) in packProfiles)
        {
            string? ver = null, status;
            string? packRoot = null;
            if (download.TryGetValue(pack, out var exact))
            {
                ver = exact; status = "PACK_EXACT";
                packRoot = where == "packs" ? System.IO.Path.Combine(env.DotnetRoot, "packs", pack, exact) : PkgDir(pack, exact);
                if (packRoot is null || !Directory.Exists(packRoot)) { u.RefReasons.Add($"pack-missing:{pack}/{exact}"); packStatuses.Add("REFERENCE_MISSING"); continue; }
            }
            else
            {
                var baseDir = System.IO.Path.Combine(env.DotnetRoot, "packs", pack);
                var cand = Directory.Exists(baseDir) && mm is not null
                    ? Directory.GetDirectories(baseDir).Select(System.IO.Path.GetFileName).Where(n => n!.StartsWith(mm + ".", StringComparison.Ordinal) && !n.Contains('-'))
                        .OrderByDescending(n => V(n)).ToList()
                    : new List<string?>();
                if (where != "packs" || cand.Count == 0) { u.RefReasons.Add($"pack-missing:{pack}/{mm}.*"); packStatuses.Add("REFERENCE_MISSING"); continue; }
                ver = cand[0]!; status = "PACK_MAJOR_MINOR";
                packRoot = System.IO.Path.Combine(baseDir, ver);
            }
            packStatuses.Add(status);
            var flist = System.IO.Path.Combine(packRoot, "data", "FrameworkList.xml");
            if (!File.Exists(flist)) { u.RefReasons.Add($"pack-no-frameworklist:{pack}/{ver}"); continue; }
            // one request per distinct profile; the union of files (a null profile = all files)
            var wantAll = profiles.Contains(null);
            foreach (var f in XDocument.Load(flist).Root!.Elements("File"))
            {
                var type = (string?)f.Attribute("Type");
                if (type is not null && type != "Managed") continue;                         // analyzers go elsewhere
                if (string.Equals((string?)f.Attribute("ReferencedByDefault"), "false", StringComparison.OrdinalIgnoreCase)) continue;
                if (!wantAll)
                {
                    var prof = ((string?)f.Attribute("Profile") ?? "").Split(';', StringSplitOptions.RemoveEmptyEntries);
                    if (!profiles.Any(p => p is not null && prof.Contains(p, StringComparer.OrdinalIgnoreCase))) continue;
                }
                var rel = (string?)f.Attribute("Path");
                if (rel is null) continue;
                var path = System.IO.Path.GetFullPath(System.IO.Path.Combine(packRoot, rel));
                items.Add(new RefItem(System.IO.Path.GetFileName(path), path, V((string?)f.Attribute("AssemblyVersion")), V((string?)f.Attribute("FileVersion")), pack, ver, true));
            }
            var po = System.IO.Path.Combine(packRoot, "data", "PackageOverrides.txt");
            if (File.Exists(po))
            {
                if (!overrides.TryGetValue(pack, out var map)) overrides[pack] = map = new(StringComparer.OrdinalIgnoreCase);
                foreach (var line in File.ReadAllLines(po))
                {
                    var parts = line.Trim().Split('|');
                    if (parts.Length == 2 && V(parts[1]) is { } cv && (!map.TryGetValue(parts[0], out var old) || old < cv)) map[parts[0]] = cv;
                }
            }
        }
        u.TfmStatus = packStatuses.Contains("REFERENCE_MISSING") ? "REFERENCE_MISSING"
            : packStatuses.Contains("PACK_MAJOR_MINOR") ? "PACK_MAJOR_MINOR" : packStatuses.Count > 0 ? "PACK_EXACT" : "NOT_APPLICABLE";

        // ---- packages and project references ----
        var libs = root.GetProperty("libraries");
        foreach (var e in target.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
        {
            var type = e.Value.TryGetProperty("type", out var t) ? t.GetString() : null;
            var slash = e.Name.IndexOf('/');
            var id = e.Name[..slash]; var ver = e.Name[(slash + 1)..];
            if (type == "project")
            {
                var lib = libs.GetProperty(e.Name);
                var relp = lib.TryGetProperty("msbuildProject", out var mp) ? mp.GetString() : lib.GetProperty("path").GetString();
                var childPath = System.IO.Path.GetFullPath(System.IO.Path.Combine(dir, relp!.Replace('/', System.IO.Path.DirectorySeparatorChar)));
                var fw = e.Value.TryGetProperty("framework", out var fwp) ? fwp.GetString() : null;
                if (!File.Exists(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(childPath)!, "obj", "project.assets.json")))
                { u.SrcReasons.Add($"p2p-no-assets:{id}"); continue; }
                var child = Load(childPath, null, fw, env, seen);
                u.Children.Add(child);
                if (child.UnitStatus != "COMPLETE" && child.UnitStatus != "SOURCE_SET_INCOMPLETE") u.SrcReasons.Add($"p2p-unit-{child.UnitStatus.ToLowerInvariant()}:{id}");
                continue;
            }
            if (type != "package") continue;
            var pdir = PkgDir(id, ver);
            var compile = e.Value.TryGetProperty("compile", out var c) ? c.EnumerateObject().Select(x => x.Name).Where(n => !n.EndsWith("/_._", StringComparison.Ordinal) && n != "_._").ToList() : new List<string>();
            if (pdir is not null && Directory.Exists(System.IO.Path.Combine(pdir, "analyzers"))
                && Directory.EnumerateFiles(System.IO.Path.Combine(pdir, "analyzers"), "*.dll", SearchOption.AllDirectories)
                    .Any(p => !p.Replace('\\', '/').Contains("/vb/", StringComparison.OrdinalIgnoreCase) && !p.Replace('\\', '/').Contains("/fs/", StringComparison.OrdinalIgnoreCase)))
                u.SrcReasons.Add($"package-analyzers:{id.ToLowerInvariant()}/{ver}");
            if (compile.Count == 0) continue;
            if (pdir is null) { u.RefReasons.Add($"package-missing:{id}/{ver}"); continue; }
            // identity: assets sha512 == the cache's recorded content hash
            var meta = System.IO.Path.Combine(pdir, ".nupkg.metadata");
            var want = libs.TryGetProperty(e.Name, out var le) && le.TryGetProperty("sha512", out var sh) ? sh.GetString() : null;
            string? have = null;
            if (File.Exists(meta)) { using var md = JsonDocument.Parse(File.ReadAllText(meta)); have = md.RootElement.TryGetProperty("contentHash", out var ch) ? ch.GetString() : null; }
            if (want is null || have is null || want != have) { u.RefReasons.Add($"package-identity:{id}/{ver}"); continue; }
            foreach (var asset in compile)
            {
                var path = System.IO.Path.GetFullPath(System.IO.Path.Combine(pdir, asset.Replace('/', System.IO.Path.DirectorySeparatorChar)));
                if (!File.Exists(path)) { u.RefReasons.Add($"package-asset-missing:{id}/{ver}/{asset}"); continue; }
                var (av, fv) = DllVersions(path);
                items.Add(new RefItem(System.IO.Path.GetFileName(path), path, av, fv, id, ver, false));
            }
        }

        // ---- conflict resolution keyed by file name (ResolvePackageFileConflicts) ----
        foreach (var g in items.GroupBy(i => i.FileName, StringComparer.OrdinalIgnoreCase).OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase))
        {
            var list = g.OrderBy(i => i.IsFramework ? 0 : 1).ThenBy(i => i.Path, StringComparer.Ordinal).ToList();
            var winner = list[0];
            foreach (var x in list.Skip(1))
            {
                if (string.Equals(x.Path, winner.Path, StringComparison.OrdinalIgnoreCase)) continue;
                var (w, rule) = Resolve(winner, x, overrides);
                var entry = new Dictionary<string, string>
                {
                    ["name"] = g.Key,
                    ["a"] = $"{winner.PackageId}/{winner.PackageVersion} av={winner.AV} fv={winner.FV}",
                    ["b"] = $"{x.PackageId}/{x.PackageVersion} av={x.AV} fv={x.FV}",
                    ["rule"] = rule,
                };
                if (w is null) { entry["winner"] = "UNRESOLVED"; u.RefReasons.Add($"conflict-unresolved:{g.Key}"); }
                else
                {
                    entry["winner"] = $"{w.PackageId}/{w.PackageVersion}";
                    if (rule == "TIE_FRAMEWORK_ASSUMED") u.TieAssumed = true;
                    winner = w;
                }
                u.Conflicts.Add(entry);
            }
            u.Manifest.Add(winner);
        }
        // reference kinds the assets do not describe
        foreach (var rk in proj.ReferenceItems) u.Unsupported.Add($"reference-kind:{rk}");
        return u;
    }

    static (RefItem? winner, string rule) Resolve(RefItem a, RefItem b, Dictionary<string, Dictionary<string, Version>> overrides)
    {
        // 1. package overrides: the overriding id is the targeting pack's id; the overridden version is inclusive
        if (Overrides(a, b, overrides)) return (a, "override");
        if (Overrides(b, a, overrides)) return (b, "override");
        // 2. existence
        if (!File.Exists(a.Path) || !File.Exists(b.Path)) return (null, "missing-file");
        // 3. assembly version
        if ((a.AV is null) != (b.AV is null)) return (null, "assembly-version-one-null");
        if (a.AV is not null && a.AV != b.AV) return (a.AV > b.AV! ? a : b, "assembly-version");
        // 4. file version
        if ((a.FV is null) != (b.FV is null)) return (null, "file-version-one-null");
        if (a.FV is not null && a.FV != b.FV) return (a.FV > b.FV! ? a : b, "file-version");
        // 5./6. package rank / platform: the preferred-packages list is not read; framework beats package (assumption)
        if (a.IsFramework != b.IsFramework) return (a.IsFramework ? a : b, "TIE_FRAMEWORK_ASSUMED");
        return (null, "equal");
    }

    static bool Overrides(RefItem over, RefItem other, Dictionary<string, Dictionary<string, Version>> overrides) =>
        overrides.TryGetValue(over.PackageId, out var map) && map.TryGetValue(other.PackageId, out var ceil)
        && V(other.PackageVersion) is { } pv && pv <= ceil;

    // ---------- compilations (children first; project references as CompilationReference) ----------
    public static void Compile(Unit u, Env env, HashSet<Unit> done)
    {
        if (!done.Add(u)) return;
        foreach (var c in u.Children) Compile(c, env, done);
        if (u.Unsupported.Count > 0 || u.Tfm is null) return;
        u.Trees = new List<SyntaxTree>();
        u.Unreadable = 0;
        foreach (var f in u.SourceFiles)
        {
            try { u.Trees.Add(CSharpSyntaxTree.ParseText(File.ReadAllText(f), path: f)); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { u.Unreadable++; }
        }
        var refs = u.Manifest.Select(m => env.Meta(m.Path)).ToList();
        foreach (var c in u.Children) if (c.Comp is not null) refs.Add(c.Comp.ToMetadataReference());
        u.Comp = CSharpCompilation.Create(u.Name, u.Trees, refs, Opts);
    }

    public static IEnumerable<Unit> Closure(Unit root)
    {
        var seen = new HashSet<Unit>();
        var stack = new Stack<Unit>(); stack.Push(root);
        while (stack.Count > 0)
        {
            var u = stack.Pop();
            if (!seen.Add(u)) continue;
            yield return u;
            foreach (var c in u.Children) stack.Push(c);
        }
    }
}

// Minimal text read of a .csproj: the properties that change the compilation, and reference kinds assets do not cover.
sealed class ProjectText
{
    public string? AssemblyName, DefineConstants, ImplicitUsings, EnableDefaultCompileItems;
    public bool UseWpf, UseWinForms;
    public List<string> Includes = new(), Removes = new(), ReferenceItems = new();
    public bool Malformed;

    public static ProjectText Read(string path)
    {
        var p = new ProjectText();
        XDocument doc;
        try { doc = XDocument.Load(path); } catch { p.Malformed = true; return p; }
        string? Last(string n) => doc.Descendants().Where(e => e.Name.LocalName == n).Select(e => e.Value.Trim()).LastOrDefault();
        p.AssemblyName = Last("AssemblyName");
        p.DefineConstants = Last("DefineConstants");
        p.ImplicitUsings = Last("ImplicitUsings");
        p.EnableDefaultCompileItems = Last("EnableDefaultCompileItems");
        p.UseWpf = string.Equals(Last("UseWPF"), "true", StringComparison.OrdinalIgnoreCase);
        p.UseWinForms = string.Equals(Last("UseWindowsForms"), "true", StringComparison.OrdinalIgnoreCase);
        foreach (var e in doc.Descendants())
        {
            if (e.Name.LocalName == "Compile")
            {
                if (e.Attribute("Include")?.Value is { Length: > 0 } inc) p.Includes.Add(inc);
                if (e.Attribute("Remove")?.Value is { Length: > 0 } rem) p.Removes.Add(rem);
            }
            if (e.Name.LocalName is "Reference" or "COMReference" && e.Attribute("Include")?.Value is { Length: > 0 } r)
                p.ReferenceItems.Add($"{e.Name.LocalName}:{r}");
        }
        return p;
    }
}

// The extractor's source-set rules (Program.cs IsSkipped / SpecMatcher / ProjectCsFiles), ported; plus the
// source-set completeness reasons of the pre-registration §1.
static class SourceSet
{
    static bool IsSkippedDir(string seg) => seg is "bin" or "obj" or ".git" or ".vs" or "node_modules" or "packages";
    static bool IsGenerated(string path) =>
        path.EndsWith(".g.cs", StringComparison.Ordinal) || path.EndsWith(".Designer.cs", StringComparison.Ordinal)
        || path.EndsWith(".AssemblyInfo.cs", StringComparison.Ordinal);

    static Func<string, bool> SpecMatcher(string spec, string dir)
    {
        var glob = spec.Replace('\\', '/').Trim();
        var rx = new StringBuilder("^");
        for (int i = 0; i < glob.Length; i++)
        {
            var c = glob[i];
            if (c == '*')
            {
                if (i + 1 < glob.Length && glob[i + 1] == '*') { rx.Append(".*"); i++; if (i + 1 < glob.Length && glob[i + 1] == '/') i++; }
                else rx.Append("[^/]*");
            }
            else if (c == '?') rx.Append("[^/]");
            else rx.Append(Regex.Escape(c.ToString()));
        }
        rx.Append('$');
        var regex = new Regex(rx.ToString(), RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1));
        return path => { try { return regex.IsMatch(System.IO.Path.GetRelativePath(dir, path).Replace('\\', '/')); } catch (RegexMatchTimeoutException) { return false; } };
    }

    static readonly string[] GeneratorAttributes = { "LibraryImport", "GeneratedRegex", "JSImport", "JSExport", "GeneratedComInterface" };

    public static void Fill(Unit u, string csproj, ProjectText proj)
    {
        var dir = System.IO.Path.GetDirectoryName(csproj)!;
        var opts = new EnumerationOptions { RecurseSubdirectories = true, IgnoreInaccessible = true };
        var all = Directory.EnumerateFiles(dir, "*.cs", opts).ToList();
        bool Skipped(string f) => System.IO.Path.GetRelativePath(dir, f).Split('/', '\\').Any(IsSkippedDir) || IsGenerated(f);
        // generated files the extractor would skip, counted (not compiled)
        u.GeneratedExcluded = all.Count(f => !System.IO.Path.GetRelativePath(dir, f).Split('/', '\\').Any(IsSkippedDir) && IsGenerated(f));
        var candidates = all.Where(f => !Skipped(f)).ToList();
        var result = new List<string>();
        var defaultCompile = !string.Equals(proj.EnableDefaultCompileItems, "false", StringComparison.OrdinalIgnoreCase);
        if (defaultCompile) result.AddRange(candidates);
        else { var inc = proj.Includes.Select(s => SpecMatcher(s, dir)).ToList(); result.AddRange(candidates.Where(f => inc.Any(m => m(f)))); }
        var prefix = dir.EndsWith(System.IO.Path.DirectorySeparatorChar) ? dir : dir + System.IO.Path.DirectorySeparatorChar;
        foreach (var inc in proj.Includes)
        {
            if (inc.IndexOfAny(new[] { '*', '?' }) >= 0) continue;
            var path = System.IO.Path.GetFullPath(System.IO.Path.Combine(dir, inc.Replace('\\', System.IO.Path.DirectorySeparatorChar)));
            if (path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase) && File.Exists(path) && !IsGenerated(path) && !path.StartsWith(prefix, StringComparison.Ordinal))
                result.Add(path);
        }
        if (proj.Removes.Count > 0) { var rm = proj.Removes.Select(s => SpecMatcher(s, dir)).ToList(); result.RemoveAll(f => rm.Any(m => m(f))); }
        u.SourceFiles.AddRange(result.Distinct().OrderBy(f => f, StringComparer.Ordinal));

        // completeness reasons (reported, never applied)
        if (proj.Malformed) u.SrcReasons.Add("csproj-malformed");
        if (proj.UseWpf) u.SrcReasons.Add("wpf-xaml-codegen");
        if (proj.UseWinForms) u.SrcReasons.Add("winforms-designer");
        if (!string.IsNullOrWhiteSpace(proj.DefineConstants)) u.SrcReasons.Add("define-constants");
        if (proj.ImplicitUsings is { } iu && (iu.Equals("enable", StringComparison.OrdinalIgnoreCase) || iu.Equals("true", StringComparison.OrdinalIgnoreCase)))
            u.SrcReasons.Add("implicit-usings-not-applied");
        for (var d = new DirectoryInfo(dir); d is not null; d = d.Parent)
            foreach (var n in new[] { "Directory.Build.props", "Directory.Build.targets" })
                if (File.Exists(System.IO.Path.Combine(d.FullName, n))) u.SrcReasons.Add($"directory-build:{n}");
        foreach (var f in u.SourceFiles)
        {
            string text;
            try { text = File.ReadAllText(f); } catch { continue; }
            foreach (var a in GeneratorAttributes)
                if (text.Contains("[" + a, StringComparison.Ordinal))
                    u.SrcReasons.Add($"framework-generator:{a}");
        }
    }
}
