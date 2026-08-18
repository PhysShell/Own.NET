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
  RetentionPath/       # C# retention witness — net8.0, CROSS-PLATFORM, build smoked in CI
    RetentionPath.csproj      # net8.0; Microsoft.Diagnostics.Runtime (ClrMD 3.x) + Newtonsoft.Json
    Program.cs         # census / roots verbs, exit-code tiers, runtime.json writer
    Heap.cs            # mark-from-roots, BFS root->object paths with field names
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

## Retention paths — is it retained, and by whom (Plan.md §4)

The stack table above has promised *"Heap analysis (retained, duplicates, **retention
paths**) — ClrMD"* since Plan.md §4. `RetentionPath/` is that half. `HeapCounter`
counts instances of named types; this answers the two questions that actually decide
a leak hunt — *is any of it retained at all*, and *who is holding it*.

Unlike its three neighbours it is **net8.0 and cross-platform**, needs no procdump,
and can attach to a live PID. CI builds it and smokes its usage surface on every
push; the end-to-end demo runs on Linux and the WPF pair on Windows.

### `census` — is there anything to hunt?

```console
$ retention-path census --pid 1234 --out runtime.json

roots                :          308 objects
on the heap          :    4 270 155 objects          573 MB
REACHABLE from roots :    4 144 653 objects          403 MB
uncollected garbage  :      125 502 objects          170 MB
>>> 70,4% of the heap is genuinely RETAINED — something holds it; run `roots`
```

**This distinction is not pedantry.** `ClrHeap.EnumerateObjects()` walks the heap
segments linearly and returns *everything allocated, including garbage the GC has
not collected yet*. A big heap is not evidence of a leak. `HeapCounter` mitigates
that by forcing a GC in the target first, which works when you can drive the target;
marking from the roots answers it directly and needs no cooperation. If the retained
share is low, **stop** — there is no reference to hunt, and the next question is
about GC timing, not about who holds what.

### `roots` — what holds the TYPICAL instance

```console
$ retention-path roots --pid 1234 --type GTDGoody

verdict: RETAINED — BrokerDataClasses.GTDGoody: 130 000 on the heap, 129 903 reachable …

#1  25/50 resolved (50,0%) — via [static-event], 7 hops
    [PinnedHandle] System.Object[]
    BrokerDataClasses.GTD
    BrokerDataClasses.CalcProcentGTD  (.k__BackingField)
    BrokerDataClasses.GTDGoody  (.fMainObject)
```

The field names come from ClrMD's `EnumerateReferencesWithFields`; they are what turn
*"this object is alive"* into *"**this field** is holding it"* — the sentence a
developer can act on. A **delegate hop** in the path is what makes it a static
*event* rather than a plain static field, which is the distinction OwnAudit's
`correlate.py` keys its `high` tier on.

**Why it samples, and what the percentages mean.** *"Who holds this object"* is
ill-posed for an object reachable from many roots: there are as many answers as
there are paths, and the shortest is an arbitrary pick rather than an explanation.
So the walk resolves a SAMPLE of paths and ranks them as a histogram — the retainer
accounting for 129 900 of 130 000 is the leak; the three hanging off the stack are
noise. The shares are shares **of the resolved sample**, never of the population.
The verdict is not sampled: reachability and the durable/transient census run over
every instance, so no display budget (`--sample`, `--max-hops`) can change the
diagnosis or the exit code.

### What it does not do — read this before trusting it

- **No dominator tree.** The principled form of "who holds it" is dominance: which
  single reference, if cut, makes the object collectable, and how much that frees.
  It also answers honestly when two references hold an object jointly, naming the
  point where the paths meet instead of picking one. That is what Eclipse MAT and
  dotMemory are built on. The A3 witness was extracted from PR #280 **without** it,
  deliberately; Own.NET#334 records what the implementation argued. The sampled
  histogram is a weaker instrument, and the ranking is how it stays honest about it.
- **A `[stack]` root is not retention** — the object is live in a frame right now,
  and is labelled so it is not mistaken for a leak. Same for `[finalizer]`. A
  verdict of `RETAINED` requires at least one *durable* retainer.
- **It matches the type, not the type's spelling.** `--type GTDGoody` must not match
  `System.Func<…GTDGoody…>` — a cached lambda whose generic *argument* mentions it.
  It did, during development, and confidently reported a 2-hop path to the wrong
  object.
- **Attaching suspends the target.** On a multi-GB heap the mark pass is minutes,
  not seconds — take a dump.

### Exit codes, and why exit 2 exists

| Exit | Meaning |
| --- | --- |
| 0 | The heap was read. `ABSENT` / `OBSERVED_ONLY` — nothing durably retains the type. |
| 1 | The heap was read. `RETAINED` — a durable path exists, and it is printed. |
| 2 | **The heap was not read.** Usage error, unreadable target, refused attach. |

*Not looking* and *looking and finding nothing* are different outcomes, and
collapsing them is how a monitoring pipeline learns to report health it never
measured. Permissions, the Yama `ptrace_scope` cases and the CI rules are in
[`docs/runtime-witness-operations.md`](../../docs/runtime-witness-operations.md).

Output is the `runtime.json` contract (`OwnAudit/docs/runtime-contract.md`), so
`OwnAudit/runtime/correlate.py` consumes it with no adapter — giving the three-way
split its missing input: **confirmed** (a static leak finding whose type also shows
up retained), **static-only** (probable FP), and **runtime-only** — retention with
nothing static to explain it, which is a rule request rather than a report.

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
  (strings), the C# PropertyChanged-storm profiler (ETW), and the **retention
  witness** (`RetentionPath/`: census + ranked root paths, `runtime.json`, exit-code
  tiers, CI-gated build and demo).
- **Deferred:** the **dominator tree / retained sizes** for the retention witness
  (Own.NET#334 — the A3 extraction left it out on purpose; the sampled histogram is
  what ships), duplicate detection for arbitrary immutable types (field-by-field
  content equality), the diagnostic-build INPC `EventSource` instrumentation in the
  target + PerfView/SematixTrace capture wiring, and a scenario corpus for the top-N
  screens.
