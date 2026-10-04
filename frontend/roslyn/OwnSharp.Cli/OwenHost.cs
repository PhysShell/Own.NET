using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OwnSharp.Cli;

/// <summary>One condition of the host itself (an <c>OWENB</c> code): a descriptor rejected, no
/// engine, a refusal. Never an analysis finding; never an <c>OWN</c> code.</summary>
internal sealed record HostDiagnostic(string File, int? Line, string Severity, string Code, string Text)
{
    /// <summary>The canonical MSBuild line: <c>file(line): severity CODE: text</c>.</summary>
    public string ToMsBuild() =>
        Line is { } line ? $"{File}({line}): {Severity} {Code}: {Text}" : $"{File}: {Severity} {Code}: {Text}";
}

/// <summary>An active Owen extension, as its descriptor declares it.</summary>
internal sealed record OwenDescriptor(string Path, string Id, string Version, IReadOnlyList<string> Capabilities,
    IReadOnlyList<string> Generators);

/// <summary>
/// The generic Owen host contract (OX-01, spec/OwenExtension.md), shared by its two front
/// doors: <c>owen build-check</c> (after a build) and <c>owen serve</c> (live, for an IDE;
/// OX-02). Everything here decides WHAT is analysed and how the host's own conditions read;
/// nothing here analyses, and nothing here names an extension.
/// </summary>
internal static class OwenHost
{
    /// <summary>The descriptor schema this host reads (`owen_extension`).</summary>
    public const int DescriptorSchema = 1;

    /// <summary>The OwnIR version the packed core speaks (spec/OwnIR.md §2).</summary>
    public const int OwnIr = 2;

    /// <summary>What an extension may require of this host. A capability is a promise about
    /// the analysis the packed extractor + core perform; it is added here only when they
    /// do.</summary>
    public static readonly string[] Capabilities = ["heap-effects", "ownership", "proven-call", "state-protocol"];

    // ---- the request file ---------------------------------------------------------------------

    /// <summary>The `key\tvalue` request the Owen.Build targets write (request.txt for a build,
    /// live.txt for an IDE). A key may repeat (`descriptor`).</summary>
    public static Dictionary<string, List<string>> ReadRequest(string path)
    {
        var map = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        foreach (var raw in File.ReadAllLines(path))
        {
            var tab = raw.IndexOf('\t');
            if (tab <= 0)
                continue;
            var key = raw[..tab];
            var value = raw[(tab + 1)..].Trim();
            if (value.Length == 0)
                continue;
            if (!map.TryGetValue(key, out var list))
                map[key] = list = [];
            list.Add(value);
        }
        return map;
    }

    public static string? One(Dictionary<string, List<string>> map, string key) =>
        map.TryGetValue(key, out var list) && list.Count > 0 ? list[^1] : null;

    // ---- descriptors --------------------------------------------------------------------------

    /// <summary>Validate every descriptor (sorted, deduplicated), then the set (one id once).
    /// Returns the active extensions sorted by id, or null with the reasons.</summary>
    public static List<OwenDescriptor>? Validate(IEnumerable<string> paths, List<HostDiagnostic> errors)
    {
        var descriptors = new List<OwenDescriptor>();
        var failed = false;
        foreach (var path in paths.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
        {
            var d = ReadDescriptor(path, errors);
            failed |= d is null;
            if (d is not null)
                descriptors.Add(d);
        }
        foreach (var dup in descriptors.GroupBy(d => d.Id, StringComparer.Ordinal).Where(g => g.Count() > 1))
        {
            errors.Add(new(dup.Last().Path, null, "error", "OWENB002", $"extension '{dup.Key}' is declared {dup.Count()} times"));
            failed = true;
        }
        if (failed)
            return null;
        descriptors.Sort((a, b) => StringComparer.Ordinal.Compare(a.Id, b.Id));
        return descriptors;
    }

    private static OwenDescriptor? ReadDescriptor(string path, List<HostDiagnostic> errors)
    {
        var before = errors.Count;
        void Bad(string code, string text) => errors.Add(new(path, null, "error", code, text));

        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(File.ReadAllBytes(path));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Bad("OWENB002", $"the extension descriptor cannot be read: {OneLine(ex.Message)}");
            return null;
        }
        using (doc)
        {
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                Bad("OWENB002", "the extension descriptor is not a JSON object");
                return null;
            }
            if (!root.TryGetProperty("owen_extension", out var schema) || schema.ValueKind != JsonValueKind.Number
                || !schema.TryGetInt32(out var schemaVersion))
            {
                Bad("OWENB002", "the extension descriptor has no integer 'owen_extension' schema version");
                return null;
            }
            if (schemaVersion != DescriptorSchema)
            {
                Bad("OWENB002", $"descriptor schema owen_extension={schemaVersion} is not one this host reads (it reads {DescriptorSchema}); update Owen.Build");
                return null;
            }
            var id = Text(root, "id");
            var version = Text(root, "version");
            if (id is null || version is null)
            {
                Bad("OWENB002", "the extension descriptor needs non-empty string 'id' and 'version'");
                return null;
            }
            if (!root.TryGetProperty("requires", out var requires) || requires.ValueKind != JsonValueKind.Object)
            {
                Bad("OWENB002", $"extension '{id}' has no 'requires' object");
                return null;
            }
            var host = Text(requires, "host");
            if (host is null || !System.Version.TryParse(host, out var needHost))
            {
                Bad("OWENB002", $"extension '{id}': 'requires.host' must be a version such as \"0.1.0\"");
                return null;
            }
            if (!requires.TryGetProperty("ownir", out var ownir) || ownir.ValueKind != JsonValueKind.Number
                || !ownir.TryGetInt32(out var needOwnIr))
            {
                Bad("OWENB002", $"extension '{id}': 'requires.ownir' must be an integer");
                return null;
            }
            var capabilities = Strings(requires, "capabilities");
            if (capabilities is null)
            {
                Bad("OWENB002", $"extension '{id}': 'requires.capabilities' must be an array of strings");
                return null;
            }
            IReadOnlyList<string> generators = [];
            if (root.TryGetProperty("frontend", out var frontend))
            {
                if (frontend.ValueKind != JsonValueKind.Object
                    || (frontend.TryGetProperty("generators", out _) && Strings(frontend, "generators") is null))
                {
                    Bad("OWENB002", $"extension '{id}': 'frontend.generators' must be an array of strings");
                    return null;
                }
                generators = Strings(frontend, "generators") ?? [];
            }

            var hostVersion = System.Version.Parse(ToolVersion.Current);
            if (needHost > hostVersion)
                Bad("OWENB003", $"extension '{id}' {version} requires Owen host {needHost}, this host is {hostVersion}; update Owen.Build");
            if (needOwnIr != OwnIr)
                Bad("OWENB003", $"extension '{id}' {version} requires OwnIR {needOwnIr}, this host's core speaks OwnIR {OwnIr}");
            foreach (var unknown in capabilities.Where(c => !Capabilities.Contains(c, StringComparer.Ordinal)))
                Bad("OWENB004", $"extension '{id}' {version} requires capability '{unknown}', which this host does not provide (it provides: {string.Join(", ", Capabilities)})");
            return errors.Count > before ? null : new OwenDescriptor(path, id, version, capabilities, generators);
        }
    }

    private static string? Text(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String && v.GetString() is { Length: > 0 } s
            ? s
            : null;

    private static List<string>? Strings(JsonElement e, string name)
    {
        if (!e.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.Array)
            return null;
        var list = new List<string>();
        foreach (var item in v.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String || item.GetString() is not { Length: > 0 } s)
                return null;
            list.Add(s);
        }
        return list;
    }

    /// <summary>obj/owen/extensions.json: what is active in this project, sorted, byte-stable.</summary>
    public static void WriteManifest(string path, IReadOnlyList<OwenDescriptor> descriptors)
    {
        var o = new StringBuilder();
        o.Append("{\n");
        o.Append($"  \"owen_host\": \"{ToolVersion.Current}\",\n");
        o.Append($"  \"ownir\": {OwnIr},\n");
        o.Append("  \"extensions\": [");
        for (var i = 0; i < descriptors.Count; i++)
        {
            var d = descriptors[i];
            o.Append(i == 0 ? "\n" : ",\n");
            o.Append("    {\n");
            o.Append($"      \"id\": {JsonSerializer.Serialize(d.Id)},\n");
            o.Append($"      \"version\": {JsonSerializer.Serialize(d.Version)},\n");
            o.Append($"      \"capabilities\": [{string.Join(", ", d.Capabilities.Order(StringComparer.Ordinal).Select(c => JsonSerializer.Serialize(c)))}]\n");
            o.Append("    }");
        }
        o.Append(descriptors.Count == 0 ? "]\n" : "\n  ]\n");
        o.Append("}\n");
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path))!);
        File.WriteAllText(path, o.ToString(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    // ---- the input set ------------------------------------------------------------------------

    /// <summary>The generator output directories the active extensions declare, in order.</summary>
    public static IEnumerable<string> Generators(IEnumerable<OwenDescriptor> descriptors) =>
        descriptors.SelectMany(d => d.Generators).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal);

    /// <summary>
    /// What the extractor reads: the project, then the C# the declared generators wrote under
    /// <paramref name="generatedRoot"/> (the extractor's own expansion skips generated files,
    /// and an extension's protocol lives in generated code). <paramref name="live"/> maps a
    /// generator to the files an IDE holds for it in memory; a generator it names is read from
    /// there instead of from the last build's output on disk.
    /// </summary>
    public static List<string> Inputs(string project, string? generatedRoot, IReadOnlyList<OwenDescriptor> descriptors,
        IReadOnlyDictionary<string, List<string>>? live = null)
    {
        var inputs = new List<string> { project };
        if (generatedRoot is null)
            return inputs;
        foreach (var generator in Generators(descriptors))
        {
            if (live is not null && live.TryGetValue(generator, out var held))
            {
                inputs.AddRange(held.Order(StringComparer.Ordinal));
                continue;
            }
            var dir = System.IO.Path.Combine(generatedRoot, generator);
            if (Directory.Exists(dir))
                inputs.AddRange(Directory.EnumerateFiles(dir, "*.cs", SearchOption.AllDirectories)
                    .Order(StringComparer.Ordinal));
        }
        return inputs;
    }

    // ---- refusals -----------------------------------------------------------------------------

    // extractor: protocol lowering refused: OrderEndpoints.cs:17: <text>
    public static readonly Regex ExtractorRefusal = new(@"refused:\s+(?<file>[^\r\n]+?):(?<line>\d+):\s+(?<text>.+)$");

    // facts.json: error: <text … (File.cs:20) — refused: …>
    public static readonly Regex CoreRefusal = new(@"^.*?:\s+error:\s+(?<text>.*\((?<file>[^()\r\n]+):(?<line>\d+)\).*)$");

    /// <summary>One error per refusal line that names a location (its file made absolute
    /// against the project directory); one project-level error carrying the whole output
    /// when none does. Never zero.</summary>
    public static List<HostDiagnostic> Refusals(string output, string project, string code, Regex located)
    {
        var dir = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(project))!;
        var found = new List<HostDiagnostic>();
        foreach (var raw in output.Split('\n'))
        {
            var m = located.Match(raw.TrimEnd('\r'));
            if (!m.Success)
                continue;
            var file = m.Groups["file"].Value;
            found.Add(new(System.IO.Path.IsPathRooted(file) ? file : System.IO.Path.GetFullPath(System.IO.Path.Combine(dir, file)),
                int.Parse(m.Groups["line"].Value, System.Globalization.CultureInfo.InvariantCulture),
                "error", code, m.Groups["text"].Value));
        }
        if (found.Count == 0)
            found.Add(new(project, null, "error", code, OneLine(output)));
        return found;
    }

    // `File.cs(18): warning OWN002: …` / `File.cs(18,3): error …`
    private static readonly Regex CanonicalOrigin = new(@"^(?<file>[^\r\n(]+?)\((?<pos>\d+(?:,\d+)*)\): (?<rest>(?:warning|error) .*)$");

    /// <summary>Make the origin of every canonical line absolute against the project
    /// directory; every other byte, the message text included, is left as it is.</summary>
    public static string Absolute(string text, string project)
    {
        var dir = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(project))!;
        // split and re-join on '\n': a trailing newline survives as the empty last piece
        return string.Join('\n', text.Split('\n').Select(piece =>
        {
            var line = piece.TrimEnd('\r');
            var m = CanonicalOrigin.Match(line);
            return m.Success && !System.IO.Path.IsPathRooted(m.Groups["file"].Value)
                ? $"{System.IO.Path.GetFullPath(System.IO.Path.Combine(dir, m.Groups["file"].Value))}({m.Groups["pos"].Value}): {m.Groups["rest"].Value}"
                : piece;
        }));
    }

    public static string OneLine(string text) =>
        string.Join(" ", text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries).Select(s => s.Trim()));
}
