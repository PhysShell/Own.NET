# P-022 step 6b (#259) — checkpoint 4: analysis wiring

> Status: **checkpoint-4 deliverable** — the bridge feeds real `OwnIR` facts
> through the ported analyses and maps their verdicts back to C# anchors, at
> the checkpoint-4 comparison surface (identity, anchor, kind, tiering).
> Checkpoint 5 (messages, evidence, rendered surfaces) is unblocked and
> compares against the same goldens. Written from the tree at the commit that
> landed it; the numbers below are the ones the suites assert.

## What landed

- **`own_bridge::check_facts(&OwnIr) -> Result<Vec<Finding>, BridgeError>`** —
  `ownlang/ownir.py::check_facts` as spec/Bridge.md §5 writes it, in order:
  lower (the cp2 `lower_full`, now also returning the Python-shaped handle
  records with `column`, the OWN051 tuples and the solve-failure reason) →
  the Layer 2 document rebuilt as the core AST (`ast.rs`) →
  `own_analysis::check_module` (buffer policy, lifetime, resolver, ownership)
  → ERROR-only, the closed BR-V2 skip list, `subject` → handle or the
  reference's map-or-raise refusal (BR-V3) → anchors per BR-V5 (the record's
  line; OWN025 at the view site with `column: None`; DI004/DI005 at the
  finder-selected call/store site) → kind and tiering per BR-V4/V6 → DI
  (`services[]` through BR-P1's coercions into the five `own-analysis`
  finders, in the bridge's append order) → effects (`effects[]`, BR-P2
  skip-not-coerce, `find_effect_storms`) → OWN050 → OWN051 → OWN052 → dedup
  (BR-V7) → the stable `(file, line, column or 0, code)` sort (BR-V8).
- **Layer 2 → core AST** rather than a second lowering: the projection
  `ownlang/lowered.py` drops only the declaration lines `to_module` fixes at
  `0`, so the AST built from the 27/27 byte-exact document is the reference's
  node for node, and a lowering defect stays visible at the Layer 2 seam
  instead of hiding behind a verdict.
- **The one core change: the verdict `subject`.** `own-analysis` emitted
  `(code, line)` only; the bridge maps through `subject` (`name#line`) and
  nothing else, so `Emit::push_at` now stamps the symbol's `origin` exactly
  where `analysis.py` passes `subject=sym.origin` (state problems, OWN001 via
  the RID's minting symbol, release, overspan, the return path, the buffer
  escape codes) and `lifetimes.py` stamps `source#line` on OWN014 — and
  nowhere else (the loan/permission codes stay subject-less, as in Python).
  Pinned through `check_module` in `own-analysis/tests/subject.rs`.
  Not stamped, deliberately: `resource_kind`, messages and evidence on the
  `.own` path are the core's own later contract (own-cli), not this
  checkpoint's, and nothing here asserts them.
- **Layer 3 fixture family** (spec/Bridge.md §6): `ownlang/verdicts.py`
  (`VERDICTS_VERSION = 1`, every `Finding` member in declaration order, a
  refusal as `{"error": …}`), `tests/test_verdict_fixtures.py` (verify /
  `--write`, ledger == swept corpora + synthetic == goldens, orphan/stale/
  missing red, determinism), `tests/fixtures/verdicts/manifest.json`, and the
  Rust replay `own-bridge/tests/verdicts.rs`. All cases go through the
  **tolerant door** (`check_facts` on the loaded document) on both sides.
- DAG: `own-bridge` → `own-syntax`, `own-cfg`, `own-analysis`,
  `own-diagnostics` added to the allowed set; a named test now asserts no
  core crate depends on the bridge.

## Census

| | |
|---|---|
| goldens (Python's truth, complete) | **77** — 22 `ownir` + 27 `lowered` + 9 `summaries` swept, **19** synthetic |
| replayed by Rust at the cp4 surface | **69** — 5 refusals, **127** findings |
| declared exclusions (executable) | **8** — 2 protocol documents, 4 coordinate-boundary controls, 2 OD-1 door controls |
| Python-only / Rust-only / Changed / Ordering-only / Unexplained, over the replayed set | **0 / 0 / 0 / 0 / 0** |

The **compared members** at cp4: `file, line, column, code, component, event,
handler, kind, advisory, severity, ignore_reason`. Not compared yet:
`message`, `related`, `flow` — the goldens carry them, cp5 compares them
without regenerating a golden.

### The unmeasured set is named, not hidden

Each exclusion is an entry in `rust_replay_excluded` with a reason and an
expectation the replay executes (`rust_refusal: bridge` + an error substring,
or `door`); the set is also pinned by name, and an exclusion that stops
holding is a red build demanding promotion.

1. **Obligation protocols (2).** `ownlang/obligations.py` has no
   `own-analysis` port. A document that declares a protocol is **refused**
   by `check_facts`, never given a verdict list with a family missing —
   `protocol_isloaded_clean` would otherwise have "matched" vacuously.
   #259's checkpoint list never names the protocol analysis; its final
   acceptance ("full test-family inventory from #258") does. Owed to cp5 or
   a step of its own — not silently absorbed here.
2. **The `u32` coordinate domain (4).** The core's line is a `u32`; the
   strict door admits every signed 64-bit coordinate (`spec/OwnIR.md` §4.2)
   and the tolerant door anything `_as_int` passes. A coordinate outside
   `0..=u32::MAX` on a lowered node, a DI registration line or an effect line
   is **refused, never clamped** (`ast::core_line`); a site or binding line
   whose only reader guards on `>= 1` folds a negative value to `0`, which
   is exact on every path (`verdict_di_duplicate_sites_last_wins` pins it).
   The reference analyzes these documents (OWN001 at `B.cs:-1`, DI001 at
   `reg.cs:-5`, …). This is the cp1 pattern again: a divergence family
   outside the measured set, recorded so a decision can be taken — a
   Python-first bound in §4.2, or a wider core line type — rather than
   "closed by widening Rust" or reported as parity.
3. **OD-1, measured (2).** The Rust tolerant entry is the typed `OwnIr`
   constructor, so BR-D2's skip-not-coerce (`deps: "a"`) and the finders'
   unknown-lifetime tolerance are unreachable through it: the reference
   reports the sibling finding, the constructor refuses the document. The
   bridge-side port of both rules exists and is pinned at the raw-document
   level (`verdict::tests`), because that is the only level the production
   surface can reach them from today.

One **comparison** boundary on refusals: the map-or-raise text interpolates
the core diagnostic's `message`, and this core's messages are still titles
(`undefined name` vs the reference's `undefined name 'loc_0'`), so the three
`hoist_neg_*` refusals are compared up to their `message=` member — on both
sides, by the same function. The lowering-time refusals are byte-exact.

### The dedup key, minus `message`

BR-V7's key is `(file, line, column, code, component, event, handler,
message, kind, advisory, severity, ignore_reason)`; cp4 carries every member
but `message`. On the reference's own outputs that is exact: every message is
a function of the handle record and the code (the flow-local wordings key on
`code`/`pool`/`ever_released`, the token wordings on the record, and the
same-handle same-code duplicates BR-V7 exists for are byte-identical), so two
findings equal on the carried members are equal on the message. The corpus
measures it (the two-exit and nested-throw leaks fold to one finding on both
sides); cp5 adds the member.

## Mutation campaign

Per the P-022 discipline (rule 2: a test is evidence only once its mutation
fails through the production surface; rule 3: no fail-fast — every catching
layer is recorded). Each mutation is applied to a copy of the file and
restored from that copy, never by `git checkout` (the lesson from cp1's
third round); `M00` is the harness-honesty control (no mutation must report
zero failures); a compile error is reported as such, never as "caught".

**Round 1 (24 mutations) surfaced three real gaps and one bad mutation**,
all fixed before round 2:

- M01 survived — nothing in the corpus produced an OWN033/034/035/041, so
  the *closed* BR-V2 list had no control per member.
  → `verdict_skip_list_artifacts` (partial return, bare return beside a
  value return, a borrow handed to a consume position, an arity mismatch;
  OWN040 is unreachable by construction).
- M04/M06 survived — `column` and `event` were redundant in the dedup key on
  that corpus (`handler` and the distinct names kept the pairs apart).
  → a same-name rebind on one line differing only in column; one record
  pair per key member (event, handler, component, kind, severity,
  ignore_reason) differing in exactly that member.
- M10 was not a mutation: `owned_here.is_empty() && …` kept the gate for the
  empty case it was meant to drop. Rewritten as `false && …`.
- The harness attributed catchers to the wrong target: cargo's `Running`
  lines are on stderr, test results on stdout, and capturing them
  separately loses the interleaving. Fixed by merging the streams.

**Round 2: 30 mutations, 29 caught, 1 declared survivor.**

| id | mutation | caught by |
|---|---|---|
| M01 | BR-V2 skip list: OWN033 no longer skipped | verdict replay |
| M02 | BR-V5 flow-local anchored at the core's line, not the acquire record | verdict replay |
| M03 | BR-V5 OWN025 anchored at the acquire, not the view site | verdict replay |
| M04 | BR-V7 dedup key drops `column` | verdict replay |
| M05 | BR-V8 sort key drops `column` | verdict replay |
| M06 | BR-V7 dedup key drops `event` | verdict replay |
| M07 | DI004/DI005 duplicate site: last-wins → first-wins (`own-analysis`) | `fact_parity::di_fact_parity` **and** verdict replay |
| M08 | BR-V6 DI001 graded `warning` | verdict replay |
| M09 | BR-D2 effect `deps` coerced instead of skipped | `verdict::tests::malformed_effect_entries_are_skipped_not_coerced` (raw-document level — the only reachable one, see OD-1) |
| M10 | BR-L8 OWN051 owned-local gate dropped | verdict replay |
| M11 | BR-M1 OWN052 never minted | verdict replay |
| M12 | BR-V3 OWN001 emitted without a subject (`own-analysis`) | `subject.rs` ×3 **and** verdict replay |
| M13 | BR-V3 OWN014 emitted without a subject (`own-analysis`) | `subject.rs` **and** verdict replay |
| M14 | protocol documents no longer refused | verdict replay (the executable exclusion ledger) |
| M15 | `core_line` clamps instead of refusing | verdict replay (the executable exclusion ledger) |
| M16 | BR-V6 source tiering inverted | verdict replay |
| M17 | BR-V6 an empty `ignore_reason` suppresses | verdict replay |
| M18 | BR-V7 dedup removed | verdict replay |
| M19 | BR-V1 ERROR-only filter removed | **survived — declared**: no warning-tier core verdict exists in this core today (Python's `validate_policies` warnings have no facts producer), so the filter has nothing to filter; kept as the faithful port, recorded as a blind spot |
| M20 | `_as_col` accepts `0` | verdict replay |
| M21 | a negative DI site line folds to `1`, not `0` | verdict replay |
| M22 | OWN050 never minted | verdict replay |
| M23 | BR-V3 handle read from the wrong subject separator | verdict replay |
| M24 | OWN051 anchored at `0`, not the call line | verdict replay |
| M25 | BR-V7 dedup key drops `handler` | verdict replay |
| M26 | BR-V7 dedup key drops `component` | verdict replay |
| M27 | BR-V7 dedup key drops `kind` | verdict replay |
| M28 | BR-V7 dedup key drops `severity` | verdict replay |
| M29 | BR-V7 dedup key drops `ignore_reason` | verdict replay |
| M30 | DI findings anchored at `0`, not the finder's anchor | `verdict::tests::di_coercions_match_the_reference` **and** verdict replay |

Two catching layers exist where the analysis owns the rule (M07, M12, M13,
M30) and one where only the bridge does — the same shape as cp1's ledger:
the bridge replay is the outer catcher, and a rule with a single catcher is a
rule with a single control.

## What checkpoint 5 needs

- the message matrix (BR-V4) on the bridge findings, and the core diagnostic
  messages behind the map-or-raise text;
- the `related`/`flow` evidence slices (DI paths via the registration map,
  the DI004/DI005 registration `related`, the effect re-run → mint slice,
  the flow-local origin → violation slice, the capture escape slice);
- `render`/`render_github`/`render_msbuild`/`build_sarif` on the bridge path
  (BR-V9), reusing `own_diagnostics::sarif`;
- tightening `verdicts.rs` to full equality on the existing goldens;
- the two decisions this checkpoint owes: the protocol analysis, and the
  coordinate domain.
