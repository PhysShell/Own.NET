namespace OwnSharp.Cli;

/// <summary>
/// Which analysis engine `owen check` runs (#262 D1). The selector belongs to
/// the LAUNCHER and only to the launcher: `own-cli` presents one engine and
/// knows nothing of Python (#261 C-4), so nothing here is ever forwarded to it
/// as an engine flag.
/// </summary>
internal enum Engine
{
    /// <summary>The vendored Python core. Stage-1 default and the reference.</summary>
    Python,

    /// <summary>The Rust core (`own-cli ownir`), opt-in at Stage 1.</summary>
    Rust,

    /// <summary>Both engines over one captured input, compared (D4/D4.1).</summary>
    Compare,
}

/// <summary>
/// Parsing and the shared exit-code contract for the selected engine.
///
/// <para><b>Python is the Stage-1 default</b> (D1) and this type is where that
/// is written down once: <see cref="Default"/> is the single place a reader —
/// or a mutation — can move it, which is what makes the "the default silently
/// became Rust" control load-bearing rather than a matter of reading four
/// launchers and hoping.</para>
/// </summary>
internal static class EngineSelection
{
    /// <summary>D1: Python remains the default for the whole of Stage 1. The
    /// public default does not move before Gate G3 (#262 Stage 3).</summary>
    public const Engine Default = Engine.Python;

    /// <summary>The spellings accepted by every launcher surface. One contract
    /// across `owen`, own-check.sh, own-check.ps1 and the Action (D2).</summary>
    public static readonly string[] Names = ["python", "rust", "compare"];

    /// <summary>
    /// The exit codes an engine may legitimately produce for a document it
    /// actually judged: 0 clean, 1 findings, 2 usage error or a refusal by the
    /// strict door. Anything else is NOT a verdict.
    ///
    /// <para>70 is deliberately NOT in this set. It is the engines' shared
    /// internal-error code (`ownlang.run()` and `own-cli` both use it), so it
    /// is a KNOWN failure rather than an unexpected status — but it is still a
    /// failure, and reading it as a finding or as clean is exactly the bug
    /// control (6) exists to catch. It maps to Owen's public internal-error
    /// path (5) like any other non-verdict, and its raw value is retained in
    /// the report the same way.</para>
    /// </summary>
    public static bool IsLegalEngineExit(int rc) => rc is 0 or 1 or 2;

    /// <summary>The engines' shared internal-error code. Known, still a
    /// failure — never a verdict.</summary>
    public const int EngineInternalError = 70;

    public static string ToName(Engine engine) => engine switch
    {
        Engine.Python => "python",
        Engine.Rust => "rust",
        Engine.Compare => "compare",
        _ => "python",
    };

    /// <summary>Parse a <c>--engine</c> value. Returns false (with an
    /// actionable message) rather than throwing, so every surface answers an
    /// unknown engine as a usage error (exit 2) in one voice.</summary>
    public static bool TryParse(string value, out Engine engine, out string error)
    {
        switch (value)
        {
            case "python":
                engine = Engine.Python;
                error = "";
                return true;
            case "rust":
                engine = Engine.Rust;
                error = "";
                return true;
            case "compare":
                engine = Engine.Compare;
                error = "";
                return true;
            default:
                engine = Default;
                error =
                    $"owen check: unknown --engine '{value}' (choose: {string.Join(", ", Names)})";
                return false;
        }
    }

    /// <summary>True when the selection needs the Rust candidate binary — and
    /// therefore needs <c>OWEN_RUST_CORE</c> to resolve (D3/D3.1).</summary>
    public static bool NeedsRust(Engine engine) => engine is Engine.Rust or Engine.Compare;

    /// <summary>True when the selection needs the Python reference — and
    /// therefore may resolve an interpreter and unpack the vendored core.
    ///
    /// <para>This is the predicate the "a Rust-only run must not resolve or
    /// unpack Python" finding turns on. It is written as its own function, not
    /// inlined at the call site, precisely so a mutation that widens it (say,
    /// back to "always") has one obvious place to be caught.</para></summary>
    public static bool NeedsPython(Engine engine) => engine is Engine.Python or Engine.Compare;
}
