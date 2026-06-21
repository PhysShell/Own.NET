# ShareX — `StreamReader` over a stream, never disposed

**Found by mining** `ShareX/ShareX` @ `ed2a864` (the WinForms re-mine — see
`docs/notes/real-world-mining.md`). Location:
`ShareX.HelpersLib/Helpers/Helpers.cs:854`.

## The bug

```csharp
StreamReader sReader = new StreamReader(ms);
return sReader.ReadToEnd();
```

A `StreamReader` is created to read a `MemoryStream` back to a string and is never disposed.
`StreamReader` is `IDisposable` and a **separate** resource from the underlying stream — even
when the stream is `using`-scoped (as it is in the original), the reader itself is left
undisposed. The CA2000 / CodeQL `cs/local-not-disposed` class; low practical impact (the
reader's only unmanaged tie is the stream, already disposed), but a real undisposed
`IDisposable` a strict analyzer flags. The fix is `using` on the reader too.

## What the checker says (real extractor output, `--flow-locals`)

```text
Helpers.cs:854: error: [OWN001] IDisposable local 'sReader' is never disposed
  (leak) [resource: disposable]
```

`acquire` is `new StreamReader(ms)`, the missing `release` is the absent `Dispose()`;
`ReadToEnd()` is a use. The local does not escape (only the returned string does), so it
stays tracked.
