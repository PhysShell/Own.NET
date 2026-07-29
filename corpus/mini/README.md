# The frozen mini corpus

Twelve C# files, one supporting-types file, and a promise: **these bytes do not
change casually.** They are the input to the `mini-corpus-diff` job, which runs
`own-check` at a PR's merge base and at its head over exactly this directory and
compares the two normalized results. A corpus that drifts turns that comparison
into a diff of two different questions.

## Why a frozen corpus at all, next to the fixture tests

The fixture tests (`tests/test_ownir_column.py` and friends) pin the contract on
synthetic facts: a hand-written record in, an asserted `Finding` out. They are
fast, precise, and blind to the frontend — a fact fixture cannot tell you that the
Roslyn extractor stopped emitting a field, because the fixture *is* the fact.

This corpus starts one layer earlier, at real C#, and goes through the whole
pipeline: Roslyn → OwnIR facts → the core → SARIF. It is small enough to run on
every PR in minutes, and complete enough that a producer change which alters what
the pipeline says about real code has somewhere to show up.

It is not a substitute for the full corpus run (OwnAudit's
`.github/workflows/corpus-differential.yml`, hours, real trees). It is the gate
that answers in minutes so the long run does not have to be on the PR path.

## What each file is for

| File | Shape | Why it is here |
|---|---|---|
| `_MiniTypes.cs` | supporting types | every `+=` binds to a real symbol without referencing WPF or a third-party assembly |
| `Subscription.cs` | `event +=` with no `-=`, plus a released control | the baseline OWN001 (warning tier — injected source) |
| `StaticEventCapture.cs` | instance handler on a static event | OWN014 region escape: a different rule, a different message, a distinct pattern |
| `Timer.cs` | started, never stopped, plus a stopped control | `[resource: timer]` |
| `DisposableField.cs` | owned `IDisposable` field, plus a disposed control | `[resource: disposable field]` |
| `LocalDisposable.cs` | undisposed local, plus `using` and returned controls | `[resource: disposable]`, and two exemptions |
| `PooledBuffer.cs` | `Rent` without `Return`, plus a `finally`-returned control | `[resource: pooled buffer]` |
| `TwoOnOneLine.cs` | two different findings on ONE line | the case a column exists for — and the collapse case a column must not split |
| `Indentation.cs` | one leak shape at four indentation depths | catches a column taken from the line's indentation instead of the syntax |
| `Advisory.cs` | `+=` on an unresolvable type | OWN050 advisory: compared through the ledger census, not the findings list |
| `Suppressed.cs` | `[OwnIgnore("reason")]`, plus a reason-less control | the suppression census, and the rule that a reason-less ignore does not suppress |
| `DiCaptive.cs` | singleton capturing a scoped service | a finding with **no** column — the mixed-coverage case |

Every positive has a negative control next to it. A frozen corpus without them
can only notice a finding that disappeared, never an exemption that broke — and a
broken exemption arrives as a `new_pattern`, which reads like noise until someone
opens the file.

## The three shapes that are load-bearing

**`TwoOnOneLine.cs`** carries two claims at once. Two *different* subscriptions on
one line must get two *different* columns — if they came back equal the coordinate
is decoration, and the differential's `fabricated_column_collision` check fires.
The *same* subscription written twice on one line must stay **one** finding — the
dedup keys on pattern identity and deliberately not on the column, so that adding
a column cannot change the finding population.

**`Indentation.cs`** exists to catch one specific plausible wrong answer.
`Diagnostic._caret_col` (the renderer's caret heuristic) falls back to the line's
leading whitespace when it cannot find an identifier. A column sourced from that
instead of from the syntax location produces numbers that differ per line and look
entirely reasonable. They are only distinguishable from the real answer when the
subscription does **not** start its line — hence the `if` wrappers and the nesting.
A one-indentation fixture cannot tell the two apart.

**`DiCaptive.cs`** is the file that keeps the expectation honest. DI001 comes from
the registration graph, not from an owned-resource record, so the slice left it
line-only. An expectation that *permits* `null-to-positive-integer` must tolerate
findings whose column stays null; one that *required* every finding to gain a
column would fail here, and the pressure would then be to invent a coordinate for
it — the exact outcome a nullable column exists to prevent.

## Changing this directory

A change here is a **corpus change**, not a producer change, and the two must not
travel in one commit. The differential compares two commits of the producer over
one corpus; if the corpus differs between them, every finding can legitimately
move and the report says nothing.

So: change the corpus in its own PR, with the diff reviewed for what it does to
the findings, and let the `mini-corpus-diff` job run against it once before a
producer change relies on it. The runner records a `corpus.digest` in `run.json`
for exactly this reason — so "the corpus was identical on both sides" is a
checkable claim rather than an assumption.
