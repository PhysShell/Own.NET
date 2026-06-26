# P-005 D5 — interprocedural ownership transfer (design v2)

**Status:** forward-looking design, not yet built. Supersedes the one-line "D5 is a
heuristic at the call boundary" sketch in
[`../proposals/P-005-idisposable-ownership.md`](../proposals/P-005-idisposable-ownership.md).
D1–D4 are built (local-not-disposed, owned-field, double-dispose, use-after-dispose,
all via the `--flow-locals` flow lattice); D5 — *what happens to an `IDisposable` when
it crosses a method boundary* — is the open frontier this note designs.

This note was sharpened by a literature/tooling review (see **Prior art**). The single
most useful finding: **D5 is a summary-contract problem, not a borrow-checker-core
problem.** The closest shipped analogues — the Checker Framework's **Resource Leak
Checker (RLC)** and its C# port **RLC#** — keep the intraprocedural checker simple and
push cross-procedure knowledge into *method-boundary summaries, annotations, and curated
library models*. That is exactly the Tier A/B/C/D shape below. Polonius (Rust) is worth
reading for precise intra-body loan reasoning, but is **not** the template for D5.

---

## 0. The reframe: core already has the vocabulary

The OwnLang core already understands the pieces D5 needs:

- Function parameters already carry `effect ∈ {consume, borrow, borrow_mut, plain}`
  (`ownlang/ownir.py`), and the CFG already lowers them: a `consume` argument moves the
  caller's value to `ESCAPED`; a `borrow` argument takes a temporary loan
  (`ownlang/cfg.py`).
- A `return var` is already modelled as a discharge/escape of the callee's local, and
  the function is stamped with an owned return type.

What is **missing** is purely *inference* and *propagation*, both extractor-side:

1. The current effect inference is **local**: `released → consume`, `only used → borrow`,
   but **`passed to another call → gives up` (stays `plain`)** — there is no fixpoint
   over the call graph.
2. A callee's owned return is modelled *inside the callee*; it is **not propagated to the
   caller's local**, so `var x = Factory()` is not recognised as an acquire.
3. There is no method-summary table / call graph. The only interprocedural code is
   `ConsumesParam` (`Program.cs`), a first-party-only, per-call-site, consume-only
   heuristic.

So **D5 ≈ an interprocedural ownership-summary pass in the extractor that feeds the
existing core vocabulary.** Almost no new checker code in core; the work is computing
summaries and lowering them to `consume`/`borrow`/acquire at call sites — the same
"synthetic-flow" discipline already used for D1–D4, lifted to the effect level.

---

## 1. The model — Method Ownership Summary (MOS)

For each method `M` whose body we can see (first-party / same compilation) we compute a
compact **boundary artifact**. The headline schema decision, forced by prior work:

> **Escape ≠ ownership transfer.** "The parameter escaped this procedure" and "ownership
> moved away from the caller" are *different questions*. Container-like code routinely
> stores a reference without taking ownership (cache, collection, non-owning field).
> The summary must keep these on **separate axes**, even if v0 lowering temporarily maps
> both conservatively.

### Per-parameter (only for `IDisposable`-typed params)

Two orthogonal axes plus evidence:

- `transfer ∈ {must, may, no, unknown}` — did ownership leave the caller?
  - `must` — released on **all** normal-return paths, OR stored into an **owning** field
    (one the type's `Dispose()` releases), OR forwarded to a callee whose summary is
    `transfer:must`.
  - `may` — the above on **some but not all** paths (partial consume).
  - `no` — only read/used; ownership stays with the caller (a *borrow*).
  - `unknown` — insufficient evidence (e.g. forwarded to an unsummarizable callee).
- `escapes ∈ {yes, no}` — did the reference outlive the call (field / collection /
  returned)? Orthogonal to `transfer`: `escapes:yes, transfer:no` is the
  "stored-but-not-owned" container case.
- `via` (optional, **debug-only** evidence string) — `dispose` / `field:_inner` /
  `forward:Callee#0` / `aliased-return`. For debugging, advisory text, and future
  precision. **Not** part of the canonical `summaries[]` contract and **not** emitted by
  D5.0's `to_dict` (a later slice may serialize it); the JSON in §6 shows it illustratively.

Derived caller-side meaning: **Consumed** = `transfer:must`; **Borrowed** =
`transfer:no, escapes:no`; **Escape-without-transfer** = `escapes:yes, transfer:{no,unknown}`.

### Per-return

`returnsOwned ∈ {fresh, aliased, aliasOf:<i>, none, unknown}`:

- `fresh` — a newly-acquired disposable (or the `fresh` return of a callee) — the caller
  now owns it.
- `aliased` — a borrowed/shared reference the caller does **not** own (a property getter
  returning a cached field, returning `this`, returning a parameter as-is).
- `aliasOf:<i>` — the return **shares the obligation of argument `i`** (RLC's
  `@MustCallAlias`): a wrapper handed back to the caller that adopts arg `i`. Disposing the
  return discharges arg `i`; the caller must **not** also dispose arg `i`. This is the
  Dapper `DbWrappedReader.Create(reader)` shape.
- `none` — no owned return at all (the method returns `void` or a non-disposable). Distinct
  from `unknown`: we *know* there is nothing for the caller to own. (`to_dict` emits this.)
- `unknown` — insufficient evidence to classify.

### `source`

`inferred | bcl | annotation | heuristic` — which tier produced this summary (Tier A–D
below). Lets the lowering trust high-confidence tiers and gate the heuristic one.

---

## 2. The four transfer directions → what we emit

Ownership crosses a boundary four ways. Each maps to an emission the **existing** core
consumes:

| Dir. | Trigger | Emit | Bug it unlocks |
|---|---|---|---|
| **T1** return-out | `var x = M()`, `MOS(M).returnsOwned = fresh` | `acquire(Disposable, x)` at the call site — `x` is now an owned local | factory leaks (D1/D3/D4 apply to `x`). *`new T()` is the special case: a ctor is a method with `returnsOwned = fresh`.* |
| **T2** arg-consume | `Callee(x)`, param `transfer:must` | `effect: consume` on that arg → core marks `x` `ESCAPED` | **double-dispose** (`x.Dispose()` after a consuming call → OWN003); **use-after-consume** (`x.Use()` → OWN002) |
| **T3** arg-borrow | param `transfer:no, escapes:no` | `effect: borrow` → `x` stays owned | **leak through a borrowing call** (caller never disposes → OWN001) — today silently lost when the arg "escapes" |
| **T4** wrap/adopt | `new Wrapper(x)` (or `Factory(x)`) where the result adopts `x` | T4a (`returnsOwned = aliasOf:0`, return aliases the arg) **or** T4b (ctor stores `x` in an owning field) | **Dapper / Polly** wrapper-adoption modelled *explicitly* — they stay `own-only 0` *with a reason*, not by accident |

T1 is the only direction needing new caller-side wiring (recognise a `fresh`-returning
call as an acquire). T2/T3/T4 are effect inference feeding machinery that already exists.
T4 reuses D2's "owner releases its fields in `Dispose`" object-level fact.

---

## 3. Tiered sources of truth (a recall ladder over a fixed precision floor)

The precision floor stays `own-only 0`; tiers raise recall. Higher tiers override lower.

- **Tier A — first-party inferred summaries.** The fixpoint of §4 over in-solution
  methods. The bulk of real coverage.
- **Tier B — curated BCL / framework contract table.** High ROI because the truth is
  *officially documented*. The crown jewel is **`leaveOpen`**: `StreamReader`,
  `StreamWriter`, `CryptoStream`, `DeflateStream`, `GZipStream`, `BinaryReader/Writer`,
  `ZipArchive` all document that they dispose the underlying stream **unless** the
  `leaveOpen` overload is used with `leaveOpen: true`. The boolean literal **at the call
  site** disambiguates consume (`false`/default → `transfer:must`) from borrow (`true` →
  `transfer:no`). Plus `fresh`-factories with documented return types (`File.Open/Create`
  → `FileStream`, `DbConnection.CreateCommand` → `DbCommand`, `new HttpClient`, …).
- **Tier C — annotations** for cross-library code whose bodies we cannot see:
  `[OwnTransfers("arg0")]` / `[OwnsReturn]` / a `[MustCallAlias]`-style attribute, plus an
  external-annotations side file (the ReSharper external-annotations pattern). Authoritative
  override of inference.
- **Tier D — heuristic fallback** (the current `ConsumesParam`) as a low-confidence
  `source:heuristic` consume signal, strictly subordinate to A–C.

RLC's defaults, adapted: **constructor returns are always `fresh`** (safe, no body
needed); **parameters/fields are borrow (`transfer:no`) when inferring a summary unless
evidence proves consume**. We **diverge** from RLC on the *unknown-callee call site*
policy — see §5.

---

## 4. The fixpoint (the interprocedural pass)

- Build a call graph over first-party methods.
- A method's summary depends on the summaries of methods it forwards a param to / returns
  the result of. Compute **bottom-up** with a worklist; iterate SCCs (recursion /
  mutual recursion) to a fixpoint on the small lattice.
- **Lattice monotonicity is biased toward precision** (§5): uncertainty resolves toward
  "caller does not own".
- **Cap the work.** Default interprocedural chain depth **3** (matching CA2000's
  `max_interprocedural_method_call_chain` default); configurable. On cap, emit `unknown`
  (→ silent) and **log the cap** — no silent truncation (project discipline).
- The domain is intentionally tiny (4 transfer values × 1 escape bit × 4 return values),
  so a bottom-up summary pass stays practical even on large graphs.

---

## 5. Precision-first policy (the key knob), stated cleanly

The fact model and the *reporting policy* are separate — prior tools make this split
explicit (ReSharper ships **Optimistic** vs **Pessimistic** dispose modes; CA2000 exposes
configurable transfer + depth).

- **Default = Optimistic (own-only 0).** At an **unknown-ownership call site**, resolve
  toward "caller no longer owns" → **silent**. We never invent a leak we cannot prove.
  Rationale: mis-`consume` loses a real leak (recall — tolerable); mis-`borrow` demands a
  dispose that may be wrong (precision — *not* tolerable). This matches today's
  "arg-passing escapes → silent" behaviour and the whole project's stance.
- **Strict / Pessimistic** (opt-in): unknown call site → assume borrow → report the leak.
  This is RLC's soundness bias. Available as a mode, never the default.
- **Advisory channel.** `transfer:may` (partial consume) and genuinely-`unknown` transfers
  surface only through a new advisory code in the **OWN05x** band (e.g. `OWN051`
  "ownership transfer unverified"), like OWN050: shown at `--verbosity normal`+, **never
  fails CI**. The honest "we couldn't verify" signal without false-positive noise.

Crucially: **we compute the full `must`/`may`/`escape` evidence regardless of mode**, so
strict mode, the advisory channel, and debugging all stand on real data — only the default
*reporting* is optimistic.

---

## 6. Serialization & lowering

**Canonical truth in a detached `summaries[]` block** in OwnIR (versionable, optional,
cacheable, decoupled from the optional `--flow-locals` bodies):

```jsonc
"summaries": [
  {
    "method": "Acme.Io.Copy(System.IO.Stream,System.IO.Stream)",   // signature key
    "file": "src/Io.cs", "line": 42, "source": "inferred",
    "params": [
      { "index": 0, "name": "src",  "disposable": true,
        "transfer": "must", "escapes": false, "via": "dispose" },
      { "index": 1, "name": "dst",  "disposable": true,
        "transfer": "no",   "escapes": false }
    ],
    "returns": { "owned": "unknown" }
  },
  {
    "method": "Dapper.SqlMapper.DbWrappedReader.Create(...,System.Data.IDataReader)",
    "source": "annotation",
    "params": [ { "index": 1, "disposable": true, "transfer": "must", "escapes": true,
                  "via": "aliased-return" } ],
    "returns": { "owned": "aliasOf:1" }
  }
]
```

A **lowering step** (extractor-side, before core CFG) injects, per call site:
`transfer:must → effect:consume`; `transfer:no → effect:borrow`; `returnsOwned:fresh →
acquire` on the caller's local; `aliasOf:i → ` the arg's obligation is discharged by the
return's obligation (and a later direct dispose of the arg → OWN003). Pure
escape-without-transfer and all `unknown`/`may` lower to **silence** in the default mode.

---

## 7. Incremental slices

- **D5.0 — infra.** MOS dataclass (two-axis), first-party call graph, bottom-up
  SCC fixpoint, serialize to `summaries[]`. No behaviour change — compute, serialize,
  and **unit-test the lattice in pure Python** (monotonicity, SCC convergence, cap
  behaviour). First PR; fully local, no SDK.
- **D5.1a — first-party T2/T3 wiring (shipped).** The OwnIR bridge now derives a
  skeleton per `functions[]` entry, runs the D5.0 solver once, and feeds the resolved
  transfer into `_infer_param_effect`'s **forwarded** branch — the exact give-up it used
  to leave plain. A param forwarded to a consuming callee is inferred `consume`, one
  forwarded to a borrow-only callee `borrow`; `may`/`unknown` stay plain (precision-first).
  No core change (the existing `lower_call` applies the effects), no extractor change for
  first-party. Live catches, proven by synthetic OwnIR tests: double-dispose / use-after
  across a *transitive* (multi-hop) consuming call (OWN002), and the precision win where a
  correct forwarded handoff that used to read as a false OWN001 leak is now silent.
- **D5.1b — the per-call-site ownership-contract channel (shipped).** `StreamReader(stream,
  leaveOpen:…)` &c. is a *per-call-site* contract — the same ctor consumes or borrows by the
  bool literal — so it needs a per-call effect channel rather than a per-method summary. The
  bridge now pre-declares three fixed sink externs (`$consume` / `$borrow` / `$borrow_mut`)
  in every lowered `Module`; the extractor routes any call's per-argument ownership through
  them (`call $consume [x]`), and they resolve via the **same** `collect_signatures` +
  `lower_call` path as any contracted call — no new checker, no new flow lowering. The `$`
  prefix cannot collide with a real C# member. The solver also reads a forward to a sink as a
  *known* transfer (`$consume`→must, `$borrow`→no), so the channel propagates **transitively**
  through first-party wrappers, not just at the direct call. `$borrow_mut` is intentionally
  excluded from the *transitive* shortcut — the transfer lattice has no shared-vs-exclusive
  axis, so a wrapper summary would silently downgrade an exclusive loan to a shared one; the
  honest move is to decline that claim (the wrapper param stays plain) while the *direct*
  `$borrow_mut` call keeps full exclusivity through `lower_call` (Codex P2). Proven by synthetic
  OwnIR tests:
  use/double-release after `$consume` (OWN002), a `$borrow`'d-then-never-released local still
  leaking (OWN001), a clean borrow-then-release, and transitive propagation through a wrapper.
  The remaining piece is **CI/C#-only**: the extractor emitting these sink calls from the bool
  literal / annotation (paired with an A/B sample on real extractor output) — Tier-B breadth
  rides into D5.3.
- **D5.2 — T1.** `fresh`-returning calls become acquire sites → factory leaks. Includes
  `out`/`ref`-owned (another `fresh` door) before async.
- **D5.3 — Tier B breadth.** The rest of the documented BCL ownership table + `fresh`
  factories.
- **D5.4 — T4 wrap/adopt** (the obligation-identity model, §11). Lands in a **three-commit
  cadence** so the core change is de-risked: **(step 0)** a *no-op identity refactor* —
  move resource state from per-binding to per-RID with a 1:1 binding↔RID mapping, behaviour
  unchanged, validated against the green D5.0–D5.3 corpus; **(step 1)** add the `alias_join`
  lowering; **(step 2)** turn on the extractor branches that emit `aliasOf:i` for *verified*
  wrapper / factory / ctor-adopt sites. Result: **Dapper / Polly** modelled explicitly and
  added as oracle regression anchors that now resolve *with a recorded reason* (cross-link
  `field-notes-patterns.md`).
- **D5.5 — Tier C annotations** (`[OwnTransfers]` / `[MustCallAlias]` + external file).
- **D5.x — advisory** `OWN051` for `may`/`unknown`, and the strict/pessimistic mode.

---

## 8. Testing

- **Core / Python:** hand-authored OwnIR with a `summaries[]` block → assert
  OWN001/002/003 fire or stay silent (synthetic-flow; no new checker). Unit-test the
  fixpoint lattice directly.
- **Extractor / CI:** A/B samples (consuming/borrowing callee in scope vs not), the same
  pattern as the P-014 Tier B `tier-b-refs` job.
- **Oracle:** **Dapper + Polly** are regression anchors. D5.4 must keep them `own-only 0`
  *and* now model the adopt explicitly (their Infer# `oracle-only` over-reports get a
  recorded reason in `field-notes-patterns.md`).

---

## 9. Scope / non-goals

- First-party (Tier A) + curated BCL table (Tier B) + annotations (Tier C) only.
  **No IL/Cecil decompilation of third-party DLLs in v0** — the terrain map confirms it's
  unnecessary: in-solution is covered by A, the famous signatures by B, the rest by C.
  Bodies-via-IL is a separate, later frontier.
- No cross-thread / async disposal **races** (already a P-005 non-goal). `IAsyncDisposable`
  reuses the same MOS later with a release-kind dimension layered on; it changes the
  *release operation*, not the *transfer shape*.
- Summaries are may/must per the lattice, biased to precision — not a proof of disposal on
  *every* path beyond what `--flow-locals` already does.
- Cap the fixpoint; log caps.

---

## 10. Open questions remaining

1. ~~`aliasOf` in the core: shared resource id vs a synthetic discharge edge.~~
   **Resolved → §11 (the obligation-identity model): Variant B, a shared RID / alias-set.**
2. Signature-key canonicalisation across overloads / generics / partial classes (the
   `method` key must be stable and collision-free).
3. Whether `escape-without-transfer` ever deserves its own advisory (e.g. "stored in a
   non-owning field — who owns this?") or stays silent. (Start silent.)

---

## 11. Obligation-identity model (resolves open question 1)

The wrapper case (`var w = Wrap(r);` where disposing **either** `w` **or** `r` discharges
the **one** underlying resource, but disposing **both** is a double-dispose) cannot be
modelled per-binding without false positives. The decomposition "consume the arg + return
a fresh resource" (Variant A) breaks on the first legal *dispose-the-inner-directly* path,
and patching it with "this consumed handle may still be released once" silently rebuilds an
alias model anyway. The prior art (Checker Framework Resource Leak Checker / RLC#) is
unanimous and names the abstraction: a **resource-alias set** — *several references that
denote one underlying obligation; calling the must-call method on any member satisfies the
obligation for all members.* RLC's dataflow fact is literally `⟨obligation, {aliases}⟩`,
not one state per variable. We adopt it (**Variant B**).

### The model

- A **resource obligation** carries the state — a **RID** with `state ∈ {Open, Released}`
  plus light metadata (does the current scope still hold an owning alias? was ownership
  transferred out?). **Obligations live on the RID, not on the handle.**
- A **handle** (local / temp / field / param) is an access path with a `rid` and a kind
  (`owning` | `non-owning view`).
- An **alias set** is the handles sharing one RID. **By default everything is 1:1** (each
  `acquire` mints a fresh RID) — so the existing core's behaviour is unchanged until a
  summary emits an alias. N:1 happens **only** on a proven alias.

### Four operations (what lowering emits)

| op | trigger | effect on RID |
|---|---|---|
| `acquire` | `fresh` return / `new` | mint a new `Open` RID, bind the handle |
| `release` | `Dispose()` / consume-by-dispose | `Open → Released` |
| `alias_join(h, rid_of_arg_i)` | `returnKind = aliasOf:i` (T4a) **or** ctor stores arg in an owning field (T4b) | add owning handle `h` to that RID's set |
| `transfer_out` | consume-into-a-foreign-owner | RID leaves the caller's responsibility |

**T4a ≡ T4b.** A factory returning a wrapper and a constructor adopting an argument into an
owning field are the *same* operation — *a new owning handle joined the arg's alias set* —
differing only in syntax. One core primitive, two extractor recognisers.

### Errors, evaluated per-RID (not per-handle)

- **OWN001 leak:** a RID is `Open` at the end of local responsibility **and** no owning
  alias of it was released, returned as owning/fresh, or transferred out. (So a local
  dropping while *another* owning alias is alive or correctly escaped is **not** a leak —
  the Dapper "return the wrapper, inner reader is local" shape.)
- **OWN003 double:** `release` on a `Released` RID (through any alias).
- **OWN002 use-after:** use on a `Released` RID (through any alias).

### Hard v1 constraints (keep the kernel tiny)

- **`aliasOf` is must-only.** An *unproven* alias is **never** merged — RLC# notes that
  using may-alias as must is unsound, and for our `own-only 0` stance that is a red line.
  Unproven alias → optimistic-silent (treat as ordinary unknown transfer), not a guess.
- **Single-source alias.** `aliasOf:i` relates **one** source RID to **one** new handle.
  Per RLC, a class with more than one `@Owning` field cannot form the simple resource-alias
  relationship — so we don't attempt multi-field merges in v1. (A wrapper may still *adopt
  other* disposables as ordinary owning fields; that's plain T4b, not aliasing — see the
  Dapper note.)
- **Owning-only.** `alias_join` is for owning members. Non-owning views (`Span`, borrowed
  slices) stay in the existing borrow/loan machinery (OWN004, POOL005). The *vocabulary*
  unifies them as `non-owning` aliases of the same resource graph, but v1 **code** does not
  — no mixing two regimes in one lattice.
- **No whole-program heap-alias analysis.** An alias is *verified*, not inferred from heap
  reachability, by exactly the two RLC-style shapes: **(a)** the arg is forwarded to an
  `aliasOf` position and the method returns that call's result, or **(b)** the arg is stored
  into a single owning field whose `Dispose()` releases it.

### Worked anchor — Dapper `DbWrappedReader.Create(cmd, reader)`

`IWrappedDataReader` controls the lifetime of *both* the `IDbCommand` and the `IDataReader`.
So the summary is a **mix**, and that's fine: `returnKind = aliasOf:reader` (the wrapper's
identity as a reader aliases the inner reader — dispose either, once), **plus** `cmd` is
`Adopted` as an ordinary owning field (plain T4b consume). This is exactly the "more than
one owned thing" case the single-source constraint anticipates: one *alias* relationship
(the reader) and one *ordinary adoption* (the command) — not two aliases. Polly's
`BulkheadPolicy(factory())` is the pure T4b form (two semaphores adopted into owning fields,
no return-alias).

### Why land it in D5.4, not D5.0

T1/T2/T3 and Tier-B `leaveOpen` ride today's `fresh`/`consume`/`borrow` rails and need no
RID. Mature systems add resource aliasing as a *precision layer over a working core*, not as
a precondition. So the RID indirection arrives as **D5.4 step 0** (the no-op refactor),
behind the green D5.0–D5.3 corpus as a safety net — see §7. Doing it earlier spends
complexity before any alias case or regression harness exists to prove the refactor is
behaviour-preserving.

> Main reading for D5.4 specifically: **Checker Framework manual §8.5** (resource aliasing /
> `@MustCallAlias`), the **RLC paper §4** (the lightweight must-alias analysis and its
> verification rules), and the **RLC# resource-alias layer**. Polonius/Rust are intuition
> for identity-over-bindings; they are not the model for the wrapper question.

---

## Prior art (read in this order; don't reinvent blindly)

- **Rust / Polonius — for intra-body loan precision, *not* the D5 template.** The Polonius
  repo + status (provisional, `-Zpolonius`, "not ready for widespread use") and Matsakis's
  *"The borrow checker within"* show Polonius makes intra-body borrow checking
  flow-sensitive (subset/outlives, loan liveness) — it does **not** infer cross-callee
  ownership transfer. The Rust Book's ownership/borrowing chapters show how much
  cross-call precision Rust gets *for free from signatures* (by-value moves, `&T`/`&mut T`
  borrow) — which is the boundary explicitness our MOS recovers by inference + annotation.
  **Flowistry** reports modular flows matched whole-program in ~94% of cases once
  ownership facts are at the boundary — evidence the summary-contract direction scales.
- **Move borrow checker (paper).** A modular, *intraprocedural* checker over single
  modules using dependency *type signatures*, with boundary declarations (`acquires`)
  for facts not locally recoverable. Validates "you don't need whole-program analysis to
  be principled" — our Tier C.
- **Checker Framework Resource Leak Checker (RLC) + RLC# (the closest analogue — spend the
  most time here).** Leak checking as a sound, *modular* accumulation problem (no
  whole-program alias analysis), improved by: lightweight **ownership transfer**
  (`@Owning`; constructor returns owning, method returns `@Owning` by default,
  params/fields `@NotOwning` by default), **resource aliasing** (`@MustCallAlias` — return
  and arg share one obligation; wrappers verified by an aliasing call *or* by storing into
  an owning field), and **fresh-obligation-on-owning-field-update**. Must-call is an
  under-approximation (on *all* paths); a recurring FP cause is "closed on only some
  paths" — direct support for our `must` vs `may` split.
- **Industrial .NET tools (read with an engineer's eye).** **CA2000** exposes
  `dispose_ownership_transfer_at_constructor`, `dispose_ownership_transfer_at_method_call`,
  and `max_interprocedural_method_call_chain` (default **3**), and recognises the
  wrapper-return/field-store transfer. The **Roslyn** dispose-ownership design issue frames
  the exact three-way tradeoff (accept FPs / add annotations / pay for interprocedural
  dataflow). **ReSharper** uses `[MustDisposeResource]` (factories/ctors),
  `[HandlesResourceDisposal]` (sinks), external annotations, and **Optimistic vs
  Pessimistic** modes — the precedent for separating the fact model from the default
  reporting policy (our §5).

One sentence to carry back into P-005: **treat D5 as a summary-contract problem, not a
borrow-checker-core problem — and make the contract preserve the distinction between
borrow, transfer, aliasing, and mere escape.**
