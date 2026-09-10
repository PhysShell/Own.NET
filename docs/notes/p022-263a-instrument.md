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
| `core-usage` | core | core startup + argv parsing + usage refusal | composed — a **lower bound** on startup, not startup |
| `core-parse-refused` | core | startup + read + parse + door refusal | composed |
| `core-full-human` | core | startup + parse + bridge + analysis + human render | composed |
| `core-full-sarif` | core | startup + parse + bridge + analysis + SARIF render | composed |
| `launcher-e2e` | launcher | launcher startup + extraction + core + render | composed |

Each rung also declares the **exit codes that mean it did its job** and a
post-condition proving it: `core-usage` 2 with the driver banner on stdout and
nothing on stderr; `core-parse-refused` 2 with the refusal on stderr and nothing
on stdout; `core-full-*` 0 or 1 (1 is "leaks found", not a failure) with a
rendered verdict; `launcher-e2e` 0 with a verdict. The post-condition runs
**once, untimed, with output captured**, so its cost never reaches a benchmark.
A cell whose invocation did not do the rung's work **is not timed at all** and
the calibration is refused.

**`launcher-extract` was withdrawn.** It invoked the launcher with
`--emit-facts` and was documented as "no core runs, so this isolates the
frontend stage". The launcher says otherwise: `--emit-facts` copies the
intermediate facts and then Stage 2 runs the engine anyway. The interval
therefore contained the whole pipeline while recording itself as launcher
startup plus extraction — the same defect as the old `core-usage` label, one
level up. Isolating launcher-scoped extraction would need either a production
launcher change or a direct extractor invocation, and a direct extractor process
is *not* the launcher's extraction stage. So it is recorded **unavailable**
rather than invented, and `frontend-extraction` stays measured as a member of
`launcher-e2e`.

**The ladder floor is a bound, not a phase.** `core-usage` is the smallest
invocation the production surface allows: the process starts, parses argv, finds
no document, writes a usage refusal and exits. Calling that interval "startup"
would be convenient and wrong — argv handling and refusal rendering are inside
it, and nothing in either production surface separates them out. So it is
recorded as `composed` over `process-startup-core` + `cli-argv-parse` +
`cli-usage-refusal`, and
what it gives D7 is a **lower bound** on core startup.

**A phase list means "this interval did these things".** One name once covered
two actions — argv parsing *and* the usage refusal — and so appeared on three
rungs that never write a usage refusal. The report copied that taxonomy
faithfully and the control compared the two and agreed they matched, which is
how a schema stays self-consistent while saying something false. The vocabulary
now separates `cli-argv-parse` (every real core invocation), `cli-usage-refusal`
(only the floor rung) and `ownir-door-refusal` (only the version-refused rung),
and a refusal phase may appear only on the rung whose **outcome evidence proves
that refusal happened** — `cli-usage-refusal` ⇔ `usage-help`,
`ownir-door-refusal` ⇔ `door-refusal`, and neither on a rung that reaches a
verdict.

Applying the same rule the other way, `launcher-e2e` now also names
`process-startup-core` and `cli-argv-parse`: the launcher spawns the core, so
those actions are genuinely inside that interval and a complete list has to say
so.

**Derived views are labelled as derived and never presented as measurements.**
`core-parse-refused − core-usage` does *not* yield parse: it yields the ownir
read+parse cost only under an assumption this instrument never measures — that
both invocations pay the same argv handling and comparably priced refusal
rendering. It is a derived **bound**. Likewise `core-full-sarif −
core-full-human` is a *renderer difference*, which is not the same quantity as
rendering in isolation.

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
| (b) | arming is **data only** | two committed JSON objects — a freeze payload and a detached ratification; no source patch, so the control proves the harness digest does not move when the gate arms and that the firewall then opens. Fixtures use the **production nested layout**, because the first set put both objects at the repository root, where a wrong path model is accidentally right |
| (c) | **fail-closed, before any measured interval** | identity verification completes and passes first; a control counts both digest computations and git invocations *inside* a measured interval and requires zero of each — a gate that pays for itself out of the startup benchmark is a defect wearing a safeguard's coat |
| (d) | **two identity domains, kept apart** | the C1/C2 gate covers reference + harness + manifest + D7 payload; the **session** identity covers the candidate binary, frozen at session start, and its drift refuses the remainder of the session. The candidate is the thing under test, so it is not instrument identity |

### What the gate actually verifies

An attestation is not "a JSON file with the right numbers in it". The values a
freeze pins — the harness digest, the manifest digest — are things anyone
holding this repository can compute in one line, so a verifier that only
compares them proves the instrument is the instrument and calls that a freeze.
It answers *is this the harness?* when the question is *did D7 happen?*

The freeze is therefore **two objects**, because a payload cannot name the
commit that contains it — that sha would have to be inside the bytes hashed into
it, and self-reference is the reason detached signatures exist:

* the **payload** (`p022-263a-d7-attestation.json`) — what D7 froze: a C1
  section of instrument identities and a C2 section of decisive protocol.
  Carries no commit reference, so it can be hashed as a unit.
* the **ratification** (`p022-263a-d7-ratification.json`) — the owner's act,
  committed separately and afterwards: it names the payload's body hash and the
  commit the payload is frozen at.

Arming requires all of: a kind/schema discriminator; a complete C1 *and* a
complete C2 section; a body hash the payload recomputes to; C1 matching observed
identity; a ratification of *that* body hash; a `payload_path` equal to the
repository-relative path this instrument actually reads its payload from, so a
ratification cannot choose which file it is about; and git blob identity — the
payload's working-tree bytes must be the blob at the commit the ratification
names, and the ratification must itself be committed and unmodified.

Every path is resolved against the **git tree root**, obtained from
`git rev-parse --show-toplevel`. This is load-bearing and was got wrong once:
`<rev>:<path>` reads the path from the root of the tree, and only a path
starting `./` or `../` is read relative to the current directory. Treating the
payload's own directory as the repository produced a bare-basename lookup for a
file that lives under `docs/evidence/`, so no production freeze could ever have
armed — while every control passed, because the throwaway fixtures put both
objects at the repository root, where the wrong model is accidentally right. The
fixtures now use the production nested layout. **C2 is
checked for presence and never read**, because its values are thresholds and a
#263-A artifact that quoted one would leak the number this module exists to keep
out. Arming thus costs two reviewed commits rather than one text editor, and
still moves no source, so the harness digest D7 freezes is untouched by it.

### The harness digest names content, not a checkout

D7's C1 will freeze the harness digest, and #263-B runs on **both** platforms,
so that value has to be the same on both. It was not. The same tree hashed
`af32f04ddbad` on Linux and `51ef2ca2422a` on a Windows runner, where
`core.autocrlf` rewrote the instrument source on checkout — one instrument with
two identities, and a frozen C1 that would arm on one platform and refuse on the
other.

This repository already knew the defect class: `.gitattributes` pins
`docs/evidence/*.json` to LF because the mutation campaigns' definition hashes
hit it first, which is exactly why the *workload manifest* digest matched across
platforms while the *harness* digest did not. But an attribute only governs
files git checks out under it — a working tree that predates the rule, a zip
download, or a contributor with a different config all still differ. So the
digest normalizes line endings itself rather than delegating its identity to a
checkout setting. `sha256_file` stays raw: the candidate binary's identity is
its actual bytes, and normalizing a binary would be a different kind of wrong.

`perf-digest-platform-stable` holds both halves.

### Reproducibility answers two questions, not one

A re-run can disagree with the first run in two entirely different ways, and
collapsing them loses the more useful signal.

* **The instrument did not reproduce.** Different cells exist, or the same cell
  did different work — its outcome changed. That is a defect in this harness and
  it fails, always.
* **The environment did not reproduce.** Every outcome is identical and the
  timings moved outside the run's own noise floor. That is a property of the
  *machine*.

The gate treated both as instrument failure, so a hosted Windows runner drifting
by 0.355 and 0.362 against a 0.35 tolerance — with every exit code and every
piece of outcome evidence identical between the runs — was reported as a broken
instrument. It is not: it is the instrument correctly detecting that the machine
is not measurement-grade, which is precisely what #263-B needs to know before it
chooses where the decisive run happens.

**The tolerance did not move.** 0.35 is still 0.35, still derived from the noise
floor the run itself recorded rather than chosen, and the failing cells are
still named with their numbers in the report. Widening it to make a red run
green would be a threshold fitted to a result, which is the one thing this
instrument exists to prevent.

What the split does *not* do is soften the shipped evidence. A CI leg may record
"this environment is not measurement-grade" and pass. The **committed**
calibration may not: `perf-provenance-complete` requires the report of record to
have reproduced on both counts and to have a non-invalidated run. Evidence gets
stricter; only the diagnosis of a hosted runner gets more honest.

## 14. Known limitations, recorded rather than routed around

1. **`bridge-lowering` and `analysis` are not separately observable** (§2).
2. **Allocation counts are not captured**; only peak RSS (§9).
3. **Population B's measurements are not implemented here** (§1) — owed on their
   own track, not narrowed away.
4. **`machine/cache-cold` is not claimed** (§6) — no reset protocol exists in
   the CI environments this instrument runs in.
5. **Git object identity is not a signature, and signed ratification is not
   offered.** The gate raises arming from "write a local file" to "land two
   reviewed, committed objects" — auditable and owner-controlled — but anyone
   with repository write access could author both. It therefore requires
   `"signature": "none"` and **records the freeze as unsigned**. A signed mode
   was written and withdrawn: it read `git verify-commit --raw` from stdout when
   git writes that status to **stderr**, so a correctly signed commit would have
   verified cryptographically and then been refused for not naming its own key.
   No control caught it, because no environment this runs in holds a signing
   key. An advertised path that is observably wrong is worse than an absent one,
   so it is absent until there is a key and a control exercising **acceptance**.
6. **Launcher-scoped extraction isolation is unavailable** (§2) — recorded
   rather than imputed, after the `--emit-facts` interval turned out to contain
   the whole pipeline.
7. **A GitHub-hosted Windows runner is not reliably measurement-grade**, and
   the instrument established that on its first day — with a sharper result
   than "the runners are noisy".

   On **one commit**, two Windows runs minutes apart disagreed about their own
   environment. The first refused it: relative IQR **1.807** against the 0.35
   floor, with **0.870** drift between the opening and closing probes. The
   second accepted it and completed a full calibration that reproduced
   within 0.35. Same commit, same runner class, opposite validity verdicts.

   So the risk is not that a Windows measurement there would be noisy — it is
   that whether it is *admissible at all* turns on scheduling luck. A decisive
   session that started on the lucky run and continued into the unlucky one
   would be half a measurement. The harness stood up in both cases, produced a
   complete and correctly-provenanced report in both cases, and reported the
   environment honestly in both cases.

   This is a result, not a defect, and it is one #263-B needs before it starts:
   **the decisive Windows measurement needs a single-tenant machine**, and D7
   should not preregister a Windows protocol that assumes a hosted runner. The
   floor was deliberately *not* raised to make the run pass — an
   instrument-validity constant chosen after seeing which runs it rejects is a
   threshold fitted to a result, which is the entire failure mode this brief
   exists to prevent.

   CI therefore asks the two questions separately: *did the harness stand up
   and report honestly* (a gate, on both platforms) and *is this environment
   measurement-grade* (recorded per run, and allowed to be "no").
