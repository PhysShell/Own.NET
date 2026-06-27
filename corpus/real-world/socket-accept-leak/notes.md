# socket-accept-leak

`Socket.Accept()` returns a fresh **owned** `Socket` the caller must dispose; dropping it leaks the
accepted connection. Covers the `Socket.Accept` branch of the accept-loop owned-API rule (sibling
to `tcplistener-accept-leak`).

- **before.cs** — `var conn = listener.Accept();` used and never disposed → `OWN001`.
- **after.cs** — `using var conn = …` → clean.
