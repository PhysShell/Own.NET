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
