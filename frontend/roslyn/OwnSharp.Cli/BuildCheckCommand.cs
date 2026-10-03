using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OwnSharp.Cli;

/// <summary>
/// `owen build-check --request &lt;file&gt;` — the generic Owen build host (OX-01,
/// spec/OwenExtension.md). Called by the `Owen.Build` package's MSBuild targets after a project
/// has been built; not meant to be typed.
///
/// <para>It is <c>owen check</c> with three additions, none of them analysis:</para>
/// <list type="number">
/// <item>it validates the <b>extension descriptors</b> the project's packages declare against
/// what this host supports, and fails loud on anything it does not understand;</item>
/// <item>it hands the C# that those extensions' generators wrote to the extractor explicitly,
/// beside the project (the extractor's own expansion skips generated files, and an
/// extension's protocol lives in generated code);</item>
/// <item>it speaks MSBuild: every failure is ONE canonical line (<c>origin: error OWENBnnn:
/// text</c>, with <c>file(line)</c> wherever there is one), so the build fails on it and the
/// Error List can navigate to it.</item>
/// </list>
///
/// <para>The findings themselves are the Rust core's, rendered by the core
/// (<c>--format msbuild</c>) and passed through byte for byte. This host renders nothing of
/// its own and knows no extension by name.</para>
///
/// <para>Exit: 0 analysed (findings shown as warnings, or none); 1 analysed, findings shown as
/// errors; 2 a host / contract / refusal error, already printed as an OWENB line.</para>
/// </summary>
internal static class BuildCheckCommand
{
    /// <summary>The descriptor schema this host reads (`owen_extension`).</summary>
    public const int DescriptorSchema = 1;

    /// <summary>The OwnIR version the packed core speaks (spec/OwnIR.md §2).</summary>
    public const int OwnIr = 2;

    /// <summary>What an extension may require of this host. A capability is a promise about
    /// the analysis the packed extractor + core perform; it is added here only when they
    /// do.</summary>
    public static readonly string[] Capabilities = ["heap-effects", "ownership", "proven-call", "state-protocol"];

    private sealed record Descriptor(string Path, string Id, string Version, IReadOnlyList<string> Capabilities,
        IReadOnlyList<string> Generators);

    public static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2 || args[0] != "--request")
        {
            Console.Error.WriteLine("usage: owen build-check --request <file>   (written by the Owen.Build targets)");
            return 2;
        }

        Dictionary<string, List<string>> request;
        try
        {
            request = ReadRequest(args[1]);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Console.WriteLine($"owen: error OWENB012: cannot read the build request '{args[1]}': {ex.Message}");
            return 2;
        }

        var project = One(request, "project");
        var severity = One(request, "severity") ?? "warning";
        var manifest = One(request, "manifest");
        var generatedRoot = One(request, "generated-root");
        var emitFacts = One(request, "emit-facts");
        if (project is null || manifest is null)
        {
            Console.WriteLine("owen: error OWENB012: the build request names no project or no manifest path");
            return 2;
        }
        if (severity is not ("warning" or "error"))
        {
            Console.WriteLine($"{project}: error OWENB002: OwenSeverity must be 'warning' or 'error', not '{severity}'");
            return 2;
        }

        // ---- 1. the extensions --------------------------------------------------------------
        var paths = request.TryGetValue("descriptor", out var given) ? given : [];
        if (paths.Count == 0)
        {
            Console.WriteLine($"{project}: warning OWENB001: Owen.Build is referenced but no Owen extension is active; nothing was analysed");
            WriteManifest(manifest, []);
            return 0;
        }
        var descriptors = new List<Descriptor>();
        var failed = false;
        foreach (var path in paths.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
        {
            var d = ReadDescriptor(path, out var errors);
            foreach (var e in errors)
                Console.WriteLine(e);
            failed |= errors.Count > 0;
            if (d is not null)
                descriptors.Add(d);
        }
        foreach (var dup in descriptors.GroupBy(d => d.Id, StringComparer.Ordinal).Where(g => g.Count() > 1))
        {
            Console.WriteLine($"{dup.Last().Path}: error OWENB002: extension '{dup.Key}' is declared {dup.Count()} times");
            failed = true;
        }
        if (failed)
            return 2;
        descriptors.Sort((a, b) => StringComparer.Ordinal.Compare(a.Id, b.Id));
        WriteManifest(manifest, descriptors);
        Console.WriteLine("Owen: active extensions: " + string.Join(", ", descriptors.Select(d => $"{d.Id} {d.Version}")));

        // ---- 2. the inputs ------------------------------------------------------------------
        var inputs = new List<string> { project };
        if (generatedRoot is not null)
        {
            foreach (var generator in descriptors.SelectMany(d => d.Generators).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
            {
                var dir = Path.Combine(generatedRoot, generator);
                if (Directory.Exists(dir))
                    inputs.AddRange(Directory.EnumerateFiles(dir, "*.cs", SearchOption.AllDirectories)
                        .Order(StringComparer.Ordinal));
            }
        }

        // ---- 3. the engine ------------------------------------------------------------------
        RustCore core;
        try
        {
            core = RustCoreLocator.Resolve();
        }
        catch (RustCoreNotResolvedException ex)
        {
            Console.WriteLine($"{project}: error OWENB005: {OneLine(ex.Message)}");
            return 2;
        }

        var factsPath = Path.GetTempFileName();
        try
        {
            var (extractRc, extractOutput) = await CheckCommand
                .RunExtractorAsync(inputs, factsPath, legacy: false, stats: false, bodyThrowEdges: false)
                .ConfigureAwait(false);
            if (extractRc == 2)
            {
                foreach (var line in Canonical(extractOutput, project, "OWENB010", ExtractorRefusal))
                    Console.WriteLine(Absolute(line, project));
                return 2;
            }
            if (extractRc != 0)
            {
                Console.WriteLine($"{project}: error OWENB012: the extractor exited {extractRc}: {OneLine(extractOutput)}");
                return 2;
            }
            if (emitFacts is not null)
                File.Copy(factsPath, emitFacts, overwrite: true);

            EngineOutcome outcome;
            try
            {
                outcome = await EngineRunner.RunRustAsync(core, factsPath, "msbuild", severity, capture: true)
                    .ConfigureAwait(false);
            }
            catch (EngineRunner.RustCoreNotStartedException ex)
            {
                Console.WriteLine($"{project}: error OWENB005: {OneLine(ex.Message)}");
                return 2;
            }
            var stdout = Encoding.UTF8.GetString(outcome.Stdout);
            var stderr = Encoding.UTF8.GetString(outcome.Stderr);
            switch (outcome.Rc)
            {
                case 0 or 1:
                    // the core's own canonical lines, unchanged but for the origin path: the
                    // core names files relative to the project directory (the extractor ran
                    // there), and the Error List must not have to guess the base
                    Console.Write(Absolute(stdout, project));
                    Console.Write(Absolute(stderr, project));
                    return outcome.Rc == 1 && severity == "error" ? 1 : 0;
                case 2:
                    foreach (var line in Canonical(stderr + stdout, project, "OWENB011", CoreRefusal))
                        Console.WriteLine(Absolute(line, project));
                    return 2;
                default:
                    Console.WriteLine($"{project}: error OWENB012: the Rust core exited {outcome.Rc}, which is not a verdict: {OneLine(stderr)}");
                    return 2;
            }
        }
        finally
        {
            try { File.Delete(factsPath); } catch (IOException) { /* best-effort */ }
        }
    }

    // ---- descriptors --------------------------------------------------------------------------

    private static Descriptor? ReadDescriptor(string path, out List<string> errors)
    {
        var found = new List<string>();
        errors = found;
        void Bad(string code, string text) => found.Add($"{path}: error {code}: {text}");

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
            if (host is null || !Version.TryParse(host, out var needHost))
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

            var hostVersion = Version.Parse(ToolVersion.Current);
            if (needHost > hostVersion)
                Bad("OWENB003", $"extension '{id}' {version} requires Owen host {needHost}, this host is {hostVersion}; update Owen.Build");
            if (needOwnIr != OwnIr)
                Bad("OWENB003", $"extension '{id}' {version} requires OwnIR {needOwnIr}, this host's core speaks OwnIR {OwnIr}");
            foreach (var unknown in capabilities.Where(c => !Capabilities.Contains(c, StringComparer.Ordinal)))
                Bad("OWENB004", $"extension '{id}' {version} requires capability '{unknown}', which this host does not provide (it provides: {string.Join(", ", Capabilities)})");
            return found.Count > 0 ? null : new Descriptor(path, id, version, capabilities, generators);
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
    private static void WriteManifest(string path, IReadOnlyList<Descriptor> descriptors)
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
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        File.WriteAllText(path, o.ToString(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    // ---- refusals, as canonical MSBuild lines ----------------------------------------------------

    // extractor: protocol lowering refused: OrderEndpoints.cs:17: <text>
    private static readonly Regex ExtractorRefusal = new(@"refused:\s+(?<file>[^\r\n]+?):(?<line>\d+):\s+(?<text>.+)$");

    // facts.json: error: <text … (File.cs:20) — refused: …>
    private static readonly Regex CoreRefusal = new(@"^.*?:\s+error:\s+(?<text>.*\((?<file>[^()\r\n]+):(?<line>\d+)\).*)$");

    /// <summary>One canonical error per refusal line that names a location; one project-level
    /// error carrying the whole output when none does. Never zero lines.</summary>
    private static List<string> Canonical(string output, string project, string code, Regex located)
    {
        var lines = new List<string>();
        foreach (var raw in output.Split('\n'))
        {
            var line = raw.TrimEnd('\r');
            var m = located.Match(line);
            if (m.Success)
                lines.Add($"{m.Groups["file"].Value}({m.Groups["line"].Value}): error {code}: {m.Groups["text"].Value}");
        }
        if (lines.Count == 0)
            lines.Add($"{project}: error {code}: {OneLine(output)}");
        return lines;
    }

    // `File.cs(18): warning OWN002: …` / `File.cs(18,3): error …`
    private static readonly Regex CanonicalOrigin = new(@"^(?<file>[^\r\n(]+?)\((?<pos>\d+(?:,\d+)*)\): (?<rest>(?:warning|error) .*)$");

    /// <summary>Make the origin of every canonical line absolute against the project
    /// directory; every other byte, the message text included, is left as it is.</summary>
    private static string Absolute(string text, string project)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(project))!;
        // split and re-join on '\n': a trailing newline survives as the empty last piece
        return string.Join('\n', text.Split('\n').Select(piece =>
        {
            var line = piece.TrimEnd('\r');
            var m = CanonicalOrigin.Match(line);
            return m.Success && !Path.IsPathRooted(m.Groups["file"].Value)
                ? $"{Path.GetFullPath(Path.Combine(dir, m.Groups["file"].Value))}({m.Groups["pos"].Value}): {m.Groups["rest"].Value}"
                : piece;
        }));
    }

    private static string OneLine(string text) =>
        string.Join(" ", text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries).Select(s => s.Trim()));

    // ---- the request file ---------------------------------------------------------------------

    private static Dictionary<string, List<string>> ReadRequest(string path)
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

    private static string? One(Dictionary<string, List<string>> map, string key) =>
        map.TryGetValue(key, out var list) && list.Count > 0 ? list[^1] : null;
}
