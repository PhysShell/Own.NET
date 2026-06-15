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
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "-o" && i + 1 < args.Length) outPath = args[++i];
    else rawInputs.Add(args[i]);
}

if (rawInputs.Count == 0)
{
    Console.Error.WriteLine("usage: ownsharp-extract <file.cs | dir> [...] [-o facts.json]");
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
static IEnumerable<string> Expand(IEnumerable<string> roots)
{
    foreach (var p in roots)
    {
        if (Directory.Exists(p))
        {
            foreach (var f in Directory.EnumerateFiles(p, "*.cs", SearchOption.AllDirectories))
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

// The field name an expression refers to: "_f" for `_f` or `this._f`, else null.
static string? FieldName(ExpressionSyntax expr) => expr switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m => m.Name.Identifier.Text,
    _ => null,
};

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

var components = new List<object>();

foreach (var path in inputs)
{
    var text = File.ReadAllText(path);
    var file = Rel(path);
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
                && m.Name.Identifier.Text is "Dispose" or "DisposeAsync"
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
                });

        // POOL001: an ArrayPool/MemoryPool buffer `Rent`ed but never `Return`ed,
        // matched per member so a `buf` returned in one method does not mask a
        // leak of a same-named `buf` in another.
        foreach (var member in cls.Members)
        {
            var rented = new List<(string Name, int Line)>();
            foreach (var inv in member.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (inv.Expression is MemberAccessExpressionSyntax m
                    && m.Name.Identifier.Text == "Rent"
                    && (m.Expression.ToString().Contains("Pool")
                        || m.Expression.ToString().Contains("pool")))
                {
                    string? name = inv.Parent switch
                    {
                        EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax vd }
                            => vd.Identifier.Text,
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
        // (P-005 D5), so those are conservatively excluded. Per member.
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
