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

The measured census is generated, never typed:
[`docs/generated/p022-cp4-census.md`](../generated/p022-cp4-census.md) —
goldens by origin, the reference's refusals and findings, the exclusions
grouped by the ledger's executable expectation, and the replayed set with its
refusals and findings — rendered by `scripts/render_checkpoint_status.py`
from `tests/verdict_census.py` (the one interpretation of the manifest the
fixture harness shares) and held in sync by `tests/test_checkpoint_status.py`
inside the suite: evidence that changes without a regenerated fragment is a
red build. The differential counts over the replayed set are asserted by the
Rust replay (every divergence collected, any one fails the build), so a
green replay reads 0 / 0 / 0 / 0 / 0 by construction. What the replay
compares is stated here because it is a declared surface, not a measurement.

The **compared members** at cp4: `file, line, column, code, component, event,
handler, kind, advisory, severity, ignore_reason`. Not compared yet:
`message`, `related`, `flow` — the goldens carry them, cp5 compares them
without regenerating a golden.

### The unmeasured set is named, not hidden

Each exclusion is an entry in `rust_replay_excluded` with a reason and an
expectation the replay executes (`rust_refusal: bridge` + an error substring,
or `door`); the set is also pinned by name, and an exclusion that stops
holding is a red build demanding promotion.

1. **Obligation protocols.** `ownlang/obligations.py` has no
   `own-analysis` port. A document that declares a protocol is **refused**
   by `check_facts`, never given a verdict list with a family missing —
   `protocol_isloaded_clean` would otherwise have "matched" vacuously.
   #259's checkpoint list never names the protocol analysis; its final
   acceptance ("full test-family inventory from #258") does. Recorded as
   **its own checkpoint (P-022 row 4b)**, deliberately not folded into cp5:
   cp5 is messages, evidence and rendering, and a whole analysis family on
   top would make the last checkpoint a bag. 4b does not block cp5; #259's
   final acceptance needs it.
2. **The `u32` coordinate domain.** The core's line is a `u32`; the
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
   "closed by widening Rust" or reported as parity. The owner's stated
   direction on review: **Python-first tightening** — define the valid
   coordinate domain normatively (a negative source line is meaningless),
   teach the reference to reject it, then remove the exclusion; as its own
   contract change with parity evidence, never by declaring the reference
   wrong because the port is `u32`.
3. **OD-1, measured.** The Rust tolerant entry is the typed `OwnIr`
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

### The `subject` tail

The core change adds data to a diagnostic; whether it changes any
**serialized** surface was checked rather than assumed. On the Rust side
`render.rs` states it does not consult `subject`, `sarif.rs` never reads it,
and its only carrier is `LocatedDiagnostic`/`DiagIdentity` — an in-memory
comparison key, not an output. On the reference, `subject` is read by the
bridge and by `report.py` (the `.ownreport.json` buffer report, struck from
the port in #256). No Rust output surface serializes it, so "behavior
changes: none" holds; cp5 re-checks this when the bridge's render/SARIF
paths land.

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

**Round 2 caught every mutation but one; the survivor, M19, was closed on
review in round 3.** M19 survived because BR-V1's ERROR-only rule guards a
state the corpus cannot produce (no facts producer reaches the one core
pass that grades below ERROR). Leaving a normative rule permanently
unprovable was the wrong resting place: the filter is now a pure predicate
(`is_mapped`, BR-V1 + BR-V2 in one place) and a synthetic WARNING is driven
through `map_core` itself — same diagnostic, same handle, ERROR → one
finding, WARNING → none — so the mutation is caught at the unit level, with
the corpus still unable to reach it (recorded as such in the campaign
definition's expected catchers).

The campaign is committed as evidence, not prose. The **definition**
`docs/evidence/p022-cp4-mutations.json` carries every mutation's target,
pattern, replacement, rule and expected catchers, with `M00` as the honesty
control; the **recorded run** `docs/evidence/p022-cp4-mutations.result.json`
is raw outcomes only — every catching test, the commit and the definition
hash it ran on — replayable with `scripts/mutate_campaign.py --run` on a
clean tree. The counts and the per-mutation table are rendered into
[`docs/generated/p022-cp4-mutations.md`](../generated/p022-cp4-mutations.md)
and checked by the suite; a result that no longer matches its definition is
a red build, not a stale number. The round tallies above are history — the
recorded run is the current claim.

Two catching layers exist where the analysis owns the rule (M07, M12, M13,
M30) and one where only the bridge does — the same shape as cp1's ledger:
the bridge replay is the outer catcher, and a rule with a single catcher is a
rule with a single control. Two rules (M09, M19) are catchable only at the
unit level because the production entry cannot reach them; both say so in
the test.

## What checkpoint 5 needs

The comparison matrix over the same frozen goldens — cp5 turns every
"deferred" row into "prove" and keeps every "proven" row as a regression
guard; **no golden is regenerated beside the cp5 implementation**, because
"implementation disagreed with the golden → regenerate → agreement" is the
one move this family exists to make impossible:

| `Finding` surface | cp4 | cp5 |
|---|---|---|
| identity (`file`, `code`, `component`, `event`, `handler`) | proven | regression |
| anchor (`line`, `column`) | proven | regression |
| `kind` | proven | regression |
| tiering (`advisory`, `severity`, `ignore_reason`) | proven | regression |
| ordering and dedup | proven | regression |
| `message` | deferred (carried) | prove |
| `related` | deferred (carried) | prove |
| `flow` (evidence slices) | deferred (carried) | prove |
| rendered diagnostic (`render*`) | deferred | prove |
| SARIF projection (`build_sarif`, bridge path) | deferred | prove |

And the wording discipline that comes with it: what cp4 proved is "the
replayed findings × the cp4 comparison projection" (the count is the
generated census's, never a sentence's), never "verdict parity complete" —
the shortcut a roadmap status is made of.

Concretely:

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
