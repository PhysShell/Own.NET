using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Diagnostics.Runtime;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Snapshots the TARGET process heap and counts live instances of suspect types.
    /// The harness drives the app out-of-process (FlaUI), so the only way to read the
    /// target's managed heap is a full dump (procdump) + ClrMD — dotnet-gcdump /
    /// dotnet-counters do not attach to .NET Framework, only CoreCLR (Plan.md §4).
    /// </summary>
    internal sealed class HeapCounter
    {
        private readonly string _procdump;
        private readonly string _scratch;

        public HeapCounter(string procdumpPath, string scratchDir)
        {
            _procdump = procdumpPath;
            _scratch = scratchDir;
            Directory.CreateDirectory(_scratch);
        }

        /// <summary>
        /// Full-dump the process and return { type -> live instance count } for the
        /// requested types. A full dump captures the heap as the GC last left it, so
        /// request a GC in the target (SematixTrace) before calling this.
        /// </summary>
        public Dictionary<string, int> CountLiveInstances(int pid, IEnumerable<string> types)
        {
            var wanted = new HashSet<string>(types);
            var counts = new Dictionary<string, int>();
            foreach (var t in wanted)
            {
                counts[t] = 0;
            }

            var dump = Path.Combine(_scratch, $"target-{pid}-{Stopwatch.GetTimestamp()}.dmp");
            RunProcdump(pid, dump);
            try
            {
                using var dataTarget = DataTarget.LoadDump(dump);
                var clr = dataTarget.ClrVersions.FirstOrDefault()
                    ?? throw new InvalidOperationException(
                        $"dump for pid {pid} contains no CLR — is the target a managed process?");
                using var runtime = clr.CreateRuntime();
                foreach (var obj in runtime.Heap.EnumerateObjects())
                {
                    var name = obj.Type?.Name;
                    if (name != null && wanted.Contains(name))
                    {
                        counts[name]++;
                    }
                }
            }
            finally
            {
                File.Delete(dump);   // dumps are large; the counts are the artifact, not the dump
            }
            return counts;
        }

        private void RunProcdump(int pid, string dumpPath)
        {
            // -ma = full dump (managed heap included), -accepteula for unattended runs.
            var psi = new ProcessStartInfo(_procdump, $"-accepteula -ma {pid} \"{dumpPath}\"")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using var p = Process.Start(psi)!;
            // Drain both pipes asynchronously BEFORE waiting: if procdump fills a pipe
            // buffer while the harness blocks in WaitForExit(), both deadlock. Bound the
            // wait so a stuck procdump can't hang the harness forever, and check the
            // exit code, not just whether a file appeared.
            var stdout = p.StandardOutput.ReadToEndAsync();
            var stderr = p.StandardError.ReadToEndAsync();
            if (!p.WaitForExit(120_000))
            {
                try { p.Kill(); } catch { /* best effort */ }
                throw new IOException($"procdump timed out (>120s) for pid {pid}");
            }
            Task.WaitAll(stdout, stderr);
            if (p.ExitCode != 0 || !File.Exists(dumpPath))
            {
                throw new IOException(
                    $"procdump failed for pid {pid} (exit {p.ExitCode}): {stderr.Result}");
            }
        }
    }
}
