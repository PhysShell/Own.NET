# P-017 — Multi-stack frontends (OwnTS / OwnJVM: OwnJava + OwnKotlin)

- **Status:** draft — forward-looking; **no code commitment.** Records the
  decided *shape* for taking the one-core/OwnIR-seam architecture beyond .NET, so
  the decision does not evaporate. Nothing here ships before the .NET surface is a
  "tasty alpha" and a real cross-stack bug pulls it off the shelf.
- **Depends on:** `spec/OwnCore.md`, `spec/Lifetimes.md` (the fact vocabulary the
  core checks), [P-001](P-001-csharp-extractor.md) (the proven Roslyn → OwnIR →
  core seam this generalises), [P-014](P-014-semantic-resolution.md) (type-aware
  binding — the lever that separates the two TS confidence tiers).

## Motivation

The core (`ownlang/`) is already language-neutral by construction: it checks
**OwnIR facts** (`acquire` / `borrow` / `release` / `use` / `escapes` / `owner`),
not C#. [P-001](P-001-csharp-extractor.md) proved the seam end-to-end —
`*.cs → Roslyn extractor → facts.ownir.json → Python core → OWN001/OWN014`. The C#
frontend never re-implements the checker; it only extracts facts.

If that is real, then the *same* core should find the *same* bug shapes in other
ecosystems, because the load-bearing bugs are not C#-specific:

```
useEffect(() => { window.addEventListener("resize", onResize); }, []);
// no return () => window.removeEventListener("resize", onResize)   → OWN001

const sub = observable.subscribe(handle);   // no sub.unsubscribe()  → OWN001
const id  = setInterval(tick, 1000);        // no clearInterval(id)  → OWN001

publisher.addListener(this::onChanged);     // Java: no removeListener → OWN001
InputStream s = new FileInputStream(path);  // Java: no close()        → OWN001
val job = scope.launch { ... }              // Kotlin: no job.cancel()  → OWN001
```

Each of these is the same `acquire` with no `release` on some path — exactly
`OWN001`, plus a `[resource: …]` kind tag. The bet of this proposal is that the
**second and third frontends cost a fact extractor, not a second checker** — and
proving that is the strongest possible evidence that "one core, OwnIR is the seam"
was the right spine, not just .NET-shaped luck.

This is the platform-agnostic-core claim made falsifiable. We resist the
soul-eating version of it just as hard as everywhere else (see Non-goals).

## The decision in two sentences

> **JS/TS:** one frontend *family*, not two products. The bug model is identical
> across `.js/.jsx/.ts/.tsx`; only the available **type information** differs, so
> the same extractor runs in two confidence tiers.
>
> **Java/Kotlin:** *split the frontends* (the source-level tooling and language
> are genuinely different), but *unify the rules* under one shared **OwnJVM**
> profile (the JVM lifecycle/resource model is shared).

The failure mode this refuses is breeding a brand per language × framework
(`OwnJS`, `OwnTS`, `OwnJava`, `OwnKotlin`, `OwnAndroid`, `OwnSpring`, `OwnReact`,
`OwnVue`, …) — "that is not a product line, it is a census." The fix is to
separate two axes that the naive layout conflates:

- **Language frontend** (what parses source & emits OwnIR): `OwnTS`, `OwnJava`, `OwnKotlin`.
- **Platform profile** (what supplies the lifetime/resource facts a domain needs):
  `OwnJVM`, `OwnAndroid`, `OwnReact`, `OwnSpring`.
- **Core** (what checks OwnIR): the existing `ownlang/` engine + OwnIR.

A profile is data fed *to* the core (lifetime regions, acquire/release pairs for a
domain), exactly as WPF already is for .NET — "WPF is the first configured
profile, not the identity." Profiles cross language frontends freely: `OwnReact`
is consumed by `OwnTS`; `OwnJVM` by both `OwnJava` and `OwnKotlin`.

## The matrix

| Stack | Product surface | Extractor / tooling | Shared profile |
|-------|-----------------|---------------------|----------------|
| C#    | **Own.NET**     | Roslyn analyzer/extractor (built, P-001) | .NET resources / lifetimes (WPF, DI, pool) |
| JS/TS | **OwnTS**       | ESLint plugin + TypeScript Compiler API   | Web / React effects |
| Java  | **OwnJava**     | Error Prone / JDT / Spoon                  | **OwnJVM** |
| Kotlin| **OwnKotlin**   | Detekt / KSP / K2 (later)                  | **OwnJVM** + Android |

Three planes, named once each:

```
Language frontend:   OwnTS        OwnJava      OwnKotlin       (+ OwnSharp/Roslyn, built)
Platform profile:    OwnReact     OwnJVM       OwnAndroid  OwnSpring
Core:                ownlang/  +  OwnIR        (one checker, one fact vocabulary)
```

> Naming note. The originating design comment also floated `Owen`/`OwenTS` and an
> `OWENTS00x` rule prefix. This proposal standardises on the existing **Own** brand
> (`OwnLang`/`OwnIR`/`OwnSharp` → `OwnTS`, rule prefix `OWNTS00x`) for consistency;
> the `Owen*` spelling is the same thing under a different skin.

---

## JS/TS — one frontend, two confidence tiers (OwnTS)

JS and TS share too much at the ecosystem level to be two products: React, Vue,
Angular, RxJS, DOM listeners, timers, `AbortController`, `Promise`/`fetch`,
`EventEmitter` — and the resource/lifetime bugs are *identical* across
`.js/.jsx/.ts/.tsx`. Splitting them would be the artificial multiplication of
entities the project exists to refuse.

What genuinely differs is **type information**, and that maps cleanly onto the
project's existing precision discipline (`OWN050` when a type can't be resolved;
"honestly skip beats confidently lie"):

- **TypeScript mode** (`.ts/.tsx`, or `.js` with `checkJs`/JSDoc): type-aware via
  the **TypeScript Compiler API** / `typescript-eslint` `parserServices`. We can
  tell an `Observable` from a look-alike `.subscribe`, resolve imports, type the
  source/handler/subscription, and build precise OwnIR. → **high-confidence
  diagnostics (hard error).**
- **JavaScript mode** (plain `.js/.jsx`): syntax + JSDoc + best-effort types.
  More heuristic, more *warnings* than hard errors unless JSDoc/`checkJs`/types lift
  the confidence. → **heuristic diagnostics.**

Same product, same OwnIR, same core — different `severity`/confidence tier on the
emitted diagnostic, decided by how much the source told us. This is the same
"definite vs maybe" split the core already makes (`spec/Diagnostics.md`), now keyed
on frontend type-resolution depth.

### Distribution & rule set

Ship as an **ESLint plugin** (`eslint-plugin-own`) — the cheapest distribution
surface in this ecosystem (`npm install`, drop into an existing config):

| Rule | Pattern | Core verdict |
|------|---------|--------------|
| `OWNTS001` | `useEffect` adds a listener with no cleanup `return` | `OWN001` |
| `OWNTS002` | `setInterval` / `setTimeout` with no `clear*` | `OWN001` |
| `OWNTS003` | `subscribe()` result never `unsubscribe`d | `OWN001` |
| `OWNTS004` | `AbortController` created but never `abort()`ed | `OWN001` |
| `OWNTS005` | unstable dependency re-triggers an external effect | (effect/region — see P-020) |

The `useEffect`/React rows above are the authoring surface; the deeper **`Own.React`
effect profile** (the `EFF001–005` catalog, the effect-storm analysis, and the
honest Cloudflare framing) is specified in
[P-020](P-020-ownts-react-effects.md). `OWNTS003/004` and `EFF003/004` are the same
cleanup semantics — P-020 is the canonical home; the ESLint rules reference it.

```
eslint-plugin-own        ← authoring rules for JS/TS (the user-facing surface)
owents-extract           ← TypeScript Compiler API → OwnIR (the fact extractor)
ownlang/ (core)          ← OwnIR → diagnostics            (unchanged)
```

The `OWNTS001` React `useEffect`-cleanup case is the recommended **marketing
spike**: a 10-line bug everyone recognises, a "request storm / Cloudflare-style"
story that sells itself, and the easiest plugin to distribute. It is a spike, not
a frontend — one rule, one tier, end-to-end, before any breadth.

---

## Java & Kotlin — split frontends, one OwnJVM profile

Java and Kotlin live on the JVM and share a lifecycle/resource model, but their
**source-level tooling and language surface are different enough that one
extractor would lie about one of them.** So: two extractors, one profile.

### Shared model → the OwnJVM profile

`OwnJVM` supplies the acquire/release pairs and lifetime regions common to the
platform — fed to the core exactly like WPF's profile is for .NET:

```
AutoCloseable / close()          (≈ IDisposable / Dispose — the direct analog)
listener add / remove
RxJava Disposable
ExecutorService.shutdown()
ThreadLocal.remove()
Spring DI lifetimes              → OwnSpring
Android Activity/Fragment/View   → OwnAndroid
coroutines / jobs / scopes       (Kotlin)
```

`AutoCloseable ≈ IDisposable` and "listener leak ≈ event leak" are why the
Java/Kotlin spike is the *strongest* platform-agnostic-core proof: it is closest to
the subscription/lifetime/resource model the core already speaks.

### OwnJava frontend

Java facts come from the type-aware JVM toolchain. Candidate hooks (pick one for
the spike, don't build all): **javac plugin / annotation processor**, **Error
Prone plugin**, or a **JDT / Spoon** extractor.

```java
publisher.addListener(this::onChanged);          // no removeListener → OWN001
InputStream s = new FileInputStream(path);        // no close()        → OWN001
```

Annotations are the natural escape-hatch / contract surface (mirrors the `.NET`
`[OwnIgnore]` and the core's `consume`/`borrow` contracts):
`@OwnResource`, `@Consumes`, `@Borrowed`, `@NoEscape`, `@Lifetime("Application")`.

### OwnKotlin frontend

Kotlin only *looks* like Java until you open real code: extension functions,
properties over get/set, lambda syntax, scope functions (`use`/`also`/`apply`/
`let`/`run`), `suspend`/coroutines, `Flow.collect`, `lifecycleScope`/
`viewModelScope`, delegates, nullable/`inline`/`value` classes. It needs **its own
hooks**, not a Java extractor in a wig:

```kotlin
publisher.addListener { onChanged() }            // no removeListener → OWN001
val job = scope.launch { ... }                   // no job.cancel()   → OWN001
viewLifecycleOwner.lifecycleScope.launch {       // Android lifetime case
    flow.collect { render(it) }
}
```

Tooling, easiest → deepest (and the order to attempt them):

- **Detekt rule** — simplest, lint-style; the right first slice.
- **KSP** — good for reading annotations and generating metadata/specs; weaker at
  method-body control-flow ("forgot the cleanup *here*").
- **Kotlin compiler plugin / K2** — deepest analysis; most power, most pain — *do
  not lead with this if you would like to keep your sanity.*
- **IntelliJ PSI** — for IDE/plugin-style analysis later.

Use Detekt for lint rules first; reach for KSP when specs/annotations matter; defer
the compiler plugin.

---

## Scope (what a first increment actually is)

Bug-driven, smallest-first, mirroring how P-001 landed (one pattern end-to-end
before breadth):

1. **OwnTS spike** — `OWNTS001` (`useEffect` listener without cleanup) only, TS
   mode, `*.tsx → owents-extract → facts.ownir.json → core → OWN001` at the JSX
   line. Framed as a marketing/PR spike.
2. **OwnJVM research spike** — one listener leak (`addListener` without
   `removeListener`) through **either** OwnJava **or** OwnKotlin → **the same
   `facts.ownir.json` shape** → the **unmodified** core → `OWN001`. The deliverable
   is the proof that the core is reused verbatim, not a frontend.

Everything is **OwnIR facts in the spec's vocabulary** — no new core code is in
scope for either spike; if a spike needs a core change, that is a finding, not a
silent edit.

## Non-goals (the most important section)

- **No second checker, in any language.** Every frontend produces/consumes OwnIR;
  the Python core stays the single source of truth. A JS/Java/Kotlin re-impl of the
  analysis is the exact drift this project exists to refuse.
- **No whole-language frontends.** Not a TypeScript type-checker, not a Java/Kotlin
  semantic engine. Extract *facts* (acquire/borrow/use/release/escape/control-flow),
  the same narrow-frontend discipline as the C# side (async/generics/LINQ-equivalents
  stay out until a real bug needs them).
- **No brand-per-framework.** `OwnVue`/`OwnAngular`/`OwnRxJava`/… are *profiles*
  under an existing frontend if they ever exist, never products.
- **No new stack before .NET is a tasty alpha** and a real cross-stack bug is in
  hand. "We supported 40% of three more languages and found zero bugs" is the
  precise failure we are avoiding.
- **Honest-skip over confident-lie** carries over: JS mode emits warnings, not hard
  errors, when types aren't there; an unsupported Kotlin coroutine shape is skipped
  and flagged, not guessed.

## Sketch / architecture (the seam, reused)

Every stack is the P-001 seam with a different front half:

```
*.ts/.tsx --[owents-extract: TS Compiler API]--> facts.ownir.json --\
*.java     --[OwnJava: ErrorProne/JDT/Spoon ]--> facts.ownir.json ---+--> [ownlang core] --> OWN0xx
*.kt       --[OwnKotlin: Detekt/KSP/K2       ]--> facts.ownir.json --/        (+ [resource:] / [profile:])
```

The OwnIR JSON is the contract (`OWNIR_VERSION`, currently `0`; a mismatched
extractor/core pair fails loudly at load — same guarantee P-001 relies on). A new
frontend that wants a resource kind the schema doesn't model yet rides the next
OwnIR-schema bump (see the deferred `subscriptions → resources` rename in
[consolidation-and-positioning.md](../notes/consolidation-and-positioning.md)),
rather than minting a private format.

**Environment note** (same constraint as P-001's dotnet): this sandbox has no
Node/JVM/Kotlin toolchain locally either. So the testable-now half of any spike is
the **Python fact-ingest against hand-written `facts.ownir.json` fixtures**; the
actual extractor (ESLint/javac/Detekt artifact) is CI-validated, exactly like the
Roslyn extractor and the `dotnet-golden` job. Land one pattern's fixtures first.

## Strategy (sequencing, not a schedule)

1. **.NET → tasty alpha.** Prove value on real OSS C# repos first (the standing
   "prove value, don't reshape form" priority from the positioning note). No second
   stack competes with this.
2. **OwnTS = marketing spike.** Small PR: React `useEffect` cleanup (`OWNTS001`).
   Big recognisable audience, cheap distribution.
3. **OwnJava/OwnKotlin = research spike.** Listener leak → the *same* OwnIR → the
   *same* core. The point is the platform-agnostic-core proof, not Java coverage.

## Open questions

1. **Which JS/TS confidence tiers are hard error vs warning by default**, and how
   `checkJs`/JSDoc promotes a `.js` file from heuristic to high-confidence — the
   exact mapping onto the existing definite/maybe split (`spec/Diagnostics.md`).
2. **OwnJava first hook:** Error Prone (easiest CI story) vs JDT/Spoon (richer
   standalone extraction) for the listener-leak spike.
3. **OwnKotlin first hook:** Detekt (simplest) almost certainly for the spike —
   confirm KSP isn't needed even for v0, and keep K2/compiler-plugin explicitly off
   the first slice.
4. **`[profile: …]` label.** This proposal assumes the deferred profile-label work
   (consolidation backlog item) lands so `OwnReact`/`OwnJVM`/`OwnAndroid` findings
   are attributable — is that a prerequisite for OwnTS, or can the spike ship with
   just `[resource: …]` as the .NET side does today?
5. **OwnIR coverage gaps.** Does any TS/JVM resource shape (e.g. `AbortController`,
   coroutine `Job`, `Flow.collect` cancellation) need a fact the current schema
   can't express? Each such gap is a concrete OwnIR-v1 input, not a blocker to note
   and route through the schema bump.
