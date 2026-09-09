using System.Security.Cryptography;
using System.Text.Json;

namespace OwnSharp.Cli;

/// <summary>
/// D4 / D4.1 — `--engine compare`: run the reference and the candidate over
/// ONE captured input and compare their public results.
///
/// <para><b>What it is.</b> A launcher production-seam compare mode for
/// Stage-1/2 dogfood and CI. It is <i>not</i> a promised public feature yet,
/// and nothing about it is a fallback: neither engine's answer ever stands in
/// for the other's failure.</para>
///
/// <para><b>Same input, proved.</b> #260's load-bearing rule is that compare
/// evidence is never manufactured from two independent extractions. The
/// extractor runs once; its OwnIR bytes are read once into a single value; and
/// each engine's input file is materialised from that value and then
/// re-hashed and checked against it before any engine starts. "Both read the
/// same path" is an assumption; a recorded digest per engine, equal to the
/// capture's, is a measurement — and it is the measurement that makes "compare
/// fed the engines different bytes and still reported agreement" a control
/// that can actually go red.</para>
///
/// <para><b>D4.1 — the result contract.</b> Agreement exposes the
/// Python/reference result (Python is still default and reference in Stage 1).
/// Engine divergence and compare execution failure BOTH exit <b>5</b> with one
/// actionable stderr diagnostic plus reproduction evidence. Exit 5 is Owen's
/// internal-failure path: a reference-vs-candidate disagreement during an
/// explicit migration compare means Owen cannot honestly emit one answer, and
/// exit 1 is unavailable because in public Owen it already means findings.</para>
///
/// <para><b>Known difference, not a defect.</b> On native Windows the Python
/// reference encodes piped output as cp1252 with CRLF while the Rust candidate
/// emits canonical UTF-8 (#262's Windows A/B/C). Compare will therefore report
/// a real divergence there for non-ASCII output. That is the declared
/// behaviour change being visible, which is the point of measuring bytes.</para>
/// </summary>
internal static class CompareMode
{
    /// <summary>D4.1: divergence and execution failure both take Owen's
    /// public internal-error path.</summary>
    public const int ExitCode = CrashReport.ExitCode;

    /// <summary>Run both engines over one capture and apply D4.1.</summary>
    /// <returns>The public exit code: the reference's own on agreement, else 5.</returns>
    public static async Task<int> RunAsync(
        ResolvedPython python, string cacheRoot, RustCore rust, string factsPath,
        string format, string severity, string[] args, bool failOnFinding)
    {
        // --- capture ONCE -------------------------------------------------
        // One read of the extractor's output, one value, one identity. Every
        // engine input below is derived from THIS array and nothing else.
        //
        // The digest is declared before the read so the failure paths below
        // can record evidence even when there is no capture to hash; "" is
        // "no capture was taken", which is exactly what that evidence says.
        var capturedSha = "";
        byte[] captured;
        try
        {
            captured = await File.ReadAllBytesAsync(factsPath).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Fail(args, rust, null, null,
                $"could not capture the extracted OwnIR: {ex.Message}", childExitCode: null);
        }

        capturedSha = Sha256Hex(captured);

        // --- the zero-document guard --------------------------------------
        // A compare that judged nothing agrees about nothing. #260's rule that
        // a run comparing zero documents FAILS applies here at the launcher's
        // granularity: a document with no analyzable unit gives both engines
        // nothing to disagree about, so a green result from it would be a
        // zero denominator wearing a passing grade.
        if (!HasAnalyzableUnit(captured, out var why))
        {
            return Fail(args, rust, null, null,
                $"the captured OwnIR contains nothing to analyse ({why}) — a compare over " +
                "zero documents proves nothing and is a failure, not an agreement",
                childExitCode: null);
        }

        // --- materialise one input per engine, then PROVE they match -------
        var pythonInput = factsPath + ".compare-python.json";
        var rustInput = factsPath + ".compare-rust.json";
        try
        {
            await File.WriteAllBytesAsync(pythonInput, captured).ConfigureAwait(false);
            await File.WriteAllBytesAsync(rustInput, captured).ConfigureAwait(false);

            var pythonSha = Sha256Hex(await File.ReadAllBytesAsync(pythonInput).ConfigureAwait(false));
            var rustSha = Sha256Hex(await File.ReadAllBytesAsync(rustInput).ConfigureAwait(false));
            if (pythonSha != capturedSha || rustSha != capturedSha)
            {
                return Fail(args, rust, null, null,
                    "the two engine inputs are not byte-identical to the single capture " +
                    $"(capture {capturedSha}, python {pythonSha}, rust {rustSha}) — the " +
                    "same-input invariant failed, so no comparison may be reported",
                    childExitCode: null);
            }

            // --- run both -------------------------------------------------
            EngineOutcome py, rs;
            try
            {
                py = await EngineRunner
                    .RunPythonAsync(python, cacheRoot, pythonInput, format, severity, capture: true)
                    .ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is InvalidOperationException or IOException)
            {
                return Fail(args, rust, null, null,
                    $"the Python reference could not be run: {ex.Message}", childExitCode: null);
            }
            try
            {
                rs = await EngineRunner
                    .RunRustAsync(rust, rustInput, format, severity, capture: true)
                    .ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is InvalidOperationException or IOException)
            {
                return Fail(args, rust, py, null,
                    $"the Rust candidate could not be run: {ex.Message}", childExitCode: null);
            }

            // --- D4.1 (c): execution failure ------------------------------
            // Either engine failing to produce a verdict is an EXECUTION
            // failure, never "the other engine's answer". Checked before
            // divergence: two results are only comparable once both exist.
            var pyLegal = EngineSelection.IsLegalEngineExit(py.Rc);
            var rsLegal = EngineSelection.IsLegalEngineExit(rs.Rc);
            if (!pyLegal || !rsLegal)
            {
                // The raw Rust child status is retained per D5 whenever the
                // Rust side is the one that misbehaved.
                int? childExit = rsLegal ? null : rs.Rc;
                var offender = !pyLegal && !rsLegal
                    ? $"both engines failed (python exit {py.Rc}, rust exit {rs.Rc})"
                    : !pyLegal
                        ? $"the Python reference failed (exit {py.Rc})"
                        : $"the Rust candidate failed (exit {rs.Rc})";
                return Fail(args, rust, py, rs,
                    $"compare execution failure — {offender}. No engine's result was " +
                    "substituted for the other's failure.",
                    childExit);
            }

            // --- D4.1 (a)/(b): agreement or divergence --------------------
            var sameOut = py.Stdout.AsSpan().SequenceEqual(rs.Stdout);
            var sameErr = py.Stderr.AsSpan().SequenceEqual(rs.Stderr);
            var sameRc = py.Rc == rs.Rc;
            if (!sameOut || !sameErr || !sameRc)
            {
                var what = string.Join(", ", new[]
                {
                    sameRc ? null : $"exit ({py.Rc} vs {rs.Rc})",
                    sameOut ? null : $"stdout ({py.Stdout.Length} vs {rs.Stdout.Length} bytes)",
                    sameErr ? null : $"stderr ({py.Stderr.Length} vs {rs.Stderr.Length} bytes)",
                }.Where(x => x is not null));
                return Fail(args, rust, py, rs,
                    $"engine divergence — the reference and the candidate disagree on {what}. " +
                    "Neither verdict is exposed as authoritative: Owen cannot honestly emit " +
                    "one answer when its reference and its candidate disagree.",
                    childExitCode: null);
            }

            // --- agreement: the externally observed result is the reference's
            // Stage 1 keeps Python as default AND reference, so on agreement
            // the user sees exactly what a `--engine python` run would have
            // produced — byte for byte, replayed undecoded.
            await ReplayAsync(py).ConfigureAwait(false);
            WriteEvidence(args, rust, capturedSha, py, rs, verdict: "agreement",
                diagnostic: null, childExitCode: null);
            return failOnFinding ? py.Rc : (py.Rc >= 2 ? py.Rc : 0);
        }
        finally
        {
            TryDelete(pythonInput);
            TryDelete(rustInput);
        }

        int Fail(string[] a, RustCore core, EngineOutcome? py, EngineOutcome? rs,
            string diagnostic, int? childExitCode)
        {
            Console.Error.WriteLine($"owen: --engine compare: {diagnostic}");
            // The reproduction line is on STDERR, not only inside the evidence
            // file: the two identities that make a compare reproducible are the
            // input bytes and the candidate binary, and a reader who has to
            // open a JSON file to learn them has been handed a filename rather
            // than a reproduction. own-check.sh prints the same two facts, so
            // the surfaces say one thing (D2).
            Console.Error.WriteLine(
                $"  Reproduction — input sha256 {(capturedSha.Length > 0 ? capturedSha : "(no capture)")}, " +
                $"candidate {core.Path} (sha256 {core.Sha256})");
            var path = WriteEvidence(a, core, capturedSha, py, rs,
                verdict: childExitCode is null && py is not null && rs is not null
                    ? "divergence"
                    : "execution-failure",
                diagnostic: diagnostic, childExitCode: childExitCode);
            if (path is not null)
            {
                Console.Error.WriteLine($"  Reproduction evidence: {path}");
            }
            return ExitCode;
        }
    }

    /// <summary>Replay the reference's captured streams to the real ones,
    /// undecoded — what the user would have seen without the compare.</summary>
    private static async Task ReplayAsync(EngineOutcome reference)
    {
        if (reference.Stdout.Length > 0)
        {
            await using var stdout = Console.OpenStandardOutput();
            await stdout.WriteAsync(reference.Stdout).ConfigureAwait(false);
            await stdout.FlushAsync().ConfigureAwait(false);
        }
        if (reference.Stderr.Length > 0)
        {
            await using var stderr = Console.OpenStandardError();
            await stderr.WriteAsync(reference.Stderr).ConfigureAwait(false);
            await stderr.FlushAsync().ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Does this OwnIR document carry anything an engine could analyse?
    ///
    /// <para>The schema requires only <c>ownir_version</c> and <c>module</c>;
    /// everything analysable lives in the optional collections. All of them
    /// empty or absent means there is no case to compare.</para>
    /// </summary>
    private static bool HasAnalyzableUnit(byte[] ownir, out string why)
    {
        if (ownir.Length == 0)
        {
            why = "the capture is empty";
            return false;
        }
        string[] collections =
            ["components", "functions", "services", "effects", "protocols", "protocol_functions"];
        try
        {
            using var doc = JsonDocument.Parse(ownir);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                why = "the capture is not an OwnIR object";
                return false;
            }
            foreach (var name in collections)
            {
                if (doc.RootElement.TryGetProperty(name, out var value)
                    && value.ValueKind == JsonValueKind.Array
                    && value.GetArrayLength() > 0)
                {
                    why = "";
                    return true;
                }
            }
            why = "every OwnIR collection is empty or absent";
            return false;
        }
        catch (JsonException ex)
        {
            // Not our call to make: a document the strict door should refuse
            // is a legitimate compare case (both engines must refuse it the
            // same way), so an unparseable capture is NOT treated as
            // zero-document here. Let both engines answer it.
            why = "";
            _ = ex;
            return true;
        }
    }

    /// <summary>One reproducible compare artifact per run, overwritten in
    /// place. It records what ran, over which bytes, with which candidate
    /// identity, and what each engine answered — enough to re-run the exact
    /// comparison by hand. No source contents, like the crash report.</summary>
    private static string? WriteEvidence(
        string[] args, RustCore rust, string capturedSha,
        EngineOutcome? py, EngineOutcome? rs, string verdict,
        string? diagnostic, int? childExitCode)
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".owen", "compare");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "last-compare.json");
            var report = new
            {
                schema = 1,
                tool = "owen",
                version = ToolVersion.Current,
                timestamp_utc = DateTime.UtcNow.ToString("o"),
                mode = "compare",
                verdict,
                diagnostic,
                args,
                // The same-input attestation: one capture, and the digest both
                // engine inputs were verified against before either started.
                input = new { sha256 = capturedSha },
                // D3: the candidate's recorded identity, so a stale binary
                // cannot stand in without the evidence changing.
                rust_core = new { path = rust.Path, sha256 = rust.Sha256, bytes = rust.ByteLength },
                python = py is null ? null : new
                {
                    exit = py.Rc,
                    stdout_sha256 = Sha256Hex(py.Stdout),
                    stderr_sha256 = Sha256Hex(py.Stderr),
                    stdout_bytes = py.Stdout.Length,
                    stderr_bytes = py.Stderr.Length,
                },
                rust = rs is null ? null : new
                {
                    exit = rs.Rc,
                    stdout_sha256 = Sha256Hex(rs.Stdout),
                    stderr_sha256 = Sha256Hex(rs.Stderr),
                    stdout_bytes = rs.Stdout.Length,
                    stderr_bytes = rs.Stderr.Length,
                },
                // D5: the raw Rust child status, retained whenever the Rust
                // child produced one outside the legal set.
                child_exit_code = childExitCode,
            };
            File.WriteAllText(path, JsonSerializer.Serialize(
                report, new JsonSerializerOptions { WriteIndented = true }));
            return path;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static string Sha256Hex(byte[] data) =>
        Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { /* best-effort cleanup */ }
    }
}
