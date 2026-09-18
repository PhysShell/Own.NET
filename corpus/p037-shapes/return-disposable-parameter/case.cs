// A1.1-a1 REGRESSION ANCHOR. `Echo` returns its own disposable PARAMETER.
//
// This is the shape that turned six CI jobs red when a1 first put owned
// parameters into the lowering set: `return s` became a fresh-factory return,
// and the core read a fresh return of something it never saw acquired as an
// escaping borrow -> [OWN004] 'parg_N' is a borrow and cannot be returned.
//
// The resource belongs to the CALLER and outlives the call. What the return
// really is, is an ALIAS of the parameter, and OwnIR cannot say that:
// `aliasOf`/`aliased` are reserved in the schema and never emitted. So the
// frontend claims NO owned return here rather than asserting a false kind.
using System.IO;

static class ShapeReturnParam
{
    static Stream Echo(Stream s)
    {
        return s;
    }

    static void Use(string path)
    {
        var owned = File.OpenRead(path);
        var same = Echo(owned);
        same.Dispose();
    }
}
