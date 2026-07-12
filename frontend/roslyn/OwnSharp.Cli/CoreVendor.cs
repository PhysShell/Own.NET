using System.Security.Cryptography;
using System.Text;

namespace OwnSharp.Cli;

/// <summary>
/// Unpacks the vendored <c>ownlang/</c> Python source (packed into this tool's
/// own nupkg under <c>ownlang-core/ownlang/*.py</c>, see the .csproj) into a
/// stable, per-version cache directory outside the tool's own (versioned,
/// nested) install path — and, per the design decision in issue #202, never
/// into the repository being analyzed. Cache root renamed to
/// <c>~/.owen/core/&lt;version&gt;/</c> for the Owen public facade (see
/// docs/notes/owen-public-facade.md); a version already unpacked under the
/// previous <c>~/.ownsharp/core/&lt;version&gt;/</c> location is reused as-is —
/// a plain fallback read, not a migration (the old location is never written
/// to or deleted) — but ONLY when its content fingerprint still matches the
/// source this install actually bundles (see <see cref="EnsureUnpacked"/>).
/// </summary>
internal static class CoreVendor
{
    /// <summary>
    /// Ensures the vendored core is unpacked for the running tool's version and
    /// returns the directory that must be the working directory / PYTHONPATH
    /// for `python -m ownlang ...` (i.e. the parent of the `ownlang` package
    /// directory, exactly like own-check.sh's `PYTHONPATH="$root"`).
    /// </summary>
    public static string EnsureUnpacked()
    {
        var sourceOwnlang = Path.Combine(AppContext.BaseDirectory, "ownlang-core", "ownlang");
        if (!Directory.Exists(sourceOwnlang))
        {
            throw new InvalidOperationException(
                $"owen: vendored core not found at '{sourceOwnlang}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global Owen.Cli` " +
                "and reinstall.");
        }
        // A same-version marker alone does NOT prove the cached files match what
        // THIS install bundles (review, PR #246): the CLI's own <Version> can
        // stay unchanged across a content-only re-vendor (exactly what shipping
        // the Owen SARIF-driver-name rename without a version bump would do),
        // and the legacy ~/.ownsharp fallback below is a second location that
        // can hold same-version-but-different-content data from a genuinely
        // different install lineage (a pre-rebrand tool). A content fingerprint
        // closes both holes with the same simple mechanism, no migration
        // subsystem: trust a cache only when its marker's hash equals the hash
        // of the source this install would unpack right now.
        var fingerprint = Fingerprint(sourceOwnlang);

        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var cacheRoot = Path.Combine(userProfile, ".owen", "core", ToolVersion.Current);
        var marker = Path.Combine(cacheRoot, ".unpacked");

        if (File.Exists(marker) && File.ReadAllText(marker) == fingerprint)
        {
            return cacheRoot;
        }

        // Simple fallback read from the previous ~/.ownsharp location (same
        // version, same content, already unpacked there by an older install)
        // — reuse it in place rather than re-copying.
        var legacyCacheRoot = Path.Combine(userProfile, ".ownsharp", "core", ToolVersion.Current);
        var legacyMarker = Path.Combine(legacyCacheRoot, ".unpacked");
        if (File.Exists(legacyMarker) && File.ReadAllText(legacyMarker) == fingerprint)
        {
            return legacyCacheRoot;
        }

        var destOwnlang = Path.Combine(cacheRoot, "ownlang");
        Directory.CreateDirectory(destOwnlang);
        foreach (var file in Directory.EnumerateFiles(sourceOwnlang, "*.py"))
        {
            var dest = Path.Combine(destOwnlang, Path.GetFileName(file));
            File.Copy(file, dest, overwrite: true);
        }
        // Write the marker LAST: an interrupted copy (killed process, full disk)
        // leaves no marker, so the next run redoes the unpack instead of running
        // against a half-written core.
        File.WriteAllText(marker, fingerprint);
        return cacheRoot;
    }

    /// <summary>SHA-256 over every vendored <c>*.py</c> file's name and content,
    /// sorted by filename for determinism — a cheap, self-contained way to tell
    /// "this cache holds exactly this source" apart from "this cache exists and
    /// the version number happens to match".</summary>
    private static string Fingerprint(string sourceOwnlang)
    {
        using var sha = SHA256.Create();
        using var buffer = new MemoryStream();
        foreach (var file in Directory.EnumerateFiles(sourceOwnlang, "*.py").OrderBy(f => f, StringComparer.Ordinal))
        {
            var nameBytes = Encoding.UTF8.GetBytes(Path.GetFileName(file));
            buffer.Write(nameBytes);
            var contentBytes = File.ReadAllBytes(file);
            buffer.Write(contentBytes);
        }
        return Convert.ToHexString(sha.ComputeHash(buffer.ToArray()));
    }
}
