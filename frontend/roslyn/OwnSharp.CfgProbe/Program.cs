// resource-effects Stage 2A probe (EXPLORATORY; research/resource-effects-v1). For every method of every input
// file that has a tracked handle (an IDisposable parameter, or a local initialised by `new` of an IDisposable
// type) it answers the pre-registered effect question three ways and prints one JSON line per method:
//   * "ioperation": a walk over the IOperation tree with the definite-release discipline at the operation level
//     (resolved symbols; a release under a conditional/loop/catch/conditional-access, or after an earlier
//     return, is not definite; nested lambdas and local functions are not immediate);
//   * "cfg": a must-analysis over ControlFlowGraph.Create(body): the set of handles released at block entry is
//     the intersection over predecessors; a branch that leaves finally regions applies those regions' releases;
//     the answer is read at the exit block. The number of handwritten lines of that analysis is the "bespoke"
//     figure the KILL GATE reads.
// The production "syntax" answer comes from the real extractor + the Python reference, run by the driver.
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.FlowAnalysis;
using Microsoft.CodeAnalysis.Operations;

var refs = new List<MetadataReference>();
foreach (var dll in Directory.GetFiles(Path.GetDirectoryName(typeof(object).Assembly.Location)!, "System*.dll")
                             .Append(typeof(object).Assembly.Location).Append(Path.Combine(Path.GetDirectoryName(typeof(object).Assembly.Location)!, "netstandard.dll")))
{
    try { refs.Add(MetadataReference.CreateFromFile(dll)); } catch (Exception) { /* a native image: skip */ }
}
foreach (var file in args)
{
    var tree = CSharpSyntaxTree.ParseText(File.ReadAllText(file), path: file);
    var comp = CSharpCompilation.Create("probe", new[] { tree }, refs,
        new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
    var model = comp.GetSemanticModel(tree);
    foreach (var m in tree.GetRoot().DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        if (model.GetDeclaredSymbol(m) is not IMethodSymbol ms) continue;
        var handles = new List<ISymbol>();
        handles.AddRange(ms.Parameters.Where(p => Disposable(p.Type)));
        foreach (var v in m.DescendantNodes().OfType<VariableDeclaratorSyntax>())
            if (v.Initializer?.Value is ObjectCreationExpressionSyntax oc && Disposable(model.GetTypeInfo(oc).Type)
                && model.GetDeclaredSymbol(v) is ILocalSymbol ls)
                handles.Add(ls);
        if (handles.Count == 0) continue;
        if (model.GetOperation(m) is not IMethodBodyOperation body) continue;
        var cfg = ControlFlowGraph.Create(body);
        var row = new Dictionary<string, object?>
        {
            ["file"] = Path.GetFileName(file), ["method"] = ms.Name,
            ["handles"] = handles.Select(h => h.Name).ToList(),
            ["ioperation"] = handles.ToDictionary(h => h.Name, h => IOperationAnswer(body, h)),
            ["cfg"] = handles.ToDictionary(h => h.Name, h => CfgAnswer(cfg, h)),
            ["cfg_blocks"] = cfg.Blocks.Length,
            ["cfg_regions"] = Regions(cfg.Root).Select(r => r.Kind.ToString()).Distinct().OrderBy(s => s).ToList(),
            ["cfg_captures"] = cfg.Blocks.SelectMany(b => b.Operations).SelectMany(o => o.DescendantsAndSelf())
                                  .Count(o => o is IFlowCaptureOperation),
            ["local_function_cfgs"] = cfg.LocalFunctions.Length,
            ["returns_new_directly"] = m.DescendantNodes().OfType<ReturnStatementSyntax>()
                                        .Any(r => r.Expression is ObjectCreationExpressionSyntax),
        };
        Console.WriteLine(JsonSerializer.Serialize(row));
    }
}

static bool Disposable(ITypeSymbol? t) =>
    t is not null && (t.Name == "IDisposable" || t.AllInterfaces.Any(i => i.Name == "IDisposable"));

static IEnumerable<ControlFlowRegion> Regions(ControlFlowRegion r)
{
    yield return r;
    foreach (var n in r.NestedRegions) foreach (var x in Regions(n)) yield return x;
}

static bool IsRelease(IOperation op, ISymbol handle) =>
    op is IInvocationOperation inv
    && inv.TargetMethod.Name is "Dispose" or "Close" or "DisposeAsync"
    && inv.Instance is { } inst && Refers(inst, handle);

static bool Refers(IOperation inst, ISymbol handle) => inst switch
{
    IParameterReferenceOperation p => SymbolEqualityComparer.Default.Equals(p.Parameter, handle),
    ILocalReferenceOperation l => SymbolEqualityComparer.Default.Equals(l.Local, handle),
    IConversionOperation c => Refers(c.Operand, handle),
    _ => false,
};

// IOperation answer: "must" if a release of the handle is immediate (not inside a lambda / local function)
// and definite (no conditional / loop / catch / conditional-access ancestor, no earlier return); "may" if a
// release exists but is not definite; "no" otherwise.
static string IOperationAnswer(IMethodBodyOperation body, ISymbol handle)
{
    var any = false;
    foreach (var op in body.DescendantsAndSelf())
    {
        if (!IsRelease(op, handle)) continue;
        any = true;
        var definite = true;
        for (var a = op.Parent; a is not null; a = a.Parent)
        {
            if (a is IAnonymousFunctionOperation or ILocalFunctionOperation) { definite = false; break; }
            if (a is IConditionalOperation or ILoopOperation or ISwitchOperation or ICatchClauseOperation
                  or IConditionalAccessOperation or ICoalesceOperation) { definite = false; break; }
        }
        // an earlier return on the same body (before this release in tree order) is not covered
        if (definite && body.DescendantsAndSelf().OfType<IReturnOperation>()
                            .Any(r => r.Syntax.SpanStart < op.Syntax.SpanStart
                                      && !r.Syntax.Ancestors().OfType<AnonymousFunctionExpressionSyntax>().Any()
                                      && !r.Syntax.Ancestors().OfType<LocalFunctionStatementSyntax>().Any()))
            definite = false;
        if (definite) return "must";
    }
    return any ? "may" : "no";
}

// CFG answer (the bespoke analysis; lines counted by the driver between the BEGIN/END markers).
// BEGIN CFG-ANALYSIS
static string CfgAnswer(ControlFlowGraph cfg, ISymbol handle)
{
    var blocks = cfg.Blocks;
    var released = new bool?[blocks.Length];          // null = not yet visited
    var work = new Queue<int>(); work.Enqueue(cfg.Blocks.First(b => b.Kind == BasicBlockKind.Entry).Ordinal);
    released[work.Peek()] = false;
    var seenRelease = false;
    bool BlockReleases(BasicBlock b) => b.Operations.SelectMany(o => o.DescendantsAndSelf())
        .Concat(b.BranchValue?.DescendantsAndSelf() ?? Enumerable.Empty<IOperation>()).Any(o => IsRelease(o, handle));
    bool FinallyReleases(ControlFlowBranch br) => br.FinallyRegions.Any(f =>
        Enumerable.Range(f.FirstBlockOrdinal, f.LastBlockOrdinal - f.FirstBlockOrdinal + 1).Any(i => BlockReleases(blocks[i])));
    while (work.Count > 0)
    {
        var b = blocks[work.Dequeue()];
        var state = released[b.Ordinal]!.Value;
        if (BlockReleases(b)) { state = true; seenRelease = true; }
        foreach (var br in new[] { b.ConditionalSuccessor, b.FallThroughSuccessor })
        {
            if (br?.Destination is not { } d) continue;
            var outState = state || FinallyReleases(br);
            if (FinallyReleases(br)) seenRelease = true;
            var joined = released[d.Ordinal] is null ? outState : released[d.Ordinal]!.Value && outState;
            if (released[d.Ordinal] != joined) { released[d.Ordinal] = joined; work.Enqueue(d.Ordinal); }
        }
    }
    var exit = cfg.Blocks.First(b => b.Kind == BasicBlockKind.Exit);
    return released[exit.Ordinal] == true ? "must" : seenRelease ? "may" : "no";
}
// END CFG-ANALYSIS
