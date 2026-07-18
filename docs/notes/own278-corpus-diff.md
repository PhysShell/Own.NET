# #278 teardown-scoped release — before/after corpus + sweep evidence

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
