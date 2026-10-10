# H-28-CMD — what the absence of `DbCommand.Dispose()` actually means

Status: **research note, no production change**. Verdict: **H28-PROVIDER-SPECIFIC**.
Base: `main` = `e889f8b`. Artifacts and reproduction: [`corpus/ownership-lab/h28-command/`](../../corpus/ownership-lab/h28-command/).

```csharp
var command = connection.CreateCommand();
var reader  = command.ExecuteReader();
var table   = new DataTable();
table.Load(reader);          // neither command nor reader is disposed
```

Citations named `evidence/…txt` are generated artifacts under that directory, each carrying
repo, ref, path, git blob sha, file sha256 and line range. Re-derive all 32 with
`scripts/derive_source_evidence.py` — non-zero exit means this note is stale.

---

## 1. The original uncertainty

H-28 was registered as *argument / callee ownership transfer*. Its "demanding instance" was
`victor-wiki/DatabaseManager` `DbInterpreter.GetDataTableAsync:699`, described in the
preregistration as *"connection is a parameter, command a local never disposed"*. H-28's own
runtime falsifier settled the **reader** and explicitly declined to settle the **command**:

> `DataTable.Load(IDataReader)` closes the reader … the demanding instance is NOT a lease /
> protocol leak … **what remains is the never-disposed `DbCommand` `cmd` (an object leak
> without a protocol consequence)**. — `h28/scripts/h28_anchors_record.py`

That is a description, not a classification: never falsified, never entered into the
witnessed-callee table, never reached a gate. This note closes it against the five candidate
classifications (real defect / provider-specific / benign / not classifiable / obsolete).

---

## 2. Recovered prior evidence

**H-28 is not on `main`.** It lives on `research/ownership-semantics-lab-v1` @ `298b305`, under
`corpus/ownership-lab/h28/` (36 files). The preregistration JSON itself lives in a separate
`Own.NET-paperwork` repository that is **not reachable**; its content is nevertheless
recoverable verbatim because `h28/scripts/h28_prereg.py` is the program that writes it.

| claim | primary evidence | status |
|---|---|---|
| H-28 = argument/callee transfer, not command lifetime | `scripts/h28_prereg.py` (`track`, `hypothesis`) | confirmed |
| demanding instance = `DbInterpreter.GetDataTableAsync:699` | `h28_prereg.py` → `anchors.demanding_instance` | confirmed |
| `DataTable.Load(reader)` **closes** the reader; BORROW refuted | `falsifier/falsifier.out` (F1 `IsClosed=True` on sqlite **and** npgsql) → `RELEASE_IF_LAST_RESULT_SET` | confirmed |
| CA2000 (default options) reports **neither** command nor reader | `analyzers/ca2000/{Repro2.cs,ca2000-warnings.txt}` — CA2000 tracks `new`, not factory results | confirmed |
| "the never-disposed `DbCommand`" | `h28_anchors_record.py` → `consequence_for_the_demanding_instance` | **recorded, never classified** ← this note |
| gate → `RECORD_AND_STOP` (1 of 10 primary candidates confirmed) | `manual-read.json`, `scripts/h28final.py`, `h28-census-v1.json` | confirmed |
| the escape rule that drops an argument-passed local | `h28_prereg.py` → `necessary_condition_verified_by_code_reading`; issue [#382](https://github.com/PhysShell/Own.NET/issues/382) (open) | confirmed |

Two provenance warnings. **Name collision:** `H28` in
`docs/notes/p022-bridge-verdict-checkpoint4b.md:216` is a *different* H28 (a bridge-verdict
hypothesis) and must not be conflated. **Stale facts:** `corpus/ownership-lab/h29/promotion/promo-u.facts.json`
— the only committed OwnIR facts mentioning `CreateCommand`/`ExecuteReader` — is **schema v1**
while the core is **v2**; `ownlang ownir` refuses it, so it is not evidence of current behaviour.

---

## 3. Versions

| component | version | source |
|---|---|---|
| .NET / Npgsql / MS.Data.Sqlite (old falsifier) | net8.0 / **10.0.3** / 10.0.12 | `h28/falsifier/w28.csproj` |
| PostgreSQL (old falsifier) | 16, pgserver, socket `/tmp/pgsc` | `h28_anchors_record.py` |
| PostgreSQL (this note) | **16.2**, `pgserver` 0.1.4 (PyPI) | started and queried here, §6 |
| BCL reference | `dotnet/runtime` `v8.0.20` **and** `v10.0.12` | the old TFM and current |
| Npgsql re-read | `v10.0.3` **and** `main` | §5.1 |
| cross-provider | `dotnet/efcore` main, `dotnet/SqlClient` main, `mysql-net/MySqlConnector` master, `ericsink/SQLitePCL.raw` main | §5.3 |
| Own.NET | `main` @ `e889f8b`, extractor TFM net8.0 | §7 |

`DbCommand.cs`, `DbDataReader.cs`, `DbConnection.cs`, `IDataReader.cs`, `IDbCommand.cs` differ
between `v8.0.20` and `v10.0.12` **only in `using`-directive order**; `DataTable.Load`'s body is
unchanged. The contract did not move.

---

## 4. Ownership semantics and the BCL contract

| object | created by | owned by | what ends its logical lifetime | what it can hold | does its `Dispose` free another object? |
|---|---|---|---|---|---|
| `DbConnection` | caller / pool / DI | caller | `Close()`/`Dispose()` | the connector: socket, buffers, server session | yes — Npgsql's connection close also closes its current reader |
| `DbCommand` | `connection.CreateCommand()` | **caller**, nothing else takes it | `Dispose()`, or never | **provider-dependent** (§5) | **provider-dependent** — Sqlite: its reader + native statements; Npgsql: nothing |
| `DbDataReader` | `command.ExecuteReader()` | **caller** | `Close()` or `Dispose()` | connector binding, a pooled `ColumnInfo[]`, and (Npgsql) the command's `Activity` | no — but it discharges one field **of the command** (§5.2) |
| `DataTable` | `new DataTable()` | caller | nothing (dispose-optional) | managed rows only | n/a — `Load` never touches the command |

**Guaranteed by the API contract.** `IDbCommand : IDisposable`, `IDataReader : IDisposable` with
a separate `Close()` — the interface guarantees `Dispose` *exists*, not what it frees
[`evidence/runtime-v10.0.12-IDbCommand.txt`]. `DbCommand : Component, IDbCommand,
IAsyncDisposable` and **does not override `Dispose` at all**; its only disposal member is
`DisposeAsync() { Dispose(); return default; }`. So BCL-level `DbCommand.Dispose()` *is*
`Component.Dispose()` and **all** command resource semantics are the provider's
[`evidence/runtime-v10.0.12-DbCommand-class.txt`, `evidence/runtime-v10.0.12-DbCommand-DisposeAsync.txt`].
`DbDataReader.Close()` is `public virtual void Close() { }` — empty — and `Dispose()` →
`Dispose(true)` → `Close()`, so for a reader the two run the *same* provider cleanup
[`evidence/runtime-v10.0.12-DbDataReader-Close-Dispose.txt`].

**What `System.Data` currently does** (an implementation fact, not a contract) —
`DataTable.Load(IDataReader, LoadOption, FillErrorEventHandler?)`, `v10.0.12` line 4974,
identical logic at `v8.0.20` line 4969 [`evidence/runtime-v10.0.12-DataTable-Load.txt`]:

```csharp
adapter.FillFromReader(new DataTable[] { this }, reader, 0, 0);
if (!reader.IsClosed && !reader.NextResult())
{
    reader.Close();
}
```

Three consequences, all load-bearing: (1) it calls **`Close()`, not `Dispose()`**; (2) it closes
**conditionally** — on a multi-result-set reader `NextResult()` is `true` and the reader is
**left open**, which is exactly the witnessed label `RELEASE_IF_LAST_RESULT_SET` and a case the
original falsifier never exercised; (3) `Load` **never touches the command** — it holds no
reference to it, so nothing about `Load` can discharge a command obligation.

---

## 5. What the providers actually do

### 5.1 Npgsql — `NpgsqlCommand.Dispose()` releases nothing

`v10.0.3` line 1712 [`evidence/npgsql-10.0.3-NpgsqlCommand-Dispose.txt`], unchanged at `main`
[`evidence/npgsql-main-NpgsqlCommand-Dispose.txt`]:

```csharp
protected override void Dispose(bool disposing)
{
    ResetTransaction();                 // _transaction = null      (managed field)
    State = CommandState.Disposed;      // managed int flag
    if (IsCacheable && InternalConnection is not null && InternalConnection.CachedCommand is null)
    {
        Reset();                        // recycle into the connection's one-slot command cache
        InternalConnection.CachedCommand = this;
        return;
    }
    IsCacheable = false;
}
```

* `Reset()` clears `_commandText`, `CommandType`, `_parameters`, `_timeout` and two flags —
  **managed only**; no connector, buffer or prepared statement [`evidence/npgsql-10.0.3-NpgsqlCommand-Reset.txt`].
* **No finalizer** (no `~NpgsqlCommand` in the file) and both public constructors call
  `GC.SuppressFinalize(this)` [`evidence/npgsql-10.0.3-NpgsqlCommand-ctor-SuppressFinalize.txt`] — an undisposed
  command leaves **nothing on the finalizer queue**.
* `connection.CreateCommand()` returns `CreateCachedCommand(this)` ⇒ `IsCacheable = true`
  [`evidence/npgsql-10.0.3-NpgsqlConnection-CreateCommand.txt`, `evidence/npgsql-10.0.3-NpgsqlCommand-CreateCachedCommand.txt`],
  so the cacheable branch is the live one for user code: the **only** observable effect of
  `Dispose()` is recycling the command into the connection's single `CachedCommand` slot.
* Server-side prepared statements belong to the **connector**
  (`NpgsqlConnector.PreparedStatementManager`, created in its constructor, cleared via
  `ClearAll()` from `NpgsqlConnector`) — never from `NpgsqlCommand`, which holds only
  `_connectorPreparedOn` to notice preparation on a *different* connector
  [`evidence/npgsql-10.0.3-NpgsqlConnector-PreparedStatementManager.txt`].
  **`command.Dispose()` issues no `DEALLOCATE`.**

### 5.2 Npgsql — the reader holds a cleanup duty over one of the *command's* fields

`ExecuteReader` calls `TraceCommandStart`, which — **only if `NpgsqlActivitySource.IsEnabled`,
i.e. `Source.HasListeners()`** — stores a `System.Diagnostics.Activity` in
`command.CurrentActivity` [`evidence/npgsql-10.0.3-NpgsqlCommand-TraceCommandStart.txt`,
`evidence/npgsql-10.0.3-NpgsqlActivitySource-IsEnabled.txt`]; the source is named `"Npgsql"`,
which is what falsifier probe P4 must match or the arm stays inert
[`evidence/npgsql-10.0.3-NpgsqlActivitySource-SourceName.txt`]). `Activity` **is** `IDisposable` in
.NET 8 and 10, and *"Dispose will stop the Activity if it is already started and notify any
event listeners"* [`evidence/runtime-v8.0.20-Activity-IDisposable.txt`,
`evidence/runtime-v8.0.20-Activity-Dispose.txt`].

The only stopper is `NpgsqlCommand.TraceCommandStop()`
[`evidence/npgsql-10.0.3-NpgsqlCommand-TraceCommandStop.txt`], and a **repo-wide** grep of `npgsql@v10.0.3` finds
exactly two call sites — both in the reader's `Dispose`:

```
src/Npgsql/NpgsqlDataReader.cs:1030   Command.TraceCommandStop();   // Dispose(bool)
src/Npgsql/NpgsqlDataReader.cs:1058   Command.TraceCommandStop();   // DisposeAsync()
```

Neither `NpgsqlDataReader.Close()` (`isDisposing: false`
[`evidence/npgsql-10.0.3-NpgsqlDataReader-Close-public.txt`]) nor `NpgsqlCommand.Dispose()` calls it; inside
`Cleanup`, `isDisposing` gates only `State = ReaderState.Disposed`
[`evidence/npgsql-10.0.3-NpgsqlDataReader-Cleanup.txt`]. So in this family, **with a tracing
listener attached**: the span never ends (an OTel batch exporter exports on end, so it is never
exported), `Activity.Current` is not popped, disposing the *command* would not help, and a
second `ExecuteReader()` on the same command hits `Debug.Assert(CurrentActivity is null)` and —
in release — orphans the previous Activity.

`Cleanup` also shows what the reader genuinely releases on **Close**, not only Dispose: it
returns its pooled `ColumnInfo[]` to `ArrayPool<ColumnInfo>.Shared`, sets
`Connector.CurrentReader = null`, calls `Connector.EndUserAction()`, and sets
**`Command.State = CommandState.Idle`** — which is what makes the command legally *reusable*
after the reader closes. That is not ownership of the command.

### 5.3 Cross-provider — the falsifier for "Dispose is always optional"

| provider | `command.Dispose()` body | releases a resource? | owns its reader? | finalizer? |
|---|---|---|---|---|
| **Npgsql** 10.0.3 / main | `ResetTransaction(); State=Disposed;` + optional recycle | **no** | no | no (`GC.SuppressFinalize`) |
| **Microsoft.Data.Sqlite** | `DisposePreparedStatements(disposing); _connection?.RemoveCommand(this); base.Dispose(disposing);` | **YES — native `sqlite3_stmt`** | **YES** (`DataReader.Dispose()`) | n/a — the SafeHandle below has one |
| **Microsoft.Data.SqlClient** | `_cachedMetaData = null; CachedAsyncState?.ResetAsyncState(); base.Dispose(disposing);` | **no** (despite its `// Release unmanaged objects` comment) | no | no |
| **MySqlConnector** | `m_isDisposed = true; base.Dispose(disposing);` | **no** | no | no (`GC.SuppressFinalize`) |

[`evidence/npgsql-10.0.3-NpgsqlCommand-Dispose.txt`, `mssqlite-SqliteCommand-Dispose.txt`,
`sqlclient-SqlCommand-Dispose.txt`, `mysqlconnector-MySqlCommand-Dispose.txt`]

The SQLite arm: `ExecuteReader` → `GetStatements()` → for an unprepared command,
`PrepareAndEnumerateStatements()`, an iterator calling `sqlite3_prepare_v2` that adds every
native statement to the command's `_preparedStatements`
[`evidence/mssqlite-SqliteCommand-PrepareAndEnumerate-head.txt`,
`evidence/mssqlite-SqliteCommand-preparedStatements-field.txt`] — so a **plain** `ExecuteReader()`
puts native handles on the **command**. `SqliteDataReader.Close()` → `Dispose(true)` disposes
only `_stmtEnumerator` and nulls `_command.DataReader`; it does **not** finalize the statements,
which live on the command [`evidence/mssqlite-SqliteDataReader-Close-Dispose.txt`]. And
`sqlite3_stmt : SafeHandle` with `ownsHandle: true` and
`ReleaseHandle() => raw.internal_sqlite3_finalize(handle)`
[`evidence/sqlitepclraw-sqlite3_stmt-SafeHandle.txt`] — `SafeHandle` carries a critical
finalizer, so without `Dispose` the `sqlite3_finalize` is deferred to non-deterministic
finalization. ⇒ **`command.Dispose()` is the only deterministic releaser of those handles in
this family**; variants B and C genuinely defer a native release to the GC.

Two intermediate hypotheses of my own were refuted and are recorded so they are not re-derived:
*"SQLite accumulates statements across executions"* — false, `PrepareAndEnumerateStatements()`
opens with `DisposePreparedStatements(disposing: false)`; *"non-disposal extends the command's
lifetime via the connection"* — false, `SqliteConnection._commands` is a
`List<WeakReference<SqliteCommand>>` [`evidence/mssqlite-SqliteConnection-commands-weakrefs.txt`].

---

## 6. Runtime observations

**Executed here.** PostgreSQL **16.2** was started via `pgserver` 0.1.4 (self-contained PyPI
wheel, Unix socket) — the harness class the original H-28 falsifier used — and queried with its
bundled `psql` to pin the server-side half independently of any source reading:

| observation | result |
|---|---|
| `PREPARE p1(int) AS SELECT $1`, then `pg_prepared_statements` in the same session | listed |
| same query from a **new** session | `0` — per-backend |
| `DECLARE c1 CURSOR …`, then `pg_cursors` | listed; gone with the session |

⇒ server-side prepared state and cursors are **session-scoped**, bound to the *connection* —
which is why no command-level `Dispose` can be their releaser. This corroborates §5.1.

**Not executed here: the .NET half.** There is no .NET SDK in this sandbox and no reachable
NuGet feed — `api.nuget.org`, `nuget.org`, `nuget.pkg.github.com`, `dotnet.microsoft.com`,
`builds.dotnet.microsoft.com`, `pkgs.dev.azure.com`, `objects.githubusercontent.com`,
`deb.debian.org` and `cache.nixos.org` are all unreachable; the ~909k-entry PyPI simple index and
the npm registry were searched and publish no modern .NET runtime (npm's `node-api-dotnet` ships
managed shims without `coreclr`). `run.sh runtime` prints `SKIP-WHY` and exits 0 rather than
pretending. The falsifier is committed **ready to run**
(`falsifier/`, pinned to net8.0 / Npgsql 10.0.3 / MS.Data.Sqlite 10.0.12 so its output compares
directly with the original `falsifier.out`); every probe exists to separate two hypotheses:

| probe | separates |
|---|---|
| P1 `reader.IsClosed` after `Load` | reproduces H-28 F1 (`RELEASE` vs `BORROW`) |
| P2 command reusable after the reader closed | "the reader bounds the command's lifetime" vs "leaves it `Idle`" (§5.2 predicts OK) |
| P3 second command on the same connection | protocol leak vs object leak |
| **P4 `ActivityListener` started/stopped counts** | **the §5.2 claim**: `stopped=0` for B and D, `stopped=1` for C and A |
| P5 `pg_prepared_statements` before/after `command.Dispose()` | whether command disposal releases server-side state (§5.1 predicts no change) |
| P6 RSS delta over N iterations, ± `command.Dispose()` | the §5.3 SQLite native-retention arm |

P4 matters most: §5.2 is the only load-bearing claim resting on `Activity` lifecycle semantics
rather than on a plainly readable `Dispose` body. P4 is **Npgsql-only** — Microsoft.Data.Sqlite
has no `ActivitySource`/`DiagnosticSource` anywhere in `SqliteCommand.cs` or `SqliteDataReader.cs`
(`grep -c 'ActivitySource\|DiagnosticSource'` over the fetched files at `dotnet/efcore@main`: 0),
so `0/0` on the SQLite variants is the expected reading, not a failed probe. P6 uses process RSS, **not**
`GC.GetTotalMemory` (the resource is native), and is a delta over N iterations with an explicit
finalization control — one snapshot cannot separate retention from allocation noise.

---

## 7. What current Own.NET does

### 7.1 Extraction (source-derived — the extractor was not runnable here)

Line numbers are `frontend/roslyn/OwnSharp.Extractor/Program.cs` @ `e889f8b`.

1. **`command` becomes a tracked owned local.** `IsOwningFactory` (L4832) recognises the ADO.NET
   tranche by method name **plus both resolved types implementing the `System.Data` interfaces**:
   `CreateCommand` with `IDbConnection`→`IDbCommand` (L4880-4882), `ExecuteReader`
   `IDbCommand`→`IDataReader` (L4877-4879), `BeginTransaction` (L4883-4885). The flow pass adds
   the local to `candidates` (L7035-7036).
2. **No exemption applies.** `IsDisposeOptional` (L2593-2606) is a closed list — `Task`/`ValueTask`,
   `DataTable`/`DataSet`/`DataView`, `StringWriter`/`StringReader`; `DbCommand` is absent.
   `HasEmptyDisposeBody` cannot apply either: since the #238 soundness gate it is confined to
   types implementing `IEnumerator<T>`, which `DbCommand` does not.
3. **`reader`'s obligation is silently dropped** at `table.Load(reader)`: the argument-escape
   rule (L7155-7162) untracks any candidate whose identifier is an `ArgumentSyntax` unless it is
   a pool buffer, a bare-statement `consumedArg`, or an adopted ctor argument of a bounded
   wrapper; then `tracked.ExceptWith(escapedLocals)` (L7182). `DataTable.Load` is external, so no
   carve-out applies. This is precisely the row of
   [#382](https://github.com/PhysShell/Own.NET/issues/382) reading *"anything else, and the
   argument is a tracked local → an escape: the local is untracked"*.
4. `table` is not a candidate (dispose-optional), and `Close`/`Dispose`/`DisposeAsync` are
   credited as releases (e.g. L3476, L4143) — which is what makes fixture variant F differ from B.

**Predicted verdict:** `OWN001` (error severity, non-zero exit) on **`command`**, silence on
**`reader`**.

### 7.2 Engine (executed)

`fx/CommandDispose.own` is a hand reduction of the same family — the honest frame
`corpus/real-world/README.md` states: a model, not C# the checker read.

```
$ corpus/ownership-lab/h28-command/run.sh engine
…:42:3: error: [OWN001] 'command' is owned but not released at end of function …
…:69:32: error: [OWN001] 'command' is owned but not released at end of function …
…:69:7:  error: [OWN001] 'reader'  is owned but not released at end of function …
3 errors.            # exit 1
PREDICTION HOLDS: 2x OWN001 'command' (B, E) + 1x OWN001 'reader' (E), A/D clean.
```
[`evidence/engine-CommandDispose.txt`]

Given the obligation the core is correct: B reports the command, A and D are clean, and E (no
`Load`, so no escape) reports **both** — which separates the escape rule from the acquire rule
without reading the extractor.

### 7.3 Where the model diverges from the runtime semantics

* **The acquire rule is provider-blind.** `IsOwningFactory` matches `System.Data` *interface*
  types precisely so it covers every provider — stated as a feature in its own comment. But §5.3
  shows `Dispose`'s effect is not uniform: real native release on Microsoft.Data.Sqlite, nothing
  on the other three. `IsDisposeOptional` is the only channel for "disposing frees nothing", and
  it is keyed on **namespace + type name** with no provider dimension and no implementation
  input. Nothing in the model can carry "Dispose-effect: none" for Npgsql and "Dispose-effect:
  native statements" for SQLite.
* **The escape drop is accidentally right, and only sometimes.** For a single-result-set reader,
  dropping `reader` agrees with the witnessed `RELEASE_IF_LAST_RESULT_SET`. For a
  **multi-result-set** reader `Load` leaves it **open** (§4.1) — there the drop is a false
  negative. Own.NET is silent in both cases and cannot distinguish them, because the call fact
  never reaches the core.
* **On Npgsql the finding is inverted.** With tracing enabled the object whose disposal is
  load-bearing is the **reader** (§5.2) — the one Own.NET is silent about — while the
  error-severity `OWN001` falls on the command, whose `Dispose` provably frees nothing (§5.1).
* **Coverage.** No committed `.facts.json` anywhere (main *or* the research branch) contains
  `CreateCommand`, `DbCommand` or `DbDataReader`, and
  `corpus/real-world/ado-executereader-leak/before.cs` deliberately makes the command a *borrowed
  parameter* ("the only leak is `reader`"). The never-disposed-`CreateCommand()` shape has never
  been through Own.NET end-to-end; `fx/CommandDispose.cs` is its first fixture.

---

## 8. Falsifiers

| if it seems that… | falsifier attempted | result |
|---|---|---|
| the command **must** be disposed | find a provider where non-disposal is provably harmless | **found**: Npgsql (§5.1), also SqlClient and MySqlConnector (§5.3) |
| disposing the command is **optional** | find a provider/path leaving an observable resource | **found**: Microsoft.Data.Sqlite — native `sqlite3_stmt` SafeHandles on the command, unreleased by reader `Close`/`Dispose`, deterministically released only by `command.Dispose()` (§5.3) |
| the **reader owns the command** | prove or refute from implementation | **refuted as ownership**: `Cleanup` sets `Command.State = Idle` — it makes the command *reusable*. A partial cleanup duty over exactly one field (`CurrentActivity`, via `reader.Dispose` → `TraceCommandStop`) is not ownership, and `Close()` does not discharge it (§5.2) |
| `DataTable.Load` discharges the command | read `Load` | **refuted**: no reference to the command (§4.1) |
| `Load` always closes the reader | read the condition | **refuted as universal**: `!reader.NextResult()` — a multi-result-set reader stays **open** (§4.1) |
| undisposed commands accumulate SQLite statements | read `PrepareAndEnumerateStatements` | **refuted**: opens with `DisposePreparedStatements(disposing: false)` (§5.3) |
| non-disposal extends command lifetime via the connection | read `SqliteConnection._commands` | **refuted**: weak references (§5.3) |
| **Own.NET is simply wrong** | localise source → facts → verdict | **partly refuted**: extraction is faithful and the core is correct given the facts (§7.2). The defect is not in a stage — it is the missing provider dimension on the acquire plus the escape rule discarding the one call fact that decides the reader (§7.3) |
| the question is obsolete | — | **refuted**: the residual was recorded but never classified (§2), and the answer changes an engineering decision (§9) |

**Not falsified but unproven at runtime:** §5.2's Activity consequence and §5.3's native
retention. Both are source-derived and marked PREDICTED; P4 and P6 exist to settle them (§6).

---

## 9. Verdict

# H28-PROVIDER-SPECIFIC

> **The absence of `Dispose()` on a `DbCommand` in the `DataTable.Load(reader)` family is not one
> fact. It is a real resource/lifetime defect on Microsoft.Data.Sqlite and releases nothing on
> Npgsql, Microsoft.Data.SqlClient and MySqlConnector. No provider-independent ownership rule can
> classify it, because the effect of `DbCommand.Dispose()` is entirely a provider implementation
> detail — the BCL declares no `Dispose` on `DbCommand` at all.**

1. The old residual *"an object leak without a protocol consequence"* is **true for Npgsql, false
   for Microsoft.Data.Sqlite**. It was written from a two-provider falsifier whose SQLite arm
   never looked at the command.
2. Own.NET's `OWN001` on the undisposed command is **sound for Microsoft.Data.Sqlite** and
   **unsupported for Npgsql**, where it is an error-severity, build-failing finding about an
   object whose `Dispose` provably frees nothing.
3. That is **not** an argument for exempting `DbCommand`: the analyzer cannot tell the two apart
   where the obligation is minted, and the SQLite case is a genuine native-handle deferral.
   Suppressing `DbCommand` to remove the Npgsql false positive would delete a true positive
   elsewhere. This is the decision the note exists to enable.
4. The sharper defect in this family is **not** the command. It is that `reader` — load-bearing on
   Npgsql (§5.2) and a real leak on a multi-result-set reader (§4.1) — is dropped by the escape
   rule with no callee fact recorded. On Npgsql with tracing on the verdict is **inverted**:
   error on the harmless object, silence on the harmful one.

**Pivot record.** The investigation moved from "is the command a leak?" to "what is the ownership
relation `connection → command → reader`?", because the command question resolved to a provider
table while the *relation* is where a reproducible, ownership-semantic, practically consequential
witness turned up (§5.2, §7.3).

---

## 10. Minimal next step

A model gap is proved (§7.3), so — and only so — the smallest experiment that would close it. It
is **an instance of [#382](https://github.com/PhysShell/Own.NET/issues/382), not a parallel
architecture**: #382 already names this exact lowering and this exact loss (*"the lowering still
destroys two facts: that an interprocedural call happened, and which callee parameter received
which resource"*). The connection is demonstrable: the witnessed H-28 label
`DataTable.Load → RELEASE_IF_LAST_RESULT_SET` *is* a callee-parameter effect, which is the
vocabulary #382 proposes to stop guessing at in the frontend. `proven_call` (OwnIR v2, H1 —
`docs/notes/h1-proven-call.md`) is the landed precedent for the transport: the frontend emits a
call-shaped op, the core decides.

| | |
|---|---|
| **Observed semantics** | `DataTable.Load(reader)` calls `reader.Close()` iff the first result set is the last, else the reader stays open; it never affects the command. `DbCommand.Dispose()`'s effect is provider-defined: nothing (Npgsql/SqlClient/MySqlConnector) or native statements + the reader (Microsoft.Data.Sqlite). |
| **Current representation** | The `Load` call is erased — `reader` joins `escapedLocals`, no `call` op (L7155-7182). The command's obligation is minted by `IsOwningFactory` (L4880) with no dispose-effect attribute; `IsDisposeOptional` (L2593) is the only "Dispose frees nothing" channel, keyed on namespace+type name. |
| **Missing fact** | (a) that an external call received the tracked reader, with the callee identity, so a witnessed-effect table can be consulted at all; (b) **conditionally** — the effect depends on `NextResult()`, which no static fact can settle. |
| **Smallest representation change** | #382's, restricted: emit a `call` op for an argument pass to an **external** callee instead of a bare escape, carrying `(callee, argument → parameter)`. No new lattice, no new diagnostic code, no provider special-casing. (b) then resolves to *may-release*, not *release* — the honest answer, needing no new vocabulary. |
| **Positive fixture** | `fx/CommandDispose.cs` variant **B** (single result set): `reader` carries a `call` fact to `DataTable.Load`, the core consults the witnessed label and reports `may-released`, leaving `OWN001` on `command` as the only finding. |
| **Negative / control fixture** | Variant **E** (no `Load`) must still report `OWN001` on **both** — proving the `call` fact did not become a blanket exemption. **A**/**D** must stay clean. |
| **Mutation / falsifier** | A multi-result-set reader passed to `Load`: `reader.IsClosed` is `false` afterwards (§4.1). Any representation recording `Load` as an unconditional release is falsified by it. Runtime probe **P4** falsifies §5.2 if `stopped=1` on variant B. |
| **Expected verdict delta** | B: `OWN001 command` unchanged, `reader` moves from *silently untracked* to *tracked-with-a-witnessed-may-release*. E: unchanged (2 findings). No finding is added or removed on this fixture — the delta is that the reader's disposition becomes a **recorded fact** instead of an erasure, which is what makes the multi-result-set false negative reachable later. |
| **Soundness risk** | Low and bounded, *provided* the label is entered as `RELEASE_IF_LAST_RESULT_SET` (conditional), never as `RELEASE`; unconditional would suppress a real leak on multi-result-set readers — a false negative worse than today's silence because it would look justified. Second risk: a `call` op for external callees widens what reaches the core, so #382's own gate applies unchanged (the H-28 `RECORD_AND_STOP` balance: ~1 true positive against ~110 sites each needing a proven effect) and must be re-checked before any default flips. |

**Explicitly not proposed:** a TLA+ model, a P-037 change, a new summary lattice, provider-wide
Npgsql special cases, a universal ADO.NET model, a Roslyn frontend rewrite, or a new diagnostic
code. The provider dimension on `IsOwningFactory` (§7.3) is deliberately **left open**: it needs a
decision about where provider knowledge may live at all, which is larger than H-28 and should not
be settled by it.
