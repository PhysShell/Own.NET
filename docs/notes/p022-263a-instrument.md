# #263-A — the measurement instrument (calibration only)

**What this is.** The frozen *instrument* for #263's P-022 performance baselines:
how a number is produced, never what the number should be. It permits building
the harness and running **calibration**. It does not authorize the decisive
measurement (#263-B, gated by the D7 freeze) and it sets **no** thresholds, no
repetition count `N`, and no Rust-vs-Python comparison statistic. Those are D7's,
preregistered before the decisive run.

**Baseline.** Built on `main` = `ca8b1064fc6ac5e0a901d8b67eb9f2bbd3543fd5`.
Stage 1 and Stage 2 of #262 are closed; Stage 3/4 are unauthorized.

- instrument: `scripts/perf_baseline.py`
- frozen workloads: `docs/evidence/p022-263a-workloads.json`
- controls: `tests/test_perf_instrument.py`
- calibration reports: `docs/evidence/p022-263a-calibration.<platform>.json`

---

## 1. Preflight reconciliation, against primary source

Read from `origin/main` at the baseline: live #263, and #262's **Performance
gates** section.

**#262's Performance gates name seven phases:** process startup; OwnIR parse;
bridge/lowering; analysis; CLI/SARIF rendering; end-to-end C# project/solution
run; peak RSS/allocations where practical.

**The brief's §1 adds one:** frontend/Roslyn extraction, explicitly *recorded but
not D7-gated* unless the owner separately ratifies a gate. The two lists
reconcile: §1 = #262's gate list + extraction as a diagnostic phase, so an
end-to-end regression can be localised instead of reported as "something
happened between `git checkout` and SARIF".

**The two populations, frozen.**

| | what it is | does it enter the D7 cutover verdict? |
|---|---|---|
| **A — G3 cutover subset** | #262's Performance-gate phases | yes — these feed D7 |
| **B — IDE-foundation remainder** | frontend extraction, no-op recheck, single-file edit recheck, diagnostic-publication latency proxy, IDE budgets | **no**, unless separately owner-ratified |

Completing #263-A must not silently narrow #263's own acceptance. Recorded here
so the narrowing cannot happen by omission — **#263 asks for measurements this
instrument does not yet take**, and they are owed on population B's own track:

- `.own` workloads: minimal file, medium module, corpus batch;
- OwnIR **serialization** (this instrument measures parse, which is #262's gate
  phase; serialization is #263's broader list);
- no-op recheck, single-file edit recheck, diagnostic-publication latency proxy;
- allocation/heap profile;
- explicit IDE latency budgets (a *budget* is a threshold and is therefore not
  #263-A's to propose at all).

## 2. What is, and is not, separately observable

Neither engine exposes per-phase timing through its production surface, and
#263-A is not authorized to add production instrumentation. So the instrument
measures a **ladder of real production invocations**, records each as the
composed interval it actually is, and names the phases inside it. Where a phase
cannot be isolated it is recorded as `composed` or `unavailable` — #263 asks for
unavailable stages to be *marked*, not imputed.

| rung | surface | interval contains | observability |
|---|---|---|---|
| `core-usage` | core | core startup + argv | **direct** — this interval *is* startup |
| `core-parse-refused` | core | startup + read + parse + door refusal | composed |
| `core-full-human` | core | startup + parse + bridge + analysis + human render | composed |
| `core-full-sarif` | core | startup + parse + bridge + analysis + SARIF render | composed |
| `launcher-extract` | launcher | launcher startup + Roslyn extraction | composed |
| `launcher-e2e` | launcher | launcher startup + extraction + core + render | composed |

**Derived views are labelled as derived and never presented as measurements.**
`parse ≈ core-parse-refused − core-usage`. `core work ≈ launcher-e2e −
launcher-extract`. `core-full-sarif − core-full-human` is a *renderer
difference*, which is not the same quantity as rendering in isolation.

**`bridge-lowering` and `analysis` are not separately observable** through either
production surface. They are recorded as members of the `core-full-*` interval.
Isolating them needs production instrumentation this brief does not authorize —
recorded as an instrument limitation rather than worked around.

**Two startups, never merged.** `process-startup-core` (the child engine) and
`process-startup-launcher` (what a user actually waits for) are separate
metrics, because merging them would let the user-visible number absorb the
child's.

## 3. Same input — which means two different things

**Isolated core rungs:** one OwnIR byte sequence, its sha256 recorded, the *same
bytes* handed to Python and to Rust.

**End-to-end:** the same pinned source tree, configuration and extractor
identity — and **each engine performs its own extraction**, inside the elapsed
time. An end-to-end number that shares one extraction between engines is a core
comparison wearing an end-to-end hat. The Rust end-to-end path goes **through
the production launcher** selecting Rust, never `own-cli` substituted for the
user-visible path.

The candidate is the production `own-cli`, built deterministically, sha256 and
byte length recorded. Never `own-shadow-engine`, never a stub.

## 4. Workloads

Frozen in `docs/evidence/p022-263a-workloads.json`, in two populations that
cannot be confused because the calibration set is **generated** by the harness
rather than found on disk.

- **Decisive** (13): the committed sample/examples/corpus trees, the five pinned
  OSS repositories of #243 at their verified pins (repo walk and largest
  solution, which is a different extractor path and a differently *ordered*
  document, not a subset), and #262's large-solution control — declared under its
  own id and recorded as an **alias** so it is never counted twice.
- **Calibration** (6): generated facts documents at three scales, a document the
  strict door refuses, and two synthetic C# trees.

Drift on a pinned target is a **failed target**, never a newer measurement.

## 5. Environment matrix

Linux **and** Windows; they differ in exactly the mechanics — process launch,
filesystem, path forms — that a single-platform baseline leaves unproven.
Recorded per run: CPU model and core count, RAM, OS, .NET SDK, Python, Rust
toolchain, runner class.

## 6. Cold and warm

- **process-cold** — a fresh process every iteration, no in-process warmup. The
  default: cheap, portable, and honestly named.
- **warm** — steady state after a stated number of **discarded** warmup
  iterations, never averaged in. The process is still fresh; what is warm is the
  OS and filesystem cache.
- **machine/cache-cold** — **not claimed.** It exists only behind a documented
  reset protocol (cache drop, reboot, fresh VM), and "caches not pre-warmed"
  with no reset step means a different kind of cold on Windows than on Linux. A
  machine-cold claim without its reset protocol is inadmissible, so the
  instrument does not make one.

## 7. Repetitions, aggregation, and what is deliberately absent

Each engine's own samples are summarised as **median + dispersion (IQR and MAD)
+ min**, never mean-only. Raw per-iteration data is retained: an aggregate whose
raw is gone cannot be re-audited.

**Not here, on purpose:**

- the decisive `N` and its escalation ladder — D7 preregisters them from
  calibration variance; the calibration repetition count in a report is an
  instrument-sizing parameter and is labelled as one;
- the **Rust-vs-Python comparison statistic** — ratio of medians and median of
  paired ratios are not the same thing, and choosing between them is a decision.
  The instrument enforces this structurally: every cell holds exactly one
  engine's samples, and a report carrying a comparison key is refused on the way
  out.

## 8. Noise, outliers, invalidation

A fixed deterministic task is timed at the start and end of every session. Its
dispersion is the **noise floor**; exceeding it, or drifting between the opening
and closing probes, **invalidates the run** rather than widening the reported
dispersion — a benchmark that absorbs contention into its error bars is
reporting the noise as if it were the subject. The floor is an
*instrument-validity* constant: it says how much the machine may wobble, and
nothing whatever about either engine.

**Reproducibility** (§9) is checked by re-running and comparing each cell's
median against the earlier run, to a tolerance taken from the **noise floor the
earlier run itself recorded** — so the check tightens on a quiet machine instead
of being a number somebody liked.

## 9. Peak RSS

By a named mechanism, recorded, never eyeballed:

- POSIX: `os.wait4` — the kernel's per-child `ru_maxrss`, for exactly the
  process spawned. Chosen over `/usr/bin/time -v` as primary because GNU time is
  a package that may simply be absent, and "the tool was missing" is not a
  memory measurement. `/usr/bin/time -v` remains the documented fallback.
- Windows: a Job Object, `PeakProcessMemoryUsed` via `QueryInformationJobObject`.

Where nothing is available the value is `null` **with a reason**, so a silent
absence can never be read as a measured zero. Allocation counts are not yet
captured — recorded as owed on population B's track rather than quietly dropped.

## 10. The CALIBRATION_ONLY firewall

Every calibration result is tagged `CALIBRATION_ONLY`, is not decision evidence,
and cannot choose a threshold.

Before the D7 freeze a **decisive** workload may be enumerated, hashed, fetched,
availability-checked, and exercised by **non-timed structural smoke** — nothing
else. The instrument is deliberately **stricter than "no paired runs"**: a
single-engine timed run of a decisive workload is refused too, because a
stopwatch appears nowhere in that permitted list.

The prohibition is structural, not clerical. There is exactly **one** function
that starts a clock and it refuses a decisive workload unless the identity gate
is armed. "We did not save the delta" is accounting-clean and epistemically
worthless: whoever watched the two numbers has already peeked, and every
threshold chosen afterwards is a rationalisation with a timestamp.

## 11. The D7-freeze gate

#263-A permits calibration and does **not** authorize the decisive run. There is
no continuous slide from one into the other: the freeze is a discrete gate with
a before and an after, and #263-B may not begin until it has passed.

## 12. The single-reference rule

Every result records the Python reference **commit SHA** alongside the
interpreter version, so a later artifact cannot silently combine comparisons
bound to two different reference states. The preferred path is that the
V1/V2/invalid-UTF-8 hygiene lands **before** the D7 freeze and #263-B.

## 13. The four carried obligations

| | obligation | where it lives |
|---|---|---|
| (a) | the identity gate exists **now**, dormant | `IdentityGate`; built before the instrument is final, because D7's C1 freezes the harness digest and a gate added after that freeze makes this a different instrument |
| (b) | arming is **data only** | a JSON attestation; the control proves the harness digest does not move when the gate arms, and that a correct attestation alone opens the firewall |
| (c) | **fail-closed, before any measured interval** | identity verification completes and passes first; a control counts digest calls *inside* a measured interval and requires zero — a gate that pays for itself out of the startup benchmark is a defect wearing a safeguard's coat |
| (d) | **two identity domains, kept apart** | the C1/C2 gate covers reference + harness + manifest + D7 payload; the **session** identity covers the candidate binary, frozen at session start, and its drift refuses the remainder of the session. The candidate is the thing under test, so it is not instrument identity |

## 14. Known limitations, recorded rather than routed around

1. **`bridge-lowering` and `analysis` are not separately observable** (§2).
2. **Allocation counts are not captured**; only peak RSS (§9).
3. **Population B's measurements are not implemented here** (§1) — owed on their
   own track, not narrowed away.
4. **`machine/cache-cold` is not claimed** (§6) — no reset protocol exists in
   the CI environments this instrument runs in.
