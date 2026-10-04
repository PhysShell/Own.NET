// OX-02: where Owen.VisualStudio's own words go. The "Owen" output pane (the service's stderr
// included: never discarded), and an opt-in machine-readable trace for the real-IDE acceptance
// run (OWEN_LIVE_TRACE=<file>): what was published, which tags the tagger produced on which text
// version, and how long each UI-thread handler took. The trace never changes behaviour.
using System;
using System.Diagnostics;
using System.IO;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.Interop;
using Newtonsoft.Json;

namespace Owen.VisualStudio
{
    internal static class OwenLog
    {
        private static readonly Guid PaneId = new Guid("a6b1a0f4-2c55-4e43-9a8b-9d0f2b8e5f31");
        private static IVsOutputWindowPane? _pane;
        private static bool _creating;

        public static void Write(string line)
        {
            OwenTrace.Event("log", new { line });
            var pane = _pane;
            if (pane != null)
            {
                pane.OutputStringThreadSafe(line + Environment.NewLine);
                return;
            }
            if (_creating)
                return;
            _creating = true;
            _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () =>
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                if (Package.GetGlobalService(typeof(SVsOutputWindow)) is IVsOutputWindow window)
                {
                    var id = PaneId;
                    window.CreatePane(ref id, "Owen", 1, 0);
                    window.GetPane(ref id, out _pane);
                }
                _pane?.OutputStringThreadSafe(line + Environment.NewLine);
            });
        }
    }

    internal static class OwenTrace
    {
        private static readonly string? Path = Environment.GetEnvironmentVariable("OWEN_LIVE_TRACE");
        private static readonly object Gate = new object();
        private static double _uiMax;

        public static void Event(string kind, object data)
        {
            if (Path == null)
                return;
            var line = JsonConvert.SerializeObject(new
            {
                t = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                kind,
                data,
            });
            lock (Gate)
                File.AppendAllText(Path, line + "\n");
        }

        /// <summary>A UI-thread handler's duration; traced when it sets a new maximum.</summary>
        public static void Ui(string handler, double ms)
        {
            if (Path == null || ms <= _uiMax)
                return;
            _uiMax = ms;
            Event("ui", new { handler, ms, pid = Process.GetCurrentProcess().Id });
        }
    }
}
