# P-022 step 7a (#260/#269) — checkpoint 1: same-input capture and the reproduction artifact

> Status: **infrastructure for shadow mode**, checkpoint 1 of the row-7a
> slice. This is not shadow mode and does not claim parity. Comparing two
> engines' end diagnostics as an acceptance surface is #260's *acceptance* and
> is blocked by #259 (cp5 and 4b); nothing here attempts it, approximates it,
> or should be quoted as it. Written from the tree at the commit that landed
> it; every number in it is generated — see
> [`docs/generated/p022-shadow-cp1-census.md`](../generated/p022-shadow-cp1-census.md).

Two questions have to be settled **before** two engines can be compared at
all, and neither of them is a comparison:

1. **Did both engines see the same input?** Without a canonical identity for
   an `OwnIR` document, "same input" is an assumption about which file was
   passed where — and a differential harness built on an assumption reports
   agreement it never measured.
2. **What does a reproduction look like?** A divergence is only actionable if
   it can be re-run from one self-contained thing.

Checkpoint 1 answers both, and nothing else.

## What landed

- **`ownlang/repro.py`** — the authoritative emitter. Strictly an OBSERVER,
  like `ownlang/lowered.py` and `ownlang/verdicts.py`: it never mutates facts,
  never changes a verdict, and is imported by nothing in the production path.
  It **composes** the three frozen layer surfaces and never re-encodes them.
  Its docstring freezes the canonical form and the artifact format, in the
  house style (the emitter's docstring is the contract, not a second spec that
  drifts from it).
- **`rust/crates/own-shadow`** — the replaying half, with **zero Python**: the
  canonical form and digest, the artifact's verification, and the artifact's
  rendering. `verify` is deliberately an *independent reading* of the same
  frozen rule rather than a port of the reference's code, so a divergence
  between the two is itself a finding.
- **`tests/fixtures/repro/digests.json`** — the canonical hash of **every**
  facts document in the shared corpora plus this family's own canonical-form
  controls. This is the same-input capture surface, and the Rust side
  recomputes all of it.
- **`tests/fixtures/repro/<case>.repro.json`** — reproduction artifacts for a
  curated set, replayed byte-for-byte by the port.
- **`tests/test_repro_fixtures.py`** — verify / `--write`, and the controls.
- **`scripts/mutate_campaign.py`** + **`scripts/render_checkpoint_status.py`**
  + **`tests/test_generated_docs.py`** — the campaign as data and the census as
  a generated document, both gated. See "Method" below.
- DAG: `own-shadow` added to the allowed edge set with an **empty** dependency
  set, and a named test asserts no core crate — nor `own-bridge` — depends on
  it. An oracle a core crate can reach is an oracle the core can shape.

## Census

Generated, not typed:
[`docs/generated/p022-shadow-cp1-census.md`](../generated/p022-shadow-cp1-census.md).
The headline figures at the time of writing: **80 documents** captured and
digest-pinned across five corpora, **80** tamper controls, **6** documents both
engines must refuse to name, **8** artifacts round-tripped and verified
(carrying 21 produced and 3 refused layer envelopes), **12** structural and
**5** domain-backstop negative controls on each side, and a mutation campaign
of **30 mutations, 30 caught, 0 survivors**.

**Python-only 0 / Rust-only 0 / Changed 0 / Ordering-only n/a / Unexplained
0**, over the 80-document measured set. *Ordering-only* is named as
inapplicable rather than reported as a zero: the canonical form sorts by
construction, so there is no ordered output being compared at this layer yet.
The census names the gates that enforce the rest, and names the unmeasured set
beside them.

## The finding: `-0`

**The two engines' JSON parsers disagree about what "parsed" means.** CPython's
`json` reads the literal `-0` as the **integer** `0`; `serde_json` reads it as
the **float** `-0.0`. Reproduction:

```console
$ python3 -c "import json; v=json.loads('-0'); print(repr(v), type(v).__name__)"
0 int
$ # serde_json: `-0` arrives at `visit_f64(-0.0)`, never at `visit_i64`
```

Found by the canonical-form torture fixture on its first run — it carried a
`negative_zero` member, and the Rust side refused a document the reference had
already hashed.

**Recorded as a finding, resolved by defining the contract — not by bending
either engine.** The reference is not changed; the port is not taught to
"agree"; no golden is regenerated. The canonical **domain** is narrowed to
exclude `-0`, because a canonical form that hashed it would assert *"both
engines saw the same document"* while the two engines held different values —
which is the exact lie this surface exists to prevent. Reconciling instead of
refusing would have meant picking one parser's reading and calling the other
wrong, which is a contract decision this checkpoint has no standing to take.

It costs the contract nothing: `spec/OwnIR.md` §4.2 already bounds every
validated coordinate to signed 64 bits, and no `OwnIR` producer emits `-0`
(measured: no document in any corpus contains one, a float, or an exponent).

The consequence is architectural rather than cosmetic. The disagreement is
**invisible after parsing** on the reference side — by then `-0` is already
`0` — so the domain has to be enforced where each engine can still see the
*literal*: `load_document` through `json`'s `parse_int`/`parse_float`/
`parse_constant` hooks on one side, the typed value's `Deserialize` on the
other. Both are backed by an executable `domain_refusals` ledger: six
documents that **both** engines must refuse, each with the reason and the
substring its refusal must carry. The day either engine starts accepting one,
its suite goes red demanding a decision.

`NaN`/`Infinity`/`-Infinity` fall under the same rule and are in the ledger:
CPython accepts them as an extension, `serde_json` rejects them as invalid
JSON, so the two engines do not agree that such a document parses at all.

### A declared boundary beside it

Nesting depth. The two parsers cap recursion differently (CPython's
interpreter limit; `serde_json`'s 128). The canonical form does not attempt to
unify them. `spec/OwnIR.md` §4.2 bounds a conforming document at 32 nested
bodies and 128 raw levels, which sits inside both caps, so no conforming
document reaches the difference — recorded rather than claimed away.

## The decisions this checkpoint took, and why

- **The canonical form is over the PARSED document, not the file's bytes.**
  Whitespace, key order and a parser-resolved duplicate key are insignificant
  text formatting; a change to any parsed value is not. Two files that parse to
  the same document are the same input, and the hash says so. Duplicate keys
  follow the reference exactly — last value wins, first position kept — and
  both sides implement that, because the canonical form is only meaningful if
  the two parsers agree about what parsing means.
- **The domain is closed and refuses rather than rounds.** Object, array,
  string, `i64` integer, bool, null. On the Rust side this is enforced *by the
  type* (there is no float variant), which makes `canonical_bytes` total; on
  the Python side it is a run-time check, because `json` has no such type. One
  contract, two enforcement points — and the two say *which one fired*, which
  turned out to be load-bearing (see Method).
- **The artifact embeds its input.** It reproduces without the corpus it came
  from, and the recomputed hash is what makes the embedded copy trustworthy.
- **`engines` and `layers` are ordered ARRAYS over frozen vocabularies.** Key
  order is not a sound carrier of semantic order for a byte-exact
  cross-language contract — the same decision the Layer 2 handle array took,
  for the same reason. The layer order is the *pipeline* order, which is what a
  first-divergence reduction will walk.
- **One layer envelope for all three layers.** `{layer, surface_version,
  status, document | error}`. A surface that encodes its own refusal as
  `{"error": …}` has it **lifted** into the envelope's status; a produced
  document is carried **verbatim**, duplicate `*_version` included, because
  lifting is what lets a *refused* layer still name the surface it refused on.
  `summaries` has no surface version of its own, so its `surface_version` is
  `null` — absence is data.
- **One door for all three layers: the tolerant one.** A reproduction artifact
  must describe what the layers did with *one and the same* input; mixing the
  strict and tolerant doors across layers would mean the three entries no
  longer describe one capture. Strict-door behaviour is Layer 1's own family.
- **No engine build identity.** The artifact names *which* engine, never which
  build of it: a git SHA would make an artifact non-reproducible from the same
  inputs, and every surface it carries is already versioned. A boundary, not
  an oversight.
- **Goldens for a curated set, properties over the whole corpus.** Every
  artifact embeds its input plus three layer documents that already live in the
  tree, so committing 80 of them would triple the corpus to prove nothing the
  curated set does not. Determinism, byte-exact round-trip, self-verification
  and tamper refusal run over **all 80**; the goldens pin the *format* on 8.
- **A new dependency, deliberately.** `sha2` (RustCrypto) enters a
  deliberately lean workspace, used by `own-shadow` alone. The reference side
  is `hashlib.sha256`; hand-rolling a digest in a crate that denies
  `arithmetic_side_effects` and `indexing_slicing` would have traded an audited
  implementation for a page of justified suppressions. No core crate depends
  on it.

## Method: the campaign is data, and the census is generated

Two pieces of tooling landed with this checkpoint because the discipline
already demanded them and prose was standing in:

- **`scripts/mutate_campaign.py`.** A campaign is a definition file (each
  mutation an exact text edit to a **production** file) plus a recorded result
  (per mutation, which layers failed). Both layers run for every mutation —
  rule 3, no fail-fast. The definition is checkable **without running
  anything**: every edit's anchor must still occur exactly once in its target,
  so a campaign whose code has moved is a red build rather than a quiet
  fiction. The recorded result's internal consistency is gated too, because a
  file written by a script is still a file somebody can edit.
- **`scripts/render_checkpoint_status.py`.** The census is rendered from
  committed evidence, and `tests/test_generated_docs.py` makes a stale copy a
  red build. The generator deliberately does **not** invent the divergence
  counters: it states that they are enforced by a gate, names the gates (read
  out of the Rust test source, so a renamed test makes the census stale), and
  names the unmeasured set. A counter the generator could not have computed
  would be the same hand-typed claim in a new place.

### Mutation campaign — three rounds

Definition: `p022-shadow-infra-checkpoint1-data/mutations.json`. Result:
`.../campaign.json`. `M00` is the harness-honesty control.

**Round 1 — 30 mutations, 27 caught, 3 survivors.** M05, M06 and M07 each
deleted the *literal-level* domain check (the i64 bound, the float refusal, the
non-finite refusal) and the suite stayed green: the **value-level backstop**
refused the same documents, and the controls only asked *that* something
refused. That is P-022 discipline 2's failure mode exactly — "a test can
exercise a private copy of the logic and pass while the public path rots".

Fixed by making the two enforcement points **distinguishable** and pinning
each control to the one it claims to protect: a literal-level refusal now
names "the integer/float/non-finite literal", a value-level one names the path
it walked to, and the ledger's needles were tightened accordingly.

**Round 2 — a harness defect, not a result.** Every row from M15 on reported
`python::artifact-golden` as a catcher, including fifteen **Rust-only**
mutations, which is impossible. Cause: M15 changes `indent=2` to `indent=4` —
the same file **size**. CPython validates a `.pyc` against the source's integer
mtime and size, so restoring the original left the *mutated* bytecode in place
and every later row measured the leftover. The runner now invalidates cached
bytecode on every write and runs the layers with `PYTHONDONTWRITEBYTECODE=1`.

This is the third time a campaign in this project has had to fix its own
harness before its numbers meant anything (cp1's `git checkout` restore, cp4's
split streams, this). The lesson is recorded in the script rather than in a
note, so the next campaign inherits it.

**Round 3 — 30 mutations, 30 caught, 0 survivors**, control clean, and no
Rust-only mutation attributed to a Python catcher. **15** mutations have
exactly one catching layer; a rule with a single catcher is a rule with a
single control, and the census lists them by id.

## What checkpoint 2 needs

The remaining row-7a checkpoints, in order, each with its own evidence, commit
and status row:

| # | deliverable | what it adds |
|---|---|---|
| 2 | the **engine protocol** | the port fills its own `engines[]` entry through a shared protocol, so an artifact carries two captures instead of one. The format already has the slot and the vocabulary |
| 3 | the **`AnalysisTrace` schema** (#269) + **stable-ID normalization** | so a comparison does not break on insignificant order or on internal identifiers |
| 4 | **first-divergence reduction** over the *lowered* and *MOS* layers | naming the layer, the case and the minimal difference; proven against a synthetic divergence introduced into a copy of a Layer 2 golden, and silent on unchanged data |

And the wording discipline that comes with all of them: what this checkpoint
proved is "80 documents share one canonical identity across two engines, and
8 reproduction artifacts round-trip byte-for-byte" — never "shadow mode", and
never "parity".
