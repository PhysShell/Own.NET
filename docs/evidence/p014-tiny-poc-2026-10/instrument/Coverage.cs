// P-014 Tiny PoC — binding coverage per unit (DESIGN §4): site statuses, the G1/G2 counters, compiler errors,
// and the built-in isolation guard (a resolved symbol must come from the unit, its manifest or its closure).
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

sealed record Site(string File, int Start, int Length, int Line, string Kind, string Status, string Symbol, string Assembly);

sealed class UnitCoverage
{
    public readonly SortedDictionary<string, SortedDictionary<string, int>> Sites = new(StringComparer.Ordinal);
    public readonly SortedDictionary<string, int> Errors = new(StringComparer.Ordinal);
    public readonly List<string> Foreign = new();
    public readonly List<Site> AllSites = new();
    public readonly SortedDictionary<string, List<string>> Probes = new(StringComparer.Ordinal);
    public int MethodsTotal, MethodsWithRelevant, MethodsAllRelevantResolved;
    public void Inc(string kind, string key, int n = 1)
    {
        if (!Sites.TryGetValue(kind, out var d)) Sites[kind] = d = new SortedDictionary<string, int>(StringComparer.Ordinal);
        d[key] = d.GetValueOrDefault(key) + n;
    }
}

static class Coverage
{
    static readonly HashSet<string> AmbiguityIds = new() { "CS0104", "CS0121", "CS0229", "CS0433" };

    // extractor Program.cs:571 (IsHandler) and :5318 (IsDisposableType), ported unchanged
    static bool IsHandler(ExpressionSyntax rhs) => rhs is IdentifierNameSyntax || rhs is MemberAccessExpressionSyntax;
    static bool IsDisposableType(string t) =>
        t is "IDisposable" or "IAsyncDisposable" or "CancellationTokenSource" or "HttpClient" or "SerialPort" or "SqlConnection"
        || ((t.EndsWith("Stream") || t.EndsWith("Reader") || t.EndsWith("Writer") || t.EndsWith("Subscription"))
            && t is not ("PipeReader" or "PipeWriter" or "System.IO.Pipelines.PipeReader" or "System.IO.Pipelines.PipeWriter"));
    static bool ImplementsIDisposable(ITypeSymbol t) =>
        t.AllInterfaces.Any(i => i.ToDisplayString() is "System.IDisposable" or "System.IAsyncDisposable")
        || t.ToDisplayString() is "System.IDisposable" or "System.IAsyncDisposable";

    static bool ContainsError(ITypeSymbol? t) => t switch
    {
        null => true,
        IErrorTypeSymbol => true,
        IArrayTypeSymbol a => ContainsError(a.ElementType),
        IPointerTypeSymbol p => ContainsError(p.PointedAtType),
        INamedTypeSymbol n => n.TypeArguments.Any(ContainsError) || (n.ContainingType is { } ct && ContainsError(ct)),
        _ => false,
    };

    public static UnitCoverage Measure(CSharpCompilation comp, IEnumerable<SyntaxTree> trees, ISet<string>? allowedAssemblies, Func<string, string> rel)
    {
        var cov = new UnitCoverage();
        var diags = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
        foreach (var g in diags.GroupBy(d => d.Id)) cov.Errors[g.Key] = g.Count();
        var byTree = diags.Where(d => d.Location.SourceTree is not null).GroupBy(d => d.Location.SourceTree!).ToDictionary(g => g.Key, g => g.ToList());

        foreach (var tree in trees.OrderBy(t => t.FilePath, StringComparer.Ordinal))
        {
            var model = comp.GetSemanticModel(tree);
            var root = tree.GetRoot();
            var errs = byTree.GetValueOrDefault(tree) ?? new List<Diagnostic>();
            bool Err(Microsoft.CodeAnalysis.Text.TextSpan s) => errs.Any(d => d.Location.SourceSpan.IntersectsWith(s));
            bool Amb(Microsoft.CodeAnalysis.Text.TextSpan s) => errs.Any(d => AmbiguityIds.Contains(d.Id) && d.Location.SourceSpan.IntersectsWith(s));
            var file = rel(tree.FilePath);
            var text = tree.GetText();
            var siteStatus = new Dictionary<SyntaxNode, string>();

            void Record(SyntaxNode node, string kind, string status, ISymbol? sym)
            {
                var asm = sym?.ContainingAssembly?.Identity.ToString() ?? "";
                if (status == "resolved" && allowedAssemblies is not null && sym?.ContainingAssembly is { } ca && !allowedAssemblies.Contains(ca.Identity.ToString()))
                    cov.Foreign.Add($"{file}:{node.GetLocation().GetLineSpan().StartLinePosition.Line + 1} {kind} {sym.ToDisplayString()} @ {asm}");
                var line = node.GetLocation().GetLineSpan().StartLinePosition.Line;
                cov.AllSites.Add(new Site(file, node.SpanStart, node.Span.Length, line + 1, kind, status, sym?.ToDisplayString() ?? "", asm));
                siteStatus[node] = status;
                var lt = text.Lines[line].ToString();
                var pi = lt.IndexOf("/*probe:", StringComparison.Ordinal);
                if (pi >= 0)
                {
                    var id = lt.Substring(pi + 8, lt.IndexOf("*/", pi, StringComparison.Ordinal) - pi - 8);
                    if (!cov.Probes.TryGetValue(id, out var l)) cov.Probes[id] = l = new List<string>();
                    l.Add($"{kind}:{status}:{sym?.ToDisplayString() ?? "-"}@{sym?.ContainingAssembly?.Name ?? "-"}");
                }
            }

            foreach (var node in root.DescendantNodes())
            {
                switch (node)
                {
                    case InvocationExpressionSyntax inv:
                    {
                        var si = model.GetSymbolInfo(inv);
                        var span = inv.Expression.Span;
                        string st = si.Symbol is not null && si.Symbol.ContainingType is not IErrorTypeSymbol && !Err(span) ? "resolved"
                            : (si.Symbol is null && si.CandidateReason == CandidateReason.Ambiguous && si.CandidateSymbols.Length >= 2) || Amb(span) ? "ambiguous"
                            : "unresolved";
                        cov.Inc("invocation", "total"); cov.Inc("invocation", st);
                        Record(inv, "invocation", st, si.Symbol);
                        break;
                    }
                    case AssignmentExpressionSyntax a when a.IsKind(SyntaxKind.AddAssignmentExpression):
                    {
                        var sym = model.GetSymbolInfo(a.Left).Symbol;
                        cov.Inc("event_assign", "total");
                        if (sym is IEventSymbol) { cov.Inc("event_assign", "event"); Record(a, "event_assign", "resolved", sym); }
                        else if (sym is not null) cov.Inc("event_assign", "non_event");
                        else
                        {
                            cov.Inc("event_assign", "unresolved");
                            if (!IsHandler(a.Right)) cov.Inc("event_assign", "unresolved_no_marker");
                            Record(a, "event_assign", "unresolved", null);
                        }
                        break;
                    }
                }
                TypeSyntax? ts = node switch
                {
                    VariableDeclarationSyntax v => v.Type,
                    ObjectCreationExpressionSyntax o => o.Type,
                    BaseTypeSyntax b => b.Type,
                    ParameterSyntax p => p.Type,
                    PropertyDeclarationSyntax pd => pd.Type,
                    MethodDeclarationSyntax md => md.ReturnType,
                    _ => null,
                };
                if (ts is not null && !(ts is IdentifierNameSyntax { IsVar: true }) && !(ts is PredefinedTypeSyntax))
                {
                    // a type node inside `new T()` has no TypeInfo of its own; its symbol carries the type
                    var tsi = model.GetSymbolInfo(ts);
                    var t = model.GetTypeInfo(ts).Type ?? tsi.Symbol as ITypeSymbol;
                    string st = !ContainsError(t) && !Err(ts.Span) ? "resolved"
                        : (t is IErrorTypeSymbol e && e.CandidateReason == CandidateReason.Ambiguous)
                          || (tsi.Symbol is null && tsi.CandidateReason == CandidateReason.Ambiguous && tsi.CandidateSymbols.Length >= 2) || Amb(ts.Span) ? "ambiguous" : "error";
                    cov.Inc("type", "total"); cov.Inc("type", st);
                    Record(ts, "type", st, t is null or IErrorTypeSymbol ? null : t);
                }
                // disposable-type sites as the extractor's IsOwnedDisposableType sees them (fields, parameters)
                TypeSyntax? dt = node switch { FieldDeclarationSyntax f => f.Declaration.Type, ParameterSyntax p => p.Type, _ => null };
                if (dt is not null)
                {
                    var t = model.GetTypeInfo(dt).Type ?? model.GetSymbolInfo(dt).Symbol as ITypeSymbol;
                    if (t is not null and not IErrorTypeSymbol) { if (ImplementsIDisposable(t)) { cov.Inc("disposable_type", "total"); cov.Inc("disposable_type", "resolved"); } }
                    else if (IsDisposableType(dt.ToString())) { cov.Inc("disposable_type", "total"); cov.Inc("disposable_type", "name_heuristic"); }
                }
            }
            // methods: "checked" only if every relevant site (event += , new of a disposable) is resolved
            foreach (var m in root.DescendantNodes().OfType<BaseMethodDeclarationSyntax>())
            {
                cov.MethodsTotal++;
                var relevant = m.DescendantNodes().Where(n => n is AssignmentExpressionSyntax aa && aa.IsKind(SyntaxKind.AddAssignmentExpression)
                    || n is ObjectCreationExpressionSyntax).ToList();
                var rel2 = relevant.Where(n => n is AssignmentExpressionSyntax
                    || (n is ObjectCreationExpressionSyntax oc && (model.GetTypeInfo(oc).Type is { } ot && !ContainsError(ot) ? ImplementsIDisposable(ot) : IsDisposableType(oc.Type.ToString())))).ToList();
                if (rel2.Count == 0) continue;
                cov.MethodsWithRelevant++;
                bool ok = rel2.All(n => n switch
                {
                    AssignmentExpressionSyntax aa => model.GetSymbolInfo(aa.Left).Symbol is not null,
                    ObjectCreationExpressionSyntax oc => model.GetTypeInfo(oc).Type is { } t && !ContainsError(t),
                    _ => false,
                });
                if (ok) cov.MethodsAllRelevantResolved++;
            }
        }
        cov.AllSites.Sort((x, y) => string.CompareOrdinal($"{x.File}|{x.Start:D9}|{x.Length:D9}|{x.Kind}", $"{y.File}|{y.Start:D9}|{y.Length:D9}|{y.Kind}"));
        return cov;
    }

    public static HashSet<string> Allowed(CSharpCompilation comp)
    {
        var set = new HashSet<string>(StringComparer.Ordinal) { comp.Assembly.Identity.ToString() };
        foreach (var r in comp.References)
            if (comp.GetAssemblyOrModuleSymbol(r) is IAssemblySymbol a) set.Add(a.Identity.ToString());
        return set;
    }

    // invariants of DESIGN §4, machine-checked
    public static List<string> Invariants(UnitCoverage c)
    {
        var bad = new List<string>();
        int G(string k, string f) => c.Sites.TryGetValue(k, out var d) ? d.GetValueOrDefault(f) : 0;
        if (G("invocation", "total") != G("invocation", "resolved") + G("invocation", "ambiguous") + G("invocation", "unresolved")) bad.Add("invocation-sum");
        if (G("type", "total") != G("type", "resolved") + G("type", "ambiguous") + G("type", "error")) bad.Add("type-sum");
        if (G("event_assign", "total") != G("event_assign", "event") + G("event_assign", "non_event") + G("event_assign", "unresolved")) bad.Add("event-sum");
        if (G("event_assign", "unresolved_no_marker") > G("event_assign", "unresolved")) bad.Add("no-marker-bound");
        if (G("disposable_type", "total") != G("disposable_type", "resolved") + G("disposable_type", "name_heuristic")) bad.Add("disposable-sum");
        return bad;
    }
}
