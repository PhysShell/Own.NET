using System.Reflection;
using System.Runtime.ExceptionServices;

// OX-02 (docs/notes/owen-visual-studio-preregistration.md): the extractor as a library.
//
// The extractor is ONE program; this file adds no second frontend. It lets a long-lived host
// (the `owen serve` IDE service) run that same program in its own process, with two
// differences from a command line and none in what is extracted:
//   * the source of a path may come from an in-memory overlay (an IDE's unsaved buffer)
//     instead of the disk — read at the one place the program reads a source file;
//   * stdout/stderr are captured instead of inherited, so nothing the program prints can
//     reach the host's own protocol stream.
// The arguments are the command line's arguments, so a run here and `ownsharp-extract` with
// the same arguments over the same file contents write the same facts, byte for byte
// (tests/check_extractor_in_process.py pins that over the extractor goldens).

partial class Program
{
    /// <summary>Full path -> contents of an unsaved buffer, for the run in progress.</summary>
    internal static IReadOnlyDictionary<string, string>? SourceOverlay;

    internal static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    /// <summary>The overlaid text of <paramref name="path"/>, when an overlay holds it. No
    /// filesystem access: the disk read stays at its one site in the parse loop.</summary>
    static bool TryOverlay(string path, out string text)
    {
        text = "";
        if (SourceOverlay is null || !SourceOverlay.TryGetValue(Path.GetFullPath(path), out var held))
            return false;
        text = held;
        return true;
    }
}

namespace OwnSharp.Extractor
{
    /// <summary>Runs the extractor program inside the calling process.</summary>
    public static class InProcessExtractor
    {
        // The program keeps run state in statics (it resets them at entry) and reads the
        // process's current directory for the paths it reports: one run at a time.
        private static readonly object Gate = new();

        private static readonly MethodInfo Entry =
            typeof(Program).Assembly.EntryPoint
            ?? throw new InvalidOperationException("ownsharp-extract has no entry point");

        /// <summary>
        /// Run <c>ownsharp-extract</c> with <paramref name="args"/> (the command line's own
        /// arguments) in <paramref name="workingDirectory"/>. <paramref name="overlay"/> maps a
        /// full source path to the text to read for it instead of the file. Returns the exit
        /// code and everything the program printed.
        /// </summary>
        public static (int ExitCode, string Output) Run(
            IReadOnlyList<string> args,
            string workingDirectory,
            IReadOnlyDictionary<string, string>? overlay)
        {
            lock (Gate)
            {
                var output = new StringWriter();
                var (stdout, stderr, cwd) = (Console.Out, Console.Error, Environment.CurrentDirectory);
                Program.SourceOverlay = overlay is null
                    ? null
                    : new Dictionary<string, string>(
                        overlay.Select(kv => KeyValuePair.Create(Path.GetFullPath(kv.Key), kv.Value)),
                        Program.PathComparer);
                try
                {
                    Console.SetOut(output);
                    Console.SetError(output);
                    Environment.CurrentDirectory = workingDirectory;
                    var rc = Entry.Invoke(null, [args.ToArray()]);
                    return ((int)rc!, output.ToString());
                }
                catch (TargetInvocationException ex) when (ex.InnerException is not null)
                {
                    ExceptionDispatchInfo.Capture(ex.InnerException).Throw();
                    throw;
                }
                finally
                {
                    Program.SourceOverlay = null;
                    Environment.CurrentDirectory = cwd;
                    Console.SetOut(stdout);
                    Console.SetError(stderr);
                }
            }
        }
    }
}
