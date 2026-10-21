// P-014 bounded design — D2 isolation falsifiers (research only, not product code).
// Builds tiny in-memory "projects" and compares ONE merged CSharpCompilation (today's extractor shape)
// with ONE compilation PER project (project references as CompilationReference). Prints, per probe site,
// the bound symbol, its containing assembly, or the candidate reason. Same Roslyn as the extractor (4.9.2).
// Framework references: the Microsoft.NETCore.App.Ref 8.0.31 reference pack passed as args[0].
using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var packDir = args[0];
var fw = Directory.EnumerateFiles(packDir, "*.dll").OrderBy(p => p, StringComparer.Ordinal)
    .Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
var opts = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary);

SyntaxTree T(string proj, string file, string code) =>
    CSharpSyntaxTree.ParseText(code, path: $"{proj}/{file}");

// A metadata-only "package" assembly with an explicit identity, so two versions share a simple name.
MetadataReference Lib(string name, string version, string body)
{
    var c = CSharpCompilation.Create(name,
        new[] { CSharpSyntaxTree.ParseText($"[assembly: System.Reflection.AssemblyVersion(\"{version}\")]\n{body}") },
        fw, opts);
    using var ms = new MemoryStream();
    var r = c.Emit(ms);
    if (!r.Success) throw new Exception(string.Join("\n", r.Diagnostics));
    return MetadataReference.CreateFromImage(ms.ToArray());
}

// Probe sites are invocations / member accesses / identifier names carrying a `/*probe:ID*/` comment on the same line.
void Report(string label, Compilation comp)
{
    var errs = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error)
        .GroupBy(d => d.Id).OrderBy(g => g.Key).Select(g => $"{g.Key}x{g.Count()}");
    Console.WriteLine($"  [{label}] errors: {string.Join(" ", errs)}");
    foreach (var tree in comp.SyntaxTrees)
    {
        var model = comp.GetSemanticModel(tree);
        var text = tree.GetText();
        foreach (var line in text.Lines)
        {
            var s = line.ToString();
            var i = s.IndexOf("/*probe:", StringComparison.Ordinal);
            if (i < 0) continue;
            var id = s.Substring(i + 8, s.IndexOf("*/", i, StringComparison.Ordinal) - i - 8);
            var node = tree.GetRoot().DescendantNodes(line.Span)
                .Where(n => line.Span.Contains(n.Span))
                .OrderBy(n => n is AssignmentExpressionSyntax ? 0 : n is InvocationExpressionSyntax ? 1 : 2)
                .FirstOrDefault(n => n is InvocationExpressionSyntax or AssignmentExpressionSyntax or ObjectCreationExpressionSyntax);
            if (node is AssignmentExpressionSyntax a) node = a.Left;
            if (node is null) { Console.WriteLine($"    {id}: no node"); continue; }
            var si = model.GetSymbolInfo(node);
            string what = si.Symbol is { } sym
                ? $"{sym.Kind} {sym.ToDisplayString()} @ {sym.ContainingAssembly?.Identity.ToString() ?? "-"}"
                : si.CandidateSymbols.Length > 0
                    ? $"null, {si.CandidateReason}: " + string.Join(" | ", si.CandidateSymbols.Select(c => $"{c.ToDisplayString()} @ {c.ContainingAssembly?.Name}"))
                    : "UNRESOLVED";
            var siteDiags = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error
                && d.Location.SourceTree == tree && line.Span.IntersectsWith(d.Location.SourceSpan)).Select(d => d.Id).Distinct();
            Console.WriteLine($"    {tree.FilePath} {id}: {what}  site-errors=[{string.Join(",", siteDiags)}]");
        }
    }
}

CSharpCompilation Merged(IEnumerable<SyntaxTree> trees, IEnumerable<MetadataReference> refs) =>
    CSharpCompilation.Create("own", trees, fw.Concat(refs), opts);
CSharpCompilation Proj(string name, IEnumerable<SyntaxTree> trees, IEnumerable<MetadataReference> refs) =>
    CSharpCompilation.Create(name, trees, fw.Concat(refs), opts);

// SDK default global usings for Microsoft.NET.Sdk (C# 10 ImplicitUsings=enable).
const string ImplicitUsings = """
global using global::System;
global using global::System.Collections.Generic;
global using global::System.IO;
global using global::System.Linq;
global using global::System.Net.Http;
global using global::System.Threading;
global using global::System.Threading.Tasks;
""";

// ---------- F2.1 two projects declare Dup.T ----------
Console.WriteLine("F2.1 Dup.T declared in two projects");
{
    var p1 = new[] { T("P1", "a.cs", "namespace Dup { public class T { public int One() => 1; } }"),
                     T("P1", "use1.cs", "class U1 { int M() => new Dup.T().One(); /*probe:p1-One*/ }") };
    var p2 = new[] { T("P2", "b.cs", "namespace Dup { public class T { public int Two() => 2; } }"),
                     T("P2", "use2.cs", @"class U2 {
 int M() => new Dup.T().Two(); /*probe:p2-Two*/
 int N() => new Dup.T().One(); /*probe:p2-One-must-fail*/
}") };
    var p3 = new[] { T("P3", "use3.cs", "class U3 { object M() => new Dup.T(); /*probe:p3-refs-both*/ }") };
    Report("merged", Merged(p1.Concat(p2).Concat(p3), Array.Empty<MetadataReference>()));
    var c1 = Proj("P1", p1, Array.Empty<MetadataReference>());
    var c2 = Proj("P2", p2, Array.Empty<MetadataReference>());
    Report("per-project P1", c1);
    Report("per-project P2", c2);
    Report("per-project P3 -> P1,P2", Proj("P3", p3, new[] { c1.ToMetadataReference(), c2.ToMetadataReference() }));
}

// ---------- F2.2 same simple assembly name, two versions ----------
Console.WriteLine("F2.2 Lib 1.0 in P1, Lib 2.0 in P2");
{
    var v1 = Lib("Lib", "1.0.0.0", "namespace L { public static class C { public static int V1Only() => 1; } }");
    var v2 = Lib("Lib", "2.0.0.0", "namespace L { public static class C { public static int V2Only() => 2; } }");
    var p1 = new[] { T("P1", "a.cs", "class A { int M() => L.C.V1Only(); /*probe:p1-V1Only*/ }") };
    var p2 = new[] { T("P2", "b.cs", "class B { int M() => L.C.V2Only(); /*probe:p2-V2Only*/ }") };
    Report("merged, first-name-wins (v1 only)", Merged(p1.Concat(p2), new[] { v1 }));
    Report("merged, both versions", Merged(p1.Concat(p2), new[] { v1, v2 }));
    Report("per-project P1 (v1)", Proj("P1", p1, new[] { v1 }));
    Report("per-project P2 (v2)", Proj("P2", p2, new[] { v2 }));
}

// ---------- F2.3 ImplicitUsings enable in P1, disable in P2 ----------
Console.WriteLine("F2.3 ImplicitUsings: P1 enable, P2 disable");
{
    var p1 = new[] { T("P1", "GlobalUsings.g.cs", ImplicitUsings),
                     T("P1", "a.cs", "class A { bool M() => File.Exists(\"x\"); /*probe:p1-File*/ }") };
    var p2 = new[] { T("P2", "b.cs", "class B { bool M() => File.Exists(\"x\"); /*probe:p2-File-must-fail*/ }") };
    Report("merged", Merged(p1.Concat(p2), Array.Empty<MetadataReference>()));
    Report("per-project P1", Proj("P1", p1, Array.Empty<MetadataReference>()));
    Report("per-project P2", Proj("P2", p2, Array.Empty<MetadataReference>()));
}

// ---------- F2.4 Timer: System.Timers vs System.Threading ----------
Console.WriteLine("F2.4 Timer: P1 implicit usings (System.Threading), P2 `using System.Timers;` only");
{
    var p1 = new[] { T("P1", "GlobalUsings.g.cs", ImplicitUsings),
                     T("P1", "a.cs", "class A { void M() { var t = new Timer(_ => { }); /*probe:p1-Timer*/ } }") };
    var p2 = new[] { T("P2", "b.cs", """
        using System.Timers;
        class B { Timer t = new Timer(100); /*probe:p2-Timer*/
          void M() { t.Elapsed += H; /*probe:p2-Elapsed*/ }
          void H(object s, ElapsedEventArgs e) { } }
        """) };
    Report("merged", Merged(p1.Concat(p2), Array.Empty<MetadataReference>()));
    Report("per-project P1", Proj("P1", p1, Array.Empty<MetadataReference>()));
    Report("per-project P2", Proj("P2", p2, Array.Empty<MetadataReference>()));
}

// ---------- F2.5 one project with a missing dependency ----------
Console.WriteLine("F2.5 P3 misses its dependency; P1 is complete");
{
    var dep = Lib("Dep", "1.0.0.0", "namespace D { public class Src { public event System.EventHandler Changed; public void Raise() => Changed?.Invoke(this, System.EventArgs.Empty); } }");
    var p1 = new[] { T("P1", "a.cs", @"class A { D.Src s = new D.Src();
 void M() { s.Changed += H; /*probe:p1-Changed*/ } void H(object o, System.EventArgs e) { } }") };
    var p3 = new[] { T("P3", "c.cs", @"class C { D.Src s = new D.Src();
 void M() { s.Changed += H; /*probe:p3-Changed-missing*/ } void H(object o, System.EventArgs e) { } }") };
    Report("merged (Dep referenced, P3 did not declare it)", Merged(p1.Concat(p3), new[] { dep }));
    Report("per-project P1 (Dep)", Proj("P1", p1, new[] { dep }));
    Report("per-project P3 (no Dep)", Proj("P3", p3, Array.Empty<MetadataReference>()));
}
