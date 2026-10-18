// #400 dictionary-ref pilot (research PoC, NOT production): a ref obtained from
// CollectionsMarshal.GetValueRefOrAddDefault / GetValueRefOrNullRef on dictionary D, used after an
// event that may mutate the SAME D while the ref is live.
//
// Hazard events (precision-first; anything else, including unknown metadata calls, is NOT a hazard):
//   direct   a mutating member of D (Add, Remove, Clear, TryAdd, EnsureCapacity, TrimExcess, an indexer
//            write, another GetValueRefOrAddDefault on D)
//   delegate a delegate invocation, when D is reachable by code we cannot see (D is a field/property, a
//            parameter, or a local that escapes the method)
//   callee   a call into a first-party method/constructor whose body (depth <= 4) contains a direct mutation
//            of the same field/property D, a delegate invocation (D a field/property), or such a call
// A use is any read or write of the ref local after the event; `x = f(...)` / `x op= f(...)` counts too,
// because the location of x is evaluated before f runs. Uses in a branch exclusive with the event's
// branch are skipped.
//
// Usage: DictRefProbe <dir-or-file>... [--implicit-usings] [--json out.json]
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var inputs = new List<string>();
var implicitUsings = false;
var perFile = false;
string? jsonOut = null;
for (var i = 0; i < args.Length; i++)
{
    if (args[i] == "--implicit-usings") implicitUsings = true;
    else if (args[i] == "--per-file") perFile = true;
    else if (args[i] == "--json") jsonOut = args[++i];
    else inputs.Add(args[i]);
}

var files = inputs.SelectMany(p => Directory.Exists(p)
        ? Directory.EnumerateFiles(p, "*.cs", SearchOption.AllDirectories)
        : new[] { p })
    .Where(f => !f.Split('/', '\\').Any(s => s is "bin" or "obj"))
    .OrderBy(f => f, StringComparer.Ordinal).ToList();
var findings = new List<Dictionary<string, object>>();
var siteCount = 0;
foreach (var group in perFile ? files.Select(f => new List<string> { f }) : new[] { files })
    Analyze(group);
foreach (var f in findings)
    Console.WriteLine($"{f["file"]}:{f["line"]}:{f["column"]}: possible stale ref '{f["ref"]}' into '{f["dictionary"]}' "
                      + $"({f["api"]} at line {f["acquired_line"]}) {f["use"]} after {f["event_kind"]} event at line "
                      + $"{f["event_line"]}: {f["event"]}");
Console.WriteLine($"sites={siteCount} findings={findings.Count} files={files.Count}");
if (jsonOut is not null)
    File.WriteAllText(jsonOut, JsonSerializer.Serialize(new { sites = siteCount, findings },
        new JsonSerializerOptions { WriteIndented = true }));
return 0;

void Analyze(List<string> group)
{
var opts = new CSharpParseOptions(LanguageVersion.Preview);
var trees = group.Select(f => CSharpSyntaxTree.ParseText(File.ReadAllText(f), opts, f)).ToList();
if (implicitUsings)
    trees.Add(CSharpSyntaxTree.ParseText(string.Join("\n", new[] { "System", "System.Collections.Generic",
        "System.IO", "System.Linq", "System.Net.Http", "System.Threading", "System.Threading.Tasks" }
        .Select(n => $"global using global::{n};")), opts, "__implicit_usings.cs"));
var refs = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "").Split(Path.PathSeparator)
    .Where(p => p.EndsWith(".dll")).Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
var compilation = CSharpCompilation.Create("probe", trees, refs,
    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, allowUnsafe: true));

foreach (var tree in trees)
{
    var model = compilation.GetSemanticModel(tree);
    foreach (var decl in tree.GetRoot().DescendantNodes().OfType<VariableDeclaratorSyntax>())
    {
        if (decl.Initializer?.Value is not RefExpressionSyntax { Expression: InvocationExpressionSyntax acq }
            || !IsRefApi(acq, model, out var api)
            || model.GetDeclaredSymbol(decl) is not ILocalSymbol refLocal
            || acq.ArgumentList.Arguments.Count == 0)
            continue;
        siteCount++;
        var dictExpr = acq.ArgumentList.Arguments[0].Expression;
        var dict = model.GetSymbolInfo(dictExpr).Symbol;
        var block = decl.FirstAncestorOrSelf<BlockSyntax>();
        if (dict is null || block is null)
            continue;
        var region = block.DescendantNodes().Where(n => n.SpanStart > decl.Span.End).ToList();
        var events = new List<(SyntaxNode node, string kind, string detail)>();
        foreach (var n in region)
            if (Hazard(n, dict, model, depth: 0, visited: new HashSet<IMethodSymbol>(SymbolEqualityComparer.Default),
                       outerBody: block) is { } h)
                events.Add((n, h.kind, h.detail));
        if (events.Count == 0)
            continue;
        // `x = ref ...` re-binds the ref to a fresh location: an event before a re-bind no longer
        // reaches the uses after it, and the re-bind itself is not a use.
        var rebinds = region.OfType<AssignmentExpressionSyntax>()
            .Where(a => a.Right is RefExpressionSyntax && a.Left is IdentifierNameSyntax l
                        && SymbolEqualityComparer.Default.Equals(model.GetSymbolInfo(l).Symbol, refLocal))
            .Select(a => a.Span).ToList();
        events = events.Where(e => !rebinds.Any(r => r.Contains(e.node.Span))).ToList();
        foreach (var use in region.OfType<IdentifierNameSyntax>())
        {
            if (!SymbolEqualityComparer.Default.Equals(model.GetSymbolInfo(use).Symbol, refLocal))
                continue;
            if (use.Parent is AssignmentExpressionSyntax { Right: RefExpressionSyntax } rb && rb.Left == use)
                continue;
            var assign = use.Parent as AssignmentExpressionSyntax;
            var hit = events.FirstOrDefault(e =>
                !Exclusive(e.node, use) &&
                !rebinds.Any(r => r.Start > e.node.Span.End && r.End <= use.SpanStart) &&
                (e.node.SpanStart > use.Span.End
                    ? assign is not null && assign.Left == use && assign.Right.Span.Contains(e.node.Span)
                    : e.node.Span.End <= use.SpanStart && !e.node.Span.Contains(use.Span)));
            if (hit.node is null)
                continue;
            var u = use.GetLocation().GetLineSpan().StartLinePosition;
            findings.Add(new()
            {
                ["file"] = tree.FilePath,
                ["line"] = u.Line + 1,
                ["column"] = u.Character + 1,
                ["ref"] = refLocal.Name,
                ["api"] = api,
                ["dictionary"] = dict.Name,
                ["acquired_line"] = decl.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
                ["event_line"] = hit.node.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
                ["event_kind"] = hit.kind,
                ["event"] = hit.detail,
                ["use"] = assign is not null && assign.Left == use ? "write" : "read",
                ["method"] = decl.FirstAncestorOrSelf<MemberDeclarationSyntax>() is BaseMethodDeclarationSyntax m
                    ? (m is MethodDeclarationSyntax md ? md.Identifier.Text : m.Kind().ToString()) : "?",
            });
            break; // one finding per ref site: the first stale use
        }
    }
}

}

static bool IsRefApi(InvocationExpressionSyntax inv, SemanticModel model, out string api)
{
    api = "";
    // an argument of an unresolved type (a partial file set) leaves overload resolution with the single
    // CollectionsMarshal candidate: still identified by symbol, never by name
    var info = model.GetSymbolInfo(inv);
    var resolved = info.Symbol ?? (info.CandidateSymbols.Length == 1 ? info.CandidateSymbols[0] : null);
    if (resolved is not IMethodSymbol m
        || m.ContainingType?.ToDisplayString() != "System.Runtime.InteropServices.CollectionsMarshal"
        || m.Name is not ("GetValueRefOrAddDefault" or "GetValueRefOrNullRef"))
        return false;
    api = m.Name;
    return m.Parameters.Length > 0
           && m.Parameters[0].Type is INamedTypeSymbol { Name: "Dictionary" } t
           && t.ContainingNamespace?.ToDisplayString() == "System.Collections.Generic";
}

static bool SameSymbol(ISymbol? a, ISymbol? b) =>
    a is not null && b is not null && SymbolEqualityComparer.Default.Equals(a.OriginalDefinition, b.OriginalDefinition);

// Is D visible to code this method does not contain?
static bool Reachable(ISymbol dict, SyntaxNode outerBody, SemanticModel model)
{
    if (dict is IFieldSymbol or IPropertySymbol or IParameterSymbol)
        return true;
    if (dict is not ILocalSymbol)
        return true;
    foreach (var id in outerBody.DescendantNodes().OfType<IdentifierNameSyntax>())
    {
        if (!SameSymbol(model.GetSymbolInfo(id).Symbol, dict))
            continue;
        if (id.Parent is ArgumentSyntax a && a.Parent?.Parent is InvocationExpressionSyntax inv
            && !(model.GetSymbolInfo(inv).Symbol is IMethodSymbol { ContainingType: var ct }
                 && ct?.ToDisplayString() == "System.Runtime.InteropServices.CollectionsMarshal"))
            return true; // escapes into a call
        if (id.Ancestors().Any(x => x is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax))
            return true; // captured
        if (id.Parent is AssignmentExpressionSyntax asg && asg.Right == id)
            return true; // aliased
        if (id.Parent is ReturnStatementSyntax)
            return true;
    }
    return false;
}


static (string kind, string detail)? Hazard(SyntaxNode n, ISymbol dict, SemanticModel model, int depth,
                                            HashSet<IMethodSymbol> visited, SyntaxNode outerBody)
{
    // indexer write on the same dictionary
    if (n is AssignmentExpressionSyntax { Left: ElementAccessExpressionSyntax ea }
        && SameSymbol(model.GetSymbolInfo(ea.Expression).Symbol, dict))
        return ("direct", $"{ea.Expression}[...] = ...");
    if (n is not InvocationExpressionSyntax inv)
        return n is BaseObjectCreationExpressionSyntax oce ? Callee(oce, model.GetSymbolInfo(oce).Symbol as IMethodSymbol,
                                                                    dict, model, depth, visited) : null;
    var target = model.GetSymbolInfo(inv);
    var sym = target.Symbol ?? target.CandidateSymbols.FirstOrDefault();
    // direct mutation
    if (inv.Expression is MemberAccessExpressionSyntax ma
        && ma.Name.Identifier.Text is "Add" or "TryAdd" or "Remove" or "Clear" or "EnsureCapacity" or "TrimExcess"
        && SameSymbol(model.GetSymbolInfo(ma.Expression).Symbol, dict))
        return ("direct", inv.ToString());
    if (sym is IMethodSymbol { Name: "GetValueRefOrAddDefault" } g
        && g.ContainingType?.ToDisplayString() == "System.Runtime.InteropServices.CollectionsMarshal"
        && inv.ArgumentList.Arguments.Count > 0
        && SameSymbol(model.GetSymbolInfo(inv.ArgumentList.Arguments[0].Expression).Symbol, dict))
        return ("direct", inv.ToString());
    // delegate invocation: a delegate's Invoke, or calling the VALUE of a local/parameter/field/property
    var invokedValue = model.GetSymbolInfo(inv.Expression).Symbol;
    var isDelegate = sym is IMethodSymbol { MethodKind: MethodKind.DelegateInvoke }
                     || invokedValue is ILocalSymbol or IParameterSymbol or IFieldSymbol or IPropertySymbol;
    if (isDelegate && (depth > 0 || Reachable(dict, outerBody, model)))
        return ("delegate", inv.ToString());
    return Callee(inv, sym as IMethodSymbol, dict, model, depth, visited);
}

static (string kind, string detail)? Callee(SyntaxNode site, IMethodSymbol? m, ISymbol dict, SemanticModel model,
                                            int depth, HashSet<IMethodSymbol> visited)
{
    // only a field/property D can be reached from inside another method body
    if (m is null || depth >= 4 || dict is not (IFieldSymbol or IPropertySymbol) || !visited.Add(m.OriginalDefinition))
        return null;
    foreach (var sref in m.OriginalDefinition.DeclaringSyntaxReferences)
    {
        var body = sref.GetSyntax() switch
        {
            BaseMethodDeclarationSyntax b => (SyntaxNode?)b.Body ?? b.ExpressionBody,
            LocalFunctionStatementSyntax lf => (SyntaxNode?)lf.Body ?? lf.ExpressionBody,
            _ => null,
        };
        if (body is null)
            continue;
        var cm = model.Compilation.GetSemanticModel(body.SyntaxTree);
        foreach (var n in body.DescendantNodes())
            if (Hazard(n, dict, cm, depth + 1, visited, body) is { } h)
                return ("callee", $"{Short(site)} -> {h.detail}");
    }
    return null;
}

static string Short(SyntaxNode n) { var s = n.ToString(); return s.Length > 60 ? s[..60] + "..." : s; }

// e is in the `then` of an if whose `else` holds u (or the reverse): never both on one path.
static bool Exclusive(SyntaxNode e, SyntaxNode u)
{
    foreach (var ifs in e.Ancestors().OfType<IfStatementSyntax>())
    {
        if (ifs.Else is null) continue;
        var eThen = ifs.Statement.Span.Contains(e.Span); var uThen = ifs.Statement.Span.Contains(u.Span);
        var eElse = ifs.Else.Span.Contains(e.Span); var uElse = ifs.Else.Span.Contains(u.Span);
        if ((eThen && uElse) || (eElse && uThen)) return true;
    }
    return false;
}
