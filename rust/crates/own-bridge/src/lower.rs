//! The `ownlang/ownir.py::to_module` port — `OwnIR` facts → the normalized
//! Layer 2 document, restricted to the behavior the shared fixtures exercise.
//!
//! The walk is deliberately DICT-SHAPED: the typed [`OwnIr`] document is
//! re-serialized to a JSON value once and lowered by the same key-by-key
//! logic as the Python reference (own-ir's round-trip preservation is a
//! pinned property, so the value equals the original facts). That keeps
//! every membership/default/truthiness decision textually comparable to
//! `to_module` instead of re-deriving it through a second type system.
//!
//! One deliberate divergence, guarded loud: a PRESENT-but-unknown resource
//! kind (Python's tolerant door falls back to `Subscription`) is a
//! [`BridgeError`] here — the tolerant-door contract is an open decision
//! (#294, the `tolerant_unknown_kind` fixture stays Python-only), and this
//! crate refuses to guess either way.

// The lowering mirrors `to_module` branch-for-branch; splitting it further
// (or moving each walk's helper away from its single caller) would trade
// lint scores for a port that no longer reads against the reference.
// Invariant-backed map reads use expect() (never bare indexing).
#![allow(
    clippy::too_many_lines,
    clippy::expect_used,
    clippy::items_after_statements,
    clippy::redundant_pub_crate
)]

use crate::mos::{
    self, MethodSkeleton, MethodSummary, Mos, ParamSkeleton, PathAction, ReturnSkeleton, Transfer,
};
use crate::BridgeError;
use own_ir::OwnIr;
use own_lowered::{
    Extern, ExternParam, Function, HandleEntry, Lifetime, LoweredDocument, Maybe, Param, Resource,
    ResourceMember, Stmt, TypeShape, LOWERED_VERSION,
};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

type Obj = Map<String, Value>;

// --- Python-semantics helpers ------------------------------------------------

/// Python truthiness over a JSON value (absent handled by the caller).
fn py_truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python `str(v)` over the JSON values the facts carry. Containers are not
/// reproduced (Python would repr them); no fixture nor real extractor puts a
/// container where a scalar is read.
fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        other => other.to_string(),
    }
}

/// Python `{x!r}` for the fail-loud message; only strings occur in practice.
fn py_repr(v: Option<&Value>) -> String {
    match v {
        None | Some(Value::Null) => "None".to_owned(),
        Some(Value::String(s)) => format!("'{s}'"),
        Some(Value::Bool(true)) => "True".to_owned(),
        Some(Value::Bool(false)) => "False".to_owned(),
        Some(other) => other.to_string(),
    }
}

/// `_as_int`: a non-throwing int coercion (a bool is NOT an int here — serde
/// keeps them distinct, matching Python's explicit bool check).
fn as_int(v: Option<&Value>) -> i64 {
    v.and_then(Value::as_i64).unwrap_or(0)
}

/// `n.get(key)` where a present non-list / absent key reads as empty.
fn as_list(v: Option<&Value>) -> &[Value] {
    v.and_then(Value::as_array).map_or(&[], Vec::as_slice)
}

fn get_str<'a>(obj: &'a Obj, key: &str) -> Option<&'a str> {
    obj.get(key).and_then(Value::as_str)
}

/// `str(obj.get(key, default))` — Python stringifies a PRESENT value of any
/// type; only an absent key takes the default.
fn str_or(obj: &Obj, key: &str, default: impl Into<String>) -> String {
    obj.get(key).map_or_else(|| default.into(), py_str)
}

// --- frozen vocabulary -------------------------------------------------------

const SUBSCRIBER_REGION: &str = "Subscriber";
const SINK_EXTERN_NAMES: [&str; 3] = ["$consume", "$borrow", "$borrow_mut"];

/// `_RESOURCES`: kind → the own resource type to acquire.
fn resource_type(rkind: &str) -> Option<&'static str> {
    match rkind {
        "subscription" | "subscribe" => Some("Subscription"),
        "timer" => Some("Timer"),
        "disposable" | "local-disposable" => Some("Disposable"),
        "pool" => Some("PooledBuffer"),
        _ => None,
    }
}

/// `_CAPTURE_SOURCE_REGIONS`: only provably-longer sources are mapped.
fn capture_source_region(source: &str) -> Option<&'static str> {
    (source == "static").then_some("Process")
}

/// `_DI_REGION`.
fn di_region(life: &str) -> Option<&'static str> {
    match life {
        "singleton" => Some("Process"),
        "scoped" => Some("scoped"),
        "transient" => Some("transient"),
        _ => None,
    }
}

fn prelude_resources() -> Vec<Resource> {
    let res = |name: &str, kind: &str, acq: &str, rel: &str| Resource {
        name: name.to_owned(),
        kind: Some(kind.to_owned()),
        members: vec![
            ResourceMember {
                role: "acquire".to_owned(),
                name: acq.to_owned(),
            },
            ResourceMember {
                role: "release".to_owned(),
                name: rel.to_owned(),
            },
        ],
    };
    vec![
        res("Subscription", "subscription token", "Subscribe", "Dispose"),
        res("Timer", "timer", "Start", "Stop"),
        res("Disposable", "disposable field", "New", "Dispose"),
        res("PooledBuffer", "pooled buffer", "Rent", "Return"),
    ]
}

fn sink_externs() -> Vec<Extern> {
    let ext = |name: &str, effect: &str| Extern {
        name: name.to_owned(),
        params: vec![ExternParam {
            effect: effect.to_owned(),
            type_name: "Disposable".to_owned(),
        }],
    };
    vec![
        ext("$consume", "consume"),
        ext("$borrow", "borrow"),
        ext("$borrow_mut", "borrow_mut"),
    ]
}

fn capture_lifetimes() -> Vec<Lifetime> {
    let lt = |name: &str, longer: Option<&str>| Lifetime {
        name: name.to_owned(),
        longer: longer.map(str::to_owned),
    };
    vec![
        lt("Process", None),
        lt("scoped", Some("Process")),
        lt("transient", Some("scoped")),
        lt(SUBSCRIBER_REGION, Some("Process")),
    ]
}

/// The curated Tier B BCL fresh-factory table (`_BCL_FRESH_BY_NS`), accepted
/// as the bare `Type.Method` or its exact fully-qualified identity.
const BCL_FRESH: [(&str, &[&str]); 4] = [
    (
        "System.IO",
        &[
            "File.OpenRead",
            "File.OpenText",
            "File.OpenWrite",
            "File.Open",
            "File.Create",
            "File.CreateText",
            "File.AppendText",
            "File.OpenHandle",
        ],
    ),
    (
        "System.Security.Cryptography",
        &[
            "SHA1.Create",
            "SHA256.Create",
            "SHA384.Create",
            "SHA512.Create",
            "MD5.Create",
            "Aes.Create",
            "RSA.Create",
            "ECDsa.Create",
        ],
    ),
    ("System.Xml", &["XmlReader.Create", "XmlWriter.Create"]),
    ("System.Text.Json", &["JsonDocument.Parse"]),
];

fn is_bcl_fresh_factory(callee: &str) -> bool {
    if callee.is_empty() {
        return false;
    }
    let name = canonical(callee);
    BCL_FRESH.iter().any(|(ns, entries)| {
        entries.iter().any(|e| {
            *e == name || name.strip_prefix(ns).and_then(|r| r.strip_prefix('.')) == Some(*e)
        })
    })
}

// --- callee identity / MOS resolution ----------------------------------------

/// `_canonical_callee_name`: the `global::`-stripped identity.
fn canonical(name: &str) -> &str {
    name.strip_prefix("global::").unwrap_or(name)
}

/// `_sig_key`: the per-overload summary key.
fn sig_key(name: &str, sig: &str) -> String {
    format!("{name}({sig})")
}

/// `_call_sig`: the optional canonical parameter-type list of a record/op.
fn call_sig(node: &Obj) -> Option<&str> {
    get_str(node, "sig")
}

/// `_mos_lookup`: per-overload key first (raw and canonical), then the exact
/// name, then its canonical form — the name-merged fallback.
fn mos_lookup<'m>(mos: &'m Mos, callee: &str, sig: Option<&str>) -> Option<&'m MethodSummary> {
    if callee.is_empty() {
        return None;
    }
    let identity = canonical(callee);
    if let Some(sig) = sig {
        if let Some(s) = mos.get(&sig_key(callee, sig)) {
            return Some(s);
        }
        if identity != callee {
            if let Some(s) = mos.get(&sig_key(identity, sig)) {
                return Some(s);
            }
        }
    }
    if let Some(s) = mos.get(callee) {
        return Some(s);
    }
    if identity != callee {
        return mos.get(identity);
    }
    None
}

/// `_callee_returns_fresh`: Tier A (a first-party summary) is authoritative;
/// only a summary-less, non-first-party callee falls back to the BCL table.
fn callee_returns_fresh(
    callee: &str,
    mos: &Mos,
    first_party: &HashSet<String>,
    sig: Option<&str>,
) -> bool {
    if callee.is_empty() {
        return false;
    }
    let identity = canonical(callee);
    if let Some(summ) = mos_lookup(mos, callee, sig) {
        return summ.returns == "fresh";
    }
    if first_party.contains(identity) {
        return false;
    }
    is_bcl_fresh_factory(callee)
}

// --- flow-body walks (the `_*` helpers of ownir.py) --------------------------

/// `_released_vars`.
fn released_vars(nodes: &[Value]) -> HashSet<String> {
    let mut out = HashSet::new();
    fn walk(nodes: &[Value], out: &mut HashSet<String>) {
        for n in nodes {
            let Some(n) = n.as_object() else { continue };
            match get_str(n, "op") {
                Some("release") => {
                    if let Some(v) = get_str(n, "var") {
                        out.insert(v.to_owned());
                    }
                }
                Some("if") => {
                    walk(as_list(n.get("then")), out);
                    walk(as_list(n.get("else")), out);
                }
                Some("while") => walk(as_list(n.get("body")), out),
                _ => {}
            }
        }
    }
    walk(nodes, &mut out);
    out
}

/// `_returns_value`.
fn returns_value(nodes: &[Value]) -> bool {
    nodes
        .iter()
        .filter_map(Value::as_object)
        .any(|n| match get_str(n, "op") {
            Some("return") => n.get("var").is_some_and(|v| !v.is_null()),
            Some("if") => {
                returns_value(as_list(n.get("then"))) || returns_value(as_list(n.get("else")))
            }
            Some("while") => returns_value(as_list(n.get("body"))),
            _ => false,
        })
}

/// `_collect_vars`.
fn collect_vars(nodes: &[Value], op_kind: &str, field: &str) -> HashSet<String> {
    let mut out = HashSet::new();
    fn walk(nodes: &[Value], op_kind: &str, field: &str, out: &mut HashSet<String>) {
        for n in nodes {
            let Some(n) = n.as_object() else { continue };
            match get_str(n, "op") {
                Some(op) if op == op_kind => {
                    if let Some(v) = get_str(n, field) {
                        out.insert(v.to_owned());
                    }
                }
                Some("if") => {
                    walk(as_list(n.get("then")), op_kind, field, out);
                    walk(as_list(n.get("else")), op_kind, field, out);
                }
                Some("while") => walk(as_list(n.get("body")), op_kind, field, out),
                _ => {}
            }
        }
    }
    walk(nodes, op_kind, field, &mut out);
    out
}

/// `_has_bare_return`.
fn has_bare_return(nodes: &[Value]) -> bool {
    nodes
        .iter()
        .filter_map(Value::as_object)
        .any(|n| match get_str(n, "op") {
            // MSRV 1.74: `Option::is_none_or` is not available yet.
            Some("return") => !n.get("var").is_some_and(|v| !v.is_null()),
            Some("if") => {
                has_bare_return(as_list(n.get("then"))) || has_bare_return(as_list(n.get("else")))
            }
            Some("while") => has_bare_return(as_list(n.get("body"))),
            _ => false,
        })
}

type CallOrigin = Option<(String, Option<String>)>;

/// `_call_result_callees`: result local → `(callee, sig)`; `None` = ambiguous.
fn call_result_callees(nodes: &[Value]) -> HashMap<String, CallOrigin> {
    let mut out: HashMap<String, CallOrigin> = HashMap::new();
    fn visit(nodes: &[Value], out: &mut HashMap<String, CallOrigin>) {
        for n in nodes {
            let Some(n) = n.as_object() else { continue };
            match get_str(n, "op") {
                Some("call") => {
                    let (Some(res), Some(callee)) = (get_str(n, "result"), get_str(n, "callee"))
                    else {
                        continue;
                    };
                    if callee.is_empty() {
                        continue;
                    }
                    let entry = (callee.to_owned(), call_sig(n).map(str::to_owned));
                    match out.get(res) {
                        None => {
                            out.insert(res.to_owned(), Some(entry));
                        }
                        Some(None) => {}
                        Some(Some((prev_callee, prev_sig))) => {
                            if *prev_callee != entry.0 {
                                out.insert(res.to_owned(), None);
                            } else if *prev_sig != entry.1 {
                                out.insert(res.to_owned(), Some((entry.0, None)));
                            }
                        }
                    }
                }
                Some("if") => {
                    visit(as_list(n.get("then")), out);
                    visit(as_list(n.get("else")), out);
                }
                Some("while") => visit(as_list(n.get("body")), out),
                _ => {}
            }
        }
    }
    visit(nodes, &mut out);
    out
}

/// `_param_signals`: (released, handed-to-a-call, used) on any path.
fn param_signals(pname: &str, nodes: &[Value]) -> (bool, bool, bool) {
    let (mut rel, mut passed, mut used) = (false, false, false);
    for n in nodes {
        let Some(n) = n.as_object() else { continue };
        match get_str(n, "op") {
            Some("release") if py_str(n.get("var").unwrap_or(&Value::Null)) == pname => rel = true,
            Some("call") => {
                if as_list(n.get("args")).iter().any(|a| py_str(a) == pname) {
                    passed = true;
                }
            }
            Some("use") if py_str(n.get("var").unwrap_or(&Value::Null)) == pname => used = true,
            Some("if") => {
                for sub in [as_list(n.get("then")), as_list(n.get("else"))] {
                    let (sr, sp, su) = param_signals(pname, sub);
                    rel |= sr;
                    passed |= sp;
                    used |= su;
                }
            }
            Some("while") => {
                let (sr, sp, su) = param_signals(pname, as_list(n.get("body")));
                rel |= sr;
                passed |= sp;
                used |= su;
            }
            _ => {}
        }
    }
    (rel, passed, used)
}

/// `_walk_release`: (`rel_out` 0/1/2, `falls_through`, `exits_ok`).
fn walk_release(pname: &str, nodes: &[Value], rel_in: u8) -> (u8, bool, bool) {
    let mut rel = rel_in;
    let mut exits_ok = true;
    for n in nodes {
        let Some(n) = n.as_object() else { continue };
        match get_str(n, "op") {
            Some("release") if py_str(n.get("var").unwrap_or(&Value::Null)) == pname => rel = 2,
            Some("return") => return (rel, false, exits_ok && rel == 2),
            Some("if") => {
                let (rt, lt, okt) = walk_release(pname, as_list(n.get("then")), rel);
                let (re, le, oke) = walk_release(pname, as_list(n.get("else")), rel);
                exits_ok = exits_ok && okt && oke;
                if lt && le {
                    rel = if rt == re { rt } else { 1 };
                } else if lt || le {
                    rel = if lt { rt } else { re };
                } else {
                    return (rel, false, exits_ok); // both branches returned
                }
            }
            Some("while") => {
                let (rb, lb, okb) = walk_release(pname, as_list(n.get("body")), rel);
                exits_ok = exits_ok && okb;
                if lb && rb != rel {
                    rel = 1;
                }
            }
            _ => {}
        }
    }
    (rel, true, exits_ok)
}

/// `_definite_release`: released on EVERY normal-return path.
fn definite_release(pname: &str, nodes: &[Value]) -> bool {
    let (rel, falls_through, exits_ok) = walk_release(pname, nodes, 0);
    exits_ok && (!falls_through || rel == 2)
}

/// `_forward_targets`: every `(callee, sig, arg_index)` a call hands `pname` to.
fn forward_targets(
    pname: &str,
    nodes: &[Value],
    recurse: bool,
) -> Vec<(String, Option<String>, i64)> {
    let mut out = Vec::new();
    for n in nodes {
        let Some(n) = n.as_object() else { continue };
        match get_str(n, "op") {
            Some("call") => {
                let callee = str_or(n, "callee", "");
                if callee.is_empty() {
                    continue;
                }
                for (j, a) in as_list(n.get("args")).iter().enumerate() {
                    if py_str(a) == pname {
                        out.push((
                            callee.clone(),
                            call_sig(n).map(str::to_owned),
                            i64::try_from(j).unwrap_or(i64::MAX),
                        ));
                    }
                }
            }
            Some("if") if recurse => {
                out.extend(forward_targets(pname, as_list(n.get("then")), true));
                out.extend(forward_targets(pname, as_list(n.get("else")), true));
            }
            Some("while") if recurse => {
                out.extend(forward_targets(pname, as_list(n.get("body")), true));
            }
            _ => {}
        }
    }
    out
}

/// `_contains_return`.
fn contains_return(n: &Obj) -> bool {
    match get_str(n, "op") {
        Some("return") => true,
        Some("if") => [as_list(n.get("then")), as_list(n.get("else"))]
            .into_iter()
            .any(|s| s.iter().filter_map(Value::as_object).any(contains_return)),
        Some("while") => as_list(n.get("body"))
            .iter()
            .filter_map(Value::as_object)
            .any(contains_return),
        _ => false,
    }
}

/// `_early_return_before_forward`.
fn early_return_before_forward(pname: &str, nodes: &[Value]) -> bool {
    for n in nodes {
        let Some(n) = n.as_object() else { continue };
        if get_str(n, "op") == Some("call")
            && as_list(n.get("args")).iter().any(|a| py_str(a) == pname)
        {
            return false; // reached the forward first
        }
        if contains_return(n) {
            return true;
        }
    }
    false
}

/// `_infer_return_skeleton` (P-005 D5.2, precision-first).
fn infer_return_skeleton(
    nodes: &[Value],
    param_names: &HashSet<String>,
    first_party: &HashSet<String>,
    call_key: &dyn Fn(&str, Option<&str>) -> String,
) -> ReturnSkeleton {
    let returned = collect_vars(nodes, "return", "var");
    if returned.is_empty() {
        return ReturnSkeleton::None;
    }
    if has_bare_return(nodes) {
        return ReturnSkeleton::None;
    }
    let acquired = collect_vars(nodes, "acquire", "var");
    let call_results = call_result_callees(nodes);
    if returned
        .iter()
        .all(|v| acquired.contains(v) && !param_names.contains(v) && !call_results.contains_key(v))
    {
        return ReturnSkeleton::Fresh;
    }
    if returned.len() == 1 {
        let v = returned.iter().next().expect("len == 1");
        if let Some(Some((callee, csig))) = call_results.get(v) {
            if !param_names.contains(v) && !acquired.contains(v) {
                if !first_party.contains(canonical(callee)) && is_bcl_fresh_factory(callee) {
                    return ReturnSkeleton::Fresh;
                }
                return ReturnSkeleton::Forward {
                    callee: call_key(callee, csig.as_deref()),
                };
            }
        }
    }
    ReturnSkeleton::None
}

/// `_infer_param_effect`: the bounded interprocedural contract inference.
fn infer_param_effect(
    pname: &str,
    nodes: &[Value],
    forward_transfer: Option<Transfer>,
) -> Option<&'static str> {
    let (rel, passed, used) = param_signals(pname, nodes);
    if rel {
        return definite_release(pname, nodes).then_some("consume");
    }
    if passed {
        return match forward_transfer {
            Some(Transfer::Must) => Some("consume"),
            Some(Transfer::No) => Some("borrow"),
            _ => None, // may / unknown / unresolved -> plain (precision-first)
        };
    }
    used.then_some("borrow")
}

// --- skeleton building (`_build_skeletons` + `_merge_skeletons`) -------------

/// `_merge_returns`: only a kind ALL overloads agree on survives.
fn merge_returns(rets: &[&ReturnSkeleton]) -> ReturnSkeleton {
    if rets.iter().all(|r| matches!(r, ReturnSkeleton::Fresh)) {
        return ReturnSkeleton::Fresh;
    }
    if rets.iter().all(|r| matches!(r, ReturnSkeleton::None)) {
        return ReturnSkeleton::None;
    }
    ReturnSkeleton::Unknown // mixed / forward -> fails closed
}

/// `_merge_skeletons`: collapse same-key overloads into ONE conservative
/// summary at (key, parameter-index) granularity.
fn merge_skeletons(key: &str, group: &[MethodSkeleton]) -> MethodSkeleton {
    if let [single] = group {
        let mut sk = single.clone();
        key.clone_into(&mut sk.key);
        return sk;
    }
    let mut by_index: BTreeMap<i64, Vec<PathAction>> = BTreeMap::new();
    for sk in group {
        for p in &sk.params {
            let paths = if p.paths.is_empty() {
                vec![PathAction::Borrow] // a kept index joins in as a borrow
            } else {
                p.paths.clone()
            };
            by_index.entry(p.index).or_default().extend(paths);
        }
    }
    let params = by_index
        .into_iter()
        .map(|(index, paths)| ParamSkeleton { index, paths })
        .collect();
    let rets: Vec<&ReturnSkeleton> = group.iter().map(|s| &s.ret).collect();
    MethodSkeleton {
        key: key.to_owned(),
        params,
        ret: merge_returns(&rets),
    }
}

/// `_forward_path_action`: a sink extern is a resolved transfer; anything
/// else is a forward edge (per-overload key when the sig names one).
fn forward_path_action(
    callee: &str,
    sig: Option<&str>,
    arg: i64,
    call_key: &dyn Fn(&str, Option<&str>) -> String,
) -> PathAction {
    match callee {
        "$consume" => PathAction::Dispose,
        "$borrow" => PathAction::Borrow,
        // $borrow_mut deliberately absent (no shared-vs-exclusive axis in the
        // transfer lattice) — it falls through to a forward edge -> unknown.
        _ => PathAction::Forward {
            callee: call_key(callee, sig),
            arg,
        },
    }
}

/// `_build_skeletons`: one merged skeleton per bare name plus one per emitted
/// `name(sig)` overload group.
fn build_skeletons(raw_fns: &[Value]) -> Vec<MethodSkeleton> {
    let mut counts: HashMap<String, usize> = HashMap::new();
    for f in raw_fns.iter().filter_map(Value::as_object) {
        let name = str_or(f, "name", "");
        let c = counts.entry(name).or_insert(0);
        *c = c.saturating_add(1);
    }
    let first_party: HashSet<String> = counts
        .keys()
        .filter(|k| !k.is_empty())
        .map(|k| canonical(k).to_owned())
        .collect();

    let mut sig_keys: HashSet<String> = HashSet::new();
    for f in raw_fns.iter().filter_map(Value::as_object) {
        let name = str_or(f, "name", "");
        if !name.is_empty() && counts.get(&name).copied().unwrap_or(0) > 1 {
            if let Some(fsig) = call_sig(f) {
                sig_keys.insert(sig_key(&name, fsig));
            }
        }
    }

    let call_key = |callee: &str, sig: Option<&str>| -> String {
        if let Some(sig) = sig {
            for cand in [sig_key(callee, sig), sig_key(canonical(callee), sig)] {
                if sig_keys.contains(&cand) {
                    return cand;
                }
            }
        }
        if !counts.contains_key(callee) {
            let identity = canonical(callee);
            if counts.contains_key(identity) {
                return identity.to_owned();
            }
        }
        callee.to_owned()
    };

    // insertion-ordered groups (order only affects solver internals, which
    // are order-independent; kept for a faithful walk).
    let mut by_key: Vec<(String, Vec<MethodSkeleton>)> = Vec::new();
    let mut by_sig: Vec<(String, Vec<MethodSkeleton>)> = Vec::new();
    fn push_group(groups: &mut Vec<(String, Vec<MethodSkeleton>)>, key: &str, sk: MethodSkeleton) {
        if let Some((_, g)) = groups.iter_mut().find(|(k, _)| k == key) {
            g.push(sk);
        } else {
            groups.push((key.to_owned(), vec![sk]));
        }
    }

    for f in raw_fns.iter().filter_map(Value::as_object) {
        let key = str_or(f, "name", "");
        if key.is_empty() {
            continue;
        }
        let body = as_list(f.get("body"));
        let raw_params = as_list(f.get("params"));
        let mut params: Vec<ParamSkeleton> = Vec::new();
        for (i, p) in raw_params.iter().enumerate() {
            let Some(p) = p.as_object() else { continue };
            let cname = str_or(p, "name", "?");
            let eff = p.get("effect");
            let paths: Vec<PathAction> = match eff.and_then(Value::as_str) {
                Some("consume") => vec![PathAction::Dispose], // explicit override
                Some("borrow" | "borrow_mut") => vec![PathAction::Borrow],
                Some(_) => Vec::new(), // explicit non-owning
                None => {
                    let (rel, passed, used) = param_signals(&cname, body);
                    if rel {
                        if definite_release(&cname, body) {
                            vec![PathAction::Dispose]
                        } else {
                            // partial release (TZ D1): a kept path exists, so
                            // the join is `may`, never a flattened `must`.
                            vec![PathAction::Dispose, PathAction::Borrow]
                        }
                    } else if passed {
                        let allt = forward_targets(&cname, body, true);
                        let top = forward_targets(&cname, body, false);
                        let mut paths: Vec<PathAction> = allt
                            .iter()
                            .map(|(c, s, j)| forward_path_action(c, s.as_deref(), *j, &call_key))
                            .collect();
                        if !(allt.len() == 1
                            && top.len() == 1
                            && !early_return_before_forward(&cname, body))
                        {
                            // not a single unconditional handoff: a
                            // no-transfer path exists -> `may`/`no`.
                            paths.push(PathAction::Borrow);
                        }
                        paths
                    } else if used {
                        vec![PathAction::Borrow]
                    } else {
                        Vec::new()
                    }
                }
            };
            params.push(ParamSkeleton {
                index: i64::try_from(i).unwrap_or(i64::MAX),
                paths,
            });
        }
        let pnames: HashSet<String> = raw_params
            .iter()
            .filter_map(Value::as_object)
            .map(|p| str_or(p, "name", ""))
            .collect();
        let ret = infer_return_skeleton(body, &pnames, &first_party, &call_key);
        let sk = MethodSkeleton {
            key: key.clone(),
            params,
            ret,
        };
        if counts.get(&key).copied().unwrap_or(0) > 1 {
            if let Some(fsig) = call_sig(f) {
                push_group(&mut by_sig, &sig_key(&key, fsig), sk.clone());
            }
        }
        push_group(&mut by_key, &key, sk);
    }

    let mut out: Vec<MethodSkeleton> = by_key
        .iter()
        .map(|(k, group)| merge_skeletons(k, group))
        .collect();
    out.extend(by_sig.iter().map(|(k, group)| merge_skeletons(k, group)));
    out
}

// --- the optimistic-default machinery (untrack / kill sites) ------------------

/// `_unverified_transfer_calls`, reduced to the arg-name set `to_module`
/// derives from it (the OWN051 advisory channel does not touch the lowered
/// document, so the callee/transfer/line tuple members are not carried).
fn unverified_arg_names(nodes: &[Value], mos: &Mos) -> HashSet<String> {
    let mut out = HashSet::new();
    fn walk(nodes: &[Value], mos: &Mos, out: &mut HashSet<String>) {
        for n in nodes {
            let Some(n) = n.as_object() else { continue };
            match get_str(n, "op") {
                Some("call") => {
                    let callee = str_or(n, "callee", "");
                    if let Some(summ) = mos_lookup(mos, &callee, call_sig(n)) {
                        if let Some(args) = n.get("args").and_then(Value::as_array) {
                            for (j, a) in args.iter().enumerate() {
                                let j = i64::try_from(j).unwrap_or(i64::MAX);
                                let ps = summ.params.iter().find(|q| q.index == j);
                                if ps.is_some_and(|q| {
                                    matches!(q.transfer, Transfer::May | Transfer::Unknown)
                                }) {
                                    out.insert(py_str(a));
                                }
                            }
                        }
                    }
                }
                Some("if") => {
                    walk(as_list(n.get("then")), mos, out);
                    walk(as_list(n.get("else")), mos, out);
                }
                Some("while") => walk(as_list(n.get("body")), mos, out),
                _ => {}
            }
        }
    }
    walk(nodes, mos, &mut out);
    out
}

/// `_kill_sites_for_unverified`: local name → the TOP-LEVEL call node where
/// its tracking stops (Python keys on `id(n)`; here the node's identity is
/// its address in the facts value tree, stable for the whole lowering).
fn kill_sites_for_unverified<'v>(nodes: &'v [Value], mos: &Mos) -> HashMap<String, &'v Value> {
    let mut sites: HashMap<String, &'v Value> = HashMap::new();
    let mut minted: HashSet<String> = HashSet::new();

    fn collect_mints(n: &Value, minted: &mut HashSet<String>) {
        let Some(n) = n.as_object() else { return };
        match get_str(n, "op") {
            Some("acquire" | "alias_join") => {
                if let Some(v) = get_str(n, "var") {
                    minted.insert(v.to_owned());
                }
            }
            Some("call") => {
                if let Some(r) = get_str(n, "result") {
                    if !r.is_empty() {
                        minted.insert(r.to_owned());
                    }
                }
            }
            Some("if") => {
                for key in ["then", "else"] {
                    for x in as_list(n.get(key)) {
                        collect_mints(x, minted);
                    }
                }
            }
            Some("while") => {
                for x in as_list(n.get("body")) {
                    collect_mints(x, minted);
                }
            }
            _ => {}
        }
    }

    for n_v in nodes {
        if let Some(n) = n_v.as_object() {
            if get_str(n, "op") == Some("call") {
                let callee = str_or(n, "callee", "");
                if let Some(summ) = mos_lookup(mos, &callee, call_sig(n)) {
                    if let Some(args) = n.get("args").and_then(Value::as_array) {
                        for (j, a) in args.iter().enumerate() {
                            let j = i64::try_from(j).unwrap_or(i64::MAX);
                            let ps = summ.params.iter().find(|q| q.index == j);
                            let aname = py_str(a);
                            if ps.is_some_and(|q| {
                                matches!(q.transfer, Transfer::May | Transfer::Unknown)
                            }) && minted.contains(&aname)
                                && !sites.contains_key(&aname)
                            {
                                sites.insert(aname, n_v);
                            }
                        }
                    }
                }
            }
        }
        collect_mints(n_v, &mut minted);
    }
    sites
}

// --- branch-local hoisting ----------------------------------------------------

/// `_branch_hoist_safe`: hoisting is leak-safe only if no path can exit
/// before the post-merge release on a path that did not acquire `name`.
fn branch_hoist_safe(
    nodes: &[Value],
    name: &str,
    mos: &Mos,
    first_party: &HashSet<String>,
) -> bool {
    let is_acq = |n: &Obj| -> bool {
        match get_str(n, "op") {
            Some("acquire") => str_or(n, "var", "") == name,
            Some("call") => {
                str_or(n, "result", "") == name
                    && callee_returns_fresh(&str_or(n, "callee", ""), mos, first_party, call_sig(n))
            }
            _ => false,
        }
    };
    // (safe, acquired_after); safe = false => a fabricated-leak exit exists.
    fn analyze(
        seq: &[Value],
        mut acquired: bool,
        name: &str,
        is_acq: &dyn Fn(&Obj) -> bool,
    ) -> (bool, bool) {
        for n in seq {
            let Some(n) = n.as_object() else { continue };
            if is_acq(n) {
                acquired = true;
            } else {
                match get_str(n, "op") {
                    Some("return") => {
                        if !acquired && str_or(n, "var", "") != name {
                            return (false, acquired);
                        }
                    }
                    Some("if") => {
                        let (s1, a1) = analyze(as_list(n.get("then")), acquired, name, is_acq);
                        if !s1 {
                            return (false, acquired);
                        }
                        let (s2, a2) = analyze(as_list(n.get("else")), acquired, name, is_acq);
                        if !s2 {
                            return (false, acquired);
                        }
                        acquired = acquired || (a1 && a2);
                    }
                    Some("while") => {
                        // 0-trip: no acquisition gained
                        let (s, _) = analyze(as_list(n.get("body")), acquired, name, is_acq);
                        if !s {
                            return (false, acquired);
                        }
                    }
                    _ => {}
                }
            }
        }
        (true, acquired)
    }
    analyze(nodes, false, name, &is_acq).0
}

/// `_hoisted_branch_locals`: name → (first branch-acquire line, pool kind).
fn hoisted_branch_locals(
    nodes: &[Value],
    mos: &Mos,
    first_party: &HashSet<String>,
) -> HashMap<String, (i64, bool)> {
    let mut acq_depth: HashMap<String, u32> = HashMap::new();
    let mut acq_line: HashMap<String, i64> = HashMap::new();
    let mut acq_pool: HashMap<String, bool> = HashMap::new();
    let mut ref_depth: HashMap<String, u32> = HashMap::new();
    let mut loop_acq: HashSet<String> = HashSet::new();

    struct W<'a> {
        mos: &'a Mos,
        first_party: &'a HashSet<String>,
        acq_depth: &'a mut HashMap<String, u32>,
        acq_line: &'a mut HashMap<String, i64>,
        acq_pool: &'a mut HashMap<String, bool>,
        ref_depth: &'a mut HashMap<String, u32>,
        loop_acq: &'a mut HashSet<String>,
    }

    fn walk(w: &mut W<'_>, nodes: &[Value], depth: u32, in_loop: bool) {
        for n in nodes {
            let Some(n) = n.as_object() else { continue };
            let op = get_str(n, "op");
            let line = as_int(n.get("line"));
            let acq: Option<String> = match op {
                Some("acquire") => Some(str_or(n, "var", "?")),
                Some("call") => {
                    let (callee, res) = (get_str(n, "callee"), get_str(n, "result"));
                    match (callee, res) {
                        (Some(c), Some(r)) if !c.is_empty() && !r.is_empty() => {
                            callee_returns_fresh(c, w.mos, w.first_party, call_sig(n))
                                .then(|| r.to_owned())
                        }
                        _ => None,
                    }
                }
                _ => None,
            };
            if let Some(acq) = acq {
                let d = w.acq_depth.entry(acq.clone()).or_insert(depth);
                *d = (*d).min(depth);
                w.acq_line.entry(acq.clone()).or_insert(line);
                if op == Some("acquire") && n.get("kind").and_then(Value::as_str) == Some("pool") {
                    w.acq_pool.insert(acq.clone(), true);
                }
                if in_loop {
                    w.loop_acq.insert(acq);
                }
            }
            match op {
                Some("use" | "release" | "overspan" | "return") => {
                    if let Some(v) = get_str(n, "var") {
                        let d = w.ref_depth.entry(v.to_owned()).or_insert(depth);
                        *d = (*d).min(depth);
                    }
                }
                Some("call") => {
                    for a in as_list(n.get("args")) {
                        let name = py_str(a);
                        let d = w.ref_depth.entry(name).or_insert(depth);
                        *d = (*d).min(depth);
                    }
                }
                _ => {}
            }
            match op {
                Some("if") => {
                    walk(w, as_list(n.get("then")), depth.saturating_add(1), in_loop);
                    walk(w, as_list(n.get("else")), depth.saturating_add(1), in_loop);
                }
                Some("while") => walk(w, as_list(n.get("body")), depth.saturating_add(1), true),
                _ => {}
            }
        }
    }

    let mut w = W {
        mos,
        first_party,
        acq_depth: &mut acq_depth,
        acq_line: &mut acq_line,
        acq_pool: &mut acq_pool,
        ref_depth: &mut ref_depth,
        loop_acq: &mut loop_acq,
    };
    walk(&mut w, nodes, 0, false);

    acq_depth
        .iter()
        .filter(|(name, d)| {
            **d >= 1
                && ref_depth.get(*name).copied() == Some(0)
                && !loop_acq.contains(*name)
                && branch_hoist_safe(nodes, name, mos, first_party)
        })
        .map(|(name, _)| {
            (
                name.clone(),
                (
                    acq_line.get(name).copied().unwrap_or(0),
                    acq_pool.get(name).copied().unwrap_or(false),
                ),
            )
        })
        .collect()
}

// --- handle-entry construction -----------------------------------------------

fn unrepresentable(key: &str, v: &Value) -> BridgeError {
    BridgeError(format!(
        "handle metadata key '{key}' carries a value the typed Layer 2 \
         surface cannot represent ({v}) — extend the contract deliberately \
         instead of coercing"
    ))
}

fn want_str(rec: &Obj, key: &str) -> Result<Option<String>, BridgeError> {
    match rec.get(key) {
        None => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.clone())),
        Some(other) => Err(unrepresentable(key, other)),
    }
}

fn want_i64(rec: &Obj, key: &str) -> Result<Option<i64>, BridgeError> {
    rec.get(key).map_or(Ok(None), |v| {
        v.as_i64().map(Some).ok_or_else(|| unrepresentable(key, v))
    })
}

fn want_bool(rec: &Obj, key: &str) -> Result<Option<bool>, BridgeError> {
    match rec.get(key) {
        None => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        Some(other) => Err(unrepresentable(key, other)),
    }
}

fn want_maybe(rec: &Obj, key: &str) -> Result<Maybe<String>, BridgeError> {
    match rec.get(key) {
        None => Ok(Maybe::Missing),
        Some(Value::Null) => Ok(Maybe::Null),
        Some(Value::String(s)) => Ok(Maybe::Value(s.clone())),
        Some(other) => Err(unrepresentable(key, other)),
    }
}

/// A subscription-fact handle record: `{**sub, component, file[, di_source_life]}`
/// projected through the `_HANDLE_KEYS` allowlist by key MEMBERSHIP.
fn subscription_entry(
    handle: &str,
    sub: &Obj,
    cname: &str,
    comp_file: Option<&Value>,
    di_source_life: Option<&str>,
) -> Result<HandleEntry, BridgeError> {
    let mut rec = sub.clone();
    rec.insert("component".to_owned(), Value::String(cname.to_owned()));
    rec.insert(
        "file".to_owned(),
        comp_file
            .cloned()
            .unwrap_or_else(|| Value::String("?".to_owned())),
    );
    if let Some(dl) = di_source_life {
        rec.insert("di_source_life".to_owned(), Value::String(dl.to_owned()));
    }
    Ok(HandleEntry {
        handle: handle.to_owned(),
        component: want_str(&rec, "component")?,
        file: want_str(&rec, "file")?,
        line: want_i64(&rec, "line")?,
        event: want_str(&rec, "event")?,
        handler: want_str(&rec, "handler")?,
        resource: want_str(&rec, "resource")?,
        released: want_bool(&rec, "released")?,
        source: want_maybe(&rec, "source")?,
        source_type: want_maybe(&rec, "source_type")?,
        di_source_life: want_str(&rec, "di_source_life")?,
        type_name: want_maybe(&rec, "type")?,
        ever_released: want_bool(&rec, "ever_released")?,
        pool: want_bool(&rec, "pool")?,
    })
}

/// A flow-local handle record (`parg_*` carries no `pool` key; `loc_*` does).
fn flow_local_entry(
    handle: &str,
    file: &str,
    line: i64,
    event: &str,
    component: &str,
    ever_released: bool,
    pool: Option<bool>,
) -> HandleEntry {
    HandleEntry {
        handle: handle.to_owned(),
        component: Some(component.to_owned()),
        file: Some(file.to_owned()),
        line: Some(line),
        event: Some(event.to_owned()),
        handler: None,
        resource: Some("flow-local".to_owned()),
        released: None,
        source: Maybe::Missing,
        source_type: Maybe::Missing,
        di_source_life: None,
        type_name: Maybe::Missing,
        ever_released: Some(ever_released),
        pool,
    }
}

// --- DI registrations ---------------------------------------------------------

/// `_di_life_map`: DI-registered service name → its lifetime.
fn di_life_map(root: &Obj) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for s in as_list(root.get("services"))
        .iter()
        .filter_map(Value::as_object)
    {
        if let (Some(name), Some(lt)) = (get_str(s, "name"), get_str(s, "lifetime")) {
            if di_region(lt).is_some() {
                out.insert(name.to_owned(), lt.to_owned());
            }
        }
    }
    out
}

/// `_subscriber_region`.
fn subscriber_region(cname: &str, di_life: &HashMap<String, String>) -> String {
    di_life
        .get(cname)
        .and_then(|lt| di_region(lt))
        .unwrap_or(SUBSCRIBER_REGION)
        .to_owned()
}

// --- function-parameter lowering ----------------------------------------------

/// `_lower_fn_params`.
#[allow(clippy::too_many_arguments)] // mirrors the reference signature
fn lower_fn_params(
    f: &Obj,
    ffile: &str,
    fname: &str,
    handles: &mut Vec<HandleEntry>,
    loc: &mut i64,
    localmap: &mut HashMap<String, String>,
    released: &HashSet<String>,
    mos: &Mos,
) -> Vec<Param> {
    let mut out = Vec::new();
    let Some(raw) = f.get("params").and_then(Value::as_array) else {
        return out;
    };
    let summ = mos_lookup(mos, fname, call_sig(f));
    for (i, p) in raw.iter().enumerate() {
        let Some(p) = p.as_object() else { continue };
        let cname = str_or(p, "name", "?");
        let eff: Option<&str> = p.get("effect").and_then(Value::as_str).or_else(|| {
            let ftrans = summ.and_then(|s| {
                s.params
                    .iter()
                    .find(|q| q.index == i64::try_from(i).unwrap_or(i64::MAX))
                    .map(|q| q.transfer)
            });
            infer_param_effect(&cname, as_list(f.get("body")), ftrans)
        });
        let tref = match eff {
            Some("consume") => TypeShape {
                name: "Disposable".to_owned(),
                borrowed: false,
                mutable: false,
            },
            Some("borrow") => TypeShape {
                name: "Disposable".to_owned(),
                borrowed: true,
                mutable: false,
            },
            Some("borrow_mut") => TypeShape {
                name: "Disposable".to_owned(),
                borrowed: true,
                mutable: true,
            },
            _ => TypeShape {
                name: "int".to_owned(), // a plain (non-owned) parameter
                borrowed: false,
                mutable: false,
            },
        };
        let sym = format!("parg_{loc}");
        *loc = loc.saturating_add(1);
        let line = as_int(p.get("line"));
        localmap.insert(cname.clone(), sym.clone());
        handles.push(flow_local_entry(
            &sym,
            ffile,
            line,
            &cname,
            fname,
            released.contains(&cname),
            None,
        ));
        out.push(Param {
            handle: sym,
            type_shape: tref,
            line,
            lifetime: None,
        });
    }
    out
}

// --- flow lowering (`_lower_flow`) --------------------------------------------

struct FnCtx<'v, 'a> {
    ffile: &'a str,
    fname: &'a str,
    handles: &'a mut Vec<HandleEntry>,
    loc: &'a mut i64,
    localmap: &'a mut HashMap<String, String>,
    released: &'a HashSet<String>,
    mos: &'a Mos,
    hoisted: &'a BTreeSet<String>,
    first_party: &'a HashSet<String>,
    overloaded: &'a HashSet<String>,
    untracked: &'a HashSet<String>,
    kill_sites: &'a HashMap<String, &'v Value>,
}

fn lower_flow<'v>(ctx: &mut FnCtx<'v, '_>, nodes: &'v [Value]) -> Result<Vec<Stmt>, BridgeError> {
    let mut body: Vec<Stmt> = Vec::new();
    for n_v in nodes {
        let Some(n) = n_v.as_object() else { continue };
        let op = get_str(n, "op");
        let line = as_int(n.get("line"));
        match op {
            Some("acquire") => {
                let name = str_or(n, "var", "?");
                if ctx.hoisted.contains(&name) || ctx.untracked.contains(&name) {
                    continue;
                }
                let handle = format!("loc_{}", ctx.loc);
                *ctx.loc = ctx.loc.saturating_add(1);
                ctx.localmap.insert(name.clone(), handle.clone());
                ctx.handles.push(flow_local_entry(
                    &handle,
                    ctx.ffile,
                    line,
                    &name,
                    ctx.fname,
                    ctx.released.contains(&name),
                    Some(n.get("kind").and_then(Value::as_str) == Some("pool")),
                ));
                body.push(Stmt::Acquire {
                    handle,
                    resource: "Disposable".to_owned(),
                    line,
                });
            }
            Some("alias_join") => {
                let name = str_or(n, "var", "?");
                let src_h = ctx.localmap.get(&str_or(n, "src", "")).cloned();
                // the OLD binding dies FIRST, even when the new alias makes
                // no claim (an unreleased original leaks, never silently
                // discharges through the dead handle).
                if !ctx.hoisted.contains(&name) {
                    ctx.localmap.remove(&name);
                }
                if let Some(src_h) = src_h {
                    if !ctx.hoisted.contains(&name) && !ctx.untracked.contains(&name) {
                        let handle = format!("loc_{}", ctx.loc);
                        *ctx.loc = ctx.loc.saturating_add(1);
                        ctx.localmap.insert(name.clone(), handle.clone());
                        ctx.handles.push(flow_local_entry(
                            &handle,
                            ctx.ffile,
                            line,
                            &name,
                            ctx.fname,
                            ctx.released.contains(&name),
                            Some(false),
                        ));
                        body.push(Stmt::AliasJoin {
                            handle,
                            src: src_h,
                            line,
                        });
                    }
                }
            }
            Some("use") => {
                let key = py_str(n.get("var").unwrap_or(&Value::Null));
                if let Some(h) = ctx.localmap.get(&key) {
                    body.push(Stmt::Use {
                        handle: h.clone(),
                        line,
                    });
                }
            }
            Some("overspan") => {
                let key = py_str(n.get("var").unwrap_or(&Value::Null));
                if let Some(h) = ctx.localmap.get(&key) {
                    body.push(Stmt::Overspan {
                        handle: h.clone(),
                        line,
                    });
                }
            }
            Some("release") => {
                let key = py_str(n.get("var").unwrap_or(&Value::Null));
                if let Some(h) = ctx.localmap.get(&key) {
                    body.push(Stmt::Release {
                        handle: h.clone(),
                        line,
                    });
                }
            }
            Some("return") => {
                let h = n
                    .get("var")
                    .filter(|v| !v.is_null())
                    .and_then(|v| ctx.localmap.get(&py_str(v)))
                    .cloned();
                body.push(Stmt::Return { handle: h, line });
            }
            Some("if") => {
                let then_b = lower_flow(ctx, as_list(n.get("then")))?;
                let else_b = lower_flow(ctx, as_list(n.get("else")))?;
                body.push(Stmt::If {
                    cond: "?".to_owned(),
                    then: then_b,
                    r#else: else_b,
                    line,
                });
            }
            Some("while") => {
                let body_b = lower_flow(ctx, as_list(n.get("body")))?;
                body.push(Stmt::While {
                    cond: "?".to_owned(),
                    body: body_b,
                    line,
                });
            }
            Some("call") => {
                let callee = str_or(n, "callee", "");
                let identity = canonical(&callee);
                let args = n.get("args").and_then(Value::as_array);
                let mos = ctx.mos;
                // the direct-`Call` gate stays on the RAW name so it never
                // names a callee absent from the core signature table.
                let summ_raw = if callee.is_empty() {
                    None
                } else {
                    mos.get(&callee)
                };
                // stage-2 resolution for the channel: per-overload sig key
                // first, then the name-merged fallback.
                let resolved = mos_lookup(mos, &callee, call_sig(n));
                let channel_case = resolved.is_some_and(|r| {
                    args.is_some()
                        && (ctx.overloaded.contains(identity)
                            || r.params
                                .iter()
                                .any(|q| matches!(q.transfer, Transfer::May | Transfer::Unknown)))
                });
                if channel_case {
                    let resolved = resolved.expect("channel_case implies resolved");
                    for (j, a) in args.expect("channel_case implies args").iter().enumerate() {
                        let j = i64::try_from(j).unwrap_or(i64::MAX);
                        let channel = resolved.params.iter().find(|q| q.index == j).and_then(|q| {
                            match q.transfer {
                                Transfer::Must => Some("$consume"),
                                Transfer::No => Some("$borrow"),
                                Transfer::May | Transfer::Unknown => None,
                            }
                        });
                        if let Some(channel) = channel {
                            let aname = py_str(a);
                            if !ctx.untracked.contains(&aname) {
                                let arg = ctx.localmap.get(&aname).cloned().unwrap_or(aname);
                                body.push(Stmt::Call {
                                    callee: channel.to_owned(),
                                    args: vec![arg],
                                    line,
                                });
                            }
                        }
                    }
                } else if (summ_raw.is_some() || SINK_EXTERN_NAMES.contains(&callee.as_str()))
                    && !callee.is_empty()
                {
                    if let Some(args) = args {
                        let arg_refs = args
                            .iter()
                            .map(|a| {
                                let s = py_str(a);
                                ctx.localmap.get(&s).cloned().unwrap_or(s)
                            })
                            .collect();
                        body.push(Stmt::Call {
                            callee: callee.clone(),
                            args: arg_refs,
                            line,
                        });
                    }
                }
                // the kill site of a tracked local: discharge here, unmap after.
                if !ctx.kill_sites.is_empty() {
                    if let Some(args) = args {
                        for a in args {
                            let aname = py_str(a);
                            if ctx
                                .kill_sites
                                .get(&aname)
                                .is_some_and(|site| std::ptr::eq(*site, n_v))
                            {
                                if let Some(killed) = ctx.localmap.remove(&aname) {
                                    body.push(Stmt::Call {
                                        callee: "$consume".to_owned(),
                                        args: vec![killed],
                                        line,
                                    });
                                }
                            }
                        }
                    }
                }
                // result rebind kills the old binding; a fresh-returning
                // callee then mints a new obligation for the result.
                let result = get_str(n, "result").filter(|r| !r.is_empty());
                if let Some(result) = result {
                    if !ctx.hoisted.contains(result) {
                        ctx.localmap.remove(result);
                        if !ctx.untracked.contains(result)
                            && callee_returns_fresh(&callee, mos, ctx.first_party, call_sig(n))
                        {
                            let handle = format!("loc_{}", ctx.loc);
                            *ctx.loc = ctx.loc.saturating_add(1);
                            ctx.localmap.insert(result.to_owned(), handle.clone());
                            ctx.handles.push(flow_local_entry(
                                &handle,
                                ctx.ffile,
                                line,
                                result,
                                ctx.fname,
                                ctx.released.contains(result),
                                Some(false),
                            ));
                            body.push(Stmt::Acquire {
                                handle,
                                resource: "Disposable".to_owned(),
                                line,
                            });
                        }
                    }
                }
            }
            _ => {
                return Err(BridgeError(format!(
                    "unknown OwnIR flow op {} ({}:{line}) — extractor/core \
                     vocabulary skew; a new op must bump OWNIR_VERSION (see \
                     spec/OwnIR.md)",
                    py_repr(n.get("op")),
                    ctx.ffile,
                )))
            }
        }
    }
    Ok(body)
}

// --- the entry point ----------------------------------------------------------

pub(crate) fn lower(facts: &OwnIr) -> Result<LoweredDocument, BridgeError> {
    let root_value = facts.to_value().map_err(|e| BridgeError(e.to_string()))?;
    let root = root_value
        .as_object()
        .expect("a struct serializes to an object");

    let mut handles: Vec<HandleEntry> = Vec::new();
    let mut functions: Vec<Function> = Vec::new();
    let mut gid: i64 = 0;
    let mut any_capture = false;
    let di_life = di_life_map(root);

    // --- components: the subscription/capture lowering -----------------------
    let components: &[Value] = match root.get("components") {
        None => &[],
        Some(Value::Array(a)) => a.as_slice(),
        Some(_) => {
            return Err(BridgeError(
                "OwnIR 'components' must be a JSON array".to_owned(),
            ))
        }
    };
    for comp_v in components {
        let Some(comp) = comp_v.as_object() else {
            return Err(BridgeError(
                "each OwnIR component must be a JSON object".to_owned(),
            ));
        };
        let cname = comp
            .get("name")
            .map_or_else(|| format!("Component{gid}"), py_str);
        let mut body: Vec<Stmt> = Vec::new();
        let mut params: Vec<Param> = Vec::new();
        let mut fn_lt: Option<String> = None; // the subscriber region, iff a capture
        let self_region = subscriber_region(&cname, &di_life);
        let subscriptions: &[Value] = match comp.get("subscriptions") {
            None => &[],
            Some(Value::Array(a)) => a.as_slice(),
            Some(_) => {
                return Err(BridgeError(
                    "component 'subscriptions' must be a JSON array".to_owned(),
                ))
            }
        };
        for sub_v in subscriptions {
            let Some(sub) = sub_v.as_object() else {
                return Err(BridgeError(
                    "each subscription must be a JSON object".to_owned(),
                ));
            };
            let rkind = get_str(sub, "resource").unwrap_or("subscription");
            // R1: an unresolved-subscription marker is never lowered.
            if rkind == "unresolved-subscription" {
                continue;
            }
            // R2: a self-rooted subscribe is a GC-collectible self-cycle.
            if rkind == "subscribe" && get_str(sub, "source") == Some("self") {
                continue;
            }
            // R3: a `capture` routes through the lifetime/region engine.
            if rkind == "capture" {
                let region = get_str(sub, "source").and_then(capture_source_region);
                let Some(region) = region else { continue };
                if py_truthy(sub.get("released")) {
                    continue; // mitigated — torn down on close
                }
                let handle = format!("cap_{gid}");
                gid = gid.saturating_add(1);
                handles.push(subscription_entry(
                    &handle,
                    sub,
                    &cname,
                    comp.get("file"),
                    None,
                )?);
                let line = as_int(sub.get("line"));
                params.push(Param {
                    handle: handle.clone(),
                    type_shape: TypeShape {
                        name: "EventSource".to_owned(),
                        borrowed: false,
                        mutable: false,
                    },
                    line: 0,
                    lifetime: Some(region.to_owned()),
                });
                body.push(Stmt::Subscribe {
                    source: handle,
                    line,
                });
                fn_lt = Some(self_region.clone());
                any_capture = true;
                continue;
            }
            // R4: instance-level provenance beats the type-level DI hop.
            if rkind == "subscription"
                && get_str(sub, "source") == Some("injected")
                && get_str(sub, "source_provenance") == Some("returned_fresh")
            {
                continue;
            }
            // R5: an injected subscription whose source TYPE has a KNOWN DI
            // lifetime reroutes through the region engine.
            if rkind == "subscription"
                && get_str(sub, "source") == Some("injected")
                && !py_truthy(sub.get("released"))
            {
                let src_life = get_str(sub, "source_type").and_then(|st| di_life.get(st));
                if let Some(src_life) = src_life {
                    let src_life = src_life.clone();
                    let handle = format!("cap_{gid}");
                    gid = gid.saturating_add(1);
                    handles.push(subscription_entry(
                        &handle,
                        sub,
                        &cname,
                        comp.get("file"),
                        Some(&src_life),
                    )?);
                    let line = as_int(sub.get("line"));
                    params.push(Param {
                        handle: handle.clone(),
                        type_shape: TypeShape {
                            name: "EventSource".to_owned(),
                            borrowed: false,
                            mutable: false,
                        },
                        line: 0,
                        lifetime: di_region(&src_life).map(str::to_owned),
                    });
                    body.push(Stmt::Subscribe {
                        source: handle,
                        line,
                    });
                    fn_lt = Some(self_region.clone());
                    any_capture = true;
                    continue;
                }
            }
            // R6: the acquire/release token path.
            let handle = format!("sub_{gid}");
            gid = gid.saturating_add(1);
            handles.push(subscription_entry(
                &handle,
                sub,
                &cname,
                comp.get("file"),
                None,
            )?);
            let Some(rtype) = resource_type(rkind) else {
                // Python's tolerant door falls back to Subscription here; that
                // contract is an open decision (#294) this crate refuses to
                // pre-empt in either direction — fail loud instead.
                return Err(BridgeError(format!(
                    "unknown resource kind '{rkind}' — the tolerant-door \
                     fallback is an open decision (#294); the Rust bridge \
                     refuses to guess"
                )));
            };
            let line = as_int(sub.get("line"));
            body.push(Stmt::Acquire {
                handle: handle.clone(),
                resource: rtype.to_owned(),
                line,
            });
            if py_truthy(sub.get("released")) {
                body.push(Stmt::Release { handle, line });
            }
        }
        functions.push(Function {
            name: cname,
            lifetime: fn_lt,
            params,
            ret: None,
            body,
        });
    }

    // --- functions: the per-method flow lowering (P-016 B0b/B2) ---------------
    let mut loc: i64 = 0;
    let raw_fns: &[Value] = match root.get("functions") {
        Some(Value::Array(a)) => a.as_slice(),
        _ => &[], // Python: a non-list `functions` skips the whole section
    };
    // D5.1: resolve interprocedural transfer once, up front; degradation to
    // an empty MOS mirrors Python's exception guard (not reachable from the
    // production skeleton builder, which never emits duplicate keys).
    let mos_map: Mos = mos::solve(build_skeletons(raw_fns)).unwrap_or_default();
    let fp_names: Vec<String> = raw_fns
        .iter()
        .filter_map(Value::as_object)
        .filter(|f| py_truthy(f.get("name")))
        .map(|f| str_or(f, "name", ""))
        .collect();
    let first_party: HashSet<String> = fp_names.iter().map(|n| canonical(n).to_owned()).collect();
    let overloaded: HashSet<String> = {
        let mut counts: HashMap<&str, usize> = HashMap::new();
        for n in &fp_names {
            let c = counts.entry(canonical(n)).or_insert(0);
            *c = c.saturating_add(1);
        }
        counts
            .into_iter()
            .filter(|(_, c)| *c > 1)
            .map(|(n, _)| n.to_owned())
            .collect()
    };
    for fn_v in raw_fns {
        let Some(f) = fn_v.as_object() else { continue };
        let fname = f.get("name").map_or_else(|| format!("Fn{loc}"), py_str);
        let ffile = str_or(f, "file", "?");
        let nodes: &[Value] = as_list(f.get("body"));
        let released = released_vars(nodes);
        let mut localmap: HashMap<String, String> = HashMap::new();
        let fparams = lower_fn_params(
            f,
            &ffile,
            &fname,
            &mut handles,
            &mut loc,
            &mut localmap,
            &released,
            &mos_map,
        );
        // the optimistic default (d5 §5): a may/unknown-contract handoff
        // discharges at a TOP-LEVEL call (kill site) or untracks whole-body.
        let unverified = unverified_arg_names(nodes, &mos_map);
        let kill_sites = kill_sites_for_unverified(nodes, &mos_map);
        let untracked: HashSet<String> = unverified
            .into_iter()
            .filter(|a| !kill_sites.contains_key(a))
            .collect();
        // cross-branch locals declared once at the outer scope; an untracked
        // local must NOT be hoisted (it would re-mint the removed obligation).
        let hoist: BTreeMap<String, (i64, bool)> =
            hoisted_branch_locals(nodes, &mos_map, &first_party)
                .into_iter()
                .filter(|(k, _)| !untracked.contains(k))
                .collect();
        let hoisted_set: BTreeSet<String> = hoist.keys().cloned().collect();
        let mut fbody: Vec<Stmt> = Vec::new();
        for (hname, (hline, hpool)) in &hoist {
            let hh = format!("loc_{loc}");
            loc = loc.saturating_add(1);
            localmap.insert(hname.clone(), hh.clone());
            handles.push(flow_local_entry(
                &hh,
                &ffile,
                *hline,
                hname,
                &fname,
                released.contains(hname),
                Some(*hpool),
            ));
            fbody.push(Stmt::Acquire {
                handle: hh,
                resource: "Disposable".to_owned(),
                line: *hline,
            });
        }
        let mut ctx = FnCtx {
            ffile: &ffile,
            fname: &fname,
            handles: &mut handles,
            loc: &mut loc,
            localmap: &mut localmap,
            released: &released,
            mos: &mos_map,
            hoisted: &hoisted_set,
            first_party: &first_party,
            overloaded: &overloaded,
            untracked: &untracked,
            kill_sites: &kill_sites,
        };
        fbody.extend(lower_flow(&mut ctx, nodes)?);
        // a value-returning body gets an owned return type so `return s`
        // models a valid escape (discharge), not a void-return mismatch.
        let fret = returns_value(nodes).then(|| TypeShape {
            name: "Disposable".to_owned(),
            borrowed: false,
            mutable: false,
        });
        functions.push(Function {
            name: fname,
            lifetime: None,
            params: fparams,
            ret: fret,
            body: fbody,
        });
    }

    let module = root
        .get("module")
        .map_or_else(|| "Extracted".to_owned(), py_str);
    Ok(LoweredDocument {
        lowered_version: LOWERED_VERSION,
        module,
        resources: prelude_resources(),
        externs: sink_externs(),
        lifetimes: if any_capture {
            capture_lifetimes()
        } else {
            Vec::new()
        },
        functions,
        handles,
    })
}
