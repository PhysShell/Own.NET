# Subscription released via explicit-delegate `+=` / bare `-=` (release-match FP)

**Pattern.** A view holds an injected `INotifyPropertyChanged` it does not own,
subscribes in the ctor, and unsubscribes in `Dispose`. The codebase's idiom writes
the two sides **asymmetrically**:

```csharp
_source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);  // ctor: explicit delegate-creation
_source.PropertyChanged -= OnSourcePropertyChanged;                                    // Dispose: bare method group
```

Both name the same `(receiver, handler)` pair; the only difference is the `+=`
wraps the handler in a `new …Handler(...)` delegate-creation and the `-=` does not.
The explicit-delegate `+=` is the dominant subscription shape in SectorTS
(`BrokerDataClasses/*.cs`, ~250 sites).

**The bug (Own.NET extractor).** The Roslyn extractor keys release on the raw
handler *text*: `+=` records `new System.ComponentModel.PropertyChangedEventHandler(H)`
as the handler and the `-=` collector stores the bare `H`, so
`unsub.Contains("{left}|{right}")` never matches. Worse, `IsHandler` accepts only
`IdentifierName` / `MemberAccess`, so a `-= new …Handler(H)` is not even collected,
and the P-004 static-handler exemption is skipped for a `+= new …Handler(StaticM)`.
Net effect: a correctly torn-down subscription is reported as an unreleased leak —
a false positive. The fix normalizes a delegate-creation to its inner handler
before keying (extractor `NormalizeHandler`), so the wrapped `+=` and the bare `-=`
match.

**Why this case uses a single-source `Dispose` (not a rebinding setter).** The
`after.cs` here holds a **readonly** `_source` set once in the ctor and released in
`Dispose`, so "after = clean" is **unconditionally** true: the one subscription
created is the exact one torn down. It deliberately avoids the *setter-rebind*
idiom (`… -= h; _source = value; _source.PropertyChanged += new …(h)`), because
own-check's release model is **not flow-sensitive** — it treats *any* matching `-=`
in the class as releasing the subscription. Under a rebinding setter that model
would call the subscription released even though the `-=` detached only the *old*
source and the newly-assigned source is never torn down (Codex P2 on #163). That
soundness gap is **pre-existing** (a bare `-=`/`+=` rebinding setter already
behaved identically before this PR) and orthogonal to this text-normalization fix;
tracking the last-rebound subscription would need flow-sensitive release analysis,
a separate change. Keeping the corpus case rebind-free makes the regression assert
the normalization only, not the lenient model.

**What the checker says (`.own` reduction).** Modelling the ctor+Dispose as one
scope, the unreleased token in `before.cs` is the generic **OWN001** (owned
resource not released on all paths), carrying the resource-kind tag:

```text
$ python -m ownlang check corpus/wpf/subscription-explicit-delegate-release/case.own
case.own:…: error: [OWN001] 'sub' is owned but not released at end of function
  [resource: subscription token]
```

**Regression guard.** `scripts/benchmark.py` runs the real C# through the
extractor + core: `before.cs` must be **caught** (the leak is real) and `after.cs`
must be **silent** (the release is recognized). Before the `NormalizeHandler` fix,
`after.cs` falsely reports OWN001 → the benchmark's specificity gate fails; after
it, silent.

**Honesty / scope.** `case.own` is a hand reduction that carries only the
acquire/release logic; the syntactic `+=`/`-=` asymmetry that the extractor must
normalize lives in `before.cs` / `after.cs`, which are representative of the real
SectorTS idiom, not a verbatim copy of one file.
