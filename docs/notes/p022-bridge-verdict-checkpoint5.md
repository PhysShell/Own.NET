# P-022 step 6b (#259) — checkpoint 5: messages, evidence, rendered surfaces

> Status: **checkpoint 5 complete at its surface** — 5.0 inventory, 5.1
> messages and evidence, 5.2 refusal text, 5.3 rendered surfaces, 5.4 the
> status surfaces and the census. This note names what checkpoint 5 has to prove, who owns each
> string it must reproduce, and what each sub-checkpoint closed. Every count
> lives in the generated fragments
> [`p022-cp5-inventory.md`](../generated/p022-cp5-inventory.md) and
> [`p022-cp5-mutations.md`](../generated/p022-cp5-mutations.md); nothing is
> typed here.

Checkpoint 4 ([note](p022-bridge-verdict-checkpoint4.md)) proved identity,
anchor, kind and tiering over the replayed set, and left three members of
`ownir.Finding` carried by the goldens but not compared: `message`, `related`
and `flow` — plus the rendered surfaces (`render_finding`, `build_sarif`),
which have no golden at all. Checkpoint 5 turns each of those into a proof
against **the same frozen goldens**: no golden in
`tests/fixtures/{verdicts,lowered,summaries,ownir}` is regenerated or edited
beside the implementation, because "the port disagreed with the golden →
regenerate → agreement" is the one move this family exists to make impossible.

## 1. Who owns each string

A finding's `message` reaches the Layer 3 document from **three** places, and
the distinction decides where each is ported. The inventory fragment carries
one row per branch with its owner and its measured coverage; the shape is:

| owner | what | where it lives (reference) | where it must live (port) |
|---|---|---|---|
| **bridge** | the BR-V4 matrix — every flow-local wording, the OWN025 view sentence, the OWN014 capture/captive sentences with their `nice` lifetime phrases and the inline-lambda note, the six token-kind sentences, and the OWN050/051/052 advisories | `ownlang/ownir.py::check_facts` (and `_unresolved_findings`, the OWN051 mint in `_lower_flow`) | `own-bridge` (`verdict.rs`) — cp5.1 |
| **core analysis** | DI001–DI005 and EFF001 — the bridge copies `c.message` / `s.message` from the finder's own value and never rewords it (BR-B1: the analysis owns its verdict) | `ownlang/di.py` (five `message` properties + `_consumed_suffix`), `ownlang/effects.py` (`EffectStorm.message`) | `own-analysis` (`di.rs`, `effect.rs`) — cp5.1 |
| **core diagnostic** | the two flow-local fallbacks (`IDisposable local 'x': <core message>`, and its pooled twin) and the `message=` member of the BR-V3 map-or-raise refusal text | the core `Diagnostic.message` built by `ownlang/cfg.py` / `ownlang/analysis.py` / `ownlang/lifetimes.py` | `own-cfg` / `own-analysis` — cp5.2 |
| **bridge, out of scope** | OBL001–005 (`_protocol_message`) | `ownlang/ownir.py::_protocol_findings` | #259 row **4b**, not cp5 — the port refuses a protocol-bearing document |

### The core-diagnostic layer does not exist on the Rust side yet

This is the checkpoint's one real gap, and it was checked rather than assumed:

* every Rust core diagnostic is constructed with its **title** as the message —
  `own-analysis/src/check.rs:29`, `lifetime.rs:25`, `lifetime.rs:161`,
  `ownership.rs:232`, `di.rs:425`, `effect.rs:239` all read
  `title(code).unwrap_or(code)`;
* `own-cfg`'s own diagnostic value carries **no message field at all**
  (`own-cfg/src/lib.rs:50` — `Diag { code, line }`), so the resolver's
  `undefined name 'loc_0'` has nowhere to live today;
* the `own-diagnostics` families that look like they cover this do not.
  `tests/render_replay.rs` proves `Diagnostic::render` / `render_pretty` over a
  message the **fixture supplies**; `tests/model_replay.rs` proves the value
  shape; `own-analysis/tests/parity.rs` compares `(line, code)` only. So the
  message *rendering* is proven and the message *text an analysis produces* is
  not proven anywhere — exactly as cp4 recorded ("this core's messages are
  still titles").

Consequence for cp5.2: the three `hoist_neg_*` refusals are compared up to
their `message=` member today only because `own_cfg::Diag` cannot carry the
name the reference interpolates. Removing that comparison boundary means
teaching the resolver's diagnostic to carry its message — additive data on a
core value, the same shape of change cp4 made for `subject`, and the same
question has to be answered again: does it reach any **serialized** core
surface? (§4 below.)

### The analysis values are missing their presentation data

`own-analysis::di::Service` deliberately dropped the ctor/site metadata
("presentation-only metadata … omitted — evidence and SARIF are a later step",
`di.rs:47`). cp5 is that later step, so cp5.1 restores:

* `Service`: `ctor_file`, `ctor_line`, `ctor_type` — `_consumed_suffix`'s input
  and the DI001/002/003 `related` anchor;
* `DiFinding`: its `message`, and the registration `(file, line)` the DI004 /
  DI005 `related` needs *beside* the call/store-site primary;
* `EffectStorm`: its `message`, plus `origin_kind` and `decl_line` — the second
  hop of the effect slice is the mint site, which the port does not carry.

None of that changes a verdict: it is data the finders already computed and
threw away.

## 2. The evidence slices (BR-V5)

Every family, and every degradation rule, is one ledger row in the fragment:
the DI retention path through `di_path_steps` (one, two, and `via`-hop
lengths), the DI consuming-constructor `related` (with and without a known impl
type), the DI004 and DI005 registration `related`, the OWN014 escape slice
(subscribe site → source registration site), the EFF001 slice (re-run site →
identity-mint site), and the flow-local origin → violation slice per code and
per pool wording. The degradations are the rules that yield an **empty** slice:
a step whose line is `< 1` is omitted, a slice left shorter than two steps is
dropped, and — separately — the shapes that never carry a slice by design (a
flow-local OWN001 is a single point; an OWN014 from the capture route has no
registration hop to reach).

One reading worth recording, because a naive port gets it backwards: the
"shorter than two steps is dropped" rule is **not** universal. It is applied by
the OWN014 escape slice (`len(steps) >= 2`), by `_flow_local_steps` (which
returns a pair or nothing) and by the effect slice (both lines `>= 1`);
`di_path_steps` has no such guard, so a DI path with exactly one resolvable
registration site emits a **one-step** `flow`. The goldens contain such a case.

## 3. The rendered surfaces (BR-V9)

`render_finding` (human / github / msbuild) and `build_sarif` on the bridge
path have **no golden of any kind** — Layer 3 froze the finding list, never its
renderings. What pins them today is `tests/test_ownir.py`, and reading it
against BR-V9 leaves named holes: the workflow-command escaping is pinned for
`%`, LF and the property separators `:`/`,` but **not** for CR; the SARIF
`ownirSchemaVersion` driver stamp is pinned nowhere in the suite; and the
bridge SARIF's `region` omission for `line < 1`, its `startColumn`, its
backslash-normalised URI, its `relatedLocations`/`codeFlows` projection and its
`suppressions` array are each pinned by at most one incidental assertion rather
than by a case that exists for them.

So cp5.3 is a **new fixture family**, not a tightening: an observer emitter
beside `ownlang/verdicts.py`, its own frozen manifest ledger, a verify/`--write`
harness with red stale/missing/orphaned states, and a Rust replay with byte
equality and zero Python. Its ledger rows are already declared in the inventory
fragment and read zero until the family exists.

Two constraints it inherits:

* **Reuse where the format is the core's.** `own_diagnostics::sarif` already
  ports `_phys`, `related_locations` and `code_flow`; the bridge's SARIF differs
  from the core's (`properties`, `suppressions`, `startColumn`, the
  `ownirSchemaVersion` stamp, a per-finding file rather than one run file), so
  the shared parts are reused and the bridge-specific parts are built in
  `own-bridge` — `own-diagnostics`' behaviour on the core path does not move.
* **`subject` must not leak.** cp4 established that no Rust output surface
  serializes a diagnostic's `subject`, and promised cp5 would re-check it once
  the bridge grew render and SARIF paths. `ownir.Finding` has no `subject`
  member at all, so a bridge surface that emitted one would be inventing a
  field; cp5.3 proves that with a test over the serialized surfaces rather than
  by restating the promise.

## 4. What cp5 must not do

* **No golden is regenerated or edited.** A disagreement is classified — port
  bug (fix the Rust), declared boundary (owner decision required, a stop), or a
  Python bug (report, do not fix: Python is the oracle and the BR-V4 strings are
  normative — OwnAudit fingerprints depend on them).
* **No `ownlang/` production change.** New observer modules only, exactly as
  `verdicts.py` and `lowered.py` are.
* **`rust_replay_excluded` neither grows nor shrinks** without an owner
  decision. Its families stay as cp4 left them: the protocol documents
  (row 4b), the `u32` coordinate-domain controls (a contract decision the owner
  has stated a direction for — Python-first tightening — but has not taken), and
  the OD-1 typed-door controls (measured).
* **`own-shadow` does not grow a Layer 3 reducer.** The verdict layer stays
  refused there until #260's acceptance, after 4b.

## 5. The wording that will be true after cp5

> Layer 3 parity over the measured set at the full `Finding` and rendered
> surfaces; unmeasured set: protocol documents (4b), coordinate-domain controls
> (decision owed), OD-1 door controls.

Not "verdict parity complete", not "#259 complete", not "shadow mode", not
"P-022 done".

## 6. The named gaps, and how cp5 closes each

Every row the inventory fragment marks **(gap)** is a branch the corpus cannot
prove. They fall into four groups, and none of them is closed by declaring a
survivor — a synthetic case is added under the manifest ledger instead (the
`M19` precedent from cp4 applies only where a production input genuinely cannot
reach the branch, and the test has to say so itself):

1. **Flow-local wordings the corpus never mints** — the `OWN009` sentences, the
   pooled `OWN002`/`OWN003`/`OWN009` sentences, and the two fallbacks that
   interpolate a core message. New synthetic verdict cases (cp5.1); the
   fallbacks additionally need cp5.2's core message layer to be meaningful.
2. **OWN014 wordings the corpus never mints** — the DI `scoped` / `transient` /
   unknown-lifetime phrases, both inline-lambda notes, and the named
   (non-static) capture origin. New synthetic verdict cases (cp5.1).
3. **Evidence families and degradations reachable only through an excluded
   case** — the one-step DI path and the dropped effect slice live today only in
   documents the Rust side refuses by declared boundary, so they are carried but
   never replayed. New synthetic cases inside the replayed set (cp5.1).
4. **Every BR-V9 row** — no fixture family exists. cp5.3.

The mutation campaign for each checkpoint is what makes the closure evidence
rather than intention: a mutation the corpus does not catch is a missing
control, and the answer is the synthetic case, never a declared survivor.

## 7. What checkpoint 5.1 landed

`own_bridge::Finding` grew `message`, `related` and `flow`, the BR-V4 matrix
and the BR-V5 slice builders were ported, and `own-bridge/tests/verdicts.rs`
now compares **every** member of the reference's `Finding` — cp4's identity,
anchor, kind and tiering plus the three it carried without comparing. **No
golden was regenerated or edited to reach that**: the goldens have carried
those three members since cp4, and the replay went green against the files as
committed.

Three pieces of it are additive core data rather than bridge logic, because the
reference puts them there and BR-B1 says the analysis owns its verdict:

* `own_analysis::di::Service` regained the ctor metadata #214 had dropped as
  "presentation-only", and `DiFinding` now carries its `message`, the
  registration `(file, line)` its DI004/DI005 `related` needs beside the
  call/store-site primary, and the raw `site_line` that says whether the
  primary came from a site at all — which `line` alone cannot, once the
  registration fallback has been applied;
* `own_analysis::effect::EffectStorm` now carries its `message`, plus the
  `origin_kind`, `decl_line` and reference `chain` it is built from — the
  reference's `_Lattice` already computed the chain and the port was throwing
  it away;
* nothing else moved. `check_di` and `effect_diagnostics` (the `(line, code)`
  projections) are untouched, so no existing core surface changed shape.

### Divergences found, and how each was classified

**None.** The first full-equality run over the 69 cases cp4 replayed was green,
and the smoke check that the comparison bites was made explicitly (breaking one
wording turns fourteen cases red) rather than inferred from a passing suite.
That is a statement about the measured set only — see the next section for what
the measured set did not contain.

### Synthetic cases, because a green replay over a corpus that never reaches a branch proves nothing about it

The cp5.0 inventory named every wording and slice the goldens do not reach.
Each one that a facts document *can* reach is now a case under the frozen
manifest ledger — the OWN009 and pooled flow-local wordings with their slices,
the DI-scoped and both inline-lambda OWN014 wordings, the injected-source
lambda note, the dropped OWN014 escape slice, the bare consuming-constructor
tail, the one-step DI retention path, and the dropped effect slice. Adding them
rewrote **no** existing record in either the verdict ledger or the shadow
slice's digest ledger, which is P-022 discipline rule 4 measured rather than
asserted.

The branches a facts document *cannot* reach are pinned instead by controls in
`verdict::tests`, driven through `map_core` — the production path — in the
shape cp4's `M19` established: the two flow-local fallbacks (the nine-op flow
vocabulary raises only codes that already have a wording), the `transient` and
unrecognised DI lifetime phrases (nothing is shorter than the transient region,
and the DI life map admits only the three lifetimes), and the capture route's
named-source origin (routing R3 mints a handle only for a source with a
declared capture region, and `static` is the only one). Their expected text is
**the reference's own output**, and it is not written in the Rust tests: it is
read from `tests/fixtures/unreachable_branches.json`, which
`tests/test_unreachable_branch_probe.py` produces by running `check_facts` with
its lowering and core substituted — the only way to ask the oracle about a
state its own inputs cannot construct. That makes "the reference says so" a
re-runnable fact rather than a claim about how carefully someone read
`ownir.py`, and it removes the second copy of the text a port could otherwise
drift into agreeing with instead of with Python.

What the probe does **not** prove is worth stating in the same breath: the
substitution removes reachability, ordering and the pipeline around the branch,
so it can never stand in for a golden anywhere a golden is possible. It is used
only where one is not.

Every remaining zero row in the inventory fragment now carries its disposition;
a zero row without one renders as `GAP: no control`, so the ledger cannot go
quiet about a branch nobody covered.

### One property of the surface, recorded rather than papered over

The pooled "rented but never returned" sentence is emitted by **two** branches
of the matrix — the flow-local never-returned wording and the `pool` token
wording — on the same `kind`, with the same empty `handler`. Nothing in a
serialized `Finding` separates them, so the inventory carries them as one row.
A port that reached the sentence by the other branch would produce a
byte-identical golden; that is what parity on this surface means, and it is
stated on the row instead of being hidden behind a discriminator that does not
exist.

### The finding cp5.1 did not expect: `message` blinded three of BR-V7's controls

Re-running the checkpoint-4 campaign against the cp5.1 tree turned five
`BR-V7 dedup key drops <member>` mutations from caught into survived. That is
not a weakening, and it is not noise: putting `message` in the key made three
of its members **unobservable at the output surface**. Every wording that
varies with `event`, `kind` or `severity` interpolates it, so downstream of
`check_facts` there is no document producing two findings equal on the message
and differing on one of the three — dropping such a member from the key can no
longer change any output.

Two of the five were recoverable and are now goldens
(`verdict_dedup_key_members`): the disposable-field wording names no handler,
so two `Dispose*` methods on one field are separated by `handler` alone; the
flow-local wording names no component, so the same local leaking in two methods
of one file is separated by `component` alone. The other three drive `dedup`
directly — extracted from `check_facts` for exactly that reason, so the control
runs the production function rather than a copy of it — and the campaign
definition now names that control instead of the replay, because the replay
genuinely cannot catch them any more.

Recording the shape of it, since it will recur: **a comparison surface that
gains a member can lose controls for the members it subsumes.** The campaign is
what surfaced it; a green suite would not have.

## 8. What checkpoint 5.2 landed

The `message=` cut is gone: the three `hoist_neg_*` refusals compare **byte for
byte**, with no normalization on either side. What it took:

* **`own_cfg::Diag` carries a message.** The resolver's `undefined name '<name>'`
  is the one core text the bridge's map-or-raise refusal interpolates over the
  measured corpus — measured, not assumed: driving every facts document in the
  four shared corpora through `to_module` + `check_module` and filtering to the
  diagnostics that fail to map yields exactly one message, and it is that one.
* **`own-analysis` reads it.** `push_cfg_diag` uses the carried message and
  falls back to the code's title where `own-cfg` has none.
* **The remainder is a tripwire, not a blind spot.** `Diag::message` is an
  `Option`, deliberately: a code whose text is not ported still renders as its
  title, and because the refusal comparison is now byte-exact, the first golden
  that refuses on such a code goes **red** demanding the message instead of
  agreeing with a title. That is why porting only what the surface consumes is
  safe here, and it is the reason the cut had to go before the port grew.

### The bug the cut was hiding

Removing the normalization turned the three refusals red immediately, on a
member cp4 could not see: **`py_repr`**. The reference formats the interpolated
message with CPython's `repr`, which switches from `'` to `"` when the string
contains a single quote and no double quote — and *every* core message that
names an identifier does. cp4's placeholder quoted unconditionally with `'`, so
it produced `message='undefined name 'loc_0''` where the reference produces
`message="undefined name 'loc_0'"`.

Classified as a **port bug**, fixed in Rust, and pinned by a unit control whose
expected values are CPython's `repr()` output for the quote switch, both escape
directions, the backslash, the ASCII control range and the `None` case. This is
the whole argument for removing a comparison boundary rather than living with
it: the boundary was not hiding "text we have not ported", it was hiding a
formatting defect in code that *was* ported.

### The consequence in `own-shadow`, and what it is not

The port's shadow capture declared its verdict layer a **partial** projection
whose stated reason was that BR-V4 and the evidence slices "are checkpoint 5
and are not ported". After 5.1 that sentence was false, and a committed
artifact carrying a false declaration is worse than none. So the layer now
emits every `Finding` member and declares `full`, and the artifacts and traces
were regenerated.

**This is not the verdict layer entering shadow mode.** The reducer still
refuses it and records the refusal in every reduction; that stays until #260's
acceptance, after row 4b. What changed is one engine's declaration of what it
puts in the envelope — which is precisely what the projection field exists for.

Promoting it opened a gap, and the gap is closed rather than noted: the
projection check only ever validated **partial** claims, so a `full` declared
over a short document — the over-claim that became reachable the moment nothing
was partial — was unchecked. It now validates both kinds, and the shadow cp2
campaign's `M35` was re-anchored from the lie that is no longer possible
(declare full while partial) to the one that is (declare full while short).

## 9. What checkpoint 5.3 landed

BR-V9 had no golden of any kind. It has one now: a new fixture family built to
the Layer 3 pattern, and a Rust replay that compares the **bytes**.

* **`ownlang/renders.py`** — an observer beside `verdicts.py`, imported by
  nothing in the production path. It calls `render_finding` and `build_sarif`
  and records what they returned: every format at both host severities, plus
  one format `render_finding` does not know, so the fallback is *rendered*
  rather than asserted equal to the human line. `RENDERS_VERSION` keys the
  surface and the docstring freezes the normalization.
* **`tests/fixtures/verdict_renders/`** — targeted cases under a frozen
  manifest ledger, each naming the BR-V9 rows it is the control for. Listed,
  never swept: rendering the whole verdict corpus at two severities would
  freeze megabytes to prove less than a handful of documents chosen for the
  rules do.
* **`tests/test_verdict_render_fixtures.py`** — verify/`--write`, with stale,
  missing and orphaned each a red build.
* **`own-bridge/tests/renders.rs`** — replays every case with zero Python and
  compares byte for byte. Not a value comparison: SARIF key order is part of
  this surface, and a value comparison would score a reordered log as
  agreement. The Rust side reconstructs the document through typed structs
  whose field order *is* the emitter's key order, because `serde_json`'s map
  type sorts and would have quietly produced a different document.

### Reuse where the format is shared, and the one place it is not

`codeFlows` is `own_diagnostics::code_flow` verbatim — the two SARIF paths
genuinely share that projection. `relatedLocations` is **not**, and reusing it
would have been a bug: the core's builder drops a step whose file is empty
(an empty `artifactLocation.uri` makes a log unprocessable for GitHub code
scanning, the invariant `evidence.py` names), while the bridge's inline
comprehension in `ownir.py` filters on the line alone and emits the empty uri.
Python is the oracle, so the port reproduces the reference's behaviour and
`render_evidence_slices` is the golden that goes red if someone "simplifies"
the two into one.

Nothing in `own-diagnostics` changed. The bridge's SARIF differs from the
core's in `properties`, `suppressions`, `region.startColumn` and the
`ownirSchemaVersion` driver stamp, so those are the bridge's own types.

### The `subject` tail, closed

Checkpoint 4 established that no Rust output surface serializes a diagnostic's
`subject` and promised to re-check once the bridge grew render and SARIF paths.
It is re-checked over the **bytes**, on both sides — the Python harness and the
Rust replay each scan the rendered document for a `subject` key — rather than
restated. `ownir.Finding` has no such member, so a bridge surface that emitted
one would be inventing a field.

### Coverage

Every BR-V9 row in the inventory ledger is pinned by at least one case, and the
join is computed rather than asserted: the row ledger lives in
`tests/verdict_surface_inventory.py`, the `pins` live in the fixture manifest,
and a row nobody pins reads `GAP: no control` while a case pinning a row the
ledger does not know is a hard problem. The counts are in
[the generated fragment](../generated/p022-cp5-inventory.md).

## 10. What checkpoint 5.4 landed

The status surfaces, brought level with what the tree proves — and nothing
more.

* **The census** (`docs/generated/p022-cp4-census.md`) now describes the cp5
  comparison surface and counts the rendered-surface family beside the verdict
  ledger, through `tests/verdict_render_census.py` — the one interpretation the
  render harness and the inventory also use. The filename stays cp4's, because
  that is where the fragment was introduced and two notes link it; what it
  *describes* it says in its own first paragraph, which is the honest way to
  keep one census for one ledger.
* **The mutation campaigns** for 5.1, 5.2 and 5.3 are registered like cp4's and
  the shadow slice's, rendered into `docs/generated/p022-cp5-mutations.md` by
  the same single interpreter and held by the same gate: a result that no
  longer matches its definition, was taken on a dirty tree, missed a required
  catcher, or names a commit this tree does not descend from is a red build.
* **`spec/Bridge.md` §6** and **`spec/BridgeBehaviorMatrix.md`** move the BR-V4
  wording rows and the BR-V9 rendering rows from "carried by the goldens,
  compared at cp5" to compared — marked `L3 ✅` in the matrix, with the legend
  saying what the mark means. The P-022 status row and the proposals index move
  with them.
* **No count is typed** into any of them. Every number lives in a generated
  fragment; the prose links.

### The wording this checkpoint earns, and the wording it does not

> Layer 3 parity over the measured set at the full `Finding` and the rendered
> surfaces; unmeasured set: protocol documents (row 4b), coordinate-domain
> controls (decision owed), OD-1 door controls.

Not "verdict parity complete" — the protocol family is a whole analysis that
is not ported, and the bridge refuses rather than answers for it. Not "#259
complete" — row 4b and the coordinate decision are both outstanding. Not
"shadow mode": the reducer still refuses the verdict layer, which is #260's
boundary. And not "P-022 done" by any reading.
