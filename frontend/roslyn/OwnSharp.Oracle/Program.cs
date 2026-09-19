// OwnSharp.Oracle — the P-037 A2.2-4 completeness oracle.
//
// EVIDENCE INFRASTRUCTURE, NOT PRODUCTION. The oracle reads the same C# inputs the extractor
// read and the facts.json the extractor wrote, and checks the frozen completeness sentence
// (docs/notes/p037-formal-kernel.md §10.6.1, corpus/p037-relevance/registry.json):
//
//   Completeness means every candidate occurrence at a call-related syntax site is either
//   represented by the raw guarded-call vocabulary or assigned exactly one named exclusion.
//   Occurrence alone does not establish ownership flow to the enclosing callee.
//
// What it is: a broad, symbol-bound inventory of candidate occurrences, an independent path
// classifier that walks each occurrence's syntax UPWARD (identifier -> wrapper -> ... -> the
// first call-related slot or a non-call context), and a two-sided join with the facts by
// stable call-site identity (site line/column + declared ordinal) on BOTH carriers,
// `functions[].guarded_facts` and `guarded_functions[].guarded_facts`. Every universe
// occurrence gets exactly one of: captured (a fact with the expected representation exists at
// its site and ordinal), excluded (exactly one frozen named exclusion), not call-related (a
// named non-call context), or RED (0 explanations, or a fact that contradicts the inventory).
// Every var/param fact must join an inventoried occurrence of the SAME symbol at its site and
// ordinal, so a fact bound by spelling to a different symbol is RED.
//
// What it is not: a second copy of the production classifier. Production classifies DOWNWARD
// over Roslyn's operation tree from the argument to its value; the oracle classifies UPWARD
// over syntax from the identifier, asks Roslyn for the semantic conversion at every edge with
// SemanticModel.GetConversion / IConversionOperation, and binds ordinals through Roslyn's own
// IArgumentOperation.Parameter rather than by position arithmetic. No source is shared.
//
// Universe (declared, symbol-bound; README.md): owned by-value parameters whose type
// implements System.IDisposable, locals initialized by an object creation of such a type, and
// locals initialized by a call to a first-party method returning such a type — the frozen
// "disposable candidate local or owned parameter" notion, on symbols. The legacy pass's own
// acquisition vocabulary (BCL factories, pool rentals) is not re-implemented; a `var` fact
// naming such a local is reported as outside_universe, counted and listed, never RED unless
// the member also declares a universe candidate of the same spelling. Every local and
// parameter reference is inventoried regardless, so the fact-side identity check is total.
//
// The oracle writes its own JSON report; it never writes OwnIR and nothing here leaks into
// facts.json. Exit 0 = no RED; 1 = RED; 2 = usage / unreadable input.

using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Operations;

return Oracle.Run(args);

static class Oracle
{
    const string Schema = "p037-completeness-oracle/1";

    // The eleven frozen named exclusions, exactly as corpus/p037-relevance/registry.json spells
    // them. The oracle can assign only these names; anything else is RED by construction.
    static readonly HashSet<string> Exclusions = new(StringComparer.Ordinal)
    {
        "nested_call_result", "container_construction", "tuple_construction", "closure_capture",
        "method_group_conversion", "receiver_not_summary_parameter", "storage_assignment",
        "user_conversion", "boxing_conversion", "nameof_operand", "member_access_on_handle",
    };

    // The closed vocabulary of NON-call contexts: an occurrence whose value path never reaches
    // a call-related slot. These are not exclusions (the sentence does not reach them); they are
    // named so the report can list them, and a context outside this table is RED, never a bin.
    static readonly HashSet<string> Contexts = new(StringComparer.Ordinal)
    {
        "local_declarator", "local_assignment", "handle_write", "return", "yield_return", "throw",
        "using_statement", "lock_statement", "foreach_source", "tested_operand", "switch_governing",
        "await_operand", "interpolation_hole", "ref_alias", "method_group_stored", "closure_stored",
        "nested_function_result", "expression_statement", "operator_operand", "query_clause",
        "local_function_declaration",
    };

    // The A1.1 optional-dispose exemption (Program.cs IsDisposeOptional): part of the frozen
    // handle DOMAIN (which parameters/locals are candidates), not of the classifier under test.
    static bool IsDisposeOptional(ITypeSymbol t)
    {
        var ns = t.ContainingNamespace?.ToString();
        return (ns == "System.Threading.Tasks" && t.Name is "Task" or "ValueTask")
            || (ns == "System.Data" && t.Name is "DataTable" or "DataSet" or "DataView")
            || (ns == "System.IO" && t.Name is "StringWriter" or "StringReader");
    }

    static bool ImplementsIDisposable(ITypeSymbol? t) =>
        t is not null
        && ((t.Name == "IDisposable" && t.ContainingNamespace?.ToString() == "System")
            || t.AllInterfaces.Any(i => i.Name == "IDisposable"
                                        && i.ContainingNamespace?.ToString() == "System"));

    static bool IsHandleType(ITypeSymbol? t) =>
        t is not null && t is not IErrorTypeSymbol && ImplementsIDisposable(t) && !IsDisposeOptional(t);

    enum Flow { Handle, MayValue, Member, Closure, MethodGroup }

    sealed record Pos(int Line, int Column);

    static Pos PosOf(SyntaxNode n)
    {
        var ls = n.GetLocation().GetLineSpan();
        return new Pos(ls.StartLinePosition.Line + 1, ls.StartLinePosition.Character + 1);
    }

    static Pos PosOf(SyntaxToken t)
    {
        var ls = t.GetLocation().GetLineSpan();
        return new Pos(ls.StartLinePosition.Line + 1, ls.StartLinePosition.Character + 1);
    }

    // ---- facts.json (read only; the oracle never writes OwnIR) ----

    sealed class ArgFact
    {
        public int Param;
        public string Kind = "";
        public string? Name;
        public int? SourceParam;
        public bool Negated;
    }

    sealed class CallFact
    {
        public Pos Site = new(0, 0);
        public string? Callee;
        public string? CallKind;
        public List<ArgFact> Args = new();
    }

    sealed class Record
    {
        public string Carrier = "";
        public string Name = "";
        public string File = "";
        public string? Sig;
        public List<CallFact> Calls = new();
        public List<Pos> GuardSites = new();
        public int Guards;
        public int Index;
        public MemberInfo? Bound;
    }

    static List<Record> LoadFacts(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        var root = doc.RootElement;
        var records = new List<Record>();
        foreach (var (carrier, key) in new[] { ("functions", "functions"), ("guarded_functions", "guarded_functions") })
        {
            if (!root.TryGetProperty(key, out var list) || list.ValueKind != JsonValueKind.Array)
                continue;
            var i = 0;
            foreach (var fn in list.EnumerateArray())
            {
                var rec = new Record
                {
                    Carrier = carrier,
                    Name = fn.GetProperty("name").GetString() ?? "",
                    File = (fn.GetProperty("file").GetString() ?? "").Replace('\\', '/'),
                    Sig = fn.TryGetProperty("sig", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null,
                    Index = i++,
                };
                if (fn.TryGetProperty("guarded_facts", out var gf) && gf.ValueKind == JsonValueKind.Object)
                {
                    if (gf.TryGetProperty("guards", out var guards) && guards.ValueKind == JsonValueKind.Array)
                    {
                        rec.Guards = guards.GetArrayLength();
                        foreach (var g in guards.EnumerateArray())
                        {
                            var gs = g.GetProperty("site");
                            rec.GuardSites.Add(new Pos(gs.GetProperty("line").GetInt32(), gs.GetProperty("column").GetInt32()));
                        }
                    }
                    if (gf.TryGetProperty("calls", out var calls) && calls.ValueKind == JsonValueKind.Array)
                        foreach (var c in calls.EnumerateArray())
                        {
                            var site = c.GetProperty("site");
                            var cf = new CallFact
                            {
                                Site = new Pos(site.GetProperty("line").GetInt32(), site.GetProperty("column").GetInt32()),
                                Callee = c.TryGetProperty("callee", out var ce) && ce.ValueKind == JsonValueKind.String ? ce.GetString() : null,
                                CallKind = c.TryGetProperty("call_kind", out var ck) && ck.ValueKind == JsonValueKind.String ? ck.GetString() : null,
                            };
                            foreach (var a in c.GetProperty("args").EnumerateArray())
                                cf.Args.Add(new ArgFact
                                {
                                    Param = a.GetProperty("param").GetInt32(),
                                    Kind = a.GetProperty("kind").GetString() ?? "",
                                    Name = a.TryGetProperty("name", out var nm) && nm.ValueKind == JsonValueKind.String ? nm.GetString() : null,
                                    SourceParam = a.TryGetProperty("source_param", out var sp) && sp.ValueKind == JsonValueKind.Number ? sp.GetInt32() : null,
                                    Negated = a.TryGetProperty("negated", out var ng) && ng.ValueKind == JsonValueKind.True,
                                });
                            rec.Calls.Add(cf);
                        }
                }
                else if (carrier == "guarded_functions")
                    rec.Guards = -1;    // malformed orphan: no sidecar at all (the producer validates this; recorded, not hidden)
                records.Add(rec);
            }
        }
        return records;
    }

    // ---- the inventory ----

    sealed class Occurrence
    {
        public ISymbol Symbol = null!;
        public string SymbolKind = "";      // local | parameter
        public string Name = "";
        public int? ParamOrdinal;
        public bool InUniverse;
        public string? UniverseRule;
        public Pos At = new(0, 0);
        public bool Nested;                 // inside a lambda / anonymous method / local function
        public string? InnerContext;        // the slot the occurrence reaches INSIDE the nested function
        public List<string> Path = new();
        public string Verdict = "";         // captured | excluded | not_call_related | red
        public string? Explanation;         // exclusion name | context name | red kind
        public string? Detail;
        public SyntaxNode? Site;
        public string? SiteKind;            // invocation | delegate_invocation | object_creation
        public int? Ordinal;
        public string? ExpectedKind;        // var | param | opaque
        public List<(SyntaxNode Site, string Explanation)> Enclosing = new();
    }

    sealed class MemberInfo
    {
        public string File = "";
        public IMethodSymbol Symbol = null!;
        public string Name = "";
        public string Kind = "";
        public string BodyForm = "";        // block | expression
        public SyntaxNode Body = null!;
        public SyntaxNode Scope = null!;    // the member declaration: the upper bound of every ancestor walk
        public List<SyntaxNode> Roots = new();   // the body, plus a constructor initializer when there is one
        public Pos At = new(0, 0);
        public SemanticModel Model = null!;
        public HashSet<ISymbol> Universe = new(SymbolEqualityComparer.Default);
        public Dictionary<ISymbol, string> UniverseRule = new(SymbolEqualityComparer.Default);
        public HashSet<string> CandidateNames = new(StringComparer.Ordinal);   // universe names + nested-function creations (the production name set)
        public HashSet<ISymbol> Written = new(SymbolEqualityComparer.Default);
        public bool DataFlowFallback;
        public List<Occurrence> Occurrences = new();
        public Dictionary<Pos, SyntaxNode> Sites = new();
        public HashSet<Pos> GuardSites = new();
        public List<Record> Records = new();
        public List<Dictionary<string, object?>> Red = new();
        public List<Dictionary<string, object?>> FactChecks = new();
        public int OutsideUniverseFacts;
    }

    static bool IsNestedFunction(SyntaxNode n) =>
        n is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax;

    static bool InsideNestedFunction(SyntaxNode n, SyntaxNode body)
    {
        for (var a = n.Parent; a is not null && a != body; a = a.Parent)
            if (IsNestedFunction(a))
                return true;
        return false;
    }

    static SyntaxNode? OutermostNestedFunction(SyntaxNode n, SyntaxNode body)
    {
        SyntaxNode? outer = null;
        for (var a = n.Parent; a is not null && a != body; a = a.Parent)
            if (IsNestedFunction(a))
                outer = a;
        return outer;
    }

    static string InitializerDescription(ILocalSymbol local)
    {
        var decl = local.DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax();
        if (decl is VariableDeclaratorSyntax vd)
        {
            var stmt = vd.Parent?.Parent;
            var head = stmt switch
            {
                LocalDeclarationStatementSyntax l when l.UsingKeyword != default => "using declaration",
                LocalDeclarationStatementSyntax => "local declaration",
                UsingStatementSyntax => "using statement",
                ForStatementSyntax => "for initializer",
                FixedStatementSyntax => "fixed statement",
                _ => stmt?.Kind().ToString() ?? "declarator",
            };
            var init = vd.Initializer?.Value;
            return init is null ? $"{head}, no initializer" : $"{head}, initializer {init.Kind()}: {Squash(init.ToString())}";
        }
        return decl?.Kind().ToString() ?? "unknown declaration";
    }

    static string Squash(string s)
    {
        var t = string.Join(" ", s.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return t.Length > 80 ? t[..77] + "..." : t;
    }

    // Universe rule for a local of this member, or null when the local is outside the universe.
    static string? LocalUniverseRule(ILocalSymbol local, SemanticModel model)
    {
        if (local.IsUsing)
            return null;
        if (local.DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax() is not VariableDeclaratorSyntax vd)
            return null;
        if (vd.Parent?.Parent is not LocalDeclarationStatementSyntax)
            return null;
        var init = vd.Initializer?.Value;
        switch (init)
        {
            case BaseObjectCreationExpressionSyntax oc:
                return IsHandleType(model.GetTypeInfo(oc).Type) ? "created_local" : null;
            case InvocationExpressionSyntax inv:
            {
                if (model.GetSymbolInfo(inv).Symbol is not IMethodSymbol m)
                    return null;
                if (m.DeclaringSyntaxReferences.Length > 0 && !m.ReturnsVoid && IsHandleType(m.ReturnType))
                    return "first_party_factory_local";
                // The two BCL acquisition idioms the census and the samples are written in: the
                // System.IO.File factories and a pool rental (a `byte[]` buffer the renter must
                // return, an IMemoryOwner the renter must dispose). The legacy pass's wider
                // factory vocabulary (crypto, Xml, Json, ADO.NET) is not re-implemented here; a
                // fact on such a local is reported as outside_universe, by initializer.
                var ns = m.ContainingType?.ContainingNamespace?.ToString();
                if (m.ContainingType is { Name: "File" } && ns == "System.IO"
                    && m.Name is "OpenRead" or "OpenWrite" or "Open" or "Create" or "OpenText" or "CreateText" or "AppendText")
                    return "bcl_file_factory_local";
                if (m.Name == "Rent" && ns == "System.Buffers"
                    && m.ContainingType is { Name: "ArrayPool" or "MemoryPool", Arity: 1 })
                    return "pool_rental_local";
                return null;
            }
            default:
                return null;
        }
    }

    static void BuildUniverse(MemberInfo m)
    {
        foreach (var p in m.Symbol.Parameters)
            if (p.RefKind == RefKind.None && IsHandleType(p.Type))
            {
                m.Universe.Add(p);
                m.UniverseRule[p] = "owned_parameter";
                m.CandidateNames.Add(p.Name);
            }
        foreach (var vd in m.Roots.SelectMany(r => r.DescendantNodes()).OfType<VariableDeclaratorSyntax>())
        {
            if (m.Model.GetDeclaredSymbol(vd) is not ILocalSymbol local)
                continue;
            var rule = LocalUniverseRule(local, m.Model);
            if (rule is null)
                continue;
            if (SymbolEqualityComparer.Default.Equals(local.ContainingSymbol, m.Symbol))
            {
                m.Universe.Add(local);
                m.UniverseRule[local] = rule;
            }
            // A creation inside a nested function is not this member's candidate, but its
            // NAME is in the production candidate set (the legacy collector does not stop at
            // lambdas), so it takes part in the same-spelling check.
            m.CandidateNames.Add(local.Name);
        }
    }

    static void BuildStability(MemberInfo m)
    {
        try
        {
            DataFlowAnalysis? flow = m.Body switch
            {
                BlockSyntax b => m.Model.AnalyzeDataFlow(b),
                ArrowExpressionClauseSyntax a => m.Model.AnalyzeDataFlow(a.Expression),
                ExpressionSyntax e => m.Model.AnalyzeDataFlow(e),
                _ => null,
            };
            if (flow is { Succeeded: true })
                foreach (var s in flow.WrittenInside)
                    m.Written.Add(s);
            else
                m.DataFlowFallback = true;
        }
        catch (Exception)
        {
            m.DataFlowFallback = true;
        }
        // A `ref` alias may write later; G-V4 counts it as exposure. Roslyn's region analysis
        // does not, so the one syntactic rule is added on both paths.
        foreach (var r in m.Body.DescendantNodes().OfType<RefExpressionSyntax>())
            if (m.Model.GetSymbolInfo(StripParens(r.Expression)).Symbol is IParameterSymbol p)
                m.Written.Add(p);
        if (!m.DataFlowFallback)
            return;
        foreach (var n in m.Body.DescendantNodes())
        {
            ISymbol? written = n switch
            {
                AssignmentExpressionSyntax a => m.Model.GetSymbolInfo(StripParens(a.Left)).Symbol,
                PrefixUnaryExpressionSyntax u when u.IsKind(SyntaxKind.PreIncrementExpression)
                                                  || u.IsKind(SyntaxKind.PreDecrementExpression)
                                                  || u.IsKind(SyntaxKind.AddressOfExpression)
                    => m.Model.GetSymbolInfo(StripParens(u.Operand)).Symbol,
                PostfixUnaryExpressionSyntax u when u.IsKind(SyntaxKind.PostIncrementExpression)
                                                   || u.IsKind(SyntaxKind.PostDecrementExpression)
                    => m.Model.GetSymbolInfo(StripParens(u.Operand)).Symbol,
                ArgumentSyntax a when a.RefKindKeyword.IsKind(SyntaxKind.RefKeyword)
                                      || a.RefKindKeyword.IsKind(SyntaxKind.OutKeyword)
                    => m.Model.GetSymbolInfo(StripParens(a.Expression)).Symbol,
                _ => null,
            };
            if (written is IParameterSymbol or ILocalSymbol)
                m.Written.Add(written);
        }
    }

    static ExpressionSyntax StripParens(ExpressionSyntax e)
    {
        while (e is ParenthesizedExpressionSyntax p)
            e = p.Expression;
        return e;
    }

    static bool Stable(MemberInfo m, IParameterSymbol p) => !m.Written.Contains(p);

    // ---- the path classifier: from the identifier UP to the first call-related slot ----

    sealed class Outcome
    {
        public string Verdict = "";
        public string? Explanation;
        public string? Detail;
        public SyntaxNode? Site;
        public string? SiteKind;
        public int? Ordinal;
        public string? ExpectedKind;

        public static Outcome Captured(SyntaxNode site, string kind, int ordinal, string expected) =>
            new() { Verdict = "captured", Site = site, SiteKind = kind, Ordinal = ordinal, ExpectedKind = expected };

        public static Outcome Excluded(string name, SyntaxNode? site = null, string? kind = null, int? ordinal = null)
        {
            if (!Exclusions.Contains(name))
                throw new InvalidOperationException($"oracle bug: '{name}' is not a frozen exclusion");
            return new Outcome { Verdict = "excluded", Explanation = name, Site = site, SiteKind = kind, Ordinal = ordinal };
        }

        public static Outcome Context(string name)
        {
            if (!Contexts.Contains(name))
                throw new InvalidOperationException($"oracle bug: '{name}' is not a named context");
            return new Outcome { Verdict = "not_call_related", Explanation = name };
        }

        public static Outcome Red(string kind, string detail) =>
            new() { Verdict = "red", Explanation = kind, Detail = detail };
    }

    // The registry's conversion-edge vocabulary, from Roslyn's semantic conversion.
    //   explicitSyntax = the conversion is spelled as a cast (the user-defined edge is then
    //   "explicit" by the registry's naming, whatever the operator's declared kind).
    static string EdgeOf(Conversion c, bool explicitSyntax)
    {
        if (!c.Exists)
            return "unresolved";
        if (c.IsUserDefined)
            return explicitSyntax ? "user_defined_explicit" : "user_defined_implicit";
        if (c.IsIdentity)
            return explicitSyntax ? "identity" : "none";
        if (c.IsReference)
            return c.IsImplicit ? "reference_upcast" : "reference_checked";
        if (c.IsBoxing)
            return "boxing";
        if (c.IsConditionalExpression || c.IsSwitchExpression)
            return "none";      // target-typed: the arms carry the edges, checked one by one
        if (c.IsAnonymousFunction || c.IsMethodGroup)
            return "delegate";
        return "other:" + c;
    }

    static bool UnderArgument(SyntaxNode n, SyntaxNode body)
    {
        for (var a = n.Parent; a is not null && a != body; a = a.Parent)
            if (a is ArgumentSyntax)
                return true;
        return false;
    }

    // A derived value (a test, an await, an interpolation, an operator) is not the handle: no
    // named exclusion covers it. Under an argument that is a hole in the frozen vocabulary and
    // therefore RED; elsewhere it is a named non-call context.
    static Outcome Derived(string name, SyntaxNode node, MemberInfo m) =>
        UnderArgument(node, m.Scope)
            ? Outcome.Red("unclassified_argument_shape:" + name, $"a {name} of the handle is under an argument; no frozen exclusion names it")
            : Outcome.Context(name);

    static string ExpectedKind(Flow flow, ISymbol symbol, bool refOrOut, bool isParams, MemberInfo m)
    {
        if (refOrOut || isParams || flow == Flow.MayValue)
            return "opaque";
        if (symbol is IParameterSymbol p)
            return Stable(m, p) ? "param" : "opaque";
        return "var";
    }

    static (int ordinal, bool isParams) BindOrdinal(ArgumentSyntax arg, int index, IEnumerable<IArgumentOperation>? ops)
    {
        // Roslyn attaches the argument operation to the innermost expression (`(r)`, `r!` bind
        // to `r`), so the match is by span containment; a params/default argument carries the
        // call's own syntax and matches nothing, and the source position is the fallback the
        // spec names for an unresolved callee.
        var op = ops?.FirstOrDefault(a => arg.Span.Contains(a.Syntax.Span));
        // An EXPANDED params argument is one element of the array Roslyn builds for the slot:
        // the ParamArray argument carries the call's own syntax, its elements carry the
        // arguments'. A collapsed params argument (an array passed whole) matched above.
        var isParams = false;
        if (op is null && ops is not null)
        {
            op = ops.FirstOrDefault(a => a.ArgumentKind == ArgumentKind.ParamArray
                                         && a.Value is IArrayCreationOperation { Initializer: { } init }
                                         && init.ElementValues.Any(e => arg.Span.Contains(e.Syntax.Span)));
            isParams = op is not null;
        }
        if (op?.Parameter is { } p)
        {
            var owner = p.ContainingSymbol as IMethodSymbol;
            var ordinal = p.Ordinal + (owner?.ReducedFrom is not null ? 1 : 0);
            return (ordinal, isParams || op.ArgumentKind == ArgumentKind.ParamArray);
        }
        return (index, false);
    }

    static Outcome AtArgument(ArgumentSyntax arg, Flow flow, List<string> path, ISymbol symbol, MemberInfo m)
    {
        var model = m.Model;
        if (arg.Parent is TupleExpressionSyntax)
            return Outcome.Excluded("tuple_construction");
        if (arg.Parent is BracketedArgumentListSyntax)
            return Outcome.Red("unclassified_argument_shape:indexer_argument", "the handle is an index of an element access");
        if (arg.Parent is not ArgumentListSyntax al)
            return Outcome.Red("unclassified_argument_shape:" + arg.Parent?.Kind(), "argument outside an argument list");
        var index = al.Arguments.IndexOf(arg);
        SyntaxNode site;
        string siteKind;
        IEnumerable<IArgumentOperation>? ops;
        switch (al.Parent)
        {
            case InvocationExpressionSyntax inv:
            {
                var sym = model.GetSymbolInfo(inv).Symbol as IMethodSymbol;
                if (inv.Expression is IdentifierNameSyntax { Identifier.Text: "nameof" } && sym is null)
                    return Outcome.Excluded("nameof_operand");   // not a call: attributed to the slot above, if any
                site = inv;
                siteKind = sym is { MethodKind: MethodKind.DelegateInvoke } ? "delegate_invocation" : "invocation";
                ops = (model.GetOperation(inv) as IInvocationOperation)?.Arguments;
                break;
            }
            case BaseObjectCreationExpressionSyntax oc:
                site = oc;
                siteKind = "object_creation";
                ops = (model.GetOperation(oc) as IObjectCreationOperation)?.Arguments;
                break;
            case ConstructorInitializerSyntax:
                return Outcome.Red("unclassified_argument_shape:constructor_initializer", "the handle is an argument of `: this(...)` / `: base(...)`, a call site outside the vocabulary");
            default:
                return Outcome.Red("unclassified_argument_shape:" + al.Parent?.Kind(), "argument list of an unmodelled parent");
        }
        var (ordinal, isParams) = BindOrdinal(arg, index, ops);
        switch (flow)
        {
            case Flow.Closure:
                return Outcome.Excluded("closure_capture", site, siteKind, ordinal);
            case Flow.MethodGroup:
                return Outcome.Excluded("method_group_conversion", site, siteKind, ordinal);
            case Flow.Member:
                return Outcome.Excluded("member_access_on_handle", site, siteKind, ordinal);
        }
        // The argument's own conversion to the parameter, implicit and therefore invisible in
        // the syntax: `TakeBox(r)` is op_Implicit(r), `SinkObject(token)` is a box.
        var edge = EdgeOf(model.GetConversion(arg.Expression), explicitSyntax: false);
        path.Add("argument:" + edge);
        switch (edge)
        {
            case "user_defined_implicit":
                return Outcome.Excluded("user_conversion", site, siteKind, ordinal);
            case "boxing":
                return Outcome.Excluded("boxing_conversion", site, siteKind, ordinal);
            case "none" or "reference_upcast" or "unresolved":
                break;
            case "identity" or "reference_checked" or "delegate":
                return Outcome.Red("unclassified_conversion:" + edge, "an implicit argument conversion of this kind was not expected");
            default:
                return Outcome.Red("unclassified_conversion:" + edge, "a conversion edge the frozen vocabulary does not name");
        }
        var refOrOut = arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword) || arg.RefKindKeyword.IsKind(SyntaxKind.OutKeyword);
        if (refOrOut)
            path.Add(arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword) ? "ref" : "out");
        if (isParams)
            path.Add("params");
        return Outcome.Captured(site, siteKind, ordinal, ExpectedKind(flow, symbol, refOrOut, isParams, m));
    }

    // An arm of a may-value form carries its own implicit conversion to the form's type.
    static Outcome? ArmEdge(ExpressionSyntax arm, List<string> path, MemberInfo m)
    {
        var edge = EdgeOf(m.Model.GetConversion(arm), explicitSyntax: false);
        path.Add("arm:" + edge);
        return edge switch
        {
            "user_defined_implicit" => Outcome.Excluded("user_conversion"),
            "boxing" => Outcome.Excluded("boxing_conversion"),
            "none" or "reference_upcast" or "unresolved" => null,
            _ => Outcome.Red("unclassified_conversion:" + edge, "an arm conversion the frozen vocabulary does not name"),
        };
    }

    static Outcome Receiver(InvocationExpressionSyntax inv, SyntaxNode receiver, Flow flow, List<string> path, ISymbol symbol, MemberInfo m)
    {
        var sym = m.Model.GetSymbolInfo(inv).Symbol as IMethodSymbol;
        switch (flow)
        {
            case Flow.Member:
                return Outcome.Excluded("member_access_on_handle", inv, "invocation", 0);
            case Flow.Closure or Flow.MethodGroup:
                return Outcome.Red("unclassified_context:receiver_of_" + flow, "a closure or method group used as a call receiver");
        }
        if (sym?.ReducedFrom is null)
            return Outcome.Excluded("receiver_not_summary_parameter", inv, "invocation", 0);
        // A reduced extension receiver binds ordinal 0 through its own implicit conversion:
        // identity or a reference conversion keeps the handle, a boxing conversion does not.
        var edge = receiver is ExpressionSyntax re ? EdgeOf(m.Model.GetConversion(re), explicitSyntax: false) : "unresolved";
        path.Add("receiver:" + edge);
        return edge switch
        {
            "boxing" => Outcome.Excluded("boxing_conversion", inv, "invocation", 0),
            "none" or "reference_upcast" or "unresolved" => Outcome.Captured(inv, "invocation", 0, ExpectedKind(flow, symbol, false, false, m)),
            _ => Outcome.Red("unclassified_conversion:receiver:" + edge, "a receiver conversion the frozen vocabulary does not name"),
        };
    }

    static Outcome Walk(SyntaxNode start, Flow flow, List<string> path, ISymbol symbol, MemberInfo m, SyntaxNode stopAt)
    {
        var model = m.Model;
        var node = start;
        while (true)
        {
            var parent = node.Parent;
            if (parent is null)
                return Outcome.Context("expression_statement");
            if (node is LocalFunctionStatementSyntax)
                // The capture lives in a declared local function; its calls are that function's
                // (the known gap: nested function bodies have no record of their own).
                return Outcome.Context("local_function_declaration");
            if (parent == stopAt)
                return node is ArrowExpressionClauseSyntax ? Outcome.Context("return")
                    : stopAt == m.Scope ? Outcome.Context("expression_statement")
                    : Outcome.Context("nested_function_result");
            switch (parent)
            {
                case ParenthesizedExpressionSyntax:
                    path.Add("parenthesized");
                    node = parent;
                    continue;
                case PostfixUnaryExpressionSyntax pu when pu.IsKind(SyntaxKind.SuppressNullableWarningExpression):
                    path.Add("null_forgiving");
                    node = parent;
                    continue;
                case PrefixUnaryExpressionSyntax not when not.IsKind(SyntaxKind.LogicalNotExpression)
                                                          && flow == Flow.Handle && node == start
                                                          && symbol is IParameterSymbol { Type.SpecialType: SpecialType.System_Boolean }:
                    // `!p` on a by-value boolean parameter is representable: param{..., negated}.
                    path.Add("negated");
                    node = parent;
                    continue;
                case CheckedExpressionSyntax:
                    path.Add("checked");
                    node = parent;
                    continue;
                case CastExpressionSyntax cast when cast.Expression == node:
                {
                    if (flow is Flow.Closure or Flow.MethodGroup)
                    {
                        path.Add("cast:delegate");
                        node = parent;
                        continue;
                    }
                    var conv = model.GetOperation(cast) as IConversionOperation;
                    var edge = conv is null ? "unresolved" : EdgeOf(conv.GetConversion(), explicitSyntax: true);
                    path.Add("cast:" + edge);
                    switch (edge)
                    {
                        case "user_defined_explicit":
                            return Outcome.Excluded("user_conversion");
                        case "boxing":
                            return Outcome.Excluded("boxing_conversion");
                        case "identity" or "reference_upcast" or "reference_checked" or "unresolved":
                            node = parent;
                            continue;
                        default:
                            return Outcome.Red("unclassified_conversion:" + edge, $"cast `{Squash(cast.ToString())}`");
                    }
                }
                case BinaryExpressionSyntax asx when asx.IsKind(SyntaxKind.AsExpression) && asx.Left == node:
                {
                    var conv = model.GetOperation(asx) as IConversionOperation;
                    var c = conv?.GetConversion() ?? default;
                    if (!c.Exists)
                    {
                        path.Add("as:unresolved");
                        node = parent;
                        continue;
                    }
                    if (c.IsIdentity || (c.IsReference && c.IsImplicit))
                    {
                        path.Add("as:" + (c.IsIdentity ? "identity" : "reference_upcast"));
                        node = parent;
                        continue;
                    }
                    if (c.IsReference)
                    {
                        path.Add("as_may_fail:may_fail_null");
                        if (flow == Flow.Handle)
                            flow = Flow.MayValue;
                        node = parent;
                        continue;
                    }
                    if (c.IsBoxing)
                    {
                        path.Add("as:boxing");
                        return Outcome.Excluded("boxing_conversion");
                    }
                    return Outcome.Red("unclassified_conversion:as:" + c, $"`{Squash(asx.ToString())}`");
                }
                case ConditionalExpressionSyntax ce when ce.WhenTrue == node || ce.WhenFalse == node:
                {
                    if (flow is Flow.Handle or Flow.MayValue && ArmEdge((ExpressionSyntax)node, path, m) is { } bad)
                        return bad;
                    path.Add("conditional");
                    if (flow == Flow.Handle)
                        flow = Flow.MayValue;
                    node = parent;
                    continue;
                }
                case ConditionalExpressionSyntax:
                    return Derived("tested_operand", node, m);
                case BinaryExpressionSyntax co when co.IsKind(SyntaxKind.CoalesceExpression) && (co.Left == node || co.Right == node):
                {
                    if (flow is Flow.Handle or Flow.MayValue && ArmEdge((ExpressionSyntax)node, path, m) is { } bad)
                        return bad;
                    path.Add("null_coalescing");
                    if (flow == Flow.Handle)
                        flow = Flow.MayValue;
                    node = parent;
                    continue;
                }
                case SwitchExpressionArmSyntax arm when arm.Expression == node:
                {
                    if (flow is Flow.Handle or Flow.MayValue && ArmEdge((ExpressionSyntax)node, path, m) is { } bad)
                        return bad;
                    path.Add("switch_expression");
                    if (flow == Flow.Handle)
                        flow = Flow.MayValue;
                    node = arm.Parent!;
                    continue;
                }
                case SwitchExpressionArmSyntax:
                    return Derived("tested_operand", node, m);
                case SwitchExpressionSyntax sw when sw.GoverningExpression == node:
                    return Derived("switch_governing", node, m);
                case MemberAccessExpressionSyntax ma when ma.Expression == node:
                {
                    if (ma.Parent is InvocationExpressionSyntax inv && inv.Expression == ma)
                        return Receiver(inv, node, flow, path, symbol, m);
                    if (flow is Flow.Closure or Flow.MethodGroup)
                        return Outcome.Red("unclassified_context:member_of_" + flow, "a member access on a closure or method group");
                    if (model.GetSymbolInfo(ma).Symbol is IMethodSymbol)
                    {
                        path.Add("method_group");
                        flow = Flow.MethodGroup;
                        node = parent;
                        continue;
                    }
                    path.Add("member_access");
                    flow = Flow.Member;
                    node = parent;
                    continue;
                }
                case ConditionalAccessExpressionSyntax ca when ca.Expression == node:
                {
                    if (flow is Flow.Closure or Flow.MethodGroup)
                        return Outcome.Red("unclassified_context:conditional_access_of_" + flow, "a conditional access on a closure or method group");
                    if (ca.WhenNotNull is InvocationExpressionSyntax cinv && cinv.Expression is MemberBindingExpressionSyntax)
                        return Receiver(cinv, node, flow, path, symbol, m);
                    path.Add("conditional_access");
                    flow = Flow.Member;
                    node = parent;
                    continue;
                }
                case ElementAccessExpressionSyntax ea when ea.Expression == node:
                    if (flow is Flow.Closure or Flow.MethodGroup)
                        return Outcome.Red("unclassified_context:element_of_" + flow, "an element access on a closure or method group");
                    path.Add("element_access");
                    flow = Flow.Member;
                    node = parent;
                    continue;
                case ArgumentSyntax arg when arg.Expression == node:
                    return AtArgument(arg, flow, path, symbol, m);
                case ExpressionElementSyntax:
                    return Outcome.Excluded("container_construction");
                case InitializerExpressionSyntax init:
                    if (init.IsKind(SyntaxKind.ObjectInitializerExpression) || init.IsKind(SyntaxKind.WithInitializerExpression))
                        return Outcome.Red("unclassified_context:object_initializer_element", "a bare element in an object initializer");
                    return Outcome.Excluded("container_construction");
                case AssignmentExpressionSyntax asg:
                {
                    if (asg.Left == node)
                        return Outcome.Context("handle_write");
                    var target = StripParens(asg.Left);
                    var tsym = model.GetSymbolInfo(target).Symbol;
                    var storage = target is ElementAccessExpressionSyntax or ImplicitElementAccessSyntax
                                  || tsym is IFieldSymbol or IPropertySymbol or IEventSymbol;
                    if (storage)
                    {
                        if (flow == Flow.Closure)
                            return Outcome.Context("closure_stored");
                        if (flow == Flow.MethodGroup)
                            return Outcome.Context("method_group_stored");
                        if (flow == Flow.Member)
                            return Outcome.Excluded("member_access_on_handle");
                        return Outcome.Excluded("storage_assignment");
                    }
                    if (tsym is ILocalSymbol or IParameterSymbol)
                        return flow switch
                        {
                            Flow.Closure => Outcome.Context("closure_stored"),
                            Flow.MethodGroup => Outcome.Context("method_group_stored"),
                            _ => Outcome.Context("local_assignment"),
                        };
                    return Outcome.Red("unclassified_context:assignment_to_" + target.Kind(), $"`{Squash(asg.ToString())}`");
                }
                case EqualsValueClauseSyntax:
                    return flow switch
                    {
                        Flow.Closure => Outcome.Context("closure_stored"),
                        Flow.MethodGroup => Outcome.Context("method_group_stored"),
                        _ => Outcome.Context("local_declarator"),
                    };
                case ReturnStatementSyntax or ArrowExpressionClauseSyntax:
                    return Outcome.Context("return");
                case YieldStatementSyntax:
                    return Outcome.Context("yield_return");
                case ThrowStatementSyntax or ThrowExpressionSyntax:
                    return Outcome.Context("throw");
                case UsingStatementSyntax:
                    return Outcome.Context("using_statement");
                case LockStatementSyntax:
                    return Outcome.Context("lock_statement");
                case ForEachStatementSyntax:
                    return Outcome.Context("foreach_source");
                case AwaitExpressionSyntax:
                    return Derived("await_operand", node, m);
                case IsPatternExpressionSyntax:
                    return Derived("tested_operand", node, m);
                case BinaryExpressionSyntax b when b.IsKind(SyntaxKind.EqualsExpression) || b.IsKind(SyntaxKind.NotEqualsExpression):
                    return Derived("tested_operand", node, m);
                case BinaryExpressionSyntax:
                    return Derived("operator_operand", node, m);
                case PrefixUnaryExpressionSyntax:
                    return Derived("operator_operand", node, m);
                case InterpolationSyntax:
                    return Derived("interpolation_hole", node, m);
                case QueryClauseSyntax or SelectOrGroupClauseSyntax or QueryExpressionSyntax or QueryBodySyntax
                     or OrderingSyntax or JoinIntoClauseSyntax or QueryContinuationSyntax:
                    return Derived("query_clause", node, m);
                case RefExpressionSyntax:
                    return Outcome.Context("ref_alias");
                case ExpressionStatementSyntax:
                    return Outcome.Context("expression_statement");
                case IfStatementSyntax or WhileStatementSyntax or DoStatementSyntax or ForStatementSyntax:
                    return Derived("tested_operand", node, m);
                case SwitchStatementSyntax:
                    return Derived("switch_governing", node, m);
                case AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax:
                    // The handle is a nested function's body expression (`() => r`): a value the
                    // closure returns. Only reachable in the bounded inner walk.
                    return Outcome.Context("nested_function_result");
                default:
                    return Outcome.Red("unclassified_context:" + parent.Kind(),
                                       $"`{Squash(parent.ToString())}` — a syntax the oracle has no rule for");
            }
        }
    }

    // The nearest call-related slot above a node: an argument of an invocation / object
    // creation, or the receiver of a call. Used only to attribute an already-decided exclusion
    // to the site it sits under; it decides nothing.
    static (SyntaxNode Site, string Kind, int Ordinal)? EnclosingSlot(SyntaxNode from, MemberInfo m)
    {
        var n = from;
        while (n is not null && n != m.Scope && n.Parent is not null && !IsNestedFunction(n.Parent))
        {
            if (n.Parent is ArgumentSyntax arg && arg.Expression == n && arg.Parent is ArgumentListSyntax al)
            {
                var index = al.Arguments.IndexOf(arg);
                switch (al.Parent)
                {
                    case InvocationExpressionSyntax inv:
                    {
                        var sym = m.Model.GetSymbolInfo(inv).Symbol as IMethodSymbol;
                        if (inv.Expression is IdentifierNameSyntax { Identifier.Text: "nameof" } && sym is null)
                        {
                            n = inv;    // `nameof(...)` is not a call: keep looking above it
                            continue;
                        }
                        var kind = sym is { MethodKind: MethodKind.DelegateInvoke } ? "delegate_invocation" : "invocation";
                        return (inv, kind, BindOrdinal(arg, index, (m.Model.GetOperation(inv) as IInvocationOperation)?.Arguments).ordinal);
                    }
                    case BaseObjectCreationExpressionSyntax oc:
                        return (oc, "object_creation", BindOrdinal(arg, index, (m.Model.GetOperation(oc) as IObjectCreationOperation)?.Arguments).ordinal);
                    default:
                        return null;
                }
            }
            if (n.Parent is MemberAccessExpressionSyntax ma && ma.Expression == n
                && ma.Parent is InvocationExpressionSyntax rinv && rinv.Expression == ma)
                return (rinv, "invocation", 0);
            n = n.Parent;
        }
        return null;
    }

    static void Inventory(MemberInfo m)
    {
        var model = m.Model;
        foreach (var id in m.Roots.SelectMany(r => r.DescendantNodes()).OfType<IdentifierNameSyntax>())
        {
            var sym = model.GetSymbolInfo(id).Symbol;
            if (sym is not (ILocalSymbol or IParameterSymbol))
                continue;
            if (!SymbolEqualityComparer.Default.Equals(sym.ContainingSymbol, m.Symbol))
                continue;   // a nested function's own local / parameter, or another member's
            if (id.Parent is NameColonSyntax or NameEqualsSyntax)
                continue;   // a parameter NAME in `f(x: ...)` is not a reference to a local
            var occ = new Occurrence
            {
                Symbol = sym,
                SymbolKind = sym is ILocalSymbol ? "local" : "parameter",
                Name = sym.Name,
                ParamOrdinal = (sym as IParameterSymbol)?.Ordinal,
                InUniverse = m.Universe.Contains(sym),
                UniverseRule = m.UniverseRule.TryGetValue(sym, out var rule) ? rule : null,
                At = PosOf(id),
                Nested = InsideNestedFunction(id, m.Scope),
            };
            Outcome outcome;
            if (occ.Nested)
            {
                var fn = OutermostNestedFunction(id, m.Scope)!;
                var inner = Walk(id, Flow.Handle, new List<string>(), sym, m, fn);
                occ.InnerContext = inner.Verdict == "captured"
                    ? $"call_slot:{inner.SiteKind}@{PosOf(inner.Site!).Line}:{PosOf(inner.Site!).Column}"
                    : $"{inner.Verdict}:{inner.Explanation}";
                occ.Path.Add("closure");
                outcome = Walk(fn, Flow.Closure, occ.Path, sym, m, m.Scope);
            }
            else
                outcome = Walk(id, Flow.Handle, occ.Path, sym, m, m.Scope);
            occ.Verdict = outcome.Verdict;
            occ.Explanation = outcome.Explanation;
            occ.Detail = outcome.Detail;
            occ.Site = outcome.Site;
            occ.SiteKind = outcome.SiteKind;
            occ.Ordinal = outcome.Ordinal;
            occ.ExpectedKind = outcome.ExpectedKind;
            // An exclusion decided inside an expression (a cast, an initializer, a tuple) still
            // sits under some call slot; name it, so the fact side can say "captured an
            // occurrence excluded by X" rather than merely "no occurrence".
            if (occ.Verdict == "excluded" && occ.Site is null
                && EnclosingSlot(occ.Nested ? OutermostNestedFunction(id, m.Scope)! : id, m) is { } slot)
            {
                occ.Site = slot.Site;
                occ.SiteKind = slot.Kind;
                occ.Ordinal = slot.Ordinal;
            }
            // Every call whose ARGUMENT contains the explained site receives that site's result,
            // never the handle: nested_call_result at each of them, recorded so the report shows
            // inner-captured / outer-excluded side by side. `nameof` is not a call and yields no
            // value, so nothing encloses a nameof_operand.
            if (occ.Site is not null && occ.Explanation != "nameof_operand")
                for (var a = occ.Site; a is not null && a != m.Scope && !IsNestedFunction(a); a = a.Parent)
                    if (a.Parent is ArgumentSyntax { Parent: ArgumentListSyntax { Parent: { } call } } && call is InvocationExpressionSyntax or BaseObjectCreationExpressionSyntax)
                        occ.Enclosing.Add((call, "nested_call_result"));
            m.Occurrences.Add(occ);
        }
        m.Occurrences.Sort((x, y) => x.At.Line != y.At.Line ? x.At.Line.CompareTo(y.At.Line) : x.At.Column.CompareTo(y.At.Column));
        foreach (var n in m.Roots.SelectMany(r => r.DescendantNodes()))
            if (n is InvocationExpressionSyntax or BaseObjectCreationExpressionSyntax)
                m.Sites[PosOf(n)] = n;
            else if (n is IfStatementSyntax)
                m.GuardSites.Add(PosOf(n));
    }

    // ---- the two-sided join ----

    static Dictionary<string, object?> RedItem(MemberInfo m, string kind, string detail, Pos? at = null,
                                               string? symbol = null, Pos? site = null, int? ordinal = null)
    {
        var d = new Dictionary<string, object?>
        {
            ["kind"] = kind,
            ["member"] = m.Name,
            ["file"] = m.File,
        };
        if (at is not null)
            d["at"] = $"{at.Line}:{at.Column}";
        if (symbol is not null)
            d["symbol"] = symbol;
        if (site is not null)
            d["site"] = $"{site.Line}:{site.Column}";
        if (ordinal is not null)
            d["ordinal"] = ordinal;
        d["detail"] = detail;
        return d;
    }

    static void Join(MemberInfo m, List<Dictionary<string, object?>> red)
    {
        void Red(string kind, string detail, Pos? at = null, string? symbol = null, Pos? site = null, int? ordinal = null)
        {
            var item = RedItem(m, kind, detail, at, symbol, site, ordinal);
            m.Red.Add(item);
            red.Add(item);
        }

        var record = m.Records.Count == 1 ? m.Records[0] : null;
        if (m.Records.Count > 1)
            Red("member_in_both_carriers", string.Join(" + ", m.Records.Select(r => r.Carrier)));
        var factIndex = new Dictionary<(Pos, int), (CallFact call, ArgFact arg)>();
        var callIndex = new Dictionary<Pos, CallFact>();
        if (record is not null)
            foreach (var c in record.Calls)
            {
                callIndex[c.Site] = c;
                foreach (var a in c.Args)
                    factIndex[(c.Site, a.Param)] = (c, a);
            }

        // Occurrence side: every universe occurrence at a call-related slot must be captured
        // with its expected representation.
        foreach (var occ in m.Occurrences)
        {
            if (!occ.InUniverse)
                continue;
            switch (occ.Verdict)
            {
                case "red":
                    Red(occ.Explanation!, occ.Detail ?? "", occ.At, occ.Name);
                    break;
                case "captured":
                {
                    var site = PosOf(occ.Site!);
                    var expectedKind = occ.SiteKind == "invocation" ? null : occ.SiteKind;
                    if (!callIndex.TryGetValue(site, out var call))
                    {
                        Red("occurrence_not_captured",
                            record is null
                                ? "no record in either carrier for this member"
                                : $"the member's record has no call fact at this site (expected {occ.ExpectedKind} at ordinal {occ.Ordinal})",
                            occ.At, occ.Name, site, occ.Ordinal);
                        break;
                    }
                    if (call.CallKind != expectedKind)
                        Red("call_kind_mismatch", $"fact call_kind {call.CallKind ?? "absent"}, site is {occ.SiteKind}",
                            occ.At, occ.Name, site, occ.Ordinal);
                    if (!factIndex.TryGetValue((site, occ.Ordinal!.Value), out var slot))
                    {
                        Red("occurrence_not_captured", $"the call fact has no slot at ordinal {occ.Ordinal} (slots: {string.Join(",", call.Args.Select(a => a.Param))})",
                            occ.At, occ.Name, site, occ.Ordinal);
                        break;
                    }
                    var ok = occ.ExpectedKind switch
                    {
                        "var" => slot.arg.Kind == "var" && slot.arg.Name == occ.Name,
                        "param" => slot.arg.Kind == "param" && slot.arg.SourceParam == occ.ParamOrdinal,
                        "opaque" => slot.arg.Kind == "opaque",
                        _ => false,
                    };
                    if (!ok)
                        Red("representation_mismatch",
                            $"expected {occ.ExpectedKind}{(occ.ExpectedKind == "var" ? "{" + occ.Name + "}" : occ.ExpectedKind == "param" ? "{" + occ.ParamOrdinal + "}" : "")}, "
                            + $"fact has {slot.arg.Kind}{(slot.arg.Name is not null ? "{" + slot.arg.Name + "}" : slot.arg.SourceParam is not null ? "{" + slot.arg.SourceParam + "}" : "")}; path {string.Join(" > ", occ.Path)}",
                            occ.At, occ.Name, site, occ.Ordinal);
                    break;
                }
            }
        }

        // Fact side: every var/param fact must join an inventoried occurrence of the SAME symbol
        // at its site and ordinal; every call fact must sit on a site the member owns and be
        // made relevant by some handle-shaped occurrence.
        if (record is null)
            return;
        foreach (var call in record.Calls)
        {
            var check = new Dictionary<string, object?>
            {
                ["site"] = $"{call.Site.Line}:{call.Site.Column}",
                ["callee"] = call.Callee,
                ["call_kind"] = call.CallKind,
            };
            m.FactChecks.Add(check);
            if (!m.Sites.TryGetValue(call.Site, out var siteNode))
            {
                Red("fact_site_not_found", "no invocation or object creation starts at this site in the member's body", site: call.Site);
                check["verdict"] = "red";
                continue;
            }
            if (InsideNestedFunction(siteNode, m.Scope))
                Red("fact_in_nested_function", "the site belongs to a lambda or local function body, not to this member", site: call.Site);
            var siteKind = siteNode is BaseObjectCreationExpressionSyntax ? "object_creation"
                : m.Model.GetSymbolInfo(siteNode).Symbol is IMethodSymbol { MethodKind: MethodKind.DelegateInvoke } ? "delegate_invocation"
                : "invocation";
            if ((call.CallKind ?? "invocation") != siteKind)
                Red("call_kind_mismatch", $"fact call_kind {call.CallKind ?? "absent"}, site is {siteKind}", site: call.Site);
            var relevant = false;
            var slots = new List<string>();
            foreach (var arg in call.Args)
            {
                var at = m.Occurrences.Where(o => !o.Nested && o.Site is not null && PosOf(o.Site) == call.Site && o.Ordinal == arg.Param).ToList();
                var represented = at.Where(o => o.Verdict == "captured").ToList();
                string verdict;
                switch (arg.Kind)
                {
                    case "var":
                    {
                        var match = represented.FirstOrDefault(o => o.SymbolKind == "local" && o.Name == arg.Name && o.ExpectedKind == "var");
                        if (match is not null)
                        {
                            relevant = true;
                            if (match.InUniverse)
                                verdict = "matched";
                            else if (m.CandidateNames.Contains(arg.Name!))
                            {
                                verdict = "red";
                                Red("fact_binds_other_symbol",
                                    $"the fact names `{arg.Name}` by spelling, but the symbol at this slot is a different local ({InitializerDescription((ILocalSymbol)match.Symbol)}) while a candidate of the same spelling exists in the member",
                                    match.At, arg.Name, call.Site, arg.Param);
                            }
                            else
                            {
                                verdict = "outside_universe";
                                m.OutsideUniverseFacts++;
                                check["outside_universe_" + arg.Param] = InitializerDescription((ILocalSymbol)match.Symbol);
                            }
                        }
                        else if (represented.FirstOrDefault(o => o.SymbolKind == "local" && o.Name == arg.Name) is { } other)
                        {
                            verdict = "red";
                            Red("representation_mismatch", $"fact has var{{{arg.Name}}}, the oracle expects {other.ExpectedKind} (path {string.Join(" > ", other.Path)})",
                                other.At, arg.Name, call.Site, arg.Param);
                        }
                        else if (at.FirstOrDefault(o => o.Verdict == "excluded" && o.Name == arg.Name) is { } excluded)
                        {
                            verdict = "red";
                            Red("fact_captures_excluded_occurrence:" + excluded.Explanation,
                                $"fact has var{{{arg.Name}}} at a slot the oracle excludes by {excluded.Explanation} (path {string.Join(" > ", excluded.Path)})",
                                excluded.At, arg.Name, call.Site, arg.Param);
                        }
                        else
                        {
                            verdict = "red";
                            Red("fact_without_occurrence", $"fact has var{{{arg.Name}}}, no local of that name is referenced at this slot", site: call.Site, ordinal: arg.Param);
                        }
                        break;
                    }
                    case "param":
                    {
                        var match = represented.FirstOrDefault(o => o.SymbolKind == "parameter" && o.ParamOrdinal == arg.SourceParam
                                                                    && o.ExpectedKind == "param" && o.Path.Contains("negated") == arg.Negated);
                        if (match is not null)
                        {
                            relevant |= match.InUniverse;
                            verdict = "matched";
                        }
                        else if (represented.FirstOrDefault(o => o.SymbolKind == "parameter" && o.ParamOrdinal == arg.SourceParam) is { } other)
                        {
                            verdict = "red";
                            Red("representation_mismatch", $"fact has param{{{arg.SourceParam}}}, the oracle expects {other.ExpectedKind} (path {string.Join(" > ", other.Path)})",
                                other.At, other.Name, call.Site, arg.Param);
                        }
                        else if (at.FirstOrDefault(o => o.Verdict == "excluded" && o.ParamOrdinal == arg.SourceParam) is { } excluded)
                        {
                            verdict = "red";
                            Red("fact_captures_excluded_occurrence:" + excluded.Explanation,
                                $"fact has param{{{arg.SourceParam}}} at a slot the oracle excludes by {excluded.Explanation}",
                                excluded.At, excluded.Name, call.Site, arg.Param);
                        }
                        else
                        {
                            verdict = "red";
                            Red("param_fact_misbound", $"fact has param{{{arg.SourceParam}}}, no reference to that parameter is at this slot", site: call.Site, ordinal: arg.Param);
                        }
                        break;
                    }
                    case "opaque":
                    {
                        if (represented.Any(o => o.ExpectedKind == "opaque" && o.InUniverse))
                        {
                            relevant = true;
                            verdict = "matched";
                        }
                        else if (represented.FirstOrDefault(o => o.ExpectedKind == "opaque" && o.SymbolKind == "local") is { } outsideLocal)
                        {
                            // A may-value / ref / params slot over a local outside the universe: if
                            // production tracks it (a factory the oracle does not name), this is the
                            // call's cause; the same-spelling rule applies exactly as to a `var`.
                            if (m.CandidateNames.Contains(outsideLocal.Name))
                            {
                                verdict = "red";
                                Red("fact_binds_other_symbol",
                                    $"an opaque slot over local `{outsideLocal.Name}` ({InitializerDescription((ILocalSymbol)outsideLocal.Symbol)}) while a candidate of the same spelling exists in the member",
                                    outsideLocal.At, outsideLocal.Name, call.Site, arg.Param);
                            }
                            else
                            {
                                verdict = "outside_universe";
                                m.OutsideUniverseFacts++;
                                check["outside_universe_" + arg.Param] = InitializerDescription((ILocalSymbol)outsideLocal.Symbol);
                            }
                        }
                        else if (represented.Any(o => !o.InUniverse))
                            verdict = "opaque_over_non_universe";     // a non-candidate reference: production owes it nothing
                        else
                            verdict = "opaque";                       // no handle-shaped occurrence: an ordinary opaque argument
                        break;
                    }
                    default:
                        verdict = arg.Kind;
                        break;
                }
                slots.Add($"{arg.Param}:{arg.Kind}={verdict}");
            }
            // A `var` naming a universe or outside-universe local, or a universe parameter under
            // any representation, is what makes the call relevant in the frozen sense; a call
            // fact made relevant by nothing the oracle can see is a fact without a cause.
            var outside = slots.Any(s => s.EndsWith("=outside_universe", StringComparison.Ordinal));
            if (!relevant && !outside)
                Red("fact_without_relevant_occurrence", $"no handle-shaped occurrence makes this call relevant (slots {string.Join(" ", slots)})", site: call.Site);
            check["slots"] = slots;
            check["verdict"] = m.Red.Any(r => (string?)r.GetValueOrDefault("site") == $"{call.Site.Line}:{call.Site.Column}") ? "red" : "ok";
        }
    }

    // ---- driver ----

    static IEnumerable<string> Expand(IEnumerable<string> roots)
    {
        foreach (var r in roots)
        {
            if (Directory.Exists(r))
            {
                foreach (var f in Directory.EnumerateFiles(r, "*.cs", SearchOption.AllDirectories).OrderBy(p => p, StringComparer.Ordinal))
                    if (!IsSkipped(f))
                        yield return f;
            }
            else if (File.Exists(r))
                yield return r;
            else
                Console.Error.WriteLine($"oracle: skipping (not found): {r}");
        }
    }

    static bool IsSkipped(string path)
    {
        foreach (var seg in path.Split('/', '\\'))
            if (seg is "bin" or "obj" or ".git" or ".vs" or "node_modules" or "packages")
                return true;
        return path.EndsWith(".g.cs", StringComparison.Ordinal)
               || path.EndsWith(".Designer.cs", StringComparison.Ordinal)
               || path.EndsWith(".AssemblyInfo.cs", StringComparison.Ordinal);
    }

    static string Rel(string path) =>
        Path.GetRelativePath(Directory.GetCurrentDirectory(), path).Replace('\\', '/');

    static string MemberName(IMethodSymbol s) => $"{s.ContainingType.ToDisplayString()}.{s.Name}";

    static IEnumerable<MemberInfo> Members(string file, SyntaxTree tree, SemanticModel model)
    {
        var root = tree.GetRoot();
        foreach (var type in root.DescendantNodes().OfType<TypeDeclarationSyntax>())
            foreach (var member in type.Members)
            {
                switch (member)
                {
                    case BaseMethodDeclarationSyntax bm:
                    {
                        SyntaxNode? body = bm.Body ?? (SyntaxNode?)bm.ExpressionBody;
                        if (body is null || model.GetDeclaredSymbol(bm) is not IMethodSymbol sym)
                            continue;
                        var roots = new List<SyntaxNode> { body };
                        if (bm is ConstructorDeclarationSyntax { Initializer: { } init })
                            roots.Insert(0, init);
                        yield return Make(file, sym, body, bm, roots, bm.Kind().ToString(), bm.Body is null ? "expression" : "block", model, PosOf(bm));
                        break;
                    }
                    case BasePropertyDeclarationSyntax bp:
                    {
                        if (bp.AccessorList is not null)
                            foreach (var acc in bp.AccessorList.Accessors)
                            {
                                SyntaxNode? body = acc.Body ?? (SyntaxNode?)acc.ExpressionBody;
                                if (body is null || model.GetDeclaredSymbol(acc) is not IMethodSymbol asym)
                                    continue;
                                yield return Make(file, asym, body, acc, new List<SyntaxNode> { body }, acc.Kind().ToString(), acc.Body is null ? "expression" : "block", model, PosOf(acc));
                            }
                        var eb = (bp as PropertyDeclarationSyntax)?.ExpressionBody ?? (bp as IndexerDeclarationSyntax)?.ExpressionBody;
                        if (eb is not null && model.GetDeclaredSymbol(bp) is IPropertySymbol { GetMethod: { } getter })
                            yield return Make(file, getter, eb, bp, new List<SyntaxNode> { eb }, bp.Kind().ToString(), "expression", model, PosOf(bp));
                        break;
                    }
                }
            }
    }

    static MemberInfo Make(string file, IMethodSymbol sym, SyntaxNode body, SyntaxNode scope, List<SyntaxNode> roots,
                           string kind, string form, SemanticModel model, Pos at) =>
        new()
        {
            File = file,
            Symbol = sym,
            Name = MemberName(sym),
            Kind = kind,
            BodyForm = form,
            Body = body,
            Scope = scope,
            Roots = roots,
            At = at,
            Model = model,
        };

    internal static int Run(string[] args)
    {
        string? factsPath = null, outPath = null;
        var refDirs = new List<string>();
        var raw = new List<string>();
        var quiet = false;
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == "--facts" && i + 1 < args.Length) factsPath = args[++i];
            else if ((args[i] == "-o" || args[i] == "--out") && i + 1 < args.Length) outPath = args[++i];
            else if (args[i] == "--ref-dir" && i + 1 < args.Length) refDirs.Add(args[++i]);
            else if (args[i] == "--quiet") quiet = true;
            else if (args[i] == "-h" || args[i] == "--help")
            {
                Console.WriteLine("usage: ownsharp-oracle <file.cs | dir> [...] --facts facts.json -o oracle.json [--ref-dir <dir>] [--quiet]");
                return 0;
            }
            else raw.Add(args[i]);
        }
        if (raw.Count == 0 || factsPath is null || outPath is null)
        {
            Console.Error.WriteLine("usage: ownsharp-oracle <file.cs | dir> [...] --facts facts.json -o oracle.json [--ref-dir <dir>] [--quiet]");
            return 2;
        }
        if (!File.Exists(factsPath))
        {
            Console.Error.WriteLine($"oracle: facts not found: {factsPath}");
            return 2;
        }
        var inputs = Expand(raw).Distinct().ToList();
        if (inputs.Count == 0)
        {
            Console.Error.WriteLine("oracle: no .cs input");
            return 2;
        }

        var parsed = inputs.Select(p => (file: Rel(p), tree: CSharpSyntaxTree.ParseText(File.ReadAllText(p), path: p))).ToList();
        var tpa = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "")
            .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
            .Where(p => p.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
            .ToList();
        var refNames = new HashSet<string>(tpa.Select(Path.GetFileName)!, StringComparer.OrdinalIgnoreCase);
        var references = tpa.Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
        foreach (var dir in refDirs)
        {
            if (!Directory.Exists(dir))
                continue;
            foreach (var dll in Directory.EnumerateFiles(dir, "*.dll", SearchOption.AllDirectories).OrderBy(p => p, StringComparer.Ordinal))
                if (!refNames.Contains(Path.GetFileName(dll)))
                    try { references.Add(MetadataReference.CreateFromFile(dll)); refNames.Add(Path.GetFileName(dll)); }
                    catch (Exception) { /* not loadable: the symbol degrades to unresolved, as in the extractor */ }
        }
        var compilation = CSharpCompilation.Create("own-oracle", parsed.Select(p => p.tree), references,
                                                   new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        List<Record> records;
        try
        {
            records = LoadFacts(factsPath);
        }
        catch (Exception ex) when (ex is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            Console.Error.WriteLine($"oracle: facts unreadable: {ex.GetType().Name}: {ex.Message}");
            return 2;
        }

        var members = new List<MemberInfo>();
        foreach (var (file, tree) in parsed)
        {
            var model = compilation.GetSemanticModel(tree);
            foreach (var m in Members(file, tree, model))
            {
                BuildUniverse(m);
                BuildStability(m);
                Inventory(m);
                members.Add(m);
            }
        }

        // Bind every record to exactly one member: same file and name; overloads by the sites the
        // record carries (a call or guard site is unique in a file). A record that carries no
        // sidecar at all has nothing to join; it binds by elimination when that is unambiguous
        // and is otherwise left alone, counted, never RED.
        var red = new List<Dictionary<string, object?>>();
        var unboundNoFacts = 0;
        foreach (var pass in new[] { 0, 1 })
            foreach (var rec in records)
            {
                var hasSites = rec.Calls.Count + rec.GuardSites.Count > 0;
                if (hasSites != (pass == 0))
                    continue;
                var same = members.Where(m => m.File == rec.File && m.Name == rec.Name).ToList();
                if (same.Count == 0)
                {
                    red.Add(new Dictionary<string, object?>
                    {
                        ["kind"] = "record_unbound", ["member"] = rec.Name, ["file"] = rec.File,
                        ["detail"] = $"{rec.Carrier}[{rec.Index}] names a member the oracle did not enumerate in this file",
                    });
                    continue;
                }
                MemberInfo? chosen = null;
                if (hasSites)
                {
                    var owning = same.Where(m => rec.Calls.All(c => m.Sites.ContainsKey(c.Site))
                                                 && rec.GuardSites.All(g => m.GuardSites.Contains(g))).ToList();
                    if (owning.Count == 1)
                        chosen = owning[0];
                    if (chosen is null)
                    {
                        red.Add(new Dictionary<string, object?>
                        {
                            ["kind"] = "record_unbound", ["member"] = rec.Name, ["file"] = rec.File,
                            ["detail"] = $"{rec.Carrier}[{rec.Index}]: {same.Count} overload(s), {owning.Count} own every site the record carries",
                        });
                        continue;
                    }
                }
                else
                {
                    var free = same.Where(m => m.Records.Count == 0).ToList();
                    if (free.Count == 1)
                        chosen = free[0];
                    else
                    {
                        unboundNoFacts++;
                        continue;
                    }
                }
                rec.Bound = chosen;
                chosen.Records.Add(rec);
            }
        foreach (var m in members)
            Join(m, red);

        // ---- the report ----
        var exclusionCounts = Exclusions.ToDictionary(x => x, _ => 0, StringComparer.Ordinal);
        var contextCounts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        var universe = new SortedDictionary<string, int>(StringComparer.Ordinal);
        int occurrences = 0, universeOccurrences = 0, captured = 0, excluded = 0, notCall = 0, nested = 0, nestedUnobserved = 0,
            facts = 0, matchedVarParam = 0, outsideUniverse = 0, enclosingNested = 0;
        var methodsOut = new List<Dictionary<string, object?>>();
        foreach (var m in members.OrderBy(x => x.File, StringComparer.Ordinal).ThenBy(x => x.At.Line).ThenBy(x => x.At.Column))
        {
            foreach (var (s, rule) in m.UniverseRule)
                universe[rule] = universe.GetValueOrDefault(rule) + 1;
            var occOut = new List<Dictionary<string, object?>>();
            foreach (var o in m.Occurrences)
            {
                occurrences++;
                if (!o.InUniverse)
                    continue;
                universeOccurrences++;
                if (o.Nested)
                {
                    nested++;
                    if (o.InnerContext?.StartsWith("call_slot:", StringComparison.Ordinal) == true)
                        nestedUnobserved++;
                }
                switch (o.Verdict)
                {
                    case "captured": captured++; break;
                    case "excluded": excluded++; exclusionCounts[o.Explanation!]++; break;
                    case "not_call_related": notCall++; contextCounts[o.Explanation!] = contextCounts.GetValueOrDefault(o.Explanation!) + 1; break;
                }
                enclosingNested += o.Enclosing.Count;
                var d = new Dictionary<string, object?>
                {
                    ["symbol"] = o.Name,
                    ["symbol_kind"] = o.SymbolKind,
                    ["universe_rule"] = o.UniverseRule,
                    ["at"] = $"{o.At.Line}:{o.At.Column}",
                    ["verdict"] = o.Verdict,
                    ["explanation"] = o.Explanation,
                    ["path"] = o.Path,
                };
                if (o.Site is not null)
                {
                    var sp = PosOf(o.Site);
                    d["site"] = $"{sp.Line}:{sp.Column}";
                    d["site_kind"] = o.SiteKind;
                    d["ordinal"] = o.Ordinal;
                }
                if (o.ExpectedKind is not null)
                    d["expected"] = o.ExpectedKind;
                if (o.Nested)
                {
                    d["nested_function"] = true;
                    d["inner_context"] = o.InnerContext;
                }
                if (o.Enclosing.Count > 0)
                    d["enclosing_sites"] = o.Enclosing.Select(e => new Dictionary<string, object?>
                    {
                        ["site"] = $"{PosOf(e.Site).Line}:{PosOf(e.Site).Column}", ["explanation"] = e.Explanation,
                    }).ToList();
                if (o.Detail is not null)
                    d["detail"] = o.Detail;
                occOut.Add(d);
            }
            foreach (var r in m.Records)
                facts += r.Calls.Sum(c => c.Args.Count(a => a.Kind is "var" or "param"));
            outsideUniverse += m.OutsideUniverseFacts;
            matchedVarParam += m.FactChecks.Sum(c => ((List<string>?)c.GetValueOrDefault("slots"))?.Count(s => s.EndsWith("=matched", StringComparison.Ordinal) && (s.Contains(":var=") || s.Contains(":param="))) ?? 0);
            var md = new Dictionary<string, object?>
            {
                ["member"] = m.Name,
                ["file"] = m.File,
                ["at"] = $"{m.At.Line}:{m.At.Column}",
                ["kind"] = m.Kind,
                ["body"] = m.BodyForm,
                ["carrier"] = m.Records.Count == 0 ? "none" : string.Join("+", m.Records.Select(r => r.Carrier)),
                ["universe"] = m.UniverseRule.OrderBy(kv => kv.Key.Name, StringComparer.Ordinal)
                                 .Select(kv => $"{kv.Key.Name}:{kv.Value}").ToList(),
                ["occurrences"] = occOut,
                ["facts"] = m.FactChecks,
                ["red"] = m.Red.Count,
            };
            if (m.DataFlowFallback)
                md["stability"] = "syntactic_fallback";
            methodsOut.Add(md);
        }
        var redKinds = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var r in red)
        {
            var k = (string)r["kind"]!;
            redKinds[k] = redKinds.GetValueOrDefault(k) + 1;
        }
        var errors = compilation.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
        var report = new Dictionary<string, object?>
        {
            ["schema"] = Schema,
            ["inputs"] = parsed.Select(p => p.file).ToList(),
            ["compile_errors"] = errors.Count,
            ["compile_error_examples"] = errors.Take(5).Select(d => d.ToString()).ToList(),
            ["facts"] = Rel(Path.GetFullPath(factsPath)),
            ["records"] = new Dictionary<string, object?>
            {
                ["functions"] = records.Count(r => r.Carrier == "functions"),
                ["guarded_functions"] = records.Count(r => r.Carrier == "guarded_functions"),
                ["bound"] = records.Count(r => r.Bound is not null),
                ["unbound_without_facts"] = unboundNoFacts,
            },
            ["universe"] = universe,
            ["summary"] = new Dictionary<string, object?>
            {
                ["members"] = members.Count,
                ["references"] = occurrences,
                ["universe_occurrences"] = universeOccurrences,
                ["captured"] = captured,
                ["excluded"] = excluded,
                ["enclosing_nested_call_result"] = enclosingNested,
                ["not_call_related"] = notCall,
                ["nested_function_occurrences"] = nested,
                ["nested_function_call_slots_unobserved"] = nestedUnobserved,
                ["var_param_facts"] = facts,
                ["var_param_facts_matched"] = matchedVarParam,
                ["var_facts_outside_universe"] = outsideUniverse,
                ["red"] = red.Count,
            },
            ["exclusions"] = exclusionCounts.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToDictionary(kv => kv.Key, kv => kv.Value),
            ["contexts"] = contextCounts,
            ["red_kinds"] = redKinds,
            ["red"] = red,
            ["members"] = methodsOut,
        };
        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
        File.WriteAllText(outPath, json + "\n");
        if (!quiet)
        {
            Console.WriteLine($"oracle: {members.Count} member(s), {universeOccurrences} universe occurrence(s): "
                              + $"{captured} captured, {excluded} excluded (+{enclosingNested} enclosing nested_call_result), {notCall} not call-related, "
                              + $"{nested} in nested functions; {facts} var/param fact(s), {outsideUniverse} outside the universe; RED {red.Count}");
            foreach (var (k, n) in redKinds)
                Console.WriteLine($"  RED {k}: {n}");
        }
        return red.Count == 0 ? 0 : 1;
    }
}
