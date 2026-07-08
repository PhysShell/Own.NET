# P-029 — Agent memory & policy layer (`.agents/`)

- **Status:** draft — design only, no code/directory changes shipped by this
  proposal.
- **Depends on:** nothing structurally; it formalizes conventions already used
  elsewhere in this repo (see Sketch). Consumed by, but does not depend on, the
  reflect/learning-engine design in the sibling private repo `PhysShell/007`
  (`docs/reflect.md` there) — that engine is one possible *source* of
  promotions into the layer this proposal defines; a human editing `AGENTS.md`
  by hand is another, equally valid, source.

## Motivation

`AGENTS.md` today is one flat 18-line file covering core commands, the lint
gate, the pipeline shape, and a handful of hard rules (unknown-call handling,
`assert_never` dispatch sites, codegen modes, OwnIR versioning). That is
exactly the right size for what it covers today. The risk is what happens as
it grows: this repo already carries 25 proposals and 30+ design notes under
`docs/`, plus a second, much longer file
(`AGENTS.execution-surfaces.md`, 14KB) for a single ADR. Two failure modes are
already visible in miniature:

1. **One file bloats past readability.** An agent-guidance file that grows by
   accretion (one more bullet per lesson learned) turns into the "corporate
   Confluence after three reorgs" problem — long enough that neither a human
   nor an agent reliably reads all of it before acting.
2. **Guidance scatters undiscoverably.** `docs/notes/` already holds
   agent-relevant lessons (e.g. `docs/notes/field-notes-patterns.md`,
   `docs/notes/agent-capability-layer.md`) that a coding agent has no reason to
   load unless it happens to grep for them.

Separately, an external tool
([`claude-reflect`](https://github.com/BayramAnnakov/claude-reflect)) and the
sibling private harness `007` (which drives `claude`/`codex` over this repo
from the outside — see `007`'s own `README.md`) both converge on the same
idea: corrections and repeat-failure patterns from real agent runs should
become reviewed, persistent project memory rather than being re-learned every
session. `007` is explicitly the place that *mines* run records for candidate
learnings (`docs/reflect.md` in that repo) — it is private, and its own
`README.md` is explicit that harness-internal reasoning must never land in a
public tree. What this repo needs, independent of whether 007 ever ships that
engine, is: **a defined, reviewed, structured place those promotions — or a
human's own manual corrections — land in.** That is this proposal's entire
scope: the destination shape, not a detector.

## Scope

### The directory

```text
AGENTS.md                    # short index — points into .agents/*.md, nothing else
.agents/
  commands.md                # how to run check/emit/cfg/report, tests, lint — today's AGENTS.md body
  invariants.md               # hard rules: unknown-call handling, assert_never sites, OwnIR versioning
  gates.md                    # prose description of what CI/agents must run and why
  codegen.md                  # the two codegen modes; "do not add runtime released? flags"
  frontend-roslyn.md          # Roslyn extractor rules: bin/ refs, OWN050 advisory, facts-only boundary
.007/
  gate.toml                   # machine-readable mirror of gates.md — see below
```

`AGENTS.md` shrinks to an index in the same shape this repo already uses for
`docs/proposals/README.md` (a table of what exists and one line of status) and
`docs/ROADMAP.md` (a hub linking to satellite documents). This is not a new
idiom for the repo — it is applying the hub-and-satellite pattern the repo
already relies on to agent guidance specifically, instead of one growing file.

Each `.agents/*.md` file gets a soft line budget (~150 lines, the same
heuristic `claude-reflect` uses to warn on oversized memory files). Once a
file would cross that budget, it splits — same discipline that already
produced 25 separate proposals instead of one `PROPOSALS.md`.

### `.007/gate.toml`

This repo does not yet have a `.007/` directory. `007`'s `o7 run` already
looks for `<repo>/.007/gate.toml` by convention and ships a worked example at
`007/examples/gate.own.net.toml` (three steps: `ruff check .`, `mypy ownlang`,
`python tests/run_tests.py` — a direct read of the current `AGENTS.md` lint
and regression rules). Adopting it here means:

```toml
schema = 1

[[gate]]
name = "ruff"
cmd = "ruff check ."
required = true

[[gate]]
name = "mypy-ownlang"
cmd = "mypy ownlang"
required = true

[[gate]]
name = "regression"
cmd = "python tests/run_tests.py"
required = true
```

`gates.md` is then prose *about* this file (why each gate exists, what to run
when only touching a subset), not a competing source of truth — see the
open question on generation below.

### The promotion contract

Whatever proposes a change to `.agents/*.md` — a human noticing a repeat
correction, or an accepted candidate out of `007`'s (separate, private)
reflect queue — must arrive as an ordinary reviewed PR carrying:

- **the rule itself**, scoped to one `.agents/*.md` file and section;
- **provenance**: what motivated it (a run, a PR comment, a postmortem) —
  free text is enough, this is not a machine-checked field;
- **no bypass of normal review**. This repo does not gain a direct-write or
  auto-merge path for agent memory. A promotion patch is a diff like any
  other; it goes through the same PR process as this proposal itself.

## Non-goals

- **No detector/queue/regex-capture pipeline lives here.** Mining agent runs
  for candidate learnings is explicitly `007`'s concern (private, separate
  repo) or a human's own judgment — never a component added to this repo.
- **No live prompt-capture hook** (claude-reflect's `UserPromptSubmit`
  mechanism). This repo has no chat surface to hook, and does not gain one for
  this purpose.
- **No unreviewed auto-write.** Every change to `.agents/*.md` or
  `.007/gate.toml` is a normal, human-reviewed commit — the same bar as any
  other source change in this repo.
- **No cross-project memory.** `.agents/` describes this repo only; it is not
  a place to accumulate generic "how agents should behave" advice that belongs
  in a user's own global config.
- **No new rule DSL.** `.agents/*.md` is prose for humans and agents to read,
  same register as the existing `AGENTS.md`; `.007/gate.toml` is the one
  machine-readable artifact, and it already has an owner (`007`'s
  `GateManifest` parser) — this proposal does not invent a second one.
- **Not a replacement for `.cursor/rules` or `.roo/rules-*`.** Those already
  exist for tool-specific surfaces; this proposal does not touch them (see
  open question below on whether they should later generate *from*
  `.agents/`, not the reverse).

## Sketch

Today's `AGENTS.md` maps onto the split almost line-for-line, which is a good
sign the split is carving at a real joint rather than inventing one:

| Current `AGENTS.md` line | Destination |
| --- | --- |
| `python -m ownlang check\|emit\|cfg\|report` usage | `.agents/commands.md` |
| `tests/run_tests.py` / `test_codegen_props.py` invocation | `.agents/commands.md` |
| `ruff check .` + `mypy` gate | `.agents/gates.md` (+ `.007/gate.toml`) |
| Ruff SIM omission rationale | `.agents/gates.md` |
| Pipeline shape (parser → CFG → analyses → diagnostics) | `.agents/invariants.md` |
| Unknown-call hard-error rule | `.agents/invariants.md` |
| `assert_never` dispatch-site rule | `.agents/invariants.md` |
| Codegen's two modes / no runtime flags | `.agents/codegen.md` |
| OwnIR schema versioning rule | `.agents/invariants.md` |
| `own-check.sh`/`.ps1`, `--flow-locals` default | `.agents/frontend-roslyn.md` |
| Roslyn `bin/` refs / OWN050 | `.agents/frontend-roslyn.md` |
| `audit/` decoupling note | `.agents/invariants.md` (one line, pointer to `audit/README.md`) |
| CodeGraph MCP preference | `.agents/commands.md` |

`AGENTS.md` becomes:

```markdown
# AGENTS.md

Guidance for agents working in this repo. Start here, then follow a link:

| File | Covers |
|---|---|
| `.agents/commands.md` | How to run check/emit/cfg/report, tests, lint |
| `.agents/gates.md` | What must pass before a change lands, and why |
| `.agents/invariants.md` | Hard rules that must not be violated |
| `.agents/codegen.md` | Codegen modes and constraints |
| `.agents/frontend-roslyn.md` | Roslyn extractor rules and boundaries |
```

## Open questions

1. **Should `.agents/gates.md` be generated from `.007/gate.toml`, or hand
   written?** P-023 (`Own.Arch`) already rejects the "two parrots" pattern for
   C4 diagrams vs. `rules.yaml` — the same logic applies here: if `gates.md`
   drifts from what `gate.toml` actually runs, agents get told one thing and
   CI does another. Leaning: `gate.toml` is the source of truth; `gates.md`
   carries only the *why*, with a generated table of the *what* (name + cmd)
   checked in CI so drift fails loudly rather than rotting silently.
2. **Does the promotion contract need its own proposal**, or does it stay a
   section of this one? Leaning: stays here until there's a second consumer
   besides `007`'s reflect design — one contract, one place, until proven
   otherwise.
3. **Should `.cursor/rules/` and `.roo/rules-*/` eventually generate from
   `.agents/`** instead of maintaining separate tool-specific prose? Not in
   scope for this proposal's MVP, but the same "single source of truth, many
   renderers" instinct that shaped the `.007/gate.toml` question applies. Left
   for a later proposal once `.agents/` exists and the duplication is real
   (not hypothetical).
4. **Line-budget enforcement:** soft convention (reviewers watch for it) or a
   CI check (`wc -l` gate on `.agents/*.md`, matching the "warn past ~150
   lines" heuristic)? Leaning: start as a soft PR-review convention; only add
   a mechanical gate if bloat actually recurs — no gate for a problem that
   hasn't happened yet.
5. **Timing relative to `007`'s reflect engine:** this proposal's directory
   layout is useful on its own (splitting an already-growing `AGENTS.md`)
   regardless of whether `007`'s mining engine ever ships. It should not block
   on that design landing first.
