# tcplistener-acceptsocket-leak

`TcpListener.AcceptSocket()` returns a fresh **owned** `Socket` the caller must dispose; dropping it
leaks the accepted connection. Covers the `TcpListener.AcceptSocket` branch of the accept-loop
owned-API rule (sibling to `tcplistener-accept-leak`, which covers `AcceptTcpClient`).

- **before.cs** — `var sock = listener.AcceptSocket();` used and never disposed → `OWN001`.
- **after.cs** — `using var sock = …` → clean.
