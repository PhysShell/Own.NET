//! The obligation-protocol **grammar** (P-025), ported from the shared parser in
//! `ownlang/obligations.py`.
//!
//! # Why this lives in `own-ir` at all
//!
//! `load()` delegates every `protocols[]` and `protocol_functions[]` record to
//! that parser, and wraps its errors as `OwnIRError`. So the parser is part of
//! the strict-door contract even though it lives in another module: a document
//! the parser refuses is a document `load()` refuses. Leaving it out would not
//! be a smaller checkpoint, it would be a strict door with a hole in it — which
//! is what the second census measured, at 47 of 58 permissive cases.
//!
//! # One grammar, two consumers (#259 checkpoint 4b)
//!
//! Checkpoint 1 ported **acceptance only**: these functions answered "is this a
//! well-formed protocol declaration / event tree?" and threw the answer away,
//! because nothing consumed a typed representation. Checkpoint 4b wires the
//! obligation analysis, which needs exactly the value this module was already
//! deriving and discarding.
//!
//! So they now *validate and construct* — one implementation of the grammar,
//! read by two consumers:
//!
//! * the **strict door** ([`crate::strict`]), which takes the record's identity
//!   and drops the rest;
//! * the **analysis** (`own_analysis::obligation`), which takes the value.
//!
//! A second parser in `own-analysis` would be two interpretations of one
//! grammar, which is the drift a single authority exists to prevent — and it
//! would be the reference's shape inverted, since `obligations.py` is *one*
//! module holding the grammar, the types and the walk.
//!
//! # What is here, and what deliberately is not
//!
//! [`Matcher::matches`], [`Matcher::describe`], [`Protocol::applies_to`] and
//! [`Protocol::tracks_target`] are here because the reference defines them on
//! the dataclasses themselves: they are the values' own meaning — a predicate
//! over two facts, a phrase naming a matcher — and none of them decides
//! anything. Every verdict-deciding part (the `{OPEN, CLOSED}` lattice, the
//! walker, the definite/maybe split, emission and ordering) is
//! `own-analysis`'s, and the codes, messages and evidence slices are
//! `own-bridge`'s.
//!
//! # Two rules that are not about types
//!
//! [`parse_protocol`] refuses a protocol that can never fire (no barriers with
//! `exit_barriers: false`) and one whose barrier equals its `opens` matcher (the
//! walk checks opens first, so the barrier is dead). Every value in such a
//! record has the right type and a legal vocabulary; what is wrong is that the
//! record cannot *mean* anything.
//!
//! They are [`OwnIrErrorKind::WellFormedness`]. An earlier revision reported
//! them as `Shape` on the grounds that the taxonomy was already frozen at six —
//! which got the reasoning backwards. The taxonomy was frozen by the *first*
//! census; this mechanism was found by the *second*. Freezing a category set
//! against later evidence, and then filing new mechanisms under the nearest
//! available name, is the precise substitution the enum was built to stop.

use std::collections::BTreeSet;

use serde_json::{Map, Value};

use crate::strict::{defaulted_int_value, name_slot, optional_string, MAX_NESTING_DEPTH};
use crate::{OwnIrError, OwnIrErrorKind};

/// The closed event vocabulary of `protocol_functions[].events` — the `ev`
/// discriminator. Mirrors the flow-op rule (`OwnIR` §5): a present-but-unknown
/// value is rejected, never skipped.
const EVENT_KINDS: [&str; 6] = ["assign", "call", "if", "return", "throw", "while"];

/// Matcher vocabulary for `opens` / `closes` / `barriers` / `allow`.
const MATCHER_KINDS: [&str; 2] = ["assign", "call"];

fn shape(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Shape, message)
}

fn vocabulary(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::Vocabulary, message)
}

/// Right types, legal vocabulary, and still meaningless — see the module doc.
fn well_formed(message: impl Into<String>) -> OwnIrError {
    OwnIrError::new(OwnIrErrorKind::WellFormedness, message)
}

/// Which shape a [`Matcher`] selects. The reference stores the discriminator as
/// a string on a frozen dataclass; an enum is the same value with the
/// vocabulary made unrepresentable-if-wrong.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MatcherKind {
    /// Matches an assign event with the same `target`.
    Assign,
    /// Matches a call event with the same `callee`.
    Call,
}

/// One event pattern (`obligations.Matcher`).
///
/// - `Assign`: matches an assign event with the same `target`; `value` narrows
///   to a specific written boolean (`None` = any value, **including an opaque
///   one**).
/// - `Call`: matches a call event with the same `target` (the callee); a
///   non-empty `args` narrows to calls whose distinguished argument is in the
///   set — a call with an *unknown* argument does not match a narrowed matcher,
///   because a barrier crossing we cannot prove is not invented.
///
/// Equality is the reference's dataclass equality, and it is load-bearing: the
/// `opens in barriers` rule below is a value comparison. `args` is a set, not a
/// list, because the reference stores a `frozenset`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Matcher {
    pub kind: MatcherKind,
    /// assign: the member name; call: the callee name.
    pub target: String,
    /// assign only — `None` means "any written value".
    pub value: Option<bool>,
    /// call only — empty means "any argument".
    pub args: BTreeSet<String>,
}

impl Matcher {
    /// Does this pattern match `event`? Non-leaf events never match.
    ///
    /// The narrowed-args rule is the precision policy in one line: an argument
    /// the frontend could not read is `None`, and `None` is not in any set.
    #[must_use]
    pub fn matches(&self, event: &Event) -> bool {
        match (self.kind, event) {
            (MatcherKind::Assign, Event::Assign { target, value, .. }) => {
                *target == self.target && (self.value.is_none() || *value == self.value)
            }
            (MatcherKind::Call, Event::Call { callee, arg, .. }) => {
                *callee == self.target
                    && (self.args.is_empty() || arg.as_ref().is_some_and(|a| self.args.contains(a)))
            }
            _ => false,
        }
    }

    /// A stable, line-free human phrase for messages (`IsLoaded = true`,
    /// `EndUpdate()`). The bridge interpolates it into the OBL wording and into
    /// the first step of the evidence slice.
    #[must_use]
    pub fn describe(&self) -> String {
        match self.kind {
            MatcherKind::Assign => match self.value {
                None => format!("{} = ...", self.target),
                Some(true) => format!("{} = true", self.target),
                Some(false) => format!("{} = false", self.target),
            },
            MatcherKind::Call => format!("{}()", self.target),
        }
    }
}

/// One project-declared obligation protocol (`obligations.Protocol`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Protocol {
    pub name: String,
    pub opens: Matcher,
    pub closes: Matcher,
    pub barriers: Vec<Matcher>,
    pub allow: Vec<Matcher>,
    /// `return` / `throw` / end-of-body are barriers too (the OWN001 shape: an
    /// obligation may not leak out of the method).
    pub exit_barriers: bool,
    /// Explicit scope: method names the protocol applies to (exact, or a
    /// trailing `Type.Method` suffix). Empty = every method that reports
    /// events. Tight scoping is the false-positive control.
    pub methods: Vec<String>,
    pub description: String,
}

impl Protocol {
    /// Is this protocol in scope for a method named `fn_name`?
    #[must_use]
    pub fn applies_to(&self, fn_name: &str) -> bool {
        self.methods.is_empty()
            || self
                .methods
                .iter()
                .any(|m| fn_name == m || fn_name.ends_with(&format!(".{m}")))
    }

    /// Is `target` one of the flags whose assigns drive this protocol? (The
    /// opaque-write discharge rule asks this.)
    #[must_use]
    pub fn tracks_target(&self, target: &str) -> bool {
        [&self.opens, &self.closes]
            .into_iter()
            .any(|m| m.kind == MatcherKind::Assign && m.target == target)
    }
}

/// One event of a method's ordered tree (`obligations.Event`).
///
/// `line` is an `i64`, not a `u32`: a protocol fact never reaches the core's
/// lowering, so it carries no `u32` coordinate domain and no clamping question
/// — the value travels to the finding's anchor exactly as the document wrote
/// it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    Assign {
        target: String,
        /// `None` = opaque (the frontend saw a non-literal RHS).
        value: Option<bool>,
        line: i64,
    },
    Call {
        callee: String,
        /// The distinguished argument (`nameof`/string literal), if known.
        arg: Option<String>,
        line: i64,
    },
    Return {
        line: i64,
    },
    Throw {
        line: i64,
    },
    If {
        line: i64,
        then: Vec<Self>,
        orelse: Vec<Self>,
    },
    While {
        line: i64,
        body: Vec<Self>,
    },
}

impl Event {
    /// The source line this event reports, whatever its shape. Every variant
    /// carries one (absent in the document reads as `0`), and the walk anchors
    /// on it.
    #[must_use]
    pub const fn line(&self) -> i64 {
        match *self {
            Self::Assign { line, .. }
            | Self::Call { line, .. }
            | Self::Return { line }
            | Self::Throw { line }
            | Self::If { line, .. }
            | Self::While { line, .. } => line,
        }
    }
}

/// One method's ordered event tree, as reported by a frontend
/// (`obligations.MethodEvents`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MethodEvents {
    pub name: String,
    pub file: String,
    pub events: Vec<Event>,
}

/// Parse one `protocols[]` record, fail-loud on any shape violation.
///
/// # Errors
/// [`OwnIrError`] on any shape, vocabulary or identity violation, in the
/// reference parser's order.
pub fn parse_protocol(raw: &Value) -> Result<Protocol, OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!("a protocol must be an object, got {raw}")));
    };
    let name = name_slot(obj, "name", "protocol")?.to_owned();
    let what = format!("protocol '{name}'");

    // Presence is checked for BOTH before either is parsed, so a record missing
    // one reports the requirement rather than a matcher error for the other.
    if !obj.contains_key("opens") || !obj.contains_key("closes") {
        return Err(shape(format!(
            "{what}: 'opens' and 'closes' are both required"
        )));
    }
    // `require_value`: an opens/closes assign matcher must name the written
    // boolean — "any write opens" is not a checkable protocol.
    let opens = matcher(&obj["opens"], &format!("{what} 'opens'"), true)?;
    let closes = matcher(&obj["closes"], &format!("{what} 'closes'"), true)?;

    let barriers = matchers(obj, "barriers", &what)?;
    let allow = matchers(obj, "allow", &what)?;

    let exit_barriers = match obj.get("exit_barriers") {
        None => true,
        Some(Value::Bool(b)) => *b,
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'exit_barriers' must be a boolean, got {other}"
            )))
        }
    };
    if barriers.is_empty() && !exit_barriers {
        return Err(well_formed(format!(
            "{what}: no barriers and exit_barriers is false — the protocol can \
             never fire (a rule that structurally never fires is decoration)"
        )));
    }
    if barriers.contains(&opens) {
        return Err(well_formed(format!(
            "{what}: a barrier equals the 'opens' matcher — the open wins and \
             the barrier can never fire (re-entrancy checks are not supported yet)"
        )));
    }

    let scope: Option<&Map<String, Value>> = match obj.get("scope") {
        None => None,
        Some(Value::Object(m)) => Some(m),
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'scope' must be an object, got {other}"
            )))
        }
    };
    let mut methods: Vec<String> = Vec::new();
    match scope.and_then(|s| s.get("methods")) {
        None => {}
        Some(Value::Array(raw_methods)) => {
            for method in raw_methods {
                // A scope entry is a method NAME the protocol is filtered by, so
                // an empty or mistyped one is an identity failure. The reference
                // raises one message for this and for a non-array `methods`; the
                // ledger separates them because a missing container and an
                // unusable name are different defects.
                let Some(m) = method.as_str().filter(|m| !m.is_empty()) else {
                    return Err(OwnIrError::new(
                        OwnIrErrorKind::Identity,
                        format!("{what}: 'scope.methods' entries must be non-empty strings"),
                    ));
                };
                methods.push(m.to_owned());
            }
        }
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'scope.methods' must be an array of non-empty strings, got {other}"
            )))
        }
    }
    let description = match obj.get("description") {
        None => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'description' must be a string, got {other}"
            )))
        }
    };
    Ok(Protocol {
        name,
        opens,
        closes,
        barriers,
        allow,
        exit_barriers,
        methods,
        description,
    })
}

/// `barriers` / `allow`: an array of matchers, each parsed without the
/// `require_value` rule that only `opens`/`closes` carry.
fn matchers(obj: &Map<String, Value>, key: &str, what: &str) -> Result<Vec<Matcher>, OwnIrError> {
    let Some(v) = obj.get(key) else {
        return Ok(Vec::new());
    };
    let Some(items) = v.as_array() else {
        return Err(shape(format!("{what}: '{key}' must be an array, got {v}")));
    };
    items
        .iter()
        .map(|m| matcher(m, &format!("{what} {key}"), false))
        .collect()
}

/// One matcher object.
fn matcher(raw: &Value, what: &str, require_value: bool) -> Result<Matcher, OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!("{what} must be an object, got {raw}")));
    };
    let kind = obj.get("kind").and_then(Value::as_str);
    let Some(kind) = kind.filter(|k| MATCHER_KINDS.contains(k)) else {
        let got = obj.get("kind").unwrap_or(&Value::Null);
        return Err(vocabulary(format!(
            "{what}: unknown matcher kind {got} — the vocabulary is {MATCHER_KINDS:?}"
        )));
    };
    if kind == "assign" {
        let target = name_slot(obj, "target", what)?.to_owned();
        let value = match obj.get("value") {
            None | Some(Value::Null) => None,
            Some(Value::Bool(b)) => Some(*b),
            Some(other) => {
                return Err(shape(format!(
                    "{what}: assign 'value' must be a boolean, got {other}"
                )))
            }
        };
        if require_value && value.is_none() {
            return Err(shape(format!(
                "{what}: an opens/closes assign matcher must state the written \
                 boolean 'value' — 'any write' cannot open or close an obligation"
            )));
        }
        return Ok(Matcher {
            kind: MatcherKind::Assign,
            target,
            value,
            args: BTreeSet::new(),
        });
    }
    let callee = name_slot(obj, "callee", what)?.to_owned();
    let args = match obj.get("args") {
        None => BTreeSet::new(),
        Some(Value::Array(items)) if items.iter().all(Value::is_string) => items
            .iter()
            .filter_map(Value::as_str)
            .map(ToOwned::to_owned)
            .collect(),
        Some(_) => {
            return Err(shape(format!(
                "{what}: call 'args' must be an array of strings"
            )))
        }
    };
    Ok(Matcher {
        kind: MatcherKind::Call,
        target: callee,
        value: None,
        args,
    })
}

/// Parse one `protocol_functions[]` record.
///
/// # Errors
/// [`OwnIrError`] on any violation in the record or its event tree.
pub fn parse_method(raw: &Value) -> Result<MethodEvents, OwnIrError> {
    let Some(obj) = raw.as_object() else {
        return Err(shape(format!(
            "a protocol function must be an object, got {raw}"
        )));
    };
    let name = name_slot(obj, "name", "protocol function")?.to_owned();
    let what = format!("protocol function '{name}'");
    // `raw.get("file", "?")` — absent defaults, a present non-string is refused.
    let file = match obj.get("file") {
        None => "?".to_owned(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => {
            return Err(shape(format!(
                "{what}: 'file' must be a string, got {other}"
            )))
        }
    };
    let events = events(obj.get("events"), &what, 0)?;
    Ok(MethodEvents { name, file, events })
}

/// An ordered event list, recursive over `if` / `while`.
///
/// Absent means empty; a present `null` is not a list and is rejected.
///
/// Nesting is bounded by the contract's own domain limit
/// ([`MAX_NESTING_DEPTH`], `spec/OwnIR.md` §4.2), counted in enclosing bodies
/// with the top-level list at 0.
///
/// An earlier revision argued a counter here would be dead code, because
/// `serde_json`'s 128-level parse limit and `to_value`'s guard both fired
/// first. That was true only while the contract had no depth of its own: 32
/// domain levels are reached at roughly 62 JSON levels, so this now fires long
/// before either.
///
/// The check goes **before** the list check, which is where the reference puts
/// it and not where the flow-body equivalent puts it. The asymmetry is real
/// rather than sloppy: the reference reads a missing branch as
/// `e.get("then", [])`, so an absent arm still descends a level, whereas the
/// flow walker probes for a key that may not be there and must not count what
/// it did not find. Two recursions, two contracts.
fn events(raw: Option<&Value>, what: &str, depth: usize) -> Result<Vec<Event>, OwnIrError> {
    if depth > MAX_NESTING_DEPTH {
        return Err(shape(format!(
            "{what}: events nested deeper than {MAX_NESTING_DEPTH} levels"
        )));
    }
    let items: &[Value] = match raw {
        None => &[],
        Some(Value::Array(items)) => items,
        Some(other) => {
            return Err(shape(format!(
                "{what}: events must be an array, got {other}"
            )))
        }
    };
    let mut out: Vec<Event> = Vec::with_capacity(items.len());
    for event in items {
        let Some(obj) = event.as_object() else {
            return Err(shape(format!(
                "{what}: each event must be an object, got {event}"
            )));
        };
        let kind = obj.get("ev").and_then(Value::as_str);
        let Some(kind) = kind.filter(|k| EVENT_KINDS.contains(k)) else {
            let got = obj.get("ev").unwrap_or(&Value::Null);
            return Err(vocabulary(format!(
                "{what}: unknown protocol event {got} — the vocabulary is {EVENT_KINDS:?}"
            )));
        };
        // The line is checked for every kind, before the per-kind fields.
        let line = defaulted_int_value(obj, "line", what)?;
        let next = depth.saturating_add(1);
        out.push(match kind {
            "assign" => {
                let target = name_slot(obj, "target", &format!("{what} assign"))?.to_owned();
                let value = match obj.get("value") {
                    None | Some(Value::Null) => None,
                    Some(Value::Bool(b)) => Some(*b),
                    Some(other) => {
                        return Err(shape(format!(
                            "{what}: assign 'value' must be a boolean or absent \
                             (absent = opaque write), got {other}"
                        )))
                    }
                };
                Event::Assign {
                    target,
                    value,
                    line,
                }
            }
            "call" => {
                let callee = name_slot(obj, "callee", &format!("{what} call"))?.to_owned();
                optional_string(obj, "arg", what)?;
                Event::Call {
                    callee,
                    arg: obj
                        .get("arg")
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned),
                    line,
                }
            }
            "if" => Event::If {
                line,
                then: events(obj.get("then"), what, next)?,
                orelse: events(obj.get("else"), what, next)?,
            },
            "while" => Event::While {
                line,
                body: events(obj.get("body"), what, next)?,
            },
            "return" => Event::Return { line },
            // "throw" — EVENT_KINDS is closed, and checked above.
            _ => Event::Throw { line },
        });
    }
    Ok(out)
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::{parse_method, parse_protocol, Event, Matcher, MatcherKind};
    use serde_json::json;
    use std::collections::BTreeSet;

    fn assign(target: &str, value: Option<bool>) -> Matcher {
        Matcher {
            kind: MatcherKind::Assign,
            target: target.to_owned(),
            value,
            args: BTreeSet::new(),
        }
    }

    /// The grammar builds the value the analysis consumes, not just a verdict
    /// about the record — the whole point of checkpoint 4b's change here.
    #[test]
    fn a_protocol_record_becomes_its_typed_value() {
        let p = parse_protocol(&json!({
            "name": "DocLoad",
            "opens": {"kind": "assign", "target": "IsLoaded", "value": false},
            "closes": {"kind": "assign", "target": "IsLoaded", "value": true},
            "barriers": [{"kind": "call", "callee": "OnPropertyChanged",
                          "args": ["Document", "Rows"]}],
            "allow": [{"kind": "call", "callee": "OnPropertyChanged", "args": ["IsBusy"]}],
            "scope": {"methods": ["VM.Load"]},
            "description": "d"
        }))
        .unwrap();
        assert_eq!(p.name, "DocLoad");
        assert_eq!(p.opens, assign("IsLoaded", Some(false)));
        assert_eq!(p.closes, assign("IsLoaded", Some(true)));
        assert_eq!(p.barriers.len(), 1);
        assert_eq!(p.allow.len(), 1);
        assert!(p.exit_barriers, "absent 'exit_barriers' defaults to true");
        assert_eq!(p.methods, vec!["VM.Load".to_owned()]);
        assert_eq!(p.description, "d");
        assert!(p.tracks_target("IsLoaded"));
        assert!(!p.tracks_target("Title"));
        assert!(p.applies_to("Ns.VM.Load"), "a Type.Method suffix matches");
        assert!(p.applies_to("VM.Load"), "an exact name matches");
        assert!(!p.applies_to("Ns.VM.LoadAll"), "a prefix is not a suffix");
        assert!(!p.applies_to("Ns.OtherVM.Load2"));
    }

    /// `describe()` is the phrase the bridge interpolates; the opaque form is
    /// the one no `opens`/`closes` can reach, and a barrier can.
    #[test]
    fn describe_covers_every_matcher_form() {
        assert_eq!(assign("IsLoaded", Some(true)).describe(), "IsLoaded = true");
        assert_eq!(
            assign("IsLoaded", Some(false)).describe(),
            "IsLoaded = false"
        );
        assert_eq!(assign("IsLoaded", None).describe(), "IsLoaded = ...");
        assert_eq!(
            Matcher {
                kind: MatcherKind::Call,
                target: "EndUpdate".to_owned(),
                value: None,
                args: BTreeSet::new(),
            }
            .describe(),
            "EndUpdate()"
        );
    }

    /// The precision policy, at the matcher: a narrowed barrier does not match
    /// an argument it does not name, and does not match an argument the
    /// frontend could not read.
    #[test]
    fn a_narrowed_call_matcher_never_matches_an_unknown_argument() {
        let narrowed = Matcher {
            kind: MatcherKind::Call,
            target: "OnPropertyChanged".to_owned(),
            value: None,
            args: std::iter::once("Document".to_owned()).collect(),
        };
        let call = |arg: Option<&str>| Event::Call {
            callee: "OnPropertyChanged".to_owned(),
            arg: arg.map(ToOwned::to_owned),
            line: 1,
        };
        assert!(narrowed.matches(&call(Some("Document"))));
        assert!(!narrowed.matches(&call(Some("Totals"))));
        assert!(!narrowed.matches(&call(None)));
        let wide = Matcher {
            args: BTreeSet::new(),
            ..narrowed
        };
        assert!(wide.matches(&call(None)), "an un-narrowed matcher matches");
    }

    /// An assign matcher with no `value` matches ANY write, the opaque one
    /// included — which is what lets a barrier name a flag without a value.
    #[test]
    fn an_unvalued_assign_matcher_matches_every_write() {
        let any = assign("IsLoaded", None);
        for value in [Some(true), Some(false), None] {
            assert!(any.matches(&Event::Assign {
                target: "IsLoaded".to_owned(),
                value,
                line: 1
            }));
        }
        assert!(!any.matches(&Event::Assign {
            target: "Other".to_owned(),
            value: None,
            line: 1
        }));
    }

    /// A method record becomes its tree, `if`/`while` nested, with the file
    /// default the reference uses.
    #[test]
    fn a_method_record_becomes_its_event_tree() {
        let m = parse_method(&json!({
            "name": "VM.Load",
            "events": [
                {"ev": "assign", "target": "IsLoaded", "value": false, "line": 10},
                {"ev": "if", "line": 20,
                 "then": [{"ev": "call", "callee": "Notify", "arg": "Doc", "line": 21}],
                 "else": [{"ev": "return", "line": 22}]},
                {"ev": "while", "line": 30, "body": [{"ev": "throw", "line": 31}]}
            ]
        }))
        .unwrap();
        assert_eq!(m.file, "?", "an absent 'file' defaults to '?'");
        let Some(Event::If { then, orelse, .. }) = m.events.get(1) else {
            panic!("the second event is an if")
        };
        assert_eq!(
            then.first(),
            Some(&Event::Call {
                callee: "Notify".to_owned(),
                arg: Some("Doc".to_owned()),
                line: 21
            })
        );
        assert_eq!(orelse.first(), Some(&Event::Return { line: 22 }));
        let Some(Event::While { body, .. }) = m.events.get(2) else {
            panic!("the third event is a while")
        };
        assert_eq!(body.first(), Some(&Event::Throw { line: 31 }));
    }

    /// An absent `line` reads as `0`, and a negative one travels: the protocol
    /// path has no `u32` coordinate domain to clamp against.
    #[test]
    fn an_absent_line_is_zero_and_a_negative_one_survives() {
        let m = parse_method(&json!({
            "name": "m",
            "events": [{"ev": "return"}, {"ev": "throw", "line": -3}]
        }))
        .unwrap();
        assert_eq!(m.events.first(), Some(&Event::Return { line: 0 }));
        assert_eq!(m.events.get(1), Some(&Event::Throw { line: -3 }));
    }
}
