//! The two forced-failure controls, behind the off-by-default
//! `fault-injection` cargo feature.
//!
//! #261 rules on two failure modes:
//!
//! ```text
//! catchable panic    -> exactly one actionable stderr diagnostic + exit 70,
//!                       never 101
//! uncatchable death  -> a visible hard failure: non-zero, outside
//!                       {0, 1, 2, 70}, no findings, no `ok` line, never
//!                       masked. NO particular OS exit number is contracted.
//! ```
//!
//! Both are *measured* rather than asserted from the design, which needs a way
//! to make them happen on demand — and a production binary must not carry one.
//! Hence the feature: `cargo build -p own-cli` compiles [`maybe_inject`] to a
//! `const fn` with an empty body, and only
//! `cargo test -p own-cli --features fault-injection` builds the hooks at all.
//!
//! The panic is raised with [`std::panic::panic_any`] rather than the `panic!`
//! macro. That is not a way around the workspace's `clippy::panic` deny — it is
//! the right API for this job: `panic_any` takes the payload as a value, which
//! is exactly what the diagnostic has to recover and print, so the control
//! exercises the payload path a real panic would take instead of a stringly
//! special case.

/// Force one of the two failure modes when the environment asks for it.
///
/// Called after argument parsing, so the control travels the same path a real
/// panic in the analysis would: through `catch_unwind` in `main`, with the hook
/// already installed.
#[cfg(feature = "fault-injection")]
pub(crate) fn maybe_inject() {
    if std::env::var_os("OWN_CLI_FAULT_PANIC").is_some() {
        std::panic::panic_any("forced panic (fault-injection)");
    }
    if std::env::var_os("OWN_CLI_FAULT_ABORT").is_some() {
        // A genuinely UNCATCHABLE termination: `catch_unwind` cannot see it and
        // no hook runs. What the OS then reports (a SIGABRT on Unix, an abort
        // status on Windows) is recorded by the note, never contracted.
        std::process::abort();
    }
}

/// The production build: nothing to inject, and nothing compiled in to inject
/// it with.
#[cfg(not(feature = "fault-injection"))]
pub(crate) const fn maybe_inject() {}
