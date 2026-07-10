using System.Diagnostics;

namespace OwnSharp.Cli;

/// <summary>
/// `ownsharp check` — extract (bundled Roslyn extractor, in a child process)
/// -> facts.json -> the vendored core (system Python) -> render. Flags mirror
/// scripts/own-check.sh 1:1; the exit-code contract is the same one (own-check
/// comment): 0 clean, 1 findings, &gt;=2 a hard error, plus --fail-on-finding.
/// </summary>
internal static class CheckCommand
{
    private static readonly HashSet<string> ValidFormats = ["human", "github", "msbuild", "sarif"];
    private static readonly HashSet<string> ValidSeverities = ["error", "warning"];

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
                $"ownsharp check: unknown --format '{format}' (choose: {string.Join(", ", ValidFormats)})");
            return 2;
        }
        if (!ValidSeverities.Contains(severity))
        {
            Console.Error.WriteLine(
                $"ownsharp check: unknown --severity '{severity}' (choose: {string.Join(", ", ValidSeverities)})");
            return 2;
        }
        if (paths.Count == 0)
        {
            paths.Add(".");
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
            throw new InvalidOperationException($"ownsharp check: {flag} requires a value");
        }
        return args[++i];
    }

    /// <summary>Stage 1: run the bundled extractor as a child process. All of its
    /// own output (build/run chatter, if any) goes to OUR stderr, keeping
    /// stdout clean for stage 2 — same as own-check.sh's `1>&amp;2` on this stage.</summary>
    private static async Task<int> RunExtractorAsync(
        IReadOnlyList<string> paths, string factsPath, bool legacy, bool stats, bool bodyThrowEdges)
    {
        var extractorDll = Path.Combine(AppContext.BaseDirectory, "ownsharp-extract.dll");
        if (!File.Exists(extractorDll))
        {
            Console.Error.WriteLine(
                $"ownsharp: bundled extractor not found at '{extractorDll}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global OwnSharp.Cli` and reinstall.");
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
            ?? throw new InvalidOperationException("ownsharp: failed to start the extractor process");
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
    /// shim is a native apphost, so that would resolve to ownsharp.exe itself,
    /// not the dotnet muxer.</summary>
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
            ?? throw new InvalidOperationException("ownsharp: failed to start the Python core process");
        await proc.WaitForExitAsync().ConfigureAwait(false);
        return proc.ExitCode;
    }
}
