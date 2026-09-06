# P-022 step 6b (#259) — checkpoint 4b: the obligation-protocol analysis (OBL001–005)

> Status: **checkpoint 4b complete — Layer 3 parity over the measured set,
> protocol family included.** 4b.0 the inventory, 4b.1 the analysis and its
> fact-parity family, 4b.2 the bridge and the promotion, 4b.3 the status
> surfaces. This note is both the plan and the completeness ledger: every
> behaviour of `ownlang/obligations.py` and of the bridge's BR-P3 mapping,
> named with what pins it, plus what the corpus reached before and what it
> reaches now. Counts are not typed here: they live in the generated fragments
> ([census](../generated/p022-cp4-census.md),
> [surface inventory](../generated/p022-cp5-inventory.md),
> [campaigns](../generated/p022-cp4b-mutations.md)) and the prose links.

Checkpoints 1–5 ([cp4](p022-bridge-verdict-checkpoint4.md),
[cp5](p022-bridge-verdict-checkpoint5.md)) took `own_bridge::check_facts` to
Layer 3 parity over the measured set, on the full `Finding` and on the rendered
surfaces. One analysis family was missing from the Rust side entirely: the
obligation protocols. The bridge **refused** a document with a non-empty
`protocols[]` (`own-bridge/src/verdict.rs::refuse_protocols`) rather than
return a verdict list with a family silently absent, and the two reference
documents `protocol_isloaded_clean` / `protocol_isloaded_violation` sat in the
verdict ledger's `rust_replay_excluded` with the executable expectation
"`check_facts` errors, and the error contains `obligation protocol`".

4b removed that refusal. It is its own checkpoint rather than a fourth job for
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

## 1. What the two existing reference documents reached (the starting point)

Both were excluded from the Rust replay, so over the **replayed** set the
protocol family was at nothing: the surface-inventory rows `obl_message`,
`protocol_flow` and `protocol_flow_3` all reported no replayed coverage, each
with the recorded disposition "row 4b". Over **all goldens** — Python's
complete truth, which is what 4b inherited as its starting corpus — the picture
was narrower than the row names suggest, and it was measured rather than
assumed
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

So the corpus reached exactly one shape: an OBL001 barrier crossing, definite,
inside an `if` branch, with a late close, on a dotted method name matched by a
`Type.Method` scope suffix, past an allow-listed call and a call the protocol
does not name. Everything else in §2 and §3 below had **no golden**: OBL002,
OBL003, OBL004, OBL005, every exit anchor, every loop, `exit_barriers: false`,
the opaque-write asymmetry, args-narrowing and the unknown argument, exact
scope matching, duplicate protocol names, the malformed-entry skip, the
non-list blocks, the sort key, and the two-step slice itself. Every one of
them has a control now, and the inventory counts them over the replayed set —
the `.*` placeholder row is gone, replaced by five wordings, two exit_desc
tails, five precise slice shapes and an empty-slice degradation.

## 2. The analysis, behaviour by behaviour (`ownlang/obligations.py`)

Each row is a case in the analysis-level fact-parity family
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
`protocol_isloaded_violation` already reached it. The third column is what the
corpus reached **before** 4b; every row is covered now.

| # | Behaviour | Reached before 4b? |
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
| the acceptance grammar (ported at cp1) | `parse_protocol` / `parse_matcher` / `parse_events` / `parse_method` | `own-ir/src/protocol.rs` — now also the typed constructor |
| the lattice, the walker, `check_protocols`, `unmatched_scopes` | `obligations.py` | `own-analysis/src/obligation.rs`, beside `di.rs` / `effect.rs` |
| the `(kind, definite)` → code table, the messages, the slice | `ownir.py::_protocol_findings` / `_protocol_message` | `own-bridge/src/verdict.rs`, where `refuse_protocols` was |

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

## 4. The surfaces 4b moved

| surface | change |
|---|---|
| `tests/fixtures/verdicts/manifest.json` | the two protocol entries left `rust_replay_excluded`; the new `verdict_protocol_*` cases joined `cases` (insertion-stable) |
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
temptation. **None was hit**: no golden and no `ownlang/` line was touched to
make something agree, no divergence looked like a reference bug, every
semantics question was answered by `obligations.py` or `spec/OwnIR.md` §8, the
two doors needed no new ledger member (the one door-unreachable rule is pinned
at the raw-document level, as cp4 established), and every synthetic case built
inside the existing grammar.

* wanting to touch a golden or `ownlang/` to make something agree;
* a divergence that looks like a **Python** bug — P-025's standing red line is
  *never invent a violation*, so it gets reported, not fixed;
* needing semantics that are in neither `obligations.py` nor `spec/OwnIR.md`
  §8;
* the strict door and the tolerant path diverging in a way that needs a new
  ledger member;
* a synthetic case that cannot be built without changing the grammar.

## 6. What landed, and what it cost

### 6.1 The four commits

| checkpoint | what it did |
|---|---|
| **4b.0** | this note: the behaviour ledger, and the measured picture of what the corpus reached |
| **4b.1** | `own-analysis/src/obligation.rs`; `own-ir/src/protocol.rs` from validate-only to validate-and-construct; `tests/test_obligation_fact_parity.py` + its fixture + `own-analysis/tests/obligation_parity.rs`; campaign `p022-cp4b-1` |
| **4b.2** | `refuse_protocols` removed and BR-P3 mapped in its BR-V1 place; both exclusions promoted; seven synthetic Layer 3 cases and one rendered case; the surface inventory's OBL rows made real; the shadow artifact regenerated; campaign `p022-cp4b-2` |
| **4b.3** | the status surfaces: P-022 row 4b and its queue, `spec/Bridge.md` §6, the behavior matrix, the cp4/cp5 history banners, the proposals index, and both campaigns registered in the renderer and in the replayability gate |

### 6.2 Python source of truth, and the frozen fixtures

`ownlang/` is **unchanged** — not one line of `obligations.py` or `ownir.py`.
Every Python file 4b adds is an observer or a generator, in the shape
`verdicts.py` and `lowered.py` established.

| family | authored by | replayed by |
|---|---|---|
| analysis-level violations (new) | `python tests/test_obligation_fact_parity.py --write` → `tests/fixtures/obligation_fact_parity.json` | `cargo test -p own-analysis --test obligation_parity` |
| Layer 3 verdicts | `python tests/test_verdict_fixtures.py --write` | `cargo test -p own-bridge --test verdicts` |
| rendered surfaces | `python tests/test_verdict_render_fixtures.py --write` | `cargo test -p own-bridge --test renders` |
| reproduction artifacts | `python tests/test_repro_fixtures.py --write` **and** `OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test engine` (each engine writes only its own entry) | `cargo test -p own-shadow` |

Steady state runs **zero Python**: `cd rust && cargo test --workspace`.

### 6.3 Production dependency changes

One: `own-analysis → own-ir`, an edge the DAG test already allowed, made
explicit rather than borrowed through `own-cfg`'s re-export. No new crate, and
no core crate depends on the bridge — the constraint that keeps bridge
inference out of the solver is untouched.

### 6.4 Behaviour changes in Python

**None.** The reference is the oracle; every divergence was resolved by
changing the port.

### 6.5 The differential over the measured set

Python-only, Rust-only, changed, ordering-only and unexplained are **0** on
every axis, and that is asserted rather than tallied: the Layer 3 replay
compares every replayed case's full ordered verdict list on every `Finding`
member, collects every divergence without fail-fast, and fails if one exists;
the analysis-level replay does the same over every violation member and the
dead-rule list. A green `cargo test --workspace` is 0/0/0/0/0 by construction.
The measured set itself is the [census](../generated/p022-cp4-census.md) and
the [surface inventory](../generated/p022-cp5-inventory.md); the unmeasured
set is now the coordinate-domain controls and the OD-1 door controls, and
nothing else.

### 6.6 What the campaigns found

Both campaigns are recorded in full
([fragment](../generated/p022-cp4b-mutations.md); definitions and raw results
under `docs/evidence/p022-cp4b-{1,2}.json`). Each was run twice, because the
first run of each found real holes — which is the whole point of running one:

**4b.1 (the analysis).** Three survivors, two of them inherited from the
reference's own suite:

* *`allow` beats `barrier` was unobservable.* The canonical test protocol's
  barrier arguments and allow arguments are **disjoint**, so no event can match
  both and deleting the allow check changes nothing. `tests/test_obligations.py`
  has the same blind spot. A protocol whose barrier matches every
  `OnPropertyChanged` and whose allow names one argument is the only shape in
  which the rule fires at all.
* *`exit_barriers: false` was only tested against the end-of-method leak*, which
  `run()` guards separately — the guard on `return`/`throw` had no case.
* *the unknown-argument rule was masked by the allow list*: with the narrowing
  inverted, an unknown argument matches the **allow** entry too, and allow wins.

A fourth mutation survived correctly: the `if !self.silent` guard around a
loop's emitting pass is **provably redundant**, because `_emit` re-checks the
flag. It is an equivalent mutant, the reference carries the same redundant
guard, and the mutation now attacks `_emit`'s guard — where the two-phase
discipline is actually enforced.

**4b.2 (the bridge).** Four findings:

* *first-wins was rescued by dedup.* Two duplicate records naming the **same**
  barrier produce two byte-identical findings, which BR-V7 collapses — so the
  rule was invisible through its own control. The records now name different
  barriers.
* *the malformed-method skip only proved the easy half*: the bad record was
  last, so a port that stopped at the first bad entry behaved identically.
* *the non-list-block control was vacuous*: with no protocols there is nothing
  to report either way. The rule is observable only through a **scoped**
  protocol, where an empty method list makes the rule dead and a silenced
  family says nothing.
* *the rendered surfaces reached two of the five codes*, so neither exit
  wording nor the `, ` `CPython` puts between scope entries was in the compared
  bytes.

Both campaigns now read fully caught with no missed catchers, on a clean tree.

### 6.7 Two things measured, not claimed

1. **BR-V5's "a slice shorter than two steps is dropped" does not apply on the
   protocol path.** `_protocol_findings` filters steps with `line < 1` and
   stops there; it never drops a short slice. So a leak off the end carries a
   **one-step** slice (its second step would repeat the first), and one whose
   open has no line carries **none**. The port reproduces the reference
   exactly, and the surface inventory grew the families to match rather than
   the port being bent to the prose. Whether the spec sentence or the code is
   wrong is a Python-first question 4b does not answer.
2. **The family's append position is unobservable end to end.** BR-V1 puts
   protocol findings after effects and before OWN050, but BR-V8 sorts by
   `(file, line, column, code)` and two findings from different families never
   share a code — so the code component decides before insertion order can.
   Recorded here rather than dressed up as a control, the same way cp5.1
   recorded that three dedup-key members became unobservable once `message`
   joined the key.

### 6.8 The one golden family that was regenerated

`tests/fixtures/repro/protocol_isloaded_violation.{repro,trace}.json`. The
Rust engine's `verdicts` layer moves from `refused` to `produced` and now
carries the same finding the reference does — the artifact is a record of what
each engine could produce, so a promotion changes it by construction. Same
shape of change as #339's `partial` → `full`, and stated for the same reason.
The `own-shadow` **reducer** is untouched: its scope is still
`["lowered", "summaries"]` and it still records the verdict layer as refused in
every reduction, because crossing that line is #260's acceptance, not 4b's.

Everything else regenerated is an insertion into a ledger whose records depend
only on themselves — `tests/fixtures/repro/digests.json` gained the new
synthetic documents with **zero** existing records rewritten, and the verdict
manifest gained its cases the same way.

## 7. The wording 4b earns

> Layer 3 parity over the measured set, protocol family included; unmeasured
> set: coordinate-domain controls (decision owed), OD-1 door controls.

Not "#259 complete" — the coordinate-domain decision is still owed. Not
"shadow mode": the `own-shadow` reducer still refuses the verdict layer, which
is #260's boundary. Not "P-022 done".
