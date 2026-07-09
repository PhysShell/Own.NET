//! The canonical CFG-JSON seam — an exact port of `ownlang/cfg_json.py`.
//!
//! [`canonical_json`] produces the byte-for-byte string
//! `python -m ownlang cfg --format json` emits, so the differential oracle can
//! diff the two directly. Two things must line up with Python for that to hold:
//!
//! * **the projection**: block order, the first-appearance symbol table
//!   (params first, then instruction operands in the exact sub-order
//!   `_instr_json` visits them), the field vocabulary, and null handling;
//! * **the textual form**: [`python_dumps`] reproduces
//!   `json.dumps(obj, indent=2, sort_keys=True)` — 2-space indent, sorted keys,
//!   and crucially `ensure_ascii=True` (non-ASCII escaped as `\uXXXX`), which
//!   `serde_json`'s own pretty-printer does not do.

use std::collections::HashMap;
use std::fmt::Write as _;

use own_syntax::ast::Effect;
use serde_json::{Map, Value};

use crate::buffers::BufferInfo;
use crate::ir::{Cfg, Instr, SymId, Symbol};

/// Version gate for the seam, independent of `OwnIR`'s. Bump on any incompatible
/// vocabulary change, never for additive optional fields. Mirrors
/// `cfg_json.CFG_JSON_VERSION`.
pub const CFG_JSON_VERSION: i64 = 0;

fn opt_str(s: Option<&str>) -> Value {
    s.map_or(Value::Null, |v| Value::String(v.to_owned()))
}

fn opt_bool(b: Option<bool>) -> Value {
    b.map_or(Value::Null, Value::Bool)
}

fn opt_i64(n: Option<i64>) -> Value {
    n.map_or(Value::Null, Value::from)
}

const fn effect_name(e: Effect) -> &'static str {
    match e {
        Effect::Borrow => "borrow",
        Effect::BorrowMut => "borrow_mut",
        Effect::Consume => "consume",
        Effect::Plain => "plain",
    }
}

fn buffer_value(info: Option<&BufferInfo>) -> Value {
    let Some(info) = info else {
        return Value::Null;
    };
    let mut m = Map::new();
    m.insert("mode".into(), Value::String(info.mode.value().to_owned()));
    m.insert("elem".into(), Value::String(info.elem.clone()));
    m.insert("size_const".into(), opt_i64(info.size_const));
    m.insert("size_var".into(), opt_str(info.size_var.as_deref()));
    m.insert("inline_bytes".into(), Value::from(info.inline_bytes));
    m.insert("fallback_pool".into(), Value::Bool(info.fallback_pool));
    m.insert(
        "fallback_forbidden".into(),
        Value::Bool(info.fallback_forbidden),
    );
    m.insert(
        "clear_on_release".into(),
        Value::Bool(info.clear_on_release),
    );
    m.insert("sensitive".into(), Value::Bool(info.sensitive));
    m.insert("trace".into(), Value::Bool(info.trace));
    m.insert("counters".into(), Value::Bool(info.counters));
    m.insert("policy_name".into(), opt_str(info.policy_name.as_deref()));
    m.insert("line".into(), Value::from(info.line));
    Value::Object(m)
}

/// Symbol -> stable table index in first-appearance order, mirroring
/// `cfg_json._SymTable`. Identity is the arena [`SymId`] (the same identity the
/// analysis keys on), so aliasing structure survives the projection.
struct SymTable<'a> {
    cfg: &'a Cfg,
    index: HashMap<u32, usize>,
    rows: Vec<Value>,
}

impl<'a> SymTable<'a> {
    fn new(cfg: &'a Cfg) -> Self {
        Self {
            cfg,
            index: HashMap::new(),
            rows: Vec::new(),
        }
    }

    fn ref_sym(&mut self, sym: Option<SymId>) -> Value {
        let Some(id) = sym else {
            return Value::Null;
        };
        if let Some(&idx) = self.index.get(&id.0) {
            return Value::from(u64::try_from(idx).unwrap_or(u64::MAX));
        }
        let idx = self.rows.len();
        self.index.insert(id.0, idx);
        let row = symbol_row(self.cfg.symbol(id));
        self.rows.push(row);
        Value::from(u64::try_from(idx).unwrap_or(u64::MAX))
    }
}

fn symbol_row(s: &Symbol) -> Value {
    let mut m = Map::new();
    m.insert("name".into(), Value::String(s.name.clone()));
    m.insert("kind".into(), Value::String(s.kind.py_name().to_owned()));
    m.insert("def_line".into(), Value::from(s.def_line));
    m.insert("is_param_borrow".into(), Value::Bool(s.is_param_borrow));
    m.insert("borrow_is_mut".into(), opt_bool(s.borrow_is_mut));
    m.insert("type_name".into(), opt_str(s.type_name.as_deref()));
    m.insert("resource_kind".into(), opt_str(s.resource_kind.as_deref()));
    m.insert("origin".into(), opt_str(s.origin.as_deref()));
    m.insert("buffer".into(), buffer_value(s.buffer.as_ref()));
    Value::Object(m)
}

fn instr_value(ins: &Instr, syms: &mut SymTable<'_>) -> Value {
    let mut m = Map::new();
    match ins {
        Instr::Acquire {
            sym,
            resource,
            line,
        } => {
            m.insert("op".into(), Value::String("acquire".into()));
            m.insert("sym".into(), syms.ref_sym(Some(*sym)));
            m.insert("resource".into(), Value::String(resource.clone()));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::AcquireBuffer { sym, info, line } => {
            m.insert("op".into(), Value::String("acquire_buffer".into()));
            m.insert("sym".into(), syms.ref_sym(Some(*sym)));
            m.insert("buffer".into(), buffer_value(Some(info)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::MoveInto { dst, src, line } => {
            m.insert("op".into(), Value::String("move_into".into()));
            m.insert("dst".into(), syms.ref_sym(Some(*dst)));
            m.insert("src".into(), syms.ref_sym(Some(*src)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::Release { sym, line } => {
            m.insert("op".into(), Value::String("release".into()));
            m.insert("sym".into(), syms.ref_sym(Some(*sym)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::Use { sym, line } => {
            m.insert("op".into(), Value::String("use".into()));
            m.insert("sym".into(), syms.ref_sym(Some(*sym)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::Overspan { sym, line } => {
            m.insert("op".into(), Value::String("overspan".into()));
            m.insert("sym".into(), syms.ref_sym(Some(*sym)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::Invoke { callee, args, line } => {
            m.insert("op".into(), Value::String("invoke".into()));
            m.insert("callee".into(), Value::String(callee.clone()));
            let arg_vals: Vec<Value> = args
                .iter()
                .map(|(s, e)| {
                    let mut a = Map::new();
                    a.insert("sym".into(), syms.ref_sym(*s));
                    a.insert("effect".into(), Value::String(effect_name(*e).to_owned()));
                    Value::Object(a)
                })
                .collect();
            m.insert("args".into(), Value::Array(arg_vals));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::BorrowStart {
            owner,
            binding,
            is_mut,
            line,
        } => {
            m.insert("op".into(), Value::String("borrow_start".into()));
            m.insert("owner".into(), syms.ref_sym(Some(*owner)));
            m.insert("binding".into(), syms.ref_sym(Some(*binding)));
            m.insert("mut".into(), Value::Bool(*is_mut));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::BorrowEnd {
            owner,
            binding,
            is_mut,
            line,
        } => {
            m.insert("op".into(), Value::String("borrow_end".into()));
            m.insert("owner".into(), syms.ref_sym(Some(*owner)));
            m.insert("binding".into(), syms.ref_sym(Some(*binding)));
            m.insert("mut".into(), Value::Bool(*is_mut));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::AliasJoin { handle, src, line } => {
            m.insert("op".into(), Value::String("alias_join".into()));
            m.insert("handle".into(), syms.ref_sym(Some(*handle)));
            m.insert("src".into(), syms.ref_sym(Some(*src)));
            m.insert("line".into(), Value::from(*line));
        }
        Instr::Return { sym, line } => {
            m.insert("op".into(), Value::String("return".into()));
            m.insert("sym".into(), syms.ref_sym(*sym));
            m.insert("line".into(), Value::from(*line));
        }
    }
    Value::Object(m)
}

/// One function's CFG as a canonical JSON value (`cfg_json.cfg_json`).
fn cfg_value(cfg: &Cfg) -> Value {
    let mut syms = SymTable::new(cfg);
    // Params first — this pins their table indices ahead of any operand.
    let params: Vec<Value> = cfg.params.iter().map(|p| syms.ref_sym(Some(*p))).collect();
    // Blocks in id order (id == arena position); this is Python's
    // `sorted(cfg.blocks, key=id)`, which is already sorted here.
    let blocks: Vec<Value> = cfg
        .blocks
        .iter()
        .map(|b| {
            let mut bm = Map::new();
            bm.insert("id".into(), Value::from(b.id.0));
            bm.insert("label".into(), Value::String(b.label.clone()));
            let succ: Vec<Value> = b.succ.iter().map(|s| Value::from(s.0)).collect();
            bm.insert("succ".into(), Value::Array(succ));
            let instrs: Vec<Value> = b.instrs.iter().map(|i| instr_value(i, &mut syms)).collect();
            bm.insert("instrs".into(), Value::Array(instrs));
            Value::Object(bm)
        })
        .collect();

    let mut m = Map::new();
    m.insert("name".into(), Value::String(cfg.fn_name.clone()));
    m.insert("entry".into(), Value::from(cfg.entry.0));
    m.insert("has_return_type".into(), Value::Bool(cfg.has_return_type));
    m.insert("params".into(), Value::Array(params));
    m.insert("symbols".into(), Value::Array(syms.rows));
    m.insert("blocks".into(), Value::Array(blocks));
    Value::Object(m)
}

/// The whole module's CFGs as one versioned document
/// (`cfg_json.module_cfg_json`).
#[must_use]
pub fn module_cfg_value(cfgs: &[Cfg]) -> Value {
    let mut m = Map::new();
    m.insert("ownlang_cfg_version".into(), Value::from(CFG_JSON_VERSION));
    let functions: Vec<Value> = cfgs.iter().map(cfg_value).collect();
    m.insert("functions".into(), Value::Array(functions));
    Value::Object(m)
}

/// The canonical textual form of the seam — what `cfg --format json` prints and
/// what the oracle byte-compares (`cfg_json.canonical_json`).
#[must_use]
pub fn canonical_json(cfgs: &[Cfg]) -> String {
    python_dumps(&module_cfg_value(cfgs))
}

/// Serialize a JSON value exactly like `CPython`'s
/// `json.dumps(obj, indent=2, sort_keys=True)` (default `ensure_ascii=True`).
#[must_use]
pub fn python_dumps(value: &Value) -> String {
    let mut out = String::new();
    encode(value, 0, &mut out);
    out
}

fn indent(level: usize) -> String {
    " ".repeat(level.saturating_mul(2))
}

fn encode(v: &Value, level: usize, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => encode_string(s, out),
        Value::Array(arr) => {
            if arr.is_empty() {
                out.push_str("[]");
                return;
            }
            let child = indent(level.saturating_add(1));
            out.push_str("[\n");
            for (i, item) in arr.iter().enumerate() {
                if i != 0 {
                    out.push_str(",\n");
                }
                out.push_str(&child);
                encode(item, level.saturating_add(1), out);
            }
            out.push('\n');
            out.push_str(&indent(level));
            out.push(']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            let child = indent(level.saturating_add(1));
            // sort_keys=True — independent of the map's own iteration order.
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push_str("{\n");
            for (i, k) in keys.iter().enumerate() {
                if i != 0 {
                    out.push_str(",\n");
                }
                out.push_str(&child);
                encode_string(k, out);
                out.push_str(": ");
                if let Some(val) = map.get(*k) {
                    encode(val, level.saturating_add(1), out);
                }
            }
            out.push('\n');
            out.push_str(&indent(level));
            out.push('}');
        }
    }
}

/// String escaping matching `CPython`'s `ensure_ascii=True` encoder: `"` `\` and
/// the short control escapes, `\u00XX` for other controls, and `\uXXXX`
/// (UTF-16 code units, surrogate pairs for astral scalars) for everything
/// outside the printable-ASCII range `0x20..=0x7e`.
fn encode_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c if (c as u32) <= 0x7e => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::python_dumps;
    use serde_json::json;

    // Every expectation below is the literal output of CPython's
    // `json.dumps(obj, indent=2, sort_keys=True)` (default `ensure_ascii=True`);
    // this is the property the CFG-JSON seam's byte-identity rests on.

    #[test]
    fn dumps_indent_sorts_keys_and_handles_empties() {
        assert_eq!(python_dumps(&json!({})), "{}");
        assert_eq!(python_dumps(&json!([])), "[]");
        let v = json!({"b": 1, "a": [2, 3], "c": {"z": true, "y": null}});
        assert_eq!(
            python_dumps(&v),
            "{\n  \"a\": [\n    2,\n    3\n  ],\n  \"b\": 1,\n  \"c\": {\n    \"y\": null,\n    \"z\": true\n  }\n}"
        );
    }

    #[test]
    fn ensure_ascii_matches_cpython() {
        assert_eq!(python_dumps(&json!("м")), "\"\\u043c\""); // Cyrillic U+043C
        assert_eq!(python_dumps(&json!("\u{7f}")), "\"\\u007f\""); // DEL is escaped
        assert_eq!(python_dumps(&json!("~")), "\"~\""); // 0x7e stays raw
        assert_eq!(python_dumps(&json!("\u{1}")), "\"\\u0001\"");
        assert_eq!(python_dumps(&json!("a\tb\nc")), "\"a\\tb\\nc\"");
        assert_eq!(python_dumps(&json!("\"\\")), "\"\\\"\\\\\"");
        // astral scalar -> UTF-16 surrogate pair, like CPython
        assert_eq!(python_dumps(&json!("😀")), "\"\\ud83d\\ude00\"");
    }
}
