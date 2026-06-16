# P-014 — Semantic resolution for the C# extractor

- **Status:** draft (P0 — the extractor is currently unusable on real code)
- **Depends on:** [P-001](P-001-csharp-extractor.md) (the seam this deepens — it
  stays intact), [P-004](P-004-wpf-lifetime-profile.md) (consumes the cleaned
  signal), `spec/OwnCore.md` / `spec/Diagnostics.md` (the fact vocabulary and the
  one new informational code). Strategy hub: [`docs/ROADMAP.md`](../ROADMAP.md).

## Motivation

Run the v0 extractor on a real WPF/desktop solution and it produces a *wall* of
false positives. Two distinct failures, both predicted by our own docs:

1. **It matches arithmetic as event subscriptions.** Syntax-only Roslyn cannot
   tell `event += handler` from `decimal += decimal`. So `sum += value`,
   `startIndex += batchSize`, `total += p.Cost.Value` all become "event
   subscribed but never unsubscribed". On a real codebase this is the *majority*
   of the noise — pure arithmetic flagged as leaks.
2. **It can't see external types.** `grid.View.CellValueChanged += …` on a
   DevExpress control, `Closing += Window_Closing` on a WPF `Window` — the
   declaring type lives in an assembly the syntax pass never opened, so the
   extractor guesses, and guesses "leak".

This is exactly the `event += without -=` cell the `ROADMAP.md` reality-matrix
tags **⚠️ heuristic / false-positive-prone**, and exactly the *"confidently
wrong"* tooling the philosophy section says to avoid (*"honestly skipping beats
confidently lying; the market for confident-but-wrong tooling is already
saturated"*). The cause is structural: the `event +=` fact is **type-dependent**,
and v0 is **type-free**. No amount of syntactic cleverness closes that gap — the
only real fix is to let the extractor *see types*.

## Scope

Build the type-dependent facts from a Roslyn **`SemanticModel`** instead of raw
syntax. Concretely, `lhs += rhs` becomes a subscription fact **iff** the model
resolves `lhs` to an event (`IEventSymbol`) or a delegate-typed member —
otherwise it is not emitted at all. Three tiers, in cost order:

- **Tier A — project-local compilation (default, no third-party refs).** Build a
  `CSharpCompilation` over the **project's own source files** plus the framework
  reference for the target TFM — *nothing else*. This already resolves locals,
  fields, in-project types and primitives, so:
  - `sum += value` → `sum` is `decimal` → not an event → **silent** (cause #1 gone);
  - an in-project `event Foo += h` → `IEventSymbol` → real subscription fact;
  - a DevExpress `grid.CellValueChanged += h` → declaring type unresolved →
    handled by the fallback below.
  We **never reference or parse DevExpress (or any third-party) source.** Their
  types simply stay unresolved, and unresolved is not "leak".
- **Tier B — full references (opt-in flag).** When the user *wants* external
  events checked, resolve the project's real references — either via
  **`MSBuildWorkspace`** (open the `.csproj`/`.sln`; the build system resolves
  references; this is the principled version of "load all the target's
  dependencies", with no fake project) or via **`MetadataReference`** over the
  target's already-built `bin/**/*.dll`. Roslyn reads assembly **metadata**
  (public types and events) directly — **no source, no decompiler.**
- **Unresolved fallback (first-class, honest).** When a symbol cannot be resolved
  (an error type), the extractor MUST NOT emit a leak. It emits a distinct
  *informational* diagnostic, in our voice:

  ```text
  OWN05x: cannot verify 'grid.View.CellValueChanged' — its declaring type is an
  unresolved reference (build the project or pass references); leakage analysis
  skipped
  ```

  It is not a leak and it is not "definitely fine" — it is *unchecked*, and we
  say exactly that. Low/informational severity, counted separately from findings,
  never fails a build.

## Non-goals

- **A full semantic C# frontend.** We resolve only what a *specific fact* needs
  (the type of a `+=` LHS, the type of a disposed field). No whole-program
  dataflow, no `async`/generics/LINQ inference beyond that. Still **narrow, still
  intraprocedural, still fact-only** — `SemanticModel` is a sharper chisel, not a
  new mandate to "understand C#".
- **Parsing third-party source, or a decompiler.** Tier B reads compiled
  metadata; that is the entire external-reference story. If it isn't in metadata,
  it's unresolved → the fallback fires.
- **Deciding whether a *resolved* event subscription is actually a leak.** That
  lifetime judgment (is the owner long-lived? is it a `Window` whose `-=` is
  moot?) stays **P-004**. P-014 removes the *gross* noise (arithmetic, unresolved
  externals) so P-004's heuristic operates on real subscriptions only — it does
  not pretend to settle the lifetime question itself.
- **Requiring a green build for Tier A.** The compilation degrades gracefully:
  partial resolution still types the locals/fields we need.

## Sketch

```text
                         ┌─ lhs resolves to event/delegate ─→ acquire(Subscription) fact
*.cs ─[CSharpCompilation ┤
      + SemanticModel]   ├─ lhs resolves to a value type   ─→ (silent: not a subscription)
                         └─ lhs unresolved (error type)     ─→ OWN05x "leakage analysis skipped"
```

Tier A needs only the project's sources; Tier B adds references (workspace or
`bin` DLLs). The OwnIR seam is unchanged downstream: resolved subscriptions still
emit the same `acquire`/`release` facts P-001/P-004 already define, the Python
core still produces `OWN001`/`OWN014`, and the bridge still maps verdicts to the
C# line. **Environment note:** like all extractor work, this is `dotnet`-only and
CI-validated (the sandbox has no local SDK); Tier B's workspace path is heavier
in CI than Tier A.

## Relationship to the spec & docs (avoiding drift)

The whole point of `spec/` vs `docs/proposals/` is that aspirational docs must
not lie about the code. So, explicitly:

- **Normative `spec/` is untouched.** `spec/` defines the OwnIR fact vocabulary
  and the core's semantics; it says *nothing* about the extractor's internals
  (verified — no `spec/` file mentions Roslyn, syntax, compilation or
  references). P-014 changes **frontend internals behind the existing OwnIR
  seam**: same facts in, same `OWN001`/`OWN014` out, core (`ownlang/`) unchanged.
  Net normative drift: **zero**.
- **The OwnIR contract stays additive.** The new "unchecked" output is an
  additive, optional channel (a separate `unchecked: […]` list or a
  `resource:"unresolved"` record an older core ignores) — **no `ownir_version`
  bump**, consistent with the P-013 discipline. The one genuinely new artifact is
  an informational diagnostic code, which lands in `spec/Diagnostics.md` *when
  built* (spec follows code, not before).
- **The prose that says "syntax-only" must be superseded on build, or it becomes
  the lie this repo guards against.** Those statements live in: `P-001` (Scope /
  Sketch "Environment note" / it being "a syntactic/local pattern extractor"),
  `frontend/roslyn/README.md` ("Syntax-only (no compilation, no references)"),
  the `Program.cs` header, `docs/howto-visual-studio.md` (the "syntax-only"
  caveat), the top-level `README.md`, and `ROADMAP.md`. When P-014 ships, each
  flips to *"type-aware (project-local `SemanticModel`), still fact-only and
  intraprocedural"*.
- **It does not contradict the ROADMAP philosophy — it fulfils it.** *"The
  frontend's job is not to understand C# … its job is to extract facts"* still
  holds: we resolve a type to get **one fact** right, not to model the language.
  And *"honestly skipping beats confidently lying"* is precisely the
  unresolved-fallback. The `ROADMAP.md` "what the frontend deliberately does NOT
  touch yet" list shrinks by one carefully-scoped item (type of a `+=` LHS), with
  the reasoning recorded here.
- **P-001 / P-004 boundaries.** P-014 *supersedes P-001's syntax-only
  constraint* but not its seam or OwnIR contract (those it keeps). P-004 is
  unblocked, not replaced: it still owns the long-lived-owner lifetime call.

## Open questions

1. **The unresolved diagnostic.** A new informational code (e.g. `OWN050`, exact
   number reserved against `ownlang/diagnostics.py` at build time) — and does it
   need a third severity *note* level below `WARNING`, or do we render it as a
   non-`OWN001` `WARNING`? How does it interact with `--severity`?
2. **Tier A reference set.** Just the framework reference for the TFM, or also
   project-to-project references (cheap and accurate via a workspace)?
3. **Tier B mechanism / default.** `MSBuildWorkspace` (robust, needs restore +
   matching SDK) vs `bin/**/*.dll` `MetadataReference`s (lighter, needs a prior
   build) — which is the opt-in default?
4. **Interim behaviour.** Until Tier A lands, do we **gate the `event +=` rule
   off by default** (honest silence) rather than ship a tightened-but-still-lying
   syntactic heuristic? (Leaning gate, per "no half-measures".)
5. **Performance / model shift.** The per-file scan becomes a per-project
   compilation (symbols must resolve across files). Cache one compilation per
   project; acceptable for CI/local, but it is a real architecture change to the
   extractor's loop.
6. **`[OwnIgnore("reason")]`** interplay with unresolved notes — does a suppressed
   member also suppress its "unchecked" note?
