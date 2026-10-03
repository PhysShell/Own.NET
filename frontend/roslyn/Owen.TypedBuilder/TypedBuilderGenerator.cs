// The Typed Builder as a Roslyn incremental generator (OX-01, generator delivery A).
//
// For every source file that declares a [TypedProtocol] class, it runs the SAME model and
// renderer as the CLI (TypedBuilderCore.cs, linked) over that file's text and adds the result
// to the compilation. So the typed API exists in every compilation — `dotnet build`, the
// IDE's live one, a design-time build — with no build step of its own (preregistration K-3).
//
// The one difference from the CLI's bytes is a first line `#nullable enable`: a generated
// source compiles with nullable annotations off unless it says otherwise, and the rendered
// protocol uses `string?`. The rendered text after that line is the CLI's, byte for byte.
//
// A declaration the model refuses is a compiler ERROR (OWENTB001, one per defect), never an
// empty output that would leave the protocol silently missing.

using System.Collections.Generic;
using System.Collections.Immutable;
using System.IO;
using System.Linq;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

namespace Own.TypedBuilder
{
    [Generator(LanguageNames.CSharp)]
    public sealed class TypedBuilderGenerator : IIncrementalGenerator
    {
        private static readonly DiagnosticDescriptor Refused = new(
            id: "OWENTB001",
            title: "Typed Builder declaration refused",
            messageFormat: "{0}",
            category: "Owen.TypedBuilder",
            defaultSeverity: DiagnosticSeverity.Error,
            isEnabledByDefault: true);

        public void Initialize(IncrementalGeneratorInitializationContext context)
        {
            context.RegisterPostInitializationOutput(static post =>
                post.AddSource("Owen.TypedBuilder.Attributes.g.cs", SourceText.From(Attributes, Encoding.UTF8)));

            var declarations = context.SyntaxProvider
                .CreateSyntaxProvider(
                    static (node, _) => node is ClassDeclarationSyntax c && IsTypedProtocol(c),
                    static (ctx, _) => ctx.Node.SyntaxTree)
                .Collect();

            context.RegisterSourceOutput(declarations, static (spc, trees) =>
            {
                var hints = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
                foreach (var tree in trees.Distinct().OrderBy(t => t.FilePath, System.StringComparer.Ordinal))
                {
                    var file = Path.GetFileName(tree.FilePath);
                    // exactly the CLI's input: the file's text with \r\n folded to \n
                    var text = tree.GetText(spc.CancellationToken).ToString().Replace("\r\n", "\n");
                    var root = CSharpSyntaxTree.ParseText(text, cancellationToken: spc.CancellationToken)
                        .GetRoot(spc.CancellationToken);
                    var problems = new List<string>();
                    var model = Model.Read(root, file, problems);
                    if (model is null || problems.Count > 0)
                    {
                        var where = FirstDeclaration(tree);
                        foreach (var problem in problems)
                            spc.ReportDiagnostic(Diagnostic.Create(Refused, where, $"{file}: {problem}"));
                        continue;
                    }
                    var stem = Path.GetFileNameWithoutExtension(file);
                    var hint = stem + ".Protocol.g.cs";
                    for (var n = 2; !hints.Add(hint); n++)
                        hint = $"{stem}.{n}.Protocol.g.cs";
                    spc.AddSource(hint, SourceText.From("#nullable enable\n" + Emit.Render(model), Encoding.UTF8));
                }
            });
        }

        private static bool IsTypedProtocol(ClassDeclarationSyntax c) =>
            c.AttributeLists.SelectMany(l => l.Attributes).Any(a =>
            {
                var name = a.Name switch
                {
                    QualifiedNameSyntax q => q.Right.Identifier.Text,
                    AliasQualifiedNameSyntax q => q.Name.Identifier.Text,
                    SimpleNameSyntax s => s.Identifier.Text,
                    _ => a.Name.ToString(),
                };
                return name is "TypedProtocol" or "TypedProtocolAttribute";
            });

        private static Location FirstDeclaration(SyntaxTree tree)
        {
            var c = tree.GetRoot().DescendantNodes().OfType<ClassDeclarationSyntax>().FirstOrDefault(IsTypedProtocol);
            return c is null ? Location.None : c.Identifier.GetLocation();
        }

        // The vocabulary, matched by NAME by both this generator and the Owen extractor. Emitted
        // into the consumer's own compilation as internal types in the global namespace, so a
        // declaration needs no `using`, the package adds no runtime assembly, and the rendered
        // protocol (which names [ProtocolToken] / [ProtocolRegion] unqualified) is unchanged.
        private const string Attributes = @"// Generated by Owen.TypedBuilder. The Typed Builder vocabulary, matched by name.
#nullable enable

/// The entity whose state protocol is generated. A `partial class`.
[global::System.AttributeUsage(global::System.AttributeTargets.Class)]
internal sealed class TypedProtocolAttribute : global::System.Attribute
{
}

/// The one property that holds the state. Its enum's first member is the initial state.
[global::System.AttributeUsage(global::System.AttributeTargets.Property)]
internal sealed class ProtocolStateAttribute : global::System.Attribute
{
}

/// A field the builder demands before Build() exists.
[global::System.AttributeUsage(global::System.AttributeTargets.Property)]
internal sealed class BuilderRequiredAttribute : global::System.Attribute
{
}

/// A transition: its name, the state it leaves, the state it enters.
[global::System.AttributeUsage(global::System.AttributeTargets.Method)]
internal sealed class TransitionAttribute : global::System.Attribute
{
    public TransitionAttribute(string name, object from, object to)
    {
        Name = name;
        From = from;
        To = to;
    }

    public string Name { get; }

    public object From { get; }

    public object To { get; }
}

/// A state: a ref struct over the entity (Owen state-protocol profile).
[global::System.AttributeUsage(global::System.AttributeTargets.Struct)]
internal sealed class ProtocolTokenAttribute : global::System.Attribute
{
}

/// A region entry: (entity, callback) (Owen state-protocol profile).
[global::System.AttributeUsage(global::System.AttributeTargets.Method)]
internal sealed class ProtocolRegionAttribute : global::System.Attribute
{
}
";
    }
}
