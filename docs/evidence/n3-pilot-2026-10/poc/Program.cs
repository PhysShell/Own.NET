// N3 pilot PoC: a scope-owned object reaches detached work (01-preregistration-g1-g4.md §2-§3).
// Research only. Parses a source tree, never builds or restores it.
//
// usage: n3poc <src-dir> --lifetimes lifetimes.json --refs <ref-dir> [--refs <ref-dir> ...] --out warnings.tsv
//
// lifetimes.json (written by n3_run.py from extractor `services` facts under G0 rules 1, 2 and 4):
//   {"service": {"IFoo": "scoped" | "singleton" | "transient" | "mixed"},
//    "impl":    {"Foo": "scoped" | ...},
//    "impls":   {"IFoo": ["Foo", ...]}}
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var srcDir = args[0];
string? lifetimesPath = null, outPath = null;
var refDirs = new List<string>();
for (var i = 1; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--lifetimes": lifetimesPath = args[++i]; break;
        case "--refs": refDirs.Add(args[++i]); break;
        case "--out": outPath = args[++i]; break;
        default: throw new ArgumentException($"unknown argument {args[i]}");
    }
}

var lt = Lifetimes.Load(lifetimesPath);
var skip = new[] { "/obj/", "/bin/", "/.git/", "/node_modules/" };
var files = Directory.EnumerateFiles(srcDir, "*.cs", SearchOption.AllDirectories)
    .Where(f => !skip.Any(s => f.Replace('\\', '/').Contains(s))).OrderBy(f => f, StringComparer.Ordinal).ToList();
var parse = new CSharpParseOptions(LanguageVersion.Preview);
var trees = files.Select(f => CSharpSyntaxTree.ParseText(File.ReadAllText(f), parse,
    Path.GetRelativePath(srcDir, f).Replace('\\', '/'))).ToList();
var refs = refDirs.SelectMany(d => Directory.EnumerateFiles(d, "*.dll"))
    .Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
var comp = CSharpCompilation.Create("n3scan", trees, refs,
    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, nullableContextOptions: NullableContextOptions.Enable));

// S2: AddDbContext<T>(...) lifetimes, read from syntax (EF Core is not referenced).
var dbContexts = new Dictionary<string, string>(StringComparer.Ordinal);
foreach (var t in trees)
{
    foreach (var inv in t.GetRoot().DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (inv.Expression is not MemberAccessExpressionSyntax { Name: GenericNameSyntax g }
            || g.Identifier.Text != "AddDbContext" || g.TypeArgumentList.Arguments.Count == 0) continue;
        var name = Syn.SimpleName(g.TypeArgumentList.Arguments[^1]);
        var argText = inv.ArgumentList.ToString();
        var life = argText.Contains("ServiceLifetime.Singleton") ? "singleton"
            : argText.Contains("ServiceLifetime.Transient") ? "transient" : "scoped";
        dbContexts[name] = dbContexts.TryGetValue(name, out var prev) && prev != life ? "mixed" : life;
    }
}

var scan = new Scanner(comp, lt, dbContexts);
foreach (var t in trees) scan.Run(t);

using var w = outPath is null ? Console.Out : new StreamWriter(outPath, false, new System.Text.UTF8Encoding(false));
w.WriteLine("file\tline\tclass\tmethod\tS\tD\tobject\tholder\tcapture_line\tsnippet");
foreach (var r in scan.Warnings.OrderBy(r => r.File, StringComparer.Ordinal).ThenBy(r => r.Line).ThenBy(r => r.Object))
    w.WriteLine(string.Join('\t', r.File, r.Line, r.Class, r.Method, r.S, r.D, r.Object, r.Holder, r.CaptureLine, r.Snippet));
Console.Error.WriteLine($"n3poc: {files.Count} files, {scan.Warnings.Count} warnings, " +
    $"{scan.RequestBoundTypes} request-bound types, {scan.DetachedSites} detached sites, " +
    $"{scan.UnknownSites} detached sites using only unknown-ownership fields");
return 0;

sealed record Warning(string File, int Line, string Class, string Method, string S, string D, string Object,
    string Holder, int CaptureLine, string Snippet);

sealed class Lifetimes
{
    public Dictionary<string, string> Service = new(StringComparer.Ordinal);
    public Dictionary<string, string> Impl = new(StringComparer.Ordinal);
    public Dictionary<string, List<string>> Impls = new(StringComparer.Ordinal);

    public static Lifetimes Load(string? path)
    {
        var l = new Lifetimes();
        if (path is null) return l;
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        foreach (var p in doc.RootElement.GetProperty("service").EnumerateObject()) l.Service[p.Name] = p.Value.GetString()!;
        foreach (var p in doc.RootElement.GetProperty("impl").EnumerateObject()) l.Impl[p.Name] = p.Value.GetString()!;
        foreach (var p in doc.RootElement.GetProperty("impls").EnumerateObject())
            l.Impls[p.Name] = p.Value.EnumerateArray().Select(x => x.GetString()!).ToList();
        return l;
    }

    public string Of(string typeName) => Service.TryGetValue(typeName, out var v) ? v : "unknown";
}

static class Syn
{
    public static string SimpleName(TypeSyntax t) => t switch
    {
        QualifiedNameSyntax q => SimpleName(q.Right),
        AliasQualifiedNameSyntax a => SimpleName(a.Name),
        GenericNameSyntax g => g.Identifier.Text,
        IdentifierNameSyntax i => i.Identifier.Text,
        NullableTypeSyntax n => SimpleName(n.ElementType),
        _ => t.ToString(),
    };

    public static string SimpleName(ITypeSymbol? t) => t switch
    {
        null => "",
        INamedTypeSymbol n => n.Name,
        _ => t.Name,
    };

    public static int Line(SyntaxNode n) => n.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    public static string Snip(SyntaxNode n)
    {
        var s = n.ToString().Replace('\t', ' ').Replace('\r', ' ').Replace('\n', ' ');
        while (s.Contains("  ")) s = s.Replace("  ", " ");
        return s.Length > 160 ? s[..160] + "…" : s;
    }
}

sealed class Scanner(CSharpCompilation comp, Lifetimes lt, Dictionary<string, string> dbContexts)
{
    public readonly List<Warning> Warnings = new();
    public int RequestBoundTypes, DetachedSites, UnknownSites;
    readonly HashSet<(string, int, string)> _seen = new();

    static readonly HashSet<string> RequestBases = new(StringComparer.Ordinal)
        { "ControllerBase", "Controller", "PageModel", "Hub" };
    static readonly HashSet<string> HttpContextMembers = new(StringComparer.Ordinal)
        { "HttpContext", "Request", "Response" };
    static readonly HashSet<string> MapMethods = new(StringComparer.Ordinal)
        { "MapGet", "MapPost", "MapPut", "MapDelete", "MapPatch", "MapMethods", "Map" };

    // --- ownership (§2) ---

    // R1/R2/R3: request-bound holder. Returns the reason, or null.
    string? RequestBound(INamedTypeSymbol type, ClassDeclarationSyntax decl)
    {
        if (decl.AttributeLists.SelectMany(a => a.Attributes).Any(a => Syn.SimpleName(a.Name) is "ApiController"))
            return "R1";
        for (var b = type.BaseType; b is not null; b = b.BaseType)
            if (RequestBases.Contains(b.Name)) return b.Name is "PageModel" or "Hub" ? "R2" : "R1";
        // error-typed bases (no reference) keep their syntax name
        if (decl.BaseList?.Types.Any(t => RequestBases.Contains(Syn.SimpleName(t.Type))) == true) return "R1";
        if (lt.Impl.TryGetValue(type.Name, out var l) && l == "scoped") return "R3";
        return null;
    }

    // S2/S3/S4 for a type name injected into a request-bound holder.
    string? OwnershipOfInjected(string typeName)
    {
        if (dbContexts.TryGetValue(typeName, out var d) && d == "scoped") return "S2";
        if (typeName == "IServiceProvider") return "S4";
        if (typeName == "HttpClient") return null; // S5: never
        if (lt.Of(typeName) == "scoped") return "S3";
        return null;
    }

    // Fields/properties of the holder assigned from a constructor parameter, plus primary-constructor
    // parameters: symbol -> (S row, injected type name).
    Dictionary<ISymbol, (string S, string Type)> InjectedMembers(ClassDeclarationSyntax decl, SemanticModel sm)
    {
        var res = new Dictionary<ISymbol, (string, string)>(SymbolEqualityComparer.Default);
        var ctors = decl.Members.OfType<ConstructorDeclarationSyntax>().ToList();
        foreach (var ctor in ctors)
        {
            var ps = ctor.ParameterList.Parameters.ToDictionary(p => p.Identifier.Text, p => p);
            foreach (var asg in ctor.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            {
                var rhs = asg.Right is BinaryExpressionSyntax { RawKind: (int)SyntaxKind.CoalesceExpression } c ? c.Left : asg.Right;
                if (rhs is not IdentifierNameSyntax id || !ps.TryGetValue(id.Identifier.Text, out var p) || p.Type is null) continue;
                var target = sm.GetSymbolInfo(asg.Left).Symbol;
                var tn = Syn.SimpleName(p.Type);
                if (target is IFieldSymbol or IPropertySymbol && OwnershipOfInjected(tn) is { } s) res[target] = (s, tn);
            }
        }
        if (decl.ParameterList is { } pl)
            foreach (var p in pl.Parameters)
                if (p.Type is not null && sm.GetDeclaredSymbol(p) is { } ps && OwnershipOfInjected(Syn.SimpleName(p.Type)) is { } s)
                    res[ps] = (s, Syn.SimpleName(p.Type));
        return res;
    }

    // --- scan ---

    public void Run(SyntaxTree tree)
    {
        var sm = comp.GetSemanticModel(tree);
        foreach (var decl in tree.GetRoot().DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            if (sm.GetDeclaredSymbol(decl) is not INamedTypeSymbol type) continue;
            var rb = RequestBound(type, decl);
            if (rb is null) continue;
            RequestBoundTypes++;
            var injected = InjectedMembers(decl, sm);
            var ctx = new Ctx(tree, sm, decl, type, rb, injected, rb is "R1" or "R2");
            foreach (var m in decl.Members.OfType<BaseMethodDeclarationSyntax>())
            {
                if (m is ConstructorDeclarationSyntax) continue;
                ScanBody(ctx, m, MethodName(m), new Dictionary<ISymbol, (string, string)>(SymbolEqualityComparer.Default));
            }
        }
        // R2: middleware InvokeAsync(HttpContext ...) parameters and minimal-API handler lambdas.
        foreach (var m in tree.GetRoot().DescendantNodes().OfType<MethodDeclarationSyntax>()
                     .Where(m => m.Identifier.Text is "InvokeAsync" or "Invoke"))
        {
            var cls = m.FirstAncestorOrSelf<ClassDeclarationSyntax>();
            if (cls is null || sm.GetDeclaredSymbol(cls) is not INamedTypeSymbol type) continue;
            var locals = ParamOwnership(m.ParameterList, sm, requireHttpContext: true);
            if (locals.Count == 0) continue;
            var ctx = new Ctx(tree, sm, cls, type, "R2", new(SymbolEqualityComparer.Default), false);
            ScanBody(ctx, m, m.Identifier.Text, locals);
        }
        foreach (var inv in tree.GetRoot().DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (inv.Expression is not MemberAccessExpressionSyntax ma || !MapMethods.Contains(ma.Name.Identifier.Text)) continue;
            foreach (var arg in inv.ArgumentList.Arguments)
            {
                if (arg.Expression is not ParenthesizedLambdaExpressionSyntax lam) continue;
                var locals = ParamOwnership(lam.ParameterList, sm, requireHttpContext: false);
                if (locals.Count == 0) continue;
                var cls = inv.FirstAncestorOrSelf<ClassDeclarationSyntax>();
                var type = cls is null ? null : sm.GetDeclaredSymbol(cls) as INamedTypeSymbol;
                var ctx = new Ctx(tree, sm, cls, type, "R2", new(SymbolEqualityComparer.Default), false);
                ScanBody(ctx, lam, ma.Name.Identifier.Text + "(lambda)", locals);
            }
        }
    }

    Dictionary<ISymbol, (string, string)> ParamOwnership(ParameterListSyntax pl, SemanticModel sm, bool requireHttpContext)
    {
        var res = new Dictionary<ISymbol, (string, string)>(SymbolEqualityComparer.Default);
        var hasCtx = pl.Parameters.Any(p => p.Type is not null && Syn.SimpleName(p.Type) == "HttpContext");
        if (requireHttpContext && !hasCtx) return res;
        foreach (var p in pl.Parameters)
        {
            if (p.Type is null || sm.GetDeclaredSymbol(p) is not { } s) continue;
            var tn = Syn.SimpleName(p.Type);
            var row = tn is "HttpContext" or "HttpRequest" or "HttpResponse" ? "S1" : OwnershipOfInjected(tn);
            if (row is not null) res[s] = (row, tn);
        }
        return res;
    }

    static string MethodName(BaseMethodDeclarationSyntax m) => m switch
    {
        MethodDeclarationSyntax md => md.Identifier.Text,
        _ => m.Kind().ToString(),
    };

    sealed record Ctx(SyntaxTree Tree, SemanticModel Sm, ClassDeclarationSyntax? Decl, INamedTypeSymbol? Type,
        string Holder, Dictionary<ISymbol, (string S, string Type)> Injected, bool HasHttpContextProperty);

    // Scope-owned reference named by an expression's root identifier, or null.
    (string S, string Name)? OwnedRoot(Ctx c, ExpressionSyntax e, Dictionary<ISymbol, (string S, string Type)> locals,
        SyntaxNode? work)
    {
        var root = e;
        while (true)
        {
            if (root is MemberAccessExpressionSyntax ma && ma.Expression is not ThisExpressionSyntax) root = ma.Expression;
            else if (root is MemberAccessExpressionSyntax ma2) { root = ma2.Name; break; }
            else if (root is InvocationExpressionSyntax inv) root = inv.Expression;
            else if (root is ConditionalAccessExpressionSyntax ca) root = ca.Expression;
            else if (root is PostfixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.SuppressNullableWarningExpression } pu) root = pu.Operand;
            else if (root is ElementAccessExpressionSyntax ea) root = ea.Expression;
            else break;
        }
        if (root is not SimpleNameSyntax id) return null;
        return OwnedName(c, id, locals, work);
    }

    (string S, string Name)? OwnedName(Ctx c, SimpleNameSyntax id, Dictionary<ISymbol, (string S, string Type)> locals,
        SyntaxNode? work)
    {
        var sym = c.Sm.GetSymbolInfo(id).Symbol;
        if (sym is not null && locals.TryGetValue(sym, out var l))
        {
            // a local declared inside the detached work is not captured from outside
            if (work is not null && sym.Locations.Any(loc => work.Span.Contains(loc.SourceSpan) && loc.SourceTree == c.Tree)) return null;
            return (l.S, id.Identifier.Text);
        }
        if (sym is not null && c.Injected.TryGetValue(sym.OriginalDefinition, out var f)) return (f.S, id.Identifier.Text);
        if (c.HasHttpContextProperty && HttpContextMembers.Contains(id.Identifier.Text))
        {
            // the holder's own HttpContext/Request/Response property (resolved, or unresolved by name)
            if (sym is IPropertySymbol p && RequestBases.Contains(p.ContainingType.Name)) return ("S1", id.Identifier.Text);
            if (sym is null && !locals.Keys.Any(k => k.Name == id.Identifier.Text)) return ("S1", id.Identifier.Text);
        }
        return null;
    }

    void ScanBody(Ctx c, SyntaxNode body, string method, Dictionary<ISymbol, (string S, string Type)> locals)
    {
        // one-step local aliases: `var x = <scope-owned expr>;` outside any detached work (S1 accessor reads too)
        foreach (var v in body.DescendantNodes().OfType<VariableDeclaratorSyntax>())
        {
            if (v.Initializer?.Value is not { } init || c.Sm.GetDeclaredSymbol(v) is not { } vs) continue;
            if (IsInsideDetached(c, v, body)) continue;
            if (init is MemberAccessExpressionSyntax { Name.Identifier.Text: "HttpContext" } acc
                && c.Sm.GetTypeInfo(acc.Expression).Type?.Name == "IHttpContextAccessor")
            { locals[vs] = ("S1", "HttpContext"); continue; }
            var vt = c.Sm.GetTypeInfo(init).Type;
            if (init is SimpleNameSyntax or MemberAccessExpressionSyntax
                && OwnedRoot(c, (ExpressionSyntax)init, locals, null) is { } o
                && (init is SimpleNameSyntax || vt?.Name is "HttpContext" or "HttpRequest" or "HttpResponse"))
                locals[vs] = (o.S, vt?.Name ?? o.Name);
        }

        foreach (var inv in body.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var name = InvokedName(inv);
            if (name is null) continue;
            if (IsTaskStarter(c, inv, name) is { } startD)
            {
                if (!IsDiscarded(inv)) continue;
                DetachedSites++;
                var lam = inv.ArgumentList.Arguments.Select(a => a.Expression).FirstOrDefault(IsLambda);
                if (lam is null) continue;
                ReportUses(c, lam, method, startD, locals);
            }
            else if (IsQueue(c, inv, name))
            {
                DetachedSites++;
                foreach (var lam in inv.ArgumentList.Arguments.Select(a => a.Expression).Where(IsLambda))
                    ReportUses(c, lam, method, "D2", locals);
            }
            else if (IsDiscarded(inv) && !IsInsideDetached(c, inv, body))
            {
                if (inv.Expression is MemberAccessExpressionSyntax ma && ma.Expression is not ThisExpressionSyntax)
                {
                    // D3a: receiver is scope-owned
                    if (OwnedRoot(c, ma.Expression, locals, null) is not { } o) continue;
                    if (!ReturnsTask(c, inv, name)) continue;
                    DetachedSites++;
                    if (CompletesSynchronously(c, inv, ma)) continue;
                    Add(c, inv, method, o.S, "D3a", o.Name);
                }
                else if (SameClassCallee(c, inv) is { } callee)
                {
                    // D3b: one hop into a same-class method; uses after its first await
                    DetachedSites++;
                    if (UseAfterFirstAwait(c, inv, callee, locals) is { } u) Add(c, inv, method, u.S, "D3b", u.Name, u.Line);
                }
            }
        }
    }

    static bool IsLambda(ExpressionSyntax e) => e is LambdaExpressionSyntax or AnonymousMethodExpressionSyntax;

    static string? InvokedName(InvocationExpressionSyntax inv) => inv.Expression switch
    {
        MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
        SimpleNameSyntax s => s.Identifier.Text,
        MemberBindingExpressionSyntax mb => mb.Name.Identifier.Text,
        _ => null,
    };

    string? IsTaskStarter(Ctx c, InvocationExpressionSyntax inv, string name)
    {
        var recv = (inv.Expression as MemberAccessExpressionSyntax)?.Expression.ToString();
        if (name == "Run" && recv is "Task" or "System.Threading.Tasks.Task") return "D1";
        if (name == "StartNew" && recv is "Task.Factory") return "D1";
        if (name is "QueueUserWorkItem" or "UnsafeQueueUserWorkItem" && recv is "ThreadPool") return "D1";
        if (name == "Start" && inv.Expression is MemberAccessExpressionSyntax { Expression: ObjectCreationExpressionSyntax oc }
            && Syn.SimpleName(oc.Type) == "Thread" && oc.ArgumentList?.Arguments.FirstOrDefault()?.Expression is { } a && IsLambda(a))
            return "D1";
        return null;
    }

    bool IsQueue(Ctx c, InvocationExpressionSyntax inv, string name)
    {
        if (!(name.StartsWith("QueueBackgroundWorkItem", StringComparison.Ordinal) || name.StartsWith("Enqueue", StringComparison.Ordinal)))
            return false;
        if (inv.Expression is not MemberAccessExpressionSyntax ma) return false;
        if (ma.Expression.ToString() is "HostingEnvironment" or "System.Web.Hosting.HostingEnvironment") return true;
        var recvType = c.Sm.GetTypeInfo(ma.Expression).Type;
        var tn = recvType is null || recvType.TypeKind == TypeKind.Error ? DeclaredTypeName(c, ma.Expression) : recvType.Name;
        if (tn is null) return false;
        return lt.Of(tn) == "singleton" || tn.EndsWith("BackgroundTaskQueue", StringComparison.Ordinal);
    }

    string? DeclaredTypeName(Ctx c, ExpressionSyntax e)
    {
        var sym = c.Sm.GetSymbolInfo(e).Symbol;
        var t = sym switch { IFieldSymbol f => f.Type, IPropertySymbol p => p.Type, ILocalSymbol l => l.Type, IParameterSymbol p => p.Type, _ => null };
        return t?.Name;
    }

    // `_ = call;` or `call;` as a statement (optionally through .ConfigureAwait/.ContinueWith), never awaited.
    static bool IsDiscarded(InvocationExpressionSyntax inv)
    {
        SyntaxNode n = inv;
        while (n.Parent is MemberAccessExpressionSyntax { Name.Identifier.Text: "ConfigureAwait" or "ContinueWith" } ma
               && ma.Parent is InvocationExpressionSyntax outer) n = outer;
        if (n.Parent is ExpressionStatementSyntax) return true;
        return n.Parent is AssignmentExpressionSyntax { Left: IdentifierNameSyntax { Identifier.Text: "_" } } asg
               && asg.Parent is ExpressionStatementSyntax;
    }

    bool IsInsideDetached(Ctx c, SyntaxNode n, SyntaxNode body)
    {
        for (var p = n.Parent; p is not null && p != body; p = p.Parent)
        {
            if (p is not (LambdaExpressionSyntax or AnonymousMethodExpressionSyntax)) continue;
            if (p.Parent is ArgumentSyntax { Parent.Parent: InvocationExpressionSyntax inv } && InvokedName(inv) is { } nm
                && (IsTaskStarter(c, inv, nm) is not null || IsQueue(c, inv, nm))) return true;
        }
        return false;
    }

    bool ReturnsTask(Ctx c, InvocationExpressionSyntax inv, string name)
    {
        var t = c.Sm.GetTypeInfo(inv).Type;
        if (t is not null && t.TypeKind != TypeKind.Error) return t.Name is "Task" or "ValueTask";
        return name.EndsWith("Async", StringComparison.Ordinal); // unresolved type: name convention (reported)
    }

    // D3a silence: every resolved implementation of the callee is non-async and returns a completed task.
    bool CompletesSynchronously(Ctx c, InvocationExpressionSyntax inv, MemberAccessExpressionSyntax ma)
    {
        var tn = DeclaredTypeName(c, ma.Expression);
        if (tn is null) return false;
        var impls = lt.Impls.TryGetValue(tn, out var l) ? l : new List<string> { tn };
        var bodies = new List<MethodDeclarationSyntax>();
        foreach (var impl in impls)
            foreach (var t in comp.GetSymbolsWithName(impl, SymbolFilter.Type).OfType<INamedTypeSymbol>())
                foreach (var m in t.GetMembers(ma.Name.Identifier.Text).OfType<IMethodSymbol>())
                    foreach (var r in m.DeclaringSyntaxReferences)
                        if (r.GetSyntax() is MethodDeclarationSyntax md) bodies.Add(md);
        if (bodies.Count == 0) return false;
        return bodies.All(md => !md.Modifiers.Any(SyntaxKind.AsyncKeyword)
            && (md.ExpressionBody?.Expression.ToString() is { } eb && IsCompleted(eb)
                || md.Body?.Statements is [ReturnStatementSyntax { Expression: { } rex }] && IsCompleted(rex.ToString())));
    }

    static bool IsCompleted(string e) => e is "Task.CompletedTask" or "default" or "ValueTask.CompletedTask"
        || e.StartsWith("Task.FromResult", StringComparison.Ordinal);

    MethodDeclarationSyntax? SameClassCallee(Ctx c, InvocationExpressionSyntax inv)
    {
        if (c.Decl is null) return null;
        var target = inv.Expression is MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } m ? m.Name
            : inv.Expression as SimpleNameSyntax;
        if (target is null) return null;
        var sym = c.Sm.GetSymbolInfo(target).Symbol as IMethodSymbol
                  ?? c.Sm.GetSymbolInfo(target).CandidateSymbols.OfType<IMethodSymbol>().FirstOrDefault();
        if (sym is null || c.Type is null || !SymbolEqualityComparer.Default.Equals(sym.ContainingType, c.Type)) return null;
        // §3 D3b is a discarded *Task* call (`_ = MAsync(…)`): a void callee is not detached work by itself
        if (sym.ReturnType.Name is not ("Task" or "ValueTask")) return null;
        return sym.DeclaringSyntaxReferences.Select(r => r.GetSyntax()).OfType<MethodDeclarationSyntax>()
            .FirstOrDefault(md => md.Body is not null || md.ExpressionBody is not null);
    }

    (string S, string Name, int Line)? UseAfterFirstAwait(Ctx c, InvocationExpressionSyntax call, MethodDeclarationSyntax callee,
        Dictionary<ISymbol, (string S, string Type)> callerLocals)
    {
        var body = (SyntaxNode?)callee.Body ?? callee.ExpressionBody;
        if (body is null) return null;
        // the callee's own first await: one inside a nested lambda or local function does not suspend the callee
        var firstAwait = body.DescendantNodes(n => n == body || n is not (AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax))
            .OfType<AwaitExpressionSyntax>().FirstOrDefault();
        if (firstAwait is null) return null;
        // parameters bound to scope-owned arguments at this call site
        var calleeSm = comp.GetSemanticModel(callee.SyntaxTree);
        var paramOwn = new Dictionary<ISymbol, (string S, string Type)>(SymbolEqualityComparer.Default);
        var args = call.ArgumentList.Arguments;
        for (var i = 0; i < args.Count && i < callee.ParameterList.Parameters.Count; i++)
            if (OwnedRoot(c, args[i].Expression, callerLocals, null) is { } o
                && calleeSm.GetDeclaredSymbol(callee.ParameterList.Parameters[i]) is { } ps)
                paramOwn[ps] = (o.S, o.Name);
        var cc = c with { Sm = calleeSm, Tree = callee.SyntaxTree };
        foreach (var id in body.DescendantNodes().OfType<SimpleNameSyntax>())
        {
            if (id.SpanStart <= firstAwait.Span.End) continue;
            if (id.Parent is MemberAccessExpressionSyntax ma && ma.Name == id && ma.Expression is not ThisExpressionSyntax) continue;
            if (OwnedName(cc, id, paramOwn, null) is { } u) return (u.S, u.Name, Syn.Line(id));
        }
        return null;
    }

    void ReportUses(Ctx c, ExpressionSyntax lam, string method, string d, Dictionary<ISymbol, (string S, string Type)> locals)
    {
        var any = false;
        foreach (var id in lam.DescendantNodes().OfType<SimpleNameSyntax>())
        {
            // only the root of a member-access chain names the captured object
            if (id.Parent is MemberAccessExpressionSyntax ma && ma.Name == id && ma.Expression is not ThisExpressionSyntax) continue;
            if (id.Parent is MemberBindingExpressionSyntax) continue;
            if (OwnedName(c, id, locals, lam) is not { } o) continue;
            any = true;
            Add(c, lam.Parent?.Parent?.Parent ?? lam, method, o.S, d, o.Name, Syn.Line(id));
        }
        if (!any) UnknownSites++;
    }

    // `captureLine`: where the scope-owned object is used (D1/D2/D3b) or the call itself (D3a)
    void Add(Ctx c, SyntaxNode site, string method, string s, string d, string obj, int captureLine = 0)
    {
        var line = Syn.Line(site);
        if (!_seen.Add((c.Tree.FilePath, line, obj))) return;
        Warnings.Add(new Warning(c.Tree.FilePath, line, c.Type?.Name ?? "?", method, s, d, obj, c.Holder,
            captureLine == 0 ? line : captureLine, Syn.Snip(site)));
    }
}
