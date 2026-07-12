using System.Diagnostics;

namespace OwnSharp.Cli;

/// <summary>
/// `owen check` — extract (bundled Roslyn extractor, in a child process)
/// -> facts.json -> the vendored core (system Python) -> render. Flags mirror
/// scripts/own-check.sh 1:1; the exit-code contract is the same one (own-check
/// comment): 0 clean, 1 findings, &gt;=2 a hard error, plus --fail-on-finding.
/// Exit 4 is `owen`'s own: no path resolved to anything the currently
/// included frontend (.NET/C#) can analyze — see <see cref="HasSupportedInput"/>.
/// </summary>
internal static class CheckCommand
{
    private static readonly HashSet<string> ValidFormats = ["human", "github", "msbuild", "sarif"];
    private static readonly HashSet<string> ValidSeverities = ["error", "warning"];

    // The product (Owen) is language-neutral at the OwnIR/core level; this
    // distribution currently wires up only the .NET/C# frontend. Naming the
    // extensions here (instead of e.g. "just try everything and see") is
    // what makes "unsupported input fails explicitly" possible at all -- a
    // silent 0-finding scan on a .ts file or an empty directory would
    // otherwise look identical to a genuinely clean C# scan.
    private static readonly HashSet<string> SupportedExtensions = [".cs", ".csproj", ".sln"];

    public static async Task<int> RunAsync(string[] args)
    {
        string format;
        string severity;
        bool failOnFinding;
        bool legacy;
        bool stats;
        bool bodyThrowEdges;
        string? emitFacts;
        List<string> paths;
        try
        {
            (format, severity, failOnFinding, legacy, stats, bodyThrowEdges, emitFacts, paths) = ParseArgs(args);
        }
        catch (InvalidOperationException ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 2;
        }

        if (!ValidFormats.Contains(format))
        {
            Console.Error.WriteLine(
                $"owen check: unknown --format '{format}' (choose: {string.Join(", ", ValidFormats)})");
            return 2;
        }
        if (!ValidSeverities.Contains(severity))
        {
            Console.Error.WriteLine(
                $"owen check: unknown --severity '{severity}' (choose: {string.Join(", ", ValidSeverities)})");
            return 2;
        }
        if (paths.Count == 0)
        {
            paths.Add(".");
        }

        if (!HasSupportedInput(paths, out var reason))
        {
            Console.Error.WriteLine($"owen check: no supported input found — {reason}");
            Console.Error.WriteLine(
                "Included frontend: .NET / C# (.cs, .csproj, .sln). " +
                "This is not a clean scan: nothing was analyzed.");
            return 4;
        }

        // Resolve Python FIRST: no point extracting facts just to fail on stage 2.
        ResolvedPython python;
        try
        {
            python = PythonResolver.Resolve();
        }
        catch (PythonNotFoundException ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 3;
        }

        var factsPath = Path.GetTempFileName();
        try
        {
            var extractRc = await RunExtractorAsync(paths, factsPath, legacy, stats, bodyThrowEdges)
                .ConfigureAwait(false);
            if (extractRc != 0)
            {
                return extractRc;
            }

            if (emitFacts is not null)
            {
                File.Copy(factsPath, emitFacts, overwrite: true);
            }

            var cacheRoot = CoreVendor.EnsureUnpacked();
            var rc = await RunCoreAsync(python, cacheRoot, factsPath, format, severity).ConfigureAwait(false);

            if (failOnFinding)
            {
                return rc;
            }
            return rc >= 2 ? rc : 0;
        }
        finally
        {
            try { File.Delete(factsPath); } catch (IOException) { /* best-effort cleanup */ }
        }
    }

    private static (string Format, string Severity, bool FailOnFinding, bool Legacy, bool Stats,
        bool BodyThrowEdges, string? EmitFacts, List<string> Paths) ParseArgs(string[] args)
    {
        var format = "human";
        var severity = "error";
        var failOnFinding = false;
        var legacy = false;
        var stats = false;
        var bodyThrowEdges = false;
        string? emitFacts = null;
        var paths = new List<string>();
        var onlyPaths = false; // true after a bare `--`

        for (var i = 0; i < args.Length; i++)
        {
            var a = args[i];
            if (onlyPaths)
            {
                paths.Add(a);
                continue;
            }
            switch (a)
            {
                case "--": onlyPaths = true; break;
                case "--format": format = RequireValue(args, ref i, "--format"); break;
                case "--severity": severity = RequireValue(args, ref i, "--severity"); break;
                case "--emit-facts": emitFacts = RequireValue(args, ref i, "--emit-facts"); break;
                case "--fail-on-finding": failOnFinding = true; break;
                case "--legacy": legacy = true; break;
                case "--stats": stats = true; break;
                case "--body-throw-edges": bodyThrowEdges = true; break;
                default: paths.Add(a); break;
            }
        }

        return (format, severity, failOnFinding, legacy, stats, bodyThrowEdges, emitFacts, paths);
    }

    private static string RequireValue(string[] args, ref int i, string flag)
    {
        if (i + 1 >= args.Length)
        {
            throw new InvalidOperationException($"owen check: {flag} requires a value");
        }
        return args[++i];
    }

    /// <summary>True if at least one of <paramref name="paths"/> resolves to
    /// something the currently included frontend can analyze: a file whose
    /// extension is in <see cref="SupportedExtensions"/>, or a directory that
    /// recursively contains at least one <c>.cs</c> file. A path that doesn't
    /// exist on disk at all is also unsupported (not silently skipped) -- the
    /// point is to never let "nothing to analyze" print as "0 findings,
    /// clean".</summary>
    private static bool HasSupportedInput(IReadOnlyList<string> paths, out string reason)
    {
        var problems = new List<string>();
        foreach (var p in paths)
        {
            if (Directory.Exists(p))
            {
                if (Directory.EnumerateFiles(p, "*.cs", SearchOption.AllDirectories).Any())
                {
                    reason = "";
                    return true;
                }
                problems.Add($"'{p}' is a directory with no .cs files");
            }
            else if (File.Exists(p))
            {
                if (SupportedExtensions.Contains(Path.GetExtension(p)))
                {
                    reason = "";
                    return true;
                }
                problems.Add($"'{p}' has an unsupported extension ({Path.GetExtension(p)})");
            }
            else
            {
                problems.Add($"'{p}' does not exist");
            }
        }
        reason = string.Join("; ", problems);
        return false;
    }

    /// <summary>Stage 1: run the bundled extractor as a child process. All of its
    /// own output (build/run chatter, if any) goes to OUR stderr, keeping
    /// stdout clean for stage 2 — same as own-check.sh's `1>&amp;2` on this stage.</summary>
    private static async Task<int> RunExtractorAsync(
        IReadOnlyList<string> paths, string factsPath, bool legacy, bool stats, bool bodyThrowEdges)
    {
        // "ownsharp-extract.dll" is OwnSharp.Extractor's own real AssemblyName/output
        // filename (internal project name, unchanged by the Owen public facade) —
        // this is the file that actually ships, not a stale reference.
        var extractorDll = Path.Combine(AppContext.BaseDirectory, "ownsharp-extract.dll");
        if (!File.Exists(extractorDll))
        {
            Console.Error.WriteLine(
                $"owen: bundled extractor not found at '{extractorDll}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global Owen.Cli` and reinstall.");
            return 2;
        }

        var psi = new ProcessStartInfo(ResolveDotnetMuxer())
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        psi.ArgumentList.Add("exec");
        psi.ArgumentList.Add(extractorDll);
        foreach (var p in paths)
        {
            psi.ArgumentList.Add(p);
        }
        psi.ArgumentList.Add("-o");
        psi.ArgumentList.Add(factsPath);
        if (!legacy)
        {
            psi.ArgumentList.Add("--flow-locals");
        }
        if (stats)
        {
            psi.ArgumentList.Add("--stats");
        }
        if (bodyThrowEdges)
        {
            psi.ArgumentList.Add("--body-throw-edges");
        }

        using var proc = Process.Start(psi)
            ?? throw new InvalidOperationException("owen: failed to start the extractor process");
        var stdoutTask = proc.StandardOutput.ReadToEndAsync();
        var stderrTask = proc.StandardError.ReadToEndAsync();
        await proc.WaitForExitAsync().ConfigureAwait(false);
        var stdout = await stdoutTask.ConfigureAwait(false);
        var stderr = await stderrTask.ConfigureAwait(false);
        if (stdout.Length > 0) Console.Error.Write(stdout);
        if (stderr.Length > 0) Console.Error.Write(stderr);
        return proc.ExitCode;
    }

    /// <summary>The `dotnet` muxer used to `exec` the bundled extractor dll. A
    /// dotnet *tool* install requires the .NET SDK/runtime already on PATH
    /// (that's how `dotnet tool install` itself runs), so a bare "dotnet" PATH
    /// lookup is the reliable default; DOTNET_ROOT (set by some CI/sandboxed
    /// installs) is honored first when present. Deliberately NOT
    /// Process.GetCurrentProcess().MainModule — on Windows a `dotnet tool`
    /// shim is a native apphost, so that would resolve to owen.exe itself
    /// (the ToolCommandName-based shim), not the dotnet muxer.</summary>
    private static string ResolveDotnetMuxer()
    {
        var root = Environment.GetEnvironmentVariable("DOTNET_ROOT");
        if (!string.IsNullOrEmpty(root))
        {
            var exeName = OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet";
            var candidate = Path.Combine(root, exeName);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        return "dotnet";
    }

    /// <summary>Stage 2: the one checker, run against the vendored core via the
    /// resolved system Python. Findings print to the real stdout/stderr — this
    /// is the surface the user actually asked for.</summary>
    private static async Task<int> RunCoreAsync(
        ResolvedPython python, string cacheRoot, string factsPath, string format, string severity)
    {
        var psi = new ProcessStartInfo(python.FileName)
        {
            UseShellExecute = false,
            WorkingDirectory = cacheRoot,
        };
        foreach (var a in python.LeadingArgs)
        {
            psi.ArgumentList.Add(a);
        }
        psi.ArgumentList.Add("-m");
        psi.ArgumentList.Add("ownlang");
        psi.ArgumentList.Add("ownir");
        psi.ArgumentList.Add(factsPath);
        psi.ArgumentList.Add("--format");
        psi.ArgumentList.Add(format);
        psi.ArgumentList.Add("--severity");
        psi.ArgumentList.Add(severity);
        // Belt-and-suspenders alongside WorkingDirectory: `-m` already adds the
        // cwd to sys.path[0], but own-check.sh/.ps1 both set PYTHONPATH
        // explicitly too, and matching that is cheap insurance.
        psi.EnvironmentVariables["PYTHONPATH"] = cacheRoot;

        using var proc = Process.Start(psi)
            ?? throw new InvalidOperationException("owen: failed to start the Python core process");
        await proc.WaitForExitAsync().ConfigureAwait(false);
        return proc.ExitCode;
    }
}
