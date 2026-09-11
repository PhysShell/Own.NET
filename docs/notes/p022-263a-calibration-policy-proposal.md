# P-022 / #263-A — calibration reproducibility policy, PROPOSAL

**Status: PROPOSAL. Nothing here is ratified, and nothing here is a number.**

This document freezes the *mechanism* by which two calibration runs are judged
to agree. It deliberately contains no constant values. Every quantity that will
eventually carry a number is named, given units and a sign convention, and left
empty, because a document that fixes a mechanism and a value in the same breath
is a document where the value was chosen by whoever was holding the pen.

No clock authority is claimed or implied. No measurement is proposed here.

## Why this document exists, in the frozen brief's own terms

#263-A §13 asks for an instrument, a `CALIBRATION_ONLY` validation report and a
fresh exact-head PASS. The instrument exists and passes. But §7 requires a
mechanical noise and outlier policy fixed **in advance**, together with a
determinism check, and §9 says that a second run on the same environment must
reproduce within that policy — otherwise the instrument is **not yet frozen**.

The repository's own record says plainly that this is not satisfied: the
committed sizing pairs do not reproduce reliably, the report-of-record glob is
empty, and `n=5` has passed and failed on this machine in no pattern. Reading
§13 while treating §9 as a decorative paragraph would be a very human way
through the gate, and dismantling exactly that move is what the last twelve
rounds were for.

So the blockage is not a missing file with the right name. **We need an
instrument that says compatible things twice**, and a written, mechanical
definition of "compatible" that was fixed before it was applied.

## 1. The object of admissibility

The policy decides exactly one question, about exactly one kind of input:

> Given **two calibration runs** of the **same instrument** on the **same
> environment** over the **same cell universe**, is the pair
> `reproducible`, `inconclusive`, or `invalid`?

It does **not** decide whether any engine is fast enough, whether a change is a
regression, or whether any workload meets any budget. Those are D7 questions and
§6 keeps them in a different document, behind a different freeze. See §7 below,
which states the separation as a rule rather than a hope.

The three verdicts are not interchangeable:

| verdict | meaning |
|---|---|
| `reproducible` | the two runs agree within the frozen policy; the instrument is behaving as an instrument |
| `inconclusive` | the runs are comparable and their agreement is neither clearly inside nor clearly outside the policy |
| `invalid` | the two runs are **not comparable**, so no statement about agreement is available at all |

`invalid` is not a bad score. It is a refusal to score, and it must never be
reported as a failure to reproduce — an incomparable pair says nothing about
the instrument, and calling it a failure would invite fixing it by re-running.

## 2. The frozen form

### 2.1 Statistic and granularity

- **Granularity: the cell.** A cell is the existing four-part identity
  `(rung, engine, workload, regime)`. No coarser unit, so a well-behaved cell
  cannot average away a badly behaved one; no finer unit, so nothing new has to
  be recorded.
- **Statistic: the cell's median** of its retained samples, in nanoseconds —
  the quantity the instrument already computes and commits as `median_ns`.
- **Retention** is governed by §6 below and by nothing else.

### 2.2 The comparison must be symmetric, and today it is not

Reproducibility is a **symmetric relation**: if run A agrees with run B, run B
agrees with run A. The incumbent rule is not symmetric. It computes

    rel = |m_B − m_A| / m_A

dividing by whichever run happens to have been recorded first. For a tolerance
`T` and a ratio `r = m_B / m_A`, the forward direction refuses when `r > 1 + T`
and the reversed direction refuses when `r > 1 / (1 − T)`. Since
`1 / (1 − T) > 1 + T` for every `T > 0`, there is always a non-empty band

    1 + T  <  r  <  1 / (1 − T)

in which **the verdict depends on which run was recorded first**. That is a
structural property of the form, true for any positive tolerance, and it does
not depend on the incumbent constant's value.

Nothing in the committed record turns on this — no verdict has been shown to sit
in that band — and this document does not go looking, because hunting through
recorded pairs for one that flips is selection on outcome wearing a lab coat. It
is reported as a defect of the *form*, and the replacement form removes it by
construction.

**The proposed comparison is symmetric in both terms:**

    Δ(c)      = |m_B(c) − m_A(c)|                     the observed change
    t(c)      = (m_A(c) + m_B(c)) / 2                 the reference duration
    bound(t)  = A_abs + R_rel · t                     the admissible change

`t` is the midpoint precisely so that swapping the runs changes nothing. Using
either run alone reintroduces the asymmetry; using the minimum would make the
bound depend on which run was slower, which is the same disease.

### 2.3 Why hybrid, and the honesty cost of saying so

A purely relative bound applies one fraction across a population spanning three
orders of magnitude. Round 6's exploratory reading — formally **O3,
inconclusive**, licensing nothing — observed that relative shift rises sharply
at the short end of the ladder while absolute drift does not stay constant
either. Round 7 then showed that a minimal real-process witness does not
reproduce the historical instability at all.

So the hybrid form is **chosen on data that has already been seen**. That is
permitted for choosing a *form* and forbidden for fixing *constants*, and it is
the whole reason §4's holdout firewall exists. This document states the
dependency rather than hiding it: if the form is wrong, the holdout is what will
say so, and the response to a failed holdout is §4, not a better fit.

`A_abs` carries nanoseconds. `R_rel` is dimensionless. Neither has a value here.

### 2.4 The three-way per-cell rule, and its inequalities

    Δ(c) ≤ bound(t(c))                  →  cell reproducible
    Δ(c) >  M · bound(t(c))             →  cell NOT reproducible
    otherwise                           →  cell inconclusive

with `M > 1` a single dimensionless widening factor. One factor rather than a
second independent pair of constants, because every extra constant is another
place a result can be steered.

The inequalities are fixed here and are not adjustable: the reproducible branch
is **inclusive** (`≤`) and the refusing branch is **strict** (`>`). A value
landing exactly on a boundary is therefore decided by the written rule and never
by a rounding direction.

Comparisons are performed in exact rational arithmetic, as `classify.py` already
does, so that an edge is decided by the rule rather than by binary floating
point.

### 2.5 Aggregation: precedence, never counting

A run pair's verdict is determined by strict precedence over its cells:

1. any cell `invalid`, or any pair-level invalidating condition in §6 → **pair `invalid`**
2. else any cell **not reproducible** → **pair NOT reproducible**
3. else any cell `inconclusive` → **pair `inconclusive`**
4. else → **pair `reproducible`**

**There is deliberately no tolerated-failure count.** A rule of the form "at most
`K` cells may fail" introduces a constant whose only function is to decide how
much disagreement to forgive, and it will be adjusted the first time `K + 1`
cells fail. The multiplicity problem this creates is real and is named rather
than solved by a knob: requiring every cell to agree over a large universe is a
strict family-wise condition, and the correct response is a bound that honestly
describes the instrument's own dispersion, not a budget of permitted failures.
If that proves impossible, the honest outcome is a failed policy under §4 and a
conversation with the owner, not a `K` that grows until the gate opens.

## 3. How the constants will be obtained

### 3.1 Design evidence and validation evidence are different corpora

**Design / training evidence** — already-seen calibration data, admissible for
choosing the form and fitting the constants:

- the Round 6 ladder and its full dataset
- the Round 7 dataset, every retained observation and accounting field
- the four committed sizing halves, stale and marked stale
- the preserved pre-contract artifacts under `docs/evidence/historical/`

**Validation evidence** — does not exist yet, is specified in §4, and may not be
drawn from anything above.

Using the training corpus to fit the constants and then citing the same corpus as
independent evidence that the policy works is the single move this document
exists to make impossible.

### 3.2 The fit consumes dispersion, never pass/fail labels

This is the load-bearing rule of the whole proposal.

The constants must be fitted to **the instrument's own observed variation as a
function of duration**, and to nothing else. They must **not** be fitted to
which historical pairs anyone believes should have passed.

The reason is that "which pairs should have passed" is a label applied after the
outcomes were seen. Fitting a tolerance to such labels is tolerance shopping
performed in a single step, and it would produce a constant that is guaranteed to
ratify the history it was derived from while predicting nothing.

Fitting to dispersion has no such property: the bound describes how much this
instrument moves when measuring the same thing twice, which is a claim about the
instrument that a fresh pair can falsify.

Concretely, the preregistered fitting procedure must state, before it is run:

- the exact subset of the training corpus it consumes, by committed file and sha256
- the response variable — observed `|Δ|` between comparable repeated measurements
- the predictor — the reference duration `t`
- the model — the `bound(t) = A_abs + R_rel · t` form frozen in §2
- the estimator — a **quantile** of the dispersion at level `q`, so the bound is
  an explicit coverage statement about the instrument rather than a best fit
- that the procedure is **deterministic**: same inputs, same constants, no seed,
  no manual adjustment, no re-run
- that its output is committed **before** any validation pair is recorded

`q` is a constant and has no value here.

### 3.3 Choosing N without escalating until it passes

The policy also fixes how the repetition count `N` is selected, and this is where
the obvious mistake lives.

**Forbidden:** "N is the smallest count at which the pair reproduces." That is
literally escalate-until-pass, and it converts the stop rule into a starting gun.

**Required:** `N` is chosen **before** the validation pair, from the fitted
dispersion model, as the smallest count on a preregistered ladder whose
*predicted* dispersion falls within `bound(t)` for every cell. The prediction is
made once, from training evidence, and committed. The validation pair then tests
that choice exactly once.

If the validation pair fails, `N` is **not** increased. §4 applies.

The ladder's values and its maximum are constants and have no values here.

## 4. The holdout firewall

After the mechanism is frozen and the constants are frozen by §3, and **before**
any validation measurement exists, a validation protocol is committed that fixes:

- the environment, by the recorded fingerprint of §6.5
- the cell universe
- `N` and the warmup discards
- that the pair is **exactly two runs**, recorded back to back
- that both halves are committed, pass or fail
- the verdict procedure, which is §2 applied mechanically

Then it is run **once**.

    validation pair reproducible   →  §7's gate may proceed
    validation pair inconclusive   →  reported as inconclusive; the gate does NOT open
    validation pair not reproducible → FAILED POLICY, returned to the owner
    validation pair invalid        →  the pair was not comparable; diagnose the
                                      incomparability, do not rescore it

**On a failure, the constants are not adjusted.** Not widened, not refitted, not
"re-estimated with the new data included". The policy is returned to the owner as
failed, with the evidence, and the next step is a design decision they make.
Refitting after seeing the holdout is tolerance shopping in a good suit, and it
is the exact failure mode this entire PR was built to prevent.

A second validation pair requires a separate authorisation, and a policy that
needed several attempts must say so in its own record.

## 5. What the instrument already fixes, and is carried forward unchanged

Stated so that the §7 contract below is complete rather than implied:

- **Warmup discards** are a policy default enforced by a control, not a knob, and
  the `warm` regime's discards are not retained in the dataset because discarding
  them is what the regime is.
- **Pair identity** is the existing ten-axis contract, and a mismatch raises
  rather than reporting a verdict.
- **Outcome identity precedes timing.** Two runs that agree to the nanosecond
  while exiting differently reproduced a coincidence, not a measurement.
- **Both halves of a pair are committed**, each naming the other, so a verdict can
  be recomputed instead of trusted.

## 6. The complete §7 contract

Every item below must carry an explicit decision, including an explicit "none".
A silently absent policy is the thing §7 forbids.

### 6.1 Warmup discards

Per regime, fixed in advance, enforced by a control, not tunable per run. The
current values are already policy and are carried forward.

### 6.2 Trimming and winsorizing: **none**

Stated as an explicit decision, not an omission. No trimmed mean, no winsorizing,
no outlier rejection of any kind on retained samples.

Every trimming rule carries a constant — how much to cut — and that constant is a
place to steer the result from. The statistic is already the median, which is
robust without discarding anything, and a sample that is genuinely wrong is the
business of §6.4's invalidating conditions, which refuse the run rather than
quietly improving it.

### 6.3 Noise floor

The existing opening and closing noise probes are carried forward as
**run-invalidating conditions**, not as reproducibility conditions. They bound
dispersion within one probe and drift between the opening and closing probes.
They are different statistical quantities from the reproducibility bound and are
not refitted by §3; this document does not propose new values for them.

### 6.4 Run-invalidating conditions

A run is `invalid`, and is never scored for reproducibility, when any of:

- an identity contract breach — the candidate, the arms, or the harness digest
  moved during the run
- an outcome contract breach — any spawn exited outside its declared contract
- a noise probe outside §6.3
- a required cell missing, unknown, or named twice
- a recorded field absent where the platform should have produced it

Each condition must name itself in the record, with the cell or spawn that
triggered it, and the run must leave a durable artifact saying so.

### 6.5 Same environment

A pair is comparable only if both halves carry the identical **environment
fingerprint**: the existing ten pair-identity axes, plus the recorded machine and
OS identity.

A fingerprint mismatch makes the pair `invalid`, **never** "not reproducible".
The instrument cannot cryptographically prove two runs happened on one machine;
it can record what it observed, and it must refuse rather than guess.

A GitHub-hosted Windows runner is already recorded as not measurement-grade —
two runs minutes apart on one commit disagreed about their own environment — so
the validation environment must be named explicitly in §4's protocol.

### 6.6 Determinism and the re-run rule

The verdict function is pure: same two committed reports in, same verdict out,
recomputable by anyone from the committed evidence. No clock, no network, no
filesystem state, no randomness.

§9's re-run rule is satisfied by §4's validation pair and by nothing else. In
particular it is **not** satisfied by any pair already in the repository, all of
which predate this policy.

## 7. Separation from D7, stated as a rule

| this policy decides | this policy never decides |
|---|---|
| whether two calibration runs agree | whether any engine is fast enough |
| whether the instrument may be frozen | any performance budget or regression bound |
| which `N` the instrument uses | any G3 metric's pass or fail |
| when a run is invalid | anything about a decisive workload |

Three consequences, binding:

1. No constant defined by this policy may be read by, copied into, or derived
   from any D7 threshold, and none may be used as one.
2. The output of this policy is **never** an input to a G3 verdict. It gates the
   instrument, not the result.
3. The incumbent reproducibility constant is **not** carried forward by
   assumption. It remains in force until §3 freezes a replacement and §4
   validates it; at that point its retirement is an owner decision, recorded.

## 8. The gate

```text
policy mechanism frozen            (this document, ratified)
        ↓
constants frozen by preregistered calibration procedure    (§3, no holdout data)
        ↓
validation protocol committed                              (§4, before measuring)
        ↓
fresh validation pair, run once
        ↓
reproducible under §7 contract?
   yes                          no / inconclusive
    ↓                                   ↓
#263-A PASS                      owner decision / redesign
                                 (constants are NOT adjusted)
```

## 9. Every deferred constant, with no value

| name | unit | what it bounds | fixed by |
|---|---|---|---|
| `A_abs` | nanoseconds | the duration-independent part of the admissible change | §3.2 |
| `R_rel` | dimensionless | the duration-proportional part | §3.2 |
| `q` | quantile level | the coverage the bound claims over the instrument's dispersion | §3.2 |
| `M` | dimensionless, `> 1` | the width of the inconclusive band | §3.2 |
| the `N` ladder | counts | the repetition counts the instrument may use | §3.3 |
| `N_max` | count | the ladder's mandatory stop | §3.3 |

Six names, no numbers. If a later revision of this document contains a value that
did not come from §3's procedure, that value was invented, and this table is
where it will be visible.

## 10. What this proposal does not do

It does not authorise any measurement, any re-record of the stale sizing pairs,
any calibration of record, the D7 freeze, #263-B, merge, Stage 3 or Stage 4. It
does not move the incumbent constants. It does not claim the instrument is
frozen — that is precisely what it is a plan to find out.

It is a mechanism awaiting ratification, and every number it will eventually need
is still missing on purpose.
