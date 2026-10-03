using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Operations;

// Heap-effect source facts (H0, docs/notes/heap-effect-summaries.md): the LOCAL evidence the
// core's heap-effect summary solver (ownlang/heap_effects.py, own-bridge heap_effects.rs)
// composes into per-method summaries. Written ONLY under `--heap-effects FILE`, to that file:
// the OwnIR facts document is never touched, with or without the flag.
//
// This is FACT EXTRACTION, not an analysis. It reads one method body at a time and records,
// in a small token vocabulary, what the body itself does:
//
//   a value's SOURCES   param:<i> | receiver | heap | local:<n> | call:<k>
//                       (a value of an inert type — unmanaged or string — carries nothing)
//   derefs              sources read THROUGH (a field, an element, a property)
//   writes              {kind: instance|static|indirect, target: sources of the written object}
//   stores              sources of values put somewhere that outlives the call
//   returns             sources of the returned value
//   calls               callee key, dispatch, receiver and per-parameter argument sources
//   locals              per local, the sources ever assigned to it (flow-insensitive)
//   unknown             reasons the body has a construct this vocabulary does not model
//
// It never decides anything: no summary is solved here, no call is called harmless, no callee
// body is read from a call site. Every construct the walk does not model is recorded as an
// `unknown` reason, and the solver reads a method with one as Unknown everywhere — the
// vocabulary is default-deny, so a missing case can only lose precision, never invent "clean".
internal static class HeapEffectFacts
{
    internal const int Version = 1;

    // One spelling for a method's identity, on both sides of a call edge.
    private static readonly SymbolDisplayFormat KeyFormat = SymbolDisplayFormat.CSharpErrorMessageFormat;

    internal static string Key(IMethodSymbol method) =>
        (method.ReducedFrom ?? method).OriginalDefinition.ToDisplayString(KeyFormat);

    public static Dictionary<string, object?> Extract(Compilation compilation,
                                                      IReadOnlyList<(string file, SyntaxTree tree)> parsed)
    {
        var methods = new SortedDictionary<string, Dictionary<string, object?>>(StringComparer.Ordinal);
        foreach (var (file, tree) in parsed)
        {
            var model = compilation.GetSemanticModel(tree);
            foreach (var node in tree.GetRoot().DescendantNodes())
            {
                IMethodSymbol? symbol = null;
                IOperation? body = null;
                switch (node)
                {
                    case BaseMethodDeclarationSyntax m when m.Body is not null || m.ExpressionBody is not null:
                        symbol = model.GetDeclaredSymbol(m) as IMethodSymbol;
                        body = model.GetOperation(m);
                        break;
                    case AccessorDeclarationSyntax a when a.Body is not null || a.ExpressionBody is not null:
                        symbol = model.GetDeclaredSymbol(a) as IMethodSymbol;
                        body = model.GetOperation(a);
                        break;
                    case PropertyDeclarationSyntax { ExpressionBody: { } arrow } p:
                        symbol = (model.GetDeclaredSymbol(p) as IPropertySymbol)?.GetMethod;
                        body = model.GetOperation(arrow);
                        break;
                    case IndexerDeclarationSyntax { ExpressionBody: { } arrow } ix:
                        symbol = (model.GetDeclaredSymbol(ix) as IPropertySymbol)?.GetMethod;
                        body = model.GetOperation(arrow);
                        break;
                }
                if (symbol is null || body is null)
                    continue;
                var key = Key(symbol);
                if (methods.ContainsKey(key))
                    continue;   // one record per method (a file passed twice is still one method)
                methods[key] = new Walk(compilation, symbol, file, node).Run(body);
            }
        }
        return new Dictionary<string, object?>
        {
            ["heap_effects_version"] = Version,
            ["methods"] = methods.Values.ToList(),
        };
    }

    /// A value of this type carries no reference: copying it shares nothing with the caller.
    internal static bool Inert(ITypeSymbol? type) =>
        type is not null
        && type.TypeKind is not (TypeKind.Pointer or TypeKind.FunctionPointer or TypeKind.Dynamic)
        && (type.SpecialType == SpecialType.System_String || type.IsUnmanagedType);

    /// Formatting a value of this type runs no user code (`ToString` of a primitive or enum).
    private static bool FormatSafe(ITypeSymbol? type) =>
        type is not null && (type.TypeKind == TypeKind.Enum || type.SpecialType is
            SpecialType.System_Boolean or SpecialType.System_Char or SpecialType.System_String
            or SpecialType.System_SByte or SpecialType.System_Byte
            or SpecialType.System_Int16 or SpecialType.System_UInt16
            or SpecialType.System_Int32 or SpecialType.System_UInt32
            or SpecialType.System_Int64 or SpecialType.System_UInt64
            or SpecialType.System_Single or SpecialType.System_Double
            or SpecialType.System_Decimal);

    private sealed class Walk
    {
        private readonly Compilation _compilation;
        private readonly IMethodSymbol _method;
        private readonly string _file;
        private readonly SyntaxNode _decl;
        private readonly bool _returnInert;

        private readonly Dictionary<ISymbol, int> _localIds = new(SymbolEqualityComparer.Default);
        private readonly List<(string Name, SortedSet<string> Sources)> _locals = new();
        // value parameters that are assigned somewhere: read through a local slot seeded with
        // `param:<i>`, so a reassigned parameter's later value is not mistaken for the argument
        private readonly Dictionary<IParameterSymbol, int> _reassigned = new(SymbolEqualityComparer.Default);
        private readonly SortedSet<string> _derefs = new(StringComparer.Ordinal);
        private readonly SortedSet<string> _stores = new(StringComparer.Ordinal);
        private readonly SortedSet<string> _returns = new(StringComparer.Ordinal);
        private readonly SortedDictionary<string, (string Kind, SortedSet<string> Target)> _writes = new(StringComparer.Ordinal);
        private readonly List<Dictionary<string, object?>> _calls = new();
        private readonly SortedSet<string> _unknown = new(StringComparer.Ordinal);
        private readonly Stack<SortedSet<string>> _conditional = new();

        public Walk(Compilation compilation, IMethodSymbol method, string file, SyntaxNode decl)
        {
            _compilation = compilation;
            _method = method;
            _file = file;
            _decl = decl;
            _returnInert = method.ReturnsVoid || Inert(method.ReturnType);
        }

        private static SortedSet<string> None() => new(StringComparer.Ordinal);

        private static SortedSet<string> One(string token) => new(StringComparer.Ordinal) { token };

        private void Unknown(string reason) => _unknown.Add(reason);

        public Dictionary<string, object?> Run(IOperation body)
        {
            if (_method.IsAsync)
                Unknown("async method");
            if (_method.ReturnsByRef || _method.ReturnsByRefReadonly)
                Unknown("ref return");
            if (_method.MethodKind == MethodKind.Constructor && HasInstanceInitializers(_method.ContainingType))
                Unknown($"instance initializers of {_method.ContainingType.ToDisplayString()}");
            foreach (var p in _method.Parameters)
                if (!Inert(p.Type) || p.RefKind is RefKind.Ref or RefKind.Out)
                    if (IsReassigned(body, p) && p.RefKind is RefKind.None or RefKind.In)
                    {
                        var slot = NewLocal(p.Name);
                        _locals[slot].Sources.Add($"param:{p.Ordinal}");
                        _reassigned[p] = slot;
                    }
            Exec(body);

            var line = _decl.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
            return new Dictionary<string, object?>
            {
                ["key"] = Key(_method),
                ["file"] = _file,
                ["line"] = line,
                ["receiver"] = !_method.IsStatic,
                ["return_inert"] = _returnInert,
                ["params"] = _method.Parameters.Select(p => new Dictionary<string, object?>
                {
                    ["index"] = p.Ordinal,
                    ["name"] = p.Name,
                    ["inert"] = Inert(p.Type) && p.RefKind is RefKind.None or RefKind.In,
                }).ToList(),
                ["locals"] = _locals.Select((l, i) => new Dictionary<string, object?>
                {
                    ["id"] = i, ["name"] = l.Name, ["sources"] = l.Sources.ToList(),
                }).ToList(),
                ["derefs"] = _derefs.ToList(),
                ["writes"] = _writes.Values.Select(w => new Dictionary<string, object?>
                {
                    ["kind"] = w.Kind, ["target"] = w.Target.ToList(),
                }).ToList(),
                ["stores"] = _stores.ToList(),
                ["returns"] = _returns.ToList(),
                ["calls"] = _calls,
                ["unknown"] = _unknown.ToList(),
            };
        }

        /// A parameter of the method being read (not one a member captured from elsewhere).
        private bool Own(IParameterSymbol p) =>
            SymbolEqualityComparer.Default.Equals(p.ContainingSymbol, _method);

        private static bool IsReassigned(IOperation body, IParameterSymbol p) =>
            body.Descendants().Any(op => op switch
            {
                IAssignmentOperation a => Refers(a.Target, p),
                IIncrementOrDecrementOperation i => Refers(i.Target, p),
                IArgumentOperation { Parameter.RefKind: RefKind.Ref or RefKind.Out } arg => Refers(arg.Value, p),
                _ => false,
            });

        private static bool Refers(IOperation target, IParameterSymbol p) =>
            target is IParameterReferenceOperation r && SymbolEqualityComparer.Default.Equals(r.Parameter, p);

        private int NewLocal(string name)
        {
            _locals.Add((name, None()));
            return _locals.Count - 1;
        }

        private int LocalId(ILocalSymbol local)
        {
            if (!_localIds.TryGetValue(local, out var id))
            {
                id = NewLocal(local.Name);
                _localIds[local] = id;
            }
            return id;
        }

        private void Write(string kind, SortedSet<string> target)
        {
            var key = kind + "|" + string.Join(",", target);
            if (!_writes.ContainsKey(key))
                _writes[key] = (kind, new SortedSet<string>(target, StringComparer.Ordinal));
        }

        // ---- static initialization: a hidden effect of naming a type ----------------------

        private void StaticAccess(INamedTypeSymbol type, string what)
        {
            if (type.DeclaringSyntaxReferences.IsEmpty)
            {
                Unknown($"{what} of external type {type.ToDisplayString()}");
                return;
            }
            if (HasStaticInitialization(type))
                Unknown($"static initialization of {type.ToDisplayString()}");
        }

        private bool HasStaticInitialization(INamedTypeSymbol type)
        {
            if (type.StaticConstructors.Any(c => !c.IsImplicitlyDeclared))
                return true;
            return HasInitializers(type, isStatic: true);
        }

        private bool HasInstanceInitializers(INamedTypeSymbol type) => HasInitializers(type, isStatic: false);

        /// A field or property initializer that runs code: anything but a compile-time constant
        /// (a `null` literal is one).
        private bool HasInitializers(INamedTypeSymbol type, bool isStatic)
        {
            foreach (var member in type.GetMembers())
            {
                if (member.IsStatic != isStatic || member is not (IFieldSymbol or IPropertySymbol or IEventSymbol))
                    continue;
                foreach (var reference in member.DeclaringSyntaxReferences)
                {
                    var syntax = reference.GetSyntax();
                    var value = syntax switch
                    {
                        VariableDeclaratorSyntax v => v.Initializer?.Value,
                        PropertyDeclarationSyntax p => p.Initializer?.Value,
                        _ => null,
                    };
                    if (value is null)
                        continue;
                    var model = _compilation.GetSemanticModel(syntax.SyntaxTree);
                    if (!model.GetConstantValue(value).HasValue)
                        return true;
                }
            }
            return false;
        }

        // ---- statements ------------------------------------------------------------------

        private void Exec(IOperation? op)
        {
            switch (op)
            {
                case null:
                case IEmptyOperation:
                case IBranchOperation:
                    return;
                case IMethodBodyOperation body:
                    Exec((IOperation?)body.BlockBody ?? body.ExpressionBody);
                    return;
                case IConstructorBodyOperation ctor:
                    Exec(ctor.Initializer);
                    Exec((IOperation?)ctor.BlockBody ?? ctor.ExpressionBody);
                    return;
                case IBlockOperation block:
                    foreach (var statement in block.Operations)
                        Exec(statement);
                    return;
                case ILabeledOperation labeled:
                    Exec(labeled.Operation);
                    return;
                case IExpressionStatementOperation statement:
                    Eval(statement.Operation);
                    return;
                case IVariableDeclarationGroupOperation group:
                    foreach (var declaration in group.Declarations)
                        Declare(declaration);
                    return;
                case IReturnOperation ret when ret.Kind == OperationKind.Return:
                    var value = Eval(ret.ReturnedValue);
                    if (!_returnInert)
                        _returns.UnionWith(value);
                    return;
                case IConditionalOperation cond when cond.Type is null:
                    Eval(cond.Condition);
                    Exec(cond.WhenTrue);
                    Exec(cond.WhenFalse);
                    return;
                case IWhileLoopOperation loop:
                    Eval(loop.Condition);
                    Exec(loop.Body);
                    Eval(loop.IgnoredCondition);
                    return;
                case IForLoopOperation loop:
                    foreach (var before in loop.Before)
                        Exec(before);
                    Eval(loop.Condition);
                    Exec(loop.Body);
                    foreach (var after in loop.AtLoopBottom)
                        Exec(after);
                    return;
                case IForEachLoopOperation loop:
                    ForEach(loop);
                    return;
                case IThrowOperation thrown:
                    Eval(thrown);
                    return;
                case ITryOperation tryOp:
                    Exec(tryOp.Body);
                    foreach (var handler in tryOp.Catches)
                    {
                        if (handler.ExceptionDeclarationOrExpression is IVariableDeclaratorOperation caught)
                            _locals[LocalId(caught.Symbol)].Sources.Add("heap");
                        else if (handler.ExceptionDeclarationOrExpression is not null)
                            Unknown("catch clause with an expression");
                        Eval(handler.Filter);
                        Exec(handler.Handler);
                    }
                    Exec(tryOp.Finally);
                    return;
                case ISwitchOperation sw:
                    var subject = Eval(sw.Value);
                    foreach (var section in sw.Cases)
                    {
                        foreach (var clause in section.Clauses)
                            switch (clause)
                            {
                                case ISingleValueCaseClauseOperation single:
                                    Eval(single.Value);
                                    break;
                                case IDefaultCaseClauseOperation:
                                    break;
                                case IPatternCaseClauseOperation pattern:
                                    Pattern(pattern.Pattern, subject);
                                    Eval(pattern.Guard);
                                    break;
                                default:
                                    Unknown($"case clause {clause.CaseKind}");
                                    break;
                            }
                        foreach (var statement in section.Body)
                            Exec(statement);
                    }
                    return;
                default:
                    Unknown($"statement {op.Kind}");
                    return;
            }
        }

        private void Declare(IVariableDeclarationOperation declaration)
        {
            foreach (var dimension in declaration.IgnoredDimensions)
                Eval(dimension);
            foreach (var declarator in declaration.Declarators)
            {
                if (declarator.Symbol.IsRef)
                {
                    Unknown("ref local");
                    continue;
                }
                var init = declarator.Initializer ?? declaration.Initializer;
                var value = Eval(init?.Value);
                _locals[LocalId(declarator.Symbol)].Sources.UnionWith(value);
            }
        }

        private void ForEach(IForEachLoopOperation loop)
        {
            var collection = loop.Collection is IConversionOperation { OperatorMethod: null } conversion
                ? conversion.Operand
                : loop.Collection;
            if (collection.Type is not IArrayTypeSymbol array)
            {
                Unknown("foreach over a non-array (an enumerator runs code)");
                return;
            }
            var items = Eval(collection);
            _derefs.UnionWith(items);
            if (loop.LoopControlVariable is IVariableDeclaratorOperation variable && !variable.Symbol.IsRef)
            {
                if (!Inert(array.ElementType))
                    _locals[LocalId(variable.Symbol)].Sources.UnionWith(items);
            }
            else
            {
                Unknown("foreach loop variable");
            }
            Exec(loop.Body);
        }

        // ---- patterns --------------------------------------------------------------------

        private void Pattern(IPatternOperation pattern, SortedSet<string> subject)
        {
            switch (pattern)
            {
                case IConstantPatternOperation constant:
                    Eval(constant.Value);
                    return;
                case IRelationalPatternOperation relational:
                    Eval(relational.Value);
                    return;
                case ITypePatternOperation:
                case IDiscardPatternOperation:
                    return;
                case IDeclarationPatternOperation declaration:
                    if (declaration.DeclaredSymbol is ILocalSymbol local && !local.IsRef)
                        _locals[LocalId(local)].Sources.UnionWith(Inert(local.Type) ? None() : subject);
                    else if (declaration.DeclaredSymbol is not null)
                        Unknown("pattern declaration");
                    return;
                case INegatedPatternOperation negated:
                    Pattern(negated.Pattern, subject);
                    return;
                case IBinaryPatternOperation binary:
                    Pattern(binary.LeftPattern, subject);
                    Pattern(binary.RightPattern, subject);
                    return;
                default:
                    // property / positional / list patterns run getters and Deconstruct
                    Unknown($"pattern {pattern.Kind}");
                    return;
            }
        }

        // ---- expressions: the sources of a value -----------------------------------------

        private SortedSet<string> Eval(IOperation? op)
        {
            if (op is null)
                return None();
            if (op.ConstantValue.HasValue)
                return None();   // a constant runs nothing (`nameof` included)
            if (op.Type is { TypeKind: TypeKind.Dynamic })
            {
                Unknown("dynamic");
                return None();
            }
            var value = Value(op);
            return Inert(op.Type) ? None() : value;
        }

        private SortedSet<string> Value(IOperation op)
        {
            switch (op)
            {
                case ILiteralOperation:
                case IDefaultValueOperation:
                case ITypeOfOperation:
                case ISizeOfOperation:
                case IDiscardOperation:
                    return None();
                case IParameterReferenceOperation p when !Own(p.Parameter):
                    // a primary-constructor parameter captured by a member: hidden state
                    Unknown("captured primary-constructor parameter");
                    return None();
                case IParameterReferenceOperation p:
                    if (_reassigned.TryGetValue(p.Parameter, out var slot))
                        return One($"local:{slot}");
                    return One($"param:{p.Parameter.Ordinal}");
                case IInstanceReferenceOperation { ReferenceKind: InstanceReferenceKind.ContainingTypeInstance }:
                    return One("receiver");
                case IInstanceReferenceOperation:
                    Unknown("implicit receiver (an object or collection initializer)");
                    return None();
                case ILocalReferenceOperation l:
                    if (l.Local.IsRef)
                    {
                        Unknown("ref local");
                        return None();
                    }
                    return One($"local:{LocalId(l.Local)}");
                case IFieldReferenceOperation f:
                    return Field(f);
                case IPropertyReferenceOperation prop:
                    return PropertyRead(prop);
                case IArrayElementReferenceOperation element:
                {
                    var array = Eval(element.ArrayReference);
                    foreach (var index in element.Indices)
                        Eval(index);
                    _derefs.UnionWith(array);
                    return array;
                }
                case IInvocationOperation inv:
                    return Invocation(inv);
                case IObjectCreationOperation creation:
                    return Creation(creation);
                case IArrayCreationOperation creation:
                    foreach (var size in creation.DimensionSizes)
                        Eval(size);
                    if (creation.Initializer is not null)
                        foreach (var item in Flatten(creation.Initializer))
                            _stores.UnionWith(Eval(item));
                    return One("heap");
                case IConversionOperation conversion:
                    if (conversion.OperatorMethod is not null)
                        return Call(conversion.OperatorMethod, null, Positional(conversion.OperatorMethod, conversion.Operand), conversion, nonVirtual: true);
                    if (conversion.Operand is IDelegateCreationOperation or IAnonymousFunctionOperation or IMethodReferenceOperation)
                    {
                        Unknown("delegate creation");
                        return None();
                    }
                    return Eval(conversion.Operand);
                case IBinaryOperation binary:
                    if (binary.OperatorMethod is not null)
                        return Call(binary.OperatorMethod, null, Positional(binary.OperatorMethod, binary.LeftOperand, binary.RightOperand), binary, nonVirtual: true);
                    if (binary.Type?.SpecialType == SpecialType.System_String
                        && !(FormatSafe(binary.LeftOperand.Type) && FormatSafe(binary.RightOperand.Type)))
                    {
                        Unknown("string concatenation of a non-primitive value (its ToString runs)");
                        return None();
                    }
                    var left = Eval(binary.LeftOperand);
                    left.UnionWith(Eval(binary.RightOperand));
                    return left;
                case IUnaryOperation unary:
                    if (unary.OperatorMethod is not null)
                        return Call(unary.OperatorMethod, null, Positional(unary.OperatorMethod, unary.Operand), unary, nonVirtual: true);
                    return Eval(unary.Operand);
                case IIncrementOrDecrementOperation step:
                    if (step.OperatorMethod is not null)
                        Call(step.OperatorMethod, null, Positional(step.OperatorMethod, step.Target), step, nonVirtual: true);
                    Assign(step.Target, Eval(step.Target));
                    return None();
                case ISimpleAssignmentOperation assignment:
                {
                    if (assignment.IsRef)
                    {
                        Unknown("ref assignment");
                        return None();
                    }
                    var value = Eval(assignment.Value);
                    Assign(assignment.Target, value);
                    return value;
                }
                case ICompoundAssignmentOperation compound:
                {
                    var current = Eval(compound.Target);
                    var value = Eval(compound.Value);
                    if (compound.OperatorMethod is not null)
                        current.UnionWith(Call(compound.OperatorMethod, null, Positional(compound.OperatorMethod, compound.Target, compound.Value), compound, nonVirtual: true));
                    else if (compound.Type?.SpecialType == SpecialType.System_String
                             && !(FormatSafe(compound.Target.Type) && FormatSafe(compound.Value.Type)))
                        Unknown("string concatenation of a non-primitive value (its ToString runs)");
                    current.UnionWith(value);
                    Assign(compound.Target, current);
                    return current;
                }
                case ICoalesceAssignmentOperation coalesce:
                {
                    var current = Eval(coalesce.Target);
                    current.UnionWith(Eval(coalesce.Value));
                    Assign(coalesce.Target, current);
                    return current;
                }
                case ICoalesceOperation coalesce:
                {
                    var value = Eval(coalesce.Value);
                    value.UnionWith(Eval(coalesce.WhenNull));
                    return value;
                }
                case IConditionalOperation cond:
                {
                    if (cond.IsRef)
                    {
                        Unknown("ref conditional");
                        return None();
                    }
                    Eval(cond.Condition);
                    var value = Eval(cond.WhenTrue);
                    value.UnionWith(Eval(cond.WhenFalse));
                    return value;
                }
                case IConditionalAccessOperation access:
                {
                    var target = Eval(access.Operation);
                    _conditional.Push(target);
                    var value = Eval(access.WhenNotNull);
                    _conditional.Pop();
                    return value;
                }
                case IConditionalAccessInstanceOperation:
                    return _conditional.Count > 0 ? new SortedSet<string>(_conditional.Peek(), StringComparer.Ordinal) : None();
                case ITupleOperation tuple:
                {
                    var value = None();
                    foreach (var element in tuple.Elements)
                        value.UnionWith(Eval(element));
                    return value;
                }
                case IInterpolatedStringOperation interpolated:
                    foreach (var part in interpolated.Parts)
                        switch (part)
                        {
                            case IInterpolatedStringTextOperation:
                                break;
                            case IInterpolationOperation hole when FormatSafe(hole.Expression.Type):
                                Eval(hole.Expression);
                                Eval(hole.Alignment);
                                Eval(hole.FormatString);
                                break;
                            default:
                                Unknown("interpolation of a non-primitive value (its ToString runs)");
                                break;
                        }
                    return None();
                case IIsTypeOperation isType:
                    Eval(isType.ValueOperand);
                    return None();
                case IIsPatternOperation isPattern:
                    Pattern(isPattern.Pattern, Eval(isPattern.Value));
                    return None();
                case ISwitchExpressionOperation sw:
                {
                    var subject = Eval(sw.Value);
                    var value = None();
                    foreach (var arm in sw.Arms)
                    {
                        Pattern(arm.Pattern, subject);
                        Eval(arm.Guard);
                        value.UnionWith(Eval(arm.Value));
                    }
                    return value;
                }
                case IThrowOperation thrown:
                    _stores.UnionWith(Eval(thrown.Exception));
                    return None();
                case IDeclarationExpressionOperation declaration:
                    return Eval(declaration.Expression);
                default:
                    Unknown($"expression {op.Kind}");
                    return None();
            }
        }

        private static IEnumerable<IOperation> Flatten(IArrayInitializerOperation initializer)
        {
            foreach (var value in initializer.ElementValues)
                if (value is IArrayInitializerOperation nested)
                    foreach (var inner in Flatten(nested))
                        yield return inner;
                else
                    yield return value;
        }

        private SortedSet<string> Field(IFieldReferenceOperation f)
        {
            if (f.Field.IsStatic)
            {
                StaticAccess(f.Field.ContainingType, "static field");
                return One("heap");
            }
            var instance = Eval(f.Instance);
            _derefs.UnionWith(instance);
            return instance;
        }

        /// An auto-property is its backing field: no accessor body runs. One that may be
        /// overridden is not — the override's accessor may have a body.
        private static bool FieldLike(IPropertySymbol property)
        {
            if (property.IsAbstract || property.IsExtern || property.IsIndexer)
                return false;
            if ((property.IsVirtual || property.IsOverride) && !property.IsSealed && !property.ContainingType.IsSealed)
                return false;
            if (property.DeclaringSyntaxReferences.IsEmpty)
                return false;
            foreach (var reference in property.DeclaringSyntaxReferences)
                switch (reference.GetSyntax())
                {
                    case PropertyDeclarationSyntax { ExpressionBody: null, AccessorList: { } accessors }
                        when accessors.Accessors.All(a => a.Body is null && a.ExpressionBody is null):
                        continue;
                    case ParameterSyntax:   // a record's positional property
                        continue;
                    default:
                        return false;
                }
            return true;
        }

        private SortedSet<string> PropertyRead(IPropertyReferenceOperation prop)
        {
            var property = prop.Property;
            if (FieldLike(property))
            {
                if (property.IsStatic)
                {
                    StaticAccess(property.ContainingType, "static property");
                    return One("heap");
                }
                var instance = Eval(prop.Instance);
                _derefs.UnionWith(instance);
                return instance;
            }
            // the length of an array is the `ldlen` instruction, not a call
            if (property.ContainingType.SpecialType == SpecialType.System_Array
                && property.Name is "Length" or "LongLength")
            {
                _derefs.UnionWith(Eval(prop.Instance));
                return None();
            }
            if (property.GetMethod is null)
            {
                Unknown($"property {property.Name} without a getter");
                return None();
            }
            return Call(property.GetMethod, prop.Instance, ByOrdinal(property.GetMethod, prop.Arguments), prop,
                        nonVirtual: IsBaseAccess(prop.Instance));
        }

        private void Assign(IOperation target, SortedSet<string> value)
        {
            switch (target)
            {
                case ILocalReferenceOperation l when !l.Local.IsRef:
                    _locals[LocalId(l.Local)].Sources.UnionWith(Inert(l.Local.Type) ? None() : value);
                    return;
                case IParameterReferenceOperation p when !Own(p.Parameter):
                    Unknown("captured primary-constructor parameter");
                    return;
                case IParameterReferenceOperation p when _reassigned.TryGetValue(p.Parameter, out var slot):
                    _locals[slot].Sources.UnionWith(value);
                    return;
                case IParameterReferenceOperation p when p.Parameter.RefKind is RefKind.Ref or RefKind.Out:
                    // the caller's storage: written, and what goes in leaves this method
                    Write("indirect", One($"param:{p.Parameter.Ordinal}"));
                    _stores.UnionWith(value);
                    return;
                case IParameterReferenceOperation:
                    return;   // an inert value parameter: a local copy
                case IFieldReferenceOperation f when f.Field.IsStatic:
                    StaticAccess(f.Field.ContainingType, "static field");
                    Write("static", None());
                    _stores.UnionWith(value);
                    return;
                case IFieldReferenceOperation f:
                    Write("instance", Eval(f.Instance));
                    _stores.UnionWith(value);
                    return;
                case IPropertyReferenceOperation prop when FieldLike(prop.Property) || prop.Property.SetMethod is null:
                    if (!FieldLike(prop.Property) && !InOwnConstructor(prop.Property))
                    {
                        Unknown($"assignment to property {prop.Property.Name} without a setter");
                        return;
                    }
                    if (prop.Property.IsStatic)
                    {
                        StaticAccess(prop.Property.ContainingType, "static property");
                        Write("static", None());
                    }
                    else
                    {
                        Write("instance", Eval(prop.Instance));
                    }
                    _stores.UnionWith(value);
                    return;
                case IPropertyReferenceOperation prop:
                {
                    var setter = prop.Property.SetMethod!;
                    var args = ByOrdinal(setter, prop.Arguments);
                    args[setter.Parameters.Length - 1].UnionWith(value);
                    Call(setter, prop.Instance, args, prop, nonVirtual: IsBaseAccess(prop.Instance));
                    return;
                }
                case IArrayElementReferenceOperation element:
                {
                    var array = Eval(element.ArrayReference);
                    foreach (var index in element.Indices)
                        Eval(index);
                    Write("indirect", array);
                    _stores.UnionWith(value);
                    return;
                }
                case IDiscardOperation:
                    return;
                case IDeclarationExpressionOperation declaration:
                    Assign(declaration.Expression, value);
                    return;
                default:
                    Unknown($"assignment to {target.Kind}");
                    return;
            }
        }

        /// A get-only auto-property assigned in its own type's constructor writes its backing field.
        private bool InOwnConstructor(IPropertySymbol property) =>
            _method.MethodKind is MethodKind.Constructor or MethodKind.StaticConstructor
            && SymbolEqualityComparer.Default.Equals(property.ContainingType, _method.ContainingType);

        private static bool IsBaseAccess(IOperation? instance) =>
            instance?.Syntax is BaseExpressionSyntax;

        // ---- calls -----------------------------------------------------------------------

        private SortedSet<string>[] Slots(IMethodSymbol method) =>
            method.Parameters.Select(_ => None()).ToArray();

        private SortedSet<string>[] Positional(IMethodSymbol method, params IOperation[] operands)
        {
            var args = Slots(method);
            for (var i = 0; i < operands.Length && i < args.Length; i++)
                args[i].UnionWith(Eval(operands[i]));
            return args;
        }

        private SortedSet<string>[] ByOrdinal(IMethodSymbol method, ImmutableArray<IArgumentOperation> arguments)
        {
            var args = Slots(method);
            foreach (var argument in arguments)
            {
                var ordinal = argument.Parameter?.Ordinal ?? -1;
                var value = Eval(argument.Value);
                if (argument.Parameter is { RefKind: RefKind.Ref or RefKind.Out })
                    ByRef(argument.Value);
                if (ordinal < 0 || ordinal >= args.Length)
                {
                    Unknown("an argument with no parameter");
                    continue;
                }
                if (argument.ArgumentKind == ArgumentKind.ParamArray)
                    _stores.UnionWith(value);   // packed into a fresh array the callee keeps
                args[ordinal].UnionWith(value);
            }
            return args;
        }

        /// A `ref` / `out` argument: the callee may write the location. What it writes comes
        /// from the callee's own parameters (which it then stores) or from the heap.
        private void ByRef(IOperation location)
        {
            switch (location)
            {
                case IDeclarationExpressionOperation declaration:
                    ByRef(declaration.Expression);
                    return;
                case IDiscardOperation:
                    return;
                default:
                    Assign(location, One("heap"));
                    return;
            }
        }

        private SortedSet<string> Invocation(IInvocationOperation inv)
        {
            var method = inv.TargetMethod;
            if (method.MethodKind == MethodKind.LocalFunction)
            {
                Unknown("local function call");
                return None();
            }
            var nonVirtual = !inv.IsVirtual || IsBaseAccess(inv.Instance);
            return Call(method, inv.Instance, ByOrdinal(method, inv.Arguments), inv, nonVirtual);
        }

        private SortedSet<string> Creation(IObjectCreationOperation creation)
        {
            if (creation.Initializer is not null)
            {
                Unknown("object or collection initializer");
                return None();
            }
            var ctor = creation.Constructor;
            if (ctor is null)
            {
                Unknown("object creation with no constructor");
                return None();
            }
            var args = ByOrdinal(ctor, creation.Arguments);
            if (ctor.IsImplicitlyDeclared)
            {
                var type = ctor.ContainingType;
                StaticAccess(type, "constructor");
                // an implicit constructor runs the instance initializers and the base constructor
                if (HasInstanceInitializers(type)
                    || !(type.IsValueType || type.BaseType?.SpecialType == SpecialType.System_Object))
                    Unknown($"implicit constructor of {type.ToDisplayString()}");
            }
            else
            {
                Call(ctor, null, args, creation, nonVirtual: true);
            }
            return One("heap");   // a new object: its contents are not tracked, so it reads as heap
        }

        private SortedSet<string> Call(IMethodSymbol method, IOperation? instance, SortedSet<string>[] args,
                                       IOperation at, bool nonVirtual)
        {
            // `object()` is empty: the root of every constructor chain
            if (method.MethodKind == MethodKind.Constructor && method.ContainingType.SpecialType == SpecialType.System_Object)
                return None();
            if (method.ReturnsByRef || method.ReturnsByRefReadonly)
                Unknown($"call to ref-returning {Key(method)}");
            if (method.IsStatic || method.MethodKind == MethodKind.Constructor)
                StaticAccess(method.ContainingType, "member");

            var receiver = instance is null ? null : Eval(instance);
            string dispatch;
            if (method.MethodKind == MethodKind.DelegateInvoke)
                dispatch = "delegate";
            else if (!nonVirtual && (method.IsVirtual || method.IsAbstract || method.IsOverride
                                      || method.ContainingType.TypeKind == TypeKind.Interface)
                     && !(method.IsSealed || method.ContainingType.IsSealed || method.ContainingType.IsValueType))
                dispatch = "virtual";
            else if (method.ContainingType.TypeKind == TypeKind.Interface)
                dispatch = "virtual";   // a static abstract member: resolved by a type argument
            else if (method.OriginalDefinition.DeclaringSyntaxReferences.IsEmpty)
                dispatch = "extern";
            else
                dispatch = "direct";

            var id = _calls.Count;
            _calls.Add(new Dictionary<string, object?>
            {
                ["id"] = id,
                ["callee"] = Key(method),
                ["dispatch"] = dispatch,
                ["receiver"] = receiver?.ToList(),
                ["args"] = args.Select(a => a.ToList()).ToList(),
                ["line"] = at.Syntax.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
            });
            return method.ReturnsVoid || Inert(method.ReturnType) ? None() : One($"call:{id}");
        }
    }
}
