# A loop-invariant call costs between 1× and 1092× — and only runtime knows which

Working note. **Trigger:** the follow-up to
[`llvm-codegen-feasibility.md`](llvm-codegen-feasibility.md). That note closed
with "loop-invariant expensive query inside a loop is a static-analysis target,
not a codegen target". The objection that followed is correct and is the reason
this note exists:

> Statically we can reach the *shape*. But we will not know what actually
> happens at runtime — and that is the killer feature. RyuJIT may handle it
> fine, or it may not, as in the case where it was crawling. Static analysis
> says "this could be suboptimal"; only measurement says **how bad**.

This note measures the spread, and it is wider than the objection assumed.
Harness in [`invariant-cost-data/`](invariant-cost-data/), `run.sh` reproduces.

## Method

Four call shapes, each written twice — evaluated inside the loop vs hoisted by
hand — over collection sizes 4 … 100 000, inner loop fixed at 1000 iterations.
`penalty = inline / hoisted`. Both variants are asserted to return the same
value. .NET 9.0.316, `DOTNET_TieredCompilation=0`, steady state.

**Every row is the same syntactic shape**: a loop-invariant call in a loop body.
A static rule matching that shape sees all of them as one finding.

## Result

| shape | n=4 | n=64 | n=4 096 | n=100 000 |
|---|---|---|---|---|
| `A: Any(x => x > t)` — predicate hits at element 0 | 2.8× | 12.6× | 11.1× | **8.3×** |
| `A: Any(x => x > t)` — predicate never hits | 12.2× | 164× | 898× | **1025×** |
| `B: Count()` on `IEnumerable` | 53× | 347× | 936× | 1025× |
| `C: OrderBy().First()` | 362× | 822× | 1092× | 1003× |
| `D: .Count` property (O(1)) | 1.0× | 1.0× | 1.0×¹ | 1.0× |

¹ one run showed 2.5× on sub-microsecond timings; that is measurement noise, not
an effect.

## What the numbers actually say

**1. The dynamic range is three orders of magnitude — 1.0× to 1092×.** A static
rule that reports all of these identically is not wrong, it is *useless for
prioritisation*. Row D is a textbook false positive: perfectly matching the
shape, costing exactly nothing, because `List.Count` is an O(1) property.

**2. The killer row is A, and it settles the argument.** Compare the two `A`
rows at n=100 000: **8.3×** versus **1025×**. The source code is
**character-for-character identical** — `data.Any(x => x > threshold)`. The only
difference is the runtime *value* of `threshold` and the data distribution:
when the predicate hits at element 0, `Any` short-circuits and collection size
becomes irrelevant; when it never hits, the call is O(n) and the cost tracks n.

No static analysis can separate those two, ever. Not a better checker, not
whole-program analysis — the two programs are the same program. The cost lives
entirely in data the analyzer does not have.

**3. Collection size does not predict cost either.** Row A[hit] is *flat* across
n (2.8 → 12.6 → 11.1 → 8.3), while row A[miss] grows a hundredfold over the same
range. So even "flag it only for large collections" — the obvious heuristic
rescue — is wrong in both directions.

## The consequence: this is Layer 1 → Layer 2, and we already have that shape

The conclusion is not "the static rule is worthless". It is that **the static
rule and the profiler are each individually unactionable, and complete each
other exactly**:

- **A profiler alone** tells you `data.Any(...)` is 30% of CPU. It does *not*
  tell you the call is loop-invariant, i.e. that the fix is free and safe. Hot
  is not the same as fixable, and most hot lines are hot because they do
  necessary work.
- **A static rule alone** tells you the call is provably invariant and gives the
  exact fix — hoist it. It cannot tell you whether that fix buys 0% or 99.9%,
  so it cannot rank, and an unranked list at 1.0×-to-1092× precision is noise.
- **Together**: *"this line is 30% of CPU **and** it is provably loop-invariant
  → hoist it, here is the edit."* That is a finding with a magnitude, a proof,
  and a patch. Neither layer produces it alone.

This is precisely the architecture [`Plan.md`](../../Plan.md) §1 already
describes — Layer 1 static → Layer 2 runtime → Layer 3 AI over finished
evidence — and precisely the confirmation pattern already used for subscription
leaks, where own-check flags and the runtime harness confirms retention
(`MED` static, `HIGH` once runtime-confirmed, Plan.md §2 category 2). The
performance case reuses the mechanism unchanged; only the witness differs
(a timer/profiler sample instead of a heap walk).

It also **repairs the objection this note's parent raised against itself**. That
note called "expensive" the kind of word that generates false positives, and
that is right — *as a static predicate*. Measured, it stops being a predicate
and becomes a number. The runtime layer is what makes the static rule shippable,
not an optional enhancement to it.

## Honest limits

- **Microbenchmark, one machine.** These are isolated shapes with no cache
  pressure from surrounding work; real applications will compress the extremes.
  The *ordering* and the fact of the spread are the claim, not the exact
  multipliers.
- **This is not evidence the rule is implementable.** Proving loop-invariance
  for a LINQ chain requires proving the receiver, the captured locals, *and* the
  lambda are all effect-free across the loop body — real interprocedural work,
  not a syntactic match. [P-036](../proposals/P-036-interprocedural-semantic-architecture.md)
  is the right *host* for it (call graph, `MethodSummary`, SCC composition), but
  **none of its five summary domains** — ownership, obligation, progress,
  region, task — is a purity/effect-freedom domain, so this would be a sixth
  one, and effects are owned by [P-008](../proposals/P-008-effects-and-resources.md)
  (draft, explicitly horizon). Nothing here estimates that cost.
- **P-036's own rules would refuse the claim by default.** Its unknown/external
  call policy classifies `Any(userLambda)` as an unresolved or unsupported
  target: conservative defaults, recorded degraded precision, and the standing
  rule that a check "may not pretend the call was proven harmless". So the
  static half would emit a *candidate with declared uncertainty*, not a verdict
  — which is another way of arriving at the same conclusion as the body of this
  note: the magnitude has to come from the runtime layer.
- **`.NET 4.7.2` was not measured.** The trigger case was on Framework, where
  there is no dynamic PGO and no guarded devirtualization; these .NET 9 numbers
  are therefore a *lower* bound on the penalty, not a reproduction of it.
- **No corpus.** Four shapes chosen to span the range. Whether real code
  clusters near 1× or near 1000× is unmeasured, and that distribution is what
  would actually decide whether the rule is worth building.

## Status

**Recorded, not scheduled.** Notes record, the ROADMAP schedules. If this is
ever picked up, the honest first step is not the rule — it is
**mining (P-012) to find out whether the pattern occurs in real C# at all, and
with which cost distribution.** Building a checker for a pattern whose real-world
cost profile is unknown is how the 1.0× false positives get shipped.
