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
| Add an **optional** field with a safe default (e.g. `type`, `source_type`, `column`) | **No** — an older core reads the record without it (see §4). |
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
carries a `line` and, optionally, a `column`, `released` (bool) and a `resource`
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

### 4.1 `column` — the optional source coordinate (normative)

A record, a contract param, or a flow op MAY carry a `column` beside its `line`:
the **1-based** source column of the *same* node the `line` anchors on. It is
optional and additive, so it does not bump `OWNIR_VERSION` (§2).

Three rules, and they are the whole contract:

1. **Same node.** The column belongs to the node the line came from. Pairing one
   node's line with another's column yields a well-formed coordinate pointing at
   a place that does not exist — worse than an absent field, because nothing
   downstream can detect it. The one place this bites today is the OWN025
   (POOL005) verdict, which anchors on the *view* site rather than the acquire:
   it therefore reports **no** column at all rather than the acquire's.
2. **Never invented.** A producer that does not know the column omits it. It is
   never `0`, never `1`, and never recovered by re-reading the source line —
   `Diagnostic._caret_col` does exactly that for its human-readable caret, by
   pulling a name out of the message text and falling back to the indentation.
   That is a renderer heuristic, not a coordinate the analysis computed.
3. **Validated, not coerced.** `load()` rejects a `column` that is not a 1-based
   integer — `0`, negative, `bool`, string, float and array all raise
   `OwnIRError`, and the walk recurses into `if`/`while` bodies. `bool` is
   rejected explicitly: `True` is an `int` in Python and would otherwise read as
   column 1. It is bounded above as well: a column above `2147483647` is
   rejected, the same domain a `line` carries (§4.2), because a column no
   consumer can hold is not a usable coordinate either. `check_facts()`, which
   may be called directly on un-validated facts, degrades to absent instead.

A flow-local handle is minted on five paths — a contract param, a direct
`acquire`, an `alias_join`, a fresh-returning call `result`, and a branch acquire
hoisted to the function scope — and the column travels all five. An `alias_join`
handle carries one, but a finding still anchors at the source acquire, because
the alias shares its obligation rather than creating a second one.

The column rides to SARIF as `region.startColumn`, alongside `startLine` and only
when a real `startLine` is present. It is what OwnAudit's `finding-occurrence/v1`
physical anchor reads (Own.NET#317, PhysShell/OwnAudit#58); a finding without one
is anchored line-only, which is a degradation rather than a failure.

### 4.2 Defensive limits on externally supplied structure (normative)

`OwnIR` is untrusted input: a file a frontend wrote, that `load()` reads. Two of
its shapes were unbounded, and an unbounded contract is only *implementable* in
a language that happens to have the same capabilities the reference does. Both
are now bounded, and the bound is part of the vocabulary rather than a property
of whichever consumer reads it first.

**Source coordinates are bounded twice: a representable form, and a domain
inside it.**

The two are different rules about different things, and a consumer that folds
them reports the wrong reason for half its rejections.

*Form.* Every coordinate integer — every `line` and every `column` — fits a
**signed 64-bit** integer. Python integers are unbounded, so the reference
accepted values no other consumer could represent; a coordinate nothing
downstream can hold is not a usable coordinate, and leaving it legal turns
every port into a source of "the reference accepted this and I cannot".

*Domain.* Inside that form:

- every `line` lies in **`[0, 2147483647]`**;
- every `column` (§4.1) lies in **`[1, 2147483647]`**, or is absent, or `null`.

**2147483647 is `int32`, and int32 is the line type of every consumer this
project feeds**: Roslyn's `LinePosition.Line` is an `int`, LSP's `uinteger` is
capped at `2^31 - 1`, and .NET diagnostics carry the same width. A line wider
than that cannot reach the place it points at, whatever it can be stored in.

**`0` is legal and means "unknown / file-level".** It is the reference's own
default for an absent line (`s.get("line", 0)` throughout `load()`), and the
corpus carries it in the goldens as well as the inputs, so the bottom of the
domain reads the reference rather than tightening it. A **negative** line is
rejected: no producer emits one — the Roslyn extractor writes
`StartLinePosition.Line + 1` off a 0-based position — and nothing downstream can
point at it. The lower bound of a `column` is one higher because a column is
1-based (§4.1); `0` there stays a producer bug rather than a sentinel.

Every line-bearing field is validated: `components[].subscriptions[].line`,
`services[].line`, `services[].ctor_line`,
`services[].root_resolve_sites[].line`, `services[].scope_cache_sites[].line`,
`effects[].line`, `effects[].bindings[].line`, `functions[].params[].line`,
`protocol_functions[].events[].line`, and the `line` on a flow op inside
`functions[].body` — the last recursing through `then`, `else` and `body`
exactly as the `column` walk does. Both of the fields this section previously
recorded as validated **nowhere** — `components[].subscriptions[].line` and the
flow-op `line` — are validated now, for type as well as for domain: the open
contract question that recorded ("whether a coordinate no rule reads should
nevertheless be well-formed") is answered **yes**, because the tolerant door
does read it and anchors findings on it.

**Flow bodies and protocol event trees nest at most 32 levels.**

`functions[].body` and `protocol_functions[].events` nest through `then`,
`else` and `body`. The limit counts those enclosing bodies — the top-level list
is level 0 — so a document nesting exactly 32 is accepted and 33 is rejected.

32 is chosen from measurement at both ends:

- the deepest nesting in any `OwnIR` fixture in this repository is **3**
  (`tests/fixtures/lowered/hoist_neg_nested_depth.facts.json`); the deepest
  event tree is **2**;
- a JSON parser applying the widespread 128-level recursion cap stops accepting
  these documents at **62** levels, because each `if` costs two JSON levels
  (an object and an array).

So the limit sits an order of magnitude above anything a producer has emitted
and roughly half way to the ceiling a consumer can still parse. It is expressed
in the `OwnIR` domain — nested bodies — and not in JSON levels, because nested
bodies are the thing a frontend can reason about; the ratio between the two is
an encoding detail.

Every limit here is a **rejection at the strict door**, not a coercion.
`check_facts()` on un-validated facts degrades instead — two entry points, two
contracts, as with `column` in §4.1, and now on the same terms for lines:

- a `column` outside its domain (or of the wrong type) reads as **absent**;
- a `line` outside its domain (or of the wrong type) reads as **`0`** —
  "unknown / file-level", the value an absent line already reads as.

**Degrade, never clamp.** `2147483648` does not become `2147483647` and `-1`
does not become `1`: a clamp moves the finding to a *real* line that is not the
one the producer meant, which is worse than saying nothing. The rule is the
same never-invent rule §4.1 states for columns.

The strict door never reaches the degrade: a document `load()` accepts has no
out-of-domain coordinate by construction. That is asserted rather than assumed
— `tests/test_ownir_defensive_limits.py` re-reads every document the #259 cp1
ledger records as accepted and checks each coordinate against this section.

## 5. Flow bodies (`functions[]`)

A flow function has a `name`, a `file`, and a `body`: an ordered list of flow
ops modelling one method's intra-procedural CFG (P-016). Each op has an `op` and
a `line`, and optionally a `column` (§4.1). The lowerer mints a globally-unique
handle per acquire so a finding maps back to the exact C# local. The **complete**
op vocabulary:

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

### 5.2 The guarded-fact sidecar (`guarded_facts`, P-037 A2.1, door-registered A2.2-D)

A flow function may carry an **optional** `guarded_facts` object: the frontend's
raw record of what flows into each *relevant* call of the method and what each
`if` tests. It is the input the guarded summary engine of P-037 (#304) reads
once phase B wires it. Through A2.1 it was validated only by the producer and
carried as an unknown field at both doors; A2.2-D makes it **known, fail-loud
vocabulary at both doors** — `load()` and the Rust strict door now validate
its shape, closed vocabularies and coordinate domains, with matching refusal
categories — while staying **semantically inert**: neither engine's lowerer,
summaries or verdicts reads it, `body` stays authoritative, and a run's MOS
documents and verdicts must not move whether it is present, absent, or valid
but wrong about everything it can be wrong about
(`docs/notes/p037-formal-kernel.md` §10.3 and §10.6.14; the A2 baselines
under `docs/evidence/` witness the pre-registration inertness,
`scripts/p037_sidecar_inertness.py` the door-registered inertness,
`corpus/p037-shapes` pins the shapes per case). Additive/optional per §2: no
`OWNIR_VERSION` bump. The JSON Schema (`$defs/guardedFacts`, `guardedCall`,
`guardedArg`, `guardedGuard`) is the normative shape; this section is its
meaning. `version` (the sidecar's own vocabulary version, currently the sole
legal value `1`) passes the same representable-integer-form gate every other
integer field in this document gets — a boolean, a string, or a non-integral
number is a shape violation, never a version mismatch — before being checked
against that closed value.

Two rules govern every field (P-037 §10.2, the raw-fact boundary):

- **Roslyn reports source facts, never P-037 interpretations.** `bool_const true`
  is a fact; `const-pos` is an interpretation relative to the callee's *elected*
  guard and belongs to the engine. `param` names the caller's own parameter by
  declared ordinal; whether that is an `id` or a `neg` edge is the engine's
  reading. There is no `fresh_owned`: a call result is `call_result{callee,sig}`
  and freshness is a summary conclusion.
- **Absence is the fail-closed signal.** A guard that is not eligible — G-V1: a
  by-value boolean parameter, or the null-ness of a by-value reference (or
  nullable) parameter, the self-null split included; G-V4: the parameter is never
  assigned, incremented, taken by `ref`, or passed by `ref`/`out` anywhere in the
  body — gets **no** entry, never `stable: false`, so an old producer, an
  unstable parameter, an unsupported predicate and unknown syntax all degrade the
  same way. The same stability rule decides whether an *argument* naming a
  parameter is a `param` fact or `opaque`.

```text
guarded_facts:
  version         1
  calls[]         one per RELEVANT call: a disposable local of this method (any
                  candidate, escaped or not) or an owned parameter flows in, as an
                  argument or as a reduced extension method's receiver, directly or
                  through a transparent wrapper or a may-value form (A2.2-1, below);
                  an invocation expression or, since A2.2-2, a constructor call
    call_kind     absent for a method invocation; `object_creation` for a
                  constructor call; `delegate_invocation` for a call through a
                  delegate value (callee/sig null, first_party false);
                  `constructor_initializer` for a constructor's `: base(...)` /
                  `: this(...)` (the target constructor is the callee)
    site          {line, column} — start of the invocation expression (identity)
    statement_line the enclosing statement's line (what the legacy ops carry)
    form          statement | initializer | expression
    callee, sig   the resolved method's functions[] key and §5.1 signature, or null
    first_party   the callee has a declaration in this compilation
    args[]        by DECLARED PARAMETER ORDINAL, strictly ascending:
                    var{name}                 a disposable local of this method
                    param{source_param[,negated]} a stable by-value parameter (`!p` -> negated)
                    bool_const{value}         a boolean literal
                    null_literal · object_creation
                    call_result{callee,sig}   the result of a resolved call
                    opaque                    everything else
  guards[]        one per ELIGIBLE `if`: {site, param, predicate, negated}
                  predicate: truth | not_null | is_null
```

Binding rules: a named argument resolves to its parameter; a reduced extension's
receiver is ordinal 0 (the unreduced declaration is the summary's home),
whether written `r.Ext(...)` or `r?.Ext(...)` (P-037 A2.2-4R3: the receiver
of a member binding is the enclosing conditional access's expression); an
argument bound to a `params` array collapses to one `opaque` slot, each
expanded element classified with its own element conversion (P-037 A2.2-4R2:
a handle under parentheses or `!` still flows, a boxed struct handle or one
passed through `op_Implicit` does not); an omitted optional argument has no
entry; a `ref`/`out` argument is `opaque`. For an
**unresolved** callee (`callee: null`) the ordinal is the *source position* —
there is no declaration to bind against, and the record says so rather than
guessing. Calls inside lambdas and local functions belong to those bodies, not
to the method. A `var` fact names the local by its spelling but is bound by
its symbol (P-037 A2.2-4R1): two locals spelled alike in sibling scopes are two
symbols, and only the candidate's references are facts; a lambda-local
creation makes nothing of the same spelling outside the lambda a handle.

Value flow (P-037 A2.2-1; the taxonomy is frozen in
docs/notes/p037-formal-kernel.md §10.6 and `corpus/p037-relevance/registry.json`).
Whether a handle flows into a slot is decided by a small value-flow walker over
Roslyn's operation tree, because syntax lies about conversions, and it is
decided independently of how precisely the slot can be represented:

- **transparent** — parentheses, the null-forgiving `!`, and a built-in
  identity or reference conversion that invokes no user-defined operator
  (implicit at the parameter, or written as a cast or an `as` the static type
  guarantees; a checked explicit reference conversion passes the same
  reference or throws before the call, never an alternate value). The same
  value reaches the callee, or the call is not entered: the fact is the
  unwrapped one (`var` / `param`) and the call is relevant.
- **may-value** — the conditional operator, `??`, a switch expression, and an
  `as` the static type does *not* guarantee (it may yield null). A handle among
  the alternatives, reached through transparent edges only, keeps the call
  relevant; the slot is `opaque`, because the vocabulary has no "one of" fact
  and no `mentions` list — opaque is opaque.
- **excluded** — a user-defined conversion, implicit or explicit, however it is
  spelled (`TakeBox(r)`, `TakeBox((Box)r)`): a hidden call whose result, not the
  handle, reaches the callee. Not relevant, whatever transparent-looking syntax
  surrounds it. A boxing conversion of a struct handle (`Sink(object)` given a
  disposable struct) is excluded the same way: the callee receives a boxed
  copy, never the value's ownership identity. Likewise a call result, a
  container or tuple construction, a closure, a method group, an ordinary
  instance receiver and a storage assignment carry no relevance to the
  enclosing call; each is a named exclusion of the frozen taxonomy, not a call
  fact.

Relevance and representability stay orthogonal: an unstable owned parameter,
a `params` slot, a `ref`/`out` argument and a may-value form are all `opaque`
*and* relevant. The census shapes `corpus/p037-shapes/sidecar-*` pin each of
these by name.

Constructor calls (P-037 A2.2-2). A constructor call is a call site of its
own, tagged `call_kind: object_creation`: the site is the `new` expression
(explicit or target-typed), the callee is the constructor's `functions[]` key
(`{Namespace.Type}..ctor`, the spelling a constructor's own record carries),
`sig` is the constructor's §5.1 signature, and the arguments bind to the
constructor's declared ordinals by the same mechanism as an invocation (named
arguments resolved, a `params` slot or a `ref`/`out` argument `opaque` but
relevant). Only the argument list binds: an object initializer attached to the
creation is a storage assignment and a collection initializer element is
container construction, both named exclusions, never call arguments. A `new`
inside an argument of another call is that call's `object_creation` argument
fact, which is not a handle: the constructor gets its own call fact, the
enclosing call gets none from it. Array creation is not a constructor call.

Delegate invocation (P-037 A2.2-2b). `a(s)`, `a.Invoke(s)` and `a?.Invoke(s)`
on a delegate-typed `a` are one call-like family, tagged
`call_kind: delegate_invocation`. The target is unknown by construction, so
`callee` and `sig` are null and `first_party` is false: the record never
guesses which method the delegate holds, and it does not spell the delegate's
`Invoke` as if it were a callee with a summary. The delegate's declared
parameters still bind the arguments by ordinal, named arguments resolved
against the delegate's parameter names. Until A2.2-2b such a call was recorded
as a plain invocation of the delegate's `Invoke`; the census shapes
`corpus/p037-shapes/sidecar-delegate-*` pin the family.

Constructor initializers (P-037 A2.2-4R5). A constructor's `: base(...)` or
`: this(...)` is a call site of its own, tagged
`call_kind: constructor_initializer`: `Holder(MemoryStream r) : base(r, true)`
passes the handle into a really invoked constructor's declared ordinal 0, the
same ownership edge a constructor call carries. The site is the initializer
itself (its coordinate is the `:`; it sits beside the constructor's body, not
inside it, and its `form` is `statement`: it runs first and yields nothing),
the callee is the target constructor's `functions[]` key (`{Type}..ctor`),
`sig` its §5.1 signature, `first_party` whether it has a declaration in the
compilation, and the arguments bind to the target constructor's declared
ordinals by the same mechanism as an invocation. A nested call inside an
initializer argument is that call's own site, as everywhere.

The call-site identity — the invocation's own coordinate plus `statement_line` —
is what lets the legacy view (`body`) and this one be joined until the C+
checkpoint canonicalizes the two representations (§10.5 of the formal note).
A `site`'s `line` follows the general `sourceLine` domain `[0, 2147483647]`
like every other line in this document; its `column` follows the 1-based
`[1, 2147483647]` domain every other column carries, but is required and
non-nullable (§4.2) — only `column` is "1-based," not both coordinates as an
earlier revision of this section said. Through A2.1 both were validated only
by the producer; A2.2-D is the instrument step that binds them to those
domains at both doors (§4.2), the same door registration §5.2 describes for
the rest of the sidecar's shape. `statement_line` (a plain, required
`sourceLine`, not a `site`) carries the same domain it always did. The
producer stays as strict as before and refuses to write a facts file at all
if one is malformed (exit 2): fail-loud at the source, now matched by a
fail-loud door.

### 5.3 The orphan carrier (`guarded_functions`, P-037 A2.2-3P)

A `functions[]` record exists only for a method the legacy pass admits: one
with a tracked disposable local or an owned parameter, whose body it can
lower. Methods with guarded raw facts and no record at all are common: a
handle passed to a non-consuming callee (every candidate escaped), a handle
handed to a delegate, a method with no handle but with a `disposing`-style
guard on a field disposal, and any method with an unmodelled construct
rejected by the legacy flow pass (for example, at this checkpoint: `lock`,
`goto`, or a local-function declaration; `try`, `switch`, loops and `using`
declarations are modelled), and, since P-037 A2.2-4R6, every member body the
legacy pass never enumerates at all: an expression-bodied method-like member
of a class, every method-like member of a struct, record, record struct or
interface, a property or indexer accessor, an expression-bodied property or
indexer (its getter). Their facts are honest raw facts and must be
delivered; a dummy `functions[]` record is not the way, because a record, even
with an empty body, enters the first-party universe at the doors
(`_build_skeletons` creates a skeleton for every named function) and can move
MOS resolution. The census shapes `corpus/p037-shapes/orphan-*` are the
witnesses, one per admission gate, `lock` standing for the unmodelled one.

So a method that has guarded facts (§5.2) **and** no `functions[]` record is
carried in the optional, additive top-level list `guarded_functions[]`:

```text
guarded_functions[]   one entry per method the legacy pass did not admit
    name              the `functions[]`-style key it would have carried
    file              as `functions[].file`
    sig               the §5.1 signature key; omitted when unresolved
    guarded_facts     exactly the §5.2 sidecar, same vocabulary, same self-check
```

Contract:

- `functions[]` stays the legacy-visible set; its semantics are unchanged
  through A2. `guarded_functions[]` is an **orphan** carrier, not a second
  source for every method: a method identity (`file`, `name`, `sig`) present
  in both is a producer defect and refuses the run (exit 2, no facts written);
  the same identity present twice *within* `guarded_functions[]` is a distinct
  producer defect, refused the same way. The producer's control knob
  `OWN_P037_SELFCHECK_PROBE=duplicate_identity` adds such a duplicate on
  purpose so the refusal can be witnessed; it never changes facts, and no
  production or evidence run sets it. A2.2-D (door-registered) makes both
  doors enforce this identity invariant too, at load rather than only at
  write time — a document violating either collision is refused
  (`Identity`). The identity's `sig` component distinguishes an **absent**
  signature from an **explicitly empty** one: `""` is the canonical
  zero-parameter-overload signature (§5.1) and a real identity component,
  while an absent `sig` means no type information was available, so the two
  are never the same identity even though the producer's own duplicate-probe
  helper happens to collapse them for its own purposes.
- The list is absent when empty, so a document without orphans keeps the
  bytes it had; when present it is the last top-level key.
- Through A2.1 both doors carried the list as additive unknown metadata
  (§4.2 applied to its coordinates exactly as to `guarded_facts`), neither
  lowerer read it, and the inertness control proved that adding, removing or
  lying in the carrier moved no MOS layer and no verdict on either engine.
  A2.2-D, the door-registration step, makes `guarded_facts` and
  `guarded_functions` known, fail-loud vocabulary on both doors — validated
  shape, closed vocabularies, coordinate domains, and the identity invariant
  above — while leaving every lowerer, summary and verdict exactly as silent
  about them as before; `scripts/p037_sidecar_inertness.py` is the witness
  that the door learning the vocabulary changed no engine's answer. It is an
  instrument change and opens a new baseline round.
- Phase B reads `functions[].guarded_facts` and
  `guarded_functions[].guarded_facts` as one guarded-method view; C+
  canonicalizes the temporary double carrier.

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
