// OX-02: the editor-independent heart of Owen.VisualStudio. An edit of a project schedules one
// analysis of a snapshot of it; the answer becomes entries (Error List rows and squiggle spans)
// only if it is still the newest. Knows no Owen extension: what is analysed is whatever the
// project's live request (obj/owen/live.txt, written by Owen.Build) names.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace Owen.VisualStudio.Live
{
    /// <summary>What an analysis is taken over: one project, as the editor has it right now.</summary>
    public sealed class LiveSnapshot
    {
        public LiveSnapshot(string key, string request, IReadOnlyList<LiveSource> documents,
            IReadOnlyList<LiveSource> generated, object? state = null)
        {
            Key = key;
            Request = request;
            Documents = documents;
            Generated = generated;
            State = state;
        }

        /// <summary>The project file: one analysis unit.</summary>
        public string Key { get; }

        /// <summary>The project's <c>obj/owen/live.txt</c>.</summary>
        public string Request { get; }

        public IReadOnlyList<LiveSource> Documents { get; }

        public IReadOnlyList<LiveSource> Generated { get; }

        /// <summary>The editor's own handle on this snapshot (VS: text snapshots, for mapping).</summary>
        public object? State { get; }

        /// <summary>The text of <paramref name="file"/> as analysed: the editor's, else the disk's.</summary>
        public string? TextOf(string file)
        {
            foreach (var d in Documents)
                if (string.Equals(Path.GetFullPath(d.Path), Path.GetFullPath(file), StringComparison.OrdinalIgnoreCase))
                    return d.Text;
            try
            {
                return File.Exists(file) ? File.ReadAllText(file) : null;
            }
            catch (IOException)
            {
                return null;
            }
        }
    }

    /// <summary>One thing to show: an Error List row (<see cref="Primary"/>) or a squiggle only.</summary>
    public sealed class LiveEntry
    {
        public string Code { get; set; } = "";

        public string Severity { get; set; } = "";

        public string Message { get; set; } = "";

        public string File { get; set; } = "";

        /// <summary>1-based; null for a file-level condition.</summary>
        public int? Line { get; set; }

        /// <summary>1-based column shown (the span's first character, preregistration §6).</summary>
        public int? Column { get; set; }

        /// <summary>0-based [start, end) within the line, for the squiggle.</summary>
        public int Start { get; set; }

        public int End { get; set; }

        /// <summary>True: the finding's own location (an Error List row and a squiggle). False: one
        /// of its witness steps (a squiggle carrying the step's message).</summary>
        public bool Primary { get; set; }

        public string Origin { get; set; } = "";

        public string Project { get; set; } = "";
    }

    public sealed class LivePublication
    {
        public LivePublication(string key, long version, IReadOnlyList<LiveEntry> entries, LiveSnapshot? snapshot,
            IReadOnlyDictionary<string, long> timing)
        {
            Key = key;
            Version = version;
            Entries = entries;
            Snapshot = snapshot;
            Timing = timing;
        }

        public string Key { get; }

        public long Version { get; }

        public IReadOnlyList<LiveEntry> Entries { get; }

        public LiveSnapshot? Snapshot { get; }

        public IReadOnlyDictionary<string, long> Timing { get; }
    }

    /// <summary>What answers an analysis: the supervised service, or a test double.</summary>
    public interface ILiveAnalyzer
    {
        Task<LiveResponse> AnalyzeAsync(string key, long version, string request,
            IReadOnlyList<LiveSource> documents, IReadOnlyList<LiveSource> generated);

        /// <summary>The operational condition to show, or null while healthy.</summary>
        string? Condition { get; }
    }

    public sealed class SupervisedAnalyzer : ILiveAnalyzer
    {
        private readonly LiveSupervisor _supervisor;

        public SupervisedAnalyzer(LiveSupervisor supervisor)
        {
            _supervisor = supervisor;
        }

        public string? Condition => _supervisor.Condition;

        public Task<LiveResponse> AnalyzeAsync(string key, long version, string request,
            IReadOnlyList<LiveSource> documents, IReadOnlyList<LiveSource> generated) =>
            _supervisor.AnalyzeAsync(key, version, request, documents, generated);
    }

    public sealed class LiveEngine
    {
        /// <summary>The code of Owen.VisualStudio's own operational row (the service stopped).</summary>
        public const string ServiceCode = "OWENV001";

        private readonly Func<string, Task<LiveSnapshot?>> _snapshot;
        private readonly Func<LiveSnapshot, ILiveAnalyzer?> _analyzer;
        private readonly Action<string> _log;
        private readonly LiveDebouncer _debouncer;
        private readonly LiveVersionGate _gate = new LiveVersionGate();

        /// <summary>Mutation M1 (preregistration §12): publish every answer, current or not.</summary>
        public bool IgnoreVersions { get; set; }

        public LiveEngine(Func<string, Task<LiveSnapshot?>> snapshot, Func<LiveSnapshot, ILiveAnalyzer?> analyzer,
            Action<string> log, TimeSpan debounce)
        {
            _snapshot = snapshot;
            _analyzer = analyzer;
            _log = log;
            _debouncer = new LiveDebouncer(debounce);
        }

        public event Action<LivePublication>? Published;

        /// <summary>An edit (or an open) of something in project <paramref name="key"/>.</summary>
        public void OnEdit(string key) => _debouncer.Schedule(key, () => AnalyzeNowAsync(key));

        /// <summary>Take the snapshot and analyse it now (the debounce's trailing edge).</summary>
        public async Task AnalyzeNowAsync(string key)
        {
            LiveSnapshot? snapshot;
            try
            {
                snapshot = await _snapshot(key).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _log("owen: snapshot of " + key + " failed: " + ex);
                return;
            }
            if (snapshot == null)
            {
                // no live request: Owen is not active in this project; show nothing for it
                Publish(new LivePublication(key, _gate.Issue(key), Array.Empty<LiveEntry>(), null, new Dictionary<string, long>()));
                return;
            }
            var version = _gate.Issue(key);
            await RunAsync(snapshot, version).ConfigureAwait(false);
        }

        /// <summary>Analyse a snapshot under an already-issued version (tests drive this directly).</summary>
        public long Issue(string key) => _gate.Issue(key);

        public async Task RunAsync(LiveSnapshot snapshot, long version)
        {
            var analyzer = _analyzer(snapshot);
            if (analyzer == null)
                return;
            LiveResponse response;
            try
            {
                response = await analyzer.AnalyzeAsync(snapshot.Key, version, snapshot.Request,
                    snapshot.Documents, snapshot.Generated).ConfigureAwait(false);
            }
            catch (LiveServiceDiedException ex)
            {
                _log("owen: " + ex.Message);
                if (IgnoreVersions || _gate.IsCurrent(snapshot.Key, version))
                    Publish(new LivePublication(snapshot.Key, version, new[] { Operational(snapshot.Key, ex.Message) },
                        snapshot, new Dictionary<string, long>()));
                return;
            }
            if (response.Status != "ok" && response.Status != "error")
                return;   // superseded/cancelled: a newer request is on its way
            if (!IgnoreVersions && !_gate.IsCurrent(snapshot.Key, response.Version))
            {
                _log("owen: dropped the answer for version " + response.Version + " of " + snapshot.Key + " (stale)");
                return;
            }
            var entries = Entries(response, snapshot);
            if (analyzer.Condition is string condition)
                entries.Insert(0, Operational(snapshot.Key, condition));
            Publish(new LivePublication(snapshot.Key, response.Version, entries, snapshot, response.Timing));
        }

        private void Publish(LivePublication publication) => Published?.Invoke(publication);

        public static LiveEntry Operational(string key, string message) => new LiveEntry
        {
            Code = ServiceCode,
            Severity = "warning",
            Message = "Owen live analysis: " + message,
            File = key,
            Primary = true,
            Origin = "host",
            Project = Path.GetFileNameWithoutExtension(key),
        };

        /// <summary>The service's diagnostics as entries, with spans per the coordinate contract.</summary>
        public static List<LiveEntry> Entries(LiveResponse response, LiveSnapshot snapshot)
        {
            var project = Path.GetFileNameWithoutExtension(snapshot.Key);
            var texts = new Dictionary<string, string[]?>(StringComparer.OrdinalIgnoreCase);
            string[]? Lines(string file)
            {
                if (!texts.TryGetValue(file, out var lines))
                    texts[file] = lines = snapshot.TextOf(file)?.Replace("\r\n", "\n").Split('\n');
                return lines;
            }
            LiveEntry Entry(LiveDiagnostic d, string file, int? line, int? column, string message, bool primary)
            {
                var entry = new LiveEntry
                {
                    Code = d.Code,
                    Severity = d.Severity,
                    Message = message,
                    File = file,
                    Line = line is int l && l >= 1 ? l : (int?)null,
                    Column = column,
                    Primary = primary,
                    Origin = d.Origin,
                    Project = project,
                };
                if (entry.Line is int n && Lines(file) is string[] all && n <= all.Length)
                {
                    var (start, end, shown) = LiveCoordinates.Span(all[n - 1], column);
                    entry.Start = start;
                    entry.End = end;
                    entry.Column = shown;
                }
                return entry;
            }

            var entries = new List<LiveEntry>();
            foreach (var d in response.Diagnostics)
            {
                entries.Add(Entry(d, d.File, d.Line, d.Column, d.Message, primary: true));
                foreach (var r in d.Related)
                {
                    if (string.Equals(r.File, d.File, StringComparison.OrdinalIgnoreCase) && r.Line == d.Line)
                        continue;   // the finding's own line already carries the squiggle
                    var step = r.Message is string m && m.Length > 0 ? m + " — " + d.Message : d.Message;
                    entries.Add(Entry(d, r.File, r.Line, r.Column, step, primary: false));
                }
            }
            return entries;
        }
    }
}
