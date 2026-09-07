//! `own-shadow-engine` — the **dev-only adapter** around the port's capture
//! (P-022 step 7a, #260 acceptance; owner decision R-1).
//!
//! ```text
//! stdin  : the captured raw bytes, and nothing else
//! stdout : one JSON document — this engine's capture of those bytes
//! stderr : diagnostics only
//! exit 0 : the capture was produced (a REFUSED layer is a capture, not a failure)
//! exit≠0 : execution failure — the capture was NOT produced
//! ```
//!
//! ## What it is not
//!
//! It is **not `own-cli`**, and it creates no #261 cutover surface. It takes no
//! arguments, opens no file, reads no environment and discovers no
//! configuration. There is nothing here for a user to invoke and nothing for a
//! command surface to grow out of: the whole program is "read the bytes on
//! stdin, hand them to `own_shadow::capture_detailed`, write the answer".
//!
//! That austerity is the decision (R-1). The compare driver's central invariant
//! is that the input is produced or loaded **exactly once** and *those exact
//! bytes* reach both engines (#260's same-input rule, owner decision B-1). An
//! adapter that accepted a path would let a second read happen where nobody
//! could see it — the driver would hand over a name instead of a value, and
//! "both engines saw the same input" would go back to being an assumption
//! about which file was passed where.
//!
//! ## A refusal is not a failure, and a failure is not a refusal
//!
//! Owner decision R-2, and the exit code is where it is enforced. `produced`
//! and `refused` are semantic **layer statuses**: an engine that refuses a
//! layer has answered, and the answer is part of the capture. A crash, a
//! timeout or a non-zero exit is a **run-level hard failure**: no capture was
//! produced, and the driver must never synthesize one or fall back to the other
//! engine's result. So this program exits non-zero only when it genuinely has
//! no answer, and a panic — which exits 101 with its message on stderr — lands
//! in exactly that class without any special handling.
//!
//! ## The envelope, and why it is not bare
//!
//! ```text
//! {"own_shadow_engine": 1,
//!  "engine": {"id", "consumed", "layers", "derived"},
//!  "canonical": {"algorithm", "digest", "bytes"} | null,
//!  "canonical_error": "..." | null,
//!  "derived_documents": {"sarif": {...}} | null}
//! ```
//!
//! * `engine` is the artifact's `engines[]` entry verbatim — the whole point.
//! * `canonical` is this engine's **own** derivation of the input's canonical
//!   identity, computed here with zero Python. Without it the driver would take
//!   the reference's word for what the document is, and the one thing this
//!   surface exists to check is that both engines agree about what they saw.
//!   `canonical_error` carries the refusal instead when these bytes are not a
//!   nameable document at all — which is a fact the driver must have, because
//!   two engines *disagreeing* about that is a domain decision rather than a
//!   comparison result.
//! * `derived_documents` carries the full rendered SARIF whose identity
//!   `engine.derived` names. The driver retains it only on mismatch; asking for
//!   it by re-invoking this program would be a second execution of the thing
//!   whose single execution is the point.

#![allow(clippy::print_stderr)]

use std::io::{Read as _, Write as _};

use own_shadow::{canonical_hash, capture_detailed, render, Json};

/// The adapter protocol version. Carried so that a driver and an adapter that
/// have drifted apart refuse each other visibly, instead of the driver reading
/// a missing member as an absent capture.
const PROTOCOL_VERSION: i64 = 1;

fn object(entries: Vec<(&str, Json)>) -> Json {
    Json::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect(),
    )
}

fn main() -> std::process::ExitCode {
    if std::env::args_os().len() > 1 {
        eprintln!(
            "own-shadow-engine takes no arguments: it reads the captured bytes on stdin and \
             writes one capture on stdout. A path argument would allow a second read of the \
             input, which is the one thing the same-input invariant forbids."
        );
        return std::process::ExitCode::from(2);
    }
    let mut raw = Vec::new();
    // The lock is bound rather than used inline: a temporary with a
    // significant `Drop` in an `if let` scrutinee outlives the branch, and a
    // program whose whole job is one read should not hold stdin open past it.
    let read = std::io::stdin().lock().read_to_end(&mut raw);
    if let Err(e) = read {
        eprintln!("own-shadow-engine: cannot read stdin: {e}");
        return std::process::ExitCode::from(2);
    }
    // The capture is taken over the bytes exactly as they arrived. Nothing
    // trims, decodes or re-encodes them on the way in — `capture_detailed`
    // hashes them on its first line, before `serde_json` looks at one.
    let captured = match capture_detailed(&raw) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("own-shadow-engine: this engine could not capture the input: {e}");
            return std::process::ExitCode::from(3);
        }
    };
    // This engine's OWN reading of the input's canonical identity. A refusal
    // here is data, not an error: it says these bytes are not a document this
    // engine can name, and the driver needs that separately from what the
    // layers did.
    let (canonical, canonical_error) = match serde_json::from_slice::<Json>(&raw) {
        Ok(value) => (canonical_hash(&value).to_json(), Json::Null),
        Err(e) => (Json::Null, Json::Str(e.to_string())),
    };
    let envelope = object(vec![
        ("own_shadow_engine", Json::Int(PROTOCOL_VERSION)),
        ("engine", captured.engine),
        ("canonical", canonical),
        ("canonical_error", canonical_error),
        (
            "derived_documents",
            captured
                .sarif
                .map_or(Json::Null, |sarif| object(vec![("sarif", sarif)])),
        ),
    ]);
    // `write_all` on the locked handle rather than `println!`: this crate
    // denies `print_stdout`, and a capture is a byte stream rather than a
    // formatted line.
    if let Err(e) = std::io::stdout()
        .lock()
        .write_all(render(&envelope).as_bytes())
    {
        eprintln!("own-shadow-engine: cannot write the capture: {e}");
        return std::process::ExitCode::from(4);
    }
    std::process::ExitCode::SUCCESS
}
