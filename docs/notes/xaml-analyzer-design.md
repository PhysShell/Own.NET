# Own.NET XAML analyzer — design note

> **Status / home.** This design note was authored in OwnAudit
> (`docs/xaml-analyzer-design.md`) and now lives here, in Own.NET, alongside the
> analyzer it describes. **Phase 1 (markup-only) is implemented** as the build-free
> runner [`audit/static/tools/xaml_check.py`](../../audit/static/tools/xaml_check.py),
> wired into [`audit/static/run_static.py`](../../audit/static/run_static.py) and the
> `desktop-wpf` profile, with its rule→category map in
> [`audit/static/taxonomy/categories.yml`](../../audit/static/taxonomy/categories.yml).
> Implemented rules: XAML101/102/103/104/106/107/108/109/110/111/112/113. Phase 2
> (Roslyn-linked) and Phase 3 (runtime correlation) remain as described below; the
> Phase-2 binding-path join is sketched in its own section near the end.

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
> catalogue below it implements XAML101/102/103/104/106/107/108/109/110, plus three rules added from
> the research-comb feedback — XAML111 (LayoutTransform cost), XAML112 (TemplateBinding opportunity)
> and XAML113 (inline-Freezable duplication). XAML100 (cross-sibling scope model) and XAML105 — both
> its in-file form and the **cross-*file*** `Source=` dictionary shadowing — are now implemented too;
> the cross-file pass resolves `MergedDictionaries` `Source=` to real files (relative / app-root /
> `;component/` pack forms), conservatively skipping anything that doesn't land on a scanned file.

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
| **XAML100** `ResourceShouldBeHoisted` ✅ | heavy shared resource (Brush/Geometry/Transform/Image, or Style/template via a full-subtree signature) keyed identically in ≥2 control-local `.Resources` scopes | per-instance control resources multiply working set; app/window scope shares (the 52×52 Brush collapse) | ✅ scope model maps |
| **XAML101** `DuplicateStatelessConverterResource` | identical stateless converter declared in many local dictionaries | converters are normally one shared instance; duplication is churn | ✅ |
| **XAML102** `DynamicResourceLikelyStatic` | `DynamicResource` for an app-local, lexically-stable, non-theme/system key | StaticResource recommended unless runtime-mutated; dynamic carries deferred lookup cost | ❌ Avalonia DynamicResource semantics differ |
| **XAML103** `SuspiciousSharedFalse` | `x:Shared="False"` on converters/styles/brushes outside documented exceptions | resources shared by default; `x:Shared=false` is the deliberate opt-out | ❌ WPF-only attribute |
| **XAML104** `DuplicateMergedDictionaryInclude` | same dictionary merged more than once | wasted load + order ambiguity | ~ (Avalonia has merged dicts, diff syntax) |
| **XAML105** `MergedDictionaryKeyShadowing` ✅ *(in-file + cross-file)* | key defined in ≥2 scopes — inline merged dictionaries, primary + merged, or (cross-file) an external `Source=` dictionary resolved to a real file → effective value depends on include order | "last merged wins, primary beats merged" — silent order dependence | ~ |
| **XAML106** `FreezableResourceShouldFreeze` | `Freezable` resource, no bindings/dynamic-resource/animation, missing `PresentationOptions:Freeze="True"` | freezing drops change-notification overhead + working set | ❌ **Freezable is WPF-only** |
| **XAML107** `VirtualizationExplicitlyDisabled` | `IsVirtualizing="False"`, `CanContentScroll="False"` on lists, non-virtualizing `ItemsPanel`, direct/mixed containers | virtualization critical for large item controls; these accidentally kill it | ✅ `VirtualizingStackPanel`/`ItemsRepeater` |
| **XAML108** `PerKeystrokeBindingWithoutDelay` | `TwoWay` + `UpdateSourceTrigger=PropertyChanged` on an editable property with no `Delay` | `Text` defaults to `LostFocus` for a reason; `Delay` exists to avoid per-keystroke flooding | ✅ |
| **XAML109** `TemplateComplexityHigh` | template-complexity score over threshold (node count, nested panels, Grid/StackPanel depth, trigger count, ItemsControl depth) | template expansion = extra visual-tree objects; layout is a 2-pass cost | ✅ |
| **XAML110** `ImageDecodedAtFullSize` | image shown small (explicit Width/Height ≤ thumbnail) but `Source` is a plain URI string, so no decode-to-size is possible | decode-to-size beats decode-full-then-scale; the hint needs a `BitmapImage`, not a string `Source` | ❌ WPF decode hints differ |
| **XAML111** `LayoutTransformSuspicious` | a `LayoutTransform` (attribute or property element) where a `RenderTransform` would do | `LayoutTransform` re-runs measure/arrange on change; `RenderTransform` is a render-time matrix. Candidate — legit when layout must reflow | ❌ Avalonia uses `LayoutTransformControl` |
| **XAML112** `TemplateBindingOpportunity` | inside a `ControlTemplate`, a `{Binding RelativeSource=TemplatedParent}` with no converter / not two-way | `{TemplateBinding}` is the cheaper compiled form; the converter/two-way exclusions are exactly TemplateBinding's limits | ✅ |
| **XAML113** `InlineFreezableDuplication` | the same inline Freezable (brush/geometry/transform set as a property value, not keyed) declared identically more than once | each inline copy is a separate object; one shared keyed resource collapses them (the inline case of XAML100) | ✅ |

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

### Phase 2 mechanics — the binding-path join (and where the link-extractor lives)

The markup pass already separates two kinds of fact, and Phase 2 makes the seam explicit:

- **`XamlPerfRules`** — resource scope, dictionaries, virtualization, layout, images, Freezables.
  These are *self-contained in markup* and are exactly the Phase-1 rules already shipped; they need
  no C# at all.
- **`XamlLinkFacts`** — `x:Class`, `DataContext` type, binding paths, event handlers, converter
  types, `ItemsSource`. These are **pointers into C#**: on their own they are inert; their value is
  the *join* to a symbol.

The join is the whole point — it is where the interprocedural core earns its keep and where this
stops being "found a `DynamicResource`, nodded gravely":

```
  binding path in XAML  ─┐
  (Text="{Binding Qty}") │
  x:Class + DataContext ─┼─►  Roslyn resolves Qty -> the property symbol
                         │       └─► own-check's interprocedural engine walks:
                         │              getter (alloc? materialize?), setter,
                         │              the PropertyChanged cascade it raises,
                         │              the converter on the binding,
                         │              the ItemsControl/template it invalidates
                         └─►  report: "this TextBox updates the source on every
                                       keystroke, runs this setter, raises these N
                                       properties, hits this converter, invalidates
                                       this ItemsControl"
```

**Where the link-extractor lives — the decision.** It does **not** get a new parallel C# checker in
OwnAudit (`src/OwnAudit.Xaml/`). That would re-create the "two analyzers in two repos" problem this
note opens by ruling out, and it contradicts the canonical-in-Own.NET rule (`README`/`Plan.md`:
"*Don't reimplement it here*"). The XAML link-facts extractor is an **extension of `own-check`** — the
existing error-tolerant `SemanticModel` extractor that already lives in Own.NET and already does the
acquire/release + region-escape walk. own-check learns to read the `.xaml` next to the `.cs` it is
already parsing (resolve `x:Class` → the code-behind type → the `DataContext`/binding symbols), and
emits the binding-join findings as more `OWNxxx`/`XAML2xx` facts on the **same rails**. One extractor,
one semantic model, one lifetime engine — no second toolchain to keep version-matched.

`OwnAudit.Xaml` as a standalone C# project is the **post-lift-out product form** (Plan.md §7), not the
way to build Phase 2: when `audit/` lifts out, the markup pass + the own-check XAML extension become
that package. Building it standalone *before* lift-out just means maintaining the parallel surface the
markup phase deliberately avoided.

**Static is a candidate, runtime confirms (ties to Phase 3).** The join produces a *suspicion* —
"this binding *can* flood the setter per keystroke". Whether it actually fires tens of thousands of
times in a real screen is a runtime fact: the converter-call / `PropertyChanged` counters of Phase 3
promote XAML108+the binding-join candidate from "structurally hot" to "measured hot" through the same
`correlate.py` suspect/confirm split. That is the difference between "you have an un-delayed
`PropertyChanged` binding" and "*this* is why the form freezes when you type one digit".

The link-fact record stays the canonical shape (so it rides the existing pipeline): a
`{tool: "own-check", rule: "XAML2xx", resource: "<binding path>", path, line, message}` where `path`
/`line` point at the **XAML** site (where a developer fixes it) and the message names the resolved C#
symbol chain — markup and code stitched into one finding, not two disconnected alerts.

**The link is the naming convention, not the `.g.cs` build artifact.** WPF's markup compiler emits a
`.g.cs` (InitializeComponent / IComponentConnector glue, `x:Name` fields, `event += handler` wiring)
into `obj/` — but only after a successful markup-compile, which would drag the join into the
build-required tier, and a freshly-cloned legacy target (the kind own-check exists for) has no current
`.g.cs`. We don't need it: the wiring it encodes is a **fixed contract** we synthesize without
building — `x:Class`→code-behind type, `Click="OnSave"`→method, `x:Name="btn"`→field,
`{Binding Qty}`→DataContext property. So the join stays **build-free** (Linux CI, broken solutions),
and `.g.cs` is reserved as an *optional build-tier ground-truth cross-check* (confirm the
convention-derived wiring, catch compiler-only edge cases like attached events / EventSetter
connection-ids), folded in later like the other build-required tiers — never the mechanism. (BAML is
even further down: a post-build binary, only for source-less audits — not on this roadmap.)

**First slice built.** `audit/static/tools/xaml_join.py` implements **XAML203**: a view whose
`x:Class` component has an OwnIR subscription the engine flagged `released=false`, wired from a
load-lifecycle handler (`Loaded`/`Initialized`/`DataContextChanged`) — the closed-view-retained leak.
It is anchored at the **code-behind subscription site** (where the matching `-=` goes), so it lands at
the same file+line as own-check's `OWN001` and **clusters with it into one high-confidence finding**
rather than double-reporting the same leak on a separate `.xaml` line; the XAML view that wired it
rides in the message. The join's honest value here is *not* new detection (own-check already finds the
subscription leak in the `.cs`) but the cross-source **confidence upgrade + view-lifecycle framing** —
where the join finds what neither source can alone (binding→`List<T>` getter, allocating converter on a
hot binding) it needs the DataContext type and OwnIR getter/converter facts, which is the XAML200/204
increment, deliberately not guessed here. own-check persists its OwnIR facts via a new `--emit-facts`,
and `run_static.py` runs the join whenever both fact sources are produced *this run*, folding the
result into the pipeline.

**The Phase-1 → Phase-2 seam is built.** The markup pass now emits a structured fact document
alongside its SARIF — `audit/static/tools/xaml_facts.py` writes `xaml-facts.json` from the *same*
parsed tree (no second parser), in an envelope that mirrors OwnIR's `*.facts.json`
(`{xaml_facts_version, module, documents}`). Each document carries the two fact families above:
**XamlResourceGraph** (`resources`, `merged_dictionaries`) and **XamlBindingFacts** (`bindings` with
parsed path / mode / UpdateSourceTrigger / converter / Delay / RelativeSource, plus `event_handlers`,
`converters_used`, and the file's `x_class`). Phase 2 is then purely the *join*: read `xaml-facts.json`
next to the OwnIR facts from `OwnSharp.Extractor`, resolve each binding `path` against the
`x_class` / DataContext type, and emit the `XAML2xx` link findings — no new XAML parsing, no second
toolchain. Phase 2 consumes this artifact; it does not re-derive it.

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
