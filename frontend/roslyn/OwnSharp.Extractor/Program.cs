// OwnSharp OwnIR extractor (P-001 v0).
//
// Scans C# *source text* (syntax only — no compilation, no references) for the
// event-subscription leak pattern and emits OwnIR facts (JSON) in the OwnLang
// spec's vocabulary. The Python core (`python -m ownlang ownir facts.json`) then
// produces the verdict (OWN001 leak) at the C# location.
//
// Heuristic (docs/proposals/P-001, P-004): a subscription is `target += handler`
// where the right side is a method group (identifier or member access), not e.g.
// `count += 1`. It is "released" if a matching `target -= handler` (same text on
// both sides) exists in the class. A `Tick`/`Elapsed` handler is additionally
// tagged resource=timer (WPF002) and counts as released if the timer's receiver
// also has a `.Stop()` call (e.g. `_timer.Stop()` in Dispose).
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

// The field name an expression refers to: "_f" for `_f` or `this._f`, else null.
static string? FieldName(ExpressionSyntax expr) => expr switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m => m.Name.Identifier.Text,
    _ => null,
};

// A field type treated as owned-disposable (syntax-only heuristic — no semantic
// model): a curated set plus a few suffixes. Gated on the class `new`ing the
// field (see below), so injected/borrowed disposables are not flagged.
static bool IsDisposableType(string t) =>
    t is "IDisposable" or "IAsyncDisposable" or "DispatcherTimer" or "Timer"
       or "CancellationTokenSource" or "HttpClient" or "SerialPort"
       or "SqlConnection"
    || t.EndsWith("Stream") || t.EndsWith("Reader") || t.EndsWith("Writer")
    || t.EndsWith("Timer") || t.EndsWith("Subscription");

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

        // every receiver with a `.Stop()` call: a timer detached this way counts
        // as released even without an explicit `Tick -=` (e.g. Stop() in Dispose).
        var stopped = new HashSet<string>();
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text == "Stop")
                stopped.Add(m.Expression.ToString());

        var subs = new List<object>();
        foreach (var a in assigns)
        {
            if (!a.IsKind(SyntaxKind.AddAssignmentExpression) || !IsHandler(a.Right))
                continue;
            var isTimer = IsTimerEvent(a.Left);
            var released = unsub.Contains($"{a.Left}|{a.Right}")
                || (isTimer && Receiver(a.Left) is { } recv && stopped.Contains(recv));
            subs.Add(new
            {
                @event = a.Left.ToString(),
                handler = a.Right.ToString(),
                line = LineOf(a.Left),
                released,
                resource = isTimer ? "timer" : "subscription",
            });
        }

        // WPF003: an IDisposable field the class constructs (`new`) but never
        // disposes. Owned (not injected) = assigned a `new` in this class;
        // released = a `<field>.Dispose()` call somewhere in the class.
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

        var disposed = new HashSet<string>();
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text == "Dispose"
                && FieldName(m.Expression) is { } df)
                disposed.Add(df);

        foreach (var fd in cls.Members.OfType<FieldDeclarationSyntax>())
        {
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

        if (subs.Count > 0)
            components.Add(new { name = cls.Identifier.Text, file, subscriptions = subs });
    }
}

// ownir_version stamps the fact-schema vocabulary; the Python core rejects a
// mismatch loudly (ownlang/ownir.py OWNIR_VERSION) rather than mis-reading facts.
var facts = new { ownir_version = 0, module = "Extracted", components };
var json = JsonSerializer.Serialize(facts, new JsonSerializerOptions { WriteIndented = true });

if (outPath is null) Console.WriteLine(json);
else File.WriteAllText(outPath, json);
return 0;
