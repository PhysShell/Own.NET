using System.IO;

namespace Factories;

// P-005 D5.2: a fresh-returning factory + its callers. The factory `Make` creates and
// hands back a NEW owned stream; the core infers `returnsOwned: fresh` from its
// `acquire; return <var>` body. A caller that binds the result and drops it (`Leaks`)
// is then charged the leak at the call site — an INTERPROCEDURAL finding the flat,
// intra-procedural detectors cannot see. A caller that disposes the result (`Clean`)
// stays silent, and the factory itself stays silent (it transfers ownership out).
public static class StreamFactory
{
    public static Stream Make()
    {
        var made = new MemoryStream();   // freshly owned, handed to the caller
        return made;
    }
}

public static class FactoryConsumers
{
    // Drops the fresh factory result without disposing -> OWN001 at the call site.
    public static void Leaks()
    {
        var factoryLeak = StreamFactory.Make();
        factoryLeak.WriteByte(1);
    }

    // Disposes the fresh factory result -> clean (silent).
    public static void Clean()
    {
        var factoryOk = StreamFactory.Make();
        factoryOk.Dispose();
    }
}
