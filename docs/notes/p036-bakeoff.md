# P-036 comparative bakeoff — Infer# / RLC# / CodeQL / CA2000 vs Owen (capability, not speed)

> Status: **research record, complete** (opened and closed 2026-09-17; Owen at
> `70189a3`; results at `docs/evidence/p036-bakeoff/`). Verdict: §8.1
> PREREGISTERED VERDICT **NO-GO** (one commoditised case under the frozen
> global D2); §8.2 METHODOLOGY SENSITIVITY reads the same evidence as
> **SHRINK** to the P-037 guarded-transfer core plus exceptional-exit teardown
> reasoning. Both are reported; neither replaces the other.
> Owner ruling that frames this note (OWNER RULING, verbatim from the task):
> physical-host qualification is **deferred**; the current host is accepted for
> exploratory comparative research and functional capability evaluation, and
> **not** accepted for final performance claims, #263 acceptance, reproducible
> latency/memory baselines, or publication-grade speed comparisons. Nothing
> below reopens that. Every timing in this note is labeled
> `EXPLORATORY ONLY / NON-ADMISSIBLE FOR #263 / NON-PUBLICATION-GRADE /
> UNCONTROLLED SHARED HOST`.
>
> Evidence discipline: every load-bearing statement is tagged
> `REPOSITORY FACT` (read from this tree at `70189a3`), `EXTERNAL SOURCE FACT`
> (a cited external artifact), `MEASURED OBSERVATION` (a tool executed here,
> raw output preserved under `docs/evidence/p036-bakeoff/`), `INFERENCE`,
> `PROPOSED P-036 CAPABILITY` (proposal text, never executed), or
> `OWNER RULING`.

Related: [P-036](../proposals/P-036-interprocedural-semantic-architecture.md),
[P-037](../proposals/P-037-guarded-effect-summaries.md), #278 / #293 / #302 /
#304 / #305 / #306 / #307, [`spec/Inference.md`](../../spec/Inference.md),
[`teardown-predicate-adversarial-audit.md`](teardown-predicate-adversarial-audit.md),
[`oracle.md`](oracle.md), [`corpus-benchmark.md`](corpus-benchmark.md),
[`own278-corpus-diff.md`](own278-corpus-diff.md),
[`research-landscape-2026.md`](research-landscape-2026.md).

Harness: [`scripts/p036_bakeoff.py`](../../scripts/p036_bakeoff.py).
Machine-readable results: [`docs/evidence/p036-bakeoff/`](../evidence/p036-bakeoff/).
New synthetic conformance cases: [`corpus/p036-bakeoff/`](../../corpus/p036-bakeoff/).

---

## Phase 0 — the P-036 decision contract (preregistration)

Written **before** any comparator ran on the corpus below. The only tool runs
that precede this section are the toolchain smoke tests on the pre-existing
three-tool fixture `corpus/fixtures/systemevents-console` (§2.0), which was
designed in July for the oracle, not for this bakeoff.

### 0.1 What P-036 actually commits to (REPOSITORY FACT)

- P-036 (`draft`) proposes a first-class interprocedural layer: OwnIR stays the
  wire seam, an internal OwnHIR, the existing OwnCFG as the local substrate,
  a derived call graph, first-class `MethodSummary` artifacts composed by a
  generic SCC/fixpoint engine, domains = ownership (MOS), obligations,
  progress, regions, tasks; diagnostics carry a proof-DAG-projected witness.
- Its **first production consumer is #304**: summary-backed lifecycle release
  reachability generalizing the landed #293/#302/#306 extractor predicates.
  P-036 §Phase 2 lists eight fixture families; families 1–3 are already caught
  by the landed predicates (regression anchors), **4–8 are the new capability**:
  4 helper that always unsubscribes → clean through summary application;
  5 helper that may unsubscribe → finding/advisory by rule policy;
  6 virtual/external cleanup target → explicit degraded precision;
  7 exceptional exit bypassing cleanup → finding with exceptional path;
  8 runtime-correlated SectorTS scenario (OwnAudit, out of this bakeoff).
- P-037 (`accepted`, frozen design) is the guarded-transfer contract: a single
  fixed bool/null-ness split per (method, disposable parameter), cell selection
  at call sites with constant arguments, two consume routes (selected `must`,
  unanimous `must`), G-T1 precision floor, G-T2 lax refinement. Its §8 rows
  1, 2, 3, 4, 7, 8, 12, 17 are the observable verdict changes.
- The **precision floor** of the whole interprocedural layer is `own-only 0`:
  no rule may fabricate `must`/`fresh`/alias; degradation goes to silence plus
  an advisory (OWN051), never to a guess (`spec/Inference.md` §7, INF-P1).

### 0.2 Landed bounded implementation (the regression floor) (REPOSITORY FACT)

`frontend/roslyn/OwnSharp.Extractor/Program.cs` credits a `-=` (and, since
#302, a timer `.Stop()`) as a release only when: it sits in a teardown context
(`TeardownContextMethods`: exact name-roots `Dispose`/`DisposeAsync`/`OnClosed`/
`OnClosing`/`OnUnloaded`/`OnFormClosed`/`OnFormClosing`, code-wired handlers of
the class's own `Closed`/`Closing`/`Unloaded`/`FormClosed`/`FormClosing`/
`Disposed`, plus the symbol-resolved intra-class call closure), and it is not
parameter-guarded (`IsParamGuardedRelease` incl. the #305 early-return and
else-branch refinements). It is lexical + symbol-based, **argument values are
never consulted** (a helper credited through the closure is credited for all
callers), and **enrollment is assumed from the name-root** (audit attack D).

The Python bridge (`ownlang/ownir.py` + `ownlang/ownership.py`) already has a
context-insensitive MOS: a per-method summary (`transfer ∈ {no, must, may,
unknown}`, `returns ∈ {fresh, aliasOf, aliased, none, unknown}`) solved by an
SCC fixpoint; a conditional release derives `may` (INF-S2) and the caller's
obligation is **untracked** at that call plus OWN051 (INF-A5). The extractor
separately has a transitive `ConsumesParam` walk (a callee that disposes or
forwards to a disposer consumes its parameter), used for the use-after-handoff
release at the call site and for `CallReleasesReceiver` (NLog sink shape).

Owen-current therefore has: intraprocedural path-sensitive ownership over a
CFG (OWN001/002/003/009, exceptional edges for `try`), a context-insensitive
summary layer for disposable parameters/returns, lexical teardown-context
predicates for subscriptions/timers, lifetime tiering (static/injected/self
sources → error/warning/silent), DI captive-dependency graph rules, and an
intraprocedural obligation-protocol core whose **C# extractor is pending**
(`docs/proposals/README.md`: P-025 "extractor pending").

### 0.3 Target questions

```text
TARGET QUESTIONS
Q1  Which P-036-scope defect families does Owen-current catch on real C#
    (before caught, fix silent), and which does it miss?
Q2  Which of those families do Infer#, RLC#, CodeQL, CA2000 catch STOCK,
    which only CONFIGURED, which only with a CUSTOM MODEL or CUSTOM QUERY,
    and which not at all (UNSUPPORTED / NOT_APPLICABLE)?
Q3  On the cases Owen-current misses INSIDE the P-036 scope (guarded-effect
    summaries, enrollment, exceptional exit, delegate/virtual cleanup
    targets, cross-method obligations, loop progress), does any comparator
    already catch them?  Yes → P-036 rebuilds; no → P-036 differentiates.
Q4  For each family, what semantic machinery does each tool bring (CFG, call
    graph, summaries, may/must, guards, constant substitution, lifecycle
    roots, enrollment, heap identity, virtual dispatch, external models,
    exceptional exit), built-in vs user-authored, and what degrades to
    unknown vs silently clean?
Q5  What does each tool's diagnostic actually give a developer (location,
    message, path/call witness, branch explanation, subject identity)?
Q6  What modelling/setup cost does each comparator need to reach the
    families at all?
```

### 0.4 Defect families

```text
DEFECT FAMILIES
F1  Subscription release reachability (the #278 class): a `-=` that exists
    but is flag-guarded / in an uncalled method / in a finalizer / in a
    name-only handler / in the wrong overload; plus the real ScreenToGif and
    SectorTS-reduced shapes; plus the token-returning Subscribe shape.
F2  Timer `Stop()` lifecycle (WPF002 twin of F1): a non-IDisposable timer
    whose only release is `Stop()` in an unproven context.
F3  Interprocedural IDisposable ownership transfer: consume/borrow/forward
    through helpers, use-after-handoff, release through a helper/sink,
    and the P-037 guarded-transfer shapes (flag-guarded helper, early-return
    spelling, wrapper forwarding the flag, negated wrapper, null-guard
    helper, mixed release/forward).
F4  Lifecycle ENROLLMENT vs EFFECT: a perfect teardown nobody runs
    (name-root `Dispose` on a non-IDisposable type; an IDisposable
    subscriber the owner drops).
F5  Exceptional exit bypassing a subscription release inside a teardown.
F6  Release reached only through a delegate/interface target.
F7  Obligation protocol crossing a helper (P-025 / #274).
F8  Loop progress through a helper (#275).
F9  Region/DI lifetime escapes (static source promotion, App-scoped bus,
    singleton captures scoped).
```

Provenance classes used for every case (never mixed into one number):
`1 historical real bug`, `2 existing regression fixture`,
`3 adversarial mutation of a real shape`, `4 synthetic conformance case`
(derived from proposal text before any comparator ran), `5 exploratory new
case`. A case designed after observing a comparator's failure is class 5 and
is marked `post-hoc`.

### 0.5 Comparators

```text
COMPARATORS
Infer#             microsoft/infersharp v1.5 (release tarball, Cilsil translator
                   + Infer v1.1.0-9d469330b6, Pulse); analyses compiled
                   .dll+.pdb; run via run_infersharp.sh.
RLC#               microsoft/global-resource-leaks-codeql @1212a92 (archived
                   2026-06-11, last commit 2023-08-12), paper arXiv:2312.01912
                   (CodeQL 2.11.4); shipped pipeline = infer.ql (spec
                   inference) + RLC.ql + docs/library-annotations.txt, where
                   `readAnnotation/5` is an EXTERNAL predicate the scripts
                   splice in. Executed either unmodified on a period-correct
                   CodeQL bundle (codeql-bundle-20221211) or, if that cannot
                   extract, with a recorded API-rename adapter on 2.27.0.
                   Paper capability, tool capability and executed capability
                   are reported separately.
CodeQL             CodeQL 2.27.0 bundle, codeql/csharp-queries 1.9.3, stock
                   `csharp-security-and-quality.qls`; build-mode none.
                   Any query written for this bakeoff is scored
                   DETECTED_CUSTOM_QUERY, never as stock.
CA2000 / .NET      Microsoft.CodeAnalysis.NetAnalyzers 8.0.9 (shipped in SDK
analyzers          8.0.425): (a) STOCK = CA2000/CA2213/CA1001 enabled at
                   warning, all dataflow options at their defaults;
                   (b) CONFIGURED = same plus interprocedural ContextSensitive,
                   dispose_analysis_kind AllPaths.
                   Secondary: IDisposableAnalyzers 4.0.8 (community, NuGet).
Owen-current       this tree at 70189a3: Roslyn extractor + Python core via
                   scripts/own-check.sh --format sarif --severity warning,
                   WindowsDesktop ref pack on (as oracle.yml does).
Owen-P036-target   P-036 + P-037 text only. PROPOSED CAPABILITY. Never a
                   measured result; reported in its own column.
```

### 0.6 Decision predicates

```text
DECISION PREDICATES
D1  Present differentiation: Owen-current catches at least one whole family
    that no comparator catches STOCK or CONFIGURED, with zero false
    positives on that family's fixes.
D2  Target differentiation: on the P-036-scope cases Owen-current MISSES
    (F3 guarded shapes, F4 enrollment, F5, F6), no comparator catches them
    STOCK or CONFIGURED either. If a comparator does, P-036 is rebuilding
    that part and the case is charged against P-036.
D3  Necessity of the semantic layer: the D2 cases need call-graph /
    summary / guard / enrollment machinery that the landed lexical
    predicates cannot express without another lexical patch — judged from
    the adversarial audit's residual attack list (C, D, E, F) and from what
    the extractor's predicate actually inspects.
D4  Breadth: a P-036 domain (ownership, obligations, progress, regions,
    tasks) counts as evidenced only if the corpus holds at least one class-1
    (historical real bug) case in it AND the bakeoff shows a semantic gap in
    every comparator on it. Domains evidenced only by class-4 cases are
    recorded as "plausible, unevidenced".
D5  Cost signal: a comparator that reaches a D2 case only with per-case
    annotations (RLC# Owning/MustCall, CA2000 exclusions, a bakeoff-written
    CodeQL query) is scored as CUSTOM, which counts for expressiveness but
    not for D2.
D6  Admissibility: every predicate rests on executed results or repository
    facts; paper claims and exploratory timings are excluded from D1–D5.

Mapping (fixed before results):
GO      D1 ∧ D2 ∧ D3 ∧ D4 ≥ 3 domains evidenced.
SHRINK  D1 ∧ D2 ∧ D3 ∧ D4 ∈ {1, 2} domains evidenced (recommend the
        evidenced subset, i.e. #304-first / P-037 core, as the P-036 scope).
NO-GO   ¬D1, or ¬D2 (comparators already cover the target cases STOCK or
        CONFIGURED), or ¬D3.
DECISION NOT YET ADMISSIBLE if the comparators could not be executed on the
        D2 families (UNSUPPORTED/CRASHED across the board) — then report the
        missing evidence instead of a verdict.
```

Anti-goalpost rule: the mapping above and the family list are frozen at this
commit; anything added afterwards is labeled post-hoc in §1.

---

## Phase 1 — the corpus (45 cases, 12 new)

The manifest is `docs/evidence/p036-bakeoff/corpus.json` (written by
`scripts/p036_bakeoff.py --write-manifest`). Per case it records id, family,
provenance class, source path, expected Owen codes, the defect subject, why
the case matters to P-036, the tools declared `NOT_APPLICABLE` by documented
rule scope, and any harness stubs. Counts by family × provenance class
(REPOSITORY FACT):

| family | class 1 real | class 2 fixture | class 3 adversarial | class 4 synthetic | total |
|---|---|---|---|---|---|
| F1 subscription reachability | 4 | 3 | 7 | 0 | 14 |
| F2 timer Stop() | 0 | 0 | 6 | 0 | 6 |
| F3 ownership transfer | 5 | 5 | 0 | 6 | 16 |
| F4 enrollment | 0 | 0 | 0 | 2 | 2 |
| F5 exceptional exit | 0 | 0 | 0 | 1 | 1 |
| F6 delegate/virtual target | 0 | 0 | 0 | 1 | 1 |
| F7 obligation via helper | 0 | 0 | 0 | 1 | 1 |
| F8 loop progress via helper | 0 | 0 | 0 | 1 | 1 |
| F9 region / DI | 0 | 3 | 0 | 0 | 3 |

Notes on honesty of the corpus:

- **No case was written after seeing a comparator result** — for the
  preregistered corpus. The twelve class-4 cases were authored from P-037 §8
  and P-036 §Phase 2 before any comparator touched them (§0). No class-5
  (post-hoc) case existed when the results matrix was read. **Two class-5
  controls were added afterwards** (§1.1), in answer to the owner's hostile
  audit of `c57a919`; they are marked post-hoc in the manifest, excluded from
  every preregistered predicate (§3.4), and read only in §8.4.
- The "historical real bug" class contains SectorTS reductions (heap-proven,
  #278), ScreenToGif (mined, `real-world-mining.md`), ShareX, NLog shapes and
  representative ADO/stream shapes — all *reductions*, not the original
  repositories. Prior full-repository runs (Dapper, Polly, ScreenToGif,
  Newtonsoft; `oracle.md`, `own278-corpus-diff.md`) are cited as REPOSITORY
  FACTS where relevant and were **not** re-run here.
- Every comparator sees the **same input** as Owen: one project per file
  (`Case.csproj`, `net8.0` or `net8.0-windows` when the file uses
  `System.Windows*`, NuGet `System.Data.SqlClient` / `Microsoft.Win32.SystemEvents`
  where used), plus a harness stub file for two undeclared fixture types
  (`IEventBus`, and a global using for the DI abstractions package). The
  stubs are identical for all tools and are recorded in the manifest.
- Two input-shape adapters, applied identically to every tool and recorded in
  the harness: (a) the three WPF partial-class fixtures (`F1-11`, `F1-12`,
  `F9-03`) get the XAML-generated half of their class as an empty
  `InitializeComponent()` stub, so the build-requiring comparators can
  compile them; (b) `F1-09` is left exactly as the fixture intends — its
  `Window` base is deliberately unresolvable (the case pins Owen's
  unresolved-lifecycle-event path) — so for the build-requiring comparators
  it is `UNSUPPORTED` by construction, not a measurement.
- ArrayPool/MemoryPool cases (POOL/OWN025) are deliberately **excluded**: they
  are not in P-036's interprocedural scope and would inflate the "Owen-only"
  count with an orthogonal capability.
- `F1-14` is the July oracle fixture reused unchanged (its own console project).

### 1.1 Post-hoc controls (class 5, added after the audit of `c57a919`)

The owner's audit of the closed record found that F4-S1's fixed side toggles
**two** variables at once — the type gains `IDisposable` *and* the owner gains
a `using` — so a tool silent on the fix could be tracking either. The two
controls below complete a 2×2 factorial around F4-S1 with everything else
byte-identical (I = type implements `IDisposable`, O = owner enrolls/disposes):

| case | cell(s) | source | lifecycle state on `before` → `after` |
|---|---|---|---|
| `F4-C1` `enrollment-control-interface-owner-drops` | I+O− → I+O+ | F4-S1's code with `: IDisposable` added and the owner still dropping the instance; the fix is F4-S1's fix verbatim | BUG REMAINS → FIXED |
| `F4-C2` `enrollment-control-dispose-without-interface` | I−O− → I−O+ | F4-S1's buggy side verbatim; the fix calls `cache.Dispose()` explicitly and never adds the interface | BUG → FIXED (normal path; the exceptional path is F5's) |

The I−O− and I+O+ cells are F4-S1's own sides re-run, so they double as a
reproducibility check on F4-S1's original rows. The provenance class is 5 by
the §0.4 rule ("a case designed after observing a comparator's failure is
class 5"): these were designed after observing a comparator's *success* and
asking what it was a success at, which is the same thing. The manifest keeps
them under `posthoc_cases`, `decision_inputs()` drops provenance 5 before
computing D1/D2/D4, and their only effect on any number in this note is the
labelled post-hoc block (§8.4).

---

## Phase 2 — comparator qualification

### 2.0 Toolchain smoke (all tools on `corpus/fixtures/systemevents-console`)

MEASURED OBSERVATION, before the corpus run, reproducing the July three-tool
table (`dispose-agreement-with-codeql.md`) on this host:

| site | Owen | CodeQL 2.27 stock | Infer# 1.5 | CA2000 (SDK 8.0.425) | IDISP 4.0.8 | RLC# (2.11.6, lib annotations) |
|---|---|---|---|---|---|---|
| `:20` `SystemEvents +=` never `-=` | OWN014 (with ref pack) / OWN050 (without) | — | — | — | — | — |
| `:43` local `FileStream` never disposed | OWN001 | `cs/local-not-disposed` | `PULSE_RESOURCE_LEAK` (×2, lines 42 and 44) | CA2000 | IDISP001 | Resource Leak (FileStream) |
| `:54` same inside a `try` method | OWN001 | `cs/local-not-disposed` | `PULSE_RESOURCE_LEAK` (×2) | CA2000 | IDISP001 | Resource Leak |
| `:77` `Dispose()` skipped on the throw path | OWN001 "may not be disposed on every path" | `cs/dispose-not-called-on-throw` (at the `Dispose` call, `:78`) | `PULSE_RESOURCE_LEAK` (`:79`) | CA2000 (only with `dispose_analysis_kind = AllPaths`; stock is silent on `:77`) | — | Resource Leak (`:77`) |

Two corrections to the July write-up fall out of this: RLC# (not run in July)
*does* flag the throw-path case, and CA2000 at its default
`NonExceptionPaths` does **not**. Also visible: Infer# reports each leak at
two program points (method entry and last access), which the oracle's ±3-line
matcher would count as one.

### 2.1 Infer#

- EXTERNAL SOURCE FACT: `microsoft/infersharp` v1.5 (2024-05-31 per the
  releases page), Linux release tarball `infersharp-linux64-v1.5.tar.gz`
  (74 MB), containing `Cilsil` (self-contained .NET 6 translator, CIL → SIL
  via Mono.Cecil) and `infer` reporting `v1.1.0-9d469330b6`. Requires compiled
  `.dll` + `.pdb`; the Docker image was not usable here (no daemon), the
  tarball was.
- EXTERNAL SOURCE FACT: the resource-leak checker is Pulse
  (`PULSE_RESOURCE_LEAK`), interprocedural with per-procedure summaries;
  unknown calls "scramble the parts of the state reachable from the
  parameters"; Pulse reports only manifest errors (conditions true regardless
  of input), latent issues stay silent (fbinfer.com, checker-pulse).
- MEASURED OBSERVATION: runs out of the box on every fixture that builds;
  ~7 s per case on this host (EXPLORATORY ONLY). No configuration or model
  was written. Diagnostics: allocation site + last-access site, no branch or
  call witness in the SARIF (Infer's `.txt` report carries a bug trace; the
  SARIF does not).
- What it cannot take: anything that does not compile (a fixture referencing
  undeclared types without a stub) → `UNSUPPORTED`.
- Ambiguity resolved: "Infer#" means the released v1.5 tarball above, not the
  fbinfer C/Java front ends and not the `infersharpaction` wrapper.

### 2.2 RLC#

- EXTERNAL SOURCE FACT: paper arXiv:2312.01912 (Gharat, Shadab, Tiwari,
  Lahiri, Lal; v2 2023-12-05); implementation `microsoft/global-resource-leaks-codeql`
  (MIT), last commit `1212a92` 2023-08-12, **archived 2026-06-11**. The paper
  says CodeQL 2.11.4; the repo README says "works only for Windows machine"
  (WSL + PowerShell wrappers), which is a scripting constraint, not a query
  constraint.
- REPOSITORY-OF-TOOL FACT (read from source): `src/RLC.ql` (1062 lines,
  `@kind problem`), `src/Dispose.qll`, `src/infer.ql` (627 lines, the
  specification-inference query of their OOPSLA'23 follow-up),
  `docs/library-annotations.txt` (93 rows: `MustCall` on ~50 BCL/Azure
  types, `MustCallAlias` on wrapper constructors such as `StreamReader(Stream)`,
  `NonOwning` on `CancellationTokenSource`, `Socket.Accept` etc.). The
  annotation predicate `readAnnotation/5` is **external**: the shipped shell
  scripts append a predicate body made of the library rows plus the rows
  `infer.ql` produced for the target, then run `RLC.ql`. Output is CSV; rows
  whose message contains "Resource Leak" are the findings, the rest
  ("Verifying …", "Missing …") are annotation-consistency checks.
- Semantics (paper §3, confirmed in source): sources = `new` of a resource
  type, calls returning a resource type (default `Owning`), `CreateMustCallFor`
  calls, `Owning` parameters; sinks = `Dispose`/`Close`, `using`, return of a
  resource type, argument to an `Owning` parameter, `EnsuresCalledMethods`,
  assignment to an `Owning` field, `Add` into a collection; **intraprocedural
  local data flow only** — the call boundary is crossed **only through
  annotations**; a resource type is anything `IDisposable` unless annotated
  otherwise; nullness handled for simple `!= null` guards; exceptional paths
  handled only inside `try`/`catch`/`finally`.
- Paper capability vs tool capability vs executed: the paper reports
  24 TP / 37 FP (39% precision) on Lucene.Net, EF Core and three Azure
  services **with manual annotations on library-typed elements only**
  (Table 3). What we execute is the shipped pipeline with the shipped
  library annotations plus its own inference — no hand annotations unless a
  case row says `custom_model`.
- MEASURED OBSERVATION: `RLC.ql` and `infer.ql` **compile unmodified** on
  the period-correct bundle `codeql-bundle-20221211` (CLI 2.11.6,
  `codeql/csharp-all` 0.4.6), and that extractor traces a .NET 8 SDK build.
  Against CodeQL 2.27.0 the same query fails to compile (40 API-drift
  errors: `ControlFlow::Node`, `Namespace.getQualifiedName`,
  `ControlFlowNode.getElement`, `getAControlFlowExitNode`) — so the honest
  execution path is the 2022 bundle, and **no adapter was written**. The
  only harness change is mechanical: identical annotation sets share one
  compiled query pack (the shipped script recompiles per database).
- Cost: ~200 s per case on first compile, ~60 s once packs are cached
  (EXPLORATORY ONLY).

### 2.3 CodeQL

- EXTERNAL SOURCE FACT: CodeQL 2.27.0 bundle (`github/codeql-action`
  release `codeql-bundle-v2.27.0`), `codeql/csharp-queries` 1.9.3,
  `codeql/csharp-all` 7.3.0. Databases are built with `--build-mode=none`
  (source + NuGet resolution, no compile), as `oracle.yml` does.
- REPOSITORY-OF-TOOL FACT: the stock suite `csharp-security-and-quality.qls`
  holds exactly three dispose-family queries —
  `cs/local-not-disposed` (`API Abuse/NoDisposeCallOnLocalIDisposable.ql`),
  `cs/dispose-not-called-on-throw` (`API Abuse/DisposeNotCalledOnException.ql`),
  `cs/missed-using-statement` — and **no** event-subscription, timer, DI or
  protocol query (the query-help index confirms). `cs/local-not-disposed` is a
  **global data-flow** configuration: sources are `new`/static `Create` of a
  *library* `IDisposable` type ("user types often have spurious IDisposable
  declarations" — first-party disposables are deliberately excluded), sinks
  include return, `using`, `foreach`, explicit `Dispose`, **an argument to a
  parameter that `mayBeDisposed`** (`commons/Disposal.qll`: a conservative
  interprocedural over-approximation — a parameter counts as disposed if
  the callee calls `Dispose` on it *anywhere*, or forwards it to such a
  parameter), field/property/indexer assignment, `Add(...)`, `Close`/`Clear`.
  So: interprocedural via a **may**-disposal relation with no path or
  guard sensitivity, biased to silence. `cs/dispose-not-called-on-throw` is
  local flow + a CFG reachability check + an interprocedural
  "may throw" relation over callees.
- Any query written for this bakeoff would be scored `DETECTED_CUSTOM_QUERY`;
  at the time of writing none has been written.

### 2.4 CA2000 / .NET analyzers

- EXTERNAL SOURCE FACT: `Microsoft.CodeAnalysis.NetAnalyzers` 8.0.9
  (`AssemblyInformationalVersion 8.0.9.11401`, shipped in SDK 8.0.425).
  CA2000 is **not enabled by default** (docs: "Enabled by default in
  .NET 10: No"); it must be switched on by severity. Documented options:
  `dispose_analysis_kind` (default `NonExceptionPaths`),
  `dispose_ownership_transfer_at_constructor` / `_at_method_call` (default
  `false`), `interprocedural_analysis_kind` ("specific to each rule"),
  `max_interprocedural_method_call_chain` (3), `points_to_analysis_kind`.
- REPOSITORY-OF-TOOL FACT (dotnet/roslyn-analyzers `main`):
  `DisposeAnalysis.TryGetOrComputeResult` defaults to
  `InterproceduralAnalysisKind.ContextSensitive`; the CA2000 analyzer
  requests `PointsToAnalysisKind.PartialWithoutTrackingFieldsAndProperties`,
  `trackInstanceFields: false`. Abstract values:
  `NotDisposable, Invalid, NotDisposed, Escaped, NotDisposedOrEscaped,
  Disposed, MaybeDisposed, Unknown`; two message families (`NotDisposed`,
  `MayBeDisposed` "use recommended dispose pattern"), each with an
  exception-paths twin. Passing a disposable to a method is ownership
  transfer only if `dispose_ownership_transfer_at_method_call` is set or the
  callee is a `Create*`/`Open*` special case; otherwise the callee is
  analysed context-sensitively up to the chain limit and the argument's
  state becomes what that analysis says (typically `MaybeDisposed` when the
  callee's disposal is conditional).
- Two configurations are run: **stock** (CA2000/CA2213/CA1001/CA1063/CA1816
  at `warning`, options untouched) and **configured** (`ContextSensitive`,
  `AllPaths`, chain 5). Secondary comparator: **IDisposableAnalyzers 4.0.8**
  (community NuGet, default severities) — its rules include IDISP001
  "dispose created", IDISP004 "don't ignore created IDisposable", IDISP007
  "don't dispose injected".
- Scope statement (docs, verbatim in spirit): CA2000 fires when "a local
  object of an IDisposable type is created, but the object is not disposed
  before all references to the object are out of scope". Events, event
  handlers, timers-as-subscriptions, DI lifetimes and project protocols are
  outside its rule text; it was never expected to solve them and is not
  scored as if it should.

### 2.5 Owen-current and Owen-P036-target

- Owen-current: extractor built from `70189a3`, Python engine (the public
  default at this HEAD; the Rust core is CI/dogfood-default only, #262
  Stage 2), `own-check.sh --format sarif --severity warning`, WindowsDesktop
  8.0.31 reference pack on. Official corpus benchmark at this HEAD with the
  ref pack (MEASURED OBSERVATION, `scripts/benchmark.py`):
  **61/62 bugs caught · 62/62 fixes clean · 0 false positives**; the one
  miss is `viewmodel-escapes-to-app` (the documented injected-source
  region-escape backlog).
- Owen-P036-target: **never executed**. Its column is filled from P-036 /
  P-037 text and labelled PROPOSED P-036 CAPABILITY in every row.

---

## Phase 4 — semantic machinery per tool (documentation and source, not scores)

Legend: **B** built-in, **U** user-authored (annotation/config/query), **—**
absent. "Silently clean" = the situation in which the tool emits nothing
although the property is unproven. Sources: §2 citations; Owen columns are
REPOSITORY FACTS at `70189a3`; the last column is PROPOSED P-036 CAPABILITY.

| concept | Owen-current | CodeQL stock (`cs/local-not-disposed`) | Infer# (Pulse) | RLC# | CA2000 (NetAnalyzers 8.0.9) | Owen-P036-target (proposed) |
|---|---|---|---|---|---|---|
| local syntax pattern | B (extractor: `+=`/`-=` pairing, `Stop()`, teardown names) | B (source/sink patterns over AST) | — (works on CIL) | B (source/sink patterns; annotation keyed by file:line) | B (IOperation patterns) | B (OwnHIR ops) |
| intraprocedural CFG | B (OwnCFG, path-sensitive; `try` lowering + exception edges since the July slices) | B (CFG used by `dispose-not-called-on-throw`; the leak query is data-flow, not path-sensitive) | B (symbolic execution over SIL CFG) | B (CFG dominance/post-dominance checks, `try` handled only when present) | B (Roslyn IOperation CFG, exception paths only under `AllPaths`) | B (OwnCFG with typed terminators incl. `Invoke`/`Throw`) |
| call graph | partial: symbol-resolved **intra-class** closure for teardown roots; first-party call edges in the MOS (`forward` paths) | B (global data flow crosses calls; `mayBeDisposed` is a may-relation over callee bodies) | B (whole-program over compiled assemblies, summaries per procedure) | — (crosses calls only through annotations) | B (context-sensitive re-analysis of callees, chain ≤ 3) | B (derived ICFG; lifecycle roots; unresolved targets explicit) |
| method summary | B for disposable params/returns (MOS: `no/must/may/unknown`, `fresh/aliasOf/…`), one per method, context-insensitive | — (no summaries; flow through callees is a may-relation) | B (Pulse summaries per procedure, path-conditioned) | U (the annotations *are* the summaries; `infer.ql` proposes `Owning`/`MustCallAlias`) | B (interprocedural result cache, context-sensitive) | B (first-class `MethodSummary` per domain, serialised, cached) |
| must vs may effect | B (`must` only on every normal-return path; `may` → untrack + OWN051) | — (any disposal anywhere in the callee silences: may treated as must → **silently clean**) | B (path-conditioned: latent vs manifest) | — (an `Owning` parameter is trusted unconditionally: may treated as must) | B (`Disposed`/`MaybeDisposed`/`NotDisposed`; `MaybeDisposed` reported only as "use recommended pattern") | B (same lattice, cellwise under guards) |
| guarded effect (bool/null param) | — (lexical demotion only: a parameter-guarded `-=` never credits; no per-call-site selection) | — | B-ish (Pulse case-splits on conditions; whether a constant argument prunes the callee's branch is tested in §3) | — | — (branch pruning by constant arguments is not part of DisposeAnalysis; observed in §3) | B (P-037: fixed split, five edge transforms, cell selection at the call site) |
| constant-argument substitution | — | — | B (symbolic values flow into summaries) | — | — (context-sensitive analysis re-analyses the callee but §3 shows the constant does not decide the branch) | B (P-037 G-A1, literals `true`/`false`/`null` and fresh non-null only) |
| lifecycle-root reachability | B, bounded: name-roots + wired own-lifecycle handlers + intra-class symbol closure | — | — (no notion of teardown roots; a Dispose method is just a procedure) | — | — (CA2213 checks fields disposed in `Dispose`, by name) | B (explicit roots incl. DI scope / framework teardown; root-to-exit paths) |
| framework enrollment (is the root ever run?) | — (assumed from the name-root; audit attack D) | — | — | — | partial: `using`/local scope only (CA2000), `IDisposable` fields (CA2213/CA1001) | B (LifecycleEnrollment: `using`, DI scope, wired callback, owner chain, model) |
| field / heap identity | partial: field name text + `Interlocked.Exchange` / alias idioms; receiver rebinding (#163) unmodelled | B for locals (data flow), fields are a **sink** (assigning to a field is "may be disposed elsewhere" → silently clean) | B (heap abstraction over SIL) | partial (`isFieldAlias` for `t.f = s` patterns) | partial (points-to without field tracking for CA2000; CA2213 tracks fields by symbol) | B (places: `Field(base, id)`, allocation sites, `UnknownHeap` explicit) |
| virtual dispatch | — (unresolved invocation extends nothing → kept warning) | B (`getARuntimeTarget` over-approximation) | B (Cilsil resolves callvirt targets conservatively) | B (`getARuntimeTarget`) | — (interface calls are opaque → argument escapes) | B (`FiniteSet(methods)` with explicit precision) |
| external modelling | Tier B BCL fresh-factory table; `$consume/$borrow` channel; P-035 config | B (library models: `Create`/`Open` factories; `Task` excluded) | B (Infer models for BCL; unknown calls scramble reachable state) | U (`library-annotations.txt`, 93 rows) | B (`DisposeOwnershipTransferLikelyTypes`, `Create*`/`Open*` special case) + U (`.editorconfig`) | U (declarative model files, P-031) + explicit `Unknown` |
| exceptional exit | B for `try` bodies (exception edge before each may-throw statement); **not** applied to teardown-context release crediting | B (`cs/dispose-not-called-on-throw`, may-throw over callees) | B (Pulse models exceptions on the SIL CFG) | partial (only inside `try`) | B under `AllPaths` only | B (`Invoke` terminators with exceptional successors for all domains) |
| runtime correlation | — in Owen (OwnAudit consumes stable IDs; static-only/runtime-only buckets) | — | — | — | — | B (proof-DAG IDs for OwnAudit correlation) |
| unknown → visible? | B: OWN050 (unresolved type), OWN051 (unverified transfer), OWN052 (solver degraded) | — (unresolved → no source, silent) | partial (`skipped_calls` in summaries, not in the report) | — (a missing `MustCall` annotation = not a resource = silent, paper §5.3) | — (`Unknown` value is never reported) | B (`Unknown(reason)` on every callsite and summary) |
| witness preserved | acquire site + message; `codeFlows` only for OWN002/OWN005-class and pool views; **subscription OWN001/OWN014 carry no evidence steps** (MEASURED: 0 `codeFlows`, 0 `relatedLocations`) | location + message (`@kind problem`, no path) | allocation site + last access; `bug_trace` in `report.json` (3 steps: allocation start / allocated here / becomes unreachable) | file:line + message ("Resource Leak (Type - L/C) in method M") | line + message; no path | ordered derivation evidence: Acquire → Call → CallTarget → SummaryApplied → Branch → Release/Escape |

---

## Phase 3 — functional bakeoff

### 3.0 The Owen-P036-target column (PROPOSED P-036 CAPABILITY — proposal text only)

What the proposals *say* each family would get. None of this has been executed
anywhere; it is placed here so the measured rows can be read against it.

| family | proposal text | source |
|---|---|---|
| F1 (guarded / uncalled / wrong-overload `-=`) | fixtures 1–3 "already caught … enter this phase as regression anchors"; helper release "proven through summary application, not extractor-side symbol fixpoints"; findings "contain a call/branch witness" | P-036 §Phase 2 |
| F1 helper that may unsubscribe | "finding/advisory according to rule policy" | P-036 §Phase 2 fixture 5 |
| F2 timer `Stop()` | same doctrine as `-=` through the same lifecycle roots ("event subscriptions and timers") | P-036 §Phase 2 |
| F3 guarded transfer (`Teardown(true)`) | "`Split(skip, no, must)`; `Teardown(true)` → borrow → caller keeps obligation → honest OWN001; `Teardown(false)` → consume" | P-037 §8 row 1 |
| F3 early-return spelling | "identical by G-S2 row 3 — the two spellings converge" | P-037 §8 row 2 |
| F3 wrapper `id` / `neg` edges | "the guard survives one hop"; cells swap on `neg` | P-037 §8 rows 7–8 |
| F3 null-guard helper | "self-null: `Split(nn(s), must, no)` … `consume` (D1 conservatism retired)" | P-037 §8 row 4 |
| F3 mixed release/forward | "`Split(g, must, must)`, collapse `must` … `consume` (unanimous must)" | P-037 §8 row 12 |
| F4 enrollment | "Proving a perfect `Dispose()` that nothing ever calls proves nothing … effect without enrollment yields a degraded or conditional verdict — never clean" | P-036 §Lifecycle roots |
| F5 exceptional exit | "exceptional exit bypassing cleanup: finding with exceptional path" | P-036 §Phase 2 fixture 7 |
| F6 virtual/external target | "virtual/external cleanup target: explicit degraded precision"; delegate targets "when statically known" | P-036 §Phase 2 fixture 6, §Call resolution |
| F7 obligations | "an obligation produced in method A and discharged in method B is recognized; discharge on only some callee exits remains `may`" | P-036 §Phase 3 |
| F8 progress | "helper calls can prove progress / no progress; unknown progress remains explicit" | P-036 §Phase 4 |
| F9 regions / DI | "extends the existing lifetime/DI region reasoning without moving DI registration extraction into the generic solver" | P-036 §Region summary |

The P-037 walls apply to the target as much as to today: no conjunctions, no
field/local guards, no guard threading beyond one edge, no per-call-site
summary specialisation (P-037 §9). A case outside the vocabulary is claimed to
degrade to today's behaviour, not to improve.

### 3.1 A finding that surfaced while validating the harness: three layers, three answers on the P-037 flagship shape

MEASURED OBSERVATION on `corpus/p036-bakeoff/guarded-consume-flag-branch/before.cs`
(`Close(s, keep)` disposes only when `!keep`; the caller passes `keep: true`):

| layer | what it says | how it was measured |
|---|---|---|
| Owen-current, C# path (extractor + core) | **silent — no finding, no advisory** | `own-check --emit-facts`: the emitted body of `Guarded.Leak` is `acquire s (24); release s (26)`. The extractor's `ConsumeReleaseArgs` → `ConsumesParam` → `DisposesLocal` asks only whether `s.Dispose()` occurs *anywhere* in `Close`'s body (`Program.cs` ~4500–4600), so the guarded handoff is lowered to a flat `release` at the call site. `Close` itself is not emitted as a function, so the bridge's summary layer never sees it. |
| Owen-current, bridge alone (hand-written facts with `Close`'s body as `if … release s`) | **OWN051 advisory, no verdict**: "cannot verify whether 'Guarded.Close' takes ownership of 's' (inferred contract: may); optimistically assuming it does — 's' is not checked past this call" | `check_facts` on synthetic OwnIR (`spec/Inference.md` INF-S2 + INF-A5 behaviour, as the TZ D1 tests pin) |
| Owen-P036-target (P-037 §8 row 1) | OWN001 at the call site: `Split(keep, no, must)`, `keep: true` selects `no`, obligation stays with the caller | PROPOSED P-036 CAPABILITY — not executed |

INFERENCE: the extractor's consume inference is **may-as-must** — the same
defect class the bridge fixed as TZ D1 (`interprocedural-tz.md` §3) and the
adversarial audit named for `-=` (attack A), now observed on the consume
channel. It is *not* a regression (the after side is silent, correctly, and
no existing corpus case pins the guarded-consume shape), but it means the
"honest silence + OWN051" story of `spec/Inference.md` does not currently hold
on the C# path for this shape: the advisory is swallowed one layer earlier.
Recorded here for #304; **deliberately not fixed in this research phase**
(repository-work rule: no verdict changes before the decision).

### 2.6 Setup and modelling cost to reach the families at all (Q6)

MEASURED OBSERVATION on this host, human effort estimated by the author of
this note (EXPLORATORY ONLY; the wall-clock figures are non-admissible):

| tool | to run at all | to reach F3 (IDisposable transfer) | to reach F1/F2 (subscriptions, timers) | to reach F7/F8 (protocols, progress) |
|---|---|---|---|---|
| Infer# 1.5 | download tarball (74 MB), `dotnet build` the target; zero configuration | stock | **no path**: no event/timer model, and Cilsil works on CIL where a subscription is just `add_X(delegate)` | no path |
| RLC# | period-correct CodeQL bundle (2022, 1.0 GB), traced build, shipped scripts; the query is unmaintained (archived) | stock pipeline (library annotations + its own inference) — but ownership is unconditional: no annotation vocabulary for a guarded transfer | **no path** (resource = `IDisposable`-typed value; an event has no `MustCall`) | no path |
| CodeQL 2.27 | bundle (≈1.4 GB), `build-mode none`; zero configuration | stock (`cs/local-not-disposed`, `cs/dispose-not-called-on-throw`) | **custom query required**: no stock rule; the naive rule is ~40 lines of QL, the port of Owen's bounded predicate ~130 lines (§evidence `custom-codeql/`, written in about two hours by someone who already knew the target predicate) | custom query per project protocol; loop progress would need a custom CFG/summary query, not attempted |
| CA2000 / NetAnalyzers | in the SDK; must be **enabled** by `.editorconfig` severity | stock once enabled; `AllPaths` for exception paths | **no path** (rule text is scoped to local IDisposable objects) | no path |
| IDisposableAnalyzers | NuGet package | stock | no path (IDISP004 sees a discarded IDisposable *return value*, which covers the token-returning Subscribe shape only) | no path |
| Owen-current | build the extractor (`dotnet build`), reference pack for WPF types | stock | stock (the differentiated family) | F7: core exists, **C# extractor pending** (not reachable on C# today); F8: not implemented |

---

## Phase 5 — diagnostics and developer usefulness (concrete, not scored)

All quotes are MEASURED OBSERVATIONS from this host's runs (raw files under
`docs/evidence/p036-bakeoff/raw/`, and the §2.0 smoke run). No subjective
score is assigned; the repository preregistered none.

### 5.1 One leak, every tool: `corpus/fixtures/systemevents-console` `:43` (`new FileStream` never disposed)

| tool | anchor | message (verbatim) | witness |
|---|---|---|---|
| Owen | `Program.cs:43` (acquire) | `[OWN001] IDisposable local 'stream' is never disposed (leak) [resource: disposable]` | none for this code (no `codeFlows`; the OWN002/OWN005 family carries "acquired here"/"moved here" steps) |
| CodeQL stock | `Program.cs:43` | `Disposable 'FileStream' is created but not disposed.` | none (`@kind problem`) |
| Infer# | `Program.cs:42` and `:44` (two results for one leak) | `Resource dynamically allocated by constructor System.IO.FileStream() on line 43 is not closed after the last access at line 44, column 9.` | 3-step `bug_trace` in `report.json` (allocation start → allocated here → memory becomes unreachable); the SARIF carries only the location |
| RLC# | `Program.cs:43` | `Resource Leak (FileStream- L)  in method LeakAFile` | none |
| CA2000 stock | `Program.cs(43,22)` | `Call System.IDisposable.Dispose on object created by 'new FileStream("scratch.bin", FileMode.Create)' before all references to it are out of scope` | none |
| IDisposableAnalyzers | `Program.cs(43,9)` | `IDISP001: Dispose created` | none |

Reading: on the plain RAII class every tool anchors at the allocation and
says roughly the same sentence; Infer# alone carries a trace, and only in its
JSON report. Nobody explains a *path* for a straight-line leak because there
is none to explain.

### 5.2 The exception-path variant, `:77` (`Dispose()` skipped when `WriteByte` throws)

| tool | anchor | message | what the developer learns |
|---|---|---|---|
| Owen | `:77` | `[OWN001] IDisposable local 'onThrow' may not be disposed on every path (leak)` | that a path exists; not which one |
| CodeQL stock | `:78` (the `Dispose` call) | `Dispose missed if exception is thrown by [call to method WriteByte](1).` | **the throwing call is named** (a related location) — the most actionable message in the set |
| Infer# | `:79` | `… is not closed after the last access at line 79, column 9.` | last access only; the exceptional branch is implicit |
| RLC# | `:77` | `Resource Leak (FileStream- L)  in method DisposeOnThrow` | that RLC# treats the `try` as a path split; nothing about which |
| CA2000 configured (`AllPaths`) | `(77,23)` | `Object created by 'new FileStream(...)' is not disposed along all exception paths.` | that it is an exception path; not which call |
| CA2000 stock | — | silent (`NonExceptionPaths` default) | nothing |

### 5.3 The subscription leak, `:20` (`SystemEvents.DisplaySettingsChanged +=`, never `-=`)

| tool | result |
|---|---|
| Owen (ref pack on) | `[OWN014] event 'SystemEvents.DisplaySettingsChanged' is subscribed (handler 'OnDisplayChanged') to a static (process-lived) event source that outlives 'DisplayWatcher'; the strong subscription promotes 'DisplayWatcher' to the source's lifetime, so it can never be collected — a region escape (leak, no release path) [resource: subscription token]` — subject, publisher lifetime tier, consequence, and the missing release path, in one sentence; no evidence steps |
| Owen (ref pack off) | `[OWN050] cannot verify 'SystemEvents.DisplaySettingsChanged' — its declaring type is an unresolved reference (build the project or pass references); leakage analysis skipped` — the *honest-unknown* path, an advisory not a verdict |
| CodeQL stock, Infer#, RLC#, CA2000, IDISP | nothing (no rule) |
| CodeQL custom (bakeoff-written) | `Event 'DisplaySettingsChanged' subscribed here is never unsubscribed in 'DisplayWatcher'.` — location + subject; no lifetime tiering, no release-path reasoning beyond what the query encodes |

### 5.4 The #278 shape, `F1-01` (guarded `-=` in a non-teardown method)

| tool | result |
|---|---|
| Owen | `Case.cs:25 [OWN001] event '_properties.PropertyChanged' is subscribed (handler 'new PropertyChangedEventHandler(OnPropertiesChanged)') but never unsubscribed; its source is an injected dependency whose lifetime is unknown, so it may outlive and keep 'GoodsDocument' alive (possible leak) [resource: subscription token]` — note the wording "never unsubscribed": the diagnostic does not say *why* the existing `-=` at line 33 was not credited (guarded by `UnregOnlyGoodys` in a method nothing here calls). The reason lives in the extractor's predicate, not in the message. `codeFlows: 0`. |
| CodeQL custom port | `Event 'PropertyChanged' subscribed here has no unguarded '-=' in a proven teardown context of 'GoodsDocument'.` — names the *criterion* that failed, still not the site that failed it |
| every stock comparator | nothing (no rule) |

Reading against P-036's witness requirement ("Subscription acquired at …;
Close() called from OnClosed(); Cleanup() reaches `return` when `_flag ==
false`; Unsubscribe at … is not reached on that path"): **no executed tool,
Owen included, produces a branch/call witness for the subscription class
today.** Owen's message is the most informative sentence, and it is still a
sentence, not a path. This is a REPOSITORY FACT about the current
`Diagnostic.evidence` coverage (only the OWN002/OWN005 and pool-view paths
carry steps; `docs/tasks/evidence-coverage.md`), not a P-036 measurement.

---

## Phase 7 — hostile review

### 7.0 Decision-contract sensitivity (recorded BEFORE the results matrix was read)

Raised by the owner on reading the checkpoint commit `fce388a`, while the
corpus run was still executing and no result beyond the §2.0 smoke and the
§3.1 harness-validation cases had been read. The preregistration is **not**
amended — changing the mapping after results start arriving would be exactly
the goalpost move §0 forbids. Instead the final verdict is reported twice:
once **exactly as frozen**, once under the sensitivity analysis below, with
the two labelled `PREREGISTERED VERDICT` and `METHODOLOGY SENSITIVITY /
CONTRACT DEFECT`. Neither replaces the other.

**Defect 1 — GO is structurally unreachable with the preregistered corpus.**
D4 counts a P-036 domain as evidenced only if the corpus holds a class-1
(historical real bug) case in it, and GO requires ≥ 3 evidenced domains. The
frozen corpus (§1 table) has class-1 cases only in F1 (4) and F3 (5); F2 is
class 3, F4–F8 are class 4, F9 is class 2. P-036's five domains map onto the
families as ownership ↔ F3/F1/F2 (lifecycle release is the ownership
summary's first consumer), obligations ↔ F7, progress ↔ F8, regions ↔ F9,
tasks ↔ none. So at most **one** domain (ownership, counting lifecycle under
it) — or two if F1 and F3 are read as separate domains — can ever be
evidenced under D4, whatever the tools do. The ceiling of the frozen mapping
is therefore SHRINK, and a SHRINK verdict must be read as partly a property
of the corpus's provenance mix, not only of the measurements. This is a
contract defect, recorded as such. The honest statement of what D4 *can*
show is: "which of P-036's domains have any real-bug grounding in this
repository today" — a useful fact, but not a GO/SHRINK discriminator.

**Defect 2 — D2 is global, so one comparator-covered target case can force
NO-GO past several differentiated families.** As frozen, ¬D2 holds if *any*
D2-scope case that Owen misses is caught STOCK/CONFIGURED by a comparator
(with the fix silent). SHRINK exists precisely for "part of the layer is
commoditised, part is not"; a global D2 cannot express that and collapses it
into NO-GO. The sensitivity analysis will therefore also evaluate a
**per-domain D2** (D2 restricted to each family separately) and report where
the global and per-domain readings diverge.

**Defect 3 — the D2-scope set itself is small and synthetic.** The cases Owen
misses inside the P-036 scope are, by construction, the class-4 cases (F3-S*,
F4-S1, F5-S1, F6-S1) plus whatever the run adds. A verdict resting on them
rests on proposal-derived shapes, not on incidents. Recorded; not fixable
without a mined corpus for those families, which is out of this phase.

Sensitivity questions the final section must answer, in this order:

```text
S1  Is GO structurally reachable with the preregistered corpus?         (no — Defect 1)
S2  Can one comparator-covered target case force NO-GO although several
    other P-036 families stay differentiated?                            (yes — Defect 2)
S3  Would a per-domain D2 produce SHRINK where the global D2 produces
    NO-GO?                                                               (evaluated on the results)
S4  Does any conclusion change when class-4 cases are removed from D1/D2?  (evaluated on the results)
```

### 3.2 Results by family (MEASURED OBSERVATIONS; every detection re-read by hand)

The generated status matrix is `docs/evidence/p036-bakeoff/summary.md`
(per case × side × tool/config) and the per-finding messages are under
`raw/`. "Discriminates" = flags `before` **and** is silent on `after`; a tool
that flags both sides never modelled the mechanism under test and is listed
separately. Where the harness status and the human reading differ, the human
reading is given and the reason stated.

**F1 — subscription release reachability (14 cases; 4 real, 3 fixtures, 7 adversarial).**
Owen discriminates all 13 two-sided cases and flags the single-sided F1-14;
zero false positives on fixes (the one CRASHED entry, F1-07's fix, was a
harness race on the shared extractor build — re-run serialised: CLEAN). Every
stock comparator is silent on every F1 case, by rule scope (no event/timer
rule), which the manifest declared before the run and the run confirmed.
Two F1 cases put an `IDisposable` in reach of the RAII tools and they still
did not fire: F1-13 (the token returned by `bus.Subscribe<T>()` is
discarded — IDISP004 and CA2000 both `MISSED`; Owen: "the result of
'bus.Subscribe<CustomerChanged>' is ignored — the IDisposable subscription is
never disposed") and F1-14 (the RAII controls are caught by all, the
subscription by Owen alone, §2.0). F1-09 is `UNSUPPORTED` for the
build-requiring tools by fixture design (unresolvable `Window`), and N/A
anyway. F1-11/F1-12 (ScreenToGif) needed the XAML stub to compile for the
comparators; Owen reads them without it (OWN014 static source; three OWN001
lambdas).

**F2 — timer `Stop()` (6 adversarial).** Owen 6/6 discriminates, no FPs. All
comparators N/A: the timer stand-in is not `IDisposable`, so no RAII tool has
a resource to track — confirmed silent.

**F3 — interprocedural IDisposable transfer (16: 5 real, 5 fixtures, 6 synthetic).**

| tool/config | discriminates | detected but FP on fix | reading |
|---|---|---|---|
| Owen | 12 (F3-01…F3-10, F3-S5, F3-S6) | 0 | misses **F3-S1…S4** — all four through the extractor's may-as-must `ConsumesParam` (§3.1); the same inference is what makes F3-S5/S6 "caught": the OWN002 there is the right verdict for an unsound reason (any `Dispose` in the callee counts), not a proof |
| CodeQL stock | 1 (F3-06) | 0 | `cs/local-not-disposed` sources are `new`/static `Create` of **library** types only: `File.OpenRead`, `AcceptTcpClient`, `ExecuteReader` are not creations, the first-party `Res` is excluded by design; a handoff to any callee that disposes the parameter *somewhere* is a sink (`mayBeDisposed`), so every guarded shape is silent on both sides. Use-after cases: no rule |
| Infer# | 2 (F3-08, F3-09) | 0 | catches `new` of a user type with `Dispose`; no models for BCL factories (`File.OpenRead`, `RandomNumberGenerator.Create`, `AcceptTcpClient`, `ExecuteReader`) → unknown → silent; silent on every guarded/handoff shape; no use-after-dispose issue type for C# |
| RLC# (shipped pipeline, 2.11.6) | 6 (F3-01 leak arm, F3-04, F3-06, F3-08, F3-09, F3-10) | 1 (F3-05) | strongest pure-RAII comparator here: an annotation-free `Owning`-by-default model; its own inference marks `Close(Stream s, bool keep)`'s `s` as `Owning`, which makes the guarded handoff a sink on both sides — no conditional ownership exists in its vocabulary. F3-05's fix (`Interlocked.Exchange(ref _timer, null)?.Dispose()`) is flagged: no heap identity through the exchange. Use-after: no rule |
| CA2000 stock | 6 (F3-01 leak arm, F3-04 via CA2213, F3-06, F3-08, F3-09, F4-S2) | 5 (F3-05, F3-S1…S4) | on the guarded shapes it emits the `MaybeDisposed` message ("use recommended dispose pattern") on **both** sides — context-sensitive re-analysis sees a conditional dispose but never prunes the branch by the constant argument; F3-05's fix flagged (CA2213, no identity through `Exchange`); misses `AcceptTcpClient`/`ExecuteReader` (not creations) |
| CA2000 configured (`AllPaths`, chain 5) | 5 | 11 | adds exception-path detections and as many exception-path "false positives" on fixes (`File.OpenRead(...)` then `s.Length` before the handoff: strictly, `s` leaks if `Length` throws). These are not false under CA2000's criterion — the corpus's "fixed" is Owen's criterion (normal paths + `try`-body throw edges). Recorded as a corpus-definition threat in §7 |
| IDisposableAnalyzers | 8 (F3-01, F3-04, F3-06, **F3-07**, F3-08, F3-09, F3-10, F4-S2) | 1 (F3-05) | the only comparator that treats a method return (`AcceptTcpClient`) as a creation (IDISP001); F3-05's fix flagged; IDISP007 "Don't dispose injected" fires on every consuming helper's `s.Dispose()` — its ownership convention is the *inverse* of the consume contract (a parameter is presumed borrowed), a design disagreement, not a leak finding |

Net for F3: on the five real-bug cases (F3-01, F3-04, F3-05, F3-06, F3-10)
every tool with a RAII rule catches at least the plain leak arm; **only Owen is
silent on the two NLog fixes (F3-04 helper sink, F3-05 `Interlocked.Exchange`)
and flags the use-after-handoff arms (F3-01, F3-02, F3-03)** — the
first-party-summary (`ConsumesParam`/`CallReleasesReceiver`) and heap-idiom
work already landed, not P-036. On the six P-037-derived cases: **nobody
discriminates F3-S1…S4**; Owen is silent without an advisory (§3.1), CA2000
flags both sides, the rest are silent. F3-S5/S6 are "caught" by Owen only
(mechanism caveat above).

**F4 — enrollment (2 synthetic).** F4-S1 (name-root `Dispose` on a
non-`IDisposable` type, nobody calls it): Owen `MISSED` — the audit's attack
D, reproduced. **IDisposableAnalyzers discriminates it stock** with IDISP009
"Add IDisposable interface" at the `Dispose` declaration: a design rule
that flags the *symptom* (a `Dispose` nobody can reach through the
interface), says nothing about the subscription, and is exactly the cheap
bounded fix the audit proposed for D ("name-root `Dispose` only when the type
implements `IDisposable`"). The manifest had declared IDISP N/A for this
family by rule scope; the declaration was too coarse for this case and the
detection is counted (the harness never masks a detection). **Post-audit:**
the fix toggles two variables (interface *and* `using`), so this detection
alone cannot tell which one IDISP009 tracked; the §1.1 controls isolate them
and §8.4 reads the result. F4-S2 (owner
drops an `IDisposable` subscriber): Owen, CA2000 and IDISP001 discriminate;
CodeQL (first-party type excluded), Infer# and RLC# miss it.

**F5 — exceptional exit inside `Dispose` (1 synthetic).** Owen `MISSED`: the
teardown-context predicate credits the `-=` in `Dispose` without looking at
the may-throw `Flush()` before it — the CFG's exception edges exist for
`try` bodies but are not consulted by the release-crediting predicate. No
comparator has a rule; CA2213 fires on both sides about the unrelated `_log`
field (wrong subject, no discrimination).

**F6 — cleanup through a delegate/interface target (1 synthetic).** Owen flags
the bug side (an interface call proves nothing: kept warning, correct) and
**also flags the fix** (`_cleanup = Detach` assigned in the ctor, invoked in
`Dispose`): the documented degraded-precision case (audit table: "teardown
via delegate field ⇒ kept warning"). A precision claim for P-036 (delegate
targets "when statically known"), not a recall claim; no comparator has a rule.

**F7 / F8 — obligations, progress (1 synthetic each).** `NOT_APPLICABLE` for
every tool including Owen (C# protocol extractor pending; PRG001 not
implemented). Nothing executed can say anything about these domains.

**F9 — regions / DI (3 fixtures).** Owen discriminates all three (DI001;
OWN001 on the App-scoped bus; OWN014 on the static source in a `Window`); all
comparators N/A and silent. One honest wrinkle: with the harness `IEventBus`
stub, F9-02 resolves and Owen reports an injected-source **OWN001 warning**,
where the official benchmark (no stub) records an OWN050 advisory and a miss —
the stub changed Owen's own verdict from "unresolved" to "warning"; the
App-lifetime *proof* (OWN014) is still not produced.

### 7.1 The ten questions

1. **Did we select cases that favour Owen?** Partly, and structurally: 20 of
   the 45 cases (F1, F2) plus the 3 F9 fixtures are Owen's own regression
   corpus, written to pin defects in Owen's *predecessor*, in defect classes
   for which no comparator ships a rule. Their result ("everyone else is
   silent") was knowable from rule scope before the run and was declared so
   in the manifest; the run only confirms that nothing fires by accident
   (F1-13/F1-14 are the two places a RAII rule could have reached, and did
   not). Those families measure *coverage of a class*, not relative quality
   on a shared class. The shared class is F3, and there Owen's edge is
   narrow: the use-after-handoff arms and two NLog heap idioms, all landed
   features; its four guarded-shape misses are real.
2. **Current Owen vs theoretical comparators?** No: every comparator was
   executed as shipped, on the same inputs. The one asymmetry runs the other
   way — RLC#'s paper results depend on manual annotations that were *not*
   reproduced, so RLC#'s executed recall is a floor for the tool, not its
   ceiling (§2.2).
3. **Theoretical P-036 vs implemented comparators?** The P-036 column is
   never scored. But the D2 scope is, by construction, "proposal-derived
   cases Owen misses", so D2 measures *whether anyone else already covers
   P-036's target shapes*, not whether P-036 would. Nothing in the note
   claims the latter; the mechanism finding of §3.1 cuts the other way (the
   C# path currently swallows the shape before any summary sees it).
4. **Custom CodeQL logic scored as stock?** No. Two bakeoff-written queries
   exist (§evidence `custom-codeql/`), are scored `DETECTED_CUSTOM_QUERY`
   only, and are excluded from D1/D2/D4 by the mechanical rule set (§3.4).
5. **Unsupported counted as missed?** Statuses are separate: `UNSUPPORTED`
   (F1-09 by fixture design; F1-11/F1-12/F9-03 until the XAML stub re-run)
   never became `MISSED`. One declaration gap the other way: the manifest
   declared N/A by rule scope for subscriptions, timers, DI, protocols and
   progress, but **not** for the use-after-dispose subclass (F3-02, F3-03,
   F3-S5, F3-S6), for which no comparator has a C# rule either; those rows
   read `MISSED` for the comparators where `NOT_APPLICABLE` would be fairer.
   Effect on the predicates: none (D1 for F3 fails on the leak arms anyway;
   the D2 scope contains only Owen-missed cases); effect on the comparator
   discrimination counts in F3: understated by up to four cases each.
6. **Lack of diagnostics confused with lack of capability?** Checked per
   tool: CodeQL's silence on handoffs is a *design* choice (a callee that
   may dispose is a sink); CA2000's both-sides `MaybeDisposed` is a
   *capability* gap (no branch pruning by constant arguments); RLC#'s is a
   *vocabulary* gap (no conditional `Owning`); Infer#'s silence on F3-S1 is a
   *model* gap (the leak in `Leak()` is manifest, no parameter decides it,
   and `File.OpenRead` is simply unmodelled), whereas its silence on
   parameter-driven shapes could also be Pulse's manifest-only reporting
   policy — the two were not separated further.
7. **Synthetic where real bugs disagree?** The D2 evidence rests entirely on
   class-4 cases (Defect 3). No class-1 case in the corpus is caught by
   P-036-target-only reasoning; on the class-1 F3 cases Owen's advantage
   comes from landed work. The SectorTS incident (#278, class 1) is caught by
   the landed predicates, and its P-037-style generalisation (the same guard
   on an `IDisposable` handoff, F3-S1) is caught by nobody — that is the
   honest shape of the evidence.
8. **Performance smuggled in?** No timing enters D1–D6. §6 carries the label
   on every number and makes one claim only: no order-of-magnitude
   disaster, and setup (database creation, traced build) dominates all
   comparators.
9. **Setup/modelling cost ignored?** §2.6. The comparators ran with zero
   per-case modelling; that is why RLC# is a floor (Q2) and why the custom
   CodeQL queries are reported as *cost*, not as CodeQL's stock capability.
10. **Wrong RLC#/Infer# artifact?** RLC# executed is the archived 2023
    `microsoft/global-resource-leaks-codeql` on CodeQL 2.11.6 (the paper
    says 2.11.4), **unmodified**, with the shipped inference and library
    annotations. Infer# executed is release v1.5 (2024) whose bundled Infer
    reports `v1.1.0-9d469330b6` — a Pulse of that vintage, not current
    Infer `main`. CodeQL 2.27.0 and IDisposableAnalyzers 4.0.8 are current;
    NetAnalyzers 8.0.9 is the SDK-8 build (SDK 9/10 analyzers not tested).

### 7.2 Surviving threats to validity

```text
T1  Corpus provenance mix: GO unreachable by construction (Defect 1).
T2  Global D2: one commoditised case decides NO-GO (Defect 2) — realised by
    F4-S1 / IDISP009.
T3  D2 scope is entirely class-4 (Defect 3).
T4  "Fixed" is Owen's criterion: CA2000 AllPaths' exception-path findings
    on F3-01/02/03 fixes are true under its own criterion.
T5  N/A declarations incomplete for use-after-dispose: comparator
    discrimination in F3 understated by ≤ 4.
T6  RLC# executed below its paper capability (no manual annotations).
T7  Infer# core vintage (Infer 1.1.0 Pulse).
T8  Owen's F3-S5/F3-S6 detections come from may-as-must consume inference
    (§3.1): correct verdict, unsound mechanism — Owen's F3 discrimination
    count overstates its proven capability by two.
T9  Harness stubs changed one Owen verdict (F9-02: OWN050 advisory → OWN001
    warning) by making a fixture type resolvable; recorded, not scored.
T10 Single run per tool on one host; CodeQL/Infer# nondeterminism was not
    probed by repetition (deterministic by design, unverified here).
T11 F1/F2 "differentiation" is rule-scope coverage, not measured quality
    on a shared class (Q1); it is real, but it is not a P-036 result.
T12 (found by the owner's audit of c57a919, after this list was closed)
    F4-S1's fixed side toggles two variables at once (the IDisposable
    interface and the owner's `using`), so the one D2-failing witness was
    confounded; the harness D1/D4 also computed "≥ 1 case" and "families"
    where the frozen text says "whole family" and "domains". Addressed
    post-hoc in §1.1 / §3.4 / §8.4 without amending the contract.
```

---

## Phase 6 — exploratory timings

`EXPLORATORY ONLY / NON-ADMISSIBLE FOR #263 / NON-PUBLICATION-GRADE /
UNCONTROLLED SHARED HOST.` One run per (case, side), three worker threads on
four cores, no warm-up policy, compile caches cold for the first cases, the
same host running the other tools concurrently. Wall-clock per side from the
main run (n = 89 sides per tool/config; the merge re-runs and the custom
post-pass are excluded):

| tool/config | median s | p90 s | max s | what the number contains |
|---|---|---|---|---|
| Owen | 2.9 | 4.6 | 8.4 | incremental `dotnet build` of the extractor + extraction + Python core |
| NetAnalyzers stock / configured | 1.7 / 1.5 | 2.3 / 2.1 | 3.2 / 2.8 | `dotnet build` of a one-file library with analyzers |
| IDisposableAnalyzers | 1.8 | 2.6 | 3.6 | same |
| Infer# | 8.4 | 10.6 | 13.0 | `dotnet build` + Cilsil translation + Pulse |
| CodeQL 2.27 stock suite | 81.0 | 91.4 | 123.9 | database creation (build-mode none, NuGet resolution) + the full security-and-quality suite |
| RLC# (2.11.6) | 81.8 | 182.3 | 226.0 | traced `dotnet build` + database + `infer.ql` + `RLC.ql` (first compile ≈ 60 s per distinct annotation set) |

Suitable conclusions, and the only ones drawn: no comparator is a 100×
disaster on inputs of this size; the two CodeQL-based comparators are
dominated by database construction and query compilation, not by analysis;
Owen's per-file cost is dominated by the extractor build it repeats per
invocation (`own-check.sh`), which a batch mode would amortise. Nothing here
ranks engines, feeds #263, or supports a latency claim.

### 3.3 The bakeoff-written CodeQL queries (DETECTED_CUSTOM_QUERY — never stock)

MEASURED OBSERVATIONS over the 2.27.0 databases of the main pass
(`raw/codeql/*.custom_query_*.json`):

| query | discriminates | FP on fix | misses | reading |
|---|---|---|---|---|
| naive (pre-#278 rule: any matching `-=` in the class releases) | 7: F1-10, F1-11, F1-12, F1-14, F6-S1, F9-02, F9-03 — exactly the cases with **no** `-=` anywhere | 7: F1-05 (the `-=` lives in a local function; the query's declaring-type test does not see it — a defect of the 40-line query, recorded), F2-01…F2-06 (no timer model was written) | F1-01…F1-04, F1-06…F1-09 (a `-=` exists somewhere → credited: the #278 hole, reproduced in QL), F1-13 (token), F4-S1, F5-S1 | the naive rule is a few lines of QL and fails exactly the class the #278 corpus was built to pin |
| teardown port (the #293/#305 predicate in ~130 lines of QL) | 15: F1-01…F1-08, F1-10, F1-11, F1-12, F1-14, F6-S1, F9-02, F9-03 | 7: F1-09 (unresolved lifecycle event; Owen's unique-name fallback was not ported), F2-01…F2-06 (no timer model) | F1-13 (token: a different mechanism), **F4-S1 and F5-S1 — the port inherits Owen's enrollment and exceptional-exit holes by construction** | matches Owen on 14 of the 15 two-sided F1/F9 cases it was written for, and **beats Owen on F6-S1's fix**: CodeQL's stock call graph (`Callable.calls`) resolves the delegate target assigned in the constructor, so the `-=` in `Detach` is credited; Owen's intra-class symbol closure does not resolve delegate invocations and keeps the warning |

Reading: the landed bounded predicate is portable to QL by someone who
already knows it, in an afternoon, and it inherits every hole of the
predicate. What CodeQL adds for free is its call graph (delegate targets,
`getARuntimeTarget`); what it does not give is a may/must summary engine:
the P-037 shapes are not a query away — they would be a bespoke
interprocedural analysis written in QL, i.e. the same architectural work
P-036 describes, in a different language.

### 3.4 Mechanical inputs to the predicates (from `results.json`, `decision_inputs`)

Predicates exactly as coded in `decision_inputs()` (the same text is written
into `results.json` under `rules`, so an auditor can recompute from `raw/`
without reading the harness): a tool/config **discriminates** a case when its
`before` status starts with `DETECTED` and its `after` status is one of
`CLEAN`, `NOT_APPLICABLE`, `ABSENT`. The harness assigns `NOT_APPLICABLE` only
over a raw `CLEAN`/`MISSED` — a manifest `na` label never hides a finding
(F4-S1: IDISP009 on `before` stays `DETECTED_STOCK`; the silent `after` is
labelled N/A) — so an N/A fix side was a clean fix side, which is the §3.2
reading "flags `before` and is silent on `after`". A narrower recomputation
(`after == CLEAN` only) would un-commoditise F4-S1 and flip §8.1; it is not
the predicate that was run, and it is recorded here so nobody has to guess.

| predicate | mechanical value | human reading (and why it differs) |
|---|---|---|
| D1 families holding | `['F2', 'F9']` | **F1 also holds**: the only comparator hits in F1 are on F1-14, the single-sided July fixture, at lines 42–79 — its three RAII *controls* (§2.0); no comparator produced anything at the subscription site `:20`. The mechanical rule cannot see subjects inside a mixed fixture. D1 is **TRUE** under both readings. |
| D2 global | `False` — `F4-S1` commoditised by `idisp/stock` (IDISP009) | as read: IDISP009 flags the design symptom, not the lifecycle; it does discriminate (fix silent). CA2000 "detects" F3-S1…S4 with a false positive on every fix → not commoditised. |
| D2 per family | `F3: True, F4: False, F5: True` | as read |
| D3 (judgment) | — | **holds for F3-S1…S4**: a branch-sensitive `ConsumesParam` would only restore the honest `may` + OWN051 (still a miss); a verdict needs guard-preserving summaries with call-site constant selection — P-037's mechanism, not a lexical patch. **Holds for F5-S1**: crediting must consult exceptional edges and callee may-throw; the lexical alternative ("any call before the `-=` in `Dispose` demotes") would flag most real `Dispose` bodies. **Fails for F4-S1**: a design rule suffices for the cheap form (IDISP009; the audit's bounded fix D). **Fails for F6-S1's precision half**: delegate-target resolution is symbol-level work CodeQL's stock library already does. |
| D4 families evidenced | `[]` | **F1** under the human reading (same F1-14 artifact). F3 has 5 class-1 cases but its leak arms are discriminated by three to six comparators, so F3 can never be "evidenced" by D4's definition. Maximum reachable D4 with this corpus: **1**. |
| D5 | — | recorded in §2.6/§3.3: comparators reached the F3 real cases with zero modelling; the P-037 shapes were reached by nobody at any modelling cost tried here; RLC# is a floor (no manual annotations). |
| D6 | — | every input above is executed except the P-036 column and F7/F8 (nothing executed by anyone). Timings excluded. |

#### 3.4.1 Literal-contract recomputation of D1 and D4 (post-audit; preregistered rows only)

The owner's audit of `c57a919` found that the harness block above computes
**approximations** of the frozen text, not the text: D1 in §0.6 says Owen
"catches at least one **whole** family", the code accepted one discriminated
case; D4 in §0.6 counts P-036 **domains** (ownership, obligations, progress,
regions, tasks), the code counted defect families. Neither changed the
preregistered outcome (F2 and F9 are caught 6/6 and 3/3; mechanical D4 was
empty), but a machine that does not implement the frozen predicate cannot be
cited as having applied it. `literal_contract()` in the harness now
recomputes both from the same rows, in every defensible reading of the
ambiguous clauses, and writes the result to `results.json` under
`decision_inputs.literal_contract` (definitions included). The block above is
untouched.

Family → domain mapping (INFERENCE, stated once, from §0.4 and the codes
each family reports under): F1, F2, F3, F4, F5, F6 → ownership (lifecycle
release and `IDisposable` ownership, OWN0xx); F7 → obligations (OBL001);
F8 → progress (PRG001); F9 → regions (OWN014 / DI001); tasks → no family.

| predicate, reading | value | what decides it |
|---|---|---|
| D1 literal, (a) "no comparator catches **any** case of the family" | `['F2', 'F9']` | Owen catches every case of F1 (14/14, F1-14 single-sided counts on `before`), F2 (6/6), F9 (3/3) with zero FPs; F1 fails (a) only through the F1-14 RAII-control artifact (§3.4). F3 is 12/16, F4 1/2, F5–F8 0/1, F6 has an Owen FP on the fix: none is a *whole* family. |
| D1 literal, (b) "no comparator catches the **whole** family" | `['F1', 'F2', 'F9']` | no comparator catches all 14 F1 cases (each catches exactly one, F1-14). |
| D4 literal, strong: class-1 present **and** every comparator catches nothing in the domain | `[]` | ownership has 9 class-1 cases but every comparator catches something in it (IDisposableAnalyzers 10 cases, CA2000 stock 7, RLC# 7, CA2000 configured 6, Infer# 3, CodeQL 2). This is the reading the preregistered block implemented, at family granularity. |
| D4 literal, weak: class-1 present **and** every comparator has a gap on a case it ran on (MISSED, or DETECTED with an FP on the fix) | `['ownership']` | every comparator fails 10–16 ownership cases it was applicable to, F3-S1…S4 and F3-S5/S6 among them for all six configs. |
| D4 literal, weak with N/A also counting as a gap | `['ownership']` | same. |
| plausible, unevidenced (cases but no class-1) | obligations, progress, regions | F7, F8 are class 4; F9 is class 2. |
| no cases | tasks | — |

Reading: under the literal text D1 is **TRUE** in both readings, and D4 is
**1 domain** (ownership) under the natural reading of "shows a semantic gap in
every comparator on it", or **0** under the strong reading the harness had
implemented. The mapping cell that the strong reading lands in is still
undefined (Defect 5); the weak reading lands in a defined cell (D4 ∈ {1, 2}
→ SHRINK, if D1 ∧ D2 ∧ D3). Which reading the contract *meant* cannot be
settled after the fact — that is exactly why it is reported as a
recomputation, not as a correction of §8.1.

---

## Phase 8 — decision

### 8.1 PREREGISTERED VERDICT (the §0.6 mapping applied exactly as frozen)

```text
PREDICATE:       D1 — present differentiation
EVIDENCE:        Owen discriminates F2 6/6 and F9 3/3 with zero comparator
                 hits (mechanical); F1 14/14 with comparator hits only on the
                 F1-14 RAII controls (human reading). 0 false positives on
                 fixes in those families.
COUNTEREVIDENCE: the F1/F2 families are Owen's own regression corpus in
                 classes no comparator ships a rule for (T11); F9-02 needed a
                 harness stub to resolve (T9).
VERDICT:         TRUE.
LIMITATION:      rule-scope coverage, not measured quality on a shared class.

PREDICATE:       D2 — target differentiation (global, as frozen)
EVIDENCE:        F3-S1, F3-S2, F3-S3, F3-S4, F5-S1: no comparator
                 discriminates (CA2000 flags both sides of F3-S1..S4;
                 CA2213 flags an unrelated field on both sides of F5-S1).
COUNTEREVIDENCE: F4-S1 is discriminated stock by IDisposableAnalyzers
                 (IDISP009 "Add IDisposable interface").
VERDICT:         FALSE — one commoditised case, exactly as the global rule
                 is written.
LIMITATION:      class-4 cases only (T3); IDISP009 flags the symptom, not the
                 subscription; the rule's globality is Defect 2.

PREDICATE:       D3 — necessity of the semantic layer
EVIDENCE:        F3-S1..S4 need guarded summaries + call-site selection;
                 F5-S1 needs exceptional-edge crediting.
COUNTEREVIDENCE: F4-S1 (design rule) and F6-S1 (symbol-level delegate
                 resolution) do not need it.
VERDICT:         TRUE for the F3-S/F5 subset; FALSE for F4-S1 and F6-S1.
LIMITATION:      judgment, not computation.

PREDICATE:       D4 — breadth
EVIDENCE:        class-1 cases exist in F1 (4) and F3 (5) only.
COUNTEREVIDENCE: F3's class-1 leak arms are commoditised; F1-14 artifact.
VERDICT:         0 families (mechanical) / 1 family, F1 (human reading).
LIMITATION:      structurally capped at 1 by the corpus (Defect 1).

PREDICATE:       D5 — cost signal        VERDICT: recorded (§2.6, §3.3).
PREDICATE:       D6 — admissibility      VERDICT: holds for D1–D5 as read;
                 F7/F8 contribute nothing; timings excluded.

MAPPING (frozen): NO-GO if ¬D1, or ¬D2, or ¬D3.  D2 = FALSE.

PREREGISTERED VERDICT: NO-GO
```

Stated plainly: applied exactly as written, the preregistered contract
returns **NO-GO**, and the single fact that returns it is that
IDisposableAnalyzers' design rule IDISP009 discriminates one synthetic
enrollment case (F4-S1) that Owen misses. Every other case Owen misses inside
the P-036 scope (the four P-037 guarded-transfer shapes and the
exceptional-exit teardown) is caught by nobody.

### 8.2 METHODOLOGY SENSITIVITY / CONTRACT DEFECT (§7.0, answered on the results; does not replace §8.1)

```text
S1  Is GO structurally reachable with the preregistered corpus?
    NO. D4 can reach at most 1 (F1); F3's real cases are commoditised on
    their leak arms by three to six comparators, and F2/F4–F9 carry no
    class-1 case. GO required 3. (Defect 1, confirmed.)

S2  Can one comparator-covered target case force NO-GO although several
    other P-036 families stay differentiated?
    YES, and it did: F4-S1 / IDISP009 flips the global D2 while F3-S1..S4
    and F5-S1 remain uncommoditised. (Defect 2, realised.)

S3  Would a per-domain D2 produce SHRINK where the global D2 produces NO-GO?
    YES. Per-domain D2 = {F3: TRUE, F5: TRUE, F4: FALSE}. With D1 TRUE and
    D3 TRUE on the F3-S/F5 subset, the frozen mapping gives SHRINK for
    D4 ∈ {1, 2} — i.e. SHRINK under the human reading of D4 (= 1). Under
    the strictly mechanical D4 (= 0) the frozen mapping has NO cell
    (SHRINK needs D4 ∈ {1,2}; NO-GO needs ¬D1/¬D2/¬D3): Defect 5 — the
    mapping is incomplete at D4 = 0.

S4  Does any conclusion change when class-4 cases are removed from D1/D2?
    The D2 scope becomes empty (vacuously TRUE); D1 and D4 are unchanged;
    the outcome is the S3 outcome: SHRINK (human D4) / undefined
    (mechanical D4). No reading of the frozen contract reaches GO.
```

Sensitivity reading of the evidence (labelled as such, not a verdict):
**SHRINK** — to the subset the run actually differentiates: the P-037
guarded-transfer core (F3-S1…S4: nobody catches the `Teardown(true)` shape,
and Owen's own C# path currently swallows it without an advisory, §3.1) and
exceptional-exit teardown reasoning (F5-S1). Two things P-036 lists are
**not** novelty on this evidence: enrollment-by-interface (a design rule;
IDISP009 has it, the audit's bounded fix D is it) and statically-known
delegate/virtual target resolution (CodeQL's stock call graph has it; a
symbol-level extractor change would too). Obligations, progress, regions and
tasks are **plausible, unevidenced**: no executed tool, Owen included, said
anything about F7/F8, and F9 is covered by landed work.

### 8.3 What this decision is not, and what it does carry forward

- It is not a ranking of tools and it carries no performance claim
  (OWNER RULING; §6 label).
- It does not change any verdict, fixture expectation or host rule.
- Carried forward for #304 regardless of the verdict: the extractor's
  `ConsumesParam` is may-as-must on the C# path (§3.1), so the
  `spec/Inference.md` "may → OWN051" story does not hold for guarded
  handoffs today; and `Diagnostic.evidence` carries no steps for the
  subscription class (§5.4), so no tool — Owen included — produces the
  witness P-036 §Evidence promises.
- Carried forward for the contract itself: Defects 1, 2, 3 and 5 (§7.0,
  §8.2). A re-run under a repaired contract must be a new preregistration,
  not an amendment of this one.
