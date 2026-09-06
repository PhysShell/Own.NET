//! The verdict mapping — `ownlang/ownir.py::check_facts` (spec/Bridge.md §5),
//! at the #259 checkpoint-5 surface: every member of the reference's `Finding`.
//! Identity and anchor (`file`, `line`, `column`, `code`, `component`, `event`,
//! `handler`), `kind`, tiering (`advisory`, `severity`), suppression
//! (`ignore_reason`) — and, added here, the synthesized `message` (BR-V4) and
//! the ordered `related`/`flow` evidence slices (BR-V5). The rendered surfaces
//! (BR-V9) are checkpoint 5.3 and live beside this module, never inside it.
//!
//! **Three owners write the message, and only one of them is here.** The BR-V4
//! matrix below synthesizes the wording for every mapped core verdict and for
//! the OWN050/051/052 advisories. The DI and effect verdicts carry the
//! `own-analysis` finder's own message verbatim — the analysis owns its verdict
//! (BR-B1), so rewording it here would be the bridge repairing a verdict. And
//! two flow-local branches interpolate the **core diagnostic's** message, which
//! this core still carries as the code's title; that is the one message the
//! bridge cannot supply, and it is checkpoint 5.2's.
//!
//! The pipeline is BR-V1 verbatim: lower → core `check_module` → map the
//! ERROR-severity core diagnostics only, skipping the closed BR-V2 artifact
//! list, each through its `subject` to a known handle (or refuse, BR-V3) →
//! append DI, effect, OWN050, OWN051 and OWN052 findings in that order → dedup
//! (BR-V7) → stable sort by `(file, line, column or 0, code)` (BR-V8).
//!
//! **Not wired, and refused rather than skipped:** the obligation-protocol
//! analysis (OBL001–005, `ownlang/obligations.py`) has no `own-analysis` port.
//! A document that declares a protocol would get a verdict list with a family
//! silently missing, so it is rejected with a [`BridgeError`] naming the
//! boundary; the verdict fixture ledger records the two reference documents
//! this excludes.
//!
//! **The dedup key is complete.** The reference deduplicates on
//! `(file, line, column, code, component, event, handler, message, kind,
//! advisory, severity, ignore_reason)` — every member except `related`/`flow`
//! (OD-5: two findings differing only in evidence collapse to the first). cp4
//! carried every member but `message` and argued it was exact on the
//! reference's own outputs; the argument is now unnecessary, because the member
//! is here.

// The mapping mirrors `check_facts` branch-for-branch; `expect()` marks
// invariant-backed reads (a value the same function just inserted).
// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules; pub(crate) is the honest
// visibility here (same stance as `mos.rs`).
#![allow(
    clippy::too_many_lines,
    clippy::expect_used,
    clippy::redundant_pub_crate
)]

use crate::lower::{self, as_col, Obj, Own051};
use crate::{ast, BridgeError};
use own_analysis::di::{self, Service, SiteTriple};
use own_analysis::effect::{self, Binding, Effect};
use own_diagnostics::{Diagnostic, Severity};
use own_ir::OwnIr;
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};

/// One evidence step: `(file, line, label)` — the reference's triple, and the
/// shape the Layer 3 golden serializes as a three-element array.
pub type Step = (String, i64, String);

/// One bridge finding — the Rust twin of `ownir.Finding`, every member.
///
/// Field semantics are the reference's: `line` is the C# anchor (the fact's
/// own line — `0` when the fact carries none, as for the anchorless OWN052);
/// `column` is the fact's 1-based column or `None`, never invented; `kind` is
/// the `[resource: <kind>]` tag; `advisory` marks a coverage note (OWN050/
/// 051/052) that never fails a build; `severity` is the intrinsic
/// `"warning"` tier of an unprovable-lifetime subscription or a DI002–005
/// verdict, `None` for a provable leak shown at the host's severity;
/// `ignore_reason` is the `[OwnIgnore("…")]` justification of a suppressed
/// (still counted) finding; `message` is the human verdict (BR-V4); `related`
/// is the unordered set of secondary anchors and `flow` the ORDERED
/// reachability slice (BR-V5), each empty for a single-point finding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub file: String,
    pub line: i64,
    pub column: Option<i64>,
    pub code: String,
    pub component: String,
    pub event: String,
    pub handler: String,
    pub message: String,
    pub kind: String,
    pub advisory: bool,
    pub severity: Option<String>,
    pub related: Vec<Step>,
    pub flow: Vec<Step>,
    pub ignore_reason: Option<String>,
}

impl Finding {
    fn new(file: impl Into<String>, line: i64, code: &str, kind: &str) -> Self {
        Self {
            file: file.into(),
            line,
            column: None,
            code: code.to_owned(),
            component: String::new(),
            event: String::new(),
            handler: String::new(),
            message: String::new(),
            kind: kind.to_owned(),
            advisory: false,
            severity: None,
            related: Vec::new(),
            flow: Vec::new(),
            ignore_reason: None,
        }
    }
}

/// BR-V2: the closed list of bridge-artifact core codes dropped before mapping.
const SKIP: [&str; 5] = ["OWN033", "OWN034", "OWN035", "OWN040", "OWN041"];

/// BR-V4: the inline-lambda note, appended verbatim wherever the record's
/// `lambda` is truthy. A lambda handler has no `-=` handle, so it could never
/// be detached even deliberately — the reference spells that out on the plain
/// subscription wording and on both OWN014 wordings, and nowhere else.
const LAMBDA_NOTE: &str = " — and being an inline lambda it has no '-=' handle, \
                           so it could never be detached";

fn lambda_note(rec: &Obj) -> &'static str {
    if truthy(rec.get("lambda")) {
        LAMBDA_NOTE
    } else {
        ""
    }
}

/// BR-V4, the flow-local half of the matrix: the wording splits on the code,
/// on `pool` (an `ArrayPool` rent is *returned*, not disposed) and — for
/// OWN001 only — on `ever_released`, which separates "released on no path" from
/// "released on some but not all".
///
/// `core_message` is the core diagnostic's own message, used by the two fallback
/// branches a code with no wording of its own takes. This core still carries
/// each code's TITLE there (checkpoint 5.2), which is why the fallback is
/// reached by no case in the measured corpus and by a control that says so.
fn flow_local_message(
    code: &str,
    name: &str,
    pool: bool,
    ever_released: bool,
    core_message: &str,
) -> String {
    if code == "OWN001" {
        return match (pool, ever_released) {
            (true, true) => format!(
                "pooled buffer '{name}' may not be returned to the pool on every path (leak)"
            ),
            (true, false) => {
                format!("pooled buffer '{name}' is rented but never returned to the pool (leak)")
            }
            (false, true) => {
                format!("IDisposable local '{name}' may not be disposed on every path (leak)")
            }
            (false, false) => format!("IDisposable local '{name}' is never disposed (leak)"),
        };
    }
    if pool {
        return match code {
            "OWN002" => format!("pooled buffer '{name}' is used after it is returned to the pool"),
            "OWN003" => {
                format!("pooled buffer '{name}' is returned to the pool more than once")
            }
            "OWN009" => {
                format!("pooled buffer '{name}' may be used after being returned on some path")
            }
            _ => format!("pooled buffer '{name}': {core_message}"),
        };
    }
    match code {
        "OWN002" => format!("IDisposable local '{name}' is used after it is disposed"),
        "OWN003" => format!("IDisposable local '{name}' is disposed more than once"),
        "OWN009" => {
            format!("IDisposable local '{name}' may be used after disposal on some path")
        }
        _ => format!("IDisposable local '{name}': {core_message}"),
    }
}

/// `_FLOW_LOCAL_VIOLATION`: the label of the site where a flow-local
/// obligation is violated. A plain leak (OWN001) has no second site — the
/// acquire IS the finding — so it is absent here and gets no slice.
fn flow_local_violation(code: &str) -> Option<&'static str> {
    match code {
        "OWN002" => Some("used here after it was released/returned"),
        "OWN003" => Some("released/returned here a second time"),
        "OWN009" => Some("may be used here after release on some path"),
        "OWN025" => Some("viewed here at full length, past what it was rented for"),
        _ => None,
    }
}

/// BR-V5: the two-step flow-local slice — the Rent/acquire site (where the
/// resource came from) → the site where its obligation is violated. Empty when
/// either line is unknown or the two sites coincide, which is the "a slice
/// shorter than two steps is dropped" rule in its concrete form here.
fn flow_local_steps(rec: &Obj, code: &str, dline: i64, pool: bool) -> Vec<Step> {
    let Some(violation) = flow_local_violation(code) else {
        return Vec::new();
    };
    let acquire = as_int(rec.get("line"));
    if acquire < 1 || dline < 1 || dline == acquire {
        return Vec::new();
    }
    let file = get_or(rec, "file", "?");
    let name = get_or(rec, "event", "?");
    let origin = if pool {
        format!("rented '{name}' here")
    } else {
        format!("acquired '{name}' here")
    };
    vec![
        (file.clone(), acquire, origin),
        (file, dline, violation.to_owned()),
    ]
}

/// BR-V4: the `nice` phrase for a DI-registered source's lifetime. An
/// unrecognised lifetime is named, not hidden — the reference interpolates it.
fn di_life_phrase(life: &str) -> String {
    match life {
        "singleton" => "a DI singleton (application-lifetime) service".to_owned(),
        "scoped" => "a DI scoped service".to_owned(),
        "transient" => "a DI transient service".to_owned(),
        other => format!("a DI {other} service"),
    }
}

/// BR-V5: a DI dependency path rendered as ordered evidence steps, each hop
/// anchored at that service's registration site (`evidence.di_path_steps`).
///
/// A hop whose registration site is unknown is **skipped**, leaving the slice
/// ordered and truthful rather than wrong. Note what this builder does NOT do:
/// it has no "shorter than two steps" guard, so a path with exactly one
/// resolvable hop emits a ONE-step `flow`. Only the OWN014 escape slice, the
/// flow-local slice and the effect slice drop a short slice.
fn di_path_steps(
    path: &[String],
    loc: &BTreeMap<String, (String, i64)>,
    end_label: &str,
) -> Vec<Step> {
    let last = path.len().saturating_sub(1);
    path.iter()
        .enumerate()
        .filter_map(|(i, name)| {
            let (file, line) = loc.get(name.as_str())?;
            let label = if i == 0 {
                format!("singleton '{name}' (captor)")
            } else if i == last {
                format!("{end_label} '{name}'")
            } else {
                format!("via '{name}'")
            };
            Some((file.clone(), *line, label))
        })
        .collect()
}

/// The end-of-path label each DI family uses — the one word that says what the
/// captor did with the service it reached.
const fn di_end_label(code: &str) -> &'static str {
    match code.as_bytes() {
        b"DI002" => "weakly captures scoped service",
        b"DI003" => "captures transient IDisposable",
        b"DI004" => "leaks transient IDisposable",
        b"DI005" => "caches scoped service",
        _ => "captures scoped service",
    }
}

/// Python `str(v)` for the JSON scalars a record field can hold (the
/// containers a scalar field cannot hold on either door are rendered as
/// JSON text — the same boundary `lower.rs` states for `py_str`).
fn py_str(v: &Value) -> String {
    lower::py_str(v)
}

/// `rec.get(key, default)` stringified — a PRESENT value of any type reads
/// through `str()`, only an absent key takes the default.
fn get_or(rec: &Obj, key: &str, default: &str) -> String {
    rec.get(key).map_or_else(|| default.to_owned(), py_str)
}

fn get_str<'a>(rec: &'a Obj, key: &str) -> Option<&'a str> {
    rec.get(key).and_then(Value::as_str)
}

/// `_as_int`: a non-bool integer or `0`.
fn as_int(v: Option<&Value>) -> i64 {
    v.and_then(Value::as_i64).unwrap_or(0)
}

/// Python truthiness of a present value (absent = falsy).
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python `{x!r}` for the two values the map-or-raise message interpolates:
/// `None`, or a string through `CPython`'s `repr`.
///
/// The quote choice is the load-bearing half, and cp4's placeholder got it
/// wrong because the comparison was cut before it: `CPython` uses `'` unless the
/// string contains a `'` and no `"`, in which case it switches to `"` rather
/// than escaping. Every core message that quotes a name — `undefined name
/// 'loc_0'` — takes that branch, so a single-quote-always port differs on
/// every one of them.
///
/// Escaping covers the backslash, the active quote and the ASCII control
/// range, which is `CPython`'s rule for every character a diagnostic message can
/// hold; printable non-ASCII (the em dash the wordings use) passes through
/// unescaped, as it does there. A NON-printable non-ASCII character would
/// diverge, and cannot occur: these messages are built from source identifiers
/// and fixed English text.
fn py_repr(v: Option<&str>) -> String {
    let Some(s) = v else {
        return "None".to_owned();
    };
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len().saturating_add(2));
    out.push(quote);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c.is_ascii_control() => {
                // `\xNN`, lowercase hex, exactly as `CPython` writes it. An
                // ASCII control fits in one byte, so both nibbles are digits.
                let byte = u32::from(c);
                out.push_str("\\x");
                for shift in [4_u32, 0] {
                    let nibble = (byte >> shift) & 0xf;
                    out.push(char::from_digit(nibble, 16).unwrap_or('0'));
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `_route_resource(rkind)[1]`: the `[resource: …]` label of an owned kind —
/// fail-loud on an unknown one, like the reference (IR4 everywhere).
fn route_kind(rkind: &str) -> Result<&'static str, BridgeError> {
    match rkind {
        "subscription" | "subscribe" => Ok("subscription token"),
        "timer" => Ok("timer"),
        "disposable" => Ok("disposable field"),
        "local-disposable" => Ok("disposable"),
        "pool" => Ok("pooled buffer"),
        other => Err(BridgeError(format!(
            "unknown resource kind '{other}' — a new kind is a vocabulary change \
             that must bump OWNIR_VERSION (see spec/OwnIR.md §2)"
        ))),
    }
}

/// `_handle_of(diag)`: the handle a core verdict is about, from its
/// structured `subject` (`name#line`) — never from the message text.
fn handle_of(d: &Diagnostic) -> Option<&str> {
    d.subject
        .as_deref()
        .filter(|s| !s.is_empty())
        .map(|s| s.split('#').next().unwrap_or(s))
}

/// BR-V3: the reference's `OwnIRError` text for a core verdict no handle
/// claims. The `message=` member interpolates the core diagnostic's message,
/// which this core still carries as its TITLE (message text is checkpoint 5) —
/// the verdict replay compares this rejection on the class, up to that member.
fn cannot_map(d: &Diagnostic) -> BridgeError {
    BridgeError(format!(
        "internal: the core reported [{}] on the lowered facts that the bridge \
         cannot map back to a C# subscription (subject={}, message={}). The OwnIR \
         lowering has drifted from the core; teach the bridge this diagnostic \
         rather than dropping the finding.",
        d.code,
        py_repr(d.subject.as_deref()),
        py_repr(Some(&d.message)),
    ))
}

/// BR-V1/BR-V2, as one pure predicate: a core diagnostic is mapped iff it is
/// an ERROR-severity verdict (a sub-error core diagnostic is not a verdict)
/// and its code is not on the closed bridge-artifact list.
///
/// The severity half cannot be reached from a facts document today — no
/// producer feeds the one core pass that grades below ERROR (the buffer-policy
/// warnings) — so it is proven on a synthetic diagnostic in this module's
/// tests rather than left as a rule the corpus can never fail.
fn is_mapped(d: &Diagnostic) -> bool {
    d.severity == Severity::Error && !SKIP.contains(&d.code.as_str())
}

/// The core half of BR-V1: map each mapped core diagnostic ([`is_mapped`])
/// through its handle record to a finding — anchor, kind and tier per
/// BR-V4/V5/V6.
fn map_core(
    diags: &[Diagnostic],
    records: &std::collections::HashMap<String, Obj>,
    svc_loc: &BTreeMap<String, (String, i64)>,
) -> Result<Vec<Finding>, BridgeError> {
    let mut out = Vec::new();
    for d in diags.iter().filter(|d| is_mapped(d)) {
        let Some(rec) = handle_of(d).and_then(|h| records.get(h)) else {
            return Err(cannot_map(d));
        };
        let event = get_or(rec, "event", "?");
        let handler = get_or(rec, "handler", "?");
        let component = rec
            .get("component")
            .map(py_str)
            .expect("every handle record carries its component");
        let file = rec
            .get("file")
            .map(py_str)
            .expect("every handle record carries its file");
        let rkind = get_str(rec, "resource").unwrap_or("subscription");
        // `sub.get("ignore_reason") or None`: an empty string never suppresses.
        let ir = rec
            .get("ignore_reason")
            .filter(|v| truthy(Some(v)))
            .map(py_str);
        let anchor = as_int(rec.get("line"));
        let column = as_col(rec.get("column"));
        if rkind == "flow-local" {
            let pool = truthy(rec.get("pool"));
            let name = &event;
            if d.code == "OWN025" {
                // the VIEW site (the core's line), never the acquire's column.
                let mut f = Finding::new(file, i64::from(d.line), "OWN025", "pooled buffer");
                f.component = component;
                f.message = format!(
                    "pooled buffer '{name}' is viewed at its full length, past the \
                     logical length it was rented for (over-read / over-clear)"
                );
                // the pool wording is forced here: an `overspan` is always a rent.
                f.flow = flow_local_steps(rec, &d.code, i64::from(d.line), true);
                f.event = event;
                out.push(f);
                continue;
            }
            let mut f = Finding::new(
                file,
                anchor,
                &d.code,
                if pool { "pooled buffer" } else { "disposable" },
            );
            f.column = column;
            f.component = component;
            f.message = flow_local_message(
                &d.code,
                name,
                pool,
                truthy(rec.get("ever_released")),
                &d.message,
            );
            f.flow = flow_local_steps(rec, &d.code, i64::from(d.line), pool);
            f.event = event;
            out.push(f);
            continue;
        }
        if truthy(rec.get("di_source_life")) {
            // OWN014 region escape sourced from the DI graph: the injected event
            // SOURCE is registered with a lifetime that outlives the subscriber,
            // so the strong subscription promotes the component to it. Error-tier.
            let life = rec.get("di_source_life").map_or_else(String::new, py_str);
            let source_type = rec.get("source_type");
            let type_name = source_type.map_or_else(|| "?".to_owned(), py_str);
            let mut f = Finding::new(file.clone(), anchor, &d.code, "subscription token");
            f.message = format!(
                "event '{event}' is subscribed (handler '{handler}') to '{type_name}' — {} \
                 that outlives '{component}'; the strong subscription promotes \
                 '{component}' to the source's lifetime, so it can never be collected — a \
                 captive/region escape (leak, no release path{})",
                di_life_phrase(&life),
                lambda_note(rec),
            );
            // BR-V5: the subscribe site -> where the longer-lived source was
            // registered. The source hop is present only when the services graph
            // knows that registration; a lone first step is dropped.
            if anchor >= 1 {
                // `svc_loc.get(st)` in the reference: an ABSENT `source_type`
                // looks the literal "?" up, and a non-string one can match no
                // key at all (the map is keyed by `str(name)`).
                let key = match source_type {
                    None => Some("?".to_owned()),
                    Some(Value::String(name)) => Some(name.clone()),
                    Some(_) => None,
                };
                if let Some((sf, sl)) = key.and_then(|k| svc_loc.get(&k)).filter(|(_, l)| *l >= 1) {
                    f.flow = vec![
                        (
                            file,
                            anchor,
                            format!("'{component}' subscribes '{event}' to '{type_name}' here"),
                        ),
                        (
                            sf.clone(),
                            *sl,
                            format!(
                                "source '{type_name}' ({life}) registered here — outlives \
                                 '{component}'"
                            ),
                        ),
                    ];
                }
            }
            f.column = column;
            f.component = component;
            f.event = event;
            f.handler = handler;
            f.ignore_reason = ir;
            out.push(f);
            continue;
        }
        if rkind == "capture" {
            // OWN014 region escape from the capture route (`event += handler`
            // fire-and-forget): no token to release, so a provable leak at
            // error tier. No escape slice — there is no registration hop.
            let source = get_str(rec, "source").unwrap_or("?");
            let origin = if source == "static" {
                "a static (process-lived) event source".to_owned()
            } else {
                let named = rec.get("source").map_or_else(|| "?".to_owned(), py_str);
                format!("a longer-lived source ('{named}')")
            };
            let mut f = Finding::new(file, anchor, &d.code, "subscription token");
            f.message = format!(
                "event '{event}' is subscribed (handler '{handler}') to {origin} that \
                 outlives '{component}'; the strong subscription promotes '{component}' \
                 to the source's lifetime, so it can never be collected — a region escape \
                 (leak, no release path{})",
                lambda_note(rec),
            );
            f.column = column;
            f.component = component;
            f.event = event;
            f.handler = handler;
            f.ignore_reason = ir;
            out.push(f);
            continue;
        }
        let kind = route_kind(rkind)?;
        // P-004 tiering: only the plain `+=` subscription and the ignored
        // `.Subscribe()` result grade on the source's proven lifetime; every
        // other kind is a provable leak at the host's severity.
        let injected = get_str(rec, "source") == Some("injected");
        let severity = match rkind {
            "timer" | "disposable" | "local-disposable" | "pool" => None,
            _ if injected => Some("warning".to_owned()),
            _ => None,
        };
        // BR-V4, the token half of the matrix. `of_type` is a TRUTHINESS test
        // on the record's `type`: an empty string adds no parenthetical, the
        // same rule the core's `kind_suffix` follows for its own tag.
        let of_type = rec
            .get("type")
            .filter(|v| truthy(Some(v)))
            .map_or_else(String::new, |v| format!(" (type '{}')", py_str(v)));
        let message = match rkind {
            "timer" => format!(
                "timer '{event}' (handler '{handler}') is started but never stopped or \
                 detached — the running timer keeps '{component}' alive (leak)"
            ),
            "disposable" => format!(
                "IDisposable field '{event}'{of_type} is never disposed — its owner \
                 '{component}' leaks it (leak)"
            ),
            "local-disposable" => {
                format!("local IDisposable '{event}'{of_type} is created but never disposed (leak)")
            }
            "subscribe" if injected => format!(
                "the result of '{event}' is ignored — its IDisposable subscription is \
                 never disposed; the source is an injected dependency whose lifetime is \
                 unknown, so it may outlive and keep '{component}' alive (possible leak)"
            ),
            "subscribe" => format!(
                "the result of '{event}' is ignored — the IDisposable subscription is \
                 never disposed, leaking '{component}' (leak)"
            ),
            "pool" => {
                format!("pooled buffer '{event}' is rented but never returned to the pool (leak)")
            }
            _ if injected => format!(
                "event '{event}' is subscribed (handler '{handler}') but never \
                 unsubscribed; its source is an injected dependency whose lifetime is \
                 unknown, so it may outlive and keep '{component}' alive (possible leak{})",
                lambda_note(rec),
            ),
            _ => format!(
                "event '{event}' is subscribed (handler '{handler}') but never \
                 unsubscribed — the source keeps '{component}' alive (leak{})",
                lambda_note(rec),
            ),
        };
        let mut f = Finding::new(file, anchor, &d.code, kind);
        f.message = message;
        f.column = column;
        f.component = component;
        f.event = event;
        f.handler = handler;
        f.severity = severity;
        f.ignore_reason = ir;
        out.push(f);
    }
    Ok(out)
}

/// A coordinate handed to `own-analysis` as an anchor: `u32` or refuse (the
/// same declared boundary as the AST lines, `ast::core_line`).
fn anchor_line(line: i64, what: &str) -> Result<u32, BridgeError> {
    ast::core_line(line, what)
}

/// A coordinate whose only reader guards on `>= 1` (a DI call/store site, an
/// effect binding's declaration line): a negative value behaves exactly like
/// `0` on every path, so it is folded to `0`; above the domain it would BE
/// read, so that side stays fail-loud.
fn guarded_line(line: i64, what: &str) -> Result<u32, BridgeError> {
    if line < 0 {
        Ok(0)
    } else {
        ast::core_line(line, what)
    }
}

/// `tuple(s.get(key, []))` for the string arrays the strict door types: a
/// present non-array is refused (the reference would char-split a string or
/// crash on anything else — accidental behavior the tolerant door does not
/// promise; #294 OD-1).
fn str_array(s: &Obj, key: &str, what: &str) -> Result<Vec<String>, BridgeError> {
    match s.get(key) {
        None => Ok(Vec::new()),
        Some(Value::Array(items)) => Ok(items.iter().map(py_str).collect()),
        Some(other) => Err(BridgeError(format!(
            "{what} '{key}' must be a JSON array of strings on this door, got {other}"
        ))),
    }
}

/// `_resolve_sites`: `(type, file, line)` per dict entry; a non-list reads as
/// empty, a non-dict entry is skipped.
fn sites(raw: Option<&Value>, what: &str) -> Result<Vec<SiteTriple>, BridgeError> {
    let Some(Value::Array(items)) = raw else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for x in items.iter().filter_map(Value::as_object) {
        out.push((
            get_or(x, "type", ""),
            get_or(x, "file", "?"),
            guarded_line(as_int(x.get("line")), what)?,
        ));
    }
    Ok(out)
}

/// BR-P1: `services[]` → `di.Service` values with the reference's coercions,
/// then the five finders (owned by `own-analysis`) in the bridge's append
/// order, each finding at the analysis-selected primary anchor.
fn di_findings(root: &Obj) -> Result<Vec<Finding>, BridgeError> {
    let Some(Value::Array(raw)) = root.get("services") else {
        return Ok(Vec::new());
    };
    let mut services = Vec::new();
    for s in raw.iter().filter_map(Value::as_object) {
        let name = get_or(s, "name", "?");
        let what = format!("service '{name}'");
        services.push(Service {
            lifetime: di::Lifetime::parse(&get_or(s, "lifetime", "")),
            deps: str_array(s, "deps", &what)?,
            weak_deps: str_array(s, "weak_deps", &what)?,
            root_resolves: str_array(s, "root_resolves", &what)?,
            // only the JSON boolean `true` counts.
            disposable: s.get("disposable") == Some(&Value::Bool(true)),
            file: get_or(s, "file", "?"),
            line: anchor_line(as_int(s.get("line")), &what)?,
            root_resolve_sites: sites(
                s.get("root_resolve_sites"),
                &format!("{what} root_resolve_sites"),
            )?,
            scope_cached: str_array(s, "scope_cached", &what)?,
            scope_cache_sites: sites(
                s.get("scope_cache_sites"),
                &format!("{what} scope_cache_sites"),
            )?,
            ctor_file: get_or(s, "ctor_file", "?"),
            ctor_line: guarded_line(as_int(s.get("ctor_line")), &what)?,
            ctor_type: get_or(s, "ctor_type", ""),
            name,
        });
    }
    // BR-P1: the registration site of every service whose line is known — the
    // anchor of each hop of a finding's retention path.
    let loc_by_name: BTreeMap<String, (String, i64)> = services
        .iter()
        .filter(|s| s.line >= 1)
        .map(|s| (s.name.clone(), (s.file.clone(), i64::from(s.line))))
        .collect();
    Ok(di::all_di_findings(&services)
        .into_iter()
        .map(|c| {
            let mut f = Finding::new(c.file, i64::from(c.line), c.code, "DI lifetime");
            f.message = c.message;
            f.flow = di_path_steps(&c.path, &loc_by_name, di_end_label(c.code));
            // BR-V5: DI001/002/003 anchor at the registration and point at the
            // consuming constructor; DI004/DI005 anchor at the call/store site
            // and point back at the registration — but only when the site is
            // what they anchored on (otherwise the registration IS the primary).
            f.related = if c.code == "DI004" || c.code == "DI005" {
                if c.site_line >= 1 && c.reg_line >= 1 {
                    vec![(
                        c.reg_file,
                        i64::from(c.reg_line),
                        format!("registration of singleton '{}'", c.singleton),
                    )]
                } else {
                    Vec::new()
                }
            } else if c.consumed_line >= 1 {
                let owner = if c.consumed_type.is_empty() || c.consumed_type == "?" {
                    "consuming constructor".to_owned()
                } else {
                    format!("consuming constructor of '{}'", c.consumed_type)
                };
                vec![(c.consumed_file, i64::from(c.consumed_line), owner)]
            } else {
                Vec::new()
            };
            f.component = c.singleton;
            f.event = c.subject;
            // DI003/002/004/005 are real verdicts shown at `warning`; DI001 is
            // the umbrella captive at the host's severity.
            if c.code != "DI001" {
                f.severity = Some("warning".to_owned());
            }
            f
        })
        .collect())
}

/// BR-P2/BR-D2: `effects[]` re-validated skip-not-coerce, then
/// `find_effect_storms` (owned by `own-analysis`) at the effect's own site.
fn effect_findings(root: &Obj) -> Result<Vec<Finding>, BridgeError> {
    let Some(Value::Array(raw)) = root.get("effects") else {
        return Ok(Vec::new());
    };
    let mut effects = Vec::new();
    'entries: for e in raw.iter().filter_map(Value::as_object) {
        let deps: Vec<String> = match e.get("deps") {
            None => Vec::new(),
            Some(Value::Array(items)) if items.iter().all(Value::is_string) => items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect(),
            Some(_) => continue,
        };
        let io = match e.get("io") {
            None => false,
            Some(Value::Bool(b)) => *b,
            Some(_) => continue,
        };
        let binds_raw: &[Value] = match e.get("bindings") {
            None => &[],
            Some(Value::Array(items)) => items.as_slice(),
            Some(_) => continue,
        };
        let mut bindings = Vec::new();
        for b in binds_raw {
            let Some(b) = b.as_object() else {
                continue 'entries;
            };
            let name_ok = b.get("name").map_or(true, Value::is_string);
            let init_ok = b.get("init").map_or(true, Value::is_string);
            let refs: Vec<String> = match b.get("refs") {
                None => Vec::new(),
                Some(Value::Array(items)) if items.iter().all(Value::is_string) => items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_owned)
                    .collect(),
                Some(_) => continue 'entries,
            };
            if !(name_ok && init_ok) {
                continue 'entries;
            }
            bindings.push(Binding {
                name: get_or(b, "name", "?"),
                init: get_or(b, "init", "unknown"),
                refs,
                line: guarded_line(as_int(b.get("line")), "effect binding")?,
            });
        }
        let component = get_or(e, "component", "?");
        effects.push(Effect {
            deps,
            io,
            bindings,
            file: get_or(e, "file", "?"),
            line: anchor_line(as_int(e.get("line")), &format!("effect in '{component}'"))?,
            component,
        });
    }
    Ok(effect::find_effect_storms(&effects)
        .into_iter()
        .map(|s| {
            let mut f = Finding::new(s.file.clone(), i64::from(s.line), "EFF001", "react effect");
            f.message = s.message();
            // BR-V5: where the effect re-fires -> where the unstable identity is
            // minted (the fix site). Both lines must be real, or no slice.
            if s.line >= 1 && s.decl_line >= 1 {
                f.flow = vec![
                    (
                        s.file.clone(),
                        i64::from(s.line),
                        format!("effect re-runs here on '{}'", s.dep),
                    ),
                    (
                        s.file,
                        i64::from(s.decl_line),
                        format!(
                            "'{}' gets a fresh identity here — stabilise with useMemo",
                            s.origin
                        ),
                    ),
                ];
            }
            f.component = s.component;
            f.event = s.dep;
            f
        })
        .collect())
}

/// `_unresolved_findings`: every `unresolved-subscription` marker as an
/// advisory OWN050 (never lowered, never a leak).
fn unresolved_findings(root: &Obj) -> Vec<Finding> {
    let mut out = Vec::new();
    let Some(Value::Array(comps)) = root.get("components") else {
        return out;
    };
    for comp in comps.iter().filter_map(Value::as_object) {
        let cfile = get_or(comp, "file", "?");
        let cname = get_or(comp, "name", "?");
        let Some(Value::Array(subs)) = comp.get("subscriptions") else {
            continue;
        };
        for sub in subs.iter().filter_map(Value::as_object) {
            if get_str(sub, "resource") != Some("unresolved-subscription") {
                continue;
            }
            let mut f = Finding::new(
                cfile.clone(),
                as_int(sub.get("line")),
                "OWN050",
                "unresolved reference",
            );
            f.column = as_col(sub.get("column"));
            f.component.clone_from(&cname);
            f.event = get_or(sub, "event", "?");
            f.handler = get_or(sub, "handler", "?");
            f.message = format!(
                "cannot verify '{}' — its declaring type is an unresolved reference \
                 (build the project or pass references); leakage analysis skipped",
                f.event
            );
            f.advisory = true;
            out.push(f);
        }
    }
    out
}

fn transfer_note(a: &Own051) -> Finding {
    let mut f = Finding::new(a.file.clone(), a.line, "OWN051", "ownership transfer");
    f.component.clone_from(&a.component);
    f.event.clone_from(&a.arg);
    f.handler.clone_from(&a.callee);
    f.message = format!(
        "cannot verify whether '{}' takes ownership of '{}' (inferred contract: {}); \
         optimistically assuming it does — '{}' is not checked past this call",
        a.callee, a.arg, a.transfer, a.arg
    );
    f.advisory = true;
    f
}

/// The dedup key (BR-V7): every `Finding` member EXCEPT `related` and `flow`.
/// Excluding the evidence is the reference's own rule and a recorded open
/// decision (OD-5) — two findings differing only in evidence collapse to the
/// first — not a shortcut taken here.
type DedupKey = (
    String,
    i64,
    Option<i64>,
    String,
    String,
    String,
    String,
    String,
    String,
    bool,
    Option<String>,
    Option<String>,
);

/// BR-V7 applied: first occurrence wins.
///
/// A named function rather than three lines inside `check_facts`, because it is
/// the only place three members of the key can be shown to matter. With
/// `message` in the key (cp5.1), `event`, `kind` and `severity` became
/// **unobservable** end to end: every wording that varies with them names them,
/// so no facts document can produce two findings equal on the message and
/// differing on one of those. They are still the reference's key members, and
/// the control for them has to drive this function directly — see the test.
fn dedup(findings: &mut Vec<Finding>) {
    let mut seen: HashSet<DedupKey> = HashSet::new();
    findings.retain(|f| seen.insert(dedup_key(f)));
}

fn dedup_key(f: &Finding) -> DedupKey {
    (
        f.file.clone(),
        f.line,
        f.column,
        f.code.clone(),
        f.component.clone(),
        f.event.clone(),
        f.handler.clone(),
        f.message.clone(),
        f.kind.clone(),
        f.advisory,
        f.severity.clone(),
        f.ignore_reason.clone(),
    )
}

/// The obligation-protocol boundary: a document declaring a protocol cannot
/// be given a complete verdict list by this core, so it is refused.
fn refuse_protocols(root: &Obj) -> Result<(), BridgeError> {
    match root.get("protocols") {
        Some(Value::Array(items)) if !items.is_empty() => Err(BridgeError(format!(
            "this document declares {} obligation protocol(s), and the protocol \
             analysis (OBL001–005, ownlang/obligations.py) is not wired into this \
             core yet — refusing rather than returning a verdict list with a family \
             missing (#259 boundary; the verdict fixture ledger records the excluded \
             reference documents)",
            items.len()
        ))),
        _ => Ok(()),
    }
}

/// The port of `check_facts` at the checkpoint-4 surface (see the module docs).
pub(crate) fn check_facts(facts: &OwnIr) -> Result<Vec<Finding>, BridgeError> {
    let root_value = facts.to_value().map_err(|e| BridgeError(e.to_string()))?;
    let root = root_value
        .as_object()
        .expect("a struct serializes to an object");
    refuse_protocols(root)?;

    let lowering = lower::lower_full(facts)?;
    let module = ast::to_module(&lowering.doc)?;
    let diags = own_analysis::check_module(&module);

    // BR-V5: the registration site of every DI service, used to anchor the
    // source hop of an OWN014 escape slice. Built from the RAW records (a
    // malformed entry is skipped, never coerced), like the reference's.
    let mut svc_loc: BTreeMap<String, (String, i64)> = BTreeMap::new();
    if let Some(Value::Array(raw)) = root.get("services") {
        for entry in raw.iter().filter_map(Value::as_object) {
            svc_loc.insert(
                get_or(entry, "name", ""),
                (get_or(entry, "file", "?"), as_int(entry.get("line"))),
            );
        }
    }

    let mut findings = map_core(&diags, &lowering.handles, &svc_loc)?;
    findings.extend(di_findings(root)?);
    findings.extend(effect_findings(root)?);
    // protocol findings would append here (refused above until wired).
    findings.extend(unresolved_findings(root));
    findings.extend(lowering.advisories.iter().map(transfer_note));
    let module_name = root.get("module").map_or_else(|| "?".to_owned(), py_str);
    for reason in &lowering.mos_notes {
        // anchorless by nature: file-level, module-scoped (BR-V5).
        let mut f = Finding::new("?", 0, "OWN052", "method summaries");
        f.component.clone_from(&module_name);
        f.message = format!(
            "interprocedural summary inference failed ({reason}); method summaries \
             skipped — cross-method ownership transfer was not checked this run"
        );
        f.advisory = true;
        findings.push(f);
    }

    dedup(&mut findings);
    // BR-V8: a STABLE sort — ties keep insertion order; an absent column
    // sorts as 0, before every real (>= 1) one, and is never emitted as such.
    findings.sort_by(|a, b| {
        a.file
            .cmp(&b.file)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.column.unwrap_or(0).cmp(&b.column.unwrap_or(0)))
            .then_with(|| a.code.cmp(&b.code))
    });
    Ok(findings)
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::panic, clippy::indexing_slicing)]
mod tests {
    use super::{dedup, di_findings, effect_findings, map_core, Finding, Obj};
    use own_diagnostics::{Diagnostic, Severity};
    use serde_json::{json, Value};
    use std::collections::BTreeMap;
    use std::collections::HashMap;

    fn obj(v: &Value) -> Obj {
        v.as_object().cloned().unwrap()
    }

    /// The reference's own wording for a branch no facts document can reach,
    /// read from `tests/fixtures/unreachable_branches.json`.
    ///
    /// The controls below do NOT carry their own copy of these strings. The
    /// file is what `tests/test_unreachable_branch_probe.py` recorded by
    /// running `check_facts` with its lowering and core substituted — the only
    /// way to ask the oracle about a state its own inputs cannot construct —
    /// and reading it here is what makes "the reference says so" a re-runnable
    /// fact instead of a claim about how carefully someone read `ownir.py`.
    /// Compiled in, so a stale fixture is a build-time change, not a runtime
    /// file lookup inside a unit test.
    fn oracle(key: &str) -> String {
        const RECORDED: &str = include_str!("../../../../tests/fixtures/unreachable_branches.json");
        let doc: Value = serde_json::from_str(RECORDED).expect("the probe record parses");
        assert_eq!(
            doc.get("probe_version").and_then(Value::as_u64),
            Some(1),
            "the probe record changed shape — teach these controls the new version"
        );
        doc.get("messages")
            .and_then(|m| m.get(key))
            .and_then(Value::as_str)
            .unwrap_or_else(|| panic!("the probe record carries no '{key}'"))
            .to_owned()
    }

    /// BR-V1: only ERROR-severity core diagnostics are mapped. The production
    /// path cannot produce a sub-error core verdict today (no facts producer
    /// reaches the buffer-policy pass that grades below ERROR), so the rule is
    /// proven on a synthetic WARNING driven through `map_core` itself: the
    /// same diagnostic, same handle, ERROR → one finding, WARNING → none.
    /// The closed BR-V2 list rides the same predicate: a skipped artifact code
    /// with no subject must be dropped, never reach map-or-raise.
    #[test]
    fn only_error_severity_core_verdicts_are_mapped() {
        let mut records: HashMap<String, Obj> = HashMap::new();
        records.insert(
            "sub_0".to_owned(),
            obj(&json!({
                "event": "bus.E", "handler": "OnE", "line": 7, "released": false,
                "component": "Vm", "file": "Vm.cs"
            })),
        );
        let error = Diagnostic::new("OWN001", "leak", 7)
            .unwrap()
            .with_subject("sub_0#7");
        let warning = error.clone().with_severity(Severity::Warning);
        let artifact = Diagnostic::new("OWN033", "return type", 0).unwrap();

        let no_services = BTreeMap::new();
        let mapped = map_core(&[error], &records, &no_services).unwrap();
        assert_eq!(
            mapped
                .iter()
                .map(|f| (f.file.as_str(), f.line, f.code.as_str()))
                .collect::<Vec<_>>(),
            vec![("Vm.cs", 7, "OWN001")]
        );
        assert!(
            map_core(&[warning], &records, &no_services)
                .unwrap()
                .is_empty(),
            "a sub-error core diagnostic is not a verdict (BR-V1)"
        );
        assert!(
            map_core(&[artifact], &records, &no_services)
                .unwrap()
                .is_empty(),
            "a BR-V2 artifact is dropped before map-or-raise, subject or not"
        );
    }

    /// BR-V3's refusal text quotes the core message through `CPython`'s `repr`,
    /// and the quote choice is not decoration: every core message that names an
    /// identifier contains a `'`, so `repr` switches to `"` rather than
    /// escaping. cp4 shipped a single-quote-always placeholder because the
    /// comparison was cut before this member; cp5.2 removed the cut and the
    /// three `hoist_neg_*` goldens went red on it immediately.
    ///
    /// Expected values below are `repr()` output, taken from `CPython`.
    #[test]
    fn py_repr_matches_cpython_including_the_quote_switch() {
        for (input, want) in [
            (None, "None"),
            (Some("undefined name 'loc_0'"), "\"undefined name 'loc_0'\""),
            (Some("has \"double\" only"), "'has \"double\" only'"),
            (Some("both ' and \""), "'both \\' and \"'"),
            (Some("plain"), "'plain'"),
            (Some("tab\there"), "'tab\\there'"),
            (Some("nl\nhere"), "'nl\\nhere'"),
            (Some("back\\slash"), "'back\\\\slash'"),
            (Some("em — dash"), "'em — dash'"),
            (Some("ctrl\u{1}byte"), "'ctrl\\x01byte'"),
            (Some("both ' and \" and \\"), "'both \\' and \" and \\\\'"),
        ] {
            assert_eq!(super::py_repr(input), want, "repr({input:?})");
        }
    }

    /// BR-V7's three unobservable key members. `event`, `kind` and `severity`
    /// cannot be dropped from the key by any facts document once `message` is
    /// in it: every wording that varies with one of them interpolates it, so a
    /// pair equal on the message and differing on one of the three does not
    /// exist downstream of `check_facts`. The members are the reference's all
    /// the same, so the control drives `dedup` — the production function — on
    /// pairs assembled here instead. (`handler` and `component` DO have such
    /// pairs, and `verdict_dedup_key_members` is the golden that carries them.)
    #[test]
    fn dedup_keeps_findings_that_differ_only_in_an_unobservable_key_member() {
        let base = Finding::new("A.cs", 4, "OWN001", "subscription token");
        for mutate in [
            (|f: &mut Finding| f.event = "other".to_owned()) as fn(&mut Finding),
            |f: &mut Finding| f.kind = "timer".to_owned(),
            |f: &mut Finding| f.severity = Some("warning".to_owned()),
        ] {
            let mut twin = base.clone();
            mutate(&mut twin);
            let mut both = vec![base.clone(), twin];
            dedup(&mut both);
            assert_eq!(
                both.len(),
                2,
                "BR-V7's key must separate these; message is equal on both"
            );
        }
        let mut identical = vec![base.clone(), base];
        dedup(&mut identical);
        assert_eq!(identical.len(), 1, "first occurrence wins");
    }

    /// BR-V4's flow-local FALLBACK: a code with no wording of its own keeps the
    /// core diagnostic's message verbatim after a colon, on both sides of the
    /// pool split. Driven through `map_core` — the production branch — because
    /// no facts document can reach it: the `OwnIR` flow vocabulary is nine ops,
    /// and the only codes they raise on a flow-local handle are OWN001/002/003/
    /// 009/025, every one of which HAS a wording. Same shape as the BR-V1
    /// severity control above: a rule the corpus cannot exercise is proven at
    /// the unit level rather than left unproven or quietly dropped.
    ///
    /// The expected text of this test and the two below is the REFERENCE's own
    /// output, not a reading of its source, and it is not written here either:
    /// [`oracle`] reads it out of the record
    /// `tests/fixtures/unreachable_branches.json`, which
    /// `tests/test_unreachable_branch_probe.py` produces by running
    /// `check_facts` with its lowering substituted. A probe, not a golden — a
    /// golden would need a facts document, which is exactly what does not
    /// exist — but a re-runnable one.
    #[test]
    fn a_flow_local_code_without_a_wording_keeps_the_core_message() {
        let mut records: HashMap<String, Obj> = HashMap::new();
        for (handle, pool) in [("loc_0", false), ("loc_1", true)] {
            records.insert(
                handle.to_owned(),
                obj(&json!({
                    "resource": "flow-local", "event": "s", "line": 4, "pool": pool,
                    "component": "C.M", "file": "A.cs", "ever_released": false
                })),
            );
        }
        let diags: Vec<Diagnostic> = ["loc_0", "loc_1"]
            .iter()
            .map(|h| {
                Diagnostic::new("OWN005", "moved 's' at A.cs:9", 9)
                    .unwrap()
                    .with_subject(format!("{h}#4"))
            })
            .collect();
        let no_services = BTreeMap::new();
        let got: Vec<String> = map_core(&diags, &records, &no_services)
            .unwrap()
            .into_iter()
            .map(|f| f.message)
            .collect();
        assert_eq!(
            got,
            vec![
                oracle("flow_local_fallback_plain"),
                oracle("flow_local_fallback_pooled"),
            ]
        );
    }

    /// BR-V4's DI lifetime phrases. `singleton` and `scoped` have goldens; the
    /// other two are defensive and say so here. A `transient` source can outlive
    /// no subscriber — `transient < scoped < Process` and `Subscriber < Process`
    /// leave nothing shorter than transient — so the lifetime engine never
    /// reports the escape; and an unrecognised lifetime never reaches
    /// `di_source_life` at all, because the DI life map admits only the three.
    #[test]
    fn every_di_lifetime_phrase_is_pinned_including_the_unreachable_two() {
        let mut records: HashMap<String, Obj> = HashMap::new();
        let mut diags = Vec::new();
        for (i, life) in ["transient", "gremlin"].iter().enumerate() {
            let handle = format!("cap_{i}");
            records.insert(
                handle.clone(),
                obj(&json!({
                    "event": "src.E", "handler": "OnE", "line": 7, "component": "Vm",
                    "file": "Vm.cs", "source": "injected", "source_type": "Src",
                    "di_source_life": life
                })),
            );
            diags.push(
                Diagnostic::new("OWN014", "escape", 7)
                    .unwrap()
                    .with_subject(format!("{handle}#7")),
            );
        }
        let no_services = BTreeMap::new();
        let got: Vec<String> = map_core(&diags, &records, &no_services)
            .unwrap()
            .into_iter()
            .map(|f| f.message)
            .collect();
        // The full sentence, not a substring, and not a sentence written here:
        // both come from the recorded probe.
        assert_eq!(
            got,
            vec![
                oracle("own014_di_transient"),
                oracle("own014_di_unknown_lifetime"),
            ]
        );
    }

    /// BR-V4's capture-route origin phrase. The static wording has goldens; the
    /// named-source one is defensive — routing R3 mints a handle only for a
    /// source with a declared capture region, and `static` is the only entry in
    /// that table, so a capture with any other source is skipped at lowering and
    /// never reaches a verdict.
    #[test]
    fn the_capture_route_names_a_non_static_source_it_can_never_be_handed() {
        let mut records: HashMap<String, Obj> = HashMap::new();
        records.insert(
            "cap_0".to_owned(),
            obj(&json!({
                "resource": "capture", "event": "svc.E", "handler": "OnE", "line": 9,
                "component": "Vm", "file": "Vm.cs", "source": "container"
            })),
        );
        let diags = vec![Diagnostic::new("OWN014", "escape", 9)
            .unwrap()
            .with_subject("cap_0#9")];
        let no_services = BTreeMap::new();
        let got = map_core(&diags, &records, &no_services).unwrap();
        assert_eq!(got[0].message, oracle("own014_capture_named_source"));
    }

    /// BR-D2 tolerance (1): a malformed effect entry is SKIPPED as a whole,
    /// never coerced into a spurious verdict. Pinned at the raw-document level
    /// on purpose: the crate's public entry is the typed `OwnIr` constructor,
    /// which refuses these shapes before this rule can run (#294 OD-1 — the
    /// verdict ledger's `door` exclusions measure exactly that), so the
    /// production surface cannot reach the rule and this is the only place
    /// the port can be shown to match the reference line for line.
    #[test]
    fn malformed_effect_entries_are_skipped_not_coerced() {
        let root = obj(&json!({
            "effects": [
                // deps must be a list of strings: `"a"` must not become `["a"]`.
                {"component": "X", "file": "X.tsx", "line": 1, "io": true, "deps": "a",
                 "bindings": [{"name": "a", "init": "object", "refs": [], "line": 1}]},
                // io must be a bool.
                {"component": "Y", "file": "Y.tsx", "line": 2, "io": "yes", "deps": ["o"],
                 "bindings": [{"name": "o", "init": "object", "refs": [], "line": 1}]},
                // a binding's refs must be a list of strings.
                {"component": "Z", "file": "Z.tsx", "line": 3, "io": true, "deps": ["o"],
                 "bindings": [{"name": "o", "init": "object", "refs": "o", "line": 1}]},
                // bindings must be a list.
                {"component": "W", "file": "W.tsx", "line": 4, "io": true, "deps": ["o"],
                 "bindings": "nope"},
                // a binding must be an object.
                {"component": "V", "file": "V.tsx", "line": 5, "io": true, "deps": ["o"],
                 "bindings": ["o"]},
                "not-an-object",
                {"component": "Ok", "file": "Ok.tsx", "line": 9, "io": true, "deps": ["o"],
                 "bindings": [{"name": "o", "init": "object", "refs": [], "line": 8}]}
            ]
        }));
        let got: Vec<(String, i64)> = effect_findings(&root)
            .unwrap()
            .into_iter()
            .map(|f| (f.file, f.line))
            .collect();
        assert_eq!(got, vec![("Ok.tsx".to_owned(), 9)]);
    }

    /// A non-list `effects` block reads as no effects (never a crash).
    #[test]
    fn effects_block_that_is_not_a_list_yields_nothing() {
        let root = obj(&json!({"effects": "nope"}));
        assert!(effect_findings(&root).unwrap().is_empty());
    }

    /// BR-P1 on the raw document: `disposable` counts only as the JSON `true`,
    /// a non-object service entry is skipped, an unknown lifetime is ignored.
    #[test]
    fn di_coercions_match_the_reference() {
        let root = obj(&json!({
            "services": [
                {"name": "App", "lifetime": "singleton", "file": "reg.cs", "line": 5,
                 "deps": ["Conn", "Mystery", "Db"]},
                {"name": "Conn", "lifetime": "transient", "file": "reg.cs", "line": 6,
                 "deps": [], "disposable": "true"},
                {"name": "Mystery", "lifetime": "prototype", "file": "reg.cs", "line": 7,
                 "deps": []},
                {"name": "Db", "lifetime": "scoped", "file": "reg.cs", "line": 8, "deps": []},
                42
            ]
        }));
        let got: Vec<(String, i64, String)> = di_findings(&root)
            .unwrap()
            .into_iter()
            .map(|f| (f.file, f.line, f.code))
            .collect();
        assert_eq!(got, vec![("reg.cs".to_owned(), 5, "DI001".to_owned())]);
    }

    /// A present non-array dependency list is refused on this door (the
    /// reference would char-split a string or crash — accidental, #294 OD-1).
    #[test]
    fn non_array_deps_are_refused_loudly() {
        let root = obj(&json!({
            "services": [{"name": "App", "lifetime": "singleton", "deps": "Db"}]
        }));
        let err = di_findings(&root).unwrap_err();
        assert!(
            err.to_string().contains("'deps' must be a JSON array"),
            "{err}"
        );
    }
}
