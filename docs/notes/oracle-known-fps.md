# Oracle known false positives — triage of the 2026-06-27 five-repo run

Companion to [`oracle.md`](oracle.md). On 2026-06-27 the cross-tool oracle ran
over five top-200-NuGet, general-purpose libraries — **Newtonsoft.Json,
CsvHelper, serilog, NLog, protobuf-net** — diffing Own.NET against Infer# and
CodeQL. This note records the triage of every **own-only** finding against the
target's real source, so the verdicts are durable and the [FP
baseline](../../corpus/oracle-fp-baseline.txt) that suppresses them on re-runs is
auditable.

Headline: across all five repos, **0 own-only findings came from the new
owned-API recognition** (ADO `ExecuteReader`/`CreateCommand`, Xml/Json
`.Create`/`.Parse`, Socket `Accept`) — those libraries don't use those APIs in a
leaking shape, so the recognition extensions added **no noise on third-party
code**. Every own-only finding is a disposable-field or event-subscription
catch — Own.NET's differentiating niche, which the oracles' leak queries (local
not-disposed) structurally cannot express. `Agree = 0` on all five for the same
reason: we and the oracles occupy orthogonal niches.

## Disposition summary

20 own-only findings, triaged to ground truth:

| disposition | count | what happens on re-run |
|---|---:|---|
| **Fixed in the extractor** | 5 | no longer fire (all NLog `WaitForDispose` timers — see below) |
| **Baselined FP** | 7 | moved to "Known FP (baselined)", out of the triage queue |
| **Non-product (path filter)** | 2 | dropped by `--exclude-tests` (`unittest` rule) |
| **True positive — kept visible** | 4 | stays in "Own.NET only" (real catch, oracle can't express) |
| **True-but-benign — kept, baselined-as-sample** | 2 | (protobuf `assorted/` samples) baselined as non-product |

The 7 baselined FPs + the 2 non-product-sample reals = 9 findings, covered by
**8 rules** in `corpus/oracle-fp-baseline.txt` (the two `NetTranscoder` copies
share one basename-keyed rule); the 2 test-base findings are the `--exclude-tests`
drops; the 4 true positives are deliberately **not** suppressed.

**Update (extractor fix landed — all NLog timers).** All 5 of the original NLog
`WaitForDispose` timer FPs are now **fixed at the source**, baseline entries deleted.
Four (`AsyncTaskTarget._taskTimeoutTimer`/`_lazyWriterTimer`,
`AsyncTargetWrapper._lazyWriterTimer`, `BufferingTargetWrapper._flushTimer`) by
`CallReleasesReceiver` — a live NLog re-run confirmed own-only leak total **8 → 4**.
The fifth, `TimeoutContinuation._timeoutTimer` (disposed through the
`Interlocked.Exchange(ref _timer, null)` result), by `RefExchangeNulledField`, which
binds the exchange result to the field so the sink call is seen as a release
(own-only **4 → 3**, NLog baseline now empty). See root-cause #1. Corpus fixtures:
`field-dispose-via-helper`, `field-dispose-via-exchange`.

## Per-finding verdicts

### NLog/NLog — 8 findings (disposable fields)

| field / class | verdict | why |
|---|---|---|
| `_timeoutTimer` / TimeoutContinuation | **FP → baseline** | `Dispose()` → `StopTimer()` → `Timer.WaitForDispose()` on the `Interlocked.Exchange(ref _timer, null)` result (ref-alias, out of fix scope) |
| `_taskTimeoutTimer` / AsyncTaskTarget | **FP → fixed** | `Dispose(bool disposing)` → `Timer.WaitForDispose()` (direct field receiver) |
| `_lazyWriterTimer` / AsyncTaskTarget | **FP → fixed** | `Dispose(bool disposing)` → `Timer.WaitForDispose()` (direct field receiver) |
| `_lazyWriterTimer` / AsyncTargetWrapper | **FP → fixed** | `CloseTarget()` → `StopLazyWriterThread()` → `Timer.WaitForDispose()` (simple alias) |
| `_flushTimer` / BufferingTargetWrapper | **FP → fixed** | `CloseTarget()` → `Timer.WaitForDispose()` (simple alias) |
| `_xmlSource` / XmlParser | **true positive → keep** | never disposed (benign: a `CharEnumerator` over a `StringReader` over a string — no unmanaged resource) |
| `_reusableFileWriteStream` / FileTarget | **true positive → keep** | never disposed (benign: `ReusableStreamCreator` over a `MemoryStream` — managed memory only) |
| `_reusableBatchFileWriteStream` / FileTarget | **true positive → keep** | never disposed (same) |

`WaitForDispose(this Timer, TimeSpan)` (NLog `Common/AsyncHelpers.cs`) really does
dispose the timer (`Change(Infinite,Infinite)` then `Dispose()`). All five timer
FPs route disposal through it, on a **local alias** of the field
(`Interlocked.Exchange(ref _timer, null)` / `var t = _timer`), inside either a
`Dispose(bool disposing)` override or a `CloseTarget()` lifecycle hook. The
extractor's field-disposal scan only inspects the **top-level statements of the
parameterless `Dispose()`** for a direct `field.Dispose()` — so it sees none of
this.

### protobuf-net/protobuf-net — 7 findings

| location | verdict | why |
|---|---|---|
| `src/protobuf-net.Core/ProtoWriter.BufferWriter.cs` `_nullWriter` | **FP → baseline** | intentional null-object kept attached for pooled reuse; `Dispose()` comments *"don't cascade dispose to the null one"* |
| `assorted/.../ProtoTranscoder.cs` `sync` (×2 copies) | **true-but-benign → baseline (non-product sample)** | `NetTranscoder` isn't `IDisposable`; one `ReaderWriterLockSlim` for app lifetime in a sample/extension tree |
| `assorted/ProtoGen/CommandLineOptions.cs` `XsltMessageEncountered` | **FP → baseline** | self-subscription: publisher (`xsltOptions`) and the lambda are both owned by the same `CommandLineOptions`, co-lifetimed |
| `assorted/SilverlightExtended/Page.xaml.cs` `timer` | **FP → baseline** | disposed by an enclosing `using (timer) { … }` the extractor missed (sample code) |
| `src/BuildToolsUnitTests/AnalyzerTestBase.cs` `logging.Log` | **test noise → path filter** | xUnit fixture; per-test lifetime |
| `src/BuildToolsUnitTests/GeneratorTestBase.cs` `logging.Log` | **test noise → path filter** | xUnit fixture; per-test lifetime |

The two `BuildToolsUnitTests` findings are now dropped by `--exclude-tests`: that
camelCase project name is one dot-less path segment, which the exact dot-component
guards missed, so `_is_test_path` gained a safe `unittest` substring rule.

### serilog/serilog — 1 finding

| location | verdict | why |
|---|---|---|
| `BatchingSink.cs` `_shutdownSignal` (CancellationTokenSource) | **true positive → keep** | `Dispose()` *and* `DisposeAsync()` only call `_shutdownSignal.Cancel()`, never `Dispose()` — a genuine (if benign) undisposed CTS |

Not an async-dispose-tracing miss: the CTS is disposed in **neither** path. This
is a real catch the oracles' local-not-disposed query can't express, and it stays
visible.

### JamesNK/Newtonsoft.Json — 2 findings

| location | verdict | why |
|---|---|---|
| `TraceJsonReader.cs` `_textWriter` | **FP → baseline** | no-op dispose: a `JsonTextWriter` over an in-memory `StringWriter`/`StringBuilder` holds no unmanaged resource |
| `JsonSerializer.cs` `serializer.Error` | **FP → baseline** | intra-call self-subscription: the serializer is freshly built from the same `JsonSerializerSettings` whose `.Error` it subscribes; co-lifetimed |

### JoshClose/CsvHelper — 2 findings

| location | verdict | why |
|---|---|---|
| `docs-src/.../ConsoleHost.cs` `AppDomain.CurrentDomain.ProcessExit` | **FP → baseline** | process-lived subscriber (a docs-generator host) to a process-lived event source — promoting it to that lifetime is vacuous |
| `docs-src/.../ConsoleHost.cs` `Console.CancelKeyPress` | **FP → baseline** | same |

## Root-cause categories and the fix that would retire each baseline

The baselined FPs cluster into four analyzer limitations. Each baseline entry is a
standing request for the corresponding capability — when it lands, retire the
entry and let the oracle re-confirm clean.

1. **Custom dispose-sink — MOSTLY FIXED** *(was 5 NLog timers; 4 now cleared, 1
   remains).* The disposal scan already covers the whole class (so
   `Dispose(bool disposing)`, `CloseTarget()`, helper methods, simple `var t = _f;`
   aliases, and null-conditional `_f?.Dispose()` were all already handled) — the one
   gap was the disposing-method **name**: NLog releases its timers through a custom
   extension `WaitForDispose(this Timer)`, not a literal `.Dispose()`. **Shipped fix:**
   `CallReleasesReceiver` (extractor) credits `field.M(...)` as a release when `M` is a
   first-party extension method whose receiver it disposes — proved by reusing
   `ConsumesParam` on `M`'s reduced receiver parameter (inspects the real body, follows
   first-party forwarding, cycle-guarded, IDisposable-only), never guessed from the
   name. A live NLog re-run confirmed it: own-only 8 → 4, the 4 direct/simple-alias
   timers cleared. The fifth, `TimeoutContinuation._timeoutTimer`, disposes the result
   of `Interlocked.Exchange(ref _timer, null)`; **`RefExchangeNulledField`** now binds
   that exchange result to the field (the idiom atomically nulls the field and returns
   its owned object), so the `current?.WaitForDispose(...)` is seen as a release —
   own-only 4 → 3, the NLog baseline now empty. Restricted to a `null`/`default`
   replacement: an exchange installing a new non-null value re-arms the field and is
   declined (precision-first). **Still open:** the protobuf `Page.xaml.cs`
   `using (preExistingLocal)` local form, which remains baselined until using-statement
   alias tracking lands. Corpus fixtures: `field-dispose-via-helper`,
   `field-dispose-via-exchange`.

2. **No-op `Dispose` not modelled** *(Newtonsoft `TraceJsonReader._textWriter`).*
   We flag any undisposed `IDisposable` structurally, without modelling that the
   concrete `Dispose` releases nothing (`StringWriter`/`StringReader`/`MemoryStream`
   over managed memory). *Fix:* a small "dispose-is-a-no-op" allowlist of BCL
   in-memory types for the field case. (Related, already shipped for one case:
   [`cts-field-dispose-optional.md`](cts-field-dispose-optional.md).) Note the NLog
   `_xmlSource` / `_reusable*Stream` reals are the *same* benign shape but are
   **kept visible** — they're genuinely undisposed; only Newtonsoft's is also
   structurally a no-op AND not worth surfacing. Revisit whether benign-managed
   field leaks should be downgraded as a class.

3. **Lifetime-unaware subscription** *(protobuf `XsltOptions`, Newtonsoft
   `serializer.Error` self-subscriptions; CsvHelper process-lived host).* OWN014's
   premise — a long-lived source outlives a shorter-lived subscriber — fails when
   publisher and subscriber are **co-lifetimed** (same owner, or both freshly
   created in one call) or the subscriber is **itself process-lived**. *Fix:*
   compare subscriber vs. source lifetime (extend the `source: "self"` handling to
   co-created locals and to process-lived hosts) rather than keying on "source is
   static/injected". See [`subscription-leaks-and-profiles.md`](subscription-leaks-and-profiles.md).

4. **Non-product trees** *(protobuf `assorted/`, CsvHelper `docs-src/`, protobuf
   `BuildToolsUnitTests/`).* Sample/extension/doc-generator code that was never
   meant to be production-clean. The generic `unittest` rule now covers camelCase
   test projects; the remaining repo-specific sample trees (`assorted/`,
   `docs-src/`) are handled per-entry in the baseline rather than by polluting the
   generic `_is_test_path` with repo-specific directory names.

## How the baseline stays honest

- **Matched by name, not line** — `(repo, file-basename, OWN code,
  message-substring)`. Re-runs clone the target at HEAD and line numbers drift;
  the field/event/local name in the message does not.
- **Suppresses only confirmed FPs.** True positives (serilog CTS; NLog benign
  field leaks) are never baselined — they remain the visible proof the niche
  works.
- **Self-retiring.** Each entry names the fix that obsoletes it. When that lands,
  delete the line; if the FP was real after all, the oracle re-surfaces it.
- **Verified in CI.** `oracle_compare.py --selftest` covers the baseline
  loader, the name-not-line match key, repo scoping, the `*` wildcard, the
  render, and the `unittest` path rule.
