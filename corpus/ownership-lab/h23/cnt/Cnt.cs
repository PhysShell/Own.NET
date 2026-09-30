using RLib;
public static class Cnt
{
    public static void M1_loop_only(int n) { R x = null; for (int i = 0; i < n; i++) x = F.Factory(); x.Ping(); }
    public static void M2_loop_then_compound(int n) { R x = null; for (int i = 0; i < n; i++) x = F.Factory(); x ??= F.Factory(); x.Ping(); }
    public static void M3_compound_then_loop(int n) { R x = null; x ??= F.Factory(); for (int i = 0; i < n; i++) x = F.Factory(); x.Ping(); }
    public static void M4_nested_then_compound(bool c) { R x = null; if (c) x = F.Factory(); x ??= F.Factory(); x.Ping(); }
    public static void M5_loop_then_ref(int n) { R x = null; for (int i = 0; i < n; i++) x = F.Factory(); F.Take(ref x); }
}
