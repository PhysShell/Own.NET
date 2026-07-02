# Subscription released via explicit-delegate `+=` / bare `-=` (release-match FP)

**Pattern.** A view/data class exposes a settable `Source` (an injected
`INotifyPropertyChanged` it does not own). The setter subscribes to the new
source and unsubscribes the old one. The codebase's idiom writes the two sides
**asymmetrically**:

```csharp
_source.PropertyChanged -= OnSourcePropertyChanged;                             // bare method group
_source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);  // explicit delegate-creation
```

Both name the same `(receiver, handler)` pair; the only difference is the `+=`
wraps the handler in a `new …Handler(...)` delegate-creation and the `-=` does
not. This is the dominant subscription shape in SectorTS
(`BrokerDataClasses/BranchDescription.cs` `Address` setter, and ~250 more).

**The bug (Own.NET extractor).** The Roslyn extractor keys release on the raw
handler *text*: `+=` records `new System.ComponentModel.PropertyChangedEventHandler(H)`
as the handler and the `-=` collector stores the bare `H`, so
`unsub.Contains("{left}|{right}")` never matches. Worse, `IsHandler` accepts only
`IdentifierName` / `MemberAccess`, so a `-= new …Handler(H)` is not even collected,
and the P-004 static-handler exemption is skipped for a `+= new …Handler(StaticM)`.
Net effect: a correctly torn-down subscription is reported as an unreleased leak —
a false positive. The fix normalizes a delegate-creation to its inner handler
before keying (extractor `Unwrap`), so the wrapped `+=` and the bare `-=` match.

**What the checker says (`.own` reduction).** Modelling the setter as one scope,
the unreleased token in `before.cs` is the generic **OWN001** (owned resource not
released on all paths), carrying the resource-kind tag:

```text
$ python -m ownlang check corpus/wpf/subscription-explicit-delegate-release/case.own
case.own:…: error: [OWN001] 'sub' is owned but not released at end of function
  [resource: subscription token]
```

**Regression guard.** `scripts/benchmark.py` runs the real C# through the
extractor + core: `before.cs` must be **caught** (the leak is real) and `after.cs`
must be **silent** (the release is recognized). Before the `Unwrap` fix, `after.cs`
falsely reports OWN001 → the benchmark's specificity gate fails; after it, silent.

**Honesty / scope.** `case.own` is a hand reduction that carries only the
acquire/release logic; the syntactic `+=`/`-=` asymmetry that the extractor must
normalize lives in `before.cs` / `after.cs`, which are representative of the real
SectorTS idiom, not a verbatim copy of one file.
