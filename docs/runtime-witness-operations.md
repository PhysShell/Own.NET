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
pipeline learns to report health it never measured. A refused attach also
writes **no** `runtime.json` artifact — there is no verdict to record.

**Proven by CI:** a denied attach exits 2, names the policy that refused, and
leaves no artifact behind.

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
