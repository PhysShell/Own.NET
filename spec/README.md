# OwnLang specification (`spec/`)

This directory is the **normative, descriptive** specification of OwnLang: what
the language *is today*, derived from the working checker and pinned by tests. It
is not a wish list. Anything not yet built lives in
[`docs/proposals/`](../docs/proposals/) instead — keeping the two apart is how we
stop aspirational docs from lying about the code.

| File | Covers |
|------|--------|
| [Grammar.md](Grammar.md) | the surface syntax: tokens, EBNF, construct→spec map |
| [OwnCore.md](OwnCore.md) | the affine-ownership + borrow-permission core: identity, states, loans, rules R1–R12, call boundary |
| [BufferPolicies.md](BufferPolicies.md) | storage policies (stack/scratch/pooled/native/inline), rules B1–B8, `policy` blocks |
| [Lifetimes.md](Lifetimes.md) | lifetime regions and the region-escape theorem, rules L1–L4 |
| [Diagnostics.md](Diagnostics.md) | every OWN code, grouped, linked to the rule that raises it |
| [CodegenContract.md](CodegenContract.md) | the checker↔codegen contract C1–C4, lowering modes |
| [OwnIR.md](OwnIR.md) | the frontend↔core fact seam (JSON): envelope, versioning + evolution policy, resource-kind + flow-op vocabulary, DI graph, rules IR1–IR6 |
| [ownir.schema.json](ownir.schema.json) | the machine-readable OwnIR schema (JSON Schema 2020-12) — the single source the Python core and the Rust `own-ir` crate are checked against; its enums are pinned to the code's authoritative sets by `tests/test_ownir.py` |
| [CLI.md](CLI.md) | the `check` / `emit` / `cfg` / `report` commands |

## Spec ↔ tests (conformance)

Each normative rule is backed by an executable example, so the spec and the
checker cannot silently drift:

- `tests/test_spec.py` — one canonical program per normative rule
  (OwnCore R1–R12/S8, Lifetimes L1–L3, Buffer B1/B4/B8, structural), asserting
  the rule's code fires. ~21 distinct codes pinned; the rest (maybe-variants,
  buffer specifics) are covered by the suites below.
- `tests/test_gallery.py`, `tests/test_lifetimes.py`, `tests/test_wpf.py`,
  `tests/test_corpus.py` — broader pinned examples.

A spec change without a matching test change (or vice-versa) is a red build. To
add a rule: write it here with an ID, add its example to `test_spec.py`, and add
the code to `Diagnostics.md`.

## Reading order

Start with [OwnCore.md](OwnCore.md). Buffers and lifetimes layer on top of it and
reuse its identity/states/loans machinery.
