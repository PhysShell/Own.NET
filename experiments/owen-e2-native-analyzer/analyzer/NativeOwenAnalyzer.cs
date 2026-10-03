// E2 spike (OX-01): a Roslyn DiagnosticAnalyzer that hands an OwnIR facts document to the
// Rust core IN PROCESS (P/Invoke into owen_e2) and reports what the core renders. The C# side
// only maps `file(line): warning CODE: text` onto a Location: no semantics here.
//
// Facts come from an AdditionalFile named *.owen-facts.json — an analyzer cannot run the
// extractor (a separate program reading files), which is itself one of the findings.

using System;
using System.Collections.Immutable;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.Text;

namespace Owen.E2
{
    [DiagnosticAnalyzer(LanguageNames.CSharp)]
    public sealed class NativeOwenAnalyzer : DiagnosticAnalyzer
    {
        private static readonly DiagnosticDescriptor Finding = new("OWNE2", "Owen finding (E2 spike)", "{0}",
            "Owen.E2", DiagnosticSeverity.Warning, true);

        private static readonly DiagnosticDescriptor LoadFailed = new("OWNE2LOAD", "Owen native core did not load",
            "{0}", "Owen.E2", DiagnosticSeverity.Warning, true);

        public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Finding, LoadFailed);

        [DllImport("owen_e2", CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory)]
        private static extern unsafe IntPtr owen_e2_check(byte* facts, UIntPtr len, byte* output, UIntPtr cap);

        // Variant 2: the shadow copy breaks DllImport's assembly-directory probing, so the
        // project tells the analyzer where the native core is (CompilerVisibleProperty
        // OwenNativeCore) and it is loaded by absolute path through NativeLibrary — which
        // exists only on .NET (Core), so it is reached by reflection from netstandard2.0.
        private delegate IntPtr CheckFn(IntPtr facts, UIntPtr len, IntPtr output, UIntPtr cap);

        private static CheckFn? LoadByPath(string path, out string? error)
        {
            error = null;
            var nl = Type.GetType("System.Runtime.InteropServices.NativeLibrary, System.Runtime.InteropServices", throwOnError: false)
                     ?? Type.GetType("System.Runtime.InteropServices.NativeLibrary", throwOnError: false);
            if (nl is null)
            {
                error = $"no NativeLibrary on this runtime ({RuntimeInformation.FrameworkDescription})";
                return null;
            }
            var load = nl.GetMethod("Load", new[] { typeof(string) });
            var export = nl.GetMethod("GetExport", new[] { typeof(IntPtr), typeof(string) });
            try
            {
                var handle = (IntPtr)load!.Invoke(null, new object[] { path })!;
                var fn = (IntPtr)export!.Invoke(null, new object[] { handle, "owen_e2_check" })!;
                return Marshal.GetDelegateForFunctionPointer<CheckFn>(fn);
            }
            catch (System.Reflection.TargetInvocationException ex)
            {
                error = $"{ex.InnerException?.GetType().Name}: {ex.InnerException?.Message}";
                return null;
            }
        }

        private static readonly Regex Line = new(@"^(?<file>.+?)\((?<line>\d+)\): warning (?<code>\w+): (?<text>.*)$");

        public override void Initialize(AnalysisContext context)
        {
            context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
            context.EnableConcurrentExecution();
            context.RegisterCompilationAction(Run);
        }

        private static unsafe void Run(CompilationAnalysisContext ctx)
        {
            foreach (var file in ctx.Options.AdditionalFiles.Where(f => f.Path.EndsWith(".owen-facts.json", StringComparison.Ordinal)))
            {
                var bytes = Encoding.UTF8.GetBytes(file.GetText(ctx.CancellationToken)?.ToString() ?? "");
                string rendered;
                ctx.Options.AnalyzerConfigOptionsProvider.GlobalOptions.TryGetValue("build_property.OwenNativeCore", out var nativePath);
                if (!string.IsNullOrEmpty(nativePath))
                {
                    var fn = LoadByPath(nativePath!, out var why);
                    if (fn is null)
                    {
                        ctx.ReportDiagnostic(Diagnostic.Create(LoadFailed, Location.None, why ?? "?"));
                        return;
                    }
                    var buffer = new byte[64 * 1024];
                    long got;
                    fixed (byte* f = bytes)
                    fixed (byte* o = buffer)
                        got = (long)fn((IntPtr)f, (UIntPtr)bytes.Length, (IntPtr)o, (UIntPtr)buffer.Length);
                    if (got < 0 || got > buffer.Length)
                    {
                        ctx.ReportDiagnostic(Diagnostic.Create(LoadFailed, Location.None, $"core refused the facts ({got})"));
                        continue;
                    }
                    rendered = Encoding.UTF8.GetString(buffer, 0, (int)got);
                    Report(ctx, rendered);
                    continue;
                }
                try
                {
                    var output = new byte[64 * 1024];
                    long need;
                    fixed (byte* f = bytes)
                    fixed (byte* o = output)
                        need = (long)owen_e2_check(f, (UIntPtr)bytes.Length, o, (UIntPtr)output.Length);
                    if (need < 0 || need > output.Length)
                    {
                        ctx.ReportDiagnostic(Diagnostic.Create(LoadFailed, Location.None, $"core refused the facts ({need})"));
                        continue;
                    }
                    rendered = Encoding.UTF8.GetString(output, 0, (int)need);
                }
                catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException or BadImageFormatException)
                {
                    ctx.ReportDiagnostic(Diagnostic.Create(LoadFailed, Location.None, $"{ex.GetType().Name}: {ex.Message}"));
                    return;
                }
                Report(ctx, rendered);
            }
        }

        private static void Report(CompilationAnalysisContext ctx, string rendered)
        {
            {
                foreach (var raw in rendered.Split('\n'))
                {
                    var m = Line.Match(raw);
                    if (!m.Success)
                        continue;
                    var tree = ctx.Compilation.SyntaxTrees.FirstOrDefault(t => t.FilePath.Replace('\\', '/').EndsWith("/" + m.Groups["file"].Value, StringComparison.Ordinal));
                    var location = Location.None;
                    if (tree is not null)
                    {
                        var line = int.Parse(m.Groups["line"].Value) - 1;
                        var text = tree.GetText(ctx.CancellationToken);
                        if (line >= 0 && line < text.Lines.Count)
                            location = Location.Create(tree, text.Lines[line].Span);
                    }
                    ctx.ReportDiagnostic(Diagnostic.Create(Finding, location, $"{m.Groups["code"].Value}: {m.Groups["text"].Value}"));
                }
            }
        }
    }
}
