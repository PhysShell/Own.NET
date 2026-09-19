# `corpus/p037-mutation` — the A2.2-5 mutation campaign against the completeness oracle

P-037 A2.2-5. A2.2-4 built an independent completeness oracle
(`frontend/roslyn/OwnSharp.Oracle`, driver `scripts/p037_completeness_oracle.py`)
and A2.2-4R repaired the six findings it raised. This campaign asks the one
question left about the control itself: **can it still catch those defects, and
does it read the meaning of a call site rather than its spelling?**

`manifest.json` and `sources/` are written by
`python scripts/p037_mutation_campaign.py generate` and never edited by hand;
`report.json` is recorded by `python scripts/p037_mutation_campaign.py run --record`
for one manifest and one production tree (both digests are in the report) and
must be re-recorded when either moves. `tests/test_p037_mutation_campaign.py`
holds all three to each other without dotnet; the campaign itself runs in CI
beside the oracle (`run` without `--record` re-runs everything and demands the
recorded report, provenance excepted).

## The rule

A mutant is **killed** only when it stays valid C#, the extractor runs to
completion, and the oracle (or the frozen-vocabulary infrastructure) raises
exactly the RED / mismatch preregistered for it in `manifest.json`. A build
failure, a compile error, an extractor crash, an oracle crash or an unrelated
check failing is a **forbidden kill reason**: it fails the whole campaign and
never counts as a catch. Any analyzer looks excellent against a deleted
semicolon; that is mutation vandalism, not mutation testing.

## Three surfaces

**Source metamorphs** (`surface: source`, expected `green`). A base program under
`sources/` and a frozen rewrite of it; the base and the mutant are each run
through the extractor and the oracle, held to their own designed
classification, and then to a contract on the facts themselves:

| id | operator | rewrite | obligations |
|---|---|---|---|
| M1-remove-handle | REMOVE_HANDLE | `Sink(r, true)` → `Sink(Stream.Null, true); r.Dispose();` | the record stays in its carrier; the `Sink` fact (`var r` at ordinal 0, the `true` literal at ordinal 1) disappears; no stale `var(r)` anywhere |
| M2-add-parentheses | ADD_PARENTHESES | `Sink(r, true)` → `Sink((((r))), true)` | same symbol, ordinal, representation, callee / sig / call_kind; the fact is equal modulo its source coordinate; the oracle's occurrence is equal |
| M3-perturb-binding-named | PERTURB_BINDING | `Take(first: r, second: q)` → `Take(second: r, first: q)` | `r` moves to ordinal 1 and `q` to ordinal 0, by declared parameter, never by source position |
| M3-perturb-binding-params | PERTURB_BINDING | `TakeP(r, q)` → `TakeP(q, r)`, `TakeP(Stream first, params Stream[] rest)` | `q` becomes the `var` at ordinal 0 and `r` the opaque expanded-params slot at ordinal 1 (the R2 machinery under perturbation) |
| M4-distinguish-nested | DISTINGUISH_NESTED | `Use(r)` → `Use(Wrap(r))` | the inner `Wrap` captures `var r` at ordinal 0, the outer occurrence reads `nested_call_result`, and no fact at `Use` carries `var(r)` |

**Producer regression mutants** (`surface: producer`, expected `killed`). Five
compile-valid reversions of the A2.2-4R repairs, each an exact `find` /
`replace` on `frontend/roslyn/OwnSharp.Extractor/Program.cs` whose anchor must
occur exactly once (a moved anchor fails the campaign: a patch that matches
nothing mutates nothing). The patch is applied to a **copy** of the extractor
project in a temporary directory and built there; the production tree is never
written. Each mutant is run over the inputs it names and must produce exactly
the preregistered RED map, the kinds the findings ledger pinned before the
repair, on the witnesses the repair left behind:

| id | reverts | expected kill |
|---|---|---|
| K-SHADOW | A2.2-4R1, the sidecar's handle lookup by symbol | `fact_binds_other_symbol` on the three `shadow-*` witnesses |
| K-PARAMS | A2.2-4R2, the expanded-params element recovery | `occurrence_not_captured` under parentheses and `!`, `fact_without_relevant_occurrence` under boxing and `op_Implicit` |
| K-COND-RECV | A2.2-4R3, the receiver under `?.` | `occurrence_not_captured` on `ext-conditional-access` |
| K-CTORINIT | A2.2-4R5, the `constructor_initializer` fact | `occurrence_not_captured` on two hostile witnesses, the probe row `CtorInit` and the shape `sidecar-ctorinit-base` (the initializer's nested calls are still walked, so `ctorinit-nested-call` stays green) |
| K-MEMBER | A2.2-4R6, the guarded-only member enumeration | `occurrence_not_captured` on the six `member-*` witnesses, the probe helper `Box.op_Implicit` and the two `orphan-*` shapes |

**A taxonomy contract mutant** (`surface: taxonomy`, expected `unclassified`).
`predicate_result` is removed from a copy of the registry. The freeze test,
the hostile-census test and the oracle driver (its check
`oracle-exclusions-frozen[*]`, added for this) must each go red *as
unclassified*, naming the removed exclusion, and nothing else may fail: the
shape keeps its occurrences and loses its name, and no infrastructure folds it
into a neighbouring name. A future `other_expression` bucket dies here.

## Acceptance

The campaign is accepted only as a whole: every declared mutant exercised
exactly once; every C# mutant compiles; every source metamorph green under its
designs and obligations; every producer mutant killed by exactly its
preregistered RED map; the taxonomy mutant unclassified; no survivor; no
unexpected kill reason; the production tree byte-identical afterwards (digests
of the extractor, the oracle and the registry, and `git status`, before and
after); the ordinary oracle RED-free on every campaign input; no open finding
in the ledger. `report.json` records each mutant's outcome and evidence, no
path and no time, so a re-run must reproduce it byte for byte.

## What this does not claim

The campaign proves the control catches the six defects it once found and reads
four metamorphic rewrites by meaning. It does not enumerate the extractor's
other seams, the hostile census remains pairwise rather than exhaustive, and
lambdas / local functions stay the separate nested-function gap.
