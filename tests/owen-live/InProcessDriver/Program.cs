// jobs file: one JSON object per line
//   {"cwd": "...", "args": ["..."], "overlay": {"<full path>": "<file holding the text>"}}
// prints one JSON line per job: {"rc": n, "output": "..."}
using System.Text.Json;
using OwnSharp.Extractor;

foreach (var line in File.ReadLines(args[0]))
{
    if (line.Length == 0)
        continue;
    using var job = JsonDocument.Parse(line);
    var root = job.RootElement;
    var jobArgs = root.GetProperty("args").EnumerateArray().Select(a => a.GetString()!).ToList();
    Dictionary<string, string>? overlay = null;
    if (root.TryGetProperty("overlay", out var o))
        overlay = o.EnumerateObject().ToDictionary(p => p.Name, p => File.ReadAllText(p.Value.GetString()!));
    var (rc, output) = InProcessExtractor.Run(jobArgs, root.GetProperty("cwd").GetString()!, overlay);
    Console.WriteLine(JsonSerializer.Serialize(new { rc, output }));
}
