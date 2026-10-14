// OX-02 (preregistration §5, K4): edit -> debounce -> one snapshot -> analyze -> publish only if
// that version is still the newest one issued. Independent of Visual Studio.
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace Owen.VisualStudio.Live
{
    /// <summary>
    /// Per-project request versions. A result is published only when its version is the latest
    /// one issued for its project, so an answer that arrives late — however late, in whatever
    /// order — can never replace a newer one (K4; mutation M1 drops this check).
    /// </summary>
    public sealed class LiveVersionGate
    {
        private readonly Dictionary<string, long> _issued = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);

        public long Issue(string key)
        {
            lock (_issued)
            {
                _issued.TryGetValue(key, out var last);
                _issued[key] = last + 1;
                return last + 1;
            }
        }

        public bool IsCurrent(string key, long version)
        {
            lock (_issued)
                return _issued.TryGetValue(key, out var last) && last == version;
        }
    }

    /// <summary>
    /// Trailing-edge debounce per project: every edit restarts the delay; when it expires the
    /// work runs once, for the text as it is then. Bursts coalesce into one analysis.
    /// </summary>
    public sealed class LiveDebouncer
    {
        private readonly TimeSpan _delay;
        private readonly Dictionary<string, CancellationTokenSource> _timers =
            new Dictionary<string, CancellationTokenSource>(StringComparer.OrdinalIgnoreCase);

        public LiveDebouncer(TimeSpan delay)
        {
            _delay = delay;
        }

        public void Schedule(string key, Func<Task> work)
        {
            CancellationTokenSource cts;
            lock (_timers)
            {
                if (_timers.TryGetValue(key, out var previous))
                    previous.Cancel();
                _timers[key] = cts = new CancellationTokenSource();
            }
            _ = RunAsync(key, cts, work);
        }

        private async Task RunAsync(string key, CancellationTokenSource cts, Func<Task> work)
        {
            try
            {
                await Task.Delay(_delay, cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            lock (_timers)
            {
                if (_timers.TryGetValue(key, out var current) && ReferenceEquals(current, cts))
                    _timers.Remove(key);
            }
            await work().ConfigureAwait(false);
        }
    }

    /// <summary>
    /// The coordinate contract (preregistration §6, gap 1): with a column, the span starts there;
    /// without one, it is the line without its leading and trailing whitespace. Returns 0-based
    /// [start, end) within the line, and the 1-based column shown. A coordinate, never a verdict.
    /// </summary>
    public static class LiveCoordinates
    {
        public static (int Start, int End, int Column) Span(string lineText, int? column)
        {
            var first = 0;
            while (first < lineText.Length && char.IsWhiteSpace(lineText[first]))
                first++;
            var end = lineText.Length;
            while (end > first && char.IsWhiteSpace(lineText[end - 1]))
                end--;
            var start = column is int c && c >= 1 && c - 1 < end ? c - 1 : first;
            if (end <= start)
                end = Math.Min(lineText.Length, start + 1);
            return (start, end, start + 1);
        }
    }
}
