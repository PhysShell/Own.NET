using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace OwnSharp.Cli;

/// <summary>
/// `owen serve` — the live Owen service for an IDE (OX-02,
/// docs/notes/owen-visual-studio-preregistration.md §4–§5). Long-lived: started once by
/// <c>Owen.VisualStudio</c>, it answers analysis requests over its stdin/stdout until told to
/// shut down or until its stdin closes. Not a user verb.
///
/// <para><b>Protocol <c>owen-live/1</c>.</b> Every message, both ways, is
/// <c>Content-Length: n\r\n\r\n</c> followed by n bytes of UTF-8 JSON. Nothing else is ever
/// written to stdout (the console is redirected to stderr before anything can print). The
/// first client message is <c>hello</c> naming this protocol. A malformed frame, a body that is
/// not a JSON object, an unknown <c>type</c> or another protocol is fatal: one <c>fatal</c>
/// frame, the reason on stderr, exit 3 — never a guess, never a resynchronisation.</para>
///
/// <para><b>Order.</b> Analyses run one at a time, in arrival order. A queued request whose key
/// has a newer queued request is answered <c>superseded</c> without running; <c>cancel</c> of a
/// queued request answers <c>cancelled</c>. A running analysis completes (the extractor is not
/// cancellable); the client publishes a result only for the latest version it issued.</para>
/// </summary>
internal static class ServeCommand
{
    public const string Protocol = "owen-live/1";
    public const int ProtocolError = 3;
    private const int MaxFrame = 256 * 1024 * 1024;

    private sealed record Pending(long Id, string Key, long Version, string Request,
        IReadOnlyList<LiveDocument> Documents, IReadOnlyList<LiveDocument> Generated);

    private sealed class ProtocolException(string message) : Exception(message);

    public static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 0)
        {
            Console.Error.WriteLine("usage: owen serve   (started by an IDE; speaks owen-live/1 on stdin/stdout)");
            return 2;
        }
        var input = new BufferedStream(Console.OpenStandardInput());
        var output = Console.OpenStandardOutput();
        // stdout carries frames and nothing else: anything printed from here on goes to stderr
        Console.SetOut(Console.Error);
        var writeGate = new object();
        void Send(object message)
        {
            var body = JsonSerializer.SerializeToUtf8Bytes(message);
            var header = Encoding.ASCII.GetBytes($"Content-Length: {body.Length}\r\n\r\n");
            lock (writeGate)
            {
                output.Write(header);
                output.Write(body);
                output.Flush();
            }
        }
        int Fatal(string reason)
        {
            Console.Error.WriteLine($"owen serve: fatal: {reason}");
            try { Send(new { type = "fatal", message = reason }); } catch (IOException) { /* the client is gone */ }
            return ProtocolError;
        }

        var pending = new List<Pending>();
        var signal = new SemaphoreSlim(0);
        var stop = new CancellationTokenSource();
        var worker = Task.Run(async () =>
        {
            while (!stop.IsCancellationRequested)
            {
                try { await signal.WaitAsync(stop.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) { return; }
                Pending? next;
                lock (pending)
                {
                    if (pending.Count == 0)
                        continue;
                    next = pending[0];
                    pending.RemoveAt(0);
                }
                Send(await AnswerAsync(next).ConfigureAwait(false));
                // Each analysis builds a whole compilation (metadata for every reference); collect
                // it now, between answers, rather than in the middle of the next one.
                GC.Collect();
                GC.WaitForPendingFinalizers();
                GC.Collect();
            }
        });

        try
        {
            var hello = ReadFrame(input) ?? throw new ProtocolException("stdin closed before hello");
            if (Type(hello) != "hello" || Str(hello, "protocol") != Protocol)
                throw new ProtocolException($"the first message must be {{\"type\":\"hello\",\"protocol\":\"{Protocol}\"}}");
            Send(new
            {
                type = "hello",
                protocol = Protocol,
                host = ToolVersion.Current,
                capabilities = OwenHost.Capabilities,
            });

            while (true)
            {
                if (ReadFrame(input) is not { } message)
                    return 0;   // the IDE closed our stdin: it is gone, so are we
                switch (Type(message))
                {
                    case "analyze":
                        var request = new Pending(
                            Long(message, "id"), Str(message, "key"), Long(message, "version"), Str(message, "request"),
                            Documents(message, "documents"), Documents(message, "generated"));
                        lock (pending)
                        {
                            foreach (var older in pending.Where(p => p.Key == request.Key).ToList())
                            {
                                pending.Remove(older);
                                Send(Answer(older, "superseded"));
                            }
                            pending.Add(request);
                        }
                        signal.Release();
                        break;
                    case "cancel":
                        var id = Long(message, "id");
                        lock (pending)
                        {
                            var queued = pending.FirstOrDefault(p => p.Id == id);
                            if (queued is not null)
                            {
                                pending.Remove(queued);
                                Send(Answer(queued, "cancelled"));
                            }
                        }
                        break;
                    case "shutdown":
                        return 0;
                    case var other:
                        throw new ProtocolException($"unknown message type '{other}'");
                }
            }
        }
        catch (ProtocolException ex)
        {
            return Fatal(ex.Message);
        }
        finally
        {
            stop.Cancel();
        }
    }

    private static object Answer(Pending p, string status) => new
    {
        type = "result",
        id = p.Id,
        key = p.Key,
        version = p.Version,
        status,
        diagnostics = Array.Empty<object>(),
        extensions = Array.Empty<string>(),
        timing = new Dictionary<string, long>(),
    };

    private static async Task<object> AnswerAsync(Pending p)
    {
        var clock = Stopwatch.StartNew();
        try
        {
            var result = await LiveAnalysis.RunAsync(p.Request, p.Documents, p.Generated).ConfigureAwait(false);
            return new
            {
                type = "result",
                id = p.Id,
                key = p.Key,
                version = p.Version,
                status = "ok",
                diagnostics = result.Diagnostics.Select(d => new
                {
                    code = d.Code,
                    severity = d.Severity,
                    message = d.Message,
                    file = d.File,
                    line = d.Line,
                    column = d.Column,
                    origin = d.Origin,
                    related = d.Related.Select(r => new { file = r.File, line = r.Line, column = r.Column, message = r.Message }),
                }),
                extensions = result.Extensions,
                timing = result.TimingMs,
            };
        }
        catch (Exception ex)
        {
            // an analysis that blew up is answered, never dropped: the IDE shows it
            Console.Error.WriteLine($"owen serve: analysis {p.Id} failed: {ex}");
            return new
            {
                type = "result",
                id = p.Id,
                key = p.Key,
                version = p.Version,
                status = "error",
                diagnostics = new[]
                {
                    new
                    {
                        code = "OWENB012", severity = "error",
                        message = $"the live analysis failed internally: {ex.GetType().Name}: {OwenHost.OneLine(ex.Message)}",
                        file = p.Key, line = (int?)null, column = (int?)null, origin = "host",
                        related = Array.Empty<object>(),
                    },
                },
                extensions = Array.Empty<string>(),
                timing = new Dictionary<string, long> { ["total"] = clock.ElapsedMilliseconds },
            };
        }
    }

    // ---- frames ---------------------------------------------------------------------------------

    /// <summary>One frame, or null at a clean end of stream (between frames).</summary>
    private static JsonElement? ReadFrame(Stream input)
    {
        int? length = null;
        var sawAny = false;
        while (true)
        {
            var line = ReadHeaderLine(input, ref sawAny);
            if (line is null)
                return sawAny ? throw new ProtocolException("stdin closed inside a frame header") : null;
            if (line.Length == 0)
                break;
            const string prefix = "Content-Length: ";
            if (!line.StartsWith(prefix, StringComparison.Ordinal)
                || !int.TryParse(line.AsSpan(prefix.Length), System.Globalization.NumberStyles.None,
                    System.Globalization.CultureInfo.InvariantCulture, out var n)
                || n < 0 || n > MaxFrame || length is not null)
                throw new ProtocolException($"malformed frame header '{line}'");
            length = n;
        }
        if (length is null)
            throw new ProtocolException("a frame without Content-Length");
        var body = new byte[length.Value];
        var read = 0;
        while (read < body.Length)
        {
            var got = input.Read(body, read, body.Length - read);
            if (got == 0)
                throw new ProtocolException($"stdin closed inside a {length} byte frame body");
            read += got;
        }
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
                throw new ProtocolException("a frame body that is not a JSON object");
            return doc.RootElement.Clone();
        }
        catch (JsonException ex)
        {
            throw new ProtocolException($"a frame body that is not JSON: {ex.Message}");
        }
    }

    private static string? ReadHeaderLine(Stream input, ref bool sawAny)
    {
        var bytes = new List<byte>();
        while (true)
        {
            var b = input.ReadByte();
            if (b < 0)
                return bytes.Count == 0 && !sawAny ? null : throw new ProtocolException("stdin closed inside a frame header");
            sawAny = true;
            if (b == '\n')
            {
                if (bytes.Count == 0 || bytes[^1] != '\r')
                    throw new ProtocolException("a frame header line not ended by CRLF");
                bytes.RemoveAt(bytes.Count - 1);
                return Encoding.ASCII.GetString(bytes.ToArray());
            }
            if (bytes.Count > 1024)
                throw new ProtocolException("a frame header line longer than 1024 bytes");
            bytes.Add((byte)b);
        }
    }

    private static string Type(JsonElement m) => Str(m, "type");

    private static string Str(JsonElement m, string name) =>
        m.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()!
            : throw new ProtocolException($"'{name}' must be a string");

    private static long Long(JsonElement m, string name) =>
        m.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt64(out var n)
            ? n
            : throw new ProtocolException($"'{name}' must be an integer");

    private static List<LiveDocument> Documents(JsonElement m, string name)
    {
        if (!m.TryGetProperty(name, out var v))
            return [];
        if (v.ValueKind != JsonValueKind.Array)
            throw new ProtocolException($"'{name}' must be an array");
        return v.EnumerateArray().Select(d => new LiveDocument(Str(d, "path"), Str(d, "text"))).ToList();
    }
}
