using System;
using RLib;
// H-24 restricted single-obligation merge: the five forms of the brief (P1-P5) and the hostile twins. Frozen BEFORE any
// code (h24-prereg-v1.json). F.Factory() is the ONE trusted row (fresh owned); F.Borrowed() has no row; `new R()` is a
// new-of-disposable acquire. Expected outcomes are in the prereg, not here.
public static class Forms
{
    // P1: both arms assign a fresh value, disposed after the merge -> expected clean (ONE merged obligation, discharged)
    public static void P1_both_fresh_disposed(bool c) { R x; if (c) x = F.Factory(); else x = F.Factory(); x.Ping(); x.Dispose(); }
    // P2: the sibling arm exits; the surviving path assigns -> expected clean (this shape broke the bridge in H-23A)
    public static void P2_exiting_sibling_disposed(bool c) { R x; if (c) x = F.Factory(); else throw new Exception(); x.Ping(); x.Dispose(); }
    // P3: both arms assign, nothing disposes -> expected EXACTLY ONE leak obligation, not two
    public static void P3_both_fresh_leak(bool c) { R x; if (c) x = F.Factory(); else x = F.Factory(); x.Ping(); }
    // P4: one arm borrowed -> REFUSE the merge (no owned obligation may be fabricated for the borrowed path)
    public static void P4_one_path_borrowed(bool c) { R x; if (c) x = F.Factory(); else x = F.Borrowed(); x.Ping(); }
    // P5: a prior owned value conditionally overwritten -> REFUSE (the first value may leak; not one merged obligation)
    public static void P5_prior_owned_overwritten(bool c) { R x = F.Factory(); if (c) x = F.Factory(); x.Dispose(); }
}
public static class Hostile
{
    // multiple writes on the same path -> REFUSE (the first value of that arm leaks; it is not a single last definition)
    public static void T1_two_writes_same_arm(bool c) { R x; if (c) { x = F.Factory(); x = F.Factory(); } else x = F.Factory(); x.Dispose(); }
    // loop backedge -> REFUSE (one obligation per iteration, no merge)
    public static void T2_loop_backedge(int n) { R x = null; for (int i = 0; i < n; i++) { if (i == 0) x = F.Factory(); else x = F.Factory(); } x?.Dispose(); }
    // try/finally -> REFUSE (classified only; H-01 territory)
    public static void T3_try_finally() { R x = null; try { x = F.Factory(); x.Ping(); } finally { x?.Dispose(); } }
    // mixed owned kinds: new-of-disposable in one arm, the trusted row in the other -> both are fresh OWNED disposables
    // (compatible by the prereg: same ownership class); recorded as its own class in the census
    public static void T4_mixed_new_and_row(bool c) { R x; if (c) x = new R(); else x = F.Factory(); x.Dispose(); }
    // null in one arm -> REFUSE (no value on that path; a merged obligation would be fabricated for it)
    public static void T5_null_arm(bool c) { R x; if (c) x = F.Factory(); else x = null; x?.Dispose(); }
    // a reference to the local INSIDE the construct after its write (the NpgsqlRestEndpoint shape) -> strict REFUSE,
    // relaxed admissible (the use precedes the merge on its own path)
    public static void T6_use_inside_arm(bool c) { R x; if (c) { x = F.Factory(); x.Ping(); } else throw new Exception(); x.Dispose(); }
    // the exact NpgsqlRest ConnectionHelper shape: two levels of if / else-if with throwing siblings, writes at depth 2
    public static R T7_npgsqlrest_exact(bool named, bool a, bool b, bool c, bool d)
    {
        R x;
        if (named) { if (a) x = F.Factory(); else if (b) x = F.Factory(); else throw new InvalidOperationException("named"); }
        else { if (c) x = F.Factory(); else if (d) x = F.Factory(); else throw new InvalidOperationException("default"); }
        x.Ping();
        return x;
    }
    // deeper nesting without exits: every leaf assigns exactly once -> PASS candidate at depth 2
    public static void T8_depth2_all_assign(bool a, bool b) { R x; if (a) { if (b) x = F.Factory(); else x = F.Factory(); } else x = F.Factory(); x.Dispose(); }
    // not definitely assigned on exit (an arm neither assigns nor exits): C# forbids a later read, so there is no merge
    public static void T9_not_definitely_assigned(bool c) { R x; if (c) x = F.Factory(); return; }
    // a switch with one write per section and a throwing default -> PASS candidate
    public static void T10_switch(int k) { R x; switch (k) { case 0: x = F.Factory(); break; case 1: x = F.Factory(); break; default: throw new Exception(); } x.Dispose(); }
    // writes in TWO top-level constructs -> REFUSE (no single merge point)
    public static void T11_two_constructs(bool a, bool b) { R x = null; if (a) x = F.Factory(); if (b) x = F.Factory(); x?.Dispose(); }
    // a write before the construct on the same path -> REFUSE (prior live obligation; P5 in statement form)
    public static void T12_write_before_construct(bool c) { R x; x = F.Factory(); if (c) x = F.Factory(); x.Dispose(); }
}
