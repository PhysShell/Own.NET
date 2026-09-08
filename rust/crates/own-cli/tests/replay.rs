//! Zero-Python replay of the frozen `own-cli ownir` CLI contract
//! (`tests/fixtures/cli_ownir/`, authoritative via
//! `python tests/test_cli_ownir_fixtures.py --write`) — P-022 step 7b, #261.
//!
//! The Python side of this contract proves the frozen bytes are still what
//! `python -m ownlang ownir` produces. **This side runs no Python at all**: it
//! builds the binary, runs it against the same bytes, and compares. That
//! separation is the whole point of the fixture — a replay that needed the
//! reference would prove the two agree on a machine that has both, which is
//! not the machine the cutover is for.
//!
//! What is compared is exit code, stdout bytes and stderr bytes. There is
//! exactly one placeholder, `<OS_ERROR>`, and one rule for it: it consumes the
//! rest of the line it appears on and what it consumed must be non-empty. The
//! `cannot read <path>: ` prefix in front of it stays byte-exact, so the
//! contract is the CLI's own sentence and only the platform's `strerror` text
//! is left to the platform — the same choice `tests/test_cli_contract.py`
//! already made with its `"cannot read"` substring, written down instead of
//! implied.
//!
//! Three structural checks come before any byte comparison, because a fixture
//! that has quietly stopped covering something passes every byte check it still
//! has: every manifest case must have a file, every file a manifest entry, and
//! the `cli_ownir_version` must agree on both sides.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use own_ir::{OwnIr, OwnIrErrorKind};
use serde_json::Value;

const FIXTURE_DIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/cli_ownir"
);
const CLI_OWNIR_VERSION: i64 = 1;
const OS_ERROR: &str = "<OS_ERROR>";

fn fixture_dir() -> PathBuf {
    PathBuf::from(FIXTURE_DIR)
}

fn read_json(path: &Path) -> Value {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("{} is not valid JSON: {e}", path.display()))
}

fn manifest() -> Value {
    read_json(&fixture_dir().join("manifest.json"))
}

/// A named field, or a failure that says which one is missing. Used instead of
/// `value["key"]` because the workspace denies `indexing_slicing` — and because
/// "the fixture has no `cases`" is a better message than an index panic.
fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    value
        .get(key)
        .unwrap_or_else(|| panic!("the fixture is missing the field {key:?}"))
}

/// Run the built binary for one case. `OWNLANG_DEBUG` is removed from the
/// inherited environment before the case's own `env` is applied, so a
/// developer who exported it does not silently change what the fixture means.
fn run_case(case: &Value) -> Output {
    let argv: Vec<String> = field(case, "argv")
        .as_array()
        .expect("argv is an array")
        .iter()
        .map(|a| a.as_str().expect("argv entries are strings").to_owned())
        .collect();
    let cwd = fixture_dir().join(field(case, "cwd").as_str().expect("cwd is a string"));
    let mut command = Command::new(env!("CARGO_BIN_EXE_own-cli"));
    command.args(&argv).current_dir(&cwd);
    command.env_remove("OWNLANG_DEBUG");
    if let Some(env) = field(case, "env").as_object() {
        for (key, value) in env {
            command.env(key, value.as_str().expect("env values are strings"));
        }
    }
    command
        .output()
        .unwrap_or_else(|e| panic!("cannot run own-cli: {e}"))
}

/// `expected` matches `actual`, with `<OS_ERROR>` consuming the rest of its
/// line — and only if it consumed something. An empty tail would mean the
/// platform said nothing about a failure, which is not a pass.
fn matches(expected: &str, actual: &str) -> bool {
    let Some((head, tail)) = expected.split_once(OS_ERROR) else {
        return expected == actual;
    };
    assert!(
        !tail.contains(OS_ERROR),
        "a case may carry at most one <OS_ERROR> placeholder"
    );
    let Some(rest) = actual.strip_prefix(head) else {
        return false;
    };
    // The placeholder stops at the newline and hands the newline itself back,
    // so whatever the case expects AFTER that line still has to match.
    let (consumed, remainder) = match rest.find('\n') {
        Some(at) => (rest.get(..at).unwrap_or(""), rest.get(at..).unwrap_or("")),
        None => (rest, ""),
    };
    !consumed.is_empty() && remainder == tail
}

/// The prefix CLI-B1 pins, built from the case's own argv rather than from the
/// expectation it is about to relax — deriving it from the thing under test
/// would make the check circular.
///
/// A CLI-B1 case is required to be exactly `["ownir", <path>]`: no flags, one
/// positional. That is not a limitation worth working around, it is what makes
/// the prefix unambiguous, and a case that grows a flag fails here rather than
/// silently relaxing more than it declared.
fn cli_b1_pinned_prefix(case: &Value) -> String {
    let argv: Vec<&str> = field(case, "argv")
        .as_array()
        .expect("argv is an array")
        .iter()
        .map(|a| a.as_str().expect("argv entries are strings"))
        .collect();
    assert_eq!(
        argv.len(),
        2,
        "a CLI-B1 case must be exactly [ownir, <path>], got {argv:?}"
    );
    assert_eq!(argv.first().copied(), Some("ownir"), "{argv:?}");
    let path = argv.get(1).copied().unwrap_or_default();
    format!("{path}: error: {path} is not valid JSON: ")
}

/// Is this case ELIGIBLE for CLI-B1's relaxed tail? Proven, never assumed.
///
/// The boundary applies **iff** the strict door rejects with
/// `OwnIrErrorKind::Json`, so the guard establishes exactly that, from the
/// case's own facts bytes, before anything is relaxed:
///
/// 1. read the exact facts bytes the CLI case used;
/// 2. decode them with `str::from_utf8`, no normalization;
/// 3. the decode must SUCCEED — invalid UTF-8 is #261 ruling 1's declared
///    reference defect and must never borrow this boundary;
/// 4. `OwnIr::from_json` on that exact `&str` must REJECT;
/// 5. the rejection's kind must be `Json`.
///
/// Any of those failing means the case is not eligible and the caller fails it.
/// `Err(reason)` says which step, so a broken control names itself.
fn cli_b1_eligible(case: &Value) -> Result<(), String> {
    let cwd = fixture_dir().join(field(case, "cwd").as_str().expect("cwd is a string"));
    let argv = field(case, "argv").as_array().expect("argv is an array");
    let path = argv
        .get(1)
        .and_then(Value::as_str)
        .ok_or_else(|| "a CLI-B1 case needs a facts path as its only positional".to_owned())?;
    let bytes = std::fs::read(cwd.join(path))
        .map_err(|e| format!("cannot read the case's facts bytes {path:?}: {e}"))?;
    // Step 3. Invalid UTF-8 belongs to ruling 1, never here.
    let text = std::str::from_utf8(&bytes).map_err(|e| {
        format!(
            "the facts are not valid UTF-8 ({e}) — that is #261 ruling 1's \
             declared reference defect, never CLI-B1"
        )
    })?;
    // Steps 4 and 5. The typed door is the authority on the kind; nothing here
    // reads the message to decide.
    match OwnIr::from_json(text) {
        Ok(_) => {
            Err("the strict door ACCEPTED these facts; CLI-B1 needs a Json rejection".to_owned())
        }
        Err(refused) if refused.kind == OwnIrErrorKind::Json => Ok(()),
        Err(refused) => Err(format!(
            "the strict door rejected with kind {:?}, not Json — CLI-B1 applies \
             iff the kind is Json, and every other family is pinned byte-exact",
            refused.kind
        )),
    }
}

fn describe(label: &str, expected: &str, actual: &str) -> String {
    format!("\n  {label} expected: {expected:?}\n  {label} actual  : {actual:?}")
}

/// A case name and every file on disk must be the same set: a manifest entry
/// without a file is a case nobody replays, and a file without an entry is a
/// case nobody lists.
#[test]
fn every_manifest_case_has_a_file_and_every_file_an_entry() {
    let manifest = manifest();
    assert_eq!(
        field(&manifest, "cli_ownir_version").as_i64(),
        Some(CLI_OWNIR_VERSION),
        "the fixture and this replay disagree about the format version"
    );
    let listed: BTreeSet<String> = field(&manifest, "cases")
        .as_array()
        .expect("cases is an array")
        .iter()
        .map(|c| field(c, "name").as_str().expect("a case name").to_owned())
        .collect();
    let mut on_disk = BTreeSet::new();
    for entry in std::fs::read_dir(fixture_dir()).expect("the fixture directory exists") {
        let name = entry.expect("a readable entry").file_name();
        let name = name.to_string_lossy();
        if let Some(stem) = name.strip_suffix(".case.json") {
            on_disk.insert(stem.to_owned());
        }
    }
    assert!(!listed.is_empty(), "the manifest lists no cases at all");
    assert_eq!(
        listed, on_disk,
        "the manifest and the case files have drifted apart — run \
         `python tests/test_cli_ownir_fixtures.py --write`"
    );
}

/// The one that matters: the built binary against the frozen bytes.
#[test]
fn replays_the_whole_cli_contract_byte_for_byte() {
    let manifest = manifest();
    let mut failures: Vec<String> = Vec::new();
    let mut replayed = 0_usize;

    for entry in field(&manifest, "cases")
        .as_array()
        .expect("cases is an array")
    {
        let name = field(entry, "name").as_str().expect("a case name");
        let case = read_json(&fixture_dir().join(format!("{name}.case.json")));
        assert_eq!(
            field(&case, "cli_ownir_version").as_i64(),
            Some(CLI_OWNIR_VERSION),
            "{name}: format version drift"
        );
        let expected = field(&case, "expected");
        let want_exit = field(expected, "exit").as_i64().expect("an exit code");
        let want_out = field(expected, "stdout").as_str().expect("a stdout string");
        let want_err = field(expected, "stderr").as_str().expect("a stderr string");

        let output = run_case(&case);
        let got_out = String::from_utf8_lossy(&output.stdout);
        let got_err = String::from_utf8_lossy(&output.stderr);
        let got_exit = output.status.code();

        // CLI-B1: prove the kind BEFORE relaxing anything, then relax only
        // the parser detail after the pinned, byte-exact CLI-owned wrapper.
        if let Some(boundary) = case.get("boundary") {
            let id = field(boundary, "id").as_str().unwrap_or("?");
            assert_eq!(id, "CLI-B1", "{name}: unknown declared boundary {id:?}");
            assert_eq!(
                field(boundary, "expected_kind").as_str(),
                Some("json"),
                "{name}: CLI-B1 applies iff the kind is Json"
            );
            if let Err(reason) = cli_b1_eligible(&case) {
                failures.push(format!("{name} [CLI-B1 NOT eligible]: {reason}"));
                replayed = replayed.saturating_add(1);
                continue;
            }
            let prefix = cli_b1_pinned_prefix(&case);
            let mut why = String::new();
            if got_exit != Some(2) {
                why.push_str(&format!("\n  exit expected: 2, actual: {got_exit:?}"));
            }
            if !got_out.is_empty() {
                why.push_str(&describe("stdout", "", &got_out));
            }
            // The wrapper is pinned byte-exact; only what follows is declared.
            if got_err.starts_with(&prefix) {
                if got_err.len() <= prefix.len() {
                    why.push_str("\n  the declared parser detail was empty");
                }
            } else {
                why.push_str(&format!(
                    "\n  the CLI-owned wrapper is pinned and did not match\n  \
                     expected prefix: {prefix:?}\n  actual stderr  : {got_err:?}"
                ));
            }
            if !why.is_empty() {
                failures.push(format!("{name} [boundary: CLI-B1]{why}"));
            }
            replayed = replayed.saturating_add(1);
            continue;
        }

        let mut why = String::new();
        if got_exit != Some(want_exit.try_into().unwrap_or(i32::MAX)) {
            why.push_str(&format!(
                "\n  exit expected: {want_exit}, actual: {got_exit:?}"
            ));
        }
        if !matches(want_out, &got_out) {
            why.push_str(&describe("stdout", want_out, &got_out));
        }
        if !matches(want_err, &got_err) {
            why.push_str(&describe("stderr", want_err, &got_err));
        }
        if !why.is_empty() {
            let oracle = field(entry, "oracle").as_str().unwrap_or("?");
            failures.push(format!("{name} [oracle: {oracle}]{why}"));
        }
        replayed = replayed.saturating_add(1);
    }

    assert!(
        failures.is_empty(),
        "{} of {replayed} cases diverged from the frozen contract:\n\n{}",
        failures.len(),
        failures.join("\n\n")
    );
    assert!(replayed > 0, "no cases were replayed");
}

/// Byte-identical stdout and stderr on rerun. A contract that only holds the
/// first time is not one, and this is cheap enough to run over every case
/// rather than a chosen few.
#[test]
fn every_case_is_deterministic() {
    let manifest = manifest();
    let mut unstable: Vec<String> = Vec::new();
    for entry in field(&manifest, "cases")
        .as_array()
        .expect("cases is an array")
    {
        let name = field(entry, "name").as_str().expect("a case name");
        let case = read_json(&fixture_dir().join(format!("{name}.case.json")));
        let first = run_case(&case);
        let second = run_case(&case);
        if first.status.code() != second.status.code()
            || first.stdout != second.stdout
            || first.stderr != second.stderr
        {
            unstable.push(name.to_owned());
        }
    }
    assert!(
        unstable.is_empty(),
        "these cases did not reproduce byte-for-byte on a second run: {unstable:?}"
    );
}

/// The `owen`-convention surface has ONE source of truth. It is authored in
/// `tests/test_cli_ownir_fixtures.py`, carried in the manifest, and held as a
/// constant in the binary; nothing here can see that constant (an integration
/// test cannot link a `[[bin]]` crate), so the check goes through the process —
/// which is the stronger form anyway, because it compares what a user sees.
#[test]
fn the_help_text_the_binary_prints_is_the_one_the_manifest_carries() {
    let manifest = manifest();
    let shell = field(&manifest, "shell_usage")
        .as_str()
        .expect("shell_usage");
    let ownir = field(&manifest, "ownir_usage")
        .as_str()
        .expect("ownir_usage");

    for flag in ["--help", "-h"] {
        let out = Command::new(env!("CARGO_BIN_EXE_own-cli"))
            .arg(flag)
            .output()
            .expect("own-cli runs");
        assert_eq!(
            String::from_utf8_lossy(&out.stdout),
            shell,
            "`own-cli {flag}` has drifted from the manifest's shell_usage"
        );
    }

    let out = Command::new(env!("CARGO_BIN_EXE_own-cli"))
        .args(["ownir", "--help"])
        .output()
        .expect("own-cli runs");
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        ownir,
        "`own-cli ownir --help` has drifted from the manifest's ownir_usage"
    );

    // The version the fixture froze must be this package's, or `--version`
    // would be pinned to a number nobody bumps.
    assert_eq!(
        field(&manifest, "own_cli_version").as_str(),
        Some(env!("CARGO_PKG_VERSION")),
        "the manifest's own_cli_version and Cargo.toml have drifted"
    );
}

/// CLI-B1's NEGATIVE CONTROL: the guard is on the rejection KIND and nothing
/// else, so a case that differs from a CLI-B1 control only in its kind must be
/// refused by the relaxed matcher.
///
/// The control is deliberately *not* a malformed mutation: malformed bytes
/// could be refused by a different parser or decoder fork and "prove" the guard
/// by accident. Same argv shape, same path shape, same valid UTF-8, same
/// fixture machinery — only the content moved, from a JSON-syntax failure to a
/// valid document with a `Version` rejection. If CLI-B1 could ever match it,
/// the boundary would have widened from "the JSON parser's detail" into
/// "strict-door wording may differ", which is exactly what #261 ruling 2b
/// refuses.
#[test]
fn cli_b1_cannot_match_a_non_json_rejection() {
    let case = read_json(&fixture_dir().join("refuse-version-mismatch.case.json"));
    assert!(
        case.get("boundary").is_none(),
        "the negative control must carry NO boundary metadata — it is pinned \
         byte-exact as a Version rejection (#261 ruling 2a)"
    );
    let verdict = cli_b1_eligible(&case);
    let reason = verdict.expect_err("a Version rejection must not be CLI-B1 eligible");
    assert!(
        reason.contains("Version"),
        "the refusal must name the kind that disqualified it, got: {reason}"
    );

    // And the positive controls still are eligible, so the assertion above is
    // about the kind rather than about the guard being broken outright.
    for name in [
        "refuse-json-empty-file",
        "refuse-json-truncated",
        "refuse-json-bom",
    ] {
        let positive = read_json(&fixture_dir().join(format!("{name}.case.json")));
        assert_eq!(
            cli_b1_eligible(&positive),
            Ok(()),
            "{name} must be CLI-B1 eligible"
        );
    }
}

/// Every case that carries CLI-B1 metadata really does reject with `Json`, and
/// every case that does NOT carry it is pinned byte-exact. Stated as a sweep so
/// a future case cannot acquire the relaxed matcher by accident.
#[test]
fn only_json_rejections_carry_the_declared_boundary() {
    let manifest = manifest();
    let mut declared = 0_usize;
    for entry in field(&manifest, "cases")
        .as_array()
        .expect("cases is an array")
    {
        let name = field(entry, "name").as_str().expect("a case name");
        let case = read_json(&fixture_dir().join(format!("{name}.case.json")));
        if case.get("boundary").is_some() {
            assert_eq!(
                cli_b1_eligible(&case),
                Ok(()),
                "{name} declares CLI-B1 but is not a Json rejection"
            );
            declared = declared.saturating_add(1);
        }
    }
    assert!(
        declared > 0,
        "no case declares CLI-B1 — the boundary would be untested"
    );
}

/// `<OS_ERROR>` is a licence to skip a platform's `strerror` wording, not a
/// licence to skip a line. These are the rules it is held to, asserted rather
/// than trusted — a bug here would silently weaken every refusal case.
#[test]
fn the_os_error_placeholder_is_strict_about_what_it_consumes() {
    let expected = "f: error: cannot read f: <OS_ERROR>\n";
    assert!(matches(
        expected,
        "f: error: cannot read f: [Errno 2] nope\n"
    ));
    assert!(matches(
        expected,
        "f: error: cannot read f: anything at all\n"
    ));
    // It must consume SOMETHING: a platform that said nothing is not a pass.
    assert!(!matches(expected, "f: error: cannot read f: \n"));
    // The head is byte-exact, and the tail after the line still has to match.
    assert!(!matches(
        expected,
        "f: error: CANNOT read f: [Errno 2] nope\n"
    ));
    assert!(!matches(
        expected,
        "f: error: cannot read f: [Errno 2] nope\nextra\n"
    ));
    // It stops at the newline rather than swallowing the rest of the stream.
    assert!(matches(
        "a: <OS_ERROR>\nb\n",
        "a: [Errno 13] Permission denied\nb\n"
    ));
    // Without a placeholder the comparison is plain equality.
    assert!(matches("exact\n", "exact\n"));
    assert!(!matches("exact\n", "exact"));
}
