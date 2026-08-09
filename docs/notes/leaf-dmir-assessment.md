# Leaf / DMIR — assessment against what OwnAudit actually has

Working note. **Trigger:** an outside reading of *"Leaf: An Instrumentation-based
Dynamic Analysis Framework for Rust"*
([arXiv:2607.15025](https://arxiv.org/abs/2607.15025), Omidvar Tehrani, Gaboardi,
Sumner, Ko) proposed it as "a concrete building block for OwnAudit" at 8.5/10,
with a separate Rust-analysis direction at 9/10, and listed five ideas to adopt.

The paper is real and summarised accurately: Leaf instruments **Rust MIR** via
`rustc` internals and delivers **DMIR**, an event-driven stream carrying static
MIR identity plus runtime facts, with a concolic executor / sanitizer / tracer
built on top. The architecture is genuinely good.

The proposal does not survive contact with the repositories. Recorded here so
nobody re-derives it — same purpose as
[P-034](../proposals/P-034-runtime-lifetime-guard.md)'s "do not re-derive" table.

## The blocking fact: wrong runtime

**Leaf instruments Rust MIR. OwnAudit audits .NET.**

Verified against `PhysShell/OwnAudit` at clone time:

- README: an orchestrator over "a legacy **.NET 4.7.2 / WPF / DevExpress** app".
- File census: 98 `.sarif`, 70 `.py`, 46 `.json`, 38 `.md`, 31 `.cs` — and
  **zero `.rs`, no `Cargo.toml`**.
- The runtime half is a **ClrMD heap walk** over a CLR process, emitting
  `runtime.json` (`schema: "ownAudit/runtime/v1"`).

There is no MIR in .NET and Leaf cannot observe a CLR process. The proposed
`Leaf → adapter → RuntimeEvidenceEvent → OwnAudit rules` pipeline is not
buildable at any effort level. The 8.5/10 is for a wire that has no endpoints.

**The 9/10 is further off still.** [P-017](../proposals/P-017-multi-stack-frontends.md)
takes the core beyond .NET to **OwnTS** and **OwnJVM (Java/Kotlin)** — Rust is
not a target and structurally should not be: this project's entire thesis is
bringing ownership discipline to a **GC language that lacks it**, and the
ROADMAP carries a standing section on *why not a Rust-style borrow checker for
C#*. Rust already has the borrow checker; there is no gap to sell into.

The likely source of the error is real and easy to trip on: **Own.NET's core is
being migrated *to* Rust** ([P-022](../proposals/P-022-rust-core-migration.md)).
That is the analyzer *written in* Rust, not the analyzer *analyzing* Rust.

## The five "adopt these", scored against the tree

| # | Proposed idea | Reality |
|---|---|---|
| 1 | Provider-agnostic Runtime Evidence IR, so we don't become a shell over Leaf | **Seam already exists.** `runtime.json` is a versioned schema consumed by `runtime/cli.py`; the collector is already swappable. What differs is snapshot vs event stream — a real question, but not this one |
| 2 | Correlate static site with runtime fact | **Already shipped.** Member-aware matching (2026-07-19): a `subscription-leak` finding's canonical `event 'A.B.Holder.Member'` identity must equal a retention root's `(short(holder), member)`; the matched root is reported as `root_holder`/`root_member`. Evidence in `docs/evidence/gtd-runtime-transition.md` |
| 3 | Static pass drives targeted instrumentation | **Not built — and the motivation does not transfer.** Leaf needs targeting because per-event MIR instrumentation is reportedly 19×–396×. A post-scenario heap snapshot has no per-event cost to target down. Only becomes relevant *if* OwnAudit moves to event-stream instrumentation, which is a decision on its own merits |
| 4 | Explicit evidence gaps: `COMPLETE / PARTIAL / OPAQUE / UNSUPPORTED` | **Already a machine contract, and stronger.** [`runtime-witness-operations.md`](../runtime-witness-operations.md): exit 0 = heap read, nothing retained; exit 1 = read, retained; **exit 2 = the heap was not read**. A refused attach writes **no** `runtime.json` — there is no verdict to record. *"Proven by CI: a denied attach exits 2, names the policy that refused, and leaves no artifact behind."* Plus `NO-TOOL: skipped` coverage maps, the OWN050/051/052 advisories, and P-036's rule that a check "may not pretend the call was proven harmless" |
| 5 | Use it as an oracle for static rules | **Pattern already shipped**, minus Leaf. The 3-way oracle (Own.NET vs Infer# vs CodeQL) plus the runtime buckets: **confirmed** (gate on these), **static-only** (suspect FP or unexercised path), **runtime-only** = *"the analyzer's blind spot — candidate for a new rule"* |

So: two already shipped, one shipped as a pattern, one already has its seam, and
one solves a cost problem this stack does not have.

The sharpest inversion is #4. The proposal offered explicit evidence gaps as
something to import — *"сделанная частью машинного контракта, а не красивой
фразой в README"*. It is already the machine contract, it is CI-proven, and
distinguishing *not looking* from *looking and finding nothing* is one of the
oldest rules in this codebase.

## What is actually worth taking

Two things, both concept-level, neither depending on Leaf.

**(a) One runtime substrate, many analyzers.** Leaf's real contribution is
decoupling: instrumentation exists separately from any particular analysis, so
one semantic layer (50 DMIR callbacks) serves a concolic executor, a sanitizer
and a tracer. The boundary transfers; the MIR does not.

**(b) Separate the *collection* substrate from the *analysis-facing*
representation.** Subtler than "one shared schema", and the part worth stealing
outright. Leaf does not hand probes to analyzers: probes are shaped for cheap
instrumentation, and a Probe-to-DMIR adapter reconstructs structured events for
analysis. The two formats are deliberately different. The failure this avoids is
one universal envelope that everything gets poured into *because the schema
already exists* — a snapshot and an event stream should not be forced to
pretend they are one datatype.

### Measured against the tree, the question is already overdue

The natural framing — "decide before the second dynamic consumer" — is **too
late by two consumers**. There are **five runtime-evidence producer
implementations across the two repositories**: four under
`Own.NET/audit/runtime/`, plus the lift-out producer in
`OwnAudit/src/OwnAudit.Runtime`.

"Collector" is the wrong word for them, and the distinction is load-bearing
rather than pedantic — it decides which layer a new contract belongs to.
Verified by the APIs each one actually calls:

| runtime evidence producer | acquisition it performs | material it interprets | output | schema field |
|---|---|---|---|---|
| `RetentionPath` | `AttachToProcess`, `procdump` | live CLR **or** `.dmp` | `runtime.json` | `"own-runtime/1"` |
| `OwnAudit.Runtime` (`RuntimeReport.cs`) | stand-side collector | live heap | `runtime.json` | `"ownAudit/runtime/v1"` |
| `LeakHarness` | `procdump` (orchestrates the scenario) | `.dmp` | `leak-harness.json` | none |
| `DuplicateDetector` | `procdump` (optional) | `.dmp` | `duplicate-detector.json` | none |
| `PropertyChangedStorm` | **none** | `.etl` captured externally | `propertychanged-storm.json` | none |

`PropertyChangedStorm` is the clean case: it opens an `ETWTraceEventSource` over
an `.etl` that PerfView/xperf/logman captured against the target's
`OwnNet-Sematix-INPC` EventSource. It acquires nothing. So the real layering is
**acquisition** (live attach / `.dmp` / `.etl`) → **interpretation** → 
**analysis-facing artifact** → `correlate.py` / `ingest.py` → SARIF.

That reframes takeaway (b) more sharply than "one substrate, many analyzers":
*the acquisition representation need not — and should not — be the evidence
representation.* A `.dmp` and an `.etl` are already good acquisition substrates
for their jobs; turning them into a universal runtime-event JSON would unify the
wrong layer. The thing worth sharing is a **runtime artifact contract**, not a
collection substrate.

So [`Plan.md`](../../Plan.md) categories 6 (PropertyChanged storms) and 11
(duplicate immutable heap data, flagged there as *"the project's gold"*) are not
future work to design around — they exist as code, each with its own bespoke
JSON. Three findings follow, all checkable:

1. **Two producers of `runtime.json` emit two different schema strings.**
   `RetentionPath` (both of its writers) says `own-runtime/1`; the newer
   stand-side collector, `docs/runtime-contract.md`, and every fixture say
   `ownAudit/runtime/v1`. This is a lift-out artifact — the collector plan
   (2026-07-18) ports `stackpeek` into `OwnAudit.Runtime` while the older
   `RetentionPath` stays canonical in Own.NET — not sloppiness. But it is live.
2. **Nothing enforces either.** `runtime/correlate.py` consumes exactly
   `retained / type / count / expected / bytes / roots / kind / holder /
   member`. It never reads `schema`, `scenario`, `iterations`, `collector`, or
   `verdict`. The only assertion on the string is
   `HeapCollectorContractTests.cs:83`, and it checks the producer against
   itself. A `runtime.json` with the wrong version — or none — correlates
   silently.
3. **The envelope fields are decorative.** `scenario` and `iterations` are
   documented and present in fixtures but unread; `collector` (a genuine
   provenance fingerprint) and `verdict` are emitted by `RetentionPath` but
   appear in neither the documented schema nor the consumer.

**No impact today** — the correlator is deliberately tolerant of unknown fields,
which is a reasonable forward-compat choice. The risk is latent and the fix is
cheap *now*, which is exactly the argument for settling it before the runtime
artifact surface expands further.

### Counted by artifact family, which is what would get versioned

Producers are the wrong unit — five implementations emit **four** analysis-facing
artifact families, and it is the families that need identity:

| artifact family | producer(s) | identity status |
|---|---|---|
| heap-retention | `RetentionPath` + `OwnAudit.Runtime` | **two conflicting identities** (`own-runtime/1` vs `ownAudit/runtime/v1`) |
| leak-growth | `LeakHarness` | **none** |
| duplicate-immutable | `DuplicateDetector` | **none** |
| propertychanged-storm | `PropertyChangedStorm` | **none** |

> **All four shipped runtime artifact families have an identity problem:
> heap-retention has two conflicting schema identities; the other three have
> none.**

### The cheap next step is versioning, not unification

A shared envelope carrying capture/process/scenario identity, producer
fingerprint, config digest and provenance, with typed-distinct payloads, is the
right *destination*. It is the wrong *first move*: it designs commonality up
front, which is precisely the mistake Leaf avoids. Leaf's lesson is **define the
boundary first, derive the representation second**.

So the minimal work that closes the real hole found above, in order:

1. **Every analysis-facing artifact gets its own mandatory schema identity** —
   one per family, e.g. `heap-retention`, `leak-growth`,
   `duplicate-immutable`, `propertychanged-storm` (names illustrative, not
   normative). Today three of the five producers emit no version at all, and
   the two that do disagree with each other — see the family table above.
2. **Readers must validate family and major version.** Tolerant of unknown
   *fields*, intolerant of unknown *identity*:

   | input | verdict |
   |---|---|
   | known family + known major + unknown extra fields | accept |
   | missing schema | reject |
   | wrong artifact family | reject |
   | unknown major | reject |

   This is the actual gap. `correlate()` currently takes a `dict` and
   structurally duck-types it on `retained`/`type`/`count`/… — so *any* JSON
   containing a `retained` array is treated as the contract.
3. **Only then extract the envelope**, from commonality *proven* by four
   shipped schemas rather than drawn in advance. Fields have to earn the right
   to be called common.

This closes the found defect now, changes no fail-closed semantics, and commits
to no universal-envelope architecture.

### Split `completeness` into three orthogonal things

The caution raised earlier resolves cleanly once the word is broken up. These
are three different states and are currently drifting toward one label:

- **Collection outcome.** Success → an artifact may exist. Refusal or failure →
  exit 2 and the artifact **must not** exist. *The existing fail-closed
  invariant, unchanged.*
- **Artifact validity.** Given an artifact: known schema, required fields,
  well-formed, producer contract satisfied → valid, else reject. *This is the
  layer that is missing today* (step 2 above).
- **Evidence coverage.** Belongs to the **artifact family**, not to a global
  enum. For heap retention the family contract can simply be
  total-or-no-artifact — no `PARTIAL` ever. For an ETW trace the physics differ
  and coverage is real data: capture interval, events lost, buffers lost, trace
  truncated, provider-enabled interval. A valid storm artifact can legitimately
  rest on a bounded trace if the claim it makes is bounded accordingly.

That keeps "refusal → no artifact" intact, because *collector refused* and
*collector succeeded over bounded observation* are different states, not two
shades of one. The invariant to write down:

> **Artifact existence proves successful execution of its producer contract,
> not completeness of every possible observation. Coverage semantics belong to
> the artifact family and must never be inferred from artifact existence
> alone.**

This is strictly better than a global `"completeness": "PARTIAL"`, which within
a year means five different things per producer and then grows a
`PARTIAL_BUT_USABLE`.

## The invariant worth stating separately

The error that produced the original proposal is natural, will recur, and is
cheap to inoculate against:

> **Do not infer analyzed-language support from the implementation language of
> the Own.NET core.** P-022 moves the *analyzer's implementation* to Rust. It
> does not change the audited runtime, does not introduce Rust MIR, and does not
> make Rust an analysis target — P-017's targets are OwnTS and OwnJVM.

Implementation language and analyzed language are orthogonal axes. Conflating
them is what turned a Rust-only instrumentation framework into an 8.5/10
recommendation for a .NET auditor.

## Provenance and limits

- The paper's existence, title, authors and subject were verified against arXiv.
- The **overhead figures** (19×–396×, ~3.5× for concrete types, ~2.8× for raw
  addresses, ~50 DMIR callback types, the `nightly-2026-07-01` pin, and the
  three demo analyses) were **not** checked here against the paper. The author
  of the original summary re-verified them against it afterwards and reports
  them correct; that is second-hand for this note's purposes, and they are
  quoted only to show that the motivation for idea #3 is cost, not to rely on
  the magnitudes.
- OwnAudit was read at a shallow clone of `main`; the collector inventory and
  schema-string findings are about that tree plus `Own.NET/audit/runtime/` at
  this branch's base commit.
- **Recorded, not scheduled** — with one exception. The identity/validation
  defect measured above is no longer an idea from a paper but a demonstrated
  contract hole, so it has a written spec at
  [`docs/tasks/runtime-artifact-identity.md`](../tasks/runtime-artifact-identity.md)
  (status: *spec, ready to implement*, explicitly **not** inserted into the
  current sequence). Everything else here remains recorded only.
