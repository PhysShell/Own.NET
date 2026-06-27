# ado-executereader-leak

`DbCommand.ExecuteReader()` returns a fresh **owned** `DbDataReader` the caller must
dispose. Dropping it leaks the reader and keeps the server-side cursor/connection busy
until finalization — the single most common real-world ADO.NET resource leak.

- **before.cs** — `var reader = cmd.ExecuteReader();` used and never disposed → `OWN001`.
  The command is a borrowed parameter, so the only leak is the reader.
- **after.cs** — `using var reader = …` disposes it on every path → clean.

Recognised by the extractor's `IsOwningFactory` (P1a, ADO.NET tranche): matched by method
name + **both** the receiver and the return type implementing the `System.Data` contract
interfaces — the receiver an `IDbCommand` and the return an `IDataReader` — so it covers every
provider (`SqlDataReader`, `NpgsqlDataReader`, …), the abstract `DbDataReader`, and the
interface, while a non-ADO helper that merely exposes an `ExecuteReader` returning a borrowed
reader is not mistaken for an owned factory. Sibling members `CreateCommand`
(`IDbConnection` → `IDbCommand`) and `BeginTransaction` (`IDbConnection` → `IDbTransaction`)
are recognised the same way.
