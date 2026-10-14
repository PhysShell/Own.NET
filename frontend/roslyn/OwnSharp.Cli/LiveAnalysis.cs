using System.Diagnostics;
using System.Text;
using System.Text.Json;
using OwnSharp.Extractor;

namespace OwnSharp.Cli;

/// <summary>One source an IDE holds in memory: its full path and its current text.</summary>
internal sealed record LiveDocument(string Path, string Text);

/// <summary>A location the core names: the finding's own, or one of its witness steps.</summary>
internal sealed record LiveLocation(string File, int Line, int? Column, string? Message);

/// <summary>One diagnostic as the IDE shows it (docs/notes/owen-visual-studio-preregistration.md §6).
/// An OWN finding is the core's <c>Finding</c>, carried; an OWENB one is the host's own.</summary>
internal sealed record LiveDiagnostic(string Code, string Severity, string Message, string File, int? Line,
    int? Column, string Origin, IReadOnlyList<LiveLocation> Related);

internal sealed record LiveResult(IReadOnlyList<LiveDiagnostic> Diagnostics, IReadOnlyList<string> Extensions,
    IReadOnlyDictionary<string, long> TimingMs);

/// <summary>
/// One live analysis (OX-02): the build host's contract (<see cref="OwenHost"/>) over the text an
/// IDE holds, through the ONE extractor run in-process (<see cref="InProcessExtractor"/>) and
/// the packaged Rust core. It is <c>owen build-check</c> with three differences, none of them
/// analysis: the sources come from memory where the IDE has them, the extractor runs in this
/// process, and the core's findings come back through its SARIF renderer so that columns and
/// witness steps survive. A verdict is never formed here.
/// </summary>
internal static class LiveAnalysis
{
    private static RustCore? _core;

    public static async Task<LiveResult> RunAsync(string requestPath, IReadOnlyList<LiveDocument> documents,
        IReadOnlyList<LiveDocument> generated)
    {
        var timing = new Dictionary<string, long>(StringComparer.Ordinal);
        var clock = Stopwatch.StartNew();
        var diagnostics = new List<LiveDiagnostic>();
        LiveResult Done(IReadOnlyList<string> extensions)
        {
            timing["total"] = clock.ElapsedMilliseconds;
            // the service's own footprint, so a host can watch it grow (preregistration §8)
            timing["working_set_kb"] = Environment.WorkingSet / 1024;
            return new LiveResult(diagnostics, extensions, timing);
        }
        void Host(HostDiagnostic d) =>
            diagnostics.Add(new(d.Code, d.Severity, d.Text, d.File, d.Line, null, "host", []));

        Dictionary<string, List<string>> request;
        try
        {
            request = OwenHost.ReadRequest(requestPath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Host(new(requestPath, null, "error", "OWENB012", $"cannot read the live request: {ex.Message}"));
            return Done([]);
        }
        var project = OwenHost.One(request, "project");
        var severity = OwenHost.One(request, "severity") ?? "warning";
        var generatedRoot = OwenHost.One(request, "generated-root");
        if (project is null)
        {
            Host(new(requestPath, null, "error", "OWENB012", "the live request names no project"));
            return Done([]);
        }
        if (severity is not ("warning" or "error"))
        {
            Host(new(project, null, "error", "OWENB002", $"OwenSeverity must be 'warning' or 'error', not '{severity}'"));
            return Done([]);
        }

        // ---- 1. the extensions: the build host's own validation ---------------------------
        var paths = request.TryGetValue("descriptor", out var given) ? given : [];
        if (paths.Count == 0)
        {
            Host(new(project, null, "warning", "OWENB001", "Owen.Build is referenced but no Owen extension is active; nothing was analysed"));
            return Done([]);
        }
        var errors = new List<HostDiagnostic>();
        var descriptors = OwenHost.Validate(paths, errors);
        errors.ForEach(Host);
        if (descriptors is null)
            return Done([]);
        var extensions = descriptors.Select(d => d.Id).ToList();

        // ---- 2. the inputs: the build's input set, the editor's text ---------------------
        var overlay = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var d in documents)
            overlay[Path.GetFullPath(d.Path)] = d.Text;
        Dictionary<string, List<string>>? live = null;
        if (generatedRoot is not null)
        {
            live = [];
            foreach (var generator in OwenHost.Generators(descriptors))
                foreach (var g in generated)
                    if (Relocate(g.Path, generator, generatedRoot) is { } path)
                    {
                        overlay[path] = g.Text;
                        (live.TryGetValue(generator, out var list) ? list : live[generator] = []).Add(path);
                    }
        }
        var inputs = OwenHost.Inputs(project, generatedRoot, descriptors, live);
        var projectDir = Path.GetDirectoryName(Path.GetFullPath(project))!;

        // ---- 3. the extractor, in this process ---------------------------------------------
        var factsPath = Path.GetTempFileName();
        try
        {
            var step = Stopwatch.StartNew();
            var (extractRc, extractOutput) = InProcessExtractor.Run(
                [.. inputs, "-o", factsPath, "--flow-locals"], projectDir, overlay);
            timing["extract"] = step.ElapsedMilliseconds;
            if (extractRc == 2)
            {
                OwenHost.Refusals(extractOutput, project, "OWENB010", OwenHost.ExtractorRefusal).ForEach(Host);
                return Done(extensions);
            }
            if (extractRc != 0)
            {
                Host(new(project, null, "error", "OWENB012", $"the extractor exited {extractRc}: {OwenHost.OneLine(extractOutput)}"));
                return Done(extensions);
            }

            // ---- 4. the core ---------------------------------------------------------------
            step.Restart();
            EngineOutcome outcome;
            try
            {
                _core ??= RustCoreLocator.Resolve();
                outcome = await EngineRunner.RunRustAsync(_core, factsPath, "sarif", severity, capture: true)
                    .ConfigureAwait(false);
            }
            catch (RustCoreNotResolvedException ex)
            {
                Host(new(project, null, "error", "OWENB005", OwenHost.OneLine(ex.Message)));
                return Done(extensions);
            }
            catch (EngineRunner.RustCoreNotStartedException ex)
            {
                _core = null;
                Host(new(project, null, "error", "OWENB005", OwenHost.OneLine(ex.Message)));
                return Done(extensions);
            }
            timing["core"] = step.ElapsedMilliseconds;
            var stdout = Encoding.UTF8.GetString(outcome.Stdout);
            var stderr = Encoding.UTF8.GetString(outcome.Stderr);
            switch (outcome.Rc)
            {
                case 0 or 1:
                    diagnostics.AddRange(FromSarif(stdout, projectDir));
                    break;
                case 2:
                    OwenHost.Refusals(stderr + stdout, project, "OWENB011", OwenHost.CoreRefusal).ForEach(Host);
                    break;
                default:
                    Host(new(project, null, "error", "OWENB012", $"the Rust core exited {outcome.Rc}, which is not a verdict: {OwenHost.OneLine(stderr)}"));
                    break;
            }
            return Done(extensions);
        }
        finally
        {
            try { File.Delete(factsPath); } catch (IOException) { /* best-effort */ }
        }
    }

    /// <summary>
    /// Where the build would have written an in-memory generated document: the compiler lays a
    /// generator's output out as <c>&lt;generated-root&gt;/&lt;generator assembly&gt;/&lt;generator type&gt;/&lt;hint&gt;</c>,
    /// and an IDE names its generated documents with the same three trailing parts under a base of
    /// its own. The generator is matched by name, never by which extension it belongs to.
    /// </summary>
    internal static string? Relocate(string path, string generator, string generatedRoot)
    {
        var parts = path.Split(['/', '\\'], StringSplitOptions.RemoveEmptyEntries);
        for (var i = parts.Length - 3; i >= 0; i--)
            if (string.Equals(parts[i], generator, StringComparison.Ordinal))
                return Path.GetFullPath(Path.Combine([generatedRoot, .. parts[i..]]));
        return null;
    }

    /// <summary>
    /// The core's findings as the SARIF renderer wrote them, carried field for field: rule id,
    /// message text, location, witness steps. Exactly the findings the msbuild renderer prints:
    /// a suppressed one (<c>[OwnIgnore]</c>) is not shown there and is not shown here, and an
    /// advisory (SARIF <c>note</c>) is a warning there and a warning here.
    /// </summary>
    internal static IEnumerable<LiveDiagnostic> FromSarif(string sarif, string projectDir)
    {
        using var doc = JsonDocument.Parse(sarif);
        foreach (var run in doc.RootElement.GetProperty("runs").EnumerateArray())
        {
            if (!run.TryGetProperty("results", out var results))
                continue;
            foreach (var r in results.EnumerateArray())
            {
                if (r.TryGetProperty("suppressions", out var sup) && sup.GetArrayLength() > 0)
                    continue;
                var level = r.GetProperty("level").GetString();
                var primary = Location(r.GetProperty("locations")[0], projectDir, null);
                var related = new List<LiveLocation>();
                if (r.TryGetProperty("codeFlows", out var flows))
                    foreach (var flow in flows.EnumerateArray())
                        foreach (var thread in flow.GetProperty("threadFlows").EnumerateArray())
                            foreach (var step in thread.GetProperty("locations").EnumerateArray())
                                if (step.TryGetProperty("location", out var at))
                                    related.Add(Location(at, projectDir, Text(at)));
                if (r.TryGetProperty("relatedLocations", out var rel))
                    foreach (var at in rel.EnumerateArray())
                        related.Add(Location(at, projectDir, Text(at)));
                yield return new LiveDiagnostic(
                    r.GetProperty("ruleId").GetString()!,
                    level == "error" ? "error" : "warning",
                    r.GetProperty("message").GetProperty("text").GetString()!,
                    primary.File, primary.Line, primary.Column, "core", related);
            }
        }

        static string? Text(JsonElement at) =>
            at.TryGetProperty("message", out var m) && m.TryGetProperty("text", out var t) ? t.GetString() : null;
    }

    private static LiveLocation Location(JsonElement at, string projectDir, string? message)
    {
        var physical = at.GetProperty("physicalLocation");
        var uri = physical.GetProperty("artifactLocation").GetProperty("uri").GetString()!;
        var file = Path.IsPathRooted(uri) ? uri : Path.GetFullPath(Path.Combine(projectDir, uri));
        int line = 0;
        int? column = null;
        if (physical.TryGetProperty("region", out var region))
        {
            if (region.TryGetProperty("startLine", out var l))
                line = l.GetInt32();
            if (region.TryGetProperty("startColumn", out var c))
                column = c.GetInt32();
        }
        return new LiveLocation(file, line, column, message);
    }
}
