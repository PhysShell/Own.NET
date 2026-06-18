# Real-world mining run — milestone 1 (WPF leak spike)

This is the write-up of the first end-to-end run of the analyser over **real,
unmodified OSS C#**, the `ROADMAP.md` milestone 1: *"find 1–3 real
subscription/timer leaks in real code (P-004)."* It is the honest record of what
the tool actually surfaces on real code — signal, precision, and the next gap the
run revealed.

## How it ran (the loop)

The Roslyn extractor needs a .NET SDK, which the dev sandbox does not have, and
the supported on-demand path (`mine.yml`, `workflow_dispatch`) could not be
triggered from the automation token. So the run used a small **push-triggered**
miner (`.github/workflows/mine-on-push.yml`) driven by a sentinel file
(`corpus/mine-target.txt`): bump the target, and CI clones the repo, runs
`scripts/mine.sh` (extractor → OwnIR → core, no per-repo build), and echoes the
report to the job log. The findings were then triaged by reading the flagged
`file:line` in a local clone of the target.

> `mine-on-push.yml` + `corpus/mine-target.txt` (and the analogous `push:` trigger
> + `corpus/oracle-target.txt` on `oracle.yml`) are **dev-loop scaffolding**
> (dev-branch only) — they exist because the token can't `workflow_dispatch`. They
> should not be merged to `main`; the supported paths stay `mine.yml` / `oracle.yml`.

## What it found

| Repo (commit) | findings | triage |
|---|---|---|
| `DapperLib/Dapper` @72a54c4 | 1 × OWN001, 1 × OWN050 | TP: `BenchmarkBase._connection` — an undisposed `SqlConnection` field (benchmark project). |
| `JoshClose/CsvHelper` @33970e5 | 43 × OWN001 | TP: undisposed `StreamReader/Writer/CsvDataReader` **locals in tests**; every `using`-scoped local was correctly skipped. |
| `NickeManarin/ScreenToGif` @27a49c3 (WPF profile off) | 8 × OWN001, 210 × OWN050 | **flagship** below + a likely-benign `App`→`AppDomain.UnhandledException` (process-lived subscriber). |
| `NickeManarin/ScreenToGif` @27a49c3 (WPF profile **on**) | 123 × OWN001, 37 × OWN050 | unlock works (OWN050 ↓), but exposes the self-owned-control precision gap below. |
| `NickeManarin/ScreenToGif` @27a49c3 (WPF **on**, after the self-owned fix) | 36 findings, 40 × OWN050 | self-owned-control FPs gone; survivors are real — 2 × `SystemEvents` leaks (error) + the 4 `VideoSource` flagship warnings. |

**Precision.** Every finding triaged by hand was a *real* undisposed/undetached
resource — no false positives from `using` (the extractor models it as release),
and the severity tiering behaved as designed. The findings cluster where
disposal discipline is intentionally lax (test/benchmark code) — real, but mostly
low-severity in practice. Disciplined shipping libraries came up clean, which is
the *precision* result the methodology wants to see.

## The flagship finding (milestone 1 ✔)

`ScreenToGif/Windows/Other/VideoSource.xaml.cs:50-83` — a WPF `Window` subscribes
**four inline lambdas to its view-model's custom events in `Window_Loaded` and
never detaches them** (`Window_Closing` does no `-=`). This is the canonical
view↔view-model lifetime shape that generic IDisposable/CA analyzers miss; it
resolves **without** the WPF reference pack because the events are the app's own
types. The extractor rates it **warning** (the source `_viewModel` is injected, so
its lifetime can't be proven) and notes the lambdas have no `-=` handle — the
honest verdict (it may be a collectable view↔vm cycle, but the
duplicate-handler-on-reload bug is real). Captured as a regression:
`corpus/real-world/screentogif-loaded-subscription/`.

## The WPF reference unlock (and the gap it revealed)

The flagship detectors went blind on framework events because the extractor only
loaded the runtime's trusted-platform assemblies — `Button.Click`,
`DispatcherTimer.Tick`, etc. fell out as OWN050. The extractor now also loads
`*.dll` from each dir in the **`OWN_EXTRA_REF_DIRS`** env var (deduped by simple
name against the TPA); the miner materializes the WindowsDesktop ref pack on Linux
(a `net8.0-windows`/`UseWPF` stub restores it via `EnableWindowsTargeting` → 47 ref
dlls) and points the var at it. On ScreenToGif this drove **OWN050 210 → 37**.

The change is **off by default** (`OWN_EXTRA_REF_DIRS` unset → unchanged
behaviour; the whole existing suite is the guard), so it is a safe, opt-in
capability add.

Unlocking framework events also jumped **OWN001 8 → 123**, dominated by **false
positives on self-owned controls**: `_thumbBottomLeft.DragDelta +=` (a `Thumb` the
adorner builds via `BuildCorner(ref _thumb, …)`), `_upButton.Click +=` (a template
part from `GetTemplateChild`), etc. A class subscribing to a control it *owns* is a
collectable cycle, not a leak — but the original exemption only recognised a direct
`field = new …`, so indirect (`ref`/`out`) construction and template parts slipped
through.

**Fixed** — the bug-driven next unit of work the run defined. The self-owned
*subscription* exemption now also folds in `ref`/`out`-populated fields (only when
the populating helper is the class's *own* method — an external `TryResolve(out _bus)`
stays a leak candidate) and
`GetTemplateChild`/`FindName` template parts (kept OUT of the disposal detector's
`constructed` set, so WPF003 still demands disposal of `new`'d fields only).
Re-mining ScreenToGif with the WPF profile confirms it: **123 → 36 findings** (40
OWN050), the adorner/template-part noise gone while the *real* leaks survive — two
`SystemEvents.DisplaySettingsChanged` subscriptions never detached (flagged
**error**: a static, process-lifetime source is a provable leak — the classic
SystemEvents leak, in `GraphicsConfigurationDialog` / `Troubleshoot`) and the four
`VideoSource` view→view-model lambdas (**warning**). Verified by the `wpf-extractor`
CI job: the `SelfOwnedControlParts` sample asserts both new shapes stay silent.

Both real leaks are locked as regressions: `corpus/real-world/screentogif-loaded-subscription/`
(VideoSource, warning) and `corpus/real-world/screentogif-systemevents-leak/`
(SystemEvents, error).

## Cross-tool validation (the oracle)

"Real leak" was, so far, our own verdict plus manual reasoning. The cross-tool
oracle (`oracle.yml` → `scripts/oracle_compare.py`) settles it: run Own.NET, CodeQL
and Infer# over the *same* commit and diff their leak-class findings. On ScreenToGif
@27a49c3, CodeQL (2.25.6, `security-and-quality`, database-from-source) ran; **Infer#
was skipped** — ScreenToGif is WPF and does not `dotnet build` on the Linux runner
(`NETSDK1100`) — so this is Own.NET vs **CodeQL**.

Their leak findings are **nearly disjoint** (file overlap: **1**):

- **Own.NET only** — every subscription/lifetime leak, including the two this run is
  about: `GraphicsConfigurationDialog.xaml.cs:35` & `Troubleshoot.xaml.cs:27`
  (`SystemEvents.DisplaySettingsChanged`, error) and `VideoSource.xaml.cs:50/67/75/83`
  (view→view-model, warning), plus a pile of own-control subscriptions
  (`EncoderListViewItem` ×6, `LightWindow` ×5, `SplitButton`, `StatusBand`, …).
  **CodeQL flags none of them** — its query set has no "event subscribed, never
  unsubscribed" rule.
- **Oracle only — 33** — entirely CodeQL's Dispose/RAII class (`cs/local-not-disposed`:
  `OpenFileDialog`/`SaveFileDialog`/`Pen`/`Bitmap`/…, and `cs/dispose-not-called-on-throw`).
  Own.NET flags none — a recall gap in the *other* class, and the cause is **method
  coverage, not type recognition**: the `--flow-locals` detector skips any method with
  an unmodelled construct (`for`/`try`/`switch`), and these disposables live in such
  methods (tell: the `StringReader`/`XmlReader` cases are a *recognised* disposable
  type, yet still missed). `for` **and** `try` are now lowered, in two slices: first
  sequential `A; B` (catch-disposes bailed for soundness), so a plain undisposed local
  inside a try-method is caught; then the **exception-edge** model — before each
  may-throw statement in a `try`, inject an exceptional exit (`if(*){ <finally>; return }`)
  — which catches the true `dispose-not-called-on-throw` shape (disposed in `try`, not
  `finally`: the throw skips the `Dispose`). Both confirmed on the cross-tool fixture:
  the plain `try`-method leak and the dispose-on-throw leak both land in **Agree** across
  all three tools (the latter matching CodeQL's `cs/dispose-not-called-on-throw`). The
  edges are injected only where sound — when the caught path's continuation is end-of-
  method (no catch, or the `try` is the body's tail); a swallowing catch with a Dispose
  *after* the try/catch (continuation disposes the resource) lowers sequentially instead,
  to avoid a false leak (PR #32 review). Still deferred: exception edges inside nested
  `try` bodies (only top-level `try` statements get an edge today), `finally`-before-
  `return` threading (bailed today), and `switch`/`do`.
- **Agree — 1** (`HttpHelper.cs`).

So the SystemEvents and VideoSource findings are **differentiated — confirmed by the
oracle, not just argued**: the tools are complementary (Own.NET on subscription/
lifetime, CodeQL on Dispose/RAII), overlapping on a single file.

**Infer#, via a buildable fixture.** ScreenToGif can't build on Linux, so to get the
third tool in, a minimal `net8.0` console reproduces the leak classes
(`corpus/fixtures/systemevents-console/`, fed to the oracle via a `local:` target).
All three tools run; the diff (latest run) is:

| `Program.cs` | leak | class | Own.NET | CodeQL | Infer# |
|---|---|---|:-:|:-:|:-:|
| `:43` | `new FileStream(…)` never disposed | Dispose/RAII | ✓ | ✓ | ✓ |
| `:54` | undisposed local inside a `try`-method | Dispose/RAII (try-lowering) | ✓ | ✓ | ✓ |
| `:77` | `Dispose()` in `try` after a may-throw call — skipped on the throw path | dispose-on-throw (exception-edge) | ✓ | ✓ | ✓ |
| `:20` | `SystemEvents.DisplaySettingsChanged +=` never `-=` | subscription | ✓ | — | — |

The three Dispose/RAII leaks are **Agree** across all three tools — the controls that
prove CodeQL *and* Infer# actually run and detect resource leaks on this code — and the
bottom two are the recall slices: the plain `try`-method leak (sequential lowering) and
the dispose-on-throw leak (exception-edge), the latter matching CodeQL's dedicated
`cs/dispose-not-called-on-throw` query. **Oracle-only is empty** — no Dispose/RAII leak
on this fixture is missed. The `SystemEvents` subscription is **Own.NET only**: **Infer#
misses it too.** Both mature oracles cover the Dispose/RAII class and neither has the
subscription-leak class — the differentiation, nailed with all three tools.

> The exception-edge slice also surfaced a hygiene bug it then fixed: a local that
> leaks on *both* the injected exceptional exit *and* the normal end produced two
> identical OWN001s (every flow-local diagnostic remaps to the acquire line, so they
> collapse). The bridge now drops byte-identical findings (`ownir.py`), pinned by
> `tests/fixtures/ownir/flow_leak_two_exits.facts.json`. One leak, one finding.

> Getting a trustworthy diff took fixing two oracle bugs: the comparator dropped
> multi-line / untagged own-check findings (`scripts/mine_report.py` parser drift —
> 38 lines "unparsed", so only 3 of ~36 findings reached the diff), and own-check ran
> without framework refs at `--severity error`, so it never emitted the very findings
> under test (SystemEvents → OWN050; VideoSource → filtered). Both fixed; the
> comparator selftest now covers the multi-line shape, and the oracle's own-check
> materializes the WindowsDesktop refs and runs at `--severity warning`.

## Reproduce

Point `mine.yml` (Actions → *mine (corpus)* → Run workflow) at a target; for the
WPF profile, set `OWN_EXTRA_REF_DIRS` to a WindowsDesktop `ref/net8.0` dir (the
miner shows how to materialize it). Read the report in the run summary / artifact.
For the cross-tool diff, run `oracle.yml` the same way — it materializes the
WindowsDesktop refs itself and emits the Own.NET-vs-CodeQL/Infer# agreement report.
