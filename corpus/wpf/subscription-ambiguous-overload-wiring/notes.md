# Subscription whose `-=` sits in the never-attached overload of an ambiguously-named wired handler (soundness FN)

**Pattern (#278 follow-up 2 — the unresolved-overload fallback blocker).** The
class wires `Closing += Window_Closing` where the lifecycle event does NOT
resolve (WPF `Window` base on a Linux runner without the reference pack), and
declares TWO `Window_Closing` overloads. A method group syntactically denotes
its whole overload set, but the runtime delegate attaches exactly ONE member —
selected by the event's delegate signature, which is precisely the information
the extractor is missing. Here the delegate-compatible overload
(`(object, CancelEventArgs)`) detaches nothing, and the `-=` sits in the other,
never-attached overload.

**The bug.** The previous slice's unresolved-event fallback added EVERY
same-named own method to the teardown set, so the `-=` in the never-attached
overload was silently credited as a release — the unresolved twin of the
invocation-overload conflation pinned by
`subscription-overload-conflated-cleanup`.

**The fix.** When the handler binds no definite symbol, the name grounds a
teardown ONLY if it is unambiguous — exactly one `IMethodSymbol` with that name
in the immediate class. Zero or 2+ matches credit nothing and keep the honest
warning. The symbol-resolved path is unchanged: when the event resolves, the
delegate's exact target is credited even among overloads (pinned in the smoke
matrix; `subscription-xaml-name-only-release/after.cs` keeps the resolved
single-handler control). The prior fallback's `CandidateSymbols` crediting is
gone with it — candidates of a failed method-group binding are the same
ambiguous overload set by another name.

**`before.cs`** → OWN001 (ambiguous, `-=` unproven). **`after.cs`** — the
positive control: same unresolved event, exactly one `Window_Closing`, `-=`
inside it → silent (whichever overload the delegate would pick, it is that
one). Both keep the usual OWN050 advisory for the unresolved `Closing +=`
itself.

**What the checker says (`.own` reduction).** The scope acquires the token and
the executed teardown path performs no release => **OWN001** with the
subscription-token resource tag.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**.
