using System.Security.Cryptography;
using System.Text;

namespace OwnSharp.Cli;

/// <summary>
/// Unpacks the vendored <c>ownlang/</c> Python source (packed into this tool's
/// own nupkg under <c>ownlang-core/ownlang/*.py</c>, see the .csproj) into a
/// stable, content-addressed cache directory outside the tool's own
/// (versioned, nested) install path — and, per the design decision in issue
/// #202, never into the repository being analyzed.
///
/// Layout: <c>~/.owen/core/&lt;version&gt;/&lt;fingerprint&gt;/ownlang/</c>, where
/// <c>fingerprint</c> is a SHA-256 over every vendored file's name and
/// content (see <see cref="Fingerprint"/>). Content-addressing (review, PR
/// #246) closes a hole a plain version-keyed marker had: the CLI's own
/// <c>&lt;Version&gt;</c> does not change every time the vendored core's
/// content does — this rebrand's own SARIF-driver-name change is the
/// concrete proof, same <c>0.1.0</c>, different core content — so a
/// version-only cache could either serve stale content on a mismatch, or
/// (worse) get overwritten file-by-file in place, leaving files the new
/// source no longer has stranded alongside the new ones with a marker that
/// then claims the (polluted) result matches. Content-addressing sidesteps
/// both: a fingerprint mismatch is a *different path*, never an overwrite of
/// an existing one, and publication into that path is atomic (build in a
/// temp sibling, then <see cref="Directory.Move(string, string)"/> once
/// fully written and verified) so a reader never observes a partial write.
///
/// A version already unpacked under the previous flat
/// <c>~/.ownsharp/core/&lt;version&gt;/</c> location (pre-rebrand layout, no
/// fingerprint) is used in place — without copying — but ONLY after
/// recomputing a fingerprint over what is actually on disk there and
/// confirming it matches the source this install bundles right now; a
/// destination with extra, missing, or modified files fails that check and
/// falls through to a fresh unpack. This is still a plain fallback *read*,
/// not a migration subsystem: the legacy location is never written to,
/// moved, or deleted by this code.
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
        var sourceFiles = SortedPyFiles(sourceOwnlang);
        var fingerprint = Fingerprint(sourceFiles);

        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var versionRoot = Path.Combine(userProfile, ".owen", "core", ToolVersion.Current);
        var finalRoot = Path.Combine(versionRoot, fingerprint);
        var finalOwnlang = Path.Combine(finalRoot, "ownlang");

        // Content-addressed: existence at the fingerprint-named path IS proof of
        // validity (see the atomic-publish note below) -- no separate marker to
        // go stale or drift from the directory's actual contents.
        if (Directory.Exists(finalOwnlang))
        {
            return finalRoot;
        }

        // Legacy fallback: verify the LEGACY DESTINATION's actual content, not a
        // marker file's say-so (review, PR #246) -- a marker only proves "an
        // unpack happened here once", never that nothing since removed, added,
        // or modified a file in that directory.
        var legacyOwnlang = Path.Combine(userProfile, ".ownsharp", "core", ToolVersion.Current, "ownlang");
        if (Directory.Exists(legacyOwnlang))
        {
            var legacyFiles = SortedPyFiles(legacyOwnlang);
            var legacyFingerprint = Fingerprint(legacyFiles);
            if (legacyFingerprint == fingerprint)
            {
                return Path.Combine(userProfile, ".ownsharp", "core", ToolVersion.Current);
            }
        }

        // Fresh unpack: build into a temp sibling, verify the DESTINATION's own
        // fingerprint matches the source before anything else can observe it,
        // then publish with a single atomic rename. A reader can only ever see
        // either nothing at finalOwnlang, or a fully-written, self-verified copy
        // -- never a partial one (crash/kill/full-disk mid-copy just leaves an
        // orphaned temp directory next to it, harmless and never consulted).
        var tempRoot = Path.Combine(versionRoot, $".tmp-{Guid.NewGuid():N}");
        var tempOwnlang = Path.Combine(tempRoot, "ownlang");
        try
        {
            Directory.CreateDirectory(tempOwnlang);
            foreach (var file in sourceFiles)
            {
                File.Copy(file, Path.Combine(tempOwnlang, Path.GetFileName(file)), overwrite: true);
            }
            var writtenFiles = SortedPyFiles(tempOwnlang);
            var writtenFingerprint = Fingerprint(writtenFiles);
            if (writtenFingerprint != fingerprint)
            {
                throw new InvalidOperationException(
                    $"owen: internal error -- the core copy at '{tempOwnlang}' does not match " +
                    "its source fingerprint after writing. Not publishing it; try reinstalling.");
            }

            if (Directory.Exists(finalOwnlang))
            {
                // Lost a race with a concurrent `owen` process that published the
                // same fingerprint first -- their content is provably identical
                // (same fingerprint), so just use it.
                return finalRoot;
            }
            Directory.CreateDirectory(finalRoot);
            Directory.Move(tempOwnlang, finalOwnlang);
            return finalRoot;
        }
        finally
        {
            if (Directory.Exists(tempRoot))
            {
                try { Directory.Delete(tempRoot, recursive: true); } catch (IOException) { /* best-effort cleanup */ }
            }
        }
    }

    private static List<string> SortedPyFiles(string dir) =>
        Directory.EnumerateFiles(dir, "*.py").OrderBy(f => Path.GetFileName(f), StringComparer.Ordinal).ToList();

    /// <summary>SHA-256 over every file's name and content, each explicitly
    /// length-prefixed (review, PR #246) so two different (name, content) sets
    /// can never hash identically by having their bytes merely concatenate the
    /// same way -- e.g. name "ab" + content "c" vs. name "a" + content "bc"
    /// would collide under bare concatenation; an 8-byte length prefix on each
    /// field rules that out. Sorted by filename first (by the caller) for a
    /// fingerprint that doesn't depend on enumeration order.</summary>
    private static string Fingerprint(IReadOnlyList<string> files)
    {
        using var sha = SHA256.Create();
        using var buffer = new MemoryStream();
        using var writer = new BinaryWriter(buffer, Encoding.UTF8, leaveOpen: true);
        foreach (var file in files)
        {
            var nameBytes = Encoding.UTF8.GetBytes(Path.GetFileName(file));
            writer.Write((long)nameBytes.Length);
            writer.Write(nameBytes);
            var contentBytes = File.ReadAllBytes(file);
            writer.Write((long)contentBytes.Length);
            writer.Write(contentBytes);
        }
        writer.Flush();
        return Convert.ToHexString(sha.ComputeHash(buffer.ToArray()));
    }
}
