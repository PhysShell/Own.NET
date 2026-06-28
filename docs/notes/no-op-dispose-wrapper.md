# No-op-dispose wrappers — BCL pass-through readers/writers over in-memory backings

Companion to [`cts-field-dispose-optional.md`](cts-field-dispose-optional.md) and the
"No-op `Dispose` not modelled" root-cause in
[`oracle-known-fps.md`](oracle-known-fps.md). Records the extractor's recognition that an
owned `IDisposable` **field** whose `Dispose()` provably frees nothing real is not a leak.

## The shape

`IsDisposeOptional` already exempts `StringWriter` / `StringReader` fields: those wrap a
`StringBuilder` / a string and hold no OS handle, so an undisposed one leaks nothing. The
same is true one level up — a **pass-through wrapper** built over an in-memory backing:

```csharp
readonly StreamReader _reader = new StreamReader(new MemoryStream(data)); // no-op dispose
```

`StreamReader`'s `Dispose()` only cascades to the `MemoryStream`, which is managed memory,
so disposing the whole chain frees nothing and leaving `_reader` undisposed is not a leak.

## The rule (`IsNoOpDisposeWrapper`)

A field is exempt when **every** construction of it is a no-op wrapper:

1. the constructed type is one of exactly two BCL **read-only** pass-through adapters —
   `StreamReader` or `BinaryReader` (namespace `System.IO`); **and**
2. its **first** constructor argument resolves to an in-memory dispose-optional backing —
   `MemoryStream`, `StringWriter`, or `StringReader` (`IsInMemoryDisposableBacking`).

Requiring *all* constructions to qualify keeps it sound: a field also assigned
`new StreamReader(path)` on some path opens a real `FileStream`, so it still leaks.

### Why readers only — writers are NOT a no-op

`StreamWriter` and `BinaryWriter` are deliberately **excluded**. A writer's `Dispose`
**flushes** buffered output to the underlying stream (documented behaviour), so a
never-disposed writer field can leave even an in-memory backing missing buffered
characters / encoder state — a real **correctness** bug, not a managed-memory-only no-op.
The `OWN001` on an undisposed writer is therefore worth keeping (Codex P2 on the first
cut, which included writers). Only the read-only adapters — whose `Dispose` just discards
a managed read-ahead buffer and closes the (in-memory) backing — are genuinely no-op.

### Why a closed allowlist, not "any BCL stream wrapper"

`GZipStream`, `DeflateStream`, and `CryptoStream` also wrap a stream, but each owns its
**own** extra resource (a native deflater, a crypto transform) whose `Dispose` is not a
no-op. So the allowlist is deliberately the two read-only adapters, never "any `Stream`
subtype". The first-argument check is on the backing *type*, so a string path
(`new StreamReader("file.txt")`, which opens a `FileStream`) and a real-stream backing
(`new StreamReader(fileStream)`) both fail it and correctly keep leaking.

## The soundness wall — what this deliberately does NOT clear

The motivating oracle finding was Newtonsoft.Json's `TraceJsonReader._textWriter`:

```csharp
_sw = new StringWriter(CultureInfo.InvariantCulture);
_textWriter = new JsonTextWriter(_sw); // a no-op in truth — but JsonTextWriter is third-party
```

Structurally identical, but `JsonTextWriter` is a **third-party** wrapper (`JsonWriter`,
not a BCL `TextWriter`). We cannot prove *its* `Dispose` is pass-through without modelling
its body — and asserting a no-op we cannot prove is exactly the unsound over-reach that
sank the static-class subscriber exemption (see
[`oracle-known-fps.md` → Rejected approaches](oracle-known-fps.md)). So Newtonsoft's
`_textWriter` stays a **baselined** finding in
[`oracle-fp-baseline.txt`](../../corpus/oracle-fp-baseline.txt), not a silent drop.

Retiring that baseline entry would need a general, recursive "Dispose is a no-op"
analysis over a first-party type's body (it disposes only dispose-optional members and
holds no unmanaged handle). That is a larger, higher-risk capability; until it lands, only
the BCL pass-through adapters — whose disposal contract is documented and fixed — are
exempted.

## Corpus

[`corpus/real-world/field-noop-dispose-wrapper`](../../corpus/real-world/field-noop-dispose-wrapper/notes.md):
before.cs (StreamReader over a real `FileStream` → `OWN001`) vs after.cs (StreamReader
over a `MemoryStream` → clean) — proving the exemption is narrow enough to keep the
file-handle leak visible.
