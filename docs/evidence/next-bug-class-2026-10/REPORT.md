# Next real-bug class selection (#382 / #406 / #400) — kill-first research report

**Result:** `GO-400`, narrowed. The first research slice of #400 moves from `List<T>`/`AsSpan` to
`Dictionary<TKey,TValue>` with `CollectionsMarshal.GetValueRefOrAddDefault` / `GetValueRefOrNullRef`. Two independent real
defects were found in that shape, and none in the original slice. #382 and #406: **NO-GO within the current evidence
budget**. No real defect was found within the pre-registered budget. That is not evidence that either direction is
useless, and both issues stay open.

**Owner decision (2026-10-18):** `ACCEPT RESEARCH RESULT / GO-400-DICTIONARY-PILOT`. One bounded Roslyn PoC, outside
production, is authorised after this report is published. Its acceptance gates are in §6.

Pre-registration, written before any experiment: [`00-preregistration.md`](00-preregistration.md).

## 1. Frozen experiment identity

| What | Value |
|---|---|
| Own.NET | `main` `2fefb19f` (merge #411); the research was run in a detached worktree, left clean afterwards |
| Extractor | built from `2fefb19f`, Release, net8.0; run with `--flow-locals [--stats]` |
| Python core | `python -m ownlang ownir|summaries` at `2fefb19f`; Python 3.12.10 |
| Rust core | `own-cli 0.1.0` built from `f8bd59be`. `rust/` is unchanged between `f8bd59be` and `2fefb19f`: #409 and #411 touched only the extractor, tests and `scripts/` |
| .NET | SDK 10.0.401; runtimes 6.0.36, 8.0.31, 10.0.12; the probes target net8.0 |
| Built-in analyzers | `Microsoft.CodeAnalysis.NetAnalyzers` from SDK 10.0.401, `AnalysisMode=All`, `AnalysisLevel=latest` |
| GitHub tooling | `gh` 2.96.0 for PR/issue/code search, `gh pr diff`, and raw files at pinned SHAs |
| Corpus 1 | the 58 bug/fix pairs of the Own.NET direction research. That corpus is private, so the triage script needs access to it; its output is committed in [`data/triage_pairs.tsv`](data/triage_pairs.tsv) |
| Corpus 2 | a GitHub code-search sample of 60 files from 31 repositories that use `CollectionsMarshal.GetValueRefOrAddDefault`, pinned by blob SHA in [`data/sample-index.tsv`](data/sample-index.tsv). The files themselves are not committed; `repro/sample.sh` re-fetches them |
| Queries | [`repro/search.sh`](repro/search.sh): 8 PR/issue queries, output in [`data/search1.txt`](data/search1.txt). Diffs: [`repro/prs_c.sh`](repro/prs_c.sh), [`repro/prs_ab.sh`](repro/prs_ab.sh) |

Budget consumed: about 0.6 agent-day (estimated). Bug-fix candidates inspected in depth: 10 of the 15 allowed.

## 2. Candidate comparison

| Candidate | Gap reproduced | Real bugs | Independent repos | Existing-tool coverage | Cost | Verdict |
|---|---|---|---|---|---|---|
| A #382 canonical calls | yes: call lost (A1), core capability (A2). For guarded shapes the core gives only advisory OWN051 even with a `call` (A3). For a local leaked through a first-party *borrowing* method the core gives OWN001 once fed a `call` | 0 | 0 | n/a | high: frontend/core boundary, two engines, parity | **NO-GO within current evidence budget** |
| B #406 closure capture | yes: a sync lambda and a local function are silent, the same leak without a lambda is OWN001; the ShareX control is silent | 0 | 0 | n/a | medium | **NO-GO within current evidence budget** |
| C #400 view invalidation | yes, at runtime: stale write lost on reallocation, shifted view after `RemoveAt`; 4 negative controls clean | **2 CONFIRMED** stale-ref defects | **2** (meziantou, dotnet/maui) | built-in NetAnalyzers (`All`): no rule fires. Third-party: NOT_TESTED | medium–high in production: new invalidation semantics, probably an OwnIR change per #400 | **GO**, narrowed slice |

## 3. Evidence

### Stale-ref mechanism (the PoC target)

| # | Repo / PR | Buggy → fixed | File / method | Mechanism | Status |
|---|---|---|---|---|---|
| C-1 | [meziantou/Meziantou.Framework#2825](https://github.com/meziantou/Meziantou.Framework/pull/2825) | `7addb26c` → `cf82931e` | `src/Meziantou.Framework/DictionaryExtensions.cs` `GetOrAdd(dict, key, valueFactory)` and `TryUpdate(dict, key, valueFactory)` | `ref var v = ref CollectionsMarshal.GetValueRefOrAddDefault(dict, …)` (`GetValueRefOrNullRef` for `TryUpdate`), then `v = valueFactory(key)`. The write location is evaluated before the call. A factory that mutates the same dictionary grows it, so the write lands in the old bucket array | **CONFIRMED_BUG**: measured by the author and fixed with regression tests. **Reproduced independently** on the verbatim buggy code ([`data/c_runtime_dictionary.out`](data/c_runtime_dictionary.out)): `returned=computed stored=<null>`. Control (non-reentrant factory) is correct |
| C-2 | [dotnet/maui#37148](https://github.com/dotnet/maui/pull/37148) (issue #36744) | `7b051d1b` → `2db8b6af` | `src/Controls/src/Core/BindableObject.cs` `GetOrCreateContext` | The same ref is held across `CreateContext(property)` → user `DefaultValueCreator` → `SetValue` on other properties → `_properties` grows → stale ref → a `null` placeholder stays → `NullReferenceException` in `ApplyBindings` | **CONFIRMED_BUG**: user report (Telerik RadDataGrid, Android) plus a regression test in the PR. **Shape reproduced** (`stored=<null>`) |
| C-2d | [dotnet/maui#36030](https://github.com/dotnet/maui/pull/36030) | — | same | same defect, earlier fix attempt | DUPLICATE (C-2) |

Independent stale-ref defects: **2**, in **2** repositories.

### Other findings

| # | Candidate | Repo / PR | Status |
|---|---|---|---|
| C-1b | C, different mechanism | Meziantou #2825, the same PR: `GetValueRefOrAddDefault` inserts `default(TValue)` **before** the factory runs, so a throwing factory leaves the key mapped to `null` permanently (`ContainsKey=True value=<null>`, reproduced) | **CONFIRMED_BUG** for an exception-safety mechanism (premature insertion). It is **not** stale-ref invalidation, is not counted for the stale-ref class, and is **not** the PoC target |
| C-3 | C | [rtkelly-labs/Parquet.SourceGenerator#639](https://github.com/rtkelly-labs/Parquet.SourceGenerator/pull/639) (`ed22cb62` → `4ca337a8`): a defensive length check against the caller's concurrent list mutation | UNSUPPORTED: concurrency, not a same-thread use after mutation |
| B-1 | B | KerckhoffsLabs.Pkcs11 pair 60 (corpus 1): a new test whose capture happens in `Task.Run`, so asynchronously | UNSUPPORTED |
| AB-1..5 | A/B | [mono/SkiaSharp#4814](https://github.com/mono/SkiaSharp/pull/4814) (open), [ChrisBrooksbank/Vox#41](https://github.com/ChrisBrooksbank/Vox/pull/41), [thomhurst/ModularPipelines#6634](https://github.com/thomhurst/ModularPipelines/pull/6634), [blxkstxllion/shopkeeper#119](https://github.com/blxkstxllion/shopkeeper/pull/119), [Flakroup/FEx#172](https://github.com/Flakroup/FEx/pull/172) | none has the A or B shape: library-internal ownership, an exception path, a BCL callee, or a mixed PR. UNSUPPORTED (FEx was skimmed only) |
| corpus 1 | A/B/C | 58 pairs: 7 locals gain a release in the fix. None has the A shape, one has the B shape (= B-1), and no pair touches `CollectionsMarshal` | — |

PLAUSIBLE_UNCONFIRMED sites in corpus 2 with the C-2 shape. They have no fix history and are **not counted**:
- dotnet/macios `NSObject2.cs:733` (`DynamicConformsToProtocol`) and `Runtime.cs:2440` (`SlowIsUserType`);
- maxtoroq/DbExtensions `SqlTable.cs:93` (a reflective factory `Invoke`);
- nightroman/FarNet `Format.cs:483` (a PowerShell `InvokeCode`).

## 4. Kill-gate ledger

| Gate | Necessary condition | Cheapest falsifier | Measured observation | Verdict |
|---|---|---|---|---|
| A1 | the frontend loses the call | facts + summaries of `GuardedConsumeSample.cs` ([`repro/a_382_probe.py`](repro/a_382_probe.py), [`data/a_382_probe.out`](data/a_382_probe.out)) | `ForwardDynamic` body = `use forwarded`; `forwarded = no`; caller records not emitted | PASS |
| A2 | the core derives `may` from a `call` | the same probe with a hand-edited `call` | `forwarded: no → may`; the other summaries are unchanged | PASS |
| A3 | the synthetic FN becomes a finding | the same probe | both callers (guard true and false) get only **OWN051 advisory** in both engines (INF-A5). A borrow leak (`Borrow2(d)`, never disposed) is silent on `main` and **OWN001** with the `call`, in both engines. Multi-level definite forwards already give OWN002 on `main` | partial |
| A4 | a real bug of shape A | corpus 1 + 5 leak-fix PRs | 0 | **NO-GO** (budget) |
| B1 | the FN comes from the capture-is-escape rule | [`repro/b_406`](repro/b_406) | the sync lambda and the local function are silent; the no-lambda leak is OWN001 (the `capturedInClosure` rule in `Program.cs`) | PASS |
| B2 | the ShareX control stays silent | the same | silent | PASS (control) |
| B3 | a real bug of shape B | corpus 1 + the same PRs + "captured lambda dispose" queries | 0; the only candidate is asynchronous | **NO-GO** (budget) |
| C1 | an observable effect with clean controls | [`repro/c_runtime_list`](repro/c_runtime_list), [`data/c_runtime_list.out`](data/c_runtime_list.out) | the stale write is lost; the view reads `[2,3,3]` while the list is `[2,3]`; with spare capacity the effect is not observable (contract violation only); 4 controls clean | PASS |
| C2 | existing tools do not cover the pattern | [`repro/c_analyzers`](repro/c_analyzers) | only CA1062 fires, which is unrelated; no rule found by search. Meziantou.Analyzer, Roslynator and ErrorProne.NET are **NOT_TESTED** (package download not authorised; about 30 minutes once authorised) | PASS for what was tested |
| C3 | real bugs of shape C | PR/issue search + diffs | 2 CONFIRMED stale-ref defects in 2 repos, both reproduced | PASS |
| C-scope | the proposed #400 first slice catches them | mechanism comparison | **no**: both are `Dictionary` ref-returns, and the mutation runs inside a callee or a delegate, not as a direct `list.Add` in the method | slice re-targeted |
| C-prec | precision is not unacceptable | crude classification of 81 sites in 27 repos ([`repro/classify_sample.py`](repro/classify_sample.py), [`data/sample_classified.txt`](data/sample_classified.txt)) | 27 sites have nothing between taking the ref and using it; about 4 are plausibly hazardous; the rest are constructors and pure calls, so an "any call" rule would be noisy. **No precision was measured** | NOT MEASURED; this is the first PoC gate |
| C-Own.NET | Own.NET misses them | current extractor + core on the buggy and fixed files | 0 findings, coverage 0/0: the area is not modelled | confirmed (UNSUPPORTED, not a bug in a modelled path) |

## 5. Recommendation

`GO-400`, narrowed to the stale-ref mechanism of C-1 and C-2:

- The threshold of ≥ 2 independently validated defects from different repositories is met. Maintainers fixed both
  with regression tests, and both were reproduced on the original code.
- The built-in .NET analyzers do not flag either defect, and Own.NET does not model this area.
- **Not established:** precision; frequency beyond these two 2026 PRs; results from third-party analyzers, CodeQL and
  Infer#, all NOT_TESTED. GO therefore authorises a bounded PoC with a precision gate, not production work.

For #382 and #406, the verdict is NO-GO within the current evidence budget; both issues stay open. For #382 the only
measured detection gain is a local leaked through a first-party borrowing method, and no real witness was found. #304
is not affected.

## 6. PoC specification (owner-authorised, bounded)

**Target (C-1 and C-2 mechanism only).** A ref obtained via `CollectionsMarshal.GetValueRefOrAddDefault` /
`GetValueRefOrNullRef` for dictionary `D` is read or written after an invocation that may run code able to mutate `D`
while the ref is live. Two cases:
- a delegate invocation, the Meziantou shape;
- a first-party method whose body transitively invokes a delegate or mutates `D`, the MAUI shape.

The ref write `v = f(...)` counts: the location of `v` is evaluated before `f` runs.

**Gates:**
- Both buggy revisions produce a correctly localised warning: Meziantou `7addb26c` on `GetOrAdd` / `TryUpdate`
  (factory overloads), MAUI `7b051d1b` on `GetOrCreateContext`.
- Both fixed revisions (`cf82931e`, `2db8b6af`) are clean.
- Mandatory negative controls, all clean:
  - no mutation;
  - mutation of a different dictionary;
  - a safe factory;
  - the ref used only before the potential mutation.
- Not every call between taking the ref and using it is dangerous.
- Precision of at least 80 % on an independent labelled sample. Insufficient data means INCONCLUSIVE.
- Third-party analyzers are compared where available, and NOT_TESTED is never reported as a MISS.
- Reuse of existing OwnIR is preferred, but never at the cost of false semantic claims.

**Hard KILL:** either real bug not found; a FP on a mandatory safe control that cannot be fixed within budget; too few
precise warnings to be practically useful; or the budget is exceeded.

**Budget:** one agent-day. No production OwnIR change, no new diagnostic rule, no golden update, no implementation PR.
The PoC ends with `GO-PRODUCTION-DESIGN`, `KILL` or `INCONCLUSIVE`.

## Limitations

- One labeller, no blind control.
- The GitHub search was limited to 8 PR/issue queries and one code search of 60 files. The A/B result means "not
  found within this budget", not "does not exist".
- CodeQL, Infer# and third-party Roslyn analyzers were NOT_TESTED.
- Corpus 1 is private research data. Its triage output is committed, but re-running the script needs access to the
  corpus.
