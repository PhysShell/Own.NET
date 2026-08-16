# Running the retention witness: permissions and failure modes

The static half of Owen reads files. The runtime witness reads **another
process's memory**, which is a privileged operation on every operating system
that takes security seriously. This page is the operational contract: what it
needs, what happens when it is refused, and why a refusal is never reported as
a clean result.

The witness lives in [`audit/runtime/RetentionPath`](../audit/runtime/RetentionPath)
and is a standalone tool — it is not part of the published `Owen.Cli` package
today.

## Two ways to read a heap

```console
$ retention-path roots --pid 4213 --type DocumentView   # attach to a live process
$ retention-path roots --dump core.4213 --type DocumentView   # read a dump file
```

**Live attach** suspends the target while it reads, then releases it. It needs
permission to trace that process. **Dump** mode needs only a readable file, so
it sidesteps the entire permission question — if attaching is inconvenient or
forbidden, this is the answer, not a workaround.

## The exit-code contract

| Exit | Meaning |
| --- | --- |
| 0 | The heap was read. `ABSENT` or `OBSERVED_ONLY` — nothing durably retains the type. |
| 1 | The heap was read. `RETAINED` — a durable retention path exists, and it is printed. |
| 2 | **The heap was not read.** Usage error, unreadable target, refused attach. |

Exit 2 is the one that matters here. *Not looking* and *looking and finding
nothing* are different outcomes, and collapsing them is how a monitoring
pipeline learns to report health it never measured.

**Proven by CI:** a denied attach exits 2, names the policy that refused, and
records that it did not look — without recording a verdict.

## The durable record

An exit code lives as long as the process. Everything downstream reads the
`runtime.json` that `--out` writes, so the three states above have to survive
into storage or the guarantee ends with the process.

Representing *"not evaluated"* by writing **no file** does not survive it.
An absent artifact means:

```text
not evaluated  OR  never invoked  OR  the runner died before invocation
               OR  persistence failed        OR  lost in transit
               OR  an older format nothing reads any more
```

Absence has too many preimages to carry meaning, so it is given none:

> **Absence of a record means no durable knowledge, never a semantic outcome.**

Every attempted evaluation writes a record when `--out` is given, and the record
states what happened:

| `execution.state` | Exit | Carries | Meaning |
| --- | --- | --- | --- |
| `observed` | 1 | `scope`, `verdict`, `retained` | The heap was read; a witness is present. |
| `clean` | 0 | `scope`, `verdict`, `retained` | The heap was read; no witness. |
| `not_evaluated` | 2 | `reason.code`, `reason.detail` | Nothing was read. No verdict is recorded. |
| `error` | 2 | `error.classification` | The heap was readable and the walk broke. |

```jsonc
{
  "schema": "own-runtime/1",
  "execution": {
    "state": "not_evaluated",
    "reason": {
      "code": "refused-attach",              // usage-error | unreadable-target | refused-attach
      "detail": "ClrDiagnosticsException: Could not attach to process 4213",
      "policy": "kernel.yama.ptrace_scope=1" // only when a refuser can be named
    }
  },
  "collector": { "tool": "retention-path", "mode": "attach", "target": "4213", … }
}
```

Two things this record deliberately does **not** do.

It does not record a verdict it did not earn. A `not_evaluated` or `error`
record carries no `verdict` key and no `retained` key **at all** — not even
`retained: []`, which downstream reads as *"looked, found nothing"* and would
re-create the collapse one layer up.

It does not claim a refusal it did not observe. `refused-attach` is a statement
about permission, so it is used only where a refusing policy can be named
(`reason.policy`); every other unreadable target gets the weaker, true
`unreadable-target` with the exception in `detail`.

`not_evaluated` and `error` are separated by *where* the failure landed: before
the heap was readable, nothing was looked at and the target is not implicated;
after it, the witness itself broke mid-walk and the target is not exonerated.

**A `clean` with no `scope` is malformed, not weak.** A record that does not say
what was looked at cannot mean "nothing was there", so consumers must route it
down the schema-violation path — never read it as a quieter `not_evaluated`.
`scope` names the population the verdict covered (`instances_on_heap`,
`instances_reachable`, `instances_durably_retained`) separately from the budgets
that bounded only the display (`sample_budget`, `max_hops_budget`), so a reader
can tell a number that constrained the verdict from one that did not.

## Linux: Yama's `ptrace_scope`

On Linux the decision belongs to the kernel, not to Owen. The Yama LSM
publishes its policy at `/proc/sys/kernel/yama/ptrace_scope`:

| Value | Who may attach |
| --- | --- |
| `0` | any process of the same user (classic behaviour) |
| `1` | **only a descendant** — the default on Ubuntu, Debian, and GitHub-hosted runners |
| `2` | admin only |
| `3` | nobody; attach is disabled until reboot |

Under the common default (`1`), attaching to a service you did not start from
this shell is refused *even though you own it*. The raw ClrMD exception does
not explain that, so the witness adds the reason and the ways out:

```console
$ retention-path roots --pid 4213 --type DocumentView
retention-path: ClrDiagnosticsException: Could not attach to process 4213
  the target is alive, so this is a PERMISSION failure: the kernel's
  Yama policy (/proc/sys/kernel/yama/ptrace_scope = 1) forbids attaching
  to a process that is not a descendant of this one. Owen did not look —
  this is NOT a verdict about the target's heap. Options:
    * take a dump and read that instead:  retention-path roots --dump <file> …
    * start the target FROM the witness, so it is a descendant;
    * have the target opt in: prctl(PR_SET_PTRACER, <witness pid>);
    * or relax the policy deliberately and temporarily:
        sudo sysctl -w kernel.yama.ptrace_scope=0
```

The advice is deliberately narrow. It appears only when it could actually be
the cause — a live attach, on Linux, where the target process exists and Yama
is restricting. A typo'd pid gets the plain "process is not running" and no
lecture about kernel policy.

### Choosing among the options

- **A dump** is the right default for anything you did not launch yourself —
  production services especially. No policy change, no privileges, and the
  file can be read somewhere else entirely.
- **Launching the target from the witness** suits reproductions and demos:
  descendants are always traceable.
- **`PR_SET_PTRACER`** is for programs that expect to be inspected and opt in
  themselves. It requires changing the target.
- **Relaxing `ptrace_scope`** weakens a system-wide protection for every
  process on the machine. Reasonable on a disposable CI runner or a developer
  box; think twice anywhere else, and set it back.

### What Owen does *not* do

It does not attempt to escalate, does not retry with `sudo`, and does not
suggest running the whole tool as root. The witness stays inside whatever
permission it was given, reports honestly when that is not enough, and leaves
the policy decision to the operator.

`scripts/flagship-demo.sh` is deliberately **sudo-free** for the same reason: a
demo script that quietly rewrites a kernel security setting is a bad neighbour.
The one place the project relaxes `ptrace_scope` is inside its own CI workflow,
on a throwaway runner, as one visible line.

## Windows

There is no Yama equivalent. Attaching works when the caller has sufficient
rights over the target — same user, or an elevated process for anything else.
Denials surface the same way: exit 2 with the underlying diagnostic, never a
verdict. CI attaches to its own child process, which needs no elevation.

## In CI

Two rules, both worth copying:

1. **Read the exit code, not the output.** Exit 2 means the step failed to
   measure; treat it as a broken step, not as a passing check with an empty
   result.
2. **Relax policy in the workflow, never in the tool.** If a job needs a live
   attach on a runner, the `sysctl` belongs in the job — visible in the log,
   scoped to that machine — not hidden inside a script that people also run on
   their laptops.

Own.NET's own gate does exactly this, and asserts both halves: one step sets
`ptrace_scope=1` and requires the honest refusal; the next sets it to `0` and
requires the full end-to-end demo to produce its retention path.
