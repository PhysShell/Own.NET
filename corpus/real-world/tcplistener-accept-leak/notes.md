# tcplistener-accept-leak

`TcpListener.AcceptTcpClient()` returns a fresh **owned** `TcpClient` the caller must dispose.
Dropping it leaks the accepted connection — the socket handle stays open until finalization, the
classic accept-loop server resource leak.

- **before.cs** — `var client = listener.AcceptTcpClient();` used and never disposed → `OWN001`.
  The listener is a borrowed parameter, so the only leak is the client.
- **after.cs** — `using var client = …` disposes it on every path → clean.

Recognised by the extractor's `IsOwningFactory` (owned-API tranche): an instance "accept" member
matched by the concrete BCL receiver type + method name (`Socket.Accept`,
`TcpListener.AcceptSocket`, `TcpListener.AcceptTcpClient` in `System.Net.Sockets`) with the result
pinned to `IDisposable`, so the async variants (`AcceptTcpClientAsync` → `Task`/`ValueTask`) are
excluded.
