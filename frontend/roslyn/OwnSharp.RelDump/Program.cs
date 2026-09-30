using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

// usage: ownsharp-reldump <target.dll> [<extra reference dir> ...]
// One JSON record per PUBLIC method / property getter of a PUBLIC type: signature relations from the Roslyn
// compilation over the assembly and its references, IL relations from a linear opcode walk of the method body
// (no data flow: the 'before ret' relation is the instruction that immediately precedes each ret).
if (args.Length == 0) { Console.Error.WriteLine("usage: ownsharp-reldump <target.dll> [refdir...]"); return 2; }
var target = Path.GetFullPath(args[0]);
var refs = new List<MetadataReference>(); var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
void Add(string path) { var n = Path.GetFileNameWithoutExtension(path); if (!seen.Add(n)) return; try { refs.Add(MetadataReference.CreateFromFile(path)); } catch { seen.Remove(n); } }
Add(target);
foreach (var d in args.Skip(1)) foreach (var f in Directory.EnumerateFiles(d, "*.dll", SearchOption.AllDirectories).OrderBy(x => x, StringComparer.Ordinal)) Add(f);
foreach (var f in Directory.EnumerateFiles(Path.GetDirectoryName(target)!, "*.dll")) Add(f);
foreach (var f in (AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string ?? "").Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)) Add(f);
var comp = CSharpCompilation.Create("reldump", references: refs);
var targetName = Path.GetFileNameWithoutExtension(target);
var asm = comp.SourceModule.ReferencedAssemblySymbols.FirstOrDefault(a => string.Equals(a.Name, targetName, StringComparison.OrdinalIgnoreCase));
if (asm is null) { Console.Error.WriteLine("target assembly symbol not found: " + targetName); return 3; }
var idisp = comp.GetTypeByMetadataName("System.IDisposable"); var iadisp = comp.GetTypeByMetadataName("System.IAsyncDisposable");
var safeHandle = comp.GetTypeByMetadataName("System.Runtime.InteropServices.SafeHandle");
bool Disp(ITypeSymbol? t) => t is INamedTypeSymbol n && idisp is not null && (SymbolEqualityComparer.Default.Equals(n, idisp) || n.AllInterfaces.Any(i => SymbolEqualityComparer.Default.Equals(i, idisp)));
bool ADisp(ITypeSymbol? t) => t is INamedTypeSymbol n && iadisp is not null && (SymbolEqualityComparer.Default.Equals(n, iadisp) || n.AllInterfaces.Any(i => SymbolEqualityComparer.Default.Equals(i, iadisp)));
bool DerivesFrom(ITypeSymbol? t, INamedTypeSymbol? b) { if (b is null) return false; for (var c = t as INamedTypeSymbol; c is not null; c = c.BaseType) if (SymbolEqualityComparer.Default.Equals(c.OriginalDefinition, b)) return true; return false; }
ITypeSymbol? Unwrap(ITypeSymbol t) { if (t is INamedTypeSymbol n && n.ContainingNamespace?.ToDisplayString() == "System.Threading.Tasks" && n.Name is "Task" or "ValueTask") return n.IsGenericType ? n.TypeArguments[0] : null; return t; }
// disposability of a metadata type NAME (from IL operands): cached lookup in the compilation
var dispCache = new Dictionary<string, bool>(StringComparer.Ordinal);
bool DispName(string? fullName)
{
    if (string.IsNullOrEmpty(fullName)) return false;
    if (dispCache.TryGetValue(fullName, out var v)) return v;
    var t = comp.GetTypeByMetadataName(fullName);
    if (t is null && fullName.Contains('+')) t = comp.GetTypeByMetadataName(fullName);
    v = t is not null && (Disp(t) || ADisp(t)) && !(t.ContainingNamespace?.ToDisplayString() == "System.Threading.Tasks");
    dispCache[fullName] = v; return v;
}
// ---- metadata / IL side
using var pe = new PEReader(File.OpenRead(target)); var md = pe.GetMetadataReader();
var prov = new NameProvider(md);
string TypeName(EntityHandle h)
{
    switch (h.Kind)
    {
        case HandleKind.TypeDefinition: return prov.DefName((TypeDefinitionHandle)h);
        case HandleKind.TypeReference: return prov.RefName((TypeReferenceHandle)h);
        case HandleKind.TypeSpecification: return md.GetTypeSpecification((TypeSpecificationHandle)h).DecodeSignature(prov, null!);
        default: return "?";
    }
}
(string type, string name, string ret, bool pinvoke) Callee(EntityHandle h)
{
    switch (h.Kind)
    {
        case HandleKind.MethodDefinition:
        {
            var m = md.GetMethodDefinition((MethodDefinitionHandle)h); var sig = m.DecodeSignature(prov, null!);
            return (prov.DefName(m.GetDeclaringType()), md.GetString(m.Name), sig.ReturnType, (m.Attributes & MethodAttributes.PinvokeImpl) != 0);
        }
        case HandleKind.MemberReference:
        {
            var m = md.GetMemberReference((MemberReferenceHandle)h);
            var ret = "?"; if (m.GetKind() == MemberReferenceKind.Method) { try { ret = m.DecodeMethodSignature(prov, null!).ReturnType; } catch { } }
            return (TypeName(m.Parent), md.GetString(m.Name), ret, false);
        }
        case HandleKind.MethodSpecification: return Callee(md.GetMethodSpecification((MethodSpecificationHandle)h).Method);
        default: return ("?", "?", "?", false);
    }
}
string FieldType(EntityHandle h)
{
    try
    {
        if (h.Kind == HandleKind.FieldDefinition) return md.GetFieldDefinition((FieldDefinitionHandle)h).DecodeSignature(prov, null!);
        if (h.Kind == HandleKind.MemberReference) { var m = md.GetMemberReference((MemberReferenceHandle)h); if (m.GetKind() == MemberReferenceKind.Field) return m.DecodeFieldSignature(prov, null!); }
    } catch { }
    return "?";
}
// opcode table (System.Reflection.Emit) for operand sizes
var one = new OpCode?[256]; var two = new OpCode?[256];
foreach (var fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) if (fi.GetValue(null) is OpCode oc) { if (oc.Size == 1) one[(byte)oc.Value] = oc; else two[(byte)(oc.Value & 0xff)] = oc; }
var pinvokeDefs = new HashSet<int>();
foreach (var mh in md.MethodDefinitions) { var m = md.GetMethodDefinition(mh); if ((m.Attributes & MethodAttributes.PinvokeImpl) != 0) pinvokeDefs.Add(MetadataTokens.GetToken(mh)); }
var nameToken = new Regex("^[A-Z][a-z]*", RegexOptions.CultureInvariant);
string MetaName(INamedTypeSymbol t) { var n = t.MetadataName; return t.ContainingType is { } ct ? MetaName(ct) + "+" + n : (t.ContainingNamespace is { IsGlobalNamespace: false } ns ? ns.ToDisplayString() + "." + n : n); }
IEnumerable<INamedTypeSymbol> AllTypes(INamespaceSymbol ns)
{
    foreach (var m in ns.GetMembers())
        if (m is INamespaceSymbol sub) { foreach (var t in AllTypes(sub)) yield return t; }
        else if (m is INamedTypeSymbol t) { yield return t; foreach (var nt in Nested(t)) yield return nt; }
    static IEnumerable<INamedTypeSymbol> Nested(INamedTypeSymbol t) { foreach (var n in t.GetTypeMembers()) { yield return n; foreach (var nn in Nested(n)) yield return nn; } }
}
var records = new List<object>(); int bodies = 0, noBody = 0;
foreach (var t in AllTypes(asm.GlobalNamespace).Where(t => t.DeclaredAccessibility == Accessibility.Public))
{
    var tDisp = Disp(t) || ADisp(t); var tFinal = t.GetMembers("Finalize").Any(); var tSafe = DerivesFrom(t, safeHandle);
    foreach (var m in t.GetMembers().Where(m => m.DeclaredAccessibility == Accessibility.Public))
    {
        IMethodSymbol? me = m as IMethodSymbol; bool getter = false;
        if (m is IPropertySymbol pr && pr.GetMethod is { } g) { me = g; getter = true; }
        if (me is null || me.MethodKind is not (MethodKind.Ordinary or MethodKind.PropertyGet) || me.ReturnsVoid) continue;
        if (me.Name is "GetEnumerator" or "GetAsyncEnumerator" or "GetHashCode" or "ToString" or "Equals") continue;
        var rt = Unwrap(me.ReturnType); if (rt is null) continue;
        var retDisp = Disp(rt) || ADisp(rt);
        // IL relations
        int newobjAll = 0, newobjDisp = 0, callsAll = 0, callsDisp = 0, callsDispose = 0, callsPinvoke = 0, stfldDisp = 0, ldfldDisp = 0, ldsfldDisp = 0, stsfldDisp = 0, throws = 0, rets = 0, ilSize = 0;
        var beforeRet = new Dictionary<string, int>(); bool isPinvoke = false, hasBody = false; var newobjTypes = new HashSet<string>(); var norm = new System.Text.StringBuilder(); var callees = new HashSet<string>(); var externalCallees = new HashSet<string>(); var staticFieldTypes = new HashSet<string>();
        try
        {
            var token = me.MetadataToken;
            if (token != 0 && MetadataTokens.EntityHandle(token) is { Kind: HandleKind.MethodDefinition } mdh)
            {
                var def = md.GetMethodDefinition((MethodDefinitionHandle)mdh); isPinvoke = (def.Attributes & MethodAttributes.PinvokeImpl) != 0;
                if (def.RelativeVirtualAddress != 0)
                {
                    var body = pe.GetMethodBody(def.RelativeVirtualAddress); var r = body.GetILReader(); ilSize = r.Length; hasBody = true; bodies++;
                    string prev = "start";
                    while (r.RemainingBytes > 0)
                    {
                        var b = r.ReadByte(); OpCode? oc = b == 0xfe ? two[r.ReadByte()] : one[b];
                        if (oc is null) { break; }
                        string cur = oc.Value.Name ?? "?"; int operand = 0; EntityHandle? h = null;
                        switch (oc.Value.OperandType)
                        {
                            case OperandType.InlineNone: break;
                            case OperandType.ShortInlineBrTarget: case OperandType.ShortInlineI: case OperandType.ShortInlineVar: r.ReadByte(); break;
                            case OperandType.InlineVar: r.ReadInt16(); break;
                            case OperandType.InlineI8: case OperandType.InlineR: r.ReadInt64(); break;
                            case OperandType.InlineSwitch: { var n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadInt32(); break; }
                            case OperandType.InlineMethod: case OperandType.InlineField: case OperandType.InlineType: case OperandType.InlineTok: operand = r.ReadInt32(); try { h = MetadataTokens.EntityHandle(operand); } catch { h = null; } break;
                            default: r.ReadInt32(); break;
                        }
                        norm.Append(cur).Append(' ');
                        if (h is { } oh) { try { norm.Append(oh.Kind is HandleKind.MethodDefinition or HandleKind.MemberReference or HandleKind.MethodSpecification ? Callee(oh).type + "::" + Callee(oh).name : oh.Kind is HandleKind.FieldDefinition ? FieldType(oh) + "::f" : TypeName(oh)); } catch { norm.Append("?"); } }
                        norm.Append(';');
                        if (cur.StartsWith("newobj") && h is { } nh) { newobjAll++; var c = Callee(nh); if (DispName(c.type)) { newobjDisp++; newobjTypes.Add(c.type); } }
                        else if ((cur == "call" || cur == "callvirt") && h is { } ch)
                        {
                            callsAll++; var c = Callee(ch);
                            if (ch.Kind == HandleKind.MethodDefinition) callees.Add(c.type + "::" + c.name); else if (ch.Kind == HandleKind.MethodSpecification || ch.Kind == HandleKind.MemberReference) { if (ch.Kind == HandleKind.MethodSpecification && md.GetMethodSpecification((MethodSpecificationHandle)ch).Method.Kind == HandleKind.MethodDefinition) callees.Add(c.type + "::" + c.name); else externalCallees.Add(c.type + "::" + c.name); }
                            if (DispName(c.ret)) callsDisp++;
                            if (c.name is "Dispose" or "DisposeAsync" or "Close") callsDispose++;
                            if (c.pinvoke || pinvokeDefs.Contains(operand)) callsPinvoke++;
                        }
                        else if (cur == "stfld" && h is { } sh) { if (DispName(FieldType(sh))) stfldDisp++; }
                        else if (cur == "ldfld" && h is { } lh) { if (DispName(FieldType(lh))) ldfldDisp++; }
                        else if (cur == "ldsfld" && h is { } lsh) { if (DispName(FieldType(lsh))) ldsfldDisp++; try { staticFieldTypes.Add(lsh.Kind == HandleKind.FieldDefinition ? prov.DefName(md.GetFieldDefinition((FieldDefinitionHandle)lsh).GetDeclaringType()) : lsh.Kind == HandleKind.MemberReference ? TypeName(md.GetMemberReference((MemberReferenceHandle)lsh).Parent) : "?"); } catch { } }
                        else if (cur == "stsfld" && h is { } ssh) { if (DispName(FieldType(ssh))) stsfldDisp++; }
                        else if (cur == "throw") throws++;
                        else if (cur == "ret") { rets++; var k = prev.Split('.')[0]; beforeRet[k] = beforeRet.GetValueOrDefault(k) + 1; }
                        if (cur != "nop") prev = cur;
                    }
                }
                else noBody++;
            }
        }
        catch (Exception ex) { Console.Error.WriteLine($"il: {t.ToDisplayString()}.{me.Name}: {ex.GetType().Name}"); }
        records.Add(new
        {
            metadata_name = MetaName(t) + "::" + (getter ? "get_" + m.Name : me.Name), callees = callees.OrderBy(x => x, StringComparer.Ordinal).ToArray(), external_callees = externalCallees.OrderBy(x => x, StringComparer.Ordinal).ToArray(), callable = $"{t.ToDisplayString()}.{(getter ? "get_" + m.Name : me.Name)}", arity = me.Parameters.Length, il_hash = hasBody ? Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(norm.ToString())))[..16] : null, param_types = me.Parameters.Select(p => p.Type.ToDisplayString()).ToArray(), is_static = me.IsStatic, is_getter = getter,
            name_token = nameToken.Match(getter ? m.Name : me.Name).Value, is_extension = me.IsExtensionMethod, is_virtual = me.IsVirtual || me.IsAbstract || me.IsOverride,
            ret_type = rt.ToDisplayString(), ret_disposable = retDisp, ret_async_wrapped = !SymbolEqualityComparer.Default.Equals(rt, me.ReturnType),
            ret_is_declaring_type = SymbolEqualityComparer.Default.Equals(rt.OriginalDefinition, t.OriginalDefinition), ret_is_type_parameter = rt.TypeKind == TypeKind.TypeParameter || rt.SpecialType == SpecialType.System_Object, static_field_types = staticFieldTypes.OrderBy(x => x, StringComparer.Ordinal).ToArray(), ret_is_interface = rt.TypeKind == TypeKind.Interface, ret_is_abstract = rt is INamedTypeSymbol rn && rn.IsAbstract,
            declaring_type_disposable = tDisp, declaring_type_has_finalizer = tFinal, declaring_type_is_safehandle = tSafe, declaring_type_is_static = t.IsStatic,
            has_bool_param = me.Parameters.Any(p => p.Type.SpecialType == SpecialType.System_Boolean), has_disposable_param = me.Parameters.Any(p => Disp(p.Type) || ADisp(p.Type)),
            has_string_param = me.Parameters.Any(p => p.Type.SpecialType == SpecialType.System_String), has_stream_param = me.Parameters.Any(p => p.Type.ToDisplayString() == "System.IO.Stream"),
            has_body = hasBody, is_pinvoke = isPinvoke, il_size = ilSize, newobj_all = newobjAll, newobj_disposable = newobjDisp, newobj_disposable_types = newobjTypes.Take(4).ToArray(),
            calls_all = callsAll, calls_disposable_returning = callsDisp, calls_dispose = callsDispose, calls_pinvoke = callsPinvoke,
            stfld_disposable = stfldDisp, ldfld_disposable = ldfldDisp, ldsfld_disposable = ldsfldDisp, stsfld_disposable = stsfldDisp, throws, rets, before_ret = beforeRet
        });
    }
}
var cctors = new Dictionary<string, string>();
foreach (var th in md.TypeDefinitions)
{
    var td = md.GetTypeDefinition(th);
    foreach (var mh in td.GetMethods())
    {
        var mdef = md.GetMethodDefinition(mh); if (md.GetString(mdef.Name) != ".cctor" || mdef.RelativeVirtualAddress == 0) continue;
        var r = pe.GetMethodBody(mdef.RelativeVirtualAddress).GetILReader(); var norm = new System.Text.StringBuilder();
        while (r.RemainingBytes > 0)
        {
            var b = r.ReadByte(); OpCode? oc = b == 0xfe ? two[r.ReadByte()] : one[b]; if (oc is null) break; string cur = oc.Value.Name ?? "?"; EntityHandle? h = null;
            switch (oc.Value.OperandType)
            {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget: case OperandType.ShortInlineI: case OperandType.ShortInlineVar: r.ReadByte(); break;
                case OperandType.InlineVar: r.ReadInt16(); break;
                case OperandType.InlineI8: case OperandType.InlineR: r.ReadInt64(); break;
                case OperandType.InlineSwitch: { var n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadInt32(); break; }
                case OperandType.InlineMethod: case OperandType.InlineField: case OperandType.InlineType: case OperandType.InlineTok: { var op = r.ReadInt32(); try { h = MetadataTokens.EntityHandle(op); } catch { } break; }
                default: r.ReadInt32(); break;
            }
            norm.Append(cur).Append(' ');
            if (h is { } oh) { try { norm.Append(oh.Kind is HandleKind.MethodDefinition or HandleKind.MemberReference or HandleKind.MethodSpecification ? Callee(oh).type + "::" + Callee(oh).name : oh.Kind is HandleKind.FieldDefinition ? FieldType(oh) + "::f" : TypeName(oh)); } catch { norm.Append("?"); } }
            norm.Append(';');
        }
        cctors[prov.DefName(th)] = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(norm.ToString())))[..16];
    }
}
var mvid = asm.Modules.First().GetMetadata()?.GetModuleVersionId().ToString() ?? "";
Console.WriteLine(JsonSerializer.Serialize(new { assembly = asm.Name, version = asm.Identity.Version.ToString(), mvid, methods = records.Count, bodies, no_body = noBody, cctors, records }, new JsonSerializerOptions { WriteIndented = false }));
return 0;

sealed class NameProvider : ISignatureTypeProvider<string, object>
{
    readonly MetadataReader _md; public NameProvider(MetadataReader md) { _md = md; }
    public string DefName(TypeDefinitionHandle h)
    {
        var d = _md.GetTypeDefinition(h); var name = _md.GetString(d.Name);
        var decl = d.GetDeclaringType();
        if (!decl.IsNil) return DefName(decl) + "+" + name;
        var ns = _md.GetString(d.Namespace); return ns.Length == 0 ? name : ns + "." + name;
    }
    public string RefName(TypeReferenceHandle h)
    {
        var r = _md.GetTypeReference(h); var name = _md.GetString(r.Name);
        if (r.ResolutionScope.Kind == HandleKind.TypeReference) return RefName((TypeReferenceHandle)r.ResolutionScope) + "+" + name;
        var ns = _md.GetString(r.Namespace); return ns.Length == 0 ? name : ns + "." + name;
    }
    public string GetPrimitiveType(PrimitiveTypeCode c) => "System." + c;
    public string GetTypeFromDefinition(MetadataReader r, TypeDefinitionHandle h, byte rawTypeKind) => DefName(h);
    public string GetTypeFromReference(MetadataReader r, TypeReferenceHandle h, byte rawTypeKind) => RefName(h);
    public string GetTypeFromSpecification(MetadataReader r, object g, TypeSpecificationHandle h, byte rawTypeKind) => r.GetTypeSpecification(h).DecodeSignature(this, g);
    public string GetSZArrayType(string e) => e + "[]"; public string GetArrayType(string e, ArrayShape s) => e + "[,]";
    public string GetByReferenceType(string e) => e; public string GetPointerType(string e) => e + "*"; public string GetPinnedType(string e) => e;
    public string GetGenericInstantiation(string g, System.Collections.Immutable.ImmutableArray<string> a) => g;
    public string GetGenericMethodParameter(object g, int i) => "!!" + i; public string GetGenericTypeParameter(object g, int i) => "!" + i;
    public string GetFunctionPointerType(MethodSignature<string> s) => "fnptr"; public string GetModifiedType(string m, string u, bool req) => u;
}
