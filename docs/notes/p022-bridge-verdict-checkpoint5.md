# P-022 step 6b (#259) — checkpoint 5: messages, evidence, rendered surfaces

> Status: **checkpoint 5.1 landed** (5.0 inventory + 5.1 messages and
> evidence). This note names what checkpoint 5 has to prove, who owns each
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

Seven families and six degradation rules, one ledger row each in the fragment:
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
  decision. Its three families stay as cp4 left them: the protocol documents
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

### Six synthetic cases, because a green replay over a corpus that never reaches a branch proves nothing about it

The cp5.0 inventory named every wording and slice the goldens do not reach.
Each one that a facts document *can* reach is now a case under the frozen
manifest ledger — the OWN009 and pooled flow-local wordings with their slices,
the DI-scoped and both inline-lambda OWN014 wordings, the injected-source
lambda note, the dropped OWN014 escape slice, the bare consuming-constructor
tail, the one-step DI retention path, and the dropped effect slice. Adding them
rewrote **no** existing record in either the verdict ledger or the shadow
slice's digest ledger, which is P-022 discipline rule 4 measured rather than
asserted.

Five branches a facts document *cannot* reach are pinned instead by controls in
`verdict::tests`, driven through `map_core` — the production path — in the
shape cp4's `M19` established: the two flow-local fallbacks (the nine-op flow
vocabulary raises only codes that already have a wording), the `transient` and
unrecognised DI lifetime phrases (nothing is shorter than the transient region,
and the DI life map admits only the three lifetimes), and the capture route's
named-source origin (routing R3 mints a handle only for a source with a
declared capture region, and `static` is the only one). Their expected text is
**the reference's own output**, taken by substituting the lowering under
`check_facts` so the oracle could be asked about a state its inputs cannot
produce — not a reading of `ownir.py`.

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
