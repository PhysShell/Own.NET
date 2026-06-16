# P-014 — Project-local semantic resolution for the C# extractor

- **Status:** draft (P0 — the extractor is currently unusable on real desktop code)
- **Depends on:**
  - [P-001](P-001-csharp-extractor.md) — the seam this deepens. P-001 defines the
    Roslyn-extractor → OwnIR → Python-core pipeline (P-001:71-77) *and* owns the
    `ownir_version` stamp / additive-fact discipline (P-001:93-97). Both stay intact.
  - [P-004](P-004-wpf-lifetime-profile.md) — consumes the cleaned signal; keeps the
    long-lived-owner lifetime judgment (P-004:14-16, WPF005 → OWN014 at P-004:35,45).
  - [P-005](P-005-idisposable-ownership.md) — the disposable-field/local checks
    benefit from the same `SemanticModel` later (a follow-up increment, not this one).
  - `spec/OwnCore.md`, `spec/Diagnostics.md`, `spec/Lifetimes.md` — the fact
    vocabulary and the diagnostic catalogue. **Unchanged by this proposal** (see
    *Relationship to the spec & docs*).
- **Strategy hub:** [`docs/ROADMAP.md`](../ROADMAP.md).

## Motivation

Run the v0 extractor on a real WPF/desktop solution (GTM, ~hundreds of `.cs`) and
it produces a *wall* of false positives. Measured on that codebase: of **326**
"event subscribed but never unsubscribed" findings, **105 (32%)** are pure
arithmetic — `sum += value`, `sumSbor += p.Sbor.Cost`, `totalItem.Quantity +=
item.Quantity`, and even **for-loop steps** (`for (int startIndex = 0; …;
startIndex += batchSize)` flagged four times as an "event"). The remaining 221
are real subscriptions, but they are drowned in the noise — and many of *those*
are not leaks either (a `Window` subscribed to its own `Loaded`/`Closing`).

Two distinct failures, both predicted by our own docs:

1. **It matches arithmetic as event subscriptions.** A syntax-only Roslyn pass
   cannot tell `event += handler` from `decimal += decimal` — both parse to the
   same `AddAssignmentExpression`. `IsHandler` (Program.cs:91-92) accepts any
   `IdentifierName`/`MemberAccess` RHS, so every numeric accumulation becomes a
   "leak". On a real codebase this is the *majority* of the noise.
2. **It can't see external types.** `grid.View.CellValueChanged += …` on a
   DevExpress control, `Closing += Window_Closing` on a WPF `Window` — the
   declaring type lives in an assembly the syntax pass never opened, so the
   extractor guesses, and guesses "leak".

This is exactly the `event += without -=` cell the reality-matrix tags **⚠️
heuristic** with "false positives" (ROADMAP.md:100), and exactly the
*confidently-wrong* tooling the philosophy section rejects: *"honestly skipping
beats confidently lying; the market for confident-but-wrong tooling is already
saturated"* (ROADMAP.md:49-51). The cause is structural: the `event +=` fact is
**type-dependent**, and v0 is **type-free**. No amount of syntactic cleverness
closes that gap — a tightened heuristic (e.g. "RHS must be a method declared in
the class") still lies on `total += obj.Foo` when `Foo` also names a method, and
still cannot see an external event. The only real fix is to let the extractor
*see types*.

## Scope

Build the type-dependent facts from a Roslyn **`SemanticModel`** instead of raw
syntax. Concretely, `lhs += rhs` becomes a subscription fact **iff** the model
binds `lhs` to an event (`IEventSymbol`) — equivalently, the model classifies the
node as an `IEventAssignmentOperation` — otherwise it is not emitted. Three tiers,
in cost order.

### Tier A — project-local compilation (default, no third-party refs)

Replace the per-file `CSharpSyntaxTree.ParseText(...)` loop (Program.cs:131-155,
one isolated tree per file) with a single `CSharpCompilation` over **all** input
source trees, referencing the extractor runtime's framework assemblies via
`AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")` (zero-config — they are on disk
wherever `dotnet` runs) — *nothing else*. Compiling all inputs together means
cross-file *and* cross-project in-project types/events resolve for free, with no
project-to-project references and no MSBuild. Per candidate `+=`, take
`GetSemanticModel(tree)` and inspect the LHS symbol / operation. (Killing the
numeric FPs needs no references at all — a declared `decimal sumSbor` binds to an
`IFieldSymbol` regardless of whether `decimal` resolves, and an `IFieldSymbol` is
not an `IEventSymbol`; the framework set only *promotes* BCL events from
"unresolved" to a clean fact.) Scoping the compilation to one project of a large
monorepo is a noted future capability — see *Open questions*; the default is one
compilation over everything passed in. This already resolves locals, fields, in-project types and primitives:

- `sum += value` → `sum` binds to a `decimal` local/field → not an event →
  **silent** (cause #1 gone — all 105 numeric FPs drop);
- an in-project `event Foo += h` → `IEventSymbol` → real subscription fact;
- BCL events (`INotifyPropertyChanged.PropertyChanged`,
  `INotifyCollectionChanged.CollectionChanged`) resolve from the framework
  reference → real subscription fact;
- a DevExpress `grid.CellValueChanged += h` → declaring type unresolved → handled
  by the fallback below.

We **never reference or parse DevExpress (or any third-party) source.** Their
types simply stay unresolved, and unresolved is not "leak".

### Tier B — full references (opt-in flag)

When the user *wants* external events checked, resolve the project's real
references. Two mechanisms, traded off in *Open questions*:

- **`MSBuildWorkspace`** — open the `.csproj`/`.sln`; the build system resolves
  references (PackageReferences, project-to-project, framework, transitive). This
  is the principled "load all the target's dependencies" with no fake project.
  *Cost:* needs a matching .NET SDK + a prior `restore`, pulls in
  `Microsoft.CodeAnalysis.Workspaces.MSBuild` + MSBuild assemblies (via
  `MSBuildLocator`), is SDK-version-sensitive, and is heavier in CI.
- **`MetadataReference` over the target's built `bin/**/*.dll`** — point the
  compilation at the already-compiled output. Roslyn reads assembly **metadata**
  (public types and events) directly — **no source, no decompiler.** *Cost:*
  requires a prior successful build (populated `bin`), and discovering the right
  TFM output folder; over-references harmlessly (referencing unused DLLs is free).

Either way it is **metadata only** — never third-party source, never a decompiler.

### Unresolved fallback (first-class, honest)

When a symbol cannot be resolved (an error type — Tier A on an external event,
Tier B on a missing reference), the extractor **MUST NOT emit a leak, and MUST NOT
fall back to the old syntactic guess.** It emits a distinct *informational*
diagnostic, in our voice:

```text
OWN050: cannot verify 'grid.View.CellValueChanged' — its declaring type is an
unresolved reference (build the project or pass references); leakage analysis
skipped
```

This is the ROADMAP's "honestly skipping" made literal: it is not a leak claim
and not a clean bill of health — it is *unchecked*, and we say exactly that. It is
counted separately from findings and never fails a build. **Severity is
`warning`** — see *Severity & plumbing*; there is no `info`/`note` tier in the
core and this proposal does not invent one.

> Note: an early sketch phrased this as "…skipped; not a leak". We drop the
> "not a leak" clause — it reads as a verdict ("we checked, it's fine") when the
> truth is the opposite of a verdict. "leakage analysis skipped" is the honest
> framing.

## Severity & plumbing (the non-obvious part)

Two facts about the current core constrain the implementation:

1. **The core has exactly two severities, `ERROR` and `WARNING`** (`Severity`
   enum, `ownlang/diagnostics.py:28-30`); `Diagnostic` defaults to `ERROR`
   (diagnostics.py:79). In `ownir.py`, `severity` is a presentation string scoped
   to `error`/`warning` (render_finding, ownir.py:174-183). There is **no level
   below warning.** The unresolved diagnostic is therefore a `warning`.

2. **`check_facts()` drops every diagnostic whose `severity != Severity.ERROR`**
   (`ownir.py:326-329`). A warning emitted through the *normal* diagnostic path
   would be silently discarded and never reach the C# bridge. The unresolved
   channel must therefore be produced as a `Finding` through a path that
   **bypasses** that filter — mirroring how `DI001` is produced and appended
   directly via `findings.extend(_di_findings(facts))` (ownir.py:377; helper at
   ownir.py:390-412). The subscription-leak message itself is built in the
   `check_facts` if/elif chain (ownir.py:344-372); the new channel plugs in as a
   sibling helper, not inside that chain.

Code id: **OWN050** — deliberately a fresh band, not a gap-fill. OWN001-041 are
all *faults*; this is a *coverage note* ("we could not check"), so it sits outside
the fault series rather than squatting an unrelated gap (OWN025-029 would read as
buffer-policy codes, since OWN015-024 is the buffer block). OWN050 opens a "C#
front-end / resolution coverage" band (051+ reserved for future front-end coverage
notes). Stays in the `OWN` namespace (the user sees one prefix; the `DI001` code is
the captive-dependency check's, not a precedent for a new front-end prefix). Add
the title to the `TITLES` map (a code with no title renders empty but does not
crash, diagnostics.py:88-90).

## Rollout (incremental — one fact at a time)

The `SemanticModel` infrastructure (one `CSharpCompilation`, per-tree
`GetSemanticModel`) is built once, but applied **first to the event-subscription
fact only** — the highest-noise check. The disposable-field, local-disposable and
pool detectors keep their current name/suffix matching (`IsDisposableType`,
Program.cs:123-127) for now; they are lower-volume and lower-FP, and migrating
them to symbol-based type resolution is a clean follow-up increment once the
compilation plumbing has proven itself. This keeps P-014 a contained, reviewable
change rather than a rewrite of every detector.

## Build plan (Tier A, incremental)

Ordered; each task is independently reviewable with an explicit acceptance check.
T1→T2 are sequential (infra then fix); T3/T4 land with T2; T5 (docs) any time; T6
(validation) last.

### T0 — dependency prep
- `OwnSharp.Extractor.csproj`: confirm `Microsoft.CodeAnalysis.CSharp` is the only
  Roslyn package needed (Tier A uses TPA `MetadataReference`s — **no** Workspaces /
  MSBuild package). Update the syntax-only comment (csproj:24).
- **Accept:** builds, no new heavy dependency.

### T1 — one compilation + semantic model (infra, no behaviour change)
- Refactor Program.cs:131-155: parse every input `.cs` into a `SyntaxTree` (keep
  `path:`), build **one** `CSharpCompilation.Create(...)` over all trees with
  references = `AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")` split on
  `Path.PathSeparator` → `MetadataReference.CreateFromFile`, options
  `new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)`. Error-tolerant:
  ignore compile diagnostics.
- Get `compilation.GetSemanticModel(tree)` per tree; thread it into the
  class/assignment loop. Leave every detector's logic unchanged for now.
- **Accept:** extractor runs on GTM + `frontend/roslyn/samples` and emits the
  **same facts as before** (pure regression — model is built but unused); no crash
  on unresolved symbols; runtime acceptable (one parse of all files + symbol tables).

### T2 — semantic event discriminator (the fix)
- In the event loop (Program.cs:174-189) replace the `IsHandler` + AddAssignment
  gate with symbol-based classification of `a.Left`:
  - `model.GetSymbolInfo(a.Left).Symbol is IEventSymbol` (equivalently
    `model.GetOperation(a) is IEventAssignmentOperation`) → **subscription fact**
    (released = existing `-=` / `.Stop()` matching, unchanged).
  - resolved to a non-event (`ILocalSymbol`/`IFieldSymbol`/`IPropertySymbol`/
    `IParameterSymbol`…) → **skip** — this is what kills the numeric FPs.
  - unresolved (`Symbol == null` / error-typed receiver) → emit an **unresolved
    marker** fact (e.g. `resource: "unresolved-subscription"`) for the OWN050
    channel. **Do not** fall back to the old syntactic guess.
- **Accept:** on GTM all 105 numeric `+=` FPs disappear (`for(... i += step)`,
  `sum += value`, `x.Qty += y.Qty`); in-project + BCL events
  (`PropertyChanged`/`CollectionChanged`) still emit subscription facts;
  WPF/DevExpress events emit unresolved markers (not leaks).

### T3 — `--event-leaks` gate (default off)
- Parse a `--event-leaks` flag in Program.cs (default **off**). When off, suppress
  emission of `subscription`/`timer`/`unresolved-subscription` facts; keep
  `disposable`/`local-disposable`/`pool`. Tier A landing flips the documented
  default to **on**.
- **Accept:** default GTM run emits zero subscription/OWN050 output; `--event-leaks`
  turns them on.

### T4 — OWN050 channel in the core (warning, bypasses the ERROR filter)
- `ownlang/ownir.py`: add `_unresolved_findings(facts)` mirroring `_di_findings`
  (helper near :390-412), appended at :377 via `findings.extend(...)`. Build a
  `Finding(code="OWN050", message="cannot verify '<event>' — its declaring type is
  an unresolved reference (build the project or pass references); leakage analysis
  skipped", …)` rendered as **warning**. This path bypasses the `ERROR`-only filter
  at check_facts (:326-329).
- `ownlang/diagnostics.py`: add `"OWN050": "declaring type unresolved — leakage
  analysis skipped"` to `TITLES` (:33-71).
- **Accept:** a sample with an unresolved external event yields one OWN050 warning;
  exit code unchanged (warnings never fail the build).

### T5 — spec + prose (anti-drift)
- `spec/Diagnostics.md`: add the OWN050 row (the one normative addition — a
  coverage note / warning).
- Supersede the 10 "syntax-only" sites listed under *Relationship to the spec &
  docs*, **including the by-hand `ROADMAP.md:37-40` reword** (a grep for
  "syntax-only" misses it). Remove the `frontend/roslyn/README.md:73-75` non-goal
  "semantic event resolution".
- **Accept:** grep for "syntax-only" / "no compilation, no references" is clean;
  ROADMAP philosophy reworded; spec/ core otherwise untouched.

### T6 — tests / corpus validation
- Add corpus cases: numeric `+=` (silent), in-project event (subscription),
  BCL `PropertyChanged` (subscription), unresolved external event (OWN050). Update
  any test asserting the old syntactic behaviour.
- Re-run the GTM triage; record before/after (326 findings / 105 FP → event-FP ≈ 0).
- **Accept:** test suite green; GTM numeric-`+=` event FPs at zero.

## Non-goals

- **A full semantic C# frontend.** We resolve only what a *specific fact* needs
  (the type of a `+=` LHS). No whole-program dataflow, no async/generics/LINQ
  inference. Still **narrow, intraprocedural, fact-only** — `SemanticModel` is a
  sharper chisel, not a mandate to "understand C#".
- **Parsing third-party source, or a decompiler.** Tier B reads compiled
  metadata; that is the entire external-reference story. If it isn't in metadata,
  it's unresolved → the fallback fires.
- **Deciding whether a *resolved* subscription is actually a leak.** That lifetime
  judgment (is the owner long-lived? is a `Window`'s own-event `-=` moot?) stays
  **P-004** — its mechanisms are `[OwnIgnore("source lifetime is shorter")]`
  (P-004:60-61) and WPF005 firing OWN014 only on a *longer-lived* source
  (P-004:35,45). P-014 removes the *gross* noise (arithmetic, unresolved
  externals) so P-004's heuristic operates on real subscriptions only. (The first
  P-004 increment — the self-owned-source exemption, skipping a subscription whose
  source is `this` or a field the class constructs — landed alongside this work;
  see P-004.)
- **Requiring a green build for Tier A.** The compilation degrades gracefully:
  partial resolution still types the locals/fields Tier A needs.
- **A new `info`/`note` severity level.** The unresolved channel is a `warning`.
  Adding a third severity is a real (if small) core change and is out of scope.

## Versioning

An additive, optional informational channel does **not** require an
`OWNIR_VERSION` bump. `OWNIR_VERSION = 0`, bumped only "whenever the fact
vocabulary changes incompatibly" (ownir.py:77-81); the existing additive precedent
is explicit — "the resource/type fields are additive and optional, so they do NOT
bump `ownir_version`" (ownir.py:48-51). `load()` rejects only a mismatched integer
and treats an absent field as current (ownir.py:200-208). This discipline
originates in **P-001:93-97** and the `ownir.py` docstring — *not* P-013 (an
earlier draft mis-cited P-013, which contains no version rule; its governing
constraint is the ROADMAP "one checker" rule, P-013:19-21).

In the recommended implementation the unresolved diagnostic is a **core-side
`Finding`** (the `_di_findings`-style path), so it introduces *no new OwnIR input
fact at all* — it is trivially version-neutral. Tier A/B change only *how* the
extractor decides to emit the existing subscription fact, not the fact's shape.

## Relationship to the spec & docs (avoiding drift)

The whole point of `spec/` vs `docs/` is that aspirational prose must not lie
about the code. Explicitly:

- **Normative `spec/` is untouched.** A whole-word search over all 8 spec files
  finds **zero** mentions of `Roslyn`, `SemanticModel`, whole-word `references`,
  or `syntactic`; `syntax` only ever means OwnLang's own surface grammar
  (Grammar.md:4), and `compilation` appears once meaning C# `[Conditional]`
  symbols in codegen (BufferPolicies.md:57). The spec is **Roslyn-agnostic**, so
  changing *how the C# front-end extracts a fact* moves no normative text. (To be
  precise: `spec/` is not implementation-*neutral* — every file pins its source of
  truth to the Python modules, e.g. Diagnostics.md:3-5 → `ownlang/diagnostics.py`.
  But the front-end is not the spec's substrate, so the "zero normative drift"
  conclusion holds for exactly that reason.) **Net normative drift: zero.**
- **The one normative addition** is the new diagnostic OWN050: one row in
  `spec/Diagnostics.md` plus a matching `TITLES` entry in `ownlang/diagnostics.py`.
  The `SemanticModel` work itself adds no code.
- **The "syntax-only" prose must be superseded on build**, or it becomes the lie
  this repo guards against. Each flips to *"type-aware (project-local
  `SemanticModel`), still fact-only and intraprocedural"*:
  - `frontend/roslyn/OwnSharp.Extractor/Program.cs:3` — header "syntax only — no
    compilation, no references".
  - `Program.cs:117-118` — "syntax-only heuristic — no semantic model" (disposable
    type matching; becomes symbol-based when P-005's increment lands).
  - `Program.cs:293` — "ownership transfer is ambiguous syntactically" (soften:
    resolvable via project-local binding where available, still conservative).
  - `OwnSharp.Extractor.csproj:24` — "Syntax-only Roslyn… no compilation/references".
  - `frontend/roslyn/README.md:13` — "Syntax-only (no compilation, no references)".
  - `frontend/roslyn/README.md:73-75` — **removes** the non-goal "semantic event
    resolution" (P-014 delivers exactly that); the "one checker, not two" line
    (README:16) stays true.
  - `docs/howto-visual-studio.md:153-155` — drop "syntax-only"; keep the
    no-interprocedural / no-async / honest-skip sentences verbatim.
  - `README.md:142` (Russian) — the `(frontend/roslyn/, syntax-only)` tag.
  - `docs/proposals/P-001-csharp-extractor.md:12-13` and `:34` — the "C#,
    syntax-only" / "syntactic/local pattern extractor" tags; cross-reference P-014
    as the successor increment.
  - **`docs/ROADMAP.md:37-40`** — the load-bearing one: *"The frontend's job is not
    to 'understand C#' (SemanticModel hides async, generics, LINQ…)"*. This is not
    a literal "syntax-only" string (a grep-and-replace would miss it) and is the
    single most direct philosophical contradiction. Reword by hand to: *"uses a
    project-local `SemanticModel` for binding/type resolution — not whole-language
    understanding (still no async/generics/LINQ/whole-program reasoning)."*
- **It fulfils the ROADMAP philosophy, not contradicts it.** "The frontend's job
  is to extract facts" still holds — we resolve a type to get *one fact* right.
  And the unresolved-fallback *is* "honestly skipping beats confidently lying".
  The "deliberately does NOT touch yet" list (ROADMAP.md:44-48: async, generics,
  LINQ, closures, interprocedural, whole-program…) is untouched — P-014 adds
  binding, not any of those.

## Resolved decisions

- **Tier A reference set.** Framework assemblies via the extractor runtime's
  `TRUSTED_PLATFORM_ASSEMBLIES` (zero-config); **one** `CSharpCompilation` over all
  input trees (cross-project resolution for free — no project-to-project refs, no
  MSBuild); do not chase the target's exact TFM (WPF/DevExpress stay unresolved →
  fallback / Tier B). Killing the numeric FPs needs no references at all (symbol
  *kind* comes from the declaration); the framework set only promotes BCL events
  (`PropertyChanged`/`CollectionChanged`) from "unresolved" to a clean fact.
- **Interim behaviour.** No tightened-but-still-lying heuristic. Ship a
  default-**off** gate on the event-subscription rule now (disposable/pool stay
  on); Tier A graduates the default off→on. This gate is the *first instance* of a
  general "select which checks run" surface — see Open questions Q2.
- **Diagnostic code.** **OWN050**, severity `warning`, emitted via the
  filter-bypassing `_di_findings`-style path (not the `ERROR`-only `check_facts`
  pipeline).

## Open questions

1. **Compilation scoping in a large monorepo.** The default is one compilation
   over everything passed in. In a monorepo of many projects where the user wants
   to analyse *one*, we need a way to scope it — e.g. accept a `.csproj`/`.sln`
   filter, a per-project compilation mode, or path-based scoping. **Deferred — not
   built in the first cut**, recorded here so the one-compilation default is a
   conscious choice, not a ceiling.
2. **General check-selection / configuration surface.** The interim gate-off is a
   special case of a broader need: a way to enable/disable check *categories*
   (subscription / disposable / pool / local-disposable / …) and set their
   severities — ideally a linter-style **config file** (`.ownrc` / `own.toml`, à la
   `ruff.toml` / `.editorconfig`) rather than an ever-growing flag list. This is
   large enough to warrant **its own proposal (candidate P-015)**; P-014 ships only
   the single `--event-leaks` gate as instance #1 and forward-references it.
3. **Tier B mechanism / default.** `MSBuildWorkspace` (robust, needs SDK +
   restore, heavier) vs `bin/**/*.dll` `MetadataReference`s (lighter, needs a prior
   build). Leaning **bin-DLL `MetadataReference`** as the opt-in default
   (CI-friendly, no SDK coupling — relevant given P-001's "sandbox has no local SDK"
   note), with `MSBuildWorkspace` as the zero-config-from-`.csproj` alternative.
4. **`[OwnIgnore("reason")]` interplay.** Does a suppressed member also suppress
   its OWN050 "unchecked" note, or is "unchecked" orthogonal to "ignored"?
5. **Performance / model shift.** The per-file scan becomes a single per-run
   compilation (symbols must resolve across files). Cache it; acceptable for
   CI/local, but it is a real architecture change to the extractor's loop
   (Program.cs:131-155), not a comment edit.
