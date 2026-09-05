//! The verdict mapping — `ownlang/ownir.py::check_facts` (spec/Bridge.md §5),
//! at the #259 checkpoint-4 surface: every finding's **identity and anchor**
//! (`file`, `line`, `column`, `code`, `component`, `event`, `handler`), its
//! `kind`, its tiering (`advisory`, `severity`) and its suppression
//! (`ignore_reason`) — everything the reference's dedup key and sort key are
//! made of, except the human `message`. Message synthesis (BR-V4), the
//! `related`/`flow` evidence slices and the rendered surfaces are checkpoint 5.
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
//! **Dedup key, minus the message.** The reference deduplicates on
//! `(file, line, column, code, component, event, handler, message, kind,
//! advisory, severity, ignore_reason)`. This checkpoint carries every member
//! but `message`. That is not a weakening on the reference's own outputs:
//! every message is a function of the finding's handle record and code (the
//! flow-local wordings key on `code`/`pool`/`ever_released`, the token
//! wordings on the record, and the same-handle same-code duplicates BR-V7
//! exists for are byte-identical), so two findings equal on the carried key
//! are equal on the message too. The fixture replay measures it on the whole
//! corpus; checkpoint 5 adds the member itself.

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
use std::collections::HashSet;

/// One bridge finding — the Rust twin of `ownir.Finding` at the checkpoint-4
/// surface (the `message`, `related` and `flow` members land with checkpoint 5).
///
/// Field semantics are the reference's: `line` is the C# anchor (the fact's
/// own line — `0` when the fact carries none, as for the anchorless OWN052);
/// `column` is the fact's 1-based column or `None`, never invented; `kind` is
/// the `[resource: <kind>]` tag; `advisory` marks a coverage note (OWN050/
/// 051/052) that never fails a build; `severity` is the intrinsic
/// `"warning"` tier of an unprovable-lifetime subscription or a DI002–005
/// verdict, `None` for a provable leak shown at the host's severity;
/// `ignore_reason` is the `[OwnIgnore("…")]` justification of a suppressed
/// (still counted) finding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub file: String,
    pub line: i64,
    pub column: Option<i64>,
    pub code: String,
    pub component: String,
    pub event: String,
    pub handler: String,
    pub kind: String,
    pub advisory: bool,
    pub severity: Option<String>,
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
            kind: kind.to_owned(),
            advisory: false,
            severity: None,
            ignore_reason: None,
        }
    }
}

/// BR-V2: the closed list of bridge-artifact core codes dropped before mapping.
const SKIP: [&str; 5] = ["OWN033", "OWN034", "OWN035", "OWN040", "OWN041"];

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

/// Python `{x!r}` for the values the map-or-raise message interpolates: a
/// subject is `None` or a simple string, repr'd with single quotes.
fn py_repr(v: Option<&str>) -> String {
    v.map_or_else(|| "None".to_owned(), |s| format!("'{s}'"))
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

/// The core half of BR-V1: map each ERROR-severity core diagnostic through
/// its handle record to a finding — anchor, kind and tier per BR-V4/V5/V6.
fn map_core(
    diags: &[Diagnostic],
    records: &std::collections::HashMap<String, Obj>,
) -> Result<Vec<Finding>, BridgeError> {
    let mut out = Vec::new();
    for d in diags {
        if d.severity != Severity::Error {
            continue;
        }
        if SKIP.contains(&d.code.as_str()) {
            continue;
        }
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
            if d.code == "OWN025" {
                // the VIEW site (the core's line), never the acquire's column.
                let mut f = Finding::new(file, i64::from(d.line), "OWN025", "pooled buffer");
                f.component = component;
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
            f.event = event;
            out.push(f);
            continue;
        }
        if truthy(rec.get("di_source_life")) || rkind == "capture" {
            // OWN014 region escape: DI-sourced or a static capture — error-tier.
            let mut f = Finding::new(file, anchor, &d.code, "subscription token");
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
        let mut f = Finding::new(file, anchor, &d.code, kind);
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
            name,
        });
    }
    Ok(di::all_di_findings(&services)
        .into_iter()
        .map(|c| {
            let mut f = Finding::new(c.file, i64::from(c.line), c.code, "DI lifetime");
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
            let mut f = Finding::new(s.file, i64::from(s.line), "EFF001", "react effect");
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
    f.advisory = true;
    f
}

/// The dedup key (BR-V7) at this checkpoint — see the module docs for the
/// one member (`message`) it does not yet carry, and why that is exact here.
type DedupKey = (
    String,
    i64,
    Option<i64>,
    String,
    String,
    String,
    String,
    String,
    bool,
    Option<String>,
    Option<String>,
);

fn dedup_key(f: &Finding) -> DedupKey {
    (
        f.file.clone(),
        f.line,
        f.column,
        f.code.clone(),
        f.component.clone(),
        f.event.clone(),
        f.handler.clone(),
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

    let mut findings = map_core(&diags, &lowering.handles)?;
    findings.extend(di_findings(root)?);
    findings.extend(effect_findings(root)?);
    // protocol findings would append here (refused above until wired).
    findings.extend(unresolved_findings(root));
    findings.extend(lowering.advisories.iter().map(transfer_note));
    let module_name = root.get("module").map_or_else(|| "?".to_owned(), py_str);
    for _reason in &lowering.mos_notes {
        // anchorless by nature: file-level, module-scoped (BR-V5).
        let mut f = Finding::new("?", 0, "OWN052", "method summaries");
        f.component.clone_from(&module_name);
        f.advisory = true;
        findings.push(f);
    }

    // BR-V7: first occurrence wins.
    let mut seen: HashSet<DedupKey> = HashSet::new();
    findings.retain(|f| seen.insert(dedup_key(f)));
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
    use super::{di_findings, effect_findings, Obj};
    use serde_json::{json, Value};

    fn obj(v: &Value) -> Obj {
        v.as_object().cloned().unwrap()
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
