// P-014 Tiny PoC — in-memory controls (pre-registration §2, unit level). Each control builds synthetic units with
// real Roslyn and the local Microsoft.NETCore.App.Ref 8.0.x reference pack, runs the same Coverage.Measure as the
// project mode, and compares the observation with the expectation fixed in the pre-registration.
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

static class Controls
{
    static readonly CSharpCompilationOptions Opts = new(OutputKind.DynamicallyLinkedLibrary);

    public static int Run(Env env, string outPath, JsonSerializerOptions jo)
    {
        var packs = Path.Combine(env.DotnetRoot, "packs", "Microsoft.NETCore.App.Ref");
        var ver = Directory.GetDirectories(packs).Select(Path.GetFileName).Where(n => n!.StartsWith("8.0.") && !n.Contains('-')).OrderByDescending(n => Assets.V(n)).First()!;
        var fw = Directory.EnumerateFiles(Path.Combine(packs, ver, "ref", "net8.0"), "*.dll").OrderBy(p => p, StringComparer.Ordinal).Select(env.Meta).ToList();
        var results = new List<SortedDictionary<string, object>>();
        var allPass = true;

        SyntaxTree T(string u, string f, string code) => CSharpSyntaxTree.ParseText(code, path: $"{u}/{f}");
        MetadataReference Lib(string name, string version, string body)
        {
            var c = CSharpCompilation.Create(name, new[] { CSharpSyntaxTree.ParseText($"[assembly: System.Reflection.AssemblyVersion(\"{version}\")]\n{body}") }, fw, Opts);
            using var ms = new MemoryStream();
            var r = c.Emit(ms);
            if (!r.Success) throw new Exception(string.Join("\n", r.Diagnostics));
            return MetadataReference.CreateFromImage(ms.ToArray());
        }
        CSharpCompilation U(string name, SyntaxTree[] trees, params MetadataReference[] refs) => CSharpCompilation.Create(name, trees, fw.Concat(refs), Opts);
        UnitCoverage M(CSharpCompilation c, ISet<string>? allowed = null) => Coverage.Measure(c, c.SyntaxTrees, allowed ?? Coverage.Allowed(c), p => p);
        string P(UnitCoverage c, string probe) => c.Probes.TryGetValue(probe, out var l) ? string.Join(" | ", l) : "NO-SITE";
        int S(UnitCoverage c, string kind, string key) => c.Sites.TryGetValue(kind, out var d) ? d.GetValueOrDefault(key) : 0;
        void Check(string id, bool pass, string observed, string expected)
        {
            allPass &= pass;
            results.Add(new SortedDictionary<string, object>(StringComparer.Ordinal) { ["control"] = id, ["pass"] = pass, ["observed"] = observed, ["expected"] = expected });
            Console.WriteLine($"{(pass ? "PASS" : "FAIL")} {id}: {observed}");
        }

        const string ImplicitUsings = "global using global::System;\nglobal using global::System.Collections.Generic;\nglobal using global::System.IO;\nglobal using global::System.Linq;\nglobal using global::System.Net.Http;\nglobal using global::System.Threading;\nglobal using global::System.Threading.Tasks;\n";

        // K1 consistent BCL-only unit
        {
            var c = M(U("K1", new[] { T("K1", "a.cs", "using System.Collections.Generic; class A { int M() { var l = new List<int>(); l.Add(1); /*probe:k1*/ return l.Count; } }") }));
            Check("K1", c.Foreign.Count == 0 && P(c, "k1").Contains("invocation:resolved") && !P(c, "k1").Contains(":error") && !P(c, "k1").Contains(":unresolved")
                && S(c, "invocation", "unresolved") == 0 && c.Errors.Count == 0,
                $"foreign={c.Foreign.Count} probe={P(c, "k1")} unresolved={S(c, "invocation", "unresolved")} errors={string.Join(",", c.Errors.Keys)} types={string.Join(";", c.AllSites.Where(x => x.Kind == "type").Select(x => x.Status + ":" + x.Start + "+" + x.Length))}", "foreign=0, all invocations resolved");
        }
        // K2 same simple name, two versions, one per unit
        {
            var v1 = Lib("Lib", "1.0.0.0", "namespace L { public static class C { public static int V1Only() => 1; } }");
            var v2 = Lib("Lib", "2.0.0.0", "namespace L { public static class C { public static int V2Only() => 2; } }");
            var c1 = M(U("U1", new[] { T("U1", "a.cs", "class A { int M() => L.C.V1Only(); /*probe:k2-u1*/ }") }, v1));
            var c2 = M(U("U2", new[] { T("U2", "b.cs", "class B { int M() => L.C.V2Only(); /*probe:k2-u2*/ }") }, v2));
            Check("K2", P(c1, "k2-u1").StartsWith("invocation:resolved:L.C.V1Only()@Lib") && P(c2, "k2-u2").StartsWith("invocation:resolved:L.C.V2Only()@Lib")
                && !c1.Errors.ContainsKey("CS1704") && !c2.Errors.ContainsKey("CS1704") && c1.Foreign.Count + c2.Foreign.Count == 0,
                $"u1={P(c1, "k2-u1")} u2={P(c2, "k2-u2")}", "each unit binds its own version; no CS1704");
        }
        // K4 Dup.T: merged CS0101; per-unit U2.One() unresolved (CS1061); U3 -> U1,U2 ambiguous (CS0433 at site)
        {
            var t1 = new[] { T("U1", "a.cs", "namespace Dup { public class T { public int One() => 1; } }") };
            var t2 = new[] { T("U2", "b.cs", "namespace Dup { public class T { public int Two() => 2; } }"),
                             T("U2", "use.cs", "class U2 {\n int N() => new Dup.T().One(); /*probe:k4-u2-one*/\n}") };
            var t3 = new[] { T("U3", "c.cs", "class U3 {\n object M() => new Dup.T(); /*probe:k4-u3*/\n}") };
            var merged = M(U("own", t1.Concat(t2).Concat(t3).ToArray()), new HashSet<string>());
            var u1 = U("U1", t1); var u2 = U("U2", t2);
            var c2 = M(u2);
            var c3 = M(U("U3", t3, u1.ToMetadataReference(), u2.ToMetadataReference()));
            Check("K4", merged.Errors.ContainsKey("CS0101") && P(c2, "k4-u2-one").Contains("invocation:unresolved") && c2.Errors.ContainsKey("CS1061")
                && P(c3, "k4-u3").Contains("type:ambiguous") && c3.Errors.ContainsKey("CS0433"),
                $"merged_errors={string.Join(",", merged.Errors.Keys)} u2={P(c2, "k4-u2-one")} u3={P(c3, "k4-u3")} u3_errors={string.Join(",", c3.Errors.Keys)}",
                "merged CS0101; U2 One() unresolved+CS1061; U3 type ambiguous via CS0433");
        }
        // K5 external event vs int field, both +=
        {
            var dep = Lib("Dep5", "1.0.0.0", "namespace D { public class S { public event System.EventHandler E; public int N; void R() => E?.Invoke(this, System.EventArgs.Empty); } }");
            var c = M(U("K5", new[] { T("K5", "a.cs", "class A { D.S s = new D.S(); void M() { s.E += H; s.N += 1; } void H(object o, System.EventArgs e) { } }") }, dep));
            Check("K5", S(c, "event_assign", "event") == 1 && S(c, "event_assign", "non_event") == 1 && c.Foreign.Count == 0,
                $"event={S(c, "event_assign", "event")} non_event={S(c, "event_assign", "non_event")}", "event=1 non_event=1");
        }
        // K6 type from an absent assembly
        {
            var c = M(U("K6", new[] { T("K6", "a.cs", "class A { object M() => new Missing.Thing(); /*probe:k6*/ }") }));
            Check("K6", P(c, "k6").Contains("type:error") && !P(c, "k6").Contains(":resolved") && c.Foreign.Count == 0,
                $"probe={P(c, "k6")} foreign={c.Foreign.Count}", "unresolved, nothing invented");
        }
        // K7 #if without defines: the #else branch is the one compiled
        {
            var c = M(U("K7", new[] { T("K7", "a.cs", "class A {\n#if NET8_0\n int M() => System.Math.Max(1, 2); /*probe:k7-if*/\n#else\n int M() => System.Math.Min(1, 2); /*probe:k7-else*/\n#endif\n}") }));
            Check("K7", P(c, "k7-if") == "NO-SITE" && P(c, "k7-else").StartsWith("invocation:resolved"),
                $"if={P(c, "k7-if")} else={P(c, "k7-else")}", "#else seen, #if inactive (source-set limit)");
        }
        // F2.3 implicit usings in U1 only
        {
            var c1 = M(U("U1", new[] { T("U1", "GlobalUsings.g.cs", ImplicitUsings), T("U1", "a.cs", "class A { bool M() => File.Exists(\"x\"); /*probe:f23-u1*/ }") }));
            var c2 = M(U("U2", new[] { T("U2", "b.cs", "class B { bool M() => File.Exists(\"x\"); /*probe:f23-u2*/ }") }));
            Check("F2.3", P(c1, "f23-u1").StartsWith("invocation:resolved") && P(c2, "f23-u2").StartsWith("invocation:unresolved"),
                $"u1={P(c1, "f23-u1")} u2={P(c2, "f23-u2")}", "U2 File.Exists unresolved");
        }
        // F2.4 Timer
        {
            var c2 = M(U("U2", new[] { T("U2", "b.cs", "using System.Timers;\nclass B { Timer t = new Timer(100);\n void M() { t.Elapsed += H; /*probe:f24-elapsed*/ }\n void H(object s, ElapsedEventArgs e) { } }") }));
            Check("F2.4", P(c2, "f24-elapsed").Contains("event_assign:resolved:System.Timers.Timer.Elapsed"),
                $"u2={P(c2, "f24-elapsed")}", "U2 binds System.Timers.Timer.Elapsed (event)");
        }
        // F2.5 U3 lacks Dep, U1 has it
        {
            var dep = Lib("Dep", "1.0.0.0", "namespace D { public class Src { public event System.EventHandler Changed; public void R() => Changed?.Invoke(this, System.EventArgs.Empty); } }");
            var c1 = M(U("U1", new[] { T("U1", "a.cs", "class A { D.Src s = new D.Src();\n void M() { s.Changed += H; /*probe:f25-u1*/ } void H(object o, System.EventArgs e) { } }") }, dep));
            var c3 = M(U("U3", new[] { T("U3", "c.cs", "class C { D.Src s = new D.Src();\n void M() { s.Changed += H; /*probe:f25-u3*/ } void H(object o, System.EventArgs e) { } }") }));
            Check("F2.5", P(c1, "f25-u1").Contains("event_assign:resolved") && P(c3, "f25-u3").Contains("event_assign:unresolved") && c3.Foreign.Count == 0,
                $"u1={P(c1, "f25-u1")} u3={P(c3, "f25-u3")}", "U3 unresolved, foreign=0");
            // guard self-test: the merged shape bound U3's event through U1's reference; judged against U3's OWN manifest
            // (framework only), the guard must flag it as a foreign binding
            var merged = U("own", new[] { T("U3", "c.cs", "class C { D.Src s = new D.Src();\n void M() { s.Changed += H; } void H(object o, System.EventArgs e) { } }") }, dep);
            var u3Allowed = Coverage.Allowed(U("U3", Array.Empty<SyntaxTree>()));
            u3Allowed.Add(merged.Assembly.Identity.ToString());
            var g = M(merged, u3Allowed);
            Check("GUARD", g.Foreign.Count > 0, $"foreign={g.Foreign.Count} first={g.Foreign.FirstOrDefault()}", "guard flags a symbol from outside the unit's manifest");
        }
        // K11 unresolved lambda / new-delegate subscriptions: no OWN050 marker in today's extractor (G1)
        {
            var c = M(U("K11", new[] { T("K11", "a.cs", "class A { Ext.Thing x; void M() { x.E += (s, e) => { }; x.F += new System.EventHandler(H); x.G += H; } void H(object o, System.EventArgs e) { } }") }));
            Check("K11", S(c, "event_assign", "unresolved") == 3 && S(c, "event_assign", "unresolved_no_marker") == 2,
                $"unresolved={S(c, "event_assign", "unresolved")} no_marker={S(c, "event_assign", "unresolved_no_marker")}", "unresolved_no_marker=2 (lambda, new delegate)");
        }
        // K12 unresolved disposable-looking field type (G2)
        {
            var c = M(U("K12", new[] { T("K12", "a.cs", "class A { FooStream s; System.IO.MemoryStream m; }") }));
            Check("K12", S(c, "disposable_type", "name_heuristic") == 1 && S(c, "disposable_type", "resolved") == 1,
                $"name_heuristic={S(c, "disposable_type", "name_heuristic")} resolved={S(c, "disposable_type", "resolved")}", "name_heuristic=1, not counted resolved");
        }
        File.WriteAllText(outPath, JsonSerializer.Serialize(new { reference_pack = $"Microsoft.NETCore.App.Ref/{ver}", all_pass = allPass, results }, jo));
        return allPass ? 0 : 1;
    }
}
