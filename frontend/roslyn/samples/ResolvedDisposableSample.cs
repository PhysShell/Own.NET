using System.Data;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Own.Samples;

// P-004 resolve-aware disposability (mined: ImageSharp Vp8BitWriter / JpegBitReader).
//
// A field whose type NAME ends in Writer/Reader/Stream but does NOT actually implement
// IDisposable must NOT be flagged: the field-disposable detector now asks the RESOLVED
// type's real interface, not the name. The IDisposable control must still warn, proving
// real detection is intact (and the name heuristic still covers UNRESOLVED types, which
// the existing WPF samples exercise).

// Resolved, NOT IDisposable, name ends in "Writer" (like ImageSharp's Vp8BitWriter).
public sealed class FancyBitWriter
{
    public void Write(int x) { }
}

// Resolved, NOT IDisposable, a struct named "...Reader" (like ImageSharp's JpegBitReader).
public struct TokenReader
{
    public int Position;
}

public sealed class EncoderWithNonDisposableWriter
{
    private readonly FancyBitWriter writer = new();   // resolved, not IDisposable -> SILENT
    private TokenReader reader = new();                // resolved struct, not IDisposable -> SILENT

    public void Encode() => this.writer.Write(this.reader.Position);
}

// Control: resolved IDisposable fields the class new's but never disposes -> must WARN.
public sealed class HolderWithRealDisposable
{
    private readonly MemoryStream stream = new();              // MemoryStream IS IDisposable
    private readonly CancellationTokenSource cts = new();      // CancellationTokenSource IS IDisposable

    public long Use() => this.stream.Length + this.cts.Token.GetHashCode();
}

// Dispose-optional control (Codex): Task and DataTable ARE IDisposable, but disposal is
// conventionally optional (IsDisposeOptional) — a `new`'d, undisposed field of these must
// stay SILENT even though it resolves as IDisposable.
public sealed class HolderWithDisposeOptional
{
    private readonly Task task = new(() => { });   // Task: IDisposable but dispose-optional
    private readonly DataTable table = new();       // DataTable: IDisposable but dispose-optional

    public int Use() => this.task.Id + this.table.Columns.Count;
}
