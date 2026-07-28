# How Owen proves retention

A lifetime-bug report asks two different questions: can the program prove that
an object's release runs, and is a live process actually holding that object
through a durable reference path?

Static analysis answers the first question. A runtime witness answers the
second for a particular heap snapshot. Owen keeps those claims separate:
source establishes the missing lifetime guarantee; runtime evidence shows what
is holding the object at the moment of observation and where that path leads.

Everything below is either **proven by CI** on every commit, **observed in a
specific run** and named as such, or an **architectural rule** the
implementation follows. Where something is not yet true, it says so. None of
it is a roadmap entry wearing the present tense.

---

## 1. The bug: an unsubscribe that exists but never runs

A settings hub lives for the whole process. Every document window subscribes
to it in its constructor so it can restyle itself. There *is* an unsubscribe —
right there in the class:

```csharp
public void Cleanup(bool keepAlive)
{
    if (!keepAlive)
    {
        _settings.PropertyChanged -= OnSettingsChanged;
    }
}
```

And the close path calls `Cleanup(keepAlive: true)`.

Every closed window stays in the hub's delegate list, with its whole visual
tree behind it. The code review that would catch this has to notice that a
`-=` exists, that it is guarded by a parameter, and that the one caller passes
the value that skips it. Reviewers do not reliably do this. Neither do
checkers that pair each `+=` with any `-=` in the same class.

This is not a hypothetical. It is issue #278 reduced to its bones — a real
production leak where a formally present unsubscribe sat behind a guard nobody
ever passed `false` to, and 66% of the process heap was retained.

## 2. What the static half establishes

`owen check` reads the subscription, the release, and the paths between them.
It flags the subscription when it cannot *prove* the release runs:

```console
$ owen check examples/flagship/wpf/bad --fail-on-finding
DocumentWindow.xaml.cs:28: warning: [OWN001] event '_settings.PropertyChanged'
  is subscribed (handler 'OnSettingsChanged') but never unsubscribed …
```

The word doing the work is *provably*. A release counts when it sits somewhere
the platform itself invokes at end of life — `Dispose`, `DisposeAsync`,
`OnClosed`, `OnClosing`, `OnUnloaded`, `OnFormClosed`, `OnFormClosing` — or in
a handler wired to this object's own lifecycle event (`Closed`, `Unloaded`,
`Disposed`, …), plus anything such a method provably calls, resolved by
symbol rather than by name. A `-=` inside `Cleanup(bool)` reached only through
a parameter that switches it off is not evidence, and neither is a same-named
overload nobody calls.

The fix moves the release into `OnClosed`, unconditionally, and the finding
disappears. Same subscription, same handler — the only change is that teardown
became a teardown.

**Proven by CI:** the `bad`/`ok` pair is checked on Linux *and* Windows on
every run; `bad` must exit 1 with OWN001, `ok` must exit 0.

## 3. Why a static finding is not yet proof

Static analysis answers "is this release provable?" It cannot answer "is this
object actually still held right now, and by what?" Those are different
questions, and the second one is what a developer is really being asked to
believe.

So Owen has a second half: a runtime witness that attaches to a live process
(or reads a dump), finds the instances of a type, and reports the reference
path from a GC root to them:

```text
verdict: RETAINED — DocumentWindow: 200 on the heap, 200 durably retained

AppSettings → PropertyChanged → _invocationList → handler → DocumentWindow
```

That is no longer a claim about the future. It is a path you can read, walk
back to a field, and delete.

Two honest notes. The witness is a **separate step** — it is not part of
`owen check` and does not run on your builds. And it currently lives in
[`audit/runtime/RetentionPath`](../audit/runtime/RetentionPath) as a
standalone tool, not inside the published `Owen.Cli` package.

## 4. Why "reachable from a GC root" is the wrong question

The naive version of a witness marks from every GC root and reports whatever
it reaches. That tool will call almost anything a leak, because *reachable
right now* and *durably retained* are not the same claim.

A local variable in a frame that has not returned yet is a GC root. So is an
object sitting on the finalizer queue. Both mean **"visible at this instant"**
— neither means anything holds the object past this instant. Report them as
retention and every leak hunt drowns in noise; worse, the one real path is
buried among them.

So roots are classified, not counted:

| Kind | Means |
| --- | --- |
| `static-event`, `static-field`, `gc-handle` | **durable** — something outside this moment holds it |
| `stack`, `finalizer` | **transient** — alive right now, that is all |
| `unsupported-root:<kind>` | an honest refusal: this root kind has no mapping yet |

The verdict follows from the classification, not from reachability:

- **RETAINED** — at least one durable retainer. Exit 1.
- **OBSERVED_ONLY** — instances exist and are reachable, but only from
  transient roots. Exit 0. Live right now; not established retention.
- **ABSENT** — no instance on the heap. Exit 0.

An unknown root kind counts as *durable* on purpose. If the mapping is
incomplete, the failure should be loud and visible, never a quietly demoted
verdict.

## 5. Durable-first, because a stack frame can steal the answer

An object can be reachable from a durable root *and* be sitting in a register
at the same instant. A single-pass mark credits whichever root it happens to
reach first, and "first" is an implementation detail of iteration order.

**Observed in a live run on .NET 8:** a `Main` local holding the static
publisher caused the whole retention chain to be attributed to `[stack]` — the
static-event path, the real answer, was invisible.

The rule the traversal is built around: **durable roots are seeded and walked
to exhaustion before any transient root enters the graph.** Transient paths
then explain only what nothing durable can. The invariant that makes this
sound — a target reachable through a durably-claimed node is itself durably
claimed, so transient traversal can never bury a durable path — is written out
in the code next to the loop that depends on it.

## 6. What the first implementation got wrong

Four defects, all found in review, all of the same family: something meant to
bound *cost* silently changed the *answer*.

1. **Sampling decided the verdict.** The walk took the first N instances in
   heap-enumeration order. A type with older garbage ahead of one durably-held
   instance read as clean. Fixed: the root-kind census covers *every* reachable
   instance; `--sample` bounds only how many paths are resolved for display.
2. **Grouping merged unlike paths.** The signature was hop type names only, so
   a stack-rooted and a durably-rooted instance sharing a type sequence
   collapsed into one group and inherited whichever classification arrived
   first — hiding a real retainer or inventing one. Fixed: the signature
   carries the classification and the traversed fields.
3. **`--max-hops` erased the root.** Truncating a long path stopped the unwind
   at an intermediate object, whose root kind was `None` → `unsupported-root`
   → counted as durable → a long stack-only path reported as RETAINED. Fixed:
   the parent chain is walked to the true root for the verdict even when the
   rendered path stays short.
4. **Any reachability was a leak.** Before the classification was consulted, a
   loop local still in a register read as RETAINED.

The principle these converge on, and the one worth taking away:

> Sampling and display limits affect evidence **presentation** — never
> discovery, classification, aggregation, or the exit code.

## 7. The WPF experiment that lied, and what it taught

**Observed in a specific CI round.** The fixed WPF sample reported `0 still
subscribed` — our release had run — and the witness simultaneously reported
200 windows retained through a `[gc-handle]` path at 41 hops. Two credible
readings: WPF retains closed windows, or the measurement was wrong.

It was the measurement. `Window.Close()` finishes through the dispatcher, and
the sample was holding itself open for the witness by parking its UI thread in
a sleep. The application was frozen halfway through tearing the windows down,
and the witness faithfully photographed framework book-keeping mid-teardown.

With the hold changed to keep the message loop running and the count taken
only once the dispatcher goes idle, the same sample reports `ABSENT` — every
window collected, not one root of any kind.

Two lessons, both cheap to state and expensive to learn:

- **A runtime witness is only as honest as the moment you take the picture.**
  Whatever suspends the process for measurement must not also change what the
  process is holding.
- **The assertion that survived this bug was too narrow to catch it.** The
  check asserted "no `static-event` root" — true, specific, and green while
  the sample was misbehaving. An assertion scoped tightly enough to survive
  anything tests nothing. It now asserts the whole contract.

## 8. What CI actually proves

Not "we ran some tests". On every commit, through the **public CLI and its
JSON artifact** — never internal APIs:

| Claim | How it is checked |
| --- | --- |
| The static verdict is platform-independent | `owen check` runs on both Linux and Windows legs and must agree: `bad` → exit 1 + OWN001, `ok` → exit 0 |
| The samples build anywhere | both WPF projects compile on Linux (`EnableWindowsTargeting`); only *running* them needs Windows |
| The leak is real at runtime | on Windows, the sample is launched and held live, the witness attaches by pid, and must report `RETAINED`, exit 1, a `static-event` durable root, and the path anchors `AppSettings`, `PropertyChanged`, `_invocationList`, `DocumentWindow` |
| The fix is real at runtime | the fixed sample must report exit 0, `ABSENT` or `OBSERVED_ONLY`, and **zero** durable roots |
| The classifier's doctrine holds | a heap-free selftest (16 checks) pins the known root kinds and an unknown one, the verdict rules, and the agreement between the traversal-level and verdict-level definitions of "transient" |
| The demo is reproducible | one script builds, holds, attaches, and machine-validates the JSON against the human-readable verdict; a disagreement between them fails the run |

The path anchors are checked as **semantics, not text**: type and field names
that must appear, never a verbatim path with addresses and hop counts, which
would break on any harmless change and prove nothing when it passed.

## 9. Limits, and the operational contract

The honest boundary of all of the above.

**The snapshot is a moment.** The witness reports what is true when it reads
the heap. If the process is mid-teardown, mid-GC, or mid-anything, that is
what it reports (§7). Reading it as "always" is your inference, not its claim.

**`ABSENT` and `OBSERVED_ONLY` are not interchangeable.** `ABSENT` means no
instance was on the heap; `OBSERVED_ONLY` means instances existed and were
reachable, but nothing durable held them. Both mean "no established
retention", which is why the acceptance contract accepts either — pinning one
would be pinning GC timing, which is not a public contract.

**Unknown roots surface, they do not vanish.** A root kind with no mapping is
reported as `unsupported-root:<kind>` and counted as durable. You will see a
verdict you may not like rather than a clean bill of health the tool did not
earn.

**Linux attach is governed by kernel policy, not by Owen.** Live attach needs
permission to trace the target. Where policy allows it, the analysis runs;
where policy denies it — the common default on modern distributions and on CI
runners — the witness exits **2**, names the policy that refused, and writes no
artifact. It does not retry silently, does not escalate, and never converts "I
could not look" into "I looked and found nothing". Running against a dump
avoids the question entirely. The full operational contract, including the
choice between a dump, a descendant launch, `PR_SET_PTRACER`, and relaxing the
policy, is in
[`docs/runtime-witness-operations.md`](runtime-witness-operations.md).

**What is not claimed.** The witness reports retention, not causation: it
shows the reference that holds the object, not the commit that introduced it.
It does not repair anything. And it is not, today, part of the published CLI
package — it is a separate tool in this repository.
