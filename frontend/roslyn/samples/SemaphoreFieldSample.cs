using System;
using System.Threading;
using System.Threading.Tasks;

namespace Own.Samples;

// P-004 SemaphoreSlim FIELD dispose-optional (mined: Npgsql NpgsqlDataSource._setupMappingsSemaphore).
// SemaphoreSlim.Dispose() only frees a lazily-allocated wait handle (allocated solely when
// AvailableWaitHandle is read), so a SemaphoreSlim field used purely for Wait/WaitAsync/Release leaks
// nothing and is dispose-optional. GATED on AvailableWaitHandle: if the field's AvailableWaitHandle is
// read, the handle exists and Dispose must release it -> the field STAYS tracked (Codex). Scoped to
// FIELDS only — method-bounded LOCAL SemaphoreSlims remain tracked via FlowLocalsSample.semLeak.

// a SemaphoreSlim field used only for WaitAsync/Release, never disposed -> SILENT (dispose-optional).
public sealed class OptionalSemaphore
{
    private readonly SemaphoreSlim _optionalSem = new SemaphoreSlim(1, 1);

    public async Task RunAsync()
    {
        await _optionalSem.WaitAsync();
        try { /* critical section */ }
        finally { _optionalSem.Release(); }
    }
}

// control (the gate): the field's AvailableWaitHandle IS read, so the wait handle is allocated and
// Dispose must release it -> the field must STILL warn OWN001.
public sealed class WaitHandleSemaphore
{
    private readonly SemaphoreSlim _handleSem = new SemaphoreSlim(0, 1);

    public void Block()
    {
        _handleSem.AvailableWaitHandle.WaitOne();   // reads AvailableWaitHandle -> stays tracked
    }
}

// control (type scope): a non-SemaphoreSlim owned IDisposable (CancellationTokenSource) never disposed
// must STILL warn — the exemption is SemaphoreSlim-specific, not a blanket "any field".
public sealed class HoldsCtsField
{
    private readonly CancellationTokenSource _ctsControl = new CancellationTokenSource();

    public void Cancel() => _ctsControl.Cancel();
}
