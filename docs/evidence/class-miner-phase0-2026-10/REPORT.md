# Class miner Phase 0 — report

**Result: `GO-CANDIDATE` for one class, N3.** N3: a request-scoped object escapes into detached work. This is a
recommendation for the owner, not an implementation decision.

The other classes that reached the threshold rank below N3 on count or evidence, or conflict with earlier
decisions (§3).

Rules: [`00-preregistration.md`](00-preregistration.md), written before any record was read.

Budget used:
- the existing corpus (the direction-research ledger) only; no new miner was written;
- 10 of the 12 allowed deep-check PRs;
- well under 0.5 agent-day.

Nothing was built, no package was downloaded, and no production, OwnIR, CI or golden file was touched.

## 1. Inputs

- **Corpus.** `records.jsonl` of the direction research has 220 `github_pr_fix` records. The 58 bug/fix pairs with
  base/fix trees and Own.NET runs are among them. The ledger is private research data. Its filtered output is
  committed as [`data/eligible.tsv`](data/eligible.tsv), produced by [`scripts/extract.py`](scripts/extract.py).
- **Filter for "confirmed defect".**
  - the fix is merged;
  - ground truth is at least `patch_supported`, so `candidate`, `rejected` and `unresolved` are out;
  - the impact evidence is an issue report, a profiler or dump result, a test, or a maintainer statement;
  - the code is product code.

  101 records from 81 owners pass. Records in excluded classes (C01, C18) were then set aside.
- **Classes.** Narrow classes were defined from each record's root cause and fix, before its Own.NET result was
  looked up.
- **Corpus-record check.** For the top two classes, the diffs of the corpus records were re-read. This matters
  because most corpus levels are `reviewer_verified(llm)`, set by an earlier agent.

## 2. Candidate classes

| Class | Mechanism (one rule) | Corpus: independent owners | Deep check | Total | Own.NET today | Competitors | Effect evidence |
|---|---|---:|---|---:|---|---|---|
| **N3** | An object owned by a request/DI scope (`HttpContext`, a scoped service, a scope-provided `IServiceProvider`/`HttpClient`) reaches deliberately detached work — a discarded task `_ = …`, `Task.Run`, `QueueBackgroundWorkItem` — and is used after the scope ends | 3 (mars-vista-api, GanjoorService, ChatCore.NET) | 5 of 6 confirmed | **8** | no rule: 3/3 `not_detected_no_rule` (DI001–005 cover constructor and locator capture only) | no rule in any of the 8 analyzer packages or CodeQL; runtime scope validation does not catch it | production `ObjectDisposedException`s in every instance: 39 events in about 7 months (mars-vista); an import that always failed; staging logs; failure on Azure; a live tenant; silent loss of webhook retries |
| **N1** | A disposable is acquired; a step that can throw runs before ownership is handed over (return, field or dictionary store, registration); there is no dispose on the throw path | 3 (whizbang, rockbot, NexusKit) | 1 of 4 (BareWire) | **4** | missed 3/3. The locals are returned, stored or factory-acquired, and Own.NET tracks only non-escaping `new` locals. The opt-in `--body-throw-edges` tier would not reach them (by reading the model; not run) | CA2000 needs `dispose_analysis_kind=AllPaths` and is off by default; no other rule | one resource leaked per failed attempt (test, issue #1187, maintainer statements). No crash |
| N6 | A long-lived keyed collection (singleton, static or plugin lifetime) is only ever added to | 4 (honua, chaosflix, AI-Cockpit, BB84) | not checked | 4 | no rule | no rule | memory growth: 1 profiler, 2 tests, 1 maintainer statement |
| N7 | A `CancellationTokenSource` is disposed while concurrent code still reads its token | 3 (headless-framework, frame-flow, LiteDB) | not checked | 3 | no rule | no rule | tests |
| N1b | A release placed after a call that can throw in the same teardown sequence; the throw skips the release | 1 (PattN) | daqifi-core#504 (found while checking N1) | 2 | PattN missed (factory acquisition); daqifi not run | none | daqifi: the serial port stays claimed for the life of the process, 13 tests |
| N2 | A singleton constructor-injects a scoped service | 2 missed (affiant, SIBO) + 1 detected | — | 2 | DI001 exists. The misses are model gaps: framework registrations (`AddIdentityCore`), and a `ServiceDescriptor` with a runtime lifetime | none | both fail at startup under Development scope validation, so the framework already catches them |
| N4 | A non-atomic disposed flag under concurrent `Dispose` | 2 (couchbase, AgentInfer) | — | 2 | tool failure / no rule | none | maintainer statements; AgentInfer "not reproduced" |

Deep check, PR by PR, selected by title before reading
([`data/deepcheck-selection.tsv`](data/deepcheck-selection.tsv)). Class membership of every instance, corpus and
deep check, is in [`data/classes.tsv`](data/classes.tsv).

| PR | Class | Verdict | Why |
|---|---|---|---|
| LLabmik/DotNetCloud#43 | N3 | confirmed | scoped `_seriesService` (DbContext) used in a fire-and-forget `Task.Run`; `ObjectDisposedException` |
| DoForYou-ZA/DFY-BE#35 | N3 | confirmed | `_ = _notificationService.NotifyAdminsAsync(…)` on a request-scoped service; `ObjectDisposedException` in staging logs |
| ASADRAJA/Vendorea.PartnerConnect#49 | N3 | confirmed | request-scoped `IServiceProvider` field used inside `Task.Run`; failed reliably on Azure |
| escalated-dev/escalated-dotnet#162 | N3 | confirmed | `_ = RetryLaterAsync(…)` on a scoped dispatcher; the retry hits a disposed DbContext and is lost silently; regression test |
| microting/eform-angular-timeplanning-plugin#1669 | N3 | confirmed | fire-and-forget sends capture a request-scoped service; live `ObjectDisposedException`; tests |
| klitztuch/LanBoard#47 | N3 | **not this class** | event-triggered loads during Blazor prerender while the scope is disposing; no detached work |
| Wizard-Software/BareWire#73 | N1 | confirmed | channel created, `basic.qos` throws before registration, channel never disposed; one leak per failure |
| reqnroll/Reqnroll.IdeSupport#1119 | N1 | **not this class** | a cached proxy field nulled without dispose on failure paths (C02 shape) |
| daqifi/daqifi-core#504 | N1 | **not this class** (→ N1b) | a throwing event handler skips the release in a teardown sequence |
| modelingevolution/micro-plumberd#20 | N1 | **not counted** | shape matches (start fails after the container was created), but it is a test-support library and the resource is external (a Docker container) |

## 3. Ranking and recommendation

Ranking follows the pre-registered order: independent count, then evidence strength, then cost.

**1. N3 — `GO-CANDIDATE`.** Strongest on both count and evidence:
- 8 independent owners;
- each defect was observed failing in production or staging;
- no static tool covers it, and runtime scope validation cannot.

It is close to what Own.NET already models:
- the DI registration graph (DI001–005) supplies scoped-ness;
- the extractor already records closure captures;
- the detached-work entry points are a small, known set of APIs.

Forms by expected cost:
- **Intra-method, M.** A scoped field or `HttpContext` passed to a discarded call, or captured in a lambda handed to
  `Task.Run` or a background queue. This covers DFY-BE, Vendorea, DotNetCloud, Ganjoor, microting and mars-vista.
- **One level into a same-class method, M.** escalated (`_ = RetryLaterAsync`).
- **Cross-class, L.** ChatCore needs interprocedural flow, which is close to the #382 territory left at NO-GO.

Caveats, all unresolved:
- **Prevalence is not measured.** The deep check used keyword searches aimed at the class, so it shows recurrence
  across owners, not a rate.
- **Mature-code yield is unknown.** 7 of the 8 repos are young or small (0–4 stars). The direction research (D11, private) recorded the same pattern
  for C10, whose mature-code yield was 0.
- **The DI graph has a known false-positive problem.** It merges test and product registrations: 7/7 holdout FPs in
  D11. The C10 fallback plan (product-only graph, about 1 week) would be a prerequisite.
- **Precision is unknown.** Any design must pre-register a precision gate on an independent sample, as #400 did. The
  #400 PoC found its targets and still failed that gate.
- **Some deep-check PR texts are themselves AI-generated** (Vendorea, microting). The effect statements there are the
  maintainers' claims and were not reproduced.

**2. N1 — runner-up, not recommended now.**
- 4 independent owners, but the effect is a per-failure leak, with no crash.
- Own.NET would need two things it lacks: tracking of locals that are factory-acquired or later transferred, and
  throw edges limited to the window before the transfer.
- The existing throw tier is documented as the "CA2000 firehose". Narrowing it to the transfer window is untested.
- Factory acquisition through third-party APIs needs type-based ownership assumptions.

**3. N6, N7, N1b, N2, N4 — not recommended.**
- **N6.** Only corpus evidence; detection is cheap, but precision risk is high: intentional caches with bounded
  keys.
- **N7, N4.** Cross-thread. The direction research's final decision (§16, private) ruled these classes need new architecture and are not worth it now. The count does
  not override that decision.
- **N1b.** 2 owners, one of them found incidentally.
- **N2.** The framework already fails these at startup. It remains part of the C10 fallback, not a new class.

The Meziantou C-1b defect (a default inserted before a throwing factory, from #412) found no second instance in this
corpus. It stays a single case.

## 4. Limits

- **The corpus is biased.** It was assembled by queries aimed at resource lifetime (design A), and every ledger
  level was set by an earlier agent. Only the N3 and N1 records were re-read.
- **One researcher, no second labeller.**
- **Own.NET results for deep-check PRs are `NOT_RUN`.** Only the corpus records carry ledger-backed Own.NET
  results.
- **Silence is not safety.** Classes that did not reach 2 are not shown to be rare; they were not found in this
  corpus.

## 5. Files

- [`00-preregistration.md`](00-preregistration.md): the rules, written before any record was read.
- [`scripts/extract.py`](scripts/extract.py) and [`data/eligible.tsv`](data/eligible.tsv): the confirmed-defect
  filter over the private ledger and its output (101 records).
- [`data/classes.tsv`](data/classes.tsv): every instance per class, with source and verdict.
- [`data/deepcheck-selection.tsv`](data/deepcheck-selection.tsv): the 10 deep-check PRs, chosen by title before
  reading.
- [`scripts/search.sh`](scripts/search.sh), [`scripts/search2.sh`](scripts/search2.sh) and their outputs
  [`data/search.out`](data/search.out), [`data/search2.out`](data/search2.out). GitHub search drifts, so a re-run
  will not return the same lists.

The texts and diffs of the deep-check PRs are third-party content and are not committed. Each PR is linked by
number and can be read on GitHub.
