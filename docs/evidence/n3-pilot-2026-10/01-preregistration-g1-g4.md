# N3 bounded pilot, gates G1–G4 — pre-registration

Written 2026-10-20, 20:23 +05, before any G1 code was written. No diff of a G1 pair was read in this session.
Phase 0 read those diffs and summarised them in one line each (`class-miner-phase0-2026-10/data/classes.tsv`).
Those summaries are all that is known here.

Authority: owner decision `ACCEPT-PASS-G0 / GO-G1-PREREG-AND-BOUNDED-EXECUTION / NO-PRODUCTION`, on #415.

- **Budget.** One agent-day for G1–G4 together, the same budget approved before G0; it is not extended.
- **Order.** G1 → G2 → G3 → G4. The first failed gate stops the pilot with `KILL-N3-PILOT`, and work returns to N1.
- **Scope.** No production, OwnIR, CI or golden change. The PoC lives under `docs/evidence/n3-pilot-2026-10/`.

## 1. What a warning claims

> Code of a request-bound type hands a **scope-owned object** to **detached work**, and the detached work can still
> use that object after the request scope has ended.

A warning needs both halves: §2 proves the object is scope-owned, and §3 proves the work is detached. The type of the
object alone is never enough.

## 2. Scope-ownership evidence (fixed)

A reference is **scope-owned** only when one row below proves it. Anything else is **unknown**, and unknown is
silent.

| Id | Object | Proof required | Not enough |
|---|---|---|---|
| S1 | `HttpContext`, and `HttpRequest`/`HttpResponse` taken from it | the value comes from the `HttpContext` property of a request-bound type (R1–R3), or is read from `IHttpContextAccessor.HttpContext` **outside** the detached work and then captured | reading `accessor.HttpContext` inside the detached work (a different defect: null or stale context, not in this slice) |
| S2 | a `DbContext` subtype `T` | `T` is registered with `AddDbContext<T>` and no lifetime argument (default scoped), **or** an explicit `ServiceLifetime.Scoped`; and the reference is a constructor-injected field or parameter of a request-bound type | `AddDbContext` with `ServiceLifetime.Singleton`; `AddDbContextFactory`, `AddPooledDbContextFactory`, or a context created inside the detached work |
| S3 | a scoped service | the injected type name is proven scoped by G0 rules 1–4 (every product registration of that name is scoped), and the reference is a constructor-injected field or parameter of a request-bound type | type name only; mixed lifetimes; transient |
| S4 | `IServiceProvider` | constructor-injected into a request-bound type (R1–R3), so it is that request's scope provider; the detached work resolves from it | a provider injected into a singleton, a hosted service or any type that is not request-bound (root provider); `scope.ServiceProvider` of a scope created inside the detached work |
| S5 | `HttpClient` | **never** in this slice. Factory-created and typed clients follow `IHttpClientFactory` rules, not scope ownership | everything |

Transient `IDisposable` services resolved inside a request scope are also disposed with the scope (owner's note).
This slice does **not** prove them, so they count as unknown. The report must count how many silent sites this
leaves.

**Request-bound type**, the holder of the reference:

- **R1.** A class deriving from `ControllerBase`/`Controller`, or carrying `[ApiController]`, by its activation model.
  It does not need a DI registration.
- **R2.** A Razor `PageModel`, a SignalR `Hub`, or a minimal-API handler lambda or middleware `InvokeAsync`
  parameter.
- **R3.** A class registered scoped, proven by G0 rules 1–4.

A type registered singleton or transient, and a hosted service, is not request-bound. A transient holder is
unknown, not request-bound, in this slice.

## 3. Detached work (fixed)

The work is **detached** only in one of these forms:

| Id | Form | Condition |
|---|---|---|
| D1 | `Task.Run(λ)`, `Task.Factory.StartNew(λ)`, `ThreadPool.QueueUserWorkItem(λ)`, `new Thread(λ).Start()` | the resulting task is discarded (`_ =` or an expression statement). It is not awaited, returned, assigned and later awaited, or passed to `Task.WhenAll`/`WhenAny`/`Wait` in the same method. Any use of a scope-owned object inside `λ` counts |
| D2 | `QueueBackgroundWorkItem(λ)` (`HostingEnvironment`), or a method named `QueueBackgroundWorkItem*` / `Enqueue*` on a type registered singleton, or one whose name ends in `BackgroundTaskQueue` | any use of a scope-owned object inside `λ` counts |
| D3a | a discarded call whose **receiver** is a scope-owned object: `_ = x.MAsync(…)` or `x.MAsync(…);` with a `Task`-typed result | silent when the callee resolves, by the receiver's declared type, to a non-`async` method that returns a completed task. Otherwise reported: the scope-owned object runs code detached from the request |
| D3b | a discarded call to a method **of the same class** (`_ = MAsync(…)`, `_ = this.MAsync(…)`) | reported only when the callee uses a scope-owned field, or a parameter bound to a scope-owned argument, **after its first `await`**. One hop only: calls inside the callee are not followed |
| D3c | a discarded call to a method of **another class**, with a scope-owned argument | **silent** in this slice. There is no cross-class hop |

**Use** means a member access, a method call, or passing the reference on. A read that copies data into a local
**before** the detached work starts is not a use inside the work.

No other form counts, including async void, events and timers.

## 4. G1 — tiny PoC on real pairs

- **PoC.** A Roslyn syntax-and-semantic scan, without MSBuild evaluation of the third-party project. It uses:
  - the Microsoft.CodeAnalysis DLLs of the `e7d33e33` extractor build;
  - a compilation of the repository's `.cs` files with framework reference assemblies only. Unresolved third-party
    types are tolerated, and their names come from syntax.

  It reads the registrations through the extractor `services` facts and the G0 rules, plus `AddDbContext` calls for
  S2.

  The PoC is built with `--configfile` pointing to a nuget.org-only config and outside the `source/repos` tree. It is
  never built inside a third-party tree. Third-party code is only parsed, never restored or built (D13 isolation
  rule).
- **Pairs, fixed now.**
  - **Required:** `james-langridge/mars-vista-api#26`, `LLabmik/DotNetCloud#43`, `DoForYou-ZA/DFY-BE#35`.
  - **Reported only, not required:** `ASADRAJA/Vendorea.PartnerConnect#49`,
    `microting/eform-angular-timeplanning-plugin#1669`, `escalated-dev/escalated-dotnet#162` (D3b).
  - **Excluded by rule:** GanjoorService#508 (S5, `HttpClient`) and ChatCore.NET#2 (cross-class).
- **Trees.** For each pair, the PR's base commit (buggy) and its merge or head commit (fixed). They are fetched as
  source archives over the GitHub API into a fresh directory outside `source/repos`. Nothing is built or restored.

**PASS-G1** needs both, for each of the three required pairs:

- **Buggy tree.** At least one warning whose capture or call site is a line the fix changes or removes, and whose
  explanation names one S row and one D row.
- **Fixed tree.** No warning on the code the fix touches.

**KILL** at G1 if any of:

- a required pair is missed;
- a fixed tree is warned;
- a pair can be explained only by an ownership or detachment assumption outside §2/§3.

A rule must not be added after seeing a pair.

## 5. G2 — mandatory negative controls

One synthetic file, `controls/N3NegativeControls.cs`, is written **before** the PoC is first run on anything. Each
control sits in a request-bound controller with a proven scoped `AppDbContext`, unless stated otherwise. Every
control must be **silent**:

| # | Control |
|---|---|
| C1 | `await Task.Run(() => _db…)` |
| C2 | `return Task.Run(() => _db…)` |
| C3 | `var t = Task.Run(() => _db…); … await t;` |
| C4 | `var t1 = Task.Run(…_db…); var t2 = …; await Task.WhenAll(t1, t2);` |
| C5 | own scope: `Task.Run(async () => { using var s = _scopeFactory.CreateScope(); var db = s.ServiceProvider.GetRequiredService<AppDbContext>(); … })` |
| C6 | singleton holder: a class registered `AddSingleton` with singleton deps, firing `Task.Run` that uses its fields |
| C7 | copied data: `var id = _db.Orders.First().Id; var name = HttpContext.User.Identity!.Name; _ = Task.Run(() => Log(id, name));` |
| C8 | `_ = SaveLaterAsync();` (same class) that uses `_db` only **before** its first `await` |
| C9 | an `HttpClient` field in a controller used in a discarded `Task.Run` (S5) |
| C10 | `IServiceProvider` injected into a singleton and used in a discarded `Task.Run` (root provider, S4) |
| C11 | `IHttpClientFactory.CreateClient()` inside a discarded `Task.Run` |
| C12 | `_ = _scoped.PingAsync();` where `PingAsync` is non-`async` and returns `Task.CompletedTask` (D3a) |
| C13 | a mixed-lifetime service (registered scoped in one place and singleton in another) used in a discarded `Task.Run` |
| C14 | `accessor.HttpContext` read inside the detached work (S1, out of slice) |

The same file also holds one **positive** sample for each of S1–S4 × D1–D3b. The PoC must report each of them; a
miss is a PoC bug and is fixed before G1 is scored.

**PASS-G2:** C1–C14 silent, and the fixed trees of G1 silent (already required). **KILL** on any warning on a
control. Controls may be added after the first run; none may be removed or changed.

## 6. G3 — independent precision

- **Sample, fixed now.** The 28 mature repositories whose sources the direction research holds: 15 holdout and 13
  design-B sweep repositories, at their pinned SHAs. None of them was used to choose or shape N3. Every product-code
  warning is triaged by reading the code, with a verdict of TP, FP or UNCLEAR. Warnings in test projects (G0 rule 1)
  and in paths matching the direction-research non-product regex are counted but not triaged.
- **Threshold.** Precision ≥ 80%, with UNCLEAR counted as FP, over at least **5** product warnings.
- **PASS-G3:** both hold. **KILL:** precision below 80%, or fewer than 5 product warnings ("not enough data for a
  GO"). The sample is not widened to reach 5.

## 7. G4 — practical yield

- **PASS-G4:** at least one G3 TP that is actionable at the pinned SHA. Actionable means product code, not already
  guarded or fixed, and a concrete scope-ended path can be named, such as a request that returns before the work
  uses the object.
- **KILL:** zero actionable TP.
- G4 opens no new sample; it reads the G3 verdicts.

## 8. What any outcome does not show

- A PASS at all gates is evidence for a narrow PoC, not for a production rule. Production design needs a separate
  owner decision.
- Silence on S-unknown objects (transient `IDisposable`, mixed lifetimes, unrecognised test projects, factory
  lambdas) is not safety. The report counts those sites where the PoC can see them.
