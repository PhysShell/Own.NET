using System.Diagnostics;

namespace OwnSharp.Cli;

/// <summary>One engine's observable result: the public streams and the exit
/// code, exactly as the child produced them.
///
/// <para>The streams are RAW BYTES, not decoded text. Compare mode claims the
/// engines' public results are byte-identical, and a claim about bytes cannot
/// be measured on strings: decoding both children through one .NET encoding
/// would silently normalise away a real difference (the Windows A/B/C
/// cp1252-vs-UTF-8 behaviour change is exactly such a case) or invent one from
/// a replacement character. Bytes in, bytes compared, bytes replayed.</para>
///
/// <para>Streams are captured only when the caller asked for capture (compare
/// mode); otherwise they went straight to the real stdout/stderr and the
/// arrays are empty.</para></summary>
/// <param name="Rc">The child's raw exit code, unmapped.</param>
/// <param name="Stdout">Captured stdout bytes, or empty when not capturing.</param>
/// <param name="Stderr">Captured stderr bytes, or empty when not capturing.</param>
internal sealed record EngineOutcome(int Rc, byte[] Stdout, byte[] Stderr);

/// <summary>
/// Runs one analysis engine over one OwnIR facts file.
///
/// <para>Both engines are invoked at the same seam with the same arguments,
/// which is the point: the compare mode below can only be honest if the two
/// runs differ in the engine and in nothing else. The Rust side invokes the
/// PRODUCTION binary `own-cli ownir` — never `own-shadow-engine`, which is
/// #260's dev oracle and is not wired into production by this stage or any
/// other.</para>
/// </summary>
internal static class EngineRunner
{
    /// <summary>Stage 2, the Python reference: the vendored core run by the
    /// resolved system Python. Unchanged from the pre-Stage-1 launcher except
    /// that it can now be asked to capture its streams for compare mode.</summary>
    public static async Task<EngineOutcome> RunPythonAsync(
        ResolvedPython python, string cacheRoot, string factsPath,
        string format, string severity, bool capture)
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

        return await RunAsync(psi, capture, "the Python core").ConfigureAwait(false);
    }

    /// <summary>
    /// Thrown when the resolved candidate could not be STARTED. That is still
    /// the locator's side of D3.1's seam: "bad locator / cannot select the
    /// candidate → rc 2; candidate spawned → a legal engine result is the
    /// normal contract, an unexpected child result → rc 5". A file that exists
    /// but is not a runnable image is a configuration mistake, not Owen
    /// failing internally — and on Windows it is the ONLY way to detect a
    /// non-executable candidate at all, since there is no execute bit to test.
    /// </summary>
    public sealed class RustCoreNotStartedException(string message) : Exception(message);

    /// <summary>
    /// Stage 2, the Rust candidate: the production executable `own-cli ownir`.
    ///
    /// <para>The argument vector mirrors the Python invocation exactly — same
    /// facts path, same <c>--format</c>, same <c>--severity</c> — because
    /// #261 built this binary to reproduce that contract. No engine flag is
    /// passed: `own-cli` presents one engine and knows nothing of Python
    /// (C-4), and Stage 1 does not change that by handing it a selector.</para>
    /// </summary>
    public static async Task<EngineOutcome> RunRustAsync(
        RustCore core, string factsPath, string format, string severity, bool capture)
    {
        var psi = new ProcessStartInfo(core.Path)
        {
            UseShellExecute = false,
        };
        psi.ArgumentList.Add("ownir");
        psi.ArgumentList.Add(factsPath);
        psi.ArgumentList.Add("--format");
        psi.ArgumentList.Add(format);
        psi.ArgumentList.Add("--severity");
        psi.ArgumentList.Add(severity);
        if (CrashReport.Debug)
        {
            psi.EnvironmentVariables["OWNLANG_DEBUG"] = "1";
        }

        try
        {
            return await RunAsync(psi, capture, "the Rust core").ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception
            or IOException or InvalidOperationException or UnauthorizedAccessException)
        {
            // The candidate never started. Windows has no execute bit, so this
            // is where a non-executable candidate is caught there; on Unix the
            // locator's mode check catches it first and this is the backstop.
            throw new RustCoreNotStartedException(
                $"owen check: the candidate `own-cli` binary could not be started: " +
                $"'{core.Path}' ({ex.Message}). Set {RustCoreLocator.EnvVar} to a runnable " +
                $"`own-cli` executable. Owen did not fall back to Python.");
        }
    }

    /// <summary>Start the child and collect its result. Capturing drains both
    /// pipes concurrently AS BYTES (a serial read deadlocks once either pipe
    /// fills, and a decoded read would not answer a byte question); not
    /// capturing leaves the child attached to the real streams so the user
    /// sees the engine's own output live, exactly as before Stage 1.</summary>
    private static async Task<EngineOutcome> RunAsync(
        ProcessStartInfo psi, bool capture, string what)
    {
        psi.RedirectStandardOutput = capture;
        psi.RedirectStandardError = capture;

        using var proc = Process.Start(psi)
            ?? throw new InvalidOperationException($"owen: failed to start {what} process");

        if (!capture)
        {
            await proc.WaitForExitAsync().ConfigureAwait(false);
            return new EngineOutcome(proc.ExitCode, [], []);
        }

        var stdoutTask = DrainAsync(proc.StandardOutput.BaseStream);
        var stderrTask = DrainAsync(proc.StandardError.BaseStream);
        await proc.WaitForExitAsync().ConfigureAwait(false);
        var stdout = await stdoutTask.ConfigureAwait(false);
        var stderr = await stderrTask.ConfigureAwait(false);
        return new EngineOutcome(proc.ExitCode, stdout, stderr);
    }

    /// <summary>Read one redirected pipe to end, undecoded.</summary>
    private static async Task<byte[]> DrainAsync(Stream stream)
    {
        using var buffer = new MemoryStream();
        await stream.CopyToAsync(buffer).ConfigureAwait(false);
        return buffer.ToArray();
    }
}
