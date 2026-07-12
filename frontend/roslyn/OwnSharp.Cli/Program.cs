// owen — the single command for alpha gate A (issue #202), public facade
// "Owen" (see docs/notes/owen-public-facade.md). The underlying project/
// namespace stays OwnSharp.Cli internally -- this is a public-facing rename,
// not an internal refactor.
//
// `owen check <path|.sln>` wraps the two existing pipeline stages —
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
    Console.Error.WriteLine($"owen: unknown command '{args[0]}'");
    Console.Error.WriteLine(HelpText());
    return 2;
}

return await CheckCommand.RunAsync(args[1..]).ConfigureAwait(false);

// Product framing is deliberately language-neutral (Owen finds lifetime and
// resource-contract bugs; the OwnIR/core layer is not C#-specific) while the
// "Included frontend" line is explicit about what THIS distribution actually
// wires up today -- no plugin framework, no speculative TypeScript claim.
static string HelpText() => """
    owen — finds lifetime and resource-contract bugs.
    This distribution currently includes the .NET/C# frontend.

    Included frontend:
      .NET / C# (.cs, .csproj, .sln)

    Usage:
      owen check <path|.sln|.csproj> [more paths...] [options]
      owen --version
      owen --help

    Options (mirrors scripts/own-check.sh):
      --format {human|github|msbuild|sarif}   finding surface (default: human)
      --severity {error|warning}               how findings are shown (default: error)
      --fail-on-finding                        exit with the core's code (1 = findings) instead of always 0
      --emit-facts <path>                      also write the intermediate OwnIR facts.json here
      --legacy                                 use the flat name-based local-IDisposable detector
      --stats                                  print flow-locals coverage to stderr
      --body-throw-edges                       opt-in: flag body-level (no-try) dispose-not-called-on-throw

    Python: resolved via OWEN_PYTHON (OWN_PYTHON is a deprecated, temporary
    fallback), else `py -3` (Windows) / `python3` (elsewhere); must be
    >=3.11. No auto-install — see the error message if none is found.

    Input that doesn't match the included frontend (e.g. no .cs/.csproj/.sln
    found anywhere given) fails explicitly (exit 4) rather than reporting a
    clean scan.
    """;
