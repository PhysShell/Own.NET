// usage: LiveClientTests [<ownsharp.dll> <live.txt>]   (the service tests need both)
using System.Diagnostics;
using Owen.VisualStudio.Live;

var failures = new List<string>();
var passed = 0;
void Check(string name, bool holds, string detail)
{
    Console.WriteLine($"{(holds ? "ok" : "FAIL")}[{name}]: {detail}");
    if (holds) passed++; else failures.Add(name);
}

// ---- coordinates (preregistration §6; mutation M3 moves them) ------------------------------
{
    var (s, e, c) = LiveCoordinates.Span("            draft.Submit(now);  ", null);
    Check("coord-no-column", (s, e, c) == (12, 30, 13), $"trimmed line -> [{s},{e}) column {c}");
    (s, e, c) = LiveCoordinates.Span("    x = y;", 9);
    Check("coord-column", (s, e, c) == (8, 10, 9), $"column 9 -> [{s},{e}) column {c}");
    (s, e, c) = LiveCoordinates.Span("", null);
    Check("coord-empty", (s, e, c) == (0, 0, 1), $"empty line -> [{s},{e}) column {c}");
}

// ---- the entries a response becomes ---------------------------------------------------------
{
    var file = Path.Combine(Path.GetTempPath(), "Use.cs");
    var text = "a\nb\n  region(x, d =>\n  {\n    d.Go();\n    d.Go();\n  });\n";
    var snapshot = new LiveSnapshot("/p/P.csproj", "/p/obj/owen/live.txt", [new LiveSource(file, text)], []);
    var response = new LiveResponse
    {
        Status = "ok",
        Diagnostics =
        [
            new LiveDiagnostic
            {
                Code = "OWN002", Severity = "warning", Message = "used after", File = file, Line = 3, Origin = "core",
                Related = [new LiveLocation { File = file, Line = 3, Message = "acquired here" },
                           new LiveLocation { File = file, Line = 6, Message = "used here" }],
            },
        ],
    };
    var entries = LiveEngine.Entries(response, snapshot);
    var primary = entries.Where(x => x.Primary).ToList();
    var witness = entries.Where(x => !x.Primary).ToList();
    Check("entries-one-row", primary.Count == 1 && primary[0].Line == 3 && primary[0].Column == 3,
        $"one Error List row at the core's location: {string.Join(", ", primary.Select(p => $"{p.Line}:{p.Column}"))}");
    Check("entries-witness-squiggle", witness.Count == 1 && witness[0].Line == 6 && witness[0].Start == 4 && witness[0].End == 11
        && witness[0].Message.StartsWith("used here", StringComparison.Ordinal),
        $"the witness step on line 6 is a squiggle only: {string.Join(", ", witness.Select(w => $"{w.Line}[{w.Start},{w.End}) '{w.Message}'"))}");
}

// ---- K4: a late answer never replaces a newer one -------------------------------------------
async Task<List<long>> RaceAsync(bool ignoreVersions)
{
    var published = new List<long>();
    var analyzer = new FakeAnalyzer();
    var engine = new LiveEngine(_ => Task.FromResult<LiveSnapshot?>(null), _ => analyzer, _ => { }, TimeSpan.FromMilliseconds(10))
    {
        IgnoreVersions = ignoreVersions,
    };
    engine.Published += p => { lock (published) published.Add(p.Version); };
    var snap = new LiveSnapshot("K", "R", [], []);
    var v1 = engine.Issue("K");
    var v2 = engine.Issue("K");
    analyzer.Delays[v1] = 400;   // N answers after N+1
    analyzer.Delays[v2] = 10;
    await Task.WhenAll(engine.RunAsync(snap, v1), engine.RunAsync(snap, v2));
    return published;
}
{
    var published = await RaceAsync(ignoreVersions: false);
    Check("K4-stale-dropped", published.SequenceEqual([2L]), $"published versions: [{string.Join(", ", published)}] (version 1 answered last)");
    var mutated = await RaceAsync(ignoreVersions: true);
    Check("K4-M1-control", mutated.LastOrDefault() == 1,
        $"with the version check removed (M1) the stale answer is published last: [{string.Join(", ", mutated)}]");
}

// ---- bursts coalesce -------------------------------------------------------------------------
{
    var snapshots = 0;
    var engine = new LiveEngine(_ => { Interlocked.Increment(ref snapshots); return Task.FromResult<LiveSnapshot?>(null); },
        _ => null, _ => { }, TimeSpan.FromMilliseconds(250));
    for (var i = 0; i < 20; i++)
    {
        engine.OnEdit("K");
        await Task.Delay(30);
    }
    await Task.Delay(600);
    Check("burst-coalesced", snapshots is >= 1 and <= 2, $"20 edits 30 ms apart -> {snapshots} analysis snapshot(s)");
}

// ---- the real service: death, restart, budget (K6), a service that cannot start (M2) --------
if (args.Length >= 2)
{
    var host = Path.GetFullPath(args[0]);
    var request = Path.GetFullPath(args[1]);
    var dotnet = Process.GetCurrentProcess().MainModule!.FileName;
    var log = new List<string>();
    var clock = DateTime.UtcNow;
    using var supervisor = new LiveSupervisor(dotnet, host, l => { lock (log) log.Add(l); }, () => clock);
    var key = File.ReadAllLines(request).First(l => l.StartsWith("project\t", StringComparison.Ordinal))[8..];
    var first = await supervisor.AnalyzeAsync(key, 1, request, [], []);
    var pid1 = supervisor.ProcessId;
    Check("service-answers", first.Status == "ok", $"status {first.Status}, {first.Diagnostics.Count} diagnostic(s), pid {pid1}");

    supervisor.KillService();
    await Task.Delay(1000);
    Check("K6-death-shown", supervisor.Condition is string c1 && c1.Contains("exited", StringComparison.Ordinal),
        $"condition after a crash: {supervisor.Condition}");
    var engine = new LiveEngine(_ => Task.FromResult<LiveSnapshot?>(null), _ => new SupervisedAnalyzer(supervisor), _ => { }, TimeSpan.Zero);
    var rows = new List<LiveEntry>();
    engine.Published += p => rows.AddRange(p.Entries);
    var snap = new LiveSnapshot(key, request, [], []);
    await engine.RunAsync(snap, engine.Issue(key));
    var pid2 = supervisor.ProcessId;
    Check("K6-restarted", pid2 != pid1 && supervisor.Condition is null, $"the next request restarted it (pid {pid1} -> {pid2}); condition {supervisor.Condition ?? "cleared"}");

    for (var i = 0; i < 3; i++)
    {
        supervisor.KillService();
        await Task.Delay(800);
        try { await supervisor.AnalyzeAsync(key, 10 + i, request, [], []); } catch (LiveServiceDiedException) { }
    }
    supervisor.KillService();
    await Task.Delay(800);
    rows.Clear();
    await engine.RunAsync(snap, engine.Issue(key));
    Check("K6-budget", supervisor.GaveUp && rows.Count == 1 && rows[0].Code == LiveEngine.ServiceCode
        && rows[0].Message.Contains("off until the solution is reopened", StringComparison.Ordinal),
        $"after {LiveSupervisor.MaxRestarts} restarts in the window: gave up={supervisor.GaveUp}, row: {rows.FirstOrDefault()?.Code} '{rows.FirstOrDefault()?.Message}'");

    using var broken = new LiveSupervisor(dotnet, host + ".missing", _ => { });
    var brokenEngine = new LiveEngine(_ => Task.FromResult<LiveSnapshot?>(null), _ => new SupervisedAnalyzer(broken), _ => { }, TimeSpan.Zero);
    var brokenRows = new List<LiveEntry>();
    brokenEngine.Published += p => brokenRows.AddRange(p.Entries);
    await brokenEngine.RunAsync(snap, brokenEngine.Issue(key));
    Check("M2-cannot-start", brokenRows.Count == 1 && brokenRows[0].Code == LiveEngine.ServiceCode,
        $"a service that cannot start is one visible row: {brokenRows.FirstOrDefault()?.Code} '{brokenRows.FirstOrDefault()?.Message}'");
}
else
{
    Console.WriteLine("skip[service]: no ownsharp.dll / live.txt given");
}

Console.WriteLine($"live client tests: {passed} passed, {failures.Count} failed");
return failures.Count == 0 ? 0 : 1;

sealed class FakeAnalyzer : ILiveAnalyzer
{
    public Dictionary<long, int> Delays { get; } = [];

    public string? Condition => null;

    public async Task<LiveResponse> AnalyzeAsync(string key, long version, string request,
        IReadOnlyList<LiveSource> documents, IReadOnlyList<LiveSource> generated)
    {
        await Task.Delay(Delays.TryGetValue(version, out var d) ? d : 0);
        return new LiveResponse { Key = key, Version = version, Status = "ok" };
    }
}
