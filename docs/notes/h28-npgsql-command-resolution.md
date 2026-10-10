# H-28-CMD — resolving the undisposed `DbCommand` question

**Status: inconclusive pending three required gates. No production-code change.**
Current verdict: **H28-INCONCLUSIVE**. This is deliberately not the earlier
`H28-PROVIDER-SPECIFIC` verdict: source reading gives a provider-specific *prediction*, but the
real provider run and the production Roslyn → OwnIR → core run have not yet completed.
Artifacts and required reproductions: [`corpus/ownership-lab/h28-command/`](../../corpus/ownership-lab/h28-command/).

```csharp
var command = connection.CreateCommand();
var reader  = command.ExecuteReader();
var table   = new DataTable();
table.Load(reader);          // neither command nor reader is explicitly disposed
```

Every `evidence/*.txt` source excerpt is re-derived from its declared upstream ref and records
the git blob SHA, file SHA-256, path and line range; tagged refs are pinned, while moving `main` /
`master` snapshots are explicitly ancillary. The Npgsql finalizer absence also has a saved
full-file negative-scan artifact. Run `python3 corpus/ownership-lab/h28-command/scripts/derive_source_evidence.py`
to re-derive all 44 excerpts and that scan; non-zero means a source citation is stale.

---

## 1. Original uncertainty

H-28 was registered as *argument / callee ownership transfer*. Its demanding instance was
`victor-wiki/DatabaseManager` `DbInterpreter.GetDataTableAsync:699`, described in the
preregistration as *"connection is a parameter, command a local never disposed"*.

The old H-28 runtime falsifier settled the **reader** and explicitly left the **command** open:

> `DataTable.Load(IDataReader)` closes the reader … the demanding instance is NOT a lease /
> protocol leak … **what remains is the never-disposed DbCommand `cmd` (an object leak without a
> protocol consequence)**.

— `research/ownership-semantics-lab-v1@298b305`,
`corpus/ownership-lab/h28/scripts/h28_anchors_record.py`, field
`consequence_for_the_demanding_instance`.

That last sentence was a description, not a classification: it was never falsified, never
entered in the witnessed-callee table, and never reached a gate. That is the question addressed
here.

**Scope correction.** The earlier committed version pivoted from this provider/lifetime question
to a #382 argument-lowering model gap, treating a source-derived extractor prediction as if G3
had proved it. That was premature. This revision returns to the original H-28 command question;
#382 stays a candidate follow-up only if real Roslyn → OwnIR → verdict evidence establishes that
specific loss. No architecture conclusion is drawn in advance.

---

## 2. Recovered prior evidence

**H-28 is not on `main`.** Its primary artifacts are on `research/ownership-semantics-lab-v1`
@ `298b305`, under `corpus/ownership-lab/h28/` (36 files). The preregistration JSON lives in a
separate `Own.NET-paperwork` repository that is not reachable from this checkout; its contents
are recoverable from the committed generator `h28/scripts/h28_prereg.py`.

| claim | primary evidence | status |
|---|---|---|
| H-28 = argument/callee transfer, not command lifetime | `h28/scripts/h28_prereg.py` (`track`, `hypothesis`) | recovered |
| demanding instance = `DbInterpreter.GetDataTableAsync:699` | same file → `anchors.demanding_instance` | recovered |
| `DataTable.Load(reader)` closes the reader in the tested single-result case | `h28/falsifier/falsifier.out`, F1 `IsClosed=True` for Sqlite and Npgsql; `h28_anchors_record.py` → `RELEASE_IF_LAST_RESULT_SET` | measured in the old run |
| CA2000 (default options) does not report command or reader | `h28/analyzers/ca2000/{Repro2.cs,ca2000-warnings.txt}` | recorded |
| the undisposed `DbCommand` consequence | `h28_anchors_record.py` → `consequence_for_the_demanding_instance` | recorded, **not classified** |
| census gate → `RECORD_AND_STOP` | `h28/manual-read.json`, `h28/scripts/h28final.py`, `h28/h28-census-v1.json` | recovered |
| argument escape/drop rule | `h28/scripts/h28_prereg.py` → `necessary_condition_verified_by_code_reading`; current issue [#382](https://github.com/PhysShell/Own.NET/issues/382) | source observation; end-to-end witness pending |

Name collision: `H28` in `docs/notes/p022-bridge-verdict-checkpoint4b.md:216` is an unrelated
bridge-verdict hypothesis. It is not this ownership-lab H-28.

The old `h29/promotion/promo-u.facts.json` cannot stand in for a current production run: it is
OwnIR schema v1, while the current core accepts v2, and the core refuses it as stale.

---

## 3. Versions and source references

| component | version / ref | evidence |
|---|---|---|
| old runtime falsifier | .NET `net8.0`, Npgsql `10.0.3`, Microsoft.Data.Sqlite `10.0.12`, PostgreSQL 16 | `h28/falsifier/w28.csproj`, `h28/falsifier/falsifier.out` |
| BCL | `dotnet/runtime` `v8.0.20` and `v10.0.12` | pinned excerpts under `evidence/runtime-*` |
| Npgsql | tag `v10.0.3`; project targets `net8.0`, `net9.0`, `net10.0`; current source snapshot `main` | `evidence/npgsql-v10.0.3-target-frameworks.txt`, `evidence/npgsql-10.0.3-*`, `evidence/npgsql-main-*` |
| SQLite provider | `dotnet/efcore` tag `v10.0.12` | `evidence/mssqlite-*` |
| SQLite package TFM | `Microsoft.Data.Sqlite` package project targets `netstandard2.0`; its Core project targets `$(NetMinimum);netstandard2.0`, with EF Core 10's default .NET target `net10.0`. A `net8.0` falsifier selects the compatible `netstandard2.0` assets; .NET 10 is not required for this direct package use. | `evidence/mssqlite-v10.0.12-Microsoft.Data.Sqlite-target.txt`, `evidence/mssqlite-v10.0.12-Core-targets.txt`, `evidence/efcore-v10.0.12-default-net-target.txt` |
| SQLite native wrapper | `SQLitePCL.raw` tag `v2.1.12` (the version declared by EF Core 10.0.12) | `evidence/efcore-v10.0.12-SQLitePCLRawVersion.txt`, `evidence/sqlitepclraw-v2.1.12-*` |
| Own.NET | `main` @ `e889f8b`, extractor TFM `net8.0` | `frontend/roslyn/OwnSharp.Extractor/OwnSharp.Extractor.csproj` |

The cited BCL contracts and `DataTable.Load` body were compared at both runtime refs. The old
H-28 runtime falsifier only exercised the single-result-set path; the multi-result conditional
is source evidence, not a measurement from that run.

---

## 4. Ownership semantics and BCL contract

| object | created by | owner after creation | logical-lifetime operation | possible held state | does its disposal free another object? |
|---|---|---|---|---|---|
| `DbConnection` | caller / pool / DI | caller | `Close()` / `Dispose()` | provider connector, socket, buffers, server session | provider-specific; Npgsql connection shutdown also closes its current reader |
| `DbCommand` | `connection.CreateCommand()` | caller, absent explicit transfer | `Dispose()` ends command use; provider effects vary | provider-specific | provider-specific; see §5 |
| `DbDataReader` | `command.ExecuteReader()` | caller, absent explicit transfer | `Close()` or `Dispose()` | connector binding, provider buffers; Npgsql also stores an `Activity` on its command | not in the BCL contract; provider code may clean up reader-owned or associated state |
| `DataTable` | caller via `new` | caller | dispose-optional in Own.NET's current list | managed rows | `Load` has no command reference |

### Contract versus implementation

**BCL contract:** `IDbCommand : IDisposable`; `IDataReader : IDisposable` with a distinct
`Close()` method. Those interfaces guarantee the members, not what a provider releases
[`evidence/runtime-v10.0.12-IDbCommand.txt`]. `DbCommand : Component, IDbCommand, IAsyncDisposable`
and does not override `Dispose`; its `DisposeAsync()` calls `Dispose()`
[`evidence/runtime-v10.0.12-DbCommand-class.txt`,
`evidence/runtime-v10.0.12-DbCommand-DisposeAsync.txt`]. The actual meaning of command disposal
therefore depends on the provider. `DbDataReader.Close()` is an empty virtual default and its
base `Dispose()` calls `Close()`; provider implementations define the cleanup
[`evidence/runtime-v10.0.12-DbDataReader-Close-Dispose.txt`].

**Current `System.Data` implementation, not a universal interface guarantee:**
`DataTable.Load` delegates to `FillFromReader`, then:

```csharp
if (!reader.IsClosed && !reader.NextResult())
{
    reader.Close();
}
```

— `dotnet/runtime` `v10.0.12`, `DataTable.cs:4974`; the corresponding code is also present at
`v8.0.20` [`evidence/runtime-v10.0.12-DataTable-Load.txt`,
`evidence/runtime-v8.0.20-DataTable-Load.txt`]. It calls **`Close()`, not `Dispose()`**; on a
multi-result reader it may leave the reader open when `NextResult()` returns true; and it does
not reference or dispose the command. The original H-28 test measured only the one-result case.

---

## 5. Provider source observations (not yet runtime conclusions)

### 5.1 Npgsql `Dispose`: narrow claim only

In Npgsql `v10.0.3`, `NpgsqlCommand.Dispose(bool)` calls `ResetTransaction()`, sets
`CommandState.Disposed`, and, for a cacheable command with an empty connection cache, calls
`Reset()` and stores itself in `InternalConnection.CachedCommand`; otherwise it clears
`IsCacheable` [`evidence/npgsql-10.0.3-NpgsqlCommand-Dispose.txt`]. `Reset()` clears command text,
command type, parameters, timeout and flags [`evidence/npgsql-10.0.3-NpgsqlCommand-Reset.txt`].
`CreateCommand()` returns a command constructed with `IsCacheable=true`
[`evidence/npgsql-10.0.3-NpgsqlConnection-CreateCommand.txt`,
`evidence/npgsql-10.0.3-NpgsqlCommand-CreateCachedCommand.txt`].

Therefore **“Npgsql `Dispose` releases nothing” was too broad and is withdrawn**. It has an
observable effect on command state and can recycle the object into the connection's one-slot
cache. The source body shows no explicit release of a native handle or `DEALLOCATE` of a
server-side prepared statement. That does **not** prove a command is contractually dispose-optional,
that no other state is affected, or that `OWN001` is a false positive.

The provider source has no `~NpgsqlCommand` declaration and its public constructors call
`GC.SuppressFinalize(this)` [`evidence/npgsql-10.0.3-NpgsqlCommand-ctor-SuppressFinalize.txt`;
full-file scan is reproducible from the pinned source]. Prepared statements are managed through
the connector's `PreparedStatementManager`
[`evidence/npgsql-10.0.3-NpgsqlConnector-PreparedStatementManager.txt`]. **Connection/session
ownership does not logically prevent a command from issuing `DEALLOCATE`**; the relevant
falsifier is instead P5, which directly compares `pg_prepared_statements` before and after
`NpgsqlCommand.Dispose()` in the same PostgreSQL session. That provider runtime test is pending.

### 5.2 Npgsql reader `Close` versus `Dispose`: Activity hypothesis

When an Npgsql activity listener exists, `NpgsqlCommand.TraceCommandStart` stores the command
activity in `CurrentActivity` [`evidence/npgsql-10.0.3-NpgsqlCommand-TraceCommandStart.txt`,
`evidence/npgsql-10.0.3-NpgsqlActivitySource-IsEnabled.txt`,
`evidence/npgsql-10.0.3-NpgsqlActivitySource-SourceName.txt`]. `Activity` is disposable, and its
BCL `Dispose()` stops it [`evidence/runtime-v8.0.20-Activity-IDisposable.txt`,
`evidence/runtime-v8.0.20-Activity-Dispose.txt`]. In the pinned Npgsql source, reader `Dispose` and `DisposeAsync` invoke `TraceCommandStop`; public
reader `Close()` routes through the close path with `isDisposing:false` and does not invoke the
reader-dispose trace-stop path [`evidence/npgsql-10.0.3-NpgsqlDataReader-Dispose.txt`,
`evidence/npgsql-10.0.3-NpgsqlDataReader-DisposeAsync.txt`,
`evidence/npgsql-10.0.3-NpgsqlDataReader-Close-public.txt`,
`evidence/npgsql-10.0.3-NpgsqlCommand-TraceCommandStop.txt`].

This yields a **source-derived prediction, not yet a measured leak**: `DataTable.Load` calls
`reader.Close()`; if that closes the Npgsql reader without the `Dispose` path, an attached
listener may observe the command Activity remain started. The new P4 isolates one query per
variant and records immediately after `Load`, after `reader.Dispose()`, and after
`command.Dispose()`; no P2/P3 query is allowed between those snapshots. The Npgsql `ActivitySource`
is named `"Npgsql"`, which the listener must match. A failed P4 kills this hypothesis.

The same reader cleanup sets `Command.State = CommandState.Idle`, ends the connector user action,
clears `CurrentReader` and returns a pooled `ColumnInfo[]`
[`evidence/npgsql-10.0.3-NpgsqlDataReader-Cleanup.txt`]. `Idle` is evidence of command reuse,
not evidence that the reader owns or disposes the command.

### 5.3 Microsoft.Data.Sqlite: direct statement-count hypothesis

The cited provider version is pinned to the falsifier's **Microsoft.Data.Sqlite 10.0.12**.
`SqliteCommand` holds prepared `sqlite3_stmt` objects in `_preparedStatements`; an ordinary
`ExecuteReader()` uses `PrepareAndEnumerateStatements()`, which prepares a native statement and
first disposes any previous prepared set [`evidence/mssqlite-SqliteCommand-preparedStatements-field.txt`,
`evidence/mssqlite-SqliteCommand-PrepareAndEnumerate-head.txt`]. `SqliteCommand.Dispose(bool)`
calls `DisposePreparedStatements` and removes the command from the connection
[`evidence/mssqlite-SqliteCommand-Dispose.txt`,
`evidence/mssqlite-SqliteCommand-DisposePreparedStatements.txt`]. The reader's `Close()` delegates
to its reader disposal; that clears the command's `DataReader` and disposes the statement
**enumerator**, not the command's `_preparedStatements`
[`evidence/mssqlite-SqliteDataReader-Close-Dispose.txt`].

`sqlite3_stmt` is an owning `SafeHandle`; its `ReleaseHandle()` calls
`sqlite3_finalize` [`evidence/sqlitepclraw-sqlite3_stmt-SafeHandle.txt`], and the pinned BCL
`SafeHandle` has a finalizer [`evidence/runtime-v8.0.20-SafeHandle-finalizer.txt`,
`evidence/runtime-v10.0.12-SafeHandle-finalizer.txt`]. Thus source
predicts that command disposal is the **deterministic release path** for those command-held
handles; without it, SafeHandle finalization is a later GC fallback. This matters to a resource-lifetime
analysis, but does not turn source reading into a runtime measurement.

G2 now observes the resource directly using public `SqliteConnection.Handle`
[`evidence/mssqlite-SqliteConnection-Handle.txt`] and
`SQLitePCL.raw.sqlite3_next_stmt` [`evidence/efcore-v10.0.12-SQLitePCLRawVersion.txt`,
`evidence/sqlitepclraw-v2.1.12-sqlite3_next_stmt.txt`]. SQLitePCLRaw v2 disables its managed
pointer-to-`SafeHandle` lookup by default, so the harness calls
`db.enable_sqlite3_next_stmt(true)` immediately after opening the connection;
`sqlite3_stmt.From` registers each resulting handle, and `find_stmt` maps each enumerated pointer
back to that handle [`evidence/sqlitepclraw-v2.1.12-enable-next-stmt.txt`,
`evidence/sqlitepclraw-v2.1.12-find-stmt-enabled.txt`,
`evidence/sqlitepclraw-sqlite3_stmt-SafeHandle.txt`]. It neither samples RSS nor forces GC.
Expected differences from the direct pre-query baseline: 0 at baseline; +1 after `ExecuteReader`;
still +1 after `DataTable.Load`/reader close and after `reader.Dispose`; back to 0 after
`command.Dispose`. A second execution on the **same command** must replace the old statement
(count stays at baseline + 1), not accumulate to baseline + 2. These are assertions in the
executable harness, not results yet.

The historical side-claim that SqliteConnection strongly retains commands is not used: the
pinned 10.0.12 source shows a `List<WeakReference<SqliteCommand>>`
[`evidence/mssqlite-SqliteConnection-commands-weakrefs.txt`].

### 5.4 Other provider snapshots are ancillary

The artifacts also retain current-source snapshots for Microsoft.Data.SqlClient and
MySqlConnector. They are on moving repository refs and are not runtime-tested here; they are
context only, not the basis of this report's verdict. No universal conclusion is drawn from them.

---

## 6. Runtime and executable evidence status

**This sandbox has no `dotnet` executable**, so it cannot restore/build the falsifier or run the
production Roslyn extractor. Earlier network checks also found the NuGet hosts unreachable here.
The previous attempt to query PostgreSQL 16.2 via `pgserver` only established session-scoped
server catalog behavior; it **does not prove** what Npgsql `Command.Dispose()` does and is not
used as evidence for P5. The report withdraws that earlier inference.

**Local validation actually run:** source derivation passed for all 44 excerpts plus the pinned
Npgsql finalizer scan; `tests/test_corpus.py` passed 33/33; whole-tree `ruff check .`, `mypy`
(60 source files), Python syntax/lint checks, `bash -n`, and a C# grammar parse passed. The
pinned pgserver 0.1.4 supervisor API also started a temporary PostgreSQL server and produced the
expected Unix-socket Npgsql connection string; no .NET provider command was run. The C#
grammar parse is not a compiler result. The repository's `python tests/run_tests.py` did not
complete: its early analysis/codegen checks passed, but later history checks need a non-shallow
clone and the checkpoint test invokes `cargo`, which is not installed. This is not recorded as a
green full-suite run. Finally, `run.sh all-required` was executed in this sandbox and correctly
returned 1 because it could not run G3 or G1/G2 without the .NET 8 SDK; exact output is saved at
`evidence/required-gates-local.txt`. The manual OwnIR engine subcheck inside that command passed,
but it is not a substitute for G3. The local validation transcript, including the incomplete
repository suite's environment failure, is saved at `evidence/local-validation.txt`; the source
fetch/re-derivation transcript is `evidence/source-derivation-local.txt`.

The executable under `falsifier/` is corrected and bounded:

| gate / probe | direct observation | falsifier |
|---|---|---|
| **G1** compile | `dotnet build` of the runtime harness; the build also compiles `fx/CommandDispose.cs` | a compile error means the harness is not runnable |
| **P1–P3** lifecycle controls | reader closed after `Load`; command reuse; next command on same connection | separates reader/command logical usability and protocol busy state |
| **P4** Npgsql Activity | one `ExecuteReader` + one `Load`; snapshots at the three lifecycle points; no interposed query | no started/stopped difference at the direct snapshots kills the Activity claim |
| **G2 / P6** SQLite native state | `sqlite3_next_stmt` before/after execute, Load, reader Dispose, command Dispose, and same-command re-execution | no count change at command Dispose or reader-only release of the statement falsifies the source prediction |
| **P5** PostgreSQL prepared state | same-session `pg_prepared_statements` before `Prepare`, after, and after `command.Dispose()` | unchanged count across Dispose supports no server-statement release; a decrease refutes it |
| **G3** Own.NET end-to-end | production extractor → emitted OwnIR → solved summaries → core SARIF | any finding/anchor mismatch refutes the source-derived prediction below |

`run.sh` no longer curls NuGet as a proxy for dependency availability: it tries `dotnet restore
--ignore-failed-sources`, allowing a warm package cache to work offline. Results are explicit:
`PASS`, `FAIL`, or `SKIP`. `run.sh all` is a convenient local run; **`run.sh all-required` converts
any SKIP into a non-zero failure**. The new
`.github/workflows/h28-command-falsifier.yml` runs `all-required` on this PR and preserves the
facts, summaries, SARIF and runtime logs as an artifact. This sandbox run remains pending until
that workflow supplies real G1–G3 results.

---

## 7. Current Own.NET behavior: predicted, not end-to-end confirmed

`OWN001` means *"an owned resource is acquired but not released on every path … a possible
leak"* (`ownlang/diagnostics.py`, OWN001 catalogue entry). It does **not** assert an OS-handle
leak, nor does this investigation redefine the diagnostic as one. An error-severity finding is
not by itself proof that the provider's Dispose is operationally necessary.

Source reading of `frontend/roslyn/OwnSharp.Extractor/Program.cs` at `e889f8b` predicts:

1. `IsOwningFactory` (L4832, ADO.NET tranche L4877–4885) recognizes `IDbConnection.CreateCommand`
   returning `IDbCommand` and `IDbCommand.ExecuteReader` returning `IDataReader`. The local-flow
   pass adds these results to candidates (L7035–7036).
2. `IsDisposeOptional` (L2593–2606) exempts `DataTable`, not `DbCommand`.
3. The flow pass's argument escape adds a tracked local passed to an unrecognized external call
   to `escapedLocals` (L7155–7162), then removes it from tracked locals (L7182). `DataTable.Load`
   has no current summarized effect. This predicts `reader` is dropped at `table.Load(reader)`.
4. The predicted C# result is OWN001 on the undisposed `command`, silence on `reader` in B.
   Variants A/D/G should be clean; E should report both command and reader.

The engine-only fixture `fx/CommandDispose.own` was run and reproduces its **manual reduction**
(three expected OWN001s: command in B and E; reader in E; A/D clean). This validates the core on
handwritten OwnIR-like operations **only**. It is not evidence that the production C# extractor
emits those operations. `scripts/verify_g3.py` now performs and asserts the missing production
C# → facts → summaries → SARIF path, writing each intermediate artifact under `evidence/`.
Its actual result is pending G3.

The #382 connection is consequently **a concrete candidate witness, not yet experimentally
established**: issue #382 describes this argument-lowering loss, but until G3 reproduces the
predicted dropped-reader/command finding pair, this report does not claim a proven model gap.

---

## 8. Review corrections and falsifiers

| review concern | correction in this revision | status here |
|---|---|---|
| P4 observed Activity after P2/P3 had executed extra SQL | P4 is a separate helper: one query, snapshots immediately after Load / reader Dispose / command Dispose. P1–P3 run without an ActivityListener. | implemented; .NET run pending |
| P6 forced GC before RSS and measured allocator-dependent memory | replaced by direct `sqlite3_next_stmt` live-handle enumeration through `SqliteConnection.Handle`; no RSS, no GC; includes same-command re-execution control | implemented; .NET run pending |
| `NpgsqlConnection.ExecuteScalarAsync` probably does not compile | query now uses `CreateCommand()` + `ExecuteScalar()`; G1 builds both harness and C# fixture | fixed in source; build pending |
| PostgreSQL session scope does not imply command cannot send DEALLOCATE | removed that inference; P5 directly tests the actual Npgsql command before/after Dispose | corrected; P5 pending |
| “Dispose releases nothing” ignores cache/state effects | narrowed to “no explicit native-handle or server `DEALLOCATE` release is visible in this Dispose body”; records the state transition/cache effect | corrected |
| OWN001 is a possible-leak diagnostic, not an OS-handle oracle | states its repository wording; no false-positive conclusion from source inspection alone | corrected |
| “finding is inverted” was too categorical without G3 | withdrawn; current wording is a source-derived prediction, pending real extraction and runtime tracing | corrected |
| NuGet curl blocks a warm package cache; optional SKIP can be green | restore is attempted with `--ignore-failed-sources`; `all-required` fails on any SKIP and is the PR workflow gate | implemented; workflow pending |

The SQLite, Npgsql and BCL observations above were attacked with provider-source counterchecks;
none substitutes for G1–G3. If those gates disagree, the report and verdict must change.

---

## 9. Verdict

# H28-INCONCLUSIVE

Source inspection makes a provider-specific effect **plausible and testable**: Microsoft.Data.Sqlite
appears to keep native statement handles on `SqliteCommand`, while Npgsql's command Dispose body
shows command-state/cache work but no explicit native-handle or `DEALLOCATE` operation. The
Npgsql `Close`/`Dispose` Activity distinction is also a clear source-derived prediction.

But the mandated differentiating runtime observations and current production extraction are not
executed yet. This report therefore does **not** decide whether an undisposed command in the
Npgsql target family is benign, a contract-level ownership defect, or a misleading OWN001; it
does **not** label OWN001 a false positive; and it does **not** claim a proven Own.NET model gap.
The one final verdict is **H28-INCONCLUSIVE** until G1, G2 and G3 pass or falsify the predictions.

---

## 10. Bounded next step — no architecture proposal

Run the three kill-first gates in the new required workflow (or locally):

```bash
corpus/ownership-lab/h28-command/run.sh all-required
```

| gate | must observe | kill / required response |
|---|---|---|
| **G1** compile + isolated P4 | build succeeds; direct snapshots show whether reader Dispose, not command Dispose, stops the Activity | compile failure means the harness is not usable; no lifecycle difference retracts the Activity claim |
| **G2** native SQLite statements | direct statement count changes at the operation predicted by source; same-command second execute does not accumulate | no statement-count effect at command Dispose retracts the claimed native-release consequence |
| **G3** production C# → OwnIR → summary → verdict | exact expected `OWN001` anchors from `verify_g3.py` | any mismatch corrects the report's Own.NET behavior; until it matches, do not claim a model gap or advance #382 from this witness |

No new summary domain, provider registry, P-037 work, diagnostic, or analyzer rule is proposed. The
#382 relationship remains a follow-up candidate only if G3 proves the loss on this exact source.
