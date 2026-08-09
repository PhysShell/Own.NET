# Can .NET code get C/C++-grade compiler optimizations? — a measured answer

Working note. **Trigger:** a design discussion asked whether .NET code could be
pushed through some representation where LLVM's "insane" C/C++ optimizations
apply, and whether a proof-of-concept is doable on a shoestring. A second
question rode along: *what does .NET actually optimize in our code?* — prompted
by an expensive LINQ query that visibly re-ran every iteration of a `for` loop
on .NET Framework 4.7.2.

This note answers both **with measurements, not opinion**. The harness is
committed in [`llvm-codegen-feasibility-data/`](llvm-codegen-feasibility-data/)
and reproduced by `run.sh`, so every number below is falsifiable.

**Bottom line up front:**

1. **PoC is doable** — the pipeline is alive and the measurement ladder below
   already runs. But it is a *codegen* project, not an Own.NET project.
2. **The headline result is negative for us.** The "ownership → `noalias` →
   speed" story that makes Rust fast **did not reproduce**: alias metadata
   bought **0%** on every kernel measured. The thing that unlocks LLVM is
   **range-check elimination in the frontend**, which is ordinary compiler work
   with no ownership content.
3. **LLVM is not a capability ceiling C# cannot reach.** Hand-written C#
   `Vector256` code matched LLVM `-O3` on one kernel and **beat clang `-O3` by
   1.8×** on another. What LLVM sells is *automation*, not headroom.
4. RyuJIT is **already better than the folklore** — it hoists, clones loops, and
   eliminates bounds checks. What it does not do is **vectorize or unroll**.

## Method

- **Environment.** Intel Xeon @ 2.10GHz, 4 vCPU, AVX-512 (`avx512f/bw/dq/vl/cd/
  ifma/vbmi`), Linux 6.18.5. clang/LLVM **18.1.3**, .NET SDK **9.0.316**
  (runtime 9.0.18), `linux-x64`. Native side always
  `clang -O3 -march=x86-64-v3`.
- **Shape of the comparison.** The same kernel is written twice — once in C#
  (run by RyuJIT) and once in C (compiled by clang `-O3`, called via
  `DllImport` over `fixed` pointers). The C is deliberately written to mimic
  *naive CIL lowering*: an explicit per-element range check that calls a
  `noreturn` throw helper, and (where noted) the array length re-loaded from
  the object header rather than hoisted.
- **Controls are the point.** Every kernel carries a hand-written C# SIMD
  variant, because "LLVM beats scalar C#" is a boring claim; "LLVM beats
  *well-written* C#" is the claim that would justify building anything.
- **Correctness gate.** All four K3 variants (scalar, branchless, hand-SIMD,
  native) must return the identical value or the harness throws. They agree on
  `25830282`. An early version of the SIMD control accumulated in 32-bit while
  the scalar accumulated in 64-bit — it produced a flattering **33×** that was
  simply *less work*. The gate exists because that mistake was made here.
- **Steady state.** Reported numbers use `DOTNET_TieredCompilation=0` plus a
  5000-call warmup. See the measurement traps below — this is not a detail.

### Two measurement traps (both hit during this work)

- **Warmup.** With tiering on and a 200-call warmup, the managed kernels
  measured **1.4× slower** than steady state — and that inflated LLVM's apparent
  advantage from **3.3× to 4.6×**. The first draft of this note would have
  overstated the result by 40%. 4000 *measured* iterations did not save it;
  only a longer warmup or `TieredCompilation=0` did.
- **Unequal work.** See the correctness gate above.

## Result 1 — what actually blocks LLVM on CIL-shaped code

`lenprobe.c`, 2×2 over the same `dst[i] = a[i] + b[i]*3` loop
(`-Rpass=loop-vectorize`):

| | length re-loaded each iteration (naive `ldlen`) | length hoisted once (immutability known) |
|---|---|---|
| **aliasing unknown** | ❌ not vectorized | ✅ vectorized (width 8, interleave 2) |
| **`noalias` (`restrict`)** | ❌ not vectorized | ✅ vectorized (width 8, interleave 2) |

And `checkfree.c` vs `native2.c`, over the reduction and branchy kernels:

| loop body | vectorized? |
|---|---|
| per-element range check + `noreturn` throw | ❌ **not vectorized** |
| range check hoisted out of the loop | ✅ vectorized (width 4, interleave 4) |

**Reading.** A naive CIL→LLVM frontend emits, for every single `ldelem`, a
bounds check whose failure edge calls a `noreturn` throw helper. That extra loop
exit **switches LLVM's vectorizer off entirely** — and re-loading the array
length from the object header does the same, independently. `noalias` changes
**nothing** in either row.

So the load-bearing contribution a CIL→LLVM frontend must make is *.NET-specific
invariants* — array-length immutability, and range-check elimination — **before**
LLVM ever sees the IR. LLVM will not recover them for you. This inverts the
intuition the idea started from: the win is not "hand CIL to LLVM and collect
C-grade optimizations", it is "do the .NET-specific proof work yourself, and
LLVM's vectorizer is the reward."

## Result 2 — RyuJIT vs LLVM, measured

Median of 3 runs, steady state. `Gelem/s` = elements processed per second.

**K1 — `dst[i] = a[i] + b[i]*3` (straight-line numeric):**

| variant | Gelem/s | ×scalar |
|---|---|---|
| RyuJIT scalar | 1.85 | 1.00× |
| RyuJIT `Vector256`, no unroll | 5.4 | 2.9× |
| **RyuJIT `Vector256` ×4 unrolled** | **6.4** | **3.5×** |
| LLVM `-O3`, `noalias` | 6.1 | 3.3× |
| LLVM `-O3`, aliasing unknown | 6.1 | 3.3× |

**K2 — reduction (`s += a[i]`):**

| variant | Gelem/s | ×scalar |
|---|---|---|
| RyuJIT scalar | 2.75 | 1.00× |
| LLVM `-O3`, per-element check | 2.75 | **1.00×** |
| LLVM `-O3`, check hoisted | 11.1 | 4.0× |

**K3 — data-dependent branch (`if (v > lo && v < hi) s += v*2; else s -= v`),
random data, ~unpredictable branch — the shape of business logic:**

| variant | Gelem/s | ×scalar |
|---|---|---|
| RyuJIT scalar | 0.22 | 1.00× |
| RyuJIT "branchless" (multiply trick) | 0.18 | **0.80×** |
| **RyuJIT hand-SIMD + `ConditionalSelect`** | **5.0** | **22.5×** |
| LLVM `-O3`, per-element check | 1.39 | 6.2× |
| LLVM `-O3`, check hoisted | 2.81 | 12.5× |

**K4 — pointer chase over a managed object graph:** 0.55 Gnode/s. No vectorizer
of any kind applies; this is latency-bound and included to mark the boundary.

### Reading the table

- **`noalias` bought nothing.** K1: 6.1 vs 6.1. Over a 64K-element loop, LLVM's
  runtime alias check amortizes to zero and the versioned loop runs at the same
  speed as the `restrict` one. **The ownership→speed story does not reproduce
  here.** This is the single most decision-relevant number in the note, and it
  is the one that says *this is not an Own.NET project*.
- **LLVM did not vectorize K2/K3 at all** — inspection of the assembly shows 0
  `ymm`/`zmm` registers in `filter_sum_native` and 2 `cmov`s. Its entire 6.2× on
  K3 is **if-conversion** (branch → `cmov`, killing mispredictions), not SIMD.
  The bounds check blocked the vectorizer, exactly as Result 1 predicts.
- **Hand-written C# wins where it is written.** C# `Vector256` ×4 (6.4) edges
  out LLVM on K1 (6.1), and hand-SIMD C# on K3 (5.0) **beats clang `-O3` (2.8)
  by 1.8×** — because a human applied if-conversion *and* vectorization where
  LLVM managed only the former.
- **Micro-optimizing by hand can backfire.** The "branchless" multiply trick
  made K3 **20% slower** than the naive branch. RyuJIT did not turn it into a
  `cmov`; it just did more arithmetic.

## Result 3 — what .NET actually optimizes (the LINQ-in-a-loop question)

RyuJIT disassembly of the scalar K1 loop (`DOTNET_JitDisasm`, FullOpts) —
abridged:

```asm
G_M000_IG02:  mov   ecx, dword ptr [rdi+0x08]   ; dst.Length -- hoisted, loaded ONCE
G_M000_IG03:  test  rsi, rsi                    ; null checks   -- hoisted
              cmp   dword ptr [rsi+0x08], ecx   ; a.Length >= dst.Length -- hoisted
              cmp   dword ptr [rdx+0x08], ecx   ; b.Length >= dst.Length -- hoisted
G_M000_IG04:  mov   r9d,  dword ptr [rsi+4*r8+0x10]
              mov   r10d, dword ptr [rdx+4*r8+0x10]
              lea   r10d, [r10+2*r10]           ; *3 -> lea (strength reduction)
              add   r9d, r10d
              mov   dword ptr [rdi+4*r8+0x10], r9d
              inc   eax
              cmp   ecx, eax
              jg    SHORT G_M000_IG04           ; hot loop: ZERO bounds checks
```

That is **loop cloning**: RyuJIT proved the safe precondition once, then emits a
fast loop with **no bounds checks at all**, keeping a checked clone (`IG06`) as
fallback. Plus hoisting of lengths and null checks, and strength reduction
(`*3` → `lea`). RyuJIT is doing real optimization work.

**What it does not do: vectorize or unroll.** That is the whole 3.3× gap on K1,
and auto-vectorization remains an open request upstream
([dotnet/runtime#11263](https://github.com/dotnet/runtime/issues/11263)).

**So why was the LINQ query not hoisted out of that 4.7.2 loop?** Not a JIT bug,
and LLVM would not have fixed it either. A LINQ chain is a sequence of
**opaque, allocating, interface-dispatched calls**. Loop-invariant code motion
may only hoist an expression it can prove side-effect-free, and nothing in the
CLR gives the JIT purity information about `Where`/`Select`/`Any` over an
arbitrary user predicate. No compiler in this note's data — RyuJIT *or* clang
`-O3` — hoists an opaque call out of a loop; it is not a legal transform without
a purity proof. On 4.7.2 it is worse still: no dynamic PGO, no guarded
devirtualization, so the delegate and enumerator calls stay indirect.

The actionable consequence is the interesting one: **this class of bug is a
static-analysis target, not a codegen target.** "Loop-invariant expensive query
evaluated inside a loop" is structurally visible in source — which is Own.NET's
existing business — whereas no amount of LLVM would touch it. If any part of
this discussion deserves to become a rule, it is that one, and it has nothing to
do with LLVM.

## Landscape — who has already tried this

| Effort | What it is | Status |
|---|---|---|
| **Unity Burst** | LLVM over a C# subset (HPC#), the real proof this works — auto-vectorization, `[NoAlias]`, 10–100× on compute kernels | **Alive, shipping.** Buys its wins by *restricting the language* (no GC, no classes, no exceptions in kernels) |
| **NativeAOT-LLVM** | `dotnet/runtimelab`, LLVM backend for NativeAOT, primarily WebAssembly | Experimental branch; LLVM also used as object writer in shipping NativeAOT |
| **LLILC** | Microsoft's LLVM-based JIT for CoreCLR (2015) | **Dead**, archived, superseded |
| **Mono LLVM backend** | `--llvm` AOT path | Long-standing, production for AOT targets |
| **`rustc_codegen_clr`** | the *reverse* direction (Rust → CIL) | Referenced for context only; solves a different problem |

**Burst is the honest precedent, and it teaches the real lesson**: the way to
get LLVM-grade codegen out of C# is not to translate all of C# — it is to carve
out a **restricted subset** where the .NET-specific invariants are cheap to
establish. Which is precisely Result 1, arrived at independently.

### What Burst actually is, and whether it helps us

Burst compiles **HPC#** — "High-Performance C#", a deliberately crippled subset
— through LLVM instead of RyuJIT. The subset is the whole trick: no classes, no
managed heap references, no GC allocation, no exceptions in kernels; you work
over `struct`s and `NativeArray<T>` inside Unity's job system, and you annotate
pointers `[NoAlias]`. Under those restrictions LLVM's auto-vectorizer,
unroller and inliner all apply, and Unity reports 10–100× on compute-heavy
kernels.

Note *why* those restrictions matter, against Result 1: forbidding managed
references and using `NativeArray<T>` removes the object header, so there is no
per-iteration `ldlen`; the job system's bounds are loop-invariant by
construction, so the range checks hoist. **Burst does not beat the blockers
found above — it defines them out of the language.** That is the entire
mechanism.

Three honest conclusions about how it helps us, in decreasing order of value:

1. **As a cost calibration — the main value.** Burst is what "success" costs.
   A funded team, a decade, and a language subset severe enough that ordinary
   C# does not compile. It converts "could we do this?" into "this is the size
   of the thing", which is why rung 4+ is not recommended.
2. **As a design precedent, with a real but partial parallel here.** OwnLang is
   already a restricted language with storage discipline enforced by
   construction ([`spec/BufferPolicies.md`](../../spec/BufferPolicies.md):
   `stack`/`scratch`/`pooled`/`native`, where B1 forbids stack buffers from
   escaping). So the structural analogy `Burst : HPC#` ≈
   `LLVM backend : OwnSharp subset` is not fantasy — a language that already
   pins storage and escape could supply the invariants a frontend needs.
   **But** the parallel stops exactly where Result 2 does: the invariants worth
   supplying are range-check elimination and length immutability, and the
   ownership content contributes **0%**. OwnLang would be helping as *a
   restricted language*, not as *an ownership system* — so this is not a reason
   to build it, and it does not make the ownership work pay off in codegen.
3. **Not usable as a component.** Burst is Unity-coupled — the package, the job
   system, `NativeArray<T>`. There is nothing to vendor or reuse outside Unity.

One transferable practice, independent of any of the above: Burst ships an
**inspector** showing the generated assembly per kernel, because even inside the
subset, whether a loop vectorised is not predictable from the source. That is
the same "measure, do not assume" discipline this note's `-Rpass` output and
`DOTNET_JitDisasm` dumps applied — and the same lesson as
[`invariant-cost-static-vs-runtime.md`](invariant-cost-static-vs-runtime.md).

## Is a PoC doable? Yes — and here is the ladder

Rungs 1–3 are *already done and committed here*; the remaining cost is rung 4+.

1. ✅ **Does LLVM help CIL-shaped loops at all?** — `run.sh` part 1. Answered:
   only after frontend RCE.
2. ✅ **How big is the prize vs RyuJIT?** — 3.3–4.0× on numeric kernels, 1.00×
   when memory-bound, 0× on pointer chasing.
3. ✅ **Is the prize reachable without LLVM?** — yes, hand-SIMD C# matches or
   beats it. This is the rung that decides the project.
4. ⬜ **A real IL→LLVM translator** for a tiny opcode subset (`ldarg`/`ldloc`/
   `ldc.i4`/arithmetic/`ldelem.i4`/`stelem.i4`/`ldlen`/branches/`ret`), locals
   as `alloca` + `mem2reg`. Perhaps 300–500 lines. **Only worth writing after
   rung 3 says the automation is worth having** — and here it says it mostly
   is not.
5. ⬜ Everything real: GC write barriers, exact stack maps for a moving GC,
   exception semantics, P/Invoke, generics/shared code, tiering and OSR. This
   is where LLILC died, and it is a compiler-team-years problem, not a weekend.

**Recommendation: do not build rung 4+ here.** Not because it fails — it works —
but because rung 3 shows the payoff is available today in plain C#, and Result 1
shows the enabling work carries no ownership content, so it would not compound
with anything Own.NET does. The experiment was worth running precisely because
it produced a clean negative on the part that looked most attractive.

## What this does and does not reopen

- **Does not reopen the `tech-debt-register.md` rejection of MLIR/LLVM.** That
  rejection is about *OwnIR as a fact-interchange format* (§2: "instruction-level
  compiler frameworks, wrong abstraction"). This note asks a different question —
  LLVM as a *codegen backend for execution* — and independently lands on "no",
  for different reasons. Both stand; neither is evidence for the other.
- **Does not create a work item.** Recorded as research context, per the
  `research-landscape-2026.md` discipline: notes record, ROADMAP schedules.
- **Does leave one genuinely actionable thread**, and it is not the LLVM one:
  the loop-invariant-expensive-call rule from Result 3. Filed here as an
  observation, not a proposal — it would need corpus evidence (P-012) before
  anyone writes a rule, and "expensive" is exactly the kind of word that
  generates false positives.

## Honest limits of this measurement

- **One machine, one microarchitecture, 4 vCPU shared.** One K1 run showed
  ~30% variance from a noisy neighbour; the reported medians are stable across
  3 runs but this is not a clean benchmarking rig.
- **Four kernels is not a corpus.** They were chosen to span straight-line
  numeric / reduction / branchy / pointer-chasing, but no claim is made that
  they represent real application profiles.
- **The C side is a *proxy* for CIL lowering, not real CIL.** It was hand-written
  to mimic what a naive frontend emits. Rung 4 would replace the proxy with an
  actual translator; until then, Result 1 is a statement about *loop shapes*,
  which is how it is phrased.
- **No GC interaction is modelled at all.** The native kernels operate on pinned
  buffers. Write barriers and stack maps — the things that actually killed
  LLILC — are entirely absent from these numbers, so nothing here should be read
  as a cost estimate for a real backend.
