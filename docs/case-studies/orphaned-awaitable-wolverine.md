# Case study: the orphaned awaitable (OWN053) and Wolverine's `ScheduleRetryAsync`

**What the analyzer saw.** Scanning JasperFx/wolverine (a frozen benchmark
consumer, main at `7ee3df90` / `c20fb0cc`) the OwnIR extractor found exactly one
production local in 772 project/TFM units that is initialised by an un-awaited,
effectful awaitable and never referenced again:

```csharp
// src/Persistence/Wolverine.Postgresql/Transport/PostgresqlQueueSender.cs
try
{
    var tx = conn.BeginTransactionAsync(cancellationToken);   // never awaited, never read
    await scheduleMessageAsync(envelope, cancellationToken, conn);
}
finally
{
    await conn.CloseAsync();
}
```

**Why it matters (measured, not assumed).** Against Npgsql 10.0.3 and PostgreSQL 16:

- `BeginTransactionAsync` completes synchronously (`IsCompleted == true` right
  after the call) and changes the connection state inline, whether or not the
  returned `ValueTask<NpgsqlTransaction>` is ever awaited.
- Every later command on the connection runs inside that transaction; a second
  `BeginTransactionAsync` throws "a transaction is already in progress".
- Nobody holds the transaction, so nothing commits or disposes it; closing the
  connection rolls the work back. A probe that inserts after the orphaned call
  and closes the connection loses the insert.

**Why the message is not lost today.** Driving the real `PostgresqlQueueSender`
with an incoming row present gives `incoming = 0, scheduled = 1` after the call:
the command right before the `try` is one autocommitted batch (`delete from
incoming ...; insert into scheduled ... on conflict do update`) that already moves
the message. The write inside the orphaned transaction is a redundant second upsert
whose rollback is invisible. The defect is real — an unobserved acquisition, a
redundant rolled-back write, and a latent trap for any write placed after the
orphan — but its current impact is robustness, not data loss. The first
hand-written "exact shape" probe omitted that batch and overstated the impact;
the correction is recorded (erratum 5 in the research paperwork) and is the
reason the upstream report describes the measured behaviour only.

**Why nothing else reported it.** CA2012, VSTHRD110, MA0134 and CS4014 are silent
by design: assigning the task to a local counts as "observing it later". CS0219 is
not issued for a method-call result. IDE0059 reports the pattern in plain and
async shapes but goes silent inside `try` / `finally` — exactly this site's shape.

**What Own.NET does differently.** OWN053 looks at the *subsequent life of the
acquired protocol object*, not at the statement form: an awaitable whose result or
completion carries an obligation (an owned result, or a connection / transaction
lifecycle call) that is obtained and then never awaited, returned, stored, passed
or otherwise observed. It is deliberately narrow — discards and bare statements
belong to other rules, non-effectful awaitables are out of scope, and new
lifecycle names enter only with a runtime witness — and it offers no automatic
fix: only the author knows whether the call should be awaited, kept, or made an
explicit fire-and-forget.

**Evidence trail.** Preregistration before any code, an exact Npgsql runtime
falsifier, the analyzer-overlap measurement, an 8-consumer census (one orphan),
and an OFF/ON scan of the prototype over 766 units with Python/Rust parity and
byte-identical OFF facts; the records live in the Own.NET-paperwork repository
(`paper-eval/h29/`), the probes and drivers in `corpus/ownership-lab/h29/`.
