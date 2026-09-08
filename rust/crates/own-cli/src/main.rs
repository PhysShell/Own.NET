//! `own-cli` — the production OwnIR executable (P-022 step 7b, #261).
//!
//! ```text
//! own-cli                      help -> stdout, exit 2
//! own-cli --help | -h          help -> stdout, exit 0
//! own-cli --version            version -> stdout, exit 0
//! own-cli <garbage>            one error line + help -> stderr, exit 2
//! own-cli ownir <facts> ...    exactly what `python -m ownlang ownir` does
//! ```
//!
//! ## The oracle boundary (#261 C-1)
//!
//! The two halves above have **different oracles**, and the boundary is the
//! surface rather than the reference's internal print branch. The top-level
//! shell follows the public `owen` convention
//! (`frontend/roslyn/OwnSharp.Cli/Program.cs`) — a new cross-implementation
//! parity surface with no Python byte oracle, written once and frozen by
//! `tests/fixtures/cli_ownir/`. Everything **after `ownir` is selected** is the
//! reference as measured, including the parts that surprise: a positional-count
//! error prints the whole module docstring to *stdout* with exit 2, and an
//! unknown flag is a positional rather than an error.
//!
//! ## What it is not
//!
//! It knows nothing of Python (C-4): no engine selection, no compare mode, no
//! fallback, no environment variable that picks an engine. A Rust failure is
//! never a Python success, because there is no Python here to fall back to.
//! `owen`, `own-check.*`, the Action, `own-shadow-engine` and the compare
//! driver are untouched — Python remains the public engine until #262 says
//! otherwise, and nothing in this crate is wired to anything.
//!
//! ## The process contract
//!
//! ```text
//! 0   clean
//! 1   findings — any non-advisory, unsuppressed finding, independent of
//!     --severity
//! 2   usage error, or a facts document the strict door refuses
//! 70  internal error — ONE actionable stderr diagnostic, never 101
//! ```
//!
//! 70 rather than Rust's default 101 is the whole reason the panic path exists,
//! and a hook alone would not produce it: a hook only *observes* a panic, and
//! the process would still exit 101. The build keeps `panic = "unwind"` (the
//! workspace default — Cargo cannot set `panic` per package, so a profile that
//! aborted here would abort the whole workspace build), the hook suppresses the
//! default panic output and records the payload, and a top-level
//! [`std::panic::catch_unwind`] turns the unwind into the diagnostic and the
//! exit. Under `OWNLANG_DEBUG` the hook prints the payload and a captured
//! backtrace and the exit is **still 70** — the asymmetry the reference's
//! `run()` keeps, because exit 1 would read as findings and `owen check`
//! without `--fail-on-finding` maps that to a clean scan.

#![allow(clippy::print_stderr)]

mod faults;
mod ownir;
mod pyrepr;
mod sarif;
mod text;

use std::io::Write as _;
use std::process::ExitCode;
use std::sync::Mutex;

/// The second line of the internal-error diagnostic. Named so the panic path
/// and the I/O-failure path cannot drift into two different apologies.
const INTERNAL_ERROR_HINT: &str = "  This is a bug in the analyzer, not in your code. \
Re-run with OWNLANG_DEBUG=1 for the full backtrace and please report it.\n";

/// Where the panic hook leaves what it saw, for `catch_unwind` to report. The
/// hook runs *during* the unwind and the catch runs after it, so the payload
/// has to survive the gap between them.
static PANIC_PAYLOAD: Mutex<Option<String>> = Mutex::new(None);

/// The streams and the exit code of one invocation. Building them as values
/// rather than printing as we go is what lets the display policy be a pure
/// function a unit test can drive without a process.
pub(crate) struct Outcome {
    pub(crate) stdout: String,
    pub(crate) stderr: String,
    pub(crate) exit: u8,
}

impl Outcome {
    pub(crate) const fn new(stdout: String, stderr: String, exit: u8) -> Self {
        Self {
            stdout,
            stderr,
            exit,
        }
    }

    /// The one actionable diagnostic and exit 70. Used by every internal
    /// failure that is not a panic — a stdout write that fails, an input this
    /// binary cannot decode — so all of them answer in one voice.
    pub(crate) fn internal_error(cause: &str) -> Self {
        Self::new(
            String::new(),
            format!("own-cli: internal error: {cause}\n{INTERNAL_ERROR_HINT}"),
            70,
        )
    }
}

fn debug_enabled() -> bool {
    // Non-empty, like the reference's `os.environ.get("OWNLANG_DEBUG")`
    // truthiness — an exported-but-empty variable does not turn debug on.
    std::env::var_os("OWNLANG_DEBUG").is_some_and(|value| !value.is_empty())
}

/// Recover a panic's payload the way the standard hook would print it.
///
/// It takes the payload rather than the hook info on purpose: the info type was
/// renamed (`PanicInfo` -> `PanicHookInfo`) in a release later than the
/// workspace's declared `rust-version`, so naming it here would either warn
/// about the MSRV or use a deprecated alias. The closure passed to `set_hook`
/// infers the type; this function never has to spell it.
fn payload_of(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        return (*text).to_owned();
    }
    if let Some(text) = payload.downcast_ref::<String>() {
        return text.clone();
    }
    // A payload of some other type carries nothing printable. The reference's
    // equivalent is `type(exc).__name__: exc`; here the honest answer is the
    // word itself rather than an invented cause.
    "panic".to_owned()
}

/// Install the hook that makes exit 70 possible: it suppresses the default
/// panic output (which would otherwise print a second, differently-worded
/// diagnostic) and records what it saw. Under `OWNLANG_DEBUG` it also prints
/// the payload and a captured backtrace — the debug half of the reference's
/// asymmetry, where the technical cause is shown and the exit code is kept.
fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let payload = payload_of(info.payload());
        if let Ok(mut slot) = PANIC_PAYLOAD.lock() {
            *slot = Some(payload.clone());
        }
        if debug_enabled() {
            let where_ = info
                .location()
                .map_or_else(|| "unknown location".to_owned(), ToString::to_string);
            eprintln!("own-cli: panic: {payload} (at {where_})");
            eprint!("{}", std::backtrace::Backtrace::force_capture());
        }
    }));
}

/// Write the outcome's streams. A failure here is an internal error rather
/// than a silent truncation — the reference does the same thing (measured:
/// `--format sarif | head -c 1` exits 70 with its internal-error diagnostic,
/// deterministically, because a `BrokenPipeError` reaches its catch-all).
fn emit(outcome: &Outcome) -> std::io::Result<()> {
    if !outcome.stdout.is_empty() {
        let mut out = std::io::stdout().lock();
        out.write_all(outcome.stdout.as_bytes())?;
        out.flush()?;
    }
    if !outcome.stderr.is_empty() {
        let mut err = std::io::stderr().lock();
        err.write_all(outcome.stderr.as_bytes())?;
        err.flush()?;
    }
    Ok(())
}

/// The C-1 shell. #345 adds its subcommands to this one table.
fn dispatch(args: &[String]) -> Outcome {
    match args.first().map(String::as_str) {
        // The empty invocation and the unknown command are DISTINCT cases: the
        // first is a bare help on stdout, the second an error line plus the
        // help on stderr. `owen` draws that line and so does this.
        None => Outcome::new(text::SHELL_USAGE.to_owned(), String::new(), 2),
        Some("--help" | "-h") => Outcome::new(text::SHELL_USAGE.to_owned(), String::new(), 0),
        Some("--version") => Outcome::new(
            format!("own-cli {}\n", env!("CARGO_PKG_VERSION")),
            String::new(),
            0,
        ),
        Some("ownir") => ownir::run(args.get(1..).unwrap_or(&[])),
        Some(other) => Outcome::new(
            String::new(),
            format!(
                "own-cli: unknown command {}\n{}",
                pyrepr::py_repr(other),
                text::SHELL_USAGE
            ),
            2,
        ),
    }
}

fn run() -> u8 {
    // `args_os` rather than `args`: the latter PANICS on an argument that is
    // not valid Unicode, and a CLI that takes file paths must not turn a
    // user's file name into an internal error. The lossy conversion is a
    // deliberate, recorded limit — a path that is not valid Unicode is outside
    // the measured contract (the reference round-trips it through Python's
    // surrogateescape, which has no fixture here) and fails with an ordinary
    // "cannot read" rather than a crash.
    let args: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect();
    let outcome = dispatch(&args);
    match emit(&outcome) {
        Ok(()) => outcome.exit,
        Err(err) => {
            // The streams are already half-written by definition; the exit code
            // is the part that still has to be honest.
            let failure = Outcome::internal_error(&format!("cannot write output: {err}"));
            let _ = emit(&failure);
            failure.exit
        }
    }
}

fn main() -> ExitCode {
    install_panic_hook();
    // The catch is the mechanism, not the hook: without it an ordinary panic
    // exits 101, which #262's launcher would read as an unexpected child status
    // rather than the internal-error path.
    let code = match std::panic::catch_unwind(run) {
        Ok(code) => code,
        Err(_) => {
            if !debug_enabled() {
                let payload = PANIC_PAYLOAD
                    .lock()
                    .ok()
                    .and_then(|slot| slot.clone())
                    .unwrap_or_else(|| "panic".to_owned());
                let failure = Outcome::internal_error(&payload);
                let _ = emit(&failure);
            }
            // Under OWNLANG_DEBUG the hook has already printed the payload and
            // the backtrace; the reference prints the traceback INSTEAD of the
            // polite line, not as well as it. The exit is 70 either way.
            70
        }
    };
    ExitCode::from(code)
}

#[cfg(test)]
#[allow(clippy::expect_used)]
mod tests {
    use super::{dispatch, text, Outcome};

    fn argv(args: &[&str]) -> Vec<String> {
        args.iter().map(|a| (*a).to_owned()).collect()
    }

    /// The four shell cases of C-1, including the one distinction that is easy
    /// to lose: an empty invocation is not an unknown command.
    #[test]
    fn the_shell_follows_the_owen_convention() {
        let empty = dispatch(&argv(&[]));
        assert_eq!(empty.exit, 2);
        assert_eq!(empty.stdout, text::SHELL_USAGE);
        assert_eq!(empty.stderr, "");

        for flag in ["--help", "-h"] {
            let help = dispatch(&argv(&[flag]));
            assert_eq!(help.exit, 0, "{flag}");
            assert_eq!(help.stdout, text::SHELL_USAGE);
            assert_eq!(help.stderr, "");
        }

        let version = dispatch(&argv(&["--version"]));
        assert_eq!(version.exit, 0);
        assert_eq!(
            version.stdout,
            format!("own-cli {}\n", env!("CARGO_PKG_VERSION"))
        );

        let unknown = dispatch(&argv(&["bogus"]));
        assert_eq!(unknown.exit, 2);
        assert_eq!(
            unknown.stdout, "",
            "an unknown command says nothing on stdout"
        );
        assert_eq!(
            unknown.stderr,
            format!("own-cli: unknown command 'bogus'\n{}", text::SHELL_USAGE)
        );
    }

    /// C-1's declared defect: the reference answers `ownir --help` with
    /// "cannot read --help" and exit 2. That is not ported.
    #[test]
    fn ownir_help_answers_with_the_usage_rather_than_the_defect() {
        let help = dispatch(&argv(&["ownir", "--help"]));
        assert_eq!(help.exit, 0);
        assert_eq!(help.stdout, text::OWNIR_USAGE);
        assert_eq!(help.stderr, "");
    }

    /// The internal-error surface is one voice: the same two lines whatever
    /// produced it, and never an exit a caller could read as findings or clean.
    #[test]
    fn the_internal_error_surface_is_one_shape() {
        let failure = Outcome::internal_error("something specific");
        assert_eq!(failure.exit, 70);
        assert_eq!(failure.stdout, "");
        let mut lines = failure.stderr.lines();
        assert_eq!(
            lines.next(),
            Some("own-cli: internal error: something specific")
        );
        assert!(lines
            .next()
            .is_some_and(|line| line.contains("This is a bug in the analyzer")));
        assert_eq!(lines.next(), None, "exactly one diagnostic, two lines");
    }
}
