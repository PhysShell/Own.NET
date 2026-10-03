// own-typed-builder: the Typed Builder generator (TB-MVP-01).
//
//   own-typed-builder <Entity.cs> -o <Entity.Protocol.cs>
//
// Reads ONE hand-written declaration file and writes the state-protocol surface the
// Own.NET profile analyses (frontend/roslyn/README.md, "State protocols"): one
// [ProtocolToken] ref struct per state, one transition method per declared transition,
// one [ProtocolRegion] entry per state that has an outgoing transition, the checked
// refinement, a strict storage converter for the state, and a staged builder whose
// Build() exists only once every required field was given.
//
// The declaration (matched by NAME, so the domain depends on nothing):
//
//   [TypedProtocol]                       on the entity: a `partial class`
//   [ProtocolState]                       on exactly one property, of an enum declared in
//                                         the same file; its FIRST member is the state
//                                         Build() creates
//   [BuilderRequired]                     on each construction field, in order
//   [Transition("Name", E.From, E.To)]    on a non-public void hook: the business data the
//                                         transition writes. The STATE write is generated,
//                                         so a hook cannot move the entity to a wrong state.
//
// It is a generator, not an analysis: syntax only, no compilation, no semantic model.
// The output is a function of the input's syntax alone — `\n` newlines, UTF-8 without a
// BOM, no timestamp, no version, no path — so two runs are byte-identical. The file is
// meant to be COMMITTED and is deliberately not named `*.g.cs`: the extractor's scan
// skips those, and the profile admits a protocol only when it is in the scan as source.
//
// Exit codes: 0 written; 2 the declaration is refused (one line per defect on stderr);
// 64 usage.

using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

if (args.Length != 3 || args[1] != "-o")
{
    Console.Error.WriteLine("usage: own-typed-builder <Entity.cs> -o <Entity.Protocol.cs>");
    return 64;
}

var input = args[0];
var text = File.ReadAllText(input).Replace("\r\n", "\n");
var tree = CSharpSyntaxTree.ParseText(text, path: input);
var errors = tree.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
var problems = new List<string>();
foreach (var e in errors)
    problems.Add($"the declaration does not parse: {e.GetMessage()} (line {e.Location.GetLineSpan().StartLinePosition.Line + 1})");

Model? model = problems.Count == 0 ? Model.Read(tree.GetRoot(), Path.GetFileName(input), problems) : null;
if (model is null || problems.Count > 0)
{
    foreach (var p in problems)
        Console.Error.WriteLine($"own-typed-builder: {Path.GetFileName(input)}: {p}");
    return 2;
}

var output = Emit.Render(model);
File.WriteAllBytes(args[2], new UTF8Encoding(encoderShouldEmitUTF8Identifier: false).GetBytes(output));
return 0;

/// One transition as declared: `[Transition(Name, From, To)]` on `Hook(Parameters)`.
sealed record Transition(string Name, string From, string To, string Hook, IReadOnlyList<(string Type, string Name)> Parameters);

/// One `[BuilderRequired]` construction field.
sealed record Field(string Name, string Type, bool NullCheck);

sealed record Model(
    string Source,
    string? Namespace,
    string Entity,
    string IdType,
    string StateProperty,
    string StateEnum,
    IReadOnlyList<string> States,
    IReadOnlyList<Field> Fields,
    IReadOnlyList<Transition> Transitions)
{
    static bool Named(AttributeSyntax a, string name)
    {
        var n = a.Name switch
        {
            QualifiedNameSyntax q => q.Right.Identifier.Text,
            AliasQualifiedNameSyntax q => q.Name.Identifier.Text,
            SimpleNameSyntax s => s.Identifier.Text,
            _ => a.Name.ToString(),
        };
        return n == name || n == name + "Attribute";
    }

    static IEnumerable<AttributeSyntax> Attrs(MemberDeclarationSyntax m) =>
        m.AttributeLists.SelectMany(l => l.Attributes);

    static readonly HashSet<string> ValueKeywords = new(StringComparer.Ordinal)
    {
        "bool", "byte", "sbyte", "short", "ushort", "int", "uint", "long", "ulong",
        "decimal", "double", "float", "char",
    };

    public static Model? Read(SyntaxNode root, string source, List<string> problems)
    {
        var entities = root.DescendantNodes().OfType<ClassDeclarationSyntax>()
            .Where(c => Attrs(c).Any(a => Named(a, "TypedProtocol"))).ToList();
        if (entities.Count != 1)
        {
            problems.Add($"expected exactly one [TypedProtocol] class, found {entities.Count}");
            return null;
        }
        var entity = entities[0];
        if (!entity.Modifiers.Any(SyntaxKind.PartialKeyword))
            problems.Add($"'{entity.Identifier.Text}' must be a partial class: the generated half is the other part");
        if (entity.TypeParameterList is not null || entity.Parent is TypeDeclarationSyntax)
            problems.Add($"'{entity.Identifier.Text}' must be a top-level, non-generic class");

        var ns = entity.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().FirstOrDefault()?.Name.ToString();

        var enums = root.DescendantNodes().OfType<EnumDeclarationSyntax>()
            .ToDictionary(e => e.Identifier.Text, e => e.Members.Select(m => m.Identifier.Text).ToList());

        var properties = entity.Members.OfType<PropertyDeclarationSyntax>().ToList();
        var id = properties.FirstOrDefault(p => p.Identifier.Text == "Id");
        if (id is null)
            problems.Add($"'{entity.Identifier.Text}' has no 'Id' property: the tokens and the refusal name the entity by it");

        var stateProps = properties.Where(p => Attrs(p).Any(a => Named(a, "ProtocolState"))).ToList();
        string stateEnum = "", stateProp = "";
        List<string> states = new();
        if (stateProps.Count != 1)
            problems.Add($"expected exactly one [ProtocolState] property, found {stateProps.Count}");
        else
        {
            stateProp = stateProps[0].Identifier.Text;
            stateEnum = stateProps[0].Type.ToString();
            if (!enums.TryGetValue(stateEnum, out states!))
            {
                problems.Add($"the state property '{stateProp}' has type '{stateEnum}', which is not an enum declared in this file");
                states = new();
            }
            else if (states.Count == 0)
                problems.Add($"the state enum '{stateEnum}' has no members");
            else if (states.Distinct(StringComparer.Ordinal).Count() != states.Count)
                problems.Add($"the state enum '{stateEnum}' declares a member twice");
            if (PubliclyWritable(stateProps[0]))
                problems.Add($"the state property '{stateProp}' must not be publicly writable: the tokens are the only way to change it");
        }

        var fields = new List<Field>();
        foreach (var p in properties.Where(p => Attrs(p).Any(a => Named(a, "BuilderRequired"))))
        {
            var type = p.Type.ToString();
            if (type == "string")
                fields.Add(new Field(p.Identifier.Text, type, NullCheck: true));
            else if (ValueKeywords.Contains(type))
                fields.Add(new Field(p.Identifier.Text, type, NullCheck: false));
            else
                problems.Add($"[BuilderRequired] '{p.Identifier.Text}' has type '{type}': only string and the built-in value types are supported");
            if (p.Identifier.Text == stateProp)
                problems.Add($"[BuilderRequired] '{p.Identifier.Text}' is the state: Build() sets it");
        }

        var transitions = new List<Transition>();
        foreach (var m in entity.Members.OfType<MethodDeclarationSyntax>())
            foreach (var a in Attrs(m).Where(a => Named(a, "Transition")))
            {
                var where = $"[Transition] on '{m.Identifier.Text}'";
                var argsList = a.ArgumentList?.Arguments ?? default;
                if (argsList.Count != 3 || argsList.Any(x => x.NameEquals is not null || x.NameColon is not null))
                {
                    problems.Add($"{where}: expected (\"Name\", {stateEnum}.From, {stateEnum}.To)");
                    continue;
                }
                if (argsList[0].Expression is not LiteralExpressionSyntax lit || !lit.IsKind(SyntaxKind.StringLiteralExpression)
                    || !SyntaxFacts.IsValidIdentifier(lit.Token.ValueText))
                {
                    problems.Add($"{where}: the name must be a string literal that is a C# identifier");
                    continue;
                }
                string? State(ExpressionSyntax e)
                {
                    if (e is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } ma
                        && owner.Identifier.Text == stateEnum && states.Contains(ma.Name.Identifier.Text))
                        return ma.Name.Identifier.Text;
                    problems.Add($"{where}: '{e}' is not a member of the state enum '{stateEnum}'");
                    return null;
                }
                var from = State(argsList[1].Expression);
                var to = State(argsList[2].Expression);
                if (m.Modifiers.Any(SyntaxKind.PublicKeyword))
                    problems.Add($"{where}: the hook must not be public: a public method writing protocol data is a transition nobody declared");
                if (m.Modifiers.Any(SyntaxKind.StaticKeyword) || m.TypeParameterList is not null
                    || m.ReturnType.ToString() != "void" || m.Body is null && m.ExpressionBody is null)
                    problems.Add($"{where}: the hook must be a non-generic instance method returning void, with a body");
                var ps = new List<(string, string)>();
                foreach (var p in m.ParameterList.Parameters)
                {
                    if (p.Modifiers.Count > 0 || p.Default is not null || p.Type is null)
                        problems.Add($"{where}: parameter '{p.Identifier.Text}' must be a plain by-value parameter with no default");
                    ps.Add((p.Type?.ToString() ?? "?", p.Identifier.Text));
                }
                if (from is not null && to is not null)
                    transitions.Add(new Transition(lit.Token.ValueText, from, to, m.Identifier.Text, ps));
            }
        if (transitions.Count == 0)
            problems.Add("no [Transition] is declared");
        foreach (var dup in transitions.GroupBy(t => t.Name).Where(g => g.Count() > 1))
            problems.Add($"the transition name '{dup.Key}' is declared {dup.Count()} times");
        foreach (var t in transitions)
            if (t.Name == "Id")
                problems.Add("a transition may not be named 'Id': the tokens expose the entity's Id");

        return new Model(source, ns, entity.Identifier.Text, id?.Type.ToString() ?? "int", stateProp, stateEnum,
                         states, fields, transitions);
    }

    static bool PubliclyWritable(PropertyDeclarationSyntax p)
    {
        if (!p.Modifiers.Any(SyntaxKind.PublicKeyword))
            return false;
        var setter = p.AccessorList?.Accessors.FirstOrDefault(a => a.IsKind(SyntaxKind.SetAccessorDeclaration));
        return setter is not null && setter.Modifiers.Count == 0;
    }
}

static class Emit
{
    public static string Render(Model m)
    {
        var o = new StringBuilder();
        void L(string line = "") => o.Append(line).Append('\n');
        string Token(string state) => state + m.Entity;
        var outgoing = m.States.Where(s => m.Transitions.Any(t => t.From == s)).ToList();
        var e = m.Entity;
        var lower = char.ToLowerInvariant(e[0]) + e[1..];
        var invalid = $"Invalid{e}StateException";
        var corrupt = $"Corrupt{e}StateException";
        var initial = m.States[0];

        L($"// Generated by Own.TypedBuilder from {m.Source}. Do not edit: change {m.Source} and regenerate.");
        L("//");
        L("// The state protocol of " + e + ": one [ProtocolToken] per state, one transition per");
        L("// [Transition], one [ProtocolRegion] per state with a way out, the checked refinement,");
        L("// the strict storage of the state, and the staged builder. Own.NET analyses this file as");
        L("// source: it is the protocol's trusted definition surface.");
        L();
        L("using System;");
        L();
        if (m.Namespace is not null)
        {
            L($"namespace {m.Namespace};");
            L();
        }

        // ---- the entity's generated half --------------------------------------------------
        L($"partial class {e}");
        L("{");
        foreach (var t in m.Transitions)
        {
            var ps = string.Join(", ", t.Parameters.Select(p => $"{p.Type} {p.Name}"));
            var args = string.Join(", ", t.Parameters.Select(p => p.Name));
            L($"    // {t.From} -> {t.Name} -> {t.To}");
            L($"    internal void Apply{t.Name}({ps})");
            L("    {");
            L($"        {t.Hook}({args});");
            L($"        {m.StateProperty} = {m.StateEnum}.{t.To};");
            L("    }");
            L();
        }
        // the first step is the innermost one (see EmitBuilder)
        var first = string.Join(".", m.Fields.Select(f => f.Name + "Step").Reverse().Prepend($"{initial}Builder"));
        L($"    /// Starts a new {e} in its initial state, {initial}. Build() exists only once every");
        L("    /// required field was given.");
        L($"    public static {first} Create() => new();");
        L();
        EmitBuilder(m, L, initial);
        L("}");
        L();

        // ---- refusals ---------------------------------------------------------------------
        L($"/// The runtime half of the refinement: the state came from data, so it is checked once,");
        L("/// at the region entry.");
        L($"public sealed class {invalid}({m.IdType} id, {m.StateEnum} actual, {m.StateEnum} required)");
        L($"    : InvalidOperationException($\"{lower} {{id}} is {{actual}}, not {{required}}\")");
        L("{");
        L($"    public {m.IdType} Id {{ get; }} = id;");
        L();
        L($"    public {m.StateEnum} Actual {{ get; }} = actual;");
        L();
        L($"    public {m.StateEnum} Required {{ get; }} = required;");
        L("}");
        L();
        L($"/// A persisted state that is not exactly one of {m.StateEnum}'s names. Never mapped to a");
        L("/// state: no default, no case folding, no number.");
        L($"public sealed class {corrupt}(string raw)");
        L($"    : InvalidOperationException($\"the persisted {lower} state '{{raw}}' is not {Article(m.StateEnum)} {m.StateEnum}\")");
        L("{");
        L("    public string Raw { get; } = raw;");
        L("}");
        L();

        // ---- strict storage ---------------------------------------------------------------
        L($"/// The one mapping between {m.StateEnum} and its stored text: the exact member name.");
        L($"public static class {m.StateEnum}Storage");
        L("{");
        L($"    public static string ToStore({m.StateEnum} state) => state switch");
        L("    {");
        foreach (var s in m.States)
            L($"        {m.StateEnum}.{s} => \"{s}\",");
        L($"        _ => throw new {corrupt}(state.ToString()),");
        L("    };");
        L();
        L($"    public static {m.StateEnum} FromStore(string raw) =>");
        L($"        TryFromStore(raw, out var state) ? state : throw new {corrupt}(raw);");
        L();
        L($"    public static bool TryFromStore(string? raw, out {m.StateEnum} state)");
        L("    {");
        L("        switch (raw)");
        L("        {");
        foreach (var s in m.States)
        {
            L($"            case \"{s}\":");
            L($"                state = {m.StateEnum}.{s};");
            L("                return true;");
        }
        L("            default:");
        L("                state = default;");
        L("                return false;");
        L("        }");
        L("    }");
        L("}");
        L();

        // ---- tokens -----------------------------------------------------------------------
        foreach (var s in m.States)
        {
            var exits = m.Transitions.Where(t => t.From == s).ToList();
            L(exits.Count == 0
                ? $"/// {e} in state {s}. Terminal: no transition leaves it."
                : $"/// {e} in state {s}. A transition spends this token and hands back the next one.");
            L("[ProtocolToken]");
            L($"public readonly ref struct {Token(s)}");
            L("{");
            L($"    private readonly {e} _{lower};");
            L();
            L($"    internal {Token(s)}({e} {lower}) => _{lower} = {lower};");
            L();
            L($"    public {m.IdType} Id => _{lower}.Id;");
            foreach (var t in exits)
            {
                var ps = string.Join(", ", t.Parameters.Select(p => $"{p.Type} {p.Name}"));
                var args = string.Join(", ", t.Parameters.Select(p => p.Name));
                L();
                L($"    public {Token(t.To)} {t.Name}({ps})");
                L("    {");
                L($"        _{lower}.Apply{t.Name}({args});");
                L($"        return new {Token(t.To)}(_{lower});");
                L("    }");
            }
            L("}");
            L();
        }

        // ---- regions ----------------------------------------------------------------------
        foreach (var s in outgoing)
            L($"public delegate void {s}Region({Token(s)} {char.ToLowerInvariant(s[0]) + s[1..]});");
        L();
        L($"/// The checked refinement: {Article(e)} {e} whose state is only known at run time becomes a token");
        L("/// inside the callback, or the call throws and no token exists. A state no transition");
        L("/// leaves has no region: its token could never be spent.");
        L($"public static class {e}Protocol");
        L("{");
        for (var i = 0; i < outgoing.Count; i++)
        {
            var s = outgoing[i];
            if (i > 0)
                L();
            L("    [ProtocolRegion]");
            L($"    public static void With{s}({e} {lower}, {s}Region body)");
            L("    {");
            L($"        ArgumentNullException.ThrowIfNull({lower});");
            L("        ArgumentNullException.ThrowIfNull(body);");
            L($"        if ({lower}.{m.StateProperty} != {m.StateEnum}.{s})");
            L($"            throw new {invalid}({lower}.Id, {lower}.{m.StateProperty}, {m.StateEnum}.{s});");
            L($"        body(new {Token(s)}({lower}));");
            L("    }");
        }
        L("}");
        return o.ToString();
    }

    static string Article(string word) => "AEIOUaeiou".Contains(word[0]) ? "an" : "a";

    // The staged builder, nested inside the entity so it can reach its private constructor
    // and setters. The steps nest INWARD from the finished builder: each step constructs the
    // type that contains it through a private constructor, so the only way to a Build() is
    // through every step, in order.
    static void EmitBuilder(Model m, Action<string> L, string initial)
    {
        var e = m.Entity;
        var depth = 1;
        string Pad() => new(' ', depth * 4);
        string Lower(string s) => char.ToLowerInvariant(s[0]) + s[1..];

        L($"{Pad()}public sealed class {initial}Builder");
        L($"{Pad()}{{");
        depth++;
        foreach (var f in m.Fields)
            L($"{Pad()}private readonly {f.Type} _{Lower(f.Name)};");
        if (m.Fields.Count > 0)
            L("");
        var all = string.Join(", ", m.Fields.Select(f => $"{f.Type} {Lower(f.Name)}"));
        L($"{Pad()}{(m.Fields.Count == 0 ? "internal" : "private")} {initial}Builder({all})");
        L($"{Pad()}{{");
        foreach (var f in m.Fields)
            L($"{Pad()}    _{Lower(f.Name)} = {Lower(f.Name)};");
        L($"{Pad()}}}");
        L("");
        var init = string.Join(", ", m.Fields.Select(f => $"{f.Name} = _{Lower(f.Name)}")
            .Append($"{m.StateProperty} = {m.StateEnum}.{initial}"));
        L($"{Pad()}public {e} Build() => new() {{ {init} }};");

        // step k holds fields [0, k) and takes field k; the steps nest so that step k sits
        // inside step k+1 (the last step inside the builder).
        var opened = 0;
        for (var k = m.Fields.Count - 1; k >= 0; k--)
        {
            var f = m.Fields[k];
            var held = m.Fields.Take(k).ToList();
            var next = k == m.Fields.Count - 1 ? $"{initial}Builder" : $"{m.Fields[k + 1].Name}Step";
            L("");
            L($"{Pad()}public sealed class {f.Name}Step");
            L($"{Pad()}{{");
            depth++;
            foreach (var h in held)
                L($"{Pad()}private readonly {h.Type} _{Lower(h.Name)};");
            if (held.Count > 0)
                L("");
            var ctor = string.Join(", ", held.Select(h => $"{h.Type} {Lower(h.Name)}"));
            // the first step is where Create() starts: it holds nothing, so making one by
            // hand gains nothing
            L($"{Pad()}{(k == 0 ? "internal" : "private")} {f.Name}Step({ctor})");
            L($"{Pad()}{{");
            foreach (var h in held)
                L($"{Pad()}    _{Lower(h.Name)} = {Lower(h.Name)};");
            L($"{Pad()}}}");
            L("");
            var pass = string.Join(", ", held.Select(h => $"_{Lower(h.Name)}").Append(Lower(f.Name)));
            L($"{Pad()}public {next} {f.Name}({f.Type} {Lower(f.Name)})");
            L($"{Pad()}{{");
            if (f.NullCheck)
                L($"{Pad()}    ArgumentNullException.ThrowIfNull({Lower(f.Name)});");
            L($"{Pad()}    return new {next}({pass});");
            L($"{Pad()}}}");
            opened++;
        }
        for (var i = 0; i < opened; i++)
        {
            depth--;
            L($"{Pad()}}}");
        }
        depth--;
        L($"{Pad()}}}");
    }
}
