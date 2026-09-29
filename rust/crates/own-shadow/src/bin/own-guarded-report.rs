//! `own-guarded-report` — P-037 B1's shadow report entry point
//! (docs/notes/p037-phase-b1-shadow.md; owner decision R-1).
//!
//! ```text
//! stdin  : one OwnIR facts document, and nothing else
//! stdout : the `p037-guarded-shadow/1` report of that document
//! exit 0 : the report was produced; exit 2 : it was not
//! ```
//!
//! It takes no arguments and opens no file, for the reason `own-shadow-engine`
//! gives: the driver hands over bytes, never a name. The legacy side is
//! `own-bridge`'s MOS dump of the same document, so both sides read one input.
//! Shadow only: nothing here reaches a verdict.

#![allow(clippy::print_stderr)]

use std::io::{Read as _, Write as _};
use std::process::ExitCode;

fn run() -> Result<String, String> {
    if std::env::args_os().len() > 1 {
        return Err("takes no arguments (R-1): the facts document is stdin".to_owned());
    }
    let mut text = String::new();
    std::io::stdin()
        .read_to_string(&mut text)
        .map_err(|e| format!("stdin: {e}"))?;
    let ir = own_ir::OwnIr::from_json(&text).map_err(|e| format!("facts: {}", e.message))?;
    let dump = own_bridge::dump_summaries(&ir).map_err(|e| format!("legacy MOS: {e:?}"))?;
    let legacy = serde_json::from_str(&dump).map_err(|e| format!("legacy MOS: {e}"))?;
    Ok(own_guarded::report(&ir, &legacy).to_string())
}

fn main() -> ExitCode {
    match run() {
        Ok(report) => match writeln!(std::io::stdout().lock(), "{report}") {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("own-guarded-report: stdout: {e}");
                ExitCode::from(2)
            }
        },
        Err(e) => {
            eprintln!("own-guarded-report: {e}");
            ExitCode::from(2)
        }
    }
}
