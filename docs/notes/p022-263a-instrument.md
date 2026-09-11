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

On POSIX the same `wait4` call also carries the child's CPU split, fault counts
and context-switch counts. Those are now kept rather than discarded — see *The
interval kept its meaning and gave up its secrets* — under the same rule: off
POSIX they are `null` with a reason, never zero.

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

**Since fixed, batched with the mypy work** — both edits move the harness digest,
so doing them together costs one staleness event instead of two.
`REFERENCE_ENV_PINNED_UNSET` names the variables the reference reads that its
content-addressed identity does not cover, and every measured invocation clears
them. The same reference source can no longer behave two ways depending on the
shell it was launched from.

### The instrument is type-checked now

`scripts/perf_baseline.py` was outside `mypy`'s file list, so "Success, 43 files"
never covered the file that produces the numbers. It is in the list now — 44
files — and passes `--strict`.

The 42 errors it exposed were almost entirely one root cause: values parsed from
JSON are `object`, and the code called `.get()`, `int()` or `float()` on them
behind `x or {}` idioms with `# type: ignore` comments that had drifted to the
wrong error codes. Four narrowing helpers — `_as_obj`, `_as_list`, `_as_int`,
`_as_float` — say it once, to the reader and the checker at the same time.

They narrow in the **fail-closed** direction. A non-object where an object
belongs becomes empty, so the caller's own completeness check refuses it, rather
than raising an `AttributeError` three frames from the cause. `_as_int` and
`_as_float` reject `bool` for the same reason `_present` does: a yes/no is not a
measurement.

Six errors were not narrowing at all: `ctypes.windll` and `Popen._handle` exist
on Windows and are absent from the stubs mypy checks against on Linux. Those
carry targeted `type: ignore[attr-defined]` comments — one API each, with the
reason recorded — rather than a blanket suppression that would also hide the
next real defect.

**No control changed and none was weakened**: 15/15 throughout, and the full
suite stayed green at every step, which is the only reason to believe a
mechanical rewrite of this size did not quietly alter behaviour.

### The interval kept its meaning and gave up its secrets

`Harness._run_once` reaped every child through `os.wait4`, which hands back the
kernel's complete per-child accounting, and then read one field of it. The other
six — user CPU, system CPU, minor faults, major faults, voluntary and
involuntary context switches — were fetched and dropped on the floor.

That mattered because those six are exactly the fields that separate the
candidate explanations Round 7 exists to separate. A wall-clock difference with
no CPU difference and a context-switch difference is a scheduler story; the same
wall-clock difference with a matching CPU difference is a work story. Without
the accounting, both look identical and the round can only report that something
got slower.

They are kept now, under four constraints, each of them a way the change could
have been made wrong:

| constraint | why |
|---|---|
| `ru_utime` / `ru_stime` **rounded** to nanoseconds | everything else in the harness is ns; truncation would bias every sample the same direction, and a systematic half-tick error survives averaging in a way a symmetric one does not |
| the interval **unchanged in meaning** | `t0`, `Popen`, `wait4`, `elapsed`, exactly as before. The rusage is parsed after the clock stops |
| the two pre-existing lines between `wait4` and `elapsed` **left where they were** | moving them would tighten the interval. A tightened interval silently un-compares every future number against every recorded one, which is a worse defect than the slightly loose interval it would fix |
| off POSIX, `null` **with a reason** | there is no Windows equivalent that means the same thing. A reported `0` minor-fault count for a platform nobody asked would be the most confident possible lie, and a median over such zeros would look exactly like a flat measurement |

The fields reach the report too, not just the private Round 7 driver. A cell
carries `accounting` (summarized per field, in `ns` for the two durations and in
`count` for the four counters), `accounting_unavailable_reason`, and
`raw_accounting` per iteration. A harness that collected the accounting and then
dropped it one layer up would be the same defect wearing a different hat.

**`perf-child-accounting`** is the sixteenth control, and it checks the claim
that would otherwise be invisible: that the parse sits outside the clock. It
does that by making the parse expensive — `os.wait4` is wrapped so every rusage
field costs 10 ms to read — and then asking whether `elapsed_ns` grew. If the
harness read seven fields inside its own stopwatch, it would bill 70 ms of its
own bookkeeping to the process it was measuring, and the check would see it.

Seven mutations were run against the finished control, each caught by the check
that owns it:

| mutation | caught by |
|---|---|
| `ru_utime` returned unconverted, in seconds | `cpu_user_ns = 0` for a child burning tens of milliseconds |
| `int()` instead of `round()` in the conversion | the conversion table, at the nanosecond |
| the rusage parsed before `elapsed` | 174 µs outside the interval against 49 ms of deliberate delay |
| zeros instead of `None` on the non-POSIX path | six fields present where none was measured |
| the cell dropping `accounting` again | a cell carrying no accounting slot |
| a field name colliding with `elapsed_ns` | the row-key collision check |
| a field with no declared unit | the `ACCOUNTING_FIELDS` / `ACCOUNTING_UNITS` symmetric difference |

The last two are worth their own line, because the first version of them did not
work. Both faults make `measure_cell` raise `KeyError` partway through a cell, so
the control appended its finding to a list and then died two steps later — CI
would have shown a traceback naming the crash site and no `FAIL` line naming the
cause. The checks are terminal now: they report and return before reaching the
code their own subject breaks. A check that cannot survive long enough to speak
is not a check, which is the same lesson as the last several, arriving from a
direction I had not been watching.

The non-POSIX branch is exercised on Linux by forcing the RSS mechanism, which
drives the real branch of the real function. It is **not** a Windows test and
the control says so; what it proves is that the absence path states an absence.

### The Round 7 apparatus is not the instrument, and the digest proves it

`scripts/round7/` holds a classifier, an ELF reader, arm B's padding source and
the B1–B4 preflight. None of it is an instrument source, and the harness digest
is **unchanged at `562a7f7232da`** across the whole addition — which is the point
worth recording. A round's apparatus that quietly joined `INSTRUMENT_SOURCES`
would restale every pair and, worse, would put the reading of an experiment
inside the thing the experiment measures.

**One classifier, and the controls are wired to it.** `classify.py` is the only
implementation of P1–P5; a second copy would be a second opinion and the reading
could then choose between them. `round7-outcome-exclusivity` evaluates it over
50,653 exact rational triples — sixths, so the ratified edges `3/2`, `3`, `2/3`
and `2` land exactly on grid points rather than near them — and reports which
rule pairs overlap and where. Exact `Fraction` arithmetic throughout: a binary
float `2/3` would decide the `(2/3)B ≤ C` edge by rounding direction rather than
by the preregistered rule.

The census is run twice. Once against the real rules, which must overlap only at
`A = B = 0`; once against the previous draft's P1, which must be reported broken.
A control that has only ever seen correct input is a control nobody has tested.

**Six mutations of the real classifier, each caught by the check that owns it:**

| mutation | caught by |
|---|---|
| the old overlapping P1 restored | P1 found overlapping another rule |
| the zero guard widened to `A or B` | `A=1, B=0, C=4` refused instead of classifying P2 |
| the zero guard removed | `A=B=C=0` raising instead of routing to P5 |
| ambiguity resolved by precedence rather than raising | the classifier returning one answer where two rules fire |
| P4's edge made strict | `C = 1.5A` falling through to P5 |
| an epsilon smuggled into the zero comparison | a tiny non-zero `A` being refused |

The second one is the one that matters: it is the guard I proposed and the owner
rejected, and the control now refuses to let it back in.

**And the crash-before-reporting defect recurred.** Removing the zero guard makes
`A=B=C=0` fire P2, P3 and P4 at once, so the classifier raises and the control
died on a traceback — exit code non-zero, mutation scored CAUGHT, no `FAIL` line
naming anything. Identical in shape to the finding recorded one round earlier,
in a file written after it. The control catches the raise and reports it now.
Twice in two rounds suggests the habit is to check that a mutation *fails*
rather than that the *check* speaks, and reading the output rather than the exit
code is what caught it both times.

**The preflight reads the ELF, not a rendering of it.** `elfread.py` parses
program and section headers directly. B1 locates the padding through `st_shndx`,
which names its section outright, rather than by matching its address against
section ranges — an inference that quietly finds nothing at all for a
non-allocated section, whose address is zero. That distinction is not
theoretical: it is exactly what the B2 damage case constructs.

The four damage cases are **built**, not simulated. A real linker really does
drop an unreferenced non-`volatile` constant under `--gc-sections`; a section
emitted through inline asm with empty flags really is absent from every
`PT_LOAD`. The first attempt at that second case failed to produce the damage at
all — gcc marked the custom section `SHF_ALLOC` anyway and B2 passed it
correctly — which is why the mutation was checked before being believed.

### The execution contract, and a defect that keeps coming back

The Round 7 apparatus classified correctly and measured nothing, which turned
out to be three different silences. The owner's implementation review passed the
code and then asked what the design still did not say: **which bytes get timed,
in what order, doing how much work.**

**Which bytes.** The committed preflight proves properties of specific sha256s.
Any runner that preflighted, dropped its temporary directory, rebuilt and then
measured would be proving things about one pair of arms and timing a different
pair with the same filenames. `runner.py` is therefore one transaction — bind,
build once, preflight *those* files, freeze sha256 and byte length, then time
*those same* files with identity re-verified before every block and after the
last, all outside the clock.

**In what order.** The preregistration fixed session and half counts and said
nothing about order, which is enough to lose the whole round: all of A, then all
of B, then all of C, and an hour of machine drift becomes "the effect of the
real binary" — a result that would have survived every other check in the PR.
Blocked randomisation now: 40 blocks of `(regime, n, session)`, all three arms
inside each block with an arm's halves adjacent, arm order and block order both
deterministically shuffled, seed and planned and actual order all recorded.

The seed is `0xf937b36bd4dac422`, the first 16 hex digits of the Round 6
helper's sha256. Not a number I picked: a literal of my own would be equally
deterministic and strictly less auditable, since nothing but my word would stop
me re-rolling it until the printed order looked tidy. A control compares the
constant against the committed artifact.

**How much work.** "The Round 6 helper at its 2 ms rung" was prose. It is now
read from the ladder that established it — 460280 iterations — with a stop
condition requiring arm A's sha256 to equal that file's `helper_sha256`. Arm A
as built already **is** that helper, byte for byte, so nothing needed
recalibrating. If a future build differs the round stops rather than hunting for
a new iteration count, which would be a knob turned after authorisation.

**Nine mutations, and the third recurrence of one defect.** Eight came back with
a finding that named the cause. The ninth — hard-coding the work count instead of
binding it — exited non-zero with no `FAIL` line, because the control crashed
before reporting. That is the same shape recorded twice already.

It was caught this time because the mutation runner itself was changed to demand
a `FAIL` line rather than a non-zero exit, having been fooled by exactly this
twice. The crash then exposed a genuine defect rather than a test artifact:
`bind_work` called `Path.relative_to(ROOT)` and raised `ValueError` on any ladder
outside the repository, which is precisely what a fixture passes it. Both were
fixed: the path now falls back to a bare name, and the control reports an
unexpected raise instead of dying on it.

The lesson has now cost three rounds, and the durable fix was not another
resolution to be careful. It was making the tool that scores mutations unable to
accept silence as success.

### The sample was clamped in the vice, and nobody checked it was alive

Round 7 called `Harness._run_once` directly. That gave it the instrument's
measured interval and skipped the layer wrapped around it — the layer that
exists because twelve cells once timed `command-not-found` accurately,
reproducibly, and to no purpose.

So the round had three arms bound byte-for-byte to the right binaries, running
in a preregistered order, doing a work count traced to a committed ladder, and
**nothing checked an exit code**. All that identity work would have measured the
wrong path with great precision.

The fix is Round 7's, not the instrument's: `perf_baseline.py` is untouched and
the digest stays `562a7f7232da`. Before the clock, each arm proves untimed that
it does its job — A and B must exit 0 at 460280 iterations; arm C goes through
the instrument's own `core-usage` rung, `expect_rc` 2 **and** the `usage-help`
evidence, reused rather than restated. Then every spawn, warmup discards
included, must exit its arm's code, and one stray stops the round and records
arm, block, half, warmup-or-sample, index and the observed code.

Exit 2 alone is not sufficient and a control proves it rather than saying it: a
stand-in that exits 2 and prints nothing is handed to the preflight and refused.

**Seven mutations, and three of them found holes in my own control** — which is
the part worth recording:

| mutation | first result |
|---|---|
| timed rc check removed | caught |
| warmups no longer checked | caught |
| every arm expected to exit 0 | **crashed the control** — no finding |
| arm C judged by exit code alone | **missed** — the control read the contract string, not the decision |
| the outcome preflight not a stop condition | **missed** — never tested |
| `usage-help` stops requiring stdout | caught |
| `usage-help` tolerates stderr | caught |

The crash was the fourth appearance of the same ghost, and it was visible only
because the mutation runner now refuses to score a non-zero exit as CAUGHT
without a `FAIL` line. The two misses were worse in kind: checks that passed
happily while the thing they described was broken. One asserted that arm C's
contract *string* named the rung, which stays true however the verdict is
computed; the other never existed at all.

All three are closed and all seven now come back with a finding. The general
lesson is getting expensive to keep relearning: a control is not evidence that
something works, it is a claim that needs its own adversary — and the cheapest
adversary available is a mutation runner that will not accept silence.

### Refusing correctly is not the same as recording the refusal

The Round 7 runner refused a bad run properly and then lost the evidence. The
breach escaped `run()`, so `main()` never reached its own `--out` write: 239
halves measured, a stray exit on the last one, a traceback, and no file. The
instrument fell down the stairs gracefully and left no black box.

The control was the same mistake one level up. It read `exc.strays` from the
exception object and called that "recorded with arm, block, half and index" —
in memory, where nobody at 3am can find it. It is the same family as scoring a
mutation by its exit code: read the thing, not a proxy for it — and this is the
first time the measurement runner itself played the part.

One boundary now catches every `ExecutionContractBreach` and writes
`run_valid: false`, null `measurements`, and a structured `abort` naming either
the exact spawn (arm, block, half, warmup-or-sample, index, observed and
expected rc) or the exact arm (when, expected and observed sha256). Completed
halves survive as `partial_measurements`, flagged `not_evidence` with the reason
attached. `time_half` raises on the first stray instead of finishing the half.

`round7-durable-refusal` never inspects an exception. It drives the runner to a
forced stray and to a real mid-run identity drift, then reads the filesystem.

**And it crashed on its own first mutation.** Removing the try/except — the
original defect, restored — let the breach escape through `rn.main()` and kill
the control instead of being reported by it. Fifth appearance of the same shape,
this time inside the control written to detect that shape. The mutation runner's
insistence on a `FAIL` line is the only reason it was visible. `drive()` now
converts an escaping exception into a finding.

Seven mutations, all caught with a finding: the original escape, exit 0 on an
invalid run, measurements retained, `run_valid` never falsified, the abort
reduced to prose, identity drift losing its kind, and a half that keeps spawning
after a breach is known.

### The instrument measured something, and the answer is "not here"

Twelve review rounds built an apparatus to make one measurement honest. The
measurement ran once, on the exact head the owner pinned it to, and the formal
outcome is **(process-cold P4, warm P5)**: the witness did not reproduce in the
cold regime, and the warm regime declines to say.

240 halves and 2640 spawns, every exit code contracted and checked, zero
strays, zero identity drift. The accounting is worth stating exactly, because
one careless noun turns a true sentence false: **2400 retained samples**, of
which 1600 exited 0 (arms A and B) and 800 exited 2 (arm C), plus **240 warmup
discards** whose exit codes were checked on the same contract — any stray would
have invalidated the run — but whose rows are deliberately not retained, because
discarding them is what the `warm` regime means. Half-to-half drift across all three arms landed between
0.024 ms and 0.090 ms. Arm C cleared the P4 boundary in exactly one of the four
cells, `warm` at n=15, and a rule must hold at both counts to fire.

**A provenance claim here was withdrawn, and the withdrawal is the interesting
part.** This note originally said the reading "was written before the data
existed, and that is checkable". The operator did record a pre-clock sha256 of
`scripts/round7/readout.py` — `0f14be8a491d` — but **git cannot check that**:
the file is absent from the authorised head `7ad4a0b` and enters the tree in the
single post-run commit, beside the dataset and the reading. So the word
"checkable" was doing work nothing supported. That is an assertion dressed as a
check, published in the note that exists to argue against assertions dressed as
checks, one round after the same defect was recorded as finding 4.

What the repository does establish is the part the result rests on: **D, the
P1–P5 rules, the zero-A guard, the attribution gates and the stop rule were all
committed before any measurement existed**, and `readout.py` delegates every
classification decision to that frozen `classify.py` instead of restating it.
`round7-readout` recomputes the committed reading from the committed dataset on
every CI run, on Linux and on Windows. The outcome is determined by precommitted
rules and a reproducible application of them; the authoring order of one file is
not load-bearing, and should never have been offered as though it were.

It earned its keep immediately. The synthetic cases caught the author's own
boundary arithmetic *again* — `(A, B, C) = (1, 3, 4)` was asserted to be P3 and
is a clean P1, because `C >= 2B` needs `C >= 6` — the third time in this PR a
hand-checked edge was wrong and a control found it. Then nine mutations found
two more holes: a refusal case that appeared to test the `run_valid` gate but
was actually refused one line earlier by the missing-measurements check, proving
nothing about the gate it named; and a reading that died with a `KeyError`
instead of refusing when a repetition count went missing. Sixth appearance of
crash-instead-of-finding. `read()` now refuses by name, and the control reports
an escaping exception rather than being killed by it.

**Both corrections were owner-found, and the second one bit twice.** Adding a
control for the spawn accounting — so 2400 and 2640 are computed from the
dataset rather than quoted — produced two fresh instances of the same defect in
a row. The first compared `rn.WARMUP_DISCARDS` against a spawn count derived
from `rn.WARMUP_DISCARDS`, so mutating that constant moved both sides together
and the check stayed green: a check reading a proxy for the thing it checks.
The second was worse. The repaired block landed inside an `except` branch, so it
ran only when the dataset failed to read — dead code on every healthy run, while
the control's success line went on announcing that it had verified 2400 retained
samples. An assertion that sounds like a check, written into the edit whose
entire purpose was to remove one, in the file that exists to catch exactly this.
Both were found by mutation, not by reading. The accounting now pins to the
ratified literals and to the dataset's own recorded spawn count, runs before the
reproduction check, and three constant-drift mutations come back with findings.

**The mechanism table was not applied.** P4 fires no elevation and P5 fires no
rule, so neither regime licenses an attribution; the reading records the refusal
and its reason in both. The temptation to look anyway — the numbers are right
there, and `warm` n=15 has a C/A of 3.7 — is precisely what the preregistration
exists to overrule. A P5 that gets analysed until it says something is not a P5.

Nothing moved as a result. No threshold, no budget, no floor, no envelope,
`0.35` not consulted, no session dropped, no re-run. The preregistered stop rule
for P4 or P5 in a regime is "stop after reporting; neither licenses a policy
change", and both regimes hit it.

### The gate was never a missing file

The owner accepted Round 7 and then declined to accept #263-A, for a reason
worth recording carefully: the blockage is **not** an absent artifact named
`calibration-of-record`. §13 of the frozen brief asks for an instrument, a
`CALIBRATION_ONLY` validation report and a fresh exact-head PASS, and all three
exist. But §7 requires a mechanical noise and outlier policy fixed in advance
plus a determinism check, and §9 says a second run on the same environment must
reproduce within that policy or the instrument is **not yet frozen**.

This repository's own evidence says it does not: the sizing pairs do not
reproduce reliably, and `n=5` has passed and failed here in no pattern. Reading
§13 and treating §9 as decorative would have been a very human way through the
gate — produce the JSON with the right name and declare victory — and it is
precisely the move twelve rounds were spent dismantling. We do not need a file.
We need an instrument that says compatible things twice.

`docs/notes/p022-263a-calibration-policy-proposal.md` is the authorised
no-clock answer, and it contains **no numbers on purpose**. Six constants are
named, given units, and left empty, in a table that exists so a later invented
value is visible.

Three things in it are load-bearing.

**The incumbent comparison is not symmetric.** `reproduce()` computes
`|m_B − m_A| / m_A`, dividing by whichever run was recorded first. For tolerance
`T` and ratio `r = m_B / m_A` the forward direction refuses above `1 + T` and the
reversed direction above `1 / (1 − T)`, so for **every** positive `T` there is a
band `1 + T < r < 1/(1 − T)` where the verdict depends on run order and nothing
else. That is algebra about the form, not a number, and it was verified
exhaustively rather than asserted. No committed verdict is known to sit in that
band, and the proposal deliberately does **not** go looking: searching recorded
pairs for one that flips is selection on outcome wearing a lab coat. The
replacement compares `|Δ|` against a bound evaluated at the **midpoint** of the
two medians, which removes the asymmetry by construction.

**The constants must be fitted to dispersion, never to pass/fail labels.** This
is the whole firewall. "Which historical pairs should have passed" is a label
applied after the outcomes were seen; a tolerance fitted to those labels is
tolerance shopping completed in one step, guaranteed to ratify the history it
came from and to predict nothing. A bound fitted to the instrument's own
observed variation as a function of duration is a claim a fresh pair can
falsify.

**N is chosen before the validation pair, not by escalating until it passes.**
"The smallest N at which the pair reproduces" is the same shopping move with
better manners: it turns the stop rule into a starting gun. N is predicted once
from the fitted dispersion model, committed, and tested exactly once.

And the rule that makes the rest mean anything: **on a failed holdout the
constants are not adjusted.** Not widened, not refitted, not re-estimated with
the new data folded in. The policy goes back to the owner as failed.

### A reasonable statistical plan is not a computable function

The owner ruled the policy proposal CHANGES REQUIRED with four P0 findings, and
the sentence that explains all four is theirs: the gap between a reasonable
statistical plan and a single computable function is where people hide knobs.

The verdict universe contradicted itself — three verdicts declared, a fourth
used — and the holdout branch depended on the missing one. The fitting corpus
mixed instruments, allowing constants to be calibrated from stale halves and
museum pieces recorded under superseded harness identities. The fit said "a
quantile at level `q`" without saying how intercept and slope come out of data,
and claimed `q` was fixed by the procedure that consumes it, which is circular.
And `N` selection required predicting dispersion at a given `N` using a model
with no `N` in it, which works beautifully until someone asks where the
prediction came from.

Two things learned while fixing them.

**The tie-break is load-bearing.** Specifying the fit as a non-negative linear
quantile regression solved by exact vertex enumeration is only single-valued if
ties are resolved by a stated rule, because a quantile regression optimum need
not be unique — a whole face of the polyhedron can attain it. Over three hundred
random datasets the optimum was non-unique in thirty-four, and the tied solutions
disagreed in the intercept by a wide margin. Without a tie-break, two correct
implementations return materially different constants and both are entitled to
say they followed the document. The rule is now stated, with a principle it can
be checked against: **a tie is never resolved in the direction that makes the
gate easier to pass.** The vertex-enumeration claim itself was verified against
grid search before being written down, rather than asserted.

**There is no admissible fitting corpus today, and saying so is the finding.**
Applying the firewall honestly to what this repository holds leaves everything as
*form* evidence and nothing as numeric training data under the current harness
identity. Round 7 measured a process-shape A/B/C experiment, not a repeated
calibration population; the same stopwatch does not make it the same statistical
population. So the path forward gains two separately authorised measurements —
one training collection, one holdout — instead of constants squeezed out of the
museum exhibit.

The other repair worth naming: `N` is now a **stratum**, not a parameter. Giving
the model a closed-form `N` dependence would import the assumption that the
dominant variability is sampling uncertainty of the median, which is exactly what
Round 6 declined to establish and named as its own alternative. A functional form
nobody has evidence for is not a repair, it is missing knowledge in mathematical
notation.

### Both pairs are stale, and are not re-recorded

The digest moved from `2d6e52fe4352` to `6713e7300c7c`, and again to
`562a7f7232da` under the accounting change described above, so all four committed
halves describe an instrument that no longer exists. They are **left in
place**: re-recording is a measurement, and new measurements are not currently
authorised. The evidence is stale and says so rather than being quietly
refreshed.

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
