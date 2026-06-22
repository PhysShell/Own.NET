using System;
using System.Diagnostics.Tracing;
using System.Threading;

namespace Own.Samples;

// P-004 EventSource diagnostic-counter exemption (mined: Npgsql NpgsqlEventSource). A
// DiagnosticCounter — EventCounter / PollingCounter / IncrementingEventCounter /
// IncrementingPollingCounter — constructed with `this` (the parent EventSource) registers
// itself with that source: the runtime's CounterGroup pins it to the EventSource's lifetime,
// and an EventSource is a process-lived `static readonly Log` singleton, so the counter is a
// process-lived diagnostic that is idiomatically NEVER field-disposed (every BCL EventSource —
// RuntimeEventSource, the HTTP/ASP.NET counters — does exactly this). The counter fields must
// therefore be SILENT. Contrast `_scratch` below: a plain owned IDisposable in the SAME
// EventSource STILL leaks, proving the rule keys off the DiagnosticCounter type handed to
// `this`, not "any field declared in an EventSource".
[EventSource(Name = "Own-Sample-Counters")]
internal sealed class SampleEventSource : EventSource
{
    public static readonly SampleEventSource Log = new SampleEventSource();

    private long _bytesWritten;

    // The four counter kinds, all built in OnEventCommand with `this` -> owned by the source -> SILENT.
    private IncrementingPollingCounter? _bytesPerSecond;
    private PollingCounter? _totalBytes;
    private EventCounter? _commandDuration;
    private IncrementingEventCounter? _totalCommands;

    // Codex control: a NON-counter owned IDisposable field in the same EventSource is NOT exempt.
    // The exemption keys off the DiagnosticCounter type handed to `this`, not the containing class,
    // so this new'd-but-never-disposed resource STILL raises OWN001 ('disposable field').
    private readonly OwnedScratch _scratch = new OwnedScratch();

    private SampleEventSource() { }

    public void RecordBytes(long n) => Interlocked.Add(ref _bytesWritten, n);

    protected override void OnEventCommand(EventCommandEventArgs command)
    {
        if (command.Command != EventCommand.Enable)
            return;

        _bytesPerSecond = new IncrementingPollingCounter("bytes-per-second", this, () => Interlocked.Read(ref _bytesWritten))
        {
            DisplayName = "Bytes Written Rate",
            DisplayRateTimeScale = TimeSpan.FromSeconds(1),
        };
        _totalBytes = new PollingCounter("total-bytes", this, () => Interlocked.Read(ref _bytesWritten))
        {
            DisplayName = "Total Bytes Written",
        };
        _commandDuration = new EventCounter("command-duration", this)
        {
            DisplayName = "Command Duration",
            DisplayUnits = "ms",
        };
        _totalCommands = new IncrementingEventCounter("total-commands", this)
        {
            DisplayName = "Total Commands",
        };
    }
}

internal sealed class OwnedScratch : IDisposable
{
    public void Dispose() { }
}
