# P-012 — Real-world bug corpus & mining pipeline

- **Status:** in progress — the **corpus benchmark** (slice 1) is built:
  `scripts/benchmark.py` scores the checker against the labeled corpus on the
  *real* `before.cs`/`after.cs` (not just the `.own` reduction), measuring recall
  (the bug is caught) and specificity (the fix is silent), gated in the
  `corpus-benchmark` CI job. This is the measurement spine — the defensible number,
  and the verifiable reward for any future learning loop. **First measurement: 3/9
  caught · 9/9 fixes clean · 0 false positives** — perfect precision, and the C#
  *frontend's* recall debt is now a tracked number (the `.own` reductions all fire;
  the 6 missed are pool/dispose/handoff shapes the extractor does not yet lower —
  the itemized extraction backlog). Still ahead: raising recall case-by-case, GitHub
  mining at scale (stage 1) and the 50–100-repo prevalence scan (stage 2). See
  [docs/notes/corpus-benchmark.md](../notes/corpus-benchmark.md).
- **Depends on:** P-001 (C# → OwnIR extractor — the scanner that does stage 2);
  the existing `corpus/` layout (`before.cs`, `after.cs`,
  `expected-diagnostics.txt`, `notes.md`/`source.md`).

## Motivation

The whole frontend runs on **bug-driven expansion**: prove Own.NET catches ONE
real bug, then grow exactly to fit the next one. That principle is only as good
as the question *"which bug next?"* — and today that question is answered by
vibes. We pick WPF event leaks and ArrayPool double-returns because they *feel*
common and static-friendly, not because we counted.

We would love to count against a public "top of all .NET production errors"
dataset. It does not exist. That data lives in private dashboards — Sentry, App
Insights, Raygun, Datadog, New Relic — and nobody publishes the aggregate. So
the honest move is to build **proxy signals** and our **own measured corpus**
instead of guessing, and to feed the resulting numbers into `docs/ROADMAP.md`,
where the prioritization and the "what static analysis can / can't catch" matrix
live. This proposal is the data source for that matrix, not a competitor to it.

**Proxy signals** (legitimate as *signals*, not statistics):

- Microsoft analyzer rules — CA2000 (disposable not disposed before scope loss,
  including exceptional paths), CA2012 (`ValueTask` consumed twice). These encode
  what Microsoft thought worth shipping a rule for.
- Resource-leak research — e.g. RLC# on CodeQL reporting resource leaks across
  OSS projects and Azure microservices.
- Official exception docs flagging `NullReferenceException` and
  `ObjectDisposedException` as *developer* errors.
- DI lifetime guidance — transient `IDisposable` resolved from the root container
  leaks; singleton capturing scoped = captive dependency; async factory via
  `.Result` deadlocks.

These tell us *what to look for*. They do not tell us *how often it actually
occurs in real repos*. The pipeline below measures that.

## Scope

A **boringly practical, offline research pipeline** in four stages whose output
is a curated corpus plus a *calibrated* priority list. The corpus mirrors the
existing `corpus/` layout so today's three WPF cases and two real-world cases are
already the first members.

1. **GitHub mining.** Search merged PRs / issues across the .NET ecosystem
   (dotnet/runtime, aspnetcore, EF Core, Nethermind, …) for fix-shaped keywords:
   `"fix memory leak" .NET`, `ObjectDisposedException`, `"IDisposable" "leak"`,
   `"event handler leak"`, `"DispatcherTimer leak"`, `"ArrayPool" "Return"`,
   `"captive dependency"`, `"Cannot consume scoped service from singleton"`.
   Each promising PR gives a real `before`/`after` pair for free.
2. **Roslyn scan.** Run the **P-001 extractor** over 50–100 popular repos and
   count hits per 1k LOC for: `event += without -=`; `IDisposable` fields with no
   `Dispose`; `ArrayPool.Rent` without `Return`; `Return` before the last
   `AsSpan` use; singleton-captures-scoped from the registration graph.
3. **Runtime telemetry — on our OWN code only.** Exception-type histogram, top
   stack traces, memory-dump leak cases, WPF ViewModel retention paths. No
   scraping anyone else's telemetry; this is the one signal that is real
   measurement rather than proxy, and it is small because it is only ours.
4. **Corpus.** For every confirmed bug store `before.cs`, `after.cs`,
   `expected-diagnostics.txt`, and `source.md` (link + a one-paragraph story),
   tagged with a **detectability** label (below).

The payoff is one defensible sentence we *intend to be able to write* — e.g.
"Of 100 projects: 47 suspicious `IDisposable` leaks, 31 event subscriptions with
no unsubscribe, 12 DI lifetime mismatches, 8 ArrayPool suspicious paths, 5
use-after-dispose candidates." That is the **output we plan to produce**, not a
current measurement.

## Non-goals

- No live real-time scan of 100 repos wired in as a CI gate — it is
  resource-bound and would make every build hostage to GitHub rate limits.
- No claim of authoritative .NET error statistics. We are explicit that we don't
  have them and are building proxies *because* we don't.
- No scraping of private telemetry (Sentry/App Insights/etc.).
- This is an **offline research tool**. Its product is the corpus and a
  calibrated priority list — not a user-facing feature.

## Sketch

```text
GitHub PRs/issues  --[keyword mine]--\
50–100 repos       --[P-001 scan]----->  candidates  --[triage + reduce]-->  corpus/<area>/<case>/
our telemetry      --[histogram]-----/                                       {before.cs, after.cs,
                                                                              expected-diagnostics.txt,
                                                                              source.md, detectability tag}
                                            counts ----------------------->  docs/ROADMAP.md priority matrix
```

**Priority table — PROXY / hypothesis, NOT measured.** Every cell below is an
estimate to be *replaced* by stage-2 counts. Do not cite these as facts.

| Pattern | Prevalence (proxy) | Note |
| --- | --- | --- |
| `event += without -=` | **Very High** | old WPF/WinForms repos ~3–4× more than Blazor/MAUI |
| `IDisposable` field, no `Dispose` | **High** | broad across services and UI |
| captive dependency (singleton→scoped) | **proxy ~15%** of large ASP.NET Core projects have ≥1 | visible in registration graph |
| `ObjectDisposedException` | **extreme** mention-count (SO/issues) | but largely a timing/race bug — see detectability |
| `ArrayPool.Rent` without `Return` | **Low/Medium** | but ~20–30% in high-load parsing/serialization libs |
| `Return` before last `AsSpan` use | **Very Low** | low-level code only |

**Detectability — tag every case (full matrix lives in `docs/ROADMAP.md`):**

- *Deterministic / static-friendly:* captive dependency (in the type/registration
  graph); missing `Dispose`; `ArrayPool` Rent/Return within one method; simple
  use-after-dispose in one CFG.
- *Heuristic / false-positive-prone:* `event += without -=` (depends on object
  lifetime — only warn for long-lived objects); ownership transfer through a
  callee (`ProcessStream(s)` may dispose internally).
- *Impossible statically:* `ObjectDisposedException` from a cross-thread race;
  LOH fragmentation (runtime data volume); static-collection bloat (business
  data); unmanaged cyclic refs / `Marshal.AllocHGlobal` freed on all paths.

The tag exists so we never promise a runtime-only bug to a static checker. A
corpus entry tagged *impossible* is a documented limit, not a backlog item.

**Replay corpus targets (concrete stage-3 "replay a known bug" goals):**
dotnet/runtime use-after-return; Nethermind ArrayPool leaks / double-return;
AiDotNet.Tensors pooled-buffer leak / over-clear. Reproduce each, reduce it into
`corpus/`, and confirm the checker's verdict matches the real fix.

## Open questions

1. Repo selection for stage 2 — top-N by stars, or weight toward the high-load
   serialization/parsing libs where ArrayPool misuse actually concentrates?
2. Triage gate — what false-positive rate makes a stage-2 hit corpus-worthy vs
   noise to discard? (The heuristic patterns will be loud.)
3. `source.md` vs the existing `notes.md` — unify on one filename, or let
   `notes.md` (hand-reduced) and `source.md` (mined, with provenance link)
   coexist as a signal of origin?
4. How much of stage 1 can the `mcp__github__search_*` tooling do reproducibly
   vs a one-off scripted scrape we don't keep wired in?
5. Re-scan cadence — is the priority list a one-time calibration, or do we
   re-measure when the extractor gains a pattern (so coverage and prevalence
   stay honest together)?
