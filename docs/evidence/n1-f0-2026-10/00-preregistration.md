# N1-F0 — ownership feasibility gate — pre-registration

Written 2026-10-20, 21:51 +05, before any F0 run. Authority: owner decision
`ACCEPT-N1-COMPETITOR-GATE / GO-N1-OWNERSHIP-FEASIBILITY / NO-PRODUCTION`, on #417.

- **Budget.** 0.25 agent-day for F0-A, F0-B and F0-C together.
- **Outcome.** One verdict, `PASS-F0` or `KILL-N1`. `PASS-F0` does not authorise production work or a PoC.
- **Rules of the work.** No production, OwnIR, CI or golden change. No third-party build and no package download (D13).

## F0-A — finish the competitor check

**Run.** The four reproductions of #417 (`n1-competitor-gate-2026-10/repro`, stubs as a separate assembly), under:

| K | CA2000 settings |
|---|---|
| A1 | `AllPaths`, `interprocedural_analysis_kind = None` |
| A2 | `AllPaths`, `NonContextSensitive` |
| A3 | `AllPaths`, `ContextSensitive` |
| A4–A6 | A1–A3 plus `dispose_ownership_transfer_at_constructor = true` and `…_at_method_call = true` |

plus K1–K5 of #417 again, so that every configuration uses the new collector.

**Collector.** Every diagnostic whose location is inside the buggy **method** of each pair, from the first line of
its declaration to its closing brace, not only on the `ACQ` line. A diagnostic is **disposal-related** if its rule
is one of the following, or its message contains `dispos` (case-insensitive):

- CA2000, CA1001, CA2213, CA2215, CA2216;
- IDISP001–IDISP026;
- S2930, S2931, S3966, S4487.

**Verdict per pair.**

- **`CAUGHT`:** at least one disposal-related diagnostic in the buggy method names the leaked resource (its
  acquisition expression or its variable) in any configuration.
- **`ADJACENT`:** disposal-related diagnostics that name another object. They are listed and do not count.
- **`MISSED`:** otherwise.

**F0-A kill.** Fewer than 2 pairs `MISSED` → `KILL-N1`. The other parts are then not scored.

## F0-B — ownership oracle

**Oracle (fixed now).** A call result `r` acquired in method `M` of type `T` is **owned by `M`** only when all of
the following hold:

1. **Hand-over target.** On the success path, `M` hands `r` to one of:
   - (a) an instance field `f` of `T`;
   - (b) an element of a collection field `f` of `T` (indexer store, `Add`, `TryAdd`);
   - (c) a constructor argument of an in-source type `W` whose constructor stores it in a field `g` of `W`, where
     the `W` instance is returned or stored as in (a)/(b).
2. **The repository itself disposes that target.** The same type (`T`, or `W` for (c)) contains a
   `Dispose`/`DisposeAsync`/`Close`/`CloseAsync` call whose receiver is:
   - `f` or `g`;
   - a local obtained from `f` by `TryRemove(…, out x)`, `Remove(…, out x)`, an indexer read, or `foreach` over
     `f` / `f.Values`;
   - or `using` / `await using` of one of those.
3. **Not a borrow.** The acquisition call is not in the borrow table: `IServiceProvider.GetService`,
   `GetRequiredService`, `GetServices`, `GetKeyedService*`, `ActivatorUtilities.GetServiceOrCreateInstance`. The
   table only suppresses; it never creates ownership.

Ownership is **never** inferred from the result type being `IDisposable`/`IAsyncDisposable`, from a `Create*` name,
or from `await`. The result type matters only because rule 2 needs something to dispose.

**Defect, given ownership.** A call that can throw (any invocation or `await`, other than `nameof`/`typeof`) lies
between the acquisition and the hand-over, and no enclosing `try` disposes `r` on the way out (`catch` or
`finally` that disposes `r`, or a `published`-style flag guarding a dispose).

**F0-B inputs.**

- **Real code**, as single files from GitHub at the pairs' SHAs, parsed with framework references only:
  - R: rockbot `McpBridgeService.cs` base and fix;
  - B: BareWire `RabbitMqTransportAdapter.cs` base and fix;
  - X: NexusKit `PluginHostBuilder.cs` base and fix, plus `PluginHost.cs` at the same SHAs.
- **Negative controls** (`controls/OwnershipControls.cs`, written before the first run). Each must be **silent**:

| # | Control |
|---|---|
| N1 | DI-resolved: `var s = sp.GetRequiredService<IFoo>(); await X(); _foo = s;` with `T` disposing `_foo` (borrow table) |
| N2 | borrowed reference: a parameter stored into a field `T` disposes (not acquired by a call) |
| N3 | shared instance stored in a field `T` never disposes: `var c = Cache.Get(k); await X(); _c = c;` |
| N4 | caching factory into a dictionary `T` never disposes from |
| N5 | factory result handed over **before** any throwing call |
| N6 | the throwing step inside `try`/`catch` that disposes `r` and rethrows (the fixes' shape) |
| N7 | `published` flag + `finally` disposal (the rockbot fix's shape) |
| N8 | factory result used and disposed locally with `using` (no hand-over) |
| N9 | factory result returned to the caller (rule 1 has no return case: silent by design, an inter-procedural case) |

- **Positive samples**, which must be reported: the R, X and B shapes in synthetic form, P-R, P-X and P-B.

**F0-B pass.** All three of:

- the oracle reports the real R, X and B base files at the acquisition, with ownership established by rules 1–2,
  each citing the disposing line it found;
- it is silent on their fix files;
- N1–N9 are silent and P-R, P-X and P-B are reported.

Any failure → `KILL-N1`. The oracle must not be changed after the first run on the real files; control files may
be extended.

The oracle is a throwaway research scan (Roslyn, the same build route as the #416 PoC). It is not an Own.NET
implementation.

## F0-C — cost

Read the extractor (`frontend/roslyn/OwnSharp.Extractor/Program.cs`) and OwnIR (`ownlang/ownir.py`) and answer
three questions with file and line references:

1. Can the extractor emit an acquisition for a call result (rather than `new`) using an existing OwnIR fact kind?
2. Can it emit the hand-over (field, collection or wrapper store) as an existing release/move fact?
3. Are throw edges between acquisition and hand-over already expressible (the `--body-throw-edges` tier)?

**F0-C kill.** Any of the three needs a new OwnIR fact kind, a version bump, or a new interprocedural pass in the
core → `KILL-N1`. Needing only extractor-side work (emitting existing facts from new syntax) is acceptable, and
the estimate is reported.

## Verdict

`PASS-F0` only if F0-A, F0-B and F0-C all pass. Otherwise `KILL-N1`, naming the first failing part.
