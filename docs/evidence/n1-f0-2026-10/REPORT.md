# N1-F0 — ownership feasibility gate — report

**Result: `KILL-N1`. The first failing part is F0-B, and the failure is in the may-throw model, not in ownership.**

| Part | Verdict | Short reason |
|---|---|---|
| F0-A competitor check | **pass** | R, X, B stay `MISSED` under every `interprocedural_analysis_kind` and ownership-transfer setting, with every disposal-related diagnostic inside the method collected |
| F0-B ownership oracle | **fail** | ownership is established on all three real base files without name/type/`await` heuristics, but the **BareWire fixed file is flagged**: `Guid.NewGuid().ToString("N")` counts as a may-throw call before the hand-over |
| F0-C cost | pass (not decisive) | acquisition, hand-over and throw edges fit existing OwnIR ops; the existing throw model is the same coarse one that failed F0-B |

Rules: [`00-preregistration.md`](00-preregistration.md), committed in `66731cc2` before any F0 run. The oracle was
frozen in `081b68ee`, after its control-only debugging and before the one scored run on real files. Time used:
21:51–21:58 +05 on 2026-10-20 for the runs, inside the 0.25 agent-day budget.

No production, OwnIR, CI or golden change. Nothing third-party was built or downloaded.

## F0-A

[`scripts/run_f0a.py`](scripts/run_f0a.py) rebuilt the #417 reproductions under 11 configurations: A1–A6 cover
`interprocedural_analysis_kind` `None` / `NonContextSensitive` / `ContextSensitive`, each with and without both
ownership-transfer switches; K1–K5 repeat the #417 set. The collector takes every disposal-related diagnostic
located inside the buggy method's line span (`data/f0a_spans.tsv`), not only on the `ACQ` line.

Result (`data/f0a_method_diagnostics.tsv`):

| Pair | Result |
|---|---|
| W | CA2000 on `new ServiceBusClient(…)` in A1–A6 and K2–K4 (`CAUGHT`) |
| R | only CA2000 on `out var oldClient`, line 28, in all 11 configurations. That is another object, `ADJACENT`, so R stays `MISSED` |
| X | nothing (`MISSED`) |
| B | nothing (`MISSED`) |

3 pairs missed, against the required ≥ 2, so F0-A passes. No interprocedural setting changes anything.

## F0-B

**The oracle.** [`oracle/Program.cs`](oracle/Program.cs), a Roslyn scan, applies rules 1–3 as registered.
Ownership needs a hand-over target that the repository itself disposes, and the borrow table only suppresses. Two
details were fixed in the code header before the real run:

- **"Disposes r"** means any of: `Dispose`/`DisposeAsync`/`Close`/`CloseAsync` on `r`; the same call on an owning
  wrapper `new W(r)`; or `r` passed to a method of the same type that disposes its parameter.
- **One control-driven fix.** A dispose of `r` inside the `catch` is not a throwing site (control N6).

**Controls** (`data/f0b_controls.tsv`). N1–N9 are silent: DI-resolved, borrowed parameter, shared and cached
instances never disposed, hand-over first, `try`/`catch` dispose, `published` flag, `using`, returned. P-R, P-B and
P-X are reported.

**Real files** (`data/f0b_real.tsv`). Single files at the pairs' SHAs (hashes in `data/f0b_inputs.sha256`), parsed
with framework references only.

| File | Oracle | Ownership evidence it found |
|---|---|---|
| R base `McpBridgeService.cs` | reported at `McpClient.CreateAsync` (l. 561); throw at `await newClient.ListToolsAsync` (l. 564); hand-over `_clients[name]` (l. 577) | `_clients` element disposed: `oldClient.DisposeAsync()` (l. 573), with `oldClient` taken by `_clients.Remove(name, out var oldClient)` |
| R fix | silent | **no owned acquisition**: the fix hands the client over through `new ConnectionResources(newClient)` assigned to a local and an object-initializer member, which rules 1a–1c do not cover. Silent, but not because the cleanup was recognised |
| X base `PluginHostBuilder.cs` + `PluginHost.cs` | reported at `BuildServiceProvider` (l. 90); first throw at `provider.GetService<…>()` (l. 92); hand-over `return new PluginHost(provider)` (l. 136) | wrapper rule 1c: `PluginHost.mProvider` disposed at `PluginHost.cs:27` |
| X fix | silent | the `catch` disposes `new PluginHost(provider)`, an owning wrapper |
| B base `RabbitMqTransportAdapter.cs` | reported at `CreateChannelAsync` (l. 285); first throw listed at `Math.Min(…)` (l. 294), and `BasicQosAsync` lies in the same window; hand-over `_activeConsumerChannels[id]` (l. 321) | `channel.CloseAsync(…)` (l. 249) on a channel taken from `_activeConsumerChannels` |
| **B fix** | **reported** (FP) | ownership is right, but the only calls between `CreateChannelAsync` (l. 286) and the early hand-over (l. 300) are `Guid.NewGuid().ToString("N")` (l. 299). The registered rule "any invocation can throw" counts them |

By the registered pass rule, which requires silence on every fix file, F0-B fails. The oracle was not changed after
this run.

**What the failure means.**
- **Confirmed.** The ownership half works on these inputs:
  - it found the disposing line for all three real targets;
  - it stayed silent on all nine negative controls without any `IDisposable`, `Create*` or `await` cue;
  - in X and B it established ownership across a wrapper and across a collection.
- **Confirmed.** The registered may-throw rule is too coarse. One of three fixes is flagged only because of
  non-throwing BCL calls.
- **Inference, not scored.** A may-throw model that exempts such calls would clear B fix while keeping B base,
  because `BasicQosAsync` lies inside its window. Nothing was run to show it.
- **Limit.** The R fix shows a recall gap: a hand-over through a local wrapper or an object initializer establishes
  no ownership. A bug in that shape would be missed.

## F0-C

Read with line references in `main` (`38fb952d`):

1. **Acquisition from a call.** Already expressible: the flow-locals pass emits `acquire` for `new`, pool rents and a
   curated owning-factory table (`IsOwningFactory`, `frontend/roslyn/OwnSharp.Extractor/Program.cs:3832-3837`).
   For first-party factories the core can mint the acquire itself from a `call` op (P-005 D5.2,
   `Program.cs:3849`). An oracle-based acquire would be extractor-side only.
2. **Hand-over.** The existing `release` op can discharge the obligation (`ownlang/ownir.py:343-347`,
   `_FLOW_OPS`). Today a local stored to a field "escapes" and is not flow-tracked at all (`--flow-locals` covers
   non-escaping locals only, `Program.cs:84-87`). Changing that is extractor-side work.
3. **Throw edges.** These exist (`InjectThrowEdge`, `Program.cs:3569-3587`, `--body-throw-edges`). They use
   `StatementMayThrow` (`Program.cs:3590-3599`): any non-dispose call or `new` may throw. That is the same coarse
   model that failed F0-B, and the extractor itself calls this tier "the CA2000 firehose" (`Program.cs:100-103`).

None of the three needs a new OwnIR op, a version bump or a core interprocedural pass, so F0-C passes by its rule.
It also shows that a precise may-throw model does not exist yet; it would be new extractor work.

Estimate, an inference: the oracle port plus escape tracking is roughly several days of extractor work. A may-throw
model precise enough to clear cases like B fix has no estimate, because nothing like it exists in the repository.

## Files

- [`00-preregistration.md`](00-preregistration.md)
- [`controls/OwnershipControls.cs`](controls/OwnershipControls.cs)
- [`oracle/`](oracle/): the oracle, a Roslyn console, built like the #416 PoC.
- [`scripts/run_f0a.py`](scripts/run_f0a.py)
- `data/`:
  - `f0a_method_diagnostics.tsv`, `f0a_spans.tsv`: F0-A;
  - `f0b_controls.tsv`, `f0b_real.tsv`, `f0b_inputs.sha256`: F0-B.

The third-party source files are not committed; they are named by SHA and hash.
