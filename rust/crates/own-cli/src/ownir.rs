//! The `ownir` subcommand: argument handling, the strict door, and the
//! reference's display policy.
//!
//! C-1 puts the oracle boundary at the **surface**: once `ownir` is selected,
//! every answer — the usage errors, the refusals, every finding, every summary
//! line, every stream and every exit code — is `python -m ownlang ownir` as
//! measured, and `tests/fixtures/cli_ownir/` is the measurement.
//!
//! Two things this module does NOT do, and they are the same rule twice:
//!
//! * it never re-derives a render. `own_bridge::render_finding` and
//!   `own_bridge::build_sarif` are byte-pinned by the BR-V9 family and are the
//!   only renderers called here;
//! * it never re-derives a verdict. `own_bridge::check_facts` is the analysis,
//!   and this module only decides *which* of its findings are shown, where they
//!   go, and what the run exits with.
//!
//! What it *does* own is the display policy, which is CLI logic rather than
//! bridge logic and lives here for that reason. It is a pure function of the
//! findings and the three options ([`display`]), so the traps below are unit
//! tests rather than process invocations.

use std::collections::BTreeMap;
use std::fmt::Write as _;

use own_bridge::{build_sarif, check_facts, render_finding, Finding};
use own_ir::OwnIr;

use crate::{pyrepr::py_repr, sarif, text, Outcome};

/// The reference's `_FORMATS`, in the order `', '.join(sorted(_FORMATS))`
/// produces — `json` included, because the value gate that rejects an unknown
/// `--format` is the GLOBAL one, and it does not know the command yet.
const FORMATS: [&str; 5] = ["github", "human", "json", "msbuild", "sarif"];
const SEVERITIES: [&str; 2] = ["error", "warning"];
const VERBOSITIES: [&str; 3] = ["normal", "quiet", "verbose"];

/// The parsed `ownir` invocation. Exactly one positional; both `--flag value`
/// and `--flag=value`; no `--` separator and no short flags (C-3).
struct Parsed {
    path: String,
    format: String,
    severity: String,
    verbosity: String,
}

const fn usage_error(message: String) -> Outcome {
    Outcome::new(String::new(), message, 2)
}

/// The reference's answer to a positional-count error or an unknown argument:
/// the whole module docstring on STDOUT, exit 2.
///
/// The trailing newline is `print`'s, not the docstring's — `__doc__` ends in
/// exactly one `\n` and `print(__doc__)` puts two on the wire. The constant
/// stays the docstring verbatim and the newline is added here, so the thing
/// named `OWNLANG_DOCSTRING` is the thing it is named after.
fn docstring_usage() -> Outcome {
    Outcome::new(format!("{}\n", text::OWNLANG_DOCSTRING), String::new(), 2)
}

/// The reference's parser, reproduced including the part that surprises: an
/// unknown flag is **not** an error to it. `--bogus` matches no flag, so it
/// falls through to `positional.append(a)` — which means `--bogus <facts>` is
/// two positionals (the docstring) while `--bogus` alone is one, and takes the
/// ordinary path where opening a file called `--bogus` fails. Both halves are
/// frozen, as separate cases.
fn parse(args: &[String]) -> Result<Parsed, Outcome> {
    let mut format = "human".to_owned();
    let mut severity = "error".to_owned();
    let mut verbosity = "normal".to_owned();
    let mut positional: Vec<&str> = Vec::new();

    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        let mut matched = false;
        for (flag, slot) in [
            ("--format", &mut format),
            ("--severity", &mut severity),
            ("--verbosity", &mut verbosity),
        ] {
            if arg == flag {
                let Some(value) = iter.next() else {
                    return Err(usage_error(format!("{flag} requires a value\n")));
                };
                slot.clone_from(value);
                matched = true;
                break;
            }
            if let Some(value) = arg.strip_prefix(flag).and_then(|r| r.strip_prefix('=')) {
                value.clone_into(slot);
                matched = true;
                break;
            }
        }
        if !matched {
            positional.push(arg);
        }
    }

    // Exactly one positional; zero or extra is a usage error, and the answer is
    // the whole module docstring on STDOUT (C-1: the contract as measured, and
    // flagged `oracle: "python-docstring"` in the manifest so the owner can
    // declare that class a defect knowing exactly what was frozen).
    let [path] = positional[..] else {
        return Err(docstring_usage());
    };

    // Order matters: --format is validated before --severity before
    // --verbosity, so `--format x --severity y` answers about the format.
    for (flag, value, allowed) in [
        ("--format", &format, FORMATS.as_slice()),
        ("--severity", &severity, SEVERITIES.as_slice()),
        ("--verbosity", &verbosity, VERBOSITIES.as_slice()),
    ] {
        if !allowed.contains(&value.as_str()) {
            return Err(usage_error(format!(
                "unknown {flag} {} (choose: {})\n",
                py_repr(value),
                allowed.join(", ")
            )));
        }
    }
    // `json` passes the global gate above and is refused HERE, by the ownir
    // branch, with its own wording — which names the four surfaces in its own
    // order rather than the sorted one.
    if format == "json" {
        return Err(usage_error(
            "ownir --format must be one of github/human/msbuild/sarif (got 'json')\n".to_owned(),
        ));
    }
    Ok(Parsed {
        path: path.to_owned(),
        format,
        severity,
        verbosity,
    })
}

/// One `own-cli ownir ...` invocation, from argv to streams and an exit code.
pub(crate) fn run(args: &[String]) -> Outcome {
    // C-1's one declared defect: the reference reads `--help` as a file name
    // and dies with "cannot read". That is NOT ported — the shell convention
    // extends to the subcommand instead. Answered before the parser sees it,
    // because to the parser it is just a positional.
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Outcome::new(text::OWNIR_USAGE.to_owned(), String::new(), 0);
    }
    let parsed = match parse(args) {
        Ok(parsed) => parsed,
        Err(outcome) => return outcome,
    };
    // The forced-panic / forced-death controls, when the off-by-default
    // `fault-injection` feature is on. Placed after parsing so the control
    // exercises the same path a real panic would take.
    crate::faults::maybe_inject();
    check(&parsed)
}

/// The refusal shape both doors share: `{path}: error: {message}`, exit 2, with
/// the path exactly **as given in argv** — never resolved, never canonicalized.
fn refusal(path: &str, message: &str) -> Outcome {
    Outcome::new(String::new(), format!("{path}: error: {message}\n"), 2)
}

fn check(parsed: &Parsed) -> Outcome {
    let path = parsed.path.as_str();
    // Read ONCE, as bytes, and decode once: `OwnIr::from_json` takes `&str` and
    // the reference opens the file with `encoding="utf-8"`.
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        // The reference's OSError branch. Its tail is platform-native, which is
        // why the fixture matches it through the one `<OS_ERROR>` placeholder.
        Err(err) => return refusal(path, &format!("cannot read {path}: {err}")),
    };
    let text = match std::str::from_utf8(&bytes) {
        Ok(text) => text,
        // MEASURED, NOT PINNED (see docs/notes/p022-cli-ownir.md §1.4): the
        // reference's `load()` converts OSError and JSONDecodeError and nothing
        // else, so a UnicodeDecodeError escapes to its exit-70 catch-all. This
        // reproduces the CODE and the SHAPE and nothing claims byte parity —
        // there is no oracle for a Python exception's repr. Whether a crash on
        // malformed input is a contract or a refusal to add is a Python-first
        // decision, so no fixture case freezes it and none was invented.
        Err(err) => return Outcome::internal_error(&format!("{path}: {err}")),
    };
    let facts = match OwnIr::from_json(text) {
        Ok(facts) => facts,
        Err(refused) => return refusal(path, &refused.message),
    };
    match check_facts(&facts) {
        Err(refused) => refusal(path, &refused.to_string()),
        Ok(findings) => display(
            path,
            &findings,
            &parsed.format,
            &parsed.severity,
            &parsed.verbosity,
        ),
    }
}

/// The reference's `cmd_ownir` display policy, as a pure function.
///
/// The traps it encodes, each one measured on this tree and each one a named
/// fixture control:
///
/// * the exit code is `1 if leaks else 0` — `--severity` and `--verbosity`
///   never touch it, and the docstring's "non-zero if any error-level
///   diagnostic" is not the contract;
/// * `quiet` shows only leaks and the summary says `(N advisory hidden)`;
/// * the `ok` line fires on `not shown`, so a document whose only findings are
///   suppressed prints `ok` AND a suppressed tally, at exit 0;
/// * the verbose breakdown counts **every** finding, suppressed included;
/// * SARIF carries `shown + suppressed`, and `build_sarif` applies the
///   per-finding severity rule itself;
/// * machine formats send the summary to stderr, `human` to stdout — so a
///   clean `github`/`msbuild` run writes zero bytes to stdout.
fn display(
    path: &str,
    findings: &[Finding],
    format: &str,
    severity: &str,
    verbosity: &str,
) -> Outcome {
    // `Finding` carries no `suppressed` accessor: it is `ignore_reason.is_some()`,
    // the twin of the reference's `ignore_reason is not None`. BR-V6 keeps a
    // reason-less `[OwnIgnore]` from ever suppressing, and it does so upstream —
    // the extractor never emits one — which the empty-reason fixture proves from
    // the outside rather than assuming from the type.
    let suppressed: Vec<&Finding> = findings
        .iter()
        .filter(|f| f.ignore_reason.is_some())
        .collect();
    let active: Vec<&Finding> = findings
        .iter()
        .filter(|f| f.ignore_reason.is_none())
        .collect();
    let leaks: Vec<&Finding> = active.iter().copied().filter(|f| !f.advisory).collect();
    let notes: Vec<&Finding> = active.iter().copied().filter(|f| f.advisory).collect();
    let shown: &[&Finding] = if verbosity == "quiet" {
        &leaks
    } else {
        &active
    };

    let mut payload = String::new();
    if format == "sarif" {
        // One document for the whole run. Suppressed findings ride along so a
        // SARIF consumer can count them rather than lose them.
        let listed: Vec<Finding> = shown
            .iter()
            .chain(suppressed.iter())
            .map(|f| (*f).clone())
            .collect();
        match sarif::render(&build_sarif(&listed, severity)) {
            Ok(text) => payload.push_str(&text),
            Err(err) => return Outcome::internal_error(&format!("SARIF serialization: {err}")),
        }
    } else {
        for finding in shown {
            // The weaker of the host's severity and the finding's own level: an
            // advisory is always a warning, `--severity warning` downgrades
            // everything, and a finding whose source lifetime could not be
            // proven shows as a warning even at the default error level.
            let level = if finding.advisory
                || severity == "warning"
                || finding.severity.as_deref() == Some("warning")
            {
                "warning"
            } else {
                severity
            };
            payload.push_str(&render_finding(finding, format, level));
            payload.push('\n');
        }
    }

    let mut summary = String::new();
    if shown.is_empty() {
        let _ = writeln!(summary, "{path}: ok \u{2014} no subscription leaks found");
    }
    let leak_count = leaks.len();
    let plural = if leak_count == 1 { "" } else { "s" };
    let _ = write!(summary, "\n{leak_count} finding{plural}");
    if !notes.is_empty() {
        let hidden = notes.len();
        if verbosity == "quiet" {
            let _ = write!(summary, " ({hidden} advisory hidden)");
        } else {
            // Name the codes actually present rather than hardcoding OWN050:
            // OBL005 and the OWN051/OWN052 interprocedural notes ride the same
            // advisory band.
            let mut codes: Vec<&str> = notes.iter().map(|f| f.code.as_str()).collect();
            codes.sort_unstable();
            codes.dedup();
            let _ = write!(summary, ", {hidden} advisory ({})", codes.join("/"));
        }
    }
    if !suppressed.is_empty() {
        let _ = write!(summary, ", {} suppressed ([OwnIgnore])", suppressed.len());
    }
    summary.push_str(".\n");
    if verbosity == "verbose" && !findings.is_empty() {
        let mut by_code: BTreeMap<&str, usize> = BTreeMap::new();
        for finding in findings {
            let slot = by_code.entry(finding.code.as_str()).or_insert(0_usize);
            // `+= 1` is an arithmetic side effect the workspace denies; a count
            // that saturates is still a count, and this one cannot reach usize::MAX.
            *slot = slot.saturating_add(1);
        }
        let breakdown: Vec<String> = by_code
            .iter()
            .map(|(code, count)| format!("{code}={count}"))
            .collect();
        let _ = writeln!(summary, "  by code: {}", breakdown.join(", "));
    }

    let exit = u8::from(!leaks.is_empty());
    // The stream split: a machine format keeps stdout for the payload a host
    // parses and sends the human summary to stderr; `human` puts both on stdout.
    if matches!(format, "github" | "msbuild" | "sarif") {
        Outcome::new(payload, summary, exit)
    } else {
        let mut both = payload;
        both.push_str(&summary);
        Outcome::new(both, String::new(), exit)
    }
}

#[cfg(test)]
#[allow(clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use super::{display, parse, Parsed};
    use own_bridge::Finding;

    fn finding(code: &str, advisory: bool, ignore: Option<&str>) -> Finding {
        Finding {
            file: "Vm.cs".to_owned(),
            line: 1,
            column: None,
            code: code.to_owned(),
            component: "Vm".to_owned(),
            event: "E".to_owned(),
            handler: "On".to_owned(),
            message: "m".to_owned(),
            kind: "subscription token".to_owned(),
            advisory,
            severity: None,
            related: Vec::new(),
            flow: Vec::new(),
            ignore_reason: ignore.map(str::to_owned),
        }
    }

    fn parsed(format: &str, severity: &str, verbosity: &str) -> Parsed {
        Parsed {
            path: "f.json".to_owned(),
            format: format.to_owned(),
            severity: severity.to_owned(),
            verbosity: verbosity.to_owned(),
        }
    }

    /// `return 1 if leaks else 0`. Neither option moves it — the campaign's
    /// `--severity warning flips the exit` mutant dies here.
    #[test]
    fn exit_is_independent_of_severity_and_verbosity() {
        let leaky = [finding("OWN001", false, None)];
        for severity in ["error", "warning"] {
            for verbosity in ["quiet", "normal", "verbose"] {
                let p = parsed("human", severity, verbosity);
                let out = display("f.json", &leaky, &p.format, &p.severity, &p.verbosity);
                assert_eq!(out.exit, 1, "{severity}/{verbosity}");
            }
        }
    }

    /// An advisory note is not a verdict: it prints, and the run stays clean.
    #[test]
    fn an_advisory_alone_never_fails_the_run() {
        let notes = [finding("OWN050", true, None)];
        let out = display("f.json", &notes, "human", "error", "normal");
        assert_eq!(out.exit, 0);
        assert!(out.stdout.contains("1 advisory (OWN050)"), "{}", out.stdout);
    }

    /// A suppression is counted, never silent, and never a verdict.
    #[test]
    fn a_suppression_is_counted_but_does_not_fail_the_run() {
        let only = [finding("OWN001", false, Some("owned by the host"))];
        let out = display("f.json", &only, "human", "error", "normal");
        assert_eq!(out.exit, 0);
        assert!(out
            .stdout
            .contains("ok \u{2014} no subscription leaks found"));
        assert!(out
            .stdout
            .contains("0 findings, 1 suppressed ([OwnIgnore])."));
    }

    /// The `ok` line and the suppressed tally in ONE run — trap 4.
    #[test]
    fn quiet_hides_the_advisory_and_leaves_the_exit_alone() {
        let mixed = [
            finding("OWN001", false, None),
            finding("OWN050", true, None),
        ];
        let normal = display("f.json", &mixed, "human", "error", "normal");
        let quiet = display("f.json", &mixed, "human", "error", "quiet");
        assert_eq!(normal.exit, quiet.exit);
        assert!(normal.stdout.contains(", 1 advisory (OWN050)."));
        assert!(quiet.stdout.contains(" (1 advisory hidden)."));
        assert!(!quiet.stdout.contains("OWN050]"), "{}", quiet.stdout);
    }

    /// The breakdown iterates `findings`, not `shown`.
    #[test]
    fn the_verbose_breakdown_counts_suppressed_findings_too() {
        let docs = [
            finding("OWN001", false, None),
            finding("OWN001", false, Some("r")),
            finding("OWN050", true, None),
        ];
        let out = display("f.json", &docs, "human", "error", "verbose");
        assert!(
            out.stdout.contains("  by code: OWN001=2, OWN050=1\n"),
            "{}",
            out.stdout
        );
    }

    /// A clean machine run writes ZERO bytes to stdout; `human` writes there.
    #[test]
    fn the_stream_split_is_per_format() {
        let clean: [Finding; 0] = [];
        for format in ["github", "msbuild"] {
            let out = display("f.json", &clean, format, "error", "normal");
            assert_eq!(
                out.stdout, "",
                "{format} must not write to stdout when clean"
            );
            assert!(out
                .stderr
                .contains("ok \u{2014} no subscription leaks found"));
        }
        let human = display("f.json", &clean, "human", "error", "normal");
        assert_eq!(human.stderr, "");
        assert_eq!(
            human.stdout,
            "f.json: ok \u{2014} no subscription leaks found\n\n0 findings.\n"
        );
    }

    /// `{'s' if n != 1 else ''}` — plural at zero, singular only at one.
    #[test]
    fn the_summary_pluralizes_on_anything_but_one() {
        let clean: [Finding; 0] = [];
        assert!(display("f.json", &clean, "human", "error", "normal")
            .stdout
            .contains("\n0 findings."));
        let one = [finding("OWN001", false, None)];
        assert!(display("f.json", &one, "human", "error", "normal")
            .stdout
            .contains("\n1 finding."));
        let two = [
            finding("OWN001", false, None),
            finding("OWN002", false, None),
        ];
        assert!(display("f.json", &two, "human", "error", "normal")
            .stdout
            .contains("\n2 findings."));
    }

    /// SARIF carries `shown + suppressed`: `quiet` drops the advisory from the
    /// list but keeps the suppression.
    #[test]
    fn sarif_carries_shown_plus_suppressed() {
        let docs = [
            finding("OWN001", false, None),
            finding("OWN050", true, None),
            finding("OWN002", false, Some("r")),
        ];
        let normal = display("f.json", &docs, "sarif", "error", "normal");
        let quiet = display("f.json", &docs, "sarif", "error", "quiet");
        assert_eq!(normal.stdout.matches("\"ruleId\"").count(), 3);
        assert_eq!(quiet.stdout.matches("\"ruleId\"").count(), 2);
        assert!(
            quiet.stdout.contains("OWN002"),
            "the suppression must ride along"
        );
    }

    /// Both spellings, the last-one-wins rule, and the absence of a separator.
    #[test]
    fn the_parser_accepts_both_spellings_and_lets_the_last_flag_win() {
        let args: Vec<String> = ["f.json", "--format=human", "--format", "sarif"]
            .iter()
            .map(|s| (*s).to_owned())
            .collect();
        let parsed = parse(&args).ok().expect("a valid invocation");
        assert_eq!(parsed.format, "sarif");
        assert_eq!(parsed.path, "f.json");
    }

    /// `--` is an ordinary positional, so `-- f.json` is TWO of them.
    #[test]
    fn there_is_no_double_dash_separator() {
        let args: Vec<String> = ["--", "f.json"].iter().map(|s| (*s).to_owned()).collect();
        let outcome = parse(&args)
            .err()
            .expect("two positionals is a usage error");
        assert_eq!(outcome.exit, 2);
        assert_eq!(
            outcome.stdout,
            format!("{}\n", crate::text::OWNLANG_DOCSTRING),
            "the docstring plus print's own newline"
        );
        assert_eq!(outcome.stderr, "");
    }

    /// A missing value is a stderr line, not the docstring.
    #[test]
    fn a_missing_flag_value_is_its_own_message() {
        for flag in ["--format", "--severity", "--verbosity"] {
            let args: Vec<String> = ["f.json", flag].iter().map(|s| (*s).to_owned()).collect();
            let outcome = parse(&args).err().expect("a missing value is an error");
            assert_eq!(outcome.exit, 2);
            assert_eq!(outcome.stderr, format!("{flag} requires a value\n"));
            assert_eq!(outcome.stdout, "");
        }
    }

    /// The global gate still lists `json`; the ownir branch then refuses it.
    #[test]
    fn json_passes_the_global_gate_and_is_refused_by_the_ownir_branch() {
        let bad: Vec<String> = ["f.json", "--format", "x"]
            .iter()
            .map(|s| (*s).to_owned())
            .collect();
        assert_eq!(
            parse(&bad).err().expect("invalid").stderr,
            "unknown --format 'x' (choose: github, human, json, msbuild, sarif)\n"
        );
        let json: Vec<String> = ["f.json", "--format", "json"]
            .iter()
            .map(|s| (*s).to_owned())
            .collect();
        assert_eq!(
            parse(&json)
                .err()
                .expect("json is not an ownir surface")
                .stderr,
            "ownir --format must be one of github/human/msbuild/sarif (got 'json')\n"
        );
    }
}
