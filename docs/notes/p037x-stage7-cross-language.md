# P-037-X Stage 7 — the six frozen TypeScript twins through the unchanged core (EXPLORATORY)

Research branch `research/p037-max-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/p037-max/stage7-cross-language-prereg-v1.json` (frozen before any TypeScript frontend
change); evidence in `paper-eval/p037-max/stage7-cross-language-v1.json`. Architecture evidence
only — never TypeScript support. #304 is frozen and unchanged.

## 1. Gate (REPOSITORY FACT)

Stage 7 runs "only if the core abstraction is stable": the kernel is untouched since Stage 2 and
Stages 2b–4 changed the driver, the seam and the frontends only. Stages 5 and 6 are not entered
by their own gates — Stage 4 revealed no transport need beyond the witness identity, and case 5's
timing witness sits behind a record absence (the iterator carries no record: R).

## 2. What was built (REPOSITORY FACT)

A twin-only OwnIR `functions[]` emitter for the OwnTS spike (`frontend/ownts/ownts_p037x.py`,
heuristic like the spike, no TypeScript parser), with the frozen rules: an interface with
`close(): void` / `dispose(): void` is a resource type; a `declare function` returning one is an
ambient factory (`acquire`); `r.close()` is a `release`; a statement-form call of an in-file
function that carries a handle is one canonical `call` op plus the sidecar record with the raw
argument facts by declared ordinal (var / param / param negated / bool_const / opaque);
`if (p)` / `if (!p)` on an own boolean parameter is a body `if` plus a sidecar guard; `return e;`
is a bare return; owned parameters carry their declared `ordinal` (R3), which `--no-ordinal`
omits. The six Group E twins are copied byte for byte under `corpus/p037x-controls/ownts/`
(sha256 asserted against the master prereg) next to the opaque-flag control. Zero core lines
changed; the Stage 4 binaries are the ones every document ran through.

## 3. Results (MEASURED OBSERVATION)

| document | legacy (Python == Rust off) | guarded (Rust on) | report | held |
|---|---|---|---|---|
| e1 guarded-release bug | `OWN051` | `OWN001` | `closeUnlessKept.r = split(1) [no, must]`; the site selects pos → borrow | yes |
| e2 guarded-release safe | `OWN051` | clean | the site selects neg → consume | yes |
| e3 wrapper-id bug | `OWN051` | `OWN001` | `outer.r` imports `inner`'s split through the id edge; pos → borrow | yes |
| e4 wrapper-id safe | `OWN051` | clean | neg → consume | yes |
| e5 wrapper-neg bug | `OWN051` | `OWN001` | `outer.r = split(1) [must, no]` through the neg edge; `false` → neg → borrow | yes |
| e6 wrapper-neg safe | `OWN051` | clean | `true` → pos → consume | yes |
| X7-C1 opaque flag | `OWN051` | `OWN051` | the site is unselected (the join), never a fabricated release | yes |
| X7-C2 no-ordinal facts | `OWN051` | `OWN051` | `NO_GUARDED_EVIDENCE(ordinal_map)`: the A17 allowlist knows C# type names only | yes |

Leaked assumptions found: the A17 ordinal allowlist (C# type names) — present in the driver,
neutralised by the R3 `params[].ordinal` fact (X7-C2 is the counterfactual: without the fact the
TypeScript document cannot be placed); the diagnostic wording (`IDisposable local 'r' is never
disposed` on a `.ts` file) — cosmetic; the `disposable` kind — a vocabulary word; `sig` and name
handling — inert on TypeScript spellings. Nothing semantic.

## 4. Cost and result

Frontend-specific: the emitter (241 handwritten Python lines (estimate +150..+260)) and the pin test; core lines
changed: 0; core reused: the Python reference, own-cli (door, bridge + seam, driver, kernel,
core) and the report, all unchanged. **KEEP**: the frozen §8 rows 1/7/8 guarded semantics
reproduce on TypeScript through the unchanged core, and the one C#-specific assumption the core
carries is bypassed by a fact the C# side already emits.

## 5. Not claimed

TypeScript support; that Stage 4's relational facts work on TypeScript (not emitted, not
exercised); that #304 is reopened.
