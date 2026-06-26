# Own.NET XAML analyzer — design note

> **Status / home.** This design note was authored in OwnAudit
> (`docs/xaml-analyzer-design.md`) and now lives here, in Own.NET, alongside the
> analyzer it describes. **Phase 1 (markup-only) is implemented** as the build-free
> runner [`audit/static/tools/xaml_check.py`](../../audit/static/tools/xaml_check.py),
> wired into [`audit/static/run_static.py`](../../audit/static/run_static.py) and the
> `desktop-wpf` profile, with its rule→category map in
> [`audit/static/taxonomy/categories.yml`](../../audit/static/taxonomy/categories.yml).
> Implemented rules: XAML101/102/103/104/106/107/108/109. Phase 2 (Roslyn-linked)
> and Phase 3 (runtime correlation) remain as described below.

The biggest honest gap in OwnAudit's `docs/wpf-audit-coverage.md` ("**XAML analyzer** — a large slice of the
wishlist lives in `.xaml`, not `.cs` … Biggest gap — and technically cheap: XAML is XML, rules are
tree patterns"). This note turns that gap into a concrete, phased plan with a per-rule catalogue,
each rule tagged **build-free / hybrid / runtime** and with its **Avalonia-mappability**, so nothing
on the wishlist quietly falls through and so the first slice can ship without waiting on the stand.

The methodology is the project's own — *suspect statically → confirm at runtime → targeted fix →
re-measure* — pointed at markup. The whole point of this note is the **architectural seam**, not the
rule count.

---

## Which repo builds this (read first)

This is a **design note that lives in Own.NET, alongside the analyzer it describes in
`Own.NET/audit/`.** Per `README.md` / `Plan.md`, the audit is **canonical in
Own.NET** ("*Don't reimplement it here*"): the build-free static runners live in
`Own.NET/audit/static` (next to own-check and CodeQL), and the interprocedural lifetime engine the
hybrid rules feed (CFG lowering, dataflow, OWN001 acquire/release, OWN014 region-escape) lives in
Own.NET too — `OwnAudit/src/OwnAudit.Core` is a thin lift-out skeleton, **not** that engine.

So the implementation homes are:

- **Phase 1 (markup-only)** → a build-free XAML runner in **`Own.NET/audit/static`**, alongside the
  other build-free static runners. **Done:** `audit/static/tools/xaml_check.py`. It emits the
  canonical finding record into the same `audit/` aggregate pipeline.
- **Phase 2 (hybrid, Roslyn-linked)** → **Own.NET's interprocedural core**, because it needs the
  Roslyn semantic model and the acquire/release engine that physically live there.
- **Phase 3 (runtime correlation)** → wherever the runtime correlation lands at lift-out time; today
  the suspect/confirm split is prototyped in `OwnAudit/runtime/correlate.py`, canonical runtime in
  `Own.NET/audit/runtime`.

OwnAudit's role here is the **design note's origin + (post-lift-out) the consuming/orchestration
side**, not a parallel XAML checker. Everything below describes the analyzer's shape; "the same
pipeline" means **Own.NET's `audit/` pipeline**, not a new one in OwnAudit.

## The one architectural decision

**XAML is another fact source feeding the existing engine — not a parallel linter.**

`audit/` already has one such fact source (the Roslyn/own-check static layer) whose findings flow
through normalize → score → SARIF → baseline → report, and a lifetime engine behind OWN001/OWN014.
XAML becomes a *second* fact source emitting the **same finding record** into that **same `audit/`
pipeline**. No new mechanism: a XAML finding rides the existing fingerprint → SARIF → baseline →
ratchet → drift path for free.

```
  .cs  ──(Roslyn extractor)──┐
                             ├─► findings.json ─► fingerprint ─► SARIF / baseline / ratchet / drift
  .xaml ──(XAML extractor)───┘                                            │
                                                       runtime.json ──► correlate.py (confirm)
```

Concretely this means the XAML pass emits the canonical record
(`{tool, rule, category_name, resource, path, line, message, suppressed}`, `resource` a *description*
not a CLR type — same contract as the own-checks) and does **not** grow its own report/baseline/gate
code. The hybrid phase then links XAML facts to graph nodes; the runtime phase reuses
`correlate.py`'s suspect/confirm split verbatim.

## Where this sits relative to existing analyzers (our niche)

WpfAnalyzers / PropertyChangedAnalyzers are mature but cover **correctness**: dependency-property
declaration, `MarkupExtensionReturnType`, converter boilerplate (e.g. WPF0070 "add default field to
converter"), `INotifyPropertyChanged` plumbing. They do **not** target XAML **performance/lifetime**
pathologies — resource-scope bloat, `DynamicResource` misuse, merged-dictionary shadowing,
virtualization disablement, expensive converter hot paths. That perf/lifetime axis is our lane;
we should not re-implement their correctness rules.

---

## Phase 1 — markup-only static pass (build-free, runs in CI)

Pure XML: parse `.xaml`/`.axaml`, resolve resource scopes, build a merged-dictionary graph.
**No .NET build, no stand** — a build-free runner in `Own.NET/audit/static` that runs on Linux in CI
like the other build-free runners there. This is the cheapest deliverable of the analyzer and closes
~half the ⚠️ rows in the coverage matrix.

> **Implementation note (this repo).** Shipped as `audit/static/tools/xaml_check.py` — pure stdlib,
> so it has *no* toolchain prerequisite and always runs on Linux CI (unlike own-check, which needs a
> .NET SDK). The runner's selftest (`xaml_check.py --selftest`) gates the rules, the
> line-preservation requirement, and the SARIF round-trip through the shared `parse_sarif`. Of the
> catalogue below it implements XAML101/102/103/104/106/107/108/109; XAML100 (cross-sibling scope
> model), XAML105 (cross-*file* dictionary shadowing) and XAML110 (decode-target heuristics) are the
> documented deferred tail.

**Line preservation is a hard requirement, not a detail.** A plain `xml.etree.ElementTree.parse`
discards source positions, but our finding contract requires a real `line` and `report/sarif.py`
maps a missing/0 line to SARIF `startLine=1` — so a naive ElementTree pass would point *every*
XAML alert at the top of the file in code scanning and the dashboard. The parse step must therefore
be **line-preserving** while staying stdlib (still build-free): expat already tracks
`CurrentLineNumber`, so building the tree through an expat `StartElementHandler` that stamps each
element's start line gives us per-element lines with no third-party dependency — no `lxml`. (The
shipped runner does exactly this in `parse_xaml`.) Every rule below resolves its finding to the
offending element's stamped line; a rule that can only locate a file-level issue says so explicitly
(emits line 0, which `report/sarif.py` keeps file-level) rather than silently emitting line 1.

| Rule | What it flags | Doc rationale | Avalonia |
|---|---|---|---|
| **XAML100** `ResourceShouldBeHoisted` | heavy shared resource (Brush/Style/Geometry/Transform/BitmapImage/template) declared in a control-local dictionary, recurring across siblings | per-instance control resources multiply working set; app/window scope shares (the 52×52 Brush collapse) | ✅ scope model maps |
| **XAML101** `DuplicateStatelessConverterResource` | identical stateless converter declared in many local dictionaries | converters are normally one shared instance; duplication is churn | ✅ |
| **XAML102** `DynamicResourceLikelyStatic` | `DynamicResource` for an app-local, lexically-stable, non-theme/system key | StaticResource recommended unless runtime-mutated; dynamic carries deferred lookup cost | ❌ Avalonia DynamicResource semantics differ |
| **XAML103** `SuspiciousSharedFalse` | `x:Shared="False"` on converters/styles/brushes outside documented exceptions | resources shared by default; `x:Shared=false` is the deliberate opt-out | ❌ WPF-only attribute |
| **XAML104** `DuplicateMergedDictionaryInclude` | same dictionary merged more than once | wasted load + order ambiguity | ~ (Avalonia has merged dicts, diff syntax) |
| **XAML105** `MergedDictionaryKeyShadowing` | key defined in multiple merged dictionaries → effective value depends on include order | "last merged wins, primary beats merged" — silent order dependence | ~ |
| **XAML106** `FreezableResourceShouldFreeze` | `Freezable` resource, no bindings/dynamic-resource/animation, missing `PresentationOptions:Freeze="True"` | freezing drops change-notification overhead + working set | ❌ **Freezable is WPF-only** |
| **XAML107** `VirtualizationExplicitlyDisabled` | `IsVirtualizing="False"`, `CanContentScroll="False"` on lists, non-virtualizing `ItemsPanel`, direct/mixed containers | virtualization critical for large item controls; these accidentally kill it | ✅ `VirtualizingStackPanel`/`ItemsRepeater` |
| **XAML108** `PerKeystrokeBindingWithoutDelay` | `TwoWay` + `UpdateSourceTrigger=PropertyChanged` on an editable property with no `Delay` | `Text` defaults to `LostFocus` for a reason; `Delay` exists to avoid per-keystroke flooding | ✅ |
| **XAML109** `TemplateComplexityHigh` | template-complexity score over threshold (node count, nested panels, Grid/StackPanel depth, trigger count, ItemsControl depth) | template expansion = extra visual-tree objects; layout is a 2-pass cost | ✅ |
| **XAML110** `ThumbnailDecodedAtFullSize` | image shown small but declared without decode hints; large bitmap animated/scaled with no `BitmapScalingMode` | decode-to-size beats decode-full-then-scale; `LowQuality` smooths animated scaling | ✅ |

Exception lists matter (this is where naive greps die): **XAML106** must skip Freezables that are
animated, data-bound, or reference a `DynamicResource` (can't freeze); **XAML103** must allow the
`FrameworkElement`/`FrameworkContentElement` insertion case. Start **XAML101** with exact
type+key match; structural equivalence is a later refinement. (All three exception rules are
implemented and selftested in `xaml_check.py`.)

## Phase 2 — Roslyn-linked hybrid (where the graph pays rent)

These are genuinely **not offered by existing WPF analyzers** because they require linking XAML
usage to code symbols — which we already have machinery for. XAML says *which* converter/handler;
the graph says *what it does*.

| Rule | What it flags |
|---|---|
| **XAML200** `ConverterAllocatesOnHotPath` | `Convert`/`ConvertBack` allocates collections / materializes LINQ / touches FS / reflects / uses Dispatcher |
| **XAML201** `ConverterCallsExpensiveServices` | converter body reaches localization/IO/deep call chains |
| **XAML202** `MarkupExtensionProvideValueExpensive` | custom `ProvideValue` allocates heavily / re-resolves services / does uncached runtime work |
| **XAML203** `XamlEventHandlerCreatesLongLivedSubscription` | `Loaded=`/`Click=`/`EventSetter.Handler` resolves to code that subscribes a longer-lived service with no matching unsubscribe |
| **XAML204** `ItemsSourceBackedByListRebuildPattern` | `ItemsControl` bound to a getter returning `List<T>`/`IEnumerable` (full regen / wrapper overhead) vs `ObservableCollection<T>` |
| **XAML205** `GetterBoundFromXamlAllocatesOrMaterializes` | XAML-bound getter allocates / materializes on each call |

**XAML203 reuses the existing acquire/release + region-escape engine** (the same one behind own-check
OWN001 `+=`-without-`-=`): a XAML-originated leak becomes a lifetime fact on the same rails, not a new
detector.

## Phase 3 — runtime correlation (reuse `correlate.py`, don't add static cleverness)

Externally validated by the research: *don't sell static as a guarantee — emit candidates, confirm at
runtime.* That is exactly our existing `findings.json` (suspicion) → `runtime.json` → `correlate.py`
(confirmation) split. The XAML candidates that need runtime proof:

- **binding hot-path reality** — a converter-call counter / binding-error collector says *which* of the
  XAML200/204 candidates actually fire tens of thousands of times in a scenario.
- **visual-tree inflation / layout storms** — XAML109's static node count, upgraded by the real
  instantiated-tree count (depends on item counts, triggers, virtualization, theme).
- **image/brush cost under animation** — XAML110 confirmed only when a screen animates/zooms.
- **lifetime proof for XAML-originated patterns** — XAML203 promoted from suspicion to a retention
  path via the heap walker (phase-5 collector).

This phase needs the **runtime-trace collector** — the *other* gap from OwnAudit's `wpf-audit-coverage.md`
(binding-error trace + Dispatcher/notification counters). XAML phase 3 and that collector are the
same build.

---

## Avalonia oracle intersection

Phase-1 markup rules are **mostly oracle-reachable** (`.axaml` is the same dialect): XAML100, 107,
108, 109, 110 run on a leaking Avalonia app today. The **WPF-only tail** validated only on STS:
XAML102/103 (`DynamicResource`/`x:Shared` semantics differ) and **XAML106 (Freezable — WPF-only
concept)**. This is the same today/never line already drawn in the coverage matrix, so the XAML
analyzer and the oracle are complementary: the oracle gives us live `.axaml` to exercise the
framework-agnostic markup rules; the WPF tail waits for STS. (The shipped runner enforces this:
XAML102/103/106 short-circuit when the root declares the Avalonia namespace.)

## Roadmap summary

1. **Phase 1** — a build-free XAML runner in **`Own.NET/audit/static`** (line-preserving parse, emits
   the canonical finding record, runs in CI). **Done** (`audit/static/tools/xaml_check.py`), starting
   with the rules that already had ⚠️ rows in the coverage matrix: **XAML107** (virtualization-off),
   **XAML108** (per-keystroke binding), **XAML109** (template complexity), plus the reliably
   markup-detectable resource rules XAML101/102/103/104/106. No .NET build, no stand.
2. **Phase 2** — link XAML facts to the Roslyn semantic model in **Own.NET's interprocedural core**;
   the hybrid converter/handler/items-source rules. This is where that core earns its keep.
3. **Phase 3** — fold XAML candidates into the runtime correlation (`audit/runtime`; prototyped in
   `OwnAudit/runtime/correlate.py`) alongside the runtime-trace collector; one merged finding model,
   static suspicion upgraded by scenario evidence.

The throughline: **XAML is a first-class fact source for the same resource + lifetime core in
Own.NET**, so each phase reuses machinery `audit/` already has (finding contract,
fingerprint/baseline/ratchet, the acquire/release engine, the runtime correlation) instead of growing
a parallel checker — in either repo.
