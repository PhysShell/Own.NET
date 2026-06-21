# ShareX — `TcpListener` started and stopped, never disposed

**Found by mining** `ShareX/ShareX` @ `ed2a864` (the WinForms re-mine — see
`docs/notes/real-world-mining.md`). Location:
`ShareX.HelpersLib/Helpers/WebHelpers.cs:191`, `GetRandomUnusedPort`.

## The bug

```csharp
public static int GetRandomUnusedPort()
{
    TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
    try
    {
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }
    finally
    {
        listener.Stop();   // Stop() != Dispose()
    }
}
```

`TcpListener` is `IDisposable` (since .NET Core 3.0). `Stop()` closes the active listen
socket but does **not** dispose the listener, so the instance is never disposed — the
canonical CA2000 / CodeQL `cs/local-not-disposed` leak. The "grab a random free port" idiom
is exactly where it slips: the developer reaches for `Stop()` and assumes it is the cleanup.
The fix is `using` (or an explicit `Dispose()`), as `after.cs` shows.

## What the checker says (real extractor output, `--flow-locals`)

```text
WebHelpers.cs:191: error: [OWN001] IDisposable local 'listener' is never disposed
  (leak) [resource: disposable]
```

`acquire` is `new TcpListener(...)`, the missing `release` is the absent `Dispose()`;
`Start()` / `Stop()` are uses, not releases. `before.cs` reduces the real try/finally to
straight-line form — the leak is the missing Dispose, not the control flow.
