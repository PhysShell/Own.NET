# P-022 step 6b (#259) — final acceptance: the coordinate-domain contract

> Status: **in execution.** final.0 the inventory (this note's §1–§2), final.1
> the Python-first contract change, final.2 the Rust mirror and the promotion
> of the four boundary controls, final.3 the campaigns and the status surfaces.
> This note is both the plan and the completeness ledger. Counts are not typed
> here — they live in the generated fragments
> ([coordinate census](../generated/p022-coord-census.md),
> [cp1 census](../generated/p022-cp1-census.md),
> [Layer 3 census](../generated/p022-cp4-census.md),
> [campaigns](../generated/p022-coord-mutations.md)) and the prose links.

Checkpoints 1–5 and 4b took `own_bridge::check_facts` to Layer 3 parity over
the measured set, at the full `Finding` and at the rendered surfaces. What #259
still owed was one **contract decision**, not one more port: `spec/OwnIR.md`
§4.2 bounds a source coordinate at signed 64 bits, the core's AST holds a line
as `u32`, and the four `verdict_boundary_*` controls sat in the verdict
ledger's `rust_replay_excluded` because of the gap between those two numbers.

The decision is the owner's and is recorded in §0. This note measures the tree
against it **before** anything moves, because the previous contract change of
this shape (#326) established the order: a change to what the reference accepts
lands Python-first, and the census that judges it is taken against the tree
rather than against the change.

## 0. The decision (owner), and what it is not

**D1 — the domain.** Every `line` in an OwnIR document is an integer in
`[0, 2147483647]`. `0` means "unknown / file-level" and stays legal: it is the
reference's own default for an absent line (`s.get("line", 0)` and its
siblings throughout `load()`), and the corpus carries it in the goldens as well
as the inputs (§2). A negative line is rejected. A line above `2^31 - 1` is
rejected. Every `column` is in `[1, 2147483647]`, or absent, or `null`.

The rationale, in these terms and no others:

* **int32 is the line type of every consumer this project feeds.** Roslyn's
  `LinePosition.Line` is an `int`; LSP's `uinteger` is capped at `2^31 - 1`;
  .NET diagnostics carry the same width. A coordinate wider than that cannot
  reach the place it points at.
* **Zero is the reference's own absent sentinel**, so bounding the domain below
  at `0` rather than at `1` is reading the reference, not tightening it.
* **No producer emits a negative coordinate.**
  `frontend/roslyn/OwnSharp.Extractor/Program.cs` writes
  `StartLinePosition.Line + 1`, i.e. a 1-based line off a 0-based Roslyn
  position; the census in §2 finds negatives only in controls written to be
  negative.

**Never** "Rust holds `u32`, so the reference is wrong". That sentence is
banned from every surface this change touches. The representation of one
consumer is not an argument about a contract; the set of consumers the contract
must serve is.

**D2 — where it is enforced.** The strict door (`ownlang.ownir.load()`) rejects
an out-of-domain coordinate with category **Location** — the cp1 taxonomy's "a
representable coordinate violating its domain rule" — for **every**
line-bearing field, including the two §4.2 records as unchecked today:
`components[].subscriptions[].line` and the `line` on a flow op inside
`functions[].body` (recursing through `then` / `else` / `body`, exactly as
`_check_column` already does). Those two fields also gain **type** validation:
a string or a bool there is a Shape rejection, as it is everywhere else. §4.2's
deferred question closes in the same move.

**D3 — the tolerant door.** `check_facts()` on un-validated facts **degrades**
an out-of-domain line to `0` (absent) — exactly as `_as_col` degrades a bad
column to `None`. It never raises, never clamps to a neighbour, never invents.
The Rust bridge does the same where it refuses today
(`own_bridge::ast::core_line` and its callers in `verdict.rs`).

The consequence is the point of the whole change: the four `verdict_boundary_*`
controls leave `rust_replay_excluded`, and the exclusion ledger is left naming
only the two #294 OD-1 door controls — a declared boundary, measured, not open
work.

**What this is not.** Not a re-litigation of #326: signed-64 stays the
*representable integer form* an OwnIR coordinate may take, and the domain is a
rule about which of those values mean anything. The two are different axes and
the cp1 taxonomy already separates them (§2.4). Not a change to any severity,
any message matrix, any analysis. Not #294 OD-1, not the DI004/DI005
rendered-surface case, not the BR-V5 protocol-path sentence, not `own-shadow`'s
Layer 3 boundary.

## 1. The inventory: every coordinate slot, on both doors, in both languages

### 1.1 Lines

| slot | strict door (`load()`) today | tolerant door (`check_facts`) today | Rust typed model | Rust `u32` conversion |
|---|---|---|---|---|
| `services[].line` | type + §4.2 range (`_check_int_range`) | `_as_int` | `Option<i64>` | `verdict::anchor_line` → `ast::core_line` |
| `services[].ctor_line` | type + §4.2 range | `_as_int` | `Option<i64>` | `verdict::guarded_line` → `ast::core_line` |
| `services[].root_resolve_sites[].line` | type (inside the `all(...)`) + §4.2 range | `_as_int` | `Option<i64>` (`Site`) | `verdict::guarded_line` → `ast::core_line` |
| `services[].scope_cache_sites[].line` | type + §4.2 range | `_as_int` | `Option<i64>` (`Site`) | `verdict::guarded_line` |
| `effects[].line` | type + §4.2 range | `_as_int` | `Option<i64>` | `verdict::anchor_line` |
| `effects[].bindings[].line` | type + §4.2 range | `_as_int` | `Option<i64>` | `verdict::guarded_line` |
| `functions[].params[].line` | type + §4.2 range | `_as_int` | `Option<i64>` (`Param`) | `ast::param` → `ast::core_line` |
| `protocol_functions[].events[].line` | type + §4.2 range, through `obligations._opt_line` | the same parser, per-entry skip on failure | typed by `own_ir::protocol` | the analysis owns its own anchor |
| `components[].subscriptions[].line` | **nothing** — not range, not type | `_as_int` | untyped: `Subscription.extra` (a raw `Value`) | `verdict` reads it as an `i64` anchor |
| `functions[].body[]…line` (flow op, at every nesting shape) | **nothing** | `_as_int` | untyped: `Function.body` is raw `Value`s | `ast::stmt` → `ast::core_line` per op |

The last two rows are §4.2's recorded exception, and it is symmetric: **neither
implementation types those fields**, which is why #326 recorded them as an open
contract question rather than as a parity gap. D2 closes the question.

### 1.2 Columns

| slot | strict door today | tolerant door today | Rust |
|---|---|---|---|
| `components[].subscriptions[].column` | `_check_column`: representability, then the 1-based rule, then the §4.2 upper bound | `_as_col` → `None` on anything that is not a 1-based int | `Option<Value>` on `Subscription`, checked by `strict::column` |
| `functions[].params[].column` | `_check_column` | `_as_col` | raw, checked by `strict::column` |
| `functions[].body[]…column` (every nesting shape) | `_check_flow_columns` → `_check_column`, recursing `then`/`else`/`body` | `_as_col` | raw, checked by `strict::flow_columns` |

### 1.3 Where a line becomes a `u32`, and where a column does not

`own_bridge::ast::core_line` is the **only** narrowing on the Rust path. It is
called from `ast::param` and from every `ast::stmt` arm (acquire, release, use,
overspan, return, alias_join, call, subscribe, if, while), and from
`verdict::anchor_line` / `verdict::guarded_line` (services `line` and
`ctor_line`, both site arrays, effect and binding lines). Today it returns a
`BridgeError` naming "outside the core's line domain"; D3 makes it degrade.

The **column** path has no narrowing at all, and that answers a question this
task expected to go the other way. Measured, not read: a document carrying
`"column": 1099511627776` (`2^40`) is

* **accepted** by the Rust strict door (`OwnIr::from_json` → `Ok`), because
  `strict::column` checks representability and the 1-based rule, and `2^40` is
  a representable positive integer;
* carried as `Some(1099511627776)` on `own_bridge::Finding::column`
  (`Option<i64>`);
* emitted as `"startColumn":1099511627776` by `own_bridge::build_sarif`.

So there is **no second undeclared boundary** on the column path: it is `i64`
end to end, agreeing with the reference. The finding is recorded here because
the absence of a boundary is only evidence once it has been measured — and
because it changes what this task's column work is. `_as_col` and
`own_bridge::lower::as_col` gain D1's upper bound not to close a divergence but
so that the tolerant door cannot emit a column the strict door would refuse.

### 1.4 The comparison surface, restated because it is easy to over-claim

The cp1 ledger compares **accepted / rejected** and, on rejection, the
**category** — never the message text. That is a deliberate, documented
decision (`tests/test_ownir_validation_fixtures.py` § "What is compared, and
what deliberately is not", and the same paragraph in
`own-ir/tests/validation_replay.rs`): the reference funnels every rejection
through one `OwnIRError` whose strings are a human-facing presentation aid, so
byte-comparing them across two languages would freeze a debug surface as a
contract and fail on every rewording.

This change does **not** move that surface. The two doors' new messages are
written to say the same thing in the same shape, because a reader comparing
them by hand should not have to translate; but the executable claim stays
"same accept/reject, same category", and the ledger's recorded `message` stays
Python's own, for the record rather than for the comparison. Stating otherwise
here would be a claim the tree does not make.

## 2. The census, the churn budget, and the controls that flip

### 2.1 The census

`tests/coordinate_census.py` walks **every** `.json` file under
`tests/fixtures/` and classifies every `line`, `ctor_line` and `column` slot at
any depth, by family, by slot and by value class; the rendered result is
[`p022-coord-census.md`](../generated/p022-coord-census.md), gated by
`scripts/render_checkpoint_status.py --check` like every other fragment.

Three properties of it are load-bearing:

* **It is wider than the door.** A coordinate on an OwnIR *document* is
  something `load()` rules on; a coordinate in a golden is an *output* and the
  door never sees it. The census marks the difference and counts both, because
  D1's "`0` stays legal" is a claim about the outputs — the summaries goldens
  alone carry dozens of zero-anchored records, and a census that read only the
  inputs could not have seen a single one of them.
* **Its value classes follow the taxonomy's axis.** `outside-int64` (no
  representable integer form → `Shape`) is a different class from `negative`
  and `above-int32` (representable, out of domain → `Location`). Folding them
  would have reproduced exactly the defect #326's census had to discover: one
  violation classified two ways because the category was read off the
  reference's diagnostic instead of off the mechanism.
* **The slot inventory is asserted as a set.** `SLOTS` is the door inventory,
  and a declared slot no fixture reaches is reported as a phantom — the same
  rule `tests/test_ownir_defensive_limits.py` applies to the schema's binding
  map, for the same reason.

What the census shows, in words (the numbers are in the fragment): every
out-of-domain coordinate in the tree is either a **control written to be one**
— the cp1 ledger's edge cases, the four `verdict_boundary_*` documents, and one
synthetic `root_resolve_sites[].line: -2` in
`verdict_di_duplicate_sites_last_wins.facts.json` — or a **zero**. There is no
corpus document, and no real extractor output, carrying a coordinate this
decision takes away.

The `-2` site line deserves its own sentence, because it looks like churn and
is not. Its only reader guards on `>= 1` (a site line below 1 falls back to the
registration anchor), so `-2` and `0` behave identically on every path; the
committed golden already anchors that finding at `reg.cs:13`, the registration.
The Rust side already folds it (`verdict::guarded_line` returns `0` for a
negative). Degrading it to `0` changes nothing observable, and the golden is
outside the churn budget below.

### 2.2 The churn budget, written before the change

Measured by probe rather than predicted: the tolerant line reader was replaced
in-process with D3's degrade (`ownlang.ownir._as_int` monkeypatched to the
`_as_line` semantics) and every fixture family re-projected against its
committed goldens.

**Changes:**

1. `tests/fixtures/verdicts/verdict_boundary_line_negative.verdicts.json`
2. `tests/fixtures/verdicts/verdict_boundary_line_above_u32.verdicts.json`
3. `tests/fixtures/verdicts/verdict_boundary_service_line_negative.verdicts.json`
4. `tests/fixtures/verdicts/verdict_boundary_effect_line_negative.verdicts.json`

— in each case the finding's `line` alone, moving to `0`. The DI001 evidence
slice in (3) does **not** move: its captor step was already dropped by the
`>= 1` guard at `-5` and is still dropped at `0`.

Plus the generated fragments, which are projections of the evidence and change
because the evidence does: `p022-coord-census.md` (the goldens' classes move),
`p022-cp4-census.md` (the exclusion ledger shrinks and the replayed set grows),
and the new `p022-cp1-census.md` / `p022-coord-mutations.md`.

**Does not change, measured:**

* `tests/fixtures/verdict_renders/` — zero of the rendered-surface goldens;
* `tests/fixtures/summaries/`, `tests/fixtures/lowered/` — zero;
* `tests/fixtures/obligation_fact_parity.json`,
  `tests/fixtures/di_eff_fact_parity.json` — zero;
* `tests/fixtures/repro/` — **zero**, including `digests.json`. This one is
  worth stating precisely, because the shape of #339's and 4b's change made a
  four-record churn the natural expectation. It does not happen, for two
  independent reasons: the digest ledger pins the canonical hash of each
  **facts** document, and no facts document changes; and the curated
  reproduction-artifact set — the only place a layer envelope's
  `produced`/`refused` status is committed — does not contain any of the four
  boundary documents. The `own-shadow` reducer still refuses Layer 3, which is
  #260's boundary and unmoved.

Any diff outside this list is a defect in the work, not "what the tool
produced". It is checked with `git diff --stat` against the branch base before
every commit, and the confirmed stat is pasted into §3.

### 2.3 The cp1 ledger controls that flip

Four accept-controls become Location rejections; one stays accepted. Each is a
**re-measure**, not a weakening: the reference changes Python-first, so
stop-condition 1 ("a Rust/Python divergence is a Rust bug") does not apply, and
the ledger is re-derived from the new reference rather than relaxed to fit a
port. This is the fourth census.

| control | was | becomes | the `why` the decision replaced |
|---|---|---|---|
| `accept-line-at-i64-max` | accept | reject, `location` | "the largest representable line" |
| `accept-line-at-i64-min` | accept | reject, `location` | "…and the smallest, because the range is closed at BOTH ends and a port that bounded only the top would pass a one-sided test" |
| `accept-negative-line` | accept | reject, `location` | "a NEGATIVE line is accepted: only columns carry the 1-based rule, and conflating the two would tighten the door" |
| `accept-column-at-i64-max` | accept | reject, `location` | "…and the largest column" |
| `accept-zero-line` | accept | **accept** (unchanged) | "…and zero is the line default" |

`accept-negative-line`'s old `why` is the position D1 replaces, and it is
quoted rather than deleted: it was a correct reading of the contract as it then
stood, and the reason it no longer holds is that the contract now says lines
carry a domain rule of their own — not that columns and lines were conflated
after all. The controls whose values sit *outside* signed 64 bits
(`line-below-i64`, `line-above-i64`, `line-at-u64-max`, `line-above-u64`,
`line-float`, `column-above-i64`, `column-above-u64`, `column-float`) keep
their `shape` category untouched, which is what keeps the two axes apart: those
values have no representable integer form to violate a domain rule with.

New controls land per section and per field — `-1` and `2147483648` rejected as
`location`, `0` and `2147483647` accepted — for every line-bearing field
including the two D2 admits, plus type controls (`"x"`, `true` → `shape`) for
those two, plus the columns' new upper bound. The full set is generated into
[`p022-cp1-census.md`](../generated/p022-cp1-census.md); no count is typed here.

## 3. What landed, per checkpoint

### 3.1 The four commits

| commit | what |
|---|---|
| `docs(p022): inventory the coordinate domain before changing it (#259 final.0)` | this note's §1–§2, `tests/coordinate_census.py`, the generated coordinate census. No production code — the census that judges a contract change is taken against the tree, not against the change. |
| `feat(ownir): bound source coordinates to int32, validate every line field (Python-first) (#259 final.1)` | §4.2 and §4.1, `spec/ownir.schema.json`, `ownlang/ownir.py`, `ownlang/obligations.py`, the extended defensive-limits controls, the cp1 ledger. |
| `feat(bridge): mirror the coordinate domain and promote the four boundary controls (#259 final.2)` | `own-ir/src/strict.rs` and `protocol.rs`, `own-bridge/src/{ast,lower,verdict,render}.rs`, the exclusion ledger 6 → 2, four controls, the campaign definitions. |
| `docs(p022): record the campaigns and bring the status surfaces level (#259 final.3)` | the recorded runs, the generated fragments, P-022, the index, `spec/Bridge.md`, `spec/BridgeBehaviorMatrix.md`, this note's §3–§7. |

### 3.2 The churn, confirmed

`git diff --stat` against the branch base, for the whole change:

```text
$ git diff --stat 834f295   # the branch base
 tests/fixtures/ownir_validation.json               | 1831 +++++++++++++++++++-
 tests/fixtures/repro/digests.json                  |   22 +-
 tests/fixtures/verdicts/manifest.json              |   32 +-
 ...erdict_boundary_effect_line_negative.facts.json |    5 +-
 ...ict_boundary_effect_line_negative.verdicts.json |    2 +-
 .../verdict_boundary_line_above_u32.facts.json     |    6 +-
 .../verdict_boundary_line_above_u32.verdicts.json  |    2 +-
 .../verdict_boundary_line_negative.facts.json      |    9 +-
 .../verdict_boundary_line_negative.verdicts.json   |    2 +-
 ...rdict_boundary_service_line_negative.facts.json |    7 +-
 ...ct_boundary_service_line_negative.verdicts.json |    2 +-
 .../verdict_domain_tolerant_readers.facts.json     |   48 +
 .../verdict_domain_tolerant_readers.verdicts.json  |   48 +
 ...and 52 more files, none of them a fixture
 65 files changed, 5439 insertions(+), 792 deletions(-)
```

Against §2.2's budget, written before anything moved:

* the four `verdict_boundary_*.verdicts.json` goldens changed, and only in the
  finding's `line`. As predicted, the DI001 evidence slice did not move.
* **the budget was wrong about one thing, in the direction of the work rather
  than of the measurement.** It predicted zero churn under
  `tests/fixtures/repro/`, and that was right about what the *change* forces —
  the digest ledger pins each **facts** document and none of them changes for
  a contract reason. Five records moved anyway, and both reasons are
  deliberate: four because the boundary fixtures' own `_doc` blocks said "the
  Rust core refuses the document rather than clamp the coordinate", which
  final.2 makes false (a control whose documentation contradicts the behaviour
  it pins is worse than four digest records), and one insertion because a
  campaign found a blind spot and the fix was a new control (§5). Zero
  artifacts, traces or reductions moved; the `own-shadow` reducer still
  refuses Layer 3.
* nothing else in `tests/fixtures/` changed: `verdict_renders/`, `summaries/`,
  `lowered/` and both fact-parity ledgers are untouched, and the goldens
  anchored at line `0` — the summaries family alone carries dozens — came
  through exactly as D1 requires.

## 4. The differential over the measured set

Not restated here as numbers, because it is not measured here: it is
**asserted** by two replays that run with zero Python.

* `own-ir/tests/validation_replay.rs` runs every control in the cp1 ledger
  through `OwnIr::from_json` and builds the matrix — agreed accepts, agreed
  rejects, Rust-only accepts, Rust-only rejects, kind mismatches — collecting
  every divergence without fail-fast. All three failure rows must be zero, and
  no control may escape into serde. A green `cargo test -p own-ir` is that
  statement; a non-zero row is a red build, not a number to copy.
* `own-bridge/tests/verdicts.rs` replays every non-excluded Layer 3 case
  against its golden on **every `Finding` member** and every refusal in full,
  and now additionally asserts the §4.2 domain at **Layer 2** over every one of
  them. The four `verdict_boundary_*` controls are inside that set for the
  first time.

Migration counters over the replayed set, in the #250 packet's vocabulary:
Python-only **0**, Rust-only **0**, changed **0**, ordering-only **0**,
unexplained **0** — asserted by those two replays, not counted by hand.

The ledger's own counts live in
[`p022-cp1-census.md`](../generated/p022-cp1-census.md) and
[`p022-cp4-census.md`](../generated/p022-cp4-census.md); the corpus census is
[`p022-coord-census.md`](../generated/p022-coord-census.md).

## 5. What the campaigns found

Two new campaigns
([`p022-coord-mutations.md`](../generated/p022-coord-mutations.md)), split by
door rather than by sub-checkpoint because the two doors fail differently: the
strict one refuses, the tolerant one degrades. Every rule is mutated on **both**
sides, since a domain only one implementation enforces is a divergence rather
than a rule. Every existing campaign was re-run against the new tree, and five
rotted anchors were re-anchored rather than deleted.

The first pass of the tolerant campaign is the part worth recording, because
**seven of fifteen mutations survived** and the reason was the same in every
case: the promotion had made a rule reachable *in principle* while the corpus
still could not observe it.

1. **`ast::core_line` cannot be reached from outside any more.** `lower` reads
   every fact coordinate through `as_line`, so the Layer 2 document the AST is
   built from is already inside the domain and an out-of-domain value dies one
   layer earlier. Clamping in `core_line`, or accepting the whole `u32` range
   again, changed no golden. It is a real second line of defence over an `i64`
   field wider than the domain, and it is not an end-to-end control — so the
   control is a direct one, and its doc comment says so rather than letting a
   unit test on the function under test read as end-to-end evidence.
2. **The tolerant readers the four promoted controls do not reach.** Every one
   of those four passes through the AST build, which degrades a second time, so
   a port that kept the raw fact value still produced the right anchor. Two
   readers are not covered by that: a DI registration line an escape slice's
   source hop reads (guarded on `>= 1` and never narrowed again) and the
   subscription column (read by the column reader alone). One synthetic Layer 3
   case, `verdict_domain_tolerant_readers`, closes both — at `2^31` the hop must
   be DROPPED and the column ABSENT, with an in-domain twin beside each so the
   control cannot pass by refusing everything.
3. **One equivalent mutant, proven and re-anchored.** `render::code_flows` used
   to drop a step it could not convert; §4.2 makes every flow-step line
   convertible, so re-introducing the drop drops nothing and mutating the
   fallback value is unreachable. The mutation was moved onto the conversion
   itself — a one-line shift of every step — which the byte-exact rendered
   replay catches.

The campaign also found a divergence the promotion introduced rather than
exposed: `lower::as_col` had no upper bound, so final.1's Python change would
have left the two tolerant column readers disagreeing. Bounded, with the
control above.

Two mutations were rewritten rather than kept, because each was *caught* by a
traceback rather than by a named check: a Python mutation that removes a type
guard makes the domain comparison raise a `TypeError`, and a catcher recorded
as "non-zero exit with no reported failure" is evidence of a crash, not of the
rule. Both now attack the same rule where it is legible — the bool-is-int trap
on the strict door, and a refusing tolerant reader on the other.

## 6. Measured, not claimed

* **The Rust column path has no `u32` anywhere.** Measured through the crate
  rather than read: a document carrying `"column": 2^40` is accepted by the
  Rust strict door, carried as `Some(1099511627776)` on `Finding::column`, and
  emitted to SARIF as `startColumn 1099511627776`. There was no second
  undeclared boundary to find. The tolerant column readers gained D1's upper
  bound on both sides so the tolerant door cannot emit a column the strict door
  would refuse — not to close a divergence, but so one cannot open.
* **The cp1 ledger compares category, never message text**, and this change
  does not move that surface. The two doors' new messages are written to say
  the same thing in the same shape, and a Rust-local control now pins the
  port's own text against drift; neither makes message text a cross-language
  contract, and claiming otherwise would be a claim the tree does not make.
* **The protocol family's tolerant rule is untouched.** Type and
  representability are grammar and still skip a malformed entry whole (cp4b's
  rule); only the DOMAIN follows the door. That split is a `Door` parameter
  rather than a second parser, because two readings of one grammar is exactly
  what 4b collapsed into one.
* **`ast::core_line` is unreachable end to end**, per §5.1. Recorded rather
  than removed: the type it guards is wider than the domain.
* **The `own-shadow` reducer still refuses Layer 3.** Unmoved, and #260's
  boundary. Nothing here crosses it.

## 7. The wording this earns

> #259 final acceptance reached: Layer 3 parity over the **full** #258 family
> inventory at the full `Finding` and the rendered surfaces; declared boundary:
> the two OD-1 door controls (#294), measured, not open work.

Not "verdict parity complete". Not "shadow mode" — that is #260's acceptance,
still blocked on its own two decisions. Not "P-022 done", and not "Rust is the
default": the cutover is #262's, behind #260 and #261.
