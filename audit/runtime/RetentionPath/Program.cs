using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.Diagnostics.Runtime;
using Newtonsoft.Json;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Retention paths (Plan.md §4): the half of the runtime arm that HeapCounter leaves
    /// undone. HeapCounter counts instances of named types; this answers the two questions
    /// that actually decide a leak hunt:
    ///
    ///   1. is any of it RETAINED, or is the heap just full of uncollected garbage?
    ///   2. if it is retained — WHO is holding it?
    ///
    /// Emits the `runtime.json` contract (OwnAudit/docs/runtime-contract.md) so
    /// OwnAudit's runtime/correlate.py consumes the output directly: a `confirmed` finding
    /// is a static leak finding whose type also shows up here as retained, and a
    /// `runtime-only` finding — retention with nothing static to explain it — is the
    /// analyzer's blind spot, i.e. a rule request.
    ///
    /// Usage:
    ///   RetentionPath census  --pid N | --dump D  [--out runtime.json] [--top 25]
    ///   RetentionPath roots   --pid N | --dump D  --type TypeName [--sample 200] [--max-hops 40]
    ///
    /// `census` prints the retained SHARE first, on purpose: if only 5% of the heap is
    /// reachable, there is no leak to hunt and the next step is a GC question, not a
    /// reference question.
    ///
    /// `roots` SAMPLES the instances and reports the paths as a ranked histogram, because
    /// "who holds this object" is ill-posed for an object reachable from many roots — there
    /// are as many answers as there are paths, and the shortest is an arbitrary pick. The
    /// question worth asking is "what holds the TYPICAL instance": the retainer that
    /// accounts for 129,900 of 130,000 is the leak, and the three hanging off the stack or a
    /// prototype are noise.
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            if (args.Length == 0) return Usage();
            string verb = args[0].ToLowerInvariant();

            // The classifier boundary, pinned without a heap: the live net8
            // static-event shape (gate A also proves it end-to-end), the
            // negative neighbours, and the honest-refusal case.
            if (verb == "selftest")
                return ClassifierSelfTest() ? 0 : 1;

            int pid = ArgInt(args, "--pid", 0);
            string? dump = Arg(args, "--dump");
            if (pid == 0 && dump == null)
            {
                Console.Error.WriteLine("retention-path: need --pid <n> or --dump <path>");
                return 2;
            }

            try
            {
                using var walker = dump != null
                    ? RetentionWalker.LoadDump(dump)
                    : RetentionWalker.AttachToProcess(pid);

                switch (verb)
                {
                    case "census": return Census(walker, args);
                    case "roots": return Roots(walker, args);
                    default: return Usage();
                }
            }
            catch (Exception ex)
            {
                // A failed read must not read as "clean" — exit 2, distinct from
                // 0 (analysed, nothing retained) and 1 (analysed, retention found).
                Console.Error.WriteLine($"retention-path: {ex.GetType().Name}: {ex.Message}");
                return 2;
            }
        }

        private static int Census(RetentionWalker walker, string[] args)
        {
            var c = walker.Census();
            int top = ArgInt(args, "--top", 25);

            Console.WriteLine($"roots                : {c.Roots,12:N0} objects");
            Console.WriteLine($"on the heap          : {c.HeapObjects,12:N0} objects   {Mb(c.HeapBytes),10:N0} MB");
            Console.WriteLine($"REACHABLE from roots : {c.RetainedObjects,12:N0} objects   {Mb(c.RetainedBytes),10:N0} MB");
            Console.WriteLine($"uncollected garbage  : {c.HeapObjects - c.RetainedObjects,12:N0} objects   {Mb(c.HeapBytes - c.RetainedBytes),10:N0} MB");
            Console.WriteLine();
            Console.WriteLine(c.RetainedShare > 50
                ? $">>> {c.RetainedShare:N1}% of the heap is genuinely RETAINED — something holds it; run `roots`"
                : $">>> only {c.RetainedShare:N1}% of the heap is retained — the rest is garbage the GC has not collected");
            Console.WriteLine();
            Console.WriteLine($"{"type",-62}{"count",14}{"MB",12}");
            foreach (var kv in c.ByType.OrderByDescending(k => k.Value.Bytes).Take(top))
                Console.WriteLine($"{Short(kv.Key),-62}{kv.Value.Count,14:N0}{Mb(kv.Value.Bytes),12:N1}");

            string? outPath = Arg(args, "--out");
            if (outPath != null)
            {
                // The runtime.json contract. `expected` is left at 0 — the collector does not
                // know the budget; the scenario/config does, and correlate.py applies it.
                var retained = c.ByType
                    .OrderByDescending(k => k.Value.Bytes)
                    .Take(top)
                    .Select(kv => new Dictionary<string, object>
                    {
                        ["type"] = kv.Key,
                        ["count"] = kv.Value.Count,
                        ["expected"] = 0,
                        ["bytes"] = kv.Value.Bytes,
                        ["roots"] = new object[0],
                    })
                    .ToList();

                var doc = new Dictionary<string, object>
                {
                    ["schema"] = "own-runtime/1",
                    ["collector"] = CollectorIdentity(args),
                    ["retained"] = retained,
                };
                File.WriteAllText(outPath, JsonConvert.SerializeObject(doc, Formatting.Indented));
                Console.WriteLine();
                Console.WriteLine($"runtime.json written to {outPath}");
            }

            return c.RetainedShare > 50 ? 1 : 0;
        }

        private static int Roots(RetentionWalker walker, string[] args)
        {
            string? type = Arg(args, "--type");
            if (type == null)
            {
                Console.Error.WriteLine("retention-path roots: need --type <TypeName>");
                return 2;
            }
            int sample = ArgInt(args, "--sample", 200);
            int maxHops = ArgInt(args, "--max-hops", 40);

            var report = walker.FindRetainers(type, sample, maxHops);
            if (report.TotalOnHeap == 0)
            {
                Console.WriteLine($"verdict: ABSENT — no instance of {type} is on the heap");
                return 0;
            }
            if (report.SampledRetained == 0)
            {
                // Honest mode split (A3): instances exist but NO retention path was
                // established — never call this a proven leak.
                Console.WriteLine($"verdict: OBSERVED_ONLY — {report.TotalOnHeap:N0} instance(s) of {type} on the " +
                                  $"heap, but none of the {sample:N0}-instance sample is reachable from a GC root " +
                                  "(garbage awaiting collection, not an established retention)");
                return 0;
            }

            Console.WriteLine($"verdict: RETAINED — {report.TypeName}: {report.TotalOnHeap:N0} on the heap, " +
                              $"{report.SampledRetained:N0} of a {sample:N0}-instance sample retained");
            Console.WriteLine();
            Console.WriteLine("RETAINERS, ranked — what holds the TYPICAL instance, not merely one of them:");

            int rank = 0;
            foreach (var r in report.Retainers)
            {
                rank++;
                double share = 100.0 * r.Instances / report.SampledRetained;
                Console.WriteLine();
                Console.WriteLine($"#{rank}  {r.Instances:N0}/{report.SampledRetained:N0} ({share:N1}%) " +
                                  $"— via [{r.ContractKind()}], {r.Path.Count} hops");
                Console.Write(r.Render());
                if (rank >= 5) break;   // the tail is noise; raise --sample for resolution
            }

            Console.WriteLine();
            var dominant = report.Retainers[0];
            double dominantShare = 100.0 * dominant.Instances / report.SampledRetained;
            if (dominantShare >= 50 && dominant.ContractKind() != "stack")
            {
                string member = dominant.Member != null ? "." + dominant.Member : "";
                Console.WriteLine($">>> {dominantShare:N1}% of the retained instances hang off ONE reference: " +
                                  $"{dominant.Holder}{member}  [{dominant.ContractKind()}]");
            }
            else
            {
                Console.WriteLine(">>> no single dominant retainer in this sample — raise --sample, or the type " +
                                  "really is held from many places");
            }

            string? outPath = Arg(args, "--out");
            if (outPath != null)
            {
                var doc = new Dictionary<string, object>
                {
                    ["schema"] = "own-runtime/1",
                    ["verdict"] = "RETAINED",
                    ["collector"] = CollectorIdentity(args),
                    ["retained"] = new object[]
                    {
                        new Dictionary<string, object>
                        {
                            ["type"] = report.TypeName,
                            ["count"] = report.TotalOnHeap,
                            ["expected"] = 0,
                            ["bytes"] = 0,
                            ["roots"] = report.Retainers.Take(5).Select(r => new Dictionary<string, object>
                            {
                                ["kind"] = r.ContractKind(),
                                ["holder"] = r.Holder,
                                ["member"] = r.Member ?? "",
                                ["via"] = r.ContractKind() == "static-event" ? "delegate" : "reference",
                                ["instances"] = r.Instances,
                                ["path"] = r.Path.Select(h => h.ToString()).ToList(),
                            }).ToList(),
                        },
                    },
                };
                File.WriteAllText(outPath, JsonConvert.SerializeObject(doc, Formatting.Indented));
                Console.WriteLine();
                Console.WriteLine($"runtime.json written to {outPath}");
            }

            return 1;   // retention found
        }

        /// <summary>Who read the heap and how — so the artifact is auditable
        /// (A3): the target (pid or dump path), the collector runtime, the OS.
        /// No timestamps: identical heaps must yield identical artifacts.</summary>
        private static Dictionary<string, object> CollectorIdentity(string[] args)
        {
            return new Dictionary<string, object>
            {
                ["tool"] = "retention-path",
                ["mode"] = Arg(args, "--dump") != null ? "dump" : "attach",
                ["target"] = Arg(args, "--dump") ?? Arg(args, "--pid") ?? "?",
                ["runtime"] = Environment.Version.ToString(),
                ["os"] = Environment.OSVersion.ToString(),
            };
        }

        private static double Mb(long bytes) => bytes / 1024.0 / 1024.0;

        private static string Short(string t) =>
            t.Length <= 60 ? t : t.Substring(0, 28) + "…" + t.Substring(t.Length - 30);

        private static string? Arg(string[] args, string name)
        {
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        private static int ArgInt(string[] args, string name, int fallback)
        {
            var v = Arg(args, name);
            return v != null && int.TryParse(v, out int n) ? n : fallback;
        }

        private static bool ClassifierSelfTest()
        {
            var fails = new List<string>();
            void Check(string name, string got, string want)
            {
                if (got != want) fails.Add($"{name}: got '{got}', want '{want}'");
            }

            // 1. THE live net8 static-event path, verbatim from the flagship
            //    bad app (statics live in a pinned object[] on both runtimes).
            var staticEvent = new List<Hop>
            {
                new("Owen.Flagship.AppSettings", null),
                new("System.ComponentModel.PropertyChangedEventHandler", "PropertyChanged"),
                new("System.Object[]", "_invocationList"),
                new("System.ComponentModel.PropertyChangedEventHandler", null),
                new("Owen.Flagship.DocumentView", "_target"),
            };
            Check("net8 static event (PinnedHandle)",
                Retainer.Classify(ClrRootKind.PinnedHandle, staticEvent), "static-event");
            Check("static event through a strong handle stays an event",
                Retainer.Classify(ClrRootKind.StrongHandle, staticEvent), "static-event");

            // 2. Negative neighbour: 'stack'-flavoured NAMES are not evidence —
            //    a type/field merely containing the word must classify by its
            //    root kind, not by string contagion.
            var stackishNames = new List<Hop>
            {
                new("My.App.StackMachine", "stackCache"),
                new("My.App.Node", "next"),
            };
            Check("stack-flavoured names stay a plain handle",
                Retainer.Classify(ClrRootKind.StrongHandle, stackishNames), "gc-handle");

            // 3. Doctrine: a genuine Stack root is 'live right now', never
            //    retention — even when the path has delegate evidence.
            Check("stack root stays stack even via a delegate",
                Retainer.Classify(ClrRootKind.Stack, staticEvent), "stack");
            Check("finalizer root is a stall, not a reference leak",
                Retainer.Classify(ClrRootKind.FinalizerQueue, staticEvent), "finalizer");

            // 4. A pinned root WITHOUT delegate evidence is a static field.
            var plainStatic = new List<Hop>
            {
                new("My.App.Config", null),
                new("My.App.Cache", "_entries"),
            };
            Check("pinned root without a delegate is static-field",
                Retainer.Classify(ClrRootKind.PinnedHandle, plainStatic), "static-field");

            // 5. Honest refusal: an unknown root kind is REPORTED as
            //    unsupported, never silently classified as non-root/handle.
            Check("unknown root kind refuses honestly",
                Retainer.Classify((ClrRootKind)999, plainStatic), "unsupported-root:999");

            foreach (var f in fails)
                Console.Error.WriteLine($"FAIL: classifier {f}");
            if (fails.Count == 0)
                Console.WriteLine("retention-path classifier selftest OK: 7 checks passed");
            return fails.Count == 0;
        }

        private static int Usage()
        {
            Console.Error.WriteLine("usage:");
            Console.Error.WriteLine("  RetentionPath selftest   # classifier fixtures, no target needed");
            Console.Error.WriteLine("  RetentionPath census     --pid <n> | --dump <path> [--out runtime.json] [--top 25]");
            Console.Error.WriteLine("  RetentionPath roots      --pid <n> | --dump <path> --type <TypeName> [--sample 200] [--max-hops 40] [--out runtime.json]");
            Console.Error.WriteLine();
            Console.Error.WriteLine("  census      is there anything retained at all, or is the heap just uncollected garbage?");
            Console.Error.WriteLine("  roots       what holds the TYPICAL instance of a type (sampled, ranked);");
            Console.Error.WriteLine("              verdicts: RETAINED (root path shown) | OBSERVED_ONLY (no path established) | ABSENT");
            return 2;
        }
    }
}
