# Proposals (`docs/proposals/`)

**Forward-looking** design proposals for things OwnLang does *not* do yet. The
counterpart to [`spec/`](../../spec/): the spec is normative (what is true today,
pinned by tests); proposals are exploratory (options for tomorrow, no code
commitment). Keeping them apart stops aspirational docs from lying about the
code.

Each proposal is numbered `P-NNN` and has the same shape:

- **Status** — `draft` / `accepted` / `in progress` / `done` / `rejected`.
- **Motivation** — the real pain it solves.
- **Scope** and **Non-goals** — what it is *not* (the most important section; the
  whole project's discipline is refusing the soul-eating version).
- **Sketch** — enough design to judge feasibility, not a full spec.
- **Open questions** — what must be decided before building.

When a proposal is built, its behaviour moves into `spec/` (normative) and the
proposal is marked `done` with a pointer.

## Index

| # | Title | Status |
|---|-------|--------|
| [P-001](P-001-csharp-extractor.md) | C# → OwnIR extractor (the WPF leak spike) | draft |
| [P-002](P-002-verification-backend.md) | Verification backend (Boogie/Dafny) | draft |
| [P-003](P-003-lifetime-visualization.md) | Lifetime visualization (RustOwl-style) | draft |

## The long-term arc (one paragraph)

OwnLang today is a sound, tested resource/borrow/lifetime checker for a small
`.own` DSL that lowers to C# (see `spec/`). The arc from here:
**(1)** retro-document and pin behaviour with the spec ✅;
**(2)** ingest *real* C# via a narrow Roslyn extractor that emits OwnIR facts in
the spec's vocabulary (P-001) — the first time the tool bites real code;
**(3)** optionally export proof obligations to a verification backend for the
core soundness theorem (P-002);
**(4)** surface lifetimes/loans visually (P-003).
The core stays the same checker throughout; everything else produces or consumes
OwnIR facts. We resist the boil-the-ocean versions of each (full C# frontend,
proving all of unsafe, XAML engine) — boredom keeps projects alive.
