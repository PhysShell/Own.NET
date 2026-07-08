# P-033 — In-process sketches and bitmap indexes for legacy .NET diagnostics

- **Status:** draft. Imported from a design discussion and normalized into the
  proposal series (the pasted original suggested the then-taken number P-028).
  Note on scope: the subject is **not** the OwnLang analyzer itself but the
  legacy .NET Framework / WPF desktop application the audit targets (see
  [`audit/README.md`](../../audit/README.md)). The proposed module would ship
  as instrumentation guidance for audited legacy apps — e.g. alongside the
  runtime harnesses in [`audit/runtime/`](../../audit/runtime/README.md) — not
  as part of the analyzer.

## Summary

The legacy .NET application under audit (the WPF/.NET Framework desktop app targeted by `audit/README.md`) should gain a small, dependency-light module for compact runtime diagnostics and fast set operations using classic probabilistic and compressed data structures:

- bitsets / roaring-style bitmap indexes;
- Top-K / heavy-hitter counters;
- Count-Min Sketch for approximate frequencies;
- t-digest or DDSketch-style latency summaries;
- optional Bloom/Cuckoo filters for import and lookup pre-checks;
- optional SimHash for grouping similar errors.

The goal is not to turn a legacy desktop .NET application into a fake distributed analytics platform. That would be architecture cosplay, and nobody needs that circus. The goal is narrower: improve local diagnostics, filtering, dirty tracking, and performance visibility without requiring Redis, Valkey, Kafka, or some other infrastructure animal.

## Problem

The legacy .NET application under audit has several known pain points:

- large legacy WPF/.NET Framework surface;
- heavy dictionaries and reference data;
- expensive recalculation paths;
- memory-sensitive UI workflows;
- difficult-to-debug performance spikes;
- repeated validation and import scenarios;
- need for better local evidence before changing architecture.

Current code can observe some issues, but it likely lacks compact, queryable runtime summaries:

- which operations are actually slow at p95/p99;
- which validations fail most often;
- which dictionary/reference entries are hot;
- which rows/documents are affected by a recalculation;
- which errors are effectively the same root cause;
- which imports contain duplicates or obviously invalid references.

Without compact summaries, developers either over-log, under-measure, or guess. Guessing is not engineering. It is astrology with stack traces.

## Proposed solution

Add an internal module to the audited application, tentatively named
`Own.Diagnostics.Sketches`.

The module should expose simple interfaces, not leak implementation details into business logic.

Example conceptual interfaces:

```csharp
public interface ILatencySketch
{
    void Record(long elapsedMilliseconds);
    LatencySnapshot Snapshot();
}

public interface IHeavyHitters<T>
{
    void Add(T item, long weight = 1);
    IReadOnlyList<HeavyHittersEntry<T>> Top(int count);
}

public interface IApproxFrequency<T>
{
    void Add(T item, long count = 1);
    long Estimate(T item);
}

public interface IBitmapIndex
{
    void Add(int id);
    void Remove(int id);
    bool Contains(int id);
    // Non-mutating: each set operation returns a new index; the receiver
    // and `other` are never modified (no aliasing surprises for callers).
    IBitmapIndex And(IBitmapIndex other);
    IBitmapIndex Or(IBitmapIndex other);
    IBitmapIndex Except(IBitmapIndex other);
}
```

The first implementation may be deliberately boring:

- `BitArray` / custom packed bitset for dense ids;
- `HashSet<int>` fallback for sparse ids;
- simple Space-Saving Top-K;
- simple Count-Min Sketch;
- latency sketch adapter with an initially simple histogram implementation.

The point is to introduce the model safely before chasing cleverness. Cleverness without containment is how a “small optimization” becomes a haunted subsystem.

## Candidate use cases

### 1. Dirty tracking and affected-row calculation

Use bitmap indexes to represent sets such as:

- rows with validation errors;
- rows affected by changed customs rate;
- rows requiring recalculation;
- rows visible after current filter;
- rows already processed;
- rows excluded by user action.

Instead of scanning large collections repeatedly, compute set operations:

```text
RowsToRecalculate =
    AffectedByRateChange
    AND CurrentDeclarationRows
    AND NOT AlreadyRecalculated
```

This is especially suitable when ids are stable integer indexes within a document/import/session.

### 2. Validation and import diagnostics

Use Top-K and Count-Min Sketch to track:

- most frequent validation errors;
- most frequent invalid TNVED codes;
- most frequent import normalization problems;
- most frequently missing reference data;
- most common user correction patterns.

This helps answer:

Which 20 validation problems actually hurt users most?

Not “which validation problems look important in a meeting”, because apparently humans needed a database to learn humility.

### 3. Performance telemetry

Use latency sketches to record p50/p90/p95/p99 for operations such as:

- opening large WPF forms;
- loading reference dictionaries;
- graph 47 recalculation;
- report generation;
- import parsing;
- SQL query wrappers;
- UI filtering.

The output should be local and cheap:

```text
Operation: LoadTnvedTree
Count: 143
p50: 120 ms
p95: 2.4 s
p99: 8.1 s
Max: 9.6 s
```

Average latency alone should be treated as suspicious. Averages hide pain like a rug hides broken glass.

### 4. Error grouping

Use SimHash-like fingerprints to group similar:

- exception messages;
- stack traces;
- validation failure clusters;
- SQL error patterns.

This can later connect to the existing idea of error ids, hidden stack traces, and build-aware deobfuscation.

## Scope

### MVP

The MVP should include:

1. `ILatencySketch`
2. `IHeavyHitters<T>`
3. `IBitmapIndex`
4. one local diagnostic sink:
   - JSON file;
   - text report;
   - or debug window export.
5. instrumentation examples for 2–3 real operations.

Suggested first targets:

- dictionary/reference loading;
- graph 47 recalculation;
- validation/import flow.

### Phase 2

Add:

- Count-Min Sketch;
- Bloom filter for import pre-checks;
- SimHash grouping;
- optional compact binary export;
- analyzer/test coverage for misuse.

### Phase 3

Integrate with OwnAudit or 007 by exporting normalized evidence
(OwnAudit's `docs/sketch-based-evidence.md` already anticipates ingesting
these runtime diagnostic exports; the 007-side run evidence is specified in
007's `docs/sketch-aware-evidence.md`):

```json
{
  "schema": "own.sketches.v1",
  "source": "own.diagnostics.sketches",
  "operation": "LoadTnvedTree",
  "latency": {
    "p50_ms": 120,
    "p95_ms": 2400,
    "p99_ms": 8100
  },
  "top_errors": [],
  "affected_sets": []
}
```

## Non-goals

This proposal explicitly does not include:

- adding Redis/Valkey as a runtime dependency;
- replacing SQL Server;
- changing business rules;
- introducing approximate answers into critical legal/business decisions;
- using Bloom/HLL/Count-Min for authorization, licensing, billing, or correctness checks;
- rewriting existing WPF flows around sketches.

Approximate structures may support diagnostics and optimization. They must not become the source of truth for business decisions. Works fine?! A cart with three wheels “works fine” too.

## Safety rules

1. Every approximate structure must expose its error model in docs.
2. Approximate values must be named as estimates.
3. Exact fallback must exist where correctness matters.
4. Sketches must be resettable and exportable.
5. No global mutable singleton dumping random metrics from everywhere.
6. No business logic may depend on false-positive behavior.

## Acceptance criteria

The proposal is successful when:

- a developer can instrument an operation in fewer than 10 lines;
- bitmap indexes can represent affected row sets and combine them efficiently;
- p95/p99 latency is visible for selected operations;
- Top-K diagnostics identify frequent validation/import issues;
- exported evidence can be consumed later by OwnAudit;
- no new infrastructure is required;
- no correctness-sensitive path relies only on probabilistic results.

## Expected benefit

The audited legacy application gets a practical local observability and set-processing layer:

- fewer full scans;
- better dirty tracking;
- better recalculation targeting;
- better import diagnostics;
- clearer performance evidence;
- less guessing before refactoring.

This is not highload cosplay. It is a small internal toolbox for making the old codebase confess where it hurts.
