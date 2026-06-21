// BEFORE (buggy). Reduced from ShareX @ ed2a864 —
// ShareX.UploadersLib/FileUploaders/Vault_ooo.cs:216 (the Vault.ooo file uploader's
// DeriveCryptoData), found by mining (docs/notes/real-world-mining.md).
//
// Two crypto IDisposables are created on the upload path and never disposed, both now
// CAUGHT (OWN001):
//   * Rfc2898DeriveBytes — the PBKDF2 deriver, which holds an HMAC (a `new` acquire);
//   * RandomNumberGenerator.Create() — a static crypto FACTORY acquire (the extractor
//     recognises System.Security.Cryptography `Create*` factories that return an
//     IDisposable, alongside `new` and File.Open*/Create*; see notes.md).
//
// It is a genuine oversight, not a deliberate pattern: the sibling EncryptBytes() in
// the same file wraps its aes / MemoryStream / CryptoStream in `using`. The deriver
// does not escape — the returned CryptoData holds only the derived byte[]s — so it is
// a clean local leak. Wrapped in a class so the extractor's per-class flow pass visits
// it; uses the real System.Security.Cryptography types (in the BCL, no ref pack).
using System.Security.Cryptography;

static class VaultCrypto
{
    static CryptoData DeriveCryptoData(byte[] key)
    {
        byte[] salt = new byte[8];
        RandomNumberGenerator rng = RandomNumberGenerator.Create();   // recall gap: factory, not yet flagged
        rng.GetBytes(salt);

        Rfc2898DeriveBytes rfcDeriver =                               // <-- OWN001: never disposed
            new Rfc2898DeriveBytes(key, salt, 10000, HashAlgorithmName.SHA256);
        return new CryptoData
        {
            Salt = salt,
            Key = rfcDeriver.GetBytes(32),   // AES-256 key
            IV = rfcDeriver.GetBytes(16),    // AES-128 block IV
        };
    }

    class CryptoData
    {
        public byte[] Salt;
        public byte[] Key;
        public byte[] IV;
    }
}
