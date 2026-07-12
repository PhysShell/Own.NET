//! The full `.own` **check surface** — the port of `ownlang.__main__.check_module`.
//!
//! Composes every `.own` diagnostic pass in Python's exact order, then sorts by
//! `(line, code)` (a stable sort, so ties keep emission order):
//!
//! 1. buffer-policy validation (`own_cfg::validate_policies`);
//! 2. lifetime/region ([`crate::lifetime::check_lifetimes`]);
//! 3. per-function resolver diagnostics (`own_cfg::build_module`, "d1") then the
//!    ownership analysis ([`crate::ownership::analyze`], "d2").
//!
//! `own_cfg::build_module` returns all functions' `d1` concatenated, and this
//! runs `analyze` per function, so the pre-sort order is `[d1…][d2…]` rather than
//! Python's per-function `[fn.d1, fn.d2]` interleave. That difference is
//! invisible after the stable sort: a source line belongs to exactly one
//! function, so a same-`(line, code)` tie can only occur within one function,
//! where `d1` precedes `d2` under **both** orders. The module-level passes (1, 2)
//! come first under both.

use own_cfg::ast::Module;
use own_cfg::{build_module, collect_policies, validate_policies, Diag};
use own_diagnostics::{title, Diagnostic};

use crate::{lifetime, ownership};

/// Convert an `own-cfg` resolver/policy diagnostic (code + line) into an
/// `own-diagnostics` value; the message is the title (text parity is a later
/// step). `code` is a compile-time constant, so construction cannot fail.
fn push_cfg_diag(out: &mut Vec<Diagnostic>, d: &Diag) {
    let msg = title(d.code).unwrap_or(d.code);
    match Diagnostic::new(d.code, msg, d.line) {
        Ok(x) => out.push(x),
        Err(_) => debug_assert!(false, "own-cfg emitted an unknown code {}", d.code),
    }
}

/// Run the whole `.own` check surface over a parsed module.
///
/// Returns the diagnostics sorted by `(line, code)` — byte-for-byte the set
/// `python -m ownlang check` produces (compared on `(line, code)` at this step).
#[must_use]
pub fn check_module(module: &Module) -> Vec<Diagnostic> {
    let mut diags: Vec<Diagnostic> = Vec::new();

    // 1. buffer-policy validation (OWN018/019/021/023/024/…).
    for d in &validate_policies(&collect_policies(module)) {
        push_cfg_diag(&mut diags, d);
    }
    // 2. lifetime/region (OWN014/OWN030/OWN031/OWN036).
    diags.extend(lifetime::check_lifetimes(module));
    // 3. per-function resolver diagnostics (d1) then ownership (d2).
    let (cfgs, d1) = build_module(module);
    for d in &d1 {
        push_cfg_diag(&mut diags, d);
    }
    for cfg in &cfgs {
        diags.extend(ownership::analyze(cfg));
    }

    diags.sort_by(|a, b| a.line.cmp(&b.line).then_with(|| a.code.cmp(&b.code)));
    diags
}
