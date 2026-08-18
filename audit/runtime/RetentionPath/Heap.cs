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
    /// frees the object — and how much memory that frees). It is NOT implemented here: the
    /// A3 witness was extracted from PR #280 without it, deliberately. See
    /// `audit/runtime/README.md` § "Retention paths" for what the sampled histogram does and
    /// does not answer, and Own.NET#334 for what the dominator implementation argued.
    /// </summary>
    internal sealed class RetentionWalker : IDisposable
    {
        private readonly DataTarget _target;
        private readonly ClrRuntime _runtime;

        /// <summary>Attach to a LIVE process (suspends it for the read). No procdump needed.
        ///
        /// Opening the target is deliberately its OWN step, separate from
        /// <see cref="Create"/>: it is the only one a kernel ptrace policy can
        /// refuse. Folding the two together makes every CLR-initialisation
        /// failure indistinguishable from a permission failure, and a caller
        /// that cannot tell them apart will attribute one to the other.</summary>
        public static DataTarget OpenLiveTarget(int pid) =>
            DataTarget.AttachToProcess(pid, suspend: true);

        /// <summary>Read a full dump — the right choice when the target must not be paused.</summary>
        public static DataTarget OpenDumpTarget(string path) =>
            DataTarget.LoadDump(path);

        /// <summary>Build the CLR view over an already-opened target. Takes
        /// ownership: on success the walker disposes the target, and on failure
        /// the target is still the caller's to dispose.</summary>
        public static RetentionWalker Create(DataTarget target) => new RetentionWalker(target);

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
        /// Find what retains the instances of <paramref name="typeName"/>: one breadth-first pass
        /// from the whole root set (which gives each node its shortest path for free), then group
        /// the resolved paths by shape, ranked by how many instances each shape holds — the answer
        /// to "what is holding all of this", as opposed to "here is a path to one of them".
        ///
        /// INVARIANT (the display/verdict boundary): reachability and the durable/transient census
        /// are computed over EVERY instance on the heap. <paramref name="sample"/> bounds only how
        /// many paths are RESOLVED for display; <paramref name="maxHops"/> bounds only how many
        /// hops are RENDERED. No display limit may alter discovery, classification, aggregation,
        /// or the verdict/exit code — a presentation flag that can change the diagnosis is a
        /// lottery, not an option.
        /// </summary>
        public RetentionReport FindRetainers(string typeName, int sample, int maxHops)
        {
            // ---- 1. the targets ---------------------------------------------------------
            // Match the TYPE, not the type's spelling. A naive substring match on the type name
            // matches `System.Func<BrokerDataClasses.GTDGoody, System.Boolean>` when you asked for
            // `GTDGoody` — a cached lambda whose *generic argument* happens to mention it — and then
            // confidently reports a path to the wrong object. A tool that points at the wrong culprit
            // is worse than no tool.
            // ALL matching instances are targeted (Codex P1: taking the first
            // `sample` in heap-enumeration order could catch only old garbage
            // and miss a later durably-held instance — a false OBSERVED_ONLY).
            // The verdict is exact over the whole population; only PATH
            // RESOLUTION below is sampled (`sample` paths), keeping the
            // expensive part bounded.
            var targets = new Dictionary<ulong, string>();
            long totalOfType = 0;
            foreach (var o in Heap.EnumerateObjects())
            {
                if (!o.IsValid || o.Type?.Name == null) continue;
                if (!IsType(o.Type.Name, typeName)) continue;
                totalOfType++;
                targets[o.Address] = o.Type.Name;
            }
            if (targets.Count == 0)
                return new RetentionReport(typeName, 0, 0, 0, 0, new List<Retainer>());

            // ---- 2. one BFS from every root; parent pointers only (no strings) ------------
            // Storing a label per node would cost hundreds of MB on a 4M-object heap. Store the
            // parent address, and resolve type/field names later, for the sampled paths only.
            var parent = new Dictionary<ulong, ulong>();      // child -> parent (0 = root)
            var rootKind = new Dictionary<ulong, ClrRootKind>();
            var queue = new Queue<ulong>();

            // Seed DURABLE roots (handles/statics) before TRANSIENT ones
            // (stack frames, the finalizer queue). Parent-pointer BFS credits an
            // object to whichever root reaches it first; a Main local that
            // happens to hold the static publisher in a register would
            // otherwise claim it as [stack] and mask the real static-event
            // retention (observed live on net8, gate A pins it).
            var allRoots = Heap.EnumerateRoots().ToList();
            int reachedTargets = 0;

            void Bfs()
            {
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
            }

            // Two BFS PHASES, not merely two seeding passes: durable roots
            // (handles/statics) are seeded and walked TO EXHAUSTION before any
            // transient root (stack frame, finalizer queue) enters the graph.
            // An object can be a stack-root itself AND reachable from a pinned
            // static — a Main local holding the static publisher is exactly
            // that — and seeding it as a stack ROOT would mask the durable
            // static-event retention behind it (observed live on net8; the
            // gate-A end-to-end smoke pins the corrected verdict). Retention
            // analysis prefers durable evidence; the stack only explains what
            // nothing durable can.
            //
            // INVARIANT (why the shared `parent` map cannot bury a transient
            // path): durable traversal claims reachable targets; transient
            // traversal may need shared intermediates, but every intermediate
            // the durable phase claimed was WALKED TO EXHAUSTION — so any
            // target reachable through a durably-claimed node is already
            // durably claimed itself. A target left for phase 2 is, by
            // construction, unreachable from every durable root, and its
            // transient path cannot pass through a durably-claimed node. (The
            // early exit on `reachedTargets` fires only when ALL targets are
            // claimed, which preserves the property.) Transient ownership
            // never overwrites durable ownership, and no explainable object
            // is left unexplained.
            foreach (var seedTransient in new[] { false, true })
            {
                foreach (var root in allRoots)
                {
                    bool transientRoot = Retainer.IsTransientRootKind(root.RootKind);
                    if (transientRoot != seedTransient) continue;
                    var o = root.Object;
                    if (!o.IsValid || parent.ContainsKey(o.Address)) continue;
                    parent[o.Address] = 0;
                    rootKind[o.Address] = root.RootKind;
                    queue.Enqueue(o.Address);
                }
                Bfs();
            }

            // ---- 3. root-kind census over EVERY reachable instance ------------------------
            // The census walks each reachable target's parent chain to its true root —
            // dictionary hops only, no type/field resolution — so the VERDICT sees the
            // root kind of the whole population. Classifying only the resolved-path
            // sample would re-admit the Codex P1 bias one level up: 200+ finalizer-
            // queue-reachable corpses sitting ahead of one durably-held instance in
            // heap order would read as a false OBSERVED_ONLY.
            var durableAddrs = new List<ulong>();
            var transientAddrs = new List<ulong>();
            foreach (var kv in targets)
            {
                if (!parent.ContainsKey(kv.Key)) continue;   // not reachable — genuinely garbage
                ulong cur = kv.Key;
                while (parent.TryGetValue(cur, out ulong p) && p != 0) cur = p;
                var rk = rootKind.TryGetValue(cur, out var k) ? k : ClrRootKind.None;
                // An unknown/None kind lands on the durable side, matching Classify's
                // `unsupported-root:*` doctrine (fail-closed toward visibility).
                if (Retainer.IsTransientRootKind(rk)) transientAddrs.Add(kv.Key);
                else durableAddrs.Add(kv.Key);
            }

            // ---- 4. resolve up to `sample` paths for display, durable instances first ----
            // Path resolution (type/field names) is the expensive, bounded part.
            // Durable-first ordering guarantees that whenever the census found durable
            // retention, at least one durable path is on display: RETAINED never ships
            // without its root path.
            var groups = new Dictionary<string, Retainer>();
            long pathsResolved = 0;
            foreach (var addr in durableAddrs.Concat(transientAddrs))
            {
                if (pathsResolved >= sample) break;
                pathsResolved++;

                var hops = Unwind(addr, parent, rootKind, maxHops, out ClrRootKind kind);
                // The signature must carry the CLASSIFICATION and the fields,
                // not only hop type names (Codex P1): a stack-rooted and a
                // durably-rooted instance can share a type sequence, and
                // merging them would classify the whole group by whichever
                // came first — hiding a durable retainer or inventing one.
                string signature = Retainer.Classify(kind, hops) + " | "
                    + string.Join(" -> ", hops.Select(h => h.ToString()));

                if (!groups.TryGetValue(signature, out var retainer))
                {
                    retainer = new Retainer(hops, kind);
                    groups[signature] = retainer;
                }
                retainer.Instances++;
            }

            var ranked = groups.Values.OrderByDescending(r => r.Instances).ToList();
            return new RetentionReport(targets.Values.First(), totalOfType,
                durableAddrs.Count + transientAddrs.Count, durableAddrs.Count, pathsResolved, ranked);
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
            bool truncated = false;
            while (true)
            {
                chain.Add(cur);
                if (!parent.TryGetValue(cur, out ulong p) || p == 0) break;
                cur = p;
                if (chain.Count > maxHops) { truncated = true; break; }
            }
            if (truncated)
            {
                // Keep walking the (acyclic) parent chain WITHOUT recording
                // hops: the rendered path stays bounded, but the verdict must
                // see the true root — stopping mid-chain yielded
                // ClrRootKind.None -> 'unsupported-root:None', which the
                // verdict counts as durable, turning a long stack-only path
                // into a false RETAINED (Codex P1).
                while (parent.TryGetValue(cur, out ulong p2) && p2 != 0) cur = p2;
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

    /// <summary>One distinct retention shape, and how many of the RESOLVED paths land on it
    /// (display evidence; the verdict rests on the whole-population census, not on these).</summary>
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
        public string ContractKind() => Classify(RootKind, Path);

        /// <summary>
        /// The transient/durable split at the ClrMD level — the single source of
        /// truth shared by the BFS phase seeding, the whole-population census, and
        /// (via Classify's 'stack'/'finalizer' cases) the string-level verdict
        /// rule; the selftest pins that the layers agree. Every other kind —
        /// including an UNKNOWN one — is durable for verdict purposes (fail-closed
        /// toward visibility).
        /// </summary>
        public static bool IsTransientRootKind(ClrRootKind kind) =>
            kind == ClrRootKind.Stack || kind == ClrRootKind.FinalizerQueue;

        /// <summary>
        /// The classifier boundary (kept pure over its evidence so the
        /// selftest pins it without a heap): a ClrMD root kind plus the path's
        /// delegate evidence map onto the `runtime.json` kinds. Every KNOWN
        /// kind is named explicitly; an UNKNOWN kind is an honest
        /// `unsupported-root:<kind>` — visible evidence the mapping must be
        /// taught, never silently classified as non-root or as a handle.
        /// </summary>
        public static string Classify(ClrRootKind rootKind, IReadOnlyList<Hop> path)
        {
            // The delegate evidence: an event subscription retains through the
            // handler chain — EventHandler/MulticastDelegate hop types, or the
            // multicast `_invocationList` field. Field evidence is checked as a
            // FIELD, hop types as TYPES: an unrelated type merely named
            // "...StackFrame..." or a field named "stackCache" is not evidence.
            bool viaDelegate = path.Any(h =>
                h.Type.IndexOf("EventHandler", StringComparison.Ordinal) >= 0 ||
                h.Type.IndexOf("MulticastDelegate", StringComparison.Ordinal) >= 0 ||
                (h.Field != null && h.Field.IndexOf("invocationList", StringComparison.OrdinalIgnoreCase) >= 0));

            switch (rootKind)
            {
                case ClrRootKind.Stack:
                    return "stack";            // live in a frame right now — not retention
                case ClrRootKind.FinalizerQueue:
                    return "finalizer";        // awaiting finalization — a stall, not a reference leak
                case ClrRootKind.PinnedHandle:
                    // statics live in a pinned object[] on both runtimes
                    return viaDelegate ? "static-event" : "static-field";
                case ClrRootKind.StrongHandle:
                case ClrRootKind.AsyncPinnedHandle:
                case ClrRootKind.RefCountedHandle:
                case ClrRootKind.SizedRefHandle:
                    return viaDelegate ? "static-event" : "gc-handle";
                default:
                    return $"unsupported-root:{rootKind}";
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
        /// <summary>Root-reachable instances — exact over the whole population.</summary>
        public readonly long Retained;
        /// <summary>Reachable instances whose true root is durable — exact; the
        /// verdict's input, deliberately independent of the --sample display budget.</summary>
        public readonly long DurableRetained;
        /// <summary>How many paths were resolved for display (bounded by --sample) —
        /// the denominator for every rendered share.</summary>
        public readonly long PathsResolved;
        public readonly IReadOnlyList<Retainer> Retainers;

        public RetentionReport(string typeName, long totalOnHeap, long retained,
                               long durableRetained, long pathsResolved,
                               IReadOnlyList<Retainer> retainers)
        {
            TypeName = typeName;
            TotalOnHeap = totalOnHeap;
            Retained = retained;
            DurableRetained = durableRetained;
            PathsResolved = pathsResolved;
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
