// OX-02: the one MEF part that connects Visual Studio's Roslyn workspace to LiveEngine. It knows
// no Owen extension. For a project it sends the service the unsaved text of the project's open
// documents and its source-generated documents, exactly as the workspace holds them now.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel.Composition;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Text;
using Microsoft.VisualStudio.LanguageServices;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.TableManager;
using Microsoft.VisualStudio.Text;
using Owen.VisualStudio.Live;

namespace Owen.VisualStudio
{
    /// <summary>What a published entry needs in the editor: where it is now.</summary>
    internal sealed class PlacedEntry
    {
        public PlacedEntry(LiveEntry entry, ITrackingSpan? span)
        {
            Entry = entry;
            Span = span;
        }

        public LiveEntry Entry { get; }

        /// <summary>The squiggle's span on the text the analysis read, tracked forward; null when
        /// that text was not an editor buffer (then the line is located on the current text).</summary>
        public ITrackingSpan? Span { get; }
    }

    [Export(typeof(OwenLiveMonitor))]
    [PartCreationPolicy(CreationPolicy.Shared)]
    internal sealed class OwenLiveMonitor
    {
        private readonly VisualStudioWorkspace _workspace;
        private readonly OwenErrorListSource _errorList;
        private readonly LiveEngine _engine;
        private readonly ConcurrentDictionary<string, LiveSupervisor> _supervisors =
            new ConcurrentDictionary<string, LiveSupervisor>(StringComparer.OrdinalIgnoreCase);
        // project -> what its newest publication placed
        private readonly ConcurrentDictionary<string, IReadOnlyList<PlacedEntry>> _placed =
            new ConcurrentDictionary<string, IReadOnlyList<PlacedEntry>>(StringComparer.OrdinalIgnoreCase);

        [ImportingConstructor]
        public OwenLiveMonitor(VisualStudioWorkspace workspace, ITableManagerProvider tables)
        {
            _workspace = workspace;
            _errorList = new OwenErrorListSource(tables.GetTableManager(StandardTables.ErrorsTable));
            _engine = new LiveEngine(SnapshotAsync, AnalyzerFor, OwenLog.Write, TimeSpan.FromMilliseconds(250));
            _engine.Published += OnPublished;
            _workspace.WorkspaceChanged += OnWorkspaceChanged;
            OwenLog.Write("Owen live analysis loaded");
        }

        /// <summary>A file's entries changed (its tagger re-reads them).</summary>
        public event Action<string>? FileChanged;

        public IReadOnlyList<PlacedEntry> EntriesFor(string file)
        {
            var full = Path.GetFullPath(file);
            return _placed.Values.SelectMany(p => p)
                .Where(p => string.Equals(Path.GetFullPath(p.Entry.File), full, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }

        /// <summary>An editor opened <paramref name="file"/>: analyse its project.</summary>
        public void Opened(string file)
        {
            var key = ProjectOf(file);
            if (key != null)
                _engine.OnEdit(key);
        }

        private string? ProjectOf(string file)
        {
            var solution = _workspace.CurrentSolution;
            foreach (var id in solution.GetDocumentIdsWithFilePath(file))
                if (solution.GetProject(id.ProjectId)?.FilePath is string path)
                    return path;
            return null;
        }

        private void OnWorkspaceChanged(object sender, WorkspaceChangeEventArgs e)
        {
            switch (e.Kind)
            {
                case WorkspaceChangeKind.DocumentChanged:
                case WorkspaceChangeKind.DocumentAdded:
                case WorkspaceChangeKind.DocumentRemoved:
                case WorkspaceChangeKind.DocumentReloaded:
                case WorkspaceChangeKind.ProjectChanged:
                case WorkspaceChangeKind.ProjectAdded:
                case WorkspaceChangeKind.ProjectReloaded:
                    if (e.ProjectId != null && e.NewSolution.GetProject(e.ProjectId)?.FilePath is string key
                        && HasOpenDocument(e.NewSolution.GetProject(e.ProjectId)!))
                    {
                        OwenTrace.Event("edit", new { key, kind = e.Kind.ToString() });
                        _engine.OnEdit(key);
                    }
                    break;
            }
        }

        private bool HasOpenDocument(Project project) => project.DocumentIds.Any(_workspace.IsDocumentOpen);

        private async Task<LiveSnapshot?> SnapshotAsync(string key)
        {
            var request = LiveRequestFile.For(key);
            if (LiveRequestFile.TryRead(request) == null)
            {
                OwenTrace.Event("no-request", new { key, request });
                return null;
            }
            var project = _workspace.CurrentSolution.Projects.FirstOrDefault(
                p => string.Equals(p.FilePath, key, StringComparison.OrdinalIgnoreCase));
            if (project == null)
                return null;
            var documents = new List<LiveSource>();
            var texts = new Dictionary<string, SourceText>(StringComparer.OrdinalIgnoreCase);
            foreach (var document in project.Documents)
            {
                if (document.FilePath == null || !_workspace.IsDocumentOpen(document.Id))
                    continue;
                var text = await document.GetTextAsync().ConfigureAwait(false);
                texts[Path.GetFullPath(document.FilePath)] = text;
                documents.Add(new LiveSource(document.FilePath, text.ToString()));
            }
            var generated = new List<LiveSource>();
            foreach (var document in await project.GetSourceGeneratedDocumentsAsync().ConfigureAwait(false))
            {
                if (document.FilePath == null)
                    continue;
                var text = await document.GetTextAsync().ConfigureAwait(false);
                generated.Add(new LiveSource(document.FilePath, text.ToString()));
            }
            OwenTrace.Event("snapshot", new
            {
                key,
                documents = documents.Select(d => d.Path),
                generated = generated.Select(g => g.Path),
            });
            return new LiveSnapshot(key, request, documents, generated, texts);
        }

        private ILiveAnalyzer? AnalyzerFor(LiveSnapshot snapshot)
        {
            var request = LiveRequestFile.TryRead(snapshot.Request);
            if (request == null)
                return null;
            var supervisor = _supervisors.GetOrAdd(request.Host, host =>
            {
                var s = new LiveSupervisor(Dotnet(request), host, OwenLog.Write);
                s.ConditionChanged += _ => OwenTrace.Event("service", new { host, condition = s.Condition, gave_up = s.GaveUp });
                return s;
            });
            return new SupervisedAnalyzer(supervisor);
        }

        /// <summary>The muxer: the one MSBuild named, else the machine's, else PATH's.</summary>
        private static string Dotnet(LiveRequestFile request)
        {
            if (request.Dotnet != null && File.Exists(request.Dotnet))
                return request.Dotnet;
            var programFiles = Environment.GetEnvironmentVariable("ProgramW6432")
                ?? Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var machine = Path.Combine(programFiles, "dotnet", "dotnet.exe");
            return File.Exists(machine) ? machine : "dotnet";
        }

        private void OnPublished(LivePublication publication)
        {
            var texts = publication.Snapshot?.State as Dictionary<string, SourceText>;
            var placed = new List<PlacedEntry>();
            foreach (var entry in publication.Entries)
            {
                ITrackingSpan? span = null;
                if (entry.Line is int line && texts != null
                    && texts.TryGetValue(Path.GetFullPath(entry.File), out var text)
                    && text.FindCorrespondingEditorTextSnapshot() is ITextSnapshot snapshot
                    && line <= snapshot.LineCount)
                {
                    var l = snapshot.GetLineFromLineNumber(line - 1);
                    var start = Math.Min(l.Start.Position + entry.Start, l.End.Position);
                    var end = Math.Max(start, Math.Min(l.Start.Position + entry.End, l.End.Position));
                    span = snapshot.CreateTrackingSpan(Span.FromBounds(start, end), SpanTrackingMode.EdgeExclusive);
                }
                placed.Add(new PlacedEntry(entry, span));
            }

            var files = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (_placed.TryGetValue(publication.Key, out var old))
                foreach (var p in old)
                    files.Add(Path.GetFullPath(p.Entry.File));
            foreach (var p in placed)
                files.Add(Path.GetFullPath(p.Entry.File));
            _placed[publication.Key] = placed;

            _errorList.Publish(publication.Key, publication.Entries.Where(e => e.Primary).ToList());
            OwenTrace.Event("publish", new
            {
                key = publication.Key,
                version = publication.Version,
                timing = publication.Timing,
                entries = publication.Entries.Select(e => new
                {
                    code = e.Code, severity = e.Severity, file = e.File, line = e.Line, column = e.Column,
                    start = e.Start, end = e.End, primary = e.Primary, message = e.Message,
                }),
            });
            foreach (var file in files)
                FileChanged?.Invoke(file);
        }
    }
}
