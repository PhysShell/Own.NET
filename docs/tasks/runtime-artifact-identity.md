# Task — enforce runtime artifact family identity and major-version validation

Status: **spec, ready to implement** — *not* scheduled into the current
sequence. See §8.

Derived from [`docs/notes/leaf-dmir-assessment.md`](../notes/leaf-dmir-assessment.md),
where the defect was measured rather than proposed. This closes a contract hole
in the runtime arm. It deliberately does **not** open the shared-envelope
question, which that note argues must come *after* per-family identity, not
before.

## 0. Goal

Make every analysis-facing runtime artifact carry a mandatory family identity
and major version, and make every reader reject an artifact it cannot identify.
Do **not** change collection semantics, analysis semantics, or SARIF output.

## 1. The defect (measured, not hypothetical)

Five producer implementations emit four analysis-facing artifact families. All
four have an identity problem:

| artifact family | producer(s) | identity today |
|---|---|---|
| heap-retention | `audit/runtime/RetentionPath` + `OwnAudit/src/OwnAudit.Runtime` | **two conflicting**: `own-runtime/1` vs `ownAudit/runtime/v1` |
| leak-growth | `audit/runtime/LeakHarness` | **none** |
| duplicate-immutable | `audit/runtime/DuplicateDetector` | **none** |
| propertychanged-storm | `audit/runtime/PropertyChangedStorm` | **none** |

And nothing validates any of it. `OwnAudit/runtime/correlate.py` consumes only
`retained / type / count / expected / bytes / roots / kind / holder / member`
and never reads `schema`. **Any JSON containing a `retained` array is currently
accepted as the heap-retention contract.** The single assertion that exists
(`HeapCollectorContractTests.cs:83`) checks one producer against itself.

The heap-retention split is a **lift-out artifact**, not stray junk: the
collector plan (2026-07-18) ports `stackpeek` into `OwnAudit.Runtime` while
`RetentionPath` remains canonical in Own.NET. Any fix must treat it as a
migration with a stated compatibility decision, not pick a winner silently.

## 2. Scope

**In scope**

1. Assign **one schema identity per shipped analysis-facing artifact family**
   (four families; names to be settled in review — not normative here).
2. Resolve the heap-retention identity conflict (`own-runtime/1` vs
   `ownAudit/runtime/v1`) with an **explicit** compatibility/migration
   decision covering both producers.
3. Make each reader reject: missing identity, wrong family, unsupported major.
4. Preserve forward compatibility: unknown **fields** under a known
   family + major stay accepted.
5. Negative fixtures/tests for every rejection case (§3).
6. Preserve collection semantics unchanged: refusal/failure → exit 2 → **no
   artifact**.

**Out of scope (explicitly do not do)**

- A common envelope across families. Deferred by design — commonality must be
  proven by the four shipped schemas first.
- Any schema-field unification beyond identity + version.
- A `completeness` / `PARTIAL` enum of any kind. Coverage semantics belong to
  the artifact family (see the note's three-way split), and heap-retention's
  contract may well stay total-or-no-artifact.
- Changes to acquisition: no `.dmp`/`.etl` normalization, no new capture paths.
- New runtime analyses or new artifact families.
- Any change to SARIF semantics or to `ingest.py` output.

## 3. Acceptance matrix (hard)

Happy path alone does not close this defect. Required cases:

| input | expected |
|---|---|
| correct family + supported major | accept |
| correct family + supported major + unknown extra fields | accept |
| missing `schema` | **reject** |
| `schema` of a different runtime family | **reject** |
| unknown major | **reject** |
| malformed required payload | **reject** |
| collector refusal | exit 2, no artifact — unchanged |

The load-bearing test, which is what actually proves the hole is closed:

> a **valid-looking `retained[]`** payload with a **wrong or missing `schema`**
> **MUST NOT** correlate.

Without that case the change is a decorative `if schema != ...`.

For the lift-out, one more:

> a legacy-producer artifact and a new-producer artifact must each have
> **explicitly specified** behaviour — accepted, rejected, or accepted with a
> recorded deprecation. Not left to whichever string was typed first.

## 4. Non-goals restated as a guard

If a reviewer or implementer finds themselves designing a field that every
family would share, **stop** — that is the envelope work this task defers, and
taking it here converts a small correctness fix into an architecture change.

## 5. Priority

**Small correctness debt, high leverage.** Not a blocker, not urgent.

- *Why file it:* the defect is real, tested cheaply, and its remediation cost
  grows with every new artifact family.
- *Why not drop everything:* `correlate.py` behaves predictably today and no
  false verdict from schema drift has been demonstrated. This is a latent
  contract hole, not a fire.

## 6. Repository boundary

The change spans both repos: producers in `Own.NET/audit/runtime/` and
`OwnAudit/src/OwnAudit.Runtime`, readers in `OwnAudit/runtime/`. The
heap-retention decision (§2.2) is the coupling point and should be settled once,
in one place, before either side is edited.

## 7. Risks / pitfalls

- **Picking a canonical string silently** breaks the other producer. §3's
  lift-out case exists to prevent exactly this.
- **Tolerant-reader drift**: rejecting unknown *fields* instead of unknown
  *identity* would break forward compatibility, which is a deliberate and
  correct property today.
- **Scope creep into the envelope** — see §4.

## 8. Sequencing

Record now, implement **after** the established boundary/gate work in flight.
This is explicitly not a blocker for the current PR sequence, and inserting it
there would turn a small fix into a detour.

### This file is the canonical surface — deliberately no issue yet

The lifecycle, decided when this spec was filed:

```text
finding            → docs/notes/leaf-dmir-assessment.md
demonstrated defect → THIS FILE  (spec, ready to implement)
                      ── no GitHub issue at this stage ──
boundary/gate work done, task enters the execution queue
                    → thin GitHub issue (execution handle only)
                    → implementation PR
                    → this spec becomes the historical record
```

**No issue exists today, on purpose.** Filing one now would create a second
status surface for work we are deliberately not scheduling, and two copies of
scope/acceptance to drift apart — the exact defect this task exists to fix,
reproduced in our own process.

There is a second reason to wait: §6 notes this spans both repositories and that
the heap-retention compatibility decision must be taken once, up front. Both
trees will move before this starts, so freezing execution metadata today buys
stale dependencies.

**When it is scheduled**, the issue is a *handle*, not a specification — it must
not restate scope or acceptance:

```text
Title: Enforce runtime artifact family identity and major-version validation

Canonical spec: docs/tasks/runtime-artifact-identity.md
Why now:        the sequenced boundary/gate work is complete; entering the queue.
Scope/acceptance: normative in the task spec. Do not duplicate here.
Depends/sequencing: <actual state at scheduling time>
Implementation PR: TBD
```

That keeps GitHub's real advantages — assignability, labels/milestone, queue
position, PR linkage, closure — without minting a second normative document.
