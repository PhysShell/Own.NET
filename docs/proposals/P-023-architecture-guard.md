# P-023 — Architecture guard (`Own.Arch`)

- **Status:** draft — design accepted in discussion; implementation not started.
- **Depends on:** [P-013](P-013-distribution-surface.md) (CI Action / dotnet tool
  surface — the guard rides the same delivery rails) and
  [P-015](P-015-configuration-surface.md) (severity policy vocabulary). Phase 2
  reuses the Roslyn extraction stack from
  [P-001](P-001-csharp-extractor.md). Reporting reuses the SARIF export design
  from [`docs/notes/sarif-export.md`](../notes/sarif-export.md).

## Motivation

Architecture drift is the gap between the intended dependency structure of a
codebase and what the code actually does. In a living solution it accumulates
one "temporary" reference at a time: a ViewModel reaches into a SQL repository,
a Domain project quietly picks up a DevExpress package, and six months later the
layer diagram is fiction.

Every attempt to fix this with a "detect everything bad" platform dies the same
way:

```text
turn on the rules
get 800 violations on day one
downgrade everything to warnings
nobody reads warnings
initiative dead in a month
```

Own.Arch deliberately does **not** build a SOLID detector, a documentation-sync
checker, or a runtime-telemetry differ. The value proposition is one sentence:

> **Own.Arch fails a PR if and only if it introduces a *new* architectural
> dependency violation. Existing debt is baselined, ratcheted, and reported —
> never a build blocker.**

Three artefacts, one direction of truth:

```text
intent model:   architecture.rules.yaml        (hand-written, reviewed)
actual model:   dependency graph extracted from .sln/.csproj/assemblies
drift:          actual − allowed  → verdicts, gated against a baseline
```

Diagrams, reports, and tests are all *generated from* the intent model. There is
no second place where the intended architecture lives — no hand-maintained C4
model competing with the rules for source-of-truth status.

## Scope

### MVP: project-level dependency guard

The MVP reads the solution's project graph — no compilation, no Roslyn — and
gates on it:

| Code | Finding | Default severity | Confidence |
|------|---------|------------------|------------|
| `ARCH001` | `ProjectReference` from layer X to layer Y not in the allowed graph | error (if not baselined) | deterministic — it is an edge in a graph |
| `ARCH002` | Forbidden `PackageReference` / `packages.config` entry in a layer (e.g. SQL provider in Domain) | error (if not baselined) | deterministic for direct references |
| `ARCH003` | Project matches no layer pattern, or matches more than one | error, never baselinable | configuration defect — default deny |
| `ARCH030` | Allowed edge that no project actually uses (reverse drift: the intent model is rotting) | info / report only | deterministic |

`ARCH003` is the discipline rule: an unmapped project is a hole in the guard,
so the mapping is forced to stay total and unambiguous. The cheapest bypass —
name the project `Broker.Utils` and reference whatever you like — must not
exist.

`ARCH030` is what distinguishes a guard from yet another linter: the intent
model decays too, and "declared but unused dependency" is the only automatic
signal of that decay.

### Phase 2: type-level facts

After the project-level guard has survived contact with a real solution:

| Code | Finding | Default severity | Confidence |
|------|---------|------------------|------------|
| `ARCH010` | Type in layer X depends on a type in layer Y outside the allowed graph (catches violations invisible at project granularity) | error (if not baselined) | deterministic on compiled IL / semantic model |
| `ARCH011` | Forbidden API used in a layer (`System.Windows.MessageBox` in Domain, `SqlConnection` in Application, …) | error (if not baselined) | deterministic |
| `ARCH012` | Namespace-level dependency cycle | warning at first, error once trusted | deterministic |

Note: there is deliberately no *project*-level cycle rule — MSBuild already
refuses to build circular `ProjectReference` graphs. Cycle detection only means
something at namespace/type granularity, which is why it lives in phase 2.

### Phase 3: heuristic signals (never build blockers at introduction)

| Code | Finding | Default severity | Confidence |
|------|---------|------------------|------------|
| `ARCH020` | Type has too many distinct dependencies (fan-out / god-class signal) | warning | heuristic |
| `ARCH021` | Type in layer X mixes APIs from layers Y and Z (SRP *symptom*, not SRP verdict) | warning | heuristic |
| `ARCH022` | Interface with too many members (ISP symptom) | warning | heuristic |
| `ARCH040` | Duplicated code blocks / dead public API | report only | noisy — see Non-goals |

The tiering is the honest answer to "can you detect SOLID?": no. You can
detect **dependency facts** (deterministic — tier 1), **structural symptoms**
(heuristic — tier 2), and **quality smells** (noisy — tier 3). Selling tier 3
as tier 1 is how analyzers lose trust. Dead-code detection in particular, in a
.NET codebase with reflection, DI containers, serialization, and XAML bindings,
false-positives constantly; failing a build on it is out of the question.

## Non-goals

- **No C4 model as source of truth.** C4/PlantUML/Mermaid diagrams are a
  *rendering* of `architecture.rules.yaml`, generated in CI, never
  hand-edited, never diffed as images. A hand-maintained architecture model
  plus separate rules is two parrots arguing about who is the architect.
- **No runtime telemetry diffing** (OpenTelemetry traces vs. declared
  architecture). Valuable someday; a separate infrastructure project; not here.
- **No dead-code or clone-detection quality gates.** Report-only, forever, or
  until someone proves the false-positive rate on *our* corpus is near zero.
- **No test-coverage or documentation-freshness "drift" checks.** Those are
  quality gates, not architecture; bundling them is how the scope eats the
  tool.
- **No second rule DSL.** No generated ArchUnitNET/NetArchTest test code. One
  intent model (`rules.yaml`), one evaluator that reads it directly. If
  type-level extraction needs a library (Cecil, Roslyn), it is used as an
  *extractor*, not as a rule language.
- **No hard dependency on commercial tooling** (NDepend et al.). Optional
  later evaluation at most.
- **No "SOLID detector" claim.** The rules are SOLID-*inspired*; the README
  should say "dependency and layering guard", nothing grander.

## Sketch

The seam is the same deep-module interface as the rest of Own.NET:

```text
.sln/.csproj/packages.config --[extractor]--> arch-facts.json
                                                    |
architecture.rules.yaml  ----------------------\    |
architecture-baseline.json ---------------------+---+--[core]--> ARCH### verdicts
                                                              --> SARIF + markdown report
                                                              --> (later) Mermaid/C4 diagrams
```

The extractor emits facts; the core owns verdicts — the "one checker" rule
holds. MVP facts are plain XML reads of project files; phase 2 adds an IL or
Roslyn pass emitting type-dependency facts in the same JSON envelope.

### `architecture.rules.yaml` (intent model)

```yaml
layers:
  Presentation:
    matches: ["*.Presentation", "*.Wpf", "*.Client"]
  Application:
    matches: ["*.Application", "*.Services"]
  Domain:
    matches: ["*.Domain", "*.Core"]
  DomainAbstractions:
    matches: ["*.Domain.Abstractions"]
  Infrastructure:
    matches: ["*.Infrastructure", "*.DataAccess"]

# Direct edges only. No transitive closure is implied:
# Presentation -> Application -> Domain does NOT allow Presentation -> Domain.
allowedDependencies:
  Presentation:   [Application, DomainAbstractions]
  Application:    [Domain, DomainAbstractions]
  Infrastructure: [Domain, DomainAbstractions]
  Domain:         [DomainAbstractions]

forbiddenPackages:
  Domain:        [System.Data.SqlClient, Microsoft.Data.SqlClient, DevExpress*, Newtonsoft.Json]
  Application:   [DevExpress*, PresentationFramework]

# Phase 2:
forbiddenApis:
  Domain:        [System.Windows.*, System.Data.*]
  Application:   [System.Windows.MessageBox]
```

Resolution rules, fixed up front:

- A project matching zero or ≥2 layer patterns is `ARCH003` — config error,
  cannot be baselined or suppressed.
- Package checks cover **direct** references only in the MVP.
  `packages.config` is flat, so legacy solutions get full coverage for free;
  SDK-style transitive dependencies need `project.assets.json` parsing and are
  explicitly deferred (recorded limitation, not silent gap).

### `architecture-baseline.json` (the ratchet)

Existing violations are frozen at adoption time; the gate only fires on *new*
ones. This is the load-bearing element — without it the guard is architectural
theatre.

```json
{
  "rulesHash": "sha256:…of architecture.rules.yaml…",
  "violations": [
    {
      "rule": "ARCH001",
      "from": "Broker.Domain",
      "to": "Broker.Infrastructure",
      "fingerprint": "sha256:ab12…",
      "firstSeen": "2026-07-03",
      "reason": "legacy tax calculator; tracked as TECH-482"
    }
  ]
}
```

**Fingerprint policy (the make-or-break detail):**

- `fingerprint = sha256(rule ‖ normalized-from-symbol ‖ normalized-to-symbol)`.
  **No file paths, no line numbers** — a positional fingerprint churns the
  baseline on every refactor; a looser one lets new violations impersonate old
  ones.
- Consequence, accepted deliberately: renaming a symbol makes the old entry
  "fixed" and the new one "new" → FAIL. That is correct behaviour — it forces
  a conscious baseline update in the same PR — but only tolerable if updating
  is one command:

  ```text
  own-arch baseline accept --reason "rename only, no new edge"
  ```

  A mandatory `--reason` is the whole suppression policy; entries without one
  are rejected.
- The file is **canonically sorted, one violation per line**, so concurrent
  PRs merge without conflicts.
- `rulesHash` pins the baseline to the rules version. Tightening a rule
  invalidates the baseline; the same PR that changes the rules regenerates it.
  A stale hash is a build error, not a silent re-interpretation.

**CI decision table:**

| Observation | Verdict |
|---|---|
| known violation still present | OK (counted, reported) |
| known violation gone | GOOD — entry removed (or PR comment nudges removal) |
| new violation | **FAIL** |
| baseline entry count grew without `--reason` entries | **FAIL** (fallback invariant; normally subsumed by "new → FAIL") |
| `rulesHash` mismatch | **FAIL** — regenerate baseline alongside the rules change |

There is no separate "violation changed → REVIEW" state: with symbol-pair
fingerprints, "changed" decomposes into "one gone + one new", and the policy
above already covers both halves.

### Reporter

- **SARIF** as the primary machine output — GitHub code scanning and Azure
  DevOps render it as inline PR annotations for free
  (see [`sarif-export.md`](../notes/sarif-export.md); same format, same
  rails).
- **Markdown summary** for the PR conversation: new violations first, then the
  ratchet status (`baseline: 47 known, −2 this PR`), then `ARCH030` reverse
  drift.
- Violation messages name both endpoints and the rule, and suggest the
  layer-correct alternative:

  ```text
  ARCH001: Broker.Presentation.DeclarationViewModel → Broker.Infrastructure.SqlCustomerRepository
  Presentation may depend on: Application, Domain.Abstractions.
  Fix: call an Application service or a Domain abstraction instead.
  ```

- **Later:** generate Mermaid/PlantUML (optionally via C4 tooling as a pure
  renderer) from `rules.yaml`, and overlay the *actual* graph with drift edges
  highlighted. The intended diagram and the drift diagram come from the same
  two inputs the gate already has — no third model.

## Implementation order

Weeks are calendar-honest, not research-project-honest:

1. **Week 1 — the ratchet works end to end.** `rules.yaml` schema + parser;
   `.sln`/`.csproj`/`packages.config` extractor; `ARCH001`–`ARCH003`
   evaluation; baseline generate/accept/check; CI wiring.
   **Exit criterion: on a real solution, the baseline is frozen and a
   deliberately broken PR goes red.** A green pipeline proves nothing; the red
   PR is the acceptance test.
2. **Week 2 — feedback quality.** SARIF + markdown reporter; `--reason`
   suppression flow; `ARCH030` reverse drift; docs for "my PR went red, what
   now".
3. **Week 3 — type-level facts.** IL/Roslyn dependency extraction feeding
   `ARCH010`–`ARCH012`; forbidden-API list; same baseline mechanics (the
   fingerprint scheme already accommodates type-granularity symbols).
4. **Later, separately justified:** phase-3 heuristics as warnings; diagram
   generation; transitive package closure via `project.assets.json`;
   multi-solution/monorepo layout support.

## Open questions

1. **Where does the evaluator live?** The one-checker rule says the Python core
   owns verdicts (extractor emits `arch-facts.json`, core evaluates). But
   unlike ownership analysis, this checker is a graph-set difference — trivial
   in either language — and a self-contained dotnet tool is easier to adopt in
   C#-only shops. Leaning: follow the house seam (facts → Python core) for
   consistency and shared reporting, but keep the fact schema tool-agnostic so
   a standalone runner remains possible.
2. **Phase-2 extraction: Mono.Cecil over compiled assemblies, or Roslyn over
   source?** Cecil sees what actually ships (including generated code) but
   needs a build first; Roslyn integrates with the P-001 stack and sees
   pre-build. Leaning: Cecil for dependency edges (cheap, whole-assembly),
   Roslyn only if forbidden-API checks need syntax-level precision.
3. **Does `rules.yaml` fold into the P-015 configuration surface,** or stay a
   separate file? Leaning: separate file — it is a reviewed architectural
   artefact with its own change ceremony, not a per-developer knob.
4. **Fingerprint stability at type granularity:** namespace-qualified type
   pairs churn more than project pairs under refactoring. Is `(rule, from-type,
   to-type)` right, or should type-level entries baseline at
   `(rule, from-namespace, to-namespace)` to reduce accept-noise? Needs a trial
   run on a real diff history.
5. **Naming/positioning:** `Own.Arch` as a product family next to `Own.Async` /
   `Own.React`, or a subcommand of the existing CLI? Affects P-013 packaging
   only; the seam is unchanged either way.
