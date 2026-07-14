using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.Diagnostics.Runtime;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// The dominator tree of the object graph, and every object's RETAINED SIZE.
    ///
    /// WHY. "Who holds this object" is ill-posed when the object is reachable from several
    /// roots — there are as many answers as there are paths, and a shortest-path walk just
    /// picks one. The question that is well-posed, and the one an engineer actually needs, is:
    ///
    ///     which single reference, if cut, makes this object collectable —
    ///     and how much memory does cutting it free?
    ///
    /// That is exactly what dominance answers. D dominates X when EVERY path from a root to X
    /// goes through D. X's immediate dominator is therefore its one true retainer, and the
    /// retained size of D — the total size of everything D dominates — is what you free by
    /// dropping the reference to D. This is what Eclipse MAT and dotMemory are built on, and it
    /// is why they can say "detach this and you get 1.4 GB back" while a path walk cannot.
    ///
    /// It also answers honestly in the awkward case. If the leaked objects are held by TWO
    /// references at once, neither dominates them; their dominator sits higher up, at the point
    /// the two paths meet — and the tool will say so, instead of confidently naming one of the
    /// two and sending you off to cut a reference that frees nothing.
    ///
    /// ALGORITHM. Cooper–Harvey–Kennedy, "A Simple, Fast Dominance Algorithm" (2001) — the
    /// iterative formulation LLVM used for years. Not Lengauer–Tarjan: CHK is a page of code,
    /// converges in a couple of passes on real graphs, and needs no balanced forests. The paper
    /// is public; this is an implementation of it, not a copy of anyone's code. (PerfView, MIT,
    /// is the closest .NET reference — note it computes a *spanning tree* with inclusive sizes,
    /// which is an approximation of this.)
    ///
    /// MEMORY. A 4M-object heap will not fit in `List&lt;List&lt;int&gt;&gt;`. The graph is built as CSR
    /// (compressed sparse row): ids are handed out in discovery order and BFS processes nodes in
    /// that same order, so each node's successors land contiguously and a single int[] holds every
    /// edge. Budget roughly 150 bytes/object — a 4M-object heap costs ~600 MB in the analyzer, a
    /// 40M-object heap will not fit and should be sampled instead.
    /// </summary>
    internal sealed class DominatorTree
    {
        // node 0 is a synthetic super-root whose successors are the GC roots. Every real object
        // is therefore reachable from exactly one place, which is what makes dominance well-defined.
        private readonly int _n;
        private readonly ulong[] _address;
        private readonly long[] _size;
        private readonly int[] _succStart;   // CSR: successors of u are _succ[_succStart[u] .. _succStart[u+1])
        private readonly int[] _succ;
        private readonly int[] _idom;
        private readonly int[] _rpoNum;      // reverse-postorder index; -1 = unreachable
        private readonly long[] _retained;
        private readonly ClrHeap? _heap;   // null in the self-test, where there is no target

        private DominatorTree(ClrHeap? heap, int n, ulong[] address, long[] size,
                              int[] succStart, int[] succ)
        {
            _heap = heap;
            _n = n;
            _address = address;
            _size = size;
            _succStart = succStart;
            _succ = succ;
            _idom = new int[n];
            _rpoNum = new int[n];
            _retained = new long[n];
        }

        /// <summary>
        /// Dominate a graph given directly, with no heap behind it. Exists so the algorithm can be
        /// tested without a target process — a dominator tree that is quietly wrong produces
        /// confidently wrong advice ("cut this reference"), which is worse than no tool.
        /// </summary>
        internal static DominatorTree ForGraph(int n, int[] succStart, int[] succ, long[] size)
        {
            var t = new DominatorTree(null, n, new ulong[n], size, succStart, succ);
            t.Dominate();
            t.ComputeRetained();
            return t;
        }

        internal int IdomOf(int node) => _idom[node];
        internal long RetainedOf(int node) => _retained[node];

        /// <summary>Walk the live graph once, then dominate it.</summary>
        public static DominatorTree Build(ClrHeap heap)
        {
            // ---- 1. BFS the reachable graph into CSR ---------------------------------------
            // ids are assigned in discovery order, and the queue hands nodes back in that same
            // order, so a node's successors can be appended contiguously as it is processed.
            var id = new Dictionary<ulong, int>();
            var address = new List<ulong> { 0 };          // node 0 = the synthetic super-root
            var size = new List<long> { 0 };
            var succStart = new List<int> { 0 };
            var succ = new List<int>();
            var queue = new Queue<int>();

            // the super-root's successors are the GC roots
            foreach (var root in heap.EnumerateRoots())
            {
                var o = root.Object;
                if (!o.IsValid || o.Type == null) continue;
                if (!id.TryGetValue(o.Address, out int rid))
                {
                    rid = address.Count;
                    id[o.Address] = rid;
                    address.Add(o.Address);
                    size.Add((long)o.Size);
                    queue.Enqueue(rid);
                }
                succ.Add(rid);
            }
            succStart.Add(succ.Count);   // end of node 0's successor run

            while (queue.Count > 0)
            {
                int u = queue.Dequeue();
                // The invariant that makes CSR work: nodes are dequeued in ascending id order, so
                // succStart is appended to in that order too. Assert it rather than trust it.
                if (succStart.Count != u + 1)
                    throw new InvalidOperationException(
                        "BFS visited nodes out of id order — the CSR layout would be corrupt");

                var obj = heap.GetObject(address[u]);
                if (obj.IsValid && obj.Type != null)
                {
                    foreach (var child in obj.EnumerateReferences())
                    {
                        if (!child.IsValid || child.Type == null) continue;
                        if (!id.TryGetValue(child.Address, out int cid))
                        {
                            cid = address.Count;
                            id[child.Address] = cid;
                            address.Add(child.Address);
                            size.Add((long)child.Size);
                            queue.Enqueue(cid);
                        }
                        succ.Add(cid);
                    }
                }
                succStart.Add(succ.Count);
            }

            var t = new DominatorTree(heap, address.Count, address.ToArray(), size.ToArray(),
                                      succStart.ToArray(), succ.ToArray());
            t.Dominate();
            t.ComputeRetained();
            return t;
        }

        public int Count => _n;
        public long TotalRetained => _retained.Length > 0 ? _retained[0] : 0;

        // ---- 2. reverse postorder over the successors -------------------------------------
        private int[] ReversePostorder()
        {
            var order = new List<int>(_n);
            var state = new byte[_n];            // 0 = unseen, 1 = on stack, 2 = done
            var stack = new Stack<(int node, int next)>();

            stack.Push((0, _succStart[0]));
            state[0] = 1;
            while (stack.Count > 0)
            {
                var (u, next) = stack.Pop();
                if (next < _succStart[u + 1])
                {
                    stack.Push((u, next + 1));
                    int v = _succ[next];
                    if (state[v] == 0)
                    {
                        state[v] = 1;
                        stack.Push((v, _succStart[v]));
                    }
                }
                else
                {
                    state[u] = 2;
                    order.Add(u);                // postorder
                }
            }
            order.Reverse();                     // reverse postorder

            for (int i = 0; i < _n; i++) _rpoNum[i] = -1;
            for (int i = 0; i < order.Count; i++) _rpoNum[order[i]] = i;
            return order.ToArray();
        }

        // ---- 3. predecessors (CHK needs them) ---------------------------------------------
        private (int[] predStart, int[] pred) Predecessors()
        {
            var count = new int[_n + 1];
            for (int u = 0; u < _n; u++)
                for (int e = _succStart[u]; e < _succStart[u + 1]; e++)
                    count[_succ[e] + 1]++;

            var predStart = new int[_n + 1];
            for (int i = 0; i < _n; i++) predStart[i + 1] = predStart[i] + count[i + 1];

            var fill = new int[_n];
            var pred = new int[predStart[_n]];
            for (int u = 0; u < _n; u++)
                for (int e = _succStart[u]; e < _succStart[u + 1]; e++)
                {
                    int v = _succ[e];
                    pred[predStart[v] + fill[v]++] = u;
                }
            return (predStart, pred);
        }

        // ---- 4. Cooper–Harvey–Kennedy ------------------------------------------------------
        private void Dominate()
        {
            var rpo = ReversePostorder();
            var (predStart, pred) = Predecessors();

            for (int i = 0; i < _n; i++) _idom[i] = -1;
            _idom[0] = 0;

            bool changed = true;
            while (changed)
            {
                changed = false;
                foreach (int u in rpo)
                {
                    if (u == 0) continue;
                    int newIdom = -1;
                    for (int e = predStart[u]; e < predStart[u + 1]; e++)
                    {
                        int p = pred[e];
                        if (_idom[p] == -1) continue;               // not processed yet this pass
                        newIdom = newIdom == -1 ? p : Intersect(p, newIdom);
                    }
                    if (newIdom != -1 && _idom[u] != newIdom)
                    {
                        _idom[u] = newIdom;
                        changed = true;
                    }
                }
            }
        }

        /// <summary>Walk both fingers up the dominator chain until they meet.</summary>
        private int Intersect(int a, int b)
        {
            while (a != b)
            {
                while (_rpoNum[a] > _rpoNum[b]) a = _idom[a];
                while (_rpoNum[b] > _rpoNum[a]) b = _idom[b];
            }
            return a;
        }

        // ---- 5. retained size ---------------------------------------------------------------
        private void ComputeRetained()
        {
            for (int i = 0; i < _n; i++) _retained[i] = _size[i];

            // idom[u] always precedes u in reverse postorder, so walking the RPO backwards means
            // every node is finished before its dominator needs it. One pass, no recursion.
            var rpo = new int[_n];
            for (int i = 0; i < _n; i++) if (_rpoNum[i] >= 0) rpo[_rpoNum[i]] = i;
            for (int i = _n - 1; i >= 1; i--)
            {
                int u = rpo[i];
                if (u == 0) continue;
                int d = _idom[u];
                if (d >= 0 && d != u) _retained[d] += _retained[u];
            }

            // The super-root dominates everything, so its retained size MUST be the total size of the
            // reachable graph. If it is not, the dominator tree is wrong — and a wrong dominator tree
            // does not fail loudly, it just tells you to cut the wrong reference. Check it.
            long total = 0;
            for (int i = 0; i < _n; i++) total += _size[i];
            if (_retained[0] != total)
                throw new InvalidOperationException(
                    $"dominator tree is inconsistent: super-root retains {_retained[0]:N0} B but the " +
                    $"reachable graph is {total:N0} B — refusing to report a result that would be wrong");
        }

        /// <summary>
        /// The algorithm, checked against graphs whose dominators are known by hand. Runs anywhere —
        /// no target, no Windows. `RetentionPath selftest`.
        /// </summary>
        internal static bool SelfTest(Action<string> log)
        {
            bool ok = true;

            void Check(string what, bool cond)
            {
                log((cond ? "  ok   " : "  FAIL ") + what);
                if (!cond) ok = false;
            }

            // (a) a diamond — the case that matters. 3 is reachable through BOTH 1 and 2, so
            //     NEITHER dominates it: its immediate dominator is the root. This is precisely the
            //     shape a shortest-path walk gets wrong (it would name 1, or 2, and be confident).
            //         0 -> 1 -> 3 -> 4
            //         0 -> 2 -> 3
            {
                //                 0      1      2      3      4
                var start = new[] { 0,     2,     3,     4,     5, 5 };
                var succ = new[] { 1, 2,   3,     3,     4 };
                var size = new long[] { 0, 10, 10, 10, 10 };
                var t = ForGraph(5, start, succ, size);

                Check("diamond: idom(1) = 0", t.IdomOf(1) == 0);
                Check("diamond: idom(2) = 0", t.IdomOf(2) == 0);
                Check("diamond: idom(3) = 0  (held by BOTH 1 and 2 — neither dominates)", t.IdomOf(3) == 0);
                Check("diamond: idom(4) = 3", t.IdomOf(4) == 3);
                Check("diamond: retained(3) = 20 (itself + 4)", t.RetainedOf(3) == 20);
                Check("diamond: retained(1) = 10 (it does NOT retain 3)", t.RetainedOf(1) == 10);
                Check("diamond: retained(root) = 40", t.RetainedOf(0) == 40);
            }

            // (b) a chain — every link dominates the rest, so retained size accumulates.
            //     0 -> 1 -> 2 -> 3
            {
                var start = new[] { 0, 1, 2, 3, 3 };
                var succ = new[] { 1, 2, 3 };
                var size = new long[] { 0, 10, 20, 30 };
                var t = ForGraph(4, start, succ, size);

                Check("chain: idom(3) = 2", t.IdomOf(3) == 2);
                Check("chain: retained(1) = 60 (the whole tail)", t.RetainedOf(1) == 60);
                Check("chain: retained(2) = 50", t.RetainedOf(2) == 50);
            }

            // (c) a cycle below a single gate. 1 gates the cycle 2<->3, so 1 dominates both even
            //     though they point at each other. A naive reference-count would never free them.
            {
                //                 0     1     2     3
                var start = new[] { 0,    1,    2,    3, 4 };
                var succ = new[] { 1,    2,    3,    2 };
                var size = new long[] { 0, 10, 10, 10 };
                var t = ForGraph(4, start, succ, size);

                Check("cycle: idom(2) = 1", t.IdomOf(2) == 1);
                Check("cycle: idom(3) = 2", t.IdomOf(3) == 2);
                Check("cycle: retained(1) = 30 (cut 1 and the whole cycle collects)", t.RetainedOf(1) == 30);
            }

            log(ok ? "dominator selftest: OK" : "dominator selftest: FAILED");
            return ok;
        }

        /// <summary>
        /// The objects whose removal frees the most memory — i.e. the answer to "what is holding
        /// all of this". The super-root is skipped (it dominates everything by construction, which
        /// is true and useless).
        /// </summary>
        public IReadOnlyList<DominatorHit> Top(int count, long minBytes)
        {
            var hits = new List<DominatorHit>();
            for (int u = 1; u < _n; u++)
            {
                if (_retained[u] < minBytes) continue;
                hits.Add(new DominatorHit(u, _address[u], _retained[u], _size[u]));
            }
            hits.Sort((a, b) => b.RetainedBytes.CompareTo(a.RetainedBytes));

            // A dominator chain reports the same bytes at every link (a -> b -> c each "retain"
            // the subtree). Reporting all of them is noise; keep a link only if it retains
            // meaningfully more than the child that follows it — i.e. the points where the graph
            // actually branches. Otherwise the top-20 is one chain, twenty times.
            var kept = new List<DominatorHit>();
            var claimed = new HashSet<int>();
            foreach (var h in hits)
            {
                if (kept.Count >= count) break;
                bool redundant = false;
                for (int d = _idom[h.Node]; d > 0 && d != _idom[d]; d = _idom[d])
                {
                    if (claimed.Contains(d) && _retained[d] < h.RetainedBytes * 11 / 10)
                    {
                        redundant = true;   // an ancestor already reported ~the same bytes
                        break;
                    }
                }
                if (redundant) continue;
                claimed.Add(h.Node);
                kept.Add(h);
            }
            return kept;
        }

        /// <summary>The dominator chain from the super-root down to a node, naming each type.</summary>
        public IReadOnlyList<string> ChainTo(int node, int maxHops)
        {
            var chain = new List<int>();
            for (int u = node; u > 0 && chain.Count < maxHops; u = _idom[u])
            {
                chain.Add(u);
                if (_idom[u] == u) break;
            }
            chain.Reverse();
            return chain.Select(TypeOf).ToList();
        }

        public string TypeOf(int node)
        {
            if (_heap == null) return "#" + node;
            var o = _heap.GetObject(_address[node]);
            return o.Type?.Name ?? "?";
        }

        /// <summary>Retained bytes grouped by the TYPE of the dominator — "what class of thing is holding memory".</summary>
        public IReadOnlyList<(string Type, long Retained, long Count)> ByDominatorType(int top)
        {
            var acc = new Dictionary<string, (long bytes, long n)>();
            for (int u = 1; u < _n; u++)
            {
                // count a node only where it is the immediate dominator of something — otherwise
                // every leaf would "retain" itself and the table would just be a type histogram.
                if (_idom[u] <= 0) continue;
                string t = TypeOf(_idom[u]);
                var cur = acc.TryGetValue(t, out var v) ? v : (0L, 0L);
                acc[t] = (cur.Item1 + _retained[u], cur.Item2 + 1);
            }
            return acc.OrderByDescending(kv => kv.Value.bytes)
                      .Take(top)
                      .Select(kv => (kv.Key, kv.Value.bytes, kv.Value.n))
                      .ToList();
        }
    }

    internal sealed class DominatorHit
    {
        public readonly int Node;
        public readonly ulong Address;
        public readonly long RetainedBytes;
        public readonly long OwnBytes;

        public DominatorHit(int node, ulong address, long retainedBytes, long ownBytes)
        {
            Node = node;
            Address = address;
            RetainedBytes = retainedBytes;
            OwnBytes = ownBytes;
        }
    }
}
