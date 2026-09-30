# resource-effects — final record: EXPLICIT_MODELS_WIN (EXPLORATORY)

Research branch `research/resource-effects-v1` (from the frozen P-037-X head e05d98d0; that branch and
`main` at fb06adc2 are unchanged; no PR; no merge). Evidence in Own.NET-paperwork
`paper-eval/resource-effects/` (prereg first, manifest append-only, `final-v1.json` last). #304 open and
FROZEN, untouched; #382 open, untouched. Nothing here is a production result.

## The question and the answer

*Can Own.NET obtain trustworthy resource-effect specifications cheaply enough to remove real
frontend/API-model scope limits, without turning the analyzer into an API-name whitelist or a general
symbolic verifier?* — Yes for the two frozen real witnesses, and the cheapest trustworthy source is an
explicit two-row model with provenance. Wording: **resource-effect inference recovered 2 of the 3 frozen
real precision witnesses** (W4 at the verdict level; W2 at the selection level with verdict sensitivity,
which additionally needs the sub-stage 1b representation rule); W5 (record absence) did not move — the same
two under the answer key, under the key derived from the dependency source, and under the two-row pack.

## What was measured, stage by stage

- **Stage 0/prereg.** Both effect-blocked witnesses are blocked by exactly one EXTERNAL callable each; no
  frozen witness is first-party, so RQ-E2/E4 were narrowed to probes, controls and held-out before any code.
- **Stage 1 (answer key).** KILL GATE 1 not triggered. W4 recovered at the verdict level; W2 escaped
  through the tuple return until the 1b rule (+9 lines, opt-in, zero population cost). Identity key clean on
  H1–H4; the name-rule mutants fail on H1/H2/H4 (H3 not discriminating); H5 composes; H6 composes under 1b.
  No fact moved in the corpus, the tree or the 62 historical controls.
- **Stage 2A (CFG).** KILLED (K6): 0 of 14 shapes better than the syntax pipeline; SSA and a second graph
  needed where both fail.
- **Stage 2 (E1/E2).** s15 exactly as pre-registered; direct-return and wrapper factories fresh; only case 2
  moved in the population (a true fresh factory; the verdict is a dispose-optional type question); the
  corpus carries no shape to exercise the rules; 148 lines against a 120-line budget, recorded.
- **Stage 3 (E3 + suite).** 13 of 14 tests met, Python == Rust; T12 hits the spec's fail-closed cycle rule;
  M3/M5/M7 fail as required; M4 is inexpressible (aliasing holds by construction).
- **Stage 4.** The dependency source at 49e04fa, read through E1/E2/E3, derives the two rows with zero false
  rows and reproduces the answer-key facts and verdicts byte for byte. The two-row pack costs 0 lines.
  Documentation states one effect in prose; mining yields nothing; naming names both and four false ones;
  the LLM is right and unverifiable. The provenance gate holds; the M6 mutant shows it is load-bearing.
- **Stage 5 (held-out, frozen after Stage 1).** One true fresh row gained, no false row; three misses on an
  unresolved external type, one on a reflection escape, one on field adoption; receiver-release recall not
  measurable (K8 partial). No rule changed after the run.
- **Stage 6.** NC1 holds again on the six cases; W5 unchanged in every arm.
- **Stage 7.** The OwnTS emitter consumes the same key file under the same gate; 8 rows Python == Rust;
  core 0 changed lines; never TypeScript support.

## The decision (exactly one)

**EXPLICIT_MODELS_WIN.** Headroom is real, and the manual two-row pack is the cheapest arm that passes every
hostile control and the held-out gates. BOUNDED_AUTO_INFERENCE was not chosen because its definition
requires the budget (breached in Stage 2) and held-out rows (one). The secondary finding stands on its own:
the manual rows are derivable from the pinned dependency source through generic rules with zero false rows,
and the provenance gate makes any source safe to carry — a way to generate and review model packs, not a
reason to skip them.

Cost, whole track: extractor +267/−9, engines +50, OwnTS emitter +49/−4, probe +132 (not integrated),
tests +210, fixtures/keys +677; 0 OwnIR fields, 0 lattice values, 0 solver state, 0 CFG machinery
integrated; formal/, spec/, the owning-factory table, the release name set and the Tier B tables untouched.
Twelve correctness observations are recorded in `final-v1.json` item 25; none was fixed.
