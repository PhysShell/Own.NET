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
            if (args.Length == 0) return Usage(args, "no verb given");
            string verb = args[0].ToLowerInvariant();

            // The classifier boundary, pinned without a heap: the live net8
            // static-event shape (gate A also proves it end-to-end), the
            // negative neighbours, and the honest-refusal case.
            if (verb == "selftest")
                return ClassifierSelfTest() ? 0 : 1;

            if (verb != "census" && verb != "roots")
                return Usage(args, $"unknown verb '{verb}'");

            int pid = ArgInt(args, "--pid", 0);
            string? dump = Arg(args, "--dump");
            if (pid == 0 && dump == null)
            {
                Console.Error.WriteLine("retention-path: need --pid <n> or --dump <path>");
                return NotEvaluated(args, "usage-error", "neither --pid nor --dump was given");
            }

            // WHERE the failure happened decides what it means, so the stages are
            // tracked separately instead of being collapsed into one "did we get
            // in" flag. Opening the target is the only step a ptrace policy can
            // refuse; building the CLR view happens after the target is already
            // open, so its failures say nothing about permission; and a failure
            // during the walk is the witness breaking, not the target refusing.
            // One bool cannot carry that, and when it tried, a CLR-initialisation
            // failure on a live process under a restricting Yama policy came back
            // labelled `refused-attach`.
            DataTarget? target = null;
            var stage = Stage.OpenTarget;
            try
            {
                target = dump != null
                    ? RetentionWalker.OpenDumpTarget(dump)
                    : RetentionWalker.OpenLiveTarget(pid);

                stage = Stage.CreateRuntime;
                using var walker = RetentionWalker.Create(target);
                target = null;              // the walker owns it from here
                stage = Stage.Walk;

                switch (verb)
                {
                    case "census": return Census(walker, args);
                    default: return Roots(walker, args);
                }
            }
            catch (Exception ex)
            {
                // A failed read must not read as "clean" — exit 2, distinct from
                // 0 (analysed, nothing retained) and 1 (analysed, retention found).
                Console.Error.WriteLine($"retention-path: {ex.GetType().Name}: {ex.Message}");

                // Only the stage a policy could have refused gets the ptrace
                // lecture. Printing it after the target opened would have stderr
                // blaming the kernel while the record blames the walk — the two
                // reading one observation is the whole point of sharing YamaScope.
                if (stage == Stage.OpenTarget)
                {
                    foreach (var line in AttachAdvice(pid, live: dump == null))
                        Console.Error.WriteLine(line);
                }

                return stage == Stage.Walk
                    ? Failed(args, ex)
                    : NotEvaluated(args, ReadFailure(stage, pid, live: dump == null, ex));
            }
            finally
            {
                // Non-null only when ownership never reached the walker.
                target?.Dispose();
            }
        }

        /// <summary>The stage a run reached, because the same exception means
        /// different things at each one.</summary>
        private enum Stage
        {
            /// <summary>Opening the process or dump — refusable by a ptrace policy.</summary>
            OpenTarget,
            /// <summary>Building the CLR view over an already-open target.</summary>
            CreateRuntime,
            /// <summary>Reading the heap.</summary>
            Walk,
        }

        /// <summary>
        /// Why the heap could not be read, said no more strongly than the
        /// evidence allows.
        ///
        /// `refused-attach` is a claim about PERMISSION, so it is reserved for a
        /// failure at the one stage a permission check applies to, with a
        /// restricting policy actually in force. Even then the policy is recorded
        /// as <c>policy_in_force</c>, not as the proven cause: a live process
        /// under `ptrace_scope=1` can fail to open for reasons that have nothing
        /// to do with Yama, and this collector cannot tell those apart. Naming
        /// what was in force is observation; naming it as the refuser would be
        /// the same unearned confidence the execution record exists to prevent.
        ///
        /// Everything else — including a target that opened and then turned out
        /// not to be a readable CLR process — gets the weaker, true
        /// `unreadable-target`, with the exception in `detail`.
        /// </summary>
        private static Dictionary<string, object> ReadFailure(
            Stage stage, int pid, bool live, Exception ex)
        {
            string? policy = stage == Stage.OpenTarget ? RefusingPolicy(pid, live) : null;
            var reason = new Dictionary<string, object>
            {
                ["code"] = policy != null ? "refused-attach" : "unreadable-target",
                ["stage"] = stage == Stage.OpenTarget ? "open-target" : "create-runtime",
                ["detail"] = $"{ex.GetType().Name}: {ex.Message}",
            };
            if (policy != null) reason["policy_in_force"] = policy;
            return reason;
        }

        /// <summary>
        /// Turn a bare ClrMD exception into something a person can act on when
        /// the kernel — not the tool — refused the attach. On Linux, Yama's
        /// ptrace_scope decides whether one process may trace another; the
        /// default on most distributions and on CI runners forbids attaching to
        /// a process that is not a descendant, and the resulting exception says
        /// nothing about why.
        ///
        /// Deliberately narrow: advice only when this really could be the cause
        /// — a LIVE attach, on Linux, where the target exists (a missing pid is
        /// a different failure and deserves no lecture about ptrace) and Yama
        /// is actually restricting. Otherwise the exception stands alone.
        /// </summary>
        private static IEnumerable<string> AttachAdvice(int pid, bool live)
        {
            string? scope = YamaScope(pid, live);
            if (scope == null) yield break;

            yield return "  the target is alive and the open was refused, so a PERMISSION failure";
            yield return $"  is the likely cause: the kernel's Yama policy is restricting";
            yield return $"  (/proc/sys/kernel/yama/ptrace_scope = {scope}). That policy being in";
            yield return "  force is what Owen can see; it cannot prove this open is what it stopped.";
            yield return "  Owen did not look — this is NOT a verdict about the target's heap.";

            // Each mode restricts something different, and the remedies do not
            // carry over: telling a scope-3 user to relaunch the target as a
            // descendant would be confident, actionable, and wrong.
            switch (scope)
            {
                case "1":
                    yield return "  Mode 1: only a DESCENDANT of the tracer may be attached to. Options:";
                    yield return "    * take a dump and read that instead:  retention-path roots --dump <file> …";
                    yield return "    * start the target FROM the witness, so it is a descendant;";
                    yield return "    * have the target opt in: prctl(PR_SET_PTRACER, <witness pid>);";
                    yield return "    * or relax the policy deliberately and temporarily:";
                    yield return "        sudo sysctl -w kernel.yama.ptrace_scope=0";
                    break;
                case "2":
                    yield return "  Mode 2: attaching requires CAP_SYS_PTRACE — descendant or not, and";
                    yield return "  PR_SET_PTRACER does not help here. Options:";
                    yield return "    * take a dump and read that instead:  retention-path roots --dump <file> …";
                    yield return "    * run the witness with CAP_SYS_PTRACE (e.g. under sudo);";
                    yield return "    * or relax the policy deliberately and temporarily:";
                    yield return "        sudo sysctl -w kernel.yama.ptrace_scope=0";
                    break;
                case "3":
                    yield return "  Mode 3: attaching is disabled outright and CANNOT be re-enabled at";
                    yield return "  runtime — the value is locked until reboot, so no sysctl, capability,";
                    yield return "  or opt-in will help on this boot. Options:";
                    yield return "    * take a dump and read that instead:  retention-path roots --dump <file> …";
                    yield return "    * or change the policy in config and reboot.";
                    break;
                default:
                    yield return $"  Mode {scope} is not one this build knows (0-3 are documented). Options:";
                    yield return "    * take a dump and read that instead:  retention-path roots --dump <file> …";
                    yield return "    * or consult your kernel's Yama documentation for this value.";
                    break;
            }
        }

        /// <summary>The one place that decides whether a restricting policy was
        /// OBSERVED: a live attach, on Linux, to a process that still exists,
        /// under a Yama policy that is not permissive. Returns the scope value,
        /// or null when there is no such policy to name.
        ///
        /// This proves the policy was IN FORCE, not that it caused the failure
        /// in hand — the kernel does not tell the tracer which check rejected
        /// it. Both the human advice and the durable record read this one
        /// function, and both are worded to that limit, so stderr and the
        /// artifact cannot end up holding two opinions about one event.</summary>
        private static string? YamaScope(int pid, bool live)
        {
            if (!live || !OperatingSystem.IsLinux()) return null;

            try { using var _ = System.Diagnostics.Process.GetProcessById(pid); }
            catch { return null; }        // no such process: not a permission story

            string scope;
            try { scope = File.ReadAllText("/proc/sys/kernel/yama/ptrace_scope").Trim(); }
            catch { return null; }        // no Yama on this kernel
            return scope == "0" ? null : scope;
        }

        /// <summary>The restricting policy in force, named as the record names
        /// it, or null when there is none to name.</summary>
        private static string? RefusingPolicy(int pid, bool live)
        {
            string? scope = YamaScope(pid, live);
            return scope == null ? null : $"kernel.yama.ptrace_scope={scope}";
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

            // Same exit-code tiers as `roots`, so the same execution states:
            // a majority-retained heap is something OBSERVED and worth a `roots`
            // run; anything less is a clean look, not a silent one.
            bool present = c.RetainedShare > 50;
            var scope = new Dictionary<string, object>
            {
                ["verb"] = "census",
                ["mode"] = Arg(args, "--dump") != null ? "dump" : "attach",
                ["roots_enumerated"] = c.Roots,
                ["objects_on_heap"] = c.HeapObjects,
                ["objects_reachable"] = c.RetainedObjects,
                ["bytes_on_heap"] = c.HeapBytes,
                ["bytes_reachable"] = c.RetainedBytes,
                ["retained_share_pct"] = Math.Round(c.RetainedShare, 1),
                ["types_on_heap"] = c.ByType.Count,
                ["types_reported"] = retained.Count,
                ["top_budget"] = top,
            };
            WriteRecord(args, BuildRecord(
                CollectorIdentity(args), Evaluated(present, scope), retained: retained));

            return present ? 1 : 0;
        }

        private static int Roots(RetentionWalker walker, string[] args)
        {
            string? type = Arg(args, "--type");
            if (type == null)
            {
                Console.Error.WriteLine("retention-path roots: need --type <TypeName>");
                return NotEvaluated(args, "usage-error", "roots requires --type <TypeName>");
            }
            // Display budgets only — clamped to at least 1 so a pathological
            // `--sample 0` cannot suppress the root path a RETAINED verdict
            // must ship with. Neither flag can alter the verdict (the census
            // in FindRetainers is exact over the whole population).
            int sample = Math.Max(1, ArgInt(args, "--sample", 200));
            int maxHops = Math.Max(1, ArgInt(args, "--max-hops", 40));

            var report = walker.FindRetainers(type, sample, maxHops);
            var scope = RootsScope(args, type, report, sample, maxHops);
            if (report.TotalOnHeap == 0)
            {
                Console.WriteLine($"verdict: ABSENT — no instance of {type} is on the heap");
                WriteArtifact(args, "ABSENT", type, 0, scope, new List<Retainer>());
                return 0;
            }
            if (report.Retained == 0)
            {
                // Honest mode split (A3): instances exist but NO retention path was
                // established — never call this a proven leak.
                Console.WriteLine($"verdict: OBSERVED_ONLY — {report.TotalOnHeap:N0} instance(s) of {type} on the " +
                                  "heap, but none of them is reachable from a GC root " +
                                  "(garbage awaiting collection, not an established retention)");
                WriteArtifact(args, "OBSERVED_ONLY", type, report.TotalOnHeap, scope,
                              new List<Retainer>());
                return 0;
            }

            // The verdict CONSULTS the classification (the ok-variant of the
            // flagship demo pinned this): a path from a transient root (stack
            // frame, finalizer queue) proves the object is live RIGHT NOW,
            // not that anything retains it — a loop local still in a register
            // is not a leak. RETAINED requires at least one durable retainer;
            // an unknown root kind counts as durable on purpose (fail-closed
            // toward visibility: unknown evidence must surface loudly, never
            // quietly demote the verdict). The census behind DurableRetained
            // covers EVERY reachable instance, so the verdict cannot change
            // with the --sample display budget.
            if (report.DurableRetained == 0)
            {
                Console.WriteLine($"verdict: OBSERVED_ONLY — {report.TypeName}: {report.TotalOnHeap:N0} on the " +
                                  $"heap, {report.Retained:N0} reachable, " +
                                  "but ONLY from transient roots (stack/finalizer) — live right now, not durable " +
                                  "retention");
                foreach (var r in report.Retainers.Take(3))
                {
                    Console.WriteLine();
                    Console.WriteLine($"    via [{r.ContractKind()}], {r.Path.Count} hops:");
                    Console.Write(r.Render());
                }
                WriteArtifact(args, "OBSERVED_ONLY", type, report.TotalOnHeap, scope,
                              report.Retainers);
                return 0;
            }

            Console.WriteLine($"verdict: RETAINED — {report.TypeName}: {report.TotalOnHeap:N0} on the heap, " +
                              $"{report.Retained:N0} reachable, {report.DurableRetained:N0} durably retained " +
                              $"({report.PathsResolved:N0} path(s) resolved for display)");
            Console.WriteLine();
            Console.WriteLine("RETAINERS, ranked — what holds the TYPICAL instance, not merely one of them:");

            int rank = 0;
            foreach (var r in report.Retainers)
            {
                rank++;
                // Shares are shares OF THE RESOLVED PATHS — the display sample —
                // never of the full population the verdict was computed over.
                double share = 100.0 * r.Instances / report.PathsResolved;
                Console.WriteLine();
                Console.WriteLine($"#{rank}  {r.Instances:N0}/{report.PathsResolved:N0} resolved ({share:N1}%) " +
                                  $"— via [{r.ContractKind()}], {r.Path.Count} hops");
                Console.Write(r.Render());
                if (rank >= 5) break;   // the tail is noise; raise --sample for resolution
            }

            Console.WriteLine();
            var dominant = report.Retainers[0];
            double dominantShare = 100.0 * dominant.Instances / report.PathsResolved;
            if (dominantShare >= 50 && dominant.ContractKind() != "stack")
            {
                string member = dominant.Member != null ? "." + dominant.Member : "";
                Console.WriteLine($">>> {dominantShare:N1}% of the resolved paths hang off ONE reference: " +
                                  $"{dominant.Holder}{member}  [{dominant.ContractKind()}]");
            }
            else
            {
                Console.WriteLine(">>> no single dominant retainer in this sample — raise --sample, or the type " +
                                  "really is held from many places");
            }

            WriteArtifact(args, "RETAINED", report.TypeName, report.TotalOnHeap, scope,
                          report.Retainers);

            return 1;   // retention found
        }

        /// <summary>The verdict rule, pure over classification kinds (the
        /// selftest pins it): RETAINED requires at least one DURABLE
        /// retainer. Transient kinds (stack frame, finalizer queue) prove
        /// 'live right now', never retention; an `unsupported-root:*` kind
        /// counts as durable on purpose — unknown evidence surfaces loudly,
        /// never quietly demotes the verdict.</summary>
        internal static bool IsDurableKind(string kind) =>
            kind != "stack" && kind != "finalizer";

        internal static string VerdictOf(IEnumerable<string> retainerKinds) =>
            retainerKinds.Any(IsDurableKind) ? "RETAINED" : "OBSERVED_ONLY";

        /// <summary>The one `runtime.json` writer — every outcome emits the
        /// artifact when `--out` is given, so the ok-side of a demo is as
        /// machine-checkable as the leak side, and a run that never looked is as
        /// machine-checkable as one that did.
        ///
        /// The exit codes already keep three states apart (0 evaluated/absent,
        /// 1 evaluated/present, 2 not evaluated) and then the process ends. If
        /// storage represents "not evaluated" by writing nothing, that guarantee
        /// does not survive it: an absent file also means never invoked, runner
        /// died, persistence failed, artifact lost in transit, or a format
        /// nothing reads any more. Absence has too many preimages to carry
        /// meaning, so it is given none — the record IS the state.
        ///
        /// What must NOT come back is a verdict that was not earned: a
        /// `not_evaluated` or `error` record carries no `verdict` and no
        /// `retained` key at all. An empty `retained: []` would read downstream
        /// as "looked, found nothing", which is the very collapse this record
        /// exists to prevent.</summary>
        private static void WriteRecord(string[] args, Dictionary<string, object> doc)
        {
            string? outPath = Arg(args, "--out");
            if (outPath == null) return;
            File.WriteAllText(outPath, JsonConvert.SerializeObject(doc, Formatting.Indented));
            Console.WriteLine();
            Console.WriteLine($"runtime.json written to {outPath}");
        }

        /// <summary>Assemble the document. Pure, so the selftest can assert the
        /// record contract without a heap, a process, or a filesystem.</summary>
        internal static Dictionary<string, object> BuildRecord(
            Dictionary<string, object> collector,
            Dictionary<string, object> execution,
            string? verdict = null,
            object? retained = null)
        {
            var doc = new Dictionary<string, object>
            {
                ["schema"] = "own-runtime/1",
                ["execution"] = execution,
                ["collector"] = collector,
            };
            // Only an evaluated state may carry a measurement.
            if (verdict != null) doc["verdict"] = verdict;
            if (retained != null) doc["retained"] = retained;
            return doc;
        }

        /// <summary>The execution state of an evaluation that HAPPENED. `scope`
        /// is required, not decorative: a `clean` whose scope is unknown is a
        /// malformed record — it does not say what was looked at, so it cannot
        /// mean "nothing was there" — and consumers must treat it as a schema
        /// violation rather than as a quieter `not_evaluated`.</summary>
        internal static Dictionary<string, object> Evaluated(
            bool witnessPresent, Dictionary<string, object> scope) =>
            new Dictionary<string, object>
            {
                ["state"] = witnessPresent ? "observed" : "clean",
                ["scope"] = scope,
            };

        /// <summary>Record "I did not look, and here is why", then exit 2.</summary>
        private static int NotEvaluated(string[] args, string code, string detail) =>
            NotEvaluated(args, new Dictionary<string, object>
            {
                ["code"] = code,
                ["detail"] = detail,
            });

        private static int NotEvaluated(string[] args, Dictionary<string, object> reason)
        {
            WriteRecord(args, BuildRecord(
                CollectorIdentity(args),
                new Dictionary<string, object>
                {
                    ["state"] = "not_evaluated",
                    ["reason"] = reason,
                }));
            return 2;
        }

        /// <summary>Record "I looked and broke", then exit 2. Distinct from
        /// `not_evaluated` on purpose: the heap was readable, so a partial walk
        /// may have happened and the target is not exonerated by this outcome.
        /// The classification is the exception type — the honest granularity a
        /// collector has, rather than a guess at a cause.</summary>
        private static int Failed(string[] args, Exception ex)
        {
            WriteRecord(args, BuildRecord(
                CollectorIdentity(args),
                new Dictionary<string, object>
                {
                    ["state"] = "error",
                    ["error"] = new Dictionary<string, object>
                    {
                        ["classification"] = ex.GetType().Name,
                        ["detail"] = ex.Message,
                        ["stage"] = "walk",
                    },
                }));
            return 2;
        }

        private static void WriteArtifact(
            string[] args, string verdict, string typeName, long count,
            Dictionary<string, object> scope, IReadOnlyList<Retainer> retainers)
        {
            var doc = BuildRecord(
                CollectorIdentity(args),
                Evaluated(witnessPresent: verdict == "RETAINED", scope: scope),
                verdict,
                new object[]
                {
                    new Dictionary<string, object>
                    {
                        ["type"] = typeName,
                        ["count"] = count,
                        ["expected"] = 0,
                        ["bytes"] = 0,
                        ["roots"] = retainers.Take(5).Select(r => new Dictionary<string, object>
                        {
                            ["kind"] = r.ContractKind(),
                            ["holder"] = r.Holder,
                            ["member"] = r.Member ?? "",
                            ["via"] = r.ContractKind() == "static-event" ? "delegate" : "reference",
                            ["instances"] = r.Instances,
                            ["path"] = r.Path.Select(h => h.ToString()).ToList(),
                        }).ToList(),
                    },
                });
            WriteRecord(args, doc);
        }

        /// <summary>What the `roots` walk actually covered. Population figures
        /// come from the exact whole-population census, and the budgets that
        /// bounded only the DISPLAY are named as budgets — a reader must be able
        /// to tell a number that constrained the verdict from one that did not.</summary>
        private static Dictionary<string, object> RootsScope(
            string[] args, string typeName, RetentionReport report, int sample, int maxHops) =>
            new Dictionary<string, object>
            {
                ["verb"] = "roots",
                ["mode"] = Arg(args, "--dump") != null ? "dump" : "attach",
                ["type"] = typeName,
                ["instances_on_heap"] = report.TotalOnHeap,
                ["instances_reachable"] = report.Retained,
                ["instances_durably_retained"] = report.DurableRetained,
                ["paths_resolved"] = report.PathsResolved,
                ["sample_budget"] = sample,
                ["max_hops_budget"] = maxHops,
            };

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

            // The verdict rule (deterministic here; the live ok-demo only has
            // to prove the absence of a false RETAINED — JIT liveness of a
            // loop local is not a public contract to test against).
            Check("stack-only reachability is OBSERVED_ONLY",
                VerdictOf(new[] { "stack" }), "OBSERVED_ONLY");
            Check("finalizer-only reachability is OBSERVED_ONLY",
                VerdictOf(new[] { "finalizer", "stack" }), "OBSERVED_ONLY");
            Check("one durable retainer makes it RETAINED",
                VerdictOf(new[] { "stack", "static-event" }), "RETAINED");
            Check("unknown evidence surfaces as RETAINED, never demotes",
                VerdictOf(new[] { "unsupported-root:999" }), "RETAINED");

            // 6. The doctrine lives at TWO layers — the ClrMD-level split
            //    (BFS phase seeding + the whole-population census) and the
            //    string-level verdict rule — and they must never disagree:
            //    a kind the census calls transient must classify to a kind
            //    the verdict calls non-durable, and vice versa.
            foreach (var kind in new[] { ClrRootKind.Stack, ClrRootKind.FinalizerQueue,
                                         ClrRootKind.PinnedHandle, ClrRootKind.StrongHandle,
                                         (ClrRootKind)999 })
            {
                bool transient = Retainer.IsTransientRootKind(kind);
                bool durable = IsDurableKind(Retainer.Classify(kind, plainStatic));
                if (transient == durable)
                    fails.Add($"census/verdict split disagrees for {kind}: " +
                              $"IsTransientRootKind={transient}, IsDurableKind(Classify)={durable}");
            }

            // 7. The record contract (issue #331). The exit codes keep three
            //    states apart and then the process ends; these checks pin that
            //    the storage layer keeps them apart too, instead of letting
            //    file-absence stand in for "not evaluated" — an absence that
            //    also means never invoked, runner died, or artifact lost.
            var collector = new Dictionary<string, object> { ["tool"] = "retention-path" };
            var someScope = new Dictionary<string, object> { ["verb"] = "roots" };

            void CheckRecord(string name, Dictionary<string, object> doc,
                             string wantState, bool wantMeasurement)
            {
                if (!doc.TryGetValue("execution", out var exObj) ||
                    exObj is not Dictionary<string, object> ex)
                {
                    fails.Add($"{name}: record has no `execution` block");
                    return;
                }
                Check($"{name}: state", ex.TryGetValue("state", out var s) ? $"{s}" : "<missing>", wantState);

                // Each state owes its own evidence. A state with nothing behind
                // it is a label, and a label is what this record replaces.
                string owes = wantState switch
                {
                    "observed" or "clean" => "scope",
                    "not_evaluated" => "reason",
                    _ => "error",
                };
                if (!ex.ContainsKey(owes))
                    fails.Add($"{name}: state '{wantState}' must carry `{owes}`");

                // The half that must NOT come back: an unearned verdict, or an
                // empty `retained` that reads downstream as "looked, found
                // nothing". Absence of the key is the point.
                bool hasMeasurement = doc.ContainsKey("verdict") || doc.ContainsKey("retained");
                if (hasMeasurement != wantMeasurement)
                    fails.Add($"{name}: measurement keys present={hasMeasurement}, want {wantMeasurement}");
            }

            CheckRecord("observed record",
                BuildRecord(collector, Evaluated(true, someScope), "RETAINED", new object[0]),
                "observed", wantMeasurement: true);
            CheckRecord("clean record",
                BuildRecord(collector, Evaluated(false, someScope), "ABSENT", new object[0]),
                "clean", wantMeasurement: true);
            CheckRecord("not_evaluated record",
                BuildRecord(collector, new Dictionary<string, object>
                {
                    ["state"] = "not_evaluated",
                    ["reason"] = new Dictionary<string, object> { ["code"] = "refused-attach" },
                }),
                "not_evaluated", wantMeasurement: false);
            CheckRecord("error record",
                BuildRecord(collector, new Dictionary<string, object>
                {
                    ["state"] = "error",
                    ["error"] = new Dictionary<string, object> { ["classification"] = "IOException" },
                }),
                "error", wantMeasurement: false);

            // The state names follow the exit-code tiers, so a consumer can map
            // one onto the other without a second opinion about what happened.
            Check("witness present is `observed`",
                $"{Evaluated(true, someScope)["state"]}", "observed");
            Check("witness absent but evaluated is `clean`",
                $"{Evaluated(false, someScope)["state"]}", "clean");

            // 8. Stage attribution. A permission claim belongs to the one stage a
            //    permission check applies to. The first cut of this arc gated on
            //    "did we get a walker", which put every CLR-initialisation
            //    failure — a target that opened fine and then turned out not to
            //    be a managed process — under `refused-attach` whenever Yama
            //    happened to be restricting.
            var boom = new InvalidOperationException("the target contains no CLR");
            var afterOpen = ReadFailure(Stage.CreateRuntime, pid: 1, live: true, ex: boom);
            Check("a failure after the target opened is never a permission claim",
                $"{afterOpen["code"]}", "unreadable-target");
            Check("and it says which stage it fell over at",
                $"{afterOpen["stage"]}", "create-runtime");
            if (afterOpen.ContainsKey("policy_in_force"))
                fails.Add("create-runtime failure must not cite a ptrace policy");

            // A dump has no process to trace, so no policy can be in force for
            // it — the same call must stay silent about permission there too.
            var dumpFail = ReadFailure(Stage.OpenTarget, pid: 0, live: false, ex: boom);
            Check("an unreadable dump is not a refusal",
                $"{dumpFail["code"]}", "unreadable-target");
            if (dumpFail.ContainsKey("policy_in_force"))
                fails.Add("a dump read must not cite a ptrace policy");

            foreach (var f in fails)
                Console.Error.WriteLine($"FAIL: classifier {f}");
            if (fails.Count == 0)
                Console.WriteLine("retention-path selftest OK: classifier, verdict and record contracts hold");
            return fails.Count == 0;
        }

        private static int Usage(string[] args, string detail)
        {
            Console.Error.WriteLine("usage:");
            Console.Error.WriteLine("  RetentionPath selftest   # classifier fixtures, no target needed");
            Console.Error.WriteLine("  RetentionPath census     --pid <n> | --dump <path> [--out runtime.json] [--top 25]");
            Console.Error.WriteLine("  RetentionPath roots      --pid <n> | --dump <path> --type <TypeName> [--sample 200] [--max-hops 40] [--out runtime.json]");
            Console.Error.WriteLine();
            Console.Error.WriteLine("  census      is there anything retained at all, or is the heap just uncollected garbage?");
            Console.Error.WriteLine("  roots       what holds the TYPICAL instance of a type (exact verdict; sampled, ranked paths);");
            Console.Error.WriteLine("              verdicts: RETAINED (root path shown) | OBSERVED_ONLY (no path established) | ABSENT");
            Console.Error.WriteLine();
            Console.Error.WriteLine("  --out       write the runtime.json record. EVERY outcome writes one, including");
            Console.Error.WriteLine("              a run that never looked: execution.state is observed | clean |");
            Console.Error.WriteLine("              not_evaluated | error, and only an evaluated state carries a verdict.");
            return NotEvaluated(args, "usage-error", detail);
        }
    }
}
