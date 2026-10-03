//! Heap-effect summaries — H0, the port of `ownlang/heap_effects.py`
//! (docs/notes/heap-effect-summaries.md). INERT: nothing in the bridge's
//! verdict path reads it.
//!
//! The input is the extractor's heap-effect SOURCE FACTS (`ownsharp-extract
//! --heap-effects FILE`), not `OwnIR`: a separate document, so this module
//! takes JSON text rather than an [`own_ir::OwnIr`]. It sits beside `mos.rs`
//! for the same reason the MOS solver does — it is a summary layer of the
//! reference port, solved by a least fixpoint over the call graph's SCC
//! condensation — and it shares the dump emitter of `dump.rs`.
//!
//! The parity contract is BYTE-EXACT: the same sidecar text yields the same
//! dump bytes as `python -m ownlang.heap_effects`, and a rejected sidecar
//! yields the same message text (the validation ORDER is part of that
//! contract and mirrors the reference statement for statement).
//!
//! Lattices (see the reference module doc for their meaning):
//!
//! ```text
//! effect   plain < borrow < borrow_mut < may_escape < unknown
//! writes   none < may < unknown            (instance, static, indirect)
//! returns  sorted root strings, or ["unknown"] (absorbing)
//! ```

// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules; pub(crate) is the honest
// visibility here (same stance as `mos.rs`). `too_many_lines`: `load` mirrors
// the reference's single validation pass so the two orders can be read side by
// side.
#![allow(clippy::redundant_pub_crate, clippy::too_many_lines)]

use crate::dump::emit as emit_py;
use crate::BridgeError;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

const VERSION: i64 = 1;
const MAX_LINE: i64 = 2_147_483_647;

const PLAIN: u8 = 0;
const BORROW: u8 = 1;
const BORROW_MUT: u8 = 2;
const MAY_ESCAPE: u8 = 3;
const UNKNOWN: u8 = 4;
const EFFECTS: [&str; 5] = ["plain", "borrow", "borrow_mut", "may_escape", "unknown"];

const W_NONE: u8 = 0;
const W_MAY: u8 = 1;
const W_UNKNOWN: u8 = 2;
const WRITES: [&str; 3] = ["none", "may", "unknown"];
const WRITE_KINDS: [&str; 3] = ["instance", "static", "indirect"];
const DISPATCHES: [&str; 4] = ["direct", "virtual", "extern", "delegate"];

/// A value's source, as the extractor spells it (validated at load).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum Tok {
    Param(usize),
    Receiver,
    Heap,
    Local(usize),
    Call(usize),
}

/// What a value may be once locals and call results are resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum Root {
    Param(usize),
    Receiver,
    Heap,
    Unknown,
}

impl Root {
    fn render(self) -> String {
        match self {
            Self::Param(i) => format!("param:{i}"),
            Self::Receiver => "receiver".to_owned(),
            Self::Heap => "heap".to_owned(),
            Self::Unknown => "unknown".to_owned(),
        }
    }

    fn parse(s: &str) -> Option<Self> {
        match s {
            "receiver" => Some(Self::Receiver),
            "heap" => Some(Self::Heap),
            "unknown" => Some(Self::Unknown),
            _ => s
                .strip_prefix("param:")
                .and_then(|n| n.parse().ok())
                .map(Self::Param),
        }
    }
}

#[derive(Debug)]
struct Call {
    callee: String,
    dispatch: String,
    receiver: Option<Vec<Tok>>,
    args: Vec<Vec<Tok>>,
}

#[derive(Debug)]
struct Method {
    key: String,
    file: String,
    line: i64,
    receiver: bool,
    return_inert: bool,
    params: Vec<(String, bool)>,
    locals: Vec<Vec<Tok>>,
    derefs: Vec<Tok>,
    writes: Vec<(usize, Vec<Tok>)>,
    stores: Vec<Tok>,
    returns: Vec<Tok>,
    calls: Vec<Call>,
    unknown: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Summary {
    params: Vec<u8>,
    receiver: Option<u8>,
    writes: [u8; 3],
    /// Root strings, sorted as strings (the reference's `sorted`).
    returns: Vec<String>,
}

fn fail(where_: &str, what: &str) -> BridgeError {
    BridgeError(format!("heap-effect facts: {where_}: {what}"))
}

/// Python `type(v) is int` over the integers both JSON readers agree on.
fn int_of(v: Option<&Value>) -> Option<i64> {
    let n = v?.as_number()?;
    if let Some(i) = n.as_i64() {
        return Some(i);
    }
    // a u64 above i64::MAX is still an integer to the reference; it is never
    // a valid index or line, so any out-of-range stand-in reads the same
    n.as_u64().map(|_| i64::MAX)
}

fn strings(v: Option<&Value>) -> Option<Vec<String>> {
    v?.as_array()?
        .iter()
        .map(|x| x.as_str().map(str::to_owned))
        .collect()
}

/// One call before its tokens are validated: callee, dispatch, receiver, args.
type RawCall = (String, String, Option<Vec<String>>, Vec<Vec<String>>);

/// The raw text of every list field, validated as tokens once counts are known.
struct RawMethod {
    key: String,
    file: String,
    line: i64,
    receiver: bool,
    return_inert: bool,
    params: Vec<(String, bool)>,
    locals: Vec<Vec<String>>,
    calls: Vec<RawCall>,
    writes: Vec<(usize, Vec<String>)>,
    derefs: Vec<String>,
    stores: Vec<String>,
    returns: Vec<String>,
    unknown: Vec<String>,
}

fn load(doc: &Value) -> Result<Vec<Method>, BridgeError> {
    let Some(root) = doc.as_object() else {
        return Err(BridgeError(
            "heap-effect facts: the document is not an object".to_owned(),
        ));
    };
    if int_of(root.get("heap_effects_version")) != Some(VERSION) {
        return Err(BridgeError(format!(
            "heap-effect facts: heap_effects_version must be {VERSION}"
        )));
    }
    let raw: Vec<&Map<String, Value>> = match root.get("methods").and_then(Value::as_array) {
        Some(items) => match items.iter().map(Value::as_object).collect::<Option<_>>() {
            Some(objects) => objects,
            None => return Err(methods_shape()),
        },
        None => return Err(methods_shape()),
    };

    let mut methods = Vec::with_capacity(raw.len());
    let mut seen: HashSet<String> = HashSet::new();
    for (i, m) in raw.iter().enumerate() {
        let where_ = format!("method #{i}");
        let bad = |field: &str| {
            fail(
                &where_,
                &format!("field '{field}' is missing or has the wrong type"),
            )
        };

        let key = match m.get("key").and_then(Value::as_str) {
            Some(k) if !k.is_empty() => k.to_owned(),
            _ => return Err(bad("key")),
        };
        if !seen.insert(key.clone()) {
            return Err(fail(&where_, "duplicate key"));
        }
        let file = m
            .get("file")
            .and_then(Value::as_str)
            .ok_or_else(|| bad("file"))?
            .to_owned();
        let line = match int_of(m.get("line")) {
            Some(l) if (0..=MAX_LINE).contains(&l) => l,
            _ => return Err(bad("line")),
        };
        let receiver = m
            .get("receiver")
            .and_then(Value::as_bool)
            .ok_or_else(|| bad("receiver"))?;
        let return_inert = m
            .get("return_inert")
            .and_then(Value::as_bool)
            .ok_or_else(|| bad("return_inert"))?;

        let raw_params = m
            .get("params")
            .and_then(Value::as_array)
            .ok_or_else(|| bad("params"))?;
        let mut params = Vec::with_capacity(raw_params.len());
        for (j, p) in raw_params.iter().enumerate() {
            let p = p.as_object().ok_or_else(|| bad("params"))?;
            let index = int_of(p.get("index"));
            let name = p.get("name").and_then(Value::as_str);
            let inert = p.get("inert").and_then(Value::as_bool);
            let (Some(index), Some(name), Some(inert)) = (index, name, inert) else {
                return Err(bad("params"));
            };
            if !same(index, j) {
                return Err(fail(&where_, &format!("params[{j}] is out of sequence")));
            }
            params.push((name.to_owned(), inert));
        }

        let raw_locals = m
            .get("locals")
            .and_then(Value::as_array)
            .ok_or_else(|| bad("locals"))?;
        let mut locals = Vec::with_capacity(raw_locals.len());
        for (j, l) in raw_locals.iter().enumerate() {
            let l = l.as_object().ok_or_else(|| bad("locals"))?;
            let id = int_of(l.get("id"));
            let named = l.get("name").and_then(Value::as_str).is_some();
            let sources = strings(l.get("sources"));
            let (Some(id), true, Some(sources)) = (id, named, sources) else {
                return Err(bad("locals"));
            };
            if !same(id, j) {
                return Err(fail(&where_, &format!("locals[{j}] is out of sequence")));
            }
            locals.push(sources);
        }

        let raw_calls = m
            .get("calls")
            .and_then(Value::as_array)
            .ok_or_else(|| bad("calls"))?;
        let mut calls = Vec::with_capacity(raw_calls.len());
        for (j, c) in raw_calls.iter().enumerate() {
            let c = c.as_object().ok_or_else(|| bad("calls"))?;
            let args: Option<Vec<Vec<String>>> = c
                .get("args")
                .and_then(Value::as_array)
                .and_then(|a| a.iter().map(|x| strings(Some(x))).collect());
            let recv_raw = c.get("receiver");
            let recv = match recv_raw {
                None | Some(Value::Null) => Some(None),
                Some(v) => strings(Some(v)).map(Some),
            };
            let id = int_of(c.get("id"));
            let callee = c.get("callee").and_then(Value::as_str);
            let dispatch = c.get("dispatch").and_then(Value::as_str);
            let line_ok = matches!(int_of(c.get("line")), Some(l) if (0..=MAX_LINE).contains(&l));
            let (Some(id), Some(callee), Some(dispatch), true, Some(recv), Some(args)) =
                (id, callee, dispatch, line_ok, recv, args)
            else {
                return Err(bad("calls"));
            };
            if !same(id, j) {
                return Err(fail(&where_, &format!("calls[{j}] is out of sequence")));
            }
            if !DISPATCHES.contains(&dispatch) {
                return Err(fail(
                    &where_,
                    &format!("calls[{j}] has an unknown dispatch"),
                ));
            }
            calls.push((callee.to_owned(), dispatch.to_owned(), recv, args));
        }

        let raw_writes = m
            .get("writes")
            .and_then(Value::as_array)
            .ok_or_else(|| bad("writes"))?;
        let mut writes = Vec::with_capacity(raw_writes.len());
        for (j, w) in raw_writes.iter().enumerate() {
            let w = w.as_object().ok_or_else(|| bad("writes"))?;
            let kind = w.get("kind").and_then(Value::as_str);
            let target = strings(w.get("target"));
            let (Some(kind), Some(target)) = (kind, target) else {
                return Err(bad("writes"));
            };
            let Some(k) = WRITE_KINDS.iter().position(|x| *x == kind) else {
                return Err(fail(&where_, &format!("writes[{j}] has an unknown kind")));
            };
            writes.push((k, target));
        }

        let derefs = strings(m.get("derefs")).ok_or_else(|| bad("derefs"))?;
        let stores = strings(m.get("stores")).ok_or_else(|| bad("stores"))?;
        let returns = strings(m.get("returns")).ok_or_else(|| bad("returns"))?;
        let unknown = strings(m.get("unknown")).ok_or_else(|| bad("unknown"))?;

        let raw = RawMethod {
            key,
            file,
            line,
            receiver,
            return_inert,
            params,
            locals,
            calls,
            writes,
            derefs,
            stores,
            returns,
            unknown,
        };
        methods.push(tokens(raw, &where_)?);
    }

    let by_key: HashMap<&str, &Method> = methods.iter().map(|m| (m.key.as_str(), m)).collect();
    for (i, m) in methods.iter().enumerate() {
        for (j, c) in m.calls.iter().enumerate() {
            if c.dispatch != "direct" {
                continue;
            }
            if let Some(callee) = by_key.get(c.callee.as_str()) {
                if c.args.len() != callee.params.len() {
                    return Err(fail(
                        &format!("method #{i}"),
                        &format!(
                            "calls[{j}] has {} argument slots, its callee takes {}",
                            c.args.len(),
                            callee.params.len()
                        ),
                    ));
                }
            }
        }
    }
    Ok(methods)
}

fn methods_shape() -> BridgeError {
    BridgeError("heap-effect facts: methods must be an array of objects".to_owned())
}

fn same(value: i64, position: usize) -> bool {
    i64::try_from(position).is_ok_and(|p| p == value)
}

/// Token validation, in the reference's `_check_tokens` order.
fn tokens(raw: RawMethod, where_: &str) -> Result<Method, BridgeError> {
    let counts = (raw.params.len(), raw.locals.len(), raw.calls.len());
    let receiver = raw.receiver;
    let check = |list: &[String], field: &str| -> Result<Vec<Tok>, BridgeError> {
        list.iter()
            .map(|t| {
                parse_tok(t, receiver, counts).ok_or_else(|| {
                    fail(
                        where_,
                        &format!("{field} holds a token outside the vocabulary"),
                    )
                })
            })
            .collect()
    };
    let mut locals = Vec::with_capacity(raw.locals.len());
    for (j, sources) in raw.locals.iter().enumerate() {
        locals.push(check(sources, &format!("locals[{j}]"))?);
    }
    let derefs = check(&raw.derefs, "derefs")?;
    let mut writes = Vec::with_capacity(raw.writes.len());
    for (j, (kind, target)) in raw.writes.iter().enumerate() {
        writes.push((*kind, check(target, &format!("writes[{j}]"))?));
    }
    let stores = check(&raw.stores, "stores")?;
    let returns = check(&raw.returns, "returns")?;
    let mut calls = Vec::with_capacity(raw.calls.len());
    for (j, (callee, dispatch, recv, args)) in raw.calls.into_iter().enumerate() {
        let receiver = match recv {
            Some(r) => Some(check(&r, &format!("calls[{j}].receiver"))?),
            None => None,
        };
        let mut checked = Vec::with_capacity(args.len());
        for (k, arg) in args.iter().enumerate() {
            checked.push(check(arg, &format!("calls[{j}].args[{k}]"))?);
        }
        calls.push(Call {
            callee,
            dispatch,
            receiver,
            args: checked,
        });
    }
    Ok(Method {
        key: raw.key,
        file: raw.file,
        line: raw.line,
        receiver: raw.receiver,
        return_inert: raw.return_inert,
        params: raw.params,
        locals,
        derefs,
        writes,
        stores,
        returns,
        calls,
        unknown: raw.unknown,
    })
}

/// `(param|local|call):(0|[1-9][0-9]*)` below its count, `heap`, or
/// `receiver` on a method that has one.
fn parse_tok(t: &str, receiver: bool, counts: (usize, usize, usize)) -> Option<Tok> {
    if t == "heap" {
        return Some(Tok::Heap);
    }
    if t == "receiver" {
        return receiver.then_some(Tok::Receiver);
    }
    let (kind, digits) = t.split_once(':')?;
    let canonical = !digits.is_empty()
        && digits.bytes().all(|b| b.is_ascii_digit())
        && (digits == "0" || !digits.starts_with('0'));
    if !canonical {
        return None;
    }
    // a number too large for usize is past every count
    let n: usize = digits.parse().ok()?;
    match kind {
        "param" if n < counts.0 => Some(Tok::Param(n)),
        "local" if n < counts.1 => Some(Tok::Local(n)),
        "call" if n < counts.2 => Some(Tok::Call(n)),
        _ => None,
    }
}

// --- the solver ------------------------------------------------------------

fn bottom(m: &Method) -> Summary {
    Summary {
        params: vec![PLAIN; m.params.len()],
        receiver: m.receiver.then_some(PLAIN),
        writes: [W_NONE; 3],
        returns: Vec::new(),
    }
}

fn callee_unknown(c: &Call, methods: &HashMap<&str, &Method>) -> bool {
    c.dispatch != "direct" || !methods.contains_key(c.callee.as_str())
}

struct Eval<'a> {
    m: &'a Method,
    methods: &'a HashMap<&'a str, &'a Method>,
    solved: &'a HashMap<String, Summary>,
    params: Vec<u8>,
    receiver: u8,
    writes: [u8; 3],
}

impl Eval<'_> {
    fn roots(&self, start: &[Tok]) -> HashSet<Root> {
        let mut out = HashSet::new();
        let mut stack: Vec<Tok> = start.to_vec();
        let mut seen: HashSet<Tok> = HashSet::new();
        while let Some(t) = stack.pop() {
            if !seen.insert(t) {
                continue;
            }
            match t {
                Tok::Param(i) => {
                    out.insert(Root::Param(i));
                }
                Tok::Receiver => {
                    out.insert(Root::Receiver);
                }
                Tok::Heap => {
                    out.insert(Root::Heap);
                }
                Tok::Local(n) => {
                    if let Some(sources) = self.m.locals.get(n) {
                        stack.extend(sources.iter().copied());
                    }
                }
                Tok::Call(k) => {
                    let Some(c) = self.m.calls.get(k) else {
                        continue;
                    };
                    if callee_unknown(c, self.methods) {
                        out.insert(Root::Unknown);
                        continue;
                    }
                    let Some(s) = self.solved.get(&c.callee) else {
                        continue;
                    };
                    for r in &s.returns {
                        match Root::parse(r) {
                            Some(Root::Param(j)) => {
                                if let Some(arg) = c.args.get(j) {
                                    stack.extend(arg.iter().copied());
                                }
                            }
                            // a constructor's receiver is the new object: heap to the caller
                            Some(Root::Receiver) => match &c.receiver {
                                Some(recv) => stack.extend(recv.iter().copied()),
                                None => stack.push(Tok::Heap),
                            },
                            Some(other) => {
                                out.insert(other);
                            }
                            None => {}
                        }
                    }
                }
            }
        }
        out
    }

    fn apply(&mut self, toks: &[Tok], effect: u8, kind: usize) {
        for r in self.roots(toks) {
            match r {
                Root::Param(i) => {
                    let inert = self.m.params.get(i).is_some_and(|p| p.1);
                    if !inert {
                        if let Some(slot) = self.params.get_mut(i) {
                            *slot = (*slot).max(effect);
                        }
                    }
                }
                Root::Receiver => self.receiver = self.receiver.max(effect),
                Root::Heap | Root::Unknown => {
                    if effect >= BORROW_MUT {
                        // an object reached from neither a parameter nor the receiver
                        let level = if r == Root::Unknown || effect == UNKNOWN {
                            W_UNKNOWN
                        } else {
                            W_MAY
                        };
                        if let Some(slot) = self.writes.get_mut(kind) {
                            *slot = (*slot).max(level);
                        }
                    }
                }
            }
        }
    }
}

fn evaluate(
    m: &Method,
    methods: &HashMap<&str, &Method>,
    solved: &HashMap<String, Summary>,
) -> Summary {
    if !m.unknown.is_empty() {
        return Summary {
            params: m
                .params
                .iter()
                .map(|(_, inert)| if *inert { PLAIN } else { UNKNOWN })
                .collect(),
            receiver: m.receiver.then_some(UNKNOWN),
            writes: [W_UNKNOWN; 3],
            returns: if m.return_inert {
                Vec::new()
            } else {
                vec!["unknown".to_owned()]
            },
        };
    }
    let mut e = Eval {
        m,
        methods,
        solved,
        params: vec![PLAIN; m.params.len()],
        receiver: PLAIN,
        writes: [W_NONE; 3],
    };
    e.apply(&m.derefs, BORROW, 0);
    for (kind, target) in &m.writes {
        if *kind == 1 {
            if let Some(slot) = e.writes.get_mut(1) {
                *slot = (*slot).max(W_MAY);
            }
        } else {
            e.apply(target, BORROW_MUT, *kind);
        }
    }
    e.apply(&m.stores, MAY_ESCAPE, 0);
    for c in &m.calls {
        if callee_unknown(c, methods) {
            for arg in &c.args {
                e.apply(arg, UNKNOWN, 0);
            }
            if let Some(recv) = &c.receiver {
                e.apply(recv, UNKNOWN, 0);
            }
            e.writes = [W_UNKNOWN; 3];
            continue;
        }
        let Some(s) = solved.get(&c.callee) else {
            continue;
        };
        for (j, effect) in s.params.iter().enumerate() {
            if let Some(arg) = c.args.get(j) {
                e.apply(arg, *effect, 0);
            }
        }
        if let (Some(effect), Some(recv)) = (s.receiver, &c.receiver) {
            e.apply(recv, effect, 0);
        }
        for (mine, theirs) in e.writes.iter_mut().zip(s.writes) {
            *mine = (*mine).max(theirs);
        }
    }
    let mut returns: BTreeSet<String> = BTreeSet::new();
    if !m.return_inert {
        for r in e.roots(&m.returns) {
            if let Root::Param(i) = r {
                if m.params.get(i).is_some_and(|p| p.1) {
                    continue;
                }
            }
            returns.insert(r.render());
        }
    }
    let returns = if returns.contains("unknown") {
        vec!["unknown".to_owned()]
    } else {
        returns.into_iter().collect()
    };
    Summary {
        params: e.params,
        receiver: m.receiver.then_some(e.receiver),
        writes: e.writes,
        returns,
    }
}

/// Tarjan, iterative, bottom-up — the reference's `_sccs`, frame for frame.
fn sccs(keys: &[String], edges: &BTreeMap<String, Vec<String>>) -> Vec<Vec<String>> {
    let mut index: HashMap<String, usize> = HashMap::new();
    let mut low: HashMap<String, usize> = HashMap::new();
    let mut on_stack: HashSet<String> = HashSet::new();
    let mut stack: Vec<String> = Vec::new();
    let mut out = Vec::new();
    let mut counter: usize = 0;
    let none: Vec<String> = Vec::new();
    for root in keys {
        if index.contains_key(root) {
            continue;
        }
        let mut work: Vec<(String, usize)> = vec![(root.clone(), 0)];
        while let Some((v, pos)) = work.pop() {
            if pos == 0 {
                index.insert(v.clone(), counter);
                low.insert(v.clone(), counter);
                counter = counter.saturating_add(1);
                stack.push(v.clone());
                on_stack.insert(v.clone());
            }
            let succ = edges.get(&v).unwrap_or(&none);
            if let Some(w) = succ.get(pos) {
                work.push((v.clone(), pos.saturating_add(1)));
                if !index.contains_key(w) {
                    work.push((w.clone(), 0));
                } else if on_stack.contains(w) {
                    let wi = index.get(w).copied().unwrap_or(usize::MAX);
                    if let Some(lv) = low.get_mut(&v) {
                        *lv = (*lv).min(wi);
                    }
                }
                continue;
            }
            let lv = low.get(&v).copied().unwrap_or(usize::MAX);
            if Some(&lv) == index.get(&v) {
                let mut comp = Vec::new();
                while let Some(w) = stack.pop() {
                    on_stack.remove(&w);
                    let done = w == v;
                    comp.push(w);
                    if done {
                        break;
                    }
                }
                comp.sort();
                out.push(comp);
            }
            if let Some((parent, _)) = work.last() {
                if let Some(lp) = low.get_mut(parent) {
                    *lp = (*lp).min(lv);
                }
            }
        }
    }
    out
}

fn solve(methods: &[Method]) -> HashMap<String, Summary> {
    let by_key: HashMap<&str, &Method> = methods.iter().map(|m| (m.key.as_str(), m)).collect();
    let mut keys: Vec<String> = methods.iter().map(|m| m.key.clone()).collect();
    keys.sort();
    let mut edges: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for m in methods {
        let callees: BTreeSet<String> = m
            .calls
            .iter()
            .filter(|c| !callee_unknown(c, &by_key))
            .map(|c| c.callee.clone())
            .collect();
        edges.insert(m.key.clone(), callees.into_iter().collect());
    }
    let mut solved: HashMap<String, Summary> =
        methods.iter().map(|m| (m.key.clone(), bottom(m))).collect();
    for comp in sccs(&keys, &edges) {
        let mut changed = true;
        while changed {
            changed = false;
            for k in &comp {
                let Some(m) = by_key.get(k.as_str()) else {
                    continue;
                };
                let new = evaluate(m, &by_key, &solved);
                if solved.get(k) != Some(&new) {
                    solved.insert(k.clone(), new);
                    changed = true;
                }
            }
        }
    }
    solved
}

fn unresolved(m: &Method, methods: &HashMap<&str, &Method>) -> Vec<String> {
    let mut reasons: BTreeSet<String> = m.unknown.iter().cloned().collect();
    for c in &m.calls {
        if c.dispatch != "direct" {
            reasons.insert(format!("{} ({})", c.callee, c.dispatch));
        } else if !methods.contains_key(c.callee.as_str()) {
            reasons.insert(format!("{} (no summary)", c.callee));
        }
    }
    reasons.into_iter().collect()
}

fn effect_label(level: u8) -> &'static str {
    EFFECTS
        .get(usize::from(level))
        .copied()
        .unwrap_or("unknown")
}

fn write_label(level: u8) -> &'static str {
    WRITES.get(usize::from(level)).copied().unwrap_or("unknown")
}

/// Sidecar JSON text → the solved document, rendered byte-identically to
/// `python -m ownlang.heap_effects` (`json.dumps(indent=2, sort_keys=True)`
/// plus a newline).
pub(crate) fn dump_heap_effects(text: &str) -> Result<String, BridgeError> {
    let doc: Value = serde_json::from_str(text)
        .map_err(|_| BridgeError("heap-effect facts: not valid JSON".to_owned()))?;
    let methods = load(&doc)?;
    let by_key: HashMap<&str, &Method> = methods.iter().map(|m| (m.key.as_str(), m)).collect();
    let solved = solve(&methods);
    let mut ordered: Vec<&Method> = methods.iter().collect();
    ordered.sort_by(|a, b| a.key.cmp(&b.key));
    let mut summaries = Vec::with_capacity(ordered.len());
    for m in ordered {
        let s = solved.get(&m.key).cloned().unwrap_or_else(|| bottom(m));
        let params: Vec<Value> = m
            .params
            .iter()
            .enumerate()
            .map(|(i, (name, _))| {
                let level = s.params.get(i).copied().unwrap_or(UNKNOWN);
                json!({"index": i, "name": name, "effect": effect_label(level)})
            })
            .collect();
        let mut writes = Map::new();
        for (i, kind) in WRITE_KINDS.iter().enumerate() {
            let level = s.writes.get(i).copied().unwrap_or(W_UNKNOWN);
            writes.insert((*kind).to_owned(), json!(write_label(level)));
        }
        summaries.push(json!({
            "method": m.key,
            "file": m.file,
            "line": m.line,
            "params": params,
            "receiver": s.receiver.map(effect_label),
            "writes": writes,
            "returns": s.returns,
            "unresolved": unresolved(m, &by_key),
        }));
    }
    let out = json!({"heap_effects_version": VERSION, "summaries": summaries});
    let mut text = String::new();
    emit_py(&out, 0, &mut text);
    text.push('\n');
    Ok(text)
}
