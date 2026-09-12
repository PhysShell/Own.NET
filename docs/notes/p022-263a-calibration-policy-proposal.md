# P-022 / #263-A — calibration reproducibility policy (revision 5)

```text
Status:
  MECHANISM RATIFIED.
  STEPS 1-3 COMPLETE.
  STEP 4 NOT YET FROZEN.
  NO DESIGN CONSTANT VALUES RATIFIED.
  NO NUMERIC FITTING CORPUS EXISTS.
  NO TRAINING OR VALIDATION MEASUREMENT AUTHORISED.
```

Revision 4 still opened with "PROPOSAL. Nothing here is ratified" and then, a few
lines down, correctly reported that the statistical architecture and the
`median |Δ elapsed| > 0` precondition had been ratified. A document that
contradicts itself about its own authority is a document whose authority cannot
be read off it, which is a poor property for the artifact a freeze will point at.
The status block above is the whole answer; the title no longer calls it a
proposal.

This document freezes the *mechanism* by which two calibration runs are judged to
agree. It contains no constant values. Every quantity that will eventually carry
a number is named, given units and a sign convention, and left empty, because a
document that fixes a mechanism and a value in the same breath is a document
where the value was chosen by whoever was holding the pen.

No clock authority is claimed or implied. No measurement is proposed here.

## Revision 5 — what the owner's fourth review changed

Revision 4 was ruled **CHANGES REQUIRED before the step 4 freeze**, on one P0 in
the implementation and one authority contradiction in this document. Neither
reopens any settled design.

| finding | fixed in |
|---|---|
| P0 — the exact-arithmetic boundary held at `DesignConstants.from_committed()` and nowhere else, so `Envelope`, `Observation` and `CellObservation` accepted floats, and `Fraction * float` is a float | §2.6 — every quantitative entry point refuses non-exact input, with the new `calib-exact-domain` control |
| authority — the header said "PROPOSAL. Nothing here is ratified" while the body reported the mechanism as ratified | the status block at the top of this document |

The P0 was real and worse than it reads: driven rather than argued, a float
entering through a dataclass made the **fitted `R_rel`** a float, along with the
bound and the comparison that decides the verdict. A module that had refused a
floating-point LP solver on exactness grounds was admitting floats through the
front door.

A float is now **refused, never converted**: `Fraction(0.1)` preserves the binary
error with impeccable fidelity, which removes nothing. An `int` is refused too —
it is exact, but `int / int` is a float in Python, so admitting it leaves a float
one ordinary division away.

## Revision 4 — what the owner's third review changed

Revision 3 was ruled **PASS WITH TWO MECHANICAL CORRECTIONS**, with the
statistical architecture **RATIFIED**. The owner also **ratified the
`median |Δ elapsed| > 0` precondition** that revision 3 had flagged as an
addition they might strike: without it the `work` rule has the same structural
zero-hole (`0 ≥ 0.5 × 0`) and reports a CPU mechanism where no wall-clock drift
exists at all. The value is structural, not empirical: if the quantity being
explained is zero, mechanism attribution has no subject.

| finding | fixed in |
|---|---|
| P0 — "no constant defaults" named only `q`, `M`, `G`, `A_abs`, `R_rel` as required arguments, so an implementation could hard-code `R_runs` or the `N` ladder without contradicting the sentence | §3.6 — one immutable `DesignConstants` carrying **all five** design constants, required, no defaults |
| P1 — §3.2 required every design constant in canonical *rational* form, but `R_runs` and the ladder's elements are semantically **counts** | §2.6 — representation split by kind: rationals as reduced pairs, counts as canonical integers |

Nothing else is reopened. The owner ratified the symmetric midpoint comparison,
the hybrid envelope, the exact quantile regression, the pooled fitting, the
four-way semantics, the no-`K` aggregation, the holdout firewall and the per-`N`
stratification with deterministic `N` selection as **settled**.

## Revision 3 — what the owner's second review changed

Revision 2 was ruled **PASS WITH MECHANICAL CORRECTIONS**: the statistical
architecture accepted, the mechanism not yet ratified, on two P0 findings and two
P1.

| finding | fixed in |
|---|---|
| P0 — exact arithmetic never said how a design constant is *written down*, so one implementation could read a decimal as a float and another as a rational | §2.6 — a canonical exact-rational representation, and a refusal for anything else |
| P0 — the sequence let the implementation be written after the training data existed, which is a steering surface even with the prose frozen | §3.6 — the implementation, its controls and its frozen digest all precede the training collection |
| P1 — the tie-break rationale claimed more than the rule guarantees | §3.3 — the claim is **withdrawn** with a counterexample; the rule stands as canonicalisation only |
| P1 — `N_max` duplicated the last element of a finite frozen ladder and could contradict it | removed throughout; the ladder's last element **is** the mandatory stop |

Nothing else is reopened. The owner ratified the symmetric midpoint comparison,
the hybrid form, the quantile regression, the pooling, the four-way semantics,
the no-`K` aggregation, the holdout firewall and the per-`N` stratification as
settled, and reopening a settled choice is its own kind of drift.

## Revision 2 — what the owner's first review changed

Revision 1 was ruled **CHANGES REQUIRED** with four P0 findings and one P1. The
form was ratified in principle; the mechanism was not, because a reasonable
statistical plan is not the same object as a single computable function, and the
space between those two is where knobs hide.

| finding | fixed in |
|---|---|
| P0 — the verdict universe contradicted itself: §1 declared three verdicts, §2.5 used a fourth | §1, §2.4, §2.5, §4, §8 — the set is now **four-way** throughout |
| P0 — the numeric training corpus mixed instruments: stale halves and `historical/` artifacts belong to superseded harness and identity contracts | §3.1 — a hard current-harness firewall, and §3.5, which states the uncomfortable consequence |
| P0 — the fit of `A_abs`/`R_rel`/`q`/`M` was under-specified: two reasonable people could implement it differently and both claim to have followed the document | §3.2 and §3.3 — empirical and design constants separated, and a complete enumerable algorithm |
| P0 — `N` selection was mathematically undefined: the model has no `N` in it | §3.4 — per-`N` envelopes and a deterministic selection rule |
| P1 — §6.3 inherited constants without naming their provenance | §6.3 — the source artifact, the digest that covers it, and why this policy may not touch them |

Three things were **not** reopened in revision 2 either: the symmetric midpoint
comparison, the hybrid absolute-plus-relative form, and the no-`K` aggregation.

## Why this document exists, in the frozen brief's own terms

§13 asks for an instrument, a `CALIBRATION_ONLY` validation report and a fresh
exact-head PASS. All three exist. But §7 requires a mechanical noise and outlier
policy fixed **in advance** together with a determinism check, and §9 says a
second run on the same environment must reproduce within that policy — otherwise
the instrument is **not yet frozen**.

The repository's own record says it does not: the committed sizing pairs do not
reproduce reliably, the report-of-record glob is empty, and `n=5` has passed and
failed on this machine in no pattern. The blockage is therefore not a missing
file with the right name. **We need an instrument that says compatible things
twice**, and a mechanical definition of "compatible" fixed before it is applied.

## 1. The object of admissibility

The policy decides exactly one question, about exactly one kind of input:

> Given **two calibration runs** of the **same instrument** on the **same
> environment** over the **same cell universe**, is the pair `reproducible`,
> `not-reproducible`, `inconclusive`, or `invalid`?

It does **not** decide whether any engine is fast enough, whether a change is a
regression, or whether any workload meets any budget. Those are D7 questions and
§7 keeps them behind a different freeze.

### The verdict set is four-way, at both levels

The same four names apply to a **cell** and to a **run pair**, and no other name
may appear anywhere in the policy, the implementation, or a report.

| verdict | meaning |
|---|---|
| `reproducible` | comparable, and the observed change is within the frozen inner bound |
| `not-reproducible` | comparable, and the observed change is outside the frozen **outer** bound |
| `inconclusive` | comparable, and the change lies between the inner and outer bounds |
| `invalid` | **not comparable**; no statement about agreement is available at all |

`invalid` is not a bad score. It is a refusal to score, and it must never be
reported as a failure to reproduce — an incomparable pair says nothing about the
instrument, and calling it a failure invites fixing it by re-running.

`not-reproducible` is the statistical failure. Keeping it distinct from `invalid`
is what lets §4's holdout branch mean something: only one of those two outcomes
is evidence about the instrument.

## 2. The frozen form

### 2.1 Statistic and granularity

- **Granularity: the cell** — the existing four-part identity
  `(rung, engine, workload, regime)`. No coarser, so a well-behaved cell cannot
  average away a badly behaved one; no finer, so nothing new must be recorded.
- **Statistic: the cell's median** of its retained samples, in nanoseconds — the
  quantity the instrument already computes and commits as `median_ns`.
- **Retention** is governed by §6 and by nothing else.

### 2.2 The comparison must be symmetric, and today it is not

Reproducibility is a **symmetric relation**. The incumbent rule is not. It
computes `|m_B − m_A| / m_A`, dividing by whichever run happened to be recorded
first. For tolerance `T` and ratio `r = m_B / m_A`, the forward direction refuses
when `r > 1 + T` and the reversed direction when `r > 1 / (1 − T)`. Since
`1/(1 − T) > 1 + T` for every `T > 0`, there is always a non-empty band

    1 + T  <  r  <  1 / (1 − T)

in which **the verdict depends on which run was recorded first**. That is a
property of the form, true for every positive tolerance, independent of the
incumbent constant's value, and verified exhaustively rather than asserted.

No committed verdict is known to sit in that band, and this document deliberately
does **not** go looking: hunting through recorded pairs for one that flips is
selection on outcome wearing a lab coat.

**The replacement is symmetric in both terms:**

    Δ(c)      = |m_B(c) − m_A(c)|                 the observed change
    t(c)      = (m_A(c) + m_B(c)) / 2             the reference duration
    bound(t)  = A_abs + R_rel · t                 the inner bound

`t` is the midpoint precisely so that swapping the runs changes nothing. Either
run alone reintroduces the asymmetry; the minimum makes the bound depend on which
run was slower, which is the same disease.

### 2.3 Why hybrid, and the honesty cost of saying so

A purely relative bound applies one fraction across a population spanning three
orders of magnitude. Round 6's exploratory reading — formally **O3,
inconclusive**, licensing nothing — observed that relative shift rises sharply at
the short end while absolute drift does not stay constant either.

So the hybrid form is **chosen on data that has already been seen**. That is
permitted for choosing a *form* and forbidden for fixing *constants*, which is
the entire reason §3.1's firewall and §4's holdout exist. If the form is wrong,
the holdout is what will say so, and the response is §4, not a better fit.

`A_abs` carries nanoseconds. `R_rel` is dimensionless. Neither has a value here.

### 2.4 The per-cell rule, and its inequalities

    cell invalid (see §6.4)              →  cell `invalid`
    Δ(c) ≤ bound(t(c))                   →  cell `reproducible`
    Δ(c) >  M · bound(t(c))              →  cell `not-reproducible`
    otherwise                            →  cell `inconclusive`

with `M > 1` a single dimensionless widening factor defining the outer bound. One
factor rather than a second independent pair of constants, because every extra
constant is another place a result can be steered.

The inequalities are fixed here and are not adjustable: the reproducible branch
is **inclusive** (`≤`) and the refusing branch is **strict** (`>`). A value
landing exactly on a boundary is decided by the written rule, never by a rounding
direction. All comparisons are performed in **exact rational arithmetic**, as
`classify.py` already does, so an edge is decided by the rule rather than by
binary floating point.

### 2.5 Aggregation: precedence, never counting

A run pair's verdict is determined by strict precedence over its cells:

1. any cell `invalid`, or any pair-level invalidating condition in §6 → pair **`invalid`**
2. else any cell `not-reproducible` → pair **`not-reproducible`**
3. else any cell `inconclusive` → pair **`inconclusive`**
4. else → pair **`reproducible`**

**There is deliberately no tolerated-failure count.** A rule of the form "at most
`K` cells may fail" introduces a constant whose only function is to decide how
much disagreement to forgive, and it will be adjusted the first time `K + 1`
cells fail. The multiplicity problem this creates is real and is named rather
than solved by a knob: requiring every cell to agree over a large universe is a
strict family-wise condition, and the correct response is a bound that honestly
describes the instrument's own dispersion, not a budget of permitted failures. If
that proves impossible, the honest outcome is a failed policy under §4 and a
conversation with the owner, not a `K` that grows until the gate opens.

### 2.6 How a constant is written down

Revision 2 insisted on exact rational arithmetic and then left the constants as
"a dimensionless number", which settles nothing: a value written as a decimal —
say `0.95`, used here only as an illustration and not as a proposed value — is
read by one implementation as a binary float and by another as `19/20`, and the
two then disagree on every boundary case. That is a particularly silly gap in a document that already
refused a floating-point LP solver on exactness grounds.

**Every rational quantity in this policy — design constant, empirical constant,
and every intermediate — is represented canonically as a pair of integers:**

    numerator, denominator
    denominator > 0
    gcd(|numerator|, denominator) = 1

The reduced form with a positive denominator is unique, so the representation is
itself canonical and two implementations cannot disagree about what was frozen.

Binding consequences:

- a constant is **committed as that integer pair**, never as a decimal string and
  never as a float
- reading, writing or comparing any of these quantities through a binary
  floating-point value is a **refusal**, not a rounding difference
- the admissible ranges are expressed on the pair: `q` in `(0, 1)` means
  `0 < numerator < denominator`; `M > 1` means `numerator > denominator > 0`;
  `G ≥ 0` means `numerator ≥ 0`
- `A_abs` is a rational count of nanoseconds in the same canonical form. It is
  not rounded to an integer: rounding it would be an undeclared adjustment to a
  bound, in whichever direction the rounding happened to go

**Counts are not rationals, and are not written as though they were.** Revision 3
required *every* design constant in the reduced-pair form, which would have left
a reader working out whether `N = 15` is the pair `(15, 1)` or the integer `15`.
Representation is therefore fixed **by kind**:

| quantity | canonical form |
|---|---|
| `q`, `M`, `G` | reduced rational pair, denominator `> 0` |
| `A_abs(N)`, `R_rel(N)` | reduced rational pair, denominator `> 0` |
| `R_runs` | a canonical **integer**, `≥ 2` |
| the `N` ladder | a finite, ordered list of canonical **positive integers** |

This is a serialization and provenance correction. It changes no statistic, no
rule and no boundary.

## 3. How the constants will be obtained

### 3.1 Three corpora, and a firewall between them

**Form evidence** — already-seen data. It may motivate or select the model
**form** and **may not contribute numerically to any fitted constant**:

- the Round 6 ladder and dataset
- the Round 7 dataset
- the four committed sizing halves, stale and marked stale
- the preserved pre-contract artifacts under `docs/evidence/historical/`

**Numeric fitting corpus** — must satisfy **all** of:

- produced under the **exact current harness digest**
- produced under the **current identity contract**
- produced under the **current outcome contract**
- drawn from a **named calibration-only workload universe**, named in the
  training preregistration before collection, containing no decisive workload

**Validation corpus** — fresh, **disjoint** from the fitting corpus, collected
only **after** the constants are frozen and committed.

Why the firewall is drawn at the harness digest and not at "it came out of the
same stopwatch": Round 7 is a process-shape A/B/C experiment, not a repeated
calibration population; the stale halves were recorded under superseded harness
identities. Measuring soup with a thermometer does not calibrate it for a child.
A number came out, technically.

Using the fitting corpus to fit and then citing it as independent evidence that
the policy works is the single move this document exists to make impossible.

### 3.2 Two kinds of constants, with different origins

Revision 1 put all six in one table, which hid the fact that they come from
different places. `q` in particular cannot be "fixed by the fitting procedure",
because `q` is what *tells* the fitting procedure which quantile to estimate;
saying otherwise was circular.

**Empirical constants** — derived from the fitting corpus by the deterministic
estimator in §3.3:

| name | unit | meaning |
|---|---|---|
| `A_abs` | nanoseconds | the duration-independent part of the inner bound |
| `R_rel` | dimensionless | the duration-proportional part |

**Design constants** — **owner decisions**, ratified with a stated rationale, and
**frozen before the fitting corpus is collected**, not merely before the fit.
Freezing them only before the fit would still let them be chosen to flatter data
already in hand.

| name | unit | what it decides |
|---|---|---|
| `q` | quantile level in `(0, 1)` | which quantile of the instrument's dispersion the inner bound claims to cover |
| `M` | dimensionless, `> 1` | the width of the inconclusive band, as the outer bound's multiple of the inner |
| `R_runs` | count, `≥ 2` | how many repeated runs per cell the fitting corpus collects |
| the `N` ladder | a **finite**, ordered, frozen list of counts | the repetition counts the instrument may use; **its last element is the mandatory stop**, and there is no separate maximum — a second knob there would express nothing but a future argument about which maximum wins |
| `G` | dimensionless, `≥ 0` | the diminishing-returns margin used by §3.4 to select `N` |

No design constant may be derived from the fitting corpus, none has a value here,
and each is written in the canonical exact-rational form of §2.6 when it is
eventually ratified.

### 3.3 The empirical fit, specified as a single computable function

The response and predictor, fixed:

- the fitting corpus yields, per cell, `R_runs` runs in recorded order
- an **observation** is a **consecutive** run pair `(k, k+1)`, giving `R_runs − 1`
  observations per cell. Consecutive rather than all pairs, because all-pairs
  observations are not independent and would silently over-weight cells, and
  because a second run following a first is exactly what §9 tests
- for each observation: `y = |m_{k+1} − m_k|` and `t = (m_k + m_{k+1}) / 2`,
  the same `Δ` and `t` that §2.2 uses at verdict time
- **within one ladder rung, the observations from every cell in the named
  universe `U` are pooled into a single fit.** One envelope per rung, not one per
  cell: a per-cell envelope would have as many constant pairs as cells and would
  fit each cell's own noise, which is how a bound stops being a bound
- all arithmetic is exact rational

Given the frozen `q`, the constants are the solution of a **non-negative linear
quantile regression**:

    minimise    L(a, r) = Σ_i ρ_q( y_i − (a + r · t_i) )
    subject to  a ≥ 0 ,  r ≥ 0
    where       ρ_q(u) = q · u        for u ≥ 0
                ρ_q(u) = (q − 1) · u  for u < 0

A bound must not be negative anywhere on the duration range, which is what the
two constraints say.

**The solution is found by exact vertex enumeration, not by a numerical solver.**
A floating-point LP solver is not reproducible across platforms or library
versions, and this policy must produce identical constants from identical bytes
on Linux and on Windows. The objective is piecewise-linear and convex and the
feasible region is a polyhedron, so an optimum is attained where **two** of the
following conditions are active:

- a residual condition `a + r · t_i = y_i` for some observation `i`
- the bound `a = 0`
- the bound `r = 0`

The candidate set is therefore finite and enumerable:

1. for every pair of observations `i < j` with `t_i ≠ t_j`, the line through both:
   `r = (y_j − y_i) / (t_j − t_i)`, `a = y_i − r · t_i`
2. for every observation with `t_i ≠ 0`, the point `a = 0`, `r = y_i / t_i`
3. for every observation, the point `r = 0`, `a = y_i`
4. the corner `a = 0`, `r = 0`

Candidates violating `a ≥ 0` or `r ≥ 0` are discarded. `L` is evaluated exactly
at each survivor and the minimum is taken.

**The tie-break is load-bearing, not ceremony.** The optimum of a quantile
regression need not be unique — an entire face of the polyhedron can attain it.
Over three hundred randomly generated datasets, the optimum was non-unique in
thirty-four of them, and the tied solutions disagreed in the intercept by a wide
margin. Without a stated tie-break, two correct implementations of this document
would return materially different constants and both would be entitled to say
they followed it. That is precisely the defect this revision exists to remove.

**Tie-break, in order.** Among all objective minimisers represented by the
enumerated candidate set:

1. choose the smallest `A_abs`;
2. among those, choose the smallest `R_rel`.

This is a deterministic **canonicalisation** rule. It does not claim pointwise
dominance over every other minimiser. Its purpose is identical constants from
identical corpus bytes, and that is the whole of its purpose.

**A claim about this rule is withdrawn.** Revision 2 asserted that "a tie is
never resolved in the direction that makes the gate easier to pass". That is
false, and not merely overstated. Tied optima need not share a slope, so a
smaller intercept can come with a steeper one, and the two lines cross. A
concrete witness, found by search rather than argued: observations
`(t, y) = (8, 20), (8, 10), (3, 11)` at `q = 1/2` have two tied minimisers at
equal loss — `A_abs = 28/5, R_rel = 9/5` and `A_abs = 11, R_rel = 0`. The rule
selects the first, which is **looser** than the second for every `t > 3`.

The moral is the one this project keeps paying for: a rule may be perfectly good
at its actual job while the sentence justifying it quietly promises something
else. The rule stays; the promise goes. And no scalar tie-break by envelope area
or summed width replaces it, because that would introduce a second objective
nobody asked for, on top of the one that already decides.

**Fail-closed conditions of the fit**, each refusing rather than guessing:

- fewer than two distinct `t` values in the corpus → the two-parameter model is
  not identifiable; refuse
- any observation with a non-finite or negative `y` → refuse; `y` is an absolute
  difference and cannot be negative
- an empty candidate set after the feasibility filter → refuse

### 3.4 Selecting `N`, with `N` actually in the model

Revision 1 required choosing the smallest `N` whose *predicted dispersion* fell
within `bound(t)`, while the model `A_abs + R_rel · t` contains no `N` at all.
There was nothing to predict with. The finding is accepted without reservation.

**The rejected repair** is to give the model a closed-form `N`-dependence — a
`1/√N` term, say. That would import the assumption that the dominant variability
is sampling uncertainty of the median, which is exactly the proposition Round 6
declined to establish and named as its own alternative. A functional form nobody
has evidence for is not a repair; it is the same missing knowledge written in
mathematical notation.

**The adopted repair:** `N` enters as a **stratum**, not a parameter.

- the fitting corpus is collected at **every** `N` on the preregistered ladder
- §3.3 is run **independently per `N`**, yielding one frozen envelope per rung:
  `E_N(t) = A_abs(N) + R_rel(N) · t`
- define each cell's reference duration at that rung as the **median of that
  cell's `R_runs` recorded medians**, written `t_c(N)`. A cell has several
  medians in the fitting corpus, so "the cell's duration" is otherwise not a
  single number, and a rule that does not say which one is a rule two
  implementations will answer differently
- define the scalar width of a rung over the named calibration workload universe
  `U`:

      W(N) = Σ over c in U of E_N( t_c(N) )

- let `W_min` be the smallest `W(N)` over the ladder
- **select the smallest `N` on the ladder with `W(N) ≤ (1 + G) · W_min`**

This is deterministic, consumes only the fitting corpus, and never touches
validation data. It is well defined: the rung achieving `W_min` always satisfies
the inequality for any `G ≥ 0`, so a selection always exists and there is no
undefined branch.

It also cannot become escalate-until-pass. `N` is fixed **before** the validation
pair exists, from training evidence alone, and is not revisited afterwards. The
forbidden rule — "the smallest `N` at which the pair reproduces" — turns the stop
rule into a starting gun, and is why this section exists in this form.

`A_abs(N)`, `R_rel(N)` and the selected `N` are all committed together before §4
begins.

### 3.5 The uncomfortable consequence: no admissible fitting corpus exists today

§3.1's firewall, applied honestly to what this repository holds, says that
**there is currently no admissible numerical fitting corpus** for this policy
under the current harness identity. Everything on hand is form evidence.

This is a normal outcome, not a setback, and the response is not to squeeze
constants out of the museum exhibit in `historical/`.

### 3.6 The implementation is written before the data, not after

Revision 2 jumped from a ratified mechanism straight to a measurement, leaving
the code that applies the policy to be written afterwards. That is a steering
surface even when the prose is frozen: an implementation written with the
training data already on disk can be nudged, in a hundred defensible small ways,
toward the answer its author has already seen.

So the implementation, its controls and its **frozen digest** all precede the
training collection. And its provenance is not softer than the instrument's:
**code that decides admissibility must not have weaker provenance than code that
starts the stopwatch.**

- if the implementation changes `perf_baseline.py` or any source covered by the
  **measurement-harness digest**, that digest moves — necessarily **before** any
  training data exists, never after
- if it lives separately and the harness is untouched, that is equally fine, but
  its **own digest becomes a mandatory identity axis** for the fit, for the
  constant freeze and for the validation pair, exactly as the harness digest is

The required sequence, each numbered step a separate owner decision:

```text
 1. mechanism RATIFIED                        (docs only; this document)
 2. implement pure policy / fitter / verdict  (NO constant defaults anywhere)
 3. mutation + control review, exact-head CI  (the implementation's own adversary)
 4. freeze policy-implementation digest
    AND measurement-harness digest            (both, before any corpus exists)
 5. ratify the exact-rational design constants
    q, M, R_runs, the finite N ladder, G      (owner decision; no data consulted)
 6. preregister the numeric training collection,
    bound to BOTH frozen digests              (before it is run)
 7. separate authority -> ONE training collection   (a measurement)
 8. deterministic fit per rung, select N per §3.4   (no new data)
 9. freeze the empirical constants                  (committed)
10. commit the fresh holdout protocol               (before any validation data)
11. separate authority -> ONE validation pair       (a measurement)
12. four-way verdict per §4
```

Step 2 carries **no constant defaults**, and that has to cover the whole design
set rather than the constants that happen to appear in a formula. Revision 3
named only `q`, `M`, `G`, `A_abs` and `R_rel`, which left an implementation free
to hard-code `R_runs` or the `N` ladder without contradicting a word of it — and
those two decide the corpus cardinality and the `N` selection outright. That is
precisely the steering surface this section exists to remove.

**All five design constants travel together in one immutable object**, required,
with no default anywhere:

```text
DesignConstants
    q          reduced rational pair,  0 < numerator < denominator
    M          reduced rational pair,  numerator > denominator > 0
    R_runs     canonical integer,      >= 2
    N_ladder   finite ordered list of canonical positive integers
    G          reduced rational pair,  numerator >= 0
```

Who consumes what, so that no argument is carried merely for symmetry:

- the **fitter** uses and validates `q`, `R_runs` and `N_ladder`
- the **selector** uses `G`
- the **verdict** uses `M`
- `A_abs(N)` and `R_rel(N)` are the fitter's **empirical outputs** and the
  verdict's **required inputs**; they are never design constants and never
  carry a default either

No dormant parameters are added for the sake of a tidy signature.

Steps 7 and 11 are measurements and neither is authorised by this document.
Step 5 precedes step 6 deliberately: design constants chosen after seeing the
training corpus would be design constants chosen to flatter it.

## 4. The holdout firewall

After the mechanism is frozen, the design constants are ratified, and the
empirical constants are frozen by §3.3 and §3.4, and **before** any validation
measurement exists, a validation protocol is committed fixing:

- the environment, by the recorded fingerprint of §6.5
- the cell universe
- the selected `N` and the warmup discards
- that the pair is **exactly two runs**, recorded back to back
- that both halves are committed, whatever the verdict
- the verdict procedure, which is §2 applied mechanically

Then it is run **once**.

| holdout verdict | consequence |
|---|---|
| `reproducible` | §8's gate may proceed |
| `inconclusive` | reported as inconclusive; the gate does **not** open |
| `not-reproducible` | **FAILED POLICY**, returned to the owner with the evidence |
| `invalid` | the pair was not comparable; diagnose the incomparability, do **not** rescore it |

**On `not-reproducible` the constants are not adjusted.** Not widened, not
refitted, not re-estimated with the new data folded in. Refitting after seeing
the holdout is tolerance shopping in a good suit, and it is the exact failure
mode this entire PR was built to prevent.

A second validation pair requires separate authorisation, and a policy that
needed several attempts must say so in its own record.

## 5. What the instrument already fixes, carried forward unchanged

- **Warmup discards** are a policy default, not a knob. The source comment records
  why: warmup was once moved from two to three alongside a repetitions escalation
  that had been authorised on its own, turning one permitted knob into two turned
  after seeing which runs went red.
- **Pair identity** is the existing ten-axis contract, and a mismatch raises
  rather than reporting a verdict.
- **Outcome identity precedes timing.** Two runs agreeing to the nanosecond while
  exiting differently reproduced a coincidence, not a measurement.
- **Both halves of a pair are committed**, each naming the other, so a verdict can
  be recomputed instead of trusted.

## 6. The complete §7 contract

Every item carries an explicit decision, including an explicit "none". A silently
absent policy is the thing §7 forbids.

### 6.1 Warmup discards

Per regime, fixed in advance, enforced by a control, not tunable per run. The
current values are already policy and are carried forward unchanged.

### 6.2 Trimming and winsorizing: **none**

An explicit decision, not an omission. No trimmed mean, no winsorizing, no
outlier rejection of any kind on retained samples.

Every trimming rule carries a constant — how much to cut — and that constant is a
place to steer from. The statistic is already the median, robust without
discarding anything, and a sample that is genuinely wrong is the business of
§6.4's invalidating conditions, which refuse the run rather than quietly
improving it.

### 6.3 Noise floor, and the provenance of its inherited constants

The opening and closing noise probes are carried forward as **run-invalidating
conditions**, not as reproducibility conditions. They bound dispersion within one
probe and drift between the opening and closing probes. They are different
statistical quantities from the reproducibility bound and are **not** refitted by
§3.

**Provenance, stated exactly**, because "carried forward" in a document that
claims to contain no numbers otherwise invites the later question of whether
these were new constants or merely already lying about:

- **Where they live:** `NOISE_PROBE_MAX_RELATIVE_IQR` and `NOISE_PROBE_MAX_DRIFT`
  in `scripts/perf_baseline.py`, together with `DEFAULT_WARMUP_DISCARDS` and
  `DEFAULT_CALIBRATION_REPETITIONS`.
- **What covers them:** the content-addressed **harness digest**, `562a7f7232da`
  at this head. Those constants are part of the hashed instrument sources, so the
  digest is a commitment to their values.
- **Who froze them:** they are incumbent ratified policy, in force before this
  document existed, and D7's C1 freezes the harness digest that covers them.
- **Why this policy may not change them:** changing any of them **moves the
  harness digest**, which stales every pair ever recorded against the old value
  and un-compares every future number from every recorded one. A reproducibility
  policy that silently re-based the instrument while defining reproducibility
  would be worse than no policy.

This document therefore **inherits** them and does not introduce, re-derive or
propose values for them. Their retirement or replacement is a separate owner
decision with its own re-record cost, and is out of scope here.

### 6.4 Invalidating conditions, at two levels

§2.4 and §2.5 both consume this section, and they consume different halves of it,
so both are stated.

**Cell-level — the cell is `invalid` and is never scored:**

- the cell's recorded outcome is not valid in either run
- the two runs disagree about the cell's observed exit code or outcome validity;
  they did not measure the same thing, so their durations are not comparable
- the cell produced no median in either run
- the cell is present in one run and absent from the other

**Pair-level — the whole pair is `invalid`, whatever its cells say:**

- an identity contract breach — the candidate, the arms, or the harness digest
  moved during either run
- an outcome contract breach — any spawn exited outside its declared contract
- a noise probe outside §6.3
- an environment fingerprint mismatch under §6.5
- a required cell missing, unknown, or named twice in either run
- a recorded field absent where the platform should have produced it

Each condition names itself in the record, with the cell or spawn that triggered
it, and the run leaves a durable artifact saying so.

### 6.5 Same environment

A pair is comparable only if both halves carry the identical **environment
fingerprint**: the existing ten pair-identity axes plus the recorded machine and
OS identity.

A fingerprint mismatch makes the pair `invalid`, **never** `not-reproducible`.
The instrument cannot cryptographically prove two runs happened on one machine;
it can record what it observed, and it must refuse rather than guess.

A GitHub-hosted Windows runner is already recorded as not measurement-grade — two
runs minutes apart on one commit disagreed about their own environment — so the
environment must be named explicitly in §4's protocol and in the step 6 training
preregistration.

### 6.6 Determinism and the re-run rule

The verdict function is pure: same two committed reports in, same verdict out,
recomputable by anyone from committed evidence. No clock, no network, no
filesystem state, no randomness.

The **fitting** procedure is equally pure: same corpus bytes in, same
`(A_abs, R_rel)` out, on any platform, by §3.3's exact enumeration and tie-break.

§9's re-run rule is satisfied by §4's validation pair and by nothing else. In
particular it is **not** satisfied by any pair already in the repository, all of
which predate this policy and most of which predate the current harness identity.

## 7. Separation from D7, stated as a rule

| this policy decides | this policy never decides |
|---|---|
| whether two calibration runs agree | whether any engine is fast enough |
| whether the instrument may be frozen | any performance budget or regression bound |
| which `N` the instrument uses | any G3 metric's pass or fail |
| when a run is invalid | anything about a decisive workload |

Three binding consequences:

1. No constant defined by this policy may be read by, copied into, or derived
   from any D7 threshold, and none may be used as one.
2. The output of this policy is **never** an input to a G3 verdict. It gates the
   instrument, not the result.
3. The incumbent reproducibility constant is **not** carried forward by
   assumption. It remains in force until §3 freezes a replacement and §4
   validates it; its retirement is then an owner decision, recorded.

## 8. The gate

```text
policy mechanism frozen                     (this document, ratified)
        ↓
pure implementation written, mutation-reviewed, CI green
        ↓
policy-implementation digest AND measurement-harness digest frozen
        ↓
design constants ratified as exact rationals   (§2.6, §3.2; no data consulted)
        ↓
training collection preregistered against both digests, authorised, run once
        ↓
empirical constants frozen per rung, N selected   (§3.3, §3.4; deterministic)
        ↓
validation protocol committed               (§4; before any validation data)
        ↓
ONE fresh validation pair
        ↓
four-way verdict under §2 and the §6 contract
   reproducible          inconclusive / not-reproducible / invalid
        ↓                              ↓
   #263-A PASS              owner decision / redesign
                            (constants are NOT adjusted)
```

## 9. Every constant, with no value

**Empirical — output of §3.3, one pair per ladder rung:**

| name | unit | fixed by |
|---|---|---|
| `A_abs(N)` | nanoseconds | §3.3, from the fitting corpus at rung `N` |
| `R_rel(N)` | dimensionless | §3.3, from the fitting corpus at rung `N` |

**Design — owner decisions under §3.2, frozen before any corpus is collected:**

| name | unit | fixed by |
|---|---|---|
| `q` | quantile level in `(0, 1)` | owner ratification |
| `M` | dimensionless, `> 1` | owner ratification |
| `R_runs` | count, `≥ 2` | owner ratification |
| the `N` ladder | finite ordered list of counts; last element is the mandatory stop | owner ratification |
| `G` | dimensionless, `≥ 0` | owner ratification |

**Inherited — not set, not re-derived, not proposed here:** the noise-probe
limits, the warmup discards and the default calibration repetitions, all covered
by harness digest `562a7f7232da` per §6.3.

No numbers. If a later revision contains a value that did not come from §3.3 or
from a recorded owner ratification, that value was invented, and these tables are
where it will be visible.

## 10. What this proposal does not do

It does not authorise any measurement — not the training collection at step 7,
not the validation pair at step 11. Steps 2 and 3 are done and step 4, the
digest freeze, is the next thing awaiting the owner's word; this document does
not grant it. It does not re-record the stale sizing pairs, promote a
calibration of record, freeze D7, unblock #263-B, merge, or start Stage 3 or
Stage 4. It does not move any incumbent constant, and it still contains no
values.

It does not claim the instrument is frozen. It is a plan to find out, and every
number it will eventually need is still missing on purpose.
