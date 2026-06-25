using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Diagnostics.Runtime;
using Newtonsoft.Json;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Duplicate-immutable-data detector (Plan.md §2 cat. 11 — the project's "gold").
    /// Walks the TARGET process heap from a full dump (ClrMD) and groups identical
    /// immutable values; a value held by many separate instances is wasted memory that
    /// interning / a flyweight / a reference-by-id would collapse (units, countries,
    /// currencies, repeated reference-table strings).
    ///
    /// This first cut covers STRINGS — the highest-value, most common case. Arbitrary
    /// immutable reference types (field-by-field content equality) are a later
    /// refinement. Emits a JSON result that audit/runtime/ingest.py converts to SARIF
    /// (rule RUNTIME-DUP-IMMUTABLE -> category 11) for the unified report.
    ///
    /// Windows / build-required: needs a full dump (procdump) + ClrMD. Not part of the
    /// Linux CI gate — the ingest bridge is what CI tests.
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            var opts = DupOptions.Parse(args);
            if (opts == null)
            {
                return 2;
            }
            try
            {
                return Run(opts);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"duplicate-detector: failed — {ex.Message}");
                return 2;
            }
        }

        private static int Run(DupOptions opts)
        {
            // Analyze an existing dump, or take one of a live pid (then delete it).
            var ownsDump = opts.DumpPath == null;
            var dump = opts.DumpPath ?? CreateDump(opts);
            var findings = new List<Dictionary<string, object>>();
            try
            {
                using var dataTarget = DataTarget.LoadDump(dump);
                var clr = dataTarget.ClrVersions.FirstOrDefault()
                    ?? throw new InvalidOperationException(
                        "dump contains no CLR — is the target a managed process?");
                using var runtime = clr.CreateRuntime();

                // Group live strings by value: instance count + total bytes per value.
                // Group by the FULL string — the display cap (--max-string-length) must
                // NOT be the grouping key, or distinct long strings that share the first
                // N chars (JSON/XML blobs with a common prefix) collapse into one bogus
                // group with inflated count/wastedBytes (Codex review on #103). Read the
                // whole string for the key, hashing anything longer than the cap so the
                // dictionary never retains large blobs, and keep a short readable sample
                // only for display.
                var groups = new Dictionary<string, (long Count, ulong Bytes, string Sample)>();
                foreach (var obj in runtime.Heap.EnumerateObjects())
                {
                    if (obj.Type == null || !obj.Type.IsString)
                    {
                        continue;
                    }
                    var full = obj.AsString(int.MaxValue);   // actual length, not capped
                    if (string.IsNullOrEmpty(full))
                    {
                        continue;
                    }
                    var key = full!.Length <= opts.MaxStringLength ? full : LongKey(full);
                    if (groups.TryGetValue(key, out var cur))
                    {
                        groups[key] = (cur.Count + 1, cur.Bytes + obj.Size, cur.Sample);
                    }
                    else
                    {
                        groups[key] = (1, obj.Size, Truncate(full, opts.MaxStringLength));
                    }
                }

                foreach (var kv in groups)
                {
                    var count = kv.Value.Count;
                    if (count < 2)
                    {
                        continue;   // a unique value is not duplication
                    }
                    var bytesPer = (long)(kv.Value.Bytes / (ulong)count);
                    var wasted = (count - 1) * bytesPer;   // duplicates beyond one canonical instance
                    var report = wasted >= opts.MinWastedBytes;
                    if (!report && !opts.IncludeBelowThreshold)
                    {
                        continue;
                    }
                    var sample = kv.Value.Sample;
                    findings.Add(new Dictionary<string, object>
                    {
                        ["rule"] = "RUNTIME-DUP-IMMUTABLE",
                        ["type"] = "System.String",
                        ["value"] = Truncate(sample, 80),
                        ["count"] = count,
                        ["bytesPerInstance"] = bytesPer,
                        ["wastedBytes"] = wasted,
                        ["report"] = report,
                        ["message"] = $"{count} duplicate \"{Truncate(sample, 40)}\" strings "
                                      + $"(~{wasted / 1024} KB wasted; intern or use a flyweight)",
                    });
                }
            }
            finally
            {
                if (ownsDump)
                {
                    File.Delete(dump);   // dumps are large; the findings are the artifact
                }
            }

            findings = findings.OrderByDescending(f => (long)f["wastedBytes"]).ToList();
            var result = new Dictionary<string, object>
            {
                ["tool"] = "duplicate-detector",
                ["target"] = opts.Target,
                ["commit"] = opts.Commit,
                ["minWastedBytes"] = opts.MinWastedBytes,
                ["findings"] = findings,
            };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(opts.OutPath))!);
            File.WriteAllText(opts.OutPath, JsonConvert.SerializeObject(result, Formatting.Indented));

            var reported = findings.Count(f => (bool)f["report"]);
            Console.WriteLine(
                $"duplicate-detector: {reported} duplicate group(s) over threshold -> {opts.OutPath}");
            return reported > 0 ? 1 : 0;
        }

        private static string CreateDump(DupOptions opts)
        {
            if (opts.Pid == 0)
            {
                throw new ArgumentException("either --dump or --pid is required");
            }
            Directory.CreateDirectory(opts.ScratchDir);
            var dump = Path.Combine(opts.ScratchDir, $"dup-{opts.Pid}.dmp");
            var psi = new ProcessStartInfo(opts.ProcdumpPath, $"-accepteula -ma {opts.Pid} \"{dump}\"")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using var p = Process.Start(psi)!;
            // Drain pipes before waiting (avoid the full-buffer deadlock); bound the wait.
            var stdout = p.StandardOutput.ReadToEndAsync();
            var stderr = p.StandardError.ReadToEndAsync();
            if (!p.WaitForExit(120_000))
            {
                try { p.Kill(); } catch { /* best effort */ }
                throw new IOException($"procdump timed out (>120s) for pid {opts.Pid}");
            }
            Task.WaitAll(stdout, stderr);
            if (p.ExitCode != 0 || !File.Exists(dump))
            {
                throw new IOException(
                    $"procdump failed for pid {opts.Pid} (exit {p.ExitCode}): {stderr.Result}");
            }
            return dump;
        }

        private static string Truncate(string s, int n) => s.Length <= n ? s : s.Substring(0, n) + "…";

        // For strings longer than the display cap, key on length + a hash of the FULL
        // content so distinct long strings never merge, without retaining the blob.
        private static string LongKey(string s)
        {
            using var sha = SHA256.Create();
            var hash = sha.ComputeHash(Encoding.Unicode.GetBytes(s));
            return "len=" + s.Length + ":" + BitConverter.ToString(hash).Replace("-", "");
        }
    }

    /// <summary>Command-line options for the duplicate detector.</summary>
    internal sealed class DupOptions
    {
        public string? DumpPath { get; private set; }
        public int Pid { get; private set; }
        public string ProcdumpPath { get; private set; } = "procdump.exe";
        public string ScratchDir { get; private set; } = "artifacts/own-audit/dumps";
        public long MinWastedBytes { get; private set; } = 65536;   // 64 KB
        public int MaxStringLength { get; private set; } = 512;
        public bool IncludeBelowThreshold { get; private set; }
        public string OutPath { get; private set; } = "artifacts/own-audit/duplicate-detector.json";
        public string Target { get; private set; } = "";
        public string Commit { get; private set; } = "";

        public static DupOptions? Parse(string[] args)
        {
            var o = new DupOptions();
            for (var i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--dump": o.DumpPath = Next(args, ref i); break;
                    case "--pid": o.Pid = int.Parse(Next(args, ref i)); break;
                    case "--procdump": o.ProcdumpPath = Next(args, ref i); break;
                    case "--scratch": o.ScratchDir = Next(args, ref i); break;
                    case "--min-wasted-bytes": o.MinWastedBytes = long.Parse(Next(args, ref i)); break;
                    case "--max-string-length": o.MaxStringLength = int.Parse(Next(args, ref i)); break;
                    case "--include-below-threshold": o.IncludeBelowThreshold = true; break;
                    case "--out": o.OutPath = Next(args, ref i); break;
                    case "--target": o.Target = Next(args, ref i); break;
                    case "--commit": o.Commit = Next(args, ref i); break;
                    default:
                        Console.Error.WriteLine($"duplicate-detector: unknown arg {args[i]}");
                        return null;
                }
            }
            if (o.DumpPath == null && o.Pid == 0)
            {
                Console.Error.WriteLine(
                    "Usage: DuplicateDetector (--dump <file> | --pid <n> --procdump <path>) "
                    + "[--min-wasted-bytes N] [--out json] [--target owner/repo] [--commit sha]");
                return null;
            }
            return o;
        }

        private static string Next(string[] args, ref int i)
        {
            if (i + 1 >= args.Length)
            {
                throw new ArgumentException($"{args[i]} requires a value");
            }
            return args[++i];
        }
    }
}
