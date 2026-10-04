// OX-02 (preregistration §4, K6): the long-lived `owen serve` child, and the policy that keeps
// it honest. Independent of Visual Studio.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace Owen.VisualStudio.Live
{
    /// <summary>The service process is gone (or never came up): its exit code and last stderr.</summary>
    public sealed class LiveServiceDiedException : Exception
    {
        public LiveServiceDiedException(string message)
            : base(message)
        {
        }
    }

    /// <summary>
    /// One <c>dotnet exec &lt;Owen.Build&gt;/ownsharp.dll serve</c> process. Requests are framed on its
    /// stdin, answers read from its stdout and matched by id; its stderr is kept (the last lines
    /// go into the failure message, every line to <see cref="Log"/>), never discarded. When the
    /// process ends, every pending request fails with <see cref="LiveServiceDiedException"/>.
    /// </summary>
    public sealed class LiveService : IDisposable
    {
        private readonly Process _process;
        private readonly Stream _stdin;
        private readonly object _writeGate = new object();
        private readonly ConcurrentDictionary<long, TaskCompletionSource<LiveResponse>> _pending =
            new ConcurrentDictionary<long, TaskCompletionSource<LiveResponse>>();
        private readonly Queue<string> _stderrTail = new Queue<string>();
        private readonly TaskCompletionSource<JObject> _hello = new TaskCompletionSource<JObject>();
        private long _nextId;
        private string? _death;

        private LiveService(Process process, Action<string> log)
        {
            _process = process;
            Log = log;
            _stdin = process.StandardInput.BaseStream;
        }

        public Action<string> Log { get; }

        public int ProcessId => _process.Id;

        public bool IsAlive => _death == null && !_process.HasExited;

        /// <summary>Why the service is gone, once it is.</summary>
        public string? Death => _death;

        public event Action<LiveService>? Died;

        /// <summary>Start the service and complete the owen-live/1 handshake.</summary>
        public static async Task<LiveService> StartAsync(string dotnet, string hostDll, Action<string> log,
            TimeSpan handshakeTimeout)
        {
            if (!File.Exists(hostDll))
                throw new LiveServiceDiedException("the Owen service '" + hostDll + "' does not exist (restore the project, or update Owen.Build)");
            var psi = new ProcessStartInfo(dotnet, "exec \"" + hostDll + "\" serve")
            {
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            psi.EnvironmentVariables["DOTNET_ROLL_FORWARD"] = "Major";
            Process process;
            try
            {
                process = Process.Start(psi) ?? throw new LiveServiceDiedException("the Owen service did not start");
            }
            catch (System.ComponentModel.Win32Exception ex)
            {
                throw new LiveServiceDiedException("the Owen service could not be started with '" + dotnet + "': " + ex.Message);
            }
            ChildProcessGuard.Attach(process);
            var service = new LiveService(process, log);
            service.Run();
            LiveFrames.Write(service._stdin, LiveFrames.Hello());
            var done = await Task.WhenAny(service._hello.Task, Task.Delay(handshakeTimeout)).ConfigureAwait(false);
            if (done != service._hello.Task)
            {
                service.Kill();
                throw new LiveServiceDiedException("the Owen service did not answer hello within " + handshakeTimeout.TotalSeconds + " s");
            }
            var hello = await service._hello.Task.ConfigureAwait(false);
            if ((string?)hello["protocol"] != LiveFrames.Protocol)
            {
                service.Kill();
                throw new LiveServiceDiedException("the Owen service speaks '" + hello["protocol"] + "', not " + LiveFrames.Protocol);
            }
            return service;
        }

        public Task<LiveResponse> AnalyzeAsync(string key, long version, string request,
            IEnumerable<LiveSource> documents, IEnumerable<LiveSource> generated)
        {
            var id = Interlocked.Increment(ref _nextId);
            var tcs = new TaskCompletionSource<LiveResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
            _pending[id] = tcs;
            if (_death != null)
                Fail(_death);
            try
            {
                lock (_writeGate)
                    LiveFrames.Write(_stdin, LiveFrames.Analyze(id, key, version, request, documents, generated));
            }
            catch (IOException ex)
            {
                Died1("writing to the Owen service failed: " + ex.Message);
            }
            return tcs.Task;
        }

        private void Run()
        {
            var reader = new Thread(() =>
            {
                try
                {
                    var stdout = _process.StandardOutput.BaseStream;
                    while (true)
                    {
                        var frame = LiveFrames.Read(stdout);
                        if (frame == null)
                            break;
                        var type = (string?)frame["type"];
                        if (type == "hello")
                            _hello.TrySetResult(frame);
                        else if (type == "result")
                        {
                            var response = LiveFrames.Response(frame);
                            if (_pending.TryRemove(response.Id, out var tcs))
                                tcs.TrySetResult(response);
                        }
                        else if (type == "fatal")
                            Log("owen serve: fatal: " + frame["message"]);
                        else
                            throw new LiveProtocolException("unknown message type '" + type + "'");
                    }
                }
                catch (Exception ex) when (ex is LiveProtocolException || ex is IOException)
                {
                    Log("owen serve: " + ex.Message);
                    Kill();
                }
                _process.WaitForExit(5000);
                Died1(null);
            })
            { IsBackground = true, Name = "Owen live service reader" };
            reader.Start();

            var errors = new Thread(() =>
            {
                string? line;
                while ((line = _process.StandardError.ReadLine()) != null)
                {
                    Log("owen serve: " + line);
                    lock (_stderrTail)
                    {
                        _stderrTail.Enqueue(line);
                        while (_stderrTail.Count > 20)
                            _stderrTail.Dequeue();
                    }
                }
            })
            { IsBackground = true, Name = "Owen live service stderr" };
            errors.Start();
        }

        private void Died1(string? why)
        {
            if (_death != null)
                return;
            string tail;
            lock (_stderrTail)
                tail = string.Join(" | ", _stderrTail.Where(l => l.Trim().Length > 0));
            var code = _process.HasExited ? _process.ExitCode.ToString(System.Globalization.CultureInfo.InvariantCulture) : "?";
            _death = (why ?? "the Owen live analysis service exited (code " + code + ")")
                + (tail.Length > 0 ? ": " + tail : "");
            _hello.TrySetException(new LiveServiceDiedException(_death));
            Fail(_death);
            Died?.Invoke(this);
        }

        private void Fail(string why)
        {
            foreach (var id in _pending.Keys.ToList())
                if (_pending.TryRemove(id, out var tcs))
                    tcs.TrySetException(new LiveServiceDiedException(why));
        }

        public void Kill()
        {
            try
            {
                if (!_process.HasExited)
                    _process.Kill();
            }
            catch (InvalidOperationException)
            {
                // already gone
            }
        }

        public void Dispose()
        {
            try
            {
                lock (_writeGate)
                    LiveFrames.Write(_stdin, new JObject { ["type"] = "shutdown" });
            }
            catch (IOException)
            {
                // already gone
            }
            if (!_process.WaitForExit(2000))
                Kill();
        }
    }

    /// <summary>
    /// K6: the service may die; that is shown, and live analysis restarts on the next request, at
    /// most <see cref="MaxRestarts"/> times in <see cref="Window"/>. After that it stays off, and
    /// says so, until the solution is reopened. Never silent.
    /// </summary>
    public sealed class LiveSupervisor : IDisposable
    {
        public const int MaxRestarts = 3;
        public static readonly TimeSpan Window = TimeSpan.FromMinutes(5);

        private readonly string _dotnet;
        private readonly string _host;
        private readonly Action<string> _log;
        private readonly Func<DateTime> _now;
        private readonly List<DateTime> _starts = new List<DateTime>();
        private readonly SemaphoreSlim _gate = new SemaphoreSlim(1, 1);
        private LiveService? _service;

        public LiveSupervisor(string dotnet, string host, Action<string> log, Func<DateTime>? now = null)
        {
            _dotnet = dotnet;
            _host = host;
            _log = log;
            _now = now ?? (() => DateTime.UtcNow);
        }

        /// <summary>The operational condition to show (OWENV001), or null while healthy.</summary>
        public string? Condition { get; private set; }

        /// <summary>True once the restart budget is spent.</summary>
        public bool GaveUp { get; private set; }

        public event Action<LiveSupervisor>? ConditionChanged;

        public int? ProcessId => _service?.ProcessId;

        public async Task<LiveResponse> AnalyzeAsync(string key, long version, string request,
            IReadOnlyList<LiveSource> documents, IReadOnlyList<LiveSource> generated)
        {
            var service = await EnsureAsync().ConfigureAwait(false);
            return await service.AnalyzeAsync(key, version, request, documents, generated).ConfigureAwait(false);
        }

        private async Task<LiveService> EnsureAsync()
        {
            await _gate.WaitAsync().ConfigureAwait(false);
            try
            {
                if (_service != null && _service.IsAlive)
                    return _service;
                if (GaveUp)
                    throw new LiveServiceDiedException(Condition ?? "Owen live analysis is off");
                var now = _now();
                _starts.RemoveAll(t => now - t > Window);
                if (_service != null && _starts.Count > MaxRestarts)
                {
                    GaveUp = true;
                    SetCondition((Condition ?? "the Owen live analysis service stopped")
                        + ". It was restarted " + MaxRestarts + " times in " + Window.TotalMinutes
                        + " minutes; live analysis is off until the solution is reopened (builds still run Owen).");
                    throw new LiveServiceDiedException(Condition!);
                }
                _starts.Add(now);
                try
                {
                    _service = await LiveService.StartAsync(_dotnet, _host, _log, TimeSpan.FromSeconds(60)).ConfigureAwait(false);
                }
                catch (LiveServiceDiedException ex)
                {
                    SetCondition(ex.Message);
                    throw;
                }
                _service.Died += s =>
                {
                    if (ReferenceEquals(s, _service))
                        SetCondition(s.Death);
                };
                if (Condition != null && !GaveUp)
                    SetCondition(null);
                return _service;
            }
            finally
            {
                _gate.Release();
            }
        }

        private void SetCondition(string? condition)
        {
            Condition = condition;
            ConditionChanged?.Invoke(this);
        }

        /// <summary>Test hook and K6 drill: kill the running service as a crash would.</summary>
        public void KillService() => _service?.Kill();

        public void Dispose() => _service?.Dispose();
    }
}
