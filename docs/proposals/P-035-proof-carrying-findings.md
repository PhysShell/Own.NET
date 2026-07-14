# P-035 — Proof-carrying findings and replayable derivation certificates

- **Status:** draft — design only; no certificate schema, verifier, or product claim
  described here is implemented yet.
- **Depends on:** canonical OwnIR/fact extraction, stable finding identities, ordered
  evidence/flow, and the existing Python ↔ Rust parity discipline.
- **First candidate consumer:** [`PRG001` / Own.Progress](https://github.com/PhysShell/Own.NET/issues/275),
  because its derivation can be kept deliberately small and path-shaped.
- **Companion consumer design:**
  [`PhysShell/OwnAudit/docs/proof-carrying-findings.md`](https://github.com/PhysShell/OwnAudit/blob/main/docs/proof-carrying-findings.md)
  after that document lands.

## Motivation

Own.NET findings already carry human-readable messages, source locations,
secondary evidence, and ordered flows suitable for SARIF `codeFlows`. That is
useful evidence, but it is still a presentation emitted by the same analyzer
that computed the verdict. A reviewer can inspect the path, yet must trust that
the core applied its transfer rules, summaries, joins, and conclusion rule
correctly.

For the most valuable deterministic findings, Own.NET should be able to emit a
small machine-readable derivation certificate alongside the ordinary finding.
A separate, deliberately boring verifier replays that derivation against the
canonical input facts and either accepts or rejects it.

The product claim is intentionally narrow:

> **Owen can attach an independently replayable derivation showing how a
> finding follows from the canonical facts it analyzed.**

This is not the claim that arbitrary C# semantics, CLR behavior, reflection,
source generators, weaving, or every frontend assumption has been formally
proved correct. The certificate starts at the canonical fact boundary. Calling
anything broader a proof would be marketing discovering modal logic and using
it for evil.

## Core shape

```text
C# / XAML / project inputs
        ↓
trusted frontend and canonicalization boundary
        ↓
canonical OwnIR / analysis facts
        ↓
untrusted inference engine proposes finding + certificate
        ↓
small independent verifier replays primitive rules
        ↓
verified derivation / invalid derivation / unsupported certificate
        ↓
normal human output: message, evidence, codeFlows, audit reports
```

The inference engine may remain complex, optimized, incremental, parallel, or
implemented twice. The verifier must not be. Its job is not to rediscover a
finding or run the analyzer again; its job is to check a finite derivation that
names every premise and rule application needed for the conclusion.

## Terminology

- **Fact:** canonical input accepted by the analysis boundary: CFG edge, guard,
  acquisition, release, call target, summary, lifetime ordering, and so on.
- **Finding:** the usual diagnostic conclusion (`OWN001`, `DI001`, `PRG001`, …).
- **Evidence:** locations and ordered flow shown to a human.
- **Certificate:** a machine-readable sequence or DAG of primitive derivation
  steps whose root is the finding conclusion.
- **Verifier/kernel:** the small implementation that validates every step and
  rejects unknown or malformed input.
- **Verified derivation:** a certificate accepted by the verifier against a
  specific canonical fact set and rule-vocabulary version.

A verified derivation is stronger than “the analyzer printed a plausible
trace”, but weaker than “the source program was formally verified”. The docs,
CLI, SARIF properties, and UI must preserve that distinction.

## Trust boundary

### Trusted for the claim

The initial trusted computing base is:

1. the canonical fact schema and normalization rules;
2. the frontend components that produce those facts from source inputs;
3. the certificate verifier;
4. the primitive rule specification consumed by that verifier;
5. the binding between the verified conclusion and the emitted finding.

### Not trusted for the claim

The main solver, summary inference implementation, worklist ordering, cache,
incremental engine, Python reference implementation, and Rust implementation do
not need to be trusted to *construct* a valid certificate. They may contain a
bug and propose nonsense; the verifier must reject the nonsense.

This does not eliminate all trust. It moves semantic trust out of a sprawling
analysis implementation into a smaller explicit boundary that can be audited,
fuzzed, differentially tested, and eventually formalized if that effort becomes
worth the oxygen.

## Certificate envelope (direction, not frozen schema)

```json
{
  "schema": "own/derivation/v1",
  "rule": "PRG001",
  "rule_vocab": "own.progress/v1",
  "facts_digest": "sha256:...",
  "conclusion": {
    "path": "Parser.cs",
    "anchor": "loop:Parser.ReadNodes:84",
    "measure": "local:reader.Position",
    "verdict": "reachable-backedge-without-progress"
  },
  "steps": [
    {
      "id": "s1",
      "rule": "FACT.LOOP_GUARD",
      "fact": "f-loop-84"
    },
    {
      "id": "s2",
      "rule": "SUMMARY.OUTCOME_PROGRESS",
      "fact": "f-call-tryreadnode",
      "outcome": "false",
      "progress": "never"
    },
    {
      "id": "s3",
      "rule": "CFG.BRANCH",
      "premises": ["s1", "s2"],
      "edge": "false -> continue"
    },
    {
      "id": "s4",
      "rule": "CFG.BACKEDGE_NO_EXIT",
      "premises": ["s3"],
      "edge": "continue -> loop-header"
    },
    {
      "id": "s5",
      "rule": "PRG001.INTRO",
      "premises": ["s1", "s4"],
      "measure_progress": "never"
    }
  ],
  "root": "s5"
}
```

The final schema must avoid unstable source-line identity and stringly-typed
symbol guessing. Facts, symbols, CFG nodes, summaries, and locations need
canonical handles. Human text is rendering metadata, never a proof premise.

The certificate binds to a digest of the exact normalized facts it was checked
against. A certificate copied to another run with different facts is invalid,
even when the source paths and messages happen to look similar.

## Primitive rule design

The verifier accepts only a closed, versioned vocabulary. Unknown rule kinds,
unknown discriminator values, duplicate step IDs, missing premises, cycles in a
supposedly acyclic certificate, mismatched fact digests, and malformed symbol
references fail loudly.

Rule families should stay small:

### Fact introduction

Turns a referenced canonical fact into a verifier judgment.

Examples:

- `FACT.CFG_EDGE`
- `FACT.LOOP_GUARD`
- `FACT.ACQUIRE`
- `FACT.RELEASE`
- `FACT.LIFETIME_ORDER`
- `FACT.CALL_TARGET`
- `FACT.SUMMARY`

### Structural reasoning

Checks local graph/path composition without executing the full analyzer.

Examples:

- `CFG.PATH_COMPOSE`
- `CFG.BRANCH`
- `CFG.BACKEDGE`
- `CFG.NO_EXIT_ON_PATH`
- `CFG.REACHABLE`

### Summary application

Applies a named, canonical method summary to an exact call target and outcome.

Examples:

- `SUMMARY.APPLY_EFFECT`
- `SUMMARY.OUTCOME_PROGRESS`
- `SUMMARY.OWNERSHIP_TRANSFER`

The verifier checks exact overload identity where `sig` exists and performs no
inventive fallback. Conservative fallback belongs to inference; a certificate
must name the precise premise that justified its conclusion.

### Domain conclusion rules

Each diagnostic family gets a tiny set of introduction rules.

Examples:

- `PRG001.INTRO`
- `OWN001.INTRO`
- `OWN014.INTRO`
- `DI001.INTRO`
- `OBL001.INTRO`

A conclusion rule should be boring enough to state in a few lines. If verifying
one finding requires embedding the entire analyzer as a “primitive” rule, the
certificate has failed as a design.

## First slice: `PRG001`

`Own.Progress` is a good first target because the useful proof object is already
a short ordered path:

```text
recognized loop guard
  -> reachable branch
  -> no progress on the controlling measure
  -> no break/return/throw
  -> back-edge
  -> PRG001
```

A minimal v1 vocabulary can therefore be limited to:

- recognized guard facts;
- canonical progress-measure identity and direction;
- local progress events;
- exact outcome-sensitive call summaries;
- CFG branch/path/back-edge composition;
- exit facts;
- `PRG001.INTRO`.

The first implementation must not generalize into arbitrary ranking functions,
symbolic termination proving, temporal logic, or a universal theorem-prover API.
One narrow certificate that reviewers can understand beats a majestic framework
that never reaches a finding.

## Verifier contract

The verifier must be:

- deterministic;
- side-effect free;
- total over accepted bounded input, or explicitly resource-bounded;
- independent from the inference entrypoint;
- free of plugins and user-provided executable rules;
- fail-closed on unknown vocabulary;
- able to return a structured rejection reason;
- versioned independently from the analyzer implementation;
- tested against corrupted and adversarial certificates.

Suggested result shape:

```json
{
  "status": "valid",
  "schema": "own/derivation/v1",
  "rule_vocab": "own.progress/v1",
  "root": "s5",
  "conclusion_digest": "sha256:..."
}
```

or:

```json
{
  "status": "invalid",
  "step": "s5",
  "reason": "PRG001.INTRO requires a reachable non-exit back-edge"
}
```

`unsupported-schema` must remain distinct from `invalid`. An older consumer may
not understand a new vocabulary; that is not evidence that the producer emitted
an internally false derivation.

## Relationship to evidence and SARIF

Certificates do not replace ordered evidence or `codeFlows`.

- **Certificate:** machine-checkable logical derivation.
- **Evidence/codeFlow:** reviewer-facing explanation and navigation.

They should be generated from the same canonical handles so drift is detectable.
A verified certificate whose displayed evidence omits or contradicts the
verified path is a presentation bug and should fail a test.

The ordinary finding remains useful when certificates are disabled or not yet
supported for that diagnostic family. The CLI and audit pipeline may display:

```text
derivation: verified
```

but must not silently turn “certificate absent” into “verified”. Expected states
are at least:

- `verified`;
- `invalid`;
- `unverified` (not requested or not emitted);
- `unsupported` (consumer does not understand the schema/vocabulary).

## Finding identity and determinism

The finding fingerprint must remain line-independent. The certificate may refer
to source locations for display, but its semantic conclusion identity should be
based on stable handles such as rule, symbol, resource/measure, method, and
canonical CFG identity.

Required laws:

```text
verify(facts, derive(facts)) = valid
verify(facts2, certificate_bound_to_facts1) = invalid  when digest differs
normalize(normalize(certificate)) = normalize(certificate)
reorder_independent_steps(certificate) preserves verdict
move_source_lines(finding) preserves semantic finding fingerprint
Python(facts).verified_conclusions = Rust(facts).verified_conclusions
```

The last equality is about accepted semantic conclusions, not necessarily byte-
identical construction order. Canonical serialization can be added if stable
byte-for-byte artifacts prove useful.

## Proposed implementation boundary

### Own.NET owns

- certificate and rule-vocabulary specifications;
- canonical handles needed by certificates;
- certificate construction in analysis implementations;
- the independent verifier;
- verifier conformance fixtures;
- negative/corruption tests;
- binding accepted derivations to canonical findings;
- Python/Rust parity for verified conclusions.

### OwnAudit owns

- transporting certificate artifacts without flattening them;
- recording verification state and verifier metadata;
- baseline/diff behavior for certificate-bearing findings;
- SARIF properties, report rendering, and dashboard affordances;
- refusing to present invalid certificates as verified;
- optional future correlation with runtime evidence.

OwnAudit must not implement a second certificate kernel or reconstruct proofs
from rendered evidence. One vocabulary, one verifier, many consumers.

## Delivery slices

### Slice 0 — specification checkpoint

- freeze terminology and trust claim;
- select canonical fact handles;
- define `own/derivation/v1` envelope;
- define `own.progress/v1` primitive rules;
- specify resource limits and rejection semantics;
- add hand-written valid and invalid fixtures.

### Slice 1 — standalone `PRG001` verifier

- implement verifier with no dependency on the main progress solver;
- verify hand-written fixtures;
- mutation-test every required premise and rule parameter;
- expose a CLI/dev entrypoint for replay.

### Slice 2 — producer integration

- make Python `Own.Progress` emit certificates;
- bind successful verification to emitted findings;
- make Rust emit semantically equivalent certificates or accepted conclusions;
- keep certificate generation optional until precision and artifact size are
  measured.

### Slice 3 — audit/report consumption

- preserve certificate and verification metadata through normalization;
- render `verified` state and a readable derivation tree;
- retain the existing ordered evidence path;
- add baseline and SARIF tests in OwnAudit.

### Slice 4 — second diagnostic family

Choose one existing high-value deterministic family (`OWN014`, `DI001`, or an
obligation rule) and test whether the primitive vocabulary composes without
turning into an analyzer-shaped kernel. This slice is the architecture test: a
second family must reuse primitives while adding only a small domain conclusion
surface.

## Acceptance contract

1. A valid hand-written `PRG001` certificate is accepted against its exact fact
   fixture.
2. Removing any required premise makes the certificate invalid.
3. Changing the facts digest makes the certificate invalid before rule replay.
4. Unknown schema, rule vocabulary, and rule kinds fail loudly with distinct
   structured outcomes.
5. A cycle in the derivation graph is rejected.
6. A certificate cannot assert reachability, exact call target, progress, exit,
   lifetime order, or ownership transfer without a matching canonical premise.
7. The verifier never calls the main solver or imports its transfer functions.
8. A finding is marked `verified` only after successful replay in the same run
   or by a consumer that records the verifier result.
9. Displayed evidence/codeFlow remains consistent with the canonical handles in
   the accepted certificate.
10. Python and Rust agree on the set of verified semantic conclusions for shared
    fixtures.
11. Verification is deterministic under input-map ordering and independent-step
    ordering.
12. Fuzzing/mutation tests cannot crash the verifier or make it accept malformed
    vocabulary.
13. Existing findings and reports remain unchanged when certificate emission is
    disabled.
14. Certificate size and replay cost are measured on a real corpus before any
    default-on decision.

## Non-goals

- formalizing the full C# or CLR semantics;
- proving the Roslyn frontend correct;
- replacing SARIF evidence and human explanations;
- accepting user-defined executable proof rules;
- running Lean, Agda, Coq, Dafny, or an SMT solver in the first slice;
- certifying heuristic/advisory findings as definite;
- making every diagnostic certificate-bearing at once;
- treating certificate absence as analyzer failure;
- turning the verifier into a second inference engine;
- using “formally proven bug” as product copy for a derivation that starts at
  extracted facts.

## Open questions

1. **Certificate shape: ordered list or DAG?** A DAG permits premise sharing and
   scales better across interprocedural conclusions; an ordered list is easier to
   inspect. Leaning: DAG with canonical topological serialization.
2. **Where does verification run?** Producer-side replay catches bugs early;
   consumer-side replay protects artifact transport. Leaning: support both, with
   producer result treated as metadata rather than authority.
3. **How are canonical CFG handles formed?** They must survive line movement and
   deterministic re-extraction without pretending control-flow identity is
   trivial.
4. **Are inferred summaries premises or subproofs?** MVP may treat a frozen
   summary artifact as a premise. Longer-term trust is stronger if summaries can
   carry their own derivations. Do not recursively swallow the whole roadmap in
   v1.
5. **One global rule vocabulary or per-analysis vocabularies?** Leaning: small
   shared structural core plus versioned domain vocabularies such as
   `own.progress/v1`.
6. **Verifier language:** Rust is attractive for a small distributable kernel;
   Python is attractive for first-spec iteration. The architecture matters more
   than the language: implementation must remain independent and tiny.
7. **Artifact retention:** inline certificate in canonical findings versus a
   content-addressed sidecar referenced by digest. Measure first; do not optimize
   imaginary terabytes.

## Inspiration and prior art

The immediate design inspiration is Jan Mas Rovira's post
[“An Agda eDSL for well-typed Hilbert style proofs”](https://blog.janmasrovira.org/blog/hilbert-edsl/):
a human-friendly proof language compiles to a smaller primitive proof object
checked by the host type system. Own.NET should borrow the architectural split,
not the Hilbert calculus or Agda syntax.

The trust warning comes from
[“Using dependent types to write proofs in Haskell”](https://blog.janmasrovira.org/blog/dependent-haskell-proofs/):
a well-typed non-terminating term is not a valid proof. For Own.NET, the analogous
lesson is that a verifier which can execute arbitrary recursion, plugins, or the
main analyzer is not a trustworthy kernel merely because its API says
`Verify`.

This proposal also complements, rather than replaces, P-002's future external
verification-backend direction. P-002 concerns exporting proof obligations to a
heavier verification system; P-035 concerns replayable certificates for concrete
findings in the analyzer's everyday pipeline.