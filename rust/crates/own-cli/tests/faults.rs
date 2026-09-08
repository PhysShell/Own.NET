//! The two forced-failure controls, MEASURED rather than asserted from the
//! design — P-022 step 7b, #261.
//!
//! The whole file is behind the off-by-default `fault-injection` feature, so a
//! production build compiles none of it and the binary it tests carries no
//! hooks. Run it with:
//!
//! ```text
//! cargo test -p own-cli --features fault-injection --test faults
//! ```
//!
//! #261's two rulings, and the difference between them:
//!
//! ```text
//! catchable panic    -> exactly one actionable stderr diagnostic + exit 70,
//!                       never 101. Asserted precisely, because the number is
//!                       the contract: #262's launcher maps 70, and only 70,
//!                       onto its internal-error path.
//! uncatchable death  -> a visible hard failure: non-zero, OUTSIDE
//!                       {0, 1, 2, 70}, nothing on stdout, never masked. No
//!                       particular OS exit number is contracted, so none is
//!                       asserted — a signal on Unix and an abort status on
//!                       Windows are both correct answers, and the number this
//!                       run produced is recorded in the note instead.
//! ```

#![cfg(feature = "fault-injection")]
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::path::PathBuf;
use std::process::{Command, Output};

const FIXTURE_DIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/cli_ownir"
);

/// A perfectly ordinary invocation — one that exits 0 without the hooks — so
/// the only thing the control changes is the fault it injects.
fn run(fault: &str, debug: bool) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_own-cli"));
    command
        .args(["ownir", "../verdict_renders/render_empty.facts.json"])
        .current_dir(PathBuf::from(FIXTURE_DIR))
        .env_remove("OWNLANG_DEBUG")
        .env(fault, "1");
    if debug {
        command.env("OWNLANG_DEBUG", "1");
    }
    command.output().expect("own-cli runs")
}

/// A catchable panic is exactly one diagnostic and exit 70 — never 101, never
/// a finding, never an `ok` line.
#[test]
fn a_catchable_panic_is_one_diagnostic_and_exit_70() {
    let out = run("OWN_CLI_FAULT_PANIC", false);
    assert_eq!(
        out.status.code(),
        Some(70),
        "a panic must exit 70 (EX_SOFTWARE), never 101 — #262's launcher maps \
         only 70 onto its internal-error path"
    );
    assert!(
        out.stdout.is_empty(),
        "a panic must produce no findings and no `ok` line, got {:?}",
        String::from_utf8_lossy(&out.stdout)
    );
    let stderr = String::from_utf8_lossy(&out.stderr);
    let lines: Vec<&str> = stderr.lines().collect();
    assert_eq!(
        lines.len(),
        2,
        "EXACTLY one diagnostic (two lines), got: {stderr:?}"
    );
    assert!(
        lines[0].starts_with("own-cli: internal error: "),
        "the first line names the failure: {:?}",
        lines[0]
    );
    assert!(
        lines[0].contains("forced panic (fault-injection)"),
        "the payload is carried through, not replaced by a generic word: {:?}",
        lines[0]
    );
    assert!(
        lines[1].contains("This is a bug in the analyzer, not in your code"),
        "the second line tells the user it is not theirs: {:?}",
        lines[1]
    );
    assert!(
        !stderr.contains("note: run with `RUST_BACKTRACE"),
        "the hook must SUPPRESS the default panic output"
    );
    assert!(
        !stderr.contains("stack backtrace"),
        "no backtrace unless OWNLANG_DEBUG asks for one: {stderr:?}"
    );
}

/// The debug half of the reference's asymmetry: the technical cause is shown
/// and the exit code is kept. `run()` in `ownlang/__main__.py` does exactly
/// this, and for exactly this reason — a re-raise would exit 1, which a caller
/// reads as findings.
#[test]
fn debug_mode_shows_the_backtrace_and_still_exits_70() {
    let out = run("OWN_CLI_FAULT_PANIC", true);
    assert_eq!(
        out.status.code(),
        Some(70),
        "OWNLANG_DEBUG shows more; it must not change the exit code"
    );
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stderr.contains("forced panic (fault-injection)"),
        "the payload is printed: {stderr:?}"
    );
    assert!(
        stderr.contains("own-cli: panic:"),
        "the hook's debug line names the panic and its location: {stderr:?}"
    );
    assert!(
        out.stdout.is_empty(),
        "still no findings and no `ok` line under debug"
    );
}

/// An uncatchable death is a VISIBLE hard failure. What is asserted is that it
/// cannot be confused with any legal outcome; what is deliberately NOT asserted
/// is the number, because #261 contracts no OS exit code for this case.
#[test]
fn an_uncatchable_death_is_a_visible_hard_failure() {
    let out = run("OWN_CLI_FAULT_ABORT", false);
    assert!(
        !out.status.success(),
        "an abort must never look like a clean run"
    );
    assert!(
        out.stdout.is_empty(),
        "an abort must produce no findings and no `ok` line, got {:?}",
        String::from_utf8_lossy(&out.stdout)
    );
    // `code()` is None when a signal killed the process (Unix); either way the
    // outcome must be outside the legal set, so a caller cannot read it as
    // clean, findings, a usage error or a handled internal error.
    if let Some(code) = out.status.code() {
        assert!(
            ![0, 1, 2, 70].contains(&code),
            "an uncatchable death produced {code}, which is inside the legal \
             set {{0, 1, 2, 70}} — a caller would mistake it for an ordinary \
             outcome"
        );
    }
}

/// The control has to be a control: without the environment variable the same
/// invocation is an ordinary clean run, so the two tests above are measuring
/// the fault rather than a broken binary.
#[test]
fn without_the_environment_variable_the_same_invocation_is_clean() {
    let out = Command::new(env!("CARGO_BIN_EXE_own-cli"))
        .args(["ownir", "../verdict_renders/render_empty.facts.json"])
        .current_dir(PathBuf::from(FIXTURE_DIR))
        .env_remove("OWNLANG_DEBUG")
        .env_remove("OWN_CLI_FAULT_PANIC")
        .env_remove("OWN_CLI_FAULT_ABORT")
        .output()
        .expect("own-cli runs");
    assert_eq!(out.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&out.stdout).contains("0 findings."));
}
