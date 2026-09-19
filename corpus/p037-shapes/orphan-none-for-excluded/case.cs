using System;
using System.IO;

// A2.2-3P NEGATIVE: the only occurrence is a named exclusion (tuple_construction), so there is
// no fact to carry: no functions[] record AND no guarded_functions[] entry. Absence of the
// carrier entry is the signal, not a missing record.
static class ShapeOrphanNoneForExcluded
{
    static void Use2((Stream s, int n) t) { }
    static void Caller(string path) { var s = File.OpenRead(path); Use2((s, 1)); }
}
