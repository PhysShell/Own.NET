# Self-`WhenAnyValue` precision — the own-only subscription findings are (mostly) real

A dig into the honest caveat on the WalletWasabi oracle run — *"own-only may
include residual self-`WhenAnyValue` false positives"* — by checking the actual
target source. The headline: **most of the own-only nested findings are real
leaks, not FPs.** The genuine residual FP is one narrow shape.

## The run

Oracle `27839799505`, **WalletWasabi @ `b67080d`**, scope `WalletWasabi.Fluent`,
via the SARIF own-check (#43), ~5.5 min. **2-way** — Infer# was skipped
(`WalletWasabi.Fluent` does not build for Infer# on the Linux runner), so this is
**Own.NET vs CodeQL**. Leak-class file overlap:

| bucket | files | what |
|---|---:|---|
| Own.NET only | 34 | reactive subscription leaks (`WhenAnyValue(…).Subscribe` ignored) |
| CodeQL only | 20 | Dispose/RAII (`cs/dispose-not-called-on-throw`, `cs/local-not-disposed`) — 48 findings |
| Agree | 3 | `historyviewmodel.cs`, `mainviewmodel.cs`, `qrcodereader.cs` |

CodeQL flags **zero** subscription leaks (it has no "subscribed, never disposed"
query); its other **932** findings are all *quality* queries (missed-readonly,
catch-all, path-combine, …), outside the leak class. The tools are complementary
and near-disjoint — the documented differentiation, on real cross-tool output.

## The dig: are the own-only `WhenAnyValue` findings FPs?

The extractor silences **only** `this.WhenAnyValue(p => p.Member)
.<self-preserving ops>.Subscribe` — single-arg, single-**hop** self property — as
a collectable self-cycle (`source: "self"`); everything else stays flagged. So the
own-only findings are the shapes it does *not* silence:

- a **nested** path — `x => x.Settings.Foo`
- **multi-arg** — `x => x.A, x => x.B`
- an **unrecognised op** — e.g. `.ToSignal()`

To separate FP from real leak, I pulled the actual WalletWasabi source.

### Nested `x => x.Settings.Foo` → a **real leak**, not an FP

`BitcoinTabSettingsViewModel` — `Settings` is a **constructor-injected
`ApplicationSettings`**:

```csharp
public BitcoinTabSettingsViewModel(UiContext uiContext, ApplicationSettings settings)
public ApplicationSettings Settings { get; }          // = settings;

this.WhenAnyValue(x => x.Settings.BitcoinRpcUri)
    .Subscribe(x => BitcoinRpcUri = x);               // result ignored, no DisposeWith
```

`WhenAnyValue(x => x.Settings.BitcoinRpcUri)` attaches a `PropertyChanged` handler
to `this.Settings` — the **long-lived injected `ApplicationSettings`** — and the
handler closes over `this`. So the app-wide settings object keeps the transient
settings-tab view-model alive: **a real subscription leak.** The classifier is
*correctly conservative* here — a nested path can observe an injected/shared
object, so it must not be silenced. The same holds for `CoordinatorTabSettings­
ViewModel` (also `x => x.Settings.…` over the injected `ApplicationSettings`) and
`SettingsPageViewModel` (`x => x.UiContext.ApplicationSettings.DarkModeEnabled`).

**So most own-only nested findings are real leaks — the differentiation is
*stronger* than the caveat implied, not weaker.**

### Multi-arg single-hop own (`x => x.A, x => x.B`) → the genuine residual FP

`BitcoinTabSettingsViewModel.cs:66`:

```csharp
this.WhenAnyValue(x => x.BitcoinRpcUri, x => x.BitcoinRpcCredentialString)
    .Subscribe(…);
```

Both selectors are **single-hop OWN properties**. `WhenAnyValue` over single-hop
own properties observes only `this`, so the observable, its handler and `this`
form one cycle the GC collects together — a self-cycle, **not** a leak. The
classifier misses it *solely* because it requires `Arguments.Count == 1`. → a
genuine false positive.

## The fix (proposed)

Generalise `IsSelfRootedWhenAny` from "one single-hop self selector" to "**one or
more** single-hop self selectors" — multi-arg `WhenAnyValue` over own properties
roots at `this` exactly as a single one does:

```csharp
// A WhenAnyValue selector `p => p.Member` rooted at the lambda parameter (a
// single-hop self property — not `p => p.A.B`, not a result-combiner lambda).
static bool IsSelfMemberSelector(ArgumentSyntax arg) =>
    arg.Expression is SimpleLambdaExpressionSyntax lam
        && lam.Body is MemberAccessExpressionSyntax body
        && body.Expression is IdentifierNameSyntax pid
        && pid.Identifier.Text == lam.Parameter.Identifier.Text;

// (no System.Linq dependency — it is not imported in Program.cs)
static bool AllSelfMemberSelectors(SeparatedSyntaxList<ArgumentSyntax> args)
{
    if (args.Count < 1) return false;
    foreach (var a in args)
        if (!IsSelfMemberSelector(a)) return false;
    return true;
}

// in IsSelfRootedWhenAny, replace the single-arg branch with:
return ma.Name.Identifier.Text == "WhenAnyValue"
    && AllSelfMemberSelectors(iv.ArgumentList.Arguments);
```

Soundness is unchanged — N single-hop own-property selectors root at `this`
identically to one. **Nested paths and the result-combiner overload
(`…, (a, b) => …`) stay flagged** (conservative: they can observe an injected
object). This silences the `BitcoinTabSettingsViewModel.cs:66`-class FP and leaves
every real injected-`Settings` leak untouched.

## Why it is not done here (the coverage gap)

`IsSelfRootedWhenAny` is currently exercised **only by the mine/oracle runs on
real code** — there is **no `WhenAnyValue` sample** under
`frontend/roslyn/samples/`, so the `wpf-extractor` CI job does not cover it, and
there is no local .NET SDK to validate a change. The fix should therefore land
*with* a `WhenAnyValueViewModel.cs` sample wired into the `wpf-extractor` job —
asserting: single-arg `x => x.Member` silenced, **multi-arg `x => x.A, x => x.B`
silenced**, nested `x => x.Svc.Prop` flagged, and a combinator (`CombineLatest`)
flagged — so the classifier finally gets a CI regression pin and the change is
validated where the frontend always is: in CI, not blind.
