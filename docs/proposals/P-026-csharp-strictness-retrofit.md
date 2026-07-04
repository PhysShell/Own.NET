# P-026 — C# strictness retrofit profile (`own audit strictness`)

- **Status:** draft — a *framing/packaging* direction, not a new engine.
  Sourced from an external strategic read (a developer's "The Missing
  Programming Language" essay + a follow-up analysis of how Own.NET could speak
  to that audience). Implementation not started.
- **Depends on:** the audit orchestrator ([`Plan.md`](../../Plan.md),
  [`audit/README.md`](../../audit/README.md)) — SARIF normalization, cross-tool
  agreement scoring, the health report; the existing lifetime/resource core
  (`OWN001–015`), the typestate / obligation work
  ([P-010](P-010-type-disciplines.md), [P-025](P-025-obligation-protocols.md)),
  and the C# fact seam ([P-001](P-001-csharp-extractor.md),
  [P-014](P-014-semantic-resolution.md)). Relates to
  [P-015](P-015-configuration-surface.md) (check selection / severity) and
  [P-023](P-023-architecture-guard.md) (drift).
- **Where it lives:** an **audit profile + a report renderer**, consumed through
  CLI + SARIF only, zero coupling to `ownlang/`. It follows the audit code
  (currently `OwnAudit`, per `audit/README.md`), like [P-024](P-024-security-audit-profile.md).

## Decision (read this first)

**`own audit strictness` is a witness, not an engine.** It is a profile and a
report that *front the findings the fleet already produces* under one narrative —
"where C# lets your types lie, your domain rules live in comments, and your
resources leak because the language cannot express ownership" — plus a single
headline number (a **strictness score**). It adds **no new detector heuristic**;
every number it prints traces to a real finding from a real tool, or is labelled
`NO-TOOL`. This is the same charter as the rest of the audit fleet
("оркестратор, не анализатор"; "берём готовое"; honest coverage).

The motivating analysis proposed five angles. Two are **accepted as framing**,
two are **rejected as scope**, one is **already our identity**:

| # | Angle from the analysis | Verdict |
|---|-------------------------|---------|
| 1 | Strictness audit — "make C# stop pretending to be grown-up" | **Accept as framing** — this profile *is* that packaging over existing findings |
| 2 | Domain-invariant miner (implicit state machines hidden in flags/dates) | **Already in flight** — [P-010](P-010-type-disciplines.md) typestate + [P-025](P-025-obligation-protocols.md); this profile *surfaces* their output, it does not re-implement |
| 3 | Result/Option migration assistant (`return null` → `Option<T>`, `throw` → `Result<T,E>`) | **Reject as core scope** — see Non-goals |
| 4 | Exhaustiveness guard over OneOf/LanguageExt/… | **Defer to P-010** — internal exhaustiveness is P-010's territory; not a new pack here |
| 5 | Ownership / lifetime as the unique card | **Already the identity** (ROADMAP: "lifetime/resource bugs C# cannot express") — this profile leads with it, does not dilute it |

The load-bearing decision is the **rejection of #3/#4 as their own product.**
"Find `return null`, suggest `Option<T>`; find `throw`, suggest `Result`" is,
in the analysis's own words, something "any caffeinated student with Roslyn can
write." It is a nullable-annotation / control-flow linter — exactly the broad
"we find smells" arena where CodeQL/Sonar/Semgrep win on sales budget, not
merit, and which the ROADMAP explicitly refuses. We take the *vocabulary*
("the domain model lies", "make invalid states visible → then unrepresentable")
without becoming that linter. Ownership/lifetime stays the moat.

## Motivation — meeting an audience that already articulated the pain

The essay ranks C# at 4.5/5: big ecosystem, good perf, good DevX, but
"expressive types: mixed" — nullable is opt-in and warning-only, `!` launders
nulls, unions are perennially "coming", no local immutability. The reader wants
**C# ecosystem + F#/Rust-like safety** and is not going to switch languages to
get it. That is precisely Own.NET's long-term identity restated by an outsider:

> an external static-contract layer for C#/.NET that adds ownership, typestate,
> effects, capabilities, and domain-specific types **without rewriting the
> codebase.** — `docs/ROADMAP.md`

So the value here is **not new capability** — it is a *doorway* sized for this
reader. Today the capabilities are addressed by their mechanism (`OWN008`,
`DI003`, `OBL002`, "captive dependency"), which lands with a lifetime nerd, not
with someone whose complaint is "C# lets my types lie". `own audit strictness`
re-presents the same evidence as *"here are the places C# let your model lie"*,
with one score to argue about.

## Scope

- A CLI surface `own audit strictness <target>` that runs the relevant slice of
  the existing fleet and renders a **strictness report** (markdown + json),
  reusing the audit orchestrator's normalize/score/report pipeline.
- A **strictness score** derived *only* from findings that already exist,
  bucketed into named strictness dimensions (below), each dimension carrying an
  honest coverage state (`covered` / `NO-TOOL` / `partial`).
- A markdown narrative that groups findings as *invariant lies*, not as tool
  codes — e.g. an implicit state machine surfaced by P-010/P-025 is rendered as
  "`Order.Status` + `PaidAt` + `CancelledAt` form an implicit state machine;
  these constraints are not encoded in the type system", with the underlying
  finding IDs as evidence.

### The dimensions (all fronting existing or proposed detectors)

| Strictness dimension | Backed by |
|----------------------|-----------|
| Ownership / resource lifetime not expressed | `OWN001–015`, WPF/`IDisposable`/DI/pool profiles ([P-004](P-004-wpf-lifetime-profile.md)–[P-007](P-007-arraypool-span.md)) |
| Implicit state machines / typestate in flags & dates | [P-010](P-010-type-disciplines.md), [P-025](P-025-obligation-protocols.md) |
| Non-exhaustive handling hiding future cases | [P-010](P-010-type-disciplines.md) |
| Source-of-truth drift (config vs DI, XAML vs VM, EF vs migrations) | [P-015](P-015-configuration-surface.md), [P-023](P-023-architecture-guard.md) |
| Null-safety not enforced (`!`, opt-in NRT) | external analyzers via SARIF adapter; `NO-TOOL` until wired |

## Non-goals (the most important section)

- **No new heuristic detector.** No regex over `return null` / `throw`. If a
  dimension has no reliable tool, it is `NO-TOOL`, not faked. (Same rule that
  killed the security scanner engine in [P-024](P-024-security-audit-profile.md).)
- **Not an Option/Result migration linter.** We do not ship "rewrite `Customer?`
  to `Option<Customer>`" as a product. Suggesting union/`Result` remodels *as
  prose in the report* is fine (it is the narrative); shipping an autofix/analyzer
  pack for it is the SAST fight we refuse.
- **Not a generic nullable-annotation nag.** Roslyn's own analyzers + Sonar
  already own "you used `!`". We surface null-safety posture only as a *dimension
  of the score*, via existing tools, not as our own rule.
- **The score is not a vanity metric.** Every point of the 0–100 must be
  reconstructable from listed findings + coverage. A dimension that did not run
  lowers *confidence/coverage*, it does not silently read as "clean" (the audit
  charter's honest-coverage rule).
- **No new language, no autofix arm here.** This is a lens over the audit; the
  fix-arm lives where the audit's `fix/` layer lives.

## The honest gap (do not paper over it)

The analysis's demo — `own audit strictness MySolution.sln → Strictness score:
61/100` over an *arbitrary* solution — assumes a general C# semantic frontend.
That is not shipped: real-C# ingestion is the Roslyn extractor
([P-001](P-001-csharp-extractor.md)) + semantic resolution
([P-014](P-014-semantic-resolution.md)), both "in progress", scoped to the
lifetime/leak profiles, not to whole-solution strictness. So the first cut is
either:

- **(a)** run over the existing audit target (the legacy WPF app the fleet
  already ingests) and score *that*, or
- **(b)** ship the score frame with most dimensions honestly `NO-TOOL` and fill
  them as extractor coverage lands.

Both are charter-honest. What we must **not** do is print a green `61/100` whose
missing dimensions were silently treated as passing — that is the exact
dishonesty `audit/README.md` forbids.

## Sketch

```text
own audit strictness <target> [--profile wpf|generic] [--baseline <run>]
  → run fleet slice  → SARIF                     (existing adapters)
  → normalize        → categorized findings       (audit/aggregate/normalize.py)
  → map to strictness dimensions + coverage state  (new: thin mapping table)
  → score            → 0..100 + per-dimension breakdown, confidence from coverage
  → render           → strictness.md + strictness.json  (new renderer over report.py)
```

Report head (illustrative):

```markdown
# C# Strictness Audit — <target> @ <commit>

Strictness score: 61/100   (coverage: 4/6 dimensions; 2 NO-TOOL)

## Where the type system is not carrying the invariant
1. 9 implicit state machines (Status + *At flags)      [P-010/P-025 evidence]
2. 8 ambiguous IDisposable ownership transfers          [OWN / D-series]
3. 31 mutable setters on domain records                 [NO-TOOL: partial]
...
```

Score = weighted sum over dimensions; each dimension's contribution is a function
of its findings and severity; `NO-TOOL` dimensions do not contribute points but
*cap displayed confidence*. Deterministic over a fixed commit (diffable, like
every audit run), so `--baseline` yields new/old/suppressed exactly as the
orchestrator already does.

## Open questions

- **Score model.** Absolute (findings → deductions) is honest but noisy across
  codebases; a percentile against a corpus is friendlier but needs a corpus and
  can lie about small repos. Start absolute + per-dimension, defer any headline
  cross-repo comparison.
- **First target.** (a) the audit's WPF target (real, narrow) vs (b) frame-first
  with `NO-TOOL` dimensions. Leaning (a): it produces a *real* score to show,
  not a mostly-empty frame.
- **Where the mapping table lives.** It is audit-side config (dimension ← rule
  ids), so it should sit with the orchestrator's category map, not in `ownlang/`.
- **Naming.** `own audit strictness` vs `own strictness`; whether "strictness"
  reads as scolding — the report's job is to read as *diagnosis of hidden
  invariants*, not style-nagging.

## What we deliberately keep from the analysis, in one line

The *framing* ("the domain model lies; the lifetime is unexpressed; the error is
hidden in an exception; the invariant survives on the honor system") and the
*doorway* (one score, one narrative for the F#/Rust-refugee reader) — laid over
the evidence the fleet already produces. Not a new analyzer; a lens that makes
the existing verdicts legible to someone who wants an S-tier language and hasn't
noticed Own.NET is quietly building the missing layer for the one they already use.
