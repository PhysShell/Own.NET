//! Buffer storage policies — an exact port of `ownlang/buffers.py`.
//!
//! A buffer is an owned resource that additionally carries a resolved storage
//! **policy** ([`BufferInfo`]). [`resolve`] turns a `Buffer.<mode>(...)` intent
//! plus the module's `policy` blocks into that validated metadata; the
//! resolution is total — it always yields a usable `BufferInfo` so lowering has
//! something to attach, with any policy/bound problems surfaced as diagnostics.
//!
//! Diagnostics here carry only their **code + line** (not the human message):
//! the CFG-JSON oracle seam this crate is gated on compares the resolved
//! `BufferInfo` (which *is* in the seam), not the diagnostic text (a
//! verdict-layer contract gated later, at the `own-diagnostics`/SARIF step). The
//! `BufferInfo` field computation is ported value-for-value.

use std::collections::HashMap;

use own_syntax::ast::{BufferIntent, Expr, PolicyValue};

use crate::Diag;

/// Storage mode a `Buffer.<mode>(...)` intent selects.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BufferMode {
    Stack,
    Scratch,
    Pooled,
    Native,
    Inline,
}

impl BufferMode {
    /// The wire spelling — `BufferMode.<M>.value` in Python (also the CFG-JSON
    /// `mode` field).
    #[must_use]
    pub const fn value(self) -> &'static str {
        match self {
            Self::Stack => "stack",
            Self::Scratch => "scratch",
            Self::Pooled => "pooled",
            Self::Native => "native",
            Self::Inline => "inline",
        }
    }

    /// Parse a mode spelling. `None` for an unknown mode — the caller
    /// (`lower_buffer`) rejects those before ever calling [`resolve`], mirroring
    /// Python's `if rhs.mode not in MODE_NAMES` guard around `BufferMode(...)`.
    #[must_use]
    pub fn from_value(s: &str) -> Option<Self> {
        match s {
            "stack" => Some(Self::Stack),
            "scratch" => Some(Self::Scratch),
            "pooled" => Some(Self::Pooled),
            "native" => Some(Self::Native),
            "inline" => Some(Self::Inline),
            _ => None,
        }
    }

    /// Modes whose backing storage may live on the stack (so the buffer must not
    /// escape the function). `scratch` is included — at runtime it *might* be the
    /// stack arm. Mirrors the Python `STACK_BACKED` membership.
    #[must_use]
    pub const fn stack_backed(self) -> bool {
        matches!(self, Self::Stack | Self::Scratch | Self::Inline)
    }
}

/// Recognized names in a `Buffer.<mode>(..., name = value)` intent.
pub(crate) const VALID_OPTIONS: [&str; 10] = [
    "policy",
    "inline",
    "inline_bytes",
    "max",
    "max_bytes",
    "fallback",
    "clear",
    "trace",
    "counters",
    "sensitive",
];

/// Recognized keys in a `policy { ... }` block.
pub(crate) const VALID_POLICY_KEYS: [&str; 7] = [
    "inline_bytes",
    "max_bytes",
    "fallback",
    "clear_on_release",
    "trace",
    "counters",
    "sensitive",
];

const DEFAULT_INLINE_BYTES: i64 = 1024;
const MAX_STACK_BYTES: i64 = 4096;

const TRACE_ON: [&str; 3] = ["debug", "on", "true"];
const TRACE_OFF: [&str; 3] = ["off", "none", "false"];

/// Resolved, validated metadata for one buffer intent.
///
/// Attached to the owning [`Symbol`](crate::Symbol) and the
/// [`AcquireBuffer`](crate::Instr) instruction, and projected into the CFG-JSON
/// seam by [`crate::json`].
// The six bool flags are the resolved storage contract, 1:1 with the Python
// `BufferInfo` dataclass and part of the frozen CFG-JSON seam — not a bag of
// parameters to bundle into a sub-struct.
#[allow(clippy::struct_excessive_bools)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BufferInfo {
    pub mode: BufferMode,
    /// Element type — always `"byte"` today (matches Python).
    pub elem: String,
    pub size_const: Option<i64>,
    pub size_var: Option<String>,
    pub inline_bytes: i64,
    pub fallback_pool: bool,
    pub fallback_forbidden: bool,
    pub clear_on_release: bool,
    pub sensitive: bool,
    pub trace: bool,
    pub counters: bool,
    pub policy_name: Option<String>,
    pub line: u32,
}

impl BufferInfo {
    /// Whether this buffer's storage may live on the stack (the Python
    /// `BufferInfo.stack_backed` property) — used by the ownership analysis to
    /// reject an escaping stack-backed buffer (OWN015/OWN016).
    #[must_use]
    pub const fn stack_backed(&self) -> bool {
        self.mode.stack_backed()
    }
}

/// A named, reusable `policy { ... }` block of defaults (`buffers.Policy`).
///
/// Settings preserve insertion order (irrelevant to resolution, which is
/// key-addressed) and record duplicate keys separately.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Policy {
    pub name: String,
    pub settings: Vec<(String, PolicyValue)>,
    pub line: u32,
    pub dups: Vec<String>,
}

impl Policy {
    fn get(&self, key: &str) -> Option<&PolicyValue> {
        self.settings.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }
}

/// A module's `policy` blocks, keyed by name.
pub type Policies = HashMap<String, Policy>;

fn as_int(expr: &Expr) -> Option<i64> {
    match expr {
        Expr::IntLit(i) => Some(to_i64(i.value)),
        _ => None,
    }
}

fn as_ident(expr: &Expr) -> Option<&str> {
    match expr {
        Expr::VarRef(v) => Some(v.name.as_str()),
        _ => None,
    }
}

/// `OwnLang` integer literals cap at `u64` in `own-syntax` (a recorded
/// divergence from Python's arbitrary precision); the buffer arithmetic here is
/// signed (it uses a `-1` sentinel and `< 0` guards), so values are clamped into
/// `i64` for the internal computation. The corpus stays far below the limit.
fn to_i64(v: u64) -> i64 {
    i64::try_from(v).unwrap_or(i64::MAX)
}

/// The display token a fallback value compares as (`_fallback_token`, but only
/// the *value*, not a message). Only `IntLit`/`VarRef` can name a real fallback
/// (`pool`/`forbidden`); any other expression yields a token that matches
/// neither, which is exactly Python's "invalid fallback" outcome.
fn fallback_token_expr(expr: &Expr) -> String {
    match expr {
        Expr::IntLit(i) => i.value.to_string(),
        Expr::VarRef(v) => v.name.clone(),
        _ => String::new(),
    }
}

fn fallback_token_policy(val: &PolicyValue) -> String {
    match val {
        PolicyValue::Int(n) => n.to_string(),
        PolicyValue::Bool(true) => "true".to_owned(),
        PolicyValue::Bool(false) => "false".to_owned(),
        PolicyValue::Word(w) => w.clone(),
    }
}

// The `map_or_else` combinators clippy would prefer here don't compose with the
// side-effecting `diags` (two closures can't both hold `&mut diags`); the if-let
// / match precedence mirrors `buffers.py` directly. Same for `first_int` below.
#[allow(clippy::option_if_let_else, clippy::single_match_else)]
fn opt_int(
    intent: &BufferIntent,
    base: Option<&Policy>,
    name: &str,
    default: i64,
    diags: &mut Vec<Diag>,
    line: u32,
) -> i64 {
    if let Some(e) = intent.options.get(name) {
        return match as_int(e) {
            Some(v) => v,
            None => {
                diags.push(Diag::new("OWN030", line));
                default
            }
        };
    }
    match base.and_then(|p| p.get(name)) {
        Some(PolicyValue::Int(n)) => to_i64(*n),
        Some(_) => {
            diags.push(Diag::new("OWN030", line));
            default
        }
        None => default,
    }
}

#[allow(clippy::option_if_let_else, clippy::single_match_else)] // see opt_int
fn first_int(
    intent: &BufferIntent,
    base: Option<&Policy>,
    sources: &[(bool, &str)],
    default: i64,
    diags: &mut Vec<Diag>,
    line: u32,
) -> i64 {
    for &(from_opts, key) in sources {
        if from_opts {
            if let Some(e) = intent.options.get(key) {
                return match as_int(e) {
                    Some(v) => v,
                    None => {
                        diags.push(Diag::new("OWN030", line));
                        default
                    }
                };
            }
        } else if let Some(bv) = base.and_then(|p| p.get(key)) {
            return match bv {
                PolicyValue::Int(n) => to_i64(*n),
                _ => {
                    diags.push(Diag::new("OWN030", line));
                    default
                }
            };
        }
    }
    default
}

fn bool_flag(
    opt_expr: Option<&Expr>,
    policy_val: Option<&PolicyValue>,
    default: bool,
    diags: &mut Vec<Diag>,
    line: u32,
) -> bool {
    match opt_expr {
        Some(e) => match as_ident(e) {
            Some("true") => true,
            Some("false") => false,
            _ => {
                diags.push(Diag::new("OWN030", line));
                default
            }
        },
        None => match policy_val {
            None => default,
            Some(PolicyValue::Bool(b)) => *b,
            Some(_) => {
                diags.push(Diag::new("OWN030", line));
                default
            }
        },
    }
}

fn trace_flag(
    opt_expr: Option<&Expr>,
    policy_val: Option<&PolicyValue>,
    default: bool,
    diags: &mut Vec<Diag>,
    line: u32,
) -> bool {
    match opt_expr {
        Some(e) => match as_ident(e) {
            Some(name) if TRACE_ON.contains(&name) => true,
            Some(name) if TRACE_OFF.contains(&name) => false,
            _ => {
                diags.push(Diag::new("OWN030", line));
                default
            }
        },
        None => match policy_val {
            None => default,
            Some(PolicyValue::Bool(b)) => *b,
            Some(PolicyValue::Word(w)) if TRACE_ON.contains(&w.as_str()) => true,
            Some(PolicyValue::Word(w)) if TRACE_OFF.contains(&w.as_str()) => false,
            Some(_) => {
                diags.push(Diag::new("OWN030", line));
                default
            }
        },
    }
}

/// Reject unknown keys / duplicates in `policy` blocks (`validate_policies`).
///
/// Not on the CFG-JSON path (it is a module-level check the `check` pipeline
/// runs), ported here with the rest of the buffer surface for later steps.
#[must_use]
pub fn validate_policies(policies: &Policies) -> Vec<Diag> {
    let mut diags = Vec::new();
    // Python iterates `policies.values()` in dict insertion order, i.e. source
    // declaration order, and emits diagnostics in that order. A `HashMap` loses
    // it, so recover declaration order by sorting on the declaration line (which
    // *is* that order) — NOT by name, which would reorder the diagnostic stream
    // for policies not already alphabetized.
    let mut pols: Vec<&Policy> = policies.values().collect();
    pols.sort_by_key(|p| p.line);
    for pol in pols {
        for (key, _) in &pol.settings {
            if !VALID_POLICY_KEYS.contains(&key.as_str()) {
                diags.push(Diag::new("OWN030", pol.line));
            }
        }
        for _ in &pol.dups {
            diags.push(Diag::new("OWN030", pol.line));
        }
    }
    diags
}

/// Resolve one buffer intent against the module's policies (`buffers.resolve`).
///
/// Always returns a usable [`BufferInfo`] plus any policy/bound diagnostics (by
/// code + line). `mode` has already been validated by the caller
/// (`lower_buffer`), exactly as Python constructs `BufferMode(...)` only past its
/// `MODE_NAMES` guard.
// too_many_lines: a line-for-line port of buffers.resolve.
// option_if_let_else: the map_or_else form doesn't compose with the shared
// `&mut diags` (two closures), and the fallback chain mirrors buffers.py.
#[allow(clippy::too_many_lines, clippy::option_if_let_else)]
pub(crate) fn resolve(
    intent: &BufferIntent,
    mode: BufferMode,
    policies: &Policies,
) -> (BufferInfo, Vec<Diag>) {
    let mut diags: Vec<Diag> = Vec::new();
    let line = intent.line;

    // Reject unknown option names before any default is applied.
    for (key, _) in intent.options.iter() {
        if !VALID_OPTIONS.contains(&key) {
            diags.push(Diag::new("OWN030", line));
        }
    }
    // A repeated option is a conflicting storage promise.
    for _ in &intent.dups {
        diags.push(Diag::new("OWN030", line));
    }

    // Start from a referenced policy's defaults, then let inline options win.
    let mut base: Option<&Policy> = None;
    let mut pol_name: Option<String> = None;
    if let Some(pol_expr) = intent.options.get("policy") {
        match as_ident(pol_expr) {
            None => diags.push(Diag::new("OWN030", line)),
            Some(name) => {
                pol_name = Some(name.to_owned());
                match policies.get(name) {
                    Some(p) => base = Some(p),
                    None => diags.push(Diag::new("OWN030", line)),
                }
            }
        }
    }

    let size_const = intent.size.as_deref().and_then(as_int);
    let size_var = intent.size.as_deref().and_then(as_ident).map(str::to_owned);

    let mut inline_bytes = DEFAULT_INLINE_BYTES;
    let mut fallback_pool = false;
    let mut fallback_forbidden = false;

    match mode {
        BufferMode::Stack | BufferMode::Inline => {
            fallback_forbidden = true;
            if let Some(sc) = size_const {
                inline_bytes = sc;
            } else if mode == BufferMode::Inline {
                // inline is a fixed compile-time stack buffer: the size MUST be a
                // literal. A dynamic size (even with `max`) is `stack`.
                diags.push(Diag::new("OWN021", line));
                inline_bytes = MAX_STACK_BYTES;
            } else {
                // dynamic size: needs an explicit integer `max` bound.
                inline_bytes = MAX_STACK_BYTES;
                let max_opt = intent.options.get("max");
                if matches!(max_opt, Some(e) if as_int(e).is_none()) {
                    diags.push(Diag::new("OWN030", line));
                } else {
                    let mx_val = match max_opt {
                        Some(e) => as_int(e).unwrap_or(-1),
                        None => opt_int(intent, base, "max_bytes", -1, &mut diags, line),
                    };
                    if mx_val < 0 {
                        diags.push(Diag::new("OWN021", line));
                    } else {
                        inline_bytes = mx_val;
                    }
                }
            }
        }
        BufferMode::Scratch => {
            inline_bytes = first_int(
                intent,
                base,
                &[
                    (true, "inline"),
                    (true, "inline_bytes"),
                    (false, "inline_bytes"),
                ],
                DEFAULT_INLINE_BYTES,
                &mut diags,
                line,
            );
            let fb_opt = intent.options.get("fallback");
            let fb_base = base.and_then(|p| p.get("fallback"));
            let fb_present = fb_opt.is_some() || fb_base.is_some();
            let fb = if let Some(e) = fb_opt {
                fallback_token_expr(e)
            } else if let Some(pv) = fb_base {
                fallback_token_policy(pv)
            } else {
                "pool".to_owned()
            };
            let fb_valid = fb == "pool" || fb == "forbidden";
            if fb_present && !fb_valid {
                diags.push(Diag::new("OWN030", line));
            }
            if fb == "pool" {
                fallback_pool = true;
            } else {
                fallback_forbidden = true;
                if fb_valid && size_const.map_or(true, |sc| sc > inline_bytes) {
                    diags.push(Diag::new("OWN023", line));
                }
            }
        }
        BufferMode::Pooled => fallback_pool = true,
        BufferMode::Native => {}
    }

    // Shared bound check on stack-backed modes.
    if mode.stack_backed() && inline_bytes > MAX_STACK_BYTES {
        diags.push(Diag::new("OWN019", line));
    }

    // Flags from options / policy.
    let clear = bool_flag(
        intent.options.get("clear"),
        base.and_then(|p| p.get("clear_on_release")),
        false,
        &mut diags,
        line,
    );
    let sensitive = bool_flag(
        intent.options.get("sensitive"),
        base.and_then(|p| p.get("sensitive")),
        false,
        &mut diags,
        line,
    );
    let trace = trace_flag(
        intent.options.get("trace"),
        base.and_then(|p| p.get("trace")),
        true,
        &mut diags,
        line,
    );
    let counters = bool_flag(
        intent.options.get("counters"),
        base.and_then(|p| p.get("counters")),
        true,
        &mut diags,
        line,
    );

    if sensitive && !clear {
        diags.push(Diag::new("OWN024", line));
    }

    let info = BufferInfo {
        mode,
        elem: "byte".to_owned(),
        size_const,
        size_var,
        inline_bytes,
        fallback_pool,
        fallback_forbidden,
        clear_on_release: clear,
        sensitive,
        trace,
        counters,
        policy_name: pol_name,
        line,
    };
    (info, diags)
}
