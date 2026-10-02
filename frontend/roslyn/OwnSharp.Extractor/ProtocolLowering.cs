using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

// State protocols (P-010, pillar 9): lowering a C# state-protocol surface into OwnIR `move` /
// `borrow_mut` (OwnIR v1, spec/OwnIR.md §5.3; the bridge's side is spec/Bridge.md BR-L12/L13).
//
// The surface is recognised by two attributes, matched by NAME (so an API carries no
// dependency on this project):
//
//   [ProtocolRegion]  a method `(entity, callback)`: the callback's body is an exclusive
//                     region over the entity, and its one parameter is the state token;
//   [ProtocolToken]   a ref struct: every instance METHOD is a transition that consumes the
//                     token (and borrows the entity for the call); a PROPERTY is a read.
//
// This is a LOWERING, not an analysis. It reads the syntax of one method at a time and looks
// symbols up; it never tracks state across statements, never follows aliases, and never
// decides whether a program is right. Everything it emits is checked by the core:
//
//   region entry            acquire <entity>; borrow_mut <entity> as <binding> { acquire <token>; ... }; release <entity>
//   token.Transition()      call <Type.Method> [<token>, <binding>]      (+ acquire <result>)
//   var copy = token        move <copy> <- <token>
//   token.Property          use <token>
//   a value of the entity's TYPE mentioned inside the region
//                           use <entity>                                  (exclusivity by type)
//
// WHAT IS CLAIMED. The profile protects the local C# capabilities and aliases of an entity
// that already exists: inside a region nothing but its token changes it, and a token is spent
// once. It does not protect the persisted row from other ways of changing it — a set-based
// update, a change-tracker metadata write, raw SQL, another process. Those belong to
// concurrency tokens, constraints and transactions.
//
// THE TRUST BOUNDARY. The types that DECLARE a protocol (the tokens, the type holding a
// region entry) are the trusted definition surface: token construction, region entry and
// transition plumbing live there, and their bodies are not lowered. Everything else is
// consumer code — the analysed surface. A type is one or the other, never both: consumer code
// inside a declaring type would simply be absent from the analysed program, so a region
// opened there is refused rather than guessed about.
//
// OUTSIDE a region nothing protocol-relevant is live, and a region lowers to a self-contained
// unit (the entity is acquired and released around it). So whatever surrounds a region —
// `try`/`catch`, `using`, a loop, a branch, `await` — is walked through and ignored.
//
// INSIDE a region the rule is the opposite: default-deny. The region is exclusive, and code
// the lowering cannot read is code that may reach the entity some other way. So the body may
// contain transitions, token reads, copies of a token, `if`, locals, and expressions made of
// literals, locals, fields and built-in operators — and nothing else. Every other construct is
// REFUSED (the run exits 2 and writes no facts), most importantly anything that runs code with
// no stated contract: a call, a constructor, a property getter or setter, an indexer, a
// user-defined operator or conversion. The one exception is a construct that visibly touches
// the entity: that is lowered as a use of it, and the core rejects it with a verdict rather
// than a refusal. When effect summaries (P-036/P-037) can prove a call harmless, this rule is
// the one to relax; until then an unprovable call is not analysed as safe.
//
// Also refused, anywhere: a token with no lowerable origin (`default`, `new`), a token
// parameter or return type, a token type that is not a ref struct, a region whose body is not
// a lambda written in place, a region over something that is not a local or a parameter, and
// a region entry in a position the statement walk does not reach. Those keep the shapes the
// core cannot check (a token minted outside a region, two tokens for one entity, a token spent
// against another entity) from having any spelling that lowers.
//
// And refused across the whole scan, region or no region: a protocol that is not ADMITTED (a
// public mutator of the state its transitions own), and reaching past an admitted one (see
// `CheckBoundary`). A refusal is the whole scan's: a recognised protocol construct that
// cannot be lowered safely is not reported next to findings that would read as "the rest is
// checked".
//
// BINDING. The scan is not an MSBuild compilation: it does not read `obj/`, so the usings a
// project gets implicitly are not there. A region whose entity does not bind is refused, not
// skipped; a project that relies on implicit usings writes them out (or qualifies the API).
internal static class ProtocolLowering
{
    internal sealed record Result(List<object> Functions, List<string> Refusals);

    private sealed class Refused(string message) : Exception(message);

    private sealed class Region
    {
        public required ISymbol Entity { get; init; }
        public required ITypeSymbol? EntityType { get; init; }
        public required string Owner { get; init; }
        public required string Binding { get; init; }
    }

    private sealed class Ctx
    {
        public required SemanticModel Model { get; init; }
        public required string File { get; init; }
        public required Dictionary<SyntaxTree, string> Files { get; init; }
        public required SortedDictionary<string, object> Contracts { get; init; }
        public required ISet<string> LegacyNames { get; init; }
        public List<Region> Regions { get; } = new();
        public Dictionary<ISymbol, (string Name, Region Region)> Tokens { get; } =
            new(SymbolEqualityComparer.Default);
        public HashSet<SyntaxNode> LoweredEntries { get; } = new();
        public int Counter;
        /// How many times the scan has lowered a mention of a borrowed entity. A construct
        /// that runs unknown code is refused UNLESS it moved this counter: then the core
        /// already has a use to reject, and a verdict is better than a refusal.
        public int EntityTouches;
    }

    public static Result Lower(Compilation compilation,
                               IReadOnlyList<(string file, SyntaxTree tree)> parsed,
                               ISet<string> legacyNames)
    {
        var functions = new List<object>();
        var refusals = new List<string>();
        var contracts = new SortedDictionary<string, object>(StringComparer.Ordinal);
        var files = new Dictionary<SyntaxTree, string>();
        foreach (var (file, tree) in parsed)
            files[tree] = file;

        CheckBoundary(compilation, parsed, files, refusals);

        foreach (var (file, tree) in parsed)
        {
            var model = compilation.GetSemanticModel(tree);
            var root = tree.GetRoot();
            var loweredEntries = new HashSet<SyntaxNode>();

            foreach (var method in root.DescendantNodes().OfType<BaseMethodDeclarationSyntax>())
            {
                if (model.GetDeclaredSymbol(method) is not IMethodSymbol msym)
                    continue;
                if (IsApiType(msym.ContainingType))
                {
                    // The trust boundary (see the header): a declaring type's bodies
                    // implement the protocol and are not lowered. So a region OPENED in one
                    // of them — a handler written next to the region entry it calls — would
                    // not be a violation the core missed but a program it never saw, and
                    // would read as clean. Trusted is not the same as checked.
                    foreach (var opened in method.DescendantNodes().OfType<InvocationExpressionSyntax>()
                                 .Where(i => IsRegionEntry(MethodOf(model, i))))
                        refusals.Add(At(file, opened,
                            $"a protocol region is opened inside '{msym.ContainingType.Name}', one of the protocol's own types: code there implements the protocol and is not analysed, so this region would read as clean. Use the protocol from outside the types that declare it"));
                    continue;
                }
                try
                {
                    foreach (var p in msym.Parameters)
                        if (IsToken(p.Type))
                            throw new Refused(At(file, method,
                                $"protocol token parameter '{p.Name}': a token does not cross a method boundary in this profile"));
                    if (IsToken(msym.ReturnType))
                        throw new Refused(At(file, method,
                            "a method returns a protocol token: a token does not cross a method boundary in this profile"));

                    SyntaxNode? body = (SyntaxNode?)method.Body ?? method.ExpressionBody;
                    if (body is null)
                        continue;
                    var entries = body.DescendantNodes().OfType<InvocationExpressionSyntax>()
                        .Where(i => IsRegionEntry(MethodOf(model, i))).ToList();
                    var tokenLocals = body.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                        .Where(v => model.GetDeclaredSymbol(v) is ILocalSymbol l && IsToken(l.Type))
                        .ToList();
                    if (entries.Count == 0 && tokenLocals.Count == 0)
                        continue;
                    if (method.Body is null)
                        throw new Refused(At(file, method,
                            "a method that opens a protocol region needs a block body"));

                    // A method the IDisposable flow pass ALSO has a record for keeps both: the
                    // two track disjoint resources (a disposable captured by the callback is
                    // already an escape there), so they are two independent readings of one
                    // method. They cannot share a name — two records under one name read as
                    // an overload — so this one says which reading it is.
                    var name = $"{msym.ContainingType.ToDisplayString()}.{msym.Name}";
                    if (legacyNames.Contains(name))
                        name += "$protocol";

                    var ctx = new Ctx
                    {
                        Model = model, File = file, Files = files, Contracts = contracts,
                        LegacyNames = legacyNames,
                    };
                    var ops = new List<object>();
                    foreach (var st in method.Body.Statements)
                        LowerOutside(ctx, st, ops);

                    // Fail closed on anything the statement walk did not reach: a region entry
                    // or a token local it never saw would otherwise vanish from the facts.
                    foreach (var e in entries)
                        if (!ctx.LoweredEntries.Contains(e))
                            throw new Refused(At(file, e,
                                "a protocol region entry in a position the lowering does not model (it must be a statement of its own, outside any lambda or local function)"));
                    foreach (var v in tokenLocals)
                        if (model.GetDeclaredSymbol(v) is ILocalSymbol l && !ctx.Tokens.ContainsKey(l))
                            throw new Refused(At(file, v,
                                $"protocol token '{l.Name}' is declared outside a protocol region"));
                    loweredEntries.UnionWith(ctx.LoweredEntries);

                    if (ops.Count > 0)
                        functions.Add(new Dictionary<string, object?>
                        {
                            ["name"] = name, ["file"] = file, ["body"] = ops,
                        });
                }
                catch (Refused r)
                {
                    refusals.Add(r.Message);
                }
            }

            // A region entry outside any method body (an accessor, a field initializer, a
            // top-level statement) is not modelled either.
            foreach (var inv in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (!IsRegionEntry(MethodOf(model, inv)) || loweredEntries.Contains(inv))
                    continue;
                if (inv.Ancestors().OfType<BaseMethodDeclarationSyntax>().Any())
                    continue;   // inside a method: lowered above, or already refused there
                refusals.Add(At(file, inv,
                    "a protocol region entry outside a method body is not modelled"));
            }
        }

        functions.AddRange(contracts.Values);
        return new Result(functions, refusals);
    }

    // ---- the protocol boundary -------------------------------------------------------------

    /// What the region rules REST on: a token exists only because a region entry or a
    /// transition handed it out, and the protocol's state changes only through a token. With
    /// the protocol in its own assembly the C# compiler holds most of that through `internal`.
    /// In ONE assembly — a minimal API with its domain beside the handlers — `internal` holds
    /// nothing: `new ApprovedOrder(order).Ship()` and `order.MarkShipped()` compile in a method
    /// with no region at all. A second assembly is not something this profile gets to demand,
    /// so the scan holds the boundary itself, in two halves.
    ///
    /// ADMISSION — a property of the declarations. The protocol-owned state is what the
    /// protocol's own types write on the entity, directly or through the entity methods they
    /// call. An entity is admitted only if nothing PUBLIC on it writes that state: a public
    /// setter or field, or a public method that reaches such a write. A public mutator is a
    /// transition nobody declared, so the declaration is refused instead of the bypass being
    /// allowed in silence. A write inside an object initializer is creation, not mutation.
    ///
    /// USE — a property of every other line of the scan. Outside the protocol's own types
    /// three OPERATIONS are refused: creating a token value (`new`, `default`); invoking a
    /// non-public method or constructor of the protocol or of the entity (a method group
    /// counts — the delegate is the call); writing a field, property or event of either that
    /// is not publicly writable. A MENTION is not an operation: `nameof`, `typeof`, a read.
    ///
    /// The entity types are read off the region entries' first parameter, with their base
    /// classes (inherited state is state). Nothing is annotated. Both halves read bodies, so
    /// the protocol and its entity must be in the scan as SOURCE: one that arrives only as a
    /// compiled reference cannot be admitted, and a region over it is refused. The inside of a
    /// region is left to the region's own scan, which already answers for every node there.
    private static void CheckBoundary(Compilation compilation,
                                      IReadOnlyList<(string file, SyntaxTree tree)> parsed,
                                      Dictionary<SyntaxTree, string> files,
                                      List<string> refusals)
    {
        var api = new HashSet<INamedTypeSymbol>(SymbolEqualityComparer.Default);
        var entities = new HashSet<INamedTypeSymbol>(SymbolEqualityComparer.Default);
        var regionBodies = new HashSet<SyntaxNode>();

        void AddToken(ITypeSymbol? type)
        {
            if (type?.OriginalDefinition is not INamedTypeSymbol named || !IsToken(named)
                || !api.Add(named))
                return;
            foreach (var m in named.GetMembers().OfType<IMethodSymbol>())
                AddToken(m.ReturnType);   // what a transition hands back is a token too
        }

        // Returns the protocol declarations this entry needs that are NOT in the scan as source.
        List<string> AddEntry(IMethodSymbol entry)
        {
            entry = (entry.ReducedFrom ?? entry).OriginalDefinition;
            var compiled = new List<string>();
            void NeedSource(ISymbol symbol)
            {
                if (symbol.DeclaringSyntaxReferences.IsEmpty)
                    compiled.Add(symbol.Name);
            }
            api.Add(entry.ContainingType.OriginalDefinition);
            NeedSource(entry);
            // the entity and what it inherits its state from
            var first = true;
            for (var entity = entry.Parameters.Length > 0
                     ? entry.Parameters[0].Type.OriginalDefinition as INamedTypeSymbol : null;
                 entity is { TypeKind: not TypeKind.Error, SpecialType: not SpecialType.System_Object };
                 entity = entity.BaseType?.OriginalDefinition, first = false)
            {
                entities.Add(entity);
                if (first)
                    NeedSource(entity);
            }
            foreach (var p in entry.Parameters)
                if (p.Type is INamedTypeSymbol { DelegateInvokeMethod: { } invoke })
                    foreach (var q in invoke.Parameters)
                    {
                        AddToken(q.Type);
                        if (IsToken(q.Type))
                            NeedSource(q.Type.OriginalDefinition);
                    }
            return compiled;
        }

        foreach (var (file, tree) in parsed)
        {
            var model = compilation.GetSemanticModel(tree);
            foreach (var node in tree.GetRoot().DescendantNodes())
            {
                switch (node)
                {
                    case BaseTypeDeclarationSyntax type
                        when model.GetDeclaredSymbol(type) is INamedTypeSymbol declared:
                        AddToken(declared);
                        foreach (var m in declared.GetMembers().OfType<IMethodSymbol>())
                            if (IsRegionEntry(m))
                                AddEntry(m);
                        break;
                    case InvocationExpressionSyntax inv
                        when MethodOf(model, inv) is { } method && IsRegionEntry(method):
                        var compiled = AddEntry(method);
                        if (compiled.Count > 0)
                            refusals.Add(At(file, inv,
                                $"the state protocol behind this region is not in the scan as source ({string.Join(", ", compiled.Distinct())} come from a compiled reference): its admission cannot be checked, so the region is not analysed"));
                        foreach (var arg in inv.ArgumentList.Arguments)
                            if (Unparen(arg.Expression) is AnonymousFunctionExpressionSyntax body)
                                regionBodies.Add(body);
                        break;
                }
            }
        }
        if (api.Count == 0)
            return;

        bool InFamily(ISymbol? member) =>
            member?.ContainingType?.OriginalDefinition is { } owner && entities.Contains(owner);

        string Where(ISymbol symbol)
        {
            var reference = symbol.DeclaringSyntaxReferences.FirstOrDefault();
            return reference is not null && files.TryGetValue(reference.SyntaxTree, out var f)
                ? $"{f}:{Line(reference.GetSyntax())}"
                : "?:0";
        }

        // ---- admission ---------------------------------------------------------------------

        // What one body does to the entity family: the state it writes and the family methods
        // it reaches. Read from syntax, memoized, never across an object initializer.
        var effects = new Dictionary<IMethodSymbol, (HashSet<ISymbol> Writes, HashSet<IMethodSymbol> Calls)>(
            SymbolEqualityComparer.Default);
        (HashSet<ISymbol> Writes, HashSet<IMethodSymbol> Calls) Effects(IMethodSymbol method)
        {
            if (effects.TryGetValue(method, out var known))
                return known;
            var writes = new HashSet<ISymbol>(SymbolEqualityComparer.Default);
            var calls = new HashSet<IMethodSymbol>(SymbolEqualityComparer.Default);
            effects[method] = (writes, calls);
            foreach (var reference in method.DeclaringSyntaxReferences)
            {
                var body = reference.GetSyntax();
                var model = compilation.GetSemanticModel(body.SyntaxTree);
                foreach (var name in body.DescendantNodesAndSelf().OfType<SimpleNameSyntax>())
                {
                    if (InNameof(model, name))
                        continue;
                    var symbol = Bound(model.GetSymbolInfo(name))?.OriginalDefinition;
                    if (!InFamily(symbol))
                        continue;
                    switch (symbol)
                    {
                        case IMethodSymbol { MethodKind: not MethodKind.Constructor } callee:
                            calls.Add((callee.ReducedFrom ?? callee).OriginalDefinition);
                            break;
                        case IFieldSymbol or IPropertySymbol or IEventSymbol
                            when IsWrite(name) && !InObjectInitializer(name):
                            writes.Add(symbol);
                            if (symbol is IPropertySymbol { SetMethod: { } setter })
                                calls.Add(setter.OriginalDefinition);   // a setter with a body
                            break;
                    }
                }
            }
            return (writes, calls);
        }

        // Everything `root` writes, through the family methods it reaches.
        HashSet<ISymbol> Reach(IMethodSymbol root, List<string>? unreadable = null)
        {
            var all = new HashSet<ISymbol>(SymbolEqualityComparer.Default);
            var seen = new HashSet<IMethodSymbol>(SymbolEqualityComparer.Default);
            var queue = new Queue<IMethodSymbol>();
            queue.Enqueue(root);
            while (queue.Count > 0)
            {
                var method = queue.Dequeue();
                if (!seen.Add(method))
                    continue;
                if (method.DeclaringSyntaxReferences.IsEmpty && !method.IsImplicitlyDeclared)
                    unreadable?.Add($"{method.ContainingType.Name}.{method.Name}");
                var (writes, calls) = Effects(method);
                all.UnionWith(writes);
                foreach (var callee in calls)
                    queue.Enqueue(callee);
            }
            return all;
        }

        var owned = new HashSet<ISymbol>(SymbolEqualityComparer.Default);
        foreach (var type in api)
            foreach (var member in type.GetMembers().OfType<IMethodSymbol>())
            {
                var unreadable = new List<string>();
                owned.UnionWith(Reach(member, unreadable));
                foreach (var name in unreadable.Distinct())
                    refusals.Add($"{Where(member)}: the protocol calls '{name}', whose body is not in the scan: what it does to the entity cannot be read, so the protocol is not admitted");
            }

        string Open(ISymbol member, ISymbol state) =>
            $"{Where(member)}: '{member.ContainingType.Name}.{member.Name}' is public and writes '{state.Name}', state the protocol's transitions own: a public mutator is a transition nobody declared, and every token can be bypassed through it. Make it non-public, or make it a transition";

        foreach (var entity in entities)
            foreach (var member in entity.GetMembers())
                switch (member)
                {
                    case IPropertySymbol property when owned.Contains(property)
                        && property.SetMethod is { DeclaredAccessibility: Accessibility.Public, IsInitOnly: false }:
                        refusals.Add(Open(property, property));
                        break;
                    case IFieldSymbol { DeclaredAccessibility: Accessibility.Public, IsReadOnly: false, IsConst: false } field
                        when owned.Contains(field):
                        refusals.Add(Open(field, field));
                        break;
                    case IMethodSymbol { DeclaredAccessibility: Accessibility.Public } method
                        when method.MethodKind is MethodKind.Ordinary or MethodKind.PropertySet
                            && !method.IsInitOnly
                            && Reach(method).FirstOrDefault(owned.Contains) is { } state:
                        // an auto-property's setter is the property case above
                        if (method.AssociatedSymbol is null || !owned.Contains(method.AssociatedSymbol))
                            refusals.Add(Open(method.AssociatedSymbol ?? method, state));
                        break;
                }

        // ---- use ---------------------------------------------------------------------------

        // the names worth resolving: cheap, and exact enough to keep a large scan large
        var guarded = new HashSet<string>(StringComparer.Ordinal);
        foreach (var type in api.Concat(entities))
            foreach (var member in type.GetMembers())
                if (member.DeclaredAccessibility != Accessibility.Public
                    || member is IPropertySymbol { SetMethod.DeclaredAccessibility: not Accessibility.Public })
                    guarded.Add(member.Name);

        foreach (var (file, tree) in parsed)
        {
            var model = compilation.GetSemanticModel(tree);
            foreach (var node in tree.GetRoot().DescendantNodes())
            {
                var creates = node is BaseObjectCreationExpressionSyntax or DefaultExpressionSyntax
                    || node.IsKind(SyntaxKind.DefaultLiteralExpression);
                var names = node is SimpleNameSyntax name && guarded.Contains(name.Identifier.Text);
                if (!creates && !names)
                    continue;
                if (node.Ancestors().Any(regionBodies.Contains))
                    continue;   // the region's own scan answers for this node

                var site = Enclosing(model, node);
                bool Within(HashSet<INamedTypeSymbol> types) => site.Any(types.Contains);
                // may code at this site reach a non-public member of `owner`?
                bool Outside(INamedTypeSymbol? owner)
                {
                    owner = owner?.OriginalDefinition;
                    if (owner is null)
                        return false;
                    if (api.Contains(owner))
                        return !Within(api);
                    return entities.Contains(owner) && !Within(api) && !Within(entities);
                }

                if (creates)
                {
                    var info = model.GetTypeInfo(node);
                    var made = (node.IsKind(SyntaxKind.DefaultLiteralExpression)
                        ? info.ConvertedType : info.Type ?? info.ConvertedType)?.OriginalDefinition;
                    if (IsToken(made) && !Within(api))
                        refusals.Add(At(file, node,
                            $"a protocol token '{made!.Name}' is created outside the protocol's own types: a token comes only from a region entry or a transition"));
                    else if (node is BaseObjectCreationExpressionSyntax
                             && Bound(model.GetSymbolInfo(node)) is IMethodSymbol
                                 { DeclaredAccessibility: not Accessibility.Public } ctor
                             && Outside(ctor.ContainingType))
                        refusals.Add(At(file, node,
                            Sealed(ctor.ContainingType, "the constructor", "it is invoked here")));
                    continue;
                }
                if (InNameof(model, node))
                    continue;   // a mention, not an operation

                var member = Bound(model.GetSymbolInfo(node));
                member = member is IMethodSymbol method
                    ? (method.ReducedFrom ?? method).OriginalDefinition
                    : member?.OriginalDefinition;
                var operation = member switch
                {
                    IMethodSymbol { DeclaredAccessibility: not Accessibility.Public } => "it is called here",
                    IPropertySymbol property when IsWrite(node)
                        && (property.SetMethod?.DeclaredAccessibility ?? property.DeclaredAccessibility)
                            != Accessibility.Public => "it is written here",
                    IFieldSymbol or IEventSymbol
                        when IsWrite(node) && member.DeclaredAccessibility != Accessibility.Public
                        => "it is written here",
                    _ => null,   // a read, or a public member: not this rule's business
                };
                if (operation is not null && Outside(member!.ContainingType))
                    refusals.Add(At(file, node,
                        Sealed(member.ContainingType, $"'{member.Name}'", operation)));
            }
        }

        static string Sealed(INamedTypeSymbol owner, string what, string operation) =>
            $"{what} of '{owner.Name}' is not public and belongs to a state protocol: {operation}, outside the protocol's own types, where it is reachable only through a token (the scan holds the protocol to the boundary a separate assembly would give it)";
    }

    private static ISymbol? Bound(SymbolInfo info) =>
        info.Symbol ?? (info.CandidateSymbols.Length == 1 ? info.CandidateSymbols[0] : null);

    /// The types `node` sits in, innermost first.
    private static List<INamedTypeSymbol> Enclosing(SemanticModel model, SyntaxNode node)
    {
        var chain = new List<INamedTypeSymbol>();
        var symbol = model.GetEnclosingSymbol(node.SpanStart);
        for (var type = symbol as INamedTypeSymbol ?? symbol?.ContainingType;
             type is not null; type = type.ContainingType)
            chain.Add(type.OriginalDefinition);
        return chain;
    }

    /// `nameof(x)` names a symbol and runs nothing.
    private static bool InNameof(SemanticModel model, SyntaxNode node) =>
        node.Ancestors().OfType<InvocationExpressionSyntax>().Any(inv =>
            inv.Expression is IdentifierNameSyntax { Identifier.Text: "nameof" }
            && model.GetConstantValue(inv).HasValue);

    /// The expression a name is the tail of: `a.b.Name` for `Name`, the name itself otherwise.
    private static SyntaxNode Target(SyntaxNode name)
    {
        var target = name;
        if (name.Parent is MemberAccessExpressionSyntax access && access.Name == name)
            target = access;
        while (target.Parent is ParenthesizedExpressionSyntax paren)
            target = paren;
        return target;
    }

    /// Is this name the target of a write: an assignment (an object initializer's member is
    /// one), `++`/`--`, or a `ref`/`out` argument.
    private static bool IsWrite(SyntaxNode name)
    {
        var target = Target(name);
        return target.Parent switch
        {
            AssignmentExpressionSyntax assignment => assignment.Left == target,
            PrefixUnaryExpressionSyntax or PostfixUnaryExpressionSyntax =>
                target.Parent.IsKind(SyntaxKind.PreIncrementExpression)
                || target.Parent.IsKind(SyntaxKind.PreDecrementExpression)
                || target.Parent.IsKind(SyntaxKind.PostIncrementExpression)
                || target.Parent.IsKind(SyntaxKind.PostDecrementExpression),
            ArgumentSyntax argument => !argument.RefKindKeyword.IsKind(SyntaxKind.None)
                && !argument.RefKindKeyword.IsKind(SyntaxKind.InKeyword),
            _ => false,
        };
    }

    /// A member assigned in `new T { Member = ... }` (or `with { ... }`): part of creating the
    /// value, not a change to one that exists.
    private static bool InObjectInitializer(SyntaxNode name) =>
        Target(name).Parent is AssignmentExpressionSyntax
        {
            Parent: InitializerExpressionSyntax initializer
        } && (initializer.IsKind(SyntaxKind.ObjectInitializerExpression)
              || initializer.IsKind(SyntaxKind.WithInitializerExpression));

    // ---- recognition ----------------------------------------------------------------------

    private static bool HasAttribute(ISymbol? symbol, string name) =>
        symbol is not null && symbol.GetAttributes().Any(a =>
            a.AttributeClass?.Name == name || a.AttributeClass?.Name == name + "Attribute");

    private static bool IsToken(ITypeSymbol? type) => HasAttribute(type, "ProtocolToken");

    private static bool IsRegionEntry(IMethodSymbol? method) =>
        method is not null && HasAttribute((method.ReducedFrom ?? method).OriginalDefinition,
                                           "ProtocolRegion");

    private static bool IsApiType(INamedTypeSymbol? type) =>
        type is not null && (IsToken(type)
            || type.GetMembers().OfType<IMethodSymbol>().Any(IsRegionEntry));

    /// The method an invocation names. When overload resolution FAILED (an argument did not
    /// bind — typically a degraded compilation: a missing reference, a missing global using)
    /// the single candidate still says which method was meant, and it is used: a region
    /// entry that does not bind must not silently stop being a region entry. Whatever is
    /// unresolved inside it is then refused by the region's default-deny scan.
    private static IMethodSymbol? MethodOf(SemanticModel model, InvocationExpressionSyntax inv)
    {
        var info = model.GetSymbolInfo(inv);
        if (info.Symbol is IMethodSymbol bound)
            return bound;
        var candidates = info.CandidateSymbols.OfType<IMethodSymbol>().ToList();
        return candidates.Count == 1 ? candidates[0]
            : candidates.FirstOrDefault(c => IsRegionEntry(c) || IsToken(c.ContainingType));
    }

    private static ExpressionSyntax Unparen(ExpressionSyntax e)
    {
        while (e is ParenthesizedExpressionSyntax p)
            e = p.Expression;
        return e;
    }

    private static int Line(SyntaxNode node) =>
        node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    private static string At(string file, SyntaxNode node, string message) =>
        $"{file}:{Line(node)}: {message}";

    private static Refused Refuse(Ctx ctx, SyntaxNode node, string message) =>
        new(At(ctx.File, node, message));

    /// A type whose values carry no user code: formatting or concatenating one runs nothing
    /// the lowering would have to read.
    private static bool IsInert(ITypeSymbol? type) =>
        type is not null && (type.TypeKind == TypeKind.Enum || type.SpecialType is
            SpecialType.System_Boolean or SpecialType.System_Char or SpecialType.System_String
            or SpecialType.System_SByte or SpecialType.System_Byte
            or SpecialType.System_Int16 or SpecialType.System_UInt16
            or SpecialType.System_Int32 or SpecialType.System_UInt32
            or SpecialType.System_Int64 or SpecialType.System_UInt64
            or SpecialType.System_Single or SpecialType.System_Double
            or SpecialType.System_Decimal or SpecialType.System_DateTime);

    // ---- ops ------------------------------------------------------------------------------

    private static Dictionary<string, object?> Acquire(string name, int line) =>
        new() { ["op"] = "acquire", ["var"] = name, ["line"] = line };

    private static Dictionary<string, object?> Release(string name, int line) =>
        new() { ["op"] = "release", ["var"] = name, ["line"] = line };

    private static Dictionary<string, object?> Use(string name, int line) =>
        new() { ["op"] = "use", ["var"] = name, ["line"] = line };

    private static Dictionary<string, object?> Move(string name, string src, int line) =>
        new() { ["op"] = "move", ["var"] = name, ["src"] = src, ["line"] = line };

    private static Dictionary<string, object?> Call(string callee, string[] args, int line) =>
        new() { ["op"] = "call", ["callee"] = callee, ["args"] = args, ["line"] = line };

    private static void Touch(Ctx ctx, Region region, SyntaxNode at, List<object> ops)
    {
        ops.Add(Use(region.Owner, Line(at)));
        ctx.EntityTouches++;
    }

    // ---- statements OUTSIDE a region ------------------------------------------------------

    /// Outside a region nothing protocol-relevant is live, so the only statements that matter
    /// are region entries — wherever they sit. A region is a self-contained unit, so the
    /// control flow around it (a branch, a loop, `try`, `using`) changes no verdict inside
    /// it, and the units are emitted in source order.
    private static void LowerOutside(Ctx ctx, StatementSyntax st, List<object> ops)
    {
        if (st is ExpressionStatementSyntax es
            && Unparen(es.Expression) is InvocationExpressionSyntax entry
            && IsRegionEntry(MethodOf(ctx.Model, entry)))
        {
            LowerRegion(ctx, entry, ops, st);
            return;
        }
        if (st is LocalFunctionStatementSyntax)
            return;   // another body; an entry inside it is refused as "not reached"
        if (st is LocalDeclarationStatementSyntax ld)
            foreach (var v in ld.Declaration.Variables)
                if (ctx.Model.GetDeclaredSymbol(v) is ILocalSymbol local && IsToken(local.Type))
                    throw Refuse(ctx, v,
                        $"protocol token '{local.Name}' is declared outside a protocol region");
        foreach (var nested in NestedStatements(st))
            LowerOutside(ctx, nested, ops);
    }

    /// The statements directly nested in `node` (through blocks, clauses and sections), in
    /// source order, never crossing into a lambda or a local function.
    private static IEnumerable<StatementSyntax> NestedStatements(SyntaxNode node)
    {
        foreach (var child in node.ChildNodes())
        {
            if (child is AnonymousFunctionExpressionSyntax)
                continue;
            if (child is StatementSyntax statement)
                yield return statement;
            else
                foreach (var deeper in NestedStatements(child))
                    yield return deeper;
        }
    }

    // ---- statements INSIDE a region -------------------------------------------------------

    private static void LowerInside(Ctx ctx, StatementSyntax st, List<object> ops)
    {
        switch (st)
        {
            case BlockSyntax block:
                foreach (var inner in block.Statements)
                    LowerInside(ctx, inner, ops);
                return;
            case EmptyStatementSyntax:
                return;
            case ExpressionStatementSyntax es:
                if (Unparen(es.Expression) is InvocationExpressionSyntax entry
                    && IsRegionEntry(MethodOf(ctx.Model, entry)))
                {
                    LowerRegion(ctx, entry, ops, st);
                    return;
                }
                Scan(ctx, es.Expression, ops);
                return;
            case LocalDeclarationStatementSyntax ld:
                if (!ld.UsingKeyword.IsKind(SyntaxKind.None) || !ld.AwaitKeyword.IsKind(SyntaxKind.None))
                    throw Refuse(ctx, st, "a `using` declaration inside a protocol region is not modelled");
                foreach (var v in ld.Declaration.Variables)
                {
                    var init = v.Initializer?.Value;
                    if (ctx.Model.GetDeclaredSymbol(v) is ILocalSymbol local && IsToken(local.Type))
                        LowerTokenLocal(ctx, local, init, ops, v);
                    else if (init is not null)
                        Scan(ctx, init, ops);
                }
                return;
            case IfStatementSyntax ifs:
                Scan(ctx, ifs.Condition, ops);
                var thenOps = new List<object>();
                LowerInside(ctx, ifs.Statement, thenOps);
                var elseOps = new List<object>();
                if (ifs.Else is not null)
                    LowerInside(ctx, ifs.Else.Statement, elseOps);
                ops.Add(new Dictionary<string, object?>
                {
                    ["op"] = "if", ["line"] = Line(st), ["then"] = thenOps, ["else"] = elseOps,
                });
                return;
            case ReturnStatementSyntax:
                throw Refuse(ctx, st,
                    "`return` inside a protocol region leaves the callback, not the method; not modelled");
            default:
                throw Refuse(ctx, st, $"{st.Kind()} inside a protocol region is not modelled");
        }
    }

    private static void LowerRegion(Ctx ctx, InvocationExpressionSyntax entry, List<object> ops,
                                    StatementSyntax st)
    {
        var args = entry.ArgumentList.Arguments;
        if (args.Count != 2)
            throw Refuse(ctx, entry, "a protocol region entry takes (entity, callback)");
        var entityExpr = Unparen(args[0].Expression);
        var entity = ctx.Model.GetSymbolInfo(entityExpr).Symbol;
        if (entityExpr is not IdentifierNameSyntax || entity is not (ILocalSymbol or IParameterSymbol))
            throw Refuse(ctx, entry,
                "the entity of a protocol region must be a local or a parameter: that symbol is the resource identity");
        if (Unparen(args[1].Expression) is not LambdaExpressionSyntax lambda)
            throw Refuse(ctx, entry,
                "the body of a protocol region must be a lambda written in place");
        if (lambda.AsyncKeyword.IsKind(SyntaxKind.AsyncKeyword))
            throw Refuse(ctx, entry, "the body of a protocol region cannot be async");
        ParameterSyntax? parameter = lambda switch
        {
            SimpleLambdaExpressionSyntax s => s.Parameter,
            ParenthesizedLambdaExpressionSyntax p when p.ParameterList.Parameters.Count == 1 =>
                p.ParameterList.Parameters[0],
            _ => null,
        };
        if (parameter is null
            || ctx.Model.GetDeclaredSymbol(parameter) is not IParameterSymbol token
            || !IsToken(token.Type))
            throw Refuse(ctx, entry,
                "the callback of a protocol region takes exactly one protocol token");
        // A token that is not a ref struct can be captured by a nested lambda, stored in a
        // field, or carried across an await — every one of which lets it reach ANOTHER
        // region, the shape the core cannot check. The language forbids all three for a
        // ref struct, so the lowering leans on that and refuses anything weaker.
        if (!token.Type.IsRefLikeType)
            throw Refuse(ctx, entry,
                $"protocol token type '{token.Type.Name}' must be a ref struct");

        var line = Line(st);
        var entityType = TypeOf(entity);
        // Exclusivity is BY TYPE, so an entity whose type does not resolve cannot be told
        // from anything else that does not: the scan's compilation is degraded (a missing
        // reference, an implicit using it never saw). Say so instead of guessing either way.
        if (entityType is null or IErrorTypeSymbol)
            throw Refuse(ctx, entry,
                $"the type of '{entity.Name}' does not resolve, so the region cannot be lowered: the scan is missing a reference, or a `using` the project only gets implicitly (the scan does not read `obj/`: write the using out, or qualify the name)");
        var existing = ctx.Regions.LastOrDefault(r =>
            SymbolEqualityComparer.Default.Equals(r.Entity, entity));
        if (existing is null)
        {
            // exclusivity by type: another value of an already-borrowed entity's type
            var clash = RegionByType(ctx, entityType);
            if (clash is not null)
                Touch(ctx, clash, entry, ops);
            ops.Add(Acquire(entity.Name, line));
        }
        var owner = existing?.Owner ?? entity.Name;
        ctx.Counter++;
        var region = new Region
        {
            Entity = entity, EntityType = entityType, Owner = owner,
            Binding = $"{owner}.region{ctx.Counter}",
        };
        var body = new List<object> { Acquire(token.Name, line) };
        ctx.Tokens[token] = (token.Name, region);
        ctx.Regions.Add(region);
        if (lambda.Body is BlockSyntax block)
            LowerInside(ctx, block, body);
        else if (lambda.Body is ExpressionSyntax expression)
            Scan(ctx, expression, body);
        ctx.Regions.RemoveAt(ctx.Regions.Count - 1);
        ops.Add(new Dictionary<string, object?>
        {
            ["op"] = "borrow_mut", ["owner"] = owner, ["binding"] = region.Binding,
            ["line"] = line, ["body"] = body,
        });
        if (existing is null)
            ops.Add(Release(owner, line));
        ctx.LoweredEntries.Add(entry);
    }

    private static void LowerTokenLocal(Ctx ctx, ILocalSymbol local, ExpressionSyntax? init,
                                        List<object> ops, SyntaxNode at)
    {
        if (init is not null)
        {
            var value = Unparen(init);
            if (value is IdentifierNameSyntax id
                && ctx.Model.GetSymbolInfo(id).Symbol is { } source
                && ctx.Tokens.TryGetValue(source, out var live))
            {
                // C# copies the struct; the model reads the copy as a MOVE.
                ops.Add(Move(local.Name, live.Name, Line(at)));
                ctx.Tokens[local] = (local.Name, live.Region);
                return;
            }
            if (value is InvocationExpressionSyntax inv
                && TryTransition(ctx, inv, ops, local.Name, out var region))
            {
                ctx.Tokens[local] = (local.Name, region);
                return;
            }
        }
        throw Refuse(ctx, at,
            $"protocol token '{local.Name}' has no lowerable origin: a token comes from a region entry, a transition, or a copy of a live token");
    }

    // ---- expressions ----------------------------------------------------------------------

    /// A call on a token is a transition: it consumes the token and borrows the entity for
    /// the call. `result`, when given, names the token the transition hands back.
    private static bool TryTransition(Ctx ctx, InvocationExpressionSyntax inv, List<object> ops,
                                      string? result, out Region region)
    {
        region = null!;
        if (inv.Expression is not MemberAccessExpressionSyntax access
            || MethodOf(ctx.Model, inv) is not { IsStatic: false } method
            || !IsToken(method.ContainingType))
            return false;

        string receiver;
        var target = Unparen(access.Expression);
        if (target is IdentifierNameSyntax id
            && ctx.Model.GetSymbolInfo(id).Symbol is { } symbol
            && ctx.Tokens.TryGetValue(symbol, out var live))
        {
            receiver = live.Name;
            region = live.Region;
        }
        else if (target is InvocationExpressionSyntax inner)
        {
            // a chain: `draft.Submit().Approve()` - the intermediate token is a temporary
            ctx.Counter++;
            receiver = $"$t{ctx.Counter}";
            if (!TryTransition(ctx, inner, ops, receiver, out region))
                throw Refuse(ctx, inv,
                    $"the receiver of transition '{method.Name}' is not a token this region minted");
        }
        else
        {
            throw Refuse(ctx, inv,
                $"the receiver of transition '{method.Name}' is not a token this region minted");
        }

        foreach (var arg in inv.ArgumentList.Arguments)
            Scan(ctx, arg.Expression, ops);

        var callee = $"{method.ContainingType.ToDisplayString()}.{method.Name}";
        Contract(ctx, callee, method, inv);
        ops.Add(Call(callee, new[] { receiver, region.Binding }, Line(inv)));
        if (result is not null)
        {
            if (!IsToken(method.ReturnType))
                throw Refuse(ctx, inv,
                    $"transition '{method.Name}' does not return a protocol token");
            ops.Add(Acquire(result, Line(inv)));
        }
        return true;
    }

    /// The contract of a transition, stated once per method: the token is consumed, the
    /// entity is exclusively borrowed for the call. This is a FACT about the attribute's
    /// meaning, not an inference from the method's body.
    private static void Contract(Ctx ctx, string callee, IMethodSymbol method, SyntaxNode at)
    {
        if (ctx.Contracts.ContainsKey(callee))
            return;
        if (ctx.LegacyNames.Contains(callee))
            throw Refuse(ctx, at,
                $"transition '{callee}' already has a flow record; the two lowerings are not merged in this profile");
        var decl = method.DeclaringSyntaxReferences.FirstOrDefault();
        var file = decl is not null && ctx.Files.TryGetValue(decl.SyntaxTree, out var f) ? f : "?";
        var line = decl is not null ? Line(decl.GetSyntax()) : 0;
        ctx.Contracts[callee] = new Dictionary<string, object?>
        {
            ["name"] = callee,
            ["file"] = file,
            ["params"] = new object[]
            {
                new Dictionary<string, object?> { ["name"] = "token", ["effect"] = "consume", ["line"] = line },
                new Dictionary<string, object?> { ["name"] = "entity", ["effect"] = "borrow_mut", ["line"] = line },
            },
            ["body"] = new object[] { Release("token", line) },
        };
    }

    private static ITypeSymbol? TypeOf(ISymbol symbol) => symbol switch
    {
        ILocalSymbol l => l.Type,
        IParameterSymbol p => p.Type,
        IFieldSymbol f => f.Type,
        IPropertySymbol p => p.Type,
        _ => null,
    };

    private static Region? RegionByType(Ctx ctx, ITypeSymbol? type) =>
        type is null ? null : ctx.Regions.LastOrDefault(r =>
            SymbolEqualityComparer.Default.Equals(r.EntityType, type));

    private static Region? RegionFor(Ctx ctx, ISymbol symbol, ITypeSymbol? type) =>
        ctx.Regions.LastOrDefault(r => SymbolEqualityComparer.Default.Equals(r.Entity, symbol))
        ?? RegionByType(ctx, type);

    /// Exclusivity by type: an expression that PRODUCES a value of a borrowed entity's type
    /// (a field read, a cast, an array element) may be that entity, so it counts as
    /// touching it.
    private static void NoteEntityTyped(Ctx ctx, ExpressionSyntax expression, List<object> ops)
    {
        var region = RegionByType(ctx, ctx.Model.GetTypeInfo(expression).Type);
        if (region is not null)
            Touch(ctx, region, expression, ops);
    }

    private static bool IsLiveToken(Ctx ctx, ExpressionSyntax expression, out string name)
    {
        name = "";
        if (Unparen(expression) is IdentifierNameSyntax id
            && ctx.Model.GetSymbolInfo(id).Symbol is { } symbol
            && ctx.Tokens.TryGetValue(symbol, out var token))
        {
            name = token.Name;
            return true;
        }
        return false;
    }

    /// Code with no stated contract, inside an exclusive region. If lowering its operands
    /// touched the entity the core has a use to reject; otherwise nothing says what the code
    /// does, and the region is not analysed as safe.
    private static void OpaqueCode(Ctx ctx, SyntaxNode node, string what, int touchesBefore)
    {
        if (ctx.EntityTouches > touchesBefore)
            return;
        throw Refuse(ctx, node,
            $"{what} inside a protocol region runs code with no stated contract; an exclusive region admits only transitions and what the lowering can read");
    }

    /// An expression inside a region. DEFAULT-DENY: every kind is either read here or refused.
    private static void Scan(Ctx ctx, SyntaxNode node, List<object> ops)
    {
        if (node is ExpressionSyntax typed
            && ctx.Model.GetConversion(typed).IsUserDefined)
            throw Refuse(ctx, node,
                "a user-defined conversion inside a protocol region runs code with no stated contract");

        switch (node)
        {
            case LiteralExpressionSyntax:
            case TypeOfExpressionSyntax:
            case SizeOfExpressionSyntax:
            case DefaultExpressionSyntax:
            case PredefinedTypeSyntax:
                return;
            case ParenthesizedExpressionSyntax paren:
                Scan(ctx, paren.Expression, ops);
                return;
            case CheckedExpressionSyntax @checked:
                Scan(ctx, @checked.Expression, ops);
                return;
            case ThisExpressionSyntax or BaseExpressionSyntax:
                NoteEntityTyped(ctx, (ExpressionSyntax)node, ops);
                return;
            case IdentifierNameSyntax id:
            {
                var symbol = ctx.Model.GetSymbolInfo(id).Symbol;
                switch (symbol)
                {
                    case null:
                        throw Refuse(ctx, id,
                            $"'{id.Identifier.Text}' does not resolve; an unresolved name inside a protocol region is not read as harmless");
                    case INamespaceOrTypeSymbol:
                        return;
                    case ILocalSymbol or IParameterSymbol or IFieldSymbol:
                        if (ctx.Tokens.ContainsKey(symbol))
                            throw Refuse(ctx, id,
                                $"protocol token '{id.Identifier.Text}' is used in a way the lowering does not model (transitions, property reads and copies are)");
                        var region = RegionFor(ctx, symbol, TypeOf(symbol));
                        if (region is not null)
                            Touch(ctx, region, id, ops);
                        return;
                    case IPropertySymbol property:
                    {
                        var before = ctx.EntityTouches;
                        var owner = RegionByType(ctx, property.Type);
                        if (owner is not null)
                            Touch(ctx, owner, id, ops);
                        OpaqueCode(ctx, id, $"property '{property.Name}'", before);
                        return;
                    }
                    default:
                        throw Refuse(ctx, id,
                            $"'{id.Identifier.Text}' ({symbol.Kind}) inside a protocol region is not modelled");
                }
            }
            case MemberAccessExpressionSyntax access:
            {
                if (IsLiveToken(ctx, access.Expression, out var token))
                {
                    ops.Add(Use(token, Line(access)));   // a property read on the token
                    return;
                }
                var before = ctx.EntityTouches;
                Scan(ctx, access.Expression, ops);
                var member = ctx.Model.GetSymbolInfo(access).Symbol;
                switch (member)
                {
                    case IFieldSymbol:
                        NoteEntityTyped(ctx, access, ops);
                        return;
                    case INamespaceOrTypeSymbol:
                        return;
                    case IPropertySymbol property:
                        NoteEntityTyped(ctx, access, ops);
                        OpaqueCode(ctx, access, $"property '{property.Name}'", before);
                        return;
                    default:
                        throw Refuse(ctx, access,
                            $"'{access.Name.Identifier.Text}' inside a protocol region is not modelled");
                }
            }
            case InvocationExpressionSyntax inv:
            {
                // `nameof(x)` is a constant spelled as a call
                if (ctx.Model.GetConstantValue(inv).HasValue)
                    return;
                var method = MethodOf(ctx.Model, inv);
                if (IsRegionEntry(method))
                    throw Refuse(ctx, inv,
                        "a protocol region entry in a position the lowering does not model (it must be a statement of its own)");
                if (TryTransition(ctx, inv, ops, null, out _))
                    return;
                var before = ctx.EntityTouches;
                foreach (var arg in inv.ArgumentList.Arguments)
                {
                    if (IsLiveToken(ctx, arg.Expression, out var passed))
                        throw Refuse(ctx, arg,
                            $"protocol token '{passed}' is handed to other code; a token does not leave its region");
                    Scan(ctx, arg.Expression, ops);
                }
                // the receiver, never the method's own name
                if (inv.Expression is MemberAccessExpressionSyntax target)
                    Scan(ctx, target.Expression, ops);
                NoteEntityTyped(ctx, inv, ops);
                var name = method is null
                    ? inv.Expression.ToString()
                    : $"{method.ContainingType.ToDisplayString()}.{method.Name}";
                OpaqueCode(ctx, inv, $"a call to '{name}'", before);
                return;
            }
            case BaseObjectCreationExpressionSyntax creation:
            {
                var before = ctx.EntityTouches;
                foreach (var arg in creation.ArgumentList?.Arguments ?? default)
                    Scan(ctx, arg.Expression, ops);
                if (creation.Initializer is not null)
                    throw Refuse(ctx, creation,
                        "an object initializer inside a protocol region is not modelled");
                OpaqueCode(ctx, creation, "a constructor call", before);
                return;
            }
            case ArrayCreationExpressionSyntax or ImplicitArrayCreationExpressionSyntax
                or InitializerExpressionSyntax or TupleExpressionSyntax
                or ArrayTypeSyntax or ArrayRankSpecifierSyntax or OmittedArraySizeExpressionSyntax
                or ArgumentSyntax or ConditionalExpressionSyntax:
                foreach (var child in node.ChildNodes())
                    Scan(ctx, child, ops);
                return;
            case ElementAccessExpressionSyntax element:
            {
                var before = ctx.EntityTouches;
                Scan(ctx, element.Expression, ops);
                foreach (var arg in element.ArgumentList.Arguments)
                    Scan(ctx, arg.Expression, ops);
                NoteEntityTyped(ctx, element, ops);
                if (ctx.Model.GetTypeInfo(element.Expression).Type is not IArrayTypeSymbol)
                    OpaqueCode(ctx, element, "an indexer", before);
                return;
            }
            case BinaryExpressionSyntax binary:
            {
                if (ctx.Model.GetSymbolInfo(binary).Symbol is IMethodSymbol
                    { MethodKind: not MethodKind.BuiltinOperator })
                    throw Refuse(ctx, binary,
                        "a user-defined operator inside a protocol region runs code with no stated contract");
                // string concatenation formats its operands: only inert ones run no user code
                if (binary.IsKind(SyntaxKind.AddExpression)
                    && ctx.Model.GetTypeInfo(binary).Type?.SpecialType == SpecialType.System_String
                    && !(IsInert(ctx.Model.GetTypeInfo(binary.Left).Type)
                         && IsInert(ctx.Model.GetTypeInfo(binary.Right).Type)))
                    throw Refuse(ctx, binary,
                        "string concatenation of a non-primitive value inside a protocol region calls its ToString(); not modelled");
                Scan(ctx, binary.Left, ops);
                // the right operand of `is` / `as` is a type, not a value
                if (!binary.IsKind(SyntaxKind.AsExpression) && !binary.IsKind(SyntaxKind.IsExpression))
                    Scan(ctx, binary.Right, ops);
                if (binary.IsKind(SyntaxKind.AsExpression))
                    NoteEntityTyped(ctx, binary, ops);
                return;
            }
            case PrefixUnaryExpressionSyntax or PostfixUnaryExpressionSyntax:
            {
                if (ctx.Model.GetSymbolInfo(node).Symbol is IMethodSymbol
                    { MethodKind: not MethodKind.BuiltinOperator })
                    throw Refuse(ctx, node,
                        "a user-defined operator inside a protocol region runs code with no stated contract");
                foreach (var child in node.ChildNodes())
                    Scan(ctx, child, ops);
                return;
            }
            case AssignmentExpressionSyntax assignment:
            {
                if (ctx.Model.GetSymbolInfo(assignment).Symbol is IMethodSymbol
                    { MethodKind: not MethodKind.BuiltinOperator })
                    throw Refuse(ctx, assignment,
                        "a user-defined operator inside a protocol region runs code with no stated contract");
                Scan(ctx, assignment.Left, ops);
                Scan(ctx, assignment.Right, ops);
                return;
            }
            case CastExpressionSyntax cast:
            {
                var target = ctx.Model.GetTypeInfo(cast.Type).Type;
                if (target is null
                    || ctx.Model.ClassifyConversion(cast.Expression, target).IsUserDefined)
                    throw Refuse(ctx, cast,
                        "a user-defined conversion inside a protocol region runs code with no stated contract");
                Scan(ctx, cast.Expression, ops);
                NoteEntityTyped(ctx, cast, ops);
                return;
            }
            case InterpolatedStringExpressionSyntax interpolated:
                foreach (var part in interpolated.Contents.OfType<InterpolationSyntax>())
                {
                    if (!IsInert(ctx.Model.GetTypeInfo(part.Expression).Type))
                        throw Refuse(ctx, part,
                            "interpolating a non-primitive value inside a protocol region calls its ToString(); not modelled");
                    Scan(ctx, part.Expression, ops);
                }
                return;
            default:
                throw Refuse(ctx, node, $"{node.Kind()} inside a protocol region is not modelled");
        }
    }
}
