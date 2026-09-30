// ownership-semantics-lab: assembly identity facets, one JSON line per input DLL (metadata only; nothing is executed).
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

foreach (var path in args)
{
    using var stream = File.OpenRead(path);
    using var pe = new PEReader(stream);
    var md = pe.GetMetadataReader();
    var asm = md.GetAssemblyDefinition();
    var pk = md.GetBlobBytes(asm.PublicKey);
    string? token = null;
    if (pk.Length > 0)
    {
        var hash = SHA1.HashData(pk);
        token = Convert.ToHexString(hash[^8..].Reverse().ToArray()).ToLowerInvariant();
    }
    var mvid = md.GetGuid(md.GetModuleDefinition().Mvid);
    string? tfm = null, infoVersion = null;
    foreach (var h in md.CustomAttributes)
    {
        var ca = md.GetCustomAttribute(h);
        if (ca.Constructor.Kind != HandleKind.MemberReference) continue;
        var mr = md.GetMemberReference((MemberReferenceHandle)ca.Constructor);
        if (mr.Parent.Kind != HandleKind.TypeReference) continue;
        var tn = md.GetString(md.GetTypeReference((TypeReferenceHandle)mr.Parent).Name);
        if (tn is "TargetFrameworkAttribute" or "AssemblyInformationalVersionAttribute")
        {
            var blob = md.GetBlobReader(ca.Value);
            blob.ReadUInt16();
            var s = blob.ReadSerializedString();
            if (tn == "TargetFrameworkAttribute") tfm = s; else infoVersion = s;
        }
    }
    stream.Position = 0;
    var sha = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        path, name = md.GetString(asm.Name), version = asm.Version.ToString(),
        culture = md.GetString(asm.Culture), public_key_token = token, mvid = mvid.ToString(),
        target_framework = tfm, informational_version = infoVersion, sha256 = sha, size = stream.Length,
    }));
}
