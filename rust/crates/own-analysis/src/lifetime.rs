//! Lifetime-region analysis — an exact port of `ownlang/lifetimes.py`.
//!
//! This is an **AST-level** analysis (not CFG/solver based): it reasons about
//! *region escape* — the WPF "zombie `ViewModel`" theorem. `lifetime`
//! declarations define a strict partial order; a `subscribe self to source`
//! where the source outlives the captured object promotes the object to the
//! longer region and it leaks (OWN014). Structural validation emits OWN030 (undefined
//! lifetime), OWN031 (redeclared) and OWN036 (cyclic ordering).
//!
//! Parity contract (#214): `(line, code)`. The AST is read through `own_cfg::ast`
//! (the CFG seam), so this crate keeps no production `own-syntax` edge.

use std::collections::{BTreeMap, BTreeSet};

use own_cfg::ast::{FnDecl, LifetimeDecl, Module, Stmt, Subscribe};
use own_diagnostics::{title, Diagnostic};

/// Emit a `(code, line)` diagnostic (message is the title; text parity is a
/// later step). `code` is a compile-time constant, so `new` cannot fail.
fn push(diags: &mut Vec<Diagnostic>, code: &'static str, line: u32) {
    let msg = title(code).unwrap_or(code);
    match Diagnostic::new(code, msg, line) {
        Ok(d) => diags.push(d),
        Err(_) => debug_assert!(false, "lifetime analysis emitted an unknown code {code}"),
    }
}

/// Collect every `subscribe` in a body, descending into branches/loops/borrow
/// blocks — the port of `_iter_subscribes`.
fn collect_subscribes<'a>(stmts: &'a [Stmt], out: &mut Vec<&'a Subscribe>) {
    for st in stmts {
        match st {
            Stmt::Subscribe(s) => out.push(s),
            Stmt::If(i) => {
                collect_subscribes(&i.then_body, out);
                collect_subscribes(&i.else_body, out);
            }
            Stmt::While(w) => collect_subscribes(&w.body, out),
            Stmt::BorrowBlock(b) => collect_subscribes(&b.body, out),
            _ => {}
        }
    }
}

/// Map each region to the set of regions strictly longer-lived than it (the
/// transitive closure of `<`) — the port of `_strictly_longer`.
fn strictly_longer(decls: &[LifetimeDecl]) -> BTreeMap<String, BTreeSet<String>> {
    let mut direct: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for d in decls {
        direct.entry(d.name.clone()).or_default();
        if let Some(longer) = &d.longer {
            direct.entry(longer.clone()).or_default();
            if let Some(set) = direct.get_mut(&d.name) {
                set.insert(longer.clone());
            }
        }
    }

    let mut longer: BTreeMap<String, BTreeSet<String>> = direct
        .keys()
        .map(|n| (n.clone(), BTreeSet::new()))
        .collect();
    for start in direct.keys() {
        let mut stack: Vec<String> = direct
            .get(start)
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default();
        while let Some(cur) = stack.pop() {
            let already = longer.get(start).is_some_and(|s| s.contains(&cur));
            if already {
                continue;
            }
            if let Some(set) = longer.get_mut(start) {
                set.insert(cur.clone());
            }
            if let Some(next) = direct.get(&cur) {
                stack.extend(next.iter().cloned());
            }
        }
    }
    longer
}

/// Region diagnostics for a module: structural validation of the lifetime order
/// plus the per-function escape check. Port of `check_lifetimes`.
///
/// Does NOT early-return on empty `lifetimes` — a function/parameter may still
/// carry an annotation referencing an undeclared region (OWN030).
#[must_use]
pub fn check_lifetimes(module: &Module) -> Vec<Diagnostic> {
    let mut diags: Vec<Diagnostic> = Vec::new();

    let mut names: BTreeSet<String> = BTreeSet::new();
    for d in &module.lifetimes {
        if names.contains(&d.name) {
            push(&mut diags, "OWN031", d.line);
        }
        names.insert(d.name.clone());
    }
    for d in &module.lifetimes {
        if let Some(longer) = &d.longer {
            if !names.contains(longer) {
                push(&mut diags, "OWN030", d.line);
            }
        }
    }

    let longer = strictly_longer(&module.lifetimes);
    for d in &module.lifetimes {
        // a cycle shows up as a region being strictly longer than itself.
        if longer.get(&d.name).is_some_and(|s| s.contains(&d.name)) {
            push(&mut diags, "OWN036", d.line);
        }
    }

    for f in &module.functions {
        check_fn(f, &names, &longer, &mut diags);
    }
    diags
}

fn check_fn(
    f: &FnDecl,
    names: &BTreeSet<String>,
    longer: &BTreeMap<String, BTreeSet<String>>,
    diags: &mut Vec<Diagnostic>,
) {
    // validate annotations on this function, even with no subscribes.
    if let Some(lt) = &f.lifetime {
        if !names.contains(lt) {
            push(diags, "OWN030", f.line);
        }
    }
    let mut param_lt: BTreeMap<String, String> = BTreeMap::new();
    for p in &f.params {
        if let Some(lt) = &p.lifetime {
            if names.contains(lt) {
                param_lt.insert(p.name.clone(), lt.clone());
            } else {
                push(diags, "OWN030", p.line);
            }
        }
    }

    let self_lt = f.lifetime.as_ref().filter(|lt| names.contains(lt.as_str()));
    let mut subs: Vec<&Subscribe> = Vec::new();
    collect_subscribes(&f.body, &mut subs);
    for sub in subs {
        // skip when we cannot compare (no self lifetime / untagged source):
        // conservative, avoids false positives.
        let (Some(self_lt), Some(src_lt)) = (self_lt, param_lt.get(&sub.source)) else {
            continue;
        };
        if longer.get(self_lt).is_some_and(|s| s.contains(src_lt)) {
            push(diags, "OWN014", sub.line);
        }
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::check_lifetimes;

    fn codes(src: &str) -> Vec<(u32, String)> {
        let module = own_syntax::parse(src).expect("parses");
        let mut v: Vec<(u32, String)> = check_lifetimes(&module)
            .into_iter()
            .map(|d| (d.line, d.code))
            .collect();
        v.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
        v
    }

    #[test]
    fn region_escape_is_own014() {
        // bus (App) strictly outlives self (ViewModel) → the strong subscribe
        // promotes the object and leaks.
        let src = "module M\n\
            lifetime App;\n\
            lifetime Window < App;\n\
            lifetime ViewModel < Window;\n\
            fn VM(bus: EventBus lifetime App) lifetime ViewModel {\n\
                subscribe self to bus;\n\
            }\n";
        assert_eq!(codes(src), vec![(6, "OWN014".to_owned())]);
    }

    #[test]
    fn equal_or_shorter_source_lifetime_is_clean() {
        // source at the SAME region as self → no promotion, no finding.
        let src = "module M\n\
            lifetime App;\n\
            lifetime ViewModel < App;\n\
            fn VM(peer: Other lifetime ViewModel) lifetime ViewModel {\n\
                subscribe self to peer;\n\
            }\n";
        assert!(codes(src).is_empty(), "equal-lifetime capture is fine");
    }

    #[test]
    fn cyclic_ordering_is_own036() {
        // A < B and B < A → both end up strictly longer than themselves.
        let src = "module M\nlifetime A < B;\nlifetime B < A;\n";
        assert_eq!(
            codes(src),
            vec![(2, "OWN036".to_owned()), (3, "OWN036".to_owned())]
        );
    }

    #[test]
    fn undefined_and_redeclared_lifetimes() {
        // `< Ghost` references an undeclared region (OWN030); `Dup` twice (OWN031).
        let src = "module M\n\
            lifetime Dup;\n\
            lifetime Dup;\n\
            lifetime Short < Ghost;\n";
        assert_eq!(
            codes(src),
            vec![(3, "OWN031".to_owned()), (4, "OWN030".to_owned())]
        );
    }

    #[test]
    fn subscribe_descends_into_branches() {
        // the escaping subscribe is nested inside an `if` — still found.
        let src = "module M\n\
            lifetime App;\n\
            lifetime ViewModel < App;\n\
            fn VM(bus: EventBus lifetime App) lifetime ViewModel {\n\
                if (x) { subscribe self to bus; }\n\
            }\n";
        assert_eq!(codes(src), vec![(5, "OWN014".to_owned())]);
    }
}
