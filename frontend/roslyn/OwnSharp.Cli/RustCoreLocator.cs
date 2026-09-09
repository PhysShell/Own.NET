using System.Security.Cryptography;

namespace OwnSharp.Cli;

/// <summary>Thrown when the Stage-1 Rust candidate cannot be resolved. The
/// message is already the full one-line, actionable text; the caller turns it
/// into the ratified exit code and prints nothing of its own.</summary>
internal sealed class RustCoreNotResolvedException(string message) : Exception(message);

/// <summary>The resolved candidate binary and its recorded identity.</summary>
/// <param name="Path">Absolute path to the `own-cli` binary that will run.</param>
/// <param name="Sha256">Lowercase hex SHA-256 of the file that was resolved.</param>
/// <param name="ByteLength">Length in bytes of that same file.</param>
internal sealed record RustCore(string Path, string Sha256, long ByteLength);

/// <summary>
/// D3 — the Stage-1 Rust candidate locator.
///
/// <para><b>The selector and the binary's location are different concepts.</b>
/// <c>--engine</c> says WHICH engine; <c>OWEN_RUST_CORE</c> says WHERE the
/// candidate `own-cli` binary is. The ratified development locator is exactly
/// <c>OWEN_RUST_CORE</c> — an absolute path to the binary — and no alternate
/// spelling remains open.</para>
///
/// <para><b>No discovery of any kind.</b> No PATH lookup, no
/// <c>rust/target/{debug,release}</c> probing, no "first binary found". Those
/// are how a stale binary silently stands in for the one under test, and D3
/// closes that door: the caller says exactly which file to run, or the run
/// fails visibly. Stage 3's packaged resolution is D6's problem, not this
/// one's — do not solve packaging here.</para>
///
/// <para><b>D3.1 — the exit code.</b> For <c>--engine rust|compare</c>, a
/// missing, empty, nonexistent, non-file or non-executable
/// <c>OWEN_RUST_CORE</c>, detected BEFORE the selected Rust core has
/// successfully started, is a launcher configuration/contract error: public
/// exit <b>2</b>, with one actionable diagnostic. It is not 3 (that is
/// Python-specific), not 5 (that is Owen's own internal failure), and it never
/// triggers a Python fallback. Once the candidate has actually spawned, its
/// status is governed by the Rust-child / D4.1 / D5 rules instead — that seam
/// is exactly what the Stage-1 controls mutate.</para>
/// </summary>
internal static class RustCoreLocator
{
    /// <summary>The one ratified Stage-1 development locator (D3). Named once
    /// so no second spelling can quietly appear beside it.</summary>
    public const string EnvVar = "OWEN_RUST_CORE";

    /// <summary>Public exit code for an unusable locator (D3.1). A launcher
    /// configuration error, in the same tier as any other usage mistake.</summary>
    public const int ExitCode = 2;

    /// <summary>Resolve the candidate, or throw with the actionable reason.
    /// Every rejection is a configuration/usage failure, never a fallback.</summary>
    public static RustCore Resolve()
    {
        var raw = Environment.GetEnvironmentVariable(EnvVar);

        if (raw is null)
        {
            throw new RustCoreNotResolvedException(Problem("is not set"));
        }
        if (string.IsNullOrWhiteSpace(raw))
        {
            throw new RustCoreNotResolvedException(Problem("is set but empty"));
        }

        // A directory that exists still fails the File.Exists test below, but
        // saying "is a directory" beats saying "does not exist" about a path
        // the user can see with their own eyes.
        if (Directory.Exists(raw))
        {
            throw new RustCoreNotResolvedException(
                Problem($"points at a directory, not a file: '{raw}'"));
        }
        if (!File.Exists(raw))
        {
            throw new RustCoreNotResolvedException(
                Problem($"points at a path that does not exist: '{raw}'"));
        }
        if (!IsExecutable(raw))
        {
            throw new RustCoreNotResolvedException(
                Problem($"points at a file that is not executable: '{raw}'"));
        }

        string sha;
        long length;
        try
        {
            using var stream = File.OpenRead(raw);
            length = stream.Length;
            sha = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            throw new RustCoreNotResolvedException(
                Problem($"points at a file that cannot be read: '{raw}' ({ex.Message})"));
        }

        return new RustCore(Path.GetFullPath(raw), sha, length);
    }

    /// <summary>One diagnostic shape for every rejection, so the reason varies
    /// and the contract does not.</summary>
    private static string Problem(string what) =>
        $"owen check: --engine rust/compare needs the candidate `own-cli` binary, but " +
        $"{EnvVar} {what}. Set {EnvVar} to the absolute path of the `own-cli` " +
        $"executable to run (Stage 1 does no discovery: no PATH lookup, no " +
        $"rust/target probing). Owen did not fall back to Python — an explicitly " +
        $"selected engine that cannot be started is a configuration error, not a " +
        $"reason to run something else.";

    /// <summary>
    /// Is this file runnable as a program?
    ///
    /// <para>On Unix that is a real permission question, so it is asked of the
    /// file mode: any of the three execute bits. On Windows there is no
    /// execute bit — runnability is decided by the loader — so an existing
    /// regular file is accepted and a genuinely broken image fails later, at
    /// spawn, which is the D3.1 seam's other side and already maps to the
    /// internal-error path.</para>
    /// </summary>
    private static bool IsExecutable(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            return true;
        }
        try
        {
            var mode = File.GetUnixFileMode(path);
            return (mode & (UnixFileMode.UserExecute
                          | UnixFileMode.GroupExecute
                          | UnixFileMode.OtherExecute)) != 0;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException
            or PlatformNotSupportedException)
        {
            // Cannot read the mode: refuse rather than assume runnable. A
            // false "yes" here would turn a configuration error into a spawn
            // failure reported as an internal error, which loses D3.1's
            // distinction between "could not select" and "ran and misbehaved".
            return false;
        }
    }
}
