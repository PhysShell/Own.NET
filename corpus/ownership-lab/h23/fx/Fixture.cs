using RLib;
namespace Fx;
public static class Shapes
{
    // ---- receiving shapes (section 9): trusted row F.Factory() -> fresh owned R ----
    public static void S1_declaration() { var x = F.Factory(); x.Ping(); }
    public static void S2_existing_local() { R x = null; x = F.Factory(); x.Ping(); }
    static R _field;
    public static void S3_field_store() { _field = F.Factory(); }
    public static void S4_using_var() { using var x = F.Factory(); x.Ping(); }
    public static R S5_return() { return F.Factory(); }
    public static void S6_argument() { F.Consume(F.Factory()); }
    static readonly System.Collections.Generic.Dictionary<string, R> cache = new();
    public static void S7_indexer_store(string key) { cache[key] = F.Factory(); }
    public static void S8_null_coalescing_assign() { R x = null; x ??= F.Factory(); x.Ping(); }
    public sealed class Holder { public R Prop { get; set; } }
    public static void S9_property_store(Holder h) { h.Prop = F.Factory(); }
    public static void S10_chained_temporary() { F.Factory().Ping(); }
    public static void S11_conditional(bool c) { var x = c ? F.Factory() : F.Borrowed(); x.Ping(); }
    public static void S12_tuple_assignment() { R a; int n; (a, n) = (F.Factory(), 1); a.Ping(); }
}
public static class Positive
{
    public static void A1_declaration_baseline() { var x = F.Factory(); x.Ping(); return; }
    public static void A2_assignment_leak() { R x = null; x = F.Factory(); x.Ping(); return; }
    public static void A3_assignment_then_dispose() { R x = null; x = F.Factory(); x.Ping(); x.Dispose(); }
    public static void A4_declared_value_reassigned_leak() { R x = F.Borrowed(); x = F.Factory(); x.Ping(); return; }
}
public static class Hostile
{
    public static void H1_overwrite_without_dispose() { R x = F.Factory(); x = F.Factory(); x.Dispose(); }
    public static void H2_dispose_before_overwrite() { R x = F.Factory(); x.Dispose(); x = F.Factory(); x.Dispose(); }
    public static void H3_fresh_to_null() { R x = F.Factory(); x = null; return; }
    public static void H4_borrowed_to_fresh() { R x = F.Borrowed(); x = F.Factory(); x.Dispose(); }
    public static void H5_fresh_to_borrowed() { R x = F.Factory(); x = F.Borrowed(); return; }
    public static void H6_branch_overwrite(bool flag) { R x = F.Factory(); if (flag) x = F.Factory(); x.Dispose(); }
    public static void H6b_branch_dispose_then_overwrite(bool flag) { R x = F.Factory(); if (flag) { x.Dispose(); x = F.Factory(); } x.Dispose(); }
    public static void H6c_both_branches_assign(bool flag) { R x = null; if (flag) x = F.Factory(); else x = F.Factory(); x.Dispose(); }
    public static void H7_alias_before_overwrite() { R x = F.Factory(); var y = x; x = F.Factory(); y.Dispose(); x.Dispose(); }
    public static void H8_loop_reassignment(int n) { R x = null; for (int i = 0; i < n; i++) x = F.Factory(); x?.Dispose(); }
    public static void H9_try_finally_nullinit() { R x = null; try { x = F.Factory(); x.Ping(); } finally { x?.Dispose(); } }
    public static void H10_assignment_in_condition() { R x; if ((x = F.Factory()) != null) x.Dispose(); }
}
