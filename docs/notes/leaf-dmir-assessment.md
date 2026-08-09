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
late by two consumers**. `Own.NET/audit/runtime/` already contains four C#
collectors:

| collector | output | schema field |
|---|---|---|
| `RetentionPath` | `runtime.json` | `"own-runtime/1"` |
| `OwnAudit/src/OwnAudit.Runtime` (`RuntimeReport.cs`) | `runtime.json` | `"ownAudit/runtime/v1"` |
| `LeakHarness` | `artifacts/own-audit/leak-harness.json` | none |
| `DuplicateDetector` | `artifacts/own-audit/duplicate-detector.json` | none |
| `PropertyChangedStorm` | `artifacts/own-audit/propertychanged-storm.json` | none |

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
cheap *now*, which is exactly the argument for settling it before a fourth
consumer inherits the ambiguity.

### On the proposed shape

The hybrid — a shared envelope carrying capture/process/runtime/scenario
identity, collector fingerprint, config digest and provenance, with
**typed-distinct** `HeapSnapshotEvidence` vs `EventTraceEvidence` payloads — is
the right instinct, and finding (b) above is why: snapshot and trace genuinely
are different datatypes.

One caution, from finding (2) rather than from taste. Putting
**completeness/refusal into the envelope** collides with the contract we already
have. Today the rule is binary and out-of-band: exit 2, and **no artifact at
all** — *"there is no verdict to record"*. Adding a `completeness: PARTIAL`
field creates, for the first time, a valid artifact that is admittedly
incomplete. That may well be worth it for an event trace, where partial capture
is normal rather than exceptional. But it is a **weakening of a fail-closed
invariant**, not a free addition, and it should be decided deliberately —
per-payload-family, most likely — rather than inherited from a Rust paper whose
gaps are a property of selective instrumentation we do not do.

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
- **Recorded, not scheduled.** No work item is filed off this note.
