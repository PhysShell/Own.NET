# GC observability and the LOH — what is worth adopting, and what stays runtime-only

Working note. **Trigger:** the *GCExperiment* write-up ("Making .NET GC
behaviour observable"), proposed as material to fold into our runtime layer.
This note records what is genuinely new in it, corrects one number our own docs
imply, and pins the boundary that must not move.

Companion to [`llvm-codegen-feasibility.md`](llvm-codegen-feasibility.md) (the
other half of the same discussion) and to
[P-034](../proposals/P-034-runtime-lifetime-guard.md), whose "ClrMD-free
complement" argument this reuses verbatim.

## The one factual correction worth taking

Our docs treat the Large Object Heap threshold as **85,000 bytes** of payload.
That is the documented constant, but it is not the predicate. The GC compares
the **full object size** — payload + object header + method table pointer +
alignment padding — so an array whose *payload* is comfortably under the limit
still lands on the LOH:

> `byte[84_999]` → 85,023 bytes with the 24-byte array header → rounds to
> 85,024 → **allocated on the LOH.**

The practical consequence, and the reason it is worth writing down: the familiar
"keep buffers under 85,000" folklore is **off by roughly one header**, and a
pool sized to exactly `85_000 - 1` is on the wrong heap. Anyone sizing a buffer
pool against the constant should size against `85_000 - 24 - padding`, or
simply measure.

Where this touches our docs: [`ROADMAP.md`](../ROADMAP.md) and
[`Plan.md`](../../Plan.md) both list LOH fragmentation in the detectability
matrix. Neither states a threshold, so **neither is wrong** — but if a threshold
is ever quoted in a rule, a diagnostic message, or a talk, it must be the
full-object-size version, not the payload one.

## What GCExperiment is, and what is actually adoptable

Four self-contained experiments (LOH placement; generation promotion;
allocation pressure; LOH fragmentation) built on ordinary public APIs —
`GC.GetGeneration`, `GC.Collect` with forced modes,
`GC.WaitForPendingFinalizers`, `GCSettings.LargeObjectHeapCompactionMode`,
plus small `GCMonitor`/`GCInfo` helpers for snapshots and size estimation. It
also flags a real measurement trap: without `GC.KeepAlive`, the JIT can shorten
an object's lifetime and skew the result.

The adoptable idea is **not** the GC content, which is well-trodden. It is the
**delivery shape**, and it is the same shape P-034 already argued for from a
different direction:

> a lifetime/GC observation that runs in an ordinary `dotnet test`, on any OS,
> with no PerfView, no ETW, no Windows stand, and no ClrMD heap walk.

Today our runtime layer ([`Plan.md`](../../Plan.md) §2, category 12) routes
*everything* GC-shaped to PerfView + ETW. That is correct for **evidence** and
badly overweight for **orientation** — it means no GC fact can be established in
CI, on Linux, or in a unit test. A `GC.GetGCMemoryInfo` /
`GC.CollectionCount(n)` snapshot around a scenario costs nothing and needs no
stand.

So: a cheap in-test GC probe is a reasonable sibling to P-034's disposal
quarantine, under the same honest caveat P-034 already states — it proves *what
the counters did during this test*, bounded by test coverage, and it is blind to
*why*. It is a debug assertion, not an auditor.

## The boundary that does not move

**None of this makes LOH fragmentation statically detectable.** The matrix rows
stay exactly as written:

- `ROADMAP.md`: LOH fragmentation → ❌ **impossible** (depends on runtime data
  volume / GC timing)
- `Plan.md` category 12: heavy dictionaries / LOH fragmentation / Gen2 bloat →
  **impossible** static → **RUNTIME**

A GC probe is a **runtime witness**, and it lives on the runtime side of the
line the detectability matrix draws. The matrix exists specifically to stop
runtime-shaped problems from being hung on a static checker
([`Plan.md`](../../Plan.md) §1: it "*forbids*" exactly that, killing a class of
false positives in advance). Making GC behaviour cheaper to *observe* is not an
argument for making it *inferred*, and this note must not be cited as one.

The one thing genuinely on the static side is unchanged and already ours: the
`ArrayPool`/`Span` misuse family (`POOL001`–`003`, P-007). Rent/return balance
is structurally visible; fragmentation is not.

## Status

**Recorded, not scheduled.** Per the `research-landscape-2026.md` discipline,
notes record and the ROADMAP schedules. Concretely, if anything is ever picked
up from here:

1. **The LOH threshold correction** — free, and the only item with a
   correctness argument behind it. Applies wherever a number gets quoted.
2. **A GC-counter probe as a P-034 sibling** — small, attaches to the open
   question P-034 already asks (a new `Own.Diagnostics` package vs living in
   OwnAudit's `runtime/`). Do not file it separately; it is the same decision.
3. **Nothing else.** The generation-promotion and allocation-pressure
   experiments are educational rather than diagnostic, and we do not need to
   re-derive published GC behaviour to ship a checker.
