// N1-F0 part B: ownership oracle (00-preregistration.md, F0-B). Research only, throwaway.
//
// usage: f0oracle --refs <dir> [--refs <dir>] --group <name>=<file>[;<file>...] [--group ...] --out out.tsv
//
// A call result r acquired in method M of type T is OWNED when (rules 1-3 of the pre-registration):
//   1. M hands r over on the success path to (a) a field f of T, (b) an element of a collection field f
//      (indexer store, Add, TryAdd), or (c) a constructor argument of an in-source type W whose ctor stores
//      it in a field g of W, the W instance being returned or stored as in (a)/(b);
//   2. the same type (T, or W for (c)) disposes that target: Dispose/DisposeAsync/Close/CloseAsync on f/g,
//      on a local taken from f (TryRemove/Remove out, indexer read, foreach over f or f.Values), or
//      using/await using of one of those;
//   3. the acquisition is not a borrow (IServiceProvider.GetService and friends).
// DEFECT: a throwing site (any invocation or await, except nameof/typeof) lies between the acquisition and
// the hand-over, and no enclosing try disposes r in its catch or finally.
// "Disposes r" is operationalised (fixed before the first run on real files) as any of:
//   - Dispose/DisposeAsync/Close/CloseAsync on r (also r?.X);
//   - the same call on `new W(r)` where W is an owning wrapper by rules 1c+2;
//   - r passed to a method of T whose body disposes the corresponding parameter (one hop).
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var refDirs = new List<string>();
var groups = new List<(string Name, string[] Files)>();
string? outPath = null;
for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--refs": refDirs.Add(args[++i]); break;
        case "--group":
            var g = args[++i].Split('=', 2);
            groups.Add((g[0], g[1].Split(';')));
            break;
        case "--out": outPath = args[++i]; break;
        default: throw new ArgumentException(args[i]);
    }
}
var refs = refDirs.SelectMany(d => Directory.EnumerateFiles(d, "*.dll"))
    .Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
var rows = new List<string> { "group\tfile\ttype\tmethod\tacq_line\tacq\thandover_line\tkind\tdispose_evidence\tthrow_line\tthrow_site" };
foreach (var (name, files) in groups)
{
    var trees = files.Select(f => CSharpSyntaxTree.ParseText(File.ReadAllText(f),
        new CSharpParseOptions(LanguageVersion.Preview), Path.GetFileName(f))).ToList();
    var comp = CSharpCompilation.Create(name, trees, refs,
        new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
    var o = new Oracle(comp);
    foreach (var t in trees) o.Run(t);
    foreach (var f in o.Findings) rows.Add(name + "\t" + f);
    Console.Error.WriteLine($"{name}: {o.Findings.Count} findings, {o.OwnedAcquisitions} owned acquisitions, {o.Acquisitions} call acquisitions");
}
File.WriteAllLines(outPath ?? "f0b.tsv", rows);
foreach (var r in rows) Console.WriteLine(r);
return 0;

sealed class Oracle(CSharpCompilation comp)
{
    public readonly List<string> Findings = new();
    public int Acquisitions, OwnedAcquisitions;

    static readonly HashSet<string> DisposeNames = new() { "Dispose", "DisposeAsync", "Close", "CloseAsync" };
    static readonly HashSet<string> BorrowNames = new()
        { "GetService", "GetRequiredService", "GetServices", "GetKeyedService", "GetRequiredKeyedService", "GetKeyedServices", "GetServiceOrCreateInstance" };
    static readonly HashSet<string> StoreNames = new() { "Add", "TryAdd", "AddOrUpdate", "GetOrAdd", "Enqueue", "Push" };

    static int Line(SyntaxNode n) => n.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
    static string Snip(SyntaxNode n)
    {
        var s = string.Join(' ', n.ToString().Split((char[])['\r', '\n', '\t'], StringSplitOptions.RemoveEmptyEntries).Select(x => x.Trim()));
        return s.Length > 90 ? s[..90] + "…" : s;
    }

    static ExpressionSyntax Strip(ExpressionSyntax e)
    {
        while (true)
        {
            switch (e)
            {
                case AwaitExpressionSyntax a: e = a.Expression; continue;
                case ParenthesizedExpressionSyntax p: e = p.Expression; continue;
                case PostfixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.SuppressNullableWarningExpression } pu: e = pu.Operand; continue;
                case InvocationExpressionSyntax { Expression: MemberAccessExpressionSyntax { Name.Identifier.Text: "ConfigureAwait" } ma }: e = ma.Expression; continue;
                default: return e;
            }
        }
    }

    static string? InvokedName(InvocationExpressionSyntax inv) => inv.Expression switch
    {
        MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
        SimpleNameSyntax s => s.Identifier.Text,
        MemberBindingExpressionSyntax mb => mb.Name.Identifier.Text,
        _ => null,
    };

    // the root identifier of a receiver / expression (x in x.a.b, this.x, x?.y)
    static string? RootName(ExpressionSyntax e)
    {
        while (true)
        {
            switch (e)
            {
                case MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } m: return m.Name.Identifier.Text;
                case MemberAccessExpressionSyntax m: e = m.Expression; continue;
                case ConditionalAccessExpressionSyntax c: e = c.Expression; continue;
                case ElementAccessExpressionSyntax ea: e = ea.Expression; continue;
                case ParenthesizedExpressionSyntax p: e = p.Expression; continue;
                case PostfixUnaryExpressionSyntax pu: e = pu.Operand; continue;
                case IdentifierNameSyntax id: return id.Identifier.Text;
                default: return null;
            }
        }
    }

    // receiver of a dispose-family call: `x.Dispose()`, `x?.Dispose()`, `(expr).DisposeAsync()`
    static ExpressionSyntax? DisposeReceiver(InvocationExpressionSyntax inv)
    {
        if (inv.Expression is MemberAccessExpressionSyntax ma && DisposeNames.Contains(ma.Name.Identifier.Text)) return ma.Expression;
        if (inv.Expression is MemberBindingExpressionSyntax mb && DisposeNames.Contains(mb.Name.Identifier.Text)
            && inv.Parent is ConditionalAccessExpressionSyntax ca) return ca.Expression;
        return null;
    }

    static IEnumerable<InvocationExpressionSyntax> DisposeCalls(SyntaxNode n) =>
        n.DescendantNodesAndSelf().OfType<InvocationExpressionSyntax>().Where(i => DisposeReceiver(i) is not null);

    // Rule 2: does type `decl` dispose field `field` (directly, via a local taken from it, or via using)?
    string? DisposesField(TypeDeclarationSyntax decl, string field)
    {
        var fromField = new HashSet<string>();
        foreach (var arg in decl.DescendantNodes().OfType<ArgumentSyntax>())
        {
            if (arg.Expression is DeclarationExpressionSyntax { Designation: SingleVariableDesignationSyntax sv }
                && arg.Parent?.Parent is InvocationExpressionSyntax inv && InvokedName(inv) is "TryRemove" or "Remove" or "TryGetValue" or "TryDequeue" or "TryPop" or "TryTake"
                && inv.Expression is MemberAccessExpressionSyntax ma && RootName(ma.Expression) == field)
                fromField.Add(sv.Identifier.Text);
        }
        foreach (var v in decl.DescendantNodes().OfType<VariableDeclaratorSyntax>())
            if (v.Initializer?.Value is ElementAccessExpressionSyntax ea && RootName(ea.Expression) == field) fromField.Add(v.Identifier.Text);
        foreach (var fe in decl.DescendantNodes().OfType<ForEachStatementSyntax>())
            if (RootName(fe.Expression) == field) fromField.Add(fe.Identifier.Text);
        foreach (var call in DisposeCalls(decl))
        {
            var root = RootName(DisposeReceiver(call)!);
            if (root == field || (root is not null && fromField.Contains(root))) return $"{Line(call)}: {Snip(call)}";
        }
        foreach (var u in decl.DescendantNodes().OfType<LocalDeclarationStatementSyntax>().Where(l => l.UsingKeyword != default))
            foreach (var v in u.Declaration.Variables)
                if (v.Initializer?.Value is { } init && (RootName(init) == field || (RootName(init) is { } r && fromField.Contains(r))))
                    return $"{Line(u)}: {Snip(u)}";
        return null;
    }

    bool IsField(TypeDeclarationSyntax decl, string name) =>
        decl.Members.OfType<FieldDeclarationSyntax>().Any(f => f.Declaration.Variables.Any(v => v.Identifier.Text == name))
        || decl.Members.OfType<PropertyDeclarationSyntax>().Any(p => p.Identifier.Text == name);

    // Rule 1c: in-source wrapper type W whose ctor stores parameter #i into a field g that W disposes.
    (TypeDeclarationSyntax W, string Evidence)? OwningWrapper(ObjectCreationExpressionSyntax oc, int argIndex)
    {
        var tn = oc.Type switch { IdentifierNameSyntax i => i.Identifier.Text, QualifiedNameSyntax q => q.Right.Identifier.Text, _ => null };
        if (tn is null) return null;
        foreach (var tree in comp.SyntaxTrees)
            foreach (var w in tree.GetRoot().DescendantNodes().OfType<TypeDeclarationSyntax>().Where(t => t.Identifier.Text == tn))
                foreach (var ctor in w.Members.OfType<ConstructorDeclarationSyntax>())
                {
                    if (argIndex >= ctor.ParameterList.Parameters.Count) continue;
                    var p = ctor.ParameterList.Parameters[argIndex].Identifier.Text;
                    foreach (var asg in ctor.DescendantNodes().OfType<AssignmentExpressionSyntax>())
                        if (asg.Right is IdentifierNameSyntax { Identifier.Text: var rp } && rp == p && RootName(asg.Left) is { } g && IsField(w, g)
                            && DisposesField(w, g) is { } ev)
                            return (w, $"{tn}.{g} disposed at {ev}");
                }
        return null;
    }

    public void Run(SyntaxTree tree)
    {
        foreach (var decl in tree.GetRoot().DescendantNodes().OfType<TypeDeclarationSyntax>())
            foreach (var m in decl.Members.OfType<MethodDeclarationSyntax>())
                if (m.Body is not null) Scan(decl, m);
    }

    void Scan(TypeDeclarationSyntax T, MethodDeclarationSyntax M)
    {
        // acquisitions: `var r = <call>` or `r = <call>`, the call possibly awaited
        var acqs = new List<(string R, SyntaxNode Stmt, InvocationExpressionSyntax Call)>();
        foreach (var v in M.Body!.DescendantNodes().OfType<VariableDeclaratorSyntax>())
            if (v.Initializer?.Value is { } init && Strip(init) is InvocationExpressionSyntax inv)
                acqs.Add((v.Identifier.Text, v, inv));
        foreach (var a in M.Body.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            if (a.Left is IdentifierNameSyntax id && Strip(a.Right) is InvocationExpressionSyntax inv2
                && M.Body.DescendantNodes().OfType<VariableDeclaratorSyntax>().Any(v => v.Identifier.Text == id.Identifier.Text))
                acqs.Add((id.Identifier.Text, a, inv2));
        foreach (var (r, stmt, call) in acqs)
        {
            if (InvokedName(call) is { } nm && (BorrowNames.Contains(nm) || nm is "nameof")) continue; // rule 3
            Acquisitions++;
            var after = stmt.Span.End;
            // rule 1: hand-over target on the success path, after the acquisition
            SyntaxNode? hand = null; string? kind = null; string? ev = null;
            foreach (var n in M.Body.DescendantNodes().Where(n => n.SpanStart >= after))
            {
                if (n is AssignmentExpressionSyntax { Right: var rhs } asg && Strip(rhs) is IdentifierNameSyntax { Identifier.Text: var rr } && rr == r)
                {
                    if (asg.Left is ElementAccessExpressionSyntax ea && RootName(ea.Expression) is { } cf && IsField(T, cf) && DisposesField(T, cf) is { } e1)
                    { hand = asg; kind = $"1b {cf}[]"; ev = e1; break; }
                    if (asg.Left is IdentifierNameSyntax or MemberAccessExpressionSyntax && RootName(asg.Left) is { } ff && ff != r && IsField(T, ff) && DisposesField(T, ff) is { } e2)
                    { hand = asg; kind = $"1a {ff}"; ev = e2; break; }
                }
                if (n is InvocationExpressionSyntax si && InvokedName(si) is { } sn && StoreNames.Contains(sn)
                    && si.Expression is MemberAccessExpressionSyntax sma && RootName(sma.Expression) is { } sf && IsField(T, sf)
                    && si.ArgumentList.Arguments.Any(x => Strip(x.Expression) is IdentifierNameSyntax { Identifier.Text: var ar } && ar == r)
                    && DisposesField(T, sf) is { } e3)
                { hand = si; kind = $"1b {sf}.{sn}"; ev = e3; break; }
                if (n is ObjectCreationExpressionSyntax oc && oc.ArgumentList is { } al)
                {
                    var idx = al.Arguments.ToList().FindIndex(x => Strip(x.Expression) is IdentifierNameSyntax { Identifier.Text: var ar } && ar == r);
                    if (idx >= 0 && OwningWrapper(oc, idx) is { } w
                        && (oc.Parent is ReturnStatementSyntax || (oc.Parent is AssignmentExpressionSyntax pa && RootName(pa.Left) is { } wf && IsField(T, wf))))
                    { hand = oc; kind = $"1c {w.W.Identifier.Text}"; ev = w.Evidence; break; }
                }
            }
            if (hand is null) continue;
            OwnedAcquisitions++;
            // defect: a throwing site strictly between the acquisition and the hand-over, not covered by a disposing try
            var throwing = M.Body.DescendantNodes()
                .Where(n => n.SpanStart >= after && n.Span.End <= hand.SpanStart)
                .Where(n => n is InvocationExpressionSyntax inv3 ? InvokedName(inv3) is not ("nameof") : n is AwaitExpressionSyntax)
                .Where(n => !n.Ancestors().Any(a => a == hand))
                // disposing r cannot leak r (control N6: the dispose inside the catch)
                .Where(n => !(Strip(n is AwaitExpressionSyntax aw ? aw.Expression : (ExpressionSyntax)n) is InvocationExpressionSyntax di
                              && DisposeReceiver(di) is { } dr && RootName(dr) == r))
                .FirstOrDefault(n => !CoveredByDisposingTry(T, n, r, M));
            if (throwing is null) continue;
            Findings.Add(string.Join('\t', T.SyntaxTree.FilePath, T.Identifier.Text, M.Identifier.Text, Line(stmt), Snip(call),
                Line(hand), kind, ev, Line(throwing), Snip(throwing)));
        }
    }

    bool CoveredByDisposingTry(TypeDeclarationSyntax T, SyntaxNode site, string r, MethodDeclarationSyntax M)
    {
        foreach (var tr in site.Ancestors().OfType<TryStatementSyntax>())
        {
            if (!tr.Block.Span.Contains(site.Span)) continue;
            var cleanup = tr.Catches.Select(c => (SyntaxNode)c.Block).Concat(tr.Finally is { } f ? new SyntaxNode[] { f.Block } : []);
            if (cleanup.Any(b => DisposesLocal(T, b, r))) return true;
        }
        return false;
    }

    bool DisposesLocal(TypeDeclarationSyntax T, SyntaxNode block, string r)
    {
        foreach (var call in DisposeCalls(block))
        {
            var recv = DisposeReceiver(call)!;
            if (RootName(recv) == r) return true;
            if (recv is ObjectCreationExpressionSyntax oc && oc.ArgumentList is { } al)
            {
                var idx = al.Arguments.ToList().FindIndex(x => Strip(x.Expression) is IdentifierNameSyntax { Identifier.Text: var ar } && ar == r);
                if (idx >= 0 && OwningWrapper(oc, idx) is not null) return true;
            }
        }
        // one hop: r passed to a method of T whose body disposes that parameter
        foreach (var inv in block.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (inv.Expression is not IdentifierNameSyntax callee) continue;
            var idx = inv.ArgumentList.Arguments.ToList().FindIndex(x => Strip(x.Expression) is IdentifierNameSyntax { Identifier.Text: var ar } && ar == r);
            if (idx < 0) continue;
            foreach (var md in T.Members.OfType<MethodDeclarationSyntax>().Where(x => x.Identifier.Text == callee.Identifier.Text))
            {
                if (idx >= md.ParameterList.Parameters.Count) continue;
                var p = md.ParameterList.Parameters[idx].Identifier.Text;
                if (DisposeCalls(md).Any(c => RootName(DisposeReceiver(c)!) == p)) return true;
            }
        }
        return false;
    }
}
