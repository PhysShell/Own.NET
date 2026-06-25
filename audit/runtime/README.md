# Own.NET Audit — runtime layer (Plan.md §4)

The static layer answers "where might it hurt"; the runtime layer answers "where
does it *actually* hurt", and **confirms** static findings by observing the running
app. Its findings flow through the *same* `normalize → score → report` pipeline as
the static tiers (via `ingest.py`), so a runtime-confirmed leak in the same file as
a static finding clusters with it → **high confidence** (Plan.md §3.5).

This layer covers the categories static analysis honestly can't (Plan.md §2):
event/subscription & timer leaks confirmed under load (cat. 2/3), the
`DependencyPropertyDescriptor.AddValueChanged` leak (cat. 4), **PropertyChanged
storms** measured by raise-frequency (cat. 6), and the **duplicated-immutable-data**
detector — the project's "gold" (cat. 11). For these, the runtime layer is the *only*
tool, so they were `NO-TOOL` until now.

## Stack (Windows / build-required — Plan.md §4)

net472 / WPF / DevExpress precision beats fashion, so the stack is ETW + dump, not
the CoreCLR-only `dotnet-*` tools:

| Role | Tool |
|---|---|
| UI driver (deterministic scenarios, not clicks) | **FlaUI** (UIA3) |
| Scenario ↔ snapshot breadcrumbs + GC trigger | **SematixTrace** (diagnostic build) |
| GC / alloc / CPU / WPF-render telemetry | **PerfView** (ETW) |
| Heap snapshot / full dump | **procdump** (`-ma`) |
| Heap analysis (retained, duplicates, retention paths) | **ClrMD** |

## Layout

```text
audit/runtime/
  ingest.py            # runtime JSON -> SARIF -> the unified pipeline (PURE PYTHON, CI-gated)
  scenarios/
    open-close-declaration.yml   # one deterministic leak-harness scenario (+ schema docs)
  LeakHarness/         # C# leak-harness — Windows/build-required, NOT CI-gated
    LeakHarness.csproj # net472; FlaUI.UIA3 + Microsoft.Diagnostics.Runtime + YamlDotNet
    Program.cs         # GC+snapshot loop, growth assertion, JSON result
    Scenario.cs        # YAML model
    HeapCounter.cs     # procdump + ClrMD: count live instances of suspect types
  DuplicateDetector/   # C# duplicate-immutable detector — Windows/build-required, NOT CI-gated
    DuplicateDetector.csproj  # net472; Microsoft.Diagnostics.Runtime
    Program.cs         # ClrMD over a full dump: group identical strings, wasted-bytes findings
  PropertyChangedStorm/  # C# PropertyChanged-storm profiler — Windows/build-required, NOT CI-gated
    PropertyChangedStorm.csproj  # net472; Microsoft.Diagnostics.Tracing.TraceEvent
    Program.cs         # TraceEvent over an .etl: per-property raise frequency, storm findings
```

## How the leak-harness works (Plan.md §4.1)

Deterministic loop, run on the local Windows machine against the target:

1. Launch the target (FlaUI), run the scenario once to warm up (JIT + lazy caches),
   take the **baseline** retained-instance count of each suspect type.
2. Replay the scenario `iterations` times; each cycle requests a GC in the target
   (SematixTrace) and the loop ends with a **final** snapshot.
3. A suspect **leaks** when `(final − baseline) / iterations > threshold` — retained
   instances grow ~linearly with the open/close count. A clean loop is *not* a
   finding (it's evidence of no leak).

```bash
# on Windows, against a built/running target:
LeakHarness.exe --scenario audit/runtime/scenarios/open-close-declaration.yml \
    --procdump procdump.exe --out artifacts/own-audit/leak-harness.json \
    --target acme/LegacyApp --commit "$COMMIT"

# then, anywhere (this is what CI exercises):
python audit/runtime/ingest.py --leak-harness artifacts/own-audit/leak-harness.json \
    --out artifacts/own-audit/leak-harness.sarif
# -> drop leak-harness.sarif next to the static SARIFs; run_static aggregation
#    folds it in and a confirmed leak clusters with its static OWN014/OWN001.
```

## Duplicate-immutable detector (Plan.md §2 cat. 11 — the "gold")

A heap full of identical immutable values (the same `"Country"` / unit / currency
string held by thousands of separate instances) is wasted memory that interning, a
flyweight, or a reference-by-id would collapse. The detector walks a full dump with
ClrMD, groups strings by value, and reports each group whose duplicates waste more
than `--min-wasted-bytes`. (Strings first — the highest-value case; arbitrary
immutable types are a later refinement.) It needs no UI scenario — it's a one-shot
heap analysis.

```bash
# on Windows, against a dump (or a live --pid with --procdump):
DuplicateDetector.exe --dump target.dmp --min-wasted-bytes 65536 \
    --out artifacts/own-audit/duplicate-detector.json --target acme/LegacyApp --commit "$COMMIT"

# then, anywhere (CI exercises this conversion):
python audit/runtime/ingest.py --duplicate-detector artifacts/own-audit/duplicate-detector.json \
    --out artifacts/own-audit/duplicate-detector.sarif
# -> run_static folds duplicate-detector.sarif in as a category-11 (P2) finding set.
```

## PropertyChanged-storm profiler (Plan.md §2 cat. 6)

Frequency — not correctness — is a runtime property. The static `INPC0xx` tier (cat. 5)
catches a missing `nameof` or a broken arg; it cannot see that `Total` fires
PropertyChanged 4 000x for one keystroke, half of them with **no value change**,
thrashing every binding. The profiler reads an ETW trace (`.etl`) captured while a
FlaUI scenario drove the target — a diagnostic build emits one event per raise via an
EventSource (`OwnNet-Sematix-INPC` / `Raised`, payload `{Type, Property, ValueChanged,
[SourceFile, SourceLine]}`) — aggregates per (type, property), and reports each
property over its per-operation threshold. When the build resolved a source file, a
storm clusters with a static `INPC0xx` hit in the same file → **high confidence**
(§3.5); otherwise (file-only with no line, or no location at all) it gets a unique
`inpc://<type>/<NNNN>-<property>` synthetic uri — the `<NNNN>` index keeps distinct
storming properties in distinct clusters even when their slugs collide.

```bash
# on Windows, against an .etl captured during the scenario (PerfView / xperf / logman):
PropertyChangedStorm.exe --trace artifacts/own-audit/scenario.etl --operations 1 \
    --per-op-threshold 50 --out artifacts/own-audit/propertychanged-storm.json \
    --scenario open-declaration --target acme/LegacyApp --commit "$COMMIT"

# then, anywhere (CI exercises this conversion):
python audit/runtime/ingest.py --propertychanged-storm \
    artifacts/own-audit/propertychanged-storm.json \
    --out artifacts/own-audit/propertychanged-storm.sarif
# -> run_static folds propertychanged-storm.sarif in as a category-6 (P2) finding set;
#    a located storm clusters with a static INPC0xx in the same file.
```

## Selftest

`ingest.py` carries embedded-fixture selftests (no harness, no Windows needed) and
gates on Linux CI — including the end-to-end checks that a static OWN014 plus a
runtime leak (and a static `INPC0xx` plus a runtime storm) in the same file each form
one high-confidence cluster:

```bash
python audit/runtime/ingest.py --selftest
```

## Status

- **Done:** the runtime→pipeline bridge (`ingest.py`, CI-gated, for the leak-harness,
  the duplicate detector and the PropertyChanged-storm profiler), the leak-harness
  scenario schema + one scenario, runtime rule mappings in the taxonomy (categories
  2/3/4/6/11), the C# leak-harness skeleton, the C# duplicate-immutable detector
  (strings), and the C# PropertyChanged-storm profiler (ETW).
- **Deferred:** duplicate detection for arbitrary immutable types (field-by-field
  content equality), the diagnostic-build INPC `EventSource` instrumentation in the
  target + PerfView/SematixTrace capture wiring, and a scenario corpus for the top-N
  screens.
