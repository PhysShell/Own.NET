# P-002 — Verification backend (Boogie / Dafny)

- **Status:** draft (horizon — not a near-term commitment)
- **Depends on:** `spec/OwnCore.md` (the soundness theorem to discharge)

## Motivation

Today soundness is **argued and tested**, not proven: the property fuzzer + an
independent AST oracle + the spec conformance suite give strong empirical
confidence (the theory advisor's "Level 1"). The honest next rung is exporting
the core soundness obligation to an SMT-backed verifier so we can say more than
"this Python didn't lie on today's random draws".

The theorem (from `spec/OwnCore.md §6`):

> If a program is well-typed and the ownership check passes, then it cannot:
> use-after-release, double-release, release-while-borrowed, move-while-borrowed,
> or escape a stack-backed resource.

## Scope

- **Level 2 (target):** translate per-function proof obligations to **Boogie**
  (→ Z3) — e.g. "at this `release`, no loan of `R` is active and `R` is OWNED".
  Boogie is the right backend: it is the intermediate verification language Dafny
  itself lowers to, and it maps cleanly onto our CFG + state lattice.
- **Level 3 (stretch):** a **Dafny** model of OwnCore semantics, with the rules
  as lemmas.

## Non-goals

- Proving the C# **codegen** correct (translation validation is a separate, harder
  problem; the `CodegenContract` + golden-compile cover it pragmatically).
- Proving anything about `unsafe` / interop.
- A Level-4 F\* mechanized soundness proof — interesting, far, and only worth it
  with a concrete consumer pulling for it.

## Sketch

OwnCore already produces exactly the shape Boogie wants: a CFG, per-variable
state sets, and active-loan sets with a join that is *asserted* identical across
predecessors. A backend would emit, per block, `assert`/`assume` for the
permission each operation needs, and let Z3 discharge them.

```text
CFG + states + loans  --[obligation emitter]-->  program.bpl  --[Boogie/Z3]-->  verified | counterexample
```

## Open questions

1. Is empirical (fuzzer + conformance) confidence already "enough" for the PoC's
   audience? (Likely yes until a user demands formal proof — this stays a
   proposal until then.)
2. Boogie obligations per-function only, or whole-module?
3. How to keep the Boogie model and the Python checker in sync (shared spec rule
   IDs as the contract).
