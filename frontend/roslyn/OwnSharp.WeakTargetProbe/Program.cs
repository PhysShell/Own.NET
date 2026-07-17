// S2 Step 11 — OwnSharp.WeakTargetProbe. See the .csproj for the two-mode contract.
using System.ComponentModel;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length >= 1 && args[0] == "bind") return BindMode.Run(args);
            if (args.Length >= 1 && args[0] == "probe") return ProbeMode.Run(args);
            Console.Error.WriteLine("weak-target-probe: usage: (bind|probe) ...");
            return 2;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"weak-target-probe: internal error ({e.GetType().Name}: {e.Message})");
            return 2;
        }
    }

    // --- deterministic canonical JSON (sorted keys, compact, trailing LF) for a restricted
    // value domain (bool / non-negative long / printable-ASCII string / array / object) so the
    // bytes byte-match Python json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False).
    internal static void WriteCanonical(string path, object value)
    {
        var sb = new StringBuilder();
        Emit(sb, value);
        sb.Append('\n');
        File.WriteAllBytes(path, Encoding.UTF8.GetBytes(sb.ToString()));
    }

    private static void Emit(StringBuilder sb, object? v)
    {
        switch (v)
        {
            case null: sb.Append("null"); break;
            case bool b: sb.Append(b ? "true" : "false"); break;
            case int i: sb.Append(i.ToString(System.Globalization.CultureInfo.InvariantCulture)); break;
            case long l: sb.Append(l.ToString(System.Globalization.CultureInfo.InvariantCulture)); break;
            case string s: EmitString(sb, s); break;
            case IReadOnlyList<object> arr:
                sb.Append('[');
                for (var k = 0; k < arr.Count; k++) { if (k > 0) sb.Append(','); Emit(sb, arr[k]); }
                sb.Append(']');
                break;
            case IReadOnlyDictionary<string, object> obj:
                sb.Append('{');
                var keys = obj.Keys.ToList();
                keys.Sort(StringComparer.Ordinal);
                for (var k = 0; k < keys.Count; k++)
                {
                    if (k > 0) sb.Append(',');
                    EmitString(sb, keys[k]);
                    sb.Append(':');
                    Emit(sb, obj[keys[k]]);
                }
                sb.Append('}');
                break;
            default: throw new InvalidOperationException($"non-canonical value type {v.GetType()}");
        }
    }

    private static void EmitString(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (var ch in s)
        {
            if (ch == '"' || ch == '\\') { sb.Append('\\').Append(ch); }
            else if (ch < 0x20) throw new InvalidOperationException("control char in canonical string");
            else sb.Append(ch);
        }
        sb.Append('"');
    }

    // The single canonical signature form used by BOTH bind (Roslyn) and probe (reflection).
    internal static string Sig(string returnFull, string declFull, string method, IEnumerable<string> paramFull)
        => $"{returnFull} {declFull}.{method}({string.Join(", ", paramFull)})";
}

// --- BIND MODE (G1, G2) ------------------------------------------------------------------
internal static class BindMode
{
    public static int Run(string[] args)
    {
        var a = Args.Parse(args, 1);
        var preText = SourceText.From(File.ReadAllText(a["preimage"]), Encoding.UTF8);
        var postText = SourceText.From(File.ReadAllText(a["postimage"]), Encoding.UTF8);
        var target = a["target"];
        var selectedType = a["selected-class"];
        var sourceFile = a["source-file"];
        var slotsDir = a["slots-dir"];
        using var bp = JsonDocument.Parse(File.ReadAllBytes(a["bind-params"]));

        var parse = new CSharpParseOptions(LanguageVersion.CSharp12, DocumentationMode.None);
        var preTree = CSharpSyntaxTree.ParseText(preText, parse, sourceFile);
        var postTree = CSharpSyntaxTree.ParseText(postText, parse, sourceFile);
        var (refs, slotByPath) = References.Build(slotsDir);
        // only the POSTIMAGE is compiled (semantic model); the preimage is used syntactically
        // (span location + identity + the frozen replacement text), so its class type does not
        // clash with the postimage's.
        var comp = CSharpCompilation.Create("weaktargetbind",
            new[] { postTree }, refs,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, deterministic: true));
        var postModel = comp.GetSemanticModel(postTree);

        var preRoot = preTree.GetRoot();
        var postRoot = postTree.GetRoot();

        // 1-3: locate every converted preimage AddAssignment at its hash-bound span; revalidate
        // identity; reproduce the frozen Step 8 replacement text; record (start, len, replacement).
        var edits = new List<Edit>();
        foreach (var cand in bp.RootElement.GetProperty("converted").EnumerateArray())
        {
            var fid = cand.GetProperty("finding_id").GetString()!;
            var span = new TextSpan(cand.GetProperty("acquire_span").GetProperty("start").GetInt32(),
                                    cand.GetProperty("acquire_span").GetProperty("length").GetInt32());
            var node = preRoot.FindNode(span, getInnermostNodeForTie: true);
            if (node is not AssignmentExpressionSyntax asg || asg.Span != span
                || !asg.IsKind(SyntaxKind.AddAssignmentExpression))
                return Refuse("CALLSITE_BINDING", $"{fid}: preimage span is not an event += acquire");
            var replacement = ReplacementText(asg, target, cand, out var err);
            if (replacement is null) return Refuse("CALLSITE_BINDING", $"{fid}: {err}");
            if ((cand.GetProperty("file").GetString() ?? "") != sourceFile)
                return Refuse("CALLSITE_BINDING", $"{fid}: candidate file is not the target file");
            edits.Add(new Edit(fid, span.Start, span.Length, replacement,
                               cand.GetProperty("source").GetString()!,
                               cand.GetProperty("normalized_handler").GetString()!));
        }
        if (edits.Count == 0) return Refuse("CALLSITE_BINDING", "no converted candidates to bind");

        // 4: ordered non-overlapping edits, cumulative length deltas -> each derived postimage span.
        edits.Sort((x, y) => x.PreStart.CompareTo(y.PreStart));
        for (var i = 1; i < edits.Count; i++)
            if (edits[i].PreStart < edits[i - 1].PreStart + edits[i - 1].PreLen)
                return Refuse("CALLSITE_BINDING", "overlapping converted acquire spans");
        long delta = 0;
        var callsites = new List<IReadOnlyDictionary<string, object>>();
        IMethodSymbol? firstSym = null;
        int derivedOrdinal = -1;
        string? asmName = null, mvid = null, token = null, sig = null;
        foreach (var e in edits)
        {
            var postStart = (int)(e.PreStart + delta);
            var postSpan = new TextSpan(postStart, e.Replacement.Length);
            delta += e.Replacement.Length - e.PreLen;

            // 5-6: exactly one invocation node exactly filling the derived postimage span.
            var pnode = postRoot.FindNode(postSpan, getInnermostNodeForTie: true);
            if (pnode is not InvocationExpressionSyntax inv || inv.Span != postSpan)
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: no invocation at the derived postimage span");
            if (inv.Expression.ToString() != target)
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: invocation target is not plan.target_api.subscribe");
            var argList = inv.ArgumentList.Arguments;
            if (argList.Count != 2
                || argList[0].Expression.ToString() != e.Source
                || Rewrite.NormalizeHandler(argList[1].Expression).ToString() != e.NormalizedHandler)
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: invocation arguments do not match the candidate");

            // 7: resolve the IMethodSymbol; every converted callsite must resolve to one symbol.
            if (postModel.GetSymbolInfo(inv).Symbol is not IMethodSymbol sym)
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: cannot resolve the invocation symbol");
            if (SymbolEqualityComparer.Default.Equals(sym.ContainingAssembly, comp.Assembly))
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: target is source-defined, not a reference wrapper");
            if (firstSym is null)
            {
                firstSym = sym;
                var mref = comp.GetMetadataReference(sym.ContainingAssembly) as PortableExecutableReference;
                var path = mref?.FilePath ?? "";
                if (!slotByPath.TryGetValue(path, out var slot))
                    return Refuse("WRAPPER_BINDING", $"{e.Fid}: resolved assembly is not a materialized slot");
                derivedOrdinal = slot.Ordinal;
                asmName = sym.ContainingAssembly.Name;
                mvid = ReadMvid(path);
                token = "0x" + sym.MetadataToken.ToString("x8");
                sig = Program.Sig(FQ(sym.ReturnType), FQ(sym.ContainingType), sym.Name,
                                  sym.Parameters.Select(p => FQ(p.Type)));
            }
            else if (!SymbolEqualityComparer.Default.Equals(sym, firstSym))
            {
                return Refuse("CALLSITE_BINDING", $"{e.Fid}: converted callsites resolve to different methods");
            }
            callsites.Add(new Dictionary<string, object>
            {
                ["finding_id"] = e.Fid,
                ["preimage_span"] = new List<object> { (long)e.PreStart, (long)e.PreLen },
                ["postimage_span"] = new List<object> { (long)postSpan.Start, (long)postSpan.Length },
                ["assembly_simple_name"] = asmName!,
                ["module_mvid"] = mvid!,
                ["metadata_token"] = token!,
                ["resolved_signature"] = sig!,
            });
        }
        callsites.Sort((x, y) => string.CompareOrdinal((string)x["finding_id"], (string)y["finding_id"]));

        var outObj = new Dictionary<string, object>
        {
            ["version"] = 1L,
            ["operation"] = "weak-target-bind",
            ["converted_callsites"] = (long)edits.Count,
            ["derived_wrapper_ordinal"] = (long)derivedOrdinal,
            ["resolved_wrapper"] = new Dictionary<string, object>
            {
                ["assembly_simple_name"] = asmName!,
                ["module_mvid"] = mvid!,
                ["metadata_token"] = token!,
                ["resolved_signature"] = sig!,
            },
            ["callsite_binding"] = new Dictionary<string, object>
            {
                ["all_callsites_same_symbol"] = true,
                ["target_is_source_defined"] = false,
            },
            ["callsites"] = callsites.Cast<object>().ToList(),
        };
        Program.WriteCanonical(a["out"], outObj);
        return 0;
    }

    private static string? ReplacementText(AssignmentExpressionSyntax asg, string target,
        JsonElement cand, out string err)
    {
        err = "";
        ExpressionSyntax receiver;
        string eventName;
        if (asg.Left is MemberAccessExpressionSyntax lhs
            && lhs.IsKind(SyntaxKind.SimpleMemberAccessExpression)
            && lhs.Name is IdentifierNameSyntax ev)
        { receiver = lhs.Expression; eventName = ev.Identifier.Text; }
        else if (asg.Left is IdentifierNameSyntax bare)
        { receiver = Microsoft.CodeAnalysis.CSharp.SyntaxFactory.ThisExpression(); eventName = bare.Identifier.Text; }
        else { err = "LHS is not an event member access"; return null; }
        if (eventName != cand.GetProperty("event").GetString()) { err = "event name mismatch"; return null; }
        var eventFull = asg.Left.ToString();
        var dot = eventFull.LastIndexOf('.');
        var srcDisplay = dot >= 0 ? eventFull[..dot] : "this";
        if (srcDisplay != cand.GetProperty("source").GetString()) { err = "receiver mismatch"; return null; }
        if (asg.Right.ToString() != cand.GetProperty("handler").GetString()) { err = "handler mismatch"; return null; }
        var handler = Rewrite.NormalizeHandler(asg.Right);
        if (Rewrite.NormWs(handler.ToString()) != cand.GetProperty("normalized_handler").GetString())
        { err = "normalized handler mismatch"; return null; }
        var comma = Microsoft.CodeAnalysis.CSharp.SyntaxFactory
            .Token(SyntaxKind.CommaToken)
            .WithTrailingTrivia(Microsoft.CodeAnalysis.CSharp.SyntaxFactory.Space);
        return Microsoft.CodeAnalysis.CSharp.SyntaxFactory.InvocationExpression(
            Microsoft.CodeAnalysis.CSharp.SyntaxFactory.ParseExpression(target),
            Microsoft.CodeAnalysis.CSharp.SyntaxFactory.ArgumentList(
                Microsoft.CodeAnalysis.CSharp.SyntaxFactory.SeparatedList(
                    new[]
                    {
                        Microsoft.CodeAnalysis.CSharp.SyntaxFactory.Argument(receiver.WithoutTrivia()),
                        Microsoft.CodeAnalysis.CSharp.SyntaxFactory.Argument(handler.WithoutTrivia()),
                    },
                    new[] { comma }))).ToString();
    }

    // fully-qualified metadata type name (no `global::`, no C# keyword aliasing), matching the
    // reflection FullName the probe uses, so bind and probe signatures are byte-identical (G3).
    private static readonly SymbolDisplayFormat FQFmt = SymbolDisplayFormat.FullyQualifiedFormat
        .WithMiscellaneousOptions(SymbolDisplayFormat.FullyQualifiedFormat.MiscellaneousOptions
                                  & ~SymbolDisplayMiscellaneousOptions.UseSpecialTypes);

    private static string FQ(ITypeSymbol t) => t.ToDisplayString(FQFmt).Replace("global::", "");

    private static string ReadMvid(string dllPath)
    {
        using var fs = File.OpenRead(dllPath);
        using var pe = new PEReader(fs);
        var mr = pe.GetMetadataReader();
        return mr.GetGuid(mr.GetModuleDefinition().Mvid).ToString("D");
    }

    private static int Refuse(string category, string message)
    {
        Console.Error.WriteLine($"{category}: {message}");
        return category switch
        {
            "CALLSITE_BINDING" => 11,
            "WRAPPER_BINDING" => 12,
            "TOOLCHAIN_BINDING" => 13,
            _ => 2,
        };
    }

    private readonly record struct Edit(string Fid, int PreStart, int PreLen, string Replacement,
        string Source, string NormalizedHandler);
}

// The frozen Step 8 handler peel + whitespace normalization (copied grammar; the rewriter stays frozen).
internal static class Rewrite
{
    public static ExpressionSyntax NormalizeHandler(ExpressionSyntax e)
    {
        while (e is BaseObjectCreationExpressionSyntax { ArgumentList.Arguments: { Count: 1 } args })
            e = args[0].Expression;
        return e;
    }

    public static string NormWs(string s) => string.Join(" ", s.Split((char[]?)null,
        StringSplitOptions.RemoveEmptyEntries));
}

internal static class References
{
    public static (List<MetadataReference>, Dictionary<string, Slot>) Build(string slotsDir)
    {
        var refs = new List<MetadataReference>();
        var byPath = new Dictionary<string, Slot>(StringComparer.OrdinalIgnoreCase);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        // framework references = the SELECTED runtime the probe is pinned to (TPA), first.
        var tpa = ((AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string) ?? "")
            .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries);
        foreach (var p in tpa) { seen.Add(Path.GetFileNameWithoutExtension(p)); refs.Add(MetadataReference.CreateFromFile(p)); }
        // reference slots in exact ordinal order; first simple-name wins (framework wins over a slot).
        if (Directory.Exists(slotsDir))
            foreach (var slot in Directory.GetDirectories(slotsDir).OrderBy(d => d, StringComparer.Ordinal))
            {
                var dll = Directory.GetFiles(slot, "*.dll").Single();
                var name = Path.GetFileNameWithoutExtension(dll);
                var ordinal = int.Parse(Path.GetFileName(slot));
                var full = Path.GetFullPath(dll);
                byPath[full] = new Slot(ordinal, full, name);
                if (seen.Add(name)) refs.Add(MetadataReference.CreateFromFile(full));
            }
        return (refs, byPath);
    }

    public readonly record struct Slot(int Ordinal, string Path, string SimpleName);
}

internal static class Args
{
    public static Dictionary<string, string> Parse(string[] args, int start)
    {
        var d = new Dictionary<string, string>();
        for (var i = start; i < args.Length; i++)
            if (args[i].StartsWith("--") && i + 1 < args.Length) { d[args[i][2..]] = args[i + 1]; i++; }
        return d;
    }
}

// --- PROBE MODE (G3, G4, F4) -------------------------------------------------------------
internal static class ProbeMode
{
    private const int CollectionRounds = 5;
    private const int AllocPerRound = 4194304;

    public static int Run(string[] args)
    {
        var a = Args.Parse(args, 1);
        var ordinal = int.Parse(a["wrapper-ordinal"]);
        var attempt = int.Parse(a["attempt"]);
        var target = a["target"];
        var slotsDir = a["slots-dir"];
        var outPath = a["out"];

        var slot = Path.Combine(slotsDir, ordinal.ToString("D6"));
        var rootPath = Path.GetFullPath(Directory.GetFiles(slot, "*.dll").Single());
        var slotSha = Sha256(rootPath);

        var dot = target.LastIndexOf('.');
        var typeName = target[..dot];
        var methodName = target[(dot + 1)..];

        var alc = new WrapperLoadContext(rootPath, slotsDir);
        MethodInfo method;
        Action<INotifyPropertyChanged, PropertyChangedEventHandler> invoke;
        string asmName, mvid, token, sig;
        try
        {
            // G4 preflight: load-by-path, resolve type + exact method, build delegate, prepare.
            var root = alc.LoadFromAssemblyPath(rootPath);
            var type = root.GetTypes().Single(t => t.IsPublic && !t.IsGenericType && t.Name == typeName);
            var cands = type.GetMethods(BindingFlags.Public | BindingFlags.Static)
                .Where(m => m.Name == methodName).ToList();
            method = cands.Single(m => !m.IsGenericMethod && m.ReturnType == typeof(void)
                && Params(m).SequenceEqual(new[] { typeof(INotifyPropertyChanged), typeof(PropertyChangedEventHandler) }));
            invoke = (Action<INotifyPropertyChanged, PropertyChangedEventHandler>)
                method.CreateDelegate(typeof(Action<INotifyPropertyChanged, PropertyChangedEventHandler>));
            RuntimeHelpers.PrepareMethod(method.MethodHandle);
            asmName = root.GetName().Name!;
            mvid = method.Module.ModuleVersionId.ToString("D");
            token = "0x" + method.MetadataToken.ToString("x8");
            sig = Program.Sig("System.Void", FullName(type), method.Name, Params(method).Select(FullName));
        }
        catch (Exception e) when (IsLoaderFailure(e))
        {
            var obj = new Dictionary<string, object>
            {
                ["version"] = 1L, ["operation"] = "weak-target-probe", ["attempt"] = (long)attempt,
                ["runtime_unsupported"] = true,
                ["reason"] = Inner(e).GetType().Name,
            };
            Program.WriteCanonical(outPath, obj);
            return 10; // WRAPPER_RUNTIME_UNSUPPORTED
        }

        var strongSource = new ProbeSource();
        var strongRef = RunStrong(strongSource, out var strongDelivered);
        var weakRef = RunCollectable();
        var targetSource = new ProbeSource();
        var wref = RunTarget(targetSource, invoke, out var delivered, out var threwSub, out var threwFirst);

        for (var r = 0; r < CollectionRounds; r++) CollectRound(strongSource, targetSource);
        GC.KeepAlive(strongSource);
        GC.KeepAlive(targetSource);

        var strongRetained = strongRef.TryGetTarget(out _);
        var weakCollected = !weakRef.TryGetTarget(out _);
        var subscriberCollected = !wref.TryGetTarget(out _);

        bool threwPost = false;
        try { targetSource.Raise(); } catch { threwPost = true; }
        GC.KeepAlive(targetSource);

        var result = new Dictionary<string, object>
        {
            ["version"] = 1L,
            ["operation"] = "weak-target-probe",
            ["attempt"] = (long)attempt,
            ["strong_delivered_once"] = strongDelivered == 1,
            ["strong_retained"] = strongRetained,
            ["weak_control_collected"] = weakCollected,
            ["delivered_count"] = (long)delivered,
            ["threw_on_subscribe"] = threwSub,
            ["threw_on_first_raise"] = threwFirst,
            ["subscriber_collected"] = subscriberCollected,
            ["threw_on_post_collection_raise"] = threwPost,
            ["resolved_wrapper"] = new Dictionary<string, object>
            {
                ["ordinal"] = (long)ordinal,
                ["slot_sha256"] = "sha256:" + slotSha,
                ["assembly_simple_name"] = asmName,
                ["module_mvid"] = mvid,
                ["metadata_token"] = token,
                ["resolved_signature"] = sig,
            },
        };
        Program.WriteCanonical(outPath, result);
        return 0;
    }

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.NoOptimization)]
    private static WeakReference<ProbeSubscriber> RunTarget(ProbeSource source,
        Action<INotifyPropertyChanged, PropertyChangedEventHandler> invoke,
        out int delivered, out bool threwSub, out bool threwFirst)
    {
        threwSub = false; threwFirst = false; delivered = 0;
        var sub = new ProbeSubscriber();
        var handler = new PropertyChangedEventHandler(sub.OnChanged);
        try { invoke(source, handler); } catch { threwSub = true; }
        if (!threwSub) { try { source.Raise(); } catch { threwFirst = true; } }
        delivered = sub.Count;
        return new WeakReference<ProbeSubscriber>(sub, trackResurrection: false);
    }

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.NoOptimization)]
    private static WeakReference<ProbeSubscriber> RunStrong(ProbeSource source, out int delivered)
    {
        var sub = new ProbeSubscriber();
        source.PropertyChanged += sub.OnChanged;
        source.Raise();
        delivered = sub.Count;
        return new WeakReference<ProbeSubscriber>(sub, trackResurrection: false);
    }

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.NoOptimization)]
    private static WeakReference<ProbeSubscriber> RunCollectable()
        => new(new ProbeSubscriber(), trackResurrection: false);

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.NoOptimization)]
    private static void CollectRound(ProbeSource keepA, ProbeSource keepB)
    {
        var pressure = new byte[AllocPerRound];
        for (var i = 0; i < pressure.Length; i += 4096) pressure[i] = 1;
        pressure = null!;
        GC.Collect(GC.MaxGeneration, GCCollectionMode.Forced, true, true);
        GC.WaitForPendingFinalizers();
        GC.Collect(GC.MaxGeneration, GCCollectionMode.Forced, true, true);
        GC.KeepAlive(keepA);
        GC.KeepAlive(keepB);
    }

    private static Type[] Params(MethodInfo m) => m.GetParameters().Select(p => p.ParameterType).ToArray();
    private static string FullName(Type t) => t.FullName ?? t.Name;

    private static bool IsLoaderFailure(Exception e)
    {
        var x = Inner(e);
        return x is BadImageFormatException or FileNotFoundException or FileLoadException
            or TypeLoadException or MissingMethodException or MissingMemberException
            or ReflectionTypeLoadException or InvalidOperationException;
    }

    private static Exception Inner(Exception e)
        => e is TargetInvocationException { InnerException: { } inner } ? inner : e;

    private static string Sha256(string path)
    {
        using var s = File.OpenRead(path);
        using var h = System.Security.Cryptography.SHA256.Create();
        return Convert.ToHexString(h.ComputeHash(s)).ToLowerInvariant();
    }
}

internal sealed class ProbeSource : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public void Raise() => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs("Probe"));
}

internal sealed class ProbeSubscriber
{
    public int Count;
    public void OnChanged(object? sender, PropertyChangedEventArgs e) => Count++;
}

internal sealed class WrapperLoadContext : AssemblyLoadContext
{
    private readonly string _slotsDir;
    public WrapperLoadContext(string rootPath, string slotsDir) : base("weak-target", isCollectible: false)
        => _slotsDir = slotsDir;

    protected override Assembly? Load(AssemblyName name)
    {
        if (!Directory.Exists(_slotsDir)) return null;
        foreach (var slot in Directory.GetDirectories(_slotsDir).OrderBy(d => d, StringComparer.Ordinal))
        {
            var dll = Directory.GetFiles(slot, "*.dll").SingleOrDefault();
            if (dll != null && string.Equals(Path.GetFileNameWithoutExtension(dll), name.Name,
                    StringComparison.OrdinalIgnoreCase))
                return LoadFromAssemblyPath(Path.GetFullPath(dll));
        }
        return null;
    }
}
