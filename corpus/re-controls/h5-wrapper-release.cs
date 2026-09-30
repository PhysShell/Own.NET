// resource-effects Stage 1 compositional control H5: a first-party wrapper Drop(k) whose body is the
// oracle release k.Delete(). Truth: Run leaks nothing (the wrapper consumes the key); RunUseAfter uses
// the key after the handoff (OWN002). Without a key Drop is an ordinary escape (silent); with the
// identity answer key the release composes through the consumer inference (DisposesLocal).
using System.Security.Cryptography;

static class H5
{
    static void Drop(CngKey k)
    {
        k.Delete();
    }

    static void Run(CngAlgorithm alg, string name)
    {
        CngKey key = CngKey.Create(alg, name);
        Drop(key);
    }

    static void RunUseAfter(CngAlgorithm alg, string name)
    {
        CngKey key = CngKey.Create(alg, name);
        Drop(key);
        key.Export(CngKeyBlobFormat.GenericPublicBlob);
    }
}
