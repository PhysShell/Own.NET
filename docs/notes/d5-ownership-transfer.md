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

> **Implemented** in `ownlang/ownership.py` (`solve` / `solve_with_log`). This is the
> shipped algorithm; an earlier slice used a depth-capped recursive descent, which the
> SCC condensation below replaced (it removed both the exponential the cap was guarding
> against *and* the cap-induced false `unknown`s on deep chains).

- Build a call graph over first-party methods (an edge `M → C` for every callee `C` whose
  summary `M`'s summary reads: a forwarded param, or a forwarded return).
- **Condense into SCCs** (iterative Tarjan, emitted bottom-up = reverse-topological) and
  process components in that order. The summary is **context-insensitive** — one MOS per
  method, independent of caller or depth — so a callee is resolved **once** and reused
  (the summary *is* the memoization; only same-SCC callees are still mid-iteration).
- **Param transfers**: within a component, seed each `(method, param)` at the lattice
  **bottom** (⊥, "no evidence yet") and iterate the transfer equations to their **least
  fixpoint** on the small lattice; a residual ⊥ finalizes as `no`. Seeding at ⊥ (not a
  spurious `no`) is what makes recursion *exact*: a method that disposes on its base case
  and recurses otherwise resolves to `must` (every *terminating* path disposes), and
  mutual recursion grounded by a dispose carries that `must` across the whole SCC, while
  recursion that never disposes settles at `no`.
- **Returns**: a single forward target per return ⇒ an **iterative** (not recursive),
  memoized, cycle-safe chase along forward-return edges (a return-forward cycle → `unknown`).
  Iterative so a deep but acyclic wrapper chain cannot overflow the stack.
- **Lattice monotonicity is biased toward precision** (§5): uncertainty resolves toward
  "caller does not own". The **only** `unknown` the log surfaces is an extern
  (unsummarized) callee boundary — `solve_with_log` returns those, sorted; other
  `unknown`s (return-forward cycle, un-remappable `aliasOf`, missing/unrecognised shape)
  are intrinsic precision-safe degradations, deterministic from the input, not logged.
- **No depth cap.** The condensation bounds the work (each method resolved once; the
  domain is tiny — 4 transfer values × 1 escape bit × 4 return values), so the pass stays
  linear on large graphs without truncating deep chains.

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
  and **unit-test the lattice in pure Python** (monotonicity, SCC convergence, deep-chain
  termination, extern-boundary logging). First PR; fully local, no SDK.
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
- **D5.1c — transitive borrow-kind propagation (deferred).** The D5.0 summary solver is
  *transfer*-oriented: its `Transfer` lattice (no/must/may/unknown) has no shared-vs-exclusive
  axis, so an explicit `borrow`/`borrow_mut` and a `$borrow_mut` forward both seed the same
  summary-side `borrow` bucket. The **core checker already distinguishes them** (`cfg.py`
  emits `Effect.BORROW` vs `BORROW_MUT`; `analysis.py` routes them to `_check_shared_borrowable`
  vs `_check_mut_borrowable`), so the *direct* `$borrow_mut` call keeps full exclusivity — only
  the *transitive* claim through a first-party wrapper is lost. D5.1b takes the precision-safe
  decline (a wrapper that only forwards to `$borrow_mut` stays plain — a tolerated false-
  negative, never a false shared-borrow assertion). The clean fix is **not** one more `Transfer`
  enum value but an **orthogonal borrow-kind axis** (`none | shared | mut`) on the summary,
  structured sink semantics (don't normalize `$borrow_mut` away before inference), and the same
  brutally-conservative rule the must-consume path uses: infer `borrow_mut` only on a single,
  unconditional, straight-line forward to `$borrow_mut`; any mix / fan-out / conditional / loop
  → degrade to plain/unknown and stay silent. Deliverables: borrow-kind on the summary, direct
  behaviour unchanged, `$borrow_mut` wrapper tests, and mixed-path regressions proving ambiguous
  flows degrade to silence (not shared borrow). Prior art: Rust `&`/`&mut`, RustBelt exclusivity,
  Oxide's `shrd|uniq`, Polonius's per-loan invalidation — exclusivity is a distinct semantic
  axis, not coarser metadata. **Revisit trigger:** land the axis alongside the first
  *interprocedural exclusivity consumer* — i.e. when an OWN006/011/012/013-class conflict is
  checked *across* the call boundary (today exclusivity is enforced only intraprocedurally and at
  the *direct* `$borrow_mut` call). Until that reader exists the summary axis has no consumer, so
  the decline costs no observable soundness and stays cheap to reverse: the forward edges are
  already preserved in the skeleton (`PathAction(kind="forward", …)`), so the future work is
  additive (leaf borrow-kind + a join), not a solver rebuild. Tracked here so the deferral is
  recorded, not buried (Codex P2 / CodeRabbit Major on #113); live tracker: **#122**.
- **D5.2 — T1 return-value door (shipped).** A `fresh`-returning call becomes an **acquire
  site**. `_build_skeletons` now infers the return kind (`_infer_return_skeleton`): a body that
  `acquire`s a local and returns it is `fresh` (a factory), and a single returned local that is
  the result of a first-party `call` is a `forward`-return the solver propagates (factory-of-
  factory). Caller-side, a `call` op that binds a `result` whose callee summary returns `fresh`
  is **also** lowered to an `acquire` of that local, so the existing leak / double-release /
  use-after-release checks apply at the call site. Precision-first: a returned **parameter** is
  never `fresh` (that is wrap/alias, T4/D5.4), and a non-fresh / unknown return makes no claim —
  the result is never falsely owned. Proven by synthetic OwnIR tests: factory-result leak
  (OWN001 @ the call), disposed-clean, use-after-dispose (OWN002), forward-return propagation,
  and the param-return precision guard. **Extractor emission (shipped).** The Roslyn extractor
  now produces the facts that drive this on real C# (`--flow-locals`): a `new`'d local returned
  bare outside a `try` stays tracked and emits `acquire …; return <var>` (so a first-party
  factory is classified `fresh`), and `var r = FirstPartyFactory()` — a call to a source-visible
  method returning an owned `IDisposable` — emits a `call callee=… result=r` op (the core mints
  the acquire only when it proves the callee `fresh`, so a non-fresh call is never falsely owned).
  `IsFirstPartyDisposableFactory` gates on a source-declared, non-void, disposable, non-dispose-
  optional return; same-name overloads are merged into one conservative summary (§10 q2) —
  classified `fresh` only when **every** overload returns fresh, else silent. Validated
  end-to-end by `FactoryLeakSample.cs` in CI: a dropped factory result leaks **interprocedurally**
  (OWN001 at the call site — beyond the flat detectors), while the disposed caller and the factory
  itself stay silent. **Remaining T1 door:** `out`/`ref`-owned parameters (another `fresh` source)
  — extractor-side recognition of an out-assignment as a fresh acquire — rides into a later slice
  before async.
- **Bridge branch-scope fix (shipped — separate from the D5 transfer ladder).** The OwnIR→core
  bridge uses a *flat* `localmap` but emitted each synthetic `Let` *inside* the branch block it
  occurred in, so a local `acquire`d in **both** branches of an `if` and released **after** the
  merge (`if c: r=acquire() else: r=acquire(); release r`) lowered to a post-merge `release` of
  an out-of-scope handle → the core reported **OWN030 (undefined name)** and `check_facts` raised
  `OwnIRError`. It predated D5 (reproduced with a **plain `acquire`**, no fresh/factory path);
  D5.2's call-result acquire only added another way to reach it. Fixed by making `acquire`
  lowering **branch-aware**: `_hoisted_branch_locals` finds locals acquired at depth ≥ 1 whose
  shallowest reference is at **depth 0** (function-top, so function-scope is the common dominator),
  and `to_module` declares each **once at the function's outer scope** (a single `Let`), skipping
  the in-branch acquire. A balanced cross-branch release is now CLEAN; an un-released one still
  leaks **OWN001**. Covers both the plain `acquire` and the `fresh` call-result form, and a hoisted
  ArrayPool rent keeps its `pool` kind (so it still reports as a pooled buffer). We deliberately did
  **not** soft-skip OWN030 (it would mask genuine lowering drift; the strict map-or-raise invariant
  is load-bearing). Because hoisting makes a conditional acquire **unconditional**, it is gated by
  `_branch_hoist_safe` — a definite-assignment walk that blocks the hoist when a branch can
  early-`return` before the release on a path that did not acquire the local (else the hoisted
  resource would leak there — a *false* OWN001, e.g. `if c: acquire r else: return; release r`).
  Tests: `branch_merge` / `branch_factory` / `one_branch` (clean), `branch_leak` (OWN001),
  `pool_branch` (pooled kind preserved), `guard` (early-return → not hoisted, no fabricated
  finding). **Narrower remaining limitations** (each a documented xfail lock, fixed by a later
  loop-/dominator-aware model): a reference at depth ≥ 1 inside a nested block (`nested_branch` —
  function-top isn't the common dominator), a `while`-body acquire (`loop_acq` — iterations are
  cumulative), and the early-return guard shape (`guard` — stays a loud OWN030 raise rather than a
  false positive). (Bridge branch-scope fix: Codex P2 on #116; loop exclusion Codex P1, hoist
  safety predicate + pool-kind preservation CodeRabbit on #120.)
- **D5.3 — Tier B breadth.**
  - **Producer side — `fresh` factories (shipped).** A curated `_BCL_FRESH_BY_NS` table in the
    OwnIR bridge (`ownir.py`), grouped by namespace, marks well-known BCL factories whose
    return the caller owns: **System.IO** stream factories (`File.OpenRead/OpenText/OpenWrite/
    Open/Create/CreateText/AppendText/OpenHandle`) and **System.Security.Cryptography**
    algorithm factories (`SHA1/SHA256/SHA384/SHA512/MD5.Create`, `Aes/RSA/ECDsa.Create` — a
    leaked `using var sha = SHA256.Create()` is a common real leak). A `call` to one binds a
    `fresh` result via the SAME `_callee_returns_fresh` path the first-party T1 inference uses
    (now the single source of truth for the leak pre-scan, branch-hoist safety, and lowering),
    so a leaked `var s = File.OpenRead(p)` surfaces as OWN001 *at the factory call* — invisible
    before (no body to infer from; see `corpus-benchmark.md`). Matched conservatively (Codex):
    ONLY the bare `Type.Method` or the fully-qualified identity under that type's real namespace
    (`System.IO.File.OpenRead`, `System.Security.Cryptography.SHA256.Create`) — a same-named
    factory in another namespace (`MyCompany.File.OpenRead`, `MyCrypto.SHA256.Create`) is **not**
    a match. Overload-ambiguous names are excluded (`new StreamReader(stream)` adopts its arg;
    `Process.Start` is also an instance method returning `bool`), so we never fabricate ownership
    for a look-alike. A **first-party summary overrides** the table (`_callee_
    returns_fresh` trusts a known body over Tier B), and a first-party **wrapper** that
    returns a factory result (`Make(){ return File.OpenRead(p) }`) is itself `fresh`, so a
    dropped `Make()` leaks too (the return skeleton propagates BCL freshness instead of
    forwarding to the external, unsummarizable callee). Pure factories only — overload-
    ambiguous *wrappers* that adopt an arg (`new StreamReader(stream)`) are excluded (sink/T4).
    Tests in `test_ownir.py` (leak / disposed-clean / use-after-dispose / namespace-qualified /
    non-System.IO look-alike rejected / first-party override / wrapper-fresh recall / a
    non-disposable `File.ReadAllText` making no claim).
  - **Sink side — `leaveOpen` breadth (remaining, extractor-side).** The documented
    consume/borrow table (`StreamReader`/`StreamWriter`/`CryptoStream`/… by the `leaveOpen`
    bool literal) rides the existing `$consume`/`$borrow` channel (D5.1b); its breadth is a
    C#-extractor table (the bool literal is a per-call-site fact the extractor sees), so it is
    CI/C#-only, not a pure-Python slice.
- **D5.4 — T4 wrap/adopt** (the obligation-identity model, §11). Lands in a **three-commit
  cadence** so the core change is de-risked.
  - **Step 0 — the no-op RID identity refactor (shipped).** Resource state in the core flow
    analysis (`analysis.py`) moved from per-binding to per-**RID**: `State.var` is keyed by an
    obligation id, and a handle (local/param `Symbol`) denotes a RID through `State.handle_rid`.
    The mapping is **1:1** (each `acquire`/owned-param `mint`s its own RID, `RID == id(sym)`),
    so the analysis is byte-for-byte the pre-RID behaviour — the whole green corpus is the
    proof. `join` merges `handle_rid` and raises (always-on, `-O`-safe) on a conflicting
    mapping, locking the single-mapping invariant. Tested directly in `test_rid.py` (rid_of
    1:1 default, mint, the join union/raise, and end-to-end leak/release/double/return-escape
    unchanged).
  - **Step 1 — the `alias_join` lowering (shipped).** A new core primitive `AliasJoin(handle,
    src)` (AST + CFG + `analysis.step`) makes `handle` a **new owning alias of `src`'s RID**:
    the two handles denote one obligation, `src` stays owning (unlike `move`). Because state
    lives on the RID, the existing per-RID checks now do T4 for free — releasing or escaping
    through **either** alias discharges the one resource (clean), a leak of the shared RID is
    reported **once**, releasing **both** is OWN003, and using either after release is OWN002.
    The OwnIR bridge lowers an `alias_join` flow op (`var` = the new owning handle, `src` = the
    adopted local) to it; an `alias_join` over an untracked `src` makes no claim (optimistic-
    silent, the v1 must-only rule, §11). **T4a ≡ T4b**: one primitive, two extractor recognisers
    (step 2). The **Dapper precision win** is proven — a factory that acquires `inner` locally,
    `alias_join`s a wrapper `w`, and **returns `w`** drops `inner` as a local but its obligation
    escaped through `w`, so per-RID evaluation reports **no leak** (the own-only-0-with-a-reason
    case the model exists for). Tests in `test_ownir.py` (release-wrapper / release-inner clean,
    drop-both leaks once, double-release OWN003, use-after-release OWN002, untracked-src silent,
    return-wrapper precision). *Limitation (deferred):* `alias_join` is straight-line only — an
    alias minted inside one branch of an `if` that merges with a non-aliasing path is out of v1
    scope (the bridge emits it straight-line at the wrapper site); the conflicting-merge raise
    in `_join_handle_rid` keeps that loud rather than silently wrong.
  - **Step 2 — extractor emission, ctor-adopt at the construction site (shipped, first slice).**
    The Roslyn extractor now emits the `alias_join` flow op for a *verified* constructor adopt:
    `var w = new W(x)` where `W` is first-party and adopts `x` into an owning field. The adopt is
    proven, never guessed (§11 must-only): `TryAdoptedArgIndex` requires `W` to dispose **exactly
    one** owning field **unconditionally** in its `Dispose()` (`DisposedOwningFields` — a top-level
    `_f.Dispose()`/`_f?.Dispose()`, conditional/nested excluded) **and** that field to be assigned
    **directly from a single ctor parameter** (`_f = p;`); the call must be positional up to that
    slot. Any ambiguity → no claim. The escape pass gains a matching exception
    (`IsAdoptedArgOfBoundedWrapper`): the adopted arg stays tracked **only** when the wrapper is a
    non-`using` local candidate that does not itself escape (`LocalEscapesSyntactically`,
    deliberately over-approximating so we *decline* rather than fabricate). Then the construction
    site emits `alias_join var=w src=x` instead of an acquire, so the per-RID core (steps 0/1) does
    the rest: dispose either → clean, dispose both → OWN003, drop both → one OWN001 on the inner.
    Validated end-to-end on real C# by `FactoryAdoptSample.cs` in CI (adopt-clean / dispose-inner-
    clean silent, drop-both OWN001 on the inner once, dispose-both OWN003, and a **non-adopting
    holder** making no claim so disposing both is not a false double-dispose).
  - **Step 2 remainder (deferred).** Shape **(a)** — return-alias / caller-side propagation
    (`var r = Create(reader)` where `Create` returns `aliasOf:reader`) — and the field-store-to-
    `this` form of (b) (the wrapper adopts into *its own* field across the boundary, e.g. Polly's
    `BulkheadPolicy(factory())`), plus the cases the v1 gate declines (a `using` or escaping
    wrapper). These need return-skeleton `aliasOf:i` inference and/or cross-method field analysis;
    they ride a later slice. Once shape (a) lands, **Dapper / Polly** become oracle regression
    anchors that resolve *with a recorded reason* (cross-link `field-notes-patterns.md`).
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
- No depth cap: the SCC condensation bounds the work (§4); the only logged residual is an
  extern-boundary forward (`solve_with_log`).

---

## 10. Open questions remaining

> Sequencing for closing these — together with the deferred §7 slices, #122 and
> #146 — lives in [interprocedural-roadmap.md](interprocedural-roadmap.md).

1. ~~`aliasOf` in the core: shared resource id vs a synthetic discharge edge.~~
   **Resolved → §11 (the obligation-identity model): Variant B, a shared RID / alias-set.**
2. ~~Signature-key canonicalisation across overloads / generics / partial classes (the
   `method` key must be stable and collision-free).~~ **Partially addressed:** the call
   node names its callee `{Type}.{Method}` with no parameter signature, so a true
   signature key is not reconstructable core-side. Instead, same-name overloads are
   **merged into one conservative summary** (`_merge_skeletons` in `ownir.py`): a join at
   (name, parameter-index) granularity — `must` only when every overload consumes that
   index, `fresh` only when all agree — never a fabricated `must`/`fresh`. **Residual:**
   argument-type / per-arity disambiguation would need call-site type info the fact stream
   does not carry (arity is available but not yet modelled).
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
