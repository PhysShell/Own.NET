using HelperLib;
namespace CallerLib;
public static class Caller
{
    public static R MakeDirect() => new R();                       // A: direct fresh return (own newobj)
    public static R MakeOneHop() => Helper.Make();                 // B: one-hop delegated return
    public static R MakeTwoHop() => Helper2.Make();                // C: two-hop delegated return
    public static R MakeVirtual() => Helper.Instance.Make();       // D: interface dispatch, target chosen by the dependency
    public static R MakeViaProperty() => Helper.Shared;            // E: static/cached singleton behind a property
    public static R MakeGeneric() => Helper.MakeGeneric<R>();      // F: generic helper
}
