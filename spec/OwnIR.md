# OwnIR Specification

> **Status: normative, descriptive.** This document specifies the OwnIR fact
> contract *as it is today*, derived from the working bridge
> (`ownlang/ownir.py`) and pinned by tests (see [§10 Conformance](#10-conformance)).
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
  "effects":    [ /* §7 reactive-effect graph (EFF001) */ ],
  "protocols":  [ /* §8 obligation protocols (OBL001-005): rules */ ],
  "protocol_functions": [ /* §8 obligation protocols: per-method events */ ]
}
```

`ownir_version` (int) and `module` (string) are required; every other top-level
block is optional and defaults to empty.
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

**Publisher provenance** (additive/optional, #146): an `injected` `subscription`
record may carry `source_provenance: "returned_fresh"` — the frontend's
compilation-wide pass proved that **every** in-compilation caller of the method
passes a publisher it freshly constructs and lets escape only into this call or
its own `return`. The subscription is then bounded by the returned publisher's
lifetime (the handler dies with it) and is dropped silently, like a
locally-constructed source. The instance-level provenance beats the type-level
DI hop (§6). Only this exact value routes; any other string keeps the honest
OWN001 warning, and a non-string value is rejected at load.

**Inline suppression** (additive/optional, #209): any owned-resource record may
carry `ignore_reason: "<reason>"` — the mandatory justification of an inline
`[OwnIgnore("reason")]` at that site (P-004). When present and **non-empty**, the
core still **mints** the finding but marks it **suppressed**: it is excluded from
the exit code and the human findings stream, yet still **counted** (a summary
tally) and carried in SARIF `suppressions` (`kind: "inSource"`, the reason as
`justification`) — visibility over silence, never a silent drop. The reason is
mandatory by design: an **empty** string (or an absent field) does **not**
suppress — a reason-less `[OwnIgnore]` is never a silent accept. The core, not the
frontend, decides the verdict (P-013 "one checker"): the extractor only records
the reason it read. A non-string value is rejected at load. The Roslyn frontend
currently reads `[OwnIgnore]` on **`IDisposable` field declarations** (the clearest
attribute site — the record anchors at the field); other sites are follow-ups.

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
| `call` | `callee`, `args`, optional `result`, optional `sig` | a `Call` checked against the callee's contract; a `fresh`-returning callee mints an acquire for `result` (D5.2) |
| `if` | `then`, `else` (sub-bodies) | an `If` with both branches lowered |
| `while` | `body` (sub-body) | a `While` — a back-edge the core's worklist fixpoint converges over (A1) |

Anything else is a hard error (§2, fail-loud). Overwriting a tracked local (a
re-bound `call` result or `alias_join` target) kills its previous ownership
binding, so a lost prior obligation leaks rather than reading as clean.

### 5.1 Per-overload signature keys (`sig`, interprocedural stage 2)

A `functions[]` record and a `call` op may both carry an **optional** `sig`: the
method's canonical parameter-type list — fully-qualified names, comma-separated,
no spaces, generic arity via backtick, `global::` stripped (e.g.
`"System.IO.Stream,System.Boolean"`; `""` for a zero-parameter overload). When an
**overloaded** name's records carry `sig`, the inference layer keys one summary
per overload as `name(sig)` *beside* the name-merged conservative summary, and a
`call`/forward edge whose `sig` matches resolves that overload's own contract —
one borrow overload no longer dilutes its siblings' consume/fresh verdicts.

The fallback rule is load-bearing: a `sig` missing or unmatched on **either**
side of an edge resolves against the name-merged summary (the pre-stage-2
behaviour) — degraded, never a wrong overload — and the `first_party` /
`overloaded` suppressions stay keyed on the **bare** name regardless of `sig`
(INV4). A producer without type information (ownts) simply omits the field.
Additive/optional per §2: no `OWNIR_VERSION` bump; a present-but-non-string
`sig` on a function record is rejected at load, on a flow op it reads as absent.

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

## 8. Obligation protocols (`protocols[]` / `protocol_functions[]`)

Two optional top-level arrays feeding the **OBL001–OBL005** obligation-protocol
checks (P-025) — a separate path-sensitive core analysis
([`ownlang/obligations.py`](../ownlang/obligations.py)) for *project-specific
temporal invariants*: a method briefly breaks one of its own invariants
(`IsLoaded = false` while the document rebuilds) and must restore it before a
*barrier* — a configured call (`OnPropertyChanged("Document")`) or a method
exit. The general checker cannot know that `IsLoaded` means "the document is
consistent"; the project declares it.

`protocols[]` is the **rule side** (project configuration):

```json
"protocols": [
  {"name": "DocumentLoading",
   "opens":  {"kind": "assign", "target": "IsLoaded", "value": false},
   "closes": {"kind": "assign", "target": "IsLoaded", "value": true},
   "barriers": [{"kind": "call", "callee": "OnPropertyChanged",
                 "args": ["Document", "Rows", "Totals"]}],
   "allow":    [{"kind": "call", "callee": "OnPropertyChanged",
                 "args": ["IsLoaded", "IsBusy", "Progress"]}],
   "exit_barriers": true,
   "scope": {"methods": ["BigDocumentViewModel.LoadBigDocument"]}}
]
```

`opens`/`closes` are required matchers (`assign` with a stated boolean `value`,
or `call`); `barriers` lists the events the obligation must not cross while
open (`allow` exempts explicitly safe ones); `exit_barriers` (default `true`)
makes `return`/`throw`/end-of-body barriers too; `scope.methods` restricts the
rule to named methods (exact, or a trailing `Type.Method` suffix). Tight
scoping is the false-positive control: a rule only fires where the project
asked. A scoped protocol matching no reported method is surfaced as the
advisory **OBL005** (a dead rule), never a verdict.

`protocol_functions[]` is the **fact side** — one ordered event tree per
method, in the flow-body shape of §5 (`if`/`while` nest; frontends thread
`finally` bodies onto exits exactly like the flow lowering):

```json
"protocol_functions": [
  {"name": "Broker.BigDocumentViewModel.LoadBigDocument",
   "file": "BigDocumentViewModel.cs",
   "events": [
     {"ev": "assign", "target": "IsLoaded", "value": false, "line": 184},
     {"ev": "if", "line": 220, "then": [
       {"ev": "call", "callee": "OnPropertyChanged", "arg": "Document", "line": 241}
     ], "else": []},
     {"ev": "assign", "target": "IsLoaded", "value": true, "line": 260}
   ]}
]
```

The event vocabulary is `assign` / `call` / `return` / `throw` / `if` /
`while` — closed and fail-loud like a flow op (IR4): a present-but-unknown
`ev` or matcher `kind` is rejected at load. Both blocks are additive/optional
(an older core ignores them — the IR3 additive rule), and their internal
vocabularies version *with the blocks*: extending them is a vocabulary change
under IR3/IR4.

The obligation state is a set over {OPEN, CLOSED} joined by union at merges,
so the definite/maybe split (OBL001/OBL003 vs OBL002/OBL004) falls out of the
lattice the same way OWN002 vs OWN009 does. Precision rules (normative):

- an **opaque write** to a tracked flag (`"value"` absent) may *discharge* an
  open obligation but never *creates* one — the checker never invents a
  violation;
- a **call the protocol does not name is neutral** (no discharge, no
  crossing); interprocedural obligation summaries are a later slice (P-025);
- a call with an **unknown argument** does not match an args-narrowed barrier.

Findings anchor at the barrier site (OBL001/002, and OBL003/004 for
`return`/`throw`) or at the *open* site for an obligation leaking off the end
of the method (the OWN001 anchor-at-acquire precedent), and carry an ordered
evidence slice: *opened here → barrier fired here (→ closed only here, after
the barrier)*. Messages are deliberately line-free so baseline ratchets and
FP-judge overlays that fingerprint on (path, rule, message) survive unrelated
edits.

## 9. Rules

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

## 10. Conformance

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
- **§8** — pinned by [`tests/test_obligations.py`](../tests/test_obligations.py):
  the event/matcher vocabularies are bound to the schema's `protocolEvent`/
  `protocolMatcher` consts both ways, an unknown `ev`/`kind` raises at load,
  and the `protocol_isloaded_*` fixtures assert the OBL codes end-to-end.

A change to this spec without a matching change under `tests/test_ownir.py` (or
vice-versa) is a red build.
