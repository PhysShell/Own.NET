using System.Text.Json;

namespace OwnSharp.Cli;

/// <summary>
/// The first-run failure contract (alpha gate A1): an internal error must
/// never surface as a raw stack trace, a runtime-chosen exit code, or —
/// worst — a clean scan. Every internal failure exits <see cref="ExitCode"/>
/// (5) with one short, actionable message and a deterministic diagnostic
/// report at <c>~/.owen/diag/last-failure.json</c>.
///
/// The report contains tool/OS/runtime identity, the command line, the
/// failure stage and the technical cause. It deliberately contains NO source
/// file contents — facts/source sharing stays an explicit user action
/// (`--emit-facts`). Debug mode (`--debug` or OWEN_DEBUG=1) prints the full
/// .NET trace to stderr — it changes the VOLUME of diagnostics, never the
/// machine semantics: the exit code is 5 in both modes (a re-throw would
/// exit with a runtime-chosen, platform-dependent code and break the
/// published contract).
/// </summary>
internal static class CrashReport
{
    /// <summary>Exit code for "owen (or a stage it drives) hit a bug" —
    /// distinct from usage (2), no Python (3), and no input (4), and never
    /// collapsible into findings (1) or clean (0).</summary>
    public const int ExitCode = 5;

    /// <summary>Set by `owen check --debug`; OWEN_DEBUG=1 is the env twin.</summary>
    public static bool DebugFlag { get; set; }

    public static bool Debug =>
        DebugFlag || Environment.GetEnvironmentVariable("OWEN_DEBUG") == "1";

    private const string ReportIssueUrl =
        "https://github.com/PhysShell/Own.NET/issues/new/choose";

    /// <summary>Handle an uncaught exception at the top level: polite
    /// message + report, exit 5. Debug mode additionally prints the full
    /// exception (type, message, stack) — the exit code stays 5.</summary>
    public static int Handle(Exception ex, string[] args)
    {
        if (Debug)
        {
            Console.Error.WriteLine(ex);
        }
        var report = TryWrite(args, stage: "owen",
            cause: $"{ex.GetType().FullName}: {ex.Message}",
            detail: ex.ToString(), childOutput: null);
        Console.Error.WriteLine($"owen: internal error ({ex.GetType().Name}: {ex.Message})");
        Emit(report);
        return ExitCode;
    }

    /// <summary>Frame a child stage's crash (unexpected exit code) without
    /// dumping its raw output on the user; the full capture goes into the
    /// report instead. In debug mode the caller prints the raw output.</summary>
    public static int Child(string stage, int rc, string[] args, string capturedOutput)
    {
        var report = TryWrite(args, stage,
            cause: $"{stage} exited with unexpected code {rc}",
            detail: null, childOutput: capturedOutput);
        Console.Error.WriteLine(
            $"owen: the {stage} stage failed internally (exit {rc}).");
        Emit(report);
        return ExitCode;
    }

    private static void Emit(string? reportPath)
    {
        Console.Error.WriteLine(
            "  This is a bug in owen, not in your code. Re-run with --debug " +
            "(or OWEN_DEBUG=1) for the full technical cause.");
        if (reportPath is not null)
        {
            Console.Error.WriteLine(
                $"  Diagnostic report (no source contents collected): {reportPath}");
        }
        Console.Error.WriteLine($"  Please report it: {ReportIssueUrl}");
    }

    /// <summary>One deterministic JSON report, overwritten in place (a single
    /// well-known path beats an ever-growing directory). Best-effort: a
    /// failure to write the report must never mask the original failure.</summary>
    private static string? TryWrite(
        string[] args, string stage, string cause, string? detail, string? childOutput)
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".owen", "diag");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "last-failure.json");
            var report = new
            {
                schema = 1,
                tool = "owen",
                version = ToolVersion.Current,
                timestamp_utc = DateTime.UtcNow.ToString("o"),
                os = Environment.OSVersion.ToString(),
                runtime = Environment.Version.ToString(),
                command = "check",
                args,
                stage,
                cause,
                detail,
                child_output = childOutput,
            };
            File.WriteAllText(path, JsonSerializer.Serialize(
                report, new JsonSerializerOptions { WriteIndented = true }));
            return path;
        }
        catch (Exception)
        {
            return null;
        }
    }
}
