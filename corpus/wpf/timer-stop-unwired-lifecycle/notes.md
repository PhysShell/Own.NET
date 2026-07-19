# timer-stop-unwired-lifecycle

**Pattern.** Stop() in a Window_Closing-named method with no wiring: the WPF002 timer pattern's `Stop()`-based release must
use the same teardown doctrine as `-=` (#278) — a lifecycle-looking NAME is not evidence; only a code-wired handler counts.

**Source.** Hand-reduced from the WPF002 `Stop()` soundness investigation (the
`stopped` set used to credit ANY `Stop()` on the receiver, anywhere in the
class — existence is not execution).

**Honesty caveat.** `case.own` is a hand reduction pinning the ownership
logic; `before.cs`/`after.cs` are the real-C# recall/specificity pair the
corpus benchmark scores through the actual extractor.
