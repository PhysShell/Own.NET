using System.Reflection;

namespace OwnSharp.Cli;

/// <summary>
/// The running tool's own version — doubles as the vendored-core cache key
/// (<c>~/.ownsharp/core/&lt;version&gt;/</c>), so a core mismatch between two
/// installed tool versions can never share a cache directory.
/// </summary>
internal static class ToolVersion
{
    public static string Current { get; } =
        typeof(ToolVersion).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";
}
