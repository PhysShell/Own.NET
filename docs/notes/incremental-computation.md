# Discovery note — incremental computation: when, how, and why not yet

- **Type:** discovery note (thinking on the record — *not* a proposal, *not* a
  commitment, *not* normative). Lives outside `proposals/` because it has no design
  shape yet: it records a direction we considered and the conditions under which it
  becomes worth a real proposal.
- **Trigger:** came across [Differential Datalog (DDlog)](https://github.com/vmware-archive/differential-datalog)
  — incremental Datalog compiled to Rust on top of
  [differential-dataflow](https://github.com/TimelyDataflow/differential-dataflow).
  Note the org: `vmware-archive` — the project is **archived / unmaintained**.
- **Related:** [P-002](../proposals/P-002-verification-backend.md) (a backend that
  consumes facts — Datalog-adjacent), [P-005](../proposals/P-005-idisposable-ownership.md)
  (D5 ownership-transfer-through-callee — the first interprocedural itch),
  [P-006](../proposals/P-006-di-lifetimes.md) (DI / captive-dependency — call-graph
  reasoning), [P-011](../proposals/P-011-editor-tooling.md) (editor tooling — the
  live-feedback use case), [P-013](../proposals/P-013-distribution-surface.md) (the
  **"one checker"** discipline this must not break). Strategy hub:
  [`../ROADMAP.md`](../ROADMAP.md).

## The idea in one line

Compute diagnostics from a **change** to the input facts (one edited file → a few
delta facts) rather than re-deriving everything from scratch — so the tool can give
near-instant feedback on a large solution and re-check a PR by its diff.

## Why it is conceptually a good fit

Own.NET's core is already **fact-based**. OwnIR is relational tuples
(`acquire`/`borrow`/`use`/`release`/`escape`, `Loan(owner, binding, kind)`), and the
core's rules (R1-R10, lifetime L1-L3) are logical inference rules over those tuples.
That is *exactly* the Datalog idiom, and fact-based static analysis is the
mainstream home of Datalog: Doop (Java points-to on Soufflé), CodeQL (QL, an
object-oriented Datalog). So "express the core as Datalog rules" is a recognized
architecture for our class of tool, and incremental Datalog (DDlog) is the version
of that which also gives delta-in → delta-out for free.

## Why it is *not* the move right now

1. **The current scope is intraprocedural, so incrementality is nearly free
   already.** A finding depends only on one method/class's facts (ROADMAP:
   "intraprocedural first"). A change does not ripple across the program, so a
   trivial **file-hash cache** ("re-extract and re-check only the files that
   changed") captures ~all of the practical win with none of the machinery.
   Differential dataflow earns its keep on *cross-program* derivations (transitive
   closures, joins over the whole call graph) — which we deliberately don't do yet.
2. **DDlog specifically is archived.** Adopting an unmaintained DSL + compiler is a
   standing supply-chain and maintenance risk.
3. **It would violate "one checker."** We already span two legs (C# extractor +
   Python core). A DDlog engine adds a **third language (Rust) and a second
   inference engine** — and the load-bearing invariant (P-013:19-21, ROADMAP) is
   that the Python core is the single source of truth and everything else only
   *produces or consumes* OwnIR facts. A second thing that decides verdicts is
   precisely what the project refuses.

## When it *does* earn its keep (the two gates)

Revisit seriously only when at least one is actually on the table:

- **Gate A — we go interprocedural / whole-program.** The deferred itches:
  ownership transfer through a callee ([P-005](../proposals/P-005-idisposable-ownership.md)
  D5), DI lifetimes and call-graph reasoning ([P-006](../proposals/P-006-di-lifetimes.md)).
  There a change to one method's signature ripples across the call graph and naive
  recomputation gets expensive — the classic regime where incremental dataflow
  (incremental points-to / call-graph) pays off.
- **Gate B — we want live IDE feedback.** [P-011](../proposals/P-011-editor-tooling.md):
  on every keystroke, re-running the whole solution (a real target is hundreds of
  files) is wasteful; you want edit → delta diagnostics.

Until one of these is real, incrementality is over-engineering and the file-hash
cache is the honest answer.

## If/when it matters — aim here, not at archived DDlog

- **Roslyn is already incremental on the extraction side.** Incremental parsing +
  semantic models come for free once the extractor uses a workspace
  ([P-001](../proposals/P-001-csharp-extractor.md) / P-014 Tier B). That covers
  *fact extraction* without any new engine; only the *inference* core would need
  its own incrementality.
- **Salsa (Rust)** — the demand-driven, query-memoizing incremental framework behind
  rust-analyzer (which *is* incremental static analysis for an IDE). For the Gate B
  / P-011 future it fits more naturally than Datalog (query → cache → invalidate on
  input change), and it is battle-tested in production.
- **differential-dataflow directly** — if we genuinely want delta-in/delta-out, build
  on the maintained engine (it powers Materialize) rather than archived DDlog layered
  over it.
- **Soufflé** — Datalog→C++, maintained, used by Doop. The right pick if the goal is
  "express the core declaratively as Datalog" for speed/clarity, *not* for
  incrementality (it is not incremental by default).

## The non-negotiable guardrail

Whatever the engine, incremental computation is an **optimization of how facts and
verdicts are recomputed — never a new decider.** It MUST yield bit-for-bit the same
verdicts as the batch Python core, proven by differential testing (batch vs
incremental over the corpus). The moment an incremental engine becomes a second
place where a verdict is decided, we have broken "one checker" (P-013) — which the
project's own manifesto treats as fatal.

## Decision

**Park it.** No action now; the file-hash cache covers today's intraprocedural
scope. Promote this note to a real proposal only when Gate A or Gate B lands — and
when it does, default to Salsa (IDE) or maintained differential-dataflow / Soufflé
(heavy inference) over archived DDlog, under the identical-verdicts guardrail.
