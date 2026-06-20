// OwnSharp OwnIR extractor (P-001 v0).
//
// Scans C# and emits OwnIR facts (JSON) in the OwnLang spec's vocabulary; the
// Python core (`python -m ownlang ownir facts.json`) produces the verdict
// (OWN001 leak) at the C# location.
//
// Event subscriptions are resolved type-aware (P-014 Tier A): all inputs are
// parsed into ONE CSharpCompilation with the runtime's framework references, and
// a `target += handler` is a subscription only when the SemanticModel binds the
// left side to an event symbol — so `sum += value` (arithmetic) is not a leak.
// When the left side's declaring type is an unresolved external reference we do
// not guess: a handler-shaped RHS surfaces as an OWN050 "leakage analysis
// skipped" note, never a leak. A subscription is "released" by a matching
// `target -= handler` in the class; a `Tick`/`Elapsed` handler is tagged
// resource=timer (WPF002) and is released if the timer's receiver also has a
// `.Stop()` call. The IDisposable/pool/local detectors remain syntactic for now
// (P-014 rollout: the event fact goes type-aware first).
//
// Usage: ownsharp-extract <file.cs | dir> [more ...] [-o facts.json]
//
// Inputs may be .cs files or directories. A directory is walked recursively for
// *.cs, skipping build output (bin/obj), VCS/vendor dirs (.git, node_modules)
// and generated files (*.g.cs, *.Designer.cs) — so you can point it at a whole
// repo (this is what the `own-check` script / GitHub Action do).

using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var rawInputs = new List<string>();
string? outPath = null;
// Event-subscription detection is on by default now that it is type-aware
// (P-014 Tier A graduates it from the interim off). `--no-event-leaks` opts out
// (e.g. to run only the disposable/pool detectors); it is the first instance of
// the broader check-selection surface tracked in P-015.
bool emitEvents = true;
// --flow-locals (P-016 B0b/B2, EXPERIMENTAL, default off): emit per-method flow
// facts for non-escaping local IDisposables (acquire/use/release/if/return over a
// CFG) so the core checks them path-sensitively (OWN001/002/003). Supersedes the
// flat D1 local-disposable detector when on. Default off keeps the shipped surface.
bool flowLocals = false;
// --stats (coverage): print a one-line flow-locals coverage summary to stderr
// (of the methods that have a disposable local worth checking, how many were
// flow-analysed vs honestly skipped for an unmodelled construct) and stamp the
// same counts into the facts JSON. Turns "0 findings" into "clean vs didn't-reach".
bool reportStats = false;
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "-o" && i + 1 < args.Length) outPath = args[++i];
    else if (args[i] == "--no-event-leaks") emitEvents = false;
    else if (args[i] == "--flow-locals") flowLocals = true;
    else if (args[i] == "--stats") reportStats = true;
    else rawInputs.Add(args[i]);
}

if (rawInputs.Count == 0)
{
    Console.Error.WriteLine("usage: ownsharp-extract <file.cs | dir> [...] [-o facts.json]");
    return 2;
}

// --stats reports flow-locals coverage; the counters only move inside the
// --flow-locals pass. Without it they would all be zero and the summary would
// read "0/0 methods flow-analysed" — the exact ambiguous zero --stats exists to
// kill (e.g. `own-check.sh --legacy --stats`). Refuse the contradictory combo.
if (reportStats && !flowLocals)
{
    Console.Error.WriteLine("ownsharp-extract: --stats requires --flow-locals");
    return 2;
}

// A path segment we never scan: build output, VCS, and vendored trees.
static bool IsSkippedDir(string seg) =>
    seg is "bin" or "obj" or ".git" or ".vs" or "node_modules" or "packages";

// Generated C# the author did not write (and cannot fix): skip it.
static bool IsGenerated(string path) =>
    path.EndsWith(".g.cs", StringComparison.Ordinal)
    || path.EndsWith(".Designer.cs", StringComparison.Ordinal)
    || path.EndsWith(".AssemblyInfo.cs", StringComparison.Ordinal);

static bool IsSkipped(string path)
{
    foreach (var seg in path.Split('/', '\\'))
        if (IsSkippedDir(seg)) return true;
    return IsGenerated(path);
}

// Expand directories into their .cs files; pass explicit files through as-is.
// IgnoreInaccessible tolerates an unreadable subdir mid-walk (otherwise the
// whole scan would abort with an unhandled exception on a locked directory).
static IEnumerable<string> Expand(IEnumerable<string> roots)
{
    var opts = new EnumerationOptions
    {
        RecurseSubdirectories = true,
        IgnoreInaccessible = true,
    };
    foreach (var p in roots)
    {
        if (Directory.Exists(p))
        {
            foreach (var f in Directory.EnumerateFiles(p, "*.cs", opts))
                if (!IsSkipped(f))
                    yield return f;
        }
        else
        {
            yield return p;
        }
    }
}

// A finding's file is reported relative to the current directory (the repo root
// in CI / under the Action), with forward slashes — so a GitHub annotation or an
// MSBuild diagnostic points at the right file even when two files share a name.
static string Rel(string path) =>
    Path.GetRelativePath(Directory.GetCurrentDirectory(), path).Replace('\\', '/');

var inputs = Expand(rawInputs).Distinct().ToList();

static bool IsHandler(ExpressionSyntax rhs) =>
    rhs is IdentifierNameSyntax || rhs is MemberAccessExpressionSyntax;

static int LineOf(SyntaxNode node) =>
    node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

// The receiver of `target.Member` ("_timer" for `_timer.Tick`), or null when the
// left side is a bare identifier (`Changed += h`).
static string? Receiver(ExpressionSyntax expr) =>
    expr is MemberAccessExpressionSyntax m ? m.Expression.ToString() : null;

// A timer subscription is a `Tick`/`Elapsed` handler — DispatcherTimer and the
// WinForms timer expose `Tick`, System.Timers.Timer exposes `Elapsed`. A running
// timer strong-refs the handler's owner, so an undetached one leaks it.
static bool IsTimerEvent(ExpressionSyntax left) =>
    left is MemberAccessExpressionSyntax m
        && (m.Name.Identifier.Text == "Tick" || m.Name.Identifier.Text == "Elapsed");

// P-004 self-owned exemption: is the event SOURCE owned by (and so never longer-
// lived than) the subscriber? True for a bare instance event on `this`, or a
// receiver that resolves to a field/local the class OWNS. "Owns" is the `owned`
// set the caller computes: fields the class constructs directly (`new`), builds
// indirectly through a `ref`/`out` helper, or fetches as one of its own template
// parts. Such a `source <-> this` reference cycle is GC-collectable, so the
// subscription is not a leak. The receiver is resolved to a SYMBOL (not matched by
// text), and `owned` is AST-based — not a regex. NOTE: callers must exclude timers
// — a *running* timer is rooted by the dispatcher regardless of who owns the field.
static bool IsSelfOwnedSource(ExpressionSyntax left, IEventSymbol ev,
                              SemanticModel model, HashSet<string> owned)
{
    if (left is not MemberAccessExpressionSyntax m)
        return !ev.IsStatic;   // bare event => an instance event on `this`
    if (m.Expression is ThisExpressionSyntax)
        return true;
    var recv = model.GetSymbolInfo(m.Expression).Symbol;
    return (recv is IFieldSymbol or ILocalSymbol) && owned.Contains(recv.Name);
}

// P-004 (ext): a control fetching one of its OWN template parts —
// `GetTemplateChild("PART_x")` or `[Template.]FindName(...)`, optionally behind a
// cast or `as` — owns the result (it lives inside the control's own template /
// visual tree). AST-only (matched by call name), in the spirit of the rest of the
// file; used to fold template-part fields into the self-owned exemption.
static bool IsTemplatePartFetch(ExpressionSyntax? expr)
{
    expr = expr switch
    {
        CastExpressionSyntax c => c.Expression,
        BinaryExpressionSyntax b when b.IsKind(SyntaxKind.AsExpression) => b.Left,
        _ => expr,
    };
    return expr is InvocationExpressionSyntax inv
        && (inv.Expression switch
           {
               MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
               IdentifierNameSyntax id => id.Identifier.Text,
               _ => null,
           }) is "GetTemplateChild" or "FindName";
}

// P-004 static-handler exemption: a `+= StaticMethod` stores a delegate whose
// Target is null, so no instance is retained — the subscription cannot leak a
// subscriber, however long-lived the source. Only method-group handlers
// (identifier / member access) are judged; lambdas and delegate-typed values may
// capture state and are left as leak candidates.
static bool IsStaticHandler(ExpressionSyntax right, SemanticModel model) =>
    IsHandler(right)
        && model.GetSymbolInfo(right).Symbol is IMethodSymbol { IsStatic: true };

// P-004 severity tiering: of the subscriptions that survive the self-owned and
// static-handler exemptions (and are not timers), how long-lived is the event
// SOURCE? A static event lives for the whole process, so an undetached handler is
// a provable leak -> "static". A local that is CONSTRUCTED right here (`var p =
// new Publisher(); p.X += h`) dies with the scope -> "local" (the caller drops it;
// not a heap leak). But a local that merely ALIASES something else (`var src =
// _bus; src.X += h`) has unknown provenance — it may hold a long-lived injected
// source — so it is NOT dropped. Everything else (an instance field / property /
// injected parameter, or such an aliasing local) has UNKNOWN lifetime ->
// "injected": it MIGHT outlive `this`, but we cannot prove it without ownership
// modelling, so the core renders it a warning (not a hard error) until that lands.
static string SubscriptionSourceKind(ExpressionSyntax left, IEventSymbol ev,
                                     SemanticModel model)
{
    if (ev.IsStatic)
        return "static";
    if (left is MemberAccessExpressionSyntax m)
    {
        var recv = model.GetSymbolInfo(m.Expression).Symbol;
        if (recv is ILocalSymbol local)
        {
            // Method-bounded (droppable) ONLY when the local is the publisher this
            // scope constructs (`var p = new Publisher()`), which dies with it. A
            // local initialised from anything else (a field, a parameter, a call)
            // may alias a long-lived source, so we cannot prove it bounded — fall
            // through to "injected" and warn rather than silently drop a real leak.
            var constructedHere = local.DeclaringSyntaxReferences
                .Select(r => r.GetSyntax())
                .OfType<VariableDeclaratorSyntax>()
                .Any(v => v.Initializer?.Value is ObjectCreationExpressionSyntax
                                               or ImplicitObjectCreationExpressionSyntax);
            if (constructedHere)
                return "local";
        }
        if (recv is IFieldSymbol { IsStatic: true } or IPropertySymbol { IsStatic: true })
            return "static";
    }
    return "injected";
}

// A lambda / anonymous-method handler stores no named delegate, so the
// subscription can NEVER be undone with `-=` (you would have had to cache the
// delegate in a field). A particularly sharp leak shape worth calling out.
static bool IsLambdaHandler(ExpressionSyntax right) =>
    right is AnonymousFunctionExpressionSyntax;

// P-004 source-lifetime tier for an ignored `.Subscribe()` chain (WPF004). A
// self-rooted `this.WhenAnyValue(p => p.SelfProp).<self-preserving ops>.Subscribe`
// watches the component's OWN property: the observable, its handler and `this`
// form one cycle the GC collects together, so it is NOT a leak. We classify ONLY
// this unambiguous self-cycle (the bridge drops a `source: "self"` subscribe).
// Anything else stays a flagged leak (conservative). Purely syntactic.

// A single-source operator whose arguments are only funcs / schedulers / scalars,
// so it cannot mix in an EXTERNAL observable. A combinator NOT listed here
// (CombineLatest, Merge, SelectMany, WithLatestFrom, Zip, Switch, Concat, ...), an
// operator with an observable-taking overload (Throttle/Buffer/Sample/TakeUntil/
// Window), or any unknown operator is treated as possibly external -> the chain
// stays flagged. (Conservative: an unrecognised op never silences a real leak.)
static bool IsSelfPreservingOp(string name) =>
    name is "Select" or "Where" or "Do" or "Skip" or "Take" or "SkipWhile"
        or "TakeWhile" or "ObserveOn" or "SubscribeOn" or "DistinctUntilChanged"
        or "WhereNotNull" or "Cast" or "OfType" or "StartWith" or "Scan"
        or "Finally" or "AsObservable" or "Synchronize" or "Timestamp";

// One WhenAnyValue selector `p => p.Member` rooted at the lambda parameter — a
// single-hop self property. NOT `p => p.A.B` (a path through a possibly-injected
// object that can keep `this` alive — a real leak), and NOT a result-combiner
// lambda (`(a, b) => ...`). Purely syntactic.
static bool IsSelfMemberSelector(ArgumentSyntax arg) =>
    arg.Expression is SimpleLambdaExpressionSyntax lam
        && lam.Body is MemberAccessExpressionSyntax body
        && body.Expression is IdentifierNameSyntax pid
        && pid.Identifier.Text == lam.Parameter.Identifier.Text;

static bool IsSelfRootedWhenAny(ExpressionSyntax chain)
{
    // Walk the fluent chain leftwards. The HEAD must be `this.WhenAnyValue(...)`;
    // EVERY downstream operator must be self-preserving (no external observable),
    // else a later `.CombineLatest(_bus.X)` / `.SelectMany(_ => _bus.Y)` roots the
    // subscription externally and it must stay flagged (codex P1).
    var e = chain;
    while (e is InvocationExpressionSyntax iv
           && iv.Expression is MemberAccessExpressionSyntax ma)
    {
        if (ma.Expression is ThisExpressionSyntax)
        {
            // Head: `this.WhenAnyValue(p => p.Member[, q => q.Other, ...])`. A
            // self-cycle requires WhenAnyValue with one-or-more single-hop
            // self-member selectors — each roots at `this`. `p => p.A.B` (a path
            // through a possibly-injected object) and a result-combiner overload
            // (`..., (a, b) => ...`) stay flagged. Multi-arg over own properties
            // observes only `this`, the SAME self-cycle as single-arg (see
            // docs/notes/self-whenany-precision.md).
            if (ma.Name.Identifier.Text != "WhenAnyValue"
                || iv.ArgumentList.Arguments.Count < 1)
                return false;
            foreach (var arg in iv.ArgumentList.Arguments)
                if (!IsSelfMemberSelector(arg))
                    return false;
            return true;
        }
        if (!IsSelfPreservingOp(ma.Name.Identifier.Text))
            return false;          // a combinator / unknown op -> possibly external
        e = ma.Expression;
    }
    return false;                  // not a `this.WhenAnyValue(...)`-headed chain
}

// --- P-016 B0b/B2: flow lowering for local IDisposables (experimental) ---

// A type that implements System.IDisposable (semantic) — the flow lowering tracks
// locals of such types.
static bool ImplementsIDisposable(ITypeSymbol? t) =>
    t is not null
    && ((t.Name == "IDisposable" && t.ContainingNamespace?.ToString() == "System")
        || t.AllInterfaces.Any(i => i.Name == "IDisposable"
                                    && i.ContainingNamespace?.ToString() == "System"));

// Types that implement IDisposable but whose disposal is conventionally OPTIONAL —
// the .NET guidance / Roslyn CA2000 exempt them: Task/ValueTask only hold a
// lazily-allocated wait handle, and the System.Data containers' Dispose() is a
// no-op. The flow detector must not flag an undisposed local of these (this is the
// curated exemption the flat D1 detector gets for free via IsDisposableType, which
// is exactly why D1 never flagged Task/DataTable and the semantic path did).
static bool IsDisposeOptional(ITypeSymbol t)
{
    var ns = t.ContainingNamespace?.ToString();
    return (ns == "System.Threading.Tasks" && t.Name is "Task" or "ValueTask")
        || (ns == "System.Data" && t.Name is "DataTable" or "DataSet" or "DataView");
}

static string MethodName(BaseMethodDeclarationSyntax m) => m switch
{
    MethodDeclarationSyntax md => md.Identifier.Text,
    ConstructorDeclarationSyntax => ".ctor",
    _ => "?",
};

// A `Dispose()`/`Close()`/`DisposeAsync()` call — through member access (`x.Dispose()`)
// or member binding (`x?.Dispose()`), and seen through a trailing `.ConfigureAwait(false)`
// (the idiomatic `await x.DisposeAsync().ConfigureAwait(false)` is the release, not a
// throwing call). Mirrors the unwrap in EmitFlowExpr so StatementMayThrow does not inject
// a false exceptional-leak edge before an async dispose.
static bool IsDisposeShaped(InvocationExpressionSyntax i)
{
    var callee = i.Expression;
    if (callee is MemberAccessExpressionSyntax cfg
        && cfg.Name.Identifier.Text == "ConfigureAwait"
        && cfg.Expression is InvocationExpressionSyntax innerInv)
        callee = innerInv.Expression;
    return (callee switch
    {
        MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
        MemberBindingExpressionSyntax mb => mb.Name.Identifier.Text,
        _ => (string?)null,
    }) is "Dispose" or "Close" or "DisposeAsync";
}

// True when `st` is the LAST statement of a method/accessor/constructor body block — its
// block's parent is a member declaration, not a nested statement (a BlockSyntax is itself
// a StatementSyntax, so this also excludes nested blocks). Used to decide whether a
// `try`'s exceptional-exit edges are sound (see the try lowering).
static bool IsBodyTail(StatementSyntax st) =>
    st.Parent is BlockSyntax b
    && b.Statements.Count > 0 && b.Statements[^1] == st
    && b.Parent is not StatementSyntax;

// Inject an exceptional-exit edge `if(*){ onThrow }` before a LEAF may-throw statement
// (an expression statement or a local declaration) inside a `try` body. `onThrow` is the
// continuation a throw here runs to leave the method — this try's `finally`, then any
// enclosing tries' finallys, then `return` (built in the try lowering). A resource owned
// at this point and not released by that continuation leaks on the throw path. Called for
// LEAF statements only; a COMPOUND statement (if/loop/block) is recursed into so the edge
// lands before the nested leaf — at the point the resource's ownership is exact (after any
// in-branch dispose), which is what makes nesting sound rather than a false leak.
static void InjectThrowEdge(StatementSyntax st, List<object> nodes, List<object>? onThrow)
{
    if (onThrow is not null && StatementMayThrow(st))
        nodes.Add(new { op = "if", line = LineOf(st),
                        then = new List<object>(onThrow), @else = new List<object>() });
}

// A statement that can raise an exception part-way through: it makes a call that is not
// itself a dispose, OR it creates an object (`new` — a constructor can throw, leaking a
// PRIOR owned resource whose dispose it would then skip). Creating the resource being
// acquired here is harmless: the edge lands before its `acquire`, where it is not yet owned.
// Does NOT descend into lambda / anonymous-method bodies: a `new` (or call) inside `() => …`
// runs when the delegate is INVOKED, not where it is declared, so the declaring statement is
// not a throw point — counting it would inject a phantom edge that falsely flags a prior
// resource disposed after the `try`. An immediately-invoked lambda is still caught: the outer
// invocation is itself the throw point.
static bool StatementMayThrow(StatementSyntax st) =>
    st.DescendantNodes(descendIntoChildren: n => n is not AnonymousFunctionExpressionSyntax)
      .Any(n =>
        (n is InvocationExpressionSyntax i && !IsDisposeShaped(i))
        || n is ObjectCreationExpressionSyntax or ImplicitObjectCreationExpressionSyntax);

// A catch clause that catches EVERY exception and so always continues to the post-try
// code: `catch { }` (no declaration) or `catch (Exception)` / `catch (System.Exception)` —
// with NO `when` filter (a filter may evaluate false, letting the exception propagate). A
// typed catch (`catch (IOException)`, or a qualified DOMAIN type like `catch (Foo.Exception)`
// whose rightmost name is `Exception` but is not System.Exception) or any filtered catch
// continues for only SOME exceptions; the rest propagate out, skipping the post-try dispose,
// so the resource still leaks on those paths. Match the canonical System.Exception spellings
// by full text — a rightmost-name match would misread a domain `Foo.Exception` as catch-all
// and suppress a real leak. Syntax-only (no semantic model): the inverse pathology — an
// exotic alias making a typed-looking name resolve to System.Exception — is never written.
static bool IsCatchAll(CatchClauseSyntax cc) =>
    cc.Filter is null
    && (cc.Declaration is not { } decl
        || decl.Type.ToString() is "Exception"
                               or "System.Exception"
                               or "global::System.Exception");

// Lower a method block to OwnIR flow nodes (acquire/use/release/if/return) for the
// `tracked` local IDisposables. Returns null on any UNMODELLED statement (a `goto`, labeled
// statement, local function, `lock`/`fixed`, …): the method is then honestly skipped, not
// guessed. Loops, `try`, `do` and `switch` ARE modelled below.
static List<object>? LowerFlowBody(BlockSyntax block, HashSet<string> tracked, SemanticModel model)
{
    var nodes = new List<object>();
    foreach (var st in block.Statements)
        if (!LowerFlowStmt(st, tracked, model, nodes))
            return null;
    return nodes;
}

// `canEscape`: can a throw at the current position leave the METHOD (no enclosing
// catch-all swallows it)? `onThrow`: the continuation a throw here runs to leave the
// method (finally-stack + return), or null when no exception edge should be injected
// (method level, or a region an enclosing catch-all swallows). `onReturn`: the continuation
// a `return` here runs FIRST — the enclosing `finally`(s), then the exit — so a resource a
// finally disposes is released on the return path; null = a bare return (outside any try).
// Defaults are the method-body context: throws escape, nothing is injected, returns are bare.
static bool LowerFlowStmt(StatementSyntax st, HashSet<string> tracked, SemanticModel model, List<object> nodes,
                          bool canEscape = true, List<object>? onThrow = null,
                          List<object>? onReturn = null)
{
    switch (st)
    {
        case BlockSyntax b:
            foreach (var s2 in b.Statements)
                if (!LowerFlowStmt(s2, tracked, model, nodes, canEscape, onThrow, onReturn))
                    return false;
            return true;
        case LocalDeclarationStatementSyntax ld:
            InjectThrowEdge(ld, nodes, onThrow);
            if (ld.UsingKeyword == default)
                foreach (var v in ld.Declaration.Variables)
                    if (tracked.Contains(v.Identifier.Text)
                        && (v.Initializer?.Value is ObjectCreationExpressionSyntax
                                                 or ImplicitObjectCreationExpressionSyntax
                            || IsPoolRent(v.Initializer?.Value, model)))   // ArrayPool<T> Rent
                        nodes.Add(new { op = "acquire", var = v.Identifier.Text, line = LineOf(v) });
            return true;
        case ExpressionStatementSyntax es:
            InjectThrowEdge(es, nodes, onThrow);
            EmitFlowExpr(es.Expression, tracked, model, nodes);
            return true;
        case IfStatementSyntax ifs:
        {
            var thenNodes = new List<object>();
            if (!LowerFlowStmt(ifs.Statement, tracked, model, thenNodes, canEscape, onThrow, onReturn))
                return false;
            var elseNodes = new List<object>();
            if (ifs.Else is { } e && !LowerFlowStmt(e.Statement, tracked, model, elseNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "if", line = LineOf(ifs), then = thenNodes, @else = elseNodes });
            return true;
        }
        case UsingStatementSyntax us:
            // using(...) {body}: the using local is auto-disposed (untracked); still
            // lower the body so a tracked plain local used inside is seen.
            return us.Statement is null || LowerFlowStmt(us.Statement, tracked, model, nodes, canEscape, onThrow, onReturn);
        case ReturnStatementSyntax rs:
            // A tracked local READ in the return value is a use at the return point —
            // e.g. `return BuildResult(buf)` after `pool.Return(buf)` is a use-after-
            // return. A tracked local *itself* returned is excluded upstream as an
            // escape, so lowering the return expression only adds uses, never a
            // spurious escape. Then: a `return` first runs any enclosing `finally`(s)
            // — threaded as `onReturn`, so a resource the finally releases is released
            // on the return path — then exits; outside a try it is a bare CFG exit.
            if (rs.Expression is { } rexpr)
                EmitFlowExpr(rexpr, tracked, model, nodes);
            if (onReturn is not null)
                nodes.AddRange(onReturn);
            else
                nodes.Add(new { op = "return", var = (string?)null, line = LineOf(rs) });
            return true;
        case WhileStatementSyntax ws:
        {
            // P-016 A1 reached the frontend: a `while` lowers to a `while` flow op
            // (a body that runs 0+ times with a back-edge); the core analyses it with
            // its worklist fixpoint (cross-iteration leak / use-after-release /
            // double-release). The condition is opaque (we model control flow, not
            // values). If the body has an unmodelled statement, bail the method.
            var bodyNodes = new List<object>();
            if (ws.Statement is null || !LowerFlowStmt(ws.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(ws), body = bodyNodes });
            return true;
        }
        case ForEachStatementSyntax fes:
        {
            // `foreach` runs its body 0+ times over an (opaque) collection — the same
            // ownership shape as `while`. The loop variable is never a `new`'d
            // candidate and the hidden enumerator is auto-disposed, so modelling the
            // body as a `while` is sound. (`for` and `do` are handled below; `do` runs 1+
            // times, so it is desugared rather than modelled as a bare 0+-trip `while`.)
            var bodyNodes = new List<object>();
            if (fes.Statement is null || !LowerFlowStmt(fes.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(fes), body = bodyNodes });
            return true;
        }
        case ForStatementSyntax fors:
        {
            // `for (init; cond; incr) body` runs its body 0+ times — the same
            // ownership shape as `while`/`foreach`. init/cond/incr are opaque (we
            // model control flow, not values); the tracked locals are the ones the
            // BODY declares. A resource declared in the `for` *initializer* is not a
            // method-body local, so it is never a tracked candidate — no soundness
            // concern, just a separate (rare) recall gap.
            var bodyNodes = new List<object>();
            if (fors.Statement is null || !LowerFlowStmt(fors.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(fors), body = bodyNodes });
            return true;
        }
        case TryStatementSyntax trys:
        {
            // try { A } [catch { C }...] [finally { B }] with EXCEPTION EDGES. Any LEAF
            // statement in A (at any nesting depth) that can throw gets an exceptional exit
            // `if(*){ B; … ; return }` injected before it — throw here, run the finally(s),
            // leave. A resource owned at that point and NOT released by the finally leaks on
            // the exceptional path: dispose-not-called-on-throw (a dispose placed in the try,
            // not the finally). A dispose IN the finally runs on every exceptional exit, so
            // the safe pattern stays silent; `acquire; dispose;` with no throw between has no
            // live edge, so no false leak.
            //
            // Catch bodies are not lowered; to stay SOUND, bail if any catch disposes, so
            // a release that only happens in a catch is never missed. Matches `x.Dispose()`
            // and `x?.Dispose()`.
            foreach (var cc in trys.Catches)
                if (cc.Block.DescendantNodes().OfType<InvocationExpressionSyntax>().Any(IsDisposeShaped))
                    return false;
            var finallyNodes = new List<object>();
            if (trys.Finally is { } fin && !LowerFlowStmt(fin.Block, tracked, model, finallyNodes))
                return false;
            // Does a throw in THIS body escape to method exit (so the edge — leave running
            // only the finally — models a real execution)? Sound when there is no catch (it
            // propagates out past any post-try code), the try is the body's tail (nothing
            // runs after), OR no catch is a genuine catch-all — a typed/filtered catch lets
            // the uncaught exception types propagate, skipping the post-try dispose, so the
            // resource still leaks on those paths. The one shape that SUPPRESSES the edges is
            // a catch-all on a non-tail try: every throw is caught and continues to (and may
            // dispose in) the post-try code, so a return there would falsely flag a resource
            // that path disposes. `canEscape` carries the same fact down through ENCLOSING
            // tries: a catch-all higher up already swallows these throws, so they never reach
            // method exit -> no edges in the region nested under it.
            bool escapesThisTry = trys.Catches.Count == 0
                || IsBodyTail(trys)
                || !trys.Catches.Any(IsCatchAll);
            bool bodyCanEscape = canEscape && escapesThisTry;
            // The continuation an escaping throw runs: this finally, then the enclosing
            // exceptional path (its finallys, ending in the method `return`), or just a
            // `return` when this is the outermost try. Null when suppressed -> no edges.
            List<object>? bodyOnThrow = null;
            if (bodyCanEscape)
            {
                bodyOnThrow = new List<object>(finallyNodes);
                bodyOnThrow.AddRange(onThrow ?? new List<object>
                    { new { op = "return", var = (string?)null, line = LineOf(trys) } });
            }
            // A `return` inside the body runs THIS finally, then the enclosing return path
            // (its finallys), then exits — independent of catches (a `return` is never caught,
            // unlike a throw), so it is threaded even where the throw edges are suppressed. The
            // finally release thus runs before the return: `try { …; return; } finally { d }`
            // disposes on the return path instead of being bailed.
            var bodyOnReturn = new List<object>(finallyNodes);
            bodyOnReturn.AddRange(onReturn ?? new List<object>
                { new { op = "return", var = (string?)null, line = LineOf(trys) } });
            foreach (var stmt in trys.Block.Statements)
                if (!LowerFlowStmt(stmt, tracked, model, nodes, bodyCanEscape, bodyOnThrow, bodyOnReturn))
                    return false;
            nodes.AddRange(finallyNodes);   // normal completion runs the finally
            return true;
        }
        case DoStatementSyntax dos:
        {
            // do { B } while(c)  ≡  B; while(c) { B }  — the body runs 1+ times. Lower B once
            // unconditionally (the guaranteed first iteration), then a `while` of B (0+ more).
            // Modelling it as a plain `while` (0+ trips) would be UNSOUND: a resource released
            // only in the body but acquired before the loop would falsely leak on the phantom
            // 0-trip path. Bail (like the loops) if the body has an unmodelled statement.
            if (dos.Statement is null
                || !LowerFlowStmt(dos.Statement, tracked, model, nodes, canEscape, onThrow, onReturn))
                return false;
            var bodyNodes = new List<object>();
            if (!LowerFlowStmt(dos.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(dos), body = bodyNodes });
            return true;
        }
        case SwitchStatementSyntax sw:
        {
            // switch(e) { (case L: | default:) section … } modelled as a chain of opaque,
            // mutually-exclusive branches: `if(*){ s1 } else { if(*){ s2 } else { … } }` — one
            // per section, value-opaque (we model control flow, not the matched value). A
            // trailing `break` ends a section (stripped); a section doing anything the model
            // can't place here (a nested `break`, `goto case`, `throw`) bails the method.
            List<object>? defaultNodes = null;
            var cases = new List<List<object>>();
            foreach (var section in sw.Sections)
            {
                var secNodes = new List<object>();
                if (!LowerSwitchSection(section, tracked, model, secNodes, canEscape, onThrow, onReturn))
                    return false;
                if (section.Labels.Any(l => l is DefaultSwitchLabelSyntax))
                    defaultNodes = secNodes;
                else
                    cases.Add(secNodes);
            }
            // The chain's tail — the "no earlier case matched" branch. A `default` IS that
            // branch. With NO default we do NOT model an empty no-match path: that would falsely
            // flag a resource disposed in every case of an EXHAUSTIVE switch (e.g. over an enum)
            // as leaking on a path that cannot occur. Instead the LAST case becomes the tail
            // (assume some branch runs) — sound: a genuinely non-exhaustive no-match leak is only
            // missed when EVERY case disposes the resource (a recall gap, never a false positive).
            List<object> chain;
            if (defaultNodes is not null)
                chain = defaultNodes;
            else if (cases.Count == 0)
                return true;                         // empty switch -> no flow effect
            else
            {
                chain = cases[^1];
                cases.RemoveAt(cases.Count - 1);
            }
            for (int k = cases.Count - 1; k >= 0; k--)
                chain = new List<object>
                    { new { op = "if", line = LineOf(sw), then = cases[k], @else = chain } };
            nodes.AddRange(chain);
            return true;
        }
        default:
            return false;   // unmodelled (goto/labeled/throw/...) -> bail the method
    }
}

// Lower one `switch` section's statements, treating a top-level `break` as the section
// terminator (it just exits the switch, so it is stripped). Bails (false) on any statement the
// flow model doesn't handle here — including a `break` nested inside an `if`/loop, which reaches
// the unmodelled default and conservatively skips the whole method.
static bool LowerSwitchSection(SwitchSectionSyntax section, HashSet<string> tracked,
                               SemanticModel model, List<object> nodes, bool canEscape,
                               List<object>? onThrow, List<object>? onReturn)
{
    foreach (var stmt in section.Statements)
    {
        if (stmt is BreakStatementSyntax)
            break;
        if (!LowerFlowStmt(stmt, tracked, model, nodes, canEscape, onThrow, onReturn))
            return false;
    }
    return true;
}

static void EmitFlowExpr(ExpressionSyntax expr, HashSet<string> tracked, SemanticModel model, List<object> nodes)
{
    // `await x.DisposeAsync()` is the IAsyncDisposable release — look through the
    // await to the inner call so it counts as disposal, not a bare use.
    if (expr is AwaitExpressionSyntax awaited)
        expr = awaited.Expression;
    // ... and through a trailing `.ConfigureAwait(false)` — the library-idiomatic
    // `await x.DisposeAsync().ConfigureAwait(false)` awaits the ConfigureAwait call.
    if (expr is InvocationExpressionSyntax cfg
        && cfg.Expression is MemberAccessExpressionSyntax cfgMa
        && cfgMa.Name.Identifier.Text == "ConfigureAwait"
        && cfgMa.Expression is InvocationExpressionSyntax inner)
        expr = inner;
    // x.Dispose()/x.Close()/x.DisposeAsync() on a tracked local -> release.
    if (expr is InvocationExpressionSyntax inv
        && inv.Expression is MemberAccessExpressionSyntax ma
        && ma.Name.Identifier.Text is "Dispose" or "Close" or "DisposeAsync"
        && ma.Expression is IdentifierNameSyntax rid
        && tracked.Contains(rid.Identifier.Text))
    {
        nodes.Add(new { op = "release", var = rid.Identifier.Text, line = LineOf(inv) });
        return;
    }
    // x?.Dispose()/x?.Close()/x?.DisposeAsync() (null-conditional) is the release too — the
    // call is a member BINDING under a conditional access, not a member access. Mirrors
    // IsDisposeShaped so a `?.` dispose (e.g. in a finally) is not mistaken for a bare use,
    // which would otherwise falsely flag the resource as leaked.
    if (expr is ConditionalAccessExpressionSyntax cond
        && cond.Expression is IdentifierNameSyntax cid
        && tracked.Contains(cid.Identifier.Text)
        && cond.WhenNotNull is InvocationExpressionSyntax condInv
        && condInv.Expression is MemberBindingExpressionSyntax mb
        && mb.Name.Identifier.Text is "Dispose" or "Close" or "DisposeAsync")
    {
        nodes.Add(new { op = "release", var = cid.Identifier.Text, line = LineOf(cond) });
        return;
    }
    // XPool.Return(buf) on a tracked pooled buffer -> release. The buffer is the
    // ARGUMENT (the pool is the receiver), unlike Dispose where the local is the
    // receiver; `return` early so the argument is not also counted as a use.
    if (PoolReturnBuffer(expr, model) is { } pbuf && tracked.Contains(pbuf))
    {
        nodes.Add(new { op = "release", var = pbuf, line = LineOf(expr) });
        return;
    }
    // any other reference to a tracked local -> use (once per local in this expr).
    var used = new SortedSet<string>(StringComparer.Ordinal);
    foreach (var idn in expr.DescendantNodesAndSelf().OfType<IdentifierNameSyntax>())
        if (tracked.Contains(idn.Identifier.Text))
            used.Add(idn.Identifier.Text);
    foreach (var u in used)
        nodes.Add(new { op = "use", var = u, line = LineOf(expr) });
}

// The field name an expression refers to: "_f" for `_f` or `this._f`, else null.
static string? FieldName(ExpressionSyntax expr) => expr switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m => m.Name.Identifier.Text,
    _ => null,
};

// Is `t` the System.Buffers.ArrayPool<T> type — the Return-based pool we model?
// Checked on the resolved SYMBOL, not the receiver's text, so an aliased receiver
// (`ArrayPool<int> p = ArrayPool<int>.Shared; p.Rent(n)`) binds correctly and an
// unrelated API with "pool" in its name does not false-match. ArrayPool-specific by
// design: MemoryPool<T>.Rent hands back an IMemoryOwner<T> released by Dispose (there
// is no MemoryPool.Return), so a pooled MemoryPool owner rides the IDisposable path,
// not this Return-based one.
static bool IsArrayPoolType(INamedTypeSymbol? t)
{
    if (t is null || t.Name != "ArrayPool")
        return false;
    INamespaceSymbol? ns = t.ContainingNamespace;
    if (ns is null || ns.Name != "Buffers")
        return false;
    ns = ns.ContainingNamespace;   // System.Buffers -> System
    return ns is not null && ns.Name == "System"
        && ns.ContainingNamespace is { IsGlobalNamespace: true };
}

// An ArrayPool<T> `Rent(...)` call — the acquire of a pooled buffer. Resolved via the
// SemanticModel (`model`), so the receiver may be any expression of ArrayPool<T> type.
static bool IsPoolRent(ExpressionSyntax? e, SemanticModel model) =>
    e is InvocationExpressionSyntax i
    && model.GetSymbolInfo(i).Symbol is IMethodSymbol { Name: "Rent" } sym
    && IsArrayPoolType(sym.ContainingType);

// An ArrayPool<T> `Return(buf)` call — the RELEASE of the pooled buffer `buf`. Unlike
// Dispose (where the tracked local is the receiver), the buffer is the first ARGUMENT
// and the pool is the receiver. Resolved via the SemanticModel. Returns the buffer
// name (a plain local) or null.
static string? PoolReturnBuffer(ExpressionSyntax e, SemanticModel model) =>
    e is InvocationExpressionSyntax i
        && model.GetSymbolInfo(i).Symbol is IMethodSymbol { Name: "Return" } sym
        && IsArrayPoolType(sym.ContainingType)
        && i.ArgumentList.Arguments.Count > 0
        && i.ArgumentList.Arguments[0].Expression is IdentifierNameSyntax buf
        ? buf.Identifier.Text : null;

// A field/local type treated as owned-disposable (syntax-only heuristic — no
// semantic model): a curated set plus a few suffixes. Gated on the class `new`ing
// the value, so injected/borrowed disposables are not flagged. Timer types are
// deliberately excluded: a `Tick`/`Elapsed` timer is the WPF002 pattern's job
// (released by Stop()/detach), and DispatcherTimer is not even IDisposable, so
// matching `*Timer` here would double-report and false-positive a stopped timer.
static bool IsDisposableType(string t) =>
    t is "IDisposable" or "IAsyncDisposable" or "CancellationTokenSource"
       or "HttpClient" or "SerialPort" or "SqlConnection"
    || t.EndsWith("Stream") || t.EndsWith("Reader") || t.EndsWith("Writer")
    || t.EndsWith("Subscription");

// --- P-006: DI registration + constructor graph (DI001 captive dependency) ---
// A syntactic pass over the same trees, independent of the event/disposable
// detectors: collect each class's constructor parameter types (the dependency
// graph), then each conventional IServiceCollection registration
// (Add{Singleton,Scoped,Transient}, the generic `<TService[, TImpl]>` form or the
// `typeof(...)` form) and emit `services` facts {name, lifetime, deps, file, line}
// that ownlang/di.py checks for captive dependencies. The registration's `name`
// is the SERVICE type others inject; `deps` are the IMPLEMENTATION's constructor
// parameter types. Factory/reflection/open-generic shapes we cannot read are
// recorded as unknown-dep nodes (deps: []) — silent, never guessed (P-006 scope).
static List<object> ExtractServices(List<(string file, SyntaxTree tree)> parsed)
{
    // 1. class name -> its widest constructor's parameter type names (the DI ctor).
    var ctorDeps = new Dictionary<string, List<string>>();
    foreach (var (_, tree) in parsed)
        foreach (var node in tree.GetRoot().DescendantNodes())
        {
            if (node is not ClassDeclarationSyntax cls)
                continue;
            // Candidate parameter lists: the C# 12 primary constructor (on the
            // class declaration itself) plus the PUBLIC explicit constructors —
            // take the widest. Primary-constructor injection (`class Foo(Dep d)`)
            // has no ConstructorDeclarationSyntax member, so it must be read off
            // the declaration or DI001 misses modern .NET 8 services; and the
            // default IServiceProvider only uses public constructors, so a wider
            // non-public ctor's parameters must not count as real deps (Codex).
            ParameterListSyntax? widest = cls.ParameterList;
            foreach (var m in cls.Members)
                if (m is ConstructorDeclarationSyntax ctor
                    && IsPublicCtor(ctor.Modifiers)
                    && (widest is null
                        || ctor.ParameterList.Parameters.Count > widest.Parameters.Count))
                    widest = ctor.ParameterList;
            var deps = new List<string>();
            if (widest is not null)
                foreach (var p in widest.Parameters)
                {
                    var tn = p.Type is null ? null : DiTypeName(p.Type);
                    if (tn is not null)
                        deps.Add(tn);
                }
            ctorDeps[cls.Identifier.Text] = deps;   // last decl wins (core dedups by name)
        }

    // 2. registrations -> service facts at the registration site.
    var services = new List<object>();
    foreach (var (file, tree) in parsed)
        foreach (var node in tree.GetRoot().DescendantNodes())
        {
            if (node is not InvocationExpressionSyntax inv
                || inv.Expression is not MemberAccessExpressionSyntax ma)
                continue;
            var lifetime = RegistrationLifetime(ma.Name.Identifier.Text);
            if (lifetime is null)
                continue;
            ResolveRegistration(ma.Name, inv.ArgumentList, out var service, out var impl);
            if (service is null)        // not a conventional typed registration -> skip
                continue;
            var deps = impl is not null && ctorDeps.TryGetValue(impl, out var d)
                ? d : new List<string>();
            services.Add(new
            {
                name = service,
                lifetime,
                deps,
                file,
                line = node.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
            });
        }
    return services;
}

// The DI lifetime for an IServiceCollection registration method, or null when the
// method name is not one of the three conventional registrations.
static string? RegistrationLifetime(string method) => method switch
{
    "AddSingleton" => "singleton",
    "AddScoped" => "scoped",
    "AddTransient" => "transient",
    _ => null,
};

// Service + implementation type for a registration, from the generic type
// arguments (`Add*<TService[, TImpl]>`) or the `typeof(...)` arguments
// (`Add*(typeof(TService)[, typeof(TImpl)])`). A null service means it is not a
// typed registration we can read (a bare instance / factory) -> the caller skips.
static void ResolveRegistration(SimpleNameSyntax name, ArgumentListSyntax args,
                                out string? service, out string? impl)
{
    service = null;
    impl = null;
    if (name is GenericNameSyntax gen)
    {
        var targs = gen.TypeArgumentList.Arguments;
        if (targs.Count >= 1)
            service = DiTypeName(targs[0]);
        impl = targs.Count >= 2 ? DiTypeName(targs[1]) : service;
        return;
    }
    string? first = null, second = null;
    var seen = 0;
    foreach (var a in args.Arguments)
        if (a.Expression is TypeOfExpressionSyntax tof)
        {
            if (seen == 0) first = DiTypeName(tof.Type);
            else if (seen == 1) second = DiTypeName(tof.Type);
            seen++;
        }
    if (first is not null)
    {
        service = first;
        impl = second ?? first;
    }
}

// The simple (rightmost) name of a type, for matching a registration's service
// type to a constructor parameter's type. A generic name drops its arguments
// (`ILogger<T>` -> `ILogger`); a predefined type (`int`) yields null.
static string? DiTypeName(TypeSyntax t) => t switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    GenericNameSyntax g => g.Identifier.Text,
    QualifiedNameSyntax q => DiTypeName(q.Right),
    AliasQualifiedNameSyntax aq => DiTypeName(aq.Name),
    _ => null,
};

// DI's default IServiceProvider resolves through PUBLIC constructors only — an
// explicit ctor with no access modifier defaults to private and DI never uses it.
static bool IsPublicCtor(SyntaxTokenList modifiers)
{
    foreach (var m in modifiers)
        if (m.IsKind(SyntaxKind.PublicKeyword))
            return true;
    return false;
}

var components = new List<object>();
// P-016 B0b/B2: per-method flow bodies (only when --flow-locals).
var flowFunctions = new List<object>();

// Parse every input into a syntax tree first (keeping the file path we report
// it under), then build ONE compilation over all of them so the SemanticModel
// resolves cross-file and cross-project symbols (P-014 Tier A).
var parsed = new List<(string file, SyntaxTree tree)>();
foreach (var path in inputs)
{
    // Defensive: an explicit input that is not a readable file (a directory
    // passed by mistake, a deleted path) is skipped with a note, never an
    // unhandled exception that aborts the whole scan.
    if (!File.Exists(path))
    {
        Console.Error.WriteLine($"ownsharp-extract: skipping (not a file): {path}");
        continue;
    }
    string text;
    try
    {
        text = File.ReadAllText(path);
    }
    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
    {
        // A locked/unreadable file is skipped with a note, not an abort.
        Console.Error.WriteLine($"ownsharp-extract: skipping unreadable file: {path} ({ex.Message})");
        continue;
    }
    parsed.Add((Rel(path), CSharpSyntaxTree.ParseText(text, path: path)));
}

// Project-local compilation (P-014 Tier A): the framework reference set is this
// runtime's trusted platform assemblies — zero-config, on disk wherever `dotnet`
// runs; no third-party / MSBuild references. Enough to resolve primitives,
// in-project types and BCL events; external types (WPF/DevExpress) stay
// unresolved and are surfaced as OWN050 "unchecked", never guessed as leaks.
// Error-tolerant: compile diagnostics are irrelevant — we only read symbols.
var tpa = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "")
    .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
    .Where(p => p.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
    .ToList();
var refNames = new HashSet<string>(tpa.Select(Path.GetFileName), StringComparer.OrdinalIgnoreCase);
var references = tpa.Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
// P-004 WPF profile: widen the reference set with assemblies named by the
// OWN_EXTRA_REF_DIRS env var (colon-separated dirs) — e.g. the WindowsDesktop ref
// pack — so framework events/timers (Button.Click, DispatcherTimer.Tick) resolve to
// real symbols instead of surfacing as OWN050 on a WPF app. Additive and best-
// effort: unset => unchanged behaviour; a DLL whose simple name a TPA reference
// already provides is skipped so System.* is not double-referenced from two packs.
foreach (var dir in (Environment.GetEnvironmentVariable("OWN_EXTRA_REF_DIRS") ?? "")
             .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
{
    if (!Directory.Exists(dir)) continue;
    var added = 0;
    foreach (var dll in Directory.EnumerateFiles(dir, "*.dll"))
        if (refNames.Add(Path.GetFileName(dll)))
        { references.Add(MetadataReference.CreateFromFile(dll)); added++; }
    Console.Error.WriteLine($"extractor: +{added} extra references from {dir}");
}
var compilation = CSharpCompilation.Create(
    "own", parsed.Select(p => p.tree), references,
    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

// --flow-locals coverage counters (--stats). A method "with a local" here is one
// that has a non-escaping `new` IDisposable worth tracking; of those we either
// flow-analyse it or honestly skip it (an unmodelled for/do/try/switch/async made
// LowerFlowBody bail). methods_with_local == analysed + skipped.
int statMethodsWithLocal = 0, statMethodsAnalysed = 0, statMethodsSkipped = 0;

foreach (var (file, tree) in parsed)
{
    var model = compilation.GetSemanticModel(tree);
    var root = tree.GetRoot();

    foreach (var cls in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
    {
        var assigns = cls.DescendantNodes().OfType<AssignmentExpressionSyntax>().ToList();

        // every `target -= handler` in this class, keyed by "left|right".
        var unsub = new HashSet<string>();
        foreach (var a in assigns)
            if (a.IsKind(SyntaxKind.SubtractAssignmentExpression) && IsHandler(a.Right))
                unsub.Add($"{a.Left}|{a.Right}");

        // every receiver with a `.Stop()` call: a timer detached this way counts
        // as released even without an explicit `Tick -=` (e.g. Stop() in Dispose).
        var stopped = new HashSet<string>();
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text == "Stop")
                stopped.Add(m.Expression.ToString());

        // Fields/locals this class constructs (`new`) — it OWNS them, so their
        // lifetime cannot exceed the class's. Used by the self-owned-subscription
        // exemption (P-004) just below and by the disposable detector (WPF003).
        var constructed = new HashSet<string>();
        foreach (var fd in cls.Members.OfType<FieldDeclarationSyntax>())
            foreach (var v in fd.Declaration.Variables)
                if (v.Initializer?.Value is ObjectCreationExpressionSyntax
                                          or ImplicitObjectCreationExpressionSyntax)
                    constructed.Add(v.Identifier.Text);
        foreach (var a in assigns)
            if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                && a.Right is ObjectCreationExpressionSyntax
                           or ImplicitObjectCreationExpressionSyntax
                && FieldName(a.Left) is { } fn)
                constructed.Add(fn);

        // P-004 (extended) self-owned set for the SUBSCRIPTION exemption ONLY. A
        // field can be owned without a direct `_f = new ...`; fold in two more
        // shapes the WPF mining run surfaced. Kept OUT of `constructed` so the
        // WPF003 disposal detector keeps demanding disposal of `new`'d fields only
        // (you don't dispose a borrowed-by-ref value or a template part). Both paths
        // require an actual FIELD (a `ref`/`out` local or parameter is not owned):
        //   * ref/out construction by one of THIS class's OWN helpers —
        //     `BuildCorner(ref _thumb, ...)`: the class populates the field itself,
        //     so it owns it. A `ref`/`out` to an EXTERNAL method
        //     (`container.TryResolve(out _bus)`, `Interlocked.Exchange(ref _bus, ..)`)
        //     only proves the callee CAN assign it — it may be an injected, longer-
        //     lived publisher — so it is NOT exempted, else a real leak is suppressed.
        //   * template parts — `_part = GetTemplateChild("PART_x") as T`: a control
        //     owns the parts of its own template (collectable part<->control cycle).
        var clsSymbol = model.GetDeclaredSymbol(cls);
        var selfOwned = new HashSet<string>(constructed);
        foreach (var arg in cls.DescendantNodes().OfType<ArgumentSyntax>())
            if ((arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword)
                 || arg.RefKindKeyword.IsKind(SyntaxKind.OutKeyword))
                && model.GetSymbolInfo(arg.Expression).Symbol is IFieldSymbol rf
                && arg.Parent?.Parent is InvocationExpressionSyntax callInv
                && model.GetSymbolInfo(callInv).Symbol is IMethodSymbol callee
                && clsSymbol is not null
                && SymbolEqualityComparer.Default.Equals(callee.ContainingType, clsSymbol))
                selfOwned.Add(rf.Name);
        foreach (var a in assigns)
            if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                && model.GetSymbolInfo(a.Left).Symbol is IFieldSymbol tf
                && IsTemplatePartFetch(a.Right))
                selfOwned.Add(tf.Name);

        var subs = new List<object>();
        foreach (var a in assigns)
        {
            if (!emitEvents || !a.IsKind(SyntaxKind.AddAssignmentExpression))
                continue;
            // P-014 Tier A: a `+=` is an event subscription only when the LHS binds
            // to an event symbol. `sum += value` (a local/field/property) resolves
            // to a non-event and is skipped — arithmetic, not a leak. When the LHS
            // cannot be resolved (its declaring type is an unreferenced external
            // assembly) we do NOT guess a leak: a handler-shaped RHS becomes an
            // OWN050 "unchecked" marker that the core surfaces as an advisory note.
            var leftSymbol = model.GetSymbolInfo(a.Left).Symbol;
            if (leftSymbol is IEventSymbol ev)
            {
                var isTimer = IsTimerEvent(a.Left);
                // P-004 lifetime exemptions — skip, not a leak (timers excluded: a
                // running timer is dispatcher-rooted regardless):
                //  - self-owned source (`this`, or a field/local the class
                //    constructs) — the source<->this cycle is GC-collectable;
                //  - static handler — a static method has a null delegate target,
                //    so no instance is retained and nothing can leak.
                if (!isTimer && (IsSelfOwnedSource(a.Left, ev, model, selfOwned)
                                 || IsStaticHandler(a.Right, model)))
                    continue;
                // P-004 tiering: a local-variable source is method-bounded — it
                // cannot outlive `this`, so it is not a heap leak; drop it (the same
                // spirit as the self-owned drop above). "static"/"injected" ride
                // along as a `source` hint so the core can grade the severity.
                var source = isTimer ? "static"
                                     : SubscriptionSourceKind(a.Left, ev, model);
                if (source == "local")
                    continue;
                var released = unsub.Contains($"{a.Left}|{a.Right}")
                    || (isTimer && Receiver(a.Left) is { } recv && stopped.Contains(recv));
                subs.Add(new
                {
                    @event = a.Left.ToString(),
                    handler = a.Right.ToString(),
                    line = LineOf(a.Left),
                    released,
                    // A static-source subscription (a process-lived event, or a
                    // static-field/property receiver) is a region escape, not a
                    // token leak: route it through the lifetime engine as a
                    // `capture` -> OWN014 (the WPF "escape to App"). The bridge
                    // skips a released capture (a `-=` on close), so a correctly
                    // unsubscribed static subscription stays silent. An injected/
                    // unknown source stays a token `subscription` (OWN001,
                    // severity-tiered); timers are their own kind. (P-004 WPF005;
                    // see ownlang/ownir.py `capture`.)
                    resource = isTimer ? "timer"
                             : source == "static" ? "capture"
                             : "subscription",
                    source,
                    lambda = !isTimer && IsLambdaHandler(a.Right),
                });
            }
            else if (leftSymbol is null && IsHandler(a.Right))
            {
                subs.Add(new
                {
                    @event = a.Left.ToString(),
                    handler = a.Right.ToString(),
                    line = LineOf(a.Left),
                    resource = "unresolved-subscription",
                });
            }
        }

        // WPF003: an IDisposable field the class constructs (`new`) but never
        // disposes. Owned (not injected) = in `constructed` (computed above);
        // released = a `<field>.Dispose()` call somewhere in the class.
        var disposed = new HashSet<string>();
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text is "Dispose" or "DisposeAsync"
                && FieldName(m.Expression) is { } df)
                disposed.Add(df);

        foreach (var fd in cls.Members.OfType<FieldDeclarationSyntax>())
        {
            // a `static` IDisposable field is a process-lifetime singleton (a shared
            // HttpClient, a sentinel like Dapper's DisposedReader.Instance) — it is
            // intentionally never disposed, so it is not an owned leak.
            if (fd.Modifiers.Any(m => m.IsKind(SyntaxKind.StaticKeyword)))
                continue;
            var tname = fd.Declaration.Type.ToString();
            if (!IsDisposableType(tname))
                continue;
            foreach (var v in fd.Declaration.Variables)
            {
                if (!constructed.Contains(v.Identifier.Text))
                    continue;
                subs.Add(new
                {
                    @event = v.Identifier.Text,
                    line = LineOf(v),
                    released = disposed.Contains(v.Identifier.Text),
                    resource = "disposable",
                    type = tname,
                });
            }
        }

        // WPF004: a `X.Subscribe(...)` whose IDisposable result is ignored — the
        // call stands as a bare statement (not assigned/returned/added), so the
        // token is dropped and never disposed. Member-access only (`x.Subscribe`),
        // to avoid flagging bare void `Subscribe(...)` helpers.
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text == "Subscribe"
                && inv.Parent is ExpressionStatementSyntax)
                subs.Add(new
                {
                    @event = m.ToString(),
                    line = LineOf(inv),
                    released = false,
                    resource = "subscribe",
                    // A self-rooted `this.WhenAnyValue(p => p.SelfProp)` chain is a
                    // GC-collectible self-cycle: the bridge drops `source: "self"`.
                    // Any other (external) source stays a flagged leak (null source).
                    source = IsSelfRootedWhenAny(m.Expression) ? "self" : null,
                });

        // POOL001: an ArrayPool<T> buffer `Rent`ed but never `Return`ed, the Rent
        // recognised via the shared semantic `IsPoolRent` (so an aliased pool receiver
        // binds and a non-pool `.Rent` does not false-match — one definition, the flow
        // pass below is the other consumer). Matched per member so a `buf` returned in
        // one method does not mask a
        // leak of a same-named `buf` in another. Under --flow-locals the
        // path-sensitive flow detector supersedes this for buffers held in LOCALS
        // (and additionally catches double-return / use-after-return) — but it only
        // tracks local declarations, so field/assignment-backed rents still need
        // this syntactic pass; the local-declaration rents are skipped below to
        // avoid double-reporting them (Codex).
        foreach (var member in cls.Members)
        {
            var rented = new List<(string Name, int Line)>();
            foreach (var inv in member.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (IsPoolRent(inv, model))
                {
                    string? name = inv.Parent switch
                    {
                        // a local-declaration rent is the flow pass's job under
                        // --flow-locals; skip it here so it is not double-reported.
                        EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax vd }
                            => flowLocals ? null : vd.Identifier.Text,
                        // a field/assignment rent (`_buf = pool.Rent(...)`) is NOT a
                        // flow candidate, so this pass keeps it in both modes.
                        AssignmentExpressionSyntax asg => FieldName(asg.Left),
                        _ => null,
                    };
                    if (name != null)
                        rented.Add((name, LineOf(inv)));
                }
            if (rented.Count == 0)
                continue;
            var returned = new HashSet<string>();
            foreach (var inv in member.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (inv.Expression is MemberAccessExpressionSyntax m
                    && m.Name.Identifier.Text == "Return"
                    && inv.ArgumentList.Arguments.Count > 0
                    && FieldName(inv.ArgumentList.Arguments[0].Expression) is { } rn)
                    returned.Add(rn);
            foreach (var (name, line) in rented)
                subs.Add(new
                {
                    @event = name,
                    line,
                    released = returned.Contains(name),
                    resource = "pool",
                });
        }

        // D1 (P-005): a local IDisposable the method `new`s but never disposes,
        // not guarded by `using`, and not handed out (returned / passed as an
        // argument / assigned out) — ownership transfer is ambiguous syntactically
        // (P-005 D5), so those are conservatively excluded. Per member. Suppressed
        // under --flow-locals, where the path-sensitive flow detector supersedes it.
        if (!flowLocals)
        foreach (var member in cls.Members)
        {
            var usingGuarded = new HashSet<string>();
            foreach (var u in member.DescendantNodes().OfType<UsingStatementSyntax>())
                if (u.Declaration is { } ud)
                    foreach (var v in ud.Variables)
                        usingGuarded.Add(v.Identifier.Text);

            var escaped = new HashSet<string>();
            foreach (var id in member.DescendantNodes().OfType<IdentifierNameSyntax>())
                if (id.Parent is ReturnStatementSyntax or ArgumentSyntax
                    || (id.Parent is AssignmentExpressionSyntax asg && asg.Right == id))
                    escaped.Add(id.Identifier.Text);

            var disposedLocal = new HashSet<string>();
            foreach (var inv in member.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (inv.Expression is MemberAccessExpressionSyntax m
                    && m.Name.Identifier.Text is "Dispose" or "DisposeAsync"
                    && FieldName(m.Expression) is { } dn)
                    disposedLocal.Add(dn);

            foreach (var ld in member.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
            {
                if (ld.UsingKeyword != default)
                    continue;   // `using var x = ...` is safe
                foreach (var v in ld.Declaration.Variables)
                {
                    var name = v.Identifier.Text;
                    if (usingGuarded.Contains(name) || escaped.Contains(name))
                        continue;
                    string? ctype = v.Initializer?.Value switch
                    {
                        ObjectCreationExpressionSyntax oc => oc.Type.ToString(),
                        ImplicitObjectCreationExpressionSyntax => ld.Declaration.Type.ToString(),
                        _ => null,
                    };
                    if (ctype is null || !IsDisposableType(ctype))
                        continue;
                    subs.Add(new
                    {
                        @event = name,
                        line = LineOf(v),
                        released = disposedLocal.Contains(name),
                        resource = "local-disposable",
                        type = ctype,
                    });
                }
            }
        }

        // P-016 B0b/B2 (--flow-locals): per-method flow facts for non-escaping local
        // IDisposables. The core checks them path-sensitively (OWN001/002/003).
        // Methods with an unmodelled construct (loop/try/switch) are honestly skipped.
        if (flowLocals)
            foreach (var method in cls.Members.OfType<BaseMethodDeclarationSyntax>())
            {
                if (method.Body is not { } mbody)
                    continue;
                var candidates = new HashSet<string>();
                var poolBuffers = new HashSet<string>();   // candidates that are ArrayPool<T> buffers
                foreach (var ld in mbody.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
                {
                    if (ld.UsingKeyword != default)
                        continue;
                    foreach (var v in ld.Declaration.Variables)
                        if (v.Initializer is { Value: ObjectCreationExpressionSyntax
                                                   or ImplicitObjectCreationExpressionSyntax } init
                            && model.GetTypeInfo(init.Value).Type is { } dt
                            && ImplementsIDisposable(dt) && !IsDisposeOptional(dt))
                            candidates.Add(v.Identifier.Text);
                        else if (IsPoolRent(v.Initializer?.Value, model))   // an ArrayPool<T> buffer
                        {
                            candidates.Add(v.Identifier.Text);
                            poolBuffers.Add(v.Identifier.Text);
                        }
                }
                if (candidates.Count == 0)
                    continue;
                // A local that escapes (returned / assigned out) is conservatively not
                // tracked — its release may be the caller's job. For an IDisposable,
                // passing it as an argument is an ambiguous ownership transfer too; for
                // a pooled buffer the convention is the RENTER returns it, so arg-passing
                // is a borrow (a use), not an escape — else `pool.Return(buf)` and
                // `Work(buf)` would untrack it and hide the double-return / use-after-return.
                var escapedLocals = new HashSet<string>();
                foreach (var idn in mbody.DescendantNodes().OfType<IdentifierNameSyntax>())
                {
                    var nm = idn.Identifier.Text;
                    if (!candidates.Contains(nm))
                        continue;
                    if (idn.Parent is ReturnStatementSyntax
                        || (idn.Parent is AssignmentExpressionSyntax asg && asg.Right == idn)
                        || (idn.Parent is ArgumentSyntax && !poolBuffers.Contains(nm)))
                        escapedLocals.Add(nm);
                }
                var tracked = new HashSet<string>(candidates);
                tracked.ExceptWith(escapedLocals);
                if (tracked.Count == 0)
                    continue;
                statMethodsWithLocal++;
                var fbody = LowerFlowBody(mbody, tracked, model);
                if (fbody is null || fbody.Count == 0)
                {
                    statMethodsSkipped++;   // unmodelled construct -> honestly skipped
                    continue;
                }
                statMethodsAnalysed++;
                flowFunctions.Add(new
                {
                    name = $"{cls.Identifier.Text}.{MethodName(method)}",
                    file,
                    body = fbody,
                });
            }

        if (subs.Count > 0)
            components.Add(new { name = cls.Identifier.Text, file, subscriptions = subs });
    }
}

// ownir_version stamps the fact-schema vocabulary; the Python core rejects a
// mismatch loudly (ownlang/ownir.py OWNIR_VERSION) rather than mis-reading facts.
// `stats` is additive coverage metadata — the core's load() ignores unknown keys.
var facts = new
{
    ownir_version = 0,
    module = "Extracted",
    components,
    // P-006: the DI registration + ctor graph (empty when the scan has no
    // Add{Singleton,Scoped,Transient} calls). ownlang/di.py turns it into DI001.
    services = ExtractServices(parsed),
    functions = flowFunctions,
    stats = new
    {
        methods_with_local = statMethodsWithLocal,
        methods_flow_analysed = statMethodsAnalysed,
        methods_skipped_unmodelled = statMethodsSkipped,
    },
};
var json = JsonSerializer.Serialize(facts, new JsonSerializerOptions { WriteIndented = true });

if (reportStats)
    Console.Error.WriteLine(
        $"coverage: {statMethodsAnalysed}/{statMethodsWithLocal} methods with a "
        + $"disposable local flow-analysed; {statMethodsSkipped} skipped (unmodelled construct)");

if (outPath is null) Console.WriteLine(json);
else File.WriteAllText(outPath, json);
return 0;
