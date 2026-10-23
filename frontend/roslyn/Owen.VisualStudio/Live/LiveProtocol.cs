// OX-02 (docs/notes/owen-visual-studio-preregistration.md §4): the client half of owen-live/1.
// Independent of Visual Studio, so tests/owen-live/LiveClientTests runs it on any OS.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Owen.VisualStudio.Live
{
    /// <summary>One source the editor holds: full path and current text.</summary>
    public sealed class LiveSource
    {
        public LiveSource(string path, string text)
        {
            Path = path;
            Text = text;
        }

        public string Path { get; }

        public string Text { get; }
    }

    /// <summary>A location the core names: the finding's own, or one of its witness steps.</summary>
    public sealed class LiveLocation
    {
        public string File { get; set; } = "";

        public int? Line { get; set; }

        public int? Column { get; set; }

        public string? Message { get; set; }
    }

    /// <summary>One diagnostic, as the service sends it (preregistration §6).</summary>
    public sealed class LiveDiagnostic
    {
        public string Code { get; set; } = "";

        public string Severity { get; set; } = "";

        public string Message { get; set; } = "";

        public string File { get; set; } = "";

        public int? Line { get; set; }

        public int? Column { get; set; }

        /// <summary><c>core</c> (an OWN finding) or <c>host</c> (an OWENB condition).</summary>
        public string Origin { get; set; } = "";

        public List<LiveLocation> Related { get; set; } = new List<LiveLocation>();
    }

    public sealed class LiveResponse
    {
        public long Id { get; set; }

        public string Key { get; set; } = "";

        public long Version { get; set; }

        /// <summary><c>ok</c>, <c>superseded</c>, <c>cancelled</c> or <c>error</c>.</summary>
        public string Status { get; set; } = "";

        public List<LiveDiagnostic> Diagnostics { get; set; } = new List<LiveDiagnostic>();

        public List<string> Extensions { get; set; } = new List<string>();

        public Dictionary<string, long> Timing { get; set; } = new Dictionary<string, long>();
    }

    public sealed class LiveProtocolException : Exception
    {
        public LiveProtocolException(string message)
            : base(message)
        {
        }
    }

    /// <summary><c>Content-Length: n\r\n\r\n</c> + n bytes of UTF-8 JSON, both ways.</summary>
    public static class LiveFrames
    {
        public const string Protocol = "owen-live/1";

        public static void Write(Stream output, JObject message)
        {
            var body = Encoding.UTF8.GetBytes(message.ToString(Formatting.None));
            var header = Encoding.ASCII.GetBytes("Content-Length: " + body.Length + "\r\n\r\n");
            output.Write(header, 0, header.Length);
            output.Write(body, 0, body.Length);
            output.Flush();
        }

        /// <summary>One frame, or null at a clean end of stream between frames.</summary>
        public static JObject? Read(Stream input)
        {
            int? length = null;
            var first = true;
            while (true)
            {
                var line = ReadLine(input, first);
                first = false;
                if (line == null)
                    return null;
                if (line.Length == 0)
                    break;
                const string prefix = "Content-Length: ";
                if (!line.StartsWith(prefix, StringComparison.Ordinal)
                    || !int.TryParse(line.Substring(prefix.Length), System.Globalization.NumberStyles.None,
                        System.Globalization.CultureInfo.InvariantCulture, out var n))
                    throw new LiveProtocolException("malformed frame header '" + line + "'");
                length = n;
            }
            if (length == null)
                throw new LiveProtocolException("a frame without Content-Length");
            var body = new byte[length.Value];
            var read = 0;
            while (read < body.Length)
            {
                var got = input.Read(body, read, body.Length - read);
                if (got == 0)
                    throw new LiveProtocolException("the stream closed inside a frame body");
                read += got;
            }
            try
            {
                return JObject.Parse(Encoding.UTF8.GetString(body));
            }
            catch (JsonException ex)
            {
                throw new LiveProtocolException("a frame body that is not a JSON object: " + ex.Message);
            }
        }

        private static string? ReadLine(Stream input, bool atFrameStart)
        {
            var bytes = new List<byte>();
            while (true)
            {
                var b = input.ReadByte();
                if (b < 0)
                {
                    if (bytes.Count == 0 && atFrameStart)
                        return null;
                    throw new LiveProtocolException("the stream closed inside a frame header");
                }
                if (b == '\n')
                {
                    if (bytes.Count == 0 || bytes[bytes.Count - 1] != '\r')
                        throw new LiveProtocolException("a frame header line not ended by CRLF");
                    bytes.RemoveAt(bytes.Count - 1);
                    return Encoding.ASCII.GetString(bytes.ToArray());
                }
                if (bytes.Count > 1024)
                    throw new LiveProtocolException("a frame header line longer than 1024 bytes");
                bytes.Add((byte)b);
            }
        }

        public static JObject Hello() => new JObject { ["type"] = "hello", ["protocol"] = Protocol };

        public static JObject Analyze(long id, string key, long version, string request,
            IEnumerable<LiveSource> documents, IEnumerable<LiveSource> generated)
        {
            JArray Sources(IEnumerable<LiveSource> sources)
            {
                var array = new JArray();
                foreach (var s in sources)
                    array.Add(new JObject { ["path"] = s.Path, ["text"] = s.Text });
                return array;
            }
            return new JObject
            {
                ["type"] = "analyze",
                ["id"] = id,
                ["key"] = key,
                ["version"] = version,
                ["request"] = request,
                ["documents"] = Sources(documents),
                ["generated"] = Sources(generated),
            };
        }

        public static LiveResponse Response(JObject frame)
        {
            var response = frame.ToObject<LiveResponse>(JsonSerializer.Create(new JsonSerializerSettings
            {
                ContractResolver = new Newtonsoft.Json.Serialization.DefaultContractResolver
                {
                    NamingStrategy = new Newtonsoft.Json.Serialization.SnakeCaseNamingStrategy(),
                },
                MissingMemberHandling = MissingMemberHandling.Ignore,
            }));
            return response ?? throw new LiveProtocolException("an empty result");
        }
    }

    /// <summary>The project's <c>obj/owen/live.txt</c>, written by Owen.Build (preregistration §3).</summary>
    public sealed class LiveRequestFile
    {
        private LiveRequestFile(string path, string host, string? dotnet, string? project)
        {
            Path = path;
            Host = host;
            Dotnet = dotnet;
            Project = project;
        }

        public string Path { get; }

        /// <summary>The Owen.Build package's <c>ownsharp.dll</c>: the service.</summary>
        public string Host { get; }

        /// <summary>The muxer MSBuild ran with, when it said.</summary>
        public string? Dotnet { get; }

        public string? Project { get; }

        /// <summary>Where a project's live request is: <c>obj/owen/live.txt</c> beside it.</summary>
        public static string For(string projectFile) =>
            System.IO.Path.Combine(System.IO.Path.GetDirectoryName(projectFile) ?? "", "obj", "owen", "live.txt");

        public static LiveRequestFile? TryRead(string path)
        {
            if (!File.Exists(path))
                return null;
            string? host = null, dotnet = null, project = null;
            foreach (var raw in File.ReadAllLines(path))
            {
                var tab = raw.IndexOf('\t');
                if (tab <= 0)
                    continue;
                var key = raw.Substring(0, tab);
                var value = raw.Substring(tab + 1).Trim();
                if (value.Length == 0)
                    continue;
                if (key == "host")
                    host = value;
                else if (key == "dotnet")
                    dotnet = value;
                else if (key == "project")
                    project = value;
            }
            return host == null ? null : new LiveRequestFile(path, host, dotnet, project);
        }
    }
}
