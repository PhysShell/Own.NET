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
median against the earlier run, to `REPRODUCIBILITY_MAX_MEDIAN_CHANGE`. That is
a **chosen** policy constant, not one derived from the run: this section used to
claim it came from "the noise floor the earlier run itself recorded" and so
"tightens on a quiet machine", and neither was true — the recorded limit *was*
the constant, and it never tightened. What makes it admissible is that it was
chosen before the runs it judges. See §7 for the three policies it was split
into. **Both halves of every pair are committed**, and run B records run A's
path and sha256, so the verdict can be recomputed from evidence rather than
trusted.

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

D7 §6 defines **two git commits**, not two sections of one file.

| | |
|---|---|
| **C1** | the immutable payload commit — thresholds/rules/rollups, the Python reference sha, the #263-A tree sha, harness digest and version, the workload manifest digest, and the owner's ratification |
| **C2** | a detached attestation in a **descendant** commit — the payload's commit sha, its blob sha, the sha256 of its **exact bytes**, the instrument/reference/workload bindings, and the ratification binding |

An earlier implementation used the same two letters for something else: `c1` and
`c2` were sections *inside* one payload, with `c2` holding threshold values. The
word had quietly changed profession, and an equivalent-looking scheme is not the
frozen scheme. It had no equivalent at all of `payload_blob_sha`, of exact-byte
hashing, or of the ancestry requirement.

The verifier now proves, in order: the payload declares its kind and schema and
carries every required field; its protocol section is **present and never read**
(those values are thresholds); its bindings equal what this process observes; a
detached attestation exists, declares its own kind, and is complete; its
`payload_sha256` equals the sha256 of the payload's **exact bytes**, not a
canonical re-serialisation; its `payload_blob_sha` equals the payload's git blob
at `payload_commit_sha`, and the working-tree bytes are that blob; its own
commit is a **strict descendant** of the payload commit; and its bindings and
ratification binding equal the payload's.

**One guard is defensive and untested.** A same-commit state — where the
attestation's `payload_commit_sha` names the commit that contains the
attestation — cannot be constructed with ordinary git, because the attestation
would have to contain the sha of a commit whose sha depends on the attestation.
The guard stays, because "cannot currently be built" is not "cannot exist", and
it is recorded here as untested rather than faked with a mocked git.

### The Python reference is not `HEAD`

`python_reference_commit()` returned `git rev-parse HEAD`. That is not the
reference; it is wherever the repository happens to be standing. Every commit
moved it, evidence-only commits included, which is how run A and run B of one
pair recorded two different "reference" identities while `ownlang` had not
changed a byte.

Worse at D7: the freeze creates a C1 commit and then a C2 commit, so a correctly
executed freeze would itself invalidate the reference binding it had just
written down. An alarm that counts its own installation as a break-in.

The reference commit is now the last commit that **touched the reference
source**, and a `python_reference_tree` records that source's content-addressed
git tree object beside it. The commit sha names a label; the tree object shows
two artifacts saw the same bytes. Both are in `PAIR_IDENTITY_FIELDS`.

### The anchor is provenance, not the current position

`IdentityGate.observe()` computed `instrument_tree_sha = git rev-parse HEAD` and
C1 was required to equal it. That check can never pass in production, and the
reason is written on the lifecycle itself:

    S  (the accepted #263-A tree)
      -> C1  the payload commit
        -> C2  the detached attestation commit
          -> #263-B runs here

By the time #263-B runs, HEAD is at least C2. It is not S and cannot be made to
be S. Writing the future C2 sha into C1 in advance is not a workaround, it is
asking a content-addressed commit to contain a value that determines it.

The defect is doubly embarrassing because the fix for its twin is three lines
away and argued in full: `python_reference_commit()` stopped being
`git rev-parse HEAD` in the previous round precisely because "a correctly
executed freeze would itself invalidate the reference binding it had just
written down". The same sentence was true of `instrument_tree_sha` and it went
unread.

So the anchor is now **declared by C1 and proved by content**:

| | |
|---|---|
| declared | `instrument_anchor_commit` — S, the accepted #263-A source commit |
| proved | the instrument **at S** hashes to the `harness_digest` C1 froze |
| proved | S is an ancestor of C1 |
| never required | that HEAD equal S, C1 or C2 |

The rest of the chain was already proved: C1 is a strict ancestor of C2, and C2
is located by `git log` in HEAD's own history. So `S <= C1 < C2 <= HEAD` falls
out without asserting a position anywhere. Because the workload manifest is one
of the `INSTRUMENT_SOURCES`, proving the harness digest at S also proves the
manifest at S — there is no second anchor check to write and no second anchor
check to get wrong.

`harness_digest()` reads the working tree and `harness_digest_at()` reads git
blobs at a commit, and the anchor proof compares one against the other. They
therefore share **one** formula, `_harness_digest_from`. Two implementations of
"the same" formula would make that proof a comparison of two functions, and
their agreement would mean nothing.

#### Why the fixtures could not see it

`_build_freeze` committed a README and two JSON files into a throwaway
repository, and took `observed` from the **real** one. The payload was therefore
built from the same HEAD the gate then compared it against, and the single thing
the production lifecycle does between acceptance and #263-B — move HEAD past S —
could not happen. The fixture isolated production from exactly the effect it
existed to check, which is the third time in this PR that a green control has
proved only what it was asked to prove.

The fixture now commits the real `INSTRUMENT_SOURCES` at S, does ordinary work,
freezes C1 and C2, and then **keeps committing**. `perf-gate-arms-by-data`
asserts that the anchor, C1, C2 and HEAD are four distinct commits, so if the
fixture ever stops reproducing a moving repository the control says so instead
of quietly passing. Reinstating `anchor must equal HEAD` makes a valid freeze be
refused, which is the regression test for the original defect.

### A preregistration is not three strings

C1's protocol was three key names checked for presence, and the fixture that
proved the check worked armed the gate with

    thresholds = "<frozen by D7, never read by the gate>"
    rules      = "<frozen by D7, never read by the gate>"
    rollups    = "<frozen by D7, never read by the gate>"

Two immaculate git commits, three celebratory strings, and the decisive firewall
opens.

The gate still must never **read** a threshold — a #263-A artifact that quoted
one would leak the number this module exists to keep out — but that says nothing
about whether the preregistration is *there*. Those are different questions and
only one of them was being asked. C1 now has to carry, per cell:

| | |
|---|---|
| `dimensions` | `phase`, `workload_id`, `platform`, `regime` — all four |
| the rule | `bound`, `pass_fail_rule`, `inconclusive_band`, `comparison_statistic`, `rss_policy`, `allocation_policy` |
| `repetition_ladder` | `initial_n`, `escalation_stages`, `transition_predicates`, `max_n`, `terminal_outcome` |
| or | an explicit `not_applicable` **with a stated reason** |

and roll-ups at all three preregistered levels: `workload_class`, `phase`,
`overall_g3`. A bare `not_applicable: true` is refused, because it is a way of
writing "no rule" that reads like a rule.

`_present()` inspects presence and container shape only. A blank string, an
empty list and an empty object are structurally absent however confidently they
are typed. Nothing compares, orders, or records a value, so no threshold can
leak through the verifier — and the fixture's own cells are filled with
deliberately non-production placeholders, because a fixture that only passed
with plausible *numbers* would prove the gate reads thresholds.

Every message names the field it is about, so each of the ten new damaged
freezes is matched to the check that owns it. One broad "malformed protocol"
refusal would let a dozen missing checks hide behind a single passing case.

**Completeness was recorded here as not implementable, and that was wrong.** See
the next section: the decisive population is knowable before the freeze, and
checking that every cell was decided selects nothing.

### `not_applicable: true` was accepted, and the PR said it was not

`_present()` returned `value is not None` for anything that was not a string,
list or dict. In Python a `bool` is an `int`, so:

    _present(True)  -> True
    _present(False) -> True

Both `{"not_applicable": true}` and `{"not_applicable": false}` passed a check
whose entire purpose was to demand a **stated reason**. The PR description
asserted that a bare `true` was refused. It was not, and I had written that
sentence without testing it — a claim about a guard, published, untested, in the
same document that argues a green gate proves only what it was asked to prove.

Two repairs, because the boolean hole is a class and not an instance:

- `_present()` now rejects `bool` outright, checked **before** `int` since a
  bool is one. A yes/no is never a preregistered decision, for any field.
- `not_applicable` must be a **non-empty string**. A reason in words, or the
  cell is not decided.

And a cell may no longer be both: carrying `not_applicable` alongside any rule
field is refused, because a preregistration that is simultaneously applicable
and inapplicable is not a decision, it is a superposition.

### A payload that decided half a percent of the experiment

The verifier checked every cell it was handed and never asked whether it had
been handed them all. D7 does not say "at least one well-formed cell"; it says
**for every applicable (phase × workload-id × platform × cold/warm regime)
cell**. So a payload with one immaculate cell and three roll-up strings passed.

The old fixture demonstrated the hole rather than catching it: `_valid_payload`
carried three synthetic cells and armed the gate.

`expected_d7_cells()` now enumerates the universe from data the instrument
already holds:

| axis | source | count |
|---|---|---|
| phase | the frozen `PHASES` taxonomy | 11 |
| workload id | the frozen decisive manifest, **aliases resolved** | 12 |
| platform | `D7_PLATFORMS` | 2 |
| regime | `D7_REGIMES` | 2 |
| | **cells D7 must decide** | **528** |

The gate refuses a payload with any cell **missing**, any cell **unknown**, or
any dimension tuple named **twice**. Each expected cell needs a complete rule or
an explicit `not_applicable` with a reason.

Three things this deliberately does *not* do. It does not read a value, so no
threshold passes through it. It does not decide applicability — the payload does
that, and the gate only proves the owner decided *something* about every cell.
And it does not enumerate over the running platform: the universe covers **both**
platforms wherever the gate runs, because #263-B runs on both and a Linux gate
demanding only Linux cells would let half the experiment through unfrozen.

**The alias earns no second vote.** `large-solution-control` is `alias_of`
`oss-ShareX.sln` — the same path at the same pin, declared under its own id
because #262's gate names it, and recorded as an alias precisely so it is never
counted twice in a denominator. `canonical_workload_id()` resolves it, so the
two ids are one cell; a payload naming both for the same phase/platform/regime
is refused as a duplicate. A completeness check that missed this would have
turned a double-counting safeguard into a double-counting machine.

**Why this is knowable before the freeze, and not a threshold decision.** The
brief permits enumerating, hashing and availability-checking decisive workloads
before D7 and forbids only performance exposure. It has to permit it: if the
decisive population were not known before D7, D7 could not be written. Nothing
here selects a budget, an `N`, or a tolerance. An earlier revision of this note
argued that completeness "needs the decisive cell population" and recorded it as
not implementable — that was wrong, and it was wrong in the convenient
direction.

### The completeness check proved the wrong set

The previous round built the expected universe from `PHASES`. That is the
**attribution** taxonomy — it answers "what did this timed interval contain", so
a rung can be described honestly. It is not D7's vocabulary, and using one as
the other produced a universe that was wrong in both directions at once:

| | |
|---|---|
| demanded | a preregistered rule for `cli-argv-parse`, `cli-usage-refusal`, `ownir-door-refusal` and `frontend-extraction` on every workload, platform and regime |
| omitted | the **end-to-end C# run**, one of the metrics the G3 verdict weighs most, which has no entry in `PHASES` at all because it is a *rung*, not a part |

The code had already said so and was not listened to. The accept fixture keyed
its not-applicable slice on `phase == "frontend-extraction"`, auto-excusing all
48 of those cells — the instrument admitting they were never D7's business while
the universe went on requiring them. A check that manufactures an obligation and
then ceremonially forgives it is not a check, it is paperwork.

`D7_PHASES` is now separate from `PHASES`, and the relationship between them is
**data**, not coincidence:

| set | meaning |
|---|---|
| `D7_PHASES` | the 8 G3 cutover metrics a rule is preregistered for |
| `D7_NON_METRIC_PHASES` | attribution components that are **not** gates, each with the reason recorded |
| `D7_METRICS_WITHOUT_PHASE` | a D7 metric with no single attribution phase — `end-to-end-csharp` is the launcher-e2e rung's whole interval |

`d7_vocabulary_problems()` enforces that every attribution phase is either
promoted to a metric or explicitly excluded **with a reason**. Neither is a
default, so a phase added to `PHASES` later cannot silently join or silently
miss the D7 universe. It runs in `--selftest` as well as in a control, because
the failure mode is drift rather than a wrong line.

The universe is now 8 metrics x 12 canonical decisive workloads x
2 platforms x 2 regimes = **384** cells.

**The names were provisional; they are now RATIFIED.** They were written down as
provisional because the defect being fixed here is exactly what happens when an
implementation label is left to become a normative contract by default.

The owner has since ratified the mapping against the frozen
`prompt-263A-measurement-design-4.md`, the final D7 brief and live #262, at exact
head `0374793`:

| ratified as a D7 metric | why |
|---|---|
| `process-startup-core`, `process-startup-launcher` | frozen #263-A makes child-core startup and public-launcher startup **two** metrics, not one |
| `ownir-parse`, `bridge-lowering`, `analysis` | G3 performance phases named in the frozen text |
| `render-human`, `render-sarif` | the frozen "CLI/SARIF rendering" item, as its two concrete surface metrics |
| `end-to-end-csharp` | the whole user-visible rung, correctly separate from the attribution parts it contains |

| ratified as NOT a D7 metric | why |
|---|---|
| `cli-argv-parse`, `cli-usage-refusal`, `ownir-door-refusal` | attribution taxonomy only |
| `frontend-extraction` | diagnostic population B, excluded by the frozen #263-A itself |

The denominator is ratified with them: **8 metrics x 12 canonical decisive
workloads x 2 platforms x 2 regimes = 384**. The manifest carries 13 decisive
entries, but `large-solution-control` is an alias of `oss-ShareX.sln`, so the
canonical count is 12. Ratifying 384 does **not** mean 384 numeric budgets: an
explicit `not_applicable` with a reason remains a legitimate decision for a
cell. What it means is that the owner must now decide about each one rather than
lose it between two lists.

**The source comment still reads "NAMES ARE PROVISIONAL", deliberately.** At the
commit that wrote it, they were. Editing it now would move the harness digest,
stale both pairs and force an eleventh re-record — relabelling the fire
extinguisher and re-calibrating the laboratory because of it. The ratification
binds here, in the ledger, and to the exact head it was given at.

RSS and allocation deliberately stay per-cell policies rather than becoming a
phase axis; the frozen schema already models them that way.

### The Python reference boundary, closed by observation

`python_reference_commit` and `python_reference_tree` content-address exactly
`PYTHON_REFERENCE_PATH` — `ownlang/`. That is only an honest identity if the
reference's behaviour is confined to what it names. If the measured path read a
schema, a rule table or a config from elsewhere in the repository, the reference
could change behaviour without changing its own sha, which is the same defect
class as an identity that names the checkout.

Settled by observing rather than arguing. An audit hook records every file the
reference OPENS and every process it spawns, on both render surfaces:

| | human | sarif |
|---|---|---|
| repository files opened **outside** `ownlang/` | **0** | **0** |
| processes spawned | **none** | **none** |
| `ownlang/` modules loaded on the measured path | 18 | 18 |

Three further routes were checked and are closed:

- **Static imports.** `ownlang` imports the standard library and itself, nothing
  else in the tree.
- **Config.** `ownlang/config.py` states it explicitly: no auto-discovery, no
  environment variables, no per-path overrides — a config enters only through an
  explicit `--config`, which no rung passes. A file consulted-if-present would
  be `stat`ed rather than opened and would slip past an audit; there is no such
  file to slip.
- **Subprocesses.** The `fix_*` repair pipeline does spawn processes, but none of
  it is loaded on the measured path.

`perf-reference-boundary` keeps this proven rather than asserted, and is
mutation-verified in both directions: a probe that opens `pyproject.toml`, or
spawns `/bin/true`, fails the control.

#### The one residual, not fixed here

`OWNLANG_DEBUG` is read by `ownlang/__main__.py`, and the instrument passes the
ambient environment through unchanged. It affects only the internal-error path —
on a successful run the branch is never taken, so it cannot alter analysis
output — and when it does fire it returns 70, which no rung declares, so the
outcome contract refuses the cell rather than timing it. It is therefore
**fail-closed**, but it is still an uncontrolled input that the reference
identity does not cover.

The fix is to pin or record it in the instrument's environment. That edits
`perf_baseline.py`, moves the harness digest and stales both pairs, so it is
**recorded and not applied**: re-recording is not currently authorised, and this
is worth batching with any other change that moves the digest rather than
spending a re-record on it alone.

### The manifest digest was hashing raw bytes

Round 3 content-addressed the harness digest and left `load_manifest()` hashing
raw bytes two hundred lines away — the same defect with a different variable
name, on a value C1 also freezes. `.gitattributes` pins the manifest to LF, but
an attribute only governs files git checks out under it; a zip download or a
clone predating the rule still differs. Normalization now lives in one function,
`normalized_text`, that every identity uses. The value is unchanged on Linux, so
this closes a Windows exposure without moving any number.

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

### Reproducibility answers three questions, not one

A re-run can disagree with the first run in ways that mean completely different
things, and one verdict cannot carry them.

* **`outcomes_reproduced`** — both runs did the same work: the same cells exist
  and every outcome is identical. A disagreement is a defect in **this harness**
  and always fails.
* **`timings_reproduced`** — the medians agree within the policy. A
  disagreement says the numbers did not settle. It does **not** say why: a
  contended runner, a genuinely variable workload, and a median estimate that is
  simply uncertain at this repetition count are indistinguishable from here.
  Calling it "the environment" would assert one of three causes without
  evidence, which is exactly what an earlier draft of this section did.
* **`environment_valid`** — the noise probe's own verdict.

`reproducibility.reproduced` keeps the meaning it has always had: everything
agreed. It is the conjunction, **not** a renamed subset. A red result must never
disappear because a word changed profession.

All three are required for a report of **record**. A CI leg exists to prove the
instrument stands up, so it may pass while recording `timings_reproduced: false`
as a diagnostic — but the committed calibration may not, and
`perf-provenance-complete` checks all three on the shipped artifact.

### Three policy constants, one historical value

One constant played three roles, and the report claimed the reproducibility
tolerance was "the noise floor recorded by the earlier run, not a chosen
number". That was false twice over: the recorded limit *is* that constant, so
reading it back was reading the constant through a JSON detour, and nothing
about it tightened on a quiet machine.

| policy | bounds |
|---|---|
| `NOISE_PROBE_MAX_RELATIVE_IQR` | dispersion **within** one probe |
| `NOISE_PROBE_MAX_DRIFT` | opening probe **against** closing probe |
| `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` | one cell's median, run A **against** run B |

These are three different statistical quantities. They are separated so each can
be argued about on its own terms. **The value is 0.35 for all three and is
deliberately unchanged**: it is *chosen*, and what makes it admissible is that
it was chosen before the runs it judges and is not adjusted after seeing which
of them it rejects.

### Calibration sizing: one pre-registered experiment

At 5 calibration repetitions a run failed `timings_reproduced` on exactly one
cell of forty — `core-full-human|rust|cal-facts-medium|warm`, median 7.57 ms,
IQR 3.06 ms, so its own observed relative spread was **0.404** against a 0.35
tolerance, and it was the only cell in the run whose spread exceeded it.

The obvious reading — "too few samples" — is a **hypothesis, not a proof**. More
samples reduce the uncertainty of the *median estimate*; they do not reduce the
*intrinsic* spread of the workload's distribution. If that distribution really
is ~40% wide, it stays ~40% wide at any repetition count.

So the escalation was bounded **in advance**:

1. `n=15` is the only permitted sizing escalation from the observed `n=5`.
2. `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` does not move.
3. The `n=5` evidence is preserved as exploratory, non-admissible — with the
   caveat in the paragraph below: the *original failing artifact was destroyed*,
   and what is preserved is a fresh pair.
4. If `n=15` also fails `timings_reproduced`, **stop** — no 25, no 45, no
   turning the knob until CI is green.

`n=15` reproduced on all three axes, and the largest observed relative IQR fell
from 0.404 to 0.128. That is *consistent with* the n=5 spread having been an
unstable estimate rather than the distribution truly being that wide — and it is
equally consistent with a quieter machine. One paired trial cannot separate
them, and this note does not claim it did.

**`n=5` is intermittent.** Across four observed `n=5` pairs it has now failed
twice and passed twice. So the original failure was neither a one-off nor a
systematic insufficiency: on this machine an `n=5` pair reproduces about half
the time. Both halves of the final failing pair are committed in
`docs/evidence/p022-263a-sizing-n5*.linux.json`, deliberately named so they do
*not* match the glob that identifies a report of record.

### A pair is one experiment, or it is two

Run A and run B once diverged on `tree_sha` **and** `python_reference_commit`,
because A was *committed* before B was measured and `python_reference_commit()`
is `git rev-parse HEAD`. Committing evidence between the halves moved the
recorded reference identity while `ownlang` had not changed at all — a direct
breach of the single-reference rule (§12) produced by the procedure rather than
by the code.

The pair-integrity check did not catch it: it compared harness digest,
repetitions and warmup, and said nothing about the reference or the **candidate
binary**. Those pairs happened to use one candidate, but nothing required it, so
a future pair could have compared two different binaries and reported
`reproduced: true`.

**The procedure.** Both halves are measured on ONE clean source commit, written
*outside* the repository, verified, and only then copied in and committed
together. There is no need for A to be committed before B is measured; A must be
committed by the time the evidence ships, which is a different moment.

```
clean source commit S
  run A  -> scratch/<final-name-A>.json          (tree S, dirty false)
  run B  --reproduce scratch/<final-name-A>.json
         -> scratch/<final-name-B>.json          (tree S, dirty false)
  verify identity on every axis below
  copy A and B into the repository
  one evidence commit
```

The scratch files must carry **their final committed names**: `earlier_run.path`
records the basename it was handed, so a scratch name would leave run B pointing
at a file that never ships.

**`PAIR_IDENTITY_FIELDS`** — the 10 axes two halves
must share: `tree_sha`, `tree_dirty`, `python_reference_commit`, `python_reference_tree`, `workload_manifest_sha256`, `harness_digest`, `calibration_repetitions`, `warmup_discards`, `candidate_sha256`, `candidate_bytes`.

An earlier revision of this paragraph listed nine and omitted
`python_reference_tree`, which the code had carried since the reference identity
was separated from HEAD. A prose inventory of a tuple is a second copy of that
tuple, and the second copy is the one that goes stale.

`reproduce()` **refuses** to produce a verdict when any of them differ, so a
mismatched pair is not merely detectable afterwards — it cannot be made. The
control is the second lock, checking the same axes on evidence that already
exists.

### What the corrected pairs actually showed

Re-recording under the fixed procedure was required for provenance, not to
obtain a different answer. It produced a different answer anyway, twice, and
neither is being treated as a result to bank.

| pair | outcome |
|---|---|
| first corrected attempt, `n=5` and `n=15` | both **passed** |
| second corrected attempt (final filenames), `n=5` | **passed** |
| second corrected attempt, `n=15` | **failed** — one cell, `core-full-sarif\|rust\|cal-facts-medium\|process-cold`, 0.361 |
| third, under the D7 §6 / reference-identity repair, `n=5` and `n=15` | both **passed** |
| fourth, under the anchor / protocol repair, `n=5` and `n=15` | both **passed** |
| fifth, under the N/A / completeness repair, `n=5` | **failed** — one cell, `core-full-sarif\|rust\|cal-facts-tiny\|process-cold`, 0.508 |
| fifth, `n=15` | **passed** |
| sixth, under the D7-vocabulary repair, `n=5` and `n=15` | both **passed** |

Running tally on this machine: `n=5` has failed three times and passed seven
times; `n=15` has failed twice and passed six times. Neither count reproduces
reliably, and which one "works" depends on when it was run. Every re-record was
forced by a provenance repair, never sought for a better answer, and the ledger
is kept in both directions for exactly that reason.

**So no calibration of record is restored.** Re-running was authorised to repair
provenance; promoting whichever pair happened to pass would be selection
regardless of why the re-run happened, and by now the coin has been watched land
enough times to know it is a coin. Both pairs ship as **sizing evidence**, pass
and fail alike, and `p022-263a-calibration.linux.json` stays absent until the
variance characterisation says what the measurement model should be.

The previous revision of this paragraph warned that four consecutive passes were
exactly where selection starts to look like evidence, and cautioned against
reading them as a result. The very next attempt failed. That is not a vindication
of the caution so much as a demonstration of what it was about: the streak was
never evidence of anything, and neither is its ending. Across the whole history,
**five distinct cells** have fallen outside tolerance at least once — every one
of them a `rust` cell with a median under 10 ms — while `n=5` stands at three
failures against seven passes and `n=15` at two against six. The run that fails
is not the run that is wrong.

Six attempts in, the sequence reads pass, pass, fail, pass, fail, pass for `n=5`.
Nothing about that is a trend, and the ledger exists so that no revision of this
note can quietly become one.

The failures stay in the ledger and in `docs/evidence/historical/` rather than
being summarised away, and the failing `n=5` pair from this round ships exactly
as recorded. Re-running it to obtain a passing partner would be the precise move
this instrument exists to make impossible to hide.

### Pre-contract artifacts, kept and quarantined

The four artifacts committed before the pair-identity contract existed fail it
by construction: their `earlier_run` blocks predate the fields it requires, and
their halves genuinely were measured under two different reference commits.

They are preserved **byte-identical** under `docs/evidence/historical/`, outside
the glob the live controls scan. Not deleted, because they are the record of a
real measurement and of the defect that produced it; not left in place, because
a control that must exempt specific filenames is a control with a list of
excuses. The alternative — an explicit exemption inside the check — was offered
to the owner and this location was chosen pending any objection; the move is
byte-preserving and trivially reversible.

### The escalation was spent, and it did not work

`n=15` failed too — and failed **worse**.

| pair | cells outside `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` | worst |
|---|---|---|
| `n=5` | 1 of 40 | `core-full-sarif\|rust\|cal-facts-medium\|process-cold`, 0.478 |
| `n=15` | 3 of 40 | `core-usage\|rust\|cal-facts-tiny\|process-cold`, 0.516 |

Both pairs reproduced their **outcomes** exactly and both environments were
valid. Only the timings disagreed. Tripling the repetition count did not reduce
the disagreement; it produced more of it.

This outcome is consistent with the pre-run alternative that increasing N need
not restore reproducibility when the dominant variability is not sampling
uncertainty of the median. It falsifies the narrower operational hypothesis
tested by the preregistered escalation: that moving from `n=5` to `n=15` would
reliably produce an admissible calibration on this setup. It does **not**
establish the cause of the remaining variability, nor distinguish intrinsic
workload spread from between-run environmental variation.

The earlier claim that this was "the predicted result, predicted before the run"
said more than the evidence carries: nothing predicted that `n=15` would fail on
three cells or fail worse than `n=5`. What was stated in advance was only the
alternative above and the stop rule.

**So the instrument currently has no admissible calibration of record**, and one
is not manufactured by continuing to turn the knob. The escalation permitted was
exactly one step, `5 → 15`, with a mandatory stop on failure. It failed. There
is no `n=25`, no `n=45`, and `0.35` does not move — a tolerance adjusted after
seeing which runs it rejects is a threshold fitted to a result, which is the one
thing this instrument exists to prevent.

What is committed instead is all four halves of both failed pairs, as
exploratory evidence, on clean trees, each run B naming its run A by path and
sha256 so the verdicts can be recomputed rather than trusted. The report of
record is **withdrawn**, not replaced: `p022-263a-calibration.linux.json` is
deleted rather than left certifying a superseded instrument.

**An observation, offered as a finding and not acted on.** Every cell that
failed in either pair is a `rust` cell with a median between 2.5 ms and 9.2 ms.
The Python cells, whose medians run 76–111 ms, held. A single *relative*
tolerance is applied uniformly across cells spanning roughly fifty-fold in
absolute duration, and it bites first where the durations are smallest. Whether
the policy should be magnitude-aware is a **measurement-design decision for the
owner**, taken with these numbers visible — which is precisely why this
paragraph proposes nothing.

**Why 15, stated correctly.** Not "because a report of record should carry the
better-estimated median" — that argument does not pick 15. It picks 25, then
100, and then whichever number the budget runs out at. `n=15` is used because
the owner's review, **given before any result was seen**, permitted exactly one
bounded escalation from the observed `n=5` to `n=15`, with every policy constant
unchanged and a mandatory stop if it failed. That `n=15` then came back green is
a **result**, not the reason it was chosen. The distinction is the whole
difference between a preregistered step and a knob turned until CI agreed.

CI keeps `n=5`. Its question is whether the instrument stands up, it may record
`timings_reproduced: false` as a diagnostic, and tripling every leg's runtime to
chase an artifact property it does not produce would buy nothing.

**A record that was destroyed — stated without a euphemism.** The original
failing `n=5` artifact is **lost**. It was discarded from the working tree
before the preservation rule existed, because a control forbids committing a
non-reproducing calibration and the reflex was to revert. What is committed is a
**fresh** `n=5` pair taken under the shipped instrument; it is *not* the run
that prompted the design change. The original observations survive only as
narrative — in this note and in the PR's history — and narrative is not
evidence. A hole in provenance is not a portal to the past, and this document
will not describe it as one.

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
