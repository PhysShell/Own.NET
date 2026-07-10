namespace OwnSharp.Cli;

/// <summary>
/// Unpacks the vendored <c>ownlang/</c> Python source (packed into this tool's
/// own nupkg under <c>ownlang-core/ownlang/*.py</c>, see the .csproj) into a
/// stable, per-version cache directory outside the tool's own (versioned,
/// nested) install path — and, per the design decision in issue #202, never
/// into the repository being analyzed.
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
        var cacheRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".ownsharp", "core", ToolVersion.Current);
        var destOwnlang = Path.Combine(cacheRoot, "ownlang");
        var marker = Path.Combine(cacheRoot, ".unpacked");

        if (File.Exists(marker))
        {
            return cacheRoot;
        }

        var sourceOwnlang = Path.Combine(AppContext.BaseDirectory, "ownlang-core", "ownlang");
        if (!Directory.Exists(sourceOwnlang))
        {
            throw new InvalidOperationException(
                $"ownsharp: vendored core not found at '{sourceOwnlang}' — a corrupt or " +
                "incomplete tool install. Try `dotnet tool uninstall --global OwnSharp.Cli` " +
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
