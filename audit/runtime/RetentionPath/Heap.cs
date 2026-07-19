using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Microsoft.Diagnostics.Runtime;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Mark-from-roots over a target's managed heap, and the root -> object paths for a
    /// suspect type.
    ///
    /// WHY THIS IS NOT HeapCounter. <see cref="HeapCounter"/> answers "how many instances
    /// of T are on the heap". That is a different question from "how many are RETAINED",
    /// because <c>ClrHeap.EnumerateObjects()</c> walks the heap segments linearly and
    /// returns everything allocated — including garbage the GC has not collected yet. A
    /// big heap is not evidence of a leak. HeapCounter mitigates this by forcing a GC in
    /// the target first (SematixTrace), which works when you can drive the target; this
    /// type does not need to, because marking from the roots answers the question:
    ///
    ///   reachable ≈ heap   -> genuinely retained; something holds it
    ///   reachable &lt;&lt; heap  -> not a leak; the GC simply has not collected yet
    ///
    /// WHY IT SAMPLES. "Who holds this object" is ill-posed for an object reachable from
    /// many roots — there are as many answers as there are paths, and the shortest one is
    /// an arbitrary pick, not an explanation. Ask instead: **what holds the typical
    /// instance?** So the walk takes a SAMPLE of the retained instances, computes each
    /// one's shortest path in a single BFS, and reports the paths as a HISTOGRAM. The
    /// retainer that accounts for 129,900 of 130,000 instances is the leak; the three that
    /// hang off the stack or a prototype are noise, and reading one of them as "the answer"
    /// is how a leak hunt goes wrong.
    ///
    /// The principled version of this is a dominator tree (which single reference, if cut,
    /// frees the object — and how much memory that frees). See the README.
    /// </summary>
    internal sealed class RetentionWalker : IDisposable
    {
        private readonly DataTarget _target;
        private readonly ClrRuntime _runtime;

        /// <summary>Attach to a LIVE process (suspends it for the read). No procdump needed.</summary>
        public static RetentionWalker AttachToProcess(int pid) =>
            new RetentionWalker(DataTarget.AttachToProcess(pid, suspend: true));

        /// <summary>Read a full dump — the right choice when the target must not be paused.</summary>
        public static RetentionWalker LoadDump(string path) =>
            new RetentionWalker(DataTarget.LoadDump(path));

        private RetentionWalker(DataTarget target)
        {
            _target = target;
            var clr = _target.ClrVersions.FirstOrDefault()
                ?? throw new InvalidOperationException(
                    "the target contains no CLR — is it a managed process / a full (-ma) dump?");
            _runtime = clr.CreateRuntime();
        }

        private ClrHeap Heap => _runtime.Heap;

        /// <summary>
        /// One mark pass. Returns the retained set (by type) alongside the raw heap totals,
        /// so the caller can state the retained SHARE rather than a bare object count.
        /// </summary>
        public HeapCensus Census()
        {
            long heapObjects = 0, heapBytes = 0;
            foreach (var o in Heap.EnumerateObjects())
            {
                if (!o.IsValid || o.Type == null) continue;
                heapObjects++;
                heapBytes += (long)o.Size;
            }

            var seen = new HashSet<ulong>();
            var stack = new Stack<ulong>();
            foreach (var root in Heap.EnumerateRoots())
            {
                var o = root.Object;
                if (o.IsValid && seen.Add(o.Address)) stack.Push(o.Address);
            }
            int rootCount = seen.Count;

            var byType = new Dictionary<string, TypeTally>();
            long liveObjects = 0, liveBytes = 0;
            while (stack.Count > 0)
            {
                var obj = Heap.GetObject(stack.Pop());
                if (!obj.IsValid || obj.Type == null) continue;

                liveObjects++;
                long size = (long)obj.Size;
                liveBytes += size;

                string name = obj.Type.Name ?? "<unknown>";
                if (!byType.TryGetValue(name, out var tally)) tally = new TypeTally();
                tally.Count++;
                tally.Bytes += size;
                byType[name] = tally;

                foreach (var child in obj.EnumerateReferences())
                    if (child.IsValid && seen.Add(child.Address)) stack.Push(child.Address);
            }

            return new HeapCensus(rootCount, heapObjects, heapBytes, liveObjects, liveBytes, byType);
        }

        /// <summary>
        /// Sample up to <paramref name="sample"/> retained instances of <paramref name="typeName"/>,
        /// compute every one's shortest root path in a SINGLE breadth-first pass (BFS from the whole
        /// root set gives each node its shortest path for free), then group the paths by shape.
        ///
        /// The result is ranked: the shape that retains the most instances comes first. That is the
        /// answer to "what is holding all of this", as opposed to "here is a path to one of them".
        /// </summary>
        public RetentionReport FindRetainers(string typeName, int sample, int maxHops)
        {
            // ---- 1. the targets ---------------------------------------------------------
            // Match the TYPE, not the type's spelling. A naive substring match on the type name
            // matches `System.Func<BrokerDataClasses.GTDGoody, System.Boolean>` when you asked for
            // `GTDGoody` — a cached lambda whose *generic argument* happens to mention it — and then
            // confidently reports a path to the wrong object. A tool that points at the wrong culprit
            // is worse than no tool.
            var targets = new Dictionary<ulong, string>();
            long totalOfType = 0;
            foreach (var o in Heap.EnumerateObjects())
            {
                if (!o.IsValid || o.Type?.Name == null) continue;
                if (!IsType(o.Type.Name, typeName)) continue;
                totalOfType++;
                if (targets.Count < sample) targets[o.Address] = o.Type.Name;
            }
            if (targets.Count == 0)
                return new RetentionReport(typeName, 0, 0, new List<Retainer>());

            // ---- 2. one BFS from every root; parent pointers only (no strings) ------------
            // Storing a label per node would cost hundreds of MB on a 4M-object heap. Store the
            // parent address, and resolve type/field names later, for the sampled paths only.
            var parent = new Dictionary<ulong, ulong>();      // child -> parent (0 = root)
            var rootKind = new Dictionary<ulong, ClrRootKind>();
            var queue = new Queue<ulong>();

            foreach (var root in Heap.EnumerateRoots())
            {
                var o = root.Object;
                if (!o.IsValid || parent.ContainsKey(o.Address)) continue;
                parent[o.Address] = 0;
                rootKind[o.Address] = root.RootKind;
                queue.Enqueue(o.Address);
            }

            int reachedTargets = 0;
            while (queue.Count > 0 && reachedTargets < targets.Count)
            {
                ulong addr = queue.Dequeue();
                if (targets.ContainsKey(addr)) reachedTargets++;

                var obj = Heap.GetObject(addr);
                if (!obj.IsValid || obj.Type == null) continue;

                foreach (var child in obj.EnumerateReferences())
                {
                    if (!child.IsValid || parent.ContainsKey(child.Address)) continue;
                    parent[child.Address] = addr;
                    queue.Enqueue(child.Address);
                }
            }

            // ---- 3. unwind each sampled target, and group the paths by shape --------------
            var groups = new Dictionary<string, Retainer>();
            long retainedSampled = 0;
            foreach (var kv in targets)
            {
                if (!parent.ContainsKey(kv.Key)) continue;   // not reachable — genuinely garbage
                retainedSampled++;

                var hops = Unwind(kv.Key, parent, rootKind, maxHops, out ClrRootKind kind);
                string signature = string.Join(" -> ", hops.Select(h => h.Type));

                if (!groups.TryGetValue(signature, out var retainer))
                {
                    retainer = new Retainer(hops, kind);
                    groups[signature] = retainer;
                }
                retainer.Instances++;
            }

            var ranked = groups.Values.OrderByDescending(r => r.Instances).ToList();
            return new RetentionReport(targets.Values.First(), totalOfType, retainedSampled, ranked);
        }

        /// <summary>
        /// Walk the parent chain back to a root, naming the field traversed at every hop. The field
        /// name is what turns "this object is alive" into "THIS FIELD is holding it" — the sentence a
        /// developer can act on — so it is resolved here (by re-reading the parent's references),
        /// rather than carried through the BFS at the cost of hundreds of megabytes.
        /// </summary>
        private List<Hop> Unwind(ulong target, Dictionary<ulong, ulong> parent,
                                 Dictionary<ulong, ClrRootKind> rootKind, int maxHops,
                                 out ClrRootKind kind)
        {
            var chain = new List<ulong>();
            ulong cur = target;
            while (true)
            {
                chain.Add(cur);
                if (!parent.TryGetValue(cur, out ulong p) || p == 0) break;
                cur = p;
                if (chain.Count > maxHops) break;
            }
            kind = rootKind.TryGetValue(cur, out var k) ? k : ClrRootKind.None;
            chain.Reverse();

            var hops = new List<Hop>(chain.Count);
            for (int i = 0; i < chain.Count; i++)
            {
                var obj = Heap.GetObject(chain[i]);
                string type = obj.Type?.Name ?? "?";
                string? field = null;
                if (i > 0)
                {
                    var owner = Heap.GetObject(chain[i - 1]);
                    if (owner.IsValid && owner.Type != null)
                    {
                        foreach (var r in owner.EnumerateReferencesWithFields())
                        {
                            if (r.Object.Address != chain[i]) continue;
                            field = r.Field?.Name;
                            break;
                        }
                    }
                }
                hops.Add(new Hop(type, field));
            }
            return hops;
        }

        /// <summary>
        /// Does <paramref name="heapType"/> name the type the caller asked for? Compares the SIMPLE
        /// name with generic arguments stripped, so `GTDGoody` matches `BrokerDataClasses.GTDGoody`
        /// but NOT `System.Func&lt;BrokerDataClasses.GTDGoody, System.Boolean&gt;`. A fully-qualified
        /// request (`BrokerDataClasses.GTDGoody`) is matched exactly.
        /// </summary>
        internal static bool IsType(string heapType, string wanted)
        {
            if (string.Equals(heapType, wanted, StringComparison.Ordinal)) return true;

            int lt = heapType.IndexOf('<');                         // Func<A,B> -> Func
            string bare = lt >= 0 ? heapType.Substring(0, lt) : heapType;
            if (string.Equals(bare, wanted, StringComparison.Ordinal)) return true;

            int dot = bare.LastIndexOf('.');                        // Ns.GTDGoody -> GTDGoody
            string simple = dot >= 0 ? bare.Substring(dot + 1) : bare;
            return string.Equals(simple, wanted, StringComparison.Ordinal);
        }

        /// <summary>
        /// The dominator tree of the whole live graph, with retained sizes. This is the well-posed
        /// version of "who holds it": not a path, but the one reference whose removal frees the object.
        /// </summary>
        public DominatorTree Dominate() => DominatorTree.Build(Heap);

        public void Dispose()
        {
            _runtime.Dispose();
            _target.Dispose();
        }
    }

    internal struct TypeTally
    {
        public long Count;
        public long Bytes;
    }

    internal sealed class Hop
    {
        public readonly string Type;
        public readonly string? Field;

        public Hop(string type, string? field)
        {
            Type = type;
            Field = field;
        }

        public override string ToString() =>
            Field == null ? Type : Type + "  (." + Field + ")";
    }

    /// <summary>One distinct retention shape, and how many of the sampled instances it holds.</summary>
    internal sealed class Retainer
    {
        public readonly IReadOnlyList<Hop> Path;
        public readonly ClrRootKind RootKind;
        public long Instances;

        public Retainer(IReadOnlyList<Hop> path, ClrRootKind rootKind)
        {
            Path = path;
            RootKind = rootKind;
        }

        /// <summary>
        /// Map a ClrMD root kind onto the `runtime.json` kinds (OwnAudit/docs/runtime-contract.md:
        /// static-field, static-event, gc-handle, thread-local, timer).
        ///
        /// Note there is no `StaticVar` root kind: on .NET Framework a class's statics live in a
        /// pinned `System.Object[]` handed to the runtime as a **PinnedHandle**, which is why a
        /// static-field leak surfaces as `[PinnedHandle] System.Object[] -> …`. A **delegate hop**
        /// further down the path is what makes it a static *event* rather than a plain static field —
        /// the distinction correlate.py's `high` tier keys on.
        ///
        /// `Stack` and `FinalizerQueue` are reported as themselves, deliberately: an object rooted
        /// only by the stack is merely *live right now*, not retained, and reading it as a leak is how
        /// a leak hunt goes wrong.
        /// </summary>
        public string ContractKind()
        {
            bool viaDelegate = Path.Any(h =>
                h.Type.IndexOf("EventHandler", StringComparison.Ordinal) >= 0 ||
                h.Type.IndexOf("MulticastDelegate", StringComparison.Ordinal) >= 0 ||
                (h.Field != null && h.Field.IndexOf("invocationList", StringComparison.OrdinalIgnoreCase) >= 0));

            switch (RootKind)
            {
                case ClrRootKind.Stack:
                    return "stack";            // live in a frame right now — not retention
                case ClrRootKind.FinalizerQueue:
                    return "finalizer";        // awaiting finalization — a stall, not a reference leak
                case ClrRootKind.PinnedHandle:
                    return viaDelegate ? "static-event" : "static-field";
                default:
                    return viaDelegate ? "static-event" : "gc-handle";
            }
        }

        /// <summary>The object one hop above the target — the thing actually holding the reference.</summary>
        public string Holder => Path.Count >= 2 ? Path[Path.Count - 2].Type : Path[0].Type;

        /// <summary>The field on that object, when the reference came from a named field.</summary>
        public string? Member => Path.Count >= 1 ? Path[Path.Count - 1].Field : null;

        public string Render()
        {
            var sb = new StringBuilder();
            for (int i = 0; i < Path.Count; i++)
                sb.Append("    ").Append(Path[i]).Append(Environment.NewLine);
            return sb.ToString();
        }
    }

    internal sealed class RetentionReport
    {
        public readonly string TypeName;
        public readonly long TotalOnHeap;
        public readonly long SampledRetained;
        public readonly IReadOnlyList<Retainer> Retainers;

        public RetentionReport(string typeName, long totalOnHeap, long sampledRetained,
                               IReadOnlyList<Retainer> retainers)
        {
            TypeName = typeName;
            TotalOnHeap = totalOnHeap;
            SampledRetained = sampledRetained;
            Retainers = retainers;
        }
    }

    internal sealed class HeapCensus
    {
        public readonly int Roots;
        public readonly long HeapObjects;
        public readonly long HeapBytes;
        public readonly long RetainedObjects;
        public readonly long RetainedBytes;
        public readonly IReadOnlyDictionary<string, TypeTally> ByType;

        public HeapCensus(int roots, long heapObjects, long heapBytes,
                          long retainedObjects, long retainedBytes,
                          IReadOnlyDictionary<string, TypeTally> byType)
        {
            Roots = roots;
            HeapObjects = heapObjects;
            HeapBytes = heapBytes;
            RetainedObjects = retainedObjects;
            RetainedBytes = retainedBytes;
            ByType = byType;
        }

        /// <summary>The number that decides whether this is a leak hunt at all.</summary>
        public double RetainedShare => HeapBytes == 0 ? 0 : 100.0 * RetainedBytes / HeapBytes;
    }
}
