using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using FlaUI.Core;
using FlaUI.Core.AutomationElements;
using FlaUI.UIA3;
using Newtonsoft.Json;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Deterministic leak-harness (Plan.md §4.1): drive the target through a YAML
    /// scenario N times, force a GC + heap snapshot each cycle, and assert that the
    /// retained instance count of each suspect type does NOT grow ~linearly with the
    /// iteration count. Emits a JSON result that audit/runtime/ingest.py converts to
    /// SARIF for the unified report.
    ///
    /// Windows / build-required: needs a running target, procdump (Sysinternals) and
    /// ClrMD. Not part of the Linux CI gate — the ingest bridge is what CI tests.
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            var opts = CliOptions.Parse(args);
            if (opts == null)
            {
                return 2;
            }
            try
            {
                return Run(opts);
            }
            catch (ScenarioException ex)
            {
                // A broken scenario must NOT be reported as a clean pass — exit 2
                // (distinct from clean=0 and leak-found=1) and write no result.
                Console.Error.WriteLine($"leak-harness: scenario failed — {ex.Message}");
                return 2;
            }
        }

        private static int Run(CliOptions opts)
        {
            var scenario = Scenario.Load(opts.ScenarioPath);
            var counter = new HeapCounter(opts.ProcdumpPath, opts.ScratchDir);
            var types = scenario.Suspects.Select(s => s.Type).ToList();

            using var automation = new UIA3Automation();
            var app = Application.Launch(scenario.App);
            try
            {
                var window = app.GetMainWindow(automation, TimeSpan.FromSeconds(30))
                             ?? throw new InvalidOperationException("main window did not appear");

                // Warm-up cycle BEFORE the baseline: the first open/close JITs methods
                // and lazily initialises caches, so taking the baseline after one cycle
                // avoids counting one-time allocations as a leak.
                RunCycle(window, scenario);
                var baseline = Snapshot(counter, app.ProcessId, types);

                for (var i = 0; i < scenario.Iterations; i++)
                {
                    RunCycle(window, scenario);
                }

                var final = Snapshot(counter, app.ProcessId, types);
                var findings = BuildFindings(scenario, baseline, final);
                var result = new Dictionary<string, object>
                {
                    ["tool"] = "leak-harness",
                    ["scenario"] = scenario.Name,
                    ["target"] = opts.Target,
                    ["commit"] = opts.Commit,
                    ["iterations"] = scenario.Iterations,
                    ["findings"] = findings,
                };

                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(opts.OutPath))!);
                File.WriteAllText(opts.OutPath, JsonConvert.SerializeObject(result, Formatting.Indented));

                var leaked = findings.Count(f => (bool)f["leaked"]);
                Console.WriteLine(
                    $"leak-harness: {leaked} leak(s) over {scenario.Iterations} cycles -> {opts.OutPath}");
                return leaked > 0 ? 1 : 0;
            }
            finally
            {
                app.Close();
                app.Dispose();
            }
        }

        /// <summary>
        /// One scenario cycle: replay the declared steps (open the screen, interact,
        /// close it). Determinism comes from the asserts, not the UI timing.
        ///
        /// A step that cannot run — control not found (typo, or the screen has not
        /// loaded yet) or an unknown action — THROWS rather than being silently
        /// skipped. Skipping would baseline/snapshot the wrong screen and report a
        /// clean result: a broken scenario masquerading as "no leak" (Codex review).
        /// </summary>
        private static void RunCycle(Window window, Scenario scenario)
        {
            foreach (var step in scenario.Steps)
            {
                switch (step.Action)
                {
                    case "open":
                    case "click":
                    case "close":
                        var element = window.FindFirstDescendant(cf => cf.ByAutomationId(step.Target))
                            ?? throw new ScenarioException(
                                $"step '{step.Action}' target '{step.Target}' not found");
                        // Invoke() requires the control to support the InvokePattern;
                        // if it does not, FlaUI throws — which fails the scenario too.
                        element.AsButton().Invoke();
                        break;
                    case "wait":
                        Thread.Sleep(step.Ms);
                        break;
                    default:
                        throw new ScenarioException($"unknown step action '{step.Action}'");
                }
            }
        }

        /// <summary>
        /// Request a GC in the target (SematixTrace, diagnostic build) so the dump
        /// reflects only retained objects, then snapshot the heap.
        /// </summary>
        private static Dictionary<string, int> Snapshot(HeapCounter counter, int pid, List<string> types)
        {
            GcRequester.RequestCollect(pid);   // best-effort; no-op if the target has no SematixTrace
            Thread.Sleep(500);                 // let finalizers run before the dump
            return counter.CountLiveInstances(pid, types);
        }

        private static List<Dictionary<string, object>> BuildFindings(
            Scenario scenario, Dictionary<string, int> baseline, Dictionary<string, int> final)
        {
            var findings = new List<Dictionary<string, object>>();
            foreach (var s in scenario.Suspects)
            {
                var b = baseline.TryGetValue(s.Type, out var bv) ? bv : 0;
                var f = final.TryGetValue(s.Type, out var fv) ? fv : 0;
                var growth = (double)(f - b) / Math.Max(1, scenario.Iterations);
                findings.Add(new Dictionary<string, object>
                {
                    ["rule"] = s.Rule,
                    ["type"] = s.Type,
                    ["location"] = s.Location,
                    ["line"] = s.Line,
                    ["baseline"] = b,
                    ["final"] = f,
                    ["growthPerIteration"] = growth,
                    ["threshold"] = scenario.Threshold,
                    ["leaked"] = growth > scenario.Threshold,
                    ["message"] =
                        $"retained instances of {s.Type} grew {b}->{f} over {scenario.Iterations} cycles",
                });
            }
            return findings;
        }
    }

    /// <summary>
    /// A scenario could not be executed (missing control, unknown action). Distinct
    /// from a leak: it means the audit did not actually run, so the result must NOT
    /// be treated as "clean".
    /// </summary>
    internal sealed class ScenarioException : Exception
    {
        public ScenarioException(string message) : base(message)
        {
        }
    }

    /// <summary>Best-effort GC trigger in the target via a SematixTrace named event.</summary>
    internal static class GcRequester
    {
        public static void RequestCollect(int pid)
        {
            var name = $"OwnNet.Sematix.RequestGc.{pid}";
            try
            {
                if (EventWaitHandle.TryOpenExisting(name, out var handle))
                {
                    using (handle)
                    {
                        handle.Set();
                    }
                }
            }
            catch
            {
                // The target has no SematixTrace GC hook (release build) — fall back to
                // the settle delay in Snapshot(). A missing GC request inflates counts
                // uniformly across baseline and final, so the GROWTH signal still holds.
            }
        }
    }

    /// <summary>Command-line options for the harness.</summary>
    internal sealed class CliOptions
    {
        public string ScenarioPath { get; private set; } = "";
        public string OutPath { get; private set; } = "artifacts/own-audit/leak-harness.json";
        public string ProcdumpPath { get; private set; } = "procdump.exe";
        public string ScratchDir { get; private set; } = "artifacts/own-audit/dumps";
        public string Target { get; private set; } = "";
        public string Commit { get; private set; } = "";

        public static CliOptions? Parse(string[] args)
        {
            var o = new CliOptions();
            for (var i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--scenario": o.ScenarioPath = Next(args, ref i); break;
                    case "--out": o.OutPath = Next(args, ref i); break;
                    case "--procdump": o.ProcdumpPath = Next(args, ref i); break;
                    case "--scratch": o.ScratchDir = Next(args, ref i); break;
                    case "--target": o.Target = Next(args, ref i); break;
                    case "--commit": o.Commit = Next(args, ref i); break;
                    default:
                        Console.Error.WriteLine($"LeakHarness: unknown arg {args[i]}");
                        return null;
                }
            }
            if (string.IsNullOrEmpty(o.ScenarioPath))
            {
                Console.Error.WriteLine(
                    "Usage: LeakHarness --scenario <file.yml> [--out json] [--procdump path] "
                    + "[--scratch dir] [--target owner/repo] [--commit sha]");
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
