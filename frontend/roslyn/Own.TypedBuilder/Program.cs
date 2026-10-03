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
using Own.TypedBuilder;

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
