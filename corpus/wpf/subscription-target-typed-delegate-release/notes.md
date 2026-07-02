# Subscription released via target-typed `+= new(H)` / bare `-= H` (release-match FP)

The C# 9 target-typed twin of `subscription-explicit-delegate-release`. Same FP,
different delegate-creation syntax:

```csharp
_source.PropertyChanged += new(OnSourcePropertyChanged);   // ctor: target-typed delegate creation
_source.PropertyChanged -= OnSourcePropertyChanged;        // Dispose: bare method group
```

**The bug (Own.NET extractor).** `NormalizeHandler` originally unwrapped only
`ObjectCreationExpressionSyntax` (explicit `new PropertyChangedEventHandler(H)`). A
target-typed `new(H)` is an `ImplicitObjectCreationExpressionSyntax`, so it was left
un-normalized: `new(H)` != `H` on the release key, and a correctly torn-down
subscription was reported as an unreleased OWN001 (Codex P3 on #163). The fix
matches `BaseObjectCreationExpressionSyntax` — the shared base of the explicit and
target-typed forms — so both normalize to their inner handler.

**Case shape.** Single **readonly** `_source`, subscribed once in the ctor and
released in `Dispose` — no receiver rebinding, so "after = clean" is unconditionally
true (same rationale as the explicit-delegate case; see its notes.md).

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be caught (real
leak), `after.cs` must be silent (release recognized). Before the
`BaseObjectCreationExpressionSyntax` widening, `after.cs` falsely reports OWN001.
