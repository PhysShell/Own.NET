// OX-02: Owen's squiggles. One tagger per C# buffer; it shows what OwenLiveMonitor published for
// the buffer's file — the finding's own span and its witness steps — mapped onto the current text.
using System;
using System.Collections.Generic;
using System.ComponentModel.Composition;
using System.Diagnostics;
using System.Linq;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Text;
using Microsoft.VisualStudio.Text.Adornments;
using Microsoft.VisualStudio.Text.Tagging;
using Microsoft.VisualStudio.Utilities;
using Owen.VisualStudio.Live;

namespace Owen.VisualStudio
{
    [Export(typeof(ITaggerProvider))]
    [ContentType("CSharp")]
    [TagType(typeof(IErrorTag))]
    internal sealed class OwenErrorTaggerProvider : ITaggerProvider
    {
        [Import]
        internal OwenLiveMonitor Monitor { get; set; } = null!;

        public ITagger<T>? CreateTagger<T>(ITextBuffer buffer)
            where T : ITag
        {
            if (!buffer.Properties.TryGetProperty(typeof(ITextDocument), out ITextDocument document))
                return null;
            return buffer.Properties.GetOrCreateSingletonProperty(
                typeof(OwenErrorTagger), () => new OwenErrorTagger(buffer, document, Monitor)) as ITagger<T>;
        }
    }

    internal sealed class OwenErrorTagger : ITagger<IErrorTag>
    {
        private readonly ITextBuffer _buffer;
        private readonly ITextDocument _document;
        private readonly OwenLiveMonitor _monitor;
        private string _lastTrace = "";

        public OwenErrorTagger(ITextBuffer buffer, ITextDocument document, OwenLiveMonitor monitor)
        {
            _buffer = buffer;
            _document = document;
            _monitor = monitor;
            _monitor.FileChanged += OnFileChanged;
            _monitor.Opened(document.FilePath);
        }

        public event EventHandler<SnapshotSpanEventArgs>? TagsChanged;

        private void OnFileChanged(string file)
        {
            if (!string.Equals(System.IO.Path.GetFullPath(file), System.IO.Path.GetFullPath(_document.FilePath),
                    StringComparison.OrdinalIgnoreCase))
                return;
            // Publications arrive on a background thread; the editor's tag aggregators expect
            // TagsChanged on the UI thread.
            _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () =>
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                try
                {
                    var snapshot = _buffer.CurrentSnapshot;
                    TagsChanged?.Invoke(this, new SnapshotSpanEventArgs(new SnapshotSpan(snapshot, 0, snapshot.Length)));
                }
                catch (Exception ex)
                {
                    OwenTrace.Event("error", new { where = "TagsChanged", error = ex.ToString() });
                }
            });
        }

        public IEnumerable<ITagSpan<IErrorTag>> GetTags(NormalizedSnapshotSpanCollection spans)
        {
            try
            {
                return Tags(spans);
            }
            catch (Exception ex)
            {
                // a tagger that throws is switched off by the editor: report, show nothing this time
                OwenTrace.Event("error", new { where = "GetTags", error = ex.ToString() });
                OwenLog.Write("Owen: squiggles failed: " + ex.Message);
                return Array.Empty<ITagSpan<IErrorTag>>();
            }
        }

        private IEnumerable<ITagSpan<IErrorTag>> Tags(NormalizedSnapshotSpanCollection spans)
        {
            if (spans.Count == 0)
                return Array.Empty<ITagSpan<IErrorTag>>();
            var clock = Stopwatch.StartNew();
            var snapshot = spans[0].Snapshot;
            var tags = new List<ITagSpan<IErrorTag>>();
            var traced = new List<object>();
            foreach (var placed in _monitor.EntriesFor(_document.FilePath))
            {
                var span = Locate(placed, snapshot);
                if (span is not SnapshotSpan s)
                    continue;
                var entry = placed.Entry;
                var type = entry.Severity == "error" ? PredefinedErrorTypeNames.SyntaxError : PredefinedErrorTypeNames.Warning;
                var tip = entry.Code + ": " + entry.Message;
                traced.Add(new
                {
                    code = entry.Code,
                    primary = entry.Primary,
                    line = s.Start.GetContainingLine().LineNumber + 1,
                    column = s.Start.Position - s.Start.GetContainingLine().Start.Position + 1,
                    length = s.Length,
                    text = s.GetText(),
                });
                if (spans.IntersectsWith(new NormalizedSnapshotSpanCollection(s)))
                    tags.Add(new TagSpan<IErrorTag>(s, new ErrorTag(type, tip)));
            }
            var key = snapshot.Version.VersionNumber + "|" + string.Join(";", traced.Select(t => t.ToString()));
            if (key != _lastTrace)
            {
                _lastTrace = key;
                OwenTrace.Event("tags", new { file = _document.FilePath, snapshot = snapshot.Version.VersionNumber, tags = traced });
            }
            OwenTrace.Ui("GetTags", clock.Elapsed.TotalMilliseconds);
            return tags;
        }

        private static SnapshotSpan? Locate(PlacedEntry placed, ITextSnapshot snapshot)
        {
            if (placed.Span != null)
            {
                if (placed.Span.TextBuffer != snapshot.TextBuffer)
                    return null;
                var s = placed.Span.GetSpan(snapshot);
                return s.Length > 0 ? s : (SnapshotSpan?)null;   // the text it named was deleted
            }
            if (placed.Entry.Line is not int line || line > snapshot.LineCount)
                return null;
            var l = snapshot.GetLineFromLineNumber(line - 1);
            var start = Math.Min(l.Start.Position + placed.Entry.Start, l.End.Position);
            var end = Math.Max(start, Math.Min(l.Start.Position + placed.Entry.End, l.End.Position));
            return end > start ? new SnapshotSpan(snapshot, Span.FromBounds(start, end)) : (SnapshotSpan?)null;
        }
    }
}
