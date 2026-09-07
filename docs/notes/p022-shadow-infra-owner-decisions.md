# P-022 step 7a (#260/#269) — owner decisions on the shadow-mode infrastructure slice

> Status: **infrastructure for shadow mode**. This file changes no code, no
> fixture and no measured number. It records three places where the slice
> departed from the brief it was given, and one boundary the slice did not
> state clearly enough — so that the departures are *decisions on the record*
> rather than a brief quietly re-read to match what was built.

Ratified by the repository owner at the review of
[#338](https://github.com/PhysShell/Own.NET/pull/338), 2026-09-06, on the tree
at `5286689`. Checkpoints 1–4 stay as they landed; their notes, campaigns and
recorded numbers are untouched.

## D-1 — capture and the reproduction format stay one checkpoint

**The brief said** five items, *each its own checkpoint with its own evidence,
its own commit and its own row*: (1) same-input capture with a canonical hash,
(2) the reproduction-artifact format, (3) the engine protocol, (4) the
`AnalysisTrace` and stable-ID normalization, (5) first-divergence reduction.

**What landed** is four checkpoints over five commits: items 1 and 2 are both
[checkpoint 1](p022-shadow-infra-checkpoint1.md).

**Decision: accepted, as an explicit deviation.** The two are one contract.
An artifact format without a document identity is a container carrying a claim
it cannot check — the format's central field *is* the hash, and the evidence
for either half (a byte-exact round-trip whose embedded document re-hashes to
the recorded digest) is a single indivisible check. Splitting them would have
produced a checkpoint whose only evidence was "the file parses".

What is **not** accepted is leaving this unstated. The published history is not
rewritten to renumber four checkpoints into five: the deviation is recorded
here, and row 7a and the checkpoint-1 note both point at this file. A brief
that says five and a tree that says four must disagree *in writing*.

## D-2 — the `-0` canonical-domain decision is the owner's, retrospectively

**The stop condition said**: if an engine divergence is discovered, stop and
report it; describe the fork with its options, but do not take the decision.

**What happened**: checkpoint 1 discovered a real divergence — CPython's `json`
reads the literal `-0` as the integer `0`, `serde_json` reads it as the float
`-0.0` — recorded it as a finding with a reproduction, and then **took the
contract decision itself**, narrowing the canonical domain to exclude `-0`.
The checkpoint note is candid to the point of self-indictment: it says
reconciling "is a contract decision this checkpoint has no standing to take",
in the same paragraph in which a contract decision is taken.

**Decision: the outcome is ratified; the process is corrected.** As of this
ledger the canonical domain's exclusion of `-0` is an **owner decision**, not a
checkpoint's. It stands because:

- Neither engine's semantics change. Nothing teaches CPython to hold a float or
  `serde_json` to hold an integer; the document is refused by **both**, at the
  literal, under the executable `domain_refusals` ledger.
- The alternative is worse than the refusal. A canonical form that hashed `-0`
  would assert *"both engines saw the same document"* while the two engines
  held different values — the precise lie the same-input surface exists to
  prevent.
- It costs the contract nothing. `spec/OwnIR.md` §4.2 already bounds every
  validated coordinate to signed 64 bits, and no document in any corpus
  contains `-0`, a float or an exponent.

The correction that matters for future slices: **discovering the divergence was
the trigger to stop.** The finding, the reproduction and the ledger were the
deliverable; the domain decision should have been proposed here and waited.

## D-3 — `sha2` is accepted, for `own-shadow` only

`sha2` (RustCrypto) enters a deliberately spare workspace and is used by
exactly one crate. **Accepted.** A hand-rolled SHA-256 inside a workspace that
denies `arithmetic_side_effects` and `indexing_slicing` would trade an audited
implementation for a page of justified suppressions and buy nothing.

The bound is the part to keep enforced, and it already is: `own-shadow` is
outside the semantic core, and `own-diagnostics/tests/dag.rs` asserts by name
that no core crate — `own-bridge` included — depends on it. If that test is
ever relaxed, this decision lapses with it.

## B-1 — the boundary this slice did not state: #260 wants *raw bytes*

This is the one that would have cost someone a week of commit archaeology, and
it is now stated in three places rather than none.

**#260's acceptance invariant is byte-level**: produce or load the `OwnIR`
document exactly once, hash the **raw bytes**, and feed *those exact bytes* to
both engines.

**What checkpoint 1 proves is one level up from that**: both engines derive the
same **canonical identity over the parsed document** — sorted keys, compact
separators, a closed value domain, SHA-256 over that form. Every one of the 80
documents is canonicalized and hashed by the reference and re-hashed by the
port, and the two agree.

That is the right thing to have built now, and the brief asked for exactly it.
But the two claims are not the same claim:

> **canonical-equivalent input ≠ byte-identical input.**

Two files differing in whitespace, in object key order, or in how a duplicate
key resolves can share one canonical identity. The canonical form is designed
to ignore those differences — that is its job — so it cannot also be the
evidence that they were absent.

**Consequence, and it is not optional at acceptance**: #260's same-input
invariant is **not proved by this slice**, and shadow-mode acceptance must
additionally prove that both engines consumed the identical captured byte
sequence. Until then, "same input" in this slice's vocabulary means *canonical
document identity*, and the phrase must not be read as the stronger invariant.

Now named in: the generated census's unmeasured set, `spec/Bridge.md` §6, and
P-022 row 7a.

## M-1 — merging #337: one mutation harness, not two

Recorded after the fact, because it changes shared infrastructure rather than
this slice alone. #337 landed on `main` while this branch was open, and the two
had independently added `scripts/mutate_campaign.py` and
`scripts/render_checkpoint_status.py`. Resolving that with "ours" or "theirs"
would have left the tree with two mutation harnesses drifting apart, so:

**#337's is the shared one, whole.** Its contract is strictly the better one —
schema-validated definitions, exactly-once regex anchors, per-mutation
`expected_catchers`, the `compile-error` / `invalid-mutation` / `runner-error`
vocabulary, the clean-tree contract, and provenance (definition sha256 plus the
commit the run was taken on, gated as an ancestor of HEAD). What this slice
needed went in as **generalizations of it**, not a second code path:

- `layers` — a campaign may declare explicit commands instead of a cargo
  workspace, because the shadow campaigns' catchers are a Python harness plus
  four cargo test targets. `workspace` is unchanged.
- Python-source hygiene — the `__pycache__` invalidation, now that the shared
  runner mutates `.py` files. #337's cargo-only campaigns never needed it.

The four shadow campaigns were **re-run**, not carried over: their old results
predate the provenance and required-catcher fields, so under the shared gate
they would not have been evidence. All 63 mutations still anchor; all 63 are
caught; no survivors.

Two defects surfaced during the merge, both by a gate rather than by review:

1. A `mypy --strict` rename (the shared file list holds these scripts to it)
   was left half-finished, and `plan.pop(name, None)` stopped removing the six
   domain-refusal controls from the capturable set. **The campaigns' honesty
   control refused to run over the resulting red baseline**, so nothing was
   recorded. Every positive check still passed; without the control this would
   have been recorded as evidence.
2. Two mutations declared a catcher by the old runner's name for "the Python
   layer failed without naming a check". They were still caught, and by that
   layer — but #337's expected-catchers rule reports a mutation caught only by
   something other than the test its definition names, which is exactly the
   difference between evidence and a green tick.

One fix was ported outward rather than left: `owen-cli-release.yml`'s
`build + test + pack` job runs the whole Python suite on a depth-1 checkout, so
the provenance gate cannot resolve the commit a recorded campaign names. #337
gave `ci.yml`'s tests job `fetch-depth: 0` for the same reason; that workflow
triggers on paths #337 never touched, so the gap stayed green there.

---

# The acceptance decisions (#260), ratified 2026-09-07

> These are the decisions #260's final acceptance was blocked on. They are
> recorded here **verbatim as ratified**, in the same ledger as the
> infrastructure slice's, because a decision an agent may not reopen has to be
> readable in one place. The work that lands them over the committed corpus is
> [`p022-shadow-acceptance.md`](p022-shadow-acceptance.md); the sweep #260 also
> asks for is not part of it.

## D-4 — verdict reduction scope

`REDUCTION_SCOPE` is identical to `LAYER_ORDER` on both sides — an alias in
Python, the same constant in Rust — never a third copy of the list.
`REDUCTION_VERSION` 1 → 2. `out_of_scope` stays in the schema and is empty.

## D-5 — acceptance classification

Observation *kind* and *acceptance judgement* are orthogonal fields on every
observation. `missing-layer` replaces `unexplained` as an observation **kind**.
Every content observation — `left-only`, `right-only`, `changed`,
`ordering-only`, on every layer including `summaries` — is
acceptance-`unexplained`. A `status` or `projection` observation is
`declared-boundary` **only** when its structured boundary class **and** its
(layer, kind) match an exact entry of a frozen boundary policy; the initial
policy contains only the OD-1 typed-door entries — `(lowered, status, OD-1)`,
`(summaries, status, OD-1)`, `(verdicts, status, OD-1)` — and nothing for
`projection`. A known class attached to the wrong kind or layer does not explain
it. The class is declared **by the refusing engine, structurally, in its
capture** (`boundary: {"class": ..., "detail": ...}` on the refused layer
record); the reducer copies it into the observation; `detail` never participates
in policy. No case-name matching, no error-text matching, anywhere.

## D-6 — SARIF

Canonical SARIF is a derived #260 zero-diff acceptance surface, **not** an
`AnalysisTrace` layer and not part of `LAYER_ORDER`. Each engine renders SARIF
from its **own** verdicts with one frozen, named render configuration:
`severity = "error"` (`ownlang.ownir.build_sarif(findings, "error")`,
`own_bridge::render::build_sarif(&findings, "error")`). Results: `equal`,
`renderer-only divergence` (verdict layers equal, SARIF differs),
`not-comparable` (a verdict layer differs or is refused). Digest and length are
always recorded; the full SARIF documents are retained only on mismatch.

## D-7 — verdict pairing

The BR-V8 address `file:line:column:code` is the verdict **pairing address**,
not object identity. Differences in other members are `changed` with a minimal
path. Duplicate-address ordinal semantics are frozen by an adversarial
cross-engine control: left `A~0 → message X, A~1 → message Y`, right
`A~0 → Y, A~1 → X` yields `changed` at `.message` on both addresses — never
`ordering-only`, because the ordinal is part of the address.

## B-2 — raw-input artifact

`REPRO_VERSION` 2 → **3** (2 already exists: it added `projection`). For
capturable valid OwnIR: `input.raw` carries the byte-exact input as base64 plus
`algorithm`, `digest`, `bytes`; each engine independently records
`consumed: {algorithm, digest, bytes}` of the bytes it actually consumed; both
`consumed` identities must equal `input.raw`; parsing `input.raw` must reproduce
the existing canonical identity (`input.canonical`); `input.document` remains.
Raw bytes are hashed **before** decoding or parsing. Malformed byte/JSON inputs
that cannot produce `input.document` are **negative compare-driver controls**,
not fabricated "normal" v3 artifacts.

## B-3 — migration

Every v3 `consumed` claim comes from an actual execution of that engine. No v2
foreign entry is promoted into v3 by assumption — the Python writer refuses to
carry an entry that lacks `consumed`. Canonical corpus digests
(`tests/fixtures/repro/digests.json`) remain unchanged.

## R-1 — compare runner

Add a dev-only binary `own-shadow-engine` in `own-shadow`: stdin = the captured
raw bytes; stdout = one machine-readable Rust engine capture; stderr =
diagnostics only; exit ≠ 0 = execution failure. No paths, no extraction, no
fallback, no config discovery, no user-facing CLI semantics. It is not
`own-cli` and creates no #261 cutover surface.

## R-2 — execution failure

Crash, timeout or non-zero exit is a **run-level hard failure**. It is never a
layer refusal and never causes a synthetic engine capture. Raw input, exit
information and stderr are retained in a **failure report**, not in a
reproduction artifact. `produced` / `refused` stay semantic layer statuses.

## What the acceptance work did with them, and where it stopped

Every one of the above is implemented over the **committed corpus** and no
further. The one place the decisions' own text met a measurement that did not
match it is recorded rather than smoothed: D-6 expects `not-comparable`
"exactly on the OD-1 documents", and the corpus has **two** shapes of it — the
OD-1 door's asymmetric refusal, and two documents where *both* engines refuse
the verdict layer for the same reason. The census says so.

The B-3 line "canonical corpus digests remain unchanged" holds for every digest
record. The file's own `repro_version` stamp follows the format to 3, because
both sides already ASSERT that stamp equals the emitter's version — leaving it
behind would be a red build rather than a preserved file.

## What the closure commit deliberately did not do

- **No code changes.** `ownlang/repro.py` and `rust/crates/own-shadow/` are
  untouched; so is every fixture, golden and recorded campaign result.
- **No campaign re-runs.** Every mutation anchors into `ownlang/repro.py` or
  `own-shadow/src/`, neither of which that commit edited, so the recorded
  results still described the tree they measured — and CI re-anchors each
  definition on every build (`tests/test_checkpoint_status.py`). A campaign is
  evidence about a tree, not a rite to be repeated whenever prose moves. (The
  *merge* is a different matter, and M-1 above says why the campaigns were
  re-run there: the harness itself changed.)
- **No history rewrite.** Four checkpoints, five commits, and D-1 above.

## One thing CI does not attest

`CodeRabbit` on #338 reports `success`, and its description says what that
success is: *"Review skipped: manual review required for this OSS repository"*
(the repository is under the star threshold for automatic review). There are no
submitted reviews on the pull request. A green line named after a review tool
is not a review, and this slice should never be quoted as having had one.
