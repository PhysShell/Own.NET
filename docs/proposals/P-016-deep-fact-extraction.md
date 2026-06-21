# P-016 — Deep C# fact extraction: CFG + flow lowering

- **Status:** draft (P1 — the "make the core actually bite real C#" track). **B0a
  done** (direct `Module`, no re-parse). **B0b+B2 spike landed** (experimental
  `--flow-locals`): real C# → CFG flow facts → core → path-sensitive OWN001/002/003
  on local IDisposables — proven on `samples/FlowLocalsSample.cs`, run clean over
  GTM. **GTM findings triaged:** 9 real leaks the flat name-based detector misses
  (UnitOfWork, `System.Threading.Timer`, StreamReader/Writer) + 14 dispose-optional
  FPs (Task/DataTable) now excluded by a CA2000-style exemption → 100% precision on
  the sample. The own-check wrappers (`own-check.ps1`/`.sh`) now **default to
  `--flow-locals`** (`-Legacy`/`--legacy` opts back to the flat detector); the raw
  extractor flag stays default-off pending an `OWNIR_VERSION` bump. **A1 (core loop
  support) landed:** `while` is analysed with a worklist+fixpoint over the back-edge
  (cross-iteration leak / use-after-release / double-release), replacing the single
  topological pass; `for`/`loop`/async stay `OWN020`. Pinned by `tests/test_loops.py`
  + gallery `10_leak_in_loop.own`. **A1 reached the frontend:** the flow extractor now
  lowers `while` and `foreach` bodies to a `while` back-edge flow op (0+ iterations,
  opaque condition) instead of skipping the whole method — so loopy C# is analysed
  end-to-end (cross-iteration leak/double-release through the bridge). `for` (can
  declare a resource in its initializer) and `do` (runs 1+ times) still bail honestly.
  Pinned by `samples/FlowLocalsSample.cs` (`whileLeak`/`foreachLeak`/`whileClean`) +
  `tests/fixtures/ownir/flow_while.facts.json`. Next: `for`/`foreach`-with-disposable-
  iterator lowering, escape-via-projection hardening, then full graduation.
- **Depends on:**
  - [P-014](P-014-semantic-resolution.md) Tier A — the `SemanticModel` (**DONE**).
    The hard prerequisite: typed ownership facts are impossible without binding.
  - [P-001](P-001-csharp-extractor.md) — the extractor → OwnIR → core seam, and the
    `ownir_version` contract.
  - [P-005](P-005-idisposable-ownership.md) — the first deep profile this unlocks
    (IDisposable acquire/release on all paths); [P-004](P-004-wpf-lifetime-profile.md)
    (lifetime), [P-007](P-007-arraypool-span.md) (borrow/Span).
  - `spec/OwnCore.md`, `spec/Lifetimes.md` — the fact vocabulary the core *already*
    checks (acquire / move / borrow / use / release / escape / control-flow).
- **Strategy hub:** [`docs/ROADMAP.md`](../ROADMAP.md).

## Motivation

The core (`ownlang`) is a sound, tested, flow-sensitive ownership / borrow /
lifetime checker — **but only on the `.own` DSL.** On real C#, the Roslyn frontend
feeds it a *flat list of pattern-matched resource facts* (`event +=`, IDisposable
field, pool, local-disposable). None of the core's deep machinery —
release-on-all-paths across branches, use-after-release, double-release, move,
borrow aliasing, lifetime ordering — is exercised on real code. The engine runs;
the fuel line to real C# is a trickle. Two concrete gaps:

1. **The frontend emits no control flow and no per-statement operations.** It does
   not lower real method bodies into acquire / use / release / move / borrow over a
   CFG, so OWN001/002/003/005/… never fire on real C# beyond the shallow patterns.
2. **The core does not model loops.** `cfg.py`: *"There are no loops, so the CFG is
   a DAG and a single topological pass suffices — this is exactly where loop support
   (worklist + fixpoint) would later plug in."* `OWN020` marks loops/async
   unsupported. Real C# is full of loops.

P-014 Tier A removed the hard prerequisite (the frontend now has a `SemanticModel`).
This proposal is the plan to feed the *existing* core real facts — a CFG plus
acquire/use/release/move/borrow — from real C#, **one fact-type per increment**,
plus the core loop support that lets those facts be checked on real (loopy) methods.

This is the honest answer to "does Own.NET work, or only on paper?": prove one real
flow-sensitive verdict on real C# end-to-end. If the thin vertical slice (B0+B2
below) lights up a true OWN001 on GTM, the concept is proven; if it proves
intractable, far better to learn that now than after more breadth.

## Dependencies — what we depend on to start

| # | Dependency | Status |
|---|------------|--------|
| 1 | Types in the frontend (no typed ownership facts without binding) | ✅ **DONE — P-014 Tier A `SemanticModel`** |
| 2 | A control-flow graph from real C# | Roslyn `ControlFlowGraph` / `IOperation` exists — needs lowering |
| 3 | OwnIR (and the bridge) able to carry per-method operations + a CFG | schema growth — see **B0** |
| 4 | The core handles loops | ❌ missing (`OWN020`); worklist + fixpoint — the set-of-states lattice is finite & union-merged, so it converges — see **A1** |
| 5 | An honest-skip path for shapes we cannot model (async, exotic flow) | ✅ already the project's philosophy |

Replace the "single topological pass" with a worklist, and the flat fact list with
a CFG-carrying bridge, and the existing core checks real code.

## Scope — the increments (two tracks that meet at the rich-fact bridge)

### Track A — core only (pure DSL, no frontend, `.own`-tested)

- **A1 — Loops. ✅ DONE.** Replaced the single topological pass over the DAG
  (`cfg.py`, `analysis.py`) with a worklist + fixpoint over back-edges. The lattice
  is the finite set-of-states (OwnCore §3, union at merges) → monotone → it converges
  (widening was **not** needed — the per-symbol lattice has height 4). `while` lowers
  to a header block with a back-edge from the body exit; diagnostics are emitted in a
  second pass on the converged in-states (never during fixpoint iteration). Removed
  the `OWN020` "loops" clause for `while` (`for`/`loop`/async still `OWN020`). Fully
  independent of the frontend; pinned by `tests/test_loops.py` (cross-iteration
  OWN001/003/009) + gallery `10_leak_in_loop.own`. **Frontend follow-on landed:** the
  flow extractor (`LowerFlowStmt`) now lowers `while` and `foreach` bodies to a `while`
  back-edge flow op (both are the 0+-iteration, opaque-condition shape), and the bridge
  (`ownir._lower_flow`) maps it to the core `While` node — so loopy C# is analysed
  end-to-end instead of the whole method being skipped. `for`/`do` still bail honestly.
  Pinned by `FlowLocalsSample.cs` + `tests/fixtures/ownir/flow_while.facts.json`.

### Track B — frontend depth (needs the `SemanticModel`, now present)

- **B0 — Direct-Module bridge (and kill the double parse).** Two steps:
  - **B0a (refactor, no behavior change):** today the bridge lowers OwnIR facts to
    `.own` **source text** (`ownir.py` `to_own`) and the core **re-parses that text**
    (`__main__._collect` → `parse`) before checking — a parse of a tree we just
    built, a round-trip that has existed since P-001 and doubles the lowering work
    (every new fact must be expressible as, *and survive a round-trip through*,
    generated `.own` text). Replace it: build the core `Module` AST
    (`ast_nodes`) **directly** from facts and call `check_module` — no text, no
    re-parse. The seam is already split for this (`ownir.py`: *"builds a Module and
    calls `__main__.check_module` directly … the seam is already split so that
    switch is additive, not a rewrite"*). Pin against the existing fixtures: same
    findings, one fewer parse.
  - **B0b (enabler):** extend OwnIR — and the direct `Module` construction — to carry
    per-method **basic blocks + acquire / use / release / move / borrow / return**
    operations: the schema the deep checks need. Bumps `OWNIR_VERSION` (a new fact
    *category*, NOT additive like P-014's OWN050; the version gate already forces the
    extractor and core to move together).
- **B1 / B2 — IDisposable flow for locals.** Lower a method's `new` / `using` /
  `.Dispose()` / `return` into acquire / release / escape over a Roslyn CFG → real
  **OWN001** (leaked on an exception/early-return path), **OWN002** (use after
  dispose), **OWN003** (double dispose) on live C#. The IDisposable story (P-005) —
  the most common .NET resource bug, and the first time the core's flow analysis
  bites real code. B2 (`using`/try-finally → scoped release) is the smallest first
  slice; do it before the general case.
- **B3 — Move / ownership transfer.** `return disposable`, or passing it to a callee
  that consumes it → move / escape (P-005 D5). Intraprocedural, driven by declared
  signatures, not whole-program tracing. *Landed (consume handoff):* a call to a
  first-party consumer — a method that disposes a by-value `IDisposable` parameter
  **directly, or by forwarding it to another first-party consumer** (the transitive
  chain, `ConsumesParam`) — releases the argument at the call site, so a use after the
  handoff trips OWN002 (`corpus/real-world/ownership-handoff-use{,-transitive}`). The
  signal is each callee's own body, so it is inter-procedural without a signature table.
- **B4 — Borrow / Span.** `Rent` → view → `Return`, `Span`/`ref` aliasing (P-007) —
  the borrow checker's crown jewel, hardest on C# (ref structs, Span lifetimes).
- **B5 — Lifetime ordering.** WPF005 escape (`OWN014`) and DI captive (P-006,
  partly built) — the hardest; needs an explicit lifetime model.

**Dependency order:** `B0 → B1 → B3 → B4 / B5`. `A1` is independent but needed for
B1 to cover loopy methods — until A1 lands, a method containing a loop is honestly
skipped (`OWN020`), not guessed. B0+B2 and A1 can proceed in parallel.

## Non-goals

- A full C# semantic front-end. We lower the operations the core already models, not
  the language. `async`/`await` stays an honest skip (`OWN020`) until a real bug
  demands it; whole-program/interprocedural analysis beyond signature-declared
  transfer; the XAML/binding engine. The "refuse the soul-eating version" rule holds.
- Rewriting the core. A1 *extends* the existing flow engine (worklist) — it does not
  replace the lattice. B0–B5 only feed the core; they decide no verdicts.

## Sketch

```text
            A1: worklist+fixpoint (loops)  ─────────────┐
                                                        v
real *.cs ─[Roslyn CFG + IOperation]─[B1..B5: acquire/use/release/move/borrow]
          ─[B0b: per-method ops+blocks OwnIR]─[B0a: build Module directly]
          ─[the one core]──> OWN001/002/003/005/014 @ the C# line
```

## Relationship to the spec & docs (anti-drift)

- **`spec/` core semantics: unchanged by Track B.** The core already models
  acquire/borrow/move/lifetime for `.own`; B0–B5 *feed* it those facts from C#, they
  do not change what it means. **A1 does change the core** (it analyses loops): when
  it lands, `spec/OwnCore.md`'s "loops out of scope" (§10) and the `OWN020`
  loops clause are updated to describe the worklist — spec follows code.
- **OwnIR contract:** B0b **bumps `OWNIR_VERSION`** — rich per-method facts are a new
  category, not an additive optional field (contrast P-014's OWN050, which did not
  bump). The load-time version gate already makes a mismatched extractor/core fail
  loudly, so the bump is safe by construction.
- **No new diagnostic codes** — B1–B5 reuse the existing OWN001/002/003/005/008/014.
  The only catalogue change is *removing* the loops clause from OWN020 when A1 ships.
- **"One checker" preserved:** B0a removes a parse, not a decider; the core remains
  the single source of truth.

## Open questions

1. **B0b schema shape.** Grow the OwnIR JSON with a per-function ops+blocks array
   the bridge maps to a `Module`, or have the extractor emit a serialized `Module`
   directly? (Lean: ops+blocks JSON — keeps the extractor decider-free.)
2. **try-finally / `using` modeling.** Map to a "release on all paths" region, or to
   explicit release on each CFG exit edge?
3. **How much of Roslyn's `ControlFlowGraph` to consume** (its basic blocks + the
   operations we map) vs build our own CFG from syntax. (Lean: consume Roslyn's — it
   already normalizes `using`/`try`/short-circuits.)
4. **Loop fixpoint:** does the finite set-of-states lattice converge fast enough
   as-is, or is widening warranted on pathological back-edges? (Likely converges.)
5. **Honest-skip granularity:** on an unsupported construct, skip the whole method,
   or analyse the modelable prefix and skip the rest? (Conservative: skip the method,
   emit `OWN020` once.)
6. **Which slice proves the concept fastest** — B0a+B2 on loop-free methods is the
   proposed existential spike; confirm it surfaces a real OWN001 on GTM before
   investing in B3–B5.
