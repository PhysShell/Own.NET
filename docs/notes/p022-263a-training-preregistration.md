# P-022 / #263-A — training collection preregistration (step 6)

```text
Status:
  TRAINING PREREGISTRATION RECORDED.
  NO TRAINING COLLECTION HAS RUN.
  NO EMPIRICAL CONSTANT EXISTS.
  STEP 7 COLLECTION NOT AUTHORISED.
  STEP 8 FIT NOT AUTHORISED.
  HOLDOUT NOT AUTHORISED.
```

This document and `docs/evidence/calibration/p022-263a-training-preregistration.json`
fix the protocol of a training collection **that has not happened**. Step 6 contains
no clock, no observation, no fitted `A_abs` or `R_rel`, no selected `N` and no
width. It changes neither the frozen policy nor the measurement harness.

## The gap this step closed, and where it was

The owner's review found that platform had fallen between two levels of the model
rather than out of a report. Ratified §2.1 defines a cell as the four-part
`(rung, engine, workload, regime)` and says *no finer*. §3.3 then pools every cell
of the named universe into one fit per rung, and §3.4 turns that into one width and
one selected `N`. Meanwhile the instrument requires both Linux and Windows, and
§6.5 makes environment part of comparability while recording that a GitHub-hosted
runner has already shown itself not measurement-grade.

Nothing in the ratified text said whether the universe spans platforms. Three
readings all survived every sentence, and they disagree about whether an unstable
machine widens the bound a stable one must then live under. That is a statistical
model decision, so it went to the owner rather than being chosen here.

## The owner's ruling

**Platform is not a fifth cell axis.** The frozen four-part identity is unchanged.
Platform is an **outer training stratum**, and there are exactly two universes,
`U_linux` and `U_windows`.

Within a stratum, cold and warm remain distinct cells and every cell pools into one
fit per rung by the frozen fitter, unchanged. Across strata, observations, medians,
envelopes and widths are **never** pooled, averaged or summed. The result is
`E_p,N` and `W_p(N)` per platform, rather than one envelope inflated by the noisier
runner into a forgiving blanket.

**One global `N` all the same.** Each stratum computes its own admissible set

    Q_p = { N in the ladder : W_p(N) <= (1 + G) * min_N W_p(N) }

and the selection is the smallest ladder rung in `Q_linux ∩ Q_windows`. Three
alternatives are rejected by name. `max` of the per-stratum picks looks conservative
for about twenty seconds and can select a rung admissible under neither stratum's
margin. Averaging the widths lets an unstable platform buy a stable one a wider
tolerance with its own instability. Treating one platform as the reference puts the
other into D7 with no measurement model of its own.

**Empty intersection is a stop.** `NO_COMMON_N` is an **orchestration** refusal, not
a fifth reproducibility verdict: the frozen four describe cells and run pairs and
are untouched. There is no fallback rung, no stricter-platform tie-break, no second
`G` and no second fit.

## The combiner, and the one thing it refuses to do

`scripts/training/scope.py` exists because `Q_linux ∩ Q_windows` is code that takes
a statistical decision, and §3.6 requires such code to be written and
provenance-bound **before** the data it will judge. It lives outside
`scripts/calibration/` deliberately: the step 4 control proves the frozen root grew
no new file, and it would stop proving that if this landed inside it.

**It does not re-implement the `(1 + G)` test.** The frozen `select_n` already
computes the margin and reports `widths` and `limit` beside its own pick, so `Q_p`
is read back off that result. A second copy of the margin arithmetic would only ever
prove that the two copies agree, which is the defect this PR has spent thirteen
rounds removing. `training-scope-admissible` proves the reading is real rather than
incidental: it perturbs the `limit` the frozen function reported and requires the
combiner's answer to move. A combiner that recomputed the margin itself would ignore
that and pass.

On `NO_COMMON_N` the result carries **no** `selected_n` key at all, so a caller that
reads it without checking the outcome raises `KeyError` rather than proceeding on a
number the rule did not select.

### A control that could not tell a traceback from a finding, for the seventh time

`training-scope-refusals` was first written with a helper that caught bare
`Exception` and scored that as a refusal. Under the mutation that deletes the
strata-versus-selections check, the combiner then raised `KeyError` reaching for a
stratum that was not there, and the helper read that crash as the guard working.
The mutation came back MISSED, which is the only reason it was found.

This is the same family the ledger already records six times, in a file written
after all six. The helper now returns empty only for a refusal raised **by name**,
and reports anything else as the defect it is. Recorded rather than quietly fixed,
because the interval between knowing this lesson by heart and writing it wrong
again was, this time, about forty minutes.

## The forgotten stopwatch

The first version of this step was reviewed CHANGES REQUIRED, and the finding was
not in anything it added. It was in what CI had been doing all along.

The legacy calibration pair still ran in the same job: two real `--calibrate` runs
per platform, forty timed cells each, uploaded as workflow artifacts, on the very
commit whose preregistration said it took no new observation. "Step 7 has not run"
stayed true. "Step 6 produced no new timing or resource observation" did not, and
those are different sentences. I had checked that my own commit contained no clock
and never checked what the job I was extending already did.

That is worse than an idle diagnostic, because of what this document does. Once a
preregistration fixes **exactly one** collection and forbids choosing among
attempts, a CI job gathering numbers every twelve minutes is an epistemic side
channel whoever owns it and whatever they mean to do with the output.

**The rule is now unconditional**, and deliberately not phrased about dates:

> Every timing/resource observation produced outside the single owner-authorised
> Step-7 training collection is permanently inadmissible as fitting, N-selection,
> holdout, or D7 evidence, regardless of whether it predates or postdates this
> preregistration.

The earlier wording excluded only data recorded *before* this document, which would
have readmitted whatever a later rerun produced, on the entirely sincere ground
that it is just a diagnostic. The run 2038 artifacts from both platforms are
recorded in the artifact as `POST_PREREG_LEGACY_DIAGNOSTIC`,
`INADMISSIBLE_FOR_TRAINING`, `NEVER_FIT`, `NEVER_SELECT_N`.

**The timed pair is gone from CI** while step 7 is closed, along with the step that
read its report and the step that uploaded it. What still proves the apparatus is
untimed and unchanged: the instrument selftest, the instrument controls, the round 7
apparatus controls, the round 7 runner in plan mode, the decisive structural smoke,
and the policy, freeze, constants and preregistration controls.

**And the boundary is mechanical now, not remembered.**
`training-no-incidental-measurement` scans every executable line of every workflow
and fails if any reaches `perf_baseline.py --calibrate` or `runner.py --measure`
while the artifact still records step 7 as unauthorised. It reads that state from
the preregistration rather than from a constant here, so authorising step 7 is what
relaxes it, and nothing else. It also asserts both guarded flags still exist: a
control that passed because a flag had been renamed would be the proxy defect one
more time. A shell comment naming an entrypoint is allowed, because a comment
cannot execute.

Four mutations, each caught by that control or correctly allowed: the pair added
back to `ci.yml`, an entrypoint appearing in a *different* workflow, the flag
renamed out from under the guard, and a comment that merely mentions it.

### The same guard, with its polarity reversed

The first version of that control was reviewed FAIL-OPEN, and the finding was one
operator. It read `!= "NOT AUTHORISED"` and then returned **OK**, so the state
machine was really this:

    the exact refusal  -> gate closed
    everything else    -> gate open

A typo, a missing key after some later schema change, `null`, a `True`, the
American spelling, or simply the word `AUTHORISED` all meant permission to start a
clock. The enumerated schema did not save it either: that control proved the key
was *allowed to exist*, never what its value meant. Driven rather than argued, the
old code passed with `step_7_collection` set to `AUTHORISED` **and** a real timed
step added to `ci.yml`, announcing that it was standing down. The artifact could
authorise its own stopwatch by editing one string.

It now accepts exactly one state and fails on everything else, and there is
deliberately **no authorised branch at all**. Step 6 is a preregistration and
cannot open step 7: when step 7 is really authorised, a separate reviewed artifact
and a separate owner decision change the orchestration, rather than this document
mutating into a permission bit its own producer can flip. The permitted state is
also pinned as a frozen literal by the schema control, so two controls fail rather
than one. Nine mutations: the key missing, `AUTHORISED`, `AUTHORISEDD`, `null`,
`NOT AUTHORIZED`, `not authorised`, a space-padded copy, a boolean, and the
worst case of a claimed authorisation alongside a real timed step.

### And a second fail-open in the same control, found at re-review

The polarity fix was right and did not save the scan beside it. That scan required
the command name and the forbidden flag on the **same physical line**:

    if name in line and flag in line:

The repository's own Round 7 invocation is written across four lines, with
`--plan` on a continuation line by itself. Change that one word to `--measure` and
the line naming the script carries no flag while the line carrying the flag names
no script. Driven rather than argued: the mutation on the real block came back
MISSED, and the flag-existence check passed too, because nothing had been renamed.
A plan-only step becomes a real measurement by editing one word, and the guard
stays green. The safety mechanism was defeated by a line break.

The scan now matches the **flag alone**, with no coupling to any command name.
While step 7 is shut a capability token may not appear in executable workflow text
at all, wherever it is and whatever sits beside it, so continuations, variables and
quoting cannot get between the guard and the thing it guards. That is stricter than
naming invocations, and strictness is the correct default for this phase. Building
a shell parser to decide which occurrences *really* invoke something would be a
remarkably human way to answer a three-line problem with a small compiler.

Six cases, each caught or correctly allowed: the real Round 7 block with `--plan`
turned into `--measure`, a multiline `perf_baseline.py` with `--calibrate` on the
next line, the flag assigned to a shell variable, the flag reached through a
different command name entirely, the flag in a *different* workflow across lines,
and a shell comment that merely names it.

### And the mutant that found it is now a standing catcher

Those six cases lived in a scratchpad campaign, which is a memory rather than a
property of the repository. Restore the old conjunction and the live workflow still
says `--plan`: CI goes green and the suite never notices. Proving once that the
vest stops the bullet and then removing the bullet from the tests is a remarkably
comfortable form of rigour.

`training-scanner-catches-multiline` makes it permanent. The scan itself is now a
pure helper used in both places, so the control exercises the same implementation
the live check runs rather than a copy of it. The mutant is derived from the **real**
Round 7 block in `ci.yml`, located by following the script line through its
continuations, mutated in memory and never written to disk. Nothing in it runs a
clock.

It also fails closed on the two ways it could pass while testing nothing: if the
Round 7 invocation is inlined so no continuation carries `--plan`, and if the step
disappears altogether.

A first draft of this control searched the whole file for any `--plan`, and `ci.yml`
has a second one that is a `stale-plan.json` path in an unrelated stage 2 step. The
control passed by mutating that instead, and its success line claimed both belonged
to Round 7. Its own mutation reported MISSED, which is how it was found. The check
is now scoped to the Round 7 block and its message says only what it established.

## Three binding axes from here on

    policy_implementation_digest          c3068ed7fa88…
    measurement_harness_digest            562a7f7232da…
    training_scope_implementation_digest  614bf9efe6ba…

The third is new and is computed over every committed `*.py` under
`scripts/training/` with the **same framing** step 4 froze, imported rather than
restated. If the combiner changes after collection starts, the training corpus is
stale, with no discussion about it having been only a small change to an
intersection.

## The collection, fixed in advance

Per stratum, one preregistered environment identity covers the whole ladder: rungs
5, 15 and 45, five full runs each, over the complete universe of that stratum.
Fifteen runs per platform, thirty in total. Measuring one rung on one runner and
another rung on a different one would leave `N` as something other than the only
variable that changed.

Five runs per rung give exactly four observations per cell, from the consecutive
pairs `(r1,r2)`, `(r2,r3)`, `(r3,r4)`, `(r4,r5)` — not five convenient pairs chosen
once the outcome is visible. The universe is the 40 cells the frozen instrument
emits for the six `cal-*` workloads across five rungs, two engines and both regimes;
`training-prereg-universe` computes that from the manifest and the instrument rather
than trusting the number written here.

Execution order and its seed are fixed now. The seed is `c3068ed7fa880a70`, the
first sixteen hex digits of the policy digest the owner accepted at step 4 before
this document existed, so it is not a number that could have been re-rolled until
the order looked tidy.

**Exactly one collection.** Not the first satisfactory one of several. It carries a
durable identity from its first run and ends `ADMISSIBLE` or `INVALID` by rules
written here. There is no automatic retry because CI blinked; a repeat after an
abort needs a rule already in this document or a new owner ruling.

**If either stratum invalidates, the collection yields no admissible step 8 input.**
The surviving stratum's numbers remain durable evidence of what happened, and must
never become a single-stratum fallback model. That would be selection on
survivorship wearing a CI badge.

## What this does not authorise

Not the collection, not the fit, not the holdout. The validation pair remains a
separate owner decision, and this document deliberately does not describe it, so
that a training preregistration cannot quietly authorise a fresh validation run.
