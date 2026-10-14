using System.Text;

namespace OwnSharp.Cli;

/// <summary>
/// `owen build-check --request &lt;file&gt;` — the generic Owen build host (OX-01,
/// spec/OwenExtension.md). Called by the `Owen.Build` package's MSBuild targets after a project
/// has been built; not meant to be typed.
///
/// <para>It is <c>owen check</c> with three additions, none of them analysis:</para>
/// <list type="number">
/// <item>it validates the <b>extension descriptors</b> the project's packages declare against
/// what this host supports, and fails loud on anything it does not understand;</item>
/// <item>it hands the C# that those extensions' generators wrote to the extractor explicitly,
/// beside the project (the extractor's own expansion skips generated files, and an
/// extension's protocol lives in generated code);</item>
/// <item>it speaks MSBuild: every failure is ONE canonical line (<c>origin: error OWENBnnn:
/// text</c>, with <c>file(line)</c> wherever there is one), so the build fails on it and the
/// Error List can navigate to it.</item>
/// </list>
///
/// <para>The findings themselves are the Rust core's, rendered by the core
/// (<c>--format msbuild</c>) and passed through byte for byte. This host renders nothing of
/// its own and knows no extension by name.</para>
///
/// <para>The host contract itself (descriptors, the input set, refusals) is
/// <see cref="OwenHost"/>, shared with the live IDE service (<c>owen serve</c>).</para>
///
/// <para>Exit: 0 analysed (findings shown as warnings, or none); 1 analysed, findings shown as
/// errors; 2 a host / contract / refusal error, already printed as an OWENB line.</para>
/// </summary>
internal static class BuildCheckCommand
{
    public static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2 || args[0] != "--request")
        {
            Console.Error.WriteLine("usage: owen build-check --request <file>   (written by the Owen.Build targets)");
            return 2;
        }

        Dictionary<string, List<string>> request;
        try
        {
            request = OwenHost.ReadRequest(args[1]);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Console.WriteLine($"owen: error OWENB012: cannot read the build request '{args[1]}': {ex.Message}");
            return 2;
        }

        var project = OwenHost.One(request, "project");
        var severity = OwenHost.One(request, "severity") ?? "warning";
        var manifest = OwenHost.One(request, "manifest");
        var generatedRoot = OwenHost.One(request, "generated-root");
        var emitFacts = OwenHost.One(request, "emit-facts");
        if (project is null || manifest is null)
        {
            Console.WriteLine("owen: error OWENB012: the build request names no project or no manifest path");
            return 2;
        }
        if (severity is not ("warning" or "error"))
        {
            Console.WriteLine($"{project}: error OWENB002: OwenSeverity must be 'warning' or 'error', not '{severity}'");
            return 2;
        }

        // ---- 1. the extensions --------------------------------------------------------------
        var paths = request.TryGetValue("descriptor", out var given) ? given : [];
        if (paths.Count == 0)
        {
            Console.WriteLine($"{project}: warning OWENB001: Owen.Build is referenced but no Owen extension is active; nothing was analysed");
            OwenHost.WriteManifest(manifest, []);
            return 0;
        }
        var errors = new List<HostDiagnostic>();
        var descriptors = OwenHost.Validate(paths, errors);
        foreach (var e in errors)
            Console.WriteLine(e.ToMsBuild());
        if (descriptors is null)
            return 2;
        OwenHost.WriteManifest(manifest, descriptors);
        Console.WriteLine("Owen: active extensions: " + string.Join(", ", descriptors.Select(d => $"{d.Id} {d.Version}")));

        // ---- 2. the inputs ------------------------------------------------------------------
        var inputs = OwenHost.Inputs(project, generatedRoot, descriptors);

        // ---- 3. the engine ------------------------------------------------------------------
        RustCore core;
        try
        {
            core = RustCoreLocator.Resolve();
        }
        catch (RustCoreNotResolvedException ex)
        {
            Console.WriteLine($"{project}: error OWENB005: {OwenHost.OneLine(ex.Message)}");
            return 2;
        }

        var factsPath = Path.GetTempFileName();
        try
        {
            var (extractRc, extractOutput) = await CheckCommand
                .RunExtractorAsync(inputs, factsPath, legacy: false, stats: false, bodyThrowEdges: false)
                .ConfigureAwait(false);
            if (extractRc == 2)
            {
                foreach (var d in OwenHost.Refusals(extractOutput, project, "OWENB010", OwenHost.ExtractorRefusal))
                    Console.WriteLine(d.ToMsBuild());
                return 2;
            }
            if (extractRc != 0)
            {
                Console.WriteLine($"{project}: error OWENB012: the extractor exited {extractRc}: {OwenHost.OneLine(extractOutput)}");
                return 2;
            }
            if (emitFacts is not null)
                File.Copy(factsPath, emitFacts, overwrite: true);

            EngineOutcome outcome;
            try
            {
                outcome = await EngineRunner.RunRustAsync(core, factsPath, "msbuild", severity, capture: true)
                    .ConfigureAwait(false);
            }
            catch (EngineRunner.RustCoreNotStartedException ex)
            {
                Console.WriteLine($"{project}: error OWENB005: {OwenHost.OneLine(ex.Message)}");
                return 2;
            }
            var stdout = Encoding.UTF8.GetString(outcome.Stdout);
            var stderr = Encoding.UTF8.GetString(outcome.Stderr);
            switch (outcome.Rc)
            {
                case 0 or 1:
                    // the core's own canonical lines, unchanged but for the origin path: the
                    // core names files relative to the project directory (the extractor ran
                    // there), and the Error List must not have to guess the base
                    Console.Write(OwenHost.Absolute(stdout, project));
                    Console.Write(OwenHost.Absolute(stderr, project));
                    return outcome.Rc == 1 && severity == "error" ? 1 : 0;
                case 2:
                    foreach (var d in OwenHost.Refusals(stderr + stdout, project, "OWENB011", OwenHost.CoreRefusal))
                        Console.WriteLine(d.ToMsBuild());
                    return 2;
                default:
                    Console.WriteLine($"{project}: error OWENB012: the Rust core exited {outcome.Rc}, which is not a verdict: {OwenHost.OneLine(stderr)}");
                    return 2;
            }
        }
        finally
        {
            try { File.Delete(factsPath); } catch (IOException) { /* best-effort */ }
        }
    }
}
