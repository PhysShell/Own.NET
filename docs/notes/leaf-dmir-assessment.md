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

One thing, and it is about our own roadmap rather than about Leaf.

Leaf's real contribution is **decoupling**: one semantic runtime layer, many
analyzers above it, instead of a single-purpose sanitizer that then spends
twenty years impersonating infrastructure. OwnAudit's runtime layer is today
**single-purpose** — retention/leak confirmation. But [`Plan.md`](../../Plan.md)
§2 already schedules two more runtime consumers: **category 6** (PropertyChanged
storms / frequency) and **category 11** (duplicate immutable data on the heap,
flagged there as *"the project's gold"*).

That makes the live question: **one shared runtime-evidence schema, or three
bespoke collectors?** Worth answering *before* the second collector is written,
not after. That is a genuine, correctly-scoped takeaway — and note it is
answerable entirely inside .NET, with ClrMD and ETW, with no Rust anywhere near
it.

## Provenance and limits

- The paper's existence, title, authors and subject were verified against arXiv.
- The **overhead figures** (19×–396×, ~3.5× for concrete types, ~2.8× for raw
  addresses, ~50 DMIR callback types, the `nightly-2026-07-01` pin) come from
  the summary being assessed and were **not** independently checked against the
  paper or the repository. They are quoted above only to show that the
  motivation for idea #3 is cost, not to rely on the magnitudes.
- OwnAudit was read at a shallow clone of `main`; claims are about that tree.
- **Recorded, not scheduled.** No work item is filed off this note.
