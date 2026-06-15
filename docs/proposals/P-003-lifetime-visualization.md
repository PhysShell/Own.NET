# P-003 — Lifetime visualization (RustOwl-style)

- **Status:** draft (horizon)
- **Depends on:** `spec/OwnCore.md`, `spec/Lifetimes.md`

## Motivation

The most compelling existing ownership tools for Rust are *visual*: **RustOwl**
(in-editor ownership/loan highlighting), **RustViz** (timeline of ownership and
borrow events), **BORIS** (borrow visualizer). For .NET there is no equivalent.
A "who holds whom, who must release, and why this object doesn't die" picture is
exactly the killer demo for the business-lifetime story — far more persuasive
than a code listing.

## Scope

- A **lifetime graph** per function: owners, their loans (shared/mut) as spans,
  and `subscribe` edges, with the region-escape (OWN014) path highlighted
  ("expected: Window — actual: App — path: bus → self").
- A **timeline** per owned resource: acquire → borrows → move/release/escape.
- Output as text/ASCII first (cheap, CI-friendly), then SVG/DOT; IDE integration
  much later.

## Non-goals

A full IDE extension or LSP server in v0. Runtime heap-graph visualization
(that is a separate runtime-diagnostics track). Anything requiring a GUI toolkit.

## Sketch

All the data already exists: the CFG carries instructions with symbols, states,
and loans; the lifetime analysis carries regions and `subscribe` edges. A
visualizer is a *consumer* of these facts — no new analysis. Start by emitting
DOT from the CFG + lifetime facts.

```text
CFG + lifetime facts  --[graph/timeline emitter]-->  *.dot / ASCII timeline
```

## Open questions

1. ASCII-only (CI-renderable, in-repo) vs SVG/DOT (needs Graphviz) for v0.
2. Per-function graph vs whole-module lifetime graph.
3. Does this belong before or after P-001? (A visualization of hand-written
   `.own` is less compelling than one of *real* extracted C#, so likely after.)
