using System.Runtime.InteropServices;
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
/// fails visibly.</para>
///
/// <para><b>D6 — packaged resolution (#262 Stage 3).</b> Stage 1 left this
/// deliberately unsolved, and it had to be solved before the default could
/// move: with Rust as the default, a user who sets nothing must still get a
/// working engine, and <c>OWEN_RUST_CORE</c> is a DEVELOPMENT locator that no
/// user will ever set. So when — and only when — the variable is absent, the
/// candidate is the one this install SHIPS, at a fixed path inside the tool's
/// own payload:
/// <c>{AppContext.BaseDirectory}/rust-core/{rid}/own-cli[.exe]</c>.</para>
///
/// <para>That is packaged resolution, and it is NOT discovery, which is a
/// distinction worth being exact about because the whole of D3 turns on it.
/// Discovery asks the machine where a binary might be and takes what it finds:
/// the answer depends on PATH, on the working directory, on what else is
/// installed, and "which binary ran" stops being a property of the
/// configuration. This asks nothing. There is exactly one path, it is computed
/// from the running assembly's own location and this platform's identifier,
/// the file is either there or it is not, and if it is not the run fails
/// visibly. A second candidate can never win, because there is never a second
/// candidate.</para>
///
/// <para><b>Precedence, and why this way round.</b> An explicitly set
/// <c>OWEN_RUST_CORE</c> always wins, with Stage 1's semantics and Stage 1's
/// diagnostics unchanged — the packaged path is consulted only when the
/// variable is absent entirely. A developer measuring a specific build must
/// not have the shipped binary silently substituted for it, and an empty or
/// malformed variable stays the error it was rather than becoming a fall
/// through to something else. Setting the variable is still a statement about
/// WHICH binary to run, and it is still honoured to the letter.</para>
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
            // D6. Absent — not empty, not malformed — means "use what this
            // install ships".
            return ResolvePackaged();
        }
        if (string.IsNullOrWhiteSpace(raw))
        {
            throw new RustCoreNotResolvedException(Problem("is set but empty"));
        }

        // A directory that exists still fails the File.Exists test below, but
        // saying "is a directory" beats saying "does not exist" about a path
        // the user can see with their own eyes.
        // D3 says an ABSOLUTE path, and this is where that stops being a
        // description and becomes a check. A relative locator that happens to
        // exist resolves against the current working directory — which is
        // precisely the ambient, cwd-dependent resolution D3 forbids: the same
        // OWEN_RUST_CORE would select different binaries from different
        // directories, and "which binary ran" would stop being a property of
        // the configuration. Rejected before any existence test, so the
        // diagnostic names the real problem rather than reporting on whatever
        // the relative path happened to hit.
        if (!Path.IsPathFullyQualified(raw))
        {
            throw new RustCoreNotResolvedException(
                Problem($"is not an absolute path: '{raw}'. Stage 1 resolves the candidate " +
                        "from this variable alone, so a path relative to the current directory " +
                        "would select a different binary depending on where Owen was run"));
        }

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

    /// <summary>
    /// The platform identifier the payload is keyed by.
    ///
    /// <para>Composed here rather than read from
    /// <c>RuntimeInformation.RuntimeIdentifier</c> on purpose: that property
    /// can answer with a distribution-specific RID
    /// (<c>ubuntu.22.04-x64</c>) or a libc-specific one
    /// (<c>linux-musl-x64</c>) depending on how the runtime was built, and a
    /// lookup keyed by it would miss a payload directory that is present and
    /// correct. What this needs is not the runtime's best description of the
    /// host, it is the name the PACK step used — so both sides compute it the
    /// same short way, and the set of names stays exactly the set of platforms
    /// the release actually builds for.</para>
    /// </summary>
    public static string PlatformKey()
    {
        var os = OperatingSystem.IsWindows() ? "win"
            : OperatingSystem.IsMacOS() ? "osx"
            : OperatingSystem.IsLinux() ? "linux"
            : "unknown";
        var arch = RuntimeInformation.ProcessArchitecture switch
        {
            Architecture.X64 => "x64",
            Architecture.Arm64 => "arm64",
            Architecture.X86 => "x86",
            _ => "unknown",
        };
        return $"{os}-{arch}";
    }

    /// <summary>The file name the candidate has on this platform.</summary>
    public static string BinaryName() => OperatingSystem.IsWindows() ? "own-cli.exe" : "own-cli";

    /// <summary>Where this install's own candidate lives, if it carries one.
    /// One path, computed, never searched for.</summary>
    public static string PackagedPath() =>
        Path.Combine(AppContext.BaseDirectory, "rust-core", PlatformKey(), BinaryName());

    /// <summary>
    /// D6: resolve the candidate this install ships.
    ///
    /// <para><b>The execute bit.</b> A NuGet package is a zip, and the file
    /// modes inside one do not survive the round trip on Unix: a payload file
    /// arrives mode 644 and cannot be spawned, however correct its contents
    /// are. So a packaged candidate that is not executable where it lies is
    /// materialised into a content-addressed cache and made executable there —
    /// the same shape <see cref="CoreVendor"/> already uses for the vendored
    /// Python core, and for the same two reasons: the install directory may be
    /// read-only or shared, and keying the cache by the file's own SHA-256
    /// means a different binary is a different path rather than an overwrite
    /// of one a concurrent reader might be running.</para>
    ///
    /// <para>On Windows there is no execute bit, so the file is used exactly
    /// where it was installed and nothing is copied.</para>
    /// </summary>
    private static RustCore ResolvePackaged()
    {
        var packaged = PackagedPath();
        if (!File.Exists(packaged))
        {
            throw new RustCoreNotResolvedException(
                $"owen check: the Rust engine is Owen's default, but this install carries no " +
                $"`own-cli` binary for {PlatformKey()} — expected it at '{packaged}'. That is a " +
                $"packaging/production error, not something to work around: a release package " +
                $"carries the candidate for every supported platform. To run a specific build " +
                $"instead, set {EnvVar} to its absolute path (there is no discovery: no PATH " +
                $"lookup, no rust/target probing). To fall back to the Python reference engine " +
                $"for this run, pass `--engine python`. Owen did not fall back to Python on its " +
                $"own — an engine that cannot be started is a configuration error, not a reason " +
                $"to run something else.");
        }

        string sha;
        long length;
        try
        {
            using var stream = File.OpenRead(packaged);
            length = stream.Length;
            sha = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            throw new RustCoreNotResolvedException(
                $"owen check: this install's `own-cli` binary at '{packaged}' cannot be read " +
                $"({ex.Message}) — a corrupt or incomplete install. Owen did not fall back to " +
                $"Python. Reinstall, or set {EnvVar} to an absolute path, or pass " +
                $"`--engine python` to select the reference engine explicitly.");
        }

        if (IsExecutable(packaged))
        {
            return new RustCore(packaged, sha, length);
        }
        return new RustCore(Materialize(packaged, sha), sha, length);
    }

    /// <summary>
    /// Copy the packaged candidate to <c>~/.owen/rust-core/&lt;sha256&gt;/</c>
    /// and make it executable.
    ///
    /// <para>Published atomically — written to a temp sibling and moved into
    /// place once complete — so a reader never observes a half-copied binary,
    /// and a hit is verified by SIZE and CONTENT HASH rather than by the path's
    /// name, because a path name is a claim and this one is about a file that
    /// is going to be executed.</para>
    /// </summary>
    private static string Materialize(string packaged, string sha)
    {
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var finalDir = Path.Combine(userProfile, ".owen", "rust-core", sha);
        var final = Path.Combine(finalDir, BinaryName());

        if (File.Exists(final) && Verified(final, sha))
        {
            return final;
        }

        try
        {
            Directory.CreateDirectory(finalDir);
            var temp = Path.Combine(
                finalDir, $".{BinaryName()}.{Environment.ProcessId}.{Guid.NewGuid():N}.tmp");
            File.Copy(packaged, temp, overwrite: true);
            MakeExecutable(temp);
            if (!Verified(temp, sha))
            {
                File.Delete(temp);
                throw new RustCoreNotResolvedException(
                    $"owen check: internal error — the copy of `own-cli` at '{temp}' does not " +
                    $"match the packaged binary it was copied from. Owen did not fall back to " +
                    $"Python; pass `--engine python` to select the reference engine explicitly.");
            }
            try
            {
                File.Move(temp, final, overwrite: true);
            }
            catch (IOException)
            {
                // Another process published the same content first. That is the
                // race working, not failing: the destination is content-keyed,
                // so whatever is there is the same bytes. Verify and use it.
                File.Delete(temp);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException
            or NotSupportedException or ArgumentException)
        {
            throw new RustCoreNotResolvedException(
                $"owen check: this install's `own-cli` binary is not executable where it was " +
                $"installed ('{packaged}') and could not be prepared at '{finalDir}' " +
                $"({ex.Message}). Owen did not fall back to Python. Set {EnvVar} to an " +
                $"absolute path to a runnable `own-cli`, or pass `--engine python` to select " +
                $"the reference engine explicitly.");
        }

        if (!File.Exists(final) || !Verified(final, sha) || !IsExecutable(final))
        {
            throw new RustCoreNotResolvedException(
                $"owen check: could not prepare a runnable `own-cli` at '{final}' from this " +
                $"install's packaged binary. Owen did not fall back to Python. Set {EnvVar} to " +
                $"an absolute path to a runnable `own-cli`, or pass `--engine python` to select " +
                $"the reference engine explicitly.");
        }
        return final;
    }

    /// <summary>Is the file at <paramref name="path"/> exactly the bytes
    /// <paramref name="sha"/> names? Recomputed, never inferred from a
    /// path.</summary>
    private static bool Verified(string path, string sha)
    {
        try
        {
            using var stream = File.OpenRead(path);
            return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant() == sha;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    /// <summary>Add the execute bits on Unix. A no-op on Windows, where
    /// runnability is the loader's question and not a file mode.</summary>
    private static void MakeExecutable(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        File.SetUnixFileMode(
            path,
            File.GetUnixFileMode(path)
            | UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute);
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
    /// regular file is accepted here and a genuinely broken image is refused
    /// later, at spawn.</para>
    ///
    /// <para>That later refusal is still D3.1's CONFIGURATION side, not the
    /// internal-error path: EngineRunner raises RustCoreNotStartedException
    /// and CheckCommand maps it to this class's ExitCode. A candidate that
    /// never started never ran, so it cannot have misbehaved, and 5 would
    /// blame Owen for the caller's setting.</para>
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
            // Cannot read the mode: refuse rather than assume runnable. Both
            // answers reach the same exit code — a spawn failure is ExitCode
            // too — so what a false "yes" costs is the DIAGNOSTIC and the
            // moment it arrives: the caller is told the candidate "could not
            // be started" instead of that it is not executable, after Owen has
            // already paid for a full extraction. The preflight exists to say
            // the true thing before doing the expensive thing.
            return false;
        }
    }
}
