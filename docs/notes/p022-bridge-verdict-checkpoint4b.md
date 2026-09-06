# P-022 step 6b (#259) — checkpoint 4b: the obligation-protocol analysis (OBL001–005)

> Status: **4b.0 complete — inventory only, no production code.** This note is
> the checkpoint's plan and its completeness ledger: every behaviour of
> `ownlang/obligations.py` and of the bridge's BR-P3 mapping, each one named
> with what will pin it (a row in the new fact-parity family, a synthetic
> Layer 3 case, or both), plus what the two existing reference documents
> already reach and what they do not. Counts are not typed here: they live in
> the generated fragments ([census](../generated/p022-cp4-census.md),
> [surface inventory](../generated/p022-cp5-inventory.md)) and the prose links.

Checkpoints 1–5 ([cp4](p022-bridge-verdict-checkpoint4.md),
[cp5](p022-bridge-verdict-checkpoint5.md)) took `own_bridge::check_facts` to
Layer 3 parity over the measured set, on the full `Finding` and on the rendered
surfaces. One analysis family is missing from the Rust side entirely: the
obligation protocols. Today the bridge **refuses** a document with a non-empty
`protocols[]` (`own-bridge/src/verdict.rs::refuse_protocols`) rather than
return a verdict list with a family silently absent, and the two reference
documents `protocol_isloaded_clean` / `protocol_isloaded_violation` sit in the
verdict ledger's `rust_replay_excluded` with the executable expectation
"`check_facts` errors, and the error contains `obligation protocol`".

4b removes that refusal. It is its own checkpoint rather than a fourth job for
cp5 because `obligations.py` is a path-sensitive analysis of its own — a
lattice, a walker, a matcher language — and cp5's scope was messages, evidence
and rendering.

## 0. Scope, and the three things 4b is not

**In scope.** The v1 analysis exactly as `ownlang/obligations.py` has it; the
BR-P3 mapping to `Finding`s exactly as `ownlang/ownir.py::_protocol_findings` /
`_protocol_message` have it; a fact-parity family at the analysis level; the
synthetic Layer 3 cases the corpus is missing; the promotion of the two
excluded documents; the status surfaces.

**Not in scope, by declaration:**

1. **P-025 phase 3** — interprocedural obligation summaries. v1 is an
   intramethod walk and a callee that flips a tracked flag is invisible to it;
   that is the reference's behaviour, and reproducing it is the job.
2. **The coordinate-domain decision.** The `u32` line-domain exclusions stay
   exactly as cp4 and cp5 left them. 4b touches `rust_replay_excluded` for the
   two protocol promotions and for nothing else.
3. **The `own-shadow` reducer's Layer 3 scope.** After 4b the Rust engine
   *produces* the verdict layer for a protocol-bearing document instead of
   refusing it, so that document's artifact, trace and reduction change. The
   reducer's scope stays `["lowered", "summaries"]`: comparing end diagnostics
   is #260's acceptance and moving that line is #260's decision, not 4b's.

## 1. What the two existing reference documents already reach

Both are excluded from the Rust replay, so at the **replayed** set the protocol
family is at nothing: the surface-inventory rows `obl_message`, `protocol_flow`
and `protocol_flow_3` all report no replayed coverage, each with the recorded
disposition "row 4b". Over **all goldens** — Python's complete truth, which is
what 4b inherits as its starting corpus — the picture is narrower than the row
names suggest, and it was measured rather than assumed
(`tests/verdict_surface_inventory.py`, rendered into
[`p022-cp5-inventory.md`](../generated/p022-cp5-inventory.md)):

* `obl_message` matches the OBL family as **one** row (its pattern is `.*`,
  because cp5 had no reason to split a family it declared out of scope). The
  single golden finding behind it is `protocol_isloaded_violation`'s OBL001.
* `protocol_flow_3` — the three-step slice *opened → barrier → late close* — is
  reached by that same finding.
* `protocol_flow` — the two-step slice *opened → barrier* with no late close —
  is reached by **nothing**. The corpus has no golden for it at all.

`protocol_isloaded_clean` contributes no finding, which is the point of it: it
is the silence twin, and a vacuous replay would have "matched" it.

So the corpus reaches exactly one shape: an OBL001 barrier crossing, definite,
inside an `if` branch, with a late close, on a dotted method name matched by a
`Type.Method` scope suffix, past an allow-listed call and a call the protocol
does not name. Everything else in §2 and §3 below has **no golden**: OBL002,
OBL003, OBL004, OBL005, every exit anchor, every loop, `exit_barriers: false`,
the opaque-write asymmetry, args-narrowing and the unknown argument, exact
scope matching, duplicate protocol names, the malformed-entry skip, the
non-list blocks, the sort key, and the two-step slice itself.

## 2. The analysis, behaviour by behaviour (`ownlang/obligations.py`)

Each row is a future case in the new analysis-level fact-parity family
(`tests/fixtures/obligation_fact_parity.json`, generator
`tests/test_obligation_fact_parity.py`, Rust replay in `own-analysis/tests`),
seeded from `tests/test_obligations.py` §1. The family freezes each violation
whole — `protocol`, `method`, `file`, `line`, `kind`, `definite`, `open_line`,
`barrier_desc`, `close_line` — and the dead-protocol list beside it, so a
divergence names the member it is in.

### 2.1 The lattice

| # | Behaviour | Reference |
|---|---|---|
| A1 | state is a **set** over `{OPEN, CLOSED}`; the join is set union | `_join` |
| A2 | open provenance joins by **minimum line** across the paths where it is open | `_join`, `min(lines)` |
| A3 | bottom is `(∅, None)`; a dead branch contributes bottom to a merge | `_BOTTOM`, `IfEv` arm |
| A4 | a walk starts `({CLOSED}, None)` — a method begins with nothing owed | `_Walker.run` |
| A5 | `definite` is `states == {OPEN}` — open on every path, not merely on one | `_emit` |

### 2.2 Matching

| # | Behaviour | Reference |
|---|---|---|
| B1 | an `assign` matcher matches on `target`; `value=None` matches any written value, **including an opaque write** | `Matcher.matches` |
| B2 | a `call` matcher matches on `callee`; empty `args` matches every call | `Matcher.matches` |
| B3 | a non-empty `args` narrows: an argument outside the set does not match | `Matcher.matches` |
| B4 | a call with an **unknown** argument does not match a narrowed matcher — never invent a crossing we cannot prove | `Matcher.matches` (`ev.arg is not None`) |
| B5 | `describe()`: `T = ...` (opaque), `T = true` / `T = false` (lowercased Python bool), `f()` | `Matcher.describe` |
| B6 | `applies_to`: no `scope.methods` matches every reporting method | `Protocol.applies_to` |
| B7 | `applies_to`: an **exact** name or a trailing `.Type.Method` suffix | `Protocol.applies_to` |
| B8 | `tracks_target`: a flag named by an `assign` matcher in `opens` **or** `closes` | `Protocol.tracks_target` |

### 2.3 The walk over one leaf event

The order is the semantics — opens, then closes, then barriers:

| # | Behaviour | Reference |
|---|---|---|
| C1 | an opening event wins over everything: state becomes `{OPEN}` | `_leaf` |
| C2 | **re-opening** keeps the earliest open site as provenance (`min(prev, line)`) | `_leaf` |
| C3 | a closing event discharges: `({CLOSED}, None)` — the provenance is dropped with it | `_leaf` |
| C4 | a barrier is only considered while `OPEN` is possible | `_leaf` |
| C5 | **allow beats barrier**: an allow-listed event never crosses | `_leaf` |
| C6 | the **first** matching barrier emits, then the scan stops | `_leaf` `break` |
| C7 | `barrier_desc` for a call is `callee(arg)`, and `callee()` when the argument is unknown | `_leaf` |
| C8 | `barrier_desc` for an assign barrier is `target = ...` | `_leaf` |
| C9 | an **opaque** write to a tracked flag while open adds `CLOSED` — it may have discharged | `_leaf` |
| C10 | an opaque write while **closed** never opens (the never-invent asymmetry) | `_leaf` (guarded by `OPEN in states`) |
| C11 | an opaque write to an **untracked** member is inert either way | `_leaf`, `tracks_target` |
| C12 | a call the protocol does not name is neutral — no discharge, no crossing | `_leaf` falls through |

### 2.4 Exits

| # | Behaviour | Reference |
|---|---|---|
| D1 | `return` while open emits at the **return** line, desc `return`; the path dies | `walk`, `_exit` |
| D2 | `throw` while open emits at the **throw** line, desc `throw`; the path dies | `walk`, `_exit` |
| D3 | falling off the end while open emits desc `end of method`, anchored at the **open** site (the OWN001 anchor-at-acquire precedent) | `run` |
| D4 | an end-of-method leak with **unknown** provenance anchors at `0` | `run` (`anchor = … else 0`) |
| D5 | `exit_barriers: false` silences every exit, and only exits — barriers still fire | `_exit` |
| D6 | a sequence stops at the first event that leaves the method | `walk_seq` |

### 2.5 Control flow

| # | Behaviour | Reference |
|---|---|---|
| E1 | `if` walks both arms from the same state and joins them | `walk` |
| E2 | an arm that has left the method contributes bottom, not its state | `walk` (`s1 if a1 else _BOTTOM`) |
| E3 | both arms dead ⇒ the whole `if` is dead | `walk` |
| E4 | a barrier inside one arm stays **definite** — the branch is where flow goes, not where the obligation becomes conditional | falls out of A5 |
| E5 | `while` iterates its body to a **silent** local fixpoint on the header state | `walk` |
| E6 | then re-walks the body **once**, emitting, on the converged header — so a barrier in a loop reports exactly once | `walk` |
| E7 | the emitting pass is skipped while an enclosing loop is still silent (nested loops still emit once) | `walk` (`if not self.silent`) |
| E8 | the loop's exit state is the **header**: zero iterations is always possible | `walk` |

### 2.6 Evidence and ordering

| # | Behaviour | Reference |
|---|---|---|
| F1 | close lines are collected over the whole tree, **reachability ignored**, recursing into `if`/`while` | `_close_lines` |
| F2 | the late-close hop is the **earliest** close strictly after the violation line | `check_protocols` |
| F3 | the hop is attached to **barrier** crossings only — an exit leak has no barrier to be late for | `check_protocols` |
| F4 | violations sort by `(file, line, protocol, barrier_desc)` | `check_protocols` |
| F5 | protocols × methods: every protocol is checked against every in-scope method, protocols do not interfere | `check_protocols` |

### 2.7 Dead rules

| # | Behaviour | Reference |
|---|---|---|
| G1 | a protocol with a non-empty scope matching no reported method is a dead rule | `unmatched_scopes` |
| G2 | an **unscoped** protocol is never a dead rule, even with no methods at all | `unmatched_scopes` |

## 3. The bridge mapping (BR-P3, `ownlang/ownir.py`)

Each row is a synthetic Layer 3 case under the frozen verdict ledger
(`verdict_protocol_*`, insertion-stable: no existing record rewritten), unless
it is already reached by `protocol_isloaded_violation`.

| # | Behaviour | Reached today? |
|---|---|---|
| H1 | `(barrier, definite)` → **OBL001** | yes |
| H2 | `(barrier, maybe)` → **OBL002** | no |
| H3 | `(exit, definite)` → **OBL003** | no |
| H4 | `(exit, maybe)` → **OBL004** | no |
| H5 | barrier message, definite: *"is still open when barrier '…' fires in '…' — '…' must happen first"* | yes |
| H6 | barrier message, maybe: *"may still be open (open on some path)"* | no |
| H7 | exit message, definite: *"is not closed"* | no |
| H8 | exit message, maybe: *"may not be closed (open on some path)"* | no |
| H9 | `exit_desc` for `return` / `throw`: *"'M' exits via return"* | no |
| H10 | `exit_desc` for the fall-off: *"the method falls off the end"* | no |
| H11 | every message is **line-free** (OwnAudit fingerprints on `(path, rule, message)`) | yes |
| H12 | `component` = the second-to-last dotted segment (`rsplit(".", 2)[-2]`) | yes |
| H13 | `component` = the whole name when it carries no dot | no |
| H14 | `handler` = the last dotted segment | yes |
| H15 | `event` = the protocol name; `kind` = `protocol obligation`; `column`/`severity` absent | yes |
| H16 | flow step 1: *opened here (`<opens.describe()>`)* | yes |
| H17 | flow step 2 for a barrier: *barrier '…' fires while it is open* | yes |
| H18 | flow step 2 for an exit, **only when `line != open_line`** — so an end-of-method leak has no second step | no |
| H19 | flow step 3: *closed here — after the barrier has already fired* | yes |
| H20 | steps with `line < 1` are dropped (BR-V5) | no |
| H21 | **OBL005**: advisory, anchorless (`file="?"`, `line=0`, `component="?"`, `handler=""`) | no |
| H22 | the OBL005 message interpolates `sorted(p.methods)` as a **Python list repr** | no |
| H23 | `protocols` / `protocol_functions` that are not lists ⇒ no findings | no |
| H24 | a malformed `protocols[]` entry is **skipped**, never coerced | no |
| H25 | a malformed `protocol_functions[]` entry is skipped | no |
| H26 | a duplicate protocol name resolves **first-wins** on the tolerant door | no |
| H27 | no parseable protocol ⇒ no findings, even with methods present | no |
| H28 | protocol findings are appended after effects and before OWN050 (BR-V1) | yes (vacuously — one family present) |

### 3.1 Where the port puts each half

`obligations.py` splits cleanly along BR-B1, and the port follows it:

| half | reference | port |
|---|---|---|
| the acceptance grammar (already ported) | `parse_protocol` / `parse_matcher` / `parse_events` / `parse_method` | `own-ir/src/protocol.rs` |
| the lattice, the walker, `check_protocols`, `unmatched_scopes` | `obligations.py` | **new** `own-analysis/src/obligation.rs`, beside `di.rs` / `effect.rs` |
| the `(kind, definite)` → code table, the messages, the slice | `ownir.py::_protocol_findings` / `_protocol_message` | `own-bridge/src/verdict.rs`, where `refuse_protocols` is today |

The typed `Protocol` / `Matcher` / `MethodEvents` / event values are built by
**one** implementation of the grammar with two consumers, not a second parser
in `own-analysis`: `own-ir/src/protocol.rs` grows from *validate* to *validate
and construct*, the strict door keeps taking only the identity it needs, and
the analysis takes the value. Two interpretations of one grammar is the same
drift as two censuses. No new crate: `own-analysis → own-ir` is an existing
allowed edge (`own-diagnostics/tests/dag.rs`), and no core crate depends on the
bridge.

The strict door's error texts do not move by a byte. The cp1 ledger
(`tests/fixtures/ownir_validation.json`) carries protocol controls with their
accept/reject verdict and their category; red there is a stop, not a thing to
re-baseline.

### 3.2 The door difference, and where it is pinned (OD-1)

Three of the tolerant door's protocol rules — the malformed-entry skip (H24,
H25) and first-wins on a duplicate name (H26) — are **unreachable through the
typed Rust constructor**, exactly as the effect-entry skip already is. They are
pinned at the raw-document level with unit controls in the bridge (the shape
`malformed_effect_entries_are_skipped_not_coerced` established at cp4), not by
quietly coercing a document into shape. If a synthetic case needs such a
document to travel through the door, it becomes a **declared** `verdict_door_*`
exclusion with a reason — never a silent coercion.

## 4. The surfaces 4b moves

| surface | change |
|---|---|
| `tests/fixtures/verdicts/manifest.json` | the two protocol entries leave `rust_replay_excluded`; the new `verdict_protocol_*` cases join `cases` (insertion-stable) |
| `own-bridge/tests/verdicts.rs` | the pinned exclusion set shrinks by the two promoted names — the deliberate contract change this checkpoint exists for |
| `tests/fixtures/verdicts/protocol_isloaded_*.verdicts.json` | **not regenerated**. They are Python's truth as committed; the replay must converge on them as they are |
| `tests/verdict_surface_inventory.py` | `obl_message` becomes per-code rows counted over the replayed set; `protocol_flow` / `protocol_flow_3` lose the "4b, not cp5" disposition and must each carry replayed coverage |
| `docs/generated/p022-cp4-census.md` | the "refused … `obligation protocol`" line disappears (the fragment is rendered, so it rebuilds itself) |
| `tests/fixtures/repro/protocol_isloaded_violation.*` | artifact, trace and reduction regenerate: the Rust engine's `verdicts` layer moves from `refused` to `produced`. The only golden 4b regenerates, and for a stated reason — the same shape of change #339 recorded when the shadow verdict capture moved `partial` → `full` |
| `docs/generated/p022-shadow-census.md` | rebuilds with one fewer refused layer envelope |
| `spec/BridgeBehaviorMatrix.md` | the protocol rows become `L3 ✅`; the paragraph in (e) that names the protocol family as outside the replayed set is rewritten |
| `spec/Bridge.md` §6 | "OBL analysis not ported" leaves the `rust_replay_excluded` description |
| `docs/proposals/P-022-rust-core-migration.md` | row 4b → complete; the preferred queue moves to the coordinate decision |
| `docs/notes/p022-bridge-verdict-checkpoint4.md`, `…5.md` | a "read as history" banner where they say the protocols are not ported |
| `scripts/render_checkpoint_status.py`, `tests/test_checkpoint_status.py` | the 4b campaigns registered in both |

## 5. Stop conditions

Recorded before the work, so that hitting one is a decision and not a
temptation:

* wanting to touch a golden or `ownlang/` to make something agree;
* a divergence that looks like a **Python** bug — P-025's standing red line is
  *never invent a violation*, so it gets reported, not fixed;
* needing semantics that are in neither `obligations.py` nor `spec/OwnIR.md`
  §8;
* the strict door and the tolerant path diverging in a way that needs a new
  ledger member;
* a synthetic case that cannot be built without changing the grammar.

## 6. The wording 4b earns

> Layer 3 parity over the measured set, protocol family included; unmeasured
> set: coordinate-domain controls (decision owed), OD-1 door controls.

Not "#259 complete" — the coordinate-domain decision is still owed. Not
"shadow mode": the `own-shadow` reducer still refuses the verdict layer, which
is #260's boundary. Not "P-022 done".
