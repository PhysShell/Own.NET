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
| [P-001](P-001-csharp-extractor.md) | C# → OwnIR extractor (the WPF leak spike) | in progress (v0 built) |
| [P-002](P-002-verification-backend.md) | Verification backend (Boogie/Dafny) | draft |
| [P-003](P-003-lifetime-visualization.md) | Lifetime visualization (RustOwl-style) | draft |
| [P-004](P-004-wpf-lifetime-profile.md) | WPF / UI lifetime leak profile | draft |
| [P-005](P-005-idisposable-ownership.md) | `IDisposable` ownership profile | draft |
| [P-006](P-006-di-lifetimes.md) | DI lifetime / captive dependency | draft |
| [P-007](P-007-arraypool-span.md) | ArrayPool / Span borrow-view | draft |
| [P-008](P-008-effects-and-resources.md) | Effects & resources (`Own.Effects`) | draft |
| [P-009](P-009-nogc-regions.md) | No-GC / allocation-free regions | draft |
| [P-010](P-010-type-disciplines.md) | Richer type disciplines (`Own.Types`) | draft |
| [P-011](P-011-editor-tooling.md) | Editor tooling & syntax highlighting | draft |
| [P-012](P-012-bug-corpus-mining.md) | Real-world bug corpus & mining | draft |
| [P-013](P-013-distribution-surface.md) | Distribution surface (how people run Own.NET) | v0 built (CI/Action + dotnet tool) |
| [P-014](P-014-semantic-resolution.md) | Project-local semantic resolution (kills `+=` false positives) | draft (P0) |
| [P-015](P-015-configuration-surface.md) | Configuration surface (check selection & per-category severity) | draft (stub) |
| [P-016](P-016-deep-fact-extraction.md) | Deep C# fact extraction (CFG + flow lowering; loops) | draft |

> For priorities, milestones, the framing, and the design philosophy across all
> of these, see the strategy hub: [`docs/ROADMAP.md`](../ROADMAP.md). P-004 … P-016
> capture ideas raised in design discussion — they are *on the record for
> consideration*, drafts, not commitments.

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
