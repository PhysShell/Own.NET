//! A controllable stand-in for the `own-cli` candidate, for #262 Stage-1 controls.
//!
//! Several Stage-1 controls need a candidate whose exit code and output bytes
//! the test chooses: a compare divergence, a compare execution failure, an
//! agreement (which needs the candidate to emit the reference's exact bytes),
//! and a same-input proof (which needs the candidate to report what it was
//! handed). #261's `fault-injection` build can force a panic or an abort, but
//! it cannot be told to produce a chosen answer, so it cannot express any of
//! those cases.
//!
//! Why a compiled binary rather than a shell script: a `#!`-stub is Unix-only,
//! and the launcher spawns its candidate as a process — on Windows it cannot
//! start a `.cmd`, and git-bash happily runs a mode-644 file, which is how the
//! earlier shell stubs made "non-executable" untestable there. A real native
//! executable behaves the same way on both platforms, which is what lets the
//! compare controls run on Windows at all instead of being declared N/A.
//!
//! Why plain `rustc` and not a cargo crate: adding a workspace member would
//! move the crate-edge DAG that #261's gate pins. This file is compiled
//! directly —
//!
//! ```text
//! rustc -O tests/helpers/stage1_stub.rs -o <dir>/stage1-stub[.exe]
//! ```
//!
//! — so it has no dependencies, no crate, and no effect on the production
//! graph. It is test scaffolding and is never packaged, published, or reachable
//! from any production path.
//!
//! It is invoked exactly like the real candidate (`stub ownir <facts> --format
//! F --severity S`) and is configured entirely by environment variables:
//!
//! ```text
//! STAGE1_STUB_EXIT          exit with this code (default 0)
//! STAGE1_STUB_STDOUT_FILE   write this file's bytes, verbatim, to stdout
//! STAGE1_STUB_STDERR_FILE   write this file's bytes, verbatim, to stderr
//! STAGE1_STUB_COPY_INPUT    copy the facts argument to this path before exiting
//! STAGE1_STUB_VERSION       answer `--version` with this line, exit 0
//! ```
//!
//! `STAGE1_STUB_VERSION` lets the stub stand in for the PYTHON side as well as
//! the Rust one. The launcher validates `OWEN_PYTHON` by running it with
//! `--version` and reading "Python X.Y" back, so a stub that always failed
//! would be rejected at resolution (exit 3) and never reach the compare. With
//! this it answers the probe like a supported interpreter and then fails the
//! actual run — which is the only way to exercise "the REFERENCE produced no
//! verdict while the candidate did", and it does so on both platforms rather
//! than through a Unix-only shell wrapper.
//!
//! `STDOUT_FILE`/`STDERR_FILE` take a FILE rather than a string because the
//! agreement control has to reproduce the reference's output byte for byte,
//! including its line endings — the very bytes an environment variable would
//! be least trustworthy about.
//!
//! `COPY_INPUT` copies rather than hashes so this file needs no digest
//! implementation: the harness hashes the copy and compares it against the
//! launcher's attested capture, which is the same measurement with the
//! arithmetic left where a library already exists.

use std::io::Write as _;

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.is_empty())
}

fn main() {
    // argv: ownir <facts> --format F --severity S [...]
    let args: Vec<String> = std::env::args().skip(1).collect();

    // The interpreter-probe impersonation, before anything else: the launcher
    // asks a candidate interpreter for its version and refuses one it cannot
    // read, so this answer has to come before any configured failure.
    if let Some(version) = env("STAGE1_STUB_VERSION") {
        if args.iter().any(|a| a == "--version") {
            println!("{version}");
            std::process::exit(0);
        }
    }

    if let Some(dest) = env("STAGE1_STUB_COPY_INPUT") {
        // args[0] is the subcommand ("ownir"); args[1] is the facts path.
        if let Some(facts) = args.get(1) {
            let _ = std::fs::copy(facts, dest);
        }
    }

    if let Some(path) = env("STAGE1_STUB_STDOUT_FILE") {
        if let Ok(bytes) = std::fs::read(path) {
            let mut out = std::io::stdout().lock();
            let _ = out.write_all(&bytes);
            let _ = out.flush();
        }
    }

    if let Some(path) = env("STAGE1_STUB_STDERR_FILE") {
        if let Ok(bytes) = std::fs::read(path) {
            let mut err = std::io::stderr().lock();
            let _ = err.write_all(&bytes);
            let _ = err.flush();
        }
    }

    let code: i32 = env("STAGE1_STUB_EXIT")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    std::process::exit(code);
}
