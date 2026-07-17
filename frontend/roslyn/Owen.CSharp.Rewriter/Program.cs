// owen-rewrite — S2 deterministic subscription rewriter (steps 4-7).
//
//   owen-rewrite --plan <validated-plan.json> --candidates <candidates.json>
//                --root <source-root> --out <artifact-dir>
//
// SELF-CONTAINED: this executable never assumes an upstream gate ran. It re-derives the
// canonical plan envelope from the candidates bundle, re-checks the bundle hash binding,
// the decision<->candidate bijection, the action permissions, the canonical root-relative
// source path, the root confinement and the pristine source SHA — over the exact bytes it
// then parses (no TOCTOU) — before it touches anything. Every malformed shape is a
// controlled refusal (exit 2), never a traceback.
//
// It then runs the syntactic span-node identity guard for every convert_acquire decision
// and — only if EVERY guard passes — publishes an edited postimage + a rewriter-report.json
// as ONE transactional bundle (staged in a sibling dir, atomically renamed into place).
// Any failure refuses the whole operation: nothing is published, and the source tree is
// never written to.
//
// Syntax-only by design: the acquire is matched to its hash-bound candidate using the SAME
// derivations the extractor/collector used to produce those fields, so no SemanticModel is
// needed. The INotifyPropertyChanged contract + the convert_acquire permission were proven
// in S0 and are carried in the hash-bound candidate.

using System.Security;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

return Rewriter.Run(args);

/// <summary>A controlled refusal: every failure path raises this, never an unhandled throw.</summary>
file sealed class RefuseError(string message) : Exception(message);

file static class Rewriter
{
    public static int Run(string[] args)
    {
        try
        {
            return Apply(args);
        }
        catch (RefuseError e)
        {
            Console.Error.WriteLine($"owen-rewrite: refuse: {e.Message}");
            return 2;
        }
        catch (Exception e)
        {
            // Fail closed. Every known shape/path/span failure is already a RefuseError with
            // a real message; this net exists so that an UNANTICIPATED one is still a
            // refusal that writes nothing, rather than a traceback with an exit code the
            // caller might not read as "refused".
            Console.Error.WriteLine($"owen-rewrite: refuse: internal error ({e.GetType().Name}: {e.Message})");
            return 2;
        }
    }

    static int Apply(string[] args)
    {
        // ---- args ----
        string? planPath = null, candPath = null, root = null, outDir = null;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--plan" when i + 1 < args.Length: planPath = args[++i]; break;
                case "--candidates" when i + 1 < args.Length: candPath = args[++i]; break;
                case "--root" when i + 1 < args.Length: root = args[++i]; break;
                case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
                default: throw new RefuseError($"unknown or incomplete argument '{args[i]}'");
            }
        }
        if (planPath is null || candPath is null || root is null || outDir is null)
            throw new RefuseError("--plan, --candidates, --root and --out are all required");

        var planBytes = ReadAll(planPath, "plan");
        var candBytes = ReadAll(candPath, "candidates");
        var plan = Parse(planBytes, "plan");
        var bundle = Parse(candBytes, "candidates");

        // ---- 1. the plan envelope must BE the canonical projection of this bundle ----
        // Re-derived here from the bundle's own fields (never trusted from the plan), which
        // simultaneously proves the hash binding, the bijection and the action permissions.
        var cands = ValidateBundleShape(bundle);
        var decisions = ValidateCanonicalPlan(plan, bundle, cands);

        var targetExpr = ValidateTargetApi(Str(Prop(plan, "target_api", "plan"), "subscribe", "plan.target_api"));

        var sourceFile = Arr(plan, "source_files", "plan")[0];
        var relPath = Str(sourceFile, "path", "plan.source_files[0]");
        var expectedSha = Str(sourceFile, "sha256", "plan.source_files[0]");

        // ---- 2. paths: canonical root-relative, confined, and an out-dir off the tree ----
        var rootReal = RealDir(root, "--root");
        var absPath = ConfineToRoot(rootReal, relPath);
        var outFull = PrepareOutDir(outDir, rootReal);

        // ---- 3. source: read ONCE; hash, decode and parse the SAME bytes (no TOCTOU) ----
        var sourceBytes = ReadAll(absPath, $"source '{relPath}'");
        if (Sha256Hex(sourceBytes) != expectedSha)
            throw new RefuseError($"STALE SOURCE / PREIMAGE MISMATCH for {relPath}");

        var (decoded, hadBom) = DecodeStrictUtf8(sourceBytes, relPath);
        var sourceText = SourceText.From(decoded);
        var rootNode = CSharpSyntaxTree.ParseText(sourceText).GetRoot();

        // ---- 4. guard + compute EVERY edit before applying ANY ----
        var edits = new List<TextChange>();
        var applied = new List<string>();
        var manual = new List<string>();
        var seenSpans = new List<TextSpan>();

        foreach (var (fid, action, cand) in decisions)
        {
            if (action == "manual_review") { manual.Add(fid); continue; }

            var span = SpanOf(cand, fid, sourceText.Length);
            foreach (var s in seenSpans)
                if (span.OverlapsWith(s))
                    throw new RefuseError($"{fid}: overlapping convert_acquire spans");
            seenSpans.Add(span);

            edits.Add(new TextChange(span, BuildEdit(rootNode, sourceText, span, cand, fid, targetExpr)));
            applied.Add(fid);
        }

        // ---- 5. apply (all-or-nothing) ----
        var postText = sourceText.WithChanges(edits);
        if (!EditsAreExact(sourceText, edits, postText))
            throw new RefuseError("post-image differs from the source outside the declared edits");

        // Only the declared spans changed, so the file's own line endings outside them are
        // untouched; re-attach the original BOM presence.
        var body = new UTF8Encoding(false, throwOnInvalidBytes: true).GetBytes(postText.ToString());
        var postBytes = hadBom ? Utf8Bom.Concat(body).ToArray() : body;

        var report = new
        {
            version = 1,
            operation = "apply-subscription-fixes",
            input_bundle_sha256 = Str(plan, "input_bundle_sha256", "plan"),
            validated_plan_sha256 = Sha256Hex(planBytes),   // the SAME bytes that were parsed
            target_api = new { subscribe = targetExpr.ToString() },
            source_files = new[]
            {
                new { path = relPath, pre_sha256 = expectedSha, post_sha256 = Sha256Hex(postBytes) },
            },
            applied_findings = applied.OrderBy(x => x, StringComparer.Ordinal).ToArray(),
            manual_review_findings = manual.OrderBy(x => x, StringComparer.Ordinal).ToArray(),
        };

        // ---- 6. publish the bundle transactionally ----
        Publish(outFull, relPath, postBytes, report, rootReal);

        Console.WriteLine($"owen-rewrite: applied {applied.Count} convert_acquire, "
            + $"{manual.Count} manual_review -> {outDir}");
        return 0;
    }

    // ================= inputs =================

    static readonly byte[] Utf8Bom = [0xEF, 0xBB, 0xBF];

    static byte[] ReadAll(string path, string what)
    {
        try
        {
            return File.ReadAllBytes(path);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException)
        {
            throw new RefuseError($"cannot read {what}: {e.Message}");
        }
    }

    static JsonElement Parse(byte[] bytes, string what)
    {
        try
        {
            return JsonDocument.Parse(bytes).RootElement;
        }
        catch (JsonException e)
        {
            throw new RefuseError($"{what} is not valid JSON: {e.Message}");
        }
    }

    static JsonElement Prop(JsonElement o, string name, string ctx)
    {
        if (o.ValueKind != JsonValueKind.Object)
            throw new RefuseError($"{ctx} must be an object");
        if (!o.TryGetProperty(name, out var v))
            throw new RefuseError($"{ctx}: missing '{name}'");
        return v;
    }

    static string Str(JsonElement o, string name, string ctx)
    {
        var v = Prop(o, name, ctx);
        return v.ValueKind == JsonValueKind.String
            ? v.GetString()!
            : throw new RefuseError($"{ctx}: '{name}' must be a string");
    }

    static int Int(JsonElement o, string name, string ctx)
    {
        var v = Prop(o, name, ctx);
        if (v.ValueKind != JsonValueKind.Number || !v.TryGetInt32(out var i) || i < 0)
            throw new RefuseError($"{ctx}: '{name}' must be a non-negative int");
        return i;
    }

    static List<JsonElement> Arr(JsonElement o, string name, string ctx)
    {
        var v = Prop(o, name, ctx);
        return v.ValueKind == JsonValueKind.Array
            ? v.EnumerateArray().ToList()
            : throw new RefuseError($"{ctx}: '{name}' must be an array");
    }

    static void ExactKeys(JsonElement o, string ctx, params string[] keys)
    {
        if (o.ValueKind != JsonValueKind.Object)
            throw new RefuseError($"{ctx} must be an object");
        var actual = o.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal);
        if (!actual.SetEquals(keys))
            throw new RefuseError(
                $"{ctx}: unexpected key set [{string.Join(", ", actual.OrderBy(k => k, StringComparer.Ordinal))}] "
                + $"(expected exactly [{string.Join(", ", keys.OrderBy(k => k, StringComparer.Ordinal))}])");
    }

    // ================= canonical JSON (Python `json.dumps(sort_keys, separators=(",",":"),
    // ensure_ascii=False)` — the exact producer of `bundle_sha256`) =================

    static string Canonical(JsonElement e)
    {
        var sb = new StringBuilder();
        Canon(e, sb);
        return sb.ToString();
    }

    static void Canon(JsonElement e, StringBuilder sb)
    {
        switch (e.ValueKind)
        {
            case JsonValueKind.Object:
                // Python sorts keys by code point; ordinal is the same for every key the
                // schema allows. A divergence could only ever cause a REFUSAL, never an
                // accept, because the hash is compared, not reconstructed.
                var props = e.EnumerateObject().ToList();
                props.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
                sb.Append('{');
                for (var i = 0; i < props.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    CanonString(props[i].Name, sb);
                    sb.Append(':');
                    Canon(props[i].Value, sb);
                }
                sb.Append('}');
                break;
            case JsonValueKind.Array:
                sb.Append('[');
                var first = true;
                foreach (var item in e.EnumerateArray())
                {
                    if (!first) sb.Append(',');
                    first = false;
                    Canon(item, sb);
                }
                sb.Append(']');
                break;
            case JsonValueKind.String: CanonString(e.GetString()!, sb); break;
            case JsonValueKind.Number: sb.Append(e.GetRawText()); break;
            case JsonValueKind.True: sb.Append("true"); break;
            case JsonValueKind.False: sb.Append("false"); break;
            case JsonValueKind.Null: sb.Append("null"); break;
            default: throw new RefuseError("candidates: unsupported JSON value");
        }
    }

    static void CanonString(string s, StringBuilder sb)
    {
        sb.Append('"');
        foreach (var c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\b': sb.Append("\\b"); break;
                case '\f': sb.Append("\\f"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    // ensure_ascii=False: everything >= 0x20 is emitted raw.
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    static string Sha256Hex(byte[] bytes) =>
        "sha256:" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    static string BundleSha256(JsonElement bundle) =>
        Sha256Hex(new UTF8Encoding(false, throwOnInvalidBytes: true).GetBytes(Canonical(bundle)));

    // ================= binding =================

    // The FROZEN domain envelope, restated here because a hash cannot carry it. The bundle
    // binding proves the plan and the candidates agree with EACH OTHER; it says nothing
    // about whether the candidates obey the permission policy. A forged, perfectly
    // self-consistent pair could otherwise declare `event_contract: name_only` with
    // `allowed_actions: ["convert_acquire"]`, re-hash, and be honoured.
    static readonly string[] Contracts =
        ["inotify_property_changed", "name_only", "other", "unresolved"];
    static readonly string[] Actions = ["convert_acquire", "manual_review"];

    /// <summary>The candidates bundle, validated against the frozen envelope and returned
    /// as (finding_id, element) in bundle order. Every field a later step reads is checked
    /// here, so nothing downstream can throw a shape exception.</summary>
    static List<(string Id, JsonElement El)> ValidateBundleShape(JsonElement bundle)
    {
        ExactKeys(bundle, "candidates", "version", "operation", "target_api", "selection",
            "source_files", "candidates");
        if (Int(bundle, "version", "candidates") != 1)
            throw new RefuseError("candidates: unsupported version");
        if (Str(bundle, "operation", "candidates") != "fix-subscriptions")
            throw new RefuseError("candidates: operation must be 'fix-subscriptions'");
        ExactKeys(Prop(bundle, "target_api", "candidates"), "candidates.target_api", "subscribe");
        Str(Prop(bundle, "target_api", "candidates"), "subscribe", "candidates.target_api");

        var sel = Prop(bundle, "selection", "candidates");
        ExactKeys(sel, "candidates.selection", "allowed_types", "selected_findings", "constraints");
        var types = Arr(sel, "allowed_types", "candidates.selection");
        if (types.Count != 1)
            throw new RefuseError("candidates.selection.allowed_types must hold exactly one type");
        ExactKeys(types[0], "candidates.selection.allowed_types[0]", "full_name", "file");
        var typeName = Str(types[0], "full_name", "candidates.selection.allowed_types[0]");
        var typeFile = Str(types[0], "file", "candidates.selection.allowed_types[0]");
        CheckConstraints(Prop(sel, "constraints", "candidates.selection"), "candidates.selection.constraints");

        var files = Arr(bundle, "source_files", "candidates");
        if (files.Count != 1)
            throw new RefuseError("candidates.source_files must hold exactly one file");
        ExactKeys(files[0], "candidates.source_files[0]", "path", "sha256");
        var srcPath = Str(files[0], "path", "candidates.source_files[0]");
        Str(files[0], "sha256", "candidates.source_files[0]");
        // The selected type and the source file must be the SAME file — comparing each
        // against its own copy would still admit `type -> A.cs, source -> B.cs`.
        if (typeFile != srcPath)
            throw new RefuseError(
                $"candidates: the selected type's file '{typeFile}' is not the source file '{srcPath}'");

        var list = new List<(string, JsonElement)>();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var cands = Arr(bundle, "candidates", "candidates");
        if (cands.Count == 0)
            throw new RefuseError("candidates: the bundle is empty");
        foreach (var c in cands)
        {
            var ctx = $"candidates[{list.Count}]";
            var fid = Str(c, "finding_id", ctx);
            if (!ids.Add(fid))
                throw new RefuseError($"{ctx}: duplicate finding_id {fid}");
            foreach (var k in new[] { "event", "source", "handler", "source_identity",
                                      "source_identity_kind", "handler_identity",
                                      "handler_identity_kind" })
                Str(c, k, ctx);
            var span = Prop(c, "acquire_span", ctx);
            Int(span, "start", $"{ctx}.acquire_span");
            Int(span, "length", $"{ctx}.acquire_span");

            // Each candidate belongs to the ONE selected (type, file) pair.
            if (Str(c, "containing_type", ctx) != typeName)
                throw new RefuseError($"{ctx}: is outside the single selected type {typeName}");
            if (Str(c, "file", ctx) != srcPath)
                throw new RefuseError($"{ctx}: is outside the single selected source file {srcPath}");

            var contract = Str(c, "event_contract", ctx);
            if (!Contracts.Contains(contract))
                throw new RefuseError($"{ctx}: unknown event_contract '{contract}'");
            var actions = Arr(c, "allowed_actions", ctx);
            if (actions.Count == 0)
                throw new RefuseError($"{ctx}: allowed_actions must be a non-empty string array");
            var seenActions = new HashSet<string>(StringComparer.Ordinal);
            foreach (var a in actions)
            {
                if (a.ValueKind != JsonValueKind.String)
                    throw new RefuseError($"{ctx}: allowed_actions must be a string array");
                var action = a.GetString()!;
                if (!Actions.Contains(action))
                    throw new RefuseError($"{ctx}: unknown action '{action}' in allowed_actions");
                if (!seenActions.Add(action))
                    throw new RefuseError($"{ctx}: duplicate action '{action}' in allowed_actions");
            }
            // The frozen tiering: converting an acquire is permitted ONLY for a proven
            // INotifyPropertyChanged contract, whatever the bundle claims to allow.
            if (seenActions.Contains("convert_acquire") && contract != "inotify_property_changed")
                throw new RefuseError(
                    $"{ctx}: convert_acquire is not permitted for event_contract '{contract}'");
            list.Add((fid, c));
        }

        // selected_findings: null, or a unique set naming exactly these candidates.
        var selected = Prop(sel, "selected_findings", "candidates.selection");
        if (selected.ValueKind != JsonValueKind.Null)
        {
            if (selected.ValueKind != JsonValueKind.Array)
                throw new RefuseError("candidates.selection.selected_findings must be null or an array");
            var picked = new HashSet<string>(StringComparer.Ordinal);
            foreach (var f in selected.EnumerateArray())
            {
                if (f.ValueKind != JsonValueKind.String)
                    throw new RefuseError("candidates.selection.selected_findings must hold strings");
                if (!picked.Add(f.GetString()!))
                    throw new RefuseError($"candidates.selection.selected_findings: duplicate {f.GetString()}");
            }
            if (!picked.SetEquals(ids))
                throw new RefuseError(
                    "candidates.selection.selected_findings does not name exactly the bundle's candidates");
        }
        return list;
    }

    static void CheckConstraints(JsonElement cons, string ctx)
    {
        ExactKeys(cons, ctx, "max_types_changed", "max_files_changed", "allow_helper_changes",
            "allow_config_changes", "allow_suppressions");
        if (Int(cons, "max_types_changed", ctx) != 1 || Int(cons, "max_files_changed", ctx) != 1)
            throw new RefuseError($"{ctx}: this slice changes exactly one type in one file");
        foreach (var k in new[] { "allow_helper_changes", "allow_config_changes", "allow_suppressions" })
            if (Prop(cons, k, ctx).ValueKind != JsonValueKind.False)
                throw new RefuseError($"{ctx}.{k} must be false");
    }

    /// <summary>Re-derive the canonical plan projection from the (hash-bound) bundle and
    /// require the supplied plan to BE it, field for field. This is the whole trust
    /// argument: nothing in the plan is believed, only confirmed.</summary>
    static List<(string Id, string Action, JsonElement Cand)> ValidateCanonicalPlan(
        JsonElement plan, JsonElement bundle, List<(string Id, JsonElement El)> cands)
    {
        ExactKeys(plan, "plan", "version", "operation", "input_bundle_sha256", "target_api",
            "selection", "source_files", "decisions");
        if (Int(plan, "version", "plan") != 1)
            throw new RefuseError("plan: unsupported version");
        if (Str(plan, "operation", "plan") != "fix-subscriptions")
            throw new RefuseError("plan: operation must be 'fix-subscriptions'");

        // The bundle hash binding — over the bundle's canonical bytes, not the file's.
        var declared = Str(plan, "input_bundle_sha256", "plan");
        var actual = BundleSha256(bundle);
        if (declared != actual)
            throw new RefuseError(
                $"plan.input_bundle_sha256 {declared} does not bind these candidates ({actual})");

        // target_api / selection / source_files: exactly the projection of the bundle.
        ExactKeys(Prop(plan, "target_api", "plan"), "plan.target_api", "subscribe");
        if (Str(Prop(plan, "target_api", "plan"), "subscribe", "plan.target_api")
            != Str(Prop(bundle, "target_api", "candidates"), "subscribe", "candidates.target_api"))
            throw new RefuseError("plan.target_api.subscribe does not match the candidates bundle");

        var sel = Prop(plan, "selection", "plan");
        ExactKeys(sel, "plan.selection", "allowed_types", "selected_findings", "constraints");
        var bSel = Prop(bundle, "selection", "candidates");
        var types = Arr(sel, "allowed_types", "plan.selection");
        var bTypes = Arr(bSel, "allowed_types", "candidates.selection");
        if (types.Count != 1 || bTypes.Count != 1)
            throw new RefuseError("selection.allowed_types must hold exactly one type");
        ExactKeys(types[0], "plan.selection.allowed_types[0]", "full_name", "file");
        if (Str(types[0], "full_name", "plan.selection.allowed_types[0]")
                != Str(bTypes[0], "full_name", "candidates.selection.allowed_types[0]")
            || Str(types[0], "file", "plan.selection.allowed_types[0]")
                != Str(bTypes[0], "file", "candidates.selection.allowed_types[0]"))
            throw new RefuseError("plan.selection.allowed_types does not match the candidates bundle");
        if (Canonical(Prop(sel, "selected_findings", "plan.selection"))
            != Canonical(Prop(bSel, "selected_findings", "candidates.selection")))
            throw new RefuseError("plan.selection.selected_findings does not match the candidates bundle");

        CheckConstraints(Prop(sel, "constraints", "plan.selection"), "plan.selection.constraints");

        var files = Arr(plan, "source_files", "plan");
        var bFiles = Arr(bundle, "source_files", "candidates");
        if (files.Count != 1 || bFiles.Count != 1)
            throw new RefuseError("source_files must hold exactly one file");
        ExactKeys(files[0], "plan.source_files[0]", "path", "sha256");
        var relPath = Str(files[0], "path", "plan.source_files[0]");
        if (relPath != Str(bFiles[0], "path", "candidates.source_files[0]")
            || Str(files[0], "sha256", "plan.source_files[0]")
                != Str(bFiles[0], "sha256", "candidates.source_files[0]"))
            throw new RefuseError("plan.source_files does not match the candidates bundle");

        // decisions: a total bijection onto the candidates, IN candidate order, each action
        // permitted by that candidate's own allowed list, each span/file re-derived.
        var decisions = Arr(plan, "decisions", "plan");
        if (decisions.Count != cands.Count)
            throw new RefuseError(
                $"plan.decisions covers {decisions.Count} of {cands.Count} candidates (a decision is required for each)");
        var typeName = Str(types[0], "full_name", "plan.selection.allowed_types[0]");
        var result = new List<(string, string, JsonElement)>();
        for (var i = 0; i < decisions.Count; i++)
        {
            var ctx = $"plan.decisions[{i}]";
            var d = decisions[i];
            ExactKeys(d, ctx, "finding_id", "action", "file", "acquire_span");
            var (cid, cand) = cands[i];
            var fid = Str(d, "finding_id", ctx);
            if (fid != cid)
                throw new RefuseError($"{ctx}: {fid} is out of candidate order (expected {cid})");
            var action = Str(d, "action", ctx);
            if (action is not ("convert_acquire" or "manual_review"))
                throw new RefuseError($"{ctx}: out-of-scope action '{action}'");
            if (!Arr(cand, "allowed_actions", "candidate").Any(a => a.GetString() == action))
                throw new RefuseError($"{ctx}: action '{action}' is not allowed for {fid}");
            if (Str(d, "file", ctx) != Str(cand, "file", "candidate") || Str(d, "file", ctx) != relPath)
                throw new RefuseError($"{ctx}: file does not match the candidate / the selected source file");
            if (Canonical(Prop(d, "acquire_span", ctx)) != Canonical(Prop(cand, "acquire_span", "candidate")))
                throw new RefuseError($"{ctx}: acquire_span does not match the candidate");
            if (Str(cand, "containing_type", "candidate") != typeName)
                throw new RefuseError($"{ctx}: candidate is outside the single selected type");
            result.Add((fid, action, cand));
        }
        return result;
    }

    /// <summary>The target API grammar: a canonical identifier / member-access chain and
    /// NOTHING else — no invocation, arguments, generics, `?.`, operators, object creation
    /// or arbitrary expression may ride into generated C# from the plan.</summary>
    static ExpressionSyntax ValidateTargetApi(string target)
    {
        var expr = SyntaxFactory.ParseExpression(target);
        if (expr.ContainsDiagnostics || expr.ToString() != target)
            throw new RefuseError($"target_api.subscribe '{target}': not a single canonical expression");
        CheckChain(expr, target);
        return expr;

        static void CheckChain(ExpressionSyntax e, string target)
        {
            switch (e)
            {
                case IdentifierNameSyntax id when !id.Identifier.IsMissing
                        && id.Identifier.Text.Length > 0:
                    return;
                case MemberAccessExpressionSyntax ma
                        when ma.IsKind(SyntaxKind.SimpleMemberAccessExpression)
                            && ma.Name is IdentifierNameSyntax { Identifier.IsMissing: false }:
                    CheckChain(ma.Expression, target);
                    return;
                default:
                    throw new RefuseError(
                        $"target_api.subscribe '{target}': only an identifier / member-access chain "
                        + $"is allowed here (got {e.Kind()})");
            }
        }
    }

    // ================= paths =================

    static string SafeFullPath(string path, string what)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception e) when (e is ArgumentException or NotSupportedException
            or PathTooLongException or SecurityException or IOException)
        {
            throw new RefuseError($"{what}: invalid path '{path}' ({e.Message})");
        }
    }

    /// <summary>The raw symlink/junction target of `path`, or null if it is not a link.</summary>
    static string? LinkTargetOf(string path, string what)
    {
        try
        {
            FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
            return info.LinkTarget;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException
            or ArgumentException or NotSupportedException or SecurityException)
        {
            throw new RefuseError($"{what}: cannot inspect '{path}' ({e.Message})");
        }
    }

    /// <summary>The PHYSICAL path — every existing component resolved, exactly as
    /// os.path.realpath does. Resolving only the final component would leave confinement
    /// lexical: `root/linked-dir -> /outside` is not itself a link at `root/linked-dir/f.cs`,
    /// so a purely-final resolve would call the escape confined. On each link we restart
    /// from the target's root with the target's segments ahead of the remaining ones, so a
    /// link whose own target sits behind further links still resolves. `..` is applied
    /// AFTER the prefix is resolved, which is what makes it physical rather than textual.</summary>
    static string RealPath(string path, string what)
    {
        var full = SafeFullPath(path, what);
        var root = Path.GetPathRoot(full);
        if (string.IsNullOrEmpty(root))
            throw new RefuseError($"{what}: '{path}' has no filesystem root");
        var pending = new Queue<string>(Segments(full, root));
        var cur = root;
        var hops = 0;
        while (pending.Count > 0)
        {
            var seg = pending.Dequeue();
            if (seg == ".") continue;
            if (seg == "..")
            {
                cur = Path.GetDirectoryName(cur) ?? root;
                if (cur.Length < root.Length) cur = root;
                continue;
            }
            var next = Path.Combine(cur, seg);
            var raw = LinkTargetOf(next, what);
            if (raw is null) { cur = next; continue; }
            if (++hops > 40)
                throw new RefuseError($"{what}: too many symlink hops resolving '{path}'");
            var target = SafeFullPath(Path.IsPathRooted(raw) ? raw : Path.Combine(cur, raw), what);
            var tRoot = Path.GetPathRoot(target);
            if (string.IsNullOrEmpty(tRoot))
                throw new RefuseError($"{what}: link '{next}' has an unrooted target");
            var rest = pending.ToList();
            pending.Clear();
            foreach (var s in Segments(target, tRoot)) pending.Enqueue(s);
            foreach (var s in rest) pending.Enqueue(s);
            cur = tRoot;
        }
        return cur;
    }

    static string[] Segments(string full, string root) =>
        full[root.Length..].Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
            StringSplitOptions.RemoveEmptyEntries);

    static string RealDir(string root, string what)
    {
        var real = RealPath(root, what);
        if (!Directory.Exists(real))
            throw new RefuseError($"{what}: '{root}' is not a directory");
        return real;
    }

    /// <summary>Path comparison is a PLATFORM property, not a string property: `C:\Repo`
    /// and `c:\repo` are one directory on Windows, and two on a case-sensitive filesystem.
    /// Comparing ordinally everywhere would let `c:\repo\out` slip past a `C:\Repo` root.</summary>
    static readonly StringComparison PathCmp = OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase
        : StringComparison.Ordinal;

    /// <summary>Is `path` the directory `dir` itself, or something under it? Both must
    /// already be physical (symlink-resolved) paths.</summary>
    static bool SameOrInside(string dir, string path)
    {
        if (string.Equals(path, dir, PathCmp)) return true;
        var prefix = dir.EndsWith(Path.DirectorySeparatorChar) ? dir : dir + Path.DirectorySeparatorChar;
        return path.StartsWith(prefix, PathCmp);
    }

    /// <summary>`rel` must be exactly the canonical root-relative form the collector emits
    /// (`/`-separated, no drive, no `..`, no absolute path), and must resolve to a regular
    /// file inside `rootReal`.</summary>
    static string ConfineToRoot(string rootReal, string rel)
    {
        if (rel.Length == 0 || Path.IsPathRooted(rel) || rel.Contains('\\')
            || rel.StartsWith('/') || rel.Contains("//", StringComparison.Ordinal)
            || rel.Split('/').Any(p => p is "" or "." or ".."))
            throw new RefuseError($"source path '{rel}' is not a canonical root-relative path");
        // PHYSICAL confinement: `rel` may still walk through a symlinked directory.
        var abs = RealPath(Path.Combine(rootReal, rel), $"source path '{rel}'");
        if (!SameOrInside(rootReal, abs))
            throw new RefuseError($"source path '{rel}' resolves outside the root ({abs})");
        if (!File.Exists(abs))
            throw new RefuseError($"source path '{rel}' is not a regular file");
        if (Path.GetRelativePath(rootReal, abs).Replace('\\', '/') != rel)
            throw new RefuseError($"source path '{rel}' is not in canonical form for the root");
        return abs;
    }

    /// <summary>The out-dir must be a fresh directory PHYSICALLY off the source tree. The
    /// parent is resolved first and everything is then built under that verified physical
    /// path, so a symlinked parent cannot land the bundle in the source tree while the
    /// string still looks external.</summary>
    static string PrepareOutDir(string outDir, string rootReal)
    {
        var outFull = SafeFullPath(outDir, "--out");
        var name = Path.GetFileName(outFull);
        if (string.IsNullOrEmpty(name))
            throw new RefuseError($"--out '{outDir}': not a directory name");
        var parent = Path.GetDirectoryName(outFull);
        if (parent is null || !Directory.Exists(parent))
            throw new RefuseError($"--out '{outDir}': the parent directory does not exist");
        var parentPhys = CheckOutParent(parent, outDir, rootReal);
        var outPhys = Path.Combine(parentPhys, name);
        if (Directory.Exists(outPhys) || File.Exists(outPhys) || LinkTargetOf(outPhys, "--out") is not null)
            throw new RefuseError($"--out '{outDir}' already exists — refusing to mix runs");
        return outPhys;
    }

    /// <summary>Claim a staging directory under the already-verified physical parent, then
    /// PROVE we own it — created here and now, unpredictably named, a real empty directory
    /// that resolves to itself. A deterministic name that is merely checked-then-written is
    /// a window: between the check and the first write, anyone able to guess the name can
    /// drop a link there and redirect the "isolated" postimage into the source tree.</summary>
    static string ClaimStaging(string parentPhys, string what)
    {
        for (var attempt = 0; attempt < 8; attempt++)
        {
            var name = ".owen-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
            var path = Path.Combine(parentPhys, name);
            if (Directory.Exists(path) || File.Exists(path) || LinkTargetOf(path, what) is not null)
                continue;   // astronomically unlikely; try again rather than touch it
            try
            {
                // Owner-only on Unix, set AS the directory is created — never a widened
                // window between mkdir and chmod.
                if (OperatingSystem.IsWindows())
                    Directory.CreateDirectory(path);
                else
                    Directory.CreateDirectory(path, UnixFileMode.UserRead | UnixFileMode.UserWrite
                        | UnixFileMode.UserExecute);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException
                or ArgumentException or NotSupportedException or SecurityException)
            {
                throw new RefuseError($"{what}: cannot create a staging directory ({e.Message})");
            }
            if (LinkTargetOf(path, what) is not null)
                throw new RefuseError($"{what}: the staging path is a link — refusing");
            if (!string.Equals(RealPath(path, what), path, PathCmp))
                throw new RefuseError($"{what}: the staging path does not resolve to itself — refusing");
            if (Directory.EnumerateFileSystemEntries(path).Any())
                throw new RefuseError($"{what}: the claimed staging directory is not empty — refusing");
            return path;
        }
        throw new RefuseError($"{what}: could not claim a staging directory");
    }

    /// <summary>The out-dir's parent, resolved physically and proven to be off the source
    /// tree. Called again immediately before publication: the check is cheap and the
    /// filesystem is not ours alone.</summary>
    static string CheckOutParent(string parent, string outDir, string rootReal)
    {
        var parentPhys = RealPath(parent, "--out parent");
        if (SameOrInside(rootReal, parentPhys))
            throw new RefuseError(
                $"--out '{outDir}' resolves inside the source root ({parentPhys}) — refusing to write into the tree");
        return parentPhys;
    }

    // ================= source decoding =================

    /// <summary>Decode with a THROWING UTF-8 decoder: the default Encoding.UTF8 silently
    /// replaces invalid bytes with U+FFFD, which would let the post-image re-encode bytes
    /// outside the declared edits while EditsAreExact (which compares decoded text)
    /// happily agreed. Mirrors the extractor's BOM-detecting read for UTF-8 and refuses
    /// every other encoding outright.</summary>
    static (string Text, bool HadBom) DecodeStrictUtf8(byte[] bytes, string rel)
    {
        if (bytes.Length >= 2 && ((bytes[0] == 0xFF && bytes[1] == 0xFE) || (bytes[0] == 0xFE && bytes[1] == 0xFF)))
            throw new RefuseError($"'{rel}': UTF-16 source (only UTF-8 in this slice)");
        var hadBom = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF;
        try
        {
            var strict = new UTF8Encoding(false, throwOnInvalidBytes: true);
            var text = hadBom ? strict.GetString(bytes, 3, bytes.Length - 3) : strict.GetString(bytes);
            return (text, hadBom);
        }
        catch (DecoderFallbackException e)
        {
            throw new RefuseError($"'{rel}': not valid UTF-8 ({e.Message})");
        }
    }

    // ================= the span-node identity guard =================

    /// <summary>Bounds are checked BEFORE the TextSpan exists: `new TextSpan(start, length)`
    /// throws on an overflowing start+length, and an attacker-supplied span must be a
    /// refusal, not an exception. `Int` has already rejected negatives and non-int32s, so
    /// `sourceLength - start` cannot underflow here.</summary>
    static TextSpan SpanOf(JsonElement cand, string fid, int sourceLength)
    {
        var span = Prop(cand, "acquire_span", $"candidate {fid}");
        var ctx = $"candidate {fid}.acquire_span";
        var start = Int(span, "start", ctx);
        var length = Int(span, "length", ctx);
        if (start > sourceLength || length > sourceLength - start)
            throw new RefuseError($"{fid}: acquire_span is outside the source");
        return new TextSpan(start, length);
    }

    static string BuildEdit(SyntaxNode rootNode, SourceText sourceText, TextSpan span,
        JsonElement cand, string fid, ExpressionSyntax targetExpr)
    {
        // 1-2: the span is exactly one `X += Y` AddAssignment.
        var node = rootNode.FindNode(span, getInnermostNodeForTie: true);
        if (node is not AssignmentExpressionSyntax asg
            || asg.Span != span
            || !asg.IsKind(SyntaxKind.AddAssignmentExpression))
            throw new RefuseError($"{fid}: span is not an event `+=` acquire");

        // No comment / directive trivia inside the replaced expression (can't move it safely).
        foreach (var t in asg.DescendantTrivia())
            if (t.IsKind(SyntaxKind.SingleLineCommentTrivia) || t.IsKind(SyntaxKind.MultiLineCommentTrivia)
                || t.IsDirective)
                throw new RefuseError($"{fid}: comment/directive inside the acquire — refusing to move it");

        // 3-4: the LHS is `receiver.EventName` (or a bare `EventName` on implicit this).
        ExpressionSyntax receiverExpr;
        string eventName;
        if (asg.Left is MemberAccessExpressionSyntax lhs
            && lhs.IsKind(SyntaxKind.SimpleMemberAccessExpression)
            && lhs.Name is IdentifierNameSyntax evName)
        {
            receiverExpr = lhs.Expression;
            eventName = evName.Identifier.Text;
        }
        else if (asg.Left is IdentifierNameSyntax bare)
        {
            receiverExpr = SyntaxFactory.ThisExpression();
            eventName = bare.Identifier.Text;
        }
        else
        {
            throw new RefuseError($"{fid}: LHS is not an event member access");
        }
        if (eventName != Str(cand, "event", "candidate"))
            throw new RefuseError($"{fid}: event name does not match the candidate");

        // 5-6: receiver + handler must match the hash-bound candidate. Both sides are
        // re-derived HERE with the producers' own derivations, so the comparison is exact
        // (byte-for-byte over the SHA-pinned bytes) rather than a lossy re-normalization:
        //   candidate.source  = collector: `a.Left.ToString()` up to its last '.', else "this"
        //   candidate.handler = extractor: `a.Right.ToString()` (raw, unpeeled)
        var eventFull = asg.Left.ToString();
        var dot = eventFull.LastIndexOf('.');
        var sourceDisplay = dot >= 0 ? eventFull[..dot] : "this";
        if (sourceDisplay != Str(cand, "source", "candidate"))
            throw new RefuseError($"{fid}: receiver does not match the candidate source");
        if (asg.Right.ToString() != Str(cand, "handler", "candidate"))
            throw new RefuseError($"{fid}: handler does not match the candidate handler");

        // ...and the identities the extractor derived for the non-symbol ("computed") case
        // must still hold over this text — the one identity check available without a
        // SemanticModel. `stable_symbol` identities are FQNs, already bound by the hash.
        var recv = asg.Left is MemberAccessExpressionSyntax m ? m.Expression : null;
        if (Str(cand, "source_identity_kind", "candidate") == "computed"
            && NormWs(recv is null ? "this" : recv.ToString()) != Str(cand, "source_identity", "candidate"))
            throw new RefuseError($"{fid}: receiver identity does not match the candidate");
        var handlerExpr = NormalizeHandler(asg.Right);
        if (Str(cand, "handler_identity_kind", "candidate") == "computed"
            && NormWs(handlerExpr.ToString()) != Str(cand, "handler_identity", "candidate"))
            throw new RefuseError($"{fid}: handler identity does not match the candidate");

        // 7: the acquire is a statement-form `+=` (an expression-bodied member `=> a += h`
        // is a valid but unsupported form in this slice), in the exact candidate type.
        if (asg.Parent is not ExpressionStatementSyntax)
            throw new RefuseError($"{fid}: not a statement-form `+=` (expression-bodied unsupported here)");
        if (SyntacticTypeFqn(asg) != Str(cand, "containing_type", "candidate"))
            throw new RefuseError($"{fid}: containing type does not match the candidate");

        // The edit: `target(receiver, handler)` built from the VALIDATED target node and the
        // real receiver / NORMALIZED handler nodes — `new PropertyChangedEventHandler(OnX)`
        // reaches the weak wrapper as `OnX`, the same peel the extractor's identity used.
        // Only the assignment expression is replaced: the trailing `;` and all surrounding
        // trivia stay exactly as they are.
        var comma = SyntaxFactory.Token(SyntaxKind.CommaToken).WithTrailingTrivia(SyntaxFactory.Space);
        return SyntaxFactory.InvocationExpression(targetExpr,
            SyntaxFactory.ArgumentList(SyntaxFactory.SeparatedList(
                new[]
                {
                    SyntaxFactory.Argument(receiverExpr.WithoutTrivia()),
                    SyntaxFactory.Argument(handlerExpr.WithoutTrivia()),
                },
                new[] { comma }))).ToString();
    }

    /// <summary>The extractor's delegate-creation peel: `new H(M)` / `new(M)` -> `M`.</summary>
    static ExpressionSyntax NormalizeHandler(ExpressionSyntax e)
    {
        while (e is BaseObjectCreationExpressionSyntax { ArgumentList.Arguments: { Count: 1 } args })
            e = args[0].Expression;
        return e;
    }

    /// <summary>The extractor's `FixNormWs`.</summary>
    static string NormWs(string s) =>
        string.Join(" ", s.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    /// <summary>The FQN of the type that lexically contains `node`, built from syntax in the
    /// one format the extractor's `FixFqnFormat` prints: namespaces + nested-type path, no
    /// `global::`, and type parameters included (`N.ViewModel&lt;T&gt;`, `, `-separated —
    /// SymbolDisplay's own spelling for a declaration's type parameter list).</summary>
    static string SyntacticTypeFqn(SyntaxNode node)
    {
        var parts = new List<string>();
        for (var n = node.Parent; n is not null; n = n.Parent)
        {
            switch (n)
            {
                case TypeDeclarationSyntax t:
                    parts.Add(t.TypeParameterList is { Parameters.Count: > 0 } tp
                        ? $"{t.Identifier.Text}<{string.Join(", ", tp.Parameters.Select(p => p.Identifier.Text))}>"
                        : t.Identifier.Text);
                    break;
                case BaseNamespaceDeclarationSyntax ns:
                    parts.Add(ns.Name.ToString());
                    break;
            }
        }
        parts.Reverse();
        return string.Join(".", parts);
    }

    /// <summary>The post text must equal the source with EXACTLY the declared edits applied —
    /// no diff tool's context creep, no stray reformat. Rebuild it independently and compare.</summary>
    static bool EditsAreExact(SourceText src, List<TextChange> changes, SourceText post)
    {
        var sb = new StringBuilder();
        var cursor = 0;
        foreach (var ch in changes.OrderBy(c => c.Span.Start))
        {
            sb.Append(src.ToString(TextSpan.FromBounds(cursor, ch.Span.Start)));
            sb.Append(ch.NewText);
            cursor = ch.Span.End;
        }
        sb.Append(src.ToString(TextSpan.FromBounds(cursor, src.Length)));
        return sb.ToString() == post.ToString();
    }

    // ================= transactional publication =================

    /// <summary>Stage the WHOLE bundle in a sibling dir, then publish it with one atomic
    /// rename. A failure at any write leaves no out-dir at all — never a half-published
    /// bundle whose report does not describe its postimage.</summary>
    static void Publish(string outFull, string rel, byte[] postBytes, object report, string rootReal)
    {
        // Re-prove the destination is physically off the source tree, now, against the
        // filesystem as it is at publication — not as it was at argument-parsing time —
        // and only THEN claim the directory we are about to write into.
        var parentPhys = CheckOutParent(Path.GetDirectoryName(outFull)!, outFull, rootReal);
        var staging = ClaimStaging(parentPhys, "--out");
        try
        {
            var postPath = Path.GetFullPath(Path.Combine(staging, "postimage", rel));
            var postRoot = Path.Combine(staging, "postimage");
            if (!SameOrInside(postRoot, postPath))
                throw new RefuseError($"post-image path for '{rel}' escapes the out-dir");
            Directory.CreateDirectory(Path.GetDirectoryName(postPath)!);
            File.WriteAllBytes(postPath, postBytes);
            File.WriteAllText(Path.Combine(staging, "rewriter-report.json"),
                JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }) + "\n",
                new UTF8Encoding(false));
            Directory.Move(staging, outFull);   // atomic: same parent, same volume
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            Discard(staging);
            throw new RefuseError($"cannot publish the artifact bundle: {e.Message}");
        }
        catch (RefuseError)
        {
            Discard(staging);
            throw;
        }
    }

    static void Discard(string staging)
    {
        try
        {
            if (Directory.Exists(staging)) Directory.Delete(staging, recursive: true);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            Console.Error.WriteLine($"owen-rewrite: warning: could not remove staging '{staging}': {e.Message}");
        }
    }
}
