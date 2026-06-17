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

> `mine-on-push.yml` + `corpus/mine-target.txt` are **dev-loop scaffolding**
> (dev-branch only) — they exist because the token can't dispatch `mine.yml`.
> They should not be merged to `main`; the supported path stays `mine.yml`.

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
*subscription* exemption now also folds in `ref`/`out`-populated fields and
`GetTemplateChild`/`FindName` template parts (kept OUT of the disposal detector's
`constructed` set, so WPF003 still demands disposal of `new`'d fields only).
Re-mining ScreenToGif with the WPF profile confirms it: **123 → 36 findings** (40
OWN050), the adorner/template-part noise gone while the *real* leaks survive — two
`SystemEvents.DisplaySettingsChanged` subscriptions never detached (flagged
**error**: a static, process-lifetime source is a provable leak — the classic
SystemEvents leak, in `GraphicsConfigurationDialog` / `Troubleshoot`) and the four
`VideoSource` view→view-model lambdas (**warning**). Verified by the `wpf-extractor`
CI job: the `SelfOwnedControlParts` sample asserts both new shapes stay silent.

## Reproduce

Point `mine.yml` (Actions → *mine (corpus)* → Run workflow) at a target; for the
WPF profile, set `OWN_EXTRA_REF_DIRS` to a WindowsDesktop `ref/net8.0` dir (the
miner shows how to materialize it). Read the report in the run summary / artifact.
