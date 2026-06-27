// OwnSharp OwnIR extractor (P-001 v0).
//
// Scans C# and emits OwnIR facts (JSON) in the OwnLang spec's vocabulary; the
// Python core (`python -m ownlang ownir facts.json`) produces the verdict
// (OWN001 leak) at the C# location.
//
// Event subscriptions are resolved type-aware (P-014 Tier A): all inputs are
// parsed into ONE CSharpCompilation with the runtime's framework references, and
// a `target += handler` is a subscription only when the SemanticModel binds the
// left side to an event symbol — so `sum += value` (arithmetic) is not a leak.
// When the left side's declaring type is an unresolved external reference we do
// not guess: a handler-shaped RHS surfaces as an OWN050 "leakage analysis
// skipped" note, never a leak. A subscription is "released" by a matching
// `target -= handler` in the class; a `Tick`/`Elapsed` handler is tagged
// resource=timer (WPF002) and is released if the timer's receiver also has a
// `.Stop()` call. The IDisposable/pool/local detectors remain syntactic for now
// (P-014 rollout: the event fact goes type-aware first).
//
// Usage: ownsharp-extract <file.cs | dir | *.csproj | *.sln> [more ...] [-o facts.json]
//        ownsharp-extract --project App.csproj   (flag twin of the positional form)
//        ownsharp-extract --solution App.sln
//
// Inputs may be .cs files, directories, a .csproj, or a .sln. A directory is walked
// recursively for *.cs, skipping build output (bin/obj), VCS/vendor dirs (.git,
// node_modules) and generated files (*.g.cs, *.Designer.cs) — so you can point it at a
// whole repo (this is what the `own-check` script / GitHub Action do). A .csproj resolves
// to its source set (SDK-style directory scan + concrete linked <Compile> files; no full
// MSBuild evaluation — see ProjectCsFiles); a .sln fans out over its member projects.

using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var rawInputs = new List<string>();
string? outPath = null;
// --ref-dir <dir> (repeatable, P-014 Tier B): widen the compilation's reference set with the
// DLLs under <dir>, searched RECURSIVELY — point it at a project's built `bin/` output (or a
// restored package's `lib/`) and the SemanticModel can then bind events on third-party types
// (DevExpress, etc.) instead of surfacing them as OWN050. The first-class, scriptable twin of the
// OWN_EXTRA_REF_DIRS env var (which stays non-recursive, for framework ref packs). Roslyn reads
// metadata only, so it resolves a .NET Framework `bin/` exactly as a modern-.NET one — only the
// DLLs differ. First simple-name wins, so a TPA/framework reference is never double-added.
var refDirs = new List<string>();
// Event-subscription detection is on by default now that it is type-aware
// (P-014 Tier A graduates it from the interim off). `--no-event-leaks` opts out
// (e.g. to run only the disposable/pool detectors); it is the first instance of
// the broader check-selection surface tracked in P-015.
bool emitEvents = true;
// --flow-locals (P-016 B0b/B2, EXPERIMENTAL, default off): emit per-method flow
// facts for non-escaping local IDisposables (acquire/use/release/if/return over a
// CFG) so the core checks them path-sensitively (OWN001/002/003). Supersedes the
// flat D1 local-disposable detector when on. Default off keeps the shipped surface.
bool flowLocals = false;
// --stats (coverage): print a one-line flow-locals coverage summary to stderr
// (of the methods that have a disposable local worth checking, how many were
// flow-analysed vs honestly skipped for an unmodelled construct) and stamp the
// same counts into the facts JSON. Turns "0 findings" into "clean vs didn't-reach".
bool reportStats = false;
// --body-throw-edges (opt-in, P-016 throw tier): also treat an ESCAPING body-level may-throw
// call/`new` (not only those inside a `try`) as a dispose-not-called-on-throw point — CodeQL
// cs/dispose-not-called-on-throw parity. OFF by default: it is the CA2000 firehose (flags even
// harmless MemoryStream/StringWriter dispose-on-throw), so the shipped posture stays low-FP; the
// oracle turns it on to measure full recall. Read deep in InjectThrowEdge via the static
// Program.BodyThrowEdges (declared at end of file) rather than threaded through the flow recursion.
// Reset the static field up front so a flag from a prior IN-PROCESS invocation can't leak into a
// run that did not request it (the other config — emitEvents/flowLocals/reportStats — are locals,
// re-initialized each call, so they need no reset; only this static one does). CodeRabbit.
BodyThrowEdges = false;
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "-o" && i + 1 < args.Length) outPath = args[++i];
    // `--project <App.csproj>` / `--solution <App.sln>`: the explicit-flag twin of passing the
    // project/solution as a positional input (both resolve through Expand). The flag form matches
    // the advertised `ownsharp extract --project ...` UX borrowed from the roslyn-tools CLI shape;
    // the positional form keeps the command unambiguous next to dotnet's own `run --project`.
    else if ((args[i] == "--project" || args[i] == "--solution") && i + 1 < args.Length) rawInputs.Add(args[++i]);
    else if (args[i] == "--ref-dir" && i + 1 < args.Length) refDirs.Add(args[++i]);
    else if (args[i] == "--no-event-leaks") emitEvents = false;
    else if (args[i] == "--flow-locals") flowLocals = true;
    else if (args[i] == "--body-throw-edges") BodyThrowEdges = true;
    else if (args[i] == "--stats") reportStats = true;
    else rawInputs.Add(args[i]);
}

if (rawInputs.Count == 0)
{
    Console.Error.WriteLine("usage: ownsharp-extract <file.cs | dir | *.csproj | *.sln> [...] [-o facts.json] [--ref-dir <bin-dir>]");
    return 2;
}

// --stats reports flow-locals coverage; the counters only move inside the
// --flow-locals pass. Without it they would all be zero and the summary would
// read "0/0 methods flow-analysed" — the exact ambiguous zero --stats exists to
// kill (e.g. `own-check.sh --legacy --stats`). Refuse the contradictory combo.
if (reportStats && !flowLocals)
{
    Console.Error.WriteLine("ownsharp-extract: --stats requires --flow-locals");
    return 2;
}

// --body-throw-edges only injects edges during the --flow-locals pass; without it it is a no-op.
// Warn (non-fatal) rather than fail — it is an additive recall knob layered on flow, not a mode.
if (BodyThrowEdges && !flowLocals)
    Console.Error.WriteLine("ownsharp-extract: --body-throw-edges has no effect without --flow-locals");

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

// Translate an MSBuild item spec (a path, optionally with `*`, `?`, `**` globs and either
// separator) into a predicate over a full file path, evaluated RELATIVE to the project dir.
// Enough for the common `<Compile Include>` / `<Compile Remove>` forms (a concrete path, `*.cs`,
// `**/*.cs`, `Folder/**`) without a full MSBuild glob engine: `**` matches across directories,
// `*` / `?` within a single path segment. Match is case-insensitive (MSBuild globbing is).
static Func<string, bool> SpecMatcher(string spec, string dir)
{
    var glob = spec.Replace('\\', '/').Trim();
    var rx = new StringBuilder("^");
    for (int i = 0; i < glob.Length; i++)
    {
        var c = glob[i];
        if (c == '*')
        {
            if (i + 1 < glob.Length && glob[i + 1] == '*')       // `**` -> any chars, including '/'
            {
                rx.Append(".*");
                i++;
                if (i + 1 < glob.Length && glob[i + 1] == '/') i++;   // swallow the slash after `**`
            }
            else rx.Append("[^/]*");                              // `*` -> within one path segment
        }
        else if (c == '?') rx.Append("[^/]");
        else rx.Append(Regex.Escape(c.ToString()));
    }
    rx.Append('$');
    // `.csproj` content is untrusted in CI, and adjacent wildcards (`**/**`, `**/*`) translate to
    // ambiguous adjacent quantifiers the backtracking .NET engine can blow up on (ReDoS). Bound the
    // match with a timeout, and treat a timeout as "no match" rather than letting it crash the run.
    var regex = new Regex(rx.ToString(), RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1));
    return path =>
    {
        var rel = Path.GetRelativePath(dir, path).Replace('\\', '/');
        try { return regex.IsMatch(rel); }
        catch (RegexMatchTimeoutException)
        {
            Console.Error.WriteLine($"ownsharp-extract: glob match timed out for '{spec}' on '{rel}'; treated as no match");
            return false;
        }
    };
}

// Resolve a `.csproj` to its C# source set. Doing this the MSBuild way needs a full
// project evaluation (and the `Microsoft.CodeAnalysis.Workspaces.MSBuild` + MSBuildLocator
// dependency that P-014 / the "ProjectDependencies as a category" note deliberately parks
// for the DI/solution-graph work — not for the v0 leak extractor). The pragmatic resolution
// that covers the SDK-style common case WITHOUT that baggage:
//   - candidates = every in-tree *.cs (SDK default-compile-items), with bin/obj and generated
//     files already excluded by IsSkipped;
//   - but honour the project's explicit compile set: `<EnableDefaultCompileItems>false` turns the
//     default OFF (then only files an explicit `<Compile Include>` selects are kept), and
//     `<Compile Remove="...">` subtracts excluded files — so `.csproj` input does not emit findings
//     from files the project does not actually compile (CodeRabbit: a source-set mismatch, not a
//     harmless over-approximation);
//   - plus any concrete linked `<Compile Include="..\Shared\Foo.cs" />` that points OUTSIDE the tree.
// Include/Remove globs are matched by SpecMatcher (not a full MSBuild engine, but enough for the
// common forms). Builds a list rather than yielding so the XML read can sit in a try/catch (an
// iterator may not yield from inside one); a malformed project degrades to the plain directory scan.
static List<string> ProjectCsFiles(string csproj, EnumerationOptions opts)
{
    var full = Path.GetFullPath(csproj);
    var result = new List<string>();
    // A missing project file must NOT degrade to "scan its parent directory": a typo'd
    // `--project src/Missing.csproj` would otherwise analyse all of src/**/*.cs (an
    // unintended source set), or throw if the parent is absent too. Skip the bad input with
    // a warning — the directory-scan fallback below is only for a PRESENT-but-malformed
    // project (whose <Compile> items we could not read), never an absent one. (Codex P2.)
    if (!File.Exists(full))
    {
        Console.Error.WriteLine($"ownsharp-extract: project not found: {csproj}");
        return result;
    }
    var dir = Path.GetDirectoryName(full) ?? ".";

    XDocument? doc = null;
    try { doc = XDocument.Load(full); }
    catch (Exception ex)
    {
        Console.Error.WriteLine(
            $"ownsharp-extract: {csproj}: reading <Compile> items failed ({ex.Message}); used directory scan only");
    }
    var elements = (doc?.Descendants() ?? Enumerable.Empty<XElement>()).ToList();

    // `<EnableDefaultCompileItems>false</…>` (last value wins, as MSBuild evaluates top-to-bottom)
    // turns off the implicit "every *.cs is compiled" default.
    var defaultItems = elements
        .Where(e => e.Name.LocalName == "EnableDefaultCompileItems")
        .Select(e => e.Value.Trim())
        .LastOrDefault();
    var defaultCompile = !string.Equals(defaultItems, "false", StringComparison.OrdinalIgnoreCase);

    var includes = elements.Where(e => e.Name.LocalName == "Compile")
        .Select(e => e.Attribute("Include")?.Value)
        .Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v!).ToList();
    var removes = elements.Where(e => e.Name.LocalName == "Compile")
        .Select(e => e.Attribute("Remove")?.Value)
        .Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v!).ToList();

    var candidates = Directory.EnumerateFiles(dir, "*.cs", opts).Where(f => !IsSkipped(f)).ToList();
    if (defaultCompile)
        result.AddRange(candidates);
    else
    {
        // Explicit-list project: keep only in-tree files an `<Compile Include>` selects.
        var incMatch = includes.Select(s => SpecMatcher(s, dir)).ToList();
        result.AddRange(candidates.Where(f => incMatch.Any(m => m(f))));
    }

    // Concrete linked `<Compile Include>` that points OUTSIDE the project tree, in either mode.
    var dirPrefix = dir.EndsWith(Path.DirectorySeparatorChar) ? dir : dir + Path.DirectorySeparatorChar;
    foreach (var inc in includes)
    {
        if (inc.IndexOfAny(new[] { '*', '?' }) >= 0) continue;            // a glob — handled above / by the scan
        var path = Path.GetFullPath(Path.Combine(dir, inc.Replace('\\', Path.DirectorySeparatorChar)));
        if (path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase)
            && File.Exists(path) && !IsSkipped(path)
            && !path.StartsWith(dirPrefix, StringComparison.Ordinal))    // in-tree links already added
            result.Add(path);
    }

    // Honour `<Compile Remove="...">`: drop excluded files (concrete or glob, relative to the dir).
    if (removes.Count > 0)
    {
        var rmMatch = removes.Select(s => SpecMatcher(s, dir)).ToList();
        result.RemoveAll(f => rmMatch.Any(m => m(f)));
    }

    return result.Distinct().ToList();
}

// Extract the double-quoted fields from a solution `Project(...)` line tail, in order. The fields
// are `"Name", "relpath", "{guid}"`; splitting on quotes (not raw commas) means a comma INSIDE a
// quoted name or path no longer misreads the line — CodeRabbit flagged the naive `Split(',')`,
// which could skip a valid project or resolve the wrong path. (`.sln` does not use `""` escaping.)
static List<string> QuotedFields(string s)
{
    var fields = new List<string>();
    int i = 0;
    while (true)
    {
        int a = s.IndexOf('"', i);
        if (a < 0) break;
        int b = s.IndexOf('"', a + 1);
        if (b < 0) break;
        fields.Add(s.Substring(a + 1, b - a - 1));
        i = b + 1;
    }
    return fields;
}

// Resolve a classic `.sln` to its member `.csproj` paths. The solution file lists each project
// as `Project("{type-guid}") = "Name", "rel\path.csproj", "{guid}"`; solution folders use the
// same line shape but their path is not a `.csproj`, so filtering on the extension drops them.
// Text parsing (no MSBuild) keeps this dependency-free; a missing member is reported and skipped,
// never fatal — a solution-wide scan should survive one stale project reference.
static List<string> SolutionProjects(string sln)
{
    var dir = Path.GetDirectoryName(Path.GetFullPath(sln)) ?? ".";
    var projects = new List<string>();
    string[] lines;
    try { lines = File.ReadAllLines(sln); }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"ownsharp-extract: cannot read solution {sln} ({ex.Message})");
        return projects;
    }
    foreach (var line in lines)
    {
        var t = line.TrimStart();
        if (!t.StartsWith("Project(", StringComparison.Ordinal)) continue;
        var eq = t.IndexOf('=');
        if (eq < 0) continue;
        // The path is the SECOND double-quoted field after '=' ("Name", "relpath", "{guid}");
        // quote-aware extraction tolerates a comma inside the name or path.
        var fields = QuotedFields(t.Substring(eq + 1));
        if (fields.Count < 2) continue;
        var rel = fields[1].Trim();
        if (!rel.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase)) continue;
        var path = Path.GetFullPath(Path.Combine(dir, rel.Replace('\\', Path.DirectorySeparatorChar)));
        if (File.Exists(path)) projects.Add(path);
        else Console.Error.WriteLine($"ownsharp-extract: {sln}: project not found: {rel}");
    }
    return projects;
}

// Expand inputs into their .cs files. A directory is walked recursively; a `.csproj`/`.sln`
// is resolved to its source set (so `ownsharp-extract App.csproj` / `App.sln` works, the
// CLI-first project input borrowed from the roslyn-tools tooling shape); an explicit file
// passes through as-is. IgnoreInaccessible tolerates an unreadable subdir mid-walk (otherwise
// the whole scan would abort with an unhandled exception on a locked directory).
static IEnumerable<string> Expand(IEnumerable<string> roots)
{
    var opts = new EnumerationOptions
    {
        RecurseSubdirectories = true,
        IgnoreInaccessible = true,
    };
    foreach (var p in roots)
    {
        if (Directory.Exists(p))
        {
            foreach (var f in Directory.EnumerateFiles(p, "*.cs", opts))
                if (!IsSkipped(f))
                    yield return f;
        }
        else if (p.EndsWith(".sln", StringComparison.OrdinalIgnoreCase))
        {
            foreach (var proj in SolutionProjects(p))
                foreach (var f in ProjectCsFiles(proj, opts))
                    yield return f;
        }
        else if (p.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase))
        {
            foreach (var f in ProjectCsFiles(p, opts))
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

// P-004 self-owned exemption: is the event SOURCE owned by (and so never longer-
// lived than) the subscriber? True for a bare instance event on `this`, or a
// receiver that resolves to a field/local the class OWNS. "Owns" is the `owned`
// set the caller computes: fields the class constructs directly (`new`), builds
// indirectly through a `ref`/`out` helper, or fetches as one of its own template
// parts. Such a `source <-> this` reference cycle is GC-collectable, so the
// subscription is not a leak. The receiver is resolved to a SYMBOL (not matched by
// text), and `owned` is AST-based — not a regex. NOTE: callers must exclude timers
// — a *running* timer is rooted by the dispatcher regardless of who owns the field.
static bool IsSelfOwnedSource(ExpressionSyntax left, IEventSymbol ev,
                              SemanticModel model, HashSet<string> owned)
{
    if (left is not MemberAccessExpressionSyntax m)
        return !ev.IsStatic;   // bare event => an instance event on `this`
    if (m.Expression is ThisExpressionSyntax)
        return true;
    var recv = model.GetSymbolInfo(m.Expression).Symbol;
    return (recv is IFieldSymbol or ILocalSymbol) && owned.Contains(recv.Name);
}

// P-004 (ext): a control fetching one of its OWN template parts —
// `GetTemplateChild("PART_x")` or `[Template.]FindName(...)`, optionally behind a
// cast or `as` — owns the result (it lives inside the control's own template /
// visual tree). AST-only (matched by call name), in the spirit of the rest of the
// file; used to fold template-part fields into the self-owned exemption.
static bool IsTemplatePartFetch(ExpressionSyntax? expr)
{
    expr = expr switch
    {
        CastExpressionSyntax c => c.Expression,
        BinaryExpressionSyntax b when b.IsKind(SyntaxKind.AsExpression) => b.Left,
        _ => expr,
    };
    return expr is InvocationExpressionSyntax inv
        && (inv.Expression switch
           {
               MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
               IdentifierNameSyntax id => id.Identifier.Text,
               _ => null,
           }) is "GetTemplateChild" or "FindName";
}

// P-004 static-handler exemption: a `+= StaticMethod` stores a delegate whose
// Target is null, so no instance is retained — the subscription cannot leak a
// subscriber, however long-lived the source. Only method-group handlers
// (identifier / member access) are judged; lambdas and delegate-typed values may
// capture state and are left as leak candidates. A method group's symbol can surface
// as a MEMBER GROUP (Symbol == null, CandidateSymbols populated) instead of the bound
// method, so fall back to the candidates — else a genuinely static-method handler is
// missed and a static-source subscription that retains NO instance is mis-reported as
// a region escape (mined: ImageSharp MemoryAllocatorValidator's static MemoryDiagnostics
// handlers). When falling back, require ALL candidates static so an overload set that
// mixes a static and an instance method is not wrongly exempted.
static bool IsStaticHandler(ExpressionSyntax right, SemanticModel model)
{
    if (!IsHandler(right))
        return false;
    var info = model.GetSymbolInfo(right);
    if (info.Symbol is { } s)
        return s is IMethodSymbol { IsStatic: true };
    var cands = info.CandidateSymbols;
    return cands.Length > 0 && cands.All(c => c is IMethodSymbol { IsStatic: true });
}

// P-004 process-lifetime exemption: a subscription to a PROCESS-HOST `System.AppDomain`
// event — ProcessExit / DomainUnload (shutdown cleanup hooks) or UnhandledException /
// FirstChanceException (process-wide diagnostics) — is never a region escape. The handler
// is MEANT to live for the whole process: it runs at shutdown, or on every unhandled throw,
// and the AppDomain IS the process host. Promoting the subscriber to "the AppDomain's
// lifetime" is therefore the intent, not a leak. Mined: Npgsql's PoolManager static ctor
// `AppDomain.CurrentDomain.{DomainUnload,ProcessExit} += (_,_) => ClearAll()` — a deliberate
// "close idle connectors on appdomain unload (web-app redeployment)" hook (#491).
static bool IsProcessLifetimeAppDomainEvent(IEventSymbol ev) =>
    ev.Name is "ProcessExit" or "DomainUnload" or "UnhandledException" or "FirstChanceException"
    && ev.ContainingType is { Name: "AppDomain" } ct
    && IsInNamespace(ct, "System");

// Does this handler retain NO subscriber instance? A static method group has a null delegate
// target; a lambda / anonymous method retains nothing only when it captures neither `this`
// (explicit, or implicit via an instance member) nor an enclosing local/parameter. Keeps the
// AppDomain process-lifetime exemption sound — a CAPTURING handler is still pinned to the
// process until shutdown and stays OWN014 (Codex); only a non-capturing one (Npgsql's
// `(_,_) => ClearAll()`, a static call) is safe to drop.
static bool HandlerRetainsNoInstance(ExpressionSyntax right, SemanticModel model)
{
    if (IsStaticHandler(right, model))
        return true;
    if (right is not AnonymousFunctionExpressionSyntax lambda)
        return false;   // a delegate-typed value is opaque -> conservatively assume it captures
    foreach (var node in lambda.DescendantNodes())
    {
        if (node is ThisExpressionSyntax or BaseExpressionSyntax)
            return false;
        if (node is not IdentifierNameSyntax id
            || (id.Parent is MemberAccessExpressionSyntax m && m.Name == id))   // `x.Member`: name resolved via x
            continue;
        var sym = model.GetSymbolInfo(id).Symbol;
        if (sym is IFieldSymbol { IsStatic: false } or IPropertySymbol { IsStatic: false }
                or IEventSymbol { IsStatic: false }
                or IMethodSymbol { IsStatic: false, MethodKind: MethodKind.Ordinary })
            return false;   // an instance member by SIMPLE name -> implicit `this` capture
        if (sym is ILocalSymbol or IParameterSymbol && !DeclaredWithin(sym, lambda))
            return false;   // an enclosing local / parameter -> captured
    }
    return true;
}

// Is EVERY declaration of `sym` inside `scope`? A lambda's own parameters/locals are; an
// enclosing local/parameter is not — so a reference to the latter is a capture.
static bool DeclaredWithin(ISymbol sym, SyntaxNode scope)
{
    if (sym.DeclaringSyntaxReferences.Length == 0)
        return false;
    foreach (var r in sym.DeclaringSyntaxReferences)
        if (!scope.FullSpan.Contains(r.Span))
            return false;
    return true;
}

// P-004 process-lived-subscriber exemption: the WPF application object (`App`) is a
// process-lived singleton — exactly one instance, created at startup, alive until
// the process exits. Subscribing it to a process-lived static event
// (`AppDomain.CurrentDomain.UnhandledException`, `SystemEvents.*`) promotes nothing:
// its "leaked" lifetime already equals the process. So a static-source region escape
// (OWN014) raised from inside `App` is a false positive (found mining ScreenToGif
// and its bundled Translator tool, both flagged on the textbook unhandled-exception
// hook). Detected syntactically because WPF does not resolve on the Linux runner:
// either the class derives from `Application` / `System.Windows.Application`, or it
// is the conventional XAML-split `partial class App` (whose `: Application` lives in
// the generated `App.g.cs` partial the extractor never sees). Only the STATIC-source
// escape is suppressed; an instance-field subscription leak inside `App` still fires.
static bool IsProcessLivedApplication(TypeDeclarationSyntax cls)
{
    if (cls.BaseList is { } bl)
        foreach (var bt in bl.Types)
        {
            var n = bt.Type switch
            {
                IdentifierNameSyntax id => id.Identifier.Text,
                QualifiedNameSyntax q => q.Right.Identifier.Text,
                AliasQualifiedNameSyntax aq => aq.Name.Identifier.Text,
                _ => null,
            };
            if (n is "Application")
                return true;
        }
    return cls.Identifier.Text == "App"
        && cls.Modifiers.Any(m => m.IsKind(SyntaxKind.PartialKeyword));
}

// P-004 WPF MVVM ownership: a field read from `this.DataContext`, optionally through
// an `as`/cast (`DataContext as VM`, `(VM)DataContext`). Combined with a view whose
// own XAML CONSTRUCTS its DataContext, such a field is the view's owned view-model.
static bool ReadsDataContext(ExpressionSyntax expr)
{
    expr = expr switch
    {
        BinaryExpressionSyntax b when b.IsKind(SyntaxKind.AsExpression) => b.Left,
        CastExpressionSyntax c => c.Expression,
        _ => expr,
    };
    return expr switch
    {
        IdentifierNameSyntax id => id.Identifier.Text == "DataContext",
        MemberAccessExpressionSyntax m => m.Name.Identifier.Text == "DataContext"
            && m.Expression is ThisExpressionSyntax,
        _ => false,
    };
}

// P-004 WPF MVVM ownership: does this XAML construct its own DataContext inline —
// `<Root.DataContext><vm:Foo/></Root.DataContext>` — so the view OWNS its view-model
// (a collectable view<->VM cycle)? Parsed structurally (XAML is XML), restricted to the
// ROOT element's own DataContext: the code-behind's `this.DataContext` is the root's, so
// a nested `<Grid.DataContext><ChildVm/>` (a different element's) must NOT exempt the
// view (Codex / CodeRabbit) — else a real leak on the root's injected VM is dropped.
// True only when the root's DataContext child is a constructed object that the view owns:
// NOT a binding / resource reference, and NOT an `x:`-namespace language object
// (`x:Static`, `x:Null`, `x:Reference`, ...), which name an external/shared value. A
// malformed `.xaml` yields false (conservative — no exemption, never a dropped leak).
static bool XamlDeclaresOwnedDataContext(string xaml)
{
    XDocument doc;
    try { doc = XDocument.Parse(xaml); }
    catch (System.Xml.XmlException) { return false; }
    var root = doc.Root;
    if (root is null)
        return false;
    // The root's OWN `<Root.DataContext>` property-element (a direct child of the root,
    // in the root's namespace) — not a nested element's, not another property.
    var dc = root.Element(root.Name.Namespace + (root.Name.LocalName + ".DataContext"));
    var child = dc?.Elements().FirstOrDefault();
    if (child is null)
        return false;
    if (child.Name.NamespaceName == "http://schemas.microsoft.com/winfx/2006/xaml")
        return false;   // x:Static / x:Null / x:Reference / x:Type / ...
    return child.Name.LocalName is not ("Binding" or "MultiBinding" or "PriorityBinding"
        or "StaticResource" or "DynamicResource" or "RelativeSource"
        or "TemplateBinding" or "Reference" or "Null");
}

// P-004 severity tiering: of the subscriptions that survive the self-owned and
// static-handler exemptions (and are not timers), how long-lived is the event
// SOURCE? A static event lives for the whole process, so an undetached handler is
// a provable leak -> "static". A local that is CONSTRUCTED right here (`var p =
// new Publisher(); p.X += h`) dies with the scope -> "local" (the caller drops it;
// not a heap leak). But a local that merely ALIASES something else (`var src =
// _bus; src.X += h`) has unknown provenance — it may hold a long-lived injected
// source — so it is NOT dropped. Everything else (an instance field / property /
// injected parameter, or such an aliasing local) has UNKNOWN lifetime ->
// "injected": it MIGHT outlive `this`, but we cannot prove it without ownership
// modelling, so the core renders it a warning (not a hard error) until that lands.
static string SubscriptionSourceKind(ExpressionSyntax left, IEventSymbol ev,
                                     SemanticModel model)
{
    if (ev.IsStatic)
        return "static";
    if (left is MemberAccessExpressionSyntax m)
    {
        var recv = model.GetSymbolInfo(m.Expression).Symbol;
        if (recv is ILocalSymbol local)
        {
            // Method-bounded (droppable) ONLY when the local is the publisher this
            // scope constructs (`var p = new Publisher()`), which dies with it. A
            // local initialised from anything else (a field, a parameter, a call)
            // may alias a long-lived source, so we cannot prove it bounded — fall
            // through to "injected" and warn rather than silently drop a real leak.
            var constructedHere = local.DeclaringSyntaxReferences
                .Select(r => r.GetSyntax())
                .OfType<VariableDeclaratorSyntax>()
                .Any(v => v.Initializer?.Value is ObjectCreationExpressionSyntax
                                               or ImplicitObjectCreationExpressionSyntax);
            if (constructedHere)
                return "local";
        }
        if (recv is IFieldSymbol { IsStatic: true } or IPropertySymbol { IsStatic: true })
            return "static";
    }
    return "injected";
}

// A lambda / anonymous-method handler stores no named delegate, so the
// subscription can NEVER be undone with `-=` (you would have had to cache the
// delegate in a field). A particularly sharp leak shape worth calling out.
static bool IsLambdaHandler(ExpressionSyntax right) =>
    right is AnonymousFunctionExpressionSyntax;

// P-004 source-lifetime tier for an ignored `.Subscribe()` chain (WPF004). A
// self-rooted `this.WhenAnyValue(p => p.SelfProp).<self-preserving ops>.Subscribe`
// watches the component's OWN property: the observable, its handler and `this`
// form one cycle the GC collects together, so it is NOT a leak. We classify ONLY
// this unambiguous self-cycle (the bridge drops a `source: "self"` subscribe).
// Anything else stays a flagged leak (conservative). Purely syntactic.

// A single-source operator whose arguments are only funcs / schedulers / scalars,
// so it cannot mix in an EXTERNAL observable. A combinator NOT listed here
// (CombineLatest, Merge, SelectMany, WithLatestFrom, Zip, Switch, Concat, ...), an
// operator with an observable-taking overload (Throttle/Buffer/Sample/TakeUntil/
// Window), or any unknown operator is treated as possibly external -> the chain
// stays flagged. (Conservative: an unrecognised op never silences a real leak.)
static bool IsSelfPreservingOp(string name) =>
    name is "Select" or "Where" or "Do" or "Skip" or "Take" or "SkipWhile"
        or "TakeWhile" or "ObserveOn" or "SubscribeOn" or "DistinctUntilChanged"
        or "WhereNotNull" or "Cast" or "OfType" or "StartWith" or "Scan"
        or "Finally" or "AsObservable" or "Synchronize" or "Timestamp";

// One WhenAnyValue selector `p => p.Member` rooted at the lambda parameter — a
// single-hop self property. NOT `p => p.A.B` (a path through a possibly-injected
// object that can keep `this` alive — a real leak), and NOT a result-combiner
// lambda (`(a, b) => ...`). Purely syntactic.
static bool IsSelfMemberSelector(ArgumentSyntax arg) =>
    arg.Expression is SimpleLambdaExpressionSyntax lam
        && lam.Body is MemberAccessExpressionSyntax body
        && body.Expression is IdentifierNameSyntax pid
        && pid.Identifier.Text == lam.Parameter.Identifier.Text;

static bool IsSelfRootedWhenAny(ExpressionSyntax chain)
{
    // Walk the fluent chain leftwards. The HEAD must be `this.WhenAnyValue(...)`;
    // EVERY downstream operator must be self-preserving (no external observable),
    // else a later `.CombineLatest(_bus.X)` / `.SelectMany(_ => _bus.Y)` roots the
    // subscription externally and it must stay flagged (codex P1).
    var e = chain;
    while (e is InvocationExpressionSyntax iv
           && iv.Expression is MemberAccessExpressionSyntax ma)
    {
        if (ma.Expression is ThisExpressionSyntax)
        {
            // Head: `this.WhenAnyValue(p => p.Member[, q => q.Other, ...])`. A
            // self-cycle requires WhenAnyValue with one-or-more single-hop
            // self-member selectors — each roots at `this`. `p => p.A.B` (a path
            // through a possibly-injected object) and a result-combiner overload
            // (`..., (a, b) => ...`) stay flagged. Multi-arg over own properties
            // observes only `this`, the SAME self-cycle as single-arg (see
            // docs/notes/self-whenany-precision.md).
            if (ma.Name.Identifier.Text != "WhenAnyValue"
                || iv.ArgumentList.Arguments.Count < 1)
                return false;
            foreach (var arg in iv.ArgumentList.Arguments)
                if (!IsSelfMemberSelector(arg))
                    return false;
            return true;
        }
        if (!IsSelfPreservingOp(ma.Name.Identifier.Text))
            return false;          // a combinator / unknown op -> possibly external
        e = ma.Expression;
    }
    return false;                  // not a `this.WhenAnyValue(...)`-headed chain
}

// --- P-016 B0b/B2: flow lowering for local IDisposables (experimental) ---

// A type that implements System.IDisposable (semantic) — the flow lowering tracks
// locals of such types.
static bool ImplementsIDisposable(ITypeSymbol? t) =>
    t is not null
    && ((t.Name == "IDisposable" && t.ContainingNamespace?.ToString() == "System")
        || t.AllInterfaces.Any(i => i.Name == "IDisposable"
                                    && i.ContainingNamespace?.ToString() == "System"));

// The ignored result of a member `.Subscribe(...)` is a leakable IDisposable token (WPF004) only
// when the call RETURNS an IDisposable — the Rx `IObservable<T>.Subscribe()` shape. A RESOLVED void
// / non-IDisposable return has no token to leak: StackExchange.Redis's `ISubscriber.Subscribe(channel,
// handler, flags)` returns void, as do many event-bus `Subscribe(handler)` APIs. Only an UNRESOLVED
// return type keeps the syntactic benefit of the doubt (mirrors IsOwnedDisposableType, #83). Mined:
// StackExchange.Redis ConnectionMultiplexer.Sentinel `sub.Subscribe(channel, handler, FireAndForget)`.
static bool SubscribeResultIsDisposable(ITypeSymbol? rt) =>
    rt is null or IErrorTypeSymbol
    || rt.TypeKind == TypeKind.Dynamic   // a `dynamic` receiver -> dynamic return; can't prove non-disposable (Codex)
    || ImplementsIDisposable(rt);

// Types that implement IDisposable but whose disposal is conventionally OPTIONAL —
// the .NET guidance / Roslyn CA2000 exempt them: Task/ValueTask only hold a
// lazily-allocated wait handle, and the System.Data containers' Dispose() is a
// no-op. The flow detector must not flag an undisposed local of these (this is the
// curated exemption the flat D1 detector gets for free via IsDisposableType, which
// is exactly why D1 never flagged Task/DataTable and the semantic path did).
static bool IsDisposeOptional(ITypeSymbol t)
{
    var ns = t.ContainingNamespace?.ToString();
    return (ns == "System.Threading.Tasks" && t.Name is "Task" or "ValueTask")
        || (ns == "System.Data" && t.Name is "DataTable" or "DataSet" or "DataView");
}

// A type that is System.Windows.Forms.Form or derives from it (semantic, walks the
// base chain). A modeless `Form.Show()` transfers ownership to the framework, which
// disposes the form on close — EmitFlowExpr models that show as a release.
static bool DerivesFromWinFormsForm(ITypeSymbol? t)
{
    for (var b = t; b is not null; b = b.BaseType)
        if (b.Name == "Form" && b.ContainingNamespace?.ToString() == "System.Windows.Forms")
            return true;
    return false;
}

// A type that derives from System.Diagnostics.Tracing.EventSource (semantic, walks the
// base chain). An EventSource is the canonical process-lived `static readonly Log`
// diagnostics singleton; its DiagnosticCounter fields are owned by it (IsEventSourceOwnedCounter).
static bool DerivesFromEventSource(ITypeSymbol? t)
{
    for (var b = t; b is not null; b = b.BaseType)
        if (b.Name == "EventSource" && b.ContainingNamespace?.ToString() == "System.Diagnostics.Tracing")
            return true;
    return false;
}

// A type that derives from System.Diagnostics.Tracing.DiagnosticCounter — the abstract base of
// EventCounter / IncrementingEventCounter / PollingCounter / IncrementingPollingCounter.
static bool DerivesFromDiagnosticCounter(ITypeSymbol? t)
{
    for (var b = t; b is not null; b = b.BaseType)
        if (b.Name == "DiagnosticCounter" && b.ContainingNamespace?.ToString() == "System.Diagnostics.Tracing")
            return true;
    return false;
}

// P-004 EventSource-owned diagnostic counter. A DiagnosticCounter created with `this` — the
// parent EventSource — as its owner argument REGISTERS the counter with that source: the
// runtime's CounterGroup pins it to the EventSource's lifetime, and an EventSource is a
// process-lived `static readonly Log` singleton, so the counter is a process-lived diagnostic
// that is idiomatically NEVER field-disposed (every BCL EventSource — RuntimeEventSource, the
// ASP.NET / HttpConnection counters — does exactly this). Reporting such a field as an
// undisposed leak is therefore a false positive. Mined: Npgsql's NpgsqlEventSource (eight
// counters built in OnEventCommand, none field-disposed).
static bool IsEventSourceOwnedCounter(BaseObjectCreationExpressionSyntax oce, SemanticModel model) =>
    oce.ArgumentList is { } args
    && args.Arguments.Any(arg => arg.Expression is ThisExpressionSyntax)
    && DerivesFromDiagnosticCounter(model.GetTypeInfo(oce).Type);

static string MethodName(BaseMethodDeclarationSyntax m) => m switch
{
    MethodDeclarationSyntax md => md.Identifier.Text,
    ConstructorDeclarationSyntax => ".ctor",
    _ => "?",
};

// P-005 D5.2: a FIRST-PARTY method call whose result is an owned IDisposable — the
// caller side of a fresh-returning factory. Because the callee is defined in source (not
// the BCL), the core can see its body and infer whether it returns `fresh`; if so, a
// `var r = Factory()` binding is an acquire and a caller that drops `r` leaks. The emitted
// `callee` matches the `functions[]` key `{TypeName}.{MethodName}`. A null/extern symbol,
// a void/non-disposable return, or a dispose-optional return is rejected (no claim); an
// overload (non-unique name) resolves to `unknown` in the core and is silently safe.
static bool IsFirstPartyDisposableFactory(ExpressionSyntax? expr, SemanticModel model, out string callee)
{
    callee = "";
    if (expr is not InvocationExpressionSyntax inv)
        return false;
    if (model.GetSymbolInfo(inv).Symbol is not IMethodSymbol m)
        return false;
    if (m.ReturnsVoid || m.DeclaringSyntaxReferences.Length == 0)
        return false;   // void, or not first-party (no visible body to infer `fresh` from)
    if (!ImplementsIDisposable(m.ReturnType) || IsDisposeOptional(m.ReturnType))
        return false;
    // Fully-qualified key (namespace + containing-type chain) so the call resolves to the
    // RIGHT summary: two `StreamFactory.Make` in different namespaces must not alias, or a
    // call to a non-fresh one could pick up a fresh one's summary and fabricate OWN001
    // (Codex). Must match the `functions[]` name built by `FlowFunctionName`.
    callee = $"{m.ContainingType.ToDisplayString()}.{m.Name}";
    return true;
}

// The fully-qualified `functions[]` key for a method — `{Namespace.Containing.Type}.{Name}` —
// used both as the flow-function name and as a D5.2 call callee, so the two always agree (a
// simple `{Type}.{Name}` would alias same-named types across namespaces). Falls back to the
// syntactic class name only if the symbol cannot be resolved.
static string FlowFunctionName(BaseMethodDeclarationSyntax method, string fallbackType,
                               SemanticModel model) =>
    model.GetDeclaredSymbol(method) is IMethodSymbol ms
        ? $"{ms.ContainingType.ToDisplayString()}.{ms.Name}"
        : $"{fallbackType}.{MethodName(method)}";

// P-005 D5.4 (T4 wrap/adopt): the set of OWNING fields a first-party type disposes
// UNCONDITIONALLY in its `Dispose()` — i.e. a `_f.Dispose()` / `_f?.Dispose()` /
// `this._f.Dispose()` that is a TOP-LEVEL statement of the Dispose body (not nested in an
// if/try/loop), where `_f` resolves to an instance field of `w`. Conditional or nested
// disposes are excluded: if the field is only *sometimes* disposed, claiming the arg is
// adopted could fabricate a false double-dispose, so precision-first declines it (§11
// must-only). Used to verify a ctor-adopt before emitting an `alias_join`.
static HashSet<ISymbol> DisposedOwningFields(INamedTypeSymbol w, SemanticModel model)
{
    var result = new HashSet<ISymbol>(SymbolEqualityComparer.Default);
    var dispose = w.GetMembers("Dispose").OfType<IMethodSymbol>()
        .FirstOrDefault(m => m.Parameters.Length == 0 && m.ReturnsVoid
                             && m.DeclaringSyntaxReferences.Length > 0);
    if (dispose is null)
        return result;
    if (dispose.DeclaringSyntaxReferences[0].GetSyntax() is not MethodDeclarationSyntax mds
        || mds.Body is not { } body)
        return result;
    var dm = model.Compilation.GetSemanticModel(mds.SyntaxTree);
    foreach (var st in body.Statements)            // TOP-LEVEL statements only
    {
        if (st is not ExpressionStatementSyntax es)
            continue;
        // unwrap the disposed receiver from `recv.Dispose()` or `recv?.Dispose()` — the
        // latter parses as a ConditionalAccess at the statement level, not an Invocation.
        ExpressionSyntax? recv = es.Expression switch
        {
            InvocationExpressionSyntax { Expression: MemberAccessExpressionSyntax ma }
                when ma.Name.Identifier.Text is "Dispose" => ma.Expression,
            ConditionalAccessExpressionSyntax
                { WhenNotNull: InvocationExpressionSyntax
                    { Expression: MemberBindingExpressionSyntax mb } } ca
                when mb.Name.Identifier.Text is "Dispose" => ca.Expression,
            _ => null,
        };
        if (recv is null)
            continue;
        if (dm.GetSymbolInfo(recv).Symbol is IFieldSymbol f
            && !f.IsStatic                          // a static field is shared across instances,
            && SymbolEqualityComparer.Default.Equals(f.ContainingType, w))  // not per-wrapper ownership
            result.Add(f);
    }
    return result;
}

// P-005 D5.4: does `new W(args)` ADOPT one of its arguments into an owning field — i.e. is
// the constructed object a wrapper that takes responsibility for disposing that arg? True
// iff (a) the ctor is first-party, (b) its type disposes exactly ONE owning field
// unconditionally (DisposedOwningFields), and (c) that field is assigned DIRECTLY from
// exactly one constructor parameter (`_f = p;` as a top-level ctor statement). Returns that
// parameter's positional index. Single-source by construction (§11): any ambiguity — no
// visible Dispose, 0/2+ disposed fields, the field not assigned from a single param, a
// non-positional call — yields no claim (false, idx -1). This is the only gate that lets the
// extractor emit an `alias_join`, so it must never over-claim (a false adopt would fabricate
// a double-dispose), only under-claim.
static bool TryAdoptedArgIndex(BaseObjectCreationExpressionSyntax oce, SemanticModel model,
                               out int idx)
{
    idx = -1;
    if (model.GetSymbolInfo(oce).Symbol is not IMethodSymbol ctor
        || ctor.MethodKind != MethodKind.Constructor
        || ctor.DeclaringSyntaxReferences.Length == 0)
        return false;
    var w = ctor.ContainingType;
    var disposed = DisposedOwningFields(w, model);
    if (disposed.Count != 1)
        return false;
    var field = disposed.First();
    if (ctor.DeclaringSyntaxReferences[0].GetSyntax() is not ConstructorDeclarationSyntax cds
        || cds.Body is not { } cbody)
        return false;
    var cm = model.Compilation.GetSemanticModel(cds.SyntaxTree);
    // v1 accepts only a PURE single-assignment adopter ctor `{ _f = p; }`. Any sibling
    // statement could rebind the field or mutate the param (`_f = p; Rebind(other);`), which
    // would over-claim adoption — so a multi-statement ctor is DECLINED (deferred to a later
    // slice). Precision-first: under-claim, never fabricate a false double-dispose (CodeRabbit).
    if (cbody.Statements.Count != 1
        || cbody.Statements[0] is not ExpressionStatementSyntax es
        || es.Expression is not AssignmentExpressionSyntax asg
        || !asg.IsKind(SyntaxKind.SimpleAssignmentExpression))
        return false;
    if (cm.GetSymbolInfo(asg.Left).Symbol is not IFieldSymbol lf
        || lf.IsStatic                             // shared storage, not per-instance ownership
        || !SymbolEqualityComparer.Default.Equals(lf, field))
        return false;
    if (cm.GetSymbolInfo(asg.Right).Symbol is not IParameterSymbol p
        || !SymbolEqualityComparer.Default.Equals(p.ContainingSymbol, ctor))
        return false;                              // field set from a non-parameter — bail
    var matched = p.Ordinal;
    // the call must be POSITIONAL up to the adopted slot, so the arg index == the param
    // ordinal (a named/reordered call would mis-attribute). Require enough positional args.
    if (oce.ArgumentList is not { } al || al.Arguments.Count <= matched
        || al.Arguments.Take(matched + 1).Any(a => a.NameColon is not null))
        return false;
    idx = matched;
    return true;
}

// P-005 D5.4: the adopted-argument expression of `new W(x)`, or null if W does not adopt an
// argument (TryAdoptedArgIndex). Wraps the index lookup so callers work with the syntax.
// Covers both `new W(x)` and target-typed `new(x)` (BaseObjectCreationExpressionSyntax) —
// the adopt verification resolves the ctor from the symbol either way (Codex).
static ExpressionSyntax? AdoptedArg(BaseObjectCreationExpressionSyntax oce, SemanticModel model) =>
    TryAdoptedArgIndex(oce, model, out var i) ? oce.ArgumentList!.Arguments[i].Expression : null;

// P-005 D5.4: does the local `name` ESCAPE this method (returned, stored as an assignment
// RHS, passed on as an argument, or captured by a closure)? Deliberately OVER-approximates
// — any arg-pass counts, even a borrow — because it only gates the *adopt* exception below:
// over-escaping the wrapper makes us DECLINE the alias (under-claim), never fabricate one.
// `w.Dispose()` (a member access where `w` is the receiver) is a use, not an escape, so a
// disposed wrapper still qualifies. The escape test WALKS ANCESTORS through value-wrapping
// expressions (casts, `??`, parens, conditionals) so `return (IDisposable)w;` / `x = w ?? f;`
// / `Foo((object)w)` are all caught, not just a direct-parent return/arg/assignment-RHS
// (CodeRabbit).
static bool LocalEscapesSyntactically(string name, BlockSyntax mbody)
{
    foreach (var idn in mbody.DescendantNodes().OfType<IdentifierNameSyntax>())
    {
        if (idn.Identifier.Text != name)
            continue;
        // a bare receiver `name.Member(...)` / `name?.Member` is a use/release, not an escape.
        if (idn.Parent is MemberAccessExpressionSyntax ma && ma.Expression == idn)
            continue;
        // captured by a closure (lambda / local function) — outlives the method.
        var captured = false;
        for (var p = idn.Parent; p is not null && p != mbody; p = p.Parent)
            if (p is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax)
            {
                captured = true;
                break;
            }
        if (captured)
            return true;
        // climb the value's wrapping expressions to where it lands: a return, an argument, or
        // an assignment RHS is an escape; reaching the enclosing statement first is not.
        SyntaxNode child = idn;
        var escapes = false;
        for (var p = idn.Parent; p is not null; child = p, p = p.Parent)
        {
            if (p is ReturnStatementSyntax or ArgumentSyntax
                || (p is AssignmentExpressionSyntax asg && asg.Right == child))
            {
                escapes = true;
                break;
            }
            if (p is StatementSyntax)               // reached the enclosing statement, no escape
                break;
        }
        if (escapes)
            return true;
    }
    return false;
}

// P-005 D5.4: is `idn` the adopted argument of `new W(idn)` whose wrapper is a method-bounded
// owner — i.e. should this arg occurrence NOT count as an escape? Gated hard to preserve
// own-only-0: the wrapper must be a NON-`using` local `var w = new W(idn)`, `w` must be a
// tracked disposable candidate, and `w` must not itself escape (else keeping the arg tracked
// with nothing to discharge it would fabricate an OWN001). When all hold, the arg's
// obligation is adopted by `w` and modelled as an `alias_join`; the arg stays tracked.
static bool IsAdoptedArgOfBoundedWrapper(IdentifierNameSyntax idn, SemanticModel model,
                                         HashSet<string> candidates, BlockSyntax mbody)
{
    if (idn.Parent is not ArgumentSyntax { Parent: ArgumentListSyntax
            { Parent: BaseObjectCreationExpressionSyntax oce } })
        return false;
    if (AdoptedArg(oce, model) != idn)              // idn must BE the adopted arg
        return false;
    if (oce.Parent is not EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax wv }
        || wv.Parent is not VariableDeclarationSyntax
        || wv.Parent.Parent is not LocalDeclarationStatementSyntax wld
        || wld.UsingKeyword != default)
        return false;
    var w = wv.Identifier.Text;
    return candidates.Contains(w) && !LocalEscapesSyntactically(w, mbody);
}

// A `Dispose()`/`Close()`/`DisposeAsync()` call — through member access (`x.Dispose()`)
// or member binding (`x?.Dispose()`), and seen through a trailing `.ConfigureAwait(false)`
// (the idiomatic `await x.DisposeAsync().ConfigureAwait(false)` is the release, not a
// throwing call). Mirrors the unwrap in EmitFlowExpr so StatementMayThrow does not inject
// a false exceptional-leak edge before an async dispose.
static bool IsDisposeShaped(InvocationExpressionSyntax i)
{
    var callee = i.Expression;
    if (callee is MemberAccessExpressionSyntax cfg
        && cfg.Name.Identifier.Text == "ConfigureAwait"
        && cfg.Expression is InvocationExpressionSyntax innerInv)
        callee = innerInv.Expression;
    return (callee switch
    {
        MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
        MemberBindingExpressionSyntax mb => mb.Name.Identifier.Text,
        _ => (string?)null,
    }) is "Dispose" or "Close" or "DisposeAsync";
}

// True when `st` is the LAST statement of a method/accessor/constructor body block — its
// block's parent is a member declaration, not a nested statement (a BlockSyntax is itself
// a StatementSyntax, so this also excludes nested blocks). Used to decide whether a
// `try`'s exceptional-exit edges are sound (see the try lowering).
static bool IsBodyTail(StatementSyntax st) =>
    st.Parent is BlockSyntax b
    && b.Statements.Count > 0 && b.Statements[^1] == st
    && b.Parent is not StatementSyntax;

// True when `node` sits lexically inside a `finally { }` block (walking up to the enclosing
// member / lambda boundary). A `throw` there is NOT a clean method exit: it propagates through
// any ENCLOSING `finally`/`try` cleanup, which a bare-return exit would skip — and `finally`
// bodies are lowered with the default (null) `onThrow`, so the body-level throw branch cannot
// tell them apart from the method body. Such a throw therefore keeps BAILING the method (sound
// honest-skip, as before this feature) rather than emit a false leak that misses the outer
// finally's release (Codex P2: `try { try {} finally { throw; } } finally { s.Dispose(); }`).
static bool IsInsideFinally(SyntaxNode node)
{
    for (var p = node.Parent; p is not null; p = p.Parent)
    {
        if (p is FinallyClauseSyntax) return true;
        if (p is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax
              or BaseMethodDeclarationSyntax or AccessorDeclarationSyntax) return false;
    }
    return false;
}

// Inject an exceptional-exit edge `if(*){ onThrow }` before a LEAF may-throw statement
// (an expression statement or a local declaration) inside a `try` body. `onThrow` is the
// continuation a throw here runs to leave the method — this try's `finally`, then any
// enclosing tries' finallys, then `return` (built in the try lowering). A resource owned
// at this point and not released by that continuation leaks on the throw path. Called for
// LEAF statements only; a COMPOUND statement (if/loop/block) is recursed into so the edge
// lands before the nested leaf — at the point the resource's ownership is exact (after any
// in-branch dispose), which is what makes nesting sound rather than a false leak.
static void InjectThrowEdge(StatementSyntax st, List<object> nodes, List<object>? onThrow, bool canEscape)
{
    // Inside a `try`, `onThrow` is the finally+exit continuation a throw here runs. At the
    // method-body level `onThrow` is null — by default no edge is injected (the shipped low-FP
    // posture: a body-level may-throw call is NOT treated as a leak point). The opt-in
    // --body-throw-edges tier (Program.BodyThrowEdges) lifts that: an ESCAPING body-level
    // may-throw statement (`canEscape`, so no enclosing catch-all swallows it) gets a synthetic
    // bare method exit as its continuation, matching CodeQL's cs/dispose-not-called-on-throw on
    // the no-try slice. A catch-all-suppressed region (`canEscape` false) still injects nothing.
    // `!IsInsideFinally`: a may-throw statement lexically inside a `finally` is lowered with a null
    // onThrow too, but a real exception there runs the ENCLOSING cleanup — a bare exit would skip
    // it and falsely flag a resource the outer finally/using disposes, so synthesize no edge there
    // (the symmetric guard the explicit-throw path already uses — Codex P2 on the may-throw tier).
    var cont = onThrow ?? (BodyThrowEdges && canEscape && !IsInsideFinally(st)
        ? new List<object> { new { op = "return", var = (string?)null, line = LineOf(st) } }
        : null);
    if (cont is not null && StatementMayThrow(st))
        nodes.Add(new { op = "if", line = LineOf(st),
                        then = new List<object>(cont), @else = new List<object>() });
}

// A statement that can raise an exception part-way through: it makes a call that is not
// itself a dispose, OR it creates an object (`new` — a constructor can throw, leaking a
// PRIOR owned resource whose dispose it would then skip). Creating the resource being
// acquired here is harmless: the edge lands before its `acquire`, where it is not yet owned.
// Does NOT descend into lambda / anonymous-method bodies: a `new` (or call) inside `() => …`
// runs when the delegate is INVOKED, not where it is declared, so the declaring statement is
// not a throw point — counting it would inject a phantom edge that falsely flags a prior
// resource disposed after the `try`. An immediately-invoked lambda is still caught: the outer
// invocation is itself the throw point.
static bool StatementMayThrow(StatementSyntax st) =>
    st.DescendantNodes(descendIntoChildren: n => n is not AnonymousFunctionExpressionSyntax)
      .Any(n =>
        (n is InvocationExpressionSyntax i && !IsDisposeShaped(i))
        || n is ObjectCreationExpressionSyntax or ImplicitObjectCreationExpressionSyntax);

// A catch clause that catches EVERY exception and so always continues to the post-try
// code: `catch { }` (no declaration) or `catch (Exception)` / `catch (System.Exception)` —
// with NO `when` filter (a filter may evaluate false, letting the exception propagate). A
// typed catch (`catch (IOException)`, or a qualified DOMAIN type like `catch (Foo.Exception)`
// whose rightmost name is `Exception` but is not System.Exception) or any filtered catch
// continues for only SOME exceptions; the rest propagate out, skipping the post-try dispose,
// so the resource still leaks on those paths. Match the canonical System.Exception spellings
// by full text — a rightmost-name match would misread a domain `Foo.Exception` as catch-all
// and suppress a real leak. Syntax-only (no semantic model): the inverse pathology — an
// exotic alias making a typed-looking name resolve to System.Exception — is never written.
static bool IsCatchAll(CatchClauseSyntax cc) =>
    cc.Filter is null
    && (cc.Declaration is not { } decl
        || decl.Type.ToString() is "Exception"
                               or "System.Exception"
                               or "global::System.Exception");

// Lower a method block to OwnIR flow nodes (acquire/use/release/if/return) for the
// `tracked` local IDisposables. Returns null on any UNMODELLED statement (a `goto`, labeled
// statement, local function, `lock`/`fixed`, …): the method is then honestly skipped, not
// guessed. Loops, `try`, `do` and `switch` ARE modelled below.
static List<object>? LowerFlowBody(BlockSyntax block, HashSet<string> tracked, SemanticModel model)
{
    var nodes = new List<object>();
    if (!LowerFlowStatements(block.Statements, 0, tracked, model, nodes,
                             canEscape: true, onThrow: null, onReturn: null))
        return null;
    return nodes;
}

// Lower a statement LIST, desugaring a tracked `using IMemoryOwner owner = MemoryPool.Rent(...)`
// declaration into `acquire; try { rest } finally { release }` — the implicit scope-exit Dispose is
// threaded onto the rest's returns/throws (exactly like a `finally`), so a RETURNED view of the owner
// (`using owner = …; return owner.Memory;`) is a dangling borrow read by the caller after the dispose
// -> OWN002 (Codex review on #73). With no such declaration this is identical to lowering each
// statement in turn, so non-pooled `using` locals and every existing shape are unaffected.
static bool LowerFlowStatements(IReadOnlyList<StatementSyntax> stmts, int start,
                                HashSet<string> tracked, SemanticModel model, List<object> nodes,
                                bool canEscape, List<object>? onThrow, List<object>? onReturn)
{
    for (var i = start; i < stmts.Count; i++)
    {
        var st = stmts[i];
        if (st is LocalDeclarationStatementSyntax usingDecl
            && usingDecl.UsingKeyword != default
            && usingDecl.Declaration.Variables.Count == 1
            && tracked.Contains(usingDecl.Declaration.Variables[0].Identifier.Text)
            && IsMemoryPoolRent(usingDecl.Declaration.Variables[0].Initializer?.Value, model))
        {
            var uv = usingDecl.Declaration.Variables[0];
            var owner = uv.Identifier.Text;
            var exit = new List<object> { new { op = "return", var = (string?)null, line = LineOf(usingDecl) } };
            InjectThrowEdge(usingDecl, nodes, onThrow, canEscape);   // a throw DURING Rent() runs the OUTER path (owner not yet acquired)
            nodes.Add(new { op = "acquire", var = owner, line = LineOf(uv) });
            var release = new { op = "release", var = owner, line = LineOf(uv) };
            // The rest of THIS block is the try-body; the implicit using-dispose is its finally — run
            // before a return (so a returned view is read after release) and on normal completion.
            var restOnReturn = new List<object> { release };
            restOnReturn.AddRange(onReturn ?? exit);
            List<object>? restOnThrow = null;
            if (canEscape)
            {
                restOnThrow = new List<object> { release };
                restOnThrow.AddRange(onThrow ?? exit);
            }
            if (!LowerFlowStatements(stmts, i + 1, tracked, model, nodes, canEscape, restOnThrow, restOnReturn))
                return false;
            nodes.Add(release);   // normal completion (no return) disposes at scope exit too
            return true;
        }
        if (!LowerFlowStmt(st, tracked, model, nodes, canEscape, onThrow, onReturn))
            return false;
    }
    return true;
}

// `canEscape`: can a throw at the current position leave the METHOD (no enclosing
// catch-all swallows it)? `onThrow`: the continuation a throw here runs to leave the
// method (finally-stack + return), or null when no exception edge should be injected
// (method level, or a region an enclosing catch-all swallows). `onReturn`: the continuation
// a `return` here runs FIRST — the enclosing `finally`(s), then the exit — so a resource a
// finally disposes is released on the return path; null = a bare return (outside any try).
// Defaults are the method-body context: throws escape, nothing is injected, returns are bare.
static bool LowerFlowStmt(StatementSyntax st, HashSet<string> tracked, SemanticModel model, List<object> nodes,
                          bool canEscape = true, List<object>? onThrow = null,
                          List<object>? onReturn = null)
{
    switch (st)
    {
        case BlockSyntax b:
            return LowerFlowStatements(b.Statements, 0, tracked, model, nodes, canEscape, onThrow, onReturn);
        case LocalDeclarationStatementSyntax ld:
            InjectThrowEdge(ld, nodes, onThrow, canEscape);
            if (ld.UsingKeyword == default)
                foreach (var v in ld.Declaration.Variables)
                {
                    // P-005 D5.4 (T4 adopt): `var w = new W(x)` where W is a verified wrapper
                    // that adopts the tracked local `x` into an owning field (TryAdoptedArgIndex)
                    // — emit `alias_join` instead of an acquire, so `w` joins `x`'s obligation:
                    // disposing either discharges the one resource, disposing both is OWN003. The
                    // arg `x` is kept tracked by the matching escape exception above.
                    if (tracked.Contains(v.Identifier.Text)
                        && v.Initializer?.Value is BaseObjectCreationExpressionSyntax adoptOce
                        && AdoptedArg(adoptOce, model) is IdentifierNameSyntax adoptedId
                        && tracked.Contains(adoptedId.Identifier.Text))
                        nodes.Add(new { op = "alias_join", var = v.Identifier.Text,
                                        src = adoptedId.Identifier.Text, line = LineOf(v) });
                    else if (tracked.Contains(v.Identifier.Text)
                        && (v.Initializer?.Value is ObjectCreationExpressionSyntax
                                                 or ImplicitObjectCreationExpressionSyntax
                            || IsPoolRent(v.Initializer?.Value, model)        // ArrayPool<T> Rent
                            || IsMemoryPoolRent(v.Initializer?.Value, model)  // MemoryPool<T> Rent (IMemoryOwner)
                            || IsOwningFactory(v.Initializer?.Value, model)))   // File / crypto Create* factory
                        // Tag an ArrayPool rent so the bridge labels a partial-path leak a
                        // "pooled buffer" (Return not on every path), not the generic "disposable"
                        // — the flow path previously mislabelled a pool buffer leaked on a throw edge.
                        nodes.Add(new { op = "acquire", var = v.Identifier.Text, line = LineOf(v),
                                        kind = IsPoolRent(v.Initializer?.Value, model) ? "pool" : "disposable" });
                    // P-005 D5.2: `var r = FirstPartyFactory()` — emit a `call` op (NOT an
                    // acquire); the core mints the acquire only if it proves the callee returns
                    // `fresh`, so a non-fresh first-party call is never falsely owned.
                    else if (tracked.Contains(v.Identifier.Text)
                             && IsFirstPartyDisposableFactory(v.Initializer?.Value, model, out var fpCallee))
                    {
                        // Preserve the call's TRACKED identifier args (CodeRabbit) so the core
                        // can apply the callee's per-argument ownership effects (consume/borrow)
                        // to a `var r = Wrap(stream)` — not just the fresh return. Untracked /
                        // non-identifier args are dropped (no local to attribute an effect to).
                        // Positional args only: the bridge applies the callee's effects by
                        // POSITION, so a NAMED argument (`Wrap(second: s2, first: s1)`) would
                        // mis-attribute if kept in syntactic order. Dropping named args
                        // under-claims (no effect on them) but never mis-aligns (CodeRabbit).
                        var fpArgs = v.Initializer?.Value is InvocationExpressionSyntax fpInv
                            ? fpInv.ArgumentList.Arguments
                                  .Where(a => a.NameColon is null)
                                  .Select(a => a.Expression)
                                  .OfType<IdentifierNameSyntax>()
                                  .Select(id => id.Identifier.Text)
                                  .Where(tracked.Contains)
                                  .ToArray()
                            : Array.Empty<string>();
                        nodes.Add(new { op = "call", callee = fpCallee, args = fpArgs,
                                        result = v.Identifier.Text, line = LineOf(v) });
                    }
                    // POOL005: a full-length view in the initializer — `var copy = buf.AsSpan().ToArray();`
                    // — over-reads the pooled tail just as `Emit(buf.AsSpan());` does. EmitFlowExpr is not
                    // called on a non-acquire initializer, so scan it here for the overspan (Codex review).
                    if (v.Initializer?.Value is { } vinit)
                        EmitOverspans(vinit, tracked, model, nodes);
                }
            return true;
        case ExpressionStatementSyntax es:
            InjectThrowEdge(es, nodes, onThrow, canEscape);
            EmitFlowExpr(es.Expression, tracked, model, nodes);
            return true;
        case IfStatementSyntax ifs:
        {
            var thenNodes = new List<object>();
            if (!LowerFlowStmt(ifs.Statement, tracked, model, thenNodes, canEscape, onThrow, onReturn))
                return false;
            var elseNodes = new List<object>();
            if (ifs.Else is { } e && !LowerFlowStmt(e.Statement, tracked, model, elseNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "if", line = LineOf(ifs), then = thenNodes, @else = elseNodes });
            return true;
        }
        case UsingStatementSyntax us:
        {
            // using (IMemoryOwner owner = MemoryPool.Rent(...)) { body }: the STATEMENT form of the same
            // scope-exit dispose as the `using` declaration — desugar a tracked MemoryPool owner the same
            // way (acquire; thread the dispose onto the body's returns/throws; release on completion) so a
            // returned view of it dangles -> OWN002 (CodeRabbit). Other using-statements just lower the
            // body (the using local is auto-disposed, untracked).
            if (us.Declaration is { Variables.Count: 1 } ud
                && tracked.Contains(ud.Variables[0].Identifier.Text)
                && IsMemoryPoolRent(ud.Variables[0].Initializer?.Value, model))
            {
                var uv = ud.Variables[0];
                var owner = uv.Identifier.Text;
                var exit = new List<object> { new { op = "return", var = (string?)null, line = LineOf(us) } };
                nodes.Add(new { op = "acquire", var = owner, line = LineOf(uv) });
                var release = new { op = "release", var = owner, line = LineOf(uv) };
                var bodyOnReturn = new List<object> { release };
                bodyOnReturn.AddRange(onReturn ?? exit);
                List<object>? bodyOnThrow = null;
                if (canEscape)
                {
                    bodyOnThrow = new List<object> { release };
                    bodyOnThrow.AddRange(onThrow ?? exit);
                }
                if (us.Statement is not null
                    && !LowerFlowStmt(us.Statement, tracked, model, nodes, canEscape, bodyOnThrow, bodyOnReturn))
                    return false;
                nodes.Add(release);   // normal completion disposes at scope exit too
                return true;
            }
            return us.Statement is null || LowerFlowStmt(us.Statement, tracked, model, nodes, canEscape, onThrow, onReturn);
        }
        case ReturnStatementSyntax rs:
        {
            // A tracked local READ in the return value is a use at the return point —
            // e.g. `return BuildResult(buf)` after `pool.Return(buf)` is a use-after-
            // return. A tracked local *itself* returned is excluded upstream as an
            // escape, so lowering the return expression only adds uses, never a
            // spurious escape. Then: a `return` first runs any enclosing `finally`(s)
            // — threaded as `onReturn`, so a resource the finally releases is released
            // on the return path — then exits; outside a try it is a bare CFG exit.
            if (rs.Expression is { } rexpr)
                EmitFlowExpr(rexpr, tracked, model, nodes);
            // A returned Span/Memory VIEW (borrow) ESCAPES to the caller, who uses it AFTER this
            // method's finally cleanup runs — so `try { return view; } finally { Return(buf); }`
            // hands back a DANGLING borrow (the idiomatic pool-cleanup form). Model the escaped
            // view's use AFTER the finally release(s) by inserting it just before the exit of the
            // `onReturn` chain (which is `[finally…, exit]`), so a finally that releases the owner
            // trips OWN002 (Codex). Outside a try (onReturn null) EmitFlowExpr already placed the
            // use after any earlier release, so no insertion is needed.
            var viewEscapes = rs.Expression is { } vrx
                ? ReturnedViewOwners(vrx, tracked, model) : new List<string>();
            if (onReturn is not null)
            {
                var chain = new List<object>(onReturn);
                foreach (var owner in viewEscapes)
                    chain.Insert(chain.Count - 1, new { op = "use", var = owner, line = LineOf(rs) });
                // The BARE owner returned (`using owner = …; return owner;`) is the twin of the returned
                // view: a tracked plain-identifier return can only be a using-declared MemoryPool owner
                // (a genuine transfer is escaped/untracked upstream), and its scope-exit dispose runs as we
                // return — so thread its use after the release(s) too, exactly like a view -> OWN002.
                if (rs.Expression is IdentifierNameSyntax bareOwner
                    && tracked.Contains(bareOwner.Identifier.Text)
                    && !viewEscapes.Contains(bareOwner.Identifier.Text))
                    chain.Insert(chain.Count - 1,
                        new { op = "use", var = bareOwner.Identifier.Text, line = LineOf(rs) });
                nodes.AddRange(chain);
            }
            else
            {
                // P-005 D5.2: a tracked local returned BARE (outside any `finally`) is a
                // fresh-factory transfer — emit it as the return's `var` so the core models the
                // escape (a discharge: ownership moves to the caller) and classifies the method
                // `returnsOwned: fresh`. A non-identifier / non-tracked return is a bare CFG exit.
                var rvar = rs.Expression is IdentifierNameSyntax rid
                           && tracked.Contains(rid.Identifier.Text)
                    ? rid.Identifier.Text : (string?)null;
                nodes.Add(new { op = "return", var = rvar, line = LineOf(rs) });
            }
            return true;
        }
        case WhileStatementSyntax ws:
        {
            // P-016 A1 reached the frontend: a `while` lowers to a `while` flow op
            // (a body that runs 0+ times with a back-edge); the core analyses it with
            // its worklist fixpoint (cross-iteration leak / use-after-release /
            // double-release). The condition is opaque (we model control flow, not
            // values). If the body has an unmodelled statement, bail the method.
            var bodyNodes = new List<object>();
            if (ws.Statement is null || !LowerFlowStmt(ws.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(ws), body = bodyNodes });
            return true;
        }
        case ForEachStatementSyntax fes:
        {
            // `foreach` runs its body 0+ times over an (opaque) collection — the same
            // ownership shape as `while`. The loop variable is never a `new`'d
            // candidate and the hidden enumerator is auto-disposed, so modelling the
            // body as a `while` is sound. (`for` and `do` are handled below; `do` runs 1+
            // times, so it is desugared rather than modelled as a bare 0+-trip `while`.)
            var bodyNodes = new List<object>();
            if (fes.Statement is null || !LowerFlowStmt(fes.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(fes), body = bodyNodes });
            return true;
        }
        case ForStatementSyntax fors:
        {
            // `for (init; cond; incr) body` runs its body 0+ times — the same
            // ownership shape as `while`/`foreach`. init/cond/incr are opaque (we
            // model control flow, not values); the tracked locals are the ones the
            // BODY declares. A resource declared in the `for` *initializer* is not a
            // method-body local, so it is never a tracked candidate — no soundness
            // concern, just a separate (rare) recall gap.
            var bodyNodes = new List<object>();
            if (fors.Statement is null || !LowerFlowStmt(fors.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(fors), body = bodyNodes });
            return true;
        }
        case TryStatementSyntax trys:
        {
            // try { A } [catch { C }...] [finally { B }] with EXCEPTION EDGES. Any LEAF
            // statement in A (at any nesting depth) that can throw gets an exceptional exit
            // `if(*){ B; … ; return }` injected before it — throw here, run the finally(s),
            // leave. A resource owned at that point and NOT released by the finally leaks on
            // the exceptional path: dispose-not-called-on-throw (a dispose placed in the try,
            // not the finally). A dispose IN the finally runs on every exceptional exit, so
            // the safe pattern stays silent; `acquire; dispose;` with no throw between has no
            // live edge, so no false leak.
            //
            // Catch bodies are not lowered; to stay SOUND, bail if any catch disposes, so
            // a release that only happens in a catch is never missed. Matches `x.Dispose()`
            // and `x?.Dispose()`.
            foreach (var cc in trys.Catches)
                if (cc.Block.DescendantNodes().OfType<InvocationExpressionSyntax>().Any(IsDisposeShaped))
                    return false;
            var finallyNodes = new List<object>();
            if (trys.Finally is { } fin && !LowerFlowStmt(fin.Block, tracked, model, finallyNodes))
                return false;
            // Does a throw in THIS body escape to method exit (so the edge — leave running
            // only the finally — models a real execution)? Sound when there is no catch (it
            // propagates out past any post-try code), the try is the body's tail (nothing
            // runs after), OR no catch is a genuine catch-all — a typed/filtered catch lets
            // the uncaught exception types propagate, skipping the post-try dispose, so the
            // resource still leaks on those paths. The one shape that SUPPRESSES the edges is
            // a catch-all on a non-tail try: every throw is caught and continues to (and may
            // dispose in) the post-try code, so a return there would falsely flag a resource
            // that path disposes. `canEscape` carries the same fact down through ENCLOSING
            // tries: a catch-all higher up already swallows these throws, so they never reach
            // method exit -> no edges in the region nested under it.
            bool escapesThisTry = trys.Catches.Count == 0
                || IsBodyTail(trys)
                || !trys.Catches.Any(IsCatchAll);
            bool bodyCanEscape = canEscape && escapesThisTry;
            // The continuation an escaping throw runs: this finally, then the enclosing
            // exceptional path (its finallys, ending in the method `return`), or just a
            // `return` when this is the outermost try. Null when suppressed -> no edges.
            List<object>? bodyOnThrow = null;
            if (bodyCanEscape)
            {
                bodyOnThrow = new List<object>(finallyNodes);
                bodyOnThrow.AddRange(onThrow ?? new List<object>
                    { new { op = "return", var = (string?)null, line = LineOf(trys) } });
            }
            // A `return` inside the body runs THIS finally, then the enclosing return path
            // (its finallys), then exits — independent of catches (a `return` is never caught,
            // unlike a throw), so it is threaded even where the throw edges are suppressed. The
            // finally release thus runs before the return: `try { …; return; } finally { d }`
            // disposes on the return path instead of being bailed.
            var bodyOnReturn = new List<object>(finallyNodes);
            bodyOnReturn.AddRange(onReturn ?? new List<object>
                { new { op = "return", var = (string?)null, line = LineOf(trys) } });
            if (!LowerFlowStatements(trys.Block.Statements, 0, tracked, model, nodes, bodyCanEscape, bodyOnThrow, bodyOnReturn))
                return false;
            nodes.AddRange(finallyNodes);   // normal completion runs the finally
            return true;
        }
        case DoStatementSyntax dos:
        {
            // do { B } while(c)  ≡  B; while(c) { B }  — the body runs 1+ times. Lower B once
            // unconditionally (the guaranteed first iteration), then a `while` of B (0+ more).
            // Modelling it as a plain `while` (0+ trips) would be UNSOUND: a resource released
            // only in the body but acquired before the loop would falsely leak on the phantom
            // 0-trip path. Bail (like the loops) if the body has an unmodelled statement.
            if (dos.Statement is null
                || !LowerFlowStmt(dos.Statement, tracked, model, nodes, canEscape, onThrow, onReturn))
                return false;
            var bodyNodes = new List<object>();
            if (!LowerFlowStmt(dos.Statement, tracked, model, bodyNodes, canEscape, onThrow, onReturn))
                return false;
            nodes.Add(new { op = "while", line = LineOf(dos), body = bodyNodes });
            return true;
        }
        case SwitchStatementSyntax sw:
        {
            // switch(e) { (case L: | default:) section … } modelled as a chain of opaque,
            // mutually-exclusive branches: `if(*){ s1 } else { if(*){ s2 } else { … } }` — one
            // per section, value-opaque (we model control flow, not the matched value). A
            // trailing `break` ends a section (stripped); a section doing anything the model
            // can't place here (a nested `break`, `goto case`) bails the method. A bare `throw`
            // in a section IS modelled now (an abnormal exit) when no enclosing try wraps it.
            List<object>? defaultNodes = null;
            var cases = new List<List<object>>();
            foreach (var section in sw.Sections)
            {
                var secNodes = new List<object>();
                if (!LowerSwitchSection(section, tracked, model, secNodes, canEscape, onThrow, onReturn))
                    return false;
                if (section.Labels.Any(l => l is DefaultSwitchLabelSyntax))
                    defaultNodes = secNodes;
                else
                    cases.Add(secNodes);
            }
            // The chain's tail — the "no earlier case matched" branch. A `default` IS that
            // branch. With NO default we do NOT model an empty no-match path: that would falsely
            // flag a resource disposed in every case of an EXHAUSTIVE switch (e.g. over an enum)
            // as leaking on a path that cannot occur. Instead the LAST case becomes the tail
            // (assume some branch runs) — sound: a genuinely non-exhaustive no-match leak is only
            // missed when EVERY case disposes the resource (a recall gap, never a false positive).
            List<object> chain;
            if (defaultNodes is not null)
                chain = defaultNodes;
            else if (cases.Count == 0)
                return true;                         // empty switch -> no flow effect
            else
            {
                chain = cases[^1];
                cases.RemoveAt(cases.Count - 1);
            }
            for (int k = cases.Count - 1; k >= 0; k--)
                chain = new List<object>
                    { new { op = "if", line = LineOf(sw), then = cases[k], @else = chain } };
            nodes.AddRange(chain);
            return true;
        }
        case ThrowStatementSyntax thr:
            // An explicit `throw` is an abnormal method exit: control leaves the method
            // WITHOUT running the statements below it, so a resource owned here and disposed
            // only LATER leaks on the throw path — dispose-not-called-on-throw with NO
            // enclosing `try`. Modelled at the method-body level only: `onThrow is null` AND
            // the throw escapes (`canEscape`) means no enclosing try would run a `finally` or
            // catch it, so it is a bare CFG exit where a still-owned resource leaks — the same
            // synthetic exit the injected may-throw edges use. INSIDE a try an explicit throw
            // may run a finally or be caught (typed / catch-all); modelling that soundly needs
            // the thrown-type-vs-catch match, which is not threaded here, so an explicit throw
            // there keeps bailing (return false) exactly as before — no new false escape past a
            // catch. (`throw;` rethrow only appears in a catch body, never lowered, so this is
            // the `throw expr;` form.) The win is broad: a method whose only unmodelled
            // statement was a top-level validation throw (`if (x is null) throw …;`) is now
            // analysed instead of skipped, lighting up every detector on the rest of its body.
            // ...and a throw lexically inside a `finally` likewise keeps bailing (IsInsideFinally):
            // its real continuation is the OUTER finally/try cleanup, which a bare exit would skip.
            if (canEscape && onThrow is null && !IsInsideFinally(thr))
            {
                nodes.Add(new { op = "return", var = (string?)null, line = LineOf(thr) });
                return true;
            }
            return false;
        default:
            // unmodelled (goto / labeled / local function / lock / fixed / a `throw` INSIDE a
            // try) -> bail the method, honestly skipping rather than guessing.
            return false;
    }
}

// Lower one `switch` section's statements, treating a top-level `break` as the section
// terminator (it just exits the switch, so it is stripped). Bails (false) on any statement the
// flow model doesn't handle here — including a `break` nested inside an `if`/loop, which reaches
// the unmodelled default and conservatively skips the whole method.
static bool LowerSwitchSection(SwitchSectionSyntax section, HashSet<string> tracked,
                               SemanticModel model, List<object> nodes, bool canEscape,
                               List<object>? onThrow, List<object>? onReturn)
{
    foreach (var stmt in section.Statements)
    {
        if (stmt is BreakStatementSyntax)
            break;
        if (!LowerFlowStmt(stmt, tracked, model, nodes, canEscape, onThrow, onReturn))
            return false;
    }
    return true;
}

static void EmitFlowExpr(ExpressionSyntax expr, HashSet<string> tracked, SemanticModel model, List<object> nodes)
{
    // `await x.DisposeAsync()` is the IAsyncDisposable release — look through the
    // await to the inner call so it counts as disposal, not a bare use.
    if (expr is AwaitExpressionSyntax awaited)
        expr = awaited.Expression;
    // ... and through a trailing `.ConfigureAwait(false)` — the library-idiomatic
    // `await x.DisposeAsync().ConfigureAwait(false)` awaits the ConfigureAwait call.
    if (expr is InvocationExpressionSyntax cfg
        && cfg.Expression is MemberAccessExpressionSyntax cfgMa
        && cfgMa.Name.Identifier.Text == "ConfigureAwait"
        && cfgMa.Expression is InvocationExpressionSyntax inner)
        expr = inner;
    // x.Dispose()/x.Close()/x.DisposeAsync() on a tracked local -> release.
    if (expr is InvocationExpressionSyntax inv
        && inv.Expression is MemberAccessExpressionSyntax ma
        && ma.Name.Identifier.Text is "Dispose" or "Close" or "DisposeAsync"
        && ma.Expression is IdentifierNameSyntax rid
        && tracked.Contains(rid.Identifier.Text))
    {
        nodes.Add(new { op = "release", var = rid.Identifier.Text, line = LineOf(inv) });
        return;
    }
    // x.Show() on a tracked WinForms Form-derived local -> release: a modeless form's
    // ownership transfers to the framework, which disposes it when the user closes it.
    // Modeled as a release AT THE SHOW SITE (not a method-wide exemption), so it stays
    // path-sensitive — a form shown only on one branch still leaks on the branch that
    // never shows it (Codex review on PR #57). ShowDialog() is a *modal* show and is
    // NOT matched: the caller owns a ShowDialog'd form and must dispose it, so it stays
    // a tracked use (a real leak if never disposed). Guarded by the Form-derived type so
    // an unrelated IDisposable with a Show() method is not mistaken for an ownership
    // transfer.
    if (expr is InvocationExpressionSyntax sinv
        && sinv.Expression is MemberAccessExpressionSyntax sma
        && sma.Name.Identifier.Text == "Show"
        && sma.Expression is IdentifierNameSyntax sid
        && tracked.Contains(sid.Identifier.Text)
        && DerivesFromWinFormsForm(model.GetTypeInfo(sma.Expression).Type))
    {
        nodes.Add(new { op = "release", var = sid.Identifier.Text, line = LineOf(sinv) });
        return;
    }
    // x.Stop() on a tracked System.Net.Sockets.TcpListener -> release: TcpListener.Dispose()
    // just delegates to Stop() (which disposes the listen socket and clears it), so a
    // Stop()'d listener holds no resource and is not a leak (Codex review on PR #61). It is
    // TcpListener-specific, resolved via the method symbol — Stop() on a Timer / Process / etc.
    // does NOT dispose, so it stays a tracked use; a listener never Stop()'d (nor Disposed)
    // still leaks.
    if (expr is InvocationExpressionSyntax tlinv
        && tlinv.Expression is MemberAccessExpressionSyntax
            { Name.Identifier.Text: "Stop", Expression: IdentifierNameSyntax tlid }
        && tracked.Contains(tlid.Identifier.Text)
        && model.GetSymbolInfo(tlinv).Symbol is IMethodSymbol { ContainingType: { Name: "TcpListener" } tct }
        && IsInNamespace(tct, "System", "Net", "Sockets"))
    {
        nodes.Add(new { op = "release", var = tlid.Identifier.Text, line = LineOf(tlinv) });
        return;
    }
    // x?.Dispose()/x?.Close()/x?.DisposeAsync() (null-conditional) is the release too — the
    // call is a member BINDING under a conditional access, not a member access. Mirrors
    // IsDisposeShaped so a `?.` dispose (e.g. in a finally) is not mistaken for a bare use,
    // which would otherwise falsely flag the resource as leaked.
    if (expr is ConditionalAccessExpressionSyntax cond
        && cond.Expression is IdentifierNameSyntax cid
        && tracked.Contains(cid.Identifier.Text)
        && cond.WhenNotNull is InvocationExpressionSyntax condInv
        && condInv.Expression is MemberBindingExpressionSyntax mb
        && mb.Name.Identifier.Text is "Dispose" or "Close" or "DisposeAsync")
    {
        nodes.Add(new { op = "release", var = cid.Identifier.Text, line = LineOf(cond) });
        return;
    }
    // XPool.Return(buf) on a tracked pooled buffer -> release. The buffer is the
    // ARGUMENT (the pool is the receiver), unlike Dispose where the local is the
    // receiver; `return` early so the argument is not also counted as a use.
    if (PoolReturnBuffer(expr, model) is { } pbuf && tracked.Contains(pbuf))
    {
        nodes.Add(new { op = "release", var = pbuf, line = LineOf(expr) });
        return;
    }
    // Foo(s) where Foo consumes (disposes) a by-value IDisposable parameter -> the handoff
    // RELEASES the matching argument(s) here (the inter-procedural consume contract,
    // modelled at the call site like pool Return). A later use of an argument is then a
    // use-after-handoff (OWN002). Do NOT return — other tracked arguments of the same call
    // (`Consume(s, t)`) still need their `use` below; a consumed arg is excluded from it.
    var consumed = ConsumeReleaseArgs(expr, model);
    foreach (var c in consumed)
        if (tracked.Contains(c))
            nodes.Add(new { op = "release", var = c, line = LineOf(expr) });
    // any other reference to a tracked local -> use (once per local; a consumed arg is a
    // release above, never also a use). A Span/Memory VIEW of a tracked buffer is a BORROW: a
    // reference to the view is a use of the OWNER, so using it after the owner was Returned/Disposed
    // trips OWN002 — including RETURNING a `Memory<T>` view (which CAN escape the method) after the
    // owner was released, a dangling borrow handed to the caller
    // (`Memory<byte> v = buf.AsMemory(); Return(buf); return v;`).
    var used = new SortedSet<string>(StringComparer.Ordinal);
    foreach (var idn in expr.DescendantNodesAndSelf().OfType<IdentifierNameSyntax>())
    {
        // A pure DEF of the variable — the bare LHS of `v = …` or an `out` argument — writes it without
        // reading it, so it is NOT a use of the resource (nor of a view's owner). Skipping it removes the
        // over-count where the LHS of a view REASSIGNMENT (`v = other.AsSpan()`) was scanned as a use of
        // the OLD owner (the pooled-view reassignment FP). A `ref` argument and an element/member write
        // (`v[0] = …`, `v.X = …`) still READ `v`, so they are deliberately not skipped (Codex review on #98).
        if (IsPureWrite(idn))
            continue;
        var nm = idn.Identifier.Text;
        if (tracked.Contains(nm))
        {
            if (!consumed.Contains(nm))
                used.Add(nm);
        }
        else if (ViewOwnerOf(idn, model) is { } owner
                 && tracked.Contains(owner) && !consumed.Contains(owner))
            used.Add(owner);
    }
    foreach (var u in used)
        nodes.Add(new { op = "use", var = u, line = LineOf(expr) });
    // POOL005: a full-length view of a pooled buffer anywhere in this expression -> overspan/OWN025.
    EmitOverspans(expr, tracked, model, nodes);
}

// POOL005: emit one `overspan` op per tracked pooled buffer that `expr` takes a FULL-LENGTH VIEW of
// — the core raises OWN025. The view spans the whole oversized array (`buf.AsSpan()` with no bound,
// or `buf.AsSpan(0, buf.Length)` / `new Span<T>(buf, 0, buf.Length)` whose length is the oversized
// self-`.Length`), so reading or copying through it processes the stale `[n, Length)` tail. Walks the
// whole expression so a view nested in a call (`Sink.Write(buf.AsSpan())`), a chain
// (`buf.AsSpan().ToArray()`), or a local-declaration initializer (`var copy = buf.AsSpan()...`) is
// found; a view bounded to the real `n` (`buf.AsSpan(0, n)`) is not matched. Only the VIEW is
// flagged, not a write/wipe: `Array.Clear(buf, 0, buf.Length)` merely overwrites the pooled tail
// (a safe clear-before-Return idiom), it does not expose stale bytes (Codex review). Among `tracked`
// locals only pooled buffers are the arrays the BCL AsSpan/Span symbols bind to, so this never fires
// on a tracked IDisposable / factory result. Shared by the expression-statement and local-decl paths.
static void EmitOverspans(ExpressionSyntax expr, HashSet<string> tracked, SemanticModel model, List<object> nodes)
{
    var overspanned = new SortedSet<string>(StringComparer.Ordinal);
    foreach (var node in expr.DescendantNodesAndSelf().OfType<ExpressionSyntax>())
        if (FullViewOwner(node, model) is { } owner && tracked.Contains(owner))
            overspanned.Add(owner);
    foreach (var o in overspanned)
        nodes.Add(new { op = "overspan", var = o, line = LineOf(expr) });
}

// A pure DEF of its variable — a bare identifier that is the LHS of a SIMPLE assignment (`v = …`) or
// an `out` argument (`F(out v)`): it WRITES the variable without reading the current value, so it is
// not a use of the resource. A `ref` argument is deliberately NOT a pure write — the callee receives
// (and may read) the current value, so `ref v` is a USE as well as a possible rebind (Codex review on
// #98). Element/member writes (`v[0] = …`, `v.X = …`) read `v` to reach the target, so only a bare
// identifier on the assignment's Left (or an `out` slot) qualifies. Excludes pure defs from the use scan.
static bool IsPureWrite(IdentifierNameSyntax idn) =>
    (idn.Parent is AssignmentExpressionSyntax asg
        && asg.IsKind(SyntaxKind.SimpleAssignmentExpression)
        && asg.Left == idn)
    || (idn.Parent is ArgumentSyntax arg
        && arg.RefKindKeyword.IsKind(SyntaxKind.OutKeyword)
        && arg.Expression == idn);

// A REBINDING of its variable — a pure write (above) OR a `ref` argument (the callee may reassign it).
// The b′ reassignment check treats any of these, between a view local's declaration and a later
// reference, as dropping the declared owner. A `ref` is also a USE (it is not an IsPureWrite), so it
// still emits a use of the current owner at its own position and only suppresses LATER references.
static bool IsRebind(IdentifierNameSyntax idn) =>
    IsPureWrite(idn)
    || (idn.Parent is ArgumentSyntax arg
        && arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword)
        && arg.Expression == idn);

// The field name an expression refers to: "_f" for `_f` or `this._f`, else null.
static string? FieldName(ExpressionSyntax expr) => expr switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m => m.Name.Identifier.Text,
    _ => null,
};

// The field name an expression refers to ONLY when it names a field of THIS object — a bare
// `_f` or `this._f`, NOT `other._f` (a same-named field on a DIFFERENT receiver, which plain
// text matching would conflate into a phantom release/use, CodeRabbit). Deliberately syntactic,
// not symbol-bound: the field-UAF corpus uses types that do not resolve in the project-local
// compilation, so binding on the field's TYPE is unreliable — the `this`/bare receiver shape is
// exact regardless.
static string? ThisFieldName(ExpressionSyntax expr) => expr switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m when m.Expression is ThisExpressionSyntax
        => m.Name.Identifier.Text,
    _ => null,
};

// Is there a disposed-flag early-return guard (`if (_disposed) return;`, `if (IsDisposed) return;`)
// among a handler body's TOP-LEVEL statements that OPENS before source position `before`? Such a
// guard makes a later disposed-field read safe (the canonical fix), so the field-UAF pass excludes
// it. Tight on purpose (CodeRabbit/Codex): (1) the guard must PRECEDE the read — a guard only after
// the read does not protect it, so that finding still stands; (2) the THEN branch must be an
// IMMEDIATE `return` (the guard's own action), not a `return` buried in a nested/`else` branch; and
// (3) the flag identifier matches "dispos" case-INsensitively, so the PascalCase `IsDisposed` form
// is recognised as well as `_disposed`.
static bool DisposedGuardBefore(BlockSyntax body, int before) =>
    body.Statements.OfType<IfStatementSyntax>().Any(ifs =>
        ifs.SpanStart < before
        && ifs.Condition.DescendantNodesAndSelf().OfType<IdentifierNameSyntax>()
            .Any(id => id.Identifier.Text.Contains("ispos", StringComparison.OrdinalIgnoreCase))
        && (ifs.Statement is ReturnStatementSyntax
            || (ifs.Statement is BlockSyntax gb
                && gb.Statements.FirstOrDefault() is ReturnStatementSyntax)));

// The released OWNER field reached by a read of field `f`: `f` itself when it is a released owner
// (an IDisposable or `IMemoryOwner<T>` field released in Dispose), or — when `f` is a `Memory` VIEW
// field — the owner it aliases, provided that owner is released. Null when `f` reaches no released
// owner. Unifies the direct disposed-field read (#75/#76) with the pooled-view-in-a-field dangle:
// reading `_view` (a borrow of `_owner`) after `_owner`'s release is a use of `_owner` after release.
static string? ReleasedOwner(string f, Dictionary<string, int> releasedAt,
    Dictionary<string, string> viewFieldOwner) =>
    releasedAt.ContainsKey(f) ? f
    : viewFieldOwner.TryGetValue(f, out var owner) && releasedAt.ContainsKey(owner) ? owner
    : null;

// The FIRST read of a released owner — directly (`_f.Member`) or through a Memory VIEW field that
// aliases it — in `body` that is NOT protected by an opening disposed-guard. Returns the member-
// access node and the OWNER field, or null when the body has no such read (or its first such read is
// already guarded, the canonical-fix shape). Shared by the direct handler scan and the one-hop
// helper scan (an indirect use through a private helper).
static (MemberAccessExpressionSyntax Use, string Field)? FirstUnguardedDisposedRead(
    BlockSyntax body, Dictionary<string, int> releasedAt, Dictionary<string, string> viewFieldOwner)
{
    foreach (var ma in body.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
    {
        if (ma.Name.Identifier.Text is "Dispose" or "DisposeAsync")
            continue;
        if (ThisFieldName(ma.Expression) is { } f && ReleasedOwner(f, releasedAt, viewFieldOwner) is { } owner)
            return DisposedGuardBefore(body, ma.SpanStart) ? null : (ma, owner);
    }
    return null;
}

// The method name of a SELF call (`Refresh()` or `this.Refresh()`), i.e. an instance method of the
// same object — NOT `other.Refresh()`. Used to chase a handler's ONE hop into a same-class helper.
static string? SelfCallName(InvocationExpressionSyntax inv) => inv.Expression switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax m when m.Expression is ThisExpressionSyntax
        => m.Name.Identifier.Text,
    _ => null,
};

// A private INSTANCE helper (default-private or explicit `private`, and not static/virtual/abstract/
// override or a wider accessibility) — the shape of an internal `Refresh()`-style helper a handler
// delegates to. Restricting the one-hop chase to these keeps the indirect field-UAF check low-FP
// (a public/virtual method has a broader contract than a same-class callback helper).
static bool IsPrivateInstanceHelper(MethodDeclarationSyntax m) =>
    !m.Modifiers.Any(mod => mod.IsKind(SyntaxKind.PublicKeyword)
        || mod.IsKind(SyntaxKind.ProtectedKeyword)
        || mod.IsKind(SyntaxKind.InternalKeyword)
        || mod.IsKind(SyntaxKind.StaticKeyword)
        || mod.IsKind(SyntaxKind.VirtualKeyword)
        || mod.IsKind(SyntaxKind.AbstractKeyword)
        || mod.IsKind(SyntaxKind.OverrideKeyword));

// Is `t` the System.Buffers.ArrayPool<T> type — the Return-based pool we model?
// Checked on the resolved SYMBOL, not the receiver's text, so an aliased receiver
// (`ArrayPool<int> p = ArrayPool<int>.Shared; p.Rent(n)`) binds correctly and an
// unrelated API with "pool" in its name does not false-match. ArrayPool-specific by
// design: MemoryPool<T>.Rent hands back an IMemoryOwner<T> released by Dispose (there
// is no MemoryPool.Return), so a pooled MemoryPool owner rides the IDisposable path,
// not this Return-based one.
static bool IsArrayPoolType(INamedTypeSymbol? t)
{
    if (t is null || t.Name != "ArrayPool")
        return false;
    INamespaceSymbol? ns = t.ContainingNamespace;
    if (ns is null || ns.Name != "Buffers")
        return false;
    ns = ns.ContainingNamespace;   // System.Buffers -> System
    return ns is not null && ns.Name == "System"
        && ns.ContainingNamespace is { IsGlobalNamespace: true };
}

// An ArrayPool<T> `Rent(...)` call — the acquire of a pooled buffer. Resolved via the
// SemanticModel (`model`), so the receiver may be any expression of ArrayPool<T> type.
static bool IsPoolRent(ExpressionSyntax? e, SemanticModel model) =>
    e is InvocationExpressionSyntax i
    && model.GetSymbolInfo(i).Symbol is IMethodSymbol { Name: "Rent" } sym
    && IsArrayPoolType(sym.ContainingType);

// An ArrayPool<T> `Return(buf)` call — the RELEASE of the pooled buffer `buf`. Unlike
// Dispose (where the tracked local is the receiver), the buffer is the first ARGUMENT
// and the pool is the receiver. Resolved via the SemanticModel. Returns the buffer
// name (a plain local) or null.
static string? PoolReturnBuffer(ExpressionSyntax e, SemanticModel model) =>
    e is InvocationExpressionSyntax i
        && model.GetSymbolInfo(i).Symbol is IMethodSymbol { Name: "Return" } sym
        && IsArrayPoolType(sym.ContainingType)
        && i.ArgumentList.Arguments.Count > 0
        && i.ArgumentList.Arguments[0].Expression is IdentifierNameSyntax buf
        ? buf.Identifier.Text : null;

// Is `idn` a pooled buffer passed as an argument to a CONSTRUCTOR whose result ESCAPES this method —
// `return new Wrapper(…, buf, …)` or `_field = new Wrapper(…, buf, …)`? Such a `new` hands the buffer
// to the constructed object, which becomes responsible for Return, so the buffer leaves the method
// inside the escaping object (an ownership transfer, not a borrow). One level only: the `new` must be
// the direct return value or assigned to a real FIELD — a `new` stored in a LOCAL stays a borrow (the
// local is method-scoped; a wrapper that never leaves the method and never Returns the buffer is a
// real leak, Codex), as does a `new` buried in another expression. The field check is symbol-based
// (`IFieldSymbol`) so an assignment to a same-named LOCAL is not mistaken for a field.
static bool PassedToEscapingCtor(IdentifierNameSyntax idn, SemanticModel model) =>
    idn.Parent is ArgumentSyntax { Parent: ArgumentListSyntax
            { Parent: BaseObjectCreationExpressionSyntax oce } }
    && (oce.Parent is ReturnStatementSyntax
        || (oce.Parent is AssignmentExpressionSyntax a && a.Right == oce
            && model.GetSymbolInfo(a.Left).Symbol is IFieldSymbol));

// Is `t` the System.Buffers.MemoryPool<T> type — the Dispose-based pool. Mirrors IsArrayPoolType
// (checked on the resolved symbol, so an aliased/injected `MemoryPool<T>` receiver binds and a
// look-alike does not).
static bool IsMemoryPoolType(INamedTypeSymbol? t)
{
    if (t is null || t.Name != "MemoryPool")
        return false;
    INamespaceSymbol? ns = t.ContainingNamespace;   // System.Buffers
    if (ns is null || ns.Name != "Buffers")
        return false;
    ns = ns.ContainingNamespace;                     // System.Buffers -> System
    return ns is not null && ns.Name == "System"
        && ns.ContainingNamespace is { IsGlobalNamespace: true };
}

// A MemoryPool<T>.Shared.Rent(...) call — the acquire of an IMemoryOwner<T>. There is NO
// MemoryPool.Return: the owner is released by Dispose (the IDisposable path), so unlike an ArrayPool
// buffer it is NOT a `poolBuffer`. A Rent'd owner never disposed leaks (OWN001), a second Dispose is
// a double release (OWN003), and a use of the owner after Dispose is a use-after-release (OWN002).
static bool IsMemoryPoolRent(ExpressionSyntax? e, SemanticModel model) =>
    e is InvocationExpressionSyntax i
    && model.GetSymbolInfo(i).Symbol is IMethodSymbol { Name: "Rent" } sym
    && IsMemoryPoolType(sym.ContainingType);

// The owner buffer a Span/ReadOnlySpan/Memory/ReadOnlyMemory VIEW expression borrows from:
// `owner.AsSpan(...)` / `owner.AsMemory(...)`, `new Span<T>(owner, …)` / `new Memory<T>(owner)`
// (and the ReadOnly* forms), or `owner.Memory` / `owner.Memory.Span` of a `System.Buffers.
// IMemoryOwner<T>` (a MemoryPool rental), where the source is a local identifier. Returns the owner local name,
// else null. The BORROW is recognised by the RESOLVED BCL symbols — `System.MemoryExtensions`
// `AsSpan`/`AsMemory` (which alias the receiver array) and the `System.Span<T>` / `ReadOnlySpan<T>`
// / `Memory<T>` / `ReadOnlyMemory<T>` constructor (which wraps the array argument) — NOT by name, so
// a project's own `AsSpan`/`AsMemory`, or a non-`System` look-alike type, is not mistaken for a
// borrow of `owner` (Codex). `Span` is a ref-struct borrow that cannot escape the method; `Memory`
// CAN escape (return / field), so a `Memory` view returned after the owner is released is a dangling
// borrow that leaves the method — in both cases a use of the view after the owner's release is a use
// of the owner after its release.
static string? ViewOwner(ExpressionSyntax? e, SemanticModel model)
{
    if (e is InvocationExpressionSyntax inv
        && inv.Expression is MemberAccessExpressionSyntax m
        && m.Name.Identifier.Text is "AsSpan" or "AsMemory"
        && m.Expression is IdentifierNameSyntax recv
        && model.GetSymbolInfo(inv).Symbol is IMethodSymbol { ContainingType: { Name: "MemoryExtensions" } mct }
        && IsInNamespace(mct, "System"))
        return recv.Identifier.Text;
    if (e is BaseObjectCreationExpressionSyntax oc          // explicit OR target-typed `new(buf, …)`
        && oc.ArgumentList is { Arguments.Count: > 0 }
        && oc.ArgumentList.Arguments[0].Expression is IdentifierNameSyntax arg
        && model.GetSymbolInfo(oc).Symbol is IMethodSymbol
            { ContainingType: { Name: "Span" or "ReadOnlySpan" or "Memory" or "ReadOnlyMemory" } sct }
        && IsInNamespace(sct, "System"))
        return arg.Identifier.Text;
    // owner.Memory — a Memory<T> view of a System.Buffers.IMemoryOwner<T> (e.g. a MemoryPool rental).
    // Like array.AsMemory(), the Memory CAN escape (return / field); a use of the view after the
    // owner's Dispose is a use of the owner after release (OWN002), and a returned Memory after
    // Dispose is a dangling borrow. Recognised by the resolved `IMemoryOwner<T>.Memory` property.
    if (e is MemberAccessExpressionSyntax mem
        && mem.Name.Identifier.Text == "Memory"
        && mem.Expression is IdentifierNameSyntax mo
        && model.GetSymbolInfo(mem).Symbol is IPropertySymbol { ContainingType: { Name: "IMemoryOwner" } ict }
        && IsInNamespace(ict, "System", "Buffers"))
        return mo.Identifier.Text;
    // owner.Memory.Span — the Span<T> of that Memory view (a ref-struct borrow that cannot escape).
    if (e is MemberAccessExpressionSyntax { Name.Identifier.Text: "Span" } spanAcc
        && spanAcc.Expression is MemberAccessExpressionSyntax
            { Name.Identifier.Text: "Memory", Expression: IdentifierNameSyntax mo2 } innerMem
        && model.GetSymbolInfo(innerMem).Symbol is IPropertySymbol { ContainingType: { Name: "IMemoryOwner" } ict2 }
        && IsInNamespace(ict2, "System", "Buffers"))
        return mo2.Identifier.Text;
    return null;
}

// Is `t` System.Buffers.IMemoryOwner<T> — the interface itself, or a concrete type that implements
// it? Resolved on the SYMBOL, so a fully-qualified `System.Buffers.IMemoryOwner<T>`, a type alias, or
// a concrete owner type is recognised — not only the bare `IMemoryOwner` spelling (CodeRabbit/Codex).
static bool IsMemoryOwnerType(ITypeSymbol? t) =>
    t is INamedTypeSymbol nt
    && ((nt.Name == "IMemoryOwner" && IsInNamespace(nt, "System", "Buffers"))
        || nt.AllInterfaces.Any(i => i.Name == "IMemoryOwner" && IsInNamespace(i, "System", "Buffers")));

// The owner FIELD a `Memory` view assignment aliases — `_owner.Memory` / `this._owner.Memory` of an
// IMemoryOwner<T> field. Uses the this/bare receiver restriction (ThisFieldName), so `other._owner.
// Memory` (another instance's owner) is NOT recorded and the this-qualified spelling IS (Codex). The
// borrow is recognised by the resolved `IMemoryOwner<T>.Memory` property symbol, not by name.
static string? FieldViewOwner(ExpressionSyntax e, SemanticModel model) =>
    e is MemberAccessExpressionSyntax { Name.Identifier.Text: "Memory" } mem
    && model.GetSymbolInfo(mem).Symbol is IPropertySymbol { ContainingType: { Name: "IMemoryOwner" } ict }
    && IsInNamespace(ict, "System", "Buffers")
        ? ThisFieldName(mem.Expression)
        : null;

// The tracked owner buffer a FULL-LENGTH view spans, else null. POOL005: `buf.AsSpan()` /
// `buf.AsMemory()` with NO arguments span `[0, Length)` — the WHOLE backing array — and so does
// `buf.AsSpan(0, buf.Length)` / `new Span<T>(buf, 0, buf.Length)`, whose length argument is the
// buffer's OWN oversized `.Length` (the `.Length` spelling); `new Span<T>(buf)` (only the array) too.
// A pooled array is oversized (`ArrayPool.Rent(n)` returns `Length >= n`), so such a view reaches
// past the logical length `n` into the stale `[n, Length)` tail (a previous renter's bytes): reading
// or copying through it processes that stale data — a correctness bug and a potential disclosure. A
// view bounded to the REAL rented length (`buf.AsSpan(0, n)`, `new Span<T>(buf, 0, n)`) returns null
// — it does not over-read. Recognised by the SAME resolved BCL symbols as `ViewOwner`, so a
// project's own `AsSpan`/`Span` look-alike is not mistaken for the over-read.
static string? FullViewOwner(ExpressionSyntax? e, SemanticModel model)
{
    if (e is InvocationExpressionSyntax inv
        && inv.Expression is MemberAccessExpressionSyntax m
        && m.Name.Identifier.Text is "AsSpan" or "AsMemory"
        && m.Expression is IdentifierNameSyntax recv
        && model.GetSymbolInfo(inv).Symbol is IMethodSymbol { ContainingType: { Name: "MemoryExtensions" } mct }
        && IsInNamespace(mct, "System"))
    {
        var args = inv.ArgumentList.Arguments;
        // `buf.AsSpan()` (no bound) spans the whole array; so does `buf.AsSpan(0, buf.Length)`,
        // whose length argument is the buffer's OWN oversized `.Length` (the `.Length` spelling). The
        // start must be 0 — `buf.AsSpan(k, buf.Length)` for k != 0 is out of range, not this pattern.
        if (args.Count == 0
            || (args.Count == 2 && IsZeroInt(args[0].Expression, model)
                && IsLengthOf(args[1].Expression, recv.Identifier.Text)))
            return recv.Identifier.Text;
    }
    if (e is BaseObjectCreationExpressionSyntax oc
        && oc.ArgumentList is { Arguments.Count: > 0 } al
        && al.Arguments[0].Expression is IdentifierNameSyntax arg
        && model.GetSymbolInfo(oc).Symbol is IMethodSymbol
            { ContainingType: { Name: "Span" or "ReadOnlySpan" or "Memory" or "ReadOnlyMemory" } sct }
        && IsInNamespace(sct, "System"))
    {
        // `new Span<T>(buf)` (whole array) or `new Span<T>(buf, 0, buf.Length)` (start 0, length the
        // oversized self-length).
        if (al.Arguments.Count == 1
            || (al.Arguments.Count == 3 && IsZeroInt(al.Arguments[1].Expression, model)
                && IsLengthOf(al.Arguments[2].Expression, arg.Identifier.Text)))
            return arg.Identifier.Text;
    }
    return null;
}

// `arg` is the buffer's own `.Length` (`buf.Length`) — the POOL005 `.Length` spelling, where the
// oversized backing length is passed as the operative length/count instead of the rented `n`.
static bool IsLengthOf(ExpressionSyntax arg, string owner) =>
    arg is MemberAccessExpressionSyntax { Name.Identifier.Text: "Length",
                                          Expression: IdentifierNameSyntax id }
    && id.Identifier.Text == owner;

// `arg` is the constant `0` — the start/index of a `.Length`-spelled view (`buf.AsSpan(0, buf.Length)`)
// so the view spans the WHOLE array, not an interior slice. Resolved via the constant value, so a
// `const`, `0x0`, etc. all count.
static bool IsZeroInt(ExpressionSyntax arg, SemanticModel model) =>
    model.GetConstantValue(arg) is { HasValue: true, Value: int v } && v == 0;

// The this/bare FIELD a FULL-LENGTH view spans, else null. The POOL005 FIELD twin of FullViewOwner:
// `_buf.AsSpan()` / `this._buf.AsMemory()` (no bound), `_buf.AsSpan(0, _buf.Length)` (the `.Length`
// spelling), `new Span<T>(_buf)` / `new Span<T>(_buf, 0, _buf.Length)` over a buffer the class held
// in a FIELD. The receiver is resolved through `ThisFieldName` (a bare `_buf` or `this._buf`, never
// `other._buf`), so a full-length view of a pooled FIELD — whose over-read the LOCAL-only flow pass
// never reaches — is found; the caller gates on the field actually being a pooled rent. Recognised by
// the SAME resolved BCL symbols as FullViewOwner (`System.MemoryExtensions` AsSpan/AsMemory, the
// `System.Span<T>`/… constructor), so a project's own look-alike is not mistaken for the over-read. A
// view bounded to the real rented `n` (`_buf.AsSpan(0, n)`) returns null — it does not over-read.
static string? FullViewFieldOwner(ExpressionSyntax? e, SemanticModel model)
{
    if (e is InvocationExpressionSyntax inv
        && inv.Expression is MemberAccessExpressionSyntax m
        && m.Name.Identifier.Text is "AsSpan" or "AsMemory"
        && ThisFieldName(m.Expression) is { } recv
        && model.GetSymbolInfo(inv).Symbol is IMethodSymbol { ContainingType: { Name: "MemoryExtensions" } mct }
        && IsInNamespace(mct, "System"))
    {
        var args = inv.ArgumentList.Arguments;
        if (args.Count == 0
            || (args.Count == 2 && IsZeroInt(args[0].Expression, model)
                && IsFieldLengthOf(args[1].Expression, recv)))
            return recv;
    }
    if (e is BaseObjectCreationExpressionSyntax oc
        && oc.ArgumentList is { Arguments.Count: > 0 } al
        && ThisFieldName(al.Arguments[0].Expression) is { } arg
        && model.GetSymbolInfo(oc).Symbol is IMethodSymbol
            { ContainingType: { Name: "Span" or "ReadOnlySpan" or "Memory" or "ReadOnlyMemory" } sct }
        && IsInNamespace(sct, "System"))
    {
        if (al.Arguments.Count == 1
            || (al.Arguments.Count == 3 && IsZeroInt(al.Arguments[1].Expression, model)
                && IsFieldLengthOf(al.Arguments[2].Expression, arg)))
            return arg;
    }
    return null;
}

// `arg` is the pooled FIELD's own `.Length` (`_buf.Length` / `this._buf.Length`) — the FIELD twin of
// IsLengthOf, resolving the `.Length` receiver through `ThisFieldName` so the this-qualified spelling
// counts and `other._buf.Length` does not.
static bool IsFieldLengthOf(ExpressionSyntax arg, string field) =>
    arg is MemberAccessExpressionSyntax { Name.Identifier.Text: "Length" } ma
    && ThisFieldName(ma.Expression) == field;

// If `idn` references a Span/ReadOnlySpan/Memory/ReadOnlyMemory VIEW local declared from an owner
// buffer (`Memory<T> view = owner.AsMemory(…)`), the owner buffer's local name — so a use of the
// view (including RETURNING it, an escape) lowers to a use of the owner (the borrow). Resolved
// through the view local's own declaration, so it is inert for any identifier that is not such a
// view (returns null -> ordinary handling).
static string? ViewOwnerOf(IdentifierNameSyntax idn, SemanticModel model)
{
    if (model.GetSymbolInfo(idn).Symbol is not ILocalSymbol sym)
        return null;
    foreach (var r in sym.DeclaringSyntaxReferences)
        if (r.GetSyntax() is VariableDeclaratorSyntax { Initializer.Value: { } init } decl)
        {
            // b′ (pooled-view reassignment FP): the declaration's owner holds only until `view` is
            // REASSIGNED. If a `view = …` (or a `ref`/`out` rebinding) of this same local sits between
            // the declaration and THIS reference (source order), the reference no longer borrows the
            // declared owner — its current owner is unknown, so go silent rather than attribute it to a
            // possibly-released buffer. This only ever REMOVES a use (errs to a false negative, never a
            // false positive). Matched on the resolved symbol, so a same-named local elsewhere is not
            // mistaken for a rebinding. (Full flow-sensitive per-path provenance is left for later.)
            if (ReassignedBetween(sym, decl, idn, model))
                return null;
            return ViewOwner(init, model);
        }
    return null;
}

// Is the local `sym` REBOUND (IsRebind: a direct `=` target, an `out`, or a `ref` argument) at a
// source position strictly after its declaration `decl` and strictly before the reference `use`,
// within the declaring member? Source-order and intraprocedural: straight-line code is exact; a
// reassignment on a non-taken branch suppresses conservatively (a possible miss, never a false
// positive). The b′ predicate behind ViewOwnerOf's reassignment suppression. Four writes do NOT
// count, because their effect is not yet visible to the use (all Codex/CodeRabbit review on #98):
// one in the SAME assignment as the use (`v = v.Slice(1)` — the RHS reads the still-current view);
// one that is a `ref`/`out` ARGUMENT of the same call as the use (`Reinit(out v, v[0])` — arguments
// evaluate before the callee writes the parameter); one in a `for` INCREMENTOR enclosing the use
// (`for (;;v=default) { v[0]=…; }` — the incrementor runs after the body, not at its header position);
// and one nested in a deferred body (a lambda / local function runs on invoke, not at its textual position).
static bool ReassignedBetween(ILocalSymbol sym, VariableDeclaratorSyntax decl,
                              IdentifierNameSyntax use, SemanticModel model)
{
    var scope = decl.Ancestors().FirstOrDefault(n =>
        n is BaseMethodDeclarationSyntax or AccessorDeclarationSyntax or LocalFunctionStatementSyntax);
    if (scope is null)
        return false;
    var useAssign = use.FirstAncestorOrSelf<AssignmentExpressionSyntax>();
    int lo = decl.SpanStart, hi = use.SpanStart;
    foreach (var id in scope.DescendantNodes().OfType<IdentifierNameSyntax>())
    {
        if (id.SpanStart <= lo || id.SpanStart >= hi || !IsRebind(id))
            continue;
        if (useAssign is not null && id.FirstAncestorOrSelf<AssignmentExpressionSyntax>() == useAssign)
            continue;                                   // the use's OWN assignment, not a prior rebind
        if (id.Parent is ArgumentSyntax { Parent: ArgumentListSyntax args } && args.Span.Contains(use.Span))
            continue;                                   // ref/out rebind in the SAME call: args evaluate before the callee writes
        if (id.Ancestors().OfType<ForStatementSyntax>()
               .FirstOrDefault(f => f.Incrementors.Any(i => i.Span.Contains(id.Span))) is { } forInc
            && forInc.Span.Contains(use.Span))
            continue;                                   // for-incrementor rebind runs AFTER the body, not at its header position
        if (InDeferredBody(id, scope))
            continue;                                   // a write inside a lambda/local fn does not run here
        if (SymbolEqualityComparer.Default.Equals(model.GetSymbolInfo(id).Symbol, sym))
            return true;
    }
    return false;
}

// Is `node` nested inside a lambda or local function that lies between it and `scope`? Such a body is
// DEFERRED — its statements run when it is invoked, not at their textual position — so the source-
// order reassignment scan must not treat a write inside one as a straight-line rebind (CodeRabbit #98).
static bool InDeferredBody(SyntaxNode node, SyntaxNode scope)
{
    for (var p = node.Parent; p is not null && p != scope; p = p.Parent)
        if (p is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax)
            return true;
    return false;
}

// The tracked owner buffers whose Span/Memory VIEW LOCALS are returned by `expr` (an escaping
// borrow — `return view` where `view` is `buf.AsMemory(…)`). The caller uses each such view AFTER
// this method's finally cleanup, so the return lowering re-emits the owner's use after the finally
// release(s). Distinct from a plain returned tracked local (excluded upstream as an escape) — here
// the borrow, not the owner, leaves the method, and the owner stays tracked.
static List<string> ReturnedViewOwners(ExpressionSyntax expr, HashSet<string> tracked, SemanticModel model)
{
    var owners = new List<string>();
    void AddOwner(string? owner)
    {
        if (owner is not null && tracked.Contains(owner) && !owners.Contains(owner))
            owners.Add(owner);
    }
    // Follow only the RETURNED VALUE's own structure — a view LOCAL (`return view`), an inline view
    // expression (`return buf.AsMemory(…)`), through casts / parentheses / `?:`. A member or call
    // RESULT of a view (`return view.Length`, an int) does NOT escape the view, so it is not visited
    // — scanning every descendant identifier would wrongly flag it (CodeRabbit).
    void Visit(ExpressionSyntax e)
    {
        AddOwner(ViewOwner(e, model));
        switch (e)
        {
            case IdentifierNameSyntax idn when !tracked.Contains(idn.Identifier.Text):
                AddOwner(ViewOwnerOf(idn, model));
                break;
            case ParenthesizedExpressionSyntax p:
                Visit(p.Expression);
                break;
            case CastExpressionSyntax c:
                Visit(c.Expression);
                break;
            case ConditionalExpressionSyntax q:
                Visit(q.WhenTrue);
                Visit(q.WhenFalse);
                break;
        }
    }
    Visit(expr);
    return owners;
}

// A factory call that CREATES and hands back a fresh owned IDisposable the caller must
// release — recognised via the resolved symbol (curated, the same spirit as
// IsDisposableType is for `new`). Two families:
//   * System.IO.File.Open*/Create*/*Text -> a NEW FileStream / StreamReader / StreamWriter
//     the caller owns exactly as if it had `new`'d one.
//   * System.Security.Cryptography static `Create*` factories -> a NEW owned IDisposable:
//     RandomNumberGenerator.Create(), Aes.Create(), SHA256.Create(), RSA.Create(),
//     IncrementalHash.CreateHash(), ... (guarded by static + Create-prefixed + the RESULT
//     implementing IDisposable + the crypto namespace, so an instance `CreateEncryptor()` or
//     a non-IDisposable `CreateFromName()` is never mistaken for one).
// Curated + symbol-resolved, so a borrowed/cached disposable handed back by some other API is
// never mistaken for an owned acquire (precision over recall — the set grows only as
// ownership is certain).
static bool IsOwningFactory(ExpressionSyntax? e, SemanticModel model)
{
    if (e is not InvocationExpressionSyntax i
        || model.GetSymbolInfo(i).Symbol is not IMethodSymbol sym)
        return false;
    if (sym.Name is "OpenRead" or "OpenWrite" or "Open" or "Create"
                 or "OpenText" or "CreateText" or "AppendText"
        && sym.ContainingType is { Name: "File" } ft
        && IsInNamespace(ft, "System", "IO"))
        return true;
    if (sym.IsStatic
        && sym.Name.StartsWith("Create", StringComparison.Ordinal)
        && ImplementsIDisposable(sym.ReturnType)
        && IsInNamespace(sym.ContainingType, "System", "Security", "Cryptography"))
        return true;
    return false;
}

// Is the type `t` declared in the namespace named by `parts` (outermost-first), e.g.
// IsInNamespace(t, "System", "IO") for System.IO? Walks the containing-namespace chain
// and requires it to bottom out at the global namespace (so `System.IO` matches but a
// nested `Foo.System.IO` would not).
static bool IsInNamespace(INamedTypeSymbol? t, params string[] parts)
{
    var ns = t?.ContainingNamespace;
    for (var k = parts.Length - 1; k >= 0; k--, ns = ns?.ContainingNamespace)
        if (ns is null || ns.Name != parts[k])
            return false;
    return ns is { IsGlobalNamespace: true };
}

// The local names of arguments handed to a first-party CONSUMER at this call — a method
// that takes ownership of the by-value IDisposable parameter the argument binds to and
// discharges it: either by disposing it directly, or by forwarding it to another first-party
// consumer (the transitive case, `ConsumesParam`). Such an argument's ownership moves into
// the callee and is discharged there, so the handoff is modelled as a RELEASE of the argument
// at the call site (the same shape as pool `Return(buf)`); a later use is then a
// use-after-handoff (OWN002). Inspecting each callee's OWN body means no cross-call signature
// table and no dangling-callee crash — a callee with no body (interface / abstract / extern)
// or that does not consume the param contributes nothing, and the argument stays an ordinary
// escape. Arguments resolve to parameters by NAME when `name:` is used, else by position.
static List<string> ConsumeReleaseArgs(ExpressionSyntax e, SemanticModel model)
{
    var consumed = new List<string>();
    if (e is not InvocationExpressionSyntax inv
        || model.GetSymbolInfo(inv).Symbol is not IMethodSymbol sym)
        return consumed;
    var args = inv.ArgumentList.Arguments;
    for (int i = 0; i < args.Count; i++)
    {
        // map argument -> parameter: by name for `name: value`, else by position.
        var p = args[i].NameColon is { } nc
            ? sym.Parameters.FirstOrDefault(q => q.Name == nc.Name.Identifier.Text)
            : (i < sym.Parameters.Length ? sym.Parameters[i] : null);
        if (p is not null
            && args[i].Expression is IdentifierNameSyntax aid
            && ConsumesParam(sym, p, model,
                             new HashSet<ISymbol>(SymbolEqualityComparer.Default)))
            consumed.Add(aid.Identifier.Text);
    }
    return consumed;
}

// The body of a first-party method or LOCAL FUNCTION (block or expression-bodied), scanning
// partial declarations; null for an interface/abstract/extern method (no body to inspect). A
// directly-called local function runs synchronously, so a forwarding chain through one must be
// followed too (CodeRabbit) — `LocalFunctionStatementSyntax` carries the same Body/ExpressionBody.
static SyntaxNode? ConsumerBody(IMethodSymbol sym)
{
    foreach (var r in sym.DeclaringSyntaxReferences)
        switch (r.GetSyntax())
        {
            case BaseMethodDeclarationSyntax d when ((SyntaxNode?)d.Body ?? d.ExpressionBody) is { } b:
                return b;
            case LocalFunctionStatementSyntax l when ((SyntaxNode?)l.Body ?? l.ExpressionBody) is { } lb:
                return lb;
        }
    return null;
}

// The invocations that run IMMEDIATELY when `body` executes — excluding those inside a nested
// lambda / local-function body, which run deferred (when the delegate is later invoked), not at
// this method's call boundary. The same deferred-body rule the flow lowering already uses, so a
// dispose/forward stored in a callback is not mistaken for an immediate discharge (Codex/CodeRabbit).
static IEnumerable<InvocationExpressionSyntax> ImmediateInvocations(SyntaxNode body) =>
    body.DescendantNodes(n => n is not (AnonymousFunctionExpressionSyntax
                                        or LocalFunctionStatementSyntax))
        .OfType<InvocationExpressionSyntax>();

// Does `method` CONSUME (take ownership of and discharge) its by-value IDisposable
// parameter `param`? Either (a) the body disposes it directly (`param.Dispose()`), or
// (b) — the transitive step — the body hands it to ANOTHER first-party consumer that
// consumes it (`Inner(param)` where `Inner` consumes its matching parameter). So a
// forwarding chain `Consume(sink) => Inner(sink) => sink.Dispose()` is recognised, and a
// caller's `Consume(s)` is still a handoff (a call-site release). Inspecting each callee's
// own body keeps it inter-procedural without a signature table; `visited` (keyed on the
// parameter) guards recursion on cyclic call graphs. Conservative: a param handed to an
// unknown/borrowing callee yields false (no release, no false OWN002).
static bool ConsumesParam(IMethodSymbol method, IParameterSymbol param,
                          SemanticModel model, HashSet<ISymbol> visited)
{
    if (param.RefKind != RefKind.None || !ImplementsIDisposable(param.Type))
        return false;
    if (!visited.Add(param.OriginalDefinition))
        return false;                          // cycle guard (per parameter)
    if (ConsumerBody(method) is not { } body)
        return false;                          // no body -> contributes nothing
    var name = param.Name;
    if (DisposesLocal(body, name))             // (a) disposes the parameter directly
        return true;
    // (b) transitive: the parameter is handed to another first-party consumer at an IMMEDIATE
    // call (not one deferred in a nested lambda/local function). The body may live in another
    // file, so bind its calls with that tree's OWN model (a SemanticModel only resolves nodes in
    // its own tree); the Compilation is shared across all parsed inputs.
    var bodyModel = model.Compilation.GetSemanticModel(body.SyntaxTree);
    foreach (var inv in ImmediateInvocations(body))
    {
        if (bodyModel.GetSymbolInfo(inv).Symbol is not IMethodSymbol callee)
            continue;
        var cargs = inv.ArgumentList.Arguments;
        for (int i = 0; i < cargs.Count; i++)
        {
            if (cargs[i].Expression is not IdentifierNameSyntax aid || aid.Identifier.Text != name)
                continue;
            var cp = cargs[i].NameColon is { } nc
                ? callee.Parameters.FirstOrDefault(q => q.Name == nc.Name.Identifier.Text)
                : (i < callee.Parameters.Length ? callee.Parameters[i] : null);
            if (cp is not null && ConsumesParam(callee, cp, model, visited))
                return true;
        }
    }
    return false;
}

// Does `body` dispose the local/parameter named `name` — a `name.Dispose()` / `.Close()` /
// `.DisposeAsync()` call (the consume signal)? Only IMMEDIATE calls count (`ImmediateInvocations`
// excludes nested lambda / local-function bodies): a `name.Dispose()` inside a stored callback
// runs deferred, not at this call site, so it is not a discharge here.
static bool DisposesLocal(SyntaxNode body, string name)
{
    foreach (var i in ImmediateInvocations(body))
        if (i.Expression is MemberAccessExpressionSyntax m
            && m.Name.Identifier.Text is "Dispose" or "Close" or "DisposeAsync"
            && m.Expression is IdentifierNameSyntax id && id.Identifier.Text == name)
            return true;
    return false;
}

// A field/local type treated as owned-disposable (syntax-only heuristic — no
// semantic model): a curated set plus a few suffixes. Gated on the class `new`ing
// the value, so injected/borrowed disposables are not flagged. Timer types are
// deliberately excluded: a `Tick`/`Elapsed` timer is the WPF002 pattern's job
// (released by Stop()/detach), and DispatcherTimer is not even IDisposable, so
// matching `*Timer` here would double-report and false-positive a stopped timer.
static bool IsDisposableType(string t) =>
    t is "IDisposable" or "IAsyncDisposable" or "CancellationTokenSource"
       or "HttpClient" or "SerialPort" or "SqlConnection"
    || ((t.EndsWith("Stream") || t.EndsWith("Reader") || t.EndsWith("Writer")
            || t.EndsWith("Subscription"))
        && !IsNonDisposableReaderWriter(t));

// BCL `…Reader`/`…Writer` types that the EndsWith name heuristic above matches but that are NOT
// IDisposable: System.IO.Pipelines `PipeReader`/`PipeWriter` finish via `Complete()`, not `Dispose()`.
// Excluding them stops the field-disposable detector flagging an undisposed PipeReader/PipeWriter
// field as a leak — a FALSE POSITIVE mined on Pipelines.Sockets.Unofficial (SocketConnection's
// `_input`/`_output`). Matched on the exact bare or `System.IO.Pipelines`-qualified spelling — NOT
// any simple-name match, so a project's own disposable `MyLib.PipeReader` is still flagged (Codex).
static bool IsNonDisposableReaderWriter(string t) =>
    t is "PipeReader" or "PipeWriter"
      or "System.IO.Pipelines.PipeReader" or "System.IO.Pipelines.PipeWriter";

// Is this field/local type an OWNED disposable? Prefer the RESOLVED type's real
// IDisposable/IAsyncDisposable interface: an in-project `…Writer`/`…Reader`/`…Stream`
// that is NOT actually IDisposable (ImageSharp's `Vp8BitWriter : BitWriterBase`, the
// `JpegBitReader` struct) must not be flagged by name alone. Generalises the #79
// PipeReader/PipeWriter exclusion — any resolved non-IDisposable type is excluded, no
// curated list needed. Only when the type does NOT resolve (an unreferenced external
// assembly — WPF/DevExpress on the Linux runner) do we fall back to the syntactic name
// heuristic, which is the whole reason that heuristic exists.
static bool IsOwnedDisposableType(TypeSyntax type, SemanticModel model)
{
    var sym = model.GetTypeInfo(type).Type;
    if (sym is null or IErrorTypeSymbol)
        return IsDisposableType(type.ToString());
    // Resolved: demand a REAL IDisposable, but keep the optional-dispose exemption
    // (Task/ValueTask/DataTable/DataSet/DataView) that the flat name path got for free —
    // their Dispose is a no-op / they hold only a lazy wait handle, so an undisposed field
    // of these is not a leak and must stay silent (Codex). Both helpers already exist and
    // are shared with the flow detector.
    return ImplementsIDisposable(sym) && !IsDisposeOptional(sym);
}

// --- P-006: DI registration + constructor graph (DI001 captive dependency) ---
// A syntactic pass over the same trees, independent of the event/disposable
// detectors: collect each class's constructor parameter types (the dependency
// graph), then each conventional IServiceCollection registration
// (Add{Singleton,Scoped,Transient}, the generic `<TService[, TImpl]>` form or the
// `typeof(...)` form) and emit `services` facts {name, lifetime, deps, file, line}
// that ownlang/di.py checks for captive dependencies. The registration's `name`
// is the SERVICE type others inject; `deps` are the IMPLEMENTATION's constructor
// parameter types. Factory/reflection/open-generic shapes we cannot read are
// recorded as unknown-dep nodes (deps: []) — silent, never guessed (P-006 scope).
static List<object> ExtractServices(List<(string file, SyntaxTree tree)> parsed)
{
    // 1. class name -> its widest constructor's parameter type names (the DI ctor).
    var ctorDeps = new Dictionary<string, List<string>>();
    // class name -> services injected via `WeakReference<T>` (held weakly). Kept apart
    // from ctorDeps so the strong DI001 graph never sees a weak edge; a weakly-held
    // scoped service is DI002 (the weak ref hides the GC symptom, not the lifetime bug).
    var ctorWeakDeps = new Dictionary<string, List<string>>();
    // class name -> does it implement IDisposable/IAsyncDisposable (so the container
    // owns its disposal)? Syntactic — its OWN base list names it; an inherited
    // disposable (`: Stream`) is not seen, so DI003 fires only on an explicitly
    // disposable impl, never a guessed one (precision over recall).
    var ctorDisposable = new Dictionary<string, bool>();
    // class name -> service types it resolves BY HAND off an injected IServiceProvider
    // (`provider.GetService<T>()` / `GetRequiredService<T>()`). For a SINGLETON that
    // provider is the root container, so a transient IDisposable resolved this way is
    // tracked to app shutdown: DI004 (the service-locator anti-pattern). A resolution
    // through a scope (`scope.ServiceProvider.GetRequiredService<T>()`) has a different
    // receiver and is deliberately NOT recorded — that pattern is correct.
    var classRootResolves = new Dictionary<string, List<string>>();
    // class name -> the resolution CALL SITE of each root-resolved type ({type, file, line}).
    // DI004's consumer is the GetRequiredService call site (not a ctor), so a finding anchors
    // at it; emitted as `root_resolve_sites` alongside `root_resolves`.
    var classRootResolveSites = new Dictionary<string, List<object>>();
    // class name -> service types it resolves from a scope it CREATES (`factory.CreateScope()` /
    // an injected provider's `.CreateScope()`) and then CACHES into a FIELD (DI005 — the
    // scope-per-operation fix done wrong), with the field-STORE call site of each. A scope-resolved
    // value USED in the scope and discarded (the correct shape) is not assigned to a field, so it
    // never enters here.
    var classScopeCached = new Dictionary<string, List<string>>();
    var classScopeCacheSites = new Dictionary<string, List<object>>();
    // class name -> its CONSUMING CONSTRUCTOR location (file, 1-based line): the widest
    // public ctor (or the class/primary-ctor declaration), where a captive dependency is
    // injected. A captive finding anchors at the registration site but names this too, so
    // the developer is pointed at the code, not just the wiring (P-006 open question #1).
    var classCtorLoc = new Dictionary<string, (string file, int line)>();
    foreach (var (ctorFile, tree) in parsed)
        foreach (var node in tree.GetRoot().DescendantNodes())
        {
            if (node is not ClassDeclarationSyntax cls)
                continue;
            // Candidate parameter lists: the C# 12 primary constructor (on the
            // class declaration itself) plus the PUBLIC explicit constructors —
            // take the widest. Primary-constructor injection (`class Foo(Dep d)`)
            // has no ConstructorDeclarationSyntax member, so it must be read off
            // the declaration or DI001 misses modern .NET 8 services; and the
            // default IServiceProvider only uses public constructors, so a wider
            // non-public ctor's parameters must not count as real deps (Codex).
            ParameterListSyntax? widest = cls.ParameterList;
            foreach (var m in cls.Members)
                if (m is ConstructorDeclarationSyntax ctor
                    && IsPublicCtor(ctor.Modifiers)
                    && (widest is null
                        || ctor.ParameterList.Parameters.Count > widest.Parameters.Count))
                    widest = ctor.ParameterList;
            var deps = new List<string>();
            var weakDeps = new List<string>();
            if (widest is not null)
                foreach (var p in widest.Parameters)
                {
                    if (p.Type is null)
                        continue;
                    // a `WeakReference<X>` parameter is a WEAK dep on X (not a strong dep):
                    // it keeps X off the DI001 graph, but a weakly-held scoped X is DI002.
                    if (WeakRefInner(p.Type) is { } weakInner)
                        weakDeps.Add(weakInner);
                    else if (DiTypeName(p.Type) is { } tn)
                        deps.Add(tn);
                }
            ctorDeps[cls.Identifier.Text] = deps;        // last decl wins (core dedups by name)
            ctorWeakDeps[cls.Identifier.Text] = weakDeps;
            // the consuming-constructor anchor: the widest public ctor's declaration (its
            // Parent), or the class declaration for a primary/implicit ctor. Points at the
            // code that injects the captive, surfaced as a finding's related location.
            var ctorNode = widest?.Parent ?? cls;
            classCtorLoc[cls.Identifier.Text] = (ctorFile,
                ctorNode.GetLocation().GetLineSpan().StartLinePosition.Line + 1);
            // OR across partial declarations: any part that names IDisposable makes the
            // type disposable, so a later `partial class C { }` (no base list, e.g. a
            // generated/designer file) cannot clear an earlier `partial class C : IDisposable`.
            ctorDisposable[cls.Identifier.Text] = ctorDisposable.GetValueOrDefault(cls.Identifier.Text)
                || (cls.BaseList is { } bl
                    && bl.Types.Any(bt => DiTypeName(bt.Type) is "IDisposable" or "IAsyncDisposable"));
            // DI004 — the names that refer to an injected IServiceProvider (the ROOT provider
            // for a singleton): the ctor parameters of type IServiceProvider (usable directly
            // in a primary-ctor class), plus any real class field assigned one of them. A
            // `name.GetService<T>()` / `GetRequiredService<T>()` call on such a name is then a
            // hand resolution off the root; a `scope.ServiceProvider.Get...` call has a
            // member-access receiver that is NOT one of these names, so it stays silent.
            var providerNames = new HashSet<string>();
            // the real class fields, so a ctor LOCAL alias can never enter providerNames: a
            // bare-identifier assignment LHS that is not a field would otherwise false-match a
            // same-named receiver in another scope and mint a DI004 false positive (CodeRabbit).
            var classFieldNames = new HashSet<string>(
                cls.Members.OfType<FieldDeclarationSyntax>()
                   .SelectMany(f => f.Declaration.Variables)
                   .Select(v => v.Identifier.Text));
            if (widest is not null)
                foreach (var p in widest.Parameters)
                    if (p.Type is not null && DiTypeName(p.Type) == "IServiceProvider")
                        providerNames.Add(p.Identifier.Text);
            // `_field = sp;` in any ctor — BLOCK- or EXPRESSION-bodied (an expression-bodied
            // ctor has a null Body, so scan the whole ctor's descendants, not just Body; Codex),
            // restricted to a real field so a local alias never matches.
            foreach (var mem in cls.Members)
                if (mem is ConstructorDeclarationSyntax ctorDecl)
                    foreach (var asg in ctorDecl.DescendantNodes().OfType<AssignmentExpressionSyntax>())
                        if (asg.Right is IdentifierNameSyntax rhs
                            && providerNames.Contains(rhs.Identifier.Text)
                            && AssignedFieldName(asg.Left) is { } fld
                            && classFieldNames.Contains(fld))
                            providerNames.Add(fld);
            // field initializers that capture an injected provider param (the primary-ctor
            // shape, e.g. `private readonly IServiceProvider _sp = sp;`).
            foreach (var fdecl in cls.Members.OfType<FieldDeclarationSyntax>())
                foreach (var v in fdecl.Declaration.Variables)
                    if (v.Initializer?.Value is IdentifierNameSyntax fInit
                        && providerNames.Contains(fInit.Identifier.Text))
                        providerNames.Add(v.Identifier.Text);
            var rootResolves = new List<string>();
            var rootResolveSites = new List<object>();
            if (providerNames.Count > 0)
            {
                var seenResolve = new HashSet<string>();
                foreach (var (resolved, line) in RootResolvedTypes(cls, providerNames))
                    if (seenResolve.Add(resolved))   // first call site per type wins
                    {
                        rootResolves.Add(resolved);
                        rootResolveSites.Add(new { type = resolved, file = ctorFile, line });
                    }
            }
            classRootResolves[cls.Identifier.Text] = rootResolves;
            classRootResolveSites[cls.Identifier.Text] = rootResolveSites;

            // DI005 — names whose `.CreateScope()` creates a child scope: an injected
            // `IServiceScopeFactory`, plus the injected provider itself (an injected provider's
            // `.CreateScope()` is equally a scope). A scoped service resolved off such a scope and
            // CACHED into a field (rather than used within the scope) is the scope-per-operation fix
            // done wrong. Collected with the SAME this-field discipline as providerNames so a local
            // alias never enters (no false store-match).
            var scopeCreatorNames = new HashSet<string>(providerNames);
            if (widest is not null)
                foreach (var p in widest.Parameters)
                    if (p.Type is not null && DiTypeName(p.Type) == "IServiceScopeFactory")
                        scopeCreatorNames.Add(p.Identifier.Text);
            foreach (var mem in cls.Members)
                if (mem is ConstructorDeclarationSyntax scfCtor)
                    foreach (var asg in scfCtor.DescendantNodes().OfType<AssignmentExpressionSyntax>())
                        if (asg.Right is IdentifierNameSyntax scfRhs
                            && scopeCreatorNames.Contains(scfRhs.Identifier.Text)
                            && AssignedFieldName(asg.Left) is { } scfFld
                            && classFieldNames.Contains(scfFld))
                            scopeCreatorNames.Add(scfFld);
            foreach (var fdecl in cls.Members.OfType<FieldDeclarationSyntax>())
                foreach (var v in fdecl.Declaration.Variables)
                    if (v.Initializer?.Value is IdentifierNameSyntax scfInit
                        && scopeCreatorNames.Contains(scfInit.Identifier.Text))
                        scopeCreatorNames.Add(v.Identifier.Text);
            var scopeCached = new List<string>();
            var scopeCacheSites = new List<object>();
            if (scopeCreatorNames.Count > 0)
            {
                var seenCached = new HashSet<string>();
                foreach (var (cachedType, cacheFile, line) in ScopeCachedTypes(cls, scopeCreatorNames, classFieldNames))
                    if (seenCached.Add(cachedType))   // first store per type wins
                    {
                        scopeCached.Add(cachedType);
                        scopeCacheSites.Add(new { type = cachedType, file = cacheFile, line });
                    }
            }
            classScopeCached[cls.Identifier.Text] = scopeCached;
            classScopeCacheSites[cls.Identifier.Text] = scopeCacheSites;
        }

    // 2. registrations -> service facts at the registration site.
    var services = new List<object>();
    foreach (var (file, tree) in parsed)
        foreach (var node in tree.GetRoot().DescendantNodes())
        {
            if (node is not InvocationExpressionSyntax inv
                || inv.Expression is not MemberAccessExpressionSyntax ma)
                continue;
            var lifetime = RegistrationLifetime(ma.Name.Identifier.Text);
            if (lifetime is null)
                continue;
            ResolveRegistration(ma.Name, inv.ArgumentList, out var service, out var impl);
            if (service is null)        // not a conventional typed registration -> skip
                continue;
            var deps = impl is not null && ctorDeps.TryGetValue(impl, out var d)
                ? d : new List<string>();
            var weakDeps = impl is not null && ctorWeakDeps.TryGetValue(impl, out var wd)
                ? wd : new List<string>();
            var rootResolves = impl is not null && classRootResolves.TryGetValue(impl, out var rr)
                ? rr : new List<string>();
            var rootResolveSites = impl is not null
                && classRootResolveSites.TryGetValue(impl, out var rrs) ? rrs : new List<object>();
            var scopeCached = impl is not null && classScopeCached.TryGetValue(impl, out var sca)
                ? sca : new List<string>();
            var scopeCacheSites = impl is not null
                && classScopeCacheSites.TryGetValue(impl, out var scas) ? scas : new List<object>();
            var (ctorFile, ctorLine) = impl is not null && classCtorLoc.TryGetValue(impl, out var cl)
                ? cl : ("?", 0);
            services.Add(new
            {
                name = service,
                lifetime,
                deps,
                weak_deps = weakDeps,
                // the IMPLEMENTATION's disposability — the container constructs and
                // disposes the impl, so a transient-disposable impl captured by a
                // singleton is held to app exit (DI003).
                disposable = impl is not null && ctorDisposable.TryGetValue(impl, out var disp) && disp,
                // the IMPLEMENTATION's scope-cached scoped services (DI005): a scoped service
                // resolved off a scope it creates and cached into a field — the captive the scope
                // was meant to avoid, plus the field-store site each finding anchors at.
                scope_cached = scopeCached,
                scope_cache_sites = scopeCacheSites,
                // the IMPLEMENTATION's by-hand resolutions off its injected provider — for a
                // singleton, the root; a transient IDisposable resolved this way is DI004.
                root_resolves = rootResolves,
                // the resolution CALL SITE of each — DI004 anchors at it (its real consumer).
                root_resolve_sites = rootResolveSites,
                file,
                line = node.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
                // the IMPLEMENTATION's consuming-constructor location (P-006 Q#1): where the
                // captive is injected, a finding's second anchor beside the registration site.
                ctor_file = ctorFile,
                ctor_line = ctorLine,
                // the IMPLEMENTATION type that owns that ctor — named in the finding instead of
                // the (possibly interface) service `name`, which has no constructor (Codex).
                ctor_type = impl ?? service,
            });
        }
    return services;
}

// The DI lifetime for an IServiceCollection registration method, or null when the
// method name is not one of the three conventional registrations.
static string? RegistrationLifetime(string method) => method switch
{
    "AddSingleton" => "singleton",
    "AddScoped" => "scoped",
    "AddTransient" => "transient",
    _ => null,
};

// Service + implementation type for a registration, from the generic type
// arguments (`Add*<TService[, TImpl]>`) or the `typeof(...)` arguments
// (`Add*(typeof(TService)[, typeof(TImpl)])`). A null service means it is not a
// typed registration we can read (a bare instance / factory) -> the caller skips.
static void ResolveRegistration(SimpleNameSyntax name, ArgumentListSyntax args,
                                out string? service, out string? impl)
{
    service = null;
    impl = null;
    if (name is GenericNameSyntax gen)
    {
        var targs = gen.TypeArgumentList.Arguments;
        if (targs.Count >= 1)
            service = DiTypeName(targs[0]);
        impl = targs.Count >= 2 ? DiTypeName(targs[1]) : service;
        return;
    }
    string? first = null, second = null;
    var seen = 0;
    foreach (var a in args.Arguments)
        if (a.Expression is TypeOfExpressionSyntax tof)
        {
            if (seen == 0) first = DiTypeName(tof.Type);
            else if (seen == 1) second = DiTypeName(tof.Type);
            seen++;
        }
    if (first is not null)
    {
        service = first;
        impl = second ?? first;
    }
}

// The simple (rightmost) name of a type, for matching a registration's service
// type to a constructor parameter's type. A generic name drops its arguments
// (`ILogger<T>` -> `ILogger`); a predefined type (`int`) yields null.
static string? DiTypeName(TypeSyntax t) => t switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    GenericNameSyntax g => g.Identifier.Text,
    QualifiedNameSyntax q => DiTypeName(q.Right),
    AliasQualifiedNameSyntax aq => DiTypeName(aq.Name),
    // a nullable annotation (`AppDbContext?`) does not change the injected service type —
    // unwrap it so a nullable ctor param is still a real dep (CodeRabbit review on #63).
    NullableTypeSyntax n => DiTypeName(n.ElementType),
    _ => null,
};

// If `t` is a `WeakReference<X>` (or `System.WeakReference<X>`, or a nullable
// `WeakReference<X>?`), the simple name of its single type argument X; else null.
// Syntactic, single-arg — matches how a singleton holds a captive dependency weakly.
// (`System.WeakReference` non-generic has no element type and is not a DI dep.)
static string? WeakRefInner(TypeSyntax t)
{
    if (t is NullableTypeSyntax nt)   // `WeakReference<X>?` -> unwrap the nullable annotation
        t = nt.ElementType;
    var g = t switch
    {
        GenericNameSyntax gen => gen,
        QualifiedNameSyntax { Right: GenericNameSyntax gen } => gen,
        AliasQualifiedNameSyntax { Name: GenericNameSyntax gen } => gen,
        _ => null,
    };
    // the inner `X` (or a nullable `X?`) is resolved by DiTypeName, which unwraps `?`.
    return g is { Identifier.Text: "WeakReference" }
           && g.TypeArgumentList.Arguments.Count == 1
        ? DiTypeName(g.TypeArgumentList.Arguments[0]) : null;
}

// The field a ctor assignment targets — `_field = ...` or `this._field = ...` — so a
// `_provider = provider;` copy of an injected IServiceProvider is tracked as a provider
// reference. A more complex LHS (indexer, nested member) is not a simple field -> null.
static string? AssignedFieldName(ExpressionSyntax lhs) => lhs switch
{
    IdentifierNameSyntax id => id.Identifier.Text,
    MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax, Name: IdentifierNameSyntax n }
        => n.Identifier.Text,
    _ => null,
};

// The service types a class resolves BY HAND off an injected IServiceProvider, with the
// 1-based line of each `recv.GetService<T>()` / `recv.GetRequiredService<T>()` call whose
// receiver is one of the injected-provider names (DI004). The line is the resolution call
// site — DI004's actual consumer. Single type argument only (the generic resolve form); a
// `scope.ServiceProvider.Get...` receiver is excluded by ReceiverIsProvider, so the correct
// scope-resolution pattern is never recorded.
static IEnumerable<(string type, int line)> RootResolvedTypes(
    ClassDeclarationSyntax cls, HashSet<string> providerNames)
{
    foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (inv.Expression is not MemberAccessExpressionSyntax ma
            || ma.Name is not GenericNameSyntax gen
            || gen.TypeArgumentList.Arguments.Count != 1
            || gen.Identifier.Text is not ("GetService" or "GetRequiredService")
            || !ReceiverIsProvider(ma.Expression, providerNames))
            continue;
        if (DiTypeName(gen.TypeArgumentList.Arguments[0]) is { } t)
            yield return (t, inv.GetLocation().GetLineSpan().StartLinePosition.Line + 1);
    }
}

// Is the call receiver one of the injected-provider names — `provider` / `_provider`
// (identifier) or `this._provider` (this-qualified field)? A `scope.ServiceProvider`
// receiver is a member access NOT qualified by `this`, so it returns false: only the
// injected ROOT provider, never a scope's provider, is treated as a root resolution.
// Reused by DI005 to test a `<creator>.CreateScope()` receiver against the scope-creator names.
static bool ReceiverIsProvider(ExpressionSyntax recv, HashSet<string> providerNames) => recv switch
{
    IdentifierNameSyntax id => providerNames.Contains(id.Identifier.Text),
    MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax, Name: IdentifierNameSyntax n }
        => providerNames.Contains(n.Identifier.Text),
    _ => false,
};

// Is `inv` a `<creator>.CreateScope()` call whose receiver is one of the scope-creator names (an
// injected IServiceScopeFactory or provider)? The `IServiceScopeFactory.CreateScope()` /
// `IServiceProvider.CreateScope()` that opens a child scope (DI005).
static bool IsCreateScopeOff(InvocationExpressionSyntax inv, HashSet<string> creators) =>
    inv.Expression is MemberAccessExpressionSyntax { Name.Identifier.Text: "CreateScope" } m
    && ReceiverIsProvider(m.Expression, creators);

// The type `T` of a `<scope>.ServiceProvider.GetService<T>()` / `GetRequiredService<T>()`
// expression, where `<scope>` is a scope-local declared from `CreateScope()` OR an inline
// `<creator>.CreateScope()` chain — else null (DI005). Single type argument only (the generic
// resolve form). The `.ServiceProvider` receiver is what distinguishes a scope resolution from a
// root one (DI004, off the injected provider directly).
static string? ScopeResolvedType(
    ExpressionSyntax expr, HashSet<string> scopeLocals, HashSet<string> creators)
{
    if (expr is not InvocationExpressionSyntax inv
        || inv.Expression is not MemberAccessExpressionSyntax ma
        || ma.Name is not GenericNameSyntax gen
        || gen.TypeArgumentList.Arguments.Count != 1
        || gen.Identifier.Text is not ("GetService" or "GetRequiredService")
        || ma.Expression is not MemberAccessExpressionSyntax { Name.Identifier.Text: "ServiceProvider" } sp)
        return null;
    var fromScope = sp.Expression switch
    {
        IdentifierNameSyntax id => scopeLocals.Contains(id.Identifier.Text),
        InvocationExpressionSyntax cs => IsCreateScopeOff(cs, creators),   // inline CreateScope().ServiceProvider
        _ => false,
    };
    return fromScope ? DiTypeName(gen.TypeArgumentList.Arguments[0]) : null;
}

// The service types a class resolves off a scope it CREATES and CACHES into a FIELD, with the
// 1-based line of the field store (DI005). Recognises a field assignment
// `_f = scope.ServiceProvider.Get(Required)Service<T>()` where `scope` is a local declared from
// `<creator>.CreateScope()`, and the inline `_f = <creator>.CreateScope().ServiceProvider.
// Get(Required)Service<T>()`. The LHS must be a real field (AssignedFieldName + classFieldNames) —
// a scope-resolved value used within the scope and discarded (the CORRECT pattern) is a local, not
// a field store, so it is never recorded.
static IEnumerable<(string type, string file, int line)> ScopeCachedTypes(
    ClassDeclarationSyntax cls, HashSet<string> creators, HashSet<string> classFieldNames)
{
    var scopeLocals = new HashSet<string>(StringComparer.Ordinal);
    foreach (var v in cls.DescendantNodes().OfType<VariableDeclaratorSyntax>())
        if (v.Initializer?.Value is InvocationExpressionSyntax cs && IsCreateScopeOff(cs, creators))
            scopeLocals.Add(v.Identifier.Text);
    foreach (var asg in cls.DescendantNodes().OfType<AssignmentExpressionSyntax>())
        if (AssignedFieldName(asg.Left) is { } fld && classFieldNames.Contains(fld)
            && ScopeResolvedType(asg.Right, scopeLocals, creators) is { } t)
        {
            // the store site's file comes from the assignment's OWN location, not the per-class
            // `ctorFile` — correct even if the cache write lives in another partial-class file
            // (CodeRabbit). DI005 anchors at this store, so the file must be the store's file.
            var span = asg.GetLocation().GetLineSpan();
            yield return (t, span.Path, span.StartLinePosition.Line + 1);
        }
}

// DI's default IServiceProvider resolves through PUBLIC constructors only — an
// explicit ctor with no access modifier defaults to private and DI never uses it.
static bool IsPublicCtor(SyntaxTokenList modifiers)
{
    foreach (var m in modifiers)
        if (m.IsKind(SyntaxKind.PublicKeyword))
            return true;
    return false;
}

var components = new List<object>();
// P-016 B0b/B2: per-method flow bodies (only when --flow-locals).
var flowFunctions = new List<object>();

// Parse every input into a syntax tree first (keeping the file path we report
// it under), then build ONE compilation over all of them so the SemanticModel
// resolves cross-file and cross-project symbols (P-014 Tier A).
var parsed = new List<(string file, SyntaxTree tree)>();
// P-004 WPF MVVM: source-file paths (`Foo.xaml.cs`) whose sibling `Foo.xaml` constructs
// its own DataContext (`<Foo.DataContext><VM/></...>`) — the view OWNS that VM. The
// extractor only parses `.cs`, so XAML-declared ownership is invisible from the C#
// alone; we read the sibling `.xaml` here and the subscription detector then treats a
// field assigned from `this.DataContext` as self-owned. Keyed by the tree's FilePath.
var viewsOwningDataContext = new HashSet<string>(StringComparer.Ordinal);
foreach (var path in inputs)
{
    // Defensive: an explicit input that is not a readable file (a directory
    // passed by mistake, a deleted path) is skipped with a note, never an
    // unhandled exception that aborts the whole scan.
    if (!File.Exists(path))
    {
        Console.Error.WriteLine($"ownsharp-extract: skipping (not a file): {path}");
        continue;
    }
    string text;
    try
    {
        text = File.ReadAllText(path);
    }
    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
    {
        // A locked/unreadable file is skipped with a note, not an abort.
        Console.Error.WriteLine($"ownsharp-extract: skipping unreadable file: {path} ({ex.Message})");
        continue;
    }
    parsed.Add((Rel(path), CSharpSyntaxTree.ParseText(text, path: path)));
    if (path.EndsWith(".xaml.cs", StringComparison.OrdinalIgnoreCase))
    {
        var xamlPath = path[..^3];   // strip ".cs" -> "....xaml"
        try
        {
            if (File.Exists(xamlPath) && XamlDeclaresOwnedDataContext(File.ReadAllText(xamlPath)))
                viewsOwningDataContext.Add(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // An unreadable sibling `.xaml` just means "ownership unknown" — no exemption.
        }
    }
}

// Project-local compilation (P-014 Tier A): the framework reference set is this
// runtime's trusted platform assemblies — zero-config, on disk wherever `dotnet`
// runs; no third-party / MSBuild references. Enough to resolve primitives,
// in-project types and BCL events; external types (WPF/DevExpress) stay
// unresolved and are surfaced as OWN050 "unchecked", never guessed as leaks.
// Error-tolerant: compile diagnostics are irrelevant — we only read symbols.
var tpa = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "")
    .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
    .Where(p => p.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
    .ToList();
var refNames = new HashSet<string>(tpa.Select(Path.GetFileName), StringComparer.OrdinalIgnoreCase);
var references = tpa.Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
// P-004 WPF profile: widen the reference set with assemblies named by the
// OWN_EXTRA_REF_DIRS env var (colon-separated dirs) — e.g. the WindowsDesktop ref
// pack — so framework events/timers (Button.Click, DispatcherTimer.Tick) resolve to
// real symbols instead of surfacing as OWN050 on a WPF app. Additive and best-
// effort: unset => unchanged behaviour; a DLL whose simple name a TPA reference
// already provides is skipped so System.* is not double-referenced from two packs.
foreach (var dir in (Environment.GetEnvironmentVariable("OWN_EXTRA_REF_DIRS") ?? "")
             .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
{
    if (!Directory.Exists(dir)) continue;
    var added = 0;
    foreach (var dll in Directory.EnumerateFiles(dir, "*.dll"))
        if (refNames.Add(Path.GetFileName(dll)))
        { references.Add(MetadataReference.CreateFromFile(dll)); added++; }
    Console.Error.WriteLine($"extractor: +{added} extra references from {dir}");
}
// P-014 Tier B: --ref-dir <dir> widens the reference set RECURSIVELY (a project's built `bin/`,
// a restored package's `lib/`), so events on third-party types resolve to real symbols. First
// simple-name wins (a TPA/framework or OWN_EXTRA_REF_DIRS reference already loaded is skipped),
// so a `bin/` carrying multiple target-framework copies of the same assembly references one. A
// reference that fails to load (a native DLL, a corrupt file) is skipped, not fatal — we only read
// metadata, and a missing reference degrades to OWN050, never a crash.
foreach (var dir in refDirs)
{
    if (!Directory.Exists(dir)) { Console.Error.WriteLine($"extractor: --ref-dir not found: {dir}"); continue; }
    var added = 0;
    // Ordinal sort makes "first simple-name wins" deterministic across platforms/filesystems
    // (EnumerateFiles order is unspecified), so a `bin/` with multiple TFM copies picks the same one.
    foreach (var dll in Directory.EnumerateFiles(dir, "*.dll", SearchOption.AllDirectories)
                                 .OrderBy(p => p, StringComparer.Ordinal))
    {
        var name = Path.GetFileName(dll);
        if (!refNames.Contains(name))
            // Record the name only on a successful load, so a failed DLL here doesn't burn the
            // name and silently skip a loadable same-named assembly elsewhere in the tree.
            try { references.Add(MetadataReference.CreateFromFile(dll)); refNames.Add(name); added++; }
            catch (Exception ex) { Console.Error.WriteLine($"extractor: skipped {name}: {ex.GetType().Name}"); }
    }
    Console.Error.WriteLine($"extractor: +{added} references from --ref-dir {dir} (recursive)");
}
var compilation = CSharpCompilation.Create(
    "own", parsed.Select(p => p.tree), references,
    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

// --flow-locals coverage counters (--stats). A method "with a local" here is one
// that has a non-escaping `new` IDisposable worth tracking; of those we either
// flow-analyse it or honestly skip it (an unmodelled for/do/try/switch/async made
// LowerFlowBody bail). methods_with_local == analysed + skipped.
int statMethodsWithLocal = 0, statMethodsAnalysed = 0, statMethodsSkipped = 0;

foreach (var (file, tree) in parsed)
{
    var model = compilation.GetSemanticModel(tree);
    var root = tree.GetRoot();

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

        // Fields/locals this class constructs (`new`) — it OWNS them, so their
        // lifetime cannot exceed the class's. Used by the self-owned-subscription
        // exemption (P-004) just below and by the disposable detector (WPF003).
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

        // P-004 (extended) self-owned set for the SUBSCRIPTION exemption ONLY. A
        // field can be owned without a direct `_f = new ...`; fold in two more
        // shapes the WPF mining run surfaced. Kept OUT of `constructed` so the
        // WPF003 disposal detector keeps demanding disposal of `new`'d fields only
        // (you don't dispose a borrowed-by-ref value or a template part). Both paths
        // require an actual FIELD (a `ref`/`out` local or parameter is not owned):
        //   * ref/out construction by one of THIS class's OWN helpers —
        //     `BuildCorner(ref _thumb, ...)`: the class populates the field itself,
        //     so it owns it. A `ref`/`out` to an EXTERNAL method
        //     (`container.TryResolve(out _bus)`, `Interlocked.Exchange(ref _bus, ..)`)
        //     only proves the callee CAN assign it — it may be an injected, longer-
        //     lived publisher — so it is NOT exempted, else a real leak is suppressed.
        //   * template parts — `_part = GetTemplateChild("PART_x") as T`: a control
        //     owns the parts of its own template (collectable part<->control cycle).
        var clsSymbol = model.GetDeclaredSymbol(cls);
        var selfOwned = new HashSet<string>(constructed);
        foreach (var arg in cls.DescendantNodes().OfType<ArgumentSyntax>())
            if ((arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword)
                 || arg.RefKindKeyword.IsKind(SyntaxKind.OutKeyword))
                && model.GetSymbolInfo(arg.Expression).Symbol is IFieldSymbol rf
                && arg.Parent?.Parent is InvocationExpressionSyntax callInv
                && model.GetSymbolInfo(callInv).Symbol is IMethodSymbol callee
                && clsSymbol is not null
                && SymbolEqualityComparer.Default.Equals(callee.ContainingType, clsSymbol))
                selfOwned.Add(rf.Name);
        foreach (var a in assigns)
            if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                && model.GetSymbolInfo(a.Left).Symbol is IFieldSymbol tf
                && IsTemplatePartFetch(a.Right))
                selfOwned.Add(tf.Name);
        //   * WPF MVVM view-model — `_vm = DataContext as VM`: when THIS view's own
        //     XAML constructs its DataContext (recorded in viewsOwningDataContext from
        //     the sibling `.xaml`), the view owns that VM, so the view<->VM cycle is
        //     collectable and subscribing to its events is not a leak. (Mined from
        //     ScreenToGif's VideoSource: 4 FP subscriptions to its own declared VM.)
        if (viewsOwningDataContext.Contains(tree.FilePath))
            foreach (var a in assigns)
                if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                    && model.GetSymbolInfo(a.Left).Symbol is IFieldSymbol dcf
                    && ReadsDataContext(a.Right))
                    selfOwned.Add(dcf.Name);

        // Is this class the process-lived WPF application object? Used to drop the
        // static-source region escape (OWN014) — `App` cannot be over-promoted.
        var clsIsApp = IsProcessLivedApplication(cls);

        var subs = new List<object>();
        foreach (var a in assigns)
        {
            if (!emitEvents || !a.IsKind(SyntaxKind.AddAssignmentExpression))
                continue;
            // P-014 Tier A: a `+=` is an event subscription only when the LHS binds
            // to an event symbol. `sum += value` (a local/field/property) resolves
            // to a non-event and is skipped — arithmetic, not a leak. When the LHS
            // cannot be resolved (its declaring type is an unreferenced external
            // assembly) we do NOT guess a leak: a handler-shaped RHS becomes an
            // OWN050 "unchecked" marker that the core surfaces as an advisory note.
            var leftSymbol = model.GetSymbolInfo(a.Left).Symbol;
            if (leftSymbol is IEventSymbol ev)
            {
                var isTimer = IsTimerEvent(a.Left);
                // P-004 lifetime exemptions — skip, not a leak (timers excluded: a
                // running timer is dispatcher-rooted regardless):
                //  - self-owned source (`this`, or a field/local the class
                //    constructs) — the source<->this cycle is GC-collectable;
                //  - static handler — a static method has a null delegate target,
                //    so no instance is retained and nothing can leak.
                //  - a process-host AppDomain event (ProcessExit/DomainUnload/Unhandled-
                //    Exception/FirstChanceException) whose handler retains NO instance — the
                //    handler is meant to live for the whole process, so the "escape" is the
                //    intent, not a leak (mined: Npgsql PoolManager's `AppDomain.CurrentDomain.
                //    ProcessExit += (_,_) => ClearAll()` shutdown hook). A handler that captures
                //    instance state still pins it to the process, so it stays OWN014 (Codex).
                if (!isTimer && (IsSelfOwnedSource(a.Left, ev, model, selfOwned)
                                 || IsStaticHandler(a.Right, model)
                                 || (IsProcessLifetimeAppDomainEvent(ev)
                                     && HandlerRetainsNoInstance(a.Right, model))))
                    continue;
                // P-004 tiering: a local-variable source is method-bounded — it
                // cannot outlive `this`, so it is not a heap leak; drop it (the same
                // spirit as the self-owned drop above). "static"/"injected" ride
                // along as a `source` hint so the core can grade the severity.
                var source = isTimer ? "static"
                                     : SubscriptionSourceKind(a.Left, ev, model);
                if (source == "local")
                    continue;
                // Process-lived subscriber (the WPF `App` singleton): a static-source
                // subscription promotes nothing — `App` already lives for the whole
                // process — so the region escape (OWN014) is a false positive. Scoped
                // to NON-timers: a timer is forced to source "static" above, but a
                // never-stopped timer in `App` is still a real leak (CodeRabbit).
                if (!isTimer && source == "static" && clsIsApp)
                    continue;
                var released = unsub.Contains($"{a.Left}|{a.Right}")
                    || (isTimer && Receiver(a.Left) is { } recv && stopped.Contains(recv));
                subs.Add(new
                {
                    @event = a.Left.ToString(),
                    handler = a.Right.ToString(),
                    line = LineOf(a.Left),
                    released,
                    // A static-source subscription (a process-lived event, or a
                    // static-field/property receiver) is a region escape, not a
                    // token leak: route it through the lifetime engine as a
                    // `capture` -> OWN014 (the WPF "escape to App"). The bridge
                    // skips a released capture (a `-=` on close), so a correctly
                    // unsubscribed static subscription stays silent. An injected/
                    // unknown source stays a token `subscription` (OWN001,
                    // severity-tiered); timers are their own kind. (P-004 WPF005;
                    // see ownlang/ownir.py `capture`.)
                    resource = isTimer ? "timer"
                             : source == "static" ? "capture"
                             : "subscription",
                    source,
                    lambda = !isTimer && IsLambdaHandler(a.Right),
                });
            }
            else if (leftSymbol is null && IsHandler(a.Right))
            {
                subs.Add(new
                {
                    @event = a.Left.ToString(),
                    handler = a.Right.ToString(),
                    line = LineOf(a.Left),
                    resource = "unresolved-subscription",
                });
            }
        }

        // WPF003: an IDisposable field the class constructs (`new`) but never
        // disposes. Owned (not injected) = in `constructed` (computed above);
        // released = a `<field>.Dispose()` call somewhere in the class.
        var disposed = new HashSet<string>();
        // A local that ALIASES a field of this class — `var cts = _cts;` / `var cts = this._cts;` —
        // and is then disposed THROUGH the alias (`cts.Dispose()`) releases the field's object: the
        // alias and the field name the same instance. Map each such alias LOCAL SYMBOL -> its field
        // so the disposal scan below credits the FIELD. Mined: Npgsql's NpgsqlDataSource disposes its
        // CancellationTokenSource via `var cts = _cts; cts.Dispose();`. Sound by construction:
        //  - the initializer is a `this`/bare field reference (never `other._f`) that BINDS to a real
        //    field symbol (not a same-named local);
        //  - aliases are keyed by the LOCAL SYMBOL, not its name, so a same-named local in another
        //    method (or a second alias reusing the name) is a DISTINCT entry, never conflated (Codex);
        //  - an alias REASSIGNED anywhere — by `=`, or rebound through a `ref`/`out` argument — is
        //    excluded: a rebound local no longer tracks the field, so we decline to credit it (Codex).
        var reassignedAliases = new HashSet<ISymbol>(SymbolEqualityComparer.Default);
        foreach (var asg in assigns)
            if (model.GetSymbolInfo(asg.Left).Symbol is ILocalSymbol rls)
                reassignedAliases.Add(rls);
        foreach (var arg in cls.DescendantNodes().OfType<ArgumentSyntax>())
            if ((arg.RefKindKeyword.IsKind(SyntaxKind.RefKeyword) || arg.RefKindKeyword.IsKind(SyntaxKind.OutKeyword))
                && model.GetSymbolInfo(arg.Expression).Symbol is ILocalSymbol als)
                reassignedAliases.Add(als);
        var aliasToField = new Dictionary<ISymbol, string>(SymbolEqualityComparer.Default);
        foreach (var decl in cls.DescendantNodes().OfType<VariableDeclaratorSyntax>())
            if (decl.Initializer?.Value is { } init
                && ThisFieldName(init) is { } af
                && model.GetSymbolInfo(init).Symbol is IFieldSymbol
                && model.GetDeclaredSymbol(decl) is ILocalSymbol aliasSym
                && !reassignedAliases.Contains(aliasSym))
                aliasToField[aliasSym] = af;
        // a `.Dispose()`/`.DisposeAsync()`/`.Close()` on a field — directly (`_f.Dispose()` / `this._f.…`)
        // or through an alias local (translated by SYMBOL via aliasToField) — releases that field.
        // `Close()` counts as a release here exactly as it already does for LOCAL disposables (DisposesLocal
        // and the flow detector both accept Dispose/Close/DisposeAsync); a Stream / DbConnection-style field
        // released by Close is not a leak. Mined: Npgsql ReplicationConnection disposes its NpgsqlConnection
        // field via `await _npgsqlConnection.Close(async: true)`. ThisFieldName (not FieldName) scopes the
        // credit to THIS instance's field / a validated alias: `other._f.Close()` on ANOTHER instance of
        // the same class must NOT mark this object's `_f` released (Codex/CodeRabbit) — and a field-symbol
        // ContainingType check would NOT catch that (same class -> same ContainingType), so key on the
        // `this`/bare receiver syntactically.
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text is "Dispose" or "DisposeAsync" or "Close"
                && ThisFieldName(m.Expression) is { } df)
                disposed.Add(model.GetSymbolInfo(m.Expression).Symbol is ILocalSymbol ls
                             && aliasToField.TryGetValue(ls, out var fa) ? fa : df);
        // Also the NULL-CONDITIONAL form `field?.Dispose()` (a ConditionalAccess whose
        // WhenNotNull is the `.Dispose()` invocation, NOT a plain MemberAccess) — the
        // dominant disposal shape the match above misses. Mined as an FP across ImageSharp:
        // `this.memoryStream?.Dispose()` (ZipExrCompressor/DeflateCompressor/IccDataWriter)
        // and the BufferedStreams benchmark's `[GlobalCleanup]` `field?.Dispose()` calls.
        // (The same alias-by-symbol translation applies — `cts?.Dispose()` on an aliasing local.)
        foreach (var cae in cls.DescendantNodes().OfType<ConditionalAccessExpressionSyntax>())
            if (ThisFieldName(cae.Expression) is { } cdf   // this-instance field / alias only (not `other._f?.Close()`)
                && cae.WhenNotNull is InvocationExpressionSyntax { Expression: MemberBindingExpressionSyntax mb }
                && mb.Name.Identifier.Text is "Dispose" or "DisposeAsync" or "Close")
                disposed.Add(model.GetSymbolInfo(cae.Expression).Symbol is ILocalSymbol lc
                             && aliasToField.TryGetValue(lc, out var fc) ? fc : cdf);

        // P-004 EventSource counter exemption: inside an EventSource, a DiagnosticCounter field
        // constructed with `this` is registered to (and lifetime-owned by) the source — a
        // process-lived diagnostic the source never field-disposes (see IsEventSourceOwnedCounter).
        // Collect those field names so the loop below does not report them as undisposed leaks.
        // A counter is always built in a method body (OnEventCommand) — `this` is unavailable in
        // a field initializer — so only the assignment shape (matching `constructed`) can match.
        var eventSourceCounters = new HashSet<string>();
        if (DerivesFromEventSource(clsSymbol))
            foreach (var a in assigns)
                if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                    && a.Right is BaseObjectCreationExpressionSyntax aoce
                    && IsEventSourceOwnedCounter(aoce, model)
                    && ThisFieldName(a.Left) is { } cfn)   // THIS instance's field only — `other._c` must not exempt our field (CodeRabbit)
                    eventSourceCounters.Add(cfn);

        // P-004 SemaphoreSlim field exemption (mined: Npgsql NpgsqlDataSource._setupMappingsSemaphore).
        // SemaphoreSlim.Dispose() only frees a LAZILY-allocated wait handle — allocated solely when
        // `.AvailableWaitHandle` is read — so a SemaphoreSlim field used purely for Wait/WaitAsync/Release
        // leaks nothing and is dispose-optional. GATE: if `.AvailableWaitHandle` IS read on the field,
        // that handle exists and Dispose must release it, so the field STAYS tracked (Codex). Collect the
        // field names whose AvailableWaitHandle is read (this/bare receiver) so the loop below keeps them.
        // Scoped to FIELDS only — the shared IsDisposeOptional (and the flow-locals detector / the
        // deliberate method-bounded `semLeak` control) is intentionally left untouched (CodeRabbit).
        var waitHandleSemaphores = new HashSet<string>(StringComparer.Ordinal);
        foreach (var ma in cls.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
            if (ma.Name.Identifier.Text == "AvailableWaitHandle")
            {
                // credit the FIELD whose AvailableWaitHandle is read, by SYMBOL: a this/bare access bound
                // to a real field symbol (so `other._f` and a shadowing local/param are NOT conflated —
                // CodeRabbit), OR a field-ALIAS local (`var s = _sem; s.AvailableWaitHandle` -> `_sem` —
                // Codex). Anything else (an unrelated local, another instance's field) is ignored.
                var recv = model.GetSymbolInfo(ma.Expression).Symbol;
                if (recv is IFieldSymbol && ThisFieldName(ma.Expression) is { } whf)
                    waitHandleSemaphores.Add(whf);
                else if (recv is ILocalSymbol ls && aliasToField.TryGetValue(ls, out var fa))
                    waitHandleSemaphores.Add(fa);
            }

        foreach (var fd in cls.Members.OfType<FieldDeclarationSyntax>())
        {
            // a `static` IDisposable field is a process-lifetime singleton (a shared
            // HttpClient, a sentinel like Dapper's DisposedReader.Instance) — it is
            // intentionally never disposed, so it is not an owned leak.
            if (fd.Modifiers.Any(m => m.IsKind(SyntaxKind.StaticKeyword)))
                continue;
            var tname = fd.Declaration.Type.ToString();
            // Resolve-aware: when the field type binds to a real symbol, demand an actual
            // IDisposable; only an UNRESOLVED type falls back to the name heuristic. (Stops
            // the #1 ImageSharp FP class: undisposed `Vp8BitWriter`/`JpegBitReader` fields
            // whose types merely end in Writer/Reader but are not IDisposable.)
            if (!IsOwnedDisposableType(fd.Declaration.Type, model))
                continue;
            foreach (var v in fd.Declaration.Variables)
            {
                if (!constructed.Contains(v.Identifier.Text))
                    continue;
                // an EventSource's own DiagnosticCounter (a field DECLARED as a DiagnosticCounter
                // AND registered to `this`) is process-lived and never field-disposed -> not an
                // owned leak (mined: Npgsql NpgsqlEventSource). The DECLARED-type guard keeps the
                // skip bound to genuine counter fields: a field declared as a plain IDisposable
                // that is merely assigned a counter once still leaks its OTHER resource (e.g. an
                // initial `new MemoryStream()`), so it must NOT be suppressed by name alone (Codex).
                if (eventSourceCounters.Contains(v.Identifier.Text)
                    && DerivesFromDiagnosticCounter(model.GetTypeInfo(fd.Declaration.Type).Type))
                    continue;
                // a SemaphoreSlim field whose `.AvailableWaitHandle` is never read leaks nothing —
                // Dispose() only frees that lazy handle — so it is dispose-optional and silent; if the
                // handle IS read (in waitHandleSemaphores) it stays tracked. FIELD-scoped (Npgsql).
                if (!waitHandleSemaphores.Contains(v.Identifier.Text)
                    && model.GetTypeInfo(fd.Declaration.Type).Type is { Name: "SemaphoreSlim" } st
                    && st.ContainingNamespace?.ToString() == "System.Threading")
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

        // P-007 / WPF: a field-mediated cross-method USE-AFTER-DISPOSE. An IDisposable
        // field disposed in this class's Dispose()/DisposeAsync() is then DIRECTLY read
        // (`_f.Member`) in an event-handler method — a callback an external event source
        // can still invoke AFTER the object is disposed (the very reason WPF handler
        // leaks matter). With no `if (_disposed) return;` guard the handler touches a
        // field already disposed: a use-after-dispose. We lower it to a synthetic
        // acquire/release/use flow so the existing OwnIR bridge raises OWN002 at the
        // field — no new diagnostic, no second checker (the synthetic-flow trick the
        // MemoryPool slices use). Precise by construction to stay low-FP: fires only when
        //   (a) the field is disposed in the dispose LIFECYCLE (not an ad-hoc `_f.Dispose()`),
        //   (b) the touching method is a LIVE subscription target — RHS of a `+=` / arg of
        //       a `.Subscribe(...)` — whose subscription is NOT torn down (`-= handler`
        //       means the callback cannot fire post-dispose, so it is safe),
        //   (c) the method has no disposed-guard (the canonical fix silences it), and
        //   (d) the use is a DIRECT field member access (an INDIRECT use via a helper is
        //       deliberately not chased — that is the harder frontier, left honest).
        // Gated on --flow-locals like the rest of the synthetic-flow emission.
        if (flowLocals)
        {
            // Owner fields -> declaration line (the synthetic `acquire`): IDisposable fields AND
            // `IMemoryOwner<T>` MemoryPool rentals, whose pooled buffer is released by Dispose() — so a
            // read after that Dispose (including through a Memory VIEW field of the owner) dangles.
            var dispoFieldLine = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var fd in cls.Members.OfType<FieldDeclarationSyntax>())
            {
                if (fd.Modifiers.Any(mm => mm.IsKind(SyntaxKind.StaticKeyword)))
                    continue;
                // IDisposable is matched syntactically (so a project's own unresolved `…Stream` etc.
                // still counts); IMemoryOwner is matched on the resolved SYMBOL so a qualified
                // `System.Buffers.IMemoryOwner<T>` / alias / concrete owner type counts too (CodeRabbit/
                // Codex). The cheap `StartsWith` short-circuits the common unqualified spelling first.
                var ftype = fd.Declaration.Type.ToString();
                if (!IsDisposableType(ftype)
                    && !ftype.StartsWith("IMemoryOwner", StringComparison.Ordinal)
                    && !IsMemoryOwnerType(model.GetTypeInfo(fd.Declaration.Type).Type))
                    continue;
                foreach (var v in fd.Declaration.Variables)
                    dispoFieldLine[v.Identifier.Text] = LineOf(v);
            }
            // field -> line of its `.Dispose()` INSIDE Dispose()/DisposeAsync() (the
            // release event). Restricted to the dispose methods so an ordinary
            // `_f.Dispose()` helper is not misread as object teardown.
            var releasedAt = new Dictionary<string, int>(StringComparer.Ordinal);
            if (dispoFieldLine.Count > 0)
                foreach (var dm in cls.Members.OfType<MethodDeclarationSyntax>())
                {
                    if (dm.Identifier.Text is not ("Dispose" or "DisposeAsync"))
                        continue;
                    foreach (var inv in dm.DescendantNodes().OfType<InvocationExpressionSyntax>())
                        if (inv.Expression is MemberAccessExpressionSyntax dmm
                            && dmm.Name.Identifier.Text is "Dispose" or "DisposeAsync"
                            && ThisFieldName(dmm.Expression) is { } df
                            && dispoFieldLine.ContainsKey(df)
                            && !releasedAt.ContainsKey(df))
                            releasedAt[df] = LineOf(inv);
                }
            if (releasedAt.Count > 0)
            {
                // a Memory/ReadOnlyMemory VIEW field that aliases an owner field — `_view = _owner.Memory`
                // (an IMemoryOwner rental) or `_view = _buf.AsMemory(...)` — mapped to its OWNER, so a read
                // of the VIEW field after the owner's release is a use of the released owner (the pooled-
                // buffer view-in-a-field dangle). `ViewOwner` returns the owner name for a bare-field
                // receiver; only owners actually released (in `releasedAt`) fire, checked at the read.
                var viewFieldOwner = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var a in assigns)
                    if (a.IsKind(SyntaxKind.SimpleAssignmentExpression)
                        && ThisFieldName(a.Left) is { } vf
                        && FieldViewOwner(a.Right, model) is { } vo)
                        viewFieldOwner[vf] = vo;

                // handler method names that are LIVE subscription targets. `+=` subscriptions are
                // keyed by SOURCE|handler so a `-=` removes only the MATCHING one — a handler still
                // `+=`'d to another live source stays live (a name-only set would let one `-=` drop
                // it globally, CodeRabbit/Codex). A `.Subscribe(handler)` token is released by
                // disposing the token (the Rx idiom), not a `-=`, so those handlers are always live.
                var liveEventKeys = new HashSet<string>(StringComparer.Ordinal);
                foreach (var a in assigns)
                    if (IsHandler(a.Right) && FieldName(a.Right) is { } hn)
                    {
                        var key = $"{a.Left}|{hn}";
                        if (a.IsKind(SyntaxKind.AddAssignmentExpression)) liveEventKeys.Add(key);
                        else if (a.IsKind(SyntaxKind.SubtractAssignmentExpression)) liveEventKeys.Remove(key);
                    }
                var subscribed = new HashSet<string>(
                    liveEventKeys.Select(k => k[(k.LastIndexOf('|') + 1)..]), StringComparer.Ordinal);
                foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
                    if (inv.Expression is MemberAccessExpressionSyntax sm
                        && sm.Name.Identifier.Text == "Subscribe")
                        foreach (var arg in inv.ArgumentList.Arguments)
                            if (FieldName(arg.Expression) is { } hn)
                                subscribed.Add(hn);

                // one-hop indirect reach: a private same-class helper (e.g. `Refresh()`) that itself
                // UNGUARDEDLY reads a disposed field. A handler that calls such a helper with no guard
                // before the call touches the disposed field one level down — the field-mediated UAF
                // the WPF `handler-use-after-dispose` pattern hides behind a helper. One hop only; a
                // deeper chain stays an honest miss.
                // keyed by the helper's METHOD SYMBOL (not its name) so an overload — `Refresh()` vs
                // `Refresh(e)` — is matched EXACTLY: a handler calling the safe overload is not
                // attributed the unsafe overload's read (Codex). Same-class methods are in-source, so
                // their symbols resolve even when the field's TYPE does not.
                var helperReads = new Dictionary<ISymbol, (string Field, int Line)>(SymbolEqualityComparer.Default);
                foreach (var hm in cls.Members.OfType<MethodDeclarationSyntax>())
                    if (hm.Body is { } b
                        && hm.Identifier.Text is not ("Dispose" or "DisposeAsync")
                        && IsPrivateInstanceHelper(hm)
                        && model.GetDeclaredSymbol(hm) is { } hsym
                        && FirstUnguardedDisposedRead(b, releasedAt, viewFieldOwner) is { } r)
                        helperReads[hsym] = (r.Field, LineOf(r.Use));

                foreach (var hm in cls.Members.OfType<MethodDeclarationSyntax>())
                {
                    if (hm.Body is not { } hbody)
                        continue;
                    var hname = hm.Identifier.Text;
                    if (hname is "Dispose" or "DisposeAsync")
                        continue;
                    if (!subscribed.Contains(hname))
                        continue;
                    // the FIRST trigger in the handler, in source order: a DIRECT read of a disposed
                    // field of THIS class (`_f` / `this._f`), or a self-call (`Refresh()` /
                    // `this.Refresh()`) to a private helper that unguardedly reads one. `useLine` points
                    // at the actual read; `triggerPos` is where the handler reaches it (the read or the
                    // call) — the position the disposed-guard must precede to make it safe.
                    string? useField = null;
                    int useLine = 0, triggerPos = 0;
                    foreach (var node in hbody.DescendantNodes())
                    {
                        if (node is MemberAccessExpressionSyntax ma
                            && ma.Name.Identifier.Text is not ("Dispose" or "DisposeAsync")
                            && ThisFieldName(ma.Expression) is { } uf
                            && ReleasedOwner(uf, releasedAt, viewFieldOwner) is { } owner)
                        {
                            useField = owner; useLine = LineOf(ma); triggerPos = ma.SpanStart;
                            break;
                        }
                        if (node is InvocationExpressionSyntax call
                            && SelfCallName(call) is not null              // a SELF call (this/bare), not other.X
                            && model.GetSymbolInfo(call).Symbol is { } csym
                            && helperReads.TryGetValue(csym, out var hr))
                        {
                            useField = hr.Field; useLine = hr.Line; triggerPos = call.SpanStart;
                            break;
                        }
                    }
                    // no disposed-field reach, or an opening disposed-guard PRECEDES it -> not a
                    // use-after-dispose. Otherwise emit ONE synthetic acquire/release/use flow -> OWN002.
                    if (useField is null)
                        continue;
                    if (DisposedGuardBefore(hbody, triggerPos))
                        continue;
                    flowFunctions.Add(new
                    {
                        name = $"{cls.Identifier.Text}.{hname}",
                        file,
                        body = new List<object>
                        {
                            new { op = "acquire", var = useField, line = dispoFieldLine[useField] },
                            new { op = "release", var = useField, line = releasedAt[useField] },
                            new { op = "use", var = useField, line = useLine },
                        },
                    });
                }
            }
        }

        // POOL005 (field): a FULL-LENGTH view of a pooled FIELD — `_buf.AsSpan()` / `this._buf.AsMemory()`
        // / `new Span<T>(_buf)` / the `.Length` spelling (`_buf.AsSpan(0, _buf.Length)`) — over a buffer
        // the class `Rent`ed into a FIELD (by assignment `_buf = ArrayPool<T>.Shared.Rent(n)` OR a field
        // initializer `byte[] _buf = ArrayPool<T>.Shared.Rent(n);`). The pooled array is
        // oversized (`Length >= n`), so a member that views the field full-length reads past the logical
        // length `n` into the stale `[n, Length)` tail (a previous renter's bytes). The per-method flow
        // pass only tracks LOCAL rents, so a FIELD-backed rent's over-read is unreached there; emit a
        // synthetic acquire/overspan/release flow per such field so the existing OwnIR bridge raises
        // OWN025 at the view — the synthetic-flow trick the field-UAF / MemoryPool slices use, no new
        // diagnostic. The trailing `release` is synthetic (the real `Return` is class-wide, handled by
        // the POOL001 field pass) and only keeps this one-function flow from reading as a leak. A
        // write/wipe (`Array.Clear(_buf, 0, _buf.Length)`) is not a view, so FullViewFieldOwner returns
        // null on it — only a read-capable VIEW is the over-read. Gated on --flow-locals like the rest of
        // the synthetic-flow emission.
        if (flowLocals)
        {
            // pooled FIELD -> the line it was `Rent`ed, via the shared IsPoolRent (an aliased pool
            // receiver binds; a non-pool `.Rent` does not false-match). Two rent spellings, BOTH scoped
            // to THIS class — a nested type is analysed by its OWN `cls` pass, so its rents/views must
            // neither seed nor fire here (else an inner field could be mis-attributed to the outer class,
            // CodeRabbit):
            //   * an assignment `_buf = ArrayPool<T>.Shared.Rent(n)` (ctor/Capture), target resolved
            //     through `ThisFieldName` — a bare `_buf` / `this._buf`, NEVER `other._buf` — the SAME
            //     this-instance shape FullViewFieldOwner reads the view through, so a rent into another
            //     object's field cannot seed and then false-match this class's own same-named (non-pooled)
            //     field at the view (Codex); the `FirstAncestorOrSelf == cls` guard drops a rent nested
            //     in an inner type; and
            //   * a field-declaration INITIALIZER `byte[] _buf = ArrayPool<T>.Shared.Rent(n);` — a direct
            //     member of `cls`, so inherently this-class-scoped (CodeRabbit).
            // First rent line per field anchors the synthetic acquire.
            var pooledFieldRent = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (IsPoolRent(inv, model)
                    && inv.FirstAncestorOrSelf<BaseTypeDeclarationSyntax>() == cls
                    && inv.Parent is AssignmentExpressionSyntax asg
                    && ThisFieldName(asg.Left) is { } pf
                    && !pooledFieldRent.ContainsKey(pf))
                    pooledFieldRent[pf] = LineOf(inv);
            foreach (var fdecl in cls.Members.OfType<FieldDeclarationSyntax>())
                foreach (var fv in fdecl.Declaration.Variables)
                    if (fv.Initializer?.Value is InvocationExpressionSyntax finv
                        && IsPoolRent(finv, model)
                        && !pooledFieldRent.ContainsKey(fv.Identifier.Text))
                        pooledFieldRent[fv.Identifier.Text] = LineOf(finv);
            if (pooledFieldRent.Count > 0)
                foreach (var member in cls.Members)
                {
                    if (member is BaseTypeDeclarationSyntax)
                        continue;   // a nested type is covered by its OWN class pass, not the outer's
                    // first full-length view of each pooled field in this member (one finding per field
                    // per member — repeated views of the same field do not multiply the diagnostic).
                    var seen = new HashSet<string>(StringComparer.Ordinal);
                    var ops = new List<object>();
                    foreach (var node in member.DescendantNodes().OfType<ExpressionSyntax>())
                        if (FullViewFieldOwner(node, model) is { } fld
                            && pooledFieldRent.TryGetValue(fld, out var rentLine)
                            && seen.Add(fld))
                        {
                            var vline = LineOf(node);
                            ops.Add(new { op = "acquire", var = fld, line = rentLine, kind = "pool" });
                            ops.Add(new { op = "overspan", var = fld, line = vline });
                            ops.Add(new { op = "release", var = fld, line = vline });
                        }
                    if (ops.Count > 0)
                    {
                        var mname = member switch
                        {
                            MethodDeclarationSyntax md => md.Identifier.Text,
                            ConstructorDeclarationSyntax cd => cd.Identifier.Text,
                            PropertyDeclarationSyntax pd => pd.Identifier.Text,
                            _ => "member",
                        };
                        flowFunctions.Add(new { name = $"{cls.Identifier.Text}.{mname}", file, body = ops });
                    }
                }
        }

        // WPF004: a `X.Subscribe(...)` whose IDisposable result is ignored — the
        // call stands as a bare statement (not assigned/returned/added), so the
        // token is dropped and never disposed. Member-access only (`x.Subscribe`),
        // and RESOLVE-AWARE: the call must return an IDisposable (Rx). A resolved void /
        // non-IDisposable `Subscribe` (StackExchange.Redis's `ISubscriber.Subscribe(channel,
        // handler, flags)` is void) has no token to leak; an unresolved return still counts.
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax m
                && m.Name.Identifier.Text == "Subscribe"
                && inv.Parent is ExpressionStatementSyntax
                && SubscribeResultIsDisposable(model.GetTypeInfo(inv).Type))
                subs.Add(new
                {
                    @event = m.ToString(),
                    line = LineOf(inv),
                    released = false,
                    resource = "subscribe",
                    // A self-rooted `this.WhenAnyValue(p => p.SelfProp)` chain is a
                    // GC-collectible self-cycle: the bridge drops `source: "self"`.
                    // Any other (external) source stays a flagged leak (null source).
                    source = IsSelfRootedWhenAny(m.Expression) ? "self" : null,
                });

        // POOL001: an ArrayPool<T> buffer `Rent`ed but never `Return`ed, the Rent
        // recognised via the shared semantic `IsPoolRent` (so an aliased pool receiver
        // binds and a non-pool `.Rent` does not false-match — one definition, the flow
        // pass below is the other consumer). Matched per member so a `buf` returned in
        // one method does not mask a
        // leak of a same-named `buf` in another. Under --flow-locals the
        // path-sensitive flow detector supersedes this for buffers held in LOCALS
        // (and additionally catches double-return / use-after-return) — but it only
        // tracks local declarations, so field/assignment-backed rents still need
        // this syntactic pass; the local-declaration rents are skipped below to
        // avoid double-reporting them (Codex).
        // A FIELD-backed pooled buffer is legitimately rented in one member (the ctor) and
        // Returned in another (Dispose), so for FIELDS the `pool.Return(field)` is searched
        // CLASS-WIDE (a field name is unique to the class, so this cannot cross-mask — unlike
        // same-named LOCALS in different methods, which keep the per-member scoping below).
        // Mined: ImageSharp BufferedReadStream returns this.readBuffer in Dispose(bool). (An
        // INDIRECT release via a lifetime-guard object — SharedArrayPoolBuffer — is left honest:
        // a `new X(field)` is NOT assumed to own/return the buffer, since a non-owning view like
        // `new ReadOnlyMemory<byte>(field)` would otherwise hide a real leak — Codex.)
        var fieldReleased = new HashSet<string>();
        foreach (var inv in cls.DescendantNodes().OfType<InvocationExpressionSyntax>())
            if (inv.Expression is MemberAccessExpressionSyntax rm
                && rm.Name.Identifier.Text == "Return"
                && inv.ArgumentList.Arguments.Count > 0
                && model.GetSymbolInfo(inv.ArgumentList.Arguments[0].Expression).Symbol is IFieldSymbol rfs)
                fieldReleased.Add(rfs.Name);

        foreach (var member in cls.Members)
        {
            var rented = new List<(string Name, int Line, bool IsField)>();
            foreach (var inv in member.DescendantNodes().OfType<InvocationExpressionSyntax>())
                if (IsPoolRent(inv, model))
                {
                    (string? name, bool isField) = inv.Parent switch
                    {
                        // a local-declaration rent is the flow pass's job under
                        // --flow-locals; skip it here so it is not double-reported.
                        EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax vd }
                            => (flowLocals ? null : vd.Identifier.Text, false),
                        // a field/assignment rent (`_buf = pool.Rent(...)`) is NOT a
                        // flow candidate, so this pass keeps it in both modes.
                        AssignmentExpressionSyntax asg => (FieldName(asg.Left), true),
                        _ => ((string?)null, false),
                    };
                    if (name != null)
                        rented.Add((name, LineOf(inv), isField));
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
            foreach (var (name, line, isField) in rented)
                subs.Add(new
                {
                    @event = name,
                    line,
                    // locals stay per-member; a field is also released if returned/transferred
                    // anywhere in the class (cross-member ctor-rent + Dispose-return).
                    released = returned.Contains(name) || (isField && fieldReleased.Contains(name)),
                    resource = "pool",
                });
        }

        // D1 (P-005): a local IDisposable the method `new`s but never disposes,
        // not guarded by `using`, and not handed out (returned / passed as an
        // argument / assigned out) — ownership transfer is ambiguous syntactically
        // (P-005 D5), so those are conservatively excluded. Per member. Suppressed
        // under --flow-locals, where the path-sensitive flow detector supersedes it.
        if (!flowLocals)
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

        // P-016 B0b/B2 (--flow-locals): per-method flow facts for non-escaping local
        // IDisposables. The core checks them path-sensitively (OWN001/002/003).
        // Methods with an unmodelled construct (loop/try/switch) are honestly skipped.
        if (flowLocals)
            foreach (var method in cls.Members.OfType<BaseMethodDeclarationSyntax>())
            {
                if (method.Body is not { } mbody)
                    continue;
                var candidates = new HashSet<string>();
                var poolBuffers = new HashSet<string>();   // candidates that are ArrayPool<T> buffers
                var usingMemoryOwners = new HashSet<string>();   // `using`-declared MemoryPool owners
                var newedDisposables = new HashSet<string>();    // candidates created via `new` (NOT a pool rental / factory)
                foreach (var ld in mbody.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
                {
                    if (ld.UsingKeyword != default)
                    {
                        // A `using` local is auto-disposed (not a leak candidate). But a `using` MemoryPool
                        // owner whose Memory VIEW is returned dangles after the implicit scope-exit dispose —
                        // track it so the flow's using-desugaring catches that escape. Others stay skipped.
                        foreach (var v in ld.Declaration.Variables)
                            if (IsMemoryPoolRent(v.Initializer?.Value, model))
                            {
                                candidates.Add(v.Identifier.Text);
                                usingMemoryOwners.Add(v.Identifier.Text);
                            }
                        continue;
                    }
                    foreach (var v in ld.Declaration.Variables)
                        if (v.Initializer is { Value: ObjectCreationExpressionSyntax
                                                   or ImplicitObjectCreationExpressionSyntax } init
                            && model.GetTypeInfo(init.Value).Type is { } dt
                            && ImplementsIDisposable(dt) && !IsDisposeOptional(dt))
                        {
                            candidates.Add(v.Identifier.Text);
                            newedDisposables.Add(v.Identifier.Text);
                        }
                        else if (IsPoolRent(v.Initializer?.Value, model))   // an ArrayPool<T> buffer
                        {
                            candidates.Add(v.Identifier.Text);
                            poolBuffers.Add(v.Identifier.Text);
                        }
                        else if (IsOwningFactory(v.Initializer?.Value, model))   // File / crypto Create* factory
                            candidates.Add(v.Identifier.Text);
                        else if (IsMemoryPoolRent(v.Initializer?.Value, model))   // MemoryPool<T> IMemoryOwner (Dispose-released, NOT a poolBuffer)
                            candidates.Add(v.Identifier.Text);
                        else if (IsFirstPartyDisposableFactory(v.Initializer?.Value, model, out _))
                            // P-005 D5.2: `var r = FirstPartyFactory()` — a candidate acquire
                            // IFF the core proves the callee returns `fresh` (it emits a `call`
                            // op, not an `acquire`; the core decides). Checked last so `new` /
                            // pool / BCL-factory initializers keep their existing classification.
                            candidates.Add(v.Identifier.Text);
                }
                // `using (IMemoryOwner owner = MemoryPool.Rent(...)) { … }` STATEMENT form: track the owner
                // too, so its returned view dangles after the scope-exit dispose (the desugar mirrors the
                // `using` DECLARATION form handled in the loop above).
                foreach (var us in mbody.DescendantNodes().OfType<UsingStatementSyntax>())
                    if (us.Declaration is { } usd)
                        foreach (var v in usd.Variables)
                            if (IsMemoryPoolRent(v.Initializer?.Value, model))
                            {
                                candidates.Add(v.Identifier.Text);
                                usingMemoryOwners.Add(v.Identifier.Text);
                            }
                if (candidates.Count == 0)
                    continue;
                // A local that escapes (returned / assigned out) is conservatively not
                // tracked — its release may be the caller's job. For an IDisposable,
                // passing it as an argument is an ambiguous ownership transfer too; for
                // a pooled buffer the convention is the RENTER returns it, so arg-passing
                // is a borrow (a use), not an escape — else `pool.Return(buf)` and
                // `Work(buf)` would untrack it and hide the double-return / use-after-return.
                var escapedLocals = new HashSet<string>();
                foreach (var idn in mbody.DescendantNodes().OfType<IdentifierNameSyntax>())
                {
                    var nm = idn.Identifier.Text;
                    if (!candidates.Contains(nm))
                        continue;
                    // A `nameof(x)` operand is a compile-time string, not a real reference: it
                    // neither uses, captures, nor transfers the local. Skip it so it triggers no
                    // escape rule — otherwise `nameof(s)` would look like an argument (the arg
                    // rule below) or, inside a lambda, a closure capture, and wrongly untrack a
                    // still-leaking method-bounded local (Codex review on PR #59).
                    if (idn.Parent is ArgumentSyntax { Parent: ArgumentListSyntax
                            { Parent: InvocationExpressionSyntax ninv } }
                        && ninv.Expression is IdentifierNameSyntax { Identifier.Text: "nameof" })
                        continue;
                    // Captured into a CLOSURE (lambda / anonymous method / local function):
                    // the closure can outlive the method — stored, returned, or run async —
                    // so the local is no longer method-bounded and cannot be disposed at
                    // method scope. Conservatively treat the capture as an escape (don't
                    // flag it), the same way a returned/out-passed local is untracked.
                    // Reduced from a ShareX false positive: a SemaphoreSlim throttler captured
                    // by the async lambdas of a returned `Task.WhenAll(...)` (Helpers.ForEachAsync).
                    var capturedInClosure = false;
                    for (var a = idn.Parent; a is not null && a != mbody; a = a.Parent)
                        if (a is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax)
                        {
                            capturedInClosure = true;
                            break;
                        }
                    if (capturedInClosure)
                    {
                        escapedLocals.Add(nm);
                        continue;
                    }
                    // ... unless it is handed to a CONSUMER (a first-party method that
                    // disposes a by-value IDisposable param) as a bare `Consume(s);`
                    // statement: that is a handoff RELEASED at the call site, not an escape
                    // (else the use-after-handoff would be hidden). Tied to the statement
                    // form the flow pass lowers, so a local is never exempted without a
                    // matching release (a `var n = Consume(s)` initializer is NOT lowered
                    // here, so it stays an escape rather than a false leak).
                    bool consumedArg = idn.Parent is ArgumentSyntax
                        && idn.Parent.Parent is ArgumentListSyntax
                        && idn.Parent.Parent.Parent is InvocationExpressionSyntax cinv
                        && cinv.Parent is ExpressionStatementSyntax
                        && ConsumeReleaseArgs(cinv, model).Contains(nm);
                    // A `using`-declared MemoryPool owner RETURNED bare (`using owner = …; return owner;`)
                    // is NOT a real ownership transfer: the implicit scope-exit dispose runs as the method
                    // returns, so the caller receives an already-disposed owner. Keep it TRACKED (do not
                    // escape it) so the using-desugar threads the release before the return and the inserted
                    // use of the returned owner trips OWN002 — the bare-owner twin of the returned-view
                    // dangle. A NON-using returned owner stays a genuine transfer (escaped → untracked →
                    // silent), so this never fires on `var o = Rent(); return o;`.
                    if (idn.Parent is ReturnStatementSyntax rsp)
                    {
                        // P-005 D5.2: a `new`'d IDisposable returned BARE outside any `try` is a
                        // fresh-returning FACTORY — keep it tracked so the flow body emits
                        // `acquire …; return <var>`. The core then classifies the method
                        // `returnsOwned: fresh` (and the `return <var>` discharges it, so the
                        // factory itself stays silent), letting a caller that drops the result
                        // leak. A return INSIDE a try threads `finally` edges the fresh path does
                        // not model yet, so keep the old transfer (escape) there; a `using` owner
                        // also stays tracked (its scope-exit dispose dangles the returned value).
                        var freshFactory = newedDisposables.Contains(nm)
                            && !rsp.Ancestors().TakeWhile(a => a != mbody)
                                   .OfType<TryStatementSyntax>().Any();
                        if (!usingMemoryOwners.Contains(nm) && !freshFactory)
                            escapedLocals.Add(nm);
                    }
                    // A pooled buffer handed as an argument is normally a BORROW (the renter Returns it),
                    // NOT an escape — so `pool.Return(buf); Work(buf)` still trips use-after-return. But a
                    // pooled buffer passed to a CONSTRUCTOR whose result ESCAPES this method (`return new
                    // Wrapper(buf)` / `_field = new Wrapper(buf)`) transfers ownership to that object, which
                    // becomes responsible for Return — so the buffer is NOT leaked here. Treat that as an
                    // escape (mined FP on Pipelines.Sockets.Unofficial: ArrayPoolBufferWriter.CreateNewSegment
                    // returns `new ArrayPoolRefCountedSegment(pool, array, prev)`).
                    else if ((idn.Parent is AssignmentExpressionSyntax asg && asg.Right == idn)
                        || (idn.Parent is ArgumentSyntax && !poolBuffers.Contains(nm) && !consumedArg
                            // P-005 D5.4: a disposable passed to an ADOPTING ctor arg of a
                            // method-bounded wrapper is not an escape — its obligation is
                            // adopted by the wrapper (modelled as an alias_join) and stays
                            // tracked. Gated to a non-using, non-escaping local wrapper so we
                            // never keep an arg tracked with nothing to discharge it (FP).
                            && !IsAdoptedArgOfBoundedWrapper(idn, model, candidates, mbody))
                        // An IMemoryOwner's `.Memory` view handed off as an ARGUMENT escapes the
                        // OWNER: the Memory keeps the owner alive (it IS the backing), so a consumer
                        // that stores it — `MemoryGroup.Wrap(owner.Memory)` -> the returned Image —
                        // takes over the lifetime; the owner is not leaked here. Scoped to
                        // IMemoryOwner.`Memory` (not any `local.Member`, so a FileStream whose
                        // `.Length` is read still leaks) and to `new`'d owners ONLY: a pool rental —
                        // ArrayPool or MemoryPool, `var` or `using` — keeps its dangling-borrow / use-
                        // after-dispose (OWN002/OWN003) tracking through `.Memory` handoffs, since the
                        // RENTER owns the Return/Dispose (Codex/CodeRabbit; benchmark memorypool-double-
                        // dispose). Mined FP on ImageSharp Image.WrapMemory; CodeQL agrees — no leak.
                        || (newedDisposables.Contains(nm)
                            && idn.Parent is MemberAccessExpressionSyntax { Name.Identifier.Text: "Memory" } projMem
                            && projMem.Expression == idn
                            && projMem.Parent is ArgumentSyntax
                            && IsMemoryOwnerType(model.GetTypeInfo(idn).Type))
                        || (poolBuffers.Contains(nm) && PassedToEscapingCtor(idn, model)))
                        escapedLocals.Add(nm);
                }
                var tracked = new HashSet<string>(candidates);
                tracked.ExceptWith(escapedLocals);
                if (tracked.Count == 0)
                    continue;
                statMethodsWithLocal++;
                var fbody = LowerFlowBody(mbody, tracked, model);
                if (fbody is null || fbody.Count == 0)
                {
                    statMethodsSkipped++;   // unmodelled construct -> honestly skipped
                    continue;
                }
                statMethodsAnalysed++;
                flowFunctions.Add(new
                {
                    name = FlowFunctionName(method, cls.Identifier.Text, model),
                    file,
                    body = fbody,
                });
            }

        if (subs.Count > 0)
            components.Add(new { name = cls.Identifier.Text, file, subscriptions = subs });
    }
}

// ownir_version stamps the fact-schema vocabulary; the Python core rejects a
// mismatch loudly (ownlang/ownir.py OWNIR_VERSION) rather than mis-reading facts.
// `stats` is additive coverage metadata — the core's load() ignores unknown keys.
var facts = new
{
    ownir_version = 0,
    module = "Extracted",
    components,
    // P-006: the DI registration + ctor graph (empty when the scan has no
    // Add{Singleton,Scoped,Transient} calls). ownlang/di.py turns it into DI001.
    services = ExtractServices(parsed),
    functions = flowFunctions,
    stats = new
    {
        methods_with_local = statMethodsWithLocal,
        methods_flow_analysed = statMethodsAnalysed,
        methods_skipped_unmodelled = statMethodsSkipped,
    },
};
var json = JsonSerializer.Serialize(facts, new JsonSerializerOptions { WriteIndented = true });

if (reportStats)
    Console.Error.WriteLine(
        $"coverage: {statMethodsAnalysed}/{statMethodsWithLocal} methods with a "
        + $"disposable local flow-analysed; {statMethodsSkipped} skipped (unmodelled construct)");

if (outPath is null) Console.WriteLine(json);
else File.WriteAllText(outPath, json);
return 0;

// Opt-in recall knob for the flow pass, read deep in InjectThrowEdge (a static field rather than
// a bool threaded through the whole LowerFlow* recursion). Set once from --body-throw-edges; see
// that flag's note above. Default false keeps the shipped low-FP posture; the oracle flips it on
// to measure CodeQL-parity dispose-not-called-on-throw recall on the no-try slice.
partial class Program
{
    internal static bool BodyThrowEdges;
}
