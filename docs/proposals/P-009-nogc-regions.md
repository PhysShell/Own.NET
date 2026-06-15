# P-009 — Verified allocation-free ("no-GC") regions (`Own.NoGc`)

- **Status:** draft (horizon)
- **Depends on:** buffer storage policies (`spec/BufferPolicies.md`, the
  `policy P { ... }` block and OWN015–017 escape rules); the ownership core
  (`spec/OwnCore.md`); and **P-007** (ArrayPool/Span borrow-view), which supplies
  the `Span<T>`-over-owned-storage view this region lives inside. Strategy hub:
  [`docs/ROADMAP.md`](../ROADMAP.md), `Own.Performance` track.

## Motivation

In audio, game loops, low-latency/trading, serializers, packet processing,
crypto, and WPF hot render/update paths, a hidden managed allocation in the hot
path is real harm: it invites a GC pause exactly when you cannot afford one. The
ask people *say* is "C# without a GC." We cannot deliver that, and pretending
otherwise would be the boil-the-ocean version this project exists to refuse.

Honest framing: managed objects live on the managed heap and the runtime must
know when to free them — you cannot turn that off for managed C#. Even Native AOT
is not "C# without GC": it removes the JIT and ships a self-contained AOT binary,
but it still ships runtime libraries, still has a GC, bans dynamic loading /
`Reflection.Emit`, and needs trimming. So the deliverable is **not** a runtime
change. It is a **static checker for allocation-free regions**, plus explicit
stack / scratch / native / pool memory with ownership — which is squarely
Own.NET territory. Without the ownership checker, "C# without GC" is just "C with
expensive syntax and new ways to shoot your foot."

## Scope

A region (method or block) marked `nogc` is statically verified to perform **no
managed-heap allocation**. The GC still exists app-wide; the region is a verified
island. A ladder of ambition, from most realistic to most aspirational:

1. **Allocation-free hot path** (the MVP, most useful): GC exists app-wide; one
   method/region provably does not allocate. This is the whole prize for audio,
   game loops, serializers, packet/image processing, crypto, WPF render.
2. **`NoGCRegion` runtime guard:** pair the static region with
   `GC.TryStartNoGCRegion(totalSize)` / `GC.EndNoGCRegion()`. Best-effort,
   non-nestable, needs a pre-reserved budget — and **not** a substitute for the
   static checker: a body full of `string.Format`/LINQ/closures under
   `TryStartNoGCRegion` is just an allocation circus with a budget.
3. **Manual unmanaged memory:** `NativeMemory.Alloc`/`Free`, `Span<byte>` over the
   pointer — this immediately needs the ownership checker (Alloc = acquire,
   Free = release, Span = borrowed view; Free-while-Span-live, use-after-Free,
   double-Free, leak). Reuses `native` buffer machinery directly.
4. **An OwnLang `nogc` subset that lowers to `unsafe` C#:**
   `fn hash(input: Span<byte>) -> u64 nogc { let scratch = Buffer.stack<byte>(256); ... }`
   → `Span<byte> scratch = stackalloc byte[256];`.

## Non-goals

- **"Real C# without a GC."** Impossible for managed C#; not attempted. We verify
  *regions*, we do not remove the collector.
- **A runtime GC switch / a custom no-GC runtime / forking Native AOT.** Out.
- **Whole-program allocation analysis.** Regions are opt-in and local. Unknown
  callees are rejected, not chased.
- **Replacing the runtime guard.** `TryStartNoGCRegion` is a complementary
  runtime belt; this proposal is the static suspenders.

## Sketch

Reuse note: OwnLang's existing buffer policies (stack/scratch/pool/native +
escape rules OWN015–017) are already ~80% of the machinery. This is largely a new
*policy* (`nogc`/`noheap`) layered on `spec/BufferPolicies.md`'s `policy` block,
plus an **allocation-source detector** on the C# side — not a new analysis.

DSL surface — a storage/effect policy:

```text
policy RealtimeAudio {
  nogc; noheap; noexceptions; noasync;
  allow stack; allow scratch;
  forbid pooled unless declared;     // use !Pool<T>
  forbid native unless owned;        // owned wrapper, OWN015–017 apply
}

fn Render(input: Span<float>, output: Span<float>) policy RealtimeAudio use !Scratch {
  let tmp = Buffer.stack<float>(512);
  borrow_mut tmp as t { Mix(input, t); Copy(t, output); }
}
```

C# surface (the MVP entry point): `[OwnNoGc]` or `[OwnPolicy("RealtimeAudio")]`
on a method; the Roslyn extractor (P-001) flags allocation sources as OwnIR
facts, the Python core renders the verdict at the C# line.

**Forbidden inside a `nogc` region** → the body allocates: `new` of a class;
`new string` / string interpolation; boxing; lambda/closure with capture; LINQ;
`async` / iterator (`yield`); `ToArray`/`ToList`; delegate allocation;
`params object[]`; exceptions as control flow; hidden allocations from known APIs.

**Allowed:** `stackalloc`, `Span<T>`, `ref struct`, unmanaged/native memory via an
owned wrapper, and `ArrayPool` **only** when declared `use !Pool<T>`.

```text
[OwnNoGc] method  --[Roslyn alloc-source detector]-->  alloc facts (OwnIR)
                                                          |
                                  whitelist spec (nogc contracts) --+
                                                          v
                                              Python core --> OWN-GCnnn at C# line
```

The practical knob is a **whitelist of known-nogc APIs**, e.g.
`System.MathF.Sin(float): nogc:true`, `System.Span<T>.CopyTo: nogc:true`,
`System.Linq.Enumerable.Select: nogc:false (iterator/delegate allocations likely)`.
An unknown call has **no nogc contract** → rejected by default, with the
allocation reason reported (OWN-GC004), so silence never reads as safety.

Diagnostics (`OWN-GC` family):

```text
OWN-GC001  managed allocation in nogc region
OWN-GC002  boxing
OWN-GC003  closure / delegate allocation
OWN-GC004  call to method without a nogc contract
OWN-GC005  async / iterator not allowed in nogc region
OWN-GC006  heap escape from a stack/native buffer (relates to OWN015–017)
OWN-GC007  exception allocation (exception used as control flow)
```

**First real target:** a CLAP audio plugin's render/process callback must be
allocation-free — GC pauses and hidden allocations are audible harm. The
project's own audio/CLAP direction stacks with this cleanly, so the MVP lands on
a callback that genuinely needs it rather than a toy.

**MVP, concretely:** `[OwnNoGc]` method attribute; detect the obvious allocation
sources; allow `stackalloc`/`Span`; reject unknown calls by default; support a
whitelist spec; report the allocation reason. Then wire the CLAP render callback
as the first verified region.

## Open questions

1. Granularity: method-level `[OwnNoGc]` only, or also a `nogc { ... }` block
   inside an otherwise-allocating method?
2. Whitelist provenance: hand-curated spec, harvested from BCL signatures, or a
   community-maintained file? Where does the source-of-truth live in `spec/`?
3. Do we pair the static region with `TryStartNoGCRegion` codegen (level 2), or
   keep the runtime guard strictly opt-in and orthogonal?
4. `Own.NoGc` reads as a marketing name; is `noheap`/`noalloc` the more honest
   policy keyword, given we are forbidding *allocation*, not the collector?
5. How much of the `native`-escape story (OWN015–017) needs hardening before
   level 3 is more than a checker-accepts / codegen-rejects PoC?
