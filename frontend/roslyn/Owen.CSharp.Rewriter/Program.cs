// owen-rewrite — S2 deterministic subscription rewriter (steps 4-7).
//
//   owen-rewrite --plan <validated-plan.json> --candidates <candidates.json>
//                --root <source-root> --out <artifact-dir>
//
// Reads the hash-bound (validated-plan, candidates) pair (the Python `own-fix
// subscriptions apply` gate has already validated + bound them), RE-checks the pristine
// source SHA against the exact bytes it parses (closing the TOCTOU the gate cannot),
// runs the syntactic span-node identity guard for every convert_acquire decision, and —
// only if EVERY guard passes — writes an edited postimage + a rewriter-report.json under
// <out>. Any ambiguity is a hard refusal of the whole operation (exit 2, nothing written);
// there is never a partial apply and the source tree is never touched.
//
// Syntax-only by design: the acquire is matched to its hash-bound candidate by normalized
// text (receiver / handler / event name / containing-type FQN), so no SemanticModel is
// needed. The INotifyPropertyChanged contract + the convert_acquire permission were proven
// in S0 and are carried in the hash-bound candidate.

using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

static int Refuse(string reason)
{
    Console.Error.WriteLine($"owen-rewrite: refuse: {reason}");
    return 2;
}

static string NormWs(string s) =>
    string.Join(" ", s.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

static string Sha256Hex(byte[] bytes) =>
    "sha256:" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

// --- args ---
string? planPath = null, candPath = null, root = null, outDir = null;
for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--plan" when i + 1 < args.Length: planPath = args[++i]; break;
        case "--candidates" when i + 1 < args.Length: candPath = args[++i]; break;
        case "--root" when i + 1 < args.Length: root = args[++i]; break;
        case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
        default:
            return Refuse($"unknown or incomplete argument '{args[i]}'");
    }
}
if (planPath is null || candPath is null || root is null || outDir is null)
    return Refuse("--plan, --candidates, --root and --out are all required");

JsonElement plan, cands;
try
{
    plan = JsonDocument.Parse(File.ReadAllBytes(planPath)).RootElement;
    cands = JsonDocument.Parse(File.ReadAllBytes(candPath)).RootElement;
}
catch (Exception e) when (e is IOException or JsonException)
{
    return Refuse($"cannot read inputs: {e.Message}");
}

// Candidate identity context, keyed by finding_id.
var candById = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
foreach (var c in cands.GetProperty("candidates").EnumerateArray())
    candById[c.GetProperty("finding_id").GetString()!] = c;

var targetSubscribe = plan.GetProperty("target_api").GetProperty("subscribe").GetString()!;
var sourceFile = plan.GetProperty("source_files")[0];
var relPath = sourceFile.GetProperty("path").GetString()!;
var expectedSha = sourceFile.GetProperty("sha256").GetString()!;

// --- source: read ONCE, hash + parse the SAME bytes (no TOCTOU) ---
var absPath = Path.GetFullPath(Path.Combine(root, relPath));
byte[] sourceBytes;
try
{
    sourceBytes = File.ReadAllBytes(absPath);
}
catch (Exception e) when (e is IOException or UnauthorizedAccessException)
{
    return Refuse($"cannot read source '{relPath}': {e.Message}");
}
if (Sha256Hex(sourceBytes) != expectedSha)
    return Refuse($"STALE SOURCE / PREIMAGE MISMATCH for {relPath}");

// Decode exactly as the extractor did (File.ReadAllText: BOM-detecting UTF-8), from the
// SAME bytes we hashed, so the acquire_span offsets align and there is no TOCTOU.
string decoded;
Encoding encoding;
using (var reader = new StreamReader(new MemoryStream(sourceBytes), Encoding.UTF8,
           detectEncodingFromByteOrderMarks: true))
{
    decoded = reader.ReadToEnd();
    encoding = reader.CurrentEncoding;
}
if (encoding.CodePage != Encoding.UTF8.CodePage)
    return Refuse($"unsupported source encoding '{encoding.WebName}' (only UTF-8 in this slice)");
var hadBom = sourceBytes.Length >= 3 && sourceBytes[0] == 0xEF
    && sourceBytes[1] == 0xBB && sourceBytes[2] == 0xBF;

var sourceText = SourceText.From(decoded);
var tree = CSharpSyntaxTree.ParseText(sourceText);
var rootNode = tree.GetRoot();

// --- gather + guard every convert_acquire edit; compute ALL before applying ANY ---
var edits = new List<TextChange>();
var appliedFindings = new List<string>();
var manualFindings = new List<string>();
var seenSpans = new List<TextSpan>();

foreach (var d in plan.GetProperty("decisions").EnumerateArray())
{
    var fid = d.GetProperty("finding_id").GetString()!;
    var action = d.GetProperty("action").GetString()!;
    if (action == "manual_review") { manualFindings.Add(fid); continue; }
    if (action != "convert_acquire")
        return Refuse($"{fid}: out-of-scope action '{action}'");

    if (!candById.TryGetValue(fid, out var cand))
        return Refuse($"{fid}: not a candidate");

    var spanEl = d.GetProperty("acquire_span");
    var span = new TextSpan(spanEl.GetProperty("start").GetInt32(), spanEl.GetProperty("length").GetInt32());
    if (span.End > sourceText.Length)
        return Refuse($"{fid}: span is outside the source");
    foreach (var s in seenSpans)
        if (span.OverlapsWith(s))
            return Refuse($"{fid}: overlapping convert_acquire spans");
    seenSpans.Add(span);

    // 1-2: the span is exactly one `X += Y` AddAssignment.
    var node = rootNode.FindNode(span, getInnermostNodeForTie: true);
    if (node is not AssignmentExpressionSyntax asg
        || asg.Span != span
        || !asg.IsKind(SyntaxKind.AddAssignmentExpression))
        return Refuse($"{fid}: span is not an event `+=` acquire");

    // No comment / directive trivia inside the replaced expression (can't move it safely).
    foreach (var t in asg.DescendantTrivia())
        if (t.IsKind(SyntaxKind.SingleLineCommentTrivia) || t.IsKind(SyntaxKind.MultiLineCommentTrivia)
            || t.IsDirective)
            return Refuse($"{fid}: comment/directive inside the acquire — refusing to move it");

    // 3-4: LHS is `receiver.EventName` (or a bare `EventName` on implicit this).
    string receiverText, eventName;
    if (asg.Left is MemberAccessExpressionSyntax lhs)
    {
        receiverText = lhs.Expression.ToString();
        eventName = lhs.Name.Identifier.Text;
    }
    else if (asg.Left is IdentifierNameSyntax bare)
    {
        receiverText = "this";
        eventName = bare.Identifier.Text;
    }
    else
    {
        return Refuse($"{fid}: LHS is not an event member access");
    }
    if (eventName != cand.GetProperty("event").GetString())
        return Refuse($"{fid}: event name does not match the candidate");
    // 5-6: receiver + handler text must match the hash-bound candidate.
    if (NormWs(receiverText) != NormWs(cand.GetProperty("source").GetString()!))
        return Refuse($"{fid}: receiver does not match the candidate source");
    var handlerText = asg.Right.ToString();
    if (NormWs(handlerText) != NormWs(cand.GetProperty("handler").GetString()!))
        return Refuse($"{fid}: handler does not match the candidate handler");

    // 7: the acquire is a statement-form `+=` (an expression-bodied member `=> a += h`
    // is a valid but unsupported form in this slice), in the exact candidate type.
    if (asg.Parent is not ExpressionStatementSyntax)
        return Refuse($"{fid}: not a statement-form `+=` (expression-bodied unsupported here)");
    var typeFqn = SyntacticTypeFqn(asg);
    if (typeFqn != cand.GetProperty("containing_type").GetString())
        return Refuse($"{fid}: containing type does not match the candidate");

    // The edit: replace the assignment expression (the trailing `;` and all trivia stay).
    edits.Add(new TextChange(span, $"{targetSubscribe}({receiverText}, {handlerText})"));
    appliedFindings.Add(fid);
}

if (edits.Count == 0 && appliedFindings.Count == 0 && manualFindings.Count == 0)
    return Refuse("the plan has no decisions");

// --- apply (all-or-nothing) + write the postimage + report ---
var postText = sourceText.WithChanges(edits);
// Preserve the original UTF-8 BOM presence + the file's own line endings (only the
// declared spans changed, so newlines outside them are untouched).
var body = new UTF8Encoding(false).GetBytes(postText.ToString());
var postBytes = hadBom ? new byte[] { 0xEF, 0xBB, 0xBF }.Concat(body).ToArray() : body;

// Diff guard: only the declared spans changed. WithChanges guarantees it; verify the
// unchanged remainder byte-for-byte by re-deriving the expected post text from the edits.
if (!EditsAreExact(sourceText, edits, postText))
    return Refuse("post-image differs from the source outside the declared edits");

string outPost = Path.Combine(outDir, "postimage", relPath);
try
{
    Directory.CreateDirectory(Path.GetDirectoryName(outPost)!);
    File.WriteAllBytes(outPost, postBytes);

    var report = new
    {
        version = 1,
        operation = "apply-subscription-fixes",
        input_bundle_sha256 = plan.GetProperty("input_bundle_sha256").GetString(),
        validated_plan_sha256 = Sha256Hex(File.ReadAllBytes(planPath)),
        target_api = new { subscribe = targetSubscribe },
        source_files = new[]
        {
            new { path = relPath, pre_sha256 = expectedSha, post_sha256 = Sha256Hex(postBytes) },
        },
        applied_findings = appliedFindings.OrderBy(x => x, StringComparer.Ordinal).ToArray(),
        manual_review_findings = manualFindings.OrderBy(x => x, StringComparer.Ordinal).ToArray(),
    };
    File.WriteAllText(Path.Combine(outDir, "rewriter-report.json"),
        JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }) + "\n");
}
catch (Exception e) when (e is IOException or UnauthorizedAccessException)
{
    return Refuse($"cannot write output: {e.Message}");
}

Console.WriteLine($"owen-rewrite: applied {appliedFindings.Count} convert_acquire, "
    + $"{manualFindings.Count} manual_review -> {outDir}");
return 0;

// Fully-qualified name of the type that lexically contains `node`, built from syntax
// (namespaces + nested type identifiers). Matches the extractor's non-generic FQN.
static string SyntacticTypeFqn(SyntaxNode node)
{
    var parts = new List<string>();
    for (var n = node.Parent; n is not null; n = n.Parent)
    {
        switch (n)
        {
            case TypeDeclarationSyntax t: parts.Add(t.Identifier.Text); break;
            case NamespaceDeclarationSyntax ns: parts.Add(ns.Name.ToString()); break;
            case FileScopedNamespaceDeclarationSyntax fns: parts.Add(fns.Name.ToString()); break;
        }
    }
    parts.Reverse();
    return string.Join(".", parts);
}

// The post text must equal the source with EXACTLY the declared edits applied — no diff
// tool's context creep, no stray reformat. Rebuild it independently and compare.
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
