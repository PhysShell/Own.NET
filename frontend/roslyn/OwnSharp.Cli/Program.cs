// ownsharp — the single command for alpha gate A (issue #202).
//
// `ownsharp check <path|.sln>` wraps the two existing pipeline stages —
// extractor -> core — into one `dotnet tool install`. This file only does
// verb dispatch; the real work is in CheckCommand.cs / PythonResolver.cs /
// CoreVendor.cs. No analysis logic lives here or anywhere in this project:
// packaging only, per the guardrail in issue #202.

using OwnSharp.Cli;

if (args.Length == 0 || args[0] is "-h" or "--help")
{
    Console.WriteLine(HelpText());
    return args.Length == 0 ? 2 : 0;
}

if (args[0] is "--version")
{
    Console.WriteLine(ToolVersion.Current);
    return 0;
}

if (args[0] != "check")
{
    Console.Error.WriteLine($"ownsharp: unknown command '{args[0]}'");
    Console.Error.WriteLine(HelpText());
    return 2;
}

return await CheckCommand.RunAsync(args[1..]).ConfigureAwait(false);

static string HelpText() => """
    ownsharp — find lifetime/resource bugs in C# (Own.NET)

    Usage:
      ownsharp check <path|.sln|.csproj> [more paths...] [options]
      ownsharp --version
      ownsharp --help

    Options (mirrors scripts/own-check.sh):
      --format {human|github|msbuild|sarif}   finding surface (default: human)
      --severity {error|warning}               how findings are shown (default: error)
      --fail-on-finding                        exit with the core's code (1 = findings) instead of always 0
      --emit-facts <path>                      also write the intermediate OwnIR facts.json here
      --legacy                                 use the flat name-based local-IDisposable detector
      --stats                                  print flow-locals coverage to stderr
      --body-throw-edges                       opt-in: flag body-level (no-try) dispose-not-called-on-throw

    Python: resolved via OWN_PYTHON, else `py -3` (Windows) / `python3`
    (elsewhere); must be >=3.11. No auto-install — see the error message if
    none is found.
    """;
