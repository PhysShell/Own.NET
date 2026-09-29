//! Reading the fact surface: `functions[]` records, their A2 sidecar, and the
//! fail-closed join of the legacy `body` to the sidecar (B0 A4/A15).
//!
//! Every place where the facts do not determine an answer returns an `Err`
//! reason, which the report shows as `NO_GUARDED_EVIDENCE`. Nothing here reads
//! a summary or decides a transfer.

use own_ir::{Function, OwnIr};
use serde_json::{Map, Value};

/// A `NO_GUARDED_EVIDENCE` reason.
pub(crate) type Nge = String;

fn err<T>(reason: &str) -> Result<T, Nge> {
    Err(reason.to_owned())
}

/// Declared parameter types that are never an owned disposable, so never in
/// `functions[].params` (A17: coordinate identity is not a fact; a params-list
/// index maps to a declared ordinal only when every other ordinal is one of
/// these).
const NON_DISPOSABLE: [&str; 21] = [
    "System.Boolean",
    "System.Byte",
    "System.SByte",
    "System.Int16",
    "System.UInt16",
    "System.Int32",
    "System.UInt32",
    "System.Int64",
    "System.UInt64",
    "System.Single",
    "System.Double",
    "System.Decimal",
    "System.Char",
    "System.String",
    "System.Object",
    "System.IntPtr",
    "System.UIntPtr",
    "System.DateTime",
    "System.TimeSpan",
    "System.Guid",
    "System.Threading.CancellationToken",
];

/// One raw argument fact (spec/OwnIR.md §5.2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Arg<'a> {
    Var(&'a str),
    Param {
        ordinal: u64,
        negated: bool,
    },
    Bool(bool),
    Null,
    New,
    /// A call result: a fresh value, never one of the caller's handles.
    CallResult,
    Opaque,
}

/// One sidecar call record; `args` by declared ordinal.
pub(crate) struct Call<'a> {
    pub(crate) site: (i64, i64),
    pub(crate) statement_line: i64,
    pub(crate) form: &'a str,
    pub(crate) callee: Option<&'a str>,
    pub(crate) sig: Option<&'a str>,
    pub(crate) first_party: bool,
    pub(crate) args: Vec<(u64, Arg<'a>)>,
}

impl Call<'_> {
    pub(crate) fn arg(&self, ordinal: u64) -> Option<Arg<'_>> {
        self.args.iter().find(|a| a.0 == ordinal).map(|a| a.1)
    }

    /// The slots through which the caller's parameter `ordinal` flows in.
    fn slots_of(&self, ordinal: u64) -> Vec<u64> {
        let is = |a: &Arg<'_>| matches!(a, Arg::Param { ordinal: o, .. } if *o == ordinal);
        self.args.iter().filter(|a| is(&a.1)).map(|a| a.0).collect()
    }
}

/// One eligible guard; `then_is_pos` is the canonical orientation (pos =
/// truthy / non-null).
pub(crate) struct Guard {
    line: i64,
    param: u64,
    then_is_pos: bool,
}

pub(crate) struct Sidecar<'a> {
    pub(crate) calls: Vec<Call<'a>>,
    guards: Vec<Guard>,
}

/// One `functions[]` record.
pub(crate) struct Func<'a> {
    pub(crate) name: &'a str,
    pub(crate) file: &'a str,
    sig: Option<&'a str>,
    pub(crate) params: Vec<&'a str>,
    body: &'a [Value],
    /// `Err` when absent or malformed (§0.9, A11).
    pub(crate) sidecar: Result<Sidecar<'a>, Nge>,
    /// params-list index -> declared ordinal (A17).
    pub(crate) ordinals: Option<Vec<u64>>,
}

pub(crate) fn functions(ir: &OwnIr) -> Vec<Func<'_>> {
    ir.functions.iter().flatten().map(func).collect()
}

fn func(f: &Function) -> Func<'_> {
    let params: Vec<&str> = f.params.iter().flatten().map(|p| p.name.as_str()).collect();
    let sig = f.sig.as_ref().and_then(Option::as_deref);
    let body: &[Value] = f
        .extra
        .get("body")
        .and_then(Value::as_array)
        .map_or(&[], Vec::as_slice);
    // P-037-X Stage 2b R1 (research/p037-max-v1): A2.1 emits `guarded_facts` only for a
    // method with a relevant call or an eligible guard, so for a record whose body carries
    // no `if`, `while` or `call` op the emitted sidecar would have been EMPTY and its
    // absence encodes emptiness, not missing knowledge. Any structural or call op in a
    // sidecar-less body keeps the fail-closed answer: a guard or a call the sidecar did not
    // record is exactly what §0.9 refuses to guess.
    let sidecar = match f.extra.get("guarded_facts") {
        None | Some(Value::Null) if straight_line(body) => Ok(Sidecar {
            calls: Vec::new(),
            guards: Vec::new(),
        }),
        None | Some(Value::Null) => err("missing_sidecar"),
        Some(v) => sidecar(v).map_or_else(|| err("malformed_sidecar"), Ok),
    };
    Func {
        name: str_at(&f.extra, "name").unwrap_or_default(),
        file: str_at(&f.extra, "file").unwrap_or_default(),
        ordinals: ordinals_of(f, sig, params.len()),
        sig,
        params,
        body,
        sidecar,
    }
}

/// R1's test: no `if`, `while` or `call` op at any depth.
fn straight_line(body: &[Value]) -> bool {
    let mut ops = Vec::new();
    collect(body, &mut ops);
    ops.iter()
        .all(|o| !matches!(kind_of(o), "if" | "while" | "call"))
}

/// P-037-X Stage 2b R3: the declared ordinal as a FACT (`params[].ordinal`, additive; the
/// same integer the sidecar keys `args[].param` and `guards[].param` by). Used only when
/// every param of the record carries it and the sequence is strictly increasing; when A17's
/// allowlist derivation also yields a map, the two must agree — a disagreement refuses the
/// map rather than trusting either side (control X2B-C6). Without the fact, A17 as before.
fn ordinals_of(f: &Function, sig: Option<&str>, n: usize) -> Option<Vec<u64>> {
    let derived = ordinal_map(sig, n);
    let facts: Option<Vec<u64>> = f
        .params
        .iter()
        .flatten()
        .map(|p| p.extra.get("ordinal").and_then(Value::as_u64))
        .collect();
    match facts {
        Some(facts) if !facts.is_empty() => {
            let increasing = facts.windows(2).all(|w| w[0] < w[1]);
            let arity_ok = sig.map_or(true, |s| {
                let arity = s.split(',').filter(|t| !t.is_empty()).count();
                facts.iter().all(|&o| usize::try_from(o).is_ok_and(|o| o < arity))
            });
            let agrees = derived.as_ref().map_or(true, |d| *d == facts);
            (increasing && arity_ok && agrees).then_some(facts)
        }
        _ => derived,
    }
}

/// P-037-X Stage 2b R2: the coordinate identity of a record — its name, or `name(sig)` when
/// another record shares the name and this one carries a `sig` (the per-overload key the
/// bridge's MOS uses). `None` for an overload without a `sig`: no identity, no coordinate.
pub(crate) fn identity(fns: &[Func<'_>], fi: usize) -> Option<String> {
    let f = fns.get(fi)?;
    let same_name = fns.iter().filter(|g| g.name == f.name).count();
    if same_name == 1 {
        return Some(f.name.to_owned());
    }
    let sig = f.sig?;
    let same_sig = fns
        .iter()
        .filter(|g| g.name == f.name && g.sig == Some(sig))
        .count();
    (same_sig == 1).then(|| format!("{}({})", f.name, sig))
}

/// A17: `params[i]` is the i-th declared parameter whose type is not in
/// [`NON_DISPOSABLE`], only when the counts agree exactly. A missing `sig` or
/// an array type (a multi-rank one carries a comma) is no map at all.
fn ordinal_map(sig: Option<&str>, n: usize) -> Option<Vec<u64>> {
    let sig = sig.filter(|s| !s.contains('[') && !s.contains(']'))?;
    let types = sig.split(',').filter(|t| !t.is_empty());
    let unknown: Vec<u64> = (0_u64..)
        .zip(types)
        .filter(|(_, t)| !NON_DISPOSABLE.contains(t))
        .map(|(o, _)| o)
        .collect();
    (unknown.len() == n).then_some(unknown)
}

fn str_at<'a>(m: &'a Map<String, Value>, k: &str) -> Option<&'a str> {
    m.get(k).and_then(Value::as_str)
}

fn int_at(m: &Map<String, Value>, k: &str) -> Option<i64> {
    m.get(k).and_then(Value::as_i64)
}

fn sidecar(v: &Value) -> Option<Sidecar<'_>> {
    let m = v.as_object().filter(|m| int_at(m, "version") == Some(1))?;
    let mut calls = Vec::new();
    for c in m.get("calls")?.as_array()? {
        calls.push(call(c.as_object()?)?);
    }
    let mut guards = Vec::new();
    for g in m.get("guards")?.as_array()? {
        let g = g.as_object()?;
        let pos = match str_at(g, "predicate")? {
            "truth" | "not_null" => true,
            "is_null" => false,
            _ => return None,
        };
        guards.push(Guard {
            line: int_at(g.get("site")?.as_object()?, "line")?,
            param: g.get("param")?.as_u64()?,
            then_is_pos: pos != g.get("negated")?.as_bool()?,
        });
    }
    Some(Sidecar { calls, guards })
}

fn call(c: &Map<String, Value>) -> Option<Call<'_>> {
    let site = c.get("site")?.as_object()?;
    let mut args = Vec::new();
    for a in c.get("args")?.as_array()? {
        let a = a.as_object()?;
        let arg = match str_at(a, "kind")? {
            "var" => Arg::Var(str_at(a, "name")?),
            "param" => Arg::Param {
                ordinal: a.get("source_param")?.as_u64()?,
                negated: a.get("negated").and_then(Value::as_bool).unwrap_or(false),
            },
            "bool_const" => Arg::Bool(a.get("value")?.as_bool()?),
            "null_literal" => Arg::Null,
            "object_creation" => Arg::New,
            "call_result" => Arg::CallResult,
            "opaque" => Arg::Opaque,
            _ => return None,
        };
        args.push((a.get("param")?.as_u64()?, arg));
    }
    Some(Call {
        site: (int_at(site, "line")?, int_at(site, "column")?),
        statement_line: int_at(c, "statement_line")?,
        form: str_at(c, "form")?,
        callee: str_at(c, "callee"),
        sig: str_at(c, "sig"),
        first_party: c.get("first_party")?.as_bool()?,
        args,
    })
}

/// Resolve the callee coordinate `(function, params index)` behind one call
/// slot, or why there is none (A9–A11, R).
pub(crate) fn callee_coord(
    fns: &[Func<'_>],
    c: &Call<'_>,
    slot: u64,
) -> Result<(usize, usize), Nge> {
    let Some(name) = c.callee else {
        return err("callee_unresolved");
    };
    let by_name: Vec<usize> = (0..fns.len())
        .filter(|&i| fns.get(i).is_some_and(|f| f.name == name))
        .collect();
    // P-037-X Stage 2b R2: among the records of that name, the one whose `sig` equals the
    // call's `sig` (both present); a name-only fallback exists only when neither side
    // carries a `sig`. A call whose `sig` matches no record of that name is unresolved,
    // never resolved by name.
    let hits: Vec<usize> = by_name
        .iter()
        .copied()
        .filter(|&i| {
            fns.get(i).is_some_and(|f| match (c.sig, f.sig) {
                (Some(a), Some(b)) => a == b,
                (None, None) => true,
                _ => by_name.len() == 1,
            })
        })
        .collect();
    let (fi, f) = match (by_name.as_slice(), hits.as_slice()) {
        ([], _) if c.first_party => return err("callee_no_record"),
        ([], _) => return err("callee_external"),
        (_, []) => return err("callee_sig"),
        (_, [one]) => (*one, fns.get(*one).ok_or("callee_no_record")?),
        _ => return err("callee_overloaded"),
    };
    let Some(ords) = &f.ordinals else {
        return err("callee_ordinal_map");
    };
    let idx = ords
        .iter()
        .position(|&o| o == slot)
        .ok_or("callee_no_coord")?;
    Ok((fi, idx))
}

// ---------------------------------------------------------------------------
// The fail-closed join and the paths of one coordinate
// ---------------------------------------------------------------------------

/// What one normal-return path does with the parameter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Act {
    Kept,
    Release,
    /// A forward through sidecar call `n` of the function.
    Forward(usize),
}

/// One path: its side of the joined guard (`None`: never passed it) and its
/// single action.
#[derive(Debug, Clone, Copy)]
pub(crate) struct Path {
    pub(crate) pos: Option<bool>,
    pub(crate) act: Act,
    done: bool,
}

/// The local facts of one coordinate: its paths, the joined guard's ordinal,
/// and each forward's callee coordinate (or why there is none).
pub(crate) struct Local {
    pub(crate) paths: Vec<Path>,
    pub(crate) guard: Option<u8>,
    pub(crate) fwds: Vec<(usize, Result<(usize, usize), Nge>)>,
    /// P-037-X Stage 2b R4: two DISTINCT eligible guard literals govern an action on this
    /// parameter — G-S1's seed is `Conflict` (the honest join), never no evidence.
    pub(crate) conflict: bool,
}

const MAX_PATHS: usize = 64;

fn line_of(op: &Value) -> Option<i64> {
    op.get("line").and_then(Value::as_i64)
}

fn kind_of(op: &Value) -> &str {
    op.get("op").and_then(Value::as_str).unwrap_or_default()
}

fn branch<'v>(op: &'v Value, k: &str) -> &'v [Value] {
    op.get(k)
        .and_then(Value::as_array)
        .map_or(&[], Vec::as_slice)
}

fn collect<'v>(ops: &'v [Value], out: &mut Vec<&'v Value>) {
    for op in ops {
        out.push(op);
        for k in ["then", "else", "body"] {
            collect(branch(op, k), out);
        }
    }
}

/// Whether `op` names `p` in any role.
fn touches(op: &Value, p: &str) -> bool {
    let named = |k: &str| op.get(k).and_then(Value::as_str) == Some(p);
    let mut args = op
        .get("args")
        .and_then(Value::as_array)
        .into_iter()
        .flatten();
    named("var") || named("src") || named("result") || args.any(|x| x.as_str() == Some(p))
}

struct Walk<'a> {
    calls: &'a [Call<'a>],
    p: &'a str,
    ordinal: u64,
    guarded_if: Option<(&'a Value, bool)>,
    ops: Vec<&'a Value>,
}

/// The local facts of parameter `index` of function `fi`, or why there are
/// none.
pub(crate) fn local(fns: &[Func<'_>], fi: usize, index: usize) -> Result<Local, Nge> {
    let f = fns.get(fi).ok_or("malformed")?;
    // P-037-X Stage 2b R2: an overload has a coordinate iff it has an identity (its `sig`).
    if identity(fns, fi).is_none() {
        return err("overloaded");
    }
    let sc = f.sidecar.as_ref().map_err(Clone::clone)?;
    let ordinal = f
        .ordinals
        .as_ref()
        .and_then(|o| o.get(index).copied())
        .ok_or("ordinal_map")?;
    let mut ops = Vec::new();
    collect(f.body, &mut ops);
    let p = f.params.get(index).copied().ok_or("ordinal_map")?;
    // P-037-X Stage 2b R4 (G-S1, stage 1 verbatim): the election seed of `(M, i)` joins the
    // eligible guard literals lexically governing an ownership action on parameter `i`;
    // a guard governing no action on `i` contributes nothing (its `if` is walked unguarded);
    // two distinct governing literals seed `Conflict`; the same literal governing twice, or
    // two guard records on one line, stays the fail-closed `join_guard`/`multi_guard`.
    // "Governs" is G-S1's stage-1 text, no more: the literal lexically encloses an
    // ownership action on `i` (an `if`/`else` around a release or a forward), or a
    // literal-guarded early `return` precedes such an action (the two shapes #305 pinned).
    // A guard whose branches merge before the action governs nothing: it is walked
    // unguarded and contributes no literal.
    let action_on_p = |o: &Value| {
        touches(o, p)
            && (kind_of(o) == "release"
                || sc.calls.iter().any(|c| {
                    Some(c.statement_line) == line_of(o) && !c.slots_of(ordinal).is_empty()
                }))
    };
    let mut governing: Vec<(&Value, &Guard)> = Vec::new();
    for g in &sc.guards {
        let mut ifs = ops
            .iter()
            .enumerate()
            .filter(|(_, o)| kind_of(o) == "if" && line_of(o) == Some(g.line));
        let (Some((at, only)), None) = (ifs.next(), ifs.next()) else {
            return err("join_guard");
        };
        let mut inner = Vec::new();
        collect(branch(only, "then"), &mut inner);
        collect(branch(only, "else"), &mut inner);
        let encloses = inner.iter().any(|o| action_on_p(o));
        let returns = inner.iter().any(|o| kind_of(o) == "return");
        let after = ops
            .iter()
            .skip(at.saturating_add(inner.len()).saturating_add(1))
            .any(|o| action_on_p(o));
        if encloses || (returns && after) {
            governing.push((*only, g));
        }
    }
    let (guarded_if, guard, conflict) = match governing.as_slice() {
        [] => (None, None, false),
        [(only, g)] => {
            let h = u8::try_from(g.param).map_err(|_| "ordinal_range")?;
            (Some((*only, g.then_is_pos)), Some(h), false)
        }
        many => {
            let mut params: Vec<u64> = many.iter().map(|(_, g)| g.param).collect();
            params.sort_unstable();
            params.dedup();
            if params.len() < many.len() {
                return err("multi_guard");
            }
            (None, None, true)
        }
    };
    let w = Walk {
        calls: &sc.calls,
        p,
        ordinal,
        guarded_if,
        ops,
    };
    w.check_calls()?;
    let start = Path {
        pos: None,
        act: Act::Kept,
        done: false,
    };
    let paths = w.walk(f.body, vec![start])?;
    let mut fwds: Vec<(usize, Result<(usize, usize), Nge>)> = Vec::new();
    for p in &paths {
        let Act::Forward(n) = p.act else { continue };
        let Some(c) = sc.calls.get(n).filter(|_| fwds.iter().all(|x| x.0 != n)) else {
            continue;
        };
        let slot = c.slots_of(ordinal).first().copied().ok_or("malformed")?;
        fwds.push((n, callee_coord(fns, c, slot)));
    }
    Ok(Local {
        paths,
        guard,
        fwds,
        conflict,
    })
}

impl<'a> Walk<'a> {
    fn involved(&self, c: &Call<'_>) -> bool {
        !c.slots_of(self.ordinal).is_empty()
    }

    /// Every sidecar call the parameter flows into must be placeable (A15).
    fn check_calls(&self) -> Result<(), Nge> {
        for c in self.calls.iter().filter(|c| self.involved(c)) {
            let on_line = || {
                self.ops
                    .iter()
                    .filter(|o| line_of(o) == Some(c.statement_line))
            };
            if !matches!(c.form, "statement" | "initializer") {
                return err("expression_form");
            }
            if c.slots_of(self.ordinal).len() > 1 {
                return err("multi_slot");
            }
            if c.args.iter().any(|a| a.1 == Arg::Opaque) {
                return err("opaque_slot");
            }
            if on_line().any(|o| matches!(kind_of(o), "if" | "while")) {
                return err("join_structural");
            }
            match on_line().filter(|o| touches(o, self.p)).count() {
                0 => return err("no_body_op"),
                1 => {}
                _ => return err("join_ops"),
            }
        }
        Ok(())
    }

    /// The action of one op that names the parameter.
    fn action(&self, op: &Value) -> Result<Option<Act>, Nge> {
        let kind = kind_of(op);
        let rebinds = op.get("result").and_then(Value::as_str) == Some(self.p);
        if rebinds || matches!(kind, "acquire" | "alias_join" | "overspan" | "return") {
            return err("unsupported_op");
        }
        let line = line_of(op).ok_or("malformed")?;
        let at: Vec<usize> = (0..self.calls.len())
            .filter(|&n| self.calls.get(n).is_some_and(|c| c.statement_line == line))
            .collect();
        if at.is_empty() {
            return match kind {
                "release" => Ok(Some(Act::Release)),
                "use" => Ok(None),
                _ => err("unmatched_call"),
            };
        }
        let mut mine = at
            .into_iter()
            .filter(|&n| self.calls.get(n).is_some_and(|c| self.involved(c)));
        match (mine.next(), mine.next()) {
            (Some(n), None) => Ok(Some(Act::Forward(n))),
            _ => err("join_line"),
        }
    }

    fn walk(&self, ops: &'a [Value], mut paths: Vec<Path>) -> Result<Vec<Path>, Nge> {
        for op in ops {
            match kind_of(op) {
                "if" => {
                    let side = self
                        .guarded_if
                        .filter(|g| std::ptr::eq(g.0, op))
                        .map(|g| g.1);
                    let enter = |pos: Option<bool>| -> Vec<Path> {
                        let live = paths.iter().filter(|p| !p.done);
                        live.map(|p| Path {
                            pos: pos.or(p.pos),
                            ..*p
                        })
                        .collect()
                    };
                    let (then_in, else_in) = (enter(side), enter(side.map(|s| !s)));
                    paths.retain(|p| p.done);
                    paths.extend(self.walk(branch(op, "then"), then_in)?);
                    paths.extend(self.walk(branch(op, "else"), else_in)?);
                }
                "while" => {
                    let mut inner = Vec::new();
                    collect(branch(op, "body"), &mut inner);
                    if inner
                        .iter()
                        .any(|o| touches(o, self.p) || kind_of(o) == "return")
                    {
                        return err("loop");
                    }
                }
                "return" if !touches(op, self.p) => {
                    for p in &mut paths {
                        p.done = true;
                    }
                }
                _ if touches(op, self.p) => {
                    if let Some(act) = self.action(op)? {
                        for p in paths.iter_mut().filter(|p| !p.done) {
                            if p.act != Act::Kept {
                                return err("multi_action");
                            }
                            p.act = act;
                        }
                    }
                }
                _ => {}
            }
            if paths.len() > MAX_PATHS {
                return err("paths");
            }
        }
        Ok(paths)
    }
}
