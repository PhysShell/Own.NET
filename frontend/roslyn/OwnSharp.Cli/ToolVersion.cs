using System.Reflection;

namespace OwnSharp.Cli;

/// <summary>
/// The running tool's own version — the first path segment of the
/// vendored-core cache key (<c>~/.owen/core/&lt;version&gt;/&lt;fingerprint&gt;/</c>,
/// see <see cref="CoreVendor"/>), so a core mismatch between two installed
/// tool versions can never share a cache directory even before the
/// fingerprint segment is considered.
/// </summary>
internal static class ToolVersion
{
    public static string Current { get; } =
        typeof(ToolVersion).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";
}
