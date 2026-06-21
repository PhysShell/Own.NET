// AFTER (fixed): dispose both crypto IDisposables. The PBKDF2 deriver and the RNG are
// scoped with `using`, exactly how the sibling EncryptBytes() already handles its aes /
// MemoryStream / CryptoStream. Both are released on every path (the Key/IV are derived
// before the deriver's scope ends), so the flow detector stays silent.
using System.Security.Cryptography;

static class VaultCrypto
{
    static CryptoData DeriveCryptoData(byte[] key)
    {
        byte[] salt = new byte[8];
        using var rng = RandomNumberGenerator.Create();
        rng.GetBytes(salt);

        using var rfcDeriver = new Rfc2898DeriveBytes(key, salt, 10000, HashAlgorithmName.SHA256);
        return new CryptoData
        {
            Salt = salt,
            Key = rfcDeriver.GetBytes(32),
            IV = rfcDeriver.GetBytes(16),
        };
    }

    class CryptoData
    {
        public byte[] Salt;
        public byte[] Key;
        public byte[] IV;
    }
}
