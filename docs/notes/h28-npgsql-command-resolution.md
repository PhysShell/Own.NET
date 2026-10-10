# H-28-CMD — resolving the undisposed `DbCommand` question

**Status: required gates passed in CI; no production-code change.**
Current verdict: **H28-PROVIDER-SPECIFIC**, narrowly bounded to the tested Npgsql 10.0.3 and
Microsoft.Data.Sqlite 10.0.12 paths. This does not call OWN001 a confirmed false positive or a
native-leak detector. The mandatory workflow run [#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923)
passed `all-required` and uploaded the `h28-command-falsifier` artifact; its status record is
[`evidence/ci-run-38048287923.txt`](../../corpus/ownership-lab/h28-command/evidence/ci-run-38048287923.txt).
Artifacts and reproducible gates: [`corpus/ownership-lab/h28-command/`](../../corpus/ownership-lab/h28-command/).

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
had proved it. That was premature at the time. This revision returns to the original H-28 command
question; G3 now confirms the specific extraction loss on this fixture, which supports a bounded
follow-up candidate but does not justify a universal architecture conclusion. No #382 change is
made here.

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
| argument escape/drop rule | `h28/scripts/h28_prereg.py` → `necessary_condition_verified_by_code_reading`; current issue [#382](https://github.com/PhysShell/Own.NET/issues/382) | G3 reproduces the predicted drop on this fixture; broader architecture conclusions remain out of scope |

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

## 5. Provider source observations and bounded runtime results

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
ownership does not logically prevent a command from issuing `DEALLOCATE`.** P5 directly compared
`pg_prepared_statements` before `Prepare`, after `Prepare`, and after `NpgsqlCommand.Dispose()` in
the same temporary PostgreSQL 16 session. The P5 assertion passed in workflow run
[#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923): the explicit prepared
statement count increased after Prepare and did not decrease after command Dispose. This result
is limited to that provider version and tested command; it neither says Dispose has no effect nor
proves behavior for every prepared statement or native resource. The full runtime output is in
the uploaded `h28-command-falsifier` artifact.

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

G1/P4 ran in the required workflow and its assertions passed. With the listener attached to the
Npgsql `ActivitySource`, the isolated one-query arm observed one started / zero stopped immediately
after `DataTable.Load`; explicit `reader.Dispose()` changed that to one started / one stopped.
In the command-only arm, `command.Dispose()` left the snapshot at one started / zero stopped.
The P4 helper contains no P2/P3 query between these lifecycle snapshots. This is evidence of an
unfinished tracing Activity under the tested conditions—not proof of an OS/native leak, nor a
claim about Npgsql without an ActivityListener. The exact run output is in the attached CI artifact.

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
`evidence/runtime-v10.0.12-SafeHandle-finalizer.txt`]. Source predicts that command disposal is the **deterministic release path** for those
command-held handles; without it, SafeHandle finalization is a later GC fallback. The runtime
measurement below tests the deterministic path directly and does not infer a leak from memory.

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
G2's direct-count assertions passed in workflow run [#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923): the count delta was +1 after `ExecuteReader`, stayed +1 after `DataTable.Load`/reader close and `reader.Dispose`, and returned to baseline after `command.Dispose`. A second execution on the **same command** stayed at baseline + 1 rather than accumulating a second statement, then final command disposal returned it to baseline. This establishes deterministic statement release for the tested SQLite provider path; it does not establish a permanent leak if the command is simply allowed to become unreachable, and no RSS or GC inference was used. Raw counts and logs are in the uploaded CI artifact.

The historical side-claim that SqliteConnection strongly retains commands is not used: the
pinned 10.0.12 source shows a `List<WeakReference<SqliteCommand>>`
[`evidence/mssqlite-SqliteConnection-commands-weakrefs.txt`].

### 5.4 Other provider snapshots are ancillary

The artifacts also retain current-source snapshots for Microsoft.Data.SqlClient and
MySqlConnector. They are on moving repository refs and are not runtime-tested here; they are
context only, not the basis of this report's verdict. No universal conclusion is drawn from them.

---

## 6. Runtime and executable evidence status

**The producing sandbox has no `dotnet` executable**, so its local strict run could not build the
falsifier or execute the extractor; see `evidence/required-gates-local.txt`. The required PR
workflow then ran on commit `008a21736e83139954d4ed1b34ab89fc8a194a00` and completed successfully:
job `H-28 required runtime + extractor gates`, step `Run mandatory G1-G3 gates (SKIP is failure)`
passed in run [#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923). Since
`all-required` returns non-zero on any SKIP, the compiled G1/P4, direct SQLite G2, PostgreSQL P5,
and production-extractor G3 assertions all ran and passed. The workflow uploaded the
`h28-command-falsifier` artifact containing raw observations, facts, summaries, SARIF and logs;
status metadata is saved at `evidence/ci-run-38048287923.txt`. The sandbox cannot download the raw
artifact from GitHub's Actions results store, so the exact trace files remain available from the
linked workflow run rather than copied into this checkout.

A previous standalone `pgserver` catalog check established only session-scoped server behavior;
it did **not** prove what Npgsql `Command.Dispose()` does and is not used as evidence for P5.

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

| gate / probe | result in workflow run #38048287923 | falsifier / scope |
|---|---|---|
| **G1** compile | runtime harness and linked C# fixture built successfully under `net8.0` | a compile error would have failed the required gate |
| **P1–P3** lifecycle controls | state/reuse/connection observations were emitted; they are descriptive controls, not pass/fail assertions | separate logical usability from resource-release claims |
| **P4** Npgsql Activity | assertions passed: after Load `started=1, stopped=0`; after reader Dispose `1,1`; command-only Dispose remains `1,0`; one query per arm | different snapshots or an interposed query would invalidate the tracing claim |
| **G2 / P6** SQLite native state | `sqlite3_next_stmt` delta assertions passed at baseline, ExecuteReader, Load, reader Dispose, command Dispose, and same-command re-execution | no native statement delta at command Dispose or accumulation on reuse would falsify the source prediction |
| **P5** PostgreSQL prepared state | same-session count increased after Prepare and was unchanged after command Dispose; assertion passed | a decrease would refute the bounded result for this explicit statement |
| **G3** Own.NET end-to-end | production extractor → OwnIR → summaries → SARIF matched the exact expected OWN001 anchors; assertion passed | any finding/anchor mismatch would falsify the source-derived extraction prediction |

`run.sh` no longer curls NuGet as a proxy for dependency availability: it tries `dotnet restore
--ignore-failed-sources -p:NuGetAudit=false`, allowing a warm package cache to work offline. Results
are explicit: `PASS`, `FAIL`, or `SKIP`. `run.sh all` permits environment SKIPs for local use;
**`run.sh all-required` converts any SKIP into a non-zero failure**. The PR workflow ran this strict
mode successfully and preserved the facts, summaries, SARIF and runtime logs in the
`h28-command-falsifier` artifact.

---

## 7. Own.NET behavior: G3 reproduced the predicted extraction pattern

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

The engine-only fixture `fx/CommandDispose.own` reproduces its **manual reduction** (three
expected OWN001s: command in B and E; reader in E; A/D clean). That is still only a core check on
handwritten operations. Separately, G3 ran the production C# → OwnIR → summaries → SARIF path and
passed its exact finding-anchor assertion in workflow run [#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923).
The emitted facts, summaries, SARIF and log are in the attached `h28-command-falsifier` artifact.
The verified pattern is OWN001 on `command` and silence on `reader` in B; both findings in E;
A/D clean; and the predicted command finding in the other controls.

This confirms an extractor behavior on this fixture: passing the tracked `reader` to
`DataTable.Load` does not yield a corresponding release fact in the current C# → OwnIR path. It
supports #382 as a follow-up candidate, but does not establish that every argument escape is wrong,
prove an OS/native leak, or authorize architecture work in this PR.

---

## 8. Review corrections and falsifiers

| review concern | correction in this revision | status here |
|---|---|---|
| P4 observed Activity after P2/P3 had executed extra SQL | P4 is a separate helper: one query, snapshots immediately after Load / reader Dispose / command Dispose. P1–P3 run without an ActivityListener. | G1/P4 passed in workflow run #38048287923 |
| P6 forced GC before RSS and measured allocator-dependent memory | replaced by direct `sqlite3_next_stmt` live-handle enumeration through `SqliteConnection.Handle`; no RSS, no GC; includes same-command re-execution control | G2 assertions passed in workflow run #38048287923 |
| `NpgsqlConnection.ExecuteScalarAsync` probably does not compile | query now uses `CreateCommand()` + `ExecuteScalar()`; G1 builds both harness and C# fixture | G1 build passed in workflow run #38048287923 |
| PostgreSQL session scope does not imply command cannot send DEALLOCATE | removed that inference; P5 directly tests the actual Npgsql command before/after Dispose | P5 passed; tested statement count unchanged after Dispose |
| “Dispose releases nothing” ignores cache/state effects | narrowed to “no explicit native-handle or server `DEALLOCATE` release is visible in this Dispose body”; records the state transition/cache effect | corrected |
| OWN001 is a possible-leak diagnostic, not an OS-handle oracle | states its repository wording; no false-positive conclusion from source inspection alone | corrected |
| “finding is inverted” was too categorical without G3 | replaced with a bounded statement: G3 confirms the command-finding / reader-silence pair, while P4 observes an unfinished Activity under its listener; neither proves a native leak or OWN001 false positive | G1/G2/G3 assertions passed; interpretation remains narrow |
| NuGet curl blocks a warm package cache; optional SKIP can be green | restore is attempted with `--ignore-failed-sources`; `all-required` fails on any SKIP and is the PR workflow gate | required workflow passed; artifact uploaded |

The SQLite, Npgsql and BCL source observations above were checked against the successful G1–G3
run. The verdict is bounded to those tested provider versions and assertions; if a later run
contradicts them, the report and verdict must change.

---

## 9. Verdict

# H28-PROVIDER-SPECIFIC

The required G1–G3 run passed for the tested Npgsql `10.0.3` / PostgreSQL 16 and
Microsoft.Data.Sqlite `10.0.12` paths (workflow run [#38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923); raw output in artifact `h28-command-falsifier`). For those tests:

- **SQLite:** direct `sqlite3_next_stmt` observations show the command-held statement remains
  after Load and reader disposal, then returns to baseline on command disposal; reusing the same
  command replaces rather than accumulates the statement. This establishes a deterministic
  native-statement release effect for this provider path. It does not prove a permanent leak if
  the command later becomes unreachable and SafeHandle finalization occurs.
- **Npgsql:** `Dispose` changes command state and can cache/recycle the command. P5's explicit
  server-prepared-statement count did not decrease after command disposal in the tested session;
  this does not prove behavior for every prepared statement or any separate native handle. P4
  observed an Activity still started after Load and after command-only disposal, while reader
  disposal stopped it.
- **Own.NET:** G3 reproduced the predicted diagnostic pair on the actual C# fixture: OWN001 on
  `command`, but no reader finding after the `Load(reader)` argument pass. In the tested Npgsql
  tracing arm that pair can be **potentially misleading**: the command diagnostic does not
  identify the unfinished Activity, while the reader obligation is not reported. This is not a
  claim that OWN001 is a confirmed false positive, that an OS/native leak exists on Npgsql, or
  that every `DbCommand` behaves this way.

Thus **H28-PROVIDER-SPECIFIC** is a bounded verdict about observed provider effects, not a
provider-wide analyzer rule or a resolution of OWN001's ownership-contract meaning. No diagnostic,
production semantics, or architecture was changed; PR #399 remains open.

---

## 10. Scope boundary

G1–G3 are complete for this test correction; the workflow artifact at [run #38048287923](https://github.com/PhysShell/Own.NET/actions/runs/38048287923)
contains the detailed traces and G3 intermediates. The producing sandbox could not download the
artifact, so its status metadata is preserved locally and the full artifact remains available in
GitHub Actions.

This PR stops at the validated fixture and report. It proposes no new summary domain, provider
registry, P-037 work, diagnostic, analyzer rule, or #382 architecture change. Any follow-up should
be a separate decision based on the exact bounded evidence above. PR #399 remains open and is not
to be merged as part of this work.
