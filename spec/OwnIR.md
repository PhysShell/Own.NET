# OwnIR Specification

> **Status: normative, descriptive.** This document specifies the OwnIR fact
> contract *as it is today*, derived from the working bridge
> (`ownlang/ownir.py`) and pinned by tests (see [§9 Conformance](#9-conformance)).
> Forward-looking ideas live in [`docs/proposals/`](../docs/proposals/), never
> here.

OwnIR is the **seam** between a language frontend and the OwnLang core: a
frontend (the Roslyn C# extractor, the OwnTS spike, or a hand-written fixture)
emits *facts* in this vocabulary, and the Python core
([`ownlang/ownir.py`](../ownlang/ownir.py)) lowers them onto the same checker the
`.own` DSL uses. There is **one checker** — a frontend never renders a verdict,
only facts. OwnIR is a data schema at rest (JSON), not a language.

## 1. Envelope

A facts document is a single JSON object:

```json
{
  "ownir_version": 0,
  "module": "WpfApp",
  "components": [ /* §4 owned-resource records, grouped by type */ ],
  "functions":  [ /* §5 flow bodies (intra-procedural CFG facts) */ ],
  "services":   [ /* §6 DI registration graph */ ],
  "effects":    [ /* §7 reactive-effect graph (EFF001) */ ]
}
```

`ownir_version` (int) and `module` (string) are required; `components`,
`functions`, `services`, and `effects` are each optional and default to empty.
`load()` ([`ownir.py`](../ownlang/ownir.py)) validates the shape and raises
`OwnIRError` (a `ValueError`) with an actionable message on any violation — types,
the `bool`-is-`int` trap, empty identity strings, unknown DI lifetime enums, and
a present-but-unknown resource kind are all rejected at load, before any analysis.

## 2. Versioning and the evolution policy (normative)

`OWNIR_VERSION` is a single integer, defined in
[`ownlang/ownir.py`](../ownlang/ownir.py) and **stamped identically by every
producer**: the Python core, the Roslyn extractor (`OwnSharp.Extractor`), and the
OwnTS frontend. A document whose `ownir_version` differs from the core's raises
`OwnIRError` at load — a mismatched extractor/core pair fails loudly rather than
silently mis-reading facts. A document that omits the field is read as the
current version (legacy v0 producers).

What bumps the version — the rule that keeps the three producers honest:

| Change | Bumps `OWNIR_VERSION`? |
|---|---|
| Add an **optional** field with a safe default (e.g. `type`, `source_type`) | **No** — an older core reads the record without it (see §4). |
| Add a new **resource kind** discriminator value (§4) | **Yes** — the kind selects the analysis path (§4 routing), so it is a vocabulary change, not additive metadata; a present-but-unknown kind is rejected at load. |
| Add, rename, remove, or change the meaning of a **flow op** (§5) | **Yes** — vocabulary change (see the guard below). |
| Remove or rename a required field, or change a field's semantics | **Yes** — not backward-readable. |

**Fail-loud guarantee (unknown vocabulary).** Two discriminators select an
analysis path and so must never be silently mis-read:

- **Flow op (§5).** The flow lowerer (`_lower_flow`) handles exactly the ops in
  [§5](#5-flow-bodies-functions); any other op raises `OwnIRError` — never a
  silent skip, because skipping a compound op would drop the acquire/release facts
  nested inside it and flip verdicts (a fabricated leak from a lost release, or a
  hidden leak from a lost acquire) while every existing fixture still passes.
- **Resource kind (§4).** A `resource` value the core does not know changes
  routing (`capture` → the region engine, `pool` → a pooled buffer, …), so a
  present-but-unknown kind raises at load rather than falling through to the
  `subscription` path and mis-classifying the fact. An **absent** `resource`
  field still defaults to `subscription` — that is the old-extractor-predates-the-
  field case, and adding the field is genuinely additive.

A newer extractor that introduces either against an un-bumped core therefore fails
the run instead of mis-analyzing it — which is why both **must** bump
`OWNIR_VERSION` per the table above.

## 3. What OwnIR is not

Verdict logic never lives in a frontend. The core's diagnostics (OWN0xx) come
from the same analyses the `.own` path uses
([OwnCore.md](OwnCore.md), [Lifetimes.md](Lifetimes.md), the DI/effect analyses).
The bridge's own **drift tripwire**: if the core emits a diagnostic the bridge
cannot map back to a fact handle, the bridge raises rather than dropping the
finding — a frontend cannot silently lose a verdict.

## 4. Owned-resource records (`components[].subscriptions[]`)

Each component has a `name`, a `file`, and a list historically keyed
`subscriptions` (it is really the list of owned-resource records). Each record
carries a `line` and, optionally, `released` (bool) and a `resource`
discriminator. An unreleased record is the core's **OWN001** (owned-but-not-
released) at `line`; a released one nets to a balanced acquire/release and stays
silent. The `resource`/`type` fields are additive (§2), so an older core reads
every record as a `subscription`.

| `resource` | Meaning | Tag |
|---|---|---|
| `subscription` (default) | `event +=` acquires; a matching `-=` releases | `[resource: subscription token]` |
| `timer` | a started `DispatcherTimer`/`Timer` whose `Tick`/`Elapsed` is never detached/stopped | `[resource: timer]` |
| `disposable` | an `IDisposable` field the class `new`s and never `Dispose()`s (optional `type`) | `[resource: disposable field]` |
| `subscribe` | an `X.Subscribe(...)` whose `IDisposable` result is ignored (tiered by `source`, below) | `[resource: subscription token]` |
| `capture` | a *tokenless* strong subscription whose event source provably outlives the subscriber — routes to the **lifetime/region** engine, surfaces as **OWN014** (region escape), not OWN001 | `[resource: subscription token]` |
| `local-disposable` | a local `new` of an `IDisposable` type, never disposed, not `using`-guarded, not returned | `[resource: disposable]` |
| `pool` | an `ArrayPool`/`MemoryPool` buffer `Rent`ed but never `Return`ed | `[resource: pooled buffer]` |
| `unresolved-subscription` | a `+=` whose LHS could not be bound to an event (external unreferenced assembly) — **not** owned; surfaced as advisory **OWN050**, never a leak | — |

**Source tiers** (for `subscription`/`subscribe`/`capture`, via the record's
`source`): `self` (a self-rooted, GC-collectible cycle → silent), `injected`
(unknown lifetime → OWN001 *warning*; may escalate via the DI graph, §6),
`static`/external/`unknown` (process- or longer-lived → leak). The region model
(`capture`) is precise where the token model only warns.

## 5. Flow bodies (`functions[]`)

A flow function has a `name`, a `file`, and a `body`: an ordered list of flow
ops modelling one method's intra-procedural CFG (P-016). Each op has an `op` and
a `line`. The lowerer mints a globally-unique handle per acquire so a finding
maps back to the exact C# local. The **complete** op vocabulary:

| `op` | Fields | Lowers to |
|---|---|---|
| `acquire` | `var`, optional `kind` (`"pool"`) | a new owned local (`Let`+`Acquire`); `kind:"pool"` tags it a pooled buffer |
| `release` | `var` | `Release` of the local's handle |
| `use` | `var` | `Use` of the handle |
| `overspan` | `var` | `Overspan` (POOL005: a full-length view of a pooled buffer) |
| `return` | optional `var` | `Return` (ownership transfer out) |
| `alias_join` | `var`, `src` | a new owning handle joined to `src`'s alias set (wrap/adopt, D5.4) |
| `call` | `callee`, `args`, optional `result` | a `Call` checked against the callee's contract; a `fresh`-returning callee mints an acquire for `result` (D5.2) |
| `if` | `then`, `else` (sub-bodies) | an `If` with both branches lowered |
| `while` | `body` (sub-body) | a `While` — a back-edge the core's worklist fixpoint converges over (A1) |

Anything else is a hard error (§2, fail-loud). Overwriting a tracked local (a
re-bound `call` result or `alias_join` target) kills its previous ownership
binding, so a lost prior obligation leaks rather than reading as clean.

## 6. DI registration graph (`services[]`)

An optional array feeding the **DI001** captive-dependency check (P-006), a
separate core analysis ([`ownlang/di.py`](../ownlang/di.py)):

```json
"services": [
  {"name": "EmailSender", "lifetime": "singleton", "deps": ["AppDbContext"],
   "file": "Startup.cs", "line": 12},
  {"name": "AppDbContext", "lifetime": "scoped", "deps": []}
]
```

`lifetime` ∈ {`singleton`, `scoped`, `transient`}. A singleton that reaches a
scoped service — directly or through a transient — is a DI001 finding at its
registration site. The graph is additive/optional (§2). It also feeds the region
engine: an `injected` subscription carrying a `source_type` that resolves here
uses that type's DI lifetime as a region (singleton > scoped > transient), so a
source proven to outlive the subscriber escalates its OWN001 warning to **OWN014**
(a proven captive/region escape); a co-lifetimed-or-shorter source is refuted and
silent; an unresolved `source_type` stays the honest OWN001 warning.

## 7. Reactive effects (`effects[]`)

An optional top-level array feeding the **EFF001** effect-storm check (P-020, the
OwnTS `Own.React` profile) — a separate core analysis
([`ownlang/effects.py`](../ownlang/effects.py)) over an effect's dependency array
and the stability of the render-scope values it closes over:

```json
"effects": [
  {"io": true, "line": 20, "deps": ["query"],
   "bindings": [{"name": "query", "init": "useState", "refs": [], "line": 8}]}
]
```

Each effect carries `io` (bool — whether it performs I/O; default `false`),
`line` (int), `deps` (array of dependency names), and `bindings` (the render-scope
binding table: each a `{name, init, refs, line}` — an unstable dependency, e.g. an
object/array rebuilt every render, re-triggers the effect). An I/O effect whose
dep is unstable is EFF001 (the effect storm — "not all lifecycle bugs leak memory;
some leak requests"). Like `services`, this block is additive/optional; the core
decides identity stability, not the frontend.

## 8. Rules

- **IR1.** `ownir_version` must equal the core's `OWNIR_VERSION` (or be absent);
  otherwise `load()` raises `OwnIRError`.
- **IR2.** Every producer stamps the same `OWNIR_VERSION`.
- **IR3.** Additive optional *fields* do **not** bump the version; a new/changed/
  removed **flow op** or **resource-kind value**, or a changed/removed required
  field, **does** (both are analysis-path vocabulary — see IR4).
- **IR4.** A present-but-unknown **flow op** or **resource kind** raises
  `OwnIRError` — never a silent skip or a fall-through to the wrong path.
- **IR5.** A core diagnostic the bridge cannot map to a fact handle raises —
  never a silently dropped verdict.
- **IR6.** A frontend emits facts only; all verdicts come from the core.

## 9. Conformance

Pinned by [`tests/test_ownir.py`](../tests/test_ownir.py) (the bridge suite,
`python tests/test_ownir.py`), not `test_spec.py` (OwnIR is a bridge contract,
not a surface-language rule):

- **IR1/IR2** — a mismatched `ownir_version` raises; a versionless document is
  accepted as current; each frontend producer's `ownir_version` literal is
  asserted equal to the core's `OWNIR_VERSION`.
- **IR4** — a `functions[].body` with an unknown op (`{"op": "try", …}`) raises
  `OwnIRError`; likewise a present-but-unknown `resource` kind.
- **IR5** — the unmappable-diagnostic tripwire is an internal invariant
  exercised by the flow/escape fixtures (a broken handle mapping would raise
  "cannot map back" instead of reporting the leak), not a dedicated raise-test.
- **§4/§5/§6/§7** — the resource-kind, flow-op, DI, and effect fixtures
  (`tests/fixtures/ownir/*.facts.json`) each assert their expected code.

A change to this spec without a matching change under `tests/test_ownir.py` (or
vice-versa) is a red build.
