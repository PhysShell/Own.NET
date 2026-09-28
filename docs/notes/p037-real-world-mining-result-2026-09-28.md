# P-037 bounded real-world materiality gate — result

Per [`p037-real-world-mining-prereg-2026-09-28.md`](p037-real-world-mining-prereg-2026-09-28.md)
(rules frozen before any candidate was examined) and
[`candidates.json`](../evidence/p037-real-world-mining/candidates.json)
(13 entries, 22 individual issues, frozen before any current-Own.NET
analyzer run). Research/evidence only — not authorization to implement
P-037, not B2.1a, not a touch of held R1, #368, or Phase C.

## What was done

**S1 — PhysShell/OwnAudit `leakmine`.** Read `docs/leakfix-mine.md` in
full (real, well-designed discovery/classification-vs-before/after-confirm
architecture) and inspected the repository for already-existing mined
data (`corpus.db`, `dataset.json`, `summary.md`, any committed
candidates). None exist for the `dotnet_wpf` ecosystem — the only
real, executed case-study results documented (§15) are `react_ts` and
`android_kotlin`, both wrong-language for testing current Own.NET (it has
no non-C# frontend). No new `leakmine mine` campaign was run, per the
task's explicit instruction. **S1 yielded 0 usable candidates.**

**S2 — Own.NET's own issue/PR history beyond #278.** Search surfaced
the full `#278 → #293/#302 → #305 → #306 → #304` lineage. Issue #305
("adversarial audit, 2 P1 holes pinned red") and its `docs/notes/
teardown-predicate-adversarial-audit.md` were read in full: both pinned
holes (A: early-return-spelled parameter guard; B: canonical
`if(disposing)`/else-branch) and the four further-recorded-but-unfixtured
items (C: parameter laundered through a local; D: enrollment without
`IDisposable`; E: `when`-clause coverage; F: receiver aliasing) were
individually checked against the frozen grammar. The audit document
itself cites no GitHub URL, repo, or independent real occurrence anywhere
— it is adversarial code reading against Own.NET's own predicate source,
not real-world discovery. Holes A and B are explicitly framed as the
*same* SectorTS shape from #278 under a semantics-preserving rewrite, not
a new incident, and both are now fixed by #306 regardless. C and F are
also explicitly outside the frozen scope (local-variable and aliased-
receiver guard state are both on the reject list). **S2 yielded 0
admissible candidates.**

**Bounded external search (≤30 min, per the prereg's M1).** Three
targeted web searches; the most promising hit
([dotnet/runtime#73778](https://github.com/dotnet/runtime/issues/73778),
`EventLogWatcher.Dispose(bool)`) was fetched and read in full — a real,
maintainer-reported bug with exact code. On analysis its decisive
mechanism is finalizer call-graph reachability (does anything ever call
`Dispose(false)`?) entangled with a resource kind — a raw native handle
array closed via a P/Invoke call — that Own.NET's IDisposable-flow model
does not track at all. P-037's call-site-election grammar has nothing to
elect here: there is exactly one production call site, always
`disposing: true`. To the extent the shape resembles an existing Own.NET
doctrine, it resembles the canonical-disposing/else-branch crediting rule
PR #306 already hardened. Several further hits
([JoshClose/CsvHelper#1684](https://github.com/JoshClose/CsvHelper/issues/1684),
[dotnet/runtime#89646](https://github.com/dotnet/runtime/issues/89646))
were disqualified on inspection because their guard (`leaveOpen`) is a
constructor-captured field, not a per-call method parameter — explicitly
on the frozen scope's reject list. The rest were screened out by
title/summary as feature requests, a different bug class (use-after-
dispose timing, not a leak), a different language entirely, or a
framework-level regression unrelated to application-level guarded
release. Full detail and reasoning for all 13 entries is in
`candidates.json`. **The bounded search yielded 0 admissible candidates.**

## Kill condition

**K1 fires**: after S1–S3 there were zero plausible, in-scope candidates,
and the bounded (≤30 min) targeted search also yielded zero. Per the
frozen decision rule, the threshold (≥3 independent incidents OR ≥1
material incident) cannot be met from what remains examinable within this
gate's budget, and continuing would mean either widening into a
forbidden mass-mining campaign or re-litigating already-covered/out-of-
scope material. Mining stops here per the prereg's own rule: remaining
budget is not a reason to continue once the mathematical maximum cannot
reach the threshold.

## N and decision

N = 0 independent HIGH/MEDIUM-ground-truth real incidents satisfying
C1–C6. (One HIGH-confidence real incident exists — #278 — but fails C5,
already covered. One MEDIUM-confidence real incident — dotnet/runtime
#73778 — fails C3, outside the frozen grammar / confounded with an
untracked resource kind. No incident reaches admission.)

Per the frozen decision rule: N < 3 and no material-impact incident
satisfies C1–C6 → **`CAPABILITY_GAP_ONLY`** — unchanged from the
corrected value-benchmark result. This bounded gate did not find grounds
to upgrade it to `REOPEN_CANDIDATE_R2`.

## Budget spent

Well inside the 4-hour cap. M0 (setup, prereg, S1+S2 existing-data
inventory): the bulk of the time. M1 (bounded external search): 3 web
searches + 1 full issue fetch, under the 30-minute sub-cap. M2/M3
(adjudication + this report): the remainder. Code budget: 0 production
LOC, 0 analyzer semantic LOC, 0 mining-framework LOC, 0 one-off
conversion LOC (none was needed).
