# timer-stop-param-guarded

**Pattern.** Stop() on a teardown path but behind a caller-parameter guard: the WPF002 timer pattern's `Stop()`-based release must
use the same teardown doctrine as `-=` (#278) — the caller chooses whether the release runs — same rule as the parameter-guarded `-=`.

**Source.** Hand-reduced from the WPF002 `Stop()` soundness investigation (the
`stopped` set used to credit ANY `Stop()` on the receiver, anywhere in the
class — existence is not execution).

**Honesty caveat.** `case.own` is a hand reduction pinning the ownership
logic; `before.cs`/`after.cs` are the real-C# recall/specificity pair the
corpus benchmark scores through the actual extractor.
