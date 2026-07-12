using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

namespace OwnSharp.Cli;

/// <summary>Thrown when no usable Python (&gt;=3.11) can be resolved. The message
/// is already the full one-line, actionable, install-and-retry text.</summary>
internal sealed class PythonNotFoundException(string message) : Exception(message);

/// <summary>A resolved, launchable Python interpreter (exe + any fixed leading
/// args, e.g. "py" + "-3").</summary>
internal sealed record ResolvedPython(string FileName, IReadOnlyList<string> LeadingArgs);

/// <summary>
/// Resolution order (design decision, issue #202; env var renamed for the
/// Owen public facade, see docs/notes/owen-public-facade.md):
/// <c>OWEN_PYTHON</c> env var (used exactly as given, no fallback if it
/// doesn't work — an explicit override that fails is a configuration error,
/// not a "keep guessing" case); else the legacy <c>OWN_PYTHON</c> name (a
/// temporary compatibility fallback so existing internal use doesn't break —
/// prints a deprecation note to stderr whenever it's the one actually used);
/// else the platform default (<c>py -3</c> on Windows, <c>python3</c>
/// elsewhere). No auto-download, ever: a miss is a fast, actionable failure.
/// </summary>
internal static class PythonResolver
{
    private const int MinMajor = 3;
    private const int MinMinor = 11;

    public static ResolvedPython Resolve()
    {
        var owenPython = Environment.GetEnvironmentVariable("OWEN_PYTHON");
        if (!string.IsNullOrWhiteSpace(owenPython))
        {
            var candidate = new ResolvedPython(owenPython, Array.Empty<string>());
            if (TryGetVersion(candidate, out var version) && IsSupported(version))
            {
                return candidate;
            }
            throw new PythonNotFoundException(
                $"owen: OWEN_PYTHON='{owenPython}' did not resolve to Python >={MinMajor}.{MinMinor} " +
                $"(found: {version ?? "not runnable"}). {InstallHint()}");
        }

        // Legacy fallback (temporary): OWN_PYTHON predates the Owen public
        // facade and some existing/internal use still sets it. Honored so
        // that doesn't silently break, but flagged every time it's the
        // variable actually used, so it doesn't quietly become permanent.
        var legacyOwnPython = Environment.GetEnvironmentVariable("OWN_PYTHON");
        if (!string.IsNullOrWhiteSpace(legacyOwnPython))
        {
            var candidate = new ResolvedPython(legacyOwnPython, Array.Empty<string>());
            if (TryGetVersion(candidate, out var version) && IsSupported(version))
            {
                Console.Error.WriteLine(
                    "owen: OWN_PYTHON is deprecated — set OWEN_PYTHON instead (OWN_PYTHON is a " +
                    "temporary compatibility fallback and may be removed in a future release).");
                return candidate;
            }
            throw new PythonNotFoundException(
                $"owen: OWN_PYTHON='{legacyOwnPython}' did not resolve to Python >={MinMajor}.{MinMinor} " +
                $"(found: {version ?? "not runnable"}). {InstallHint()} (OWN_PYTHON is deprecated — use OWEN_PYTHON.)");
        }

        var defaultCandidate = RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
            ? new ResolvedPython("py", ["-3"])
            : new ResolvedPython("python3", Array.Empty<string>());

        if (TryGetVersion(defaultCandidate, out var defaultVersion) && IsSupported(defaultVersion))
        {
            return defaultCandidate;
        }

        // A real-world fallback beyond the two names in the design decision: some
        // Windows machines have `python` on PATH but no `py` launcher, and some
        // Unix setups only ship `python` (already >=3 on any current OS). Trying
        // these does not weaken the contract (still >=3.11-or-fail, never an
        // auto-install), it just avoids a false negative on an otherwise-fine
        // machine.
        foreach (var name in new[] { "python3", "python" })
        {
            var fallback = new ResolvedPython(name, Array.Empty<string>());
            if (TryGetVersion(fallback, out var version) && IsSupported(version))
            {
                return fallback;
            }
        }

        throw new PythonNotFoundException(
            $"owen: no Python >={MinMajor}.{MinMinor} found on PATH. {InstallHint()} " +
            "(or set OWEN_PYTHON to an interpreter's path).");
    }

    private static bool IsSupported(string? version)
    {
        if (version is null)
        {
            return false;
        }
        var m = Regex.Match(version, @"(\d+)\.(\d+)");
        return m.Success
            && int.Parse(m.Groups[1].Value) == MinMajor
            && int.Parse(m.Groups[2].Value) >= MinMinor;
    }

    private static bool TryGetVersion(ResolvedPython candidate, out string? version)
    {
        version = null;
        try
        {
            var psi = new ProcessStartInfo(candidate.FileName)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            foreach (var a in candidate.LeadingArgs)
            {
                psi.ArgumentList.Add(a);
            }
            psi.ArgumentList.Add("--version");
            using var proc = Process.Start(psi);
            if (proc is null)
            {
                return false;
            }
            // Python printed --version to stdout since 3.4; stderr covers older
            // (never a real target here, but costs nothing to also read).
            var stdout = proc.StandardOutput.ReadToEnd();
            var stderr = proc.StandardError.ReadToEnd();
            proc.WaitForExit();
            if (proc.ExitCode != 0)
            {
                return false;
            }
            version = string.IsNullOrWhiteSpace(stdout) ? stderr : stdout;
            return true;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            return false; // the executable itself was not found
        }
        catch (IOException)
        {
            return false;
        }
    }

    private static string InstallHint()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return "Install it: winget install Python.Python.3.11";
        }
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            return "Install it: brew install python@3.11";
        }
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
        {
            return "Install it: sudo apt install -y python3.11 (or your distro's package manager)";
        }
        return "Install Python 3.11+ from https://www.python.org/downloads/";
    }
}
