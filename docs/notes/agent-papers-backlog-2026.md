# Agent-papers backlog (Sandboy / policy slice) — digest reconciliation, not commitments

Working notes reconciling an external digest of
`github.com/VoltAgent/awesome-ai-agent-papers` (filtered by a third party for
what could feed `007` / Own.NET / Sandboy) against where this branch already
stands. Same shape as
[`research-landscape-2026.md`](research-landscape-2026.md): digest → where
we're already ahead → what's genuinely new, recorded **not scheduled**. The
scope here is the Sandboy/policy slice specifically (the analyzer-core slice
lives in `research-landscape-2026.md` already).

## Already decided or built — do not re-propose

| Idea from the digest | Status here | Where |
| --- | --- | --- |
| `owen.policy.toml` as single source of truth, ignore-files as generated compat artifacts | already fully designed (Phase 1, **not built yet**, but the design is done — the digest's proposal *is* this note's origin) | [`agent-capability-layer.md`](agent-capability-layer.md) §3 |
| Sandboy as OS-level isolation; reject WASM/Wasmtime as the agent's cage | ADR **accepted**, MVP spiked (Landlock + seccomp, unprivileged wrap-the-child) | [`sandboy-isolation-adr.md`](sandboy-isolation-adr.md); code at `sandboy/` (`policy.rs`, `policy.example.toml`) |
| Raw→SARIF adapters as capability-scoped WASM components (fuel/epoch/mem limits, provenance) | already built, not a proposal | `audit/adapters/adapters.toml` (`fuel = 2_000_000_000`, `epoch_ms = 5_000`, `max_bytes = 64 MiB` per tool) + `own-adapter-host` |

The digest's own framing for these three ("policy compiler", "OS-level not
WASM-cage", "WASM only for pure SARIF adapters") is *identical* to decisions
already on record here — `agent-capability-layer.md` even names its own
origin as "an external proposal... critiqued and landed against what already
exists in this branch." Filing it again would just duplicate existing docs.

One small new sliver on top of the adapter work, worth a line but not a
mechanism change: an **adversarial-input hardening corpus** for the adapter
host's parsers (raw tool output is semi-trusted input the same way
`extract_json_array` is in `007`). Nobody has built this yet. Attach it to
`audit/adapters/` when that subtree next gets fuzz/property-test attention —
same ROI ordering `007/docs/verification.md` already used for its own
untrusted-input parsers, not a new idea.

## Genuinely new items (recorded, not scheduled, deliberately not a `P-NNN`)

Per this repo's own placement discipline (`sandboy-isolation-adr.md` §8: "in
`docs/proposals/` — not filed on purpose"), cross-cutting exploratory notes
stay in `docs/notes/` until a concrete pain drives them into the numbered
track.

### 1. AST-derived evidence graph (the "reliable Graph-RAG" angle)

Source: the "Reliable Graph-RAG for Codebases: AST-Derived Graphs vs
LLM-Extracted Knowledge Graphs" corner of the digest.

Why this fits Own.NET specifically, rather than being a generic RAG bolt-on:
the deterministic Roslyn/OwnIR extractor (P-001, P-014, P-016) already
computes exactly the facts a graph would need — symbol resolution,
ownership/lifetime ordering, subscription/dispose pairing. This would be an
**export** of already-derived facts into a queryable graph shape, not a new
extraction pipeline.

Discipline it must inherit from `research-landscape-2026.md`'s "the LLM
layer" section: the LLM **queries** the graph; it never builds or edits it.
An LLM-extracted graph is exactly the "trusted-base you can't locally
re-check" failure mode that note already rejected for spec-mining — the same
argument applies verbatim to graph construction, not just to spec inference.

Sketch (illustrative, not a spec):

```
python -m ownlang graph corpus/wpf/... --out .own/graph.json
python -m ownlang explain OWN014 --evidence-graph .own/graph.json
```

Open questions before this is worth a numbered proposal: is `.own/graph.json`
a new artifact, or just a serialization of data structures OwnIR already
builds in memory per run; incremental-invalidation cost on re-analysis; and
whether any current diagnostic actually needs cross-file graph traversal
today, or whether P-014's existing semantic resolution already covers the
cases that matter (the survey's own conclusion was "finish the line you're
on" — this should clear that bar before it's scheduled).

### 2. Claim-level evidence card per diagnostic (JADE-style)

Source: the JADE / fine-grained-knowledge-verification-in-RAG corner of the
digest — decompose a claim, check each part against evidence.

Not net-new machinery: this formalizes what already exists informally as the
oracle's agree / own-only / oracle-only evidence buckets
([`oracle.md`](oracle.md)) and the OWN014-style lifetime-order reasoning, into
a structured `evidence: [...]` array per finding.

Sketch:

```json
{
  "diagnostic": "OWN014",
  "claim": "CustomerViewModel is promoted to App lifetime",
  "evidence": [
    {"kind": "lifetime_order", "fact": "ViewModel < Window < App"},
    {"kind": "subscription", "source": "bus", "source_lifetime": "App"},
    {"kind": "missing_release", "path": "..."}
  ],
  "source_span": "CustomerViewModel.cs:15:23"
}
```

Fits naturally as SARIF `relatedLocations` / custom properties rather than a
parallel report format — the SARIF pipeline (`audit/`) already exists; this
would extend it, not fork it. If the evidence graph (§1) is ever built, this
becomes "render one node's justification path"; it needs no new artifact on
its own and could be built first, independently, if it's ever worth doing.

## What we deliberately do NOT take

Mirrors the digest's own exclusion list, and matches this repo's existing
stance (`research-landscape-2026.md`): RL training of agents, long-running
self-evolving multi-agent colonies, GUI/mobile agent training,
social-simulation and medical-workflow agent papers, "agents autonomously
open PRs." None of these touch Own.NET's actual scope — a deterministic
checker plus a narrow LLM-as-falsifiable-assistant, never LLM-as-source-of-truth.

## Bottom line

Everything above is filed as reading, not a roadmap change. The
Sandboy/policy items were already fully reconciled in
`agent-capability-layer.md` and `sandboy-isolation-adr.md` before this digest
arrived; this note's only new contribution is the evidence-graph and
claim-card sketches, both deliberately left un-numbered until a concrete pain
— not a paper title — drives them into `docs/proposals/`.
