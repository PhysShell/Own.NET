# Interprocedural Ownership Inference Specification

> **Status: normative, descriptive.** This document specifies the interprocedural
> ownership-inference layer *as it is today*, derived from the working solver
> ([`ownlang/ownership.py`](../ownlang/ownership.py)) and the bridge that feeds and
> applies it ([`ownlang/ownir.py`](../ownlang/ownir.py)), and pinned by tests (see
> [§10 Conformance](#10-conformance)). Forward-looking design lives in
> [`docs/proposals/P-005-idisposable-ownership.md`](../docs/proposals/P-005-idisposable-ownership.md)
> and [`docs/notes/d5-ownership-transfer.md`](../docs/notes/d5-ownership-transfer.md);
> the staged plan and open decisions live in
> [`docs/notes/interprocedural-roadmap.md`](../docs/notes/interprocedural-roadmap.md)
> and [`docs/notes/interprocedural-tz.md`](../docs/notes/interprocedural-tz.md).
> Never here.

## 0. What this layer is

The core checker ([OwnCore.md](OwnCore.md)) is **intraprocedural**: it reasons
about one function body. When an owned `IDisposable` crosses a method boundary —
passed to a callee, or returned from one — the caller cannot know what happened to
it without a *contract* for that boundary. This layer computes those contracts.

It is **not a second checker**. It computes, per first-party method, a compact
**Method Ownership Summary (MOS)**, then **lowers** each summary to the core's
existing vocabulary at the call site (`consume` / `borrow` effects, an `acquire`
for a fresh result, an `alias_join` for an adopt). No verdict originates here: the
core still renders every OWN0xx. This is a *summary-contract* layer, not a
borrow-checker core (the Checker Framework's Resource Leak Checker is the closest
shipped analogue; Polonius is not the template).

The **precision floor is `own-only 0`**: no rule in this document may fabricate a
`must`/`fresh`/alias contract. Every degradation resolves toward *silence*, and a
genuinely-unverifiable boundary is recorded as an advisory (§7), never guessed.

## 1. The MOS artifact

For each method `M` whose body is visible (first-party / same compilation) the
layer computes one `MethodSummary` ([`ownership.py`](../ownlang/ownership.py),
`MethodSummary`). It has two axes plus provenance:

- **Per-parameter transfer** (only for the disposable-typed params the frontend
  marks): `transfer ∈ {no, must, may, unknown}` (§2).
- **Per-return ownership**: `returns ∈ {fresh, aliasOf:<i>, aliased, none,
  unknown}` (§4).
- **`source ∈ {inferred, bcl, annotation, heuristic}`** — which tier produced the
  summary. **Today production emits only `inferred`** (Tier A, §6): the BCL and
  per-call-site tiers act at the *application* layer (§6), not as stamped
  summaries. The field is reserved for the annotation/heuristic tiers.

A second, **reserved** per-parameter axis, `escapes` ("the reference outlives the
call"), exists in the model but has **no producer** — derivation always leaves it
`False`, and it is deliberately **not serialized** (§8, `INF-R2`). The d5 design
keeps escape orthogonal to transfer; until a producer lands it must not be read as
evidence.

The summary is **context-insensitive**: exactly one MOS per method, independent of
caller or call depth. The summary *is* the memoization.

## 2. The transfer lattice

`Transfer` ([`ownership.py`](../ownlang/ownership.py), `Transfer`,
`join`): did ownership of a disposable parameter leave the caller on the call?

| value | meaning |
|---|---|
| `no` | borrowed — the caller keeps ownership (a leak if the caller never disposes) |
| `must` | transferred on **every** normal-return path |
| `may` | transferred on **some** paths, kept on others (partial consume) |
| `unknown` | insufficient evidence (extern callee, or an unresolved boundary) |

- **INF-L1 (join).** `join(a, a) = a`; if either side is `unknown` the join is
  `unknown` (absorbing); any other mix of distinct values is `may`. So one
  un-characterizable path makes the whole parameter `unknown`, and a
  transfer-path joined with a keep-path is `may` (path-dependent, and we know it).
- **INF-L2 (bottom).** `⊥` (Python `None`) is the fixpoint seed only (§5); it is
  the identity of the join and **never escapes a solved summary** — a residual `⊥`
  finalizes as `no` ("nothing demonstrably consumes it ⇒ it is kept").

## 3. Skeleton derivation — parameters (S-rules)

Before solving, the bridge derives a per-method **skeleton**
([`ownir.py`](../ownlang/ownir.py), `_build_skeletons`): each disposable parameter
gets a set of **path actions** (`dispose` | `borrow` | `forward(callee, arg)`;
the `adopt`/`return` kinds are **reserved**, see `INF-S5`) that the solver joins.

- **INF-S1 (explicit override).** An explicit `effect` on the parameter fact wins
  over all inference: `consume → [dispose]`, `borrow`/`borrow_mut → [borrow]`, any
  other string → `[]` (explicitly non-owning). A contract-only callee (no body)
  therefore still resolves.
- **INF-S2 (definite release ⇒ dispose).** A body that releases the parameter is a
  `dispose` path **only when the release is definite** — on **every**
  normal-return path (`_definite_release`). A **partial** release (one branch, a
  `while` body which may run zero times, or behind an early `return` that does not
  release) emits **both** a `dispose` and a `borrow` path, so the join is `may` and
  the caller stays plain. Flattening a partial release to `must` would charge a
  caller's defensive dispose a false OWN002/OWN003 — the precision floor forbids it.
- **INF-S3 (single straight-line forward ⇒ resolved).** A parameter handed to
  exactly one callee at exactly one top-level (straight-line) call site emits a
  single `forward(callee, arg)` path (the solver resolves it, §5). Any
  conditional / looped / multi-target forward **also** emits a `borrow` path, so
  the join is `may`/`no`, never a fabricated `must`.
- **INF-S4 (used ⇒ borrow; else nothing).** A parameter only read/used emits
  `[borrow]`; a parameter the body does nothing with emits `[]` (→ `no`).
- **INF-S5 (reserved kinds).** The path kinds `adopt` (store into an owning field,
  interprocedural T4b) and `return` (return the parameter) are understood by the
  solver as `must` but have **no production producer**: `_build_skeletons` never
  emits them, and a returned parameter is deliberately **not** a consume signal
  (that is wrap/alias, §4/§6, not consume). A port must carry their semantics but
  must not expect them from real facts.
- **INF-S6 (sink channel resolves in place).** A forward to a fixed
  ownership-sink extern (`$consume`/`$borrow`, §6) is recorded as a **resolved**
  path directly (`$consume → dispose`, `$borrow → borrow`), not a forward edge.
  `$borrow_mut` is **deliberately excluded** from this shortcut: the transfer
  lattice has no shared-vs-exclusive axis, so summarizing it transitively would
  downgrade an exclusive loan to a shared one — the wrapper param stays plain
  instead (the direct `$borrow_mut` call keeps full exclusivity; tracker #122).

## 4. Skeleton derivation — returns (R-rules)

The return kind is inferred from the body
([`ownir.py`](../ownlang/ownir.py), `_infer_return_skeleton`):

- **INF-R1.** No `return <var>` → `none` (void / no owned value).
- **INF-R2.** Any bare `return` / `return null` on some path → `none` (not
  uniformly owned; a caller dropping the result must not be charged on that path).
- **INF-R3 (fresh).** `fresh` **iff every** returned local is `acquire`d in this
  body **and** is not a parameter **and** is not also a `call` result on any path
  (mixed origin degrades — claiming fresh there would make a caller acquire a value
  it does not own on the non-acquire path).
- **INF-R4 (forward / BCL wrapper).** A single returned local that is a `call`
  result (not a param, not acquired): if the callee is first-party →
  `forward(callee)` (the solver resolves it through the callee's own return kind,
  factory-of-factory); else if the callee is a curated BCL fresh-factory (§6, Tier
  B) → `fresh` (a thin wrapper over a BCL factory is itself fresh); else
  `forward(callee)` (which the solver degrades to `unknown` at the extern boundary).
- **INF-R5.** Anything else → `none` (not provably owned ⇒ no claim).

## 5. The fixpoint solver (F-rules)

The solver ([`ownership.py`](../ownlang/ownership.py), `solve` / `solve_with_log`)
resolves every method's MOS over the call graph.

- **INF-F1 (graph).** Edges `M → C` for every first-party callee a parameter
  forwards to (`forward` paths) and every forwarded return target — only within
  the analyzed skeleton set (`_call_graph`).
- **INF-F2 (SCC order).** The graph is condensed into strongly-connected
  components (iterative Tarjan) emitted bottom-up = reverse-topological, with
  sorted adjacency for determinism. A callee in a lower SCC is resolved (and reused)
  before any caller reads it; only same-SCC callees are still mid-iteration.
- **INF-F3 (param least fixpoint).** Within an SCC, each `(method, disposable
  param)` is seeded at `⊥` and iterated to the least fixpoint on the height-3
  lattice; a residual `⊥` finalizes as `no`. Seeding at `⊥` (not a spurious `no`)
  is what makes recursion **exact**: a method that disposes on its base case and
  recurses otherwise resolves to `must`, and mutual recursion grounded by a dispose
  carries `must` across the whole SCC, while recursion that never disposes settles
  at `no`.
- **INF-F4 (no duplicate keys).** Two skeletons with the same method key raise
  immediately (`ValueError`) — silently keeping the last would make summaries
  input-order-dependent and corrupt the call graph. (Key collision-freedom for
  overloads is handled by merging *before* the solver, §M-rules.)
- **INF-F5 (return chase).** A return has at most one forward target, so it is
  resolved by an iterative (non-recursive, so a deep acyclic wrapper chain cannot
  overflow), memoized, cycle-safe walk along forward-return edges: a
  forward-return **cycle** → `unknown`; an **extern** target → `unknown` (logged);
  an **`aliasOf:<i>` propagated across a hop** → `unknown`, because remapping the
  callee-space index to the caller's arguments needs a call argument map the
  skeleton does not carry (the obligation-identity model, D5.4). `fresh` / `aliased`
  / `none` / `unknown` propagate as-is; an unrecognised kind fails closed to
  `unknown`, never silently `none`.
- **INF-F6 (observable degradation).** A failure of the solve degrades the **whole
  interprocedural layer** to the empty MOS (the checker never crashes, forwards
  stay plain), and the reason is surfaced as an advisory **OWN052** (§7) — never a
  silent skip. In the Rust port this degradation is a `Result`, never a panic.
- **INF-F7 (extern log).** `solve_with_log` returns the sorted list of forwards —
  param or return — that cross an **extern** (unsummarized) boundary: the `unknown`s
  that come from *outside* the analyzed set. It is **not** a log of all `unknown`s;
  the intrinsic precision-safe degradations (return-forward cycle, un-remappable
  `aliasOf`, missing index, unrecognised shape) are deterministic from the input
  and not logged.

## M-rules — overloads

The call node names a callee `{Type}.{Method}` **without a parameter signature**
([OwnIR §5](OwnIR.md)), so same-name overloads share a key and are **merged into
one conservative summary before solving** ([`ownir.py`](../ownlang/ownir.py),
`_merge_skeletons`, `_merge_returns`):

- **INF-M1 (param join).** Union the parameter indices across overloads; an
  overload that does nothing with an index contributes a `borrow` path (it *keeps*
  the arg), so a parameter is `must` **only when every overload consumes it** —
  never a fabricated `must` from an ambiguous name.
- **INF-M2 (return join).** `{fresh}` → `fresh`, `{none}` → `none`, `{aliased}` →
  `aliased`; any mix, or a `forward`/`aliasOf` in the group (whose index is
  overload-specific), degrades to `unknown` — never a fabricated `fresh`.
- **INF-M3 (arity residual).** Merging is by name only; disambiguation by arity or
  argument type would need call-site type information the fact stream does not carry
  today. The merge is precision-safe (never a false `must`/`fresh`), just coarser
  than a per-signature split would be. (Roadmap stage 2.)

## 6. Application at the call site (A-rules) and the tier ladder

The solved MOS is **lowered** to the core's vocabulary during
`to_module`/`_lower_flow` ([`ownir.py`](../ownlang/ownir.py)). The precision floor
stays `own-only 0`; the tiers raise recall, higher overriding lower:

- **Tier A — first-party inferred summaries** (§3–§5). The bulk of coverage;
  `source = inferred`.
- **Tier B — curated BCL fresh-factory table** (`_BCL_FRESH_BY_NS`): well-known
  static factories whose result the caller owns (`File.Open*`, `SHA256.Create`,
  `XmlReader.Create`, `JsonDocument.Parse`, …), matched only on the exact bare
  `Type.Method` or its fully-qualified identity under the real namespace. A
  **first-party summary always overrides** the table (`INF-A4`).
- **Per-call-site contract channel** — the fixed sink externs
  `$consume`/`$borrow`/`$borrow_mut`: an ownership effect the extractor pins at the
  call site (e.g. `StreamReader(s, leaveOpen: false/true)`), resolved through the
  same core signature path as any contracted call.

Lowering rules:

- **INF-A1 (param effect).** A parameter's lowered effect is: explicit `effect` >
  inferred. For a forwarded parameter the solved transfer applies: `must → consume`,
  `no → borrow`, `may`/`unknown → plain` (precision-first, §7).
- **INF-A2 (T1 fresh result).** A `call` binding a `result` whose callee summary
  `returns = fresh` (or a Tier-B fresh factory) mints an `acquire` for that local —
  the call site is a factory, so the result is a new owned obligation the leak /
  double-release / use-after checks apply to. `_callee_returns_fresh` is the
  **single source of truth** shared by the leak pre-scan, the branch-hoist safety
  walk, and the lowering, so all three agree (`INF-A6`).
- **INF-A3 (T4 alias_join).** An `alias_join` op lowers the return-alias/adopt case
  (D5.4): the new handle joins `src`'s obligation set (release/escape through
  either discharges the one resource; both → OWN003; use-after → OWN002). An
  `alias_join` over an untracked `src` makes **no claim** (must-only alias).
- **INF-A4 (tier precedence).** Tier A overrides Tier B for **every first-party
  name**, including a name dropped from the summary set (an overload): a first-party
  method never receives a fabricated BCL `fresh`.
- **INF-A5 (optimistic untrack).** A local handed to a summarized callee parameter
  whose transfer is `may` or `unknown` is **untracked at that call** — its
  obligation is not minted (its `acquire`/fresh-result/`alias_join` is skipped, and
  it is excluded from branch-hoisting). Under the optimistic default this means
  "the caller no longer owns it": neither a missing **nor** a defensive dispose
  after the call is charged. The gap is recorded as advisory **OWN051** (§7). A
  call carrying such positions is emitted through the per-argument `$`-channel (as
  overloads are, `INF-M`), so an untracked name is never referenced in emitted core
  code (which would raise OWN030, map-or-raise).
- **INF-A6 (kill on rebind).** Overwriting a tracked local (a re-bound `call`
  result or `alias_join` target) kills its previous ownership binding first, so a
  lost prior obligation leaks rather than reading as clean ([OwnIR §5](OwnIR.md)).

## 7. The optimistic default and advisories

The fact model and the *reporting policy* are separate.

- **INF-P1 (optimistic default = own-only 0).** At an unverifiable-ownership call
  site, resolve toward "caller no longer owns" → silent. A mis-`consume` loses a
  real leak (recall — tolerable); a mis-`borrow` demands a dispose that may be wrong
  (precision — not tolerable). This is the whole project's stance and the default.
- **INF-P2 (advisory OWN051).** When an **owned** local (an acquired local or a
  fresh-factory result — not a plain value) is untracked by `INF-A5`, the layer
  emits advisory **OWN051** at the call site: the honest record that ownership past
  this call was not verified. Advisory means rendered as a `warning`, `level:note`
  in SARIF, **excluded from the exit code**, hidden at `--verbosity quiet`.
- **INF-P3 (advisory OWN052).** When the solve degrades (`INF-F6`), the layer emits
  advisory **OWN052**, module-level, with the inner error — the honest record that
  cross-method contracts were skipped this run.
- **INF-P4 (strict mode — reserved).** A pessimistic mode (unknown call site →
  assume borrow → report the leak) is designed (d5 §5) but **not implemented**; the
  advisory channel and full `must`/`may` evidence exist regardless of mode.

## 8. Serialization — the summary dump

The solved summaries are observable and diffable via
`python -m ownlang summaries facts.json` ([CLI.md](CLI.md),
[`ownir.py`](../ownlang/ownir.py), `dump_summaries`): one deterministic JSON
document — summaries sorted by method key, the extern log sorted, a `degraded`
reason on solve failure.

- **INF-R1 (determinism).** The document is **byte-identical** under any
  `functions[]` input permutation: summaries sorted by key, extern log sorted,
  fixed field order, merged-overload location taken as the min `(file, line)`. This
  is what makes it a parity artifact (the Rust port of this layer is diffed against
  it), not a debug log.
- **INF-R2 (no unproduced fields).** The reserved `escapes` axis (§1) is **not**
  serialized — emitting an always-`False` field would freeze a lie into the parity
  surface. Serialize it the day a producer lands, together with the producer.

## 9. Scope / non-goals

First-party (Tier A) + curated BCL (Tier B) + the per-call-site channel only. **No
IL/Cecil decompilation of third-party assemblies**; no cross-thread / async
disposal races; no context sensitivity or points-to (context-insensitive summaries
suffice — the floor is precision, not soundness). Annotations (Tier C) and a
pessimistic mode are reserved (§7, `INF-P4`).

## 10. Rules

- **INF-L1/L2** — lattice join; `⊥` is seed-only and finalizes `no`.
- **INF-S1–S6** — parameter skeleton derivation (explicit override; definite
  release ⇒ dispose, partial ⇒ may; single straight-line forward; used ⇒ borrow;
  reserved `adopt`/`return`; sink channel + `$borrow_mut` exclusion).
- **INF-R1–R5** — return skeleton derivation (none / bare-return / fresh / forward
  / BCL-wrapper).
- **INF-M1–M3** — overload merge (param join, return join, arity residual).
- **INF-F1–F7** — the solver (graph, SCC order, param fixpoint, no duplicate keys,
  return chase, observable degradation, extern log).
- **INF-A1–A6** — call-site application (param effect, fresh result, alias_join,
  tier precedence, optimistic untrack, kill-on-rebind).
- **INF-P1–P4** — reporting policy (optimistic default, OWN051, OWN052, reserved
  strict mode).
- **INF-R1/R2** (serialization) — deterministic dump; no unproduced fields.
- **The floor.** No rule may fabricate a `must`/`fresh`/alias contract; every
  degradation resolves toward silence, and an unverifiable boundary is an advisory,
  never a guess.

## 11. Conformance

Pinned by [`tests/test_ownership.py`](../tests/test_ownership.py) (the solver
lattice, `python tests/test_ownership.py`) and
[`tests/test_ownir.py`](../tests/test_ownir.py) (derivation + application +
serialization, `python tests/test_ownir.py`) — not `test_spec.py` (this is a
bridge/solver contract, not a surface-language rule):

- **INF-L / INF-F** — `test_ownership.py`: join monotonicity, SCC convergence,
  deep-chain termination, extern-boundary logging, duplicate-key raise, the
  `aliasOf`-through-forward degradation, `to_dict` serialization.
- **INF-S2 (definite release)** — `test_ownir.py` "TZ D1": conditional / while-body
  / early-return-guarded releases degrade to `may` (one OWN051, no verdict);
  both-branch and release-then-return stay `consume`.
- **INF-S3 / INF-A1** — transitive consume/borrow through single vs conditional
  forwards; two-hop chains.
- **INF-M1–M3** — agreeing overloads resolve `must`; disagreeing join to `may`
  (OWN051); direct call to overloads routes through the channel.
- **INF-A2 / INF-A4** — first-party fresh result mints an acquire; Tier A overrides
  the BCL table; BCL fresh factories and wrappers over them.
- **INF-A5 / INF-P2** — an owned local dropped/disposed after a `may`/`unknown`
  call is silent with one OWN051; a verified borrow keeps the caller's obligation
  (true OWN001); a plain value at a `may` position stays quiet.
- **INF-F6 / INF-P3** — a patched-to-raise solver yields exactly one OWN052 and no
  fabricated verdicts; a healthy solve carries none.
- **INF-R1/R2 (serialization)** — the `summaries` dump is byte-identical under
  input permutation; the `escapes` axis is omitted.

A change to this spec without a matching change under `tests/test_ownership.py` /
`tests/test_ownir.py` (or vice-versa) is a red build.
