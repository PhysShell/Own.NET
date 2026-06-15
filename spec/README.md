# OwnLang specification (`spec/`)

This directory is the **normative, descriptive** specification of OwnLang: what
the language *is today*, derived from the working checker and pinned by tests. It
is not a wish list. Anything not yet built lives in
[`docs/proposals/`](../docs/proposals/) instead — keeping the two apart is how we
stop aspirational docs from lying about the code.

| File | Covers |
|------|--------|
| [OwnCore.md](OwnCore.md) | the affine-ownership + borrow-permission core: identity, states, loans, rules R1–R12, call boundary |
| [BufferPolicies.md](BufferPolicies.md) | storage policies (stack/scratch/pooled/native/inline), rules B1–B7 |
| [Lifetimes.md](Lifetimes.md) | lifetime regions and the region-escape theorem, rules L1–L4 |
| [Diagnostics.md](Diagnostics.md) | every OWN code, grouped, linked to the rule that raises it |
| [CodegenContract.md](CodegenContract.md) | the checker↔codegen contract C1–C4, lowering modes |

## Spec ↔ tests (conformance)

Each normative rule is backed by an executable example, so the spec and the
checker cannot silently drift:

- `tests/test_spec.py` — one canonical program per OwnCore/Lifetimes rule,
  asserting the exact code. The conformance pilot.
- `tests/test_gallery.py`, `tests/test_lifetimes.py`, `tests/test_wpf.py`,
  `tests/test_corpus.py` — broader pinned examples.

A spec change without a matching test change (or vice-versa) is a red build. To
add a rule: write it here with an ID, add its example to `test_spec.py`, and add
the code to `Diagnostics.md`.

## Reading order

Start with [OwnCore.md](OwnCore.md). Buffers and lifetimes layer on top of it and
reuse its identity/states/loans machinery.
