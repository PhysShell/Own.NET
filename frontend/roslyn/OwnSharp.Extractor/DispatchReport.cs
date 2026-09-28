// P-037 B1 (#304), A14 MEASUREMENT ONLY: an opt-in side report of Roslyn's
// dispatch facts for every relevant call, keyed by (caller, site). It is not
// OwnIR, neither engine reads it, and the facts are byte-identical when
// `--dispatch-report` is absent (docs/notes/p037-phase-b1-shadow.md §B N6,
// owner amendment 4).
//
// `dispatch` is `exact` only when the call site binds one method body: a
// static method, a constructor, a non-virtual member, a sealed member or
// type, a struct, or a `base.` call. Everything else is `open`.
// `observed_targets` are the first-party bodies THIS COMPILATION declares for
// an open call. For an open-world virtual or interface call they are not the
// runtime set, and the report says so. It computes no summary class and never
// marks a call safe; that is the shadow measurement's job.
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

static class DispatchReport
{
    public static string? Path;
    static readonly List<Dictionary<string, object?>> Rows = new();

    public static void Record(string caller, int line, int column, IMethodSymbol? sym,
                              SyntaxNode site, Compilation compilation)
    {
        if (Path is null)
            return;
        var baseCall = site is InvocationExpressionSyntax
        {
            Expression: MemberAccessExpressionSyntax { Expression: BaseExpressionSyntax }
        };
        var exact = sym is not null
            && (sym.IsStatic || sym.MethodKind == MethodKind.Constructor || baseCall
                || sym.IsSealed || sym.ContainingType.IsSealed || sym.ContainingType.IsValueType
                || (!sym.IsVirtual && !sym.IsAbstract && !sym.IsOverride
                    && sym.ContainingType.TypeKind != TypeKind.Interface));
        Rows.Add(new()
        {
            ["caller"] = caller,
            ["site"] = new Dictionary<string, object?> { ["line"] = line, ["column"] = column },
            ["callee"] = sym is null ? null : Key(sym),
            ["dispatch"] = exact ? "exact" : "open",
            ["observed_targets"] = exact || sym is null ? new List<string>() : Observed(sym, compilation),
        });
    }

    static string Key(IMethodSymbol m) => $"{m.ContainingType.ToDisplayString()}.{m.Name}";

    // The first-party bodies an open call to `sym` can reach in this
    // compilation: `sym` itself, its overrides, its interface implementations.
    static List<string> Observed(IMethodSymbol sym, Compilation compilation)
    {
        var target = (sym.ReducedFrom ?? sym).OriginalDefinition;
        bool Same(IMethodSymbol? a, IMethodSymbol? b) =>
            a is not null && b is not null
            && SymbolEqualityComparer.Default.Equals(a.OriginalDefinition, b.OriginalDefinition);
        var found = new SortedSet<string>(StringComparer.Ordinal);
        var types = compilation.GetSymbolsWithName(_ => true, SymbolFilter.Type).OfType<INamedTypeSymbol>();
        foreach (var t in types)
        {
            var implemented = t.AllInterfaces
                .SelectMany(i => i.GetMembers(target.Name).OfType<IMethodSymbol>())
                .Where(im => Same(im, target))
                .Select(im => t.FindImplementationForInterfaceMember(im) as IMethodSymbol)
                .ToList();
            foreach (var m in t.GetMembers().OfType<IMethodSymbol>())
            {
                if (m.IsAbstract || m.DeclaringSyntaxReferences.Length == 0)
                    continue;
                var hit = Same(m, target) || implemented.Any(im => Same(im, m));
                for (var o = m.OverriddenMethod; o is not null && !hit; o = o.OverriddenMethod)
                    hit = Same(o, target);
                if (hit)
                    found.Add(Key(m));
            }
        }
        return found.ToList();
    }

    public static void Write()
    {
        if (Path is null)
            return;
        var doc = new Dictionary<string, object?>
        {
            ["schema"] = "p037-dispatch-side-report/1",
            ["measurement_only"] = true,
            ["observed_targets_are_exhaustive"] = false,
            ["calls"] = Rows,
        };
        File.WriteAllText(Path, JsonSerializer.Serialize(doc, new JsonSerializerOptions { WriteIndented = true }));
    }
}
