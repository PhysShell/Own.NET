// OwnSharp OwnIR extractor (P-001 v0).
//
// Scans C# *source text* (syntax only — no compilation, no references) for the
// event-subscription leak pattern and emits OwnIR facts (JSON) in the OwnLang
// spec's vocabulary. The Python core (`python -m ownlang ownir facts.json`) then
// produces the verdict (OWN001 leak) at the C# location.
//
// v0 heuristic (documented in docs/proposals/P-001): a subscription is
// `target += handler` where the right side is a method group (identifier or
// member access), not e.g. `count += 1`. It is "released" if a matching
// `target -= handler` (same text on both sides) exists anywhere in the class.
//
// Usage: ownsharp-extract <file.cs> [more.cs ...] [-o facts.json]

using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var inputs = new List<string>();
string? outPath = null;
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "-o" && i + 1 < args.Length) outPath = args[++i];
    else inputs.Add(args[i]);
}

if (inputs.Count == 0)
{
    Console.Error.WriteLine("usage: ownsharp-extract <file.cs> [...] [-o facts.json]");
    return 2;
}

static bool IsHandler(ExpressionSyntax rhs) =>
    rhs is IdentifierNameSyntax || rhs is MemberAccessExpressionSyntax;

static int LineOf(SyntaxNode node) =>
    node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

var components = new List<object>();

foreach (var path in inputs)
{
    var text = File.ReadAllText(path);
    var file = Path.GetFileName(path);
    var root = CSharpSyntaxTree.ParseText(text, path: path).GetRoot();

    foreach (var cls in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
    {
        var assigns = cls.DescendantNodes().OfType<AssignmentExpressionSyntax>().ToList();

        // every `target -= handler` in this class, keyed by "left|right".
        var unsub = new HashSet<string>();
        foreach (var a in assigns)
            if (a.IsKind(SyntaxKind.SubtractAssignmentExpression) && IsHandler(a.Right))
                unsub.Add($"{a.Left}|{a.Right}");

        var subs = new List<object>();
        foreach (var a in assigns)
        {
            if (!a.IsKind(SyntaxKind.AddAssignmentExpression) || !IsHandler(a.Right))
                continue;
            subs.Add(new
            {
                @event = a.Left.ToString(),
                handler = a.Right.ToString(),
                line = LineOf(a.Left),
                released = unsub.Contains($"{a.Left}|{a.Right}"),
            });
        }

        if (subs.Count > 0)
            components.Add(new { name = cls.Identifier.Text, file, subscriptions = subs });
    }
}

var facts = new { module = "Extracted", components };
var json = JsonSerializer.Serialize(facts, new JsonSerializerOptions { WriteIndented = true });

if (outPath is null) Console.WriteLine(json);
else File.WriteAllText(outPath, json);
return 0;
