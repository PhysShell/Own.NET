using System.Diagnostics;

namespace OwnSharp.Cli;

/// <summary>
/// `owen check` — extract (bundled Roslyn extractor, in a child process)
/// -> facts.json -> the vendored core (system Python) -> render. Flags mirror
/// scripts/own-check.sh 1:1; the exit-code contract is the same one (own-check
/// comment): 0 clean, 1 findings, &gt;=2 a hard error, plus --fail-on-finding.
/// Exit 4 means no analyzable input: either this preflight's cheap check
/// rejects every path outright (<see cref="HasSupportedInput"/>), or every
/// path existed but the EXTRACTOR's own expansion (which alone knows its
/// skip rules — bin/obj, generated, vendor trees) found nothing after
/// filtering, in which case the extractor itself returns 4 and this command
/// simply propagates it (review, PR #246: the CLI must not duplicate the
/// extractor's expansion/skip rules to guess that outcome itself).
/// </summary>
internal static class CheckCommand
{
    private static readonly HashSet<string> ValidFormats = ["human", "github", "msbuild", "sarif"];
    private static readonly HashSet<string> ValidSeverities = ["error", "warning"];

    // The product (Owen) is language-neutral at the OwnIR/core level; this
    // distribution currently wires up only the .NET/C# frontend. Naming the
    // extensions here (instead of e.g. "just try everything and see") is
    // what makes the CHEAP half of "unsupported input fails explicitly"
    // possible: an obviously-wrong bare file (.ts, no extension at all,
    // nonexistent path) is rejected here without spinning up the extractor
    // at all. Case-insensitive (review, PR #246): Windows/macOS filesystems
    // commonly are, and MSBuild itself treats `Foo.CS`/`App.CSPROJ` as the
    // same file kinds as their lowercase spellings.
    private static readonly HashSet<string> SupportedExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".cs", ".csproj", ".sln" };

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
            var (extractRc, extractOutput) =
                await RunExtractorAsync(paths, factsPath, legacy, stats, bodyThrowEdges)
                    .ConfigureAwait(false);
            // The extractor's own contract is 0 / 2 (usage) / 4 (nothing to
            // analyze after expansion) — those pass through with its output.
            // Anything else is a crash (an unhandled exception's runtime
            // code): frame it politely and keep the raw trace in the
            // diagnostic report (or on stderr in --debug mode) — A1.
            if (extractRc is 2 or 4)
            {
                Console.Error.Write(extractOutput);
                return extractRc;
            }
            if (extractRc != 0)
            {
                if (CrashReport.Debug)
                {
                    Console.Error.Write(extractOutput);
                }
                return CrashReport.Child("extractor", extractRc, args, extractOutput);
            }
            Console.Error.Write(extractOutput);

            if (emitFacts is not null)
            {
                try
                {
                    File.Copy(factsPath, emitFacts, overwrite: true);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException
                    or ArgumentException or NotSupportedException or DirectoryNotFoundException)
                {
                    Console.Error.WriteLine(
                        $"owen check: cannot write --emit-facts '{emitFacts}': {ex.Message}");
                    return 2;
                }
            }

            var cacheRoot = CoreVendor.EnsureUnpacked();
            var rc = await RunCoreAsync(python, cacheRoot, factsPath, format, severity).ConfigureAwait(false);
            // The core self-reports internal errors as exit 70 (EX_SOFTWARE)
            // with one polite line (ownlang `run()`): surface them as OUR
            // internal error — pre-A1 a core crash exited 1 and, without
            // --fail-on-finding, was silently mapped to a CLEAN scan.
            if (rc == 70)
            {
                Console.Error.WriteLine(
                    "owen: the analysis core failed internally — the line above has the " +
                    "short cause. This is a bug in owen, not in your code.");
                Console.Error.WriteLine(
                    "  Re-run with --debug (or OWEN_DEBUG=1) for the full traceback, and " +
                    "please report it: https://github.com/PhysShell/Own.NET/issues/new/choose");
                return CrashReport.ExitCode;
            }

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
                case "--debug": CrashReport.DebugFlag = true; break;
                default:
                    // A mistyped flag must be a usage error, not a phantom
                    // path: pre-A1 `owen check --verbose .` fell through to
                    // "path '--verbose' does not exist" (exit 4), which reads
                    // as an input problem instead of the actual typo.
                    if (a.StartsWith('-'))
                    {
                        throw new InvalidOperationException(
                            $"owen check: unknown option '{a}' (see `owen --help`; " +
                            "put `--` before paths that begin with '-')");
                    }
                    paths.Add(a);
                    break;
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

    /// <summary>True if at least one of <paramref name="paths"/> is CHEAPLY,
    /// OBVIOUSLY plausible input for the currently included frontend: an
    /// existing file whose extension is in <see cref="SupportedExtensions"/>,
    /// or an existing directory. Deliberately NOT a full expansion — a
    /// directory is accepted here even if every <c>.cs</c> file under it
    /// turns out to be skipped (bin/obj, generated, vendor) once the
    /// extractor actually walks it; duplicating that skip-list in the CLI
    /// would drift from the extractor's real rules (review, PR #246). The
    /// extractor itself is the sole authority on "found nothing after
    /// expansion" and returns exit 4 for that case (Program.cs) — this
    /// preflight only catches the cheaper "obviously not C# at all" case
    /// (nonexistent path, or a bare file with the wrong extension) without
    /// paying for an extractor invocation.</summary>
    private static bool HasSupportedInput(IReadOnlyList<string> paths, out string reason)
    {
        var problems = new List<string>();
        foreach (var p in paths)
        {
            if (Directory.Exists(p))
            {
                reason = "";
                return true;
            }
            if (File.Exists(p))
            {
                if (SupportedExtensions.Contains(Path.GetExtension(p)))
                {
                    reason = "";
                    return true;
                }
                problems.Add($"'{p}' has an unsupported extension ({Path.GetExtension(p)})");
                continue;
            }
            problems.Add($"'{p}' does not exist");
        }
        reason = string.Join("; ", problems);
        return false;
    }

    /// <summary>Stage 1: run the bundled extractor as a child process. Its
    /// output (build/run chatter, warnings — and, on a crash, the raw trace)
    /// is CAPTURED and returned; the caller decides what reaches OUR stderr
    /// (everything for the contract codes, report-only for a crash — A1),
    /// keeping stdout clean for stage 2 like own-check.sh's `1>&amp;2`.</summary>
    private static async Task<(int Rc, string Output)> RunExtractorAsync(
        IReadOnlyList<string> paths, string factsPath, bool legacy, bool stats, bool bodyThrowEdges)
    {
        // "ownsharp-extract.dll" is OwnSharp.Extractor's own real AssemblyName/output
        // filename (internal project name, unchanged by the Owen public facade) —
        // this is the file that actually ships, not a stale reference.
        var extractorDll = Path.Combine(AppContext.BaseDirectory, "ownsharp-extract.dll");
        if (!File.Exists(extractorDll))
        {
            return (2,
                $"owen: bundled extractor not found at '{extractorDll}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global Owen.Cli` " +
                "and reinstall." + Environment.NewLine);
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
        return (proc.ExitCode, stdout + stderr);
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
        // Debug passthrough (A1): the core's catch-all (`ownlang.run`) prints
        // one polite line and exits 70; with OWNLANG_DEBUG=1 it re-raises the
        // full traceback instead — that is what `owen check --debug` asks for.
        if (CrashReport.Debug)
        {
            psi.EnvironmentVariables["OWNLANG_DEBUG"] = "1";
        }

        using var proc = Process.Start(psi)
            ?? throw new InvalidOperationException("owen: failed to start the Python core process");
        await proc.WaitForExitAsync().ConfigureAwait(false);
        return proc.ExitCode;
    }
}
