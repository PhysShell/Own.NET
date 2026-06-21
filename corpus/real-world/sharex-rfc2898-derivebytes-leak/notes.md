# ShareX — `Rfc2898DeriveBytes` (PBKDF2 deriver) created on the upload path, never disposed

**Found by mining** `ShareX/ShareX` @ `ed2a864` (the re-mine after the WinForms
modeless-`Form` precision fix, #57 — see `docs/notes/real-world-mining.md` and
`docs/notes/winforms-modeless-precision.md`). Once the dominant modeless-`Form` false
positives were gone, the local-disposable findings dropped to a short, mostly-real
list; this is the cleanest real bug in it.

Location: `ShareX.UploadersLib/FileUploaders/Vault_ooo.cs:216`, the Vault.ooo file
uploader's `DeriveCryptoData`.

## The bug

```csharp
private static Vault_oooCryptoData DeriveCryptoData(byte[] key)
{
    byte[] salt = new byte[8];
    RandomNumberGenerator rng = RandomNumberGenerator.Create();   // leak #2 (factory)
    rng.GetBytes(salt);

    Rfc2898DeriveBytes rfcDeriver =                               // leak #1 (new) — flagged
        new Rfc2898DeriveBytes(key, salt, PBKDF2_ITERATIONS, HashAlgorithmName.SHA256);

    return new Vault_oooCryptoData { Salt = salt,
        Key = rfcDeriver.GetBytes(32), IV = rfcDeriver.GetBytes(16) };
}
```

`Rfc2898DeriveBytes` is `IDisposable` and holds an internal HMAC. It is created to
derive the AES key + IV, the method returns, and it is **never disposed** — a real
resource leak on every Vault.ooo upload. The returned `Vault_oooCryptoData` holds only
the derived `byte[]`s (Salt/Key/IV), **not** the deriver, so it does not escape: it is
a clean, method-local leak. The correct fix is `using var rfcDeriver = …`, which is
exactly what the sibling `EncryptBytes()` in the same file already does for its `aes` /
`MemoryStream` / `CryptoStream` — so this is an accidental oversight, not a pattern.

## What the checker says (real extractor output, `--flow-locals`)

```text
Vault_ooo.cs:216: error: [OWN001] IDisposable local 'rfcDeriver' is never disposed
  (leak) [resource: disposable]
```

`acquire` is the `new Rfc2898DeriveBytes(…)`, the missing `release` is the absent
`Dispose()`. Because the deriver is never released on any path the wording is
"is never disposed" (vs the partial-path "may not be disposed on every path").

## The second leak — also caught (crypto owning-factory)

`DeriveCryptoData` leaks **two** crypto disposables: `rfcDeriver` (acquired via `new`)
and `rng = RandomNumberGenerator.Create()` (acquired via a static **factory**). The flow
detector now catches both — `IsOwningFactory` recognises the
`System.Security.Cryptography` static `Create*` factories that return an `IDisposable`
(`RandomNumberGenerator.Create()`, `SHA256.Create()`, `Aes.Create()`, …) alongside `new`
and the `System.IO.File.Open*/Create*` factories. (Originally `rng` was a documented
recall gap; the crypto owning-factory slice closed it.) `after.cs` disposes both, so the
fix is genuinely clean.

## Files

- `before.cs` — the leak, reduced and self-contained (real `System.Security.Cryptography`
  types; no reference pack needed). The extractor catches `rfcDeriver` (OWN001).
- `after.cs` — both crypto disposables scoped with `using` → silent.
- `case.own` — the OwnLang reduction (disposable acquire with no release → OWN001),
  checked by `tests/test_corpus.py`.
