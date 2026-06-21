# `TcpListener.Stop()` is a release — Stop() is the cleanup, not a half-measure

A precision fix from a **Codex review** (PR #61). While triaging the ShareX re-mine I
nearly locked an undisposed-`TcpListener` finding as a corpus regression — Codex caught
that it is a **false positive**, and it was right.

## The false positive

```csharp
public static int GetRandomUnusedPort()   // ShareX WebHelpers.cs:191
{
    TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
    try
    {
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }
    finally
    {
        listener.Stop();
    }
}
```

The flow detector flagged `listener` OWN001: it is an `IDisposable` (`TcpListener`
implements `IDisposable` since .NET Core 3.0), and `Stop()` is not in the release set
(`Dispose`/`Close`/`DisposeAsync`). But **`TcpListener.Dispose()` just delegates to
`Stop()`** — `Stop()` disposes the listen socket and clears it. So after `Stop()` there is
no held resource: an undisposed-but-stopped listener is **not a leak**, and flagging it
dents the 0-FP precision claim (CA2000 / CodeQL flag it conventionally, but it is not a
real resource leak).

## The fix — Stop() is a release, for `TcpListener`

`EmitFlowExpr` now models `tcpListener.Stop()` as a `release` of the local, alongside the
`Dispose()`/`Close()`/pool-`Return`/`Show()` releases:

```csharp
if (expr is InvocationExpressionSyntax tlinv
    && tlinv.Expression is MemberAccessExpressionSyntax
        { Name.Identifier.Text: "Stop", Expression: IdentifierNameSyntax tlid }
    && tracked.Contains(tlid.Identifier.Text)
    && model.GetSymbolInfo(tlinv).Symbol is IMethodSymbol { ContainingType: { Name: "TcpListener" } tct }
    && IsInNamespace(tct, "System", "Net", "Sockets"))
{
    nodes.Add(new { op = "release", var = tlid.Identifier.Text, line = LineOf(tlinv) });
    return;
}
```

It is **`TcpListener`-specific**, resolved on the method's containing type via the
SemanticModel — `Stop()` on a `Timer` / `Process` / `Stopwatch` / etc. does **not** dispose
and is untouched (stays a tracked use). And it is path-sensitive (a release at the call
site), like the WinForms `Show()` model: a listener never `Stop()`'d (nor disposed) still
leaks on the path that misses it.

## Pinned in CI

Two `FlowLocalsSample.cs` cases in the `wpf-extractor` `--flow-locals` step:

- `TcpListenerStopped` — `new TcpListener(...); Start(); Stop();` → **silent** (the FP this
  removes);
- `TcpListenerNeverStopped` — `new TcpListener(...); Start();` (no `Stop`) → **OWN001**, the
  control proving the release is `Stop()`-specific, not a blanket `TcpListener` exemption.

## The sibling that is *not* fixed (and why)

The same triage had a `StreamReader` finding (a reader over a `using`-scoped `MemoryStream`,
the reader not disposed). That is also a non-leak *in that specific shape* — the stream is
disposed separately and the reader holds no unmanaged resource of its own. But unlike
`TcpListener`, the extractor's general behaviour there is **correct**: a `StreamReader` over
a stream that is *not* otherwise disposed genuinely leaks the stream (the reader owns it).
Suppressing it would need stream-ownership reasoning and would cost real recall, so it is
left as-is — the narrow `using`-scoped-stream variant is an accepted, rare residual, not a
systematic FP class like `TcpListener.Stop()`.
