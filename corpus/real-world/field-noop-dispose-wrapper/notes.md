# field-noop-dispose-wrapper

An owned `IDisposable` field whose `Dispose()` releases **nothing real**, because it is a
BCL pass-through reader/writer wrapping an **in-memory** backing. Generalises the existing
`StringWriter` / `StringReader` no-op exemption (`IsDisposeOptional`) to the wrapper case:
a `StreamReader` / `StreamWriter` / `BinaryReader` / `BinaryWriter` constructed over a
`MemoryStream` / `StringWriter` / `StringReader` cascades its disposal only to that
managed-memory backing.

- **before.cs** — a `StreamReader` field over a real `FileStream` (an OS handle), never
  disposed → `OWN001` (the bug is caught; the backing is **not** in-memory, so the no-op
  exemption must not apply).
- **after.cs** — a `StreamReader` field over a `MemoryStream`, never disposed → **clean**.
  The wrapper's disposal is a no-op, so leaving it undisposed is not a leak.

## Recognition rule

The field-disposal scan exempts a field when **every** construction of it is a no-op
wrapper (`IsNoOpDisposeWrapper`): the constructed type is one of the four BCL pass-through
adapters (`StreamReader` / `StreamWriter` / `BinaryReader` / `BinaryWriter`, namespace
`System.IO`) **and** its first constructor argument resolves to an in-memory
dispose-optional backing (`MemoryStream` / `StringWriter` / `StringReader`). Requiring
*all* constructions to qualify keeps it sound: a field also assigned `new StreamReader(
path)` (which opens a real `FileStream`) on some path still leaks.

The allowlist is deliberately **closed** to those four types. Other BCL streams that also
wrap a stream — `GZipStream`, `DeflateStream`, `CryptoStream` — own their *own* extra
resource (a native deflater, a crypto transform), so they are **not** exempt.

## Honesty caveat — what this does and does not reach

This does **not** clear the motivating oracle finding it was inspired by — Newtonsoft.Json's
`TraceJsonReader._textWriter`, a `JsonTextWriter` over a `StringWriter`. `JsonTextWriter` is
a **third-party** wrapper: structurally the same no-op, but we cannot prove *its* `Dispose`
is pass-through without modelling its body, so suppressing it would be unsound. That finding
stays in `corpus/oracle-fp-baseline.txt`. Only the BCL pass-through adapters, whose
disposal contract is known, are exempted here. Full rationale:
[`../../../docs/notes/no-op-dispose-wrapper.md`](../../../docs/notes/no-op-dispose-wrapper.md).
