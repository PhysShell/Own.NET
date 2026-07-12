namespace OwnSharp.Cli;

/// <summary>
/// Unpacks the vendored <c>ownlang/</c> Python source (packed into this tool's
/// own nupkg under <c>ownlang-core/ownlang/*.py</c>, see the .csproj) into a
/// stable, per-version cache directory outside the tool's own (versioned,
/// nested) install path — and, per the design decision in issue #202, never
/// into the repository being analyzed. Cache root renamed to
/// <c>~/.owen/core/&lt;version&gt;/</c> for the Owen public facade (see
/// docs/notes/owen-public-facade.md); a version already unpacked under the
/// previous <c>~/.ownsharp/core/&lt;version&gt;/</c> location is reused as-is
/// (a plain existence check, not a migration — the old location is never
/// written to or deleted).
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
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var cacheRoot = Path.Combine(userProfile, ".owen", "core", ToolVersion.Current);
        var marker = Path.Combine(cacheRoot, ".unpacked");

        if (File.Exists(marker))
        {
            return cacheRoot;
        }

        // Simple fallback read from the previous ~/.ownsharp location (same
        // version already unpacked there by an older install of this same
        // tool) — reuse it in place rather than re-copying, no migration
        // subsystem. Only a same-version marker counts: a different version
        // there is irrelevant (each version gets its own cache directory).
        var legacyCacheRoot = Path.Combine(userProfile, ".ownsharp", "core", ToolVersion.Current);
        var legacyMarker = Path.Combine(legacyCacheRoot, ".unpacked");
        if (File.Exists(legacyMarker))
        {
            return legacyCacheRoot;
        }

        var destOwnlang = Path.Combine(cacheRoot, "ownlang");
        var sourceOwnlang = Path.Combine(AppContext.BaseDirectory, "ownlang-core", "ownlang");
        if (!Directory.Exists(sourceOwnlang))
        {
            throw new InvalidOperationException(
                $"owen: vendored core not found at '{sourceOwnlang}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global Owen.Cli` " +
                "and reinstall.");
        }

        Directory.CreateDirectory(destOwnlang);
        foreach (var file in Directory.EnumerateFiles(sourceOwnlang, "*.py"))
        {
            var dest = Path.Combine(destOwnlang, Path.GetFileName(file));
            File.Copy(file, dest, overwrite: true);
        }
        // Write the marker LAST: an interrupted copy (killed process, full disk)
        // leaves no marker, so the next run redoes the unpack instead of running
        // against a half-written core.
        File.WriteAllText(marker, ToolVersion.Current);
        return cacheRoot;
    }
}
