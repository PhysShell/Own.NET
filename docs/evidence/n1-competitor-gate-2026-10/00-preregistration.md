# N1 competitor gate — pre-registration

Written 2026-10-20, 21:11 +05. The four fix diffs have been read in order to build the reproductions. No analyzer
has been run on any reproduction.

Authority: owner decision `GO-N1-COMPETITOR-GATE`, given after `KILL-N3-PILOT` was accepted. This gate is not a GO
on an N1 PoC.

- **Budget.** 0.25 agent-day.
- **Rules of the work.** No third-party project is built and no package is downloaded. The analyzers come from the
  .NET SDK and from the local NuGet cache, the same versions as direction-research Phase 5.

## Question

N1: a disposable is acquired, a step that can throw runs before ownership is handed over (return, field or
collection store, wrapping), and no dispose runs on the throw path.

Do existing analyzers miss the four confirmed N1 defects of Phase 0 once they are configured to look? The question
matters most for CA2000 with exception paths on (`dispose_analysis_kind = AllPaths`), because that is the
documented setting for exactly this case.

## Why the earlier "not detected" does not answer it

Phase 5 ran the analyzers over loose source trees. Those runs had about 35,000 compile errors (whizbang: 34,859 on
base), so the disposable types were mostly unresolved, and CA2000 ran with its default kind. Those misses therefore
say little about what CA2000 can do.

## Pairs (fixed now)

| Id | Fix | Buggy method | Leaked resource and acquisition | Throwing step before hand-over | Hand-over on success |
|---|---|---|---|---|---|
| W | whizbang-lib/whizbang#1204 | `AzureServiceBusConnectionRetry.CreateClientWithRetryAsync` | `new ServiceBusClient(cs)` (`IAsyncDisposable`), inside a retry loop's `try` | `await VerifyNamespaceReachableAsync(…)` | `return client;` |
| R | MarimerLLC/rockbot#638 (record 638-2) | `McpBridgeService.ConnectServerAsync` | `await McpClient.CreateAsync(transport, …)`, an async factory (`IAsyncDisposable`) | `await newClient.ListToolsAsync(…)`, prompt listing | `_clients[name] = newClient;` (dictionary field) |
| X | NexusFFXIV/NexusKit#34 (record 34-2) | `PluginHostBuilder.BuildAsync` | `services.BuildServiceProvider(validateScopes: false)`, a factory (`ServiceProvider`, `IDisposable` + `IAsyncDisposable`) | `await DbInitializer.InitializeAsync(…)`, service resolution | `return new PluginHost(provider);` (wrapping) |
| B | Wizard-Software/BareWire#73 | `RabbitMqTransportAdapter.ConsumeAsync` (an `async` iterator) | `await _connection.CreateChannelAsync(…)`, an async factory (`IChannel`, `IAsyncDisposable` + `IDisposable`) | `await consumerChannel.BasicQosAsync(…)` | `_activeConsumerChannels[id] = consumerChannel;` (dictionary field) |

The four fixes are by different owners.

## Reproductions

For each pair: one file `repro/<Id>.cs` with two self-contained classes, `<Id>Buggy` and `<Id>Fixed`. The
acquisition line carries the marker comment `// ACQ:<Id>`.

- **Kept from the real code.**
  - the acquisition expression form: `new`, factory call, or awaited async factory;
  - the throwing step, as an awaited call that can throw;
  - the success hand-over (return, wrap, or dictionary store);
  - the enclosing control flow: the retry loop with `try`/`catch` in W, the `try` around the attempt in R, and the
    `async` iterator in B;
  - each fix's exact cleanup shape: W `try`/`catch` + `DisposeAsync` + rethrow, with acquisition through a
    `Func<…>` seam; R a nullable local, a `published` flag and cleanup on the failure path; X `try`/`catch` + wrap +
    `DisposeAsync` + rethrow; B early registration into the dictionary, then `try`/`catch` + release.
- **Third-party types are stubs** with the real disposable interfaces and the members used: `ServiceBusClient`,
  `McpClient`, `IChannel`/`IConnection`. `ServiceCollection`/`ServiceProvider` are the real types from the local
  ASP.NET Core reference pack.
- **Lines not on the resource's path are dropped**: logging, metrics, unrelated locals.
- The reproductions must compile with **0 errors**. An analyzer that sees a compile error proves nothing.

## Analyzers and configurations

One SDK-style project, `net10.0`, with no `PackageReference`. Analyzers are referenced by path:

- the .NET SDK `Microsoft.CodeAnalysis.NetAnalyzers` (CA2000);
- `IDisposableAnalyzers` 4.0.8 (IDISP001–IDISP026);
- `SonarAnalyzer.CSharp` 10.35.0.4138 (S2930 and others).

Every rule of every analyzer is set to warning (`dotnet_analyzer_diagnostic.severity = warning`). Configurations:

| K | `dispose_analysis_kind` | ownership transfer at constructor | ownership transfer at method call |
|---|---|---|---|
| K1 | default (`NonExceptionPaths`) | default (false) | default (false) |
| K2 | `AllPaths` | false | false |
| K3 | `AllPaths` | **true** | false |
| K4 | `AllPaths` | false | **true** |
| K5 | `AllPathsOnlyNotDisposed` | false | false |

**Harness control.** A two-method file, `Control.cs`:

- `new StreamReader(path)`, then a call that can throw, then `Dispose()`. CA2000 must report it under K2 and must
  not report it under K1.
- the same with `using`: silent in every configuration.

If this control fails, the harness is invalid and the gate stops as `INVALID`, not as KILL.

## Scoring (fixed now)

- **Relevant diagnostic.** A diagnostic whose message is about disposal or ownership, located on the leaked
  resource's acquisition statement or its declared variable, in the buggy method.
- **Pair verdict.**
  - **`CAUGHT`:** at least one configuration gives a relevant diagnostic on the buggy reproduction. This holds even
    when the fixed reproduction also gets one: a flag on the buggy site counts against N1's novelty. Whether the
    flag also distinguishes the fix is recorded separately.
  - **`MISSED`:** no relevant diagnostic on the buggy reproduction in any of K1–K5, from any of the three analyzers.

**Decision.**
- **`GO-CANDIDATE-N1`** (for an owner decision, not a PoC GO) if at least **2** pairs are `MISSED`.
- **`KILL-N1`** otherwise.

Fidelity risk: a stub or a dropped line can change an analyzer's result. Every `MISSED` is therefore re-checked by
listing the analyzer's documented limits for that shape: a factory, an `async` iterator or a dictionary store. A
`MISSED` that is explained only by a reproduction deviation from the real code becomes `UNRESOLVED` and does not
count toward GO.
