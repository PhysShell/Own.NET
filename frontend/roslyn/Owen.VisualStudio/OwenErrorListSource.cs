// OX-02: Owen's Error List rows — one ITableDataSource on the standard errors table, one table
// snapshot per project, replaced whole on every publication. The pattern is the VSSDK ErrorList
// sample's (nothing copied). Rows carry DocumentName/Line/Column, which is what the Error List
// navigates by on a double-click.
using System;
using System.Collections.Generic;
using Microsoft.VisualStudio.Shell.Interop;
using Microsoft.VisualStudio.Shell.TableControl;
using Microsoft.VisualStudio.Shell.TableManager;
using Owen.VisualStudio.Live;

namespace Owen.VisualStudio
{
    internal sealed class OwenErrorListSource : ITableDataSource
    {
        private readonly List<ITableDataSink> _sinks = new List<ITableDataSink>();
        private readonly Dictionary<string, OwenEntriesSnapshot> _snapshots =
            new Dictionary<string, OwenEntriesSnapshot>(StringComparer.OrdinalIgnoreCase);
        private int _version;

        public OwenErrorListSource(ITableManager manager)
        {
            manager.AddSource(this,
                StandardTableColumnDefinitions.ErrorSeverity,
                StandardTableColumnDefinitions.ErrorCode,
                StandardTableColumnDefinitions.Text,
                StandardTableColumnDefinitions.ProjectName,
                StandardTableColumnDefinitions.DocumentName,
                StandardTableColumnDefinitions.Line,
                StandardTableColumnDefinitions.Column,
                StandardTableColumnDefinitions.BuildTool,
                StandardTableColumnDefinitions.ErrorSource);
        }

        public string SourceTypeIdentifier => StandardTableDataSources.ErrorTableDataSource;

        public string Identifier => "Owen";

        public string DisplayName => "Owen";

        public IDisposable Subscribe(ITableDataSink sink)
        {
            lock (_sinks)
            {
                _sinks.Add(sink);
                foreach (var s in _snapshots.Values)
                    sink.AddSnapshot(s);
            }
            return new Unsubscriber(this, sink);
        }

        public void Publish(string key, IReadOnlyList<LiveEntry> rows)
        {
            lock (_sinks)
            {
                _snapshots.TryGetValue(key, out var old);
                var next = new OwenEntriesSnapshot(rows, ++_version);
                _snapshots[key] = next;
                foreach (var sink in _sinks)
                {
                    if (old != null)
                        sink.ReplaceSnapshot(old, next);
                    else
                        sink.AddSnapshot(next);
                }
            }
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly OwenErrorListSource _source;
            private readonly ITableDataSink _sink;

            public Unsubscriber(OwenErrorListSource source, ITableDataSink sink)
            {
                _source = source;
                _sink = sink;
            }

            public void Dispose()
            {
                lock (_source._sinks)
                    _source._sinks.Remove(_sink);
            }
        }
    }

    internal sealed class OwenEntriesSnapshot : TableEntriesSnapshotBase
    {
        private readonly IReadOnlyList<LiveEntry> _rows;
        private readonly int _version;

        public OwenEntriesSnapshot(IReadOnlyList<LiveEntry> rows, int version)
        {
            _rows = rows;
            _version = version;
        }

        public override int Count => _rows.Count;

        public override int VersionNumber => _version;

        public override bool TryGetValue(int index, string keyName, out object? content)
        {
            content = null;
            if (index < 0 || index >= _rows.Count)
                return false;
            var row = _rows[index];
            switch (keyName)
            {
                case StandardTableKeyNames.ErrorSeverity:
                    content = row.Severity == "error" ? __VSERRORCATEGORY.EC_ERROR : __VSERRORCATEGORY.EC_WARNING;
                    return true;
                case StandardTableKeyNames.ErrorCode:
                    content = row.Code;
                    return true;
                case StandardTableKeyNames.Text:
                    content = row.Message;
                    return true;
                case StandardTableKeyNames.ProjectName:
                    content = row.Project;
                    return true;
                case StandardTableKeyNames.DocumentName:
                    content = row.File;
                    return true;
                case StandardTableKeyNames.Line:
                    // 0-based in the table; a file-level row has no line
                    content = row.Line is int line ? line - 1 : -1;
                    return row.Line != null;
                case StandardTableKeyNames.Column:
                    content = row.Column is int column ? column - 1 : 0;
                    return row.Line != null;
                case StandardTableKeyNames.BuildTool:
                    content = "Owen";
                    return true;
                case StandardTableKeyNames.ErrorSource:
                    content = ErrorSource.Other;
                    return true;
                default:
                    return false;
            }
        }
    }
}
