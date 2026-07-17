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
        var (stagingDir, outFull) = PrepareOutDir(outDir, rootReal);

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

            var span = SpanOf(cand, fid);
            if (span.End > sourceText.Length)
                throw new RefuseError($"{fid}: span is outside the source");
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
        Publish(stagingDir, outFull, relPath, postBytes, report);

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

    /// <summary>The candidate fields this executable relies on, keyed by finding_id, in
    /// bundle order. Every access is checked here so no later step can throw a shape
    /// exception.</summary>
    static List<(string Id, JsonElement El)> ValidateBundleShape(JsonElement bundle)
    {
        var list = new List<(string, JsonElement)>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var cands = Arr(bundle, "candidates", "candidates");
        if (cands.Count == 0)
            throw new RefuseError("candidates: the bundle is empty");
        foreach (var c in cands)
        {
            var ctx = $"candidates[{list.Count}]";
            var fid = Str(c, "finding_id", ctx);
            if (!seen.Add(fid))
                throw new RefuseError($"{ctx}: duplicate finding_id {fid}");
            foreach (var k in new[] { "file", "containing_type", "event", "source", "handler",
                                      "source_identity", "source_identity_kind",
                                      "handler_identity", "handler_identity_kind" })
                Str(c, k, ctx);
            var span = Prop(c, "acquire_span", ctx);
            Int(span, "start", $"{ctx}.acquire_span");
            Int(span, "length", $"{ctx}.acquire_span");
            var actions = Arr(c, "allowed_actions", ctx);
            if (actions.Count == 0 || actions.Any(a => a.ValueKind != JsonValueKind.String))
                throw new RefuseError($"{ctx}: allowed_actions must be a non-empty string array");
            list.Add((fid, c));
        }
        return list;
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

        var cons = Prop(sel, "constraints", "plan.selection");
        ExactKeys(cons, "plan.selection.constraints", "max_types_changed", "max_files_changed",
            "allow_helper_changes", "allow_config_changes", "allow_suppressions");
        if (Int(cons, "max_types_changed", "plan.selection.constraints") != 1
            || Int(cons, "max_files_changed", "plan.selection.constraints") != 1)
            throw new RefuseError("plan.selection.constraints: this slice changes exactly one type in one file");
        foreach (var k in new[] { "allow_helper_changes", "allow_config_changes", "allow_suppressions" })
            if (Prop(cons, k, "plan.selection.constraints").ValueKind != JsonValueKind.False)
                throw new RefuseError($"plan.selection.constraints.{k} must be false");

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

    static string RealPath(string path)
    {
        var full = Path.GetFullPath(path);
        // Resolve symlinks the way the collector's os.path.realpath did, so a link cannot
        // point the "confined" path out of the tree.
        var link = File.Exists(full) ? File.ResolveLinkTarget(full, returnFinalTarget: true)
            : Directory.Exists(full) ? Directory.ResolveLinkTarget(full, returnFinalTarget: true)
            : null;
        return link is null ? full : Path.GetFullPath(link.FullName);
    }

    static string RealDir(string root, string what)
    {
        var real = RealPath(root);
        if (!Directory.Exists(real))
            throw new RefuseError($"{what}: '{root}' is not a directory");
        return real;
    }

    static bool IsInside(string dir, string path) =>
        path.StartsWith(dir.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar,
            StringComparison.Ordinal);

    /// <summary>`rel` must be exactly the canonical root-relative form the collector emits
    /// (`/`-separated, no drive, no `..`, no absolute path), and must resolve to a regular
    /// file inside `rootReal`.</summary>
    static string ConfineToRoot(string rootReal, string rel)
    {
        if (rel.Length == 0 || Path.IsPathRooted(rel) || rel.Contains('\\')
            || rel.StartsWith('/') || rel.Contains("//", StringComparison.Ordinal)
            || rel.Split('/').Any(p => p is "" or "." or ".."))
            throw new RefuseError($"source path '{rel}' is not a canonical root-relative path");
        var abs = RealPath(Path.Combine(rootReal, rel));
        if (!IsInside(rootReal, abs))
            throw new RefuseError($"source path '{rel}' escapes the root");
        if (!File.Exists(abs))
            throw new RefuseError($"source path '{rel}' is not a regular file");
        if (Path.GetRelativePath(rootReal, abs).Replace('\\', '/') != rel)
            throw new RefuseError($"source path '{rel}' is not in canonical form for the root");
        return abs;
    }

    /// <summary>The out-dir must be a fresh directory off the source tree; returns the
    /// staging dir it will be atomically renamed from.</summary>
    static (string Staging, string Out) PrepareOutDir(string outDir, string rootReal)
    {
        var outFull = Path.GetFullPath(outDir);
        if (outFull == rootReal || IsInside(rootReal, outFull))
            throw new RefuseError($"--out '{outDir}' is inside the source root — refusing to write into the tree");
        if (Directory.Exists(outFull) || File.Exists(outFull))
            throw new RefuseError($"--out '{outDir}' already exists — refusing to mix runs");
        var parent = Path.GetDirectoryName(outFull);
        if (parent is null || !Directory.Exists(parent))
            throw new RefuseError($"--out '{outDir}': the parent directory does not exist");
        var staging = Path.Combine(parent, "." + Path.GetFileName(outFull) + ".owen-staging");
        if (Directory.Exists(staging) || File.Exists(staging))
            throw new RefuseError($"staging path '{staging}' already exists — refusing");
        return (staging, outFull);
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

    static TextSpan SpanOf(JsonElement cand, string fid)
    {
        var span = Prop(cand, "acquire_span", $"candidate {fid}");
        return new TextSpan(Int(span, "start", $"candidate {fid}.acquire_span"),
            Int(span, "length", $"candidate {fid}.acquire_span"));
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
    static void Publish(string staging, string outFull, string rel, byte[] postBytes, object report)
    {
        try
        {
            var postPath = Path.GetFullPath(Path.Combine(staging, "postimage", rel));
            var postRoot = Path.Combine(staging, "postimage");
            if (!IsInside(postRoot, postPath))
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
