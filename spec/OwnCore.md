# OwnCore Specification

> **Status: normative, descriptive.** This document specifies what OwnLang *is
> today*, derived from the working checker — not a wish list. Every rule here is
> backed by the implementation (`ownlang/`) and pinned by a test (see
> [§9 Conformance](#9-conformance)). Forward-looking ideas live in
> [`docs/proposals/`](../docs/proposals/), never here.

OwnCore is the small affine-ownership + borrow-permission core of OwnLang. It is
deliberately boring: a linear resource protocol with block-scoped loans, checked
flow-sensitively over a CFG (a `while` loop is a back-edge the analysis converges
over with a worklist fixpoint). No generic lifetimes, no async borrowing,
no higher-ranked anything. Buffers and lifetime regions are layered on top and
specified separately ([BufferPolicies.md](BufferPolicies.md),
[Lifetimes.md](Lifetimes.md)).

## 1. Resource identity

A **variable name is not a resource.** A resource has a stable identity `R`,
created at `acquire`. `let y = move x` transfers ownership of `R` from `x` to
`y`; both names refer to the same `R`, and `R`'s cleanup identity (its
release/return action) travels with the move. Diagnostics and codegen MUST work
through resource identity, not variable name — checking only `release x` after
`let y = move x` would be a bug.

## 2. Kinds and types

```text
Owned resource      a value that owns a resource R (acquired, moved, or an owned param)
&T   (borrow)       a shared, read-only loan of an owner
&mut T (borrow_mut) an exclusive, mutable loan of an owner
int / bool          plain values (no ownership)
```

`Moved` and `Released` are **analyzer states, not user-facing types** (§3).

## 3. Ownership states

Each owned symbol carries a *set* of states — "what could be true here across all
paths". Merges at control-flow joins take the **union**.

```text
OWNED      owns its resource R
MOVED      ownership transferred away (move / consumed by a call)
RELEASED   released / disposed
ESCAPED    ownership left the function: returned, or consumed by a callee
```

A *definite* fault holds on every path (`OWNED ∉ S`); a *maybe* fault holds on
some path (`OWNED ∈ S` but a gone-state is also present). The two get different,
sharper codes (§6).

## 4. Loans and permissions

A borrow is a first-class **Loan(owner, binding, kind)**, kind ∈ {SHARED, MUT},
*added* when the borrow opens and *removed* when it closes. Loans live beside the
states, not inside them: **the owner stays OWNED while borrowed.** Permissions are
derived on demand:

| Owner state | Active loans | Permissions |
|---|---|---|
| OWNED | none | Own + Read + Write + Drop |
| OWNED | shared | Read (Own/Write/Drop suspended) |
| OWNED | mutable | — (exclusive: owner unusable) |
| MOVED / RELEASED / ESCAPED | — | — |

Because borrows are block-scoped (a loan opened inside a `while` body also closes
inside it, within the same iteration), the set of active loans is identical on all
predecessors of a merge — back-edges included; the checker **asserts** this
invariant rather than assuming it.

## 5. Operations

```text
let x = acquire T(args)   x: OWNED, identity R created
let y = move x            y: OWNED(R), x: MOVED
borrow x as b { ... }     opens a SHARED loan of x for the block
borrow_mut x as b { ... } opens a MUT loan of x for the block
use x                     reads x (needs Read)
release x                 needs Own + Drop (no live loan); x: RELEASED
call f(args)              f must resolve; args carry effects (§8)
return x                  x escapes: needs Own (no live loan); x: ESCAPED
```

## 6. Rules (normative)

Each rule names the diagnostic it raises. Codes are catalogued in
[Diagnostics.md](Diagnostics.md).

- **R1 — release on all paths.** An OWNED resource live at scope exit (function
  end or `return`) is a leak → **OWN001**.
- **R2 — no use after release.** Using a RELEASED (or consumed/ESCAPED) resource
  on every path → **OWN002**; on only some path → **OWN009**.
- **R3 — no double release.** `release` of an already-RELEASED resource →
  **OWN003**.
- **R4 — no use after move.** Using a MOVED resource on every path → **OWN005**;
  on only some path → **OWN010**.
- **R5 — move needs Own.** `move`/`return` of a resource with a live loan →
  **OWN007**.
- **R6 — release needs Drop.** `release` while a loan is live → **OWN008**.
- **R7 — owner read needs Read.** `use` of an owner that is mutably borrowed →
  **OWN013**.
- **R8 — exclusive borrow.** `borrow_mut` while a shared loan is live →
  **OWN006**; while another mutable loan is live → **OWN011**.
- **R9 — shared excludes mutable.** `borrow` while a mutable loan is live →
  **OWN012**.
- **R10 — borrow cannot escape.** A borrow binding used outside its live block →
  **OWN004**.
- **R11 — no implicit copy.** Binding an owned resource to a new name without
  `move` → **OWN032**.
- **R12 — release needs an owner.** `release`/`move` of a non-owned value →
  **OWN034**.

## 7. Resource protocol (summary)

```text
acquire R  ==>  exactly one release of R on every path,
                OR R moved out, OR R returned as Owned.
No use after release. No double release. No release while borrowed.
```

## 8. Call boundary

Every call MUST resolve to a declared `extern fn` or a local `fn`; an unknown
call is **OWN040** (no laundering ownership through opaque calls). Each parameter
carries an effect: `borrow` (temporary shared loan), `borrow_mut` (temporary
exclusive loan), `consume` (takes ownership → owner becomes ESCAPED), or plain.
`borrow`/`borrow_mut` parameters are **noescape** by definition; the only way a
value leaves is `consume`/return. Argument/effect mismatch → **OWN041**.

## 9. Conformance

Rules are not prose-only: each is pinned by an executable example.
`tests/test_spec.py` runs one canonical program per rule and asserts the rule's
diagnostic code is among the produced codes, so the spec and the checker cannot
drift. The broader gallery (`tests/test_gallery.py`), region
(`tests/test_lifetimes.py`) and corpus suites pin exact behaviour. A spec change
without a test change (or vice-versa) is a red build.

## 10. Out of scope (see proposals, not here)

`for`/`loop`-style iteration and async (**OWN020**) — but **not** `while`, which is
analysed via a worklist fixpoint — a real type system, value-level reasoning (an
`if`/`while` condition is opaque text — control flow is modelled, not values), C#
ingestion,
and formal soundness proofs are explicitly **not** part of OwnCore today. They
are tracked in [`docs/proposals/`](../docs/proposals/).
