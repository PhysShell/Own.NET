# P-022 / #263-A — step 7, the measurement-free environment identity manifest

```text
Status:
  STEP 6 TRAINING PREREGISTRATION PASS / CLOSED.
  ENVIRONMENT CAPTURE TOOLING AUTHORISED.
  ENVIRONMENT PROVISIONING AUTHORISED.
  EXECUTION BINDING AUTHORISED.
  FIRST STEP-7 CLOCK BLOCKED until dedicated Linux and Windows hosts exist
    and the exact binding is frozen against them.
  SINGLE STEP-7 COLLECTION AUTHORISED automatically after that gate.
  STEP 8 FIT, HOLDOUT, D7 / #263-B NOT AUTHORISED.
  NO CLOCK HAS RUN. NO OBSERVATION EXISTS.
```

## Why this is a separate tool and not a harness change

`environment_fingerprint()` in `scripts/perf_baseline.py` records about half of
what the owner's ruling makes identity-bearing. It has CPU model, logical count,
installed RAM, Python version, `rustc`, `dotnet` and `platform.platform()`. It
has no owner-assigned `environment_id`, no host fingerprint, no virtualization
boundary and no power policy, and its OS and kernel detail is only what
`platform.platform()` happens to yield.

Extending it was refused rather than attempted. `perf_baseline.py` is one of the
two files in the harness source set, so editing it moves
`measurement_harness_digest 562a7f7232da…` — the digest step 4 froze, step 5
bound its constants to, and step 6 bound its preregistration to. Preparing step 7
by invalidating the identity steps 4, 5 and 6 were accepted on is a snake eating
its own tail, and the owner named it as such.

## Where it lives, and why that is not arbitrary

Three frozen source sets exist, and the tool is outside all of them:

| set | root | bound by |
|---|---|---|
| harness | `scripts/perf_baseline.py`, `docs/evidence/p022-263a-workloads.json` | steps 4, 5, 6 |
| policy | `scripts/calibration/` | step 4 digest `c3068ed7fa88…` |
| scope | `scripts/training/` | step 6 digest `614bf9efe6ba…` |

The second and third are computed over **every committed `*.py` under the root**,
so a new file dropped into either would move a digest that is already accepted.
`scripts/training/` was the tempting place and would have broken the step-6
binding on the first commit. The tool therefore lives in `scripts/step7/`,
following the existing `scripts/round6/` and `scripts/round7/` convention, and
`envcapture-frozen-untouched` recomputes all three digests on every CI run rather
than trusting this paragraph.

## What it may never do

No clock and no resource observation: no `perf_counter`, no `monotonic`, no
`wait4`, no `getrusage`, and no timing of the subprocesses it uses to read tool
versions. `memory_bytes` is how much RAM the machine **has**, never how much
anything used.

It is deliberately self-contained and does not import `perf_baseline`. If it did,
"this file starts no clock" would stop being provable by reading this file, and
the audit would have to follow an import into the very module that exists to
start clocks.

`envcapture-no-measurement` proves this by walking the **AST**, not the text. The
module's own docstring names `perf_counter` and `wait4` in order to disclaim
them; a text scan would read the prose and call that a finding, which is the same
defect as a check reading a proxy for the thing it checks. The control also
mutates a copy in memory with a real `time.perf_counter()` and requires the
scanner to report it, so its silence on the real module is evidence rather than
an assertion.

## The two-shape field contract

Every identity field is exactly one of:

```json
{"status": "observed",    "value": "<non-empty, non-bool>"}
{"status": "unavailable", "reason": "<non-empty string>"}
```

There is no third state. An empty string, a zero, a bare boolean, a null, a
missing key and a silent absence are all refused, because the difference between
"unknown" and "zero" is exactly the difference this whole track exists to keep.
The boolean case is explicit: `bool` IS an `int` in Python, so an unguarded
numeric test would have accepted `True` as a CPU count — the Round 9 defect,
which this repository has now paid for once.

`environment_id` is the one field for which `unavailable` is itself a refusal. It
is assigned by the owner, not discovered, so its absence is an operator error
rather than a property of the machine.

## Identity versus provenance, which is the owner's ruling made checkable

| identity — drift invalidates the stratum | provenance — changes freely |
|---|---|
| `environment_id`, `host_fingerprint` | `timestamp_utc` |
| `os_build`, `kernel` | `runner_name` |
| `cpu_model`, `logical_cpu_count`, `memory_bytes` | `workflow_run_id`, `job_id` |
| `virtualization`, `power_policy` | `ci` |
| `python`, `rustc`, `dotnet` | |

`RUNNER_NAME` names an allocation, not a machine. Making it identity-bearing
turns the protocol into a farce on any orchestrated runner: either the stratum
self-invalidates on the next allocation, or one pretends different machines are
the same one. `envcapture-identity-split` refuses to let it migrate.

Fields compare **whole**, not by value alone. A field that goes from `observed`
to `unavailable` between runs is drift, and so is a changed reason; reading only
`value` would let an environment go dark unnoticed.

## The candidate sequence, fixed before any of it happens

```text
pin source/tree + build recipe/toolchains
        v
build candidate on Linux host        [UNTIMED]
build candidate on Windows host      [UNTIMED]
        v
record per-stratum candidate_sha256 and candidate_bytes
        v
freeze execution-binding artifact
        v
exact-head binding controls
        v
FIRST CLOCK
```

The two strata will have different SHA and byte length; within a stratum they
must stay identical across all fifteen runs, and a rebuild that changes bytes
after collection starts invalidates that stratum.

## A caveat recorded rather than papered over

`host_fingerprint` hashes the running system's machine id. **Inside a container
that is the container's identity, not the host's.** Run on this development
container the tool reports `virtualization: docker`, which is the honest answer
and one more reason the collection runs on a dedicated machine. The manifest
records `ci` and `runner_name` in provenance, and
`envcapture-ci-provenance` proves a manifest taken on a hosted runner says so,
so it cannot later be presented as host-taken.

## Controls

```text
envcapture-guard-reports         a control that raises is reported, never fatal
envcapture-schema                the declared key set, enforced both ways
envcapture-field-contract        observed/unavailable, with no third state
envcapture-identity-split        provenance can never become identity
envcapture-assigned-id           an owner-assigned id cannot be 'unavailable'
envcapture-drift                 provenance moves freely; identity never does
envcapture-no-measurement        no clock, no resource accounting, by AST
envcapture-reason-fits-platform  an 'unavailable' reason names THIS platform
envcapture-windows-fixture       the schema holds off Linux
envcapture-frozen-untouched      this addition moved none of the three frozen digests
envcapture-ci-provenance         a CI-taken manifest says so and cannot hide it
```

Fifteen mutations, each declaring in advance which control must catch it, and
each scored on a `FAIL` line from **that** control rather than on a non-zero
exit. Two of the fifteen mutate the **control file**, not the tool: the guard is
the durable answer to a defect recorded eight times, so it needs its own
adversary.

## Two defects the campaign found, both real

**The schema could lie about itself.** `capture()` built an identity dict and
then projected it through `IDENTITY_FIELDS`. Adding a name to the declared tuple
without adding a collector made it die with `KeyError` — a traceback rather than
a refusal. `_refuse_drift()` now names the mismatch in both directions.

**A control that crashes before reporting is a traceback, not a finding — the
eighth instance, and this one was mine, in the file written to hold the others to
account.** The mutation that promoted `runner_name` into `IDENTITY_FIELDS` killed
the fixture builder inside the *first* control, so the run died before
`envcapture-identity-split` — the control that owns exactly that defect — could
say a word. The scorer reported MISSED, correctly, because nothing printed a
`FAIL` line. The durable fix is not another resolution to be careful: `guarded()`
turns any escaping exception into a reported failure for that control and lets
the run continue, and `envcapture-guard-reports` makes restoring the bare call a
test failure rather than a story in a session log.

## What the first Windows CI run found, and what it cost

The Windows capture path was described as unverified, and one CI run on
`windows-latest` (Server 2025) made most of it verified and found two defects.

| field | Windows result |
|---|---|
| `host_fingerprint` | observed — the registry `MachineGuid` read works |
| `os_build`, `kernel` | observed — `Windows 2025Server 10.0.26100 SP0 …` |
| `memory_bytes` | observed — `GlobalMemoryStatusEx` works |
| `power_policy` | observed — `powercfg` returns the active scheme |
| `cpu_model` | observed, but **weak** |
| `virtualization` | **unavailable, for a Linux reason** |

**`virtualization` reported "systemd-detect-virt absent or unclear and no DMI
identity under /sys" — on Windows.** That is true of every Windows machine ever
built, and it reads as though a probe ran when nothing Windows-specific had been
tried at all. A stated reason naming the wrong operating system is worse than no
reason. `_virtualization()` is now platform-branched and queries
`Win32_ComputerSystem` through CIM, and `envcapture-reason-fits-platform`
enforces the general rule: an `unavailable` reason may only name mechanisms that
exist on the platform it was produced on. Designing that control immediately
caught a second instance — `_cpu_model`'s repaired reason named both `/proc/cpuinfo`
and `Win32_Processor` in one sentence.

**`cpu_model` fell through a dead tool in silence.** `wmic` is gone from recent
Windows images, so the model name arrived as `platform.processor()`'s
`AMD64 Family 25 Model 1 Stepping 1, AuthenticAMD` — a family string, not the
processor's name, and nowhere near the "cpu model exact" the ruling asks for. The
CIM query now runs first.

**A green run printed a failure.** `control_guard_reports` exercised the guard by
calling it and then deleting the entry from the failure list, which left a literal
`FAIL[envcapture-guard-fixture]` in every passing CI log — exactly the string this
repository's mutation scorer keys on, and the sort of line that teaches readers to
ignore `FAIL`. The guard is now split into a pure `guard_failure()` that returns
the message and a `guarded()` that reports it, so the probe asserts on a returned
string and prints nothing.

## What is still NOT verified

Capture on a **dedicated** Windows host. A hosted runner is not one, and the CIM
virtualization query added above has never executed anywhere, since this container
is not Windows. `envcapture-windows-fixture` exercises the schema and drift rule
on a synthetic manifest and now says exactly that rather than claiming the
Windows branches are unrun.
