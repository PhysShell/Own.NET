# #278 teardown-scoped release — before/after corpus + sweep evidence

> **Follow-up slice appended below** ("Follow-up: four silent-exemption paths
> removed") — it supersedes the first slice's numbers where they differ.

The soundness fix (a matching `-=` credits release only in a recognised teardown
context and never under a parameter guard) was measured against every surface
available on the dev runner. Baseline = frozen `366bbf93` (the G50 acceptance
commit), after = this branch. All scans used the same runner, same .NET 8 SDK;
the ScreenToGif rows additionally load the WindowsDesktop reference pack
(`OWN_EXTRA_REF_DIRS`, as `oracle.yml` does) so framework events resolve.

## Corpus benchmark (`scripts/benchmark.py`)

| | before (366bbf93) | after (#278) |
|---|---|---|
| bugs caught | 40/44 | **42/46** |
| fixes clean | 44/44 | **46/46** |
| false positives on fixes | 0 | **0** |

Row-level diff: every pre-existing row byte-identical; the only delta is the two
new cases (`subscription-param-guarded-unregister`,
`subscription-nonteardown-release`), both `before[caught: OWN001] after[clean]`.
The 4 pre-existing MISSED rows (WPF-unresolvable on a Linux runner without the
ref pack) are unchanged. The delta is strictly additive — new true positives,
nothing silenced.

## Extractor samples (`frontend/roslyn/samples`, whole-dir own-check diff)

157 → 159 findings. The only two new rows, both intended semantics:

- `FixCandidatesSample.cs:45` (`InpcAmbiguousTeardown`) — its two `-=` live in
  `Detach1()`/`Detach2()`, arbitrary non-teardown methods → now OWN001. The
  `--fix-candidates` teardown metadata (`ambiguous`, 2 candidates) is unchanged.
- `FixCandidatesSample.cs:254` (`HandlerReassignedField`) — its `-=` lives in
  the ctor → now OWN001.

Everything else — rotation silences, self-detach, `OrdersViewModel`/
`CleanStaticEventViewModel` Dispose releases, `Window_Closing` (XAML-wired)
releases — byte-identical. `tests/goldens/fix_candidates_off.golden.json` was
regenerated for the two flipped `released` values (procedure per
`tests/goldens/README.md`); `check_fix_candidates_facts.py` and the byte-parity
gate pass.

## Oracle push-target fixture (`corpus/fixtures/systemevents-console`)

Byte-identical before/after (3 findings, 1 OWN050 advisory).

## Real-repo sweep

| target | before | after | delta |
|---|---|---|---|
| ScreenToGif (mine-target), no ref pack | 214 | 214 | none |
| ScreenToGif, WindowsDesktop ref pack | 61 (20 findings, 40 OWN050) | 65 (24 findings, 40 OWN050) | +4, classified below |
| CsvHelper `src/` | 0 | 0 | none |

### Classification of the 4 new ScreenToGif findings

All four are ONE shape: `ScreenToGif/Controls/ResizingAdorner.cs` subscribes its
injected `_adornedElement` to `PreviewMouseLeftButtonDown`/`MouseMove`/`MouseUp`
in the ctor (`:91-93`, plus the re-attach half of a suspend/resume `-=`/`+=`
inside the `MouseMove` handler, `:130`). The only unconditional detach lives in
a **custom-named** teardown, `public void Destroy()` (`:502-506`), which the
owning windows call when removing the adorner.

Triage: the release is real but *not provable from the class alone* — `Destroy`
is an ordinary method the owner must remember to call (exactly the shape the
GTD leak had, minus the parameter guard; if an owner forgets `Destroy`, the
element pins the adorner). Under the #238/#278 doctrine this demotes to a kept
warning — a *mitigation candidate*, never silence. No baseline entry is added:
ScreenToGif is the miner's spot-check target (reviewed in run logs), not the
cross-tool oracle target, and the warning tier is the intended verdict for an
unproven custom teardown. If a future slice recognises "a `-=`-only method
called by all constructing owners" (needs the caller walk that is explicitly
out of this slice's budget), these four are the first candidates.

## SectorTS acceptance (GTD / PGC / KDT shape)

The real `STS_new/SectorTS` tree is not present on this runner; the faithful
reduction (static `AppData.Properties.GBProperty.PropertyChanged` chain,
`GTD` = flag-guarded `-=` in `UnregisterEventHandlers(bool)`, `PGC` =
unconditional `-=` in `UnregisterEventHandlers()`, `KDT` = no `-=`,
`CleanDoc` = `-=` in `Dispose`) was verified end-to-end: GTD, PGC and KDT are
flagged OWN001; CleanDoc is silent. Re-running
`OwnAudit/sts_audit` against the real tree (and the ClosedXML / 5-repo sweep)
remains a local, pre-merge step — together with the two merge gates from the
scope: the G50 Acceptance Run on frozen `366bbf93`, and the OwnAudit STS
baseline that classifies GTD as `runtime-only`.

---

# Follow-up: four silent-exemption paths removed

The review of the first slice found four remaining paths that credited a
release without proving it runs. All four are closed; each is red→green pinned
by a corpus case. Baseline for this section = the first slice's head
(`fix(extractor): green — #278 ...`), so the deltas isolate the follow-up.

| # | removed path | why it was unsound | corpus pin |
|---|---|---|---|
| 1 | finalizer as teardown | the publisher's delegate keeps the subscriber REACHABLE, so the finalizer never runs while the subscription is live | `subscription-finalizer-release` |
| 2 | `*_Closed`/`*_Closing`/`*_Unloaded`/... name suffix | a name is not wiring — the XAML attach never reaches the extractor and a bare name may be stale dead code | `subscription-xaml-name-only-release` |
| 3 | name-keyed intra-class closure | `Dispose() -> Cleanup()` credited every method NAMED `Cleanup`, including an uncalled `Cleanup(bool)` overload | `subscription-overload-conflated-cleanup` |
| 4 | lexical inheritance for nested callables | a local function or lambda declared inside Dispose does not run because Dispose does | `subscription-uncalled-local-function` |

The closure is now SYMBOL-based (`IMethodSymbol` + `SymbolEqualityComparer`):
an invocation extends the teardown set only with the specific own method or
local function it RESOLVES to; unresolved calls extend nothing. A lambda counts
only as the handler provably wired to the class's own lifecycle event; a local
function only when a teardown context provably calls it. One narrow name
fallback remains, for method-GROUP handlers wired to an UNRESOLVED lifecycle
event (`Closing += Window_Closing` under an unreferenced WPF `Window` base): a
method group carries no argument list, so its name denotes the whole overload
set — not the invocation-overload conflation of #3.

## Corpus benchmark

40/44 (pre-#278) → 42/46 (slice 1) → **46/50 caught · 50/50 fixes clean ·
0 FPs**. All pre-existing rows unchanged; the four new rows are
`before[caught: OWN001] after[clean]`. The previously name-carried control
`screentogif-loaded-subscription/after.cs` now wires `Closing +=
Window_Closing` in code (the honest, provable form of the same fix) and stays
clean.

## Samples / goldens / suite

`frontend/roslyn/samples` own-check output: **byte-identical** to the first
slice (no sample used any of the four removed paths).
`fix_candidates_off.golden.json`: unchanged, byte-parity gate passes;
`check_fix_candidates_facts.py`, weak-subscribe checks, full
`tests/run_tests.py`, ruff and mypy all green.

## 5-repo sweep (before = slice 1, after = follow-up)

| target | before | after | delta |
|---|---|---|---|
| ScreenToGif (WindowsDesktop ref pack) | 65 | 74 | +9, classified below |
| CsvHelper | 37 | 37 | identical |
| Dapper | 6 | 6 | identical |
| Newtonsoft.Json | 509 | 509 | identical |
| RestSharp | 3 | 3 | identical |

### Classification of the 9 new ScreenToGif findings

All nine are ONE shape — the deliberate blocker-2 trade-off. Five windows
(`Editor`, `Recorder`, `NewRecorder`, `Webcam`, `Other/Startup`) subscribe
static `SystemEvents.*`/`SystemParameters.*` events and detach them in a
`Window_Closing`/`Startup_Closing` handler that is wired **only in XAML**
(`Closing="Window_Closing"`, e.g. `Editor.xaml:17`) — the attach never reaches
the extractor, so the name-suffix rule was the only thing crediting these, and
that rule is exactly the unsound path removed (verified: the `-=` sites are
real, e.g. `Editor.xaml.cs:375-377`, `Startup.xaml.cs:66`). They surface as
OWN014 (static-source region escape with no provable release path) — a kept
honest warning, not silence, per the doctrine. These are the first candidates
for a future XAML-aware slice that credits `Closing="..."` attaches with actual
evidence; until then the corpus keeps the code-wired form as the good control
and pins the name-only form as bad.

## SectorTS acceptance re-check

Unchanged by the follow-up: the reduction still flags GTD, PGC and KDT
(OWN001) and keeps the Dispose-releasing sibling silent. The real
`STS_new/SectorTS` run and the OwnAudit STS baseline (GTD = `runtime-only`)
remain the two pre-merge gates, executed locally.
