//! Obligation-protocol analysis (OBL001–005) — an exact port of the checker in
//! `ownlang/obligations.py`.
//!
//! A legacy method often breaks one of its *own* invariants on purpose,
//! briefly: `IsLoaded = false` while a document tree is rebuilt,
//! `_suppressNotifications = true` around a batch update, `BeginUpdate()`
//! before a bulk edit. The invariant is allowed to be false — *locally*. The
//! bug is publishing that broken state to the outside world: raising
//! `PropertyChanged("Document")`, returning, or throwing while the flag is
//! still down. No general-purpose checker knows that `IsLoaded` means "the
//! document is consistent"; the project does, and declares it as an
//! **obligation protocol**.
//!
//! Like [`crate::di`] over the DI registration graph and [`crate::effect`] over
//! the render-scope binding graph, this is a **fact-driven** analysis with no
//! `.own` surface: the `OwnIR` bridge feeds it [`Protocol`] rules and
//! [`MethodEvents`] trees, both built by the one grammar in
//! [`own_ir::protocol`], and this module owns the verdict (spec/Bridge.md
//! BR-B1). The codes, the messages and the evidence slices are the bridge's
//! (BR-P3) — a [`Violation`] carries the facts they are synthesized from and
//! not a word of prose.
//!
//! The walk is path-sensitive over the structured event tree: the obligation
//! state is a **set** over `{OPEN, CLOSED}` joined by union at merges, so the
//! definite/maybe split falls out of the lattice exactly as OWN002 vs OWN009
//! does in the core. Loops are solved to a local fixpoint silently and their
//! bodies re-walked once on the converged header state, so a barrier inside a
//! loop reports once — the two-phase emission discipline of the core analyzer,
//! applied per loop.
//!
//! # The precision policy (the project's standing red line: never invent a
//! violation)
//!
//! * an **opaque** write to a tracked flag may *discharge* an obligation but
//!   never *creates* one: if OPEN is possible the state gains CLOSED (the write
//!   may have closed it), and a closed state stays closed;
//! * a call the protocol does not name is **neutral** — it neither discharges
//!   nor crosses. A callee that flips the flag internally is invisible in v1
//!   (interprocedural obligation summaries are the P-025 phase-3 slice);
//! * a call with an **unknown argument** does not match an args-narrowed
//!   barrier ([`own_ir::protocol::Matcher::matches`]);
//! * protocols are explicitly scoped — a rule only ever fires where the project
//!   asked for it.

use own_ir::protocol::{Event, MethodEvents, Protocol};

/// Which kind of crossing a [`Violation`] reports.
///
/// The bridge's `(kind, definite)` table turns this into OBL001–OBL004; the
/// split also decides whether the late-close evidence hop applies, because an
/// exit leak has no barrier to be late for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViolationKind {
    /// A configured barrier fired while the obligation was open.
    Barrier,
    /// The method left — `return`, `throw`, or off the end — while it was open.
    Exit,
}

impl ViolationKind {
    /// The reference's `kind` string, and the fact-parity fixture's spelling.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Barrier => "barrier",
            Self::Exit => "exit",
        }
    }
}

/// One obligation-protocol violation, ready for the bridge to phrase.
///
/// `line` anchors where the violation manifests: the barrier site for a
/// `barrier`/`return`/`throw` crossing, the **open** site for an obligation
/// leaking off the end of the method (the OWN001 precedent: a leak anchors at
/// the acquire). `definite` is the lattice split — `true` when the obligation
/// is open on *every* path reaching the point, `false` when only on some path.
/// `close_line` is the earliest close site after `line`, if one exists: the
/// "closed only here, after the barrier" evidence hop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Violation {
    pub protocol: String,
    pub method: String,
    pub file: String,
    pub line: i64,
    pub kind: ViolationKind,
    pub definite: bool,
    pub open_line: i64,
    /// `OnPropertyChanged(Document)` | `return` | `throw` | `end of method`.
    pub barrier_desc: String,
    pub close_line: Option<i64>,
}

/// The obligation state lattice: a set over `{OPEN, CLOSED}`, joined by union.
///
/// A pair of flags rather than a set type, because the set has exactly two
/// possible members: `{}` is the reference's bottom, and `{OPEN}` — open on
/// every path — is what makes a crossing *definite*.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct States {
    open: bool,
    closed: bool,
}

impl States {
    const BOTTOM: Self = Self {
        open: false,
        closed: false,
    };
    const OPEN: Self = Self {
        open: true,
        closed: false,
    };
    const CLOSED: Self = Self {
        open: false,
        closed: true,
    };

    const fn union(self, other: Self) -> Self {
        Self {
            open: self.open || other.open,
            closed: self.closed || other.closed,
        }
    }
}

/// A path state: which obligation states are possible, plus the earliest open
/// site among the paths where it is open (evidence provenance, min-line joined
/// exactly like the core's `_join_sites`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct State {
    states: States,
    open_line: Option<i64>,
}

impl State {
    const BOTTOM: Self = Self {
        states: States::BOTTOM,
        open_line: None,
    };

    /// The state a method starts in: nothing is owed yet.
    const fn start() -> Self {
        Self {
            states: States::CLOSED,
            open_line: None,
        }
    }

    fn join(self, other: Self) -> Self {
        Self {
            states: self.states.union(other.states),
            open_line: match (self.open_line, other.open_line) {
                (Some(a), Some(b)) => Some(a.min(b)),
                (a, b) => a.or(b),
            },
        }
    }
}

/// Path-sensitive walk of one method's event tree against one protocol.
///
/// Sequences and branches are walked exactly once (the emitting pass); a loop
/// body is iterated to a fixpoint with emission off, then re-walked once on the
/// converged header state.
struct Walker<'a> {
    proto: &'a Protocol,
    method: &'a MethodEvents,
    silent: bool,
    violations: Vec<Violation>,
}

impl<'a> Walker<'a> {
    const fn new(proto: &'a Protocol, method: &'a MethodEvents) -> Self {
        Self {
            proto,
            method,
            silent: false,
            violations: Vec::new(),
        }
    }

    fn emit(&mut self, kind: ViolationKind, line: i64, st: State, desc: String) {
        if self.silent {
            return;
        }
        self.violations.push(Violation {
            protocol: self.proto.name.clone(),
            method: self.method.name.clone(),
            file: self.method.file.clone(),
            line,
            kind,
            // `states == {OPEN}`: open on every path, not merely on one.
            definite: st.states == States::OPEN,
            open_line: st.open_line.unwrap_or(line),
            barrier_desc: desc,
            close_line: None,
        });
    }

    /// One leaf event (`assign` / `call`). The order IS the semantics: opens
    /// before closes before barriers.
    fn leaf(&mut self, ev: &Event, st: State) -> State {
        let p = self.proto;
        if p.opens.matches(ev) {
            // (re-)open: keep the earliest open site as provenance.
            let line = ev.line();
            return State {
                states: States::OPEN,
                open_line: Some(st.open_line.map_or(line, |prev| prev.min(line))),
            };
        }
        if p.closes.matches(ev) {
            return State {
                states: States::CLOSED,
                open_line: None,
            };
        }
        if !st.states.open {
            return st;
        }
        // allow beats barrier: an explicitly safe event never crosses.
        // The reference stops at the FIRST matching barrier; the description
        // it emits is read off the event, never off the barrier, so "any
        // barrier matched" is the same decision without a value to discard.
        if !p.allow.iter().any(|a| a.matches(ev)) && p.barriers.iter().any(|b| b.matches(ev)) {
            let desc = match ev {
                Event::Call { callee, arg, .. } => {
                    format!("{callee}({})", arg.as_deref().unwrap_or(""))
                }
                Event::Assign { target, .. } => format!("{target} = ..."),
                // `leaf` is only ever reached with a leaf event.
                _ => String::new(),
            };
            self.emit(ViolationKind::Barrier, ev.line(), st, desc);
        }
        // opaque write to a tracked flag: may discharge, never opens (the
        // never-invent asymmetry — see the module docs).
        if let Event::Assign {
            target,
            value: None,
            ..
        } = ev
        {
            if p.tracks_target(target) {
                return State {
                    states: st.states.union(States::CLOSED),
                    open_line: st.open_line,
                };
            }
        }
        st
    }

    fn exit(&mut self, line: i64, st: State, desc: &str) {
        if self.proto.exit_barriers && st.states.open {
            self.emit(ViolationKind::Exit, line, st, desc.to_owned());
        }
    }

    /// Returns `(state, alive)`: `alive` is `false` when every path through the
    /// sequence has already left the method.
    fn walk_seq(&mut self, events: &[Event], st: State) -> (State, bool) {
        let mut st = st;
        for ev in events {
            let (next, alive) = self.walk(ev, st);
            st = next;
            if !alive {
                return (st, false);
            }
        }
        (st, true)
    }

    fn walk(&mut self, ev: &Event, st: State) -> (State, bool) {
        match ev {
            Event::Assign { .. } | Event::Call { .. } => (self.leaf(ev, st), true),
            Event::Return { line } => {
                self.exit(*line, st, "return");
                (State::BOTTOM, false)
            }
            Event::Throw { line } => {
                self.exit(*line, st, "throw");
                (State::BOTTOM, false)
            }
            Event::If { then, orelse, .. } => {
                let (s1, a1) = self.walk_seq(then, st);
                let (s2, a2) = self.walk_seq(orelse, st);
                if !a1 && !a2 {
                    return (State::BOTTOM, false);
                }
                let left = if a1 { s1 } else { State::BOTTOM };
                let right = if a2 { s2 } else { State::BOTTOM };
                (left.join(right), true)
            }
            Event::While { body, .. } => {
                // Local fixpoint on the header state, silently. It terminates
                // for the reason the reference's does: the state set only grows
                // under union and the provenance line only falls, and both
                // domains are finite (the lines are the tree's own).
                let mut header = st;
                let was_silent = self.silent;
                self.silent = true;
                loop {
                    let (out, body_alive) = self.walk_seq(body, header);
                    let next = header.join(if body_alive { out } else { State::BOTTOM });
                    if next == header {
                        break;
                    }
                    header = next;
                }
                self.silent = was_silent;
                // One emitting pass over the body on the converged header state
                // (skipped while an enclosing loop is still in its silent
                // phase, which is what keeps a nested loop to one report).
                if !self.silent {
                    self.walk_seq(body, header);
                }
                // Zero iterations are always possible: the exit state is the
                // header.
                (header, true)
            }
        }
    }

    fn run(mut self) -> Vec<Violation> {
        let (st, alive) = self.walk_seq(&self.method.events, State::start());
        if alive && self.proto.exit_barriers && st.states.open {
            // Anchor the leak at the open site (the OWN001 precedent); an
            // unknown provenance anchors at 0.
            let anchor = st.open_line.unwrap_or(0);
            self.emit(ViolationKind::Exit, anchor, st, "end of method".to_owned());
        }
        self.violations
    }
}

/// Every close-event line in the tree, **reachability ignored** — evidence for
/// the "closed only here, after the barrier" hop.
fn close_lines(proto: &Protocol, events: &[Event], out: &mut Vec<i64>) {
    for ev in events {
        match ev {
            Event::Assign { .. } | Event::Call { .. } => {
                if proto.closes.matches(ev) {
                    out.push(ev.line());
                }
            }
            Event::If { then, orelse, .. } => {
                close_lines(proto, then, out);
                close_lines(proto, orelse, out);
            }
            Event::While { body, .. } => close_lines(proto, body, out),
            Event::Return { .. } | Event::Throw { .. } => {}
        }
    }
}

/// Check every protocol against every method in its scope. Deterministic;
/// sorted by location. Port of `obligations.check_protocols`.
#[must_use]
pub fn check_protocols(protocols: &[Protocol], methods: &[MethodEvents]) -> Vec<Violation> {
    let mut out: Vec<Violation> = Vec::new();
    for proto in protocols {
        for method in methods {
            if !proto.applies_to(&method.name) {
                continue;
            }
            let violations = Walker::new(proto, method).run();
            if violations.is_empty() {
                continue;
            }
            let mut closes = Vec::new();
            close_lines(proto, &method.events, &mut closes);
            closes.sort_unstable();
            for mut v in violations {
                // The late-close evidence hop only makes sense for a barrier
                // crossing ("the close exists, but after the publish"); an exit
                // leak has no barrier to be late for.
                if v.kind == ViolationKind::Barrier {
                    v.close_line = closes.iter().find(|c| **c > v.line).copied();
                }
                out.push(v);
            }
        }
    }
    // A STABLE sort, like the reference's: ties keep the protocol-then-method
    // construction order.
    out.sort_by(|a, b| {
        a.file
            .cmp(&b.file)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.protocol.cmp(&b.protocol))
            .then_with(|| a.barrier_desc.cmp(&b.barrier_desc))
    });
    out
}

/// Protocols whose scope matched no reported method — a dead rule.
///
/// Likely a typo'd scope. Surfaced as an advisory, never a verdict: a rule that
/// structurally never fires is decoration, and silently dead project rules are
/// worse than none. Port of `obligations.unmatched_scopes`.
#[must_use]
pub fn unmatched_scopes<'a>(
    protocols: &'a [Protocol],
    methods: &[MethodEvents],
) -> Vec<&'a Protocol> {
    protocols
        .iter()
        .filter(|p| !p.methods.is_empty() && !methods.iter().any(|m| p.applies_to(&m.name)))
        .collect()
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]
mod tests {
    use super::{check_protocols, unmatched_scopes, Violation};
    use own_ir::protocol::{parse_method, parse_protocol, MethodEvents, Protocol};
    use serde_json::json;

    /// The canonical test protocol, in the document shape the grammar takes:
    /// `IsLoaded = false` opens, `IsLoaded = true` closes,
    /// `OnPropertyChanged(Document|Rows)` is a barrier, `OnPropertyChanged(IsBusy)`
    /// is allowed.
    fn doc_load() -> Protocol {
        parse_protocol(&json!({
            "name": "DocLoad",
            "opens": {"kind": "assign", "target": "IsLoaded", "value": false},
            "closes": {"kind": "assign", "target": "IsLoaded", "value": true},
            "barriers": [{"kind": "call", "callee": "OnPropertyChanged",
                          "args": ["Document", "Rows"]}],
            "allow": [{"kind": "call", "callee": "OnPropertyChanged",
                       "args": ["IsBusy", "IsLoaded"]}]
        }))
        .unwrap()
    }

    fn method(events: &serde_json::Value) -> MethodEvents {
        parse_method(&json!({"name": "Ns.VM.Load", "file": "VM.cs", "events": events})).unwrap()
    }

    fn codes(vs: &[Violation]) -> Vec<(&'static str, bool, i64)> {
        vs.iter()
            .map(|v| (v.kind.as_str(), v.definite, v.line))
            .collect()
    }

    fn open_ev() -> serde_json::Value {
        json!({"ev": "assign", "target": "IsLoaded", "value": false, "line": 10})
    }
    fn close_ev() -> serde_json::Value {
        json!({"ev": "assign", "target": "IsLoaded", "value": true, "line": 90})
    }
    fn notify_doc() -> serde_json::Value {
        json!({"ev": "call", "callee": "OnPropertyChanged", "arg": "Document", "line": 50})
    }

    /// The shape the whole family exists for: open → barrier → close is one
    /// definite crossing, anchored at the barrier, with the open as provenance
    /// and the late close as evidence.
    #[test]
    fn open_barrier_close_is_one_definite_crossing() {
        let vs = check_protocols(
            &[doc_load()],
            &[method(&json!([open_ev(), notify_doc(), close_ev()]))],
        );
        assert_eq!(codes(&vs), vec![("barrier", true, 50)]);
        assert_eq!(vs[0].open_line, 10);
        assert_eq!(vs[0].close_line, Some(90));
        assert_eq!(vs[0].barrier_desc, "OnPropertyChanged(Document)");
        assert_eq!(vs[0].file, "VM.cs");
        assert_eq!(vs[0].method, "Ns.VM.Load");
    }

    /// The fixed twin: a close before the barrier is silence. Without it the
    /// test above proves only that the walker emits, not that it decides.
    #[test]
    fn close_before_the_barrier_is_clean() {
        let vs = check_protocols(
            &[doc_load()],
            &[method(&json!([open_ev(), close_ev(), notify_doc()]))],
        );
        assert!(vs.is_empty(), "{vs:?}");
    }

    /// The two-phase loop emission: the fixpoint iterations are silent, so a
    /// barrier inside a loop body reports exactly once — nested loops included.
    #[test]
    fn a_barrier_in_a_loop_reports_exactly_once() {
        let vs = check_protocols(
            &[doc_load()],
            &[method(&json!([
                open_ev(),
                {"ev": "while", "line": 20, "body": [notify_doc()]},
                close_ev()
            ]))],
        );
        assert_eq!(codes(&vs), vec![("barrier", true, 50)]);
        let nested = check_protocols(
            &[doc_load()],
            &[method(&json!([
                open_ev(),
                {"ev": "while", "line": 20, "body": [
                    {"ev": "while", "line": 21, "body": [notify_doc()]}]},
                close_ev()
            ]))],
        );
        assert_eq!(codes(&nested), vec![("barrier", true, 50)]);
    }

    /// The never-invent asymmetry, both halves: an opaque write to a tracked
    /// flag downgrades an open obligation to a maybe, and never opens one.
    #[test]
    fn an_opaque_write_may_discharge_but_never_opens() {
        let downgraded = check_protocols(
            &[doc_load()],
            &[method(&json!([
                open_ev(),
                {"ev": "assign", "target": "IsLoaded", "line": 20},
                notify_doc(),
                close_ev()
            ]))],
        );
        assert_eq!(codes(&downgraded), vec![("barrier", false, 50)]);
        let invented = check_protocols(
            &[doc_load()],
            &[method(&json!([
                {"ev": "assign", "target": "IsLoaded", "line": 5},
                notify_doc()
            ]))],
        );
        assert!(invented.is_empty(), "{invented:?}");
    }

    /// An exit leak anchors at the OPEN site and carries no late-close hop,
    /// even when a close exists later in the tree.
    #[test]
    fn an_end_of_method_leak_anchors_at_the_open() {
        let vs = check_protocols(&[doc_load()], &[method(&json!([open_ev()]))]);
        assert_eq!(codes(&vs), vec![("exit", true, 10)]);
        assert_eq!(vs[0].barrier_desc, "end of method");
        assert_eq!(vs[0].close_line, None);

        let thrown = check_protocols(
            &[doc_load()],
            &[method(&json!([
                open_ev(),
                {"ev": "if", "line": 20, "then": [{"ev": "throw", "line": 25}], "else": []},
                close_ev()
            ]))],
        );
        assert_eq!(codes(&thrown), vec![("exit", true, 25)]);
        assert_eq!(
            thrown[0].close_line, None,
            "an exit leak has no barrier to be late for"
        );
    }

    /// A scope matching nothing is a dead rule; an unscoped protocol never is.
    #[test]
    fn a_dead_scope_is_reported_and_an_unscoped_protocol_is_not() {
        let scoped = parse_protocol(&json!({
            "name": "Ghost",
            "opens": {"kind": "assign", "target": "x", "value": false},
            "closes": {"kind": "assign", "target": "x", "value": true},
            "scope": {"methods": ["VM.Misspelled"]}
        }))
        .unwrap();
        let protocols = [scoped];
        let methods = [method(&json!([]))];
        let dead = unmatched_scopes(&protocols, &methods);
        assert_eq!(
            dead.iter().map(|p| p.name.as_str()).collect::<Vec<_>>(),
            vec!["Ghost"]
        );
        let unscoped = [doc_load()];
        assert!(unmatched_scopes(&unscoped, &[]).is_empty());
    }
}
