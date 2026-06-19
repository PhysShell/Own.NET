# Research landscape 2026 — digest + Own.NET reading

Working notes digesting an external research-landscape survey (shared 2026-06:
"Статический анализ в 2026 и окно возможностей для Own.NET") and reading it
against where Own.NET actually stands. Companion to
`consolidation-and-positioning.md`: that note is about **form** (naming, schema,
file splits); this one is about **research positioning** — landscape, gaps, and
the role of an LLM layer. The survey's own conclusion is *"don't change focus,
finish the line you're on"*, and that is taken; the value of this note is the
three places where our reading **diverges** from the survey, recorded so they
don't evaporate.

## The survey's thesis (fair summary)

- **Direction.** Don't build "Rust for C#". Build an external static-contract
  layer for concrete, expensive, reproducible .NET resource/lifetime bugs:
  events/WPF subscriptions, `IDisposable`, DI lifetime mismatch, `ArrayPool`/
  `Span` misuse. (This is already our ROADMAP.)
- **Three landscape currents.**
  1. Abstract-interpretation foundations remain the base, but industry trades
     soundness for speed / explainability / CI-fit (rule- and query-driven
     analyzers, not whole-program soundness).
  2. The **resource-leak / must-call / specify-and-check** family is proven —
     Checker Framework resource-leak (`@MustCall`), *RLC# for C#* on CodeQL
     (24 real leaks in OSS + Azure), *Inference of Resource Management
     Specifications* — but is bottlenecked on **manual specs** and weak coverage
     of project-specific APIs.
  3. 2024–2026 **hybrid LLM + static**: the strong results keep the LLM in
     *narrow* roles (spec inference, path-feasibility triage, summary
     generation) and let a **deterministic checker decide** (InferROI, IRIS,
     LLM4PFA, MemHint; the "LLMs vs static tools on C#" benchmark: LLMs win
     recall, lose precision + localization → hybrid recommended).
- **Biggest gap, biggest opening.** There is **no public .NET lifetime/resource
  benchmark** (Java has DroidLeaks / JLeaks; security has CWE-Bench-Java /
  CASTLE). Own.NET could be the analyzer **and** the benchmark/corpus — the path
  to reproducibility and a citeable result.
- **Priority shape.** Quick wins: subscription, `IDisposable`, DI captive-dep,
  and a benchmark + SARIF + reproducible corpus. Mid: `ArrayPool`/`Span`
  borrow-view. Far: an effects layer and a general spec miner. **Do not** build
  a full-C# ownership checker, whole-program alias analysis, a port of the core
  to C#, a general effect system, or first-class LINQ/async/generics/source-gen.

## Where we agree (and where we are already ahead)

The survey is **descriptive of where we already stand** — one core, narrow
frontend, bug-driven scope, `OWN001` vs `OWN014` lifetime ordering, semantic
resolution killing the syntactic FP wall (P-014). It is a confirmation, not a
redirect. Two places we are already **ahead of the doc's own roadmap**:

- **A deterministic spec miner already exists.** The survey files "spec miner"
  under far-horizon LLM work. But our `contract-inference` (`_infer_param_effect`
  in `ownir.py`, P-006/2b) is already a *deterministic* spec miner for local
  functions: `release` inside a body → `consume`, use-only → `borrow`,
  forward-only → unresolved (deliberately not `return`→consume). The cheap, safe
  half of spec mining is **done**; only the boundary-API (BCL/NuGet) half is
  open. See the dedicated LLM section below for why that ordering matters.
- **Differentiation is already demonstrated, not hypothetical.** The doc asks
  for an oracle and a benchmark; the 3-way oracle (Own.NET vs Infer# vs CodeQL)
  has already run on real C# and produced an own-only subscription-leak set. On
  ScreenToGif it flags `SystemEvents.DisplaySettingsChanged` (error) and the four
  `VideoSource` view→view-model lambdas (warning) that **CodeQL flags none of** —
  its query set has no "event subscribed, never unsubscribed" rule — and that
  Infer# misses too. So the benchmark ask is *formalize what we already did* into
  a labeled corpus, not net-new research. The harness and the agree/own-only/
  oracle-only buckets are in `docs/notes/oracle.md`; the ScreenToGif run is
  written up in `docs/notes/real-world-mining.md` ("Cross-tool validation"). A
  larger reactive-code run (WalletWasabi) has been exercised through the same CI
  harness but is **not yet distilled into a committed corpus artifact** — that
  distillation is exactly the benchmark-corpus backlog item below, not a
  documented result to lean on here.

## The LLM layer — our position (the load-bearing section)

This is the one place we **push back on the survey's framing**.

The hybrid pattern the doc endorses (InferROI / IRIS / MemHint) is: *LLM
proposes specs/summaries → deterministic core validates*. The **shape** is
right. But the doc still centers the LLM as a **spec source for detection**, and
that quietly puts LLM output in the **trusted base**: a wrong mined spec does not
produce a visible false finding you can argue with — it silently changes what
the checker *believes*, corrupting every downstream proof. A spec whose only
provenance is "the model said so" is `source: trust me bro`, and that is not an
acceptable trusted base.

Own.NET's safer division of labor:

1. **Deterministic fixes for the mechanical ~80%** — add the missing `-=`, wrap
   in `using`, cascade `Dispose`. No LLM in the loop at all.
2. **LLM strictly downstream of the verifier, as a falsifiable assistant** for
   the non-local ~20% and for **migration into the own.net model**. Every LLM
   output is a *hypothesis* that the deterministic core + compile + tests accept
   or reject. The LLM proposes; it never decides.

Why the **fix/refactor** role beats the **spec-source** role — the asymmetry is
the whole point:

- An LLM **fix** is *locally falsifiable*: re-run Own.NET + the test suite and
  observe. Wrong fixes are caught by the same checker that flagged the bug.
- An LLM **spec** is *trusted-base*: nothing locally re-checks it; it just
  changes the checker's beliefs. Wrong specs are **silent**.

So the refactor-assistant role is **safe by construction**; the spec-source role
is not. The verifier is what makes the LLM safe to use at all — the LLM is only
ever as trustworthy as the deterministic thing that re-checks its output.

Therefore, **if** a spec miner is built, it must be **validator-gated, never
trust-the-source**: each candidate spec is downgraded from "trusted" to
"candidate validated against the API body / call sites" — symbol exists, CFG
reachable, path feasible, consistent with observed uses. A candidate that cannot
be validated against a body is **dropped, not assumed**. That is exactly what our
existing deterministic miner already does (`_infer_param_effect` reads the body),
extended to boundary APIs — not the LLM-trust version. The LLM's only job there
is to *propose candidates faster* over the huge BCL/NuGet surface we will never
hand-spec; the validator, not the model, admits them.

The product shape this implies is a **fix-loop**, not a scanner: flag → LLM
proposes a multi-edit fix/refactor → re-run Own.NET + compile + tests →
accept/reject. Honest caveat: **green ≠ behavior-preserving**, so the loop needs
a **metamorphic conformance harness** (the doc's StaAgent / Statfier line) as the
check, not human trust.

### The deploy loop is a training loop (RLVR) — and its one trap

The fix-loop has a second payoff that falls out for free: **every
`proposal → verdict` pair is a labeled training example**, so the deployment
loop *is* a data-generation loop. This is **RL from Verifiable Rewards (RLVR)** —
the regime that carried the recent frontier math/code gains — and it fits here
unusually well:

- The reward comes from a **deterministic, sound verifier**, not a learned reward
  model. RLHF's reward model is itself a fallible LLM (noisy, gameable); our
  checker + compile + tests is ground truth, so the signal is clean — precisely
  the verifiable-domain regime where RLVR actually works rather than just markets.
- **No human-labeled dataset** — the checker manufactures the labels on real code.
- **Bootstrap is free**: the deterministic fixes (the mechanical ~80%) are
  *guaranteed-correct demonstrations* to SFT on; the LLM takes the non-local ~20%,
  the verifier filters. Flywheel: deploy → propose → verify → keep winners → train
  → better proposals.
- Cheapest stable form needs no RL infra — **rejection sampling**: draw N fixes,
  keep the ones that pass checker + compile + tests, fine-tune on the winners.
  GRPO/PPO with the verifier as reward is a later, sample-efficiency move.

**The trap — and it is the same caveat as everywhere above.** "Checker went
quiet" ≠ "bug fixed correctly". Optimize literally for that and the model learns
**reward hacking / Goodhart**: delete the resource, suppress the diagnostic,
weaken the code, remove the failing test — Own.NET green, behavior broken. This
is RLVR-for-code's documented failure mode (the model hacks the test suite, not
the task). So the **metamorphic harness stops being only a deployment check and
becomes part of the reward function**: the reward must be *checker-green AND
behavior-preserved* (metamorphic invariants / behavior-diff / held-out tests),
or you train a checker-gamer. The verifier sets both the **ceiling** (the model
cannot exceed what the verifier can check — it learns the blind spots as exploits)
and the **floor** (without behavior checks it degrades).

This re-confirms **fix > spec** from the training side too: a **fix** has a clean
verifiable reward (re-run checker + tests = the label); a **mined spec** has none
— its correctness is not locally checkable (trusted base), so there is nothing
sound to reward beyond consistency. The role worth training is the one we already
chose — the **refactor assistant, not the truth generator**.

## Concrete backlog this implies (recorded, NOT scheduled)

Ordered by leverage; each annotated with where it attaches and its real cost.

- **SARIF exporter.** Standard interchange (OASIS), GitHub-native code scanning,
  and — the under-sold reason — *scientific reproducibility* (frozen, diffable
  run artifacts). Cheap, high-leverage. **Attaches to** P-012 / the distribution
  surface (P-013).
- **Benchmark corpus as a first-class artifact.** Formalize the existing mining
  + oracle runs — the documented ScreenToGif differentiation
  (`real-world-mining.md`) plus the larger WalletWasabi run that currently lives
  only in CI artifacts — into a labeled (bug / no-bug / unknown), before/after,
  SARIF-harnessed corpus. This is the survey's strongest "this is a research
  contribution, not a hobby tool" lever, and we are already partway there (miner
  + oracle exist; what is missing is the committed, labeled artifact). **Extends**
  P-012. Highest research-value item on the shelf.
- **Metamorphic robustness harness.** Semantically-equivalent mutants (rename
  handlers, `lambda ↔ method-group`, reorder under no-semantic-change, add
  harmless branches) must yield **invariant** diagnostics modulo location. This
  is simultaneously (a) the conformance check that makes the LLM fix-loop
  trustworthy and (b) a separable contribution on its own. **New, far horizon.**
- **Validator-gated spec miner for boundary APIs.** Extend the existing
  deterministic `contract-inference` to BCL/NuGet acquire/release/transfer/
  borrow specs; LLM only as a candidate proposer *behind* the validator. **Far
  horizon, explicitly NOT trusted-base** (see the LLM section).

## What we deliberately do NOT take from the survey

- **The arXiv/paper roadmap** is fine as motivation and is recorded as context,
  but it is **not a code task** — no deliverable is filed off it here.
- **The full SUB/DIS/DI/BOR code-rename matrix** (SUB001, DIS001, …) overlaps the
  `WPFxxx → SUB/TMR/DISP` rename **already logged** in
  `consolidation-and-positioning.md`. Do **not** double-track it; that note owns
  the rename decision (fold into the OwnIR v1 / profile-config work, not a
  standalone churn PR).
- **The effects / typestate / session-types layer** stays far-horizon (P-008),
  exactly as the survey itself agrees. No move toward refinement types / general
  effect systems now.

## The actual priority (unchanged)

Same conclusion as `consolidation-and-positioning.md`, reached from the research
side instead of the form side: **prove value, don't reshape form or chase the
frontier.** Concretely — turn the subscription differentiation we already have
into a labeled, SARIF-emitting, reproducible **benchmark corpus**, and keep the
LLM strictly downstream of the deterministic core as a *falsifiable* fix/
refactor assistant. The one new technical brick worth its weight is the
**metamorphic harness**, because it is what lets us trust an LLM fix-loop at all.
