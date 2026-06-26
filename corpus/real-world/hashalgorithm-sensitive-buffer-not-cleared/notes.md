# HashAlgorithm sensitive ArrayPool buffer not cleared on return

**Source.** [dotnet/runtime#71249](https://github.com/dotnet/runtime/issues/71249)
— `System.Security.Cryptography.HashAlgorithm` (`ComputeHashAsyncCore`). A replay
target named in [P-007](../../../docs/proposals/P-007-arraypool-span.md):
*dotnet/runtime* pooled-buffer handling.

**Pattern.** The method `Rent`s an `ArrayPool<byte>.Shared` buffer to stage the bytes
being hashed, then `Return`s it with **`clearArray: false`**. The pooled array still
holds the (sensitive) input, which the next renter can read — an information
disclosure. (#71249 also flags a *leak* on the exception/cancellation path; this case
models the **not-zeroed** aspect.) The fix returns with `clearArray: true` /
`CryptographicOperations.ZeroMemory`, in a `finally` so it runs even on a throw.

**What the checker says.** The OwnLang reduction models the pooled buffer as
`Buffer.pooled(n, sensitive = true)` and trips **OWN024** (a buffer marked sensitive
is not cleared on release). `clear = true` is `clearArray: true` / `ZeroMemory`.

```text
$ python -m ownlang check corpus/real-world/hashalgorithm-sensitive-buffer-not-cleared/case.own
case.own:10: error: [OWN024] buffer is marked sensitive but is not cleared on release; add 'clear = true' so its bytes are zeroed before the backing memory is reused
```

**Honesty / scope.** `case.own` is a *hand reduction*. The `sensitive` intent is
explicit in the model; the C# extractor does **not** infer "this pooled buffer holds
secret data" from arbitrary code (that needs an annotation), so `before.cs` is a
benchmark *recall miss* — recall is a tracked floor, not a per-case gate — while the
fixed `after.cs` is silent (specificity, which is absolute). The value here is pinning
the security *logic* (sensitive-buffer-not-cleared = OWN024) as a regression and
recording the first real-world OWN024 anchor, sourced from the canonical crypto-stack
case. The async/cancellation *leak* aspect of #71249 is out of scope for this case
(OwnLang rejects `async`); it is the leak class already covered by
`nethermind-patriciatree-arraypool-leak` (OWN001). `before.cs` / `after.cs` are reduced
(helpers stubbed), not a verbatim copy.
