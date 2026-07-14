using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.Diagnostics.Runtime;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// Mark-from-roots over a target's managed heap, and the root -> object path for a
    /// suspect type.
    ///
    /// WHY THIS IS NOT HeapCounter. <see cref="HeapCounter"/> answers "how many instances
    /// of T are on the heap". That is a different question from "how many are RETAINED",
    /// because <c>ClrHeap.EnumerateObjects()</c> walks the heap segments linearly and
    /// returns everything allocated — including garbage the GC has not collected yet. A
    /// big heap is not evidence of a leak. HeapCounter mitigates this by forcing a GC in
    /// the target first, which works when you can (SematixTrace); this type does not need
    /// to, because marking from the roots answers the question directly:
    ///
    ///   reachable ≈ heap   -> genuinely retained; something holds it
    ///   reachable &lt;&lt; heap  -> not a leak; the GC simply has not collected yet
    ///
    /// That distinction is the difference between a leak hunt and a wild goose chase, and
    /// it is cheap: one mark pass.
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
        /// The GC-root path to instances whose type name contains <paramref name="typeSubstring"/>.
        /// Breadth-first from the roots, so the path returned is the SHORTEST one — the most
        /// legible explanation of who is holding the object, not merely a valid one.
        ///
        /// The hops name the FIELD they traverse (ClrMD's EnumerateReferencesWithFields), which
        /// is what turns "a byte[] is reachable" into "AppData.Properties.GBProperty.PropertyChanged
        /// holds it" — the sentence a developer can act on.
        /// </summary>
        public IReadOnlyList<RetentionPathResult> FindRootPaths(string typeName, int maxPaths, int maxHops)
        {
            // Match the TYPE, not the type's spelling. A naive substring match on the type name
            // matches `System.Func<BrokerDataClasses.GTDGoody, System.Boolean>` when you asked for
            // `GTDGoody` — a cached lambda whose *generic argument* happens to mention it — and
            // then confidently reports a 2-hop path to the wrong object. A tool that points at the
            // wrong culprit is worse than no tool. So compare the simple name with the generic
            // arguments stripped.
            var targets = new Dictionary<ulong, string>();
            foreach (var o in Heap.EnumerateObjects())
            {
                if (!o.IsValid || o.Type?.Name == null) continue;
                if (!IsType(o.Type.Name, typeName)) continue;
                targets[o.Address] = o.Type.Name;
                if (targets.Count >= maxPaths) break;
            }
            if (targets.Count == 0) return Array.Empty<RetentionPathResult>();

            var found = new List<RetentionPathResult>();
            var seen = new HashSet<ulong>();
            var queue = new Queue<Node>();

            foreach (var root in Heap.EnumerateRoots())
            {
                var o = root.Object;
                if (!o.IsValid || !seen.Add(o.Address)) continue;
                queue.Enqueue(new Node(o.Address, null, Describe(root, o), root.RootKind));
            }

            while (queue.Count > 0 && found.Count < maxPaths)
            {
                var node = queue.Dequeue();

                if (targets.TryGetValue(node.Address, out var hitType))
                {
                    found.Add(new RetentionPathResult(hitType, Unwind(node), node.RootKind));
                    continue;
                }

                var obj = Heap.GetObject(node.Address);
                if (!obj.IsValid || obj.Type == null) continue;
                if (Depth(node) > maxHops) continue;

                // WithFields so a hop reads "GBProperty.PropertyChanged", not just "GBProperty".
                foreach (var reference in obj.EnumerateReferencesWithFields())
                {
                    var child = reference.Object;
                    if (!child.IsValid || !seen.Add(child.Address)) continue;
                    string hop = child.Type?.Name ?? "?";
                    if (reference.Field?.Name is string f && f.Length > 0) hop = hop + "  (." + f + ")";
                    queue.Enqueue(new Node(child.Address, node, hop, node.RootKind));
                }
            }
            return found;
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

            // strip generic arguments: `Func<A, B>` -> `Func`, `BindingList<T>` -> `BindingList`
            int lt = heapType.IndexOf('<');
            string bare = lt >= 0 ? heapType.Substring(0, lt) : heapType;

            if (string.Equals(bare, wanted, StringComparison.Ordinal)) return true;

            // allow the simple name: `GTDGoody` matches `BrokerDataClasses.GTDGoody`
            int dot = bare.LastIndexOf('.');
            string simple = dot >= 0 ? bare.Substring(dot + 1) : bare;
            return string.Equals(simple, wanted, StringComparison.Ordinal);
        }

        private static string Describe(ClrRoot root, ClrObject o) =>
            "[" + root.RootKind + "] " + (o.Type?.Name ?? "?");

        private static int Depth(Node n)
        {
            int d = 0;
            for (var p = n.Parent; p != null; p = p.Parent) d++;
            return d;
        }

        private static IReadOnlyList<string> Unwind(Node n)
        {
            var path = new List<string>();
            for (var p = n; p != null; p = p.Parent) path.Add(p.Label);
            path.Reverse();
            return path;
        }

        public void Dispose()
        {
            _runtime.Dispose();
            _target.Dispose();
        }

        private sealed class Node
        {
            public readonly ulong Address;
            public readonly Node? Parent;
            public readonly string Label;
            public readonly ClrRootKind RootKind;

            public Node(ulong address, Node? parent, string label, ClrRootKind rootKind)
            {
                Address = address;
                Parent = parent;
                Label = label;
                RootKind = rootKind;
            }
        }
    }

    internal struct TypeTally
    {
        public long Count;
        public long Bytes;
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

    internal sealed class RetentionPathResult
    {
        public readonly string TypeName;
        public readonly IReadOnlyList<string> Path;
        public readonly ClrRootKind RootKind;

        public RetentionPathResult(string typeName, IReadOnlyList<string> path, ClrRootKind rootKind)
        {
            TypeName = typeName;
            Path = path;
            RootKind = rootKind;
        }

        /// <summary>
        /// Map a ClrMD root kind onto the `runtime.json` kinds (OwnAudit/docs/runtime-contract.md:
        /// static-field, static-event, gc-handle, thread-local, timer).
        ///
        /// Note there is no `StaticVar` root kind: on .NET Framework a class's statics live in a
        /// pinned `System.Object[]` handed to the runtime as a **PinnedHandle**, which is why a
        /// static-field leak surfaces as `[PinnedHandle] System.Object[] -> …`. So PinnedHandle is
        /// where statics show up, and a **delegate hop** anywhere further down the path is what
        /// makes it a static *event* rather than a plain static field — the distinction
        /// correlate.py's `high` tier keys on.
        ///
        /// `Stack` and `FinalizerQueue` are reported as themselves. They are not contract kinds
        /// and deliberately so: an object rooted only by the stack is merely *live right now*, not
        /// retained, and reading it as a leak is how a leak hunt goes wrong.
        /// </summary>
        public string ContractKind()
        {
            bool viaDelegate = Path.Any(p =>
                p.IndexOf("EventHandler", StringComparison.Ordinal) >= 0 ||
                p.IndexOf("MulticastDelegate", StringComparison.Ordinal) >= 0);

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
    }
}
